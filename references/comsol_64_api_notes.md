# COMSOL 6.4 API 注意事项

本文档记录COMSOL 6.4在Java API层面与早期版本(5.6/6.0/6.1/6.2)的差异，避免AI生成代码时套用过时的属性键。

## 版本判断 — 从.java文件辨认

```bash
# COMSOL会在文件顶部注释中标注版本
head -5 source.java
# 典型: // Compiled with COMSOL Multiphysics 6.4 (Build: XXX)

# 或检查imports中的版本痕迹(通常没有,但有些自定义classpath会暴露)
grep -E 'comsol.*6\.' source.java
```

如果没有显式标注，可以通过几个**版本特征API**间接判断：

| 特征 | 5.6 | 6.0-6.1 | 6.2-6.3 | **6.4** |
|---|---|---|---|---|
| 主开路电位属性键 | `Ee` | `Eeq` | `Eeq` | `Eeq` |
| 创建Battery物理场 | `liionbattery` | `liion` | `liion` | `liion` |
| ModelInputs设置 | `.set("minput_temperature", ...)` | `.prop("ModelInputs").set(...)` | `.prop("ModelInputs").set(...)` | `.prop("ModelInputs").set(...)` |
| 默认网格特征 | `ftri` | `ftri`+`free` | `free`系列 | `free`系列 |
| Result Dataset类型 | `Solution` | `Solution`+`Parametric` | `Solution`+`Parametric`+`SolutionSet` | `Solution`+`Parametric`+`SolutionSet` |

**6.4与6.2/6.3差异不大**，主要是bug fix和性能优化。生成代码时按6.2+约定即可。

## 6.4 中需要注意的几个细节

### 1. liion物理场创建

```java
// 6.4标准写法
model.component("comp1").physics().create("liion", "LithiumIonBattery", "geom1");
```

**不要**用5.x的`"liionbattery"`类型名 — 6.x统一改为`"LithiumIonBattery"`。

### 2. ModelInputs必须通过`prop("ModelInputs")`访问

```java
// ✅ 6.4正确
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature_src", "userdef");
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature", "ht.T");

// ❌ 5.x旧写法 — 6.4里报错
model.component("comp1").physics("liion")
  .set("minput_temperature", "ht.T");
```

### 3. ElectrochemicalHeating耦合的几何维度参数

```java
// 6.4: 第三个参数 -1 表示全维度,会自动适应1D/2D/3D
model.component("comp1").multiphysics().create("emh1", "ElectrochemicalHeating", -1);

// 某些版本(5.x)需要显式指定维度,如 2
// 6.x统一用 -1
```

### 4. Parameter Sweep的`punit`必须显式

```java
// ✅ 6.4
model.study("std1").feature("param").set("punit", new String[]{"A"});

// 早期版本可省略,6.4严格化,省略会warning或解析为空
```

### 5. 后处理: Dataset选择

参数扫描会产生`ParametricSolutions`数据集（通常tag为`dset2`，原始解为`dset1`）。6.4中Global Evaluation等后处理要**显式指定data**：

```java
model.result().numerical("gev1").set("data", "dset2");  // 用扫描的Dataset
// 不指定的话,COMSOL会用默认数据集(可能是dset1单解),扫描结果取不到
```

### 6. Stop Condition新语法

```java
// 6.4
model.study("std1").feature("time").set("usestopcond", true);
model.study("std1").feature("time").set("stopcond",
  "(comp1.liion.E_cell<V_min)||(comp1.liion.E_cell>V_max)");
model.study("std1").feature("time").set("stopcondterminateon", "anytrue");
//   "anytrue" 任意一个条件满足就停 (扫描时每个case独立判断)
//   "alltrue" 所有条件都满足才停
```

### 7. Heat Source的Q vs Q0属性名

```java
// 6.4中,Heat Source的体热源属性键是 "Q0",不是 "Q"
model.component("comp2").physics("ht").feature("hs1").set("Q0", "comp1.aveop1(liion.Qh)");

// 早期版本可能用 "Q" — 注意区别
```

### 8. Time-Dependent Step的输出时间设置

```java
// 6.4: 用 tlist 字符串,空格分隔或range()
model.study("std1").feature("time").set("tlist", "range(0,10,3600)");
//   或
model.study("std1").feature("time").set("tlist", "0 10 20 30 ... 3600");
```

### 9. Function创建路径变化

```java
// 6.4: 函数通过 model.func() 创建,然后注册到全局或component
model.func().create("an_ocv_pos", "Analytic");
// 然后绑到component (某些情况)
// 早期版本可能写成 model.component("comp1").func()...
```

实际上6.4中`model.func()`(全局)和`model.component("comp1").func()`(组件级)都可用，**导出文件以COMSOL实际生成的为准**。

### 10. Material property group设置

```java
// 6.4: 材料属性按group组织
model.component("comp1").material("mat1").propertyGroup("def")
  .set("electrolyteconductivity", "sigma_l");
model.component("comp1").material("mat1").propertyGroup("def")
  .set("electrolytesalt_diffusivity", "Dl");

// 注意键名很长,不要简写
```

---

## 与5.x旧代码迁移checklist

如果源文件是5.x导出后没更新过，可能出现以下5.x残留(6.4中能跑但有deprecation warning)：

- `Ee` → 应改为 `Eeq`
- `set("minput_temperature", ...)` → 应套 `.prop("ModelInputs")`
- 物理场类型`"liionbattery"` → 应改为`"LithiumIonBattery"`

生成新片段时使用6.4写法，**不要为了"匹配源文件风格"用5.x旧API**。

---

## 6.4特有的Battery Design Module功能 (可选)

如果源文件用了以下feature，说明启用了6.4 Battery Design Module的高级功能：

- **Cycling Study** — 多圈循环study类型，专门处理充放电循环
- **Galvanostatic Charge/Discharge** — 替代手工配置CC step的标准feature
- **Cell Capacity Calculator** — 自动计算容量(避免手算)

```java
// 这些会出现在源文件中,作为研究类型标识
model.study("std1").create("cycle", "BatteryCycling");
```

遇到这些**不要试图重写为通用Time-Dependent + Global Equations** — 直接复用Battery模块的接口更稳。
