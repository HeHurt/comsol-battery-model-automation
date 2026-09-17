#!/usr/bin/env python3
"""
comsol_batch_runner.py — COMSOL Autonomous Mode 主执行管线

完成 STEP C/D/E 的端到端执行: 编译 → 求解 → 验证 → 反馈
对外提供 run_autonomous_cycle() 顶层接口。

依赖: pyyaml, pandas, numpy (生成报告时另需 python-docx, matplotlib)

用法:
    python comsol_batch_runner.py \\
        --java GeneratedModel.java \\
        --criteria acceptance.yaml \\
        --paths paths.json \\
        --workdir D:/models/auto_sim_001 \\
        [--iteration 1] \\
        [--max-wall-clock 7200]

paths.json 示例:
    {
        "comsolcompile": "<COMSOL_ROOT>/bin/win64/comsolcompile.exe",
        "comsolbatch":   "<COMSOL_ROOT>/bin/win64/comsolbatch.exe"
    }
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import re
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERROR: 需要安装 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ==============================================================
# 错误模式库 (与 references/autonomous_execution.md 第2-3节对齐)
# ==============================================================
COMPILE_ERROR_PATTERNS = [
    {
        "pattern": r"cannot find symbol\s*\n.*?symbol:\s*variable\s+(\w+)",
        "type": "undefined_param",
        "description": "引用了未定义的参数",
        "fix_hint": "在 model.param().set 段添加该参数"
    },
    {
        "pattern": r"cannot find symbol\s*\n.*?symbol:\s*method\s+(\w+)",
        "type": "unknown_method",
        "description": "API 方法名错或版本不匹配",
        "fix_hint": "查 Javadoc 或 comsol_64_api_notes.md"
    },
    {
        "pattern": r"';' expected",
        "type": "missing_semicolon",
        "description": "漏分号",
        "fix_hint": "在指示行末加分号"
    },
    {
        "pattern": r"'\(' expected",
        "type": "missing_paren",
        "description": "漏括号",
        "fix_hint": "补全括号"
    },
    {
        "pattern": r"incompatible types: String cannot be converted to int",
        "type": "string_int_mismatch",
        "description": "setIndex 第3参 (index) 应为 int 不是字符串",
        "fix_hint": "把 \"0\" 改为 0"
    },
    {
        "pattern": r"Property \"(\w+)\" is not defined for feature \"(\w+)\"",
        "type": "unknown_property",
        "description": "属性键不存在或 6.4 改名",
        "fix_hint": "查 comsol_64_api_notes.md (Ee→Eeq 等)"
    },
    {
        "pattern": r"Selection has no entities",
        "type": "empty_selection",
        "description": "选区配置错,边界/域索引不存在",
        "fix_hint": "检查 geom 实际产生 domain/boundary 数"
    },
]

SOLVE_ERROR_PATTERNS = [
    {
        "pattern": r"Newton method did not converge",
        "type": "newton_diverge",
        "description": "求解器发散",
        "fix_hints": [
            "减小初始时间步: tlist 改 range(0,0.01,T_end)",
            "提高 reltol: 1e-5 → 1e-4",
            "改用 Backward Euler"
        ]
    },
    {
        "pattern": r"Failed to find consistent initial values",
        "type": "init_inconsistent",
        "description": "初值矛盾",
        "fix_hints": ["检查 init1 设置,phis-phil ≈ OCV(SOC_init)"]
    },
    {
        "pattern": r"Out of memory",
        "type": "oom",
        "description": "内存不足",
        "fix_hints": [
            "减少网格 (mesh size factor 1.0→1.5)",
            "减少时间输出点",
            "关闭无用 Probe"
        ]
    },
    {
        "pattern": r"License\s+(error|timeout)|Could not check out license",
        "type": "license",
        "description": "授权问题",
        "fix_hints": ["立即停止,人工检查 license,可能 GUI 占用了名额"],
        "blocking": True   # 不允许重试
    },
    {
        "pattern": r"Stop condition met before simulation ended",
        "type": "stop_condition",
        "description": "Stop condition 触发(CC到截止)",
        "fix_hints": ["这通常不是错误,检查终止电压是否合理"],
        "non_fatal": True  # 不算失败
    },
    {
        "pattern": r"Singular matrix",
        "type": "singular_matrix",
        "description": "网格质量差或参数不物理",
        "fix_hints": [
            "检查活性物质体积分数 > 0",
            "检查孔隙率合理",
            "增加网格密度"
        ]
    },
    {
        "pattern": r"NaN or Inf encountered",
        "type": "nan_inf",
        "description": "中间数值爆炸",
        "fix_hints": ["检查 OCV 函数定义域 [0,1] 覆盖完整"]
    },
]


# ==============================================================
# 工具函数
# ==============================================================
def log(msg, level="INFO"):
    """简单日志输出"""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {level}: {msg}", flush=True)


def run_cmd(cmd, cwd=None, timeout=None, env=None):
    """运行命令,返回 (returncode, stdout, stderr)"""
    log(f"RUN: {cmd[0]} ... ({len(cmd)} args)", "DEBUG")
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, timeout=timeout, env=env,
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TimeoutExpired after {timeout}s"
    except FileNotFoundError as e:
        return -2, "", f"Executable not found: {e}"


def parse_errors(stderr, patterns):
    """匹配错误模式库,返回 [{type, description, fix_hint, matched}]"""
    found = []
    for p in patterns:
        m = re.search(p["pattern"], stderr, re.MULTILINE | re.DOTALL)
        if m:
            entry = dict(p)
            entry["matched"] = m.group(0)[:200]
            try:
                entry["groups"] = m.groups()
            except Exception:
                entry["groups"] = ()
            found.append(entry)
    return found


def append_history(history_path, entry):
    """append 一条记录到 debug_history.json"""
    history = []
    if Path(history_path).exists():
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(entry)
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ==============================================================
# STEP C: 编译
# ==============================================================
def compile_java(java_file, comsolcompile_path, workdir):
    """编译 .java → .class. 返回 dict {success, returncode, stdout, stderr, parsed_errors}"""
    log(f"Compiling {java_file} ...")
    rc, stdout, stderr = run_cmd(
        [comsolcompile_path, java_file],
        cwd=workdir,
        timeout=120
    )
    combined = (stdout or "") + "\n" + (stderr or "")
    errors = parse_errors(combined, COMPILE_ERROR_PATTERNS)
    success = (rc == 0)
    log(f"Compile {'OK' if success else 'FAILED'} (rc={rc}, errors={len(errors)})")
    return {
        "success": success,
        "returncode": rc,
        "stdout": stdout,
        "stderr": stderr,
        "parsed_errors": errors,
    }


# ==============================================================
# STEP D: 求解
# ==============================================================
def solve_with_comsolbatch(input_file, output_mph, comsolbatch_path, workdir,
                          batchlog="run.log", alivetime=600, stall_seconds=300):
    """
    跑 comsolbatch. 支持:
    - 进度监控 (stall_seconds 内日志无变化判定卡死)
    - 错误模式匹配
    返回 dict {success, returncode, log, parsed_errors, blocking}
    """
    log(f"Solving with comsolbatch ...")
    cmd = [
        comsolbatch_path,
        "-inputfile", input_file,
        "-outputfile", output_mph,
        "-batchlog", batchlog,
        "-recover",
        "-alivetime", str(alivetime),
    ]
    log_path = os.path.join(workdir, batchlog)
    # 清空旧日志
    if os.path.exists(log_path):
        try: os.remove(log_path)
        except: pass

    # 启动进程
    try:
        proc = subprocess.Popen(
            cmd, cwd=workdir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace'
        )
    except FileNotFoundError as e:
        return {"success": False, "returncode": -2, "log": "",
                "parsed_errors": [], "blocking": False, "error": str(e)}

    # 进度监控循环
    start = time.time()
    last_size = 0
    last_progress = time.time()
    stalled = False

    while proc.poll() is None:
        time.sleep(15)
        if os.path.exists(log_path):
            cur_size = os.path.getsize(log_path)
            if cur_size > last_size:
                last_size = cur_size
                last_progress = time.time()
                elapsed = time.time() - start
                log(f"  ... still running, log {cur_size} B, elapsed {elapsed:.0f}s")
        if time.time() - last_progress > stall_seconds:
            log(f"Solver stalled (no log progress for {stall_seconds}s), killing", "ERROR")
            proc.kill()
            stalled = True
            break

    rc = proc.returncode if proc.returncode is not None else -3

    # 读日志
    log_content = ""
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            log_content = f.read()

    errors = parse_errors(log_content, SOLVE_ERROR_PATTERNS)

    blocking = any(e.get("blocking", False) for e in errors)
    # Stop condition is OK
    non_fatal = all(e.get("non_fatal", False) for e in errors) if errors else False

    # success: rc==0 AND (no errors OR all non_fatal) AND not stalled
    success = (rc == 0 and not stalled and
               (not errors or non_fatal) and
               os.path.exists(os.path.join(workdir, output_mph)))

    if stalled:
        errors.append({"type": "stalled", "description": f"Solver stalled {stall_seconds}s"})

    log(f"Solve {'OK' if success else 'FAILED'} (rc={rc}, errors={len(errors)})")
    return {
        "success": success,
        "returncode": rc,
        "log": log_content[-5000:],  # 保留末尾5KB
        "parsed_errors": errors,
        "blocking": blocking,
    }


# ==============================================================
# STEP E: 验证
# ==============================================================
def check_bound(actual, bound_expr):
    """
    bound_expr 如 ">= 2.5" / "<= 60" / "in [270, 290]" / "≈ 280 ± 5"
    返回 True/False
    """
    if actual is None:
        return False
    s = bound_expr.strip()

    # in [a, b]
    m = re.match(r'in\s*\[?\s*([\d.eE+\-]+)\s*,\s*([\d.eE+\-]+)\s*\]?', s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return lo <= actual <= hi

    # ≈ X ± Y
    m = re.match(r'[≈~]?\s*([\d.eE+\-]+)\s*[±+\-]\s*([\d.eE+\-]+)', s)
    if m and ('±' in s or '+/-' in s):
        center, tol = float(m.group(1)), float(m.group(2))
        return abs(actual - center) <= tol

    # comparison operators
    for op, fn in [(">=", lambda a, b: a >= b),
                   ("<=", lambda a, b: a <= b),
                   ("!=", lambda a, b: a != b),
                   ("==", lambda a, b: abs(a - b) < 1e-9),
                   (">",  lambda a, b: a > b),
                   ("<",  lambda a, b: a < b)]:
        if s.startswith(op):
            try:
                rhs = float(s[len(op):].strip())
                return fn(actual, rhs)
            except ValueError:
                return False
    return False


# 安全表达式求值: 仅允许数学运算和 metrics 字典中的变量。
# 用于 physical_sanity 的布尔规则 (如 "E_cell >= V_min and E_cell <= V_max")。
# 注意: 这里只能求值 metrics.csv 里已导出的标量。COMSOL 表达式 (如 min(liion.E_cell))
# 必须由 .java 在 COMSOL 中求值后写入 metrics.csv,Python 侧不重新计算物理量。
_SAFE_NAMES = {
    'abs': abs, 'min': min, 'max': max, 'round': round,
    'and': None, 'or': None, 'not': None,  # 占位,实际由 Python 语法处理
}

def safe_eval_bool(expr, variables):
    """
    安全求值一个布尔表达式。variables 是 {name: value} 字典 (来自 metrics)。
    返回 (result: bool|None, reason: str)。
    无法求值时返回 (None, 原因),而不是默默 False —— 避免假装通过。
    """
    import ast as _ast

    # 找出表达式中用到的所有标识符
    try:
        tree = _ast.parse(expr, mode='eval')
    except SyntaxError as e:
        return None, f"syntax error: {e}"

    used_names = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name):
            used_names.add(node.id)
        # 禁止函数调用之外的属性访问、下标等危险操作
        if isinstance(node, (_ast.Attribute, _ast.Subscript, _ast.Lambda,
                             _ast.Import, _ast.ImportFrom)):
            return None, "expression contains disallowed construct"

    # 检查未提供的变量
    allowed = set(variables.keys()) | set(_SAFE_NAMES.keys()) | {'True', 'False', 'None'}
    missing = used_names - allowed
    if missing:
        return None, f"missing variables in metrics: {sorted(missing)}"

    # 构造受限命名空间
    safe_globals = {'__builtins__': {}}
    safe_globals.update({k: v for k, v in _SAFE_NAMES.items() if v is not None})
    safe_globals.update(variables)

    try:
        result = eval(compile(tree, '<sanity>', 'eval'), safe_globals, {})
        return bool(result), "ok"
    except Exception as e:
        return None, f"eval error: {e}"


def compute_reference_metric(sim_csv, exp_csv, metric, align_method="interp"):
    """
    计算仿真与实验对标的指标。
    sim_csv, exp_csv 都是两列 CSV (time, value)。
    """
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        log("pandas/numpy 未安装,跳过实验对标", "WARN")
        return None

    sim = pd.read_csv(sim_csv, encoding='utf-8', engine='python')
    try:
        exp = pd.read_csv(exp_csv, encoding='utf-8', engine='python')
    except UnicodeDecodeError:
        exp = pd.read_csv(exp_csv, encoding='gbk', engine='python')

    # 假设第一列是 time,第二列是 value
    sim_t, sim_v = sim.iloc[:, 0].values, sim.iloc[:, 1].values
    exp_t, exp_v = exp.iloc[:, 0].values, exp.iloc[:, 1].values

    if align_method == "interp":
        # 把仿真插值到实验时间点
        sim_v_at_exp = np.interp(exp_t, sim_t, sim_v)
        residual = sim_v_at_exp - exp_v
    else:
        # 简单截断后对齐 (备用)
        n = min(len(sim_v), len(exp_v))
        residual = sim_v[:n] - exp_v[:n]

    if metric == "RMSE":
        return float(np.sqrt(np.mean(residual ** 2)))
    elif metric == "MAE":
        return float(np.mean(np.abs(residual)))
    elif metric == "MAPE":
        return float(np.mean(np.abs(residual / exp_v)) * 100)
    elif metric == "max_dev":
        return float(np.max(np.abs(residual)))
    elif metric == "R2":
        ss_res = np.sum(residual ** 2)
        ss_tot = np.sum((exp_v - np.mean(exp_v)) ** 2)
        return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    else:
        return None


def check_acceptance(metrics, criteria, workdir):
    """逐项检查,返回 {all_passed, items_passed, items_failed, warnings, skipped}"""
    items_passed = []
    items_failed = []
    warnings = []
    skipped = []   # 无法本地求值的项 (诚实记录,不计入 pass)

    # L2: physical sanity (内置) —— 现在真正实现
    sanity = criteria.get("physical_sanity", {})
    if sanity.get("enabled", True):
        for rule in sanity.get("rules", []):
            expr = rule.get("expr", "")
            result, reason = safe_eval_bool(expr, metrics)
            item = {
                "type": "physical_sanity",
                "id": rule.get("id", expr[:30]),
                "expr": expr,
                "result": result,
                "reason": reason
            }
            if result is True:
                items_passed.append(item)
            elif result is False:
                # 物理合理性失败 = 硬失败 (数值很可能爆了)
                items_failed.append(item)
            else:
                # 无法求值 (metrics 里缺变量) —— 记入 skipped,不假装通过
                skipped.append(item)
                log(f"  physical_sanity '{item['id']}' SKIPPED: {reason}", "WARN")

    # L3: numeric criteria
    for crit in criteria.get("numeric_criteria", []):
        cid = crit["id"]
        # 契约: metrics.csv 的列名应与 numeric_criteria 的 id 一致。
        # expr 字段是给 .java 生成器和人看的说明,Python 侧不重新求值 COMSOL 表达式。
        actual = metrics.get(cid)
        matched_key = cid if actual is not None else None
        if actual is None:
            # 容错: 尝试子串匹配 (如 id=capacity 匹配列 capacity_Ah),但记录警告
            for k, v in metrics.items():
                if cid == k or cid in k or k in cid:
                    actual = v
                    matched_key = k
                    break
        item = {
            "type": "numeric",
            "id": cid,
            "description": crit.get("description", ""),
            "actual": actual,
            "matched_metric_key": matched_key,
            "bound": crit["bound"],
            "unit": crit.get("unit", ""),
        }
        if actual is None:
            # 指标根本没在 metrics.csv 里找到 —— 明确报错,不默默判 False
            item["error"] = f"metric '{cid}' not found in metrics.csv (有的列: {list(metrics.keys())})"
            item["passed"] = False
            items_failed.append(item)
            log(f"  numeric '{cid}' NOT FOUND in metrics.csv", "ERROR")
            continue
        passed = check_bound(actual, crit["bound"])
        item["passed"] = passed
        if not passed:
            if crit.get("severity", "hard") == "hard":
                items_failed.append(item)
            else:
                warnings.append(item)
        else:
            items_passed.append(item)

    # L4: experimental reference
    expref = criteria.get("experimental_reference", {})
    if expref.get("enabled", False):
        for ref in expref.get("references", []):
            sim_csv = os.path.join(workdir, ref["sim_export"])
            exp_csv = ref["file"]
            if not os.path.isabs(exp_csv):
                exp_csv = os.path.join(workdir, exp_csv)
            score = None
            err = None
            if not os.path.exists(sim_csv):
                err = f"sim export not found: {sim_csv}"
            elif not os.path.exists(exp_csv):
                err = f"experiment file not found: {exp_csv}"
            else:
                score = compute_reference_metric(
                    sim_csv, exp_csv, ref["metric"],
                    ref.get("align_method", "interp")
                )
                if score is None:
                    err = "metric computation failed (pandas/numpy missing or CSV malformed)"
            if score is None:
                passed = False
            elif ref["metric"] == "R2":
                passed = score >= ref["threshold"]   # R2 越大越好
            else:
                passed = score <= ref["threshold"]   # RMSE/MAE/MAPE/max_dev 越小越好
            item = {
                "type": "experimental",
                "id": ref["id"],
                "metric": ref["metric"],
                "score": score,
                "threshold": ref["threshold"],
                "unit": ref.get("unit", ""),
                "passed": passed
            }
            if err:
                item["error"] = err
            if score is None:
                # 无法计算 —— 记 skipped,不假装通过也不武断判失败
                skipped.append(item)
                log(f"  experimental '{ref['id']}' SKIPPED: {err}", "WARN")
                continue
            if not passed:
                if ref.get("severity", "hard") == "hard":
                    items_failed.append(item)
                else:
                    warnings.append(item)
            else:
                items_passed.append(item)

    # L4b: 可选加权聚合 (over experimental references) —— 越小越好
    weighted_cfg = expref.get("weighted_score", {})
    if weighted_cfg.get("enabled", False):
        weights = weighted_cfg.get("weights", {})
        total_weight = 0.0
        weighted_sum = 0.0
        for ref in expref.get("references", []):
            ref_id = ref.get("id")
            if ref_id not in weights:
                continue
            sim_csv = os.path.join(workdir, ref.get("sim_export", ""))
            exp_csv = ref.get("file", "")
            if not os.path.isabs(exp_csv):
                exp_csv = os.path.join(workdir, exp_csv)
            if not (os.path.exists(sim_csv) and os.path.exists(exp_csv)):
                continue
            score = compute_reference_metric(
                sim_csv, exp_csv, ref.get("metric"),
                ref.get("align_method", "interp"))
            try:
                weight = float(weights.get(ref_id))
            except (TypeError, ValueError):
                weight = None
            if score is None or weight is None or weight <= 0:
                continue
            weighted_sum += score * weight
            total_weight += weight
        weighted_item = {
            "type": "experimental_weighted", "id": "weighted_score",
            "score": None, "threshold": weighted_cfg.get("overall_threshold"),
            "unit": "", "passed": False,
        }
        if total_weight > 0:
            agg = weighted_sum / total_weight
            weighted_item["score"] = agg
            thr = weighted_item["threshold"]
            passed = (thr is None) or (agg <= thr)
            weighted_item["passed"] = passed
            (items_passed if passed else items_failed).append(weighted_item)
        else:
            weighted_item["detail"] = "insufficient_data_for_weighted_score"
            warnings.append(weighted_item)

    return {
        # all_passed 要求: 无失败项 AND 无 skipped 硬项
        # skipped 不算通过,但单独列出让 agent/用户知道哪些没验证
        "all_passed": len(items_failed) == 0 and len(skipped) == 0,
        "items_passed": items_passed,
        "items_failed": items_failed,
        "warnings": warnings,
        "skipped": skipped
    }


# ==============================================================
# 加载 metrics (假设 .java 求解后导出了 metrics.csv)
# ==============================================================
def load_metrics(workdir, csv_name="metrics.csv"):
    """读 metrics.csv,返回 dict"""
    metrics = {}
    path = os.path.join(workdir, csv_name)
    if not os.path.exists(path):
        log(f"metrics.csv not found at {path}", "WARN")
        return metrics
    try:
        import pandas as pd
        df = pd.read_csv(path, encoding='utf-8', engine='python')
    except (UnicodeDecodeError, Exception):
        try:
            import pandas as pd
            df = pd.read_csv(path, encoding='gbk', engine='python')
        except Exception as e:
            log(f"Failed to read {path}: {e}", "ERROR")
            return metrics
    # 假设 metrics.csv 是单行多列,列名对应指标
    if len(df) >= 1:
        row = df.iloc[0].to_dict()
        for k, v in row.items():
            try:
                metrics[str(k).strip()] = float(v)
            except (ValueError, TypeError):
                metrics[str(k).strip()] = v
    return metrics


# ==============================================================
# 单轮执行 (循环由上层 AI Agent 驱动)
# ==============================================================
# 重要架构说明:
#   本脚本执行 *一轮* C→D→E (编译→求解→验收)。它不会自动修改 .java 源代码,
#   因为修正编译错误/调整物理参数需要 LLM 的智能判断。
#
#   真正的 debug 循环在 AI Agent 侧:
#     1. Agent 生成/修改 .java
#     2. Agent 调用本脚本跑一轮 (传 --iteration N)
#     3. 脚本把本轮结果 append 到 debug_history.json
#     4. Agent 读 cycle_result.json,若未通过则改 .java,iteration+1,回到步骤2
#     5. Agent 自己控制总轮数 (max_iter 是 Agent 的预算,不是本脚本的)
#
#   因此本脚本不再有 for 循环。--iteration 让 Agent 标记当前轮次,
#   --reset-history 仅在第一轮清空历史,之后累积。
# ==============================================================
def run_one_cycle(java_file, criteria_file, paths_file, workdir,
                  iteration=1, reset_history=None, max_wall_clock=7200):
    """
    执行一轮 编译→求解→验收。
    iteration: 当前是第几轮 (由 Agent 传入,用于历史记录)
    reset_history: 是否清空历史。None=自动(仅 iteration==1 时清空)
    返回 dict,Agent 据此决定下一步。
    """
    workdir = os.path.abspath(workdir)
    os.makedirs(workdir, exist_ok=True)

    history_path = os.path.join(workdir, "debug_history.json")
    # 只在第一轮(或显式要求)清空历史,否则累积
    if reset_history is None:
        reset_history = (iteration == 1)
    if reset_history and os.path.exists(history_path):
        os.remove(history_path)
        log(f"History reset (iteration={iteration})")

    # 加载配置
    with open(paths_file, 'r', encoding='utf-8') as f:
        paths = json.load(f)
    with open(criteria_file, 'r', encoding='utf-8') as f:
        criteria = yaml.safe_load(f)

    java_file_abs = os.path.abspath(java_file)
    java_basename = os.path.basename(java_file_abs)
    class_basename = java_basename.replace('.java', '.class')
    output_mph = "result.mph"

    # 把 .java 复制到 workdir(如不在)
    java_in_workdir = os.path.join(workdir, java_basename)
    if java_file_abs != java_in_workdir:
        shutil.copy2(java_file_abs, java_in_workdir)

    start_time = time.time()
    log(f"=== Cycle iteration {iteration}: {java_basename} ===")
    log(f"Workdir: {workdir}")

    # 备份本轮 .java (供追溯)
    backup = os.path.join(workdir, f"{java_basename.replace('.java','')}_iter_{iteration}.java")
    shutil.copy2(java_in_workdir, backup)

    iter_entry = {"iteration": iteration, "timestamp": time.time()}

    # ---- 单轮执行,不循环 ----
    if True:
        # STEP C: 编译
        cr = compile_java(java_basename, paths["comsolcompile"], workdir)
        iter_entry["compile"] = {
            "success": cr["success"],
            "returncode": cr["returncode"],
            "errors": cr["parsed_errors"][:3],  # 只记前3个
            "stderr_tail": (cr["stderr"] or "")[-2000:]
        }
        if not cr["success"]:
            append_history(history_path, iter_entry)
            log(f"Compile failed at iter {iteration}", "ERROR")
            log("AI 需要根据错误修改 .java 然后重试 (本脚本不自动修改源代码,需上层 Agent 介入)", "INFO")
            # 自动 debug 由上层 Agent (Claude/Copilot) 负责修改 .java
            # 这里直接返回,让 Agent 看错误后续操作
            return {"success": False, "reason": "compile_failed",
                    "iteration": iteration, "details": cr}

        # STEP D: 求解
        sr = solve_with_comsolbatch(
            class_basename, output_mph,
            paths["comsolbatch"], workdir,
            alivetime=criteria.get("meta", {}).get("alivetime", 600),
            stall_seconds=criteria.get("meta", {}).get("stall_seconds", 300)
        )
        iter_entry["solve"] = {
            "success": sr["success"],
            "returncode": sr["returncode"],
            "errors": sr["parsed_errors"][:3],
            "log_tail": sr["log"][-2000:],
            "blocking": sr["blocking"]
        }
        if sr["blocking"]:
            append_history(history_path, iter_entry)
            log("Blocking error (License?), stopping immediately", "ERROR")
            return {"success": False, "reason": "blocking_error",
                    "iteration": iteration, "details": sr}
        if not sr["success"]:
            append_history(history_path, iter_entry)
            log(f"Solve failed at iter {iteration}", "ERROR")
            return {"success": False, "reason": "solve_failed",
                    "iteration": iteration, "details": sr}

        # STEP E: 验收检查
        metrics = load_metrics(workdir, "metrics.csv")
        iter_entry["metrics"] = metrics
        log(f"Loaded metrics: {list(metrics.keys())}")

        accept_result = check_acceptance(metrics, criteria, workdir)
        iter_entry["acceptance"] = accept_result

        log(f"Acceptance: PASS={len(accept_result['items_passed'])}, "
            f"FAIL={len(accept_result['items_failed'])}, "
            f"WARN={len(accept_result['warnings'])}, "
            f"SKIPPED={len(accept_result.get('skipped', []))}")

        append_history(history_path, iter_entry)

        if accept_result["all_passed"]:
            log(f"✅ All acceptance criteria passed at iteration {iteration}!", "SUCCESS")
            return {
                "success": True,
                "iteration": iteration,
                "elapsed_s": time.time() - start_time,
                "metrics": metrics,
                "acceptance": accept_result,
                "workdir": workdir,
                "next_action": "done"
            }
        else:
            n_fail = len(accept_result["items_failed"])
            n_skip = len(accept_result.get("skipped", []))
            log(f"Iteration {iteration}: {n_fail} failed, {n_skip} skipped", "WARN")
            for failed in accept_result["items_failed"]:
                log(f"  FAIL: {failed['id']} = {failed.get('actual', failed.get('score'))} "
                    f"vs {failed.get('bound', failed.get('threshold'))} {failed.get('unit','')}"
                    + (f"  [{failed['error']}]" if 'error' in failed else ""))
            for sk in accept_result.get("skipped", []):
                log(f"  SKIP: {sk['id']} — {sk.get('reason', sk.get('error', 'unknown'))}")
            # Agent 据此修改 .java (调参或修指标导出),iteration+1,重新调用本脚本
            return {
                "success": False,
                "reason": "acceptance_failed",
                "iteration": iteration,
                "metrics": metrics,
                "acceptance": accept_result,
                "workdir": workdir,
                "next_action": "agent_adjust_and_rerun"
            }


# 向后兼容别名 (旧文档/调用可能用 run_autonomous_cycle)
def run_autonomous_cycle(java_file, criteria_file, paths_file, workdir,
                         max_iter=8, max_wall_clock=7200):
    """[Deprecated] 兼容旧接口,实际只跑一轮。循环请由 Agent 驱动 run_one_cycle。"""
    log("NOTE: run_autonomous_cycle 只执行一轮。循环由 Agent 通过反复调用 run_one_cycle 驱动。", "WARN")
    return run_one_cycle(java_file, criteria_file, paths_file, workdir,
                         iteration=1, max_wall_clock=max_wall_clock)


# ==============================================================
# CLI
# ==============================================================
def main():
    p = argparse.ArgumentParser(
        description="COMSOL Autonomous Mode Runner —— 执行一轮 编译→求解→验收 (循环由 Agent 驱动)")
    p.add_argument('--java', required=True, help='.java 源文件路径')
    p.add_argument('--criteria', required=True, help='acceptance.yaml')
    p.add_argument('--paths', required=True, help='paths.json (COMSOL 路径)')
    p.add_argument('--workdir', required=True, help='工作目录')
    p.add_argument('--iteration', type=int, default=1,
                   help='当前轮次 (由 Agent 传入,用于历史累积。第1轮会重置历史)')
    p.add_argument('--reset-history', action='store_true',
                   help='强制清空 debug_history.json (默认仅 iteration==1 时清空)')
    p.add_argument('--max-wall-clock', type=int, default=7200,
                   help='单轮求解的墙钟上限秒数')
    p.add_argument('--output', default='cycle_result.json', help='结果输出 JSON')
    args = p.parse_args()

    result = run_one_cycle(
        args.java, args.criteria, args.paths, args.workdir,
        iteration=args.iteration,
        reset_history=(True if args.reset_history else None),
        max_wall_clock=args.max_wall_clock
    )

    output_path = os.path.join(args.workdir, args.output)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    log(f"Result saved to {output_path}")
    log(f"next_action = {result.get('next_action', 'n/a')}")
    sys.exit(0 if result.get("success") else 1)


if __name__ == '__main__':
    main()
