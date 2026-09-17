# 验收条件 (Acceptance Criteria) 定义框架

本文档定义 **Autonomous Mode** 中"什么时候 debug 可以停"的验收条件标准格式。

---

## 核心理念

debug 循环必须有**明确的终止条件**,否则:
- 太宽松 → AI 早早返回不合格结果
- 太严苛 → AI 永远在调,直到 max_iter 耗尽
- 不明确 → AI 自己猜目标,可能与用户预期偏差

所以 STEP A **必须** 让用户提供验收条件,否则不进入 STEP B。

---

## 验收条件的 4 个层次

每个层次单独可选,组合使用。用户至少提供一项。

| 层次 | 难度 | 用户输入 |
|---|---|---|
| **L1: 求解通过** | 低 | 无错误退出即可 |
| **L2: 物理合理** | 中 | "电压不能 <V_min" 等内置规则 |
| **L3: 数值指标** | 中 | "容量 ≥ 270Ah, 最高温度 ≤ 60°C" |
| **L4: 实验对标** | 高 | "1C放电曲线 RMSE < 0.05V (参照CSV)" |

---

## 标准 YAML 格式

工作目录中放 `acceptance.yaml`:

```yaml
# acceptance.yaml — 验收条件
# AI 会在 STEP E 逐项检查,任一未通过都触发 debug 循环

meta:
  task: "LFP 280Ah 电芯 1C CC 放电仿真"
  max_iterations: 8
  max_wall_clock_minutes: 120

# === L1: 求解通过 (始终启用,不需配置) ===

# === L2: 物理合理性规则 (built-in,可关闭) ===
physical_sanity:
  enabled: true
  rules:
    - id: voltage_in_window
      expr: "E_cell >= V_min and E_cell <= V_max"
      window_evaluation: "终止时电压在 [V_min, V_max] 内"
    - id: positive_capacity
      expr: "capacity_Ah > 0"
    - id: temperature_realistic
      expr: "max(T) < 100 and min(T) > 250"  # 250K-100°C
      reason: "排除数值爆炸"
    - id: soc_bounded
      expr: "0 <= SOC <= 1"

# === L3: 数值指标 (用户定义) ===
numeric_criteria:
  - id: capacity_retention
    description: "1C 放电容量 / 名义容量"
    expr: "abs(timeint(0,t_end,I_app_var))/3600 / Q_nom"
    bound: ">= 0.90"
    unit: ""  # 无量纲
    severity: hard      # hard / soft
                        #   hard = 必须通过,失败则继续 debug
                        #   soft = 警告,不影响 pass/fail

  - id: min_voltage
    description: "最低端电压不低于截止电压"
    expr: "min(liion.E_cell)"
    bound: ">= 2.5"
    unit: "V"
    severity: hard

  - id: max_temperature
    description: "电芯最高温度"
    expr: "max(T) - 273.15"
    bound: "<= 60"
    unit: "degC"
    severity: hard

  - id: max_temperature_rise
    description: "整体温升"
    expr: "max(T) - min(T)"
    bound: "<= 15"
    unit: "K"
    severity: soft  # 不影响 pass,只警告

# === L4: 实验数据对标 (可选) ===
experimental_reference:
  enabled: true
  references:
    - id: discharge_1C_25C
      description: "1C 放电曲线 @ 25°C 实测"
      file: "experiments/cell_LFP_280Ah_1C_25C.csv"
      file_columns: [time_s, voltage_V]      # CSV的列名
      sim_columns: [time, "liion.E_cell"]   # 仿真输出对应字段
      sim_export: "voltage_vs_time.csv"     # 仿真侧导出文件
      metric: RMSE                           # RMSE | MAE | MAPE | R2 | max_dev
      threshold: 0.05                        # 0.05 V
      unit: V
      align_method: "time_match"             # time_match | dtw | interp
      severity: hard

  # 多条件加权(可选,如果有多条实验曲线)
  weighted_score:
    enabled: false
    weights:
      discharge_1C_25C: 0.5
      discharge_2C_25C: 0.3
      discharge_1C_45C: 0.2
    overall_threshold: 0.06

# === Debug 时优先级 ===
priority_when_failing:
  # 同时多项失败时,先调哪个
  - max_temperature  # 安全相关,最优先
  - min_voltage      # 物理合理
  - capacity_retention
  - discharge_1C_25C # 实验对标
```

---

## 字段详解

### `meta`
- `task`: 任务描述,会出现在报告标题
- `max_iterations`: debug 整体循环最大次数 (默认 8)
- `max_wall_clock_minutes`: 总耗时上限 (默认 120 分钟)

### `physical_sanity`
内置物理合理性规则,**始终启用**(可关闭)。规则覆盖最常见的"数值爆炸/参数异常"。

| 内置规则 | 含义 |
|---|---|
| `voltage_in_window` | 终止时电压不越界 |
| `positive_capacity` | 容量为正 |
| `temperature_realistic` | 温度不会爆炸到非物理 |
| `soc_bounded` | SOC ∈ [0, 1] |

### `numeric_criteria` (核心)

每条规则字段:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 唯一标识 |
| `description` | string | ✓ | 人类可读描述 |
| `expr` | string | ✓ | COMSOL 表达式,会在 .mph 上 evaluate |
| `bound` | string | ✓ | 比较运算符 + 数值: `>= 0.9` / `<= 60` / `== 280` / `in [270, 290]` |
| `unit` | string | ✓ | 单位 (V/K/Ah/etc),`""` 表示无量纲 |
| `severity` | enum | ✓ | `hard`(影响pass) 或 `soft`(只警告) |

**支持的 `bound` 语法**:
- `>= 2.5`, `> 2.5`, `<= 60`, `< 60`, `== 280`, `!= 0`
- 区间: `in [270, 290]` (闭区间), `in (270, 290)` (开区间)
- 容差: `≈ 280 ± 5` (在 [275, 285] 内)

### `experimental_reference` (实验对标)

| 字段 | 说明 |
|---|---|
| `file` | 实验 CSV 路径 (相对工作目录) |
| `file_columns` | 实验 CSV 的列名 |
| `sim_columns` | 仿真侧对应字段(time + 一个或多个变量) |
| `sim_export` | 仿真侧导出的 CSV(若 .java 没自动导出,AI 会加导出代码) |
| `metric` | 比较指标 |
| `threshold` | 指标阈值 |
| `align_method` | 时间轴对齐方式 |

**支持的 `metric`**:

| Metric | 公式 | 适用 |
|---|---|---|
| `RMSE` | √(Σ(sim-exp)²/n) | 默认,平衡偏差 |
| `MAE` | Σ|sim-exp|/n | 关注平均偏差 |
| `MAPE` | Σ|sim-exp|/exp/n × 100% | 关注相对偏差 |
| `R2` | 1 - Σ(sim-exp)²/Σ(exp-mean)² | 关注相关性 |
| `max_dev` | max|sim-exp| | 关注最大偏差点 |

**阈值判定方向**:
- `R2`: `score >= threshold` 判通过(越大越好)
- 其他指标 (`RMSE`/`MAE`/`MAPE`/`max_dev`): `score <= threshold` 判通过(越小越好)

**align_method**:
- `time_match`: 仿真和实验时间步一致(罕见,需手动对齐)
- `interp`: 把仿真插值到实验时间点 (推荐,默认)
- `dtw`: Dynamic Time Warping (有相位偏差时用,比如实验有滞后)

### `priority_when_failing`

多项失败时调参顺序。按物理直觉:**安全 > 收敛 > 容量 > 实验拟合**。

---

## 三个典型场景的 acceptance.yaml 模板

### 场景1: 简单单点验证 (CC 1C 放电)

```yaml
meta:
  task: "LFP 280Ah 1C 放电基线"
  max_iterations: 6

numeric_criteria:
  - id: capacity
    description: "放电容量 (Ah)"
    expr: "abs(timeint(0,t_end,I_app_var))/3600"
    bound: ">= 270"
    unit: Ah
    severity: hard
  - id: min_voltage
    expr: "min(liion.E_cell)"
    bound: ">= 2.5"
    unit: V
    severity: hard
  - id: max_temp
    expr: "max(T) - 273.15"
    bound: "<= 50"
    unit: degC
    severity: hard
```

### 场景2: 多倍率拟合实验

```yaml
meta:
  task: "LFP 280Ah 多倍率放电曲线拟合实验"
  max_iterations: 10

# 不设单点指标,只看拟合质量
experimental_reference:
  enabled: true
  references:
    - id: rate_0_5C
      file: experiments/dchg_0.5C.csv
      file_columns: [time_s, voltage_V]
      sim_columns: [time, "liion.E_cell"]
      sim_export: "v_0.5C.csv"
      metric: RMSE
      threshold: 0.03
      unit: V
      severity: hard
    - id: rate_1C
      file: experiments/dchg_1C.csv
      file_columns: [time_s, voltage_V]
      sim_columns: [time, "liion.E_cell"]
      sim_export: "v_1C.csv"
      metric: RMSE
      threshold: 0.04
      unit: V
      severity: hard
    - id: rate_2C
      file: experiments/dchg_2C.csv
      file_columns: [time_s, voltage_V]
      sim_columns: [time, "liion.E_cell"]
      sim_export: "v_2C.csv"
      metric: RMSE
      threshold: 0.06    # 高倍率拟合放宽
      unit: V
      severity: hard
  weighted_score:
    enabled: true
    weights:
      rate_0_5C: 0.4
      rate_1C: 0.4
      rate_2C: 0.2
    overall_threshold: 0.045
```

### 场景3: 储能 CP 工况 + 温度

```yaml
meta:
  task: "LFP 280Ah CP 1P 放电 + 强制风冷"
  max_iterations: 8

numeric_criteria:
  - id: discharge_time
    description: "1P放电时长应接近 1h"
    expr: "t_end"  # Stop Condition 触发时间
    bound: "in [3300, 3900]"  # ±10%
    unit: s
    severity: hard
  - id: max_temp
    expr: "max(T) - 273.15"
    bound: "<= 45"
    unit: degC
    severity: hard
  - id: avg_efficiency
    description: "能量效率 = 放电能量 / (P_app × t)"
    expr: "timeint(0,t_end,liion.E_cell*I_app_var)/(P_app*t_end)"
    bound: ">= 0.95"
    severity: soft  # 仅警告

experimental_reference:
  enabled: false  # CP 工况通常没有现成实验数据对标
```

---

## 验收检查算法

AI 在 STEP E 执行:

```python
def check_acceptance(metrics: dict, criteria: dict) -> dict:
    results = {"all_passed": True, "failed_items": [], "warnings": []}

    # L2: 物理合理性
    for rule in criteria.get("physical_sanity", {}).get("rules", []):
        passed = evaluate_expr(rule["expr"], metrics)
        if not passed:
            results["all_passed"] = False
            results["failed_items"].append({
                "type": "physical_sanity",
                "id": rule["id"],
                "expected": rule["expr"]
            })

    # L3: 数值指标
    for crit in criteria.get("numeric_criteria", []):
        actual = evaluate_expr(crit["expr"], metrics)
        passed = check_bound(actual, crit["bound"])
        item = {
            "type": "numeric",
            "id": crit["id"],
            "actual": actual,
            "bound": crit["bound"],
            "unit": crit["unit"],
            "passed": passed
        }
        if not passed:
            if crit["severity"] == "hard":
                results["all_passed"] = False
                results["failed_items"].append(item)
            else:
                results["warnings"].append(item)

    # L4: 实验对标
    for ref in criteria.get("experimental_reference", {}).get("references", []):
        score = compute_metric(
            sim_csv=ref["sim_export"],
            exp_csv=ref["file"],
            metric=ref["metric"],
            align=ref["align_method"]
        )
        if ref["metric"] == "R2":
            passed = score >= ref["threshold"]   # R2 越大越好
        else:
            passed = score <= ref["threshold"]   # 误差类越小越好
        item = {
            "type": "experimental",
            "id": ref["id"],
            "metric": ref["metric"],
            "score": score,
            "threshold": ref["threshold"],
            "unit": ref["unit"],
            "passed": passed
        }
        if not passed:
            if ref["severity"] == "hard":
                results["all_passed"] = False
                results["failed_items"].append(item)
            else:
                results["warnings"].append(item)

    return results
```

`weighted_score.enabled=true` 时,会按 `weights` 对各 reference 分数做加权平均,
再用 `overall_threshold` 做最终判定。

完整实现见 `examples/scripts/comsol_batch_runner.py` 的 `check_acceptance()` 函数。

---

## 用户提供 acceptance.yaml 的引导话术

如果用户在 STEP A 没主动给 acceptance.yaml,AI 应该这样引导:

> 我需要先和你对齐验收条件,这决定我什么时候停止 debug。请回答:
>
> 1. **数值指标**: 这个模型最重要的输出指标是什么? 比如:
>    - 放电容量 (≥多少 Ah)?
>    - 最高温度 (≤多少 °C)?
>    - 端电压 (≥多少 V)?
>    - 能量效率 / 时长 / ...
>
> 2. **实验对标** (如有): 你有实测数据 CSV 吗? 比如 1C 放电曲线?
>    - 文件路径?
>    - 列名 (time_s, voltage_V)?
>    - 可接受的 RMSE 阈值?
>
> 3. **优先级**: 如果有矛盾(比如温度低但容量也低),优先保哪个?

收到答案后,AI 自动生成 acceptance.yaml,把每条都列给用户确认。

---

## 边界情况

### 没有实验数据时
跳过 L4,只用 L1+L2+L3。AI 会在报告中标注"未对标实验"。

### 没有具体数值指标时
退化到 L1+L2:只要求"求解能跑通 + 物理合理"。AI 会在 STEP A 警告:"无明确指标,我只能保证基本合理性,无法判断模型是否达到您的工程目标"。

### 验收不通过且无法 debug 时
达到 `max_iterations` 仍不通过 → AI 停止,生成报告记录全部失败 case + 已尝试的调参 + 建议:
- 哪些参数还可以试 (但超过预算)
- 是否需要用户介入(如校准 OCV、提供更多实验数据)
- 是否可能是验收条件本身过严
