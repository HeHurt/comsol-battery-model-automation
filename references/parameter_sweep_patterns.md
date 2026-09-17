# COMSOL Java 参数扫描片段模式 (LFP/Gr · 6.4)

本文档面向**LFP/石墨电芯**(储能场景)的P2D + 热模型参数扫描。涵盖CC/CP两种工况，并对比`.java`粘贴 vs MATLAB LiveLink两种执行路径。

> MATLAB LiveLink 驱动的扫描请转交 `comsol-livelink-matlab` skill。本文档只覆盖 `.java` 路径。

## 基本结构

COMSOL参数扫描是Study下的`Parametric` feature：

```java
// 假设 std1 已存在,新加扫描
model.study("std1").create("param", "Parametric");
model.study("std1").feature("param").set("pname",    new String[]{"Crate"});
model.study("std1").feature("param").set("plistarr", new String[]{"0.5 1 2 3"});
model.study("std1").feature("param").set("punit",    new String[]{""});
```

| 属性 | 类型 | 说明 |
|---|---|---|
| `pname` | `String[]` | 参数名数组，对应`model.param()`中已定义的参数 |
| `plistarr` | `String[]` | 每个参数对应一个空格分隔的值列表字符串 |
| `punit` | `String[]` | 单位数组，无量纲用`""` (6.4严格化,务必显式) |
| `sweeptype` | `String` | `"filled"`(配对) 或 `"specified"`(笛卡尔积) |

> ⚠️ `plistarr`是`String[]`不是`double[]` — 每个参数的所有值是**一个字符串**(空格分隔)。

## 模式1: 单参数 CC扫描

```java
// 扫描C倍率
model.study("std1").feature("param").set("pname",    new String[]{"Crate"});
model.study("std1").feature("param").set("plistarr", new String[]{"0.2 0.5 1 2 3"});
model.study("std1").feature("param").set("punit",    new String[]{""});
```

LFP储能典型范围：0.1C-3C(项目侧通常0.25C-1C，2C以上是测试边界)。

## 模式2: 单参数 CP扫描 (储能核心)

```java
// 扫描功率,前提是模型已配置CP的Global Equation (见 liion_lfp_reference.md)
model.study("std1").feature("param").set("pname",    new String[]{"P_app"});
model.study("std1").feature("param").set("plistarr", new String[]{"140 280 560 840 1120"});  // 0.25/0.5/1/1.5/2P
model.study("std1").feature("param").set("punit",    new String[]{"W"});
```

**重要**：CP扫描务必加Stop Condition，否则接近V_min时I=P/V→∞会发散：
```java
model.study("std1").feature("time").set("usestopcond", true);
model.study("std1").feature("time").set("stopcond",
  "(comp1.liion.E_cell<V_min)||(comp1.liion.E_cell>V_max)");
model.study("std1").feature("time").set("stopcondterminateon", "anytrue");
```

## 模式3: 范围语法

`plistarr`接受`range(start, step, stop)`：
```java
// 温度从-10°C到60°C,每10°C
model.study("std1").feature("param").set("pname",    new String[]{"T_amb"});
model.study("std1").feature("param").set("plistarr", new String[]{"range(263.15,10,333.15)"});
model.study("std1").feature("param").set("punit",    new String[]{"K"});
```

`range()`包含端点(如果可达)。

## 模式4: 多参数 `filled` (配对/DOE)

每行参数取自对应列。所有`plistarr`长度必须一致。

```java
// 4个测试点: (0.5P, 5°C), (1P, 25°C), (2P, 25°C), (1P, 45°C)
model.study("std1").feature("param").set("pname",    new String[]{"P_app", "T_amb"});
model.study("std1").feature("param").set("plistarr", new String[]{"280 560 1120 560", "278.15 298.15 298.15 318.15"});
model.study("std1").feature("param").set("punit",    new String[]{"W", "K"});
model.study("std1").feature("param").set("sweeptype", "filled");
```

适合从外部DOE工具(JMP/Minitab/`pyDOE`)导入的特定测试矩阵。

## 模式5: 多参数 `specified` (笛卡尔积)

```java
// 5 × 4 = 20 个case
model.study("std1").feature("param").set("pname",    new String[]{"P_app", "T_amb"});
model.study("std1").feature("param").set("plistarr", new String[]{"140 280 560 840 1120", "263.15 283.15 298.15 318.15"});
model.study("std1").feature("param").set("punit",    new String[]{"W", "K"});
model.study("std1").feature("param").set("sweeptype", "specified");
```

⚠️ 笛卡尔积爆炸快: 3参数×5水平 = 125次求解。

## 模式6: 新建独立Study做扫描

如果不想动`std1`，新建`std2`：

```java
model.study().create("std2", "Study");
model.study("std2").create("time", "Transient");

// 沿用 std1 的求解时间设置
model.study("std2").feature("time").set("tlist", "range(0,10,3600)");
model.study("std2").feature("time").set("usertol", true);
model.study("std2").feature("time").set("rtol", "1e-4");
model.study("std2").feature("time").set("activate", new String[]{"liion", "on", "ht", "on"});

// 加扫描
model.study("std2").create("param", "Parametric");
model.study("std2").feature("param").set("pname",    new String[]{"Crate"});
model.study("std2").feature("param").set("plistarr", new String[]{"0.5 1 2"});
model.study("std2").feature("param").set("punit",    new String[]{""});
```

## 后处理: 扫描结果导出CSV

扫描后最实用的操作是把每case的关键指标导出供Python/MATLAB分析。

```java
// === 1. 创建Table容器 ===
model.result().table().create("tbl1", "Table");

// === 2. 全局评估 (每case一个标量) ===
model.result().numerical().create("gev1", "EvalGlobal");
model.result().numerical("gev1").set("data", "dset2");           // 关键:用扫描的Dataset
model.result().numerical("gev1").set("expr", new String[]{
  "min(liion.E_cell)",              // 最低端电压
  "max(T)",                         // 最高温度
  "max(T)-min(T)",                  // 最大温差
  "I_app_var",                      // (CP模式时) 当前电流
  "timeint(0,t_end,abs(I_app_var))" // (CP模式时) 累积电荷量,可换算容量
});
model.result().numerical("gev1").set("descr", new String[]{
  "Min cell voltage",
  "Max temperature",
  "Max delta T",
  "Current (CP)",
  "Charge throughput"
});
model.result().numerical("gev1").set("unit", new String[]{"V", "K", "K", "A", "C"});
model.result().numerical("gev1").set("table", "tbl1");
model.result().numerical("gev1").setResult();

// === 3. 导出Table到CSV ===
model.result().export().create("tblexp1", "Table");
model.result().export("tblexp1").set("table", "tbl1");
model.result().export("tblexp1").set("filename", "D:\\sweep_out\\results.csv");
model.result().export("tblexp1").set("header", true);
model.result().export("tblexp1").run();
```

注意：
- `dset2`是扫描产生的Parametric Solutions — 实际tag从源文件grep `dataset()`确认
- `header: true`让CSV首行带列名（Python/MATLAB读取友好）
- LFP工况的合理性自检：最低电压不应低于`V_min=2.5V`，最高温度不应超过60-70°C(否则要核查冷却设置)

## 后处理: 时变曲线导出CSV (每case一条曲线)

```java
// 导出每case的电压-时间曲线 (注意:每case一个文件,或合并到一个Plot)
model.result().dataset().create("dset3", "ParametricSolutions");  // 通常自动建好
model.result().create("pg1", "PlotGroup1D");
model.result("pg1").create("ptgr1", "PointGraph");
model.result("pg1").feature("ptgr1").set("data", "dset2");
model.result("pg1").feature("ptgr1").set("expr", "liion.E_cell");
model.result("pg1").feature("ptgr1").selection().set(new int[]{<boundary_index>});

// 导出
model.result().export().create("plotexp1", "Plot");
model.result().export("plotexp1").set("plotgroup", "pg1");
model.result().export("plotexp1").set("filename", "D:\\sweep_out\\Ecell_t.csv");
model.result().export("plotexp1").run();
```

---

## 典型电池扫描场景速查

| 目标 | 扫描参数 | 典型范围(LFP) |
|---|---|---|
| 倍率特性(放电曲线族) | `Crate` | 0.1, 0.2, 0.5, 1, 2, 3 |
| 温度敏感性 | `T_amb` | 263.15 - 333.15 K |
| 储能功率特性 | `P_app` | 0.25P, 0.5P, 1P, 1.5P, 2P |
| 极片厚度优化 | `L_neg`, `L_pos` | 60-110e-6 m |
| LFP颗粒尺寸 | `rp_pos` | 0.1, 0.3, 0.5, 1 µm |
| 初始SOC敏感性 | `socinit_neg`, `socinit_pos` | 配对扫描(电荷守恒) |
| 对流换热(散热设计) | `h_amb` | 5, 10, 20, 50 W/(m²·K) |

## 批量运行(无GUI)

修改后保存`.java`，命令行编译运行：

```bash
# 编译.java为.mph
comsolcompile sweep_model.java

# 单机批量求解
comsolbatch -inputfile sweep_model.mph -outputfile sweep_solved.mph -batchlog sweep.log

# 集群并行
comsolbatch -nn 4 -np 4 -inputfile sweep_model.mph -outputfile sweep_solved.mph
#   -nn: 节点数  -np: 每节点核数
```

Windows典型路径：
```cmd
"C:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe" ^
  -inputfile "D:\models\sweep.mph" ^
  -outputfile "D:\models\sweep_solved.mph"
```

## Java vs LiveLink — 何时切换

| 你的情况 | 建议路径 |
|---|---|
| 团队规范要求改动写进`.mph`供他人复现 | **`.java`粘贴** |
| 集群批量跑(`comsolbatch`),关心吞吐 | **`.java`粘贴** + 提交`.mph` |
| 反复试错,参数频繁改 | **LiveLink** |
| 外层有优化算法(`fmincon`/`bayesopt`) | **LiveLink** |
| 扫描结果要直接进MATLAB/Python后处理 | **LiveLink** 或 `.java`+CSV导出都可 |
| 只关心给定一组参数的结果(无扫描) | 任选 |

切换路径**不影响模型本身** — 同一个`.mph`既能跑Java扫描也能跑LiveLink。

## 常见错误及修正

| 错误现象 | 原因 | 修正 |
|---|---|---|
| `Cannot create feature 'param': already exists` | Study已有param feature | 删除`.create()`,直接`.set()` |
| `Parameter 'Crate' is not defined` | 扫描参数没在`model.param()`中定义 | 先加`model.param().set("Crate","1","...")` |
| `Inconsistent array lengths` (filled模式) | 两个`plistarr`元素长度不一致 | 数空格分隔的值数量,补齐 |
| 求解时间爆炸 | `specified`模式参数水平过多 | 改`filled`,或减少水平数 |
| 结果为空/NaN | 物理场没在Step中`activate` | 检查Step的`activate`数组包含`liion`,`ht` |
| 导出CSV列名乱码 | Windows默认GBK | Python读时`encoding='gbk'`,或COMSOL启动加`-Dfile.encoding=UTF-8` |
| CP扫描部分case求解失败 | I_app_var初值偏差大 | 把`initialValueU`改为`P_app/3.2[V]` (LFP平台电压) |
| 后处理Table为空 | 没指定data="dset2" | `model.result().numerical("gev1").set("data","dset2")` |
| LFP扫描在低SOC段不收敛 | OCV平台导致dV/dSOC→0 | 减小`reltol`到1e-5,或用Backward Euler |

---

## 附录: 对比两个 `.java` 找差异 (跨参数扫描批次)

参数扫描的副产品之一是产生多个`.java`版本(每次扫描配置不同)。要快速看清两版差异:

### 标准流程

```bash
# 用git colored diff
git diff --no-index --color=always v1.java v2.java | less -R

# 或纯文本输出
diff -u v1.java v2.java > /tmp/diff.txt
```

把diff喂给AI,要求按5类分类:
1. **参数变化** (`model.param().set`)
2. **物理场变化** (`physics()`)
3. **几何变化** (`geom()`)
4. **Study/Solver变化** (`study()` / `sol()`)
5. **后处理变化** (`result()`)

详细的diff场景模板和"物理意义解读"输出格式 → 见 `team_workflow.md` "对比两个 `.java` 找差异"章节。
