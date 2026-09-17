# 1D P2D + 3D热模型多尺度耦合

本文档专门覆盖**1D电化学 + 3D热**的多尺度模型 — 储能大电芯(280Ah/314Ah)和小模组建模的主流方式。

## 为什么要1D+3D而不是纯3D

P2D电化学的求解维度是"穿过极片厚度"(几十到几百微米)，3D电芯壳体尺寸是几十到几百毫米 — **直接3D P2D网格量爆炸**(微米级网格 × 厘米级壳体 = 几百万自由度)。

工程上拆分：
- **1D P2D**：解电化学（极片厚度方向，~100µm尺度）→ 输出体热源`Qh`和端电压
- **3D ht**：解温度场（电芯整体几何，~mm-cm尺度）→ 输出温度场`T`
- **耦合**：1D的`Qh`映射到3D作为体热源；3D的`T`回馈1D作为温度输入

## 识别源文件是哪种耦合方式

```bash
# 找耦合算子
grep -nE 'create\("(genext|aveop|extrudedim|intop)[0-9]*"' source.java

# 找组件数量
grep -oE 'model\.component\("comp[0-9]+"\)\.create' source.java | sort -u
```

典型痕迹：
- 出现`comp1`和`comp2`两个组件 → 双组件方案（最常见）
- 出现`genext`(General Extrusion)或`aveop`(Average Operator) → 用算子耦合
- 出现`extrudedim`(Extra Dimension) → 用COMSOL Battery模块的内置多尺度

## 方案A: 双组件 + General Extrusion (最常见)

### 组件结构

```
model
├── comp1 (1D, geom1)
│   ├── liion (电化学)
│   ├── ht (1D方向温度,可选-通常只用comp2的T)
│   ├── 算子: genext1 (把comp1的Qh映射到comp2)
│   └── 算子: aveop1 (把1D方向的Qh平均成一个值,可选)
└── comp2 (3D, geom2)
    ├── ht (3D温度场)
    ├── 算子: genext2 (把comp2的T映射回comp1)
    └── 热源: Heat Source feature 用 comp1.genext1(liion.Qh)
```

### 关键代码模式

```java
// === 在 comp1 中创建 General Extrusion (1D → 3D方向) ===
model.component("comp1").cpl().create("genext1", "GeneralExtrusion");
model.component("comp1").cpl("genext1").selection().all();  // 1D所有域
// 关键: 设置目标(3D中要把1D的结果"广播"到哪些点)
model.component("comp1").cpl("genext1").set("dstmap", new String[]{"0", "0", "0"});
// 注意: 3D每个点都接收同一份1D解时,源映射是"自身坐标"

// === 在 comp1 中创建 Average Operator (将1D方向平均,如果需要) ===
model.component("comp1").cpl().create("aveop1", "Average");
model.component("comp1").cpl("aveop1").selection().all();
// 这样 aveop1(liion.Qh) 就是1D方向上Qh的体积平均(单位 W/m³)

// === 在 comp2 (3D热) 中添加 Heat Source 引用 comp1 的发热 ===
model.component("comp2").physics("ht").create("hs1", "HeatSource", 3);
model.component("comp2").physics("ht").feature("hs1").selection().all();
model.component("comp2").physics("ht").feature("hs1")
  .set("Q0", "comp1.aveop1(liion.Qh)");  // 跨组件引用

// === 在 comp2 中创建 General Extrusion (3D → 1D温度回馈) ===
model.component("comp2").cpl().create("genext2", "GeneralExtrusion");
model.component("comp2").cpl("genext2").selection().all();
// 通常映射的是体积平均温度 (整个电芯当一个集总热体)
// 或更精细: 多点采样,但电池尺度下通常温度梯度小,集总够用

// === 在 comp1 中,让 liion 的温度输入从 comp2 来 ===
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature_src", "userdef");
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature", "comp2.aveop2(T)");  // 或类似的算子
```

### 典型耦合的"双层平均"逻辑

```
   comp1 (1D, 微观)              comp2 (3D, 宏观)
   ┌────────────────┐              ┌────────────────┐
   │ liion.Qh(x)    │── aveop1 ──→ │ HeatSource (体平均) │
   │ (W/m³ 沿厚度)  │              │       ↓        │
   │                │              │   ht.T(x,y,z)  │
   │ liion入参 T ←──┤── aveop2 ────│ (3D温度场)    │
   │ (1D所有点取同一值) │             │                │
   └────────────────┘              └────────────────┘
```

这种"集总耦合"假设：电芯内部温度梯度小到可以视为均匀。对280Ah电芯+正常工况(<2C, 自然对流)通常成立；高倍率或强制液冷时不成立，需要更细的耦合。

## 方案B: Extra Dimension (COMSOL内置, Battery模块)

如果源文件用了`extrudedim`，那是COMSOL Battery Design Module的内置多尺度方式 — 它把1D粒子伪维度嵌入3D电芯几何，无需用户手动写算子。

```java
// 创建Extra Dimension的痕迹
model.component("comp1").mesh("mesh1").feature("xdim1");
// 物理场里有类似
model.component("comp1").physics("liion").feature("pin1").set("xdim_extr", "xdim1");
```

这种方案的修改片段：**直接改正常的`liion`节点属性即可**，COMSOL内部处理多尺度。不需要手写General Extrusion。

→ **识别**：grep `extrudedim` 或 `xdim` 关键字。

## 方案C: 边界耦合 (1D解嵌入3D边界)

某些模型把1D P2D解在3D的一个**边界**上（如电芯顶面）：

```java
// comp2 的一个边界上创建子geometry做1D P2D
// 通过 General Extrusion 把1D解从边界映射到3D体内
```

这种较少见，遇到时按General Extrusion方案理解。

---

## 修改多尺度模型时的注意事项

### 1. 修改参数 — 通常在 comp1 上
P2D参数都属于`comp1`：
```java
// LFP正极扩散系数 — 改comp1,不是comp2
model.component("comp1").physics("liion").feature("pce2").feature("pin2")
  .set("Ds", "Ds_pos_new");
```

### 2. 修改热边界 — 在 comp2 上
冷却条件、对流系数都属于3D的`comp2`：
```java
// 改电芯表面对流换热
model.component("comp2").physics("ht").feature("hf1")
  .set("h", "h_amb_new");
```

### 3. 跨组件引用语法
```
comp1.var_name   ← 从其他组件访问 comp1 中的变量/算子
comp1.aveop1(expr) ← 调用 comp1 中的算子,作用于 expr
```

### 4. 参数扫描在Study层加,与组件无关
```java
// 全局参数扫描不需要区分comp1/comp2
model.study("std1").feature("param").set("pname", new String[]{"Crate"});
```

但**导出**结果时要注意取自哪个组件：
```java
// 端电压: 1D电化学输出
model.result().numerical("gev1").set("expr", new String[]{"comp1.liion.E_cell"});

// 最高温度: 3D热场输出
model.result().numerical("gev1").set("expr", new String[]{"comp2.maxop1(T)"});
```

### 5. 网格独立设置
两个组件各自有mesh：
```java
model.component("comp1").mesh("mesh1");  // 1D网格,通常50-200单元
model.component("comp2").mesh("mesh2");  // 3D网格,根据几何复杂度
```

修改网格密度时**只动对应组件**。

---

## 双组件模型片段生成模板

```
**插入位置**: <comp1 或 comp2 中的哪个section>
**新建的tags**: <注意 comp1 和 comp2 的tag各自独立编号,如 comp1.gev1 与 comp2.gev1 互不冲突>
**依赖项**: <列出跨组件引用的算子,如 comp1.aveop1, comp2.genext2>
**风险点**: <跨组件引用是否正确;参数是全局还是某组件特有>

```java
// 明确标注每行属于哪个组件
model.component("comp1")...  // 1D电化学侧
model.component("comp2")...  // 3D热侧
```

**粘贴说明**: ...
```
