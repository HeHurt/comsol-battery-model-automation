#!/usr/bin/env python3
"""
generate_report.py — 自动生成 5-8 页 COMSOL 仿真报告 (.docx)

输入: .java / metrics.csv / acceptance.yaml / debug_history.json
输出: simulation_report.docx (含表格 + 嵌入图)

依赖: python-docx, pyyaml, pandas, matplotlib

用法:
    python generate_report.py \\
        --java GeneratedModel.java \\
        --metrics metrics.csv \\
        --criteria acceptance.yaml \\
        --debug-log debug_history.json \\
        --workdir D:/models/auto_sim_001 \\
        --out simulation_report.docx

可选输入:
    --voltage-csv voltage_vs_time.csv    用于画电压时变曲线
    --temp-csv temperature_vs_time.csv   用于画温度时变曲线
    --exp-csv experiments/dchg_1C.csv    实验对比数据
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: 需要 pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
except ImportError:
    print("ERROR: 需要 python-docx: pip install python-docx", file=sys.stderr)
    sys.exit(1)

# matplotlib 用于画图,失败则跳过图
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pandas as pd
    PLOTTING_AVAILABLE = True
    # 尝试配置中文字体 (有则用,无则图表标签回退英文,避免方框)
    _CJK_FONTS = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'Noto Sans CJK SC',
                  'WenQuanYi Micro Hei', 'Arial Unicode MS']
    import matplotlib.font_manager as _fm
    _available = {f.name for f in _fm.fontManager.ttflist}
    _CJK_OK = False
    for _f in _CJK_FONTS:
        if _f in _available:
            plt.rcParams['font.sans-serif'] = [_f]
            plt.rcParams['axes.unicode_minus'] = False
            _CJK_OK = True
            break
except ImportError:
    PLOTTING_AVAILABLE = False
    _CJK_OK = False
    print("WARN: matplotlib/pandas not available, plots will be skipped", file=sys.stderr)


# ==============================================================
# 颜色配置 (与 simulation_report_template.md 一致)
# ==============================================================
COLOR_MAIN = RGBColor(0x1E, 0x27, 0x61)    # 深蓝
COLOR_RED = RGBColor(0xC8, 0x10, 0x2E)     # 红
COLOR_GREEN = RGBColor(0x05, 0x96, 0x69)   # 绿
COLOR_AMBER = RGBColor(0xD9, 0x77, 0x06)   # 橙
COLOR_GRAY = RGBColor(0x6B, 0x72, 0x80)    # 灰
COLOR_BLACK = RGBColor(0x1A, 0x1A, 0x1A)


# ==============================================================
# 辅助: 解析 .java 提取参数
# ==============================================================
def extract_params_from_java(java_path):
    """从 .java 提取 model.param().set(...) 的所有参数"""
    params = []
    if not os.path.exists(java_path):
        return params
    with open(java_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    # 匹配 model.param().set("name", "value[unit]", "description")
    pattern = re.compile(
        r'model\.param\(\)\.set\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*(?:,\s*"([^"]*)")?\s*\)'
    )
    for m in pattern.finditer(content):
        name = m.group(1)
        value = m.group(2)
        desc = m.group(3) or ""
        # 从 value 提取单位
        unit_m = re.search(r'\[([^\]]+)\]', value)
        unit = unit_m.group(1) if unit_m else ""
        params.append({"name": name, "value": value, "unit": unit, "description": desc})
    return params


def extract_physics_from_java(java_path):
    """提取物理场接口列表"""
    physics = []
    if not os.path.exists(java_path):
        return physics
    with open(java_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    pattern = re.compile(
        r'model\.component\("(\w+)"\)\.physics\(\)\.create\(\s*"(\w+)"\s*,\s*"([^"]+)"'
    )
    for m in pattern.finditer(content):
        physics.append({"component": m.group(1), "tag": m.group(2), "type": m.group(3)})
    return physics


def detect_geometry_dimension(java_path):
    """探测几何维度 1D/2D/3D"""
    if not os.path.exists(java_path):
        return "unknown"
    with open(java_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    m = re.search(r'\.geom\(\)\.create\("(\w+)",\s*(\d)\)', content)
    if m:
        return f"{m.group(2)}D"
    return "1D"  # P2D 默认 1D


# ==============================================================
# 文档样式辅助
# ==============================================================
def set_cell_bg(cell, color_hex):
    """设置单元格背景色"""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), color_hex)
    tc_pr.append(shd)


def add_heading(doc, text, level=1, color=COLOR_MAIN):
    """加章节标题"""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = color
        run.font.name = '微软雅黑'
    return h


def add_para(doc, text, size=10.5, color=COLOR_BLACK, bold=False, italic=False, align=None):
    """加段落"""
    p = doc.add_paragraph()
    if align == 'center':
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == 'right':
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.name = '微软雅黑'
    run.bold = bold
    run.italic = italic
    return p


def add_table(doc, header, rows, col_widths=None):
    """加表格,带样式"""
    table = doc.add_table(rows=1 + len(rows), cols=len(header))
    table.style = 'Light Grid Accent 1'
    table.autofit = False

    # 表头
    hdr = table.rows[0]
    for i, h in enumerate(header):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(h)
        run.font.bold = True
        run.font.size = Pt(9.5)
        run.font.name = '微软雅黑'
        set_cell_bg(cell, "F3F4F6")

    # 数据行
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.rows[i + 1].cells[j]
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(str(val) if val is not None else "")
            run.font.size = Pt(9.5)
            run.font.name = '微软雅黑'

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Inches(w)
    return table


# ==============================================================
# 图: 电压时变 + 实验对比
# ==============================================================
def make_voltage_plot(sim_csv, exp_csv, out_png, title="端电压 vs 时间"):
    """画电压时变曲线,可选实验对比"""
    if not PLOTTING_AVAILABLE or not os.path.exists(sim_csv):
        return None
    try:
        sim = pd.read_csv(sim_csv, engine='python')
        fig, ax = plt.subplots(figsize=(6.5, 3.5), dpi=150)
        # 标签按中文字体是否可用切换,避免方框
        lab_sim, lab_exp = ("仿真", "实验") if _CJK_OK else ("Simulation", "Experiment")
        xl, yl = ("时间 (s)", "电压 (V)") if _CJK_OK else ("Time (s)", "Voltage (V)")
        t = title if _CJK_OK else "Terminal Voltage vs Time"
        ax.plot(sim.iloc[:, 0], sim.iloc[:, 1], '-', color='#1E2761', linewidth=2, label=lab_sim)

        if exp_csv and os.path.exists(exp_csv):
            try:
                exp = pd.read_csv(exp_csv, engine='python', encoding='utf-8')
            except UnicodeDecodeError:
                exp = pd.read_csv(exp_csv, engine='python', encoding='gbk')
            ax.plot(exp.iloc[:, 0], exp.iloc[:, 1], '--', color='#C8102E', linewidth=1.5, label=lab_exp)

        ax.set_xlabel(xl, fontsize=10)
        ax.set_ylabel(yl, fontsize=10)
        ax.set_title(t, fontsize=11)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150, bbox_inches='tight')
        plt.close()
        return out_png
    except Exception as e:
        print(f"WARN: failed to make voltage plot: {e}", file=sys.stderr)
        return None


def make_temperature_plot(temp_csv, out_png, title="温度 vs 时间"):
    """画温度时变曲线"""
    if not PLOTTING_AVAILABLE or not os.path.exists(temp_csv):
        return None
    try:
        df = pd.read_csv(temp_csv, engine='python')
        fig, ax = plt.subplots(figsize=(6.5, 3.5), dpi=150)
        xl, yl = ("时间 (s)", "温度 (°C)") if _CJK_OK else ("Time (s)", "Temperature (°C)")
        t = title if _CJK_OK else "Temperature vs Time"
        # 第一列假设是时间,后面是温度
        for col in df.columns[1:]:
            label = col
            data = df[col].values
            if data.mean() > 200:
                data = data - 273.15
                label = f"{col} (°C)"
            ax.plot(df.iloc[:, 0], data, linewidth=2, label=label)
        ax.set_xlabel(xl, fontsize=10)
        ax.set_ylabel(yl, fontsize=10)
        ax.set_title(t, fontsize=11)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150, bbox_inches='tight')
        plt.close()
        return out_png
    except Exception as e:
        print(f"WARN: failed to make temperature plot: {e}", file=sys.stderr)
        return None


# ==============================================================
# 主报告生成
# ==============================================================
def generate_report(args):
    """主报告生成函数"""
    # 加载所有输入
    metrics = {}
    if args.metrics and os.path.exists(args.metrics):
        try:
            df = pd.read_csv(args.metrics, engine='python', encoding='utf-8')
        except Exception:
            try:
                df = pd.read_csv(args.metrics, engine='python', encoding='gbk')
            except Exception:
                df = None
        if df is not None and len(df) > 0:
            for col in df.columns:
                try:
                    metrics[col.strip()] = float(df.iloc[0][col])
                except (ValueError, TypeError):
                    metrics[col.strip()] = df.iloc[0][col]

    criteria = {}
    if args.criteria and os.path.exists(args.criteria):
        with open(args.criteria, 'r', encoding='utf-8') as f:
            criteria = yaml.safe_load(f) or {}

    debug_history = []
    if args.debug_log and os.path.exists(args.debug_log):
        with open(args.debug_log, 'r', encoding='utf-8') as f:
            debug_history = json.load(f)

    params = extract_params_from_java(args.java) if args.java else []
    physics_list = extract_physics_from_java(args.java) if args.java else []
    geom_dim = detect_geometry_dimension(args.java) if args.java else "unknown"

    workdir = args.workdir or os.path.dirname(args.out) or "."
    plots_dir = os.path.join(workdir, "plots")
    os.makedirs(plots_dir, exist_ok=True)

    # 判断验收总体结果
    final_iter = debug_history[-1] if debug_history else None
    if final_iter and "acceptance" in final_iter:
        acc = final_iter["acceptance"]
        if acc.get("all_passed"):
            verdict = ("✅ PASS", COLOR_GREEN)
        elif acc.get("items_failed"):
            verdict = ("❌ FAIL", COLOR_RED)
        else:
            verdict = ("⚠ PARTIAL", COLOR_AMBER)
    else:
        verdict = ("⚠ INCOMPLETE", COLOR_AMBER)

    # === 开始生成 docx ===
    doc = Document()
    # 页面设置
    for section in doc.sections:
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)

    task_title = criteria.get("meta", {}).get("task", "COMSOL 仿真任务")

    # ============================================================
    # 封面
    # ============================================================
    add_para(doc, "", size=10)  # 顶部留白
    add_para(doc, "电芯仿真报告", size=30, bold=True, color=COLOR_MAIN, align='center')
    add_para(doc, "", size=8)
    add_para(doc, task_title, size=14, color=COLOR_GRAY, align='center')
    add_para(doc, "", size=20)

    # 元数据表
    meta_table = doc.add_table(rows=5, cols=2)
    meta_table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_data = [
        ("模型版本",   os.path.basename(args.java) if args.java else "N/A"),
        ("生成日期",   datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("COMSOL 版本", "6.4"),
        ("仿真平台",   "AI 自主仿真 Agent v3.0"),
        ("验收结果",   verdict[0]),
    ]
    for i, (k, v) in enumerate(meta_data):
        c1 = meta_table.rows[i].cells[0]
        c1.text = ""
        p1 = c1.paragraphs[0]
        r1 = p1.add_run(k)
        r1.font.size = Pt(11)
        r1.font.bold = True
        r1.font.name = '微软雅黑'
        c2 = meta_table.rows[i].cells[1]
        c2.text = ""
        p2 = c2.paragraphs[0]
        r2 = p2.add_run(str(v))
        r2.font.size = Pt(11)
        r2.font.name = '微软雅黑'
        if k == "验收结果":
            r2.font.bold = True
            r2.font.color.rgb = verdict[1]

    doc.add_page_break()

    # ============================================================
    # 1. 摘要
    # ============================================================
    add_heading(doc, "1. 摘要", level=1)

    add_para(doc, "任务", bold=True, size=11)
    add_para(doc, task_title)
    add_para(doc, "")

    add_para(doc, "方法", bold=True, size=11)
    add_para(doc, f"基于 COMSOL Multiphysics 6.4 的 P2D + 热耦合模型,自主生成 .java 模型文件,"
                  f"经过 {len(debug_history)} 次 debug 迭代,"
                  f"最终{'求解收敛并通过验收' if verdict[0].startswith('✅') else '未完成验收要求'}。")
    add_para(doc, "")

    add_para(doc, "主要结果", bold=True, size=11)
    if metrics:
        # 列出关键指标
        for k, v in list(metrics.items())[:6]:
            if isinstance(v, (int, float)):
                add_para(doc, f"  • {k}: {v:.4g}")
            else:
                add_para(doc, f"  • {k}: {v}")
    add_para(doc, "")

    add_para(doc, "验收结论", bold=True, size=11)
    p = doc.add_paragraph()
    run = p.add_run(verdict[0])
    run.font.size = Pt(14)
    run.font.bold = True
    run.font.color.rgb = verdict[1]
    run.font.name = '微软雅黑'

    doc.add_page_break()

    # ============================================================
    # 2. 模型描述
    # ============================================================
    add_heading(doc, "2. 模型描述", level=1)

    add_heading(doc, "2.1 几何", level=2, color=COLOR_BLACK)
    add_para(doc, f"模型几何维度: {geom_dim}")
    # 几何参数表
    geom_params = [p for p in params if any(k in p["name"] for k in ["L_", "rp_", "r_"])]
    if geom_params:
        add_table(doc, ["参数", "值", "单位", "描述"],
                  [[p["name"], p["value"], p["unit"], p["description"]] for p in geom_params],
                  col_widths=[1.5, 1.5, 1.0, 2.5])

    add_para(doc, "")
    add_heading(doc, "2.2 物理场", level=2, color=COLOR_BLACK)
    if physics_list:
        add_table(doc, ["组件", "Tag", "物理场类型"],
                  [[p["component"], p["tag"], p["type"]] for p in physics_list],
                  col_widths=[1.5, 1.5, 3.0])

    add_para(doc, "")
    add_heading(doc, "2.3 边界条件", level=2, color=COLOR_BLACK)
    add_para(doc, "(关键边界条件从 .java 中提取,具体细节见附录的完整 .java 文件)")

    doc.add_page_break()

    # ============================================================
    # 3. 完整参数表
    # ============================================================
    add_heading(doc, "3. 参数表", level=1)
    if params:
        # 拆成两列展示节省空间
        add_table(doc, ["参数", "值", "单位", "描述"],
                  [[p["name"], p["value"], p["unit"], p["description"][:40]] for p in params],
                  col_widths=[1.4, 1.6, 0.8, 2.5])

    doc.add_page_break()

    # ============================================================
    # 4. 仿真结果
    # ============================================================
    add_heading(doc, "4. 仿真结果", level=1)

    add_heading(doc, "4.1 关键指标", level=2, color=COLOR_BLACK)
    if metrics:
        add_table(doc, ["指标", "值"],
                  [[k, f"{v:.4g}" if isinstance(v, (int, float)) else str(v)]
                   for k, v in metrics.items()],
                  col_widths=[3.0, 3.0])

    # 4.2 曲线
    add_para(doc, "")
    add_heading(doc, "4.2 关键曲线", level=2, color=COLOR_BLACK)

    voltage_csv = args.voltage_csv or os.path.join(workdir, "voltage_vs_time.csv")
    if os.path.exists(voltage_csv):
        png = os.path.join(plots_dir, "voltage_vs_time.png")
        result = make_voltage_plot(voltage_csv, args.exp_csv, png,
                                   title="图 1: 端电压 vs 时间")
        if result and os.path.exists(result):
            doc.add_picture(result, width=Inches(6))
            add_para(doc, "图 1: 端电压随时间变化(及与实验对比,如有)",
                     size=9, italic=True, color=COLOR_GRAY, align='center')

    temp_csv = args.temp_csv or os.path.join(workdir, "temperature_vs_time.csv")
    if os.path.exists(temp_csv):
        png = os.path.join(plots_dir, "temperature_vs_time.png")
        result = make_temperature_plot(temp_csv, png, title="图 2: 温度 vs 时间")
        if result and os.path.exists(result):
            doc.add_picture(result, width=Inches(6))
            add_para(doc, "图 2: 温度随时间变化",
                     size=9, italic=True, color=COLOR_GRAY, align='center')

    doc.add_page_break()

    # ============================================================
    # 5. Debug 过程
    # ============================================================
    add_heading(doc, "5. Debug 过程", level=1)
    add_para(doc, f"共经过 {len(debug_history)} 次 debug 迭代,具体如下:")
    add_para(doc, "")

    for i, entry in enumerate(debug_history):
        add_para(doc, f"迭代 {entry.get('iteration', i+1)}", bold=True, size=11, color=COLOR_MAIN)
        compile_ok = entry.get("compile", {}).get("success", None)
        solve_ok = entry.get("solve", {}).get("success", None)
        acc = entry.get("acceptance", {})

        if compile_ok is not None:
            status = "✅ 通过" if compile_ok else "❌ 失败"
            add_para(doc, f"  • 编译: {status}")
            if not compile_ok:
                errs = entry.get("compile", {}).get("errors", [])
                if errs:
                    add_para(doc, f"    错误: {errs[0].get('description','unknown')}",
                            size=10, color=COLOR_RED)

        if solve_ok is not None:
            status = "✅ 通过" if solve_ok else "❌ 失败"
            add_para(doc, f"  • 求解: {status}")
            if not solve_ok:
                errs = entry.get("solve", {}).get("errors", [])
                if errs:
                    add_para(doc, f"    错误: {errs[0].get('description','unknown')}",
                            size=10, color=COLOR_RED)

        if acc:
            n_pass = len(acc.get("items_passed", []))
            n_fail = len(acc.get("items_failed", []))
            n_warn = len(acc.get("warnings", []))
            if acc.get("all_passed"):
                add_para(doc, f"  • 验收: ✅ 全部通过 ({n_pass} 项)",
                        color=COLOR_GREEN)
            else:
                add_para(doc, f"  • 验收: ⚠ 部分失败 (通过 {n_pass}, 失败 {n_fail}, 警告 {n_warn})",
                        color=COLOR_AMBER)
                for failed in acc.get("items_failed", [])[:3]:
                    add_para(doc, f"      ✗ {failed.get('id')}: "
                                  f"actual {failed.get('actual', failed.get('score'))} "
                                  f"vs {failed.get('bound', failed.get('threshold'))} "
                                  f"{failed.get('unit','')}",
                            size=9.5, color=COLOR_RED)
        add_para(doc, "")

    doc.add_page_break()

    # ============================================================
    # 6. 验收对标
    # ============================================================
    add_heading(doc, "6. 验收对标", level=1)

    if final_iter and "acceptance" in final_iter:
        acc = final_iter["acceptance"]
        rows = []

        def _fmt(item):
            """统一格式化 actual/score,None 显示为 '—'"""
            v = item.get('actual', item.get('score'))
            if v is None:
                return "—"
            if isinstance(v, (int, float)):
                return f"{v:.4g}"
            return str(v)

        for item in acc.get("items_passed", []):
            rows.append([
                item.get("id", ""),
                item.get("description", "")[:30],
                str(item.get("bound", item.get("threshold", ""))),
                _fmt(item),
                item.get("unit", ""),
                "✅ PASS"
            ])
        for item in acc.get("items_failed", []):
            note = f" ({item['error'][:25]})" if 'error' in item else ""
            rows.append([
                item.get("id", "") + note,
                item.get("description", "")[:30],
                str(item.get("bound", item.get("threshold", ""))),
                _fmt(item),
                item.get("unit", ""),
                "❌ FAIL"
            ])
        for item in acc.get("warnings", []):
            rows.append([
                item.get("id", ""),
                item.get("description", "")[:30],
                str(item.get("bound", item.get("threshold", ""))),
                _fmt(item),
                item.get("unit", ""),
                "⚠ WARN"
            ])
        for item in acc.get("skipped", []):
            reason = item.get('reason', item.get('error', ''))[:25]
            rows.append([
                item.get("id", ""),
                (item.get("description", "") or reason)[:30],
                str(item.get("bound", item.get("threshold", ""))),
                _fmt(item),
                item.get("unit", ""),
                "⊘ SKIP"
            ])
        add_table(doc, ["ID", "描述", "要求", "实际", "单位", "结果"], rows,
                  col_widths=[1.2, 1.7, 0.9, 0.9, 0.6, 0.8])

        # skipped 提示
        if acc.get("skipped"):
            add_para(doc, "")
            add_para(doc, f"⊘ 注: {len(acc['skipped'])} 项无法本地验证(指标未导出或文件缺失),"
                          f"未计入通过。详见上表 SKIP 行。",
                     size=9.5, color=COLOR_AMBER)

    add_para(doc, "")
    p = doc.add_paragraph()
    run = p.add_run(f"整体结论: {verdict[0]}")
    run.font.size = Pt(13)
    run.font.bold = True
    run.font.color.rgb = verdict[1]
    run.font.name = '微软雅黑'

    doc.add_page_break()

    # ============================================================
    # 7. 结论与建议
    # ============================================================
    add_heading(doc, "7. 结论与建议", level=1)

    if verdict[0].startswith("✅"):
        add_para(doc, "本仿真任务验收通过。")
        add_para(doc, "")
        add_para(doc, "主要发现:", bold=True)
        if final_iter and "acceptance" in final_iter:
            for item in final_iter["acceptance"].get("items_passed", [])[:3]:
                add_para(doc, f"  • {item.get('id')}: 实际 {item.get('actual', item.get('score'))} "
                              f"满足要求 {item.get('bound', item.get('threshold'))}")
    else:
        add_para(doc, "本仿真任务在 AI 自主 debug 预算内未完全达到验收要求。", bold=True, color=COLOR_RED)
        add_para(doc, "")
        add_para(doc, "建议:", bold=True)
        add_para(doc, "  1. 审阅第 5 节 Debug 过程,确认 AI 的调参方向是否合理")
        add_para(doc, "  2. 考虑放宽验收阈值(如允许的工程容差)")
        add_para(doc, "  3. 提供更多输入数据(如更精细的 OCV 实测、多倍率实验)")
        add_para(doc, "  4. 切换 Snippet Mode 进行人工 debug")

    add_para(doc, "")
    add_para(doc, "模型局限说明:", bold=True)
    add_para(doc, "  • 本模型基于给定工况构建,推广到其他温度/倍率时需重新验证")
    add_para(doc, "  • 未考虑老化、SEI 生长、锂沉积等长期机制")
    add_para(doc, "  • AI 自动调参均限于数值参数(扩散系数、反应速率、求解器容差)")
    add_para(doc, "    未涉及物理场结构性修改")

    # 保存
    doc.save(args.out)
    print(f"Report saved: {args.out}", file=sys.stderr)
    return args.out


# ==============================================================
# CLI
# ==============================================================
def main():
    ap = argparse.ArgumentParser(description="COMSOL 仿真报告生成器")
    ap.add_argument('--java', help='源 .java 文件')
    ap.add_argument('--metrics', help='metrics.csv')
    ap.add_argument('--criteria', help='acceptance.yaml')
    ap.add_argument('--debug-log', help='debug_history.json')
    ap.add_argument('--workdir', help='工作目录')
    ap.add_argument('--voltage-csv', help='voltage_vs_time.csv (可选)')
    ap.add_argument('--temp-csv', help='temperature_vs_time.csv (可选)')
    ap.add_argument('--exp-csv', help='实验对比 CSV (可选)')
    ap.add_argument('--out', required=True, help='输出 .docx 路径')
    args = ap.parse_args()

    generate_report(args)


if __name__ == '__main__':
    main()
