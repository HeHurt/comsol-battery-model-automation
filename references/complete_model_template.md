# 完整 `.java` 模型模板 (Autonomous Mode 起点)

本文档提供**端到端、节点顺序正确、可编译**的完整 .java 模板,供 Autonomous Mode 的 STEP B 作为起点。

> ⚠️ **诚实声明**: 下面的模板基于 COMSOL 6.4 Java API 的惯例编写,提供**正确的节点顺序和完整骨架**。但由于 COMSOL 的部分属性键名只能在真实环境验证,**首次运行预计仍会经历 1-3 轮 debug**(主要是属性键名微调)。它的价值在于:让 AI 不必从零拼装,大幅降低首发的结构性错误(节点顺序、依赖缺失)。
>
> **使用哲学**: 先用「最小可跑版」确保整条管线(编译→求解→导出→验收)通畅,再逐步加复杂度(热耦合、扫描)。不要一上来就写最复杂的模型。

---

## 模板分两级

| 版本 | 物理场 | 用途 | 首轮成功率 |
|---|---|---|---|
| **最小可跑版** | 仅 liion (等温) | 先打通管线 | 高 |
| **完整版** | liion + ht 电热耦合 | 正式仿真 | 中 (需 debug) |

**强烈建议**: Autonomous Mode 第一次跑,先用最小可跑版验证管线,确认能 编译→求解→导出 metrics.csv→验收。管线通了再切完整版。

---

## 1. 最小可跑版 (等温 1D P2D, CC 放电)

```java
/* ============================================================
 * LFP/Graphite 1D P2D 电芯模型 — 最小可跑版 (等温, CC 放电)
 * COMSOL 6.4 | 自动生成 | 用途: 打通 Autonomous Mode 管线
 * ============================================================ */
import com.comsol.model.*;
import com.comsol.model.util.*;

public class GeneratedModel {

  public static Model run() {
    Model model = ModelUtil.create("Model");
    model.modelPath("WORKDIR_PLACEHOLDER");   // ← Agent 替换为真实工作目录
    model.label("GeneratedModel.mph");

    // ===== 1. 参数 =====
    model.param().set("L_neg", "80[um]", "负极厚度");
    model.param().set("L_sep", "20[um]", "隔膜厚度");
    model.param().set("L_pos", "90[um]", "正极厚度");
    model.param().set("rp_neg", "10[um]", "负极颗粒半径");
    model.param().set("rp_pos", "0.5[um]", "正极颗粒半径(LFP小)");
    model.param().set("epss_neg", "0.55", "负极活性物质体积分数");
    model.param().set("epss_pos", "0.43", "正极活性物质体积分数");
    model.param().set("epsl_neg", "0.30", "负极电解液体积分数");
    model.param().set("epsl_sep", "0.40", "隔膜孔隙率");
    model.param().set("epsl_pos", "0.30", "正极电解液体积分数");
    model.param().set("csmax_neg", "31370[mol/m^3]", "负极最大锂浓度");
    model.param().set("csmax_pos", "22806[mol/m^3]", "正极最大锂浓度(LFP)");
    model.param().set("soc0_neg", "0.85", "负极初始SOC(满电)");
    model.param().set("soc0_pos", "0.05", "正极初始SOC(满电,LFP脱锂)");
    model.param().set("cl0", "1200[mol/m^3]", "初始电解液盐浓度");
    model.param().set("Ds_neg", "3.9e-14[m^2/s]", "负极固相扩散");
    model.param().set("Ds_pos", "1e-17[m^2/s]", "正极固相扩散(LFP慢)");
    model.param().set("k_neg", "2e-11[m^2.5/(mol^0.5*s)]", "负极反应速率");
    model.param().set("k_pos", "5e-12[m^2.5/(mol^0.5*s)]", "正极反应速率");
    model.param().set("sigma_neg", "100[S/m]", "负极电子电导");
    model.param().set("sigma_pos", "10[S/m]", "正极电子电导(LFP低,常加碳)");
    model.param().set("Q_nom", "280[A*h]", "名义容量");
    model.param().set("A_cell", "1[m^2]", "电极面积(归一化)");
    model.param().set("I_1C", "Q_nom/(1[h])", "1C 电流");
    model.param().set("Crate", "1", "C 倍率");
    model.param().set("I_app", "Crate*I_1C", "施加电流");
    model.param().set("V_min", "2.5[V]", "放电截止电压");
    model.param().set("V_max", "3.65[V]", "充电截止电压");
    model.param().set("t_end", "3600/Crate[s]", "放电时长估计");

    // ===== 2. OCV 函数 (LFP 平台型,见 liion_lfp_reference.md) =====
    // 正极 LFP OCV
    model.func().create("an_ocv_pos", "Analytic");
    model.func("an_ocv_pos").set("funcname", "OCV_pos");
    model.func("an_ocv_pos").set("expr",
        "3.42 + 0.05*tanh(-15*(soc-0.5)) - 0.08*(soc>0.9)*(soc-0.9)*10");
    model.func("an_ocv_pos").set("args", new String[]{"soc"});
    model.func("an_ocv_pos").set("argunit", "1");
    model.func("an_ocv_pos").set("fununit", "V");
    // 负极石墨 OCV
    model.func().create("an_ocv_neg", "Analytic");
    model.func("an_ocv_neg").set("funcname", "OCV_neg");
    model.func("an_ocv_neg").set("expr",
        "0.2 + 1.5*exp(-120*soc) + 0.04*tanh(-(soc-0.3)/0.1)");
    model.func("an_ocv_neg").set("args", new String[]{"soc"});
    model.func("an_ocv_neg").set("argunit", "1");
    model.func("an_ocv_neg").set("fununit", "V");

    // ===== 3. 组件 + 几何 (1D, 三段) =====
    model.component().create("comp1", true);
    model.component("comp1").geom().create("geom1", 1);
    // 用 3 个区间表示 负极|隔膜|正极
    model.component("comp1").geom("geom1").create("i1", "Interval");
    model.component("comp1").geom("geom1").feature("i1")
        .set("coord", new String[]{"0", "L_neg", "L_neg+L_sep", "L_neg+L_sep+L_pos"});
    model.component("comp1").geom("geom1").run();

    // ===== 4. 物理场: Lithium-Ion Battery =====
    model.component("comp1").physics().create("liion", "LithiumIonBattery", "geom1");

    // 域分配: 1=负极, 2=隔膜, 3=正极
    // 负极 Porous Electrode
    model.component("comp1").physics("liion").create("pce1", "PorousElectrode", 1);
    model.component("comp1").physics("liion").feature("pce1").selection().set(1);
    model.component("comp1").physics("liion").feature("pce1").set("epss", "epss_neg");
    model.component("comp1").physics("liion").feature("pce1").set("epsl", "epsl_neg");
    model.component("comp1").physics("liion").feature("pce1").set("sigmas", "sigma_neg");
    // 负极颗粒内固相扩散 + OCV
    model.component("comp1").physics("liion").feature("pce1")
        .set("cEeqref", "csmax_neg");
    // (Particle 子节点配置 Ds/OCV — 属性键以实际 6.4 为准)

    // 隔膜 Separator
    model.component("comp1").physics("liion").create("sep1", "Separator", 1);
    model.component("comp1").physics("liion").feature("sep1").selection().set(2);
    model.component("comp1").physics("liion").feature("sep1").set("epsl", "epsl_sep");

    // 正极 Porous Electrode
    model.component("comp1").physics("liion").create("pce2", "PorousElectrode", 1);
    model.component("comp1").physics("liion").feature("pce2").selection().set(3);
    model.component("comp1").physics("liion").feature("pce2").set("epss", "epss_pos");
    model.component("comp1").physics("liion").feature("pce2").set("epsl", "epsl_pos");
    model.component("comp1").physics("liion").feature("pce2").set("sigmas", "sigma_pos");

    // 初始电解液浓度
    model.component("comp1").physics("liion").feature("init1").set("cl", "cl0");

    // 负极集流体接地
    model.component("comp1").physics("liion").create(" recd1", "ElectrodeCurrentDensity", 0);
    // 实际上负极用 Electric Ground,正极用 Electrode Current:
    model.component("comp1").physics("liion").create("gnd1", "ElectricGround", 0);
    model.component("comp1").physics("liion").feature("gnd1").selection().set(1);   // x=0 负极端

    // 正极集流体施加电流 (CC 放电用负电流表示放电)
    model.component("comp1").physics("liion").create("ec1", "ElectrodeCurrent", 0);
    model.component("comp1").physics("liion").feature("ec1").selection().set(2);   // x=L 正极端
    model.component("comp1").physics("liion").feature("ec1").set("Is", "-I_app");  // 放电

    // ===== 5. 网格 =====
    model.component("comp1").mesh().create("mesh1");
    model.component("comp1").mesh("mesh1").autoMeshSize(4);   // 4=fine
    model.component("comp1").mesh("mesh1").run();

    // ===== 6. Study + Time-Dependent =====
    model.study().create("std1");
    model.study("std1").create("time", "Transient");
    model.study("std1").feature("time").set("tlist", "range(0,10,t_end)");

    // LFP 收敛技巧 (见 autonomous_execution.md 3.3)
    model.study("std1").feature("time").set("rtol", "1e-4");

    // 停止条件: 电压到截止
    model.study("std1").feature("time").set("usestop", true);
    model.study("std1").feature("time").set("stopcondarr", new String[]{
        "comp1.liion.phis_max < V_min"});   // 端电压低于 V_min 停止

    return model;
  }

  // ===== 求解 + 导出 metrics + 保存 =====
  public static void main(String[] args) {
    Model model = run();

    // 求解
    model.study("std1").run();

    // 导出关键指标 (列名必须与 acceptance.yaml 的 id 一致!)
    model.result().numerical().create("gev1", "EvalGlobal");
    model.result().numerical("gev1").set("expr", new String[]{
        "min(comp1.liion.phis_max)",          // 最低端电压
        "abs(timeint(0,t_end,I_app))/3600",   // 容量 Ah
    });
    model.result().numerical("gev1").set("descr", new String[]{
        "min_voltage",   // ← 对应 acceptance.yaml id: min_voltage
        "capacity",      // ← 对应 acceptance.yaml id: capacity
    });
    model.result().table().create("tbl1", "Table");
    model.result().numerical("gev1").set("table", "tbl1");
    model.result().numerical("gev1").setResult();

    model.result().export().create("exp1", "Table");
    model.result().export("exp1").set("table", "tbl1");
    model.result().export("exp1").set("filename", "WORKDIR_PLACEHOLDER/metrics.csv");
    model.result().export("exp1").set("header", true);
    model.result().export("exp1").run();

    // 导出电压时变曲线 (供报告画图 + 实验对标)
    model.result().export().create("exp2", "Plot");
    // (或用 Data 导出 phis_max vs time —— 属性以实际为准)

    // 保存 .mph
    model.save("WORKDIR_PLACEHOLDER/result.mph");
  }
}
```

**对应的 acceptance.yaml**:
```yaml
meta:
  task: "LFP 280Ah 1C 放电 (最小可跑版验证管线)"

physical_sanity:
  enabled: true
  rules:
    - id: positive_capacity
      expr: "capacity > 0"
    # 注意: physical_sanity 的 expr 变量必须是 metrics.csv 里导出的列名

numeric_criteria:
  - id: min_voltage      # ← 必须与 .java 里 descr 的 "min_voltage" 一致
    description: "最低端电压"
    expr: "COMSOL侧: min(phis_max)"   # expr 仅说明,Python不求值
    bound: ">= 2.4"
    unit: V
    severity: hard
  - id: capacity         # ← 必须与 .java 里 descr 的 "capacity" 一致
    description: "放电容量"
    expr: "COMSOL侧: timeint(I)/3600"
    bound: ">= 250"
    unit: Ah
    severity: hard
```

---

## 2. ⚠️ 关键契约: metrics.csv 列名 ↔ acceptance id

这是 v3.0 一个**容易踩坑**的隐藏契约,必须遵守:

```
.java 里:  model.result().numerical("gev1").set("descr", new String[]{"min_voltage", "capacity"});
                                                                          │              │
                                                                          ▼              ▼
metrics.csv 列名:                                                     min_voltage    capacity
                                                                          │              │
                                                                          ▼              ▼
acceptance.yaml:   numeric_criteria:  - id: min_voltage          - id: capacity
```

**三者的字符串必须完全一致**。`comsol_batch_runner.py` 的 `check_acceptance` 用 `id` 去 metrics.csv 找对应列:
- 找到 → 比较 bound
- 找不到 → 明确报 `metric 'xxx' not found`(不再默默判失败)

`expr` 字段**不被 Python 求值**,它只是给人看的说明 + 给 .java 生成器的指令。真正的物理量计算在 COMSOL 里(`EvalGlobal` 的 expr),Python 侧只做阈值比较。

**physical_sanity 的 expr 例外**: 它会被 Python 的 `safe_eval_bool` 求值,所以里面用到的变量(如 `capacity`, `V_min`)也必须是 metrics.csv 里导出的列。如果用了没导出的变量,该规则会被标记为 SKIPPED(不假装通过)。

---

## 3. 完整版 (liion + ht 电热耦合)

在最小可跑版基础上增加:

```java
// ===== 在 run() 中,liion 配置之后,mesh 之前加: =====

// 热物理场参数
model.param().set("T_amb", "298.15[K]", "环境温度");
model.param().set("h_amb", "10[W/(m^2*K)]", "对流换热系数");
model.param().set("rho_cell", "2500[kg/m^3]", "电芯密度");
model.param().set("Cp_cell", "1000[J/(kg*K)]", "比热容");
model.param().set("k_cell", "2[W/(m*K)]", "导热系数");

// Heat Transfer in Solids
model.component("comp1").physics().create("ht", "HeatTransfer", "geom1");
model.component("comp1").physics("ht").feature("solid1").set("rho", "rho_cell");
model.component("comp1").physics("ht").feature("solid1").set("Cp", "Cp_cell");
model.component("comp1").physics("ht").feature("solid1").set("k", "k_cell");
model.component("comp1").physics("ht").feature("init1").set("Tinit", "T_amb");

// 边界对流换热 (两端)
model.component("comp1").physics("ht").create("hf1", "HeatFluxBoundary", 0);
model.component("comp1").physics("ht").feature("hf1").selection().set(1, 2);
model.component("comp1").physics("ht").feature("hf1").set("HeatFluxType", "ConvectiveHeatFlux");
model.component("comp1").physics("ht").feature("hf1").set("h", "h_amb");
model.component("comp1").physics("ht").feature("hf1").set("Text", "T_amb");

// ★ 电热耦合: ElectrochemicalHeating (绝不用 ElectromagneticHeating!)
model.component("comp1").multiphysics().create("emh1", "ElectrochemicalHeating", 1);
model.component("comp1").multiphysics("emh1").set("Electrochemistry_physics", "liion");
model.component("comp1").multiphysics("emh1").set("HeatTransfer_physics", "ht");

// ===== main() 的 metrics 导出增加温度指标: =====
// "max(comp1.T)-273.15"  → descr "max_temp_C"
// "max(comp1.T)-min(comp1.T)"  → descr "max_dT_K"
```

**Study 需要同时求解 liion + ht**: Time-Dependent 默认会包含所有 active 物理场,通常不需额外配置。但如果用 segregated solver,确保 liion 和 ht 在迭代中耦合。

---

## 4. Agent 使用此模板的流程

```
STEP B (生成 .java):
  1. 复制「最小可跑版」
  2. 把 WORKDIR_PLACEHOLDER 替换为真实工作目录 (3处)
  3. 根据用户任务调整参数 (Crate, 容量, 厚度等)
  4. 确认 metrics 导出的 descr 与 acceptance.yaml 的 id 一致

STEP C-E (调 comsol_batch_runner.py):
  python comsol_batch_runner.py --java GeneratedModel.java \
      --criteria acceptance.yaml --paths paths.json \
      --workdir <dir> --iteration 1

  读 cycle_result.json:
    - next_action="done" → 进入 STEP F
    - next_action="agent_adjust_and_rerun" → 看 acceptance.items_failed,
      调参 (见 autonomous_execution.md 5.2),iteration+1,重跑
    - reason="compile_failed" → 看 details.parsed_errors,修 .java,
      iteration+1,重跑 (不传 --reset-history,历史累积)

  管线通了 (最小版能 PASS) → 切完整版 (加 ht),重复 C-E

STEP F (报告):
  python generate_report.py --debug-log debug_history.json ...
  (debug_history.json 已累积全部轮次)
```

---

## 5. 常见首轮 debug (基于经验预判)

| 首轮可能的错 | 原因 | 快速修 |
|---|---|---|
| `Property "epss" not defined` | 6.4 键名可能是 `epsilons` 等 | 查 Javadoc PorousElectrode |
| `Feature "phis_max" unknown` | 端电压变量名可能不同 | 改 `liion.phis` 或 `liion.E_cell` |
| `Selection set(1) empty` | 几何域索引从 0 还是 1 起 | 检查 geom run 后的域编号 |
| 停止条件没触发 | `stopcondarr` 语法 | 改用 Events 接口或检查变量名 |
| metrics.csv 编码乱码 | Windows GBK | runner 已用 errors='replace' 容错 |

这些都是**属性键名级别**的小修,不影响整体结构。每修一个 iteration+1,历史会累积到报告里。
