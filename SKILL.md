---
name: comsol-battery-model-automation
description: 以 Codex 为核心审计、诊断、另存修改、运行和验证 COMSOL Multiphysics 6.4 电池模型。用于已有 .mph 的电压、容量、产热、求解器和参数扫描问题，受保护模型，COMSOL 导出 .java 的定向修改，以及 liion/P2D、1D-3D 电化学-热耦合、CC/CP、comsolcompile/comsolbatch 和结果验收。MATLAB LiveLink 调度与优化器集成不在本 skill 范围内。
---

# COMSOL Battery Model Automation v5.0

由 Codex 选择最小执行路线、判断物理合理性并验收；把 sim-cli、ModelUtil、COMSOL Desktop/MCP、`comsolcompile` 和 `comsolbatch` 作为底层执行器。不要要求用户准备 JSON、选择工具或运行命令。

## 路线

| 输入与目标 | 主路线 | 必读资料 |
|---|---|---|
| 已有 `.mph`：审计、诊断、修改、重算 | MPH Direct：`run_mph_tool.py` + ModelUtil | `references/mph_runtime_workflow.md` |
| 已有导出 `.java`：理解或局部修改 | Java Snippet | `references/comsol_java_anatomy.md` |
| 从零构建并交付 `.java/.mph/metrics/report` | Autonomous Java | `references/autonomous_execution.md`、`references/acceptance_criteria.md` |
| MATLAB 调度或优化器集成 | 使用专用 LiveLink 工作流 | 不在本 skill 重复 |

MCP 不是本 skill 的主链。仅在标准多物理原型、结构化文档检索或当前路线缺少必要操作时使用；DLP `.mph` 仍优先交给 COMSOL 后端加载。

只读诊断直接执行；用户只要求诊断时不得自动修改。修改模型必须保留源文件并另存。完整建模、标定或长计算开始前确认验收条件和运行预算。

## 已有 `.mph`

执行闭环：

```text
audit → diff（需要时）→ patch另存 → reload assertions → smoke → 正式计算
```

通过单一入口运行配置，launcher 使用固定版本的 `sim-cli-core` 与 `sim-plugin-comsol`，自动复用健康会话、创建必要会话、注入配置并只清理自己创建的会话：

```powershell
python scripts/run_mph_tool.py --config D:\runs\case\audit.json
```

不要手工复制配置到 `.sim`，不要自行解析 session id。连接失败时 launcher 不会杀死未知进程；确认进程所有者后再清理。配置和输出格式见 `references/mph_runtime_workflow.md`。

### 按症状选择 preset

| 症状 | audit preset | 同时读取 |
|---|---|---|
| 电压平台、起点或截止异常 | `voltage` | `references/diagnostic_presets.md`、材料体系 reference |
| 充放电容量或 SOC 不一致 | `capacity` | `references/diagnostic_presets.md`、`references/liion_lfp_reference.md` |
| 产热、接触热或能量守恒异常 | `heat_balance` | `references/electrothermal_audit.md` |
| 不收敛、study/solver 异常 | `solver` | `references/diagnostic_presets.md`、`references/comsol_64_api_notes.md` |
| 参数扫描缺结果或取错 case | `sweep` | `references/diagnostic_presets.md`、`references/parameter_sweep_patterns.md` |

默认使用 `summary`；已知目标节点时用 `targeted`；只有摘要不足时才用 `full`。从边界条件或研究步骤追踪表达式到真实消费者，不因变量“存在”就判定它生效。区分已确认事实、推断和未验证项。

## Java

对导出 `.java` 先用 `examples/scripts/analyze_java_size.py` 和 `strip_java_for_ai.py` 生成定向视图，不按固定文件大小阈值盲目整文件读取。复用实际导出的 tag、property 和依赖顺序；不发明 API。

Autonomous Java 使用 `references/complete_model_template.md` 和 `examples/scripts/comsol_batch_runner.py`。每轮读取 `cycle_result.json`，只修改有证据支持的源码或验收配置。默认以 `comsolcompile.exe` 编译、`comsolbatch.exe` 求解；报告接口见 `references/simulation_report_template.md`。

## 环境与本机增量规则

- 默认安装目录为 `%USERPROFILE%\.codex\skills\comsol-battery-model-automation`；不要依赖作者机器上的仓库路径。
- MPH Direct 需要 Python 3.10+、`uv`、COMSOL 6.4 与可用许可证。首次运行需联网下载固定版本 runtime；非标准安装位置通过 `COMSOL_ROOT=<Multiphysics目录>` 指定。
- Java Snippet 只读分析不要求本机安装 COMSOL；编译、求解和真实验证仍需要 COMSOL。
- 受保护的 `.mph` 应由 COMSOL 后端 `ModelUtil.load()` 加载；离线 ZIP/MCP standalone 失败不代表模型损坏。
- 对受组织策略保护的 `.java`，遵循所在环境的授权读写通道；复杂脚本使用 `exec --file`，避免 PowerShell 内联转义。
- 大型 `.mph` 顺序加载并立即 `ModelUtil.remove(tag)`，不要同时驻留多个模型。
- License 错误只报告一次并停止重试。

## 验收

- 保存后的 `.mph` 必须卸载、重载并通过请求对应的 assertions。
- 物理或求解表达式修改后运行最小有效 smoke；所有结果读取显式指定单位，扫描结果明确 dataset/solnum。
- smoke 只证明最小案例，不得表述为完整扫描完成。
- 交付源/输出路径、修改清单、回读断言、smoke 配置与指标、正式计算状态；失败时保留产物并分类说明。

修改本 skill 后运行：

```powershell
$env:PYTHONUTF8='1'
$skillRoot = Join-Path $env:USERPROFILE '.codex\skills\comsol-battery-model-automation'
python -m pytest (Join-Path $skillRoot 'tests') -q
```
