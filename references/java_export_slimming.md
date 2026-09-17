# `.java` 导出瘦身工作流

本文档解决一个高频痛点: **COMSOL导出的`.java`文件过大导致AI读取困难、消耗context窗口**。

## 问题症状

清空了解(Clear Solutions)后导出的`.java`仍然>5MB,甚至达到10-30MB。AI Agent读取一次就会占用大量context窗口,严重影响响应速度和成本。

**正常体积参考**:

| 模型类型 | 期望体积 | "异常"的信号 |
|---|---|---|
| 简单1D P2D电芯 | 50-200 KB | >1 MB |
| 1D P2D + 3D热 (多尺度) | 200 KB - 2 MB | >5 MB |
| 模组级3D | 1-5 MB | >20 MB |

如果你的清空解后的电芯模型`.java`是20MB,**几乎一定是"没删干净"**,不是物理复杂度造成的。

---

## 1. `.java` 体积构成与诊断

`.java`文件的体积由3类内容贡献,差异巨大:

| 内容 | 占比影响 | 是否对AI建模必要 |
|---|---|---|
| 建模操作 (param/geom/physics/mesh/study) | 通常50-500 KB | ✅ **必须** |
| 求解器内部状态 (`model.sol(...)`的详细feature配置) | 可达数MB | ⚠️ 部分(求解器逻辑可重新生成) |
| 嵌入数据 (插值表/材料库副本/网格快照) | 单项可达10+ MB | ❌ 通常不需要 |
| GUI操作历史/调试节点 (Probe/Cut Lines等) | 数MB | ❌ 不需要 |

### 诊断命令

在Linux/Mac/Windows Git Bash:

```bash
# 文件总大小
wc -c source.java

# 各section的语句数 (代码分布)
echo "param:"; grep -c "model.param" source.java
echo "geom:";  grep -c "model.component.*\.geom" source.java
echo "physics:"; grep -c "physics" source.java
echo "mesh:"; grep -c "mesh" source.java
echo "study:"; grep -c "model.study" source.java
echo "sol (求解器):"; grep -c "model.sol" source.java
echo "result:"; grep -c "model.result" source.java
echo "func (函数/插值表):"; grep -c "model.func" source.java

# 找单行最长的部分 (通常是嵌入数据)
awk '{ print length, NR, substr($0,1,80) }' source.java | sort -rn | head -20

# 看是否有大块插值数据
grep -n 'setIndex\|set("table"' source.java | head -20
```

或者用本skill的Python脚本一键诊断: `examples/scripts/analyze_java_size.py`

---

## 2. 五个常见的"没删干净"

### A. 求解器配置 (Solver Configurations) 没删

**最常见的体积大户**。Clear Solutions只清掉数值结果,**但保留Solver Configurations节点的全部配置**(几千行预条件子、step控制、segregated分组)。这部分对建模AI是噪音。

**删除方法**:
- COMSOL Desktop左侧Model Builder → **Study → Solver Configurations** → 右键 **Delete**
- AI读到的只剩Study Step定义,编译时COMSOL会自动重新生成`sol`节点

**代价**: 删除后模型不能直接`compile`运行,需要在COMSOL里 `Compute` 或 `Show Default Solver` 重新生成。这是用空间换便利。

**省下来的体积**: 通常3-15 MB → <100 KB

### B. 插值表/OCV数据嵌入到模型

如果你的OCV曲线、`Ds_pos(SOC,T)`等是通过`Interpolation`函数从CSV加载,**默认会把整个表的数据复制到`.mph`和`.java`里**(几千行`setIndex("table",...)`)。

**优化方法**:
- 在`Interpolation`函数设置里,**Data source** 改为 **File** (而不是 Local table)
- `.java`里只会写 `model.func("int1").set("filename", "ocv_lfp.csv")` 一行
- **代价**: 编译时CSV文件必须存在于指定路径

**省下来的体积**: 每个插值表通常省 0.5-5 MB

### C. 几何历史 / 网格快照

几何反复改过的模型会保留所有几何operations(`add`/`subtract`/`extrude`等)。网格如果`Build All`过,会嵌入网格数据。

**清理方法**:
- 几何节点 → 右键 → **Build All** → **Convert to Geometry Sequence** (把累积operations合并为最终形式)
- 网格: 不要在导出前做`Build All`,或者在导出选项中**关闭Include mesh**

**省下来的体积**: 0.5-5 MB

### D. Material Library 完整副本

从COMSOL Material Library拖入的`NCM811`/`Graphite`/`LiPF6_EC_EMC`等内置材料,`.java`里会**复制材料库的所有属性表**(每个材料几千行)。

**优化方法**:
- 不直接拖`MaterialsLib_NCM811`节点
- 自己建`mat1`,手动写需要的`propertyGroup("def").set("density", "rho_pos")`等几行

**省下来的体积**: 每个内置材料 0.5-2 MB

### E. Probe / 临时调试节点

`Probe`(探针)、`Cut Line`、`Cut Plane`、`Cut Point` 等调试节点都会写入`.java`。

**清理方法**:
- Model Builder → Results → Cut Lines/Planes/Probes → 删掉不用的
- 真正需要的Probe保留即可

**省下来的体积**: 通常 <500 KB,但行数贡献大

---

## 3. 导出选项推荐设置

`File → Save As → Model File for Java (*.java)` 弹窗,**这些选项很多人忽略**:

| 选项 | 推荐 | 原因 |
|---|---|---|
| Include comments | ✅ ON | AI阅读友好 |
| Compact history | ❌ OFF | 保留建模顺序 (Compact后丢失语义) |
| **Include geometry** | ❌ OFF (几何简单且参数化时) | 几何历史可能很大 |
| **Include mesh** | ❌ OFF | 网格快照是大头之一 |
| **Include solution** | ❌ OFF | 即使Clear过,某些state可能残留 |
| **Include functions data** | ❌ OFF | 插值表数据,改用file引用 |

⚠️ **关键**: 大部分用户只注意Compact history,**忽略Include mesh/solution/functions data这三个**。这三个加起来通常占文件体积的80%以上。

---

## 4. 分层管理策略 (推荐)

不要试图用一个`.java`满足所有需求。把模型导出成**两份**:

### 完整版 `cell_LFP_280Ah_v3_full.java` (归档用)
- 本地存,**不入git** (太大)
- 包含solution、mesh、interpolation data、Material Library
- 用途: 团队归档、复现实验、灾难恢复
- 体积: 10-30 MB可接受

### 精简版 `cell_LFP_280Ah_v3.java` (日常+AI用)
- **入git**,日常修改基础
- 删除Solver Configurations
- 删除Probes/Cut Lines/调试节点
- 插值表用文件引用
- 不勾`Include mesh/solution/functions data`
- 体积目标: **<500 KB,理想<200 KB**

工作流:

```
在COMSOL Desktop里:

1. 打开 cell_v3.mph
2. File → Save As: cell_v3_full.mph  ← 备份完整版
3. Clear Solutions (清空所有解)
4. Delete Solver Configurations
5. Delete Results下的 Probes/Cut Lines/Cut Planes/Cut Points (保留必要的)
6. 把所有 Interpolation 函数改为 file-based (Data source: File)
7. 检查 Materials 节点,删掉没用的内置材料,只留自定义的
8. File → Save As Java → cell_LFP_280Ah_v3.java
   ✅ Include comments
   ❌ Compact history
   ❌ Include geometry (如果几何参数化)
   ❌ Include mesh
   ❌ Include solution
   ❌ Include functions data
9. 关闭文件,不存到 cell_v3.mph (避免误覆盖)
10. git commit cell_LFP_280Ah_v3.java
```

可以做成团队wiki的导出checklist。

---

## 5. AI专用版 (终极瘦身)

如果上面做完`.java`还是>1MB,可以再用脚本剥离求解器section,生成**AI阅读专用版**(不能直接编译):

```bash
python examples/scripts/strip_java_for_ai.py cell_v3.java cell_v3_for_ai.java
# 输出: Original 800KB → Stripped 120KB (-85%)
```

脚本做的事:
- 识别 `model.sol(...)` 连续行块,替换为占位注释
- 可选: 剥离 Probes/Cut* 节点
- 可选: 剥离非常长的 setIndex 数据块

**这个版本只给AI读,不能编译**。明确在文件头加注释提醒。

**用途**:
- AI Agent的定向文件引用和上下文加载
- diff两个模型时减少噪音

详见 `examples/scripts/strip_java_for_ai.py` 的使用说明。

---

## 6. 验证瘦身效果

```bash
# 体积对比
echo "原始:  $(du -h cell_v3_full.java | cut -f1)"
echo "精简:  $(du -h cell_v3.java | cut -f1)"
echo "AI版:  $(du -h cell_v3_for_ai.java | cut -f1)"

# token估算 (粗略: 1字节 ≈ 0.25 token,代码可能更高)
python -c "
import os
for f in ['cell_v3_full.java', 'cell_v3.java', 'cell_v3_for_ai.java']:
    if os.path.exists(f):
        kb = os.path.getsize(f) / 1024
        tok = kb * 256  # 粗略估算
        print(f'{f}: {kb:.0f} KB ≈ {tok:.0f} tokens')
"

# 预期:
# 原始:  20 MB ≈ 5,000,000 tokens  (远超任何AI context窗口)
# 精简:  300 KB ≈ 75,000 tokens     (大上下文窗口可容纳)
# AI版:  60 KB  ≈ 15,000 tokens     (各种工具都轻松装下)
```

---

## 7. 完整的"导出前瘦身"checklist

打印或存到团队wiki,**每次导出前过一遍**:

```
□ Clear Solutions (Study → Clear All Solutions)
□ Delete Solver Configurations (右键删)
□ Delete unused Probes / Cut Lines / Cut Planes / Cut Points
□ 把 Interpolation 函数改为 file-based
□ Materials: 删掉拖入的 MaterialsLib 完整副本,改用自建 mat 引用必要属性
□ 几何节点: Build All → Convert to Geometry Sequence (压缩历史)
□ File → Save As → Model File for Java
   □ ✅ Include comments
   □ ❌ Compact history
   □ ❌ Include mesh (除非几何很复杂需要保留网格定义)
   □ ❌ Include solution
   □ ❌ Include functions data
□ 验证体积 < 500 KB
□ 如果 > 1 MB,运行 examples/scripts/analyze_java_size.py 诊断
□ 如果只给AI读,再跑 strip_java_for_ai.py 生成AI版
```

---

## 8. 为什么"清空解"不够

很多人困惑: "我Clear Solutions了,为什么还这么大?"

**Clear Solutions** 只清掉:
- 数值解 (Solution Data Sets里的数值)
- 求解日志中的迭代信息

**不会清掉**:
- Solver Configurations节点本身和其全部feature配置
- 嵌入的Interpolation表数据
- Material Library完整副本
- Probe/Cut*的几何/边界定义
- 几何/网格的累积operations

要彻底瘦身,需要按上面checklist逐项手动清理,**单靠Clear Solutions远远不够**。

---

## 9. 团队制度建议

如果团队都在用COMSOL `.java`,建议:

1. **加入入仓pre-commit hook**: `.java`文件 >1MB 时拒绝commit,提示运行瘦身checklist
2. **CI自动诊断**: 每个PR运行`analyze_java_size.py`,把诊断结果贴在PR评论
3. **培训新人**: 把这个checklist作为入职必修课

伪代码示例 (`.git/hooks/pre-commit`):

```bash
#!/bin/bash
for f in $(git diff --cached --name-only | grep '\.java$'); do
    size=$(wc -c < "$f")
    if [ "$size" -gt 1048576 ]; then  # 1 MB
        echo "ERROR: $f is $(($size/1024)) KB. 请按 java_export_slimming.md 瘦身后再commit。"
        exit 1
    fi
done
```
