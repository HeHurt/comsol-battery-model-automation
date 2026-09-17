#!/usr/bin/env python3
"""
parse_comsol_errors.py — COMSOL 编译/求解错误日志解析器

独立工具:接受 stderr 或 run.log 文件,解析出结构化的错误信息和修复建议。
可被 AI Agent 调用,或开发者手动使用。

用法:
    python parse_comsol_errors.py --type compile --input compile_stderr.txt
    python parse_comsol_errors.py --type solve   --input run.log
    cat run.log | python parse_comsol_errors.py --type solve --stdin
"""

import argparse
import json
import re
import sys
from typing import Optional


# ==============================================================
# 错误模式库 (与 comsol_batch_runner.py 对齐)
# ==============================================================

COMPILE_PATTERNS = [
    {
        "id": "undefined_param",
        "pattern": r"cannot find symbol\s*\n.*?symbol:\s*variable\s+(\w+)",
        "category": "compile",
        "severity": "fixable",
        "description": "引用了未定义的参数",
        "fix_template": "在 model.param().set(...) 段添加: model.param().set(\"{0}\", \"<value>[<unit>]\", \"<description>\");",
        "reference": "references/liion_lfp_reference.md 'LFP/Gr 典型参数表' 提供默认值"
    },
    {
        "id": "unknown_method",
        "pattern": r"cannot find symbol\s*\n.*?symbol:\s*method\s+(\w+)\(([^)]*)\)",
        "category": "compile",
        "severity": "fixable",
        "description": "API 方法名错或参数不匹配",
        "fix_template": "查 Javadoc 中 {0} 的正确签名。常见 6.x 命名: createFeature/feature/set/setIndex",
        "reference": "references/comsol_official_docs.md 第3节 Javadoc 检索"
    },
    {
        "id": "unknown_class",
        "pattern": r"cannot find symbol\s*\n.*?symbol:\s*class\s+(\w+)",
        "category": "compile",
        "severity": "fixable",
        "description": "引用了不存在的类(拼写错误)",
        "fix_template": "正确类名通常是 LithiumIonBattery, HeatTransferInSolids, ElectrochemicalHeating 等",
        "reference": "references/comsol_64_api_notes.md"
    },
    {
        "id": "missing_semicolon",
        "pattern": r"';' expected",
        "category": "compile",
        "severity": "fixable",
        "description": "Java 语法错: 漏分号",
        "fix_template": "在错误行末加分号",
        "reference": None
    },
    {
        "id": "missing_paren",
        "pattern": r"'\(' expected|'\)' expected",
        "category": "compile",
        "severity": "fixable",
        "description": "Java 语法错: 括号不匹配",
        "fix_template": "检查括号配对",
        "reference": None
    },
    {
        "id": "string_int_mismatch",
        "pattern": r"incompatible types: String cannot be converted to int",
        "category": "compile",
        "severity": "fixable",
        "description": "setIndex 第3参 (index) 应为 int 不是字符串",
        "fix_template": "把 setIndex(prop, val, \"0\") 改为 setIndex(prop, val, 0)",
        "reference": None
    },
    {
        "id": "unknown_property",
        "pattern": r"Property \"(\w+)\" is not defined for feature \"(\w+)\"",
        "category": "compile",
        "severity": "fixable",
        "description": "属性键不存在或 6.4 改名",
        "fix_template": "在 feature \"{1}\" 上属性 \"{0}\" 无效。常见改名: Ee→Eeq, k_iso→k",
        "reference": "references/comsol_64_api_notes.md"
    },
    {
        "id": "empty_selection",
        "pattern": r"Selection has no entities|Selection .* is empty",
        "category": "compile",
        "severity": "fixable",
        "description": "选区配置错: 边界/域索引不存在",
        "fix_template": "检查 geom 实际产生的 domain/boundary 数,修正 selection().set(new int[]{...}) 的索引",
        "reference": None
    },
]

SOLVE_PATTERNS = [
    {
        "id": "newton_diverge",
        "pattern": r"(?:Newton|Nonlinear) (?:method |solver )?(?:did not converge|failed to converge|divergence)",
        "category": "solve",
        "severity": "fixable",
        "description": "求解器发散,常见于初始时间步或 LFP 平台段",
        "fix_template": [
            "1. 减小初始时间步: tlist 改 range(0, 0.01, T_end)",
            "2. 提高 reltol: 1e-5 → 1e-4",
            "3. 改用 Backward Euler (改 std1.time.set('tstepsbdf', 'manual'))",
            "4. 对 LFP 添加: estrat='exclude' 避免 OCV 平台干扰误差估计"
        ],
        "reference": "references/autonomous_execution.md 第3.3节 LFP 收敛技巧"
    },
    {
        "id": "init_inconsistent",
        "pattern": r"Failed to find consistent initial values|Inconsistent initial values",
        "category": "solve",
        "severity": "fixable",
        "description": "初值矛盾",
        "fix_template": [
            "对 P2D 模型: phis - phil 应≈OCV(SOC_init)",
            "检查 init1 设置的 cl/phis/phil 是否一致",
            "可尝试先用 stationary study 求初值再做瞬态"
        ],
        "reference": "references/liion_lfp_reference.md Init1 节点"
    },
    {
        "id": "oom",
        "pattern": r"Out of memory|java\.lang\.OutOfMemoryError",
        "category": "solve",
        "severity": "fixable",
        "description": "内存不足",
        "fix_template": [
            "1. 减少网格密度: mesh size factor 1.0 → 1.5 或 'coarser'",
            "2. 减少时间输出点: tlist 步长加大",
            "3. 关闭无用 Probe 和 Cut Lines",
            "4. 启动时用 -j 选项设置更大堆: comsolbatch -j 'jvmargs=-Xmx16g'"
        ],
        "reference": None
    },
    {
        "id": "license",
        "pattern": r"License (?:error|timeout|denied)|Could not check out license|FLEXlm error",
        "category": "solve",
        "severity": "blocking",  # 不允许自动重试
        "description": "授权问题",
        "fix_template": [
            "STOP - 不要自动重试",
            "1. 检查 COMSOL Desktop GUI 是否已打开占用了 license",
            "2. 检查 license 服务器是否在线",
            "3. 检查本地 license 配置 (LM_LICENSE_FILE 环境变量)"
        ],
        "reference": None
    },
    {
        "id": "stop_condition",
        "pattern": r"Stop condition met before simulation ended|stopcond.*?true",
        "category": "solve",
        "severity": "non_fatal",  # 通常是 OK 的
        "description": "Stop condition 触发(CC到截止)",
        "fix_template": [
            "对 CC/CP 工况这通常是预期行为",
            "检查终止时电压是否在 [V_min, V_max] 内合理"
        ],
        "reference": "references/liion_lfp_reference.md 'Stop Condition'"
    },
    {
        "id": "singular_matrix",
        "pattern": r"Singular matrix|Matrix is singular",
        "category": "solve",
        "severity": "fixable",
        "description": "雅可比矩阵奇异,网格质量差或参数不物理",
        "fix_template": [
            "1. 检查活性物质体积分数 epss > 0",
            "2. 检查孔隙率 epsl 合理 (0.2-0.6 范围)",
            "3. 增加网格密度,尤其在固相离散方向 (rp)",
            "4. 检查反应速率常数 k 不为 0"
        ],
        "reference": None
    },
    {
        "id": "nan_inf",
        "pattern": r"NaN(?: or | and )?Inf encountered|undefined value detected",
        "category": "solve",
        "severity": "fixable",
        "description": "中间数值爆炸",
        "fix_template": [
            "1. 检查 OCV 函数定义域 [0,1] 完整,无 holes",
            "2. 检查浓度边界是否可能 < 0",
            "3. 检查反应过电位是否数值过大 (>>1V 通常是参数错)",
            "4. 启用 Probe 监视关键变量定位爆炸位置"
        ],
        "reference": None
    },
    {
        "id": "max_iter",
        "pattern": r"Maximum number of (?:segregated|nonlinear|Newton) iterations exceeded",
        "category": "solve",
        "severity": "fixable",
        "description": "求解器内部不收敛",
        "fix_template": [
            "1. Segregated → 改 Fully Coupled",
            "2. 增加 maxiter: std1.feature('time').set('maxiter', 50)",
            "3. 检查 reltol/atol 是否过严"
        ],
        "reference": None
    },
    {
        "id": "stalled",
        "pattern": r"^$",  # 不通过 stderr 匹配,由 batch_runner 主动判定
        "category": "solve",
        "severity": "fixable",
        "description": "求解器卡死 (无日志进度)",
        "fix_template": [
            "1. 网格可能太密,减小 mesh size factor",
            "2. 可能 license 服务器响应慢,检查网络",
            "3. 可能某个非线性问题死循环,减小时间步"
        ],
        "reference": None
    },
]


def parse(text: str, category: str) -> list:
    """匹配错误模式,返回结构化错误列表"""
    patterns = COMPILE_PATTERNS if category == "compile" else SOLVE_PATTERNS
    found = []
    for p in patterns:
        try:
            for m in re.finditer(p["pattern"], text, re.MULTILINE | re.DOTALL):
                entry = {
                    "id": p["id"],
                    "category": p["category"],
                    "severity": p["severity"],
                    "description": p["description"],
                    "matched_excerpt": m.group(0)[:300],
                    "match_position": m.start(),
                    "fix_template": p["fix_template"],
                    "reference": p.get("reference"),
                }
                # 填充 fix_template 中的占位符
                if isinstance(entry["fix_template"], str) and m.groups():
                    try:
                        entry["fix_template"] = entry["fix_template"].format(*m.groups())
                    except (IndexError, KeyError):
                        pass
                if m.groups():
                    entry["captures"] = list(m.groups())
                found.append(entry)
        except re.error as e:
            print(f"WARN: regex error in pattern {p['id']}: {e}", file=sys.stderr)
    return found


def summarize(errors: list) -> dict:
    """给出诊断摘要"""
    if not errors:
        return {"diagnosis": "no_errors_found", "fixable_count": 0, "blocking": False}
    blocking = [e for e in errors if e["severity"] == "blocking"]
    non_fatal = [e for e in errors if e["severity"] == "non_fatal"]
    fixable = [e for e in errors if e["severity"] == "fixable"]
    return {
        "diagnosis": "errors_found",
        "total": len(errors),
        "blocking_count": len(blocking),
        "non_fatal_count": len(non_fatal),
        "fixable_count": len(fixable),
        "blocking": len(blocking) > 0,
        "first_action": fixable[0]["fix_template"] if fixable else None
    }


def main():
    ap = argparse.ArgumentParser(description="COMSOL 错误日志解析器")
    ap.add_argument('--type', choices=['compile', 'solve'], required=True,
                    help='错误类型(决定用哪个模式库)')
    ap.add_argument('--input', help='输入文件 (默认 stdin)')
    ap.add_argument('--stdin', action='store_true', help='从 stdin 读')
    ap.add_argument('--output', help='输出 JSON 文件 (默认 stdout)')
    args = ap.parse_args()

    if args.stdin or not args.input:
        text = sys.stdin.read()
    else:
        with open(args.input, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

    errors = parse(text, args.type)
    summary = summarize(errors)

    result = {
        "summary": summary,
        "errors": errors,
        "input_chars": len(text),
    }

    output_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_str)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(output_str)

    # 退出码: 0=无错误, 1=有可修复错误, 2=blocking 错误
    if summary["blocking"]:
        sys.exit(2)
    elif errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
