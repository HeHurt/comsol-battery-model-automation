# Lithium-Ion Battery (liion) — LFP/Graphite 参考 (COMSOL 6.4)

本文档专门面向**LFP正极 + 石墨负极**的P2D + 热耦合模型，列出节点结构、属性键、参数典型值，并重点覆盖**恒功率(CP)工况**的实现 — 这是储能场景的核心需求，且COMSOL无原生CP feature。

## liion 物理场典型节点树 (6.4)

```
liion  (Lithium-Ion Battery 主接口)
├── pce1   — Porous Electrode  (负极 Graphite)
│   └── pin1   — Particle Intercalation  (Gr颗粒嵌锂)
├── sep1   — Separator
├── pce2   — Porous Electrode  (正极 LFP)
│   └── pin2   — Particle Intercalation  (LFP颗粒嵌锂)
├── init1  — Initial Values
├── ein1   — Electric Ground  (负极集流体接地)
├── ecs1   — Electrode Current  (正极集流体)  ← CC模式
│   或 ecv1   — Electrode Potential          ← CV模式
└── (CP模式时见下方"恒功率(CP)实现")
```

## 关键节点属性 (6.4)

### Porous Electrode (`pce1` 负极Gr / `pce2` 正极LFP)

```java
// 负极 Graphite
model.component("comp1").physics("liion").feature("pce1")
  .set("epss", "epss_neg")        // 活性物质体积分数 0.55-0.65
  .set("epsl", "epsl_neg")        // 电解液体积分数 0.30-0.40
  .set("sigmas", "sigma_neg");    // 电子电导率 ~100 S/m

// 正极 LFP
model.component("comp1").physics("liion").feature("pce2")
  .set("epss", "epss_pos")        // 0.50-0.60
  .set("epsl", "epsl_pos")        // 0.25-0.35
  .set("sigmas", "sigma_pos");    // LFP本征电导率低,需碳包覆,~10-100 S/m
```

### Particle Intercalation (`pin1` Gr / `pin2` LFP)

```java
// 负极颗粒 Graphite
model.component("comp1").physics("liion").feature("pce1").feature("pin1")
  .set("rp", "rp_neg")            // 5-15 µm
  .set("Ds", "Ds_neg")            // 1e-14 ~ 5e-14 m²/s
  .set("k", "k_neg")              // 1e-11 ~ 1e-10 m/s
  .set("socinit", "socinit_neg")  // 充满态 ~0.85-0.95
  .set("csmax", "csmax_neg")      // 31370 mol/m³ (Gr理论值)
  .set("Eeq", "OCV_neg(soc)");    // 见下方OCV函数

// 正极颗粒 LFP
model.component("comp1").physics("liion").feature("pce2").feature("pin2")
  .set("rp", "rp_pos")            // 0.1-1 µm (LFP颗粒明显小于NCM)
  .set("Ds", "Ds_pos")            // 1e-18 ~ 1e-16 m²/s (LFP扩散慢)
  .set("k", "k_pos")              // 1e-11 ~ 5e-11 m/s
  .set("socinit", "socinit_pos")  // 充满态 ~0.05-0.15
  .set("csmax", "csmax_pos")      // 22806 mol/m³ (LFP理论值)
  .set("Eeq", "OCV_pos(soc)");
```

**LFP特殊性提醒**：
- LFP的OCV曲线是**平台型**(~3.4V平台占60%以上SOC范围)，与NCM的连续斜坡完全不同 — OCV函数务必用LFP实测数据，不要套NCM拟合公式
- LFP的`Ds_pos`比NCM低**2-3个数量级** — 倍率性能限制环节常常在LFP正极扩散
- LFP颗粒小(`rp_pos`~0.1-1µm)，对网格密度敏感

### Initial Values (`init1`)

```java
model.component("comp1").physics("liion").feature("init1")
  .set("cl", "cl_init")           // 电解液初始浓度 1000-1200 mol/m³
  .set("phis", "0[V]")            // 初始固相电位
  .set("phil", "0[V]");           // 初始液相电位
```

## ht 物理场 (Heat Transfer)

```java
// 对流换热边界
model.component("comp1").physics("ht").feature("hf1")
  .set("HeatFluxType", "ConvectiveHeatFlux")
  .set("h", "h_amb")               // 5-50 W/(m²·K)
  .set("Text", "T_amb");

// 初始温度
model.component("comp1").physics("ht").feature("init1")
  .set("Tinit", "T_amb");
```

## 多物理场耦合

```java
// 电化学发热 → 热源
model.component("comp1").multiphysics().create("emh1", "ElectrochemicalHeating", -1);
model.component("comp1").multiphysics("emh1").set("EcsInterface", "liion");
model.component("comp1").multiphysics("emh1").set("HeatTransferInterface", "ht");

// 温度反馈 → 电化学 (6.4中创建emh1后通常自动配置)
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature_src", "userdef");
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature", "ht.T");
```

---

## 恒流(CC)实现

最简单，直接用`ElectrodeCurrent` feature：

```java
// 6.4中ElectrodeCurrent的创建
model.component("comp1").physics("liion").create("ecs1", "ElectrodeCurrent", 0);
model.component("comp1").physics("liion").feature("ecs1")
  .selection().set(new int[]{<boundary_index>});  // 正极集流体边界

// 充电正、放电负 (与COMSOL默认约定一致)
model.component("comp1").physics("liion").feature("ecs1")
  .set("I_el", "I_app");

// 全局参数
model.param().set("I_app", "Crate*I_1C", "Applied current");
model.param().set("Crate", "1", "C-rate");
model.param().set("I_1C", "280[A]", "1C reference (e.g. 280Ah cell)");
```

---

## 恒功率(CP)实现

**COMSOL liion没有"ElectrodePower" feature**，必须通过**Global Equation**实现。原理：

> 让COMSOL自己解一个未知量`I_app`，使得约束方程 `I_app · E_cell - P_app = 0` 成立。
>
> `E_cell`是`liion.E_cell`（端电压），`P_app`是用户给定的功率。

### 实现模式（标准做法）

```java
// === Step 1: 参数 ===
model.param().set("P_app", "560[W]", "Applied power (放电正,充电负 — 注意符号约定与你的工况)");
model.param().set("V_max", "3.65[V]", "Cutoff voltage high");
model.param().set("V_min", "2.5[V]",  "Cutoff voltage low");

// === Step 2: Global Equation (核心) ===
// 在Component层添加Global Equations
model.component("comp1").physics().create("ge", "GlobalEquations", "geom1");

// 添加一个全局未知量 I_app
model.component("comp1").physics("ge").feature("ge1")
  .setIndex("name", "I_app_var", 0, 0)                  // 未知量名
  .setIndex("equation", "I_app_var*liion.E_cell-P_app", 0, 0)  // 约束方程: I*V = P
  .setIndex("initialValueU", "P_app/3.2[V]", 0, 0)      // 初值估计 (用LFP标称电压)
  .setIndex("initialValueUt", "0", 0, 0)                // 时间导数初值
  .setIndex("description", "Applied current (CP mode)", 0, 0)
  .setIndex("SIUnit", "A", 0, 0);

// === Step 3: 用 I_app_var 驱动ElectrodeCurrent ===
model.component("comp1").physics("liion").feature("ecs1")
  .set("I_el", "I_app_var");                            // ← 不是常数,是Global未知量

// === Step 4: Study Step 加截止条件 (Stop Condition) ===
// 在Time-Dependent Step下添加Events避免过充/过放
model.study("std1").feature("time").set("usestopcond", true);
model.study("std1").feature("time").set("stopcond",
  "(comp1.liion.E_cell<V_min)||(comp1.liion.E_cell>V_max)");
```

### CP实现的常见坑

| 现象 | 原因 | 修正 |
|---|---|---|
| 求解器报"Nonlinear solver did not converge" | `I_app_var`初值偏差太大 | 把`initialValueU`调整为接近真实工况的值,如`P_app/3.2[V]` |
| 接近截止电压时`I_app_var`爆炸 | `E_cell→0`时`I = P/V → ∞` | 必须加Stop Condition,否则发散 |
| 充放电符号混乱 | COMSOL默认正方向定义 | 在`P_app`的注释里明确"放电正/负",代码中保持一致 |
| 跨过LFP平台时收敛慢 | LFP的OCV平台导致dV/dSOC→0 | 减小`reltol`到1e-5,或换NDF求解器 |

### CP扫描功率

```java
// 扫描功率 (储能项目典型: 0.5P/1P/2P 等)
model.study("std1").feature("param").set("pname",    new String[]{"P_app"});
model.study("std1").feature("param").set("plistarr", new String[]{"280 560 1120"});  // 0.5/1/2 P (假设 1P=560W)
model.study("std1").feature("param").set("punit",    new String[]{"W"});
```

### CP + 温度二维扫描（储能DOE常见）

```java
model.study("std1").feature("param").set("pname",    new String[]{"P_app", "T_amb"});
model.study("std1").feature("param").set("plistarr", new String[]{"280 560 1120", "278.15 298.15 318.15"});
model.study("std1").feature("param").set("punit",    new String[]{"W", "K"});
model.study("std1").feature("param").set("sweeptype", "specified");  // 3×3 笛卡尔积
```

---

## LFP/Gr参数典型表 (280Ah储能电芯为参考)

| 含义 | 典型参数名 | 单位 | 典型值 | 备注 |
|---|---|---|---|---|
| 标称容量 | `Q_cell` | A·h | 280 | 储能主流 |
| 1C参考电流 | `I_1C` | A | 280 | = Q_cell/1h |
| 实际电流 | `I_app` | A | `Crate*I_1C` | CC用 |
| 实际功率 | `P_app` | W | `Prate*P_1C` | CP用 |
| 1P参考功率 | `P_1C` | W | ~560 | ≈ I_1C × V_nom (3.2V) |
| C倍率 | `Crate` | 1 | 0.1-3 | |
| P倍率 | `Prate` | 1 | 0.1-3 | |
| 环境温度 | `T_amb` | K | 298.15 | |
| 对流换热系数 | `h_amb` | W/(m²·K) | 5-20 | 自然对流~5,强制风冷~20-50 |
| 截止高压 | `V_max` | V | **3.65** | LFP **不要套NCM的4.2V** |
| 截止低压 | `V_min` | V | **2.5** | LFP |
| 标称电压 | `V_nom` | V | **3.2** | LFP平台电压 |
| 负极厚度 | `L_neg` | m | 70-90e-6 | |
| 隔膜厚度 | `L_sep` | m | 15-25e-6 | |
| 正极厚度 | `L_pos` | m | 80-110e-6 | LFP比能量低,正极常稍厚 |
| 负极颗粒半径 Gr | `rp_neg` | m | 5-15e-6 | |
| 正极颗粒半径 LFP | `rp_pos` | m | **0.1-1e-6** | 显著小于NCM |
| 负极活性物质分数 | `epss_neg` | 1 | 0.55-0.65 | |
| 正极活性物质分数 | `epss_pos` | 1 | 0.50-0.60 | |
| 负极电解液分数 | `epsl_neg` | 1 | 0.30-0.40 | |
| 正极电解液分数 | `epsl_pos` | 1 | 0.25-0.35 | |
| 隔膜电解液分数 | `epsl_sep` | 1 | 0.40-0.55 | |
| 负极固相扩散 Gr | `Ds_neg` | m²/s | 1e-14 - 5e-14 | |
| 正极固相扩散 LFP | `Ds_pos` | m²/s | **1e-18 - 1e-16** | 比NCM低2-3个数量级 |
| 负极反应速率 | `k_neg` | m/s | 1e-11 - 1e-10 | |
| 正极反应速率 | `k_pos` | m/s | 1e-11 - 5e-11 | |
| 电解液初始浓度 | `cl_init` | mol/m³ | 1000-1200 | |
| Gr理论最大浓度 | `csmax_neg` | mol/m³ | 31370 | |
| LFP理论最大浓度 | `csmax_pos` | mol/m³ | 22806 | |
| 负极初始SOC | `socinit_neg` | 1 | 0.85-0.95 | 充满态 |
| 正极初始SOC | `socinit_pos` | 1 | 0.05-0.15 | 充满态 |

**实际命名以源文件为准** — 本表是业内常见命名+LFP/Gr典型范围，用于数值合理性自检。

---

## SOC 端点标定 (socmin/socmax) — 必须用开路电压,不用端子截止电压

电池建模最常见的隐蔽错误:把充放电的**端子截止电压**(如充到 3.65V、放到 2.5V)当成 SOC=0/100% 的标定点。这是错的。

**铁律:`socmin/socmax`(或 `socinit`)必须用开路电压(OCV)标定,不是端子电压。**

- 端子电压 = OCV ± 极化(η)。充电 `V端子 = OCV + η`,放电 `V端子 = OCV − η`。
- LFP 满充**静置开路**就是 ~3.4–3.5V,**不可能到 3.65V**。3.65V 是 CC-CV 充电时被极化顶上去的端子电压。
- 全电池开路电压上限 = `OCP_pos(x_p) − OCP_neg(x_n)` 的可达范围。若拿一个超出该范围的端子电压去反解 SOC 端点,会逼出**非物理的负 stoichiometry**。

### 怎么正确反解 socmin/socmax

给定正负极 OCP 表 `OCP_pos(x_p)`、`OCP_neg(x_n)` 和正负极容量配平(决定 x_p↔x_n 的耦合斜率),沿充放电路径扫 SOC,令全电池开路 `OCV(SOC)=OCP_pos(x_p)−OCP_neg(x_n)` 等于**目标开路电压**(不是端子截止电压)求解:
- 0% SOC 端: 取该电芯实际的**放电静置开路下限**(LFP 常用 ~2.5V,已是底部陡降区);
- 100% SOC 端: 取**满充静置开路**(LFP ~3.45–3.50V),**不要填 CV 截止的 3.65V**。

### 自检清单(每次设 SOC 端点后)

1. 用 `socinit` 算初始开路电压,应与"该 SOC 静置实测电压"吻合(差<几十 mV)。
2. 充电仿真起点端子电压应**略高于** SOC=0 的开路;放电起点应**略低于** SOC=100% 的开路。不满足→端点或极化有问题。
3. **同一电芯的充电模型和放电模型,`socmin/socmax`、`csmax`、倍率、电压窗口、CC-CV 逻辑必须完全一致**,否则充放电容量不可比(常见症状:充入容量 ≠ 放出容量差好几个%)。
4. 记住正负极哪个是**限制电极**(`ah_pos_soc1` vs `ah_neg_soc1` 取小者定电芯容量;NP>1 时通常正极限制)。改 SOC 端点会改变可用容量,改完重新核对标称容量。

> 校准端点时，必须区分负载下端电压和开路电压。若用充电截止电压直接反解 `SOC=100%`后得到超出 `[0,1]` 的化学计量数，说明该截止电压不能作为开路端点。

---

## LFP OCV函数模板

LFP的OCV是**平台型**，不要套NCM的多项式拟合。推荐两种实现：

### 方式A: 用Analytic函数 (Sphan-Newman型经验拟合)

```java
// 创建一个Analytic函数 OCV_pos
model.func().create("an_ocv_pos", "Analytic");
model.func("an_ocv_pos").set("funcname", "OCV_pos");
model.func("an_ocv_pos").set("expr",
  "3.4323 - 0.8428*exp(-80.2493*(1-soc)^1.3198) " +
  "- 3.2474e-6*exp(20.2645*(1-soc)^3.8003) " +
  "+ 3.2482e-6*exp(20.2646*(1-soc)^3.7995)"
);
model.func("an_ocv_pos").set("args", new String[]{"soc"});
model.func("an_ocv_pos").set("argunit", "1");
model.func("an_ocv_pos").set("fununit", "V");
```

### 方式B: 用插值函数 (Interpolation) — 从CSV读实测OCV曲线

```java
// 从CSV文件加载 (列: SOC, OCV)
model.func().create("int_ocv_pos", "Interpolation");
model.func("int_ocv_pos").set("source", "file");
model.func("int_ocv_pos").set("filename", "D:\\models\\ocv_lfp.csv");
model.func("int_ocv_pos").set("funcs", new String[][]{{"OCV_pos", "1"}});
model.func("int_ocv_pos").set("interp", "piecewisecubic");
model.func("int_ocv_pos").set("extrap", "linear");
model.func("int_ocv_pos").set("argunit", "1");
model.func("int_ocv_pos").set("fununit", "V");
```

**方式B更推荐** — 直接用实测OCV数据，避免拟合误差，尤其是LFP平台两端的细节。

Gr负极OCV同理，函数名建议`OCV_neg`。

---

## 附录: 其他常用电池物理场接口 (简介)

本skill默认聚焦`liion` (P2D),但COMSOL 6.4还提供其他粒度的电池接口。遇到源文件用了这些时,知道是什么:

### LumpedBattery — 集总等效电路 (Pack级仿真)

整个电芯当成一个等效电路 (OCV + R0 + RC支路),不解多孔电极PDE。**适合Pack级、BMS算法验证**。

```java
model.component("comp1").physics().create("lb", "LumpedBattery", "geom1");
model.component("comp1").physics("lb").feature("lb1").set("E_OCV", "E_OCV(SOC)");
model.component("comp1").physics("lb").feature("lb1").set("R_0", "R0(SOC,T)");
model.component("comp1").physics("lb").feature("lb1").set("Q_cell", "Q_nom");
```

### SingleParticleBattery (`sib`) — 单粒子模型 (SPM)

每个电极用一个代表性颗粒表示,**比P2D快1-2个数量级,精度损失低倍率工况下可接受**。适合实时BMS、快速SOC/SOH估计、机器学习训练数据集。

```java
model.component("comp1").physics().create("sib", "SingleParticleBattery", "geom1");
model.component("comp1").physics("sib").feature("se1").set("c_s_max", "csmax_pos");
model.component("comp1").physics("sib").feature("se1").set("rp", "rp_pos");
model.component("comp1").physics("sib").feature("se1").set("Ds", "Ds_pos");
```

### 何时切换?

| 你的场景 | 推荐接口 |
|---|---|
| 电芯设计、极片优化、本质机制研究 | **liion (P2D)** ← 本skill默认 |
| Pack/模组集成、BMS算法、热管理设计 | LumpedBattery |
| 实时仿真、ML训练、快速SOC估计 | SingleParticleBattery (SPM) |
| 老化机制、SEI、锂沉积 | liion + 老化扩展 (本skill未覆盖) |

如果源文件用了非`liion`接口,grep `physics().create("(lb|sib|...)"` 识别,并参考COMSOL Battery Design Module文档对应章节的API。
