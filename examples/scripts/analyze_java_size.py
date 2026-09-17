#!/usr/bin/env python3
"""
analyze_java_size.py — COMSOL .java 文件体积诊断工具

分析 COMSOL 导出的 .java 文件,识别体积大头,给出针对性的瘦身建议。

用法:
    python analyze_java_size.py <path/to/model.java>
    python analyze_java_size.py cell_LFP_280Ah_v3.java

输出:
    - 文件总体积
    - 各 section (param/geom/physics/mesh/study/sol/result/func) 的行数和占比
    - 最长行 (通常是嵌入的插值表数据)
    - 估算 token 数 (对 AI 阅读成本的参考)
    - 针对性的瘦身建议

依赖: 仅 Python 标准库
兼容: Python 3.7+
"""

import argparse
import os
import re
import sys
from collections import OrderedDict


# 各 section 的识别 pattern (按 COMSOL 6.x 的导出习惯)
SECTION_PATTERNS = OrderedDict([
    ('param',       r'^\s*model\.param\(\)'),
    ('func',        r'^\s*model\.func\('),
    ('component',   r'^\s*model\.component\([^)]+\)\.create'),
    ('geom',        r'^\s*model\.component\([^)]+\)\.geom\('),
    ('variable',    r'^\s*model\.component\([^)]+\)\.variable\('),
    ('material',    r'^\s*model\.component\([^)]+\)\.material\('),
    ('selection',   r'^\s*model\.component\([^)]+\)\.selection\('),
    ('physics',     r'^\s*model\.component\([^)]+\)\.physics\('),
    ('multiphysics',r'^\s*model\.component\([^)]+\)\.multiphysics\('),
    ('cpl',         r'^\s*model\.component\([^)]+\)\.cpl\('),
    ('mesh',        r'^\s*model\.component\([^)]+\)\.mesh\('),
    ('study',       r'^\s*model\.study\('),
    ('sol',         r'^\s*model\.sol\('),
    ('batch',       r'^\s*model\.batch\('),
    ('result',      r'^\s*model\.result\('),
])


def analyze(path):
    """主分析函数"""
    if not os.path.exists(path):
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(path)

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    n_lines = len(lines)

    # 各 section 行数统计
    section_counts = {name: 0 for name in SECTION_PATTERNS}
    section_chars = {name: 0 for name in SECTION_PATTERNS}

    compiled_patterns = {name: re.compile(p) for name, p in SECTION_PATTERNS.items()}

    for line in lines:
        for name, pat in compiled_patterns.items():
            if pat.match(line):
                section_counts[name] += 1
                section_chars[name] += len(line)
                break  # 一行只算入第一个匹配的section

    # 最长行 (识别嵌入数据)
    longest_lines = sorted(
        [(len(line), i+1, line[:100]) for i, line in enumerate(lines)],
        key=lambda x: -x[0]
    )[:10]

    # setIndex 调用统计 (插值表的主要标志)
    setindex_count = sum(1 for line in lines if 'setIndex' in line)

    # ==== 输出报告 ====
    print("=" * 70)
    print(f" COMSOL .java 体积诊断: {os.path.basename(path)}")
    print("=" * 70)

    # 总体积
    if file_size < 1024:
        size_str = f"{file_size} B"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size / 1024 / 1024:.2f} MB"

    # 粗略 token 估算 (代码约 0.3-0.4 tok/byte,这里用 0.3 偏保守)
    est_tokens = int(file_size * 0.3)

    print(f"\n文件总体积: {size_str}  ({n_lines:,} 行)")
    print(f"估算 token: ~{est_tokens:,} tokens (粗略,实际可能 {int(est_tokens*0.8):,}–{int(est_tokens*1.3):,})")

    # 体积评级
    print(f"\n体积评级: ", end='')
    if file_size < 200 * 1024:
        print("✅ 健康 (<200 KB)")
    elif file_size < 1024 * 1024:
        print("◐ 略大 (200KB-1MB,可优化)")
    elif file_size < 5 * 1024 * 1024:
        print("⚠️  偏大 (1-5 MB,建议瘦身)")
    elif file_size < 20 * 1024 * 1024:
        print("❌ 过大 (5-20 MB,必须瘦身)")
    else:
        print("🚨 极大 (>20 MB,几乎必然是没清理求解器/插值表)")

    # Section分布
    print(f"\n{'Section':<14} {'行数':>8} {'占比':>8} {'体积':>10} {'体积占比':>10}")
    print("-" * 60)
    total_section_lines = sum(section_counts.values())
    total_section_chars = sum(section_chars.values())

    for name in SECTION_PATTERNS:
        cnt = section_counts[name]
        chars = section_chars[name]
        if cnt == 0:
            continue
        line_pct = 100 * cnt / n_lines if n_lines else 0
        char_pct = 100 * chars / file_size if file_size else 0
        if chars < 1024:
            chars_str = f"{chars} B"
        else:
            chars_str = f"{chars/1024:.1f} KB"

        # 标记可疑大头
        flag = ""
        if name == 'sol' and char_pct > 30:
            flag = " ⚠️"
        if name == 'func' and char_pct > 20:
            flag = " ⚠️"
        if name == 'material' and char_pct > 30:
            flag = " ⚠️"

        print(f"{name:<14} {cnt:>8,} {line_pct:>7.1f}% {chars_str:>10} {char_pct:>9.1f}%{flag}")

    # 其他统计
    other_lines = n_lines - total_section_lines
    other_chars = file_size - total_section_chars
    if other_lines > 0:
        print(f"{'(其他)':<14} {other_lines:>8,} {100*other_lines/n_lines:>7.1f}% {other_chars/1024:>9.1f} KB {100*other_chars/file_size:>9.1f}%")

    print(f"\nsetIndex 调用: {setindex_count:,} 次")
    if setindex_count > 1000:
        print("  ⚠️  大量 setIndex 通常表示嵌入了大型插值表数据")

    # 最长行 (识别嵌入数据)
    print(f"\n最长的5行 (通常是嵌入数据):")
    for length, lineno, preview in longest_lines[:5]:
        if length > 200:
            print(f"  L{lineno}: {length:,} chars — {preview[:80]}...")

    # ==== 瘦身建议 ====
    print("\n" + "=" * 70)
    print(" 瘦身建议 (按收益从高到低)")
    print("=" * 70)

    recommendations = []

    if section_chars['sol'] > 500 * 1024:
        recommendations.append((
            section_chars['sol'],
            "A",
            f"删除 Solver Configurations: 求解器节点占 {section_chars['sol']/1024:.0f} KB ({100*section_chars['sol']/file_size:.0f}%)\n"
            f"     操作: COMSOL Desktop → Study → Solver Configurations → 右键 Delete\n"
            f"     代价: 删除后需在COMSOL中重新生成sol节点 (Compute 或 Show Default Solver)"
        ))

    if section_chars['func'] > 200 * 1024 or setindex_count > 1000:
        recommendations.append((
            section_chars['func'] + setindex_count * 50,
            "B",
            f"插值表外置: func节点占 {section_chars['func']/1024:.0f} KB, setIndex {setindex_count} 次\n"
            f"     操作: 每个 Interpolation 函数 → Data source 改为 File (而非 Local table)\n"
            f"     代价: 编译时CSV必须存在指定路径"
        ))

    if section_chars['material'] > 500 * 1024:
        recommendations.append((
            section_chars['material'],
            "C",
            f"清理 Material Library 副本: material占 {section_chars['material']/1024:.0f} KB\n"
            f"     操作: 删掉拖入的 MaterialsLib_* 完整副本,自建 mat 只引用必要属性"
        ))

    if section_chars['mesh'] > 300 * 1024:
        recommendations.append((
            section_chars['mesh'],
            "D",
            f"导出时不勾 Include mesh: mesh占 {section_chars['mesh']/1024:.0f} KB\n"
            f"     操作: File → Save As Java 时关闭 'Include mesh' 选项"
        ))

    if section_chars['result'] > 200 * 1024:
        recommendations.append((
            section_chars['result'],
            "E",
            f"删除调试用的 Probes/Cut*: result占 {section_chars['result']/1024:.0f} KB\n"
            f"     操作: Model Builder → Results → 删掉不必要的 Cut Lines/Planes/Probes"
        ))

    if not recommendations:
        if file_size < 500 * 1024:
            print("\n  ✅ 文件已经较精简,无明显瘦身空间")
        else:
            print("\n  没有发现明显的单项大头,但总体仍偏大。")
            print("  可能是建模复杂度本身较高,或多个中型节点累积。")
            print("  建议查看上面的最长行,可能有自定义的大型嵌入数据。")
    else:
        recommendations.sort(key=lambda x: -x[0])
        for _, label, msg in recommendations:
            print(f"\n  [{label}] {msg}")

    # 终极方案
    print("\n" + "-" * 70)
    print("终极方案 (AI专用版,不能编译):")
    print(f"  python strip_java_for_ai.py {os.path.basename(path)} <output.java>")
    print()
    print("详见 references/java_export_slimming.md 的完整瘦身checklist。")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="COMSOL .java 文件体积诊断工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="详见 references/java_export_slimming.md"
    )
    parser.add_argument('java_file', help='COMSOL导出的.java文件路径')
    args = parser.parse_args()

    analyze(args.java_file)


if __name__ == '__main__':
    main()
