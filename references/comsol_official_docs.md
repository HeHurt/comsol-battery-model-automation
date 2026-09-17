# COMSOL 官方文档检索指南

本文档告诉 AI **何时**该去翻官方文档,**翻哪个**,**怎么翻**。

> 从 `COMSOL_ROOT` 推导 COMSOL 6.4 本地文档路径。AI 在 Autonomous Mode 自主 debug 时,如果错误模式库覆盖不了,**主动检索**官方文档。

---

## 1. 用户提供的文档路径

### 1.1 PDF 编程手册

| 文件 | 路径 | 内容 |
|---|---|---|
| **ProgrammingReferenceManual** | `<COMSOL_ROOT>\doc\pdf\COMSOL_Multiphysics\COMSOL_ProgrammingReferenceManual.pdf` | 编程流程、Java API 使用范式、批处理、Method Editor |
| **ReferenceManual** | `<COMSOL_ROOT>\doc\pdf\COMSOL_Multiphysics\COMSOL_ReferenceManual.pdf` | 命令/对象/接口完整参考 |

### 1.2 Javadoc HTML 文档

| 入口 | 路径 |
|---|---|
| **总索引** | `<COMSOL_ROOT>\doc\help\wtpwebapps\ROOT\doc\com.comsol.help.comsol\api\index.html` |
| **ModelUtil 入口类** | `<COMSOL_ROOT>\doc\help\wtpwebapps\ROOT\doc\com.comsol.help.comsol\api\com\comsol\model\util\ModelUtil.html` |
| **目录** | `<api>\com\comsol\model\` (model 包,~ 497个 HTML 文件) |

⚠️ **注意路径说明**: 用户原始消息把 ProgrammingReferenceManual 列了两次。第二个**应该**是 ReferenceManual。AI 在 STEP A 与用户确认路径时,主动提示这点。

---

## 2. "何时该查文档" 决策树

```
遇到问题
  │
  ├── 错误模式库 (autonomous_execution.md 第2-3节) 能覆盖?
  │     是 → 按库里的修复策略来,不需要查文档
  │     否 → 继续
  │
  ├── 错误涉及具体 API 方法/属性键名?
  │     是 → 查 Javadoc (从 ModelUtil.html 入口)
  │     否 → 继续
  │
  ├── 涉及建模流程/Method/批处理?
  │     是 → 查 ProgrammingReferenceManual.pdf
  │     否 → 继续
  │
  └── 涉及具体物理场属性/几何特征/求解器选项?
        是 → 查 ReferenceManual.pdf
        否 → 报告给用户,需要人工介入
```

---

## 3. Javadoc 检索指南

### 3.1 结构概览

```
api/
├── index.html                          总入口
├── overview-tree.html                  类继承树
├── allclasses-index.html               全部类索引
└── com/comsol/model/
    ├── Model.html                      主入口接口
    ├── ModelNode.html                  通用节点接口
    ├── physics/
    │   ├── PhysicsFeature.html
    │   └── ...
    ├── geom/
    │   ├── GeomFeature.html
    │   └── ...
    ├── study/
    │   ├── Study.html
    │   ├── StudyStep.html
    │   └── ...
    └── util/
        └── ModelUtil.html              ★ AI 常入口
```

### 3.2 典型 grep 流程

AI 不能直接 read HTML(太多),应该:

**步骤1**: 用 grep 在 `api/` 目录搜方法名

```bash
# 找方法 setIndex 的所有定义
grep -r -l "setIndex" "<comsol-doc>/api/com/comsol/model" 2>/dev/null | head -20

# 找方法 "createFeature" 在哪些类有
grep -r "createFeature" "<comsol-doc>/api/com/comsol/model" --include="*.html" 2>/dev/null | head -10
```

**步骤2**: 找到候选 HTML 后,用工具提取方法签名

```bash
# 提取 ModelUtil 的所有 public 方法
python -c "
from html.parser import HTMLParser
import re
with open('<comsol-doc>/api/com/comsol/model/util/ModelUtil.html') as f:
    html = f.read()
# 简单 grep 风格提取方法签名
sigs = re.findall(r'<h4>(.*?)</h4>.*?<pre>(.*?)</pre>', html, re.DOTALL)
for name, sig in sigs[:20]:
    print(name.strip(), '→', re.sub(r'<.*?>', '', sig).strip()[:120])
"
```

**步骤3**: 读关键方法的描述

按方法名定位 HTML 锚点,如:
```
ModelUtil.html#create(java.lang.String,java.lang.String)
```

### 3.3 常用类的位置

| 类 | 路径 | 用于 |
|---|---|---|
| ModelUtil | `com/comsol/model/util/ModelUtil.html` | 模型创建/管理 |
| Model | `com/comsol/model/Model.html` | 主入口接口 |
| PhysicsFeature | `com/comsol/model/physics/PhysicsFeature.html` | 物理场节点配置 |
| Study | `com/comsol/model/study/Study.html` | Study 配置 |
| Solution | `com/comsol/model/solution/Solution.html` | 求解器 |
| Material | `com/comsol/model/material/Material.html` | 材料 |
| Result | `com/comsol/model/result/Result.html` | 后处理 |

---

## 4. PDF 手册检索指南

### 4.1 ProgrammingReferenceManual.pdf — 何时查

适合检索:
- "如何用 Java API 创建 XXX"(整体流程)
- "Method Editor 怎么用"
- "批处理 comsolbatch 选项"
- "如何写 application"
- "如何用 LiveLink for MATLAB"

**不适合**: 具体属性键名查询 → 用 Javadoc 更快。

### 4.2 ReferenceManual.pdf — 何时查

适合检索:
- "Lithium-Ion Battery 物理场所有可用属性"
- "Time-Dependent Step 的 tlist 语法"
- "Convective Heat Flux 边界的属性键"
- "Interpolation 函数的所有 method 类型"

### 4.3 PDF 检索方法

PDF 不能直接 grep,但可以转文本:

```bash
# 一次性转 ProgrammingReferenceManual 为 txt (做一次,缓存供后续查)
pdftotext -layout \
    "<COMSOL_ROOT>\doc\pdf\COMSOL_Multiphysics\COMSOL_ProgrammingReferenceManual.pdf" \
    "<workdir>/cache/ProgRefMan.txt"

# 然后 grep
grep -n -A 3 "ElectrochemicalHeating" "<workdir>/cache/ProgRefMan.txt"
grep -n -A 5 "comsolbatch" "<workdir>/cache/ProgRefMan.txt" | head -30
```

`-layout` 保留版面,grep 后能看到上下文。

**缓存这些 txt 文件到工作目录**,后续 debug 不要重复转。

### 4.4 章节定位 (ProgrammingReferenceManual)

| 主题 | 大约位置 (按目录) |
|---|---|
| Getting Started with Programming | 前 30 页 |
| The Java API | ~50-150 页 |
| Model Object | ~150-250 页 |
| Geometry Programming | ~250-350 页 |
| Physics Programming | ~350-500 页 |
| Mesh / Study / Solver | ~500-650 页 |
| Results / Postprocessing | ~650-750 页 |
| Method Editor | ~750-850 页 |
| Running COMSOL from Command Line | ~850-900 页 |

页码不一定准,以实际文件目录为准。

---

## 5. 错误 → 文档映射表

当 AI 遇到错误模式库没有的错误,按这张表查:

| 错误关键词 | 优先查 | 备用查 |
|---|---|---|
| `cannot find symbol: method ...` | Javadoc (类名.html) | ProgRefMan "Method Reference" 章 |
| `Property "..." is not defined` | Javadoc 对应物理场类 | ReferenceManual |
| `Selection ... not found` | ProgRefMan "Selections" 章 | Javadoc Selection.html |
| `Mesh feature ... unknown` | ProgRefMan "Mesh Programming" | Javadoc mesh 包 |
| `Study step ... not supported` | ProgRefMan "Study Programming" | Javadoc study 包 |
| `Material property "..." invalid` | ReferenceManual "Material Database" | Javadoc Material.html |
| `Solver setting ... invalid` | ProgRefMan "Solver Programming" | ReferenceManual |
| `Export type ... unknown` | Javadoc result.export 包 | ReferenceManual |

---

## 6. 检索后的处理流程

找到答案后:
1. **引用源**: 在 debug_history.json 中记录 `"reference": "ProgRefMan p.234 / ModelUtil.create()"`
2. **应用修复**: 修改 .java 对应位置
3. **验证**: 重新编译/求解
4. **如果还不行**: 不要无限循环查文档,记下来,告诉用户

---

## 7. 主动检索 vs 等用户告诉

AI 应该**主动检索**的情况:
- ✅ 编译错误明确指向某个 API 方法 → 查 Javadoc
- ✅ 物理场属性键名报错 → 查 ReferenceManual
- ✅ 用户给的命令行参数不熟 → 查 ProgRefMan

AI 应该**等用户**的情况:
- ❌ 涉及商业建模决策 (用哪个物理场更好)
- ❌ 错误信息含糊不清,需要先排查环境
- ❌ License 相关
- ❌ 已经查了 2 个文档还没找到答案 → 停下问用户

---

## 8. 通用 Web 检索的替代

**如果用户本地文档不可用**:

| 在线资源 | 适用 |
|---|---|
| `comsol.com/documentation` | 在线版手册 (需登录) |
| `comsol.com/forum` | 社区问答 |
| `comsol.com/blog` | 应用案例 (P2D 模型有专门文章) |

但**优先用本地文档**(用户提供的路径),因为:
1. 版本对齐 (本地是 6.4)
2. 网络/防火墙不依赖
3. 受限网络可能无法访问 comsol.com

---

## 9. 文档检索的命令示例 (放进 AI prompt)

让 AI 在 debug 时遇到 "API 不确定" 时,执行:

```bash
# 假设遇到错误: cannot find symbol: method createFeature(String,String)
# 先在 Javadoc 里找

# Step 1: 找所有定义 createFeature 的类
DOC="<COMSOL_ROOT>\doc\help\wtpwebapps\ROOT\doc\com.comsol.help.comsol\api"
grep -r -l "createFeature" "$DOC/com/comsol/model" --include="*.html" 2>/dev/null | head -10

# Step 2: 看具体某个类的签名
# (假设找到 PhysicsFeature.html 有这个方法)
python3 -c "
import re
with open(r'$DOC/com/comsol/model/physics/PhysicsFeature.html') as f:
    html = f.read()
# 提取该方法的所有签名变体
sigs = re.findall(r'<a id=\"createFeature[^\"]*\".*?</section>', html, re.DOTALL)
for s in sigs[:5]:
    # 简化输出
    cleaned = re.sub(r'<[^>]+>', ' ', s)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    print(cleaned[:300])
    print('---')
"
```

如果文档转 txt 后用 grep 也很高效:
```bash
TXT="<workdir>/cache/ProgRefMan.txt"
grep -n -B 1 -A 5 "createFeature" "$TXT" | head -30
```
