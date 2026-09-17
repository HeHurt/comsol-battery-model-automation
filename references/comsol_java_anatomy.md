# COMSOL Java文件结构详解

COMSOL导出的`.java`文件是一个单类，包含`run()`方法，按命令式顺序构建模型。理解整体结构是定位修改点和插入新代码的基础。

## 顶层骨架

```java
import com.comsol.model.*;
import com.comsol.model.util.*;

public class battery_p2d_thermal {

  public static Model run() {
    Model model = ModelUtil.create("Model");
    model.modelPath("C:\\path\\to\\dir");
    model.label("battery_p2d_thermal.mph");

    // ====== 所有建模语句 ======

    return model;
  }

  public static Model run2(Model model) {  // 有时存在,COMSOL自动切分大文件
    // ...
    return model;
  }

  public static void main(String[] args) {
    Model model = run();
    // run2(model);  // 若存在
  }
}
```

> 大模型导出时COMSOL会自动把`run()`拆成`run()`/`run2()`/`run3()`...，因为单个Java方法有64KB字节码限制。修改时注意你的目标节点在哪个`run`方法里。

## 段落顺序（严格按此顺序）

COMSOL Java文件的段落顺序是固定的（依赖关系决定）：

| 顺序 | 段落 | 典型识别行 |
|---|---|---|
| 1 | 模型创建 | `ModelUtil.create`, `modelPath`, `label`, `comments` |
| 2 | 参数 | `model.param().set(...)` |
| 3 | 函数(可选) | `model.func().create(...)` — 插值表,阶跃函数等 |
| 4 | 组件 | `model.component("comp1").create(...)` |
| 5 | 几何 | `model.component("comp1").geom("geom1").create(...)` + features |
| 6 | 变量 | `model.component("comp1").variable().create(...)` |
| 7 | 材料 | `model.component("comp1").material().create(...)` + property groups |
| 8 | 物理场 | `physics().create("liion", ...)`, `.create("ht", ...)` |
| 9 | 多物理场耦合 | `multiphysics().create("emh1", ...)` |
| 10 | 网格 | `mesh("mesh1").create(...)` |
| 11 | Study | `model.study().create("std1", ...)` |
| 12 | Solver | `model.sol().create("sol1", ...)` (自动生成,很长) |
| 13 | 结果/后处理 | `model.result().create(...)`, `.export(...)` |

## 快速定位段落（grep命令）

```bash
# 看所有参数
grep -n 'model\.param()\.set' source.java

# 看所有物理场接口
grep -nE 'physics\(\)\.create\("[a-z]+"' source.java

# 看所有多物理场耦合
grep -n 'multiphysics()\.create' source.java

# 看Study和Step
grep -nE 'model\.study\("[a-z0-9]+"\)\.(create|feature)' source.java

# 看材料属性
grep -nE 'material\("[a-z0-9]+"\)\.propertyGroup' source.java

# 看后处理导出
grep -nE 'result\(\)\.(export|numerical|dataset)' source.java
```

## Tag命名约定

每个COMSOL feature都有一个字符串tag，作为`.create()`的第一个参数。tag命名规律：

- **类型前缀 + 序号**: `comp1`, `geom1`, `liion`, `liion2`, `std1`, `std2`
- **首个实例可省略序号**: 物理场常为`liion`不是`liion1`（但其他类型如组件、几何通常带`1`）
- **节点tag同样有序号**: 如`pce1`(第一个多孔电极), `pce2`(第二个)
- **用户可改名但导出文件通常用默认**: 例外是Selection可能有语义名如`negSel`

引用方式：
```java
model.physics("liion")               // 通过tag访问物理场
.feature("pce1")                     // 通过tag访问其子节点
.feature("pin1")                     // 子节点的子节点
.set("rp", "rp_neg");                // 设置属性
```

## 易踩的坑

### 1. `set()` vs `setIndex()`
- `set(prop, value)`: 替换整个属性值
- `setIndex(prop, value, i)`: 替换数组属性的第i个元素（0-based）
- `setIndex(prop, value, i, j)`: 二维数组（如材料各向异性张量）

源文件用哪个 → 你也用哪个，**风格一致比简洁重要**。

### 2. String数组的写法
许多属性接受`String[]`，即使只有一个元素：
```java
.set("pname", new String[]{"I_app"})              // 单元素
.set("pname", new String[]{"I_app", "T_amb"})     // 多元素
```

### 3. 链式调用 vs 分行写法
两种等价：
```java
// 链式
model.component("comp1").physics("liion").feature("pce1").set("epss", "epss_neg");

// 拆开（COMSOL自动导出常用这种,便于阅读）
model.component("comp1").physics("liion").feature("pce1")
     .set("epss", "epss_neg");
```

跟着源文件的换行风格走。

### 4. 用户参数名 vs Tag名 — 完全两回事
- **参数名**（如`I_app`/`T_amb`）：在物理场属性、表达式中使用
- **Tag名**（如`param`/`std1`）：在Java API的`.feature()`/`.physics()`等调用中使用

两者不冲突，可以同名但混淆容易出错。

### 5. `prop("PropName")` 对应物理场属性页签
某些物理场属性挂在子属性页签下：
```java
// 不是 model.physics("liion").set("minput_temperature", "ht.T")
// 而是 model.physics("liion").prop("ModelInputs").set("minput_temperature", "ht.T")
model.component("comp1").physics("liion")
  .prop("ModelInputs").set("minput_temperature", "ht.T");
```

不确定时在源文件中grep`prop(`找类似设置作为参考。

## 阅读新文件的推荐顺序

1. **顶部**：找模型变量名、`label`（模型语义）
2. **参数段**：理解命名习惯（驼峰?下划线?）、单位风格
3. **物理场`create`**：确认是`liion` + `ht`还是别的（如`liionsp`单粒子）
4. **多物理场`create`**：确认热-电化学怎么耦合
5. **Study段**：理解既有study做什么（CC放电?CCCV?DST工况?）
6. **跳过Solver段**（除非要改求解器容差）
7. **Results段**：看后处理输出什么，新增输出时风格保持一致

## 文件大小的现实

- 小P2D模型：~3000–8000行
- P2D + 热 + 老化：~8000–20000行
- 模组级模型：可达50000行

GitHub Copilot读取大文件可能超出context窗口。**建议grep出关键段落后再让AI看**，而不是上传整个文件。
