# 仿真报告 (.docx) 标准模板

本文档定义 **Autonomous Mode** 完成后自动生成的仿真报告标准结构。**5-8 页常规详细度**(per 用户要求)。

报告由 `examples/scripts/generate_report.py` 自动生成。

---

## 1. 报告结构总览

```
仿真报告 (5-8 页)
├── 封面 (0.5 页)
├── 1. 摘要 Executive Summary (1 页)
├── 2. 模型描述 (1-2 页)
├── 3. 参数表 (0.5 页)
├── 4. 仿真结果 (2-3 页, 含曲线)
├── 5. Debug 过程 (1 页)
├── 6. 验收对标 (1 页)
├── 7. 结论与建议 (0.5 页)
└── 附录: 文件清单 + AI 调参记录 (可选,作为追溯)
```

---

## 2. 每章内容详细规范

### 封面 (0.5 页)

```
┌─────────────────────────────────────────┐
│                                         │
│        电芯仿真报告                       │
│                                         │
│   LFP 280Ah · 1C CC 放电 · 25°C 环境      │
│                                         │
│                                         │
│   模型版本:  GeneratedModel_v3.java       │
│   生成日期:  2026-05-20                  │
│   COMSOL 版本: 6.4                      │
│   仿真平台: AI 自主仿真 Agent (v3.0)      │
│                                         │
│   验收结果:  ✅ PASS / ⚠ PARTIAL / ❌ FAIL │
│                                         │
└─────────────────────────────────────────┘
```

字段填充:
- **标题**: 取自 `acceptance.yaml` 的 `meta.task`
- **副标题**: 自动生成,模型几何 + 工况 + 温度
- **验收结果徽章**: 根据 STEP E 最终结果

### 1. 摘要 Executive Summary (1 页)

模板:

> **任务**: <从 acceptance.yaml 的 meta.task 摘录>
>
> **方法**: 基于 COMSOL Multiphysics 6.4 的 P2D + 热耦合模型,自主生成 .java 模型文件,经过 N 次 debug 迭代,最终求解收敛并通过验收。
>
> **主要结果**:
> - 1C 放电容量: 278.3 Ah (验收要求 ≥ 270 Ah) ✅
> - 最高温度: 38.5 °C (验收要求 ≤ 60 °C) ✅
> - 与实验 RMSE: 0.032 V (验收要求 ≤ 0.05 V) ✅
> - 求解时长: 12 分 33 秒
>
> **关键发现**:
> - 模型与实验在中段平台拟合良好,放电末端略有偏差
> - 颗粒固相扩散是 LFP 2C 倍率性能的主要限制
> - 自然对流条件下温升 <14 K,无需强制冷却
>
> **验收结论**: ✅ **全部验收条件通过**

### 2. 模型描述 (1-2 页)

#### 2.1 几何

- 描述: "1D 伪二维 P2D 几何,沿电池厚度方向"
- 关键尺寸表 (从 .java 提取):

| 区域 | 厚度 | 单位 |
|---|---|---|
| 负极 (Gr) | L_neg = 80 | µm |
| 隔膜 | L_sep = 20 | µm |
| 正极 (LFP) | L_pos = 90 | µm |

(自动从 model.param().set 提取并表格化)

#### 2.2 物理场

| 物理场接口 | tag | 用途 |
|---|---|---|
| Lithium-Ion Battery | liion | P2D 电化学 |
| Heat Transfer in Solids | ht | 温度场 |
| Electrochemical Heating | emh1 | 电热耦合 |

(自动从 model.component(...).physics().create(...) 提取)

#### 2.3 边界条件

- 正极集流体: Electrode Current `ecs1` (CC 模式) 或 Global Equation (CP 模式)
- 负极集流体: Electric Ground
- 电芯表面: Convective Heat Flux, h = X W/(m²·K), T_ext = X K
- (具体值从 .java 提取)

#### 2.4 网格

(从 model.component(...).mesh(...) 段提取)
- 总单元数: N
- 最小单元尺寸: X µm
- 网格类型: 1D Edge (P2D伪二维默认)

### 3. 参数表 (0.5 页)

完整列出 `model.param().set` 的所有参数:

| 参数 | 值 | 单位 | 描述 |
|---|---|---|---|
| I_1C | 280 | A | 1C 参考电流 |
| Crate | 1 | - | C 倍率 |
| I_app | Crate*I_1C | A | 实际电流 |
| T_amb | 298.15 | K | 环境温度 |
| h_amb | 10 | W/(m²·K) | 对流换热系数 |
| epss_neg | 0.6 | - | 负极活性物质体积分数 |
| ... | ... | ... | ... |

(全部从 .java 自动提取,描述取注释)

⚠️ 如果 AI 在 debug 过程中改了参数,**用 ★ 标记**:

| 参数 | 值 | 单位 | 描述 |
|---|---|---|---|
| Ds_pos | **1e-16** ★ | m²/s | 正极固相扩散 (AI 从 1e-17 调高一档) |
| OCV_pos offset | **-20mV** ★ | V | OCV 函数偏移 (AI 校准实验对标) |

★ 标记的项,会在第 5 节 Debug 过程详细说明原因。

### 4. 仿真结果 (2-3 页,核心内容)

#### 4.1 关键指标汇总表

| 指标 | 计算值 | 单位 | 备注 |
|---|---|---|---|
| 放电容量 | 278.3 | Ah | |
| 平均放电电压 | 3.18 | V | |
| 放电时长 | 3582 | s | 触发 V_min = 2.5V |
| 最高温度 | 311.7 (38.5°C) | K | |
| 最大温差 | 13.2 | K | |
| 能量效率 | 96.4% | - | |

#### 4.2 关键曲线 (插图)

**图 1: 端电压 vs 时间**
- X: 时间 (s),Y: 电压 (V)
- 曲线: 仿真 (实线) + 实验 (虚线,如有)
- 标注: V_max (3.65V), V_min (2.5V), 放电终止点
- 文件: `plots/voltage_vs_time.png` (300 DPI)

**图 2: 温度分布 vs 时间**
- 多曲线: T_max, T_avg, T_amb
- 文件: `plots/temperature_vs_time.png`

**图 3: SOC vs 时间** (从 socinit_pos/neg 演化)
- 文件: `plots/soc_vs_time.png`

**图 4: 沿厚度方向的浓度分布** (P2D 特征)
- 时间多个快照,展示 c_s 在负极/隔膜/正极分布
- 文件: `plots/concentration_profile.png`

(图根据用户场景选,1C CC 至少前 2 图,CP 还要加 P_app vs I_app_var,多尺度模型还要加 3D 温度场切片)

#### 4.3 与实验对比 (如有 reference)

| 时间 (s) | 仿真电压 (V) | 实验电压 (V) | 偏差 (V) |
|---|---|---|---|
| 0 | 3.50 | 3.50 | 0.00 |
| 600 | 3.34 | 3.32 | +0.02 |
| 1200 | 3.30 | 3.28 | +0.02 |
| 1800 | 3.27 | 3.25 | +0.02 |
| 2400 | 3.21 | 3.18 | +0.03 |
| 3000 | 3.08 | 3.05 | +0.03 |
| 3500 | 2.65 | 2.55 | +0.10 |
| RMSE | | | **0.032 V** |

(自动从 sim_export.csv 和 reference.csv 计算,取关键时刻采样)

**图 5: 仿真 vs 实验偏差曲线**
- 文件: `plots/sim_vs_exp_residual.png`

### 5. Debug 过程 (1 页)

按 `debug_history.json` 渲染:

> 共经过 **3** 次 debug 迭代,具体如下:
>
> **迭代 1**: 初始版本
> - 求解阶段: ✅ 通过
> - 验收检查: ⚠ 部分失败
>   - 容量 = 248 Ah (期望 ≥ 270 Ah) ❌
>   - RMSE = 0.087 V (期望 ≤ 0.05 V) ❌
> - 诊断: 颗粒扩散系数偏低,放电不充分
> - 调整: `Ds_pos` 从 5e-17 → 1e-16 m²/s
>
> **迭代 2**: 提升固相扩散
> - 求解阶段: ✅ 通过
> - 验收检查: ⚠ 部分失败
>   - 容量 = 276 Ah ✅
>   - RMSE = 0.062 V ❌
> - 诊断: OCV 平台与实验偏差,正极 OCV 整体偏高约 20mV
> - 调整: OCV_pos 函数加 -20mV offset
>
> **迭代 3**: OCV 校准
> - 求解阶段: ✅ 通过
> - 验收检查: ✅ 全部通过
>   - 容量 = 278.3 Ah ✅
>   - RMSE = 0.032 V ✅
> - **结论: 验收通过,停止 debug。**

加一个调参追溯表:

| 参数 | 初始值 | 最终值 | 单位 | 变化原因 |
|---|---|---|---|---|
| Ds_pos | 5e-17 | 1e-16 | m²/s | 容量不足,扩散是瓶颈 |
| OCV_pos offset | 0 | -20 | mV | 实验对标,OCV 整体偏高 |

### 6. 验收对标 (1 页)

详细表格,**逐项**列出 acceptance.yaml 的每条验收:

| ID | 描述 | 验收要求 | 实际值 | 单位 | 严重性 | 结果 |
|---|---|---|---|---|---|---|
| capacity_retention | 1C容量保持率 | ≥ 0.90 | 0.994 | - | hard | ✅ PASS |
| min_voltage | 最低端电压 | ≥ 2.5 | 2.501 | V | hard | ✅ PASS |
| max_temperature | 最高温度 | ≤ 60 | 38.5 | °C | hard | ✅ PASS |
| discharge_1C_25C | 1C 放电曲线 RMSE | ≤ 0.05 | 0.032 | V | hard | ✅ PASS |
| max_temperature_rise | 整体温升 | ≤ 15 | 13.2 | K | soft | ✅ PASS |

**整体结论**: ✅ **全部 hard 验收通过 + 全部 soft 警告通过**

如果有失败:
- 失败项用 ❌ 标记
- 整体结论改为 "⚠ 部分通过" 或 "❌ 未通过"
- 给出"未通过的可能原因"和"建议的后续操作"

### 7. 结论与建议 (0.5 页)

```
本仿真任务的主要结论:

1. 模型整体可用: 1C 工况下与实验 RMSE 0.032V (验收 0.05V),全部数值指标通过。

2. 关键校准: 通过 AI 自主 debug 完成了两项参数校准:
   - 提高正极固相扩散系数 Ds_pos (5e-17 → 1e-16 m²/s)
   - OCV_pos 整体下移 20mV (拟合实验)

   这两项校准可推广到同体系电池的其他工况仿真。

3. 模型局限:
   - 放电末端 (SOC<10%) 与实验偏差略大 (~100mV)
     可能原因: LFP 平台到底端的过渡区 OCV 拟合不够精细
   - 未涉及高倍率/低温工况,推广前需补充验证

4. 后续建议:
   - 用本模型扫描 2C/3C 高倍率工况,验证泛化能力
   - 在 -10°C 等低温条件下需调整 Ds 的温度依赖系数
   - 若有 2C 实验数据,可进一步加入多倍率联合校准
```

(基于结果,AI 自动生成)

### 附录: 文件清单 + AI 完整调参记录

简单列出工作目录中的所有文件:

```
工作目录: D:\models\auto_sim_LFP280Ah_20260520\

├── GeneratedModel.java                  最终版 .java
├── GeneratedModel_iter_1.java          初版 (供追溯)
├── GeneratedModel_iter_2.java
├── GeneratedModel.class                编译产物
├── result.mph                           ★ 验收用 .mph
├── metrics.csv                          关键指标
├── voltage_vs_time.csv                  时变电压
├── temperature_vs_time.csv              时变温度
├── debug_history.json                   完整 debug 日志
├── run.log                              COMSOL 求解日志
├── plots/                               报告引用的图
│   ├── voltage_vs_time.png
│   ├── temperature_vs_time.png
│   ├── soc_vs_time.png
│   ├── concentration_profile.png
│   └── sim_vs_exp_residual.png
├── acceptance.yaml                      验收条件 (输入)
└── simulation_report.docx               ★ 本文档
```

(完整 debug_history.json 的格式化版本附在附录,以备审计)

---

## 3. 报告样式约定

### 字体
- 标题: 微软雅黑 / Times New Roman, Bold
- 正文: 微软雅黑 / Arial, 11pt
- 表格: 微软雅黑 9-10pt
- 代码 (如出现): Consolas 9pt

### 颜色
- 主标题: 深蓝 #1E2761
- 副标题: 黑色
- 正文: 黑色
- 强调: 红色 #C8102E
- 验收 PASS: 绿色 #059669
- 验收 FAIL: 红色 #C8102E
- 警告 / SOFT FAIL: 橙色 #D97706

### 表格
- 表头: 浅灰底 #F3F4F6 + 加粗
- 单元格: 9-10pt
- 边框: 浅灰 #D1D5DB

### 图
- 全部 PNG,300 DPI
- 宽度填满正文区域 (约 6 英寸)
- 标题在图下,格式: "图 X: <描述>"
- matplotlib 风格: 浅灰背景 + 主曲线深色,辅助曲线浅色

---

## 4. 报告生成的输入清单

`generate_report.py` 需要以下输入:

| 输入 | 来源 | 用于 |
|---|---|---|
| `GeneratedModel.java` | STEP B 最终版 | 提取参数、物理场、几何描述 |
| `result.mph` | STEP D 求解产物 | (可选)再次提取数据,通常已通过 CSV 导出 |
| `metrics.csv` / `metrics.json` | STEP E 提取的指标 | 摘要、参数表、验收对标 |
| `*_vs_time.csv` | 仿真导出 | 画图 |
| `<exp_ref>.csv` | 用户提供 | 与仿真对比画图 |
| `acceptance.yaml` | 用户提供 | 验收对标的"要求"侧 |
| `debug_history.json` | STEP C-E 累积 | 第 5 节 Debug 过程 |
| `paths.json` | STEP A 配置 | 报告封面元数据 |

---

## 5. 失败情况下的报告

如果最终验收**没通过**(到 max_iter 仍 FAIL):

报告封面: ❌ **验收未通过**

第 1 节摘要换成:
> 经过 8 次 debug 迭代,模型仍未通过全部验收条件。已尝试的调参方案见第 5 节。
> 主要瓶颈: RMSE = 0.068V (要求 ≤ 0.05V)
> 建议:
> - 检查实验数据采样精度
> - 考虑放宽 RMSE 阈值至 0.07V (如果工程上可接受)
> - 提供更精细的 OCV 实测数据进行二次校准

第 5 节 Debug 过程: **完整列出 8 次迭代**(成败都列),给用户审计参考。

第 7 节结论换成:
> 自动 debug 在预算内未达成目标。**不代表模型本质有问题**,可能是:
> 1. 验收条件过于严格(可放宽阈值)
> 2. 输入数据不足(需要更多实验)
> 3. 物理建模假设需更新(超出 AI 自主权限)
>
> 建议用户审阅 debug 历史后决策:
> (a) 调整验收条件,重启 Autonomous Mode
> (b) 切换到 Snippet Mode 由人工继续 debug
> (c) 提供额外数据/约束信息后重启

**关键原则**: 失败的报告 **不是失败的输出**。完整的失败记录对工程审计、未来改进、debug 经验沉淀都极有价值。
