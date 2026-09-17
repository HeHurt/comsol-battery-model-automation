# 团队工作流: Git/仓库结构/命名/对比

本文档面向**团队协作**场景,涵盖`.java`入仓的Git规范、推荐目录结构、命名约定,以及对比两个`.java`找差异的标准做法。

> ⚠️ **入仓前先检查`.java`体积**。20MB的`.java`不应进入git仓库。完整瘦身工作流和Python脚本 → 见 `java_export_slimming.md`。简而言之: 删 Solver Configurations、插值表用file引用、关闭 Include mesh/solution/functions data。

---

## 1. Git / 仓库工作流

### 核心约定

```
优先 commit 可审查的 .java；.mph 按仓库容量和组织策略决定是否单独存储
```

理由:
- `.mph`是二进制文件，难以 diff，且可能受文件大小或组织数据策略限制
- `.java`是纯文本,完美支持`git diff`/`git blame`/code review
- `.java`从`.mph`一键导出,作为"权威源"
- 复现实验: 同事`git pull → comsolcompile → COMSOL运行`即可

### `.gitignore` 标准模板

```gitignore
# COMSOL 加密源文件 (本地保留)
*.mph
*.mph.recovery

# COMSOL 编译产物
*.class
.comsol_temp/

# MATLAB/Python 后处理临时
sweep_out/*.csv
*.mat.tmp

# IDE
.vscode/launch.json
.idea/
```

### 推荐仓库结构

```
battery-comsol-models/
├── .agents/
│   └── skills/
│       └── comsol-battery-model-automation/ ← 仓库级 skill
├── models/
│   ├── java/                         ← 唯一的git跟踪源
│   │   ├── cell_LFP_280Ah_v3.java
│   │   ├── cell_LFP_314Ah_v1.java
│   │   └── module_thermal_v2.java
│   └── mph/                          ← .gitignore屏蔽,本地
│       └── *.mph
├── docs/
│   ├── README.md
│   └── changelog.md                  ← 每个模型版本变更
├── references/                       ← 本skill的参考文档
│   ├── liion_lfp_reference.md
│   ├── parameter_sweep_patterns.md
│   └── ...
├── scripts/
│   ├── batch_param_sweep.py         ← Python+Jinja模板批量生成.java
│   ├── compile_and_run.sh           ← 编译+批量求解脚本
│   └── matlab/
│       └── livelink_sweep.m         ← LiveLink扫描脚本
└── README.md
```

### Commit Message 风格 (推荐)

```
模型名: 简短描述

详细说明:
- 改了什么参数
- 物理上为什么
- 是否影响其他模型

涉及tag: <list>
COMSOL版本: 6.4
```

例:
```
cell_LFP_280Ah_v3: 把正极颗粒半径从1µm改为0.5µm

为了评估颗粒细化对2C倍率性能的影响。
预期: 容量保持率提升约3-5%

涉及tag: liion.pce2.pin2 (rp参数)
COMSOL版本: 6.4
```

---

## 2. 命名约定 (推荐,非强制)

如果团队需要统一命名，可以参考下表。**老模型如果不符合，新增时按规则；不要批量重命名，保留历史一致性**。

### 对象tag命名表

| 对象类型 | 前缀约定 | 例 |
|---|---|---|
| 几何特征 | `blk_` / `cyl_` / `sph_` + 含义 | `blk_can`, `cyl_jellyroll` |
| 选区 (Selection) | `sel_` + 含义 | `sel_pos`, `sel_sep`, `sel_cc_pos` |
| 材料 | `mat_` + 化学组分 | `mat_LFP`, `mat_Gr`, `mat_LiPF6_EC_EMC` |
| 物理场接口 | 用COMSOL默认tag | `liion`, `ht`, `ec` |
| 物理场子节点 | 通常默认 `pce1`/`pce2`/`sep1` 等 | 默认即可 |
| 全局参数 | 物理量缩写 + 区域后缀 | `epsl_pos`, `sigma_neg`, `Ds_pos` |
| Study | `std_` + 工况 | `std_chg1C`, `std_dchg2C`, `std_HPPC` |
| Result Dataset | `dset_` + 含义 | `dset_sweep_Crate` |

### 参数命名规范 (LFP/Gr电芯)

```
[物理量缩写][_区域后缀]

物理量: eps (体积分数) / sigma (电导率) / D (扩散) / k (反应速率) / r (颗粒半径) / L (厚度)
区域: _neg (负极/Gr) / _pos (正极/LFP) / _sep (隔膜) / _l (液相) / _s (固相)
```

例:
- `epsl_pos` = 正极液相体积分数
- `Ds_neg` = 负极固相扩散系数
- `rp_pos` = 正极颗粒半径
- `sigma_s_neg` = 负极固相电导率

### 模型文件命名

```
cell_<化学>_<容量>_v<版本>.java
module_<功能>_v<版本>.java
```

例:
- `cell_LFP_280Ah_v3.java`
- `cell_LFP_314Ah_v1.java`
- `module_3D_thermal_v2.java`

---

## 3. 对比两个 `.java` 找差异

### 场景

用户给了 `cell_v1.java` 和 `cell_v2.java`,问"改了什么"。

### 标准流程

#### 步骤1: 终端生成diff

```bash
# 用git的彩色diff (推荐,即使文件不在仓库里)
git diff --no-index --color=always models/java/cell_v1.java models/java/cell_v2.java | less -R

# 或纯文本diff
diff -u models/java/cell_v1.java models/java/cell_v2.java > /tmp/diff.txt
```

#### 步骤2: AI按结构化分类总结

把diff喂给AI,要求按以下5类总结:

| 分类 | 关注的代码段 |
|---|---|
| **参数变化** | `model.param().set(...)` 行的改动 |
| **物理场变化** | 新增/删除/修改 `physics().create(...)` 或 `physics(...).feature(...).set(...)` |
| **几何变化** | `geom(...)` 下的改动 |
| **Study/Solver变化** | `study(...)` / `sol(...)` 下的改动 |
| **后处理变化** | `result(...)` 下的改动 |

#### 步骤3: 标准输出模板

```markdown
# v1 vs v2 差异摘要

## 1. 参数变化 (X项)
- `rp_pos`: 1e-6 → 5e-7 m (颗粒半径减半)
- `T_amb`: 298.15 → 313.15 K (环境温度+15K)

## 2. 物理场变化
- 新增: `pin2.Ds_T_dep` 表达式 (扩散系数加温度依赖)
- 修改: `ecs1.I_el` 从 "I_app" 改为 "I_app_var" (CP模式切换)
- 新增: Global Equation `ge1` for CP

## 3. 几何变化
- 无

## 4. Study/Solver变化
- `std1.time.tlist`: "range(0,10,3600)" → "range(0,5,7200)" (时步细化,时长翻倍)
- 新增: Stop Condition `(E_cell<V_min)||(E_cell>V_max)`

## 5. 后处理变化
- 新增Table `tbl2` 导出温度时变曲线

## 物理意义解读 (推断)
该改动看起来是把v1的CC放电(1C到3600s)改为v2的**CP放电带温升测试**:
- 颗粒细化提升倍率性能
- 环境温度+15K模拟夏季工况
- CP模式需要Stop Condition防止低压发散
- 时步细化为了捕捉LFP平台过渡区
```

#### 步骤4: 物理意义解读

AI**应该**基于参数变化推断改动的物理意图(例上面"物理意义解读"段)。但要明确标注**这是推断,不是用户confirmed**。

---

## 4. 模型版本演进的标准模板

每次模型重大变更,在`.java`顶部加固定格式的修改记录:

```java
/*
 * === 修改记录 ===
 * v3 (2026-05-18): 加入CP工况,P_app范围0.5P-2P
 *   - 新增Global Equation ge1 求解 I_app_var
 *   - 新增Stop Condition防低压发散
 *   - 修改ecs1.I_el引用I_app_var
 * v2 (2026-04-22): 颗粒半径细化
 *   - rp_pos: 1µm → 0.5µm
 * v1 (2026-03-15): 初版P2D + 3D热模型
 *   - 280Ah电芯,1D P2D + 3D壳体热场
 *   - General Extrusion耦合 (genext1/genext2)
 * === END ===
 */
```

好处:
- diff友好(只追加,不修改历史行)
- 与git commit message互补
- 单独导出`.java`时也能查到变更历史
- 新人快速理解模型演进

---

## 5. AI 修改完后的标准交付清单 (5项)

每次AI生成代码片段后,**强制**给出以下信息(即使用户没问):

1. **修改摘要** (3-5行bullet): 改了什么、为什么
2. **影响范围**: 哪些tag被新增/修改/删除
3. **未改动的承诺**: 明确"以下部分保持不变: [列表]"
4. **验证建议**: 用户应该跑什么Study来验证
5. **回写建议**: 用`comsolcompile`编译还是直接COMSOL `File → Compile Java File`

例:

```markdown
## 修改摘要
- 新增Global Equation `ge1` 实现CP工况
- 修改`ecs1.I_el`从"I_app"改为"I_app_var"
- 加入Stop Condition防低压发散

## 影响范围
- 新增: `comp1.ge1` (Global Equations节点)
- 修改: `comp1.liion.ecs1` (I_el属性)
- 修改: `std1.time` (新增usestopcond/stopcond)

## 未改动的承诺
- 所有几何参数 (`L_neg`/`L_pos`/`L_sep`) 不变
- 物理场pce1/pce2/sep1的属性不变
- 网格设置不变
- 后处理result设置不变

## 验证建议
- 跑std1,P_app=560W (1P) → 端电压应在2.5-3.65V平台内,放电时间≈1h
- 检查I_app_var随时间变化曲线: 平台期接近常数,接近V_min时电流上升

## 回写建议
建议用COMSOL Desktop的 `File → Compile Java File`,因为新加了Global Equation,
GUI编译会自动校验方程的雅可比可解性。命令行comsolcompile也能用但报错信息不如GUI友好。
```

---

## 6. 团队上手 onboarding 建议

新工程师加入仿真团队时:

1. **第一周**: 读本skill的`SKILL.md`和`references/comsol_java_anatomy.md`,在COMSOL里手工导出一个简单`.java`,跟着grep流程读一遍
2. **第二周**: 跟着`references/liion_lfp_reference.md`理解LFP/Gr模型的物理场结构,尝试改一个参数,编译运行
3. **第三周**: 学习`references/parameter_sweep_patterns.md`,跑一次C倍率扫描,导出CSV用Python/MATLAB分析
4. **第四周**: 看`references/multiscale_1d_3d_coupling.md`,理解大电芯的多尺度建模
5. **持续**: 用AI Agent生成代码时,严格按SKILL.md的5步工作流走,**禁止跳过Step 2-3直接生成**

定期(月度)review新的失败case,把根因写进自检清单或新增reference,**让skill持续演化**。
