# MPH Runtime Workflow

## 目录

1. 单命令入口与会话所有权
2. Audit scopes 和 presets
3. Diff
4. Patch 与回读
5. Verify
6. Smoke
7. 故障边界

## 1. 单命令入口与会话所有权

所有触碰 `.mph` 的动作通过 launcher 执行：

```powershell
$skillRoot = Join-Path $env:USERPROFILE '.codex\skills\comsol-battery-model-automation'
python (Join-Path $skillRoot 'scripts\run_mph_tool.py') `
  --config C:\COMSOL-runs\case\audit.json
```

前置条件：Python 3.10+、`uv`、COMSOL 6.4 和可用许可证。launcher 默认通过 `uvx` 获取固定版本 `sim-cli-core==0.3.7` 与 `sim-plugin-comsol==0.1.14`，因此首次运行需要访问 PyPI；之后可复用本机缓存。COMSOL 装在非标准位置时，将 `COMSOL_ROOT` 指向 `Multiphysics` 目录，例如 `D:\Apps\COMSOL64\Multiphysics`，不要指向 `bin\win64`。

launcher 自动执行：

1. `sim --json ps` 查找 COMSOL session。
2. 对候选 session 做轻量 exec 健康检查。
3. 无健康 session 时建立 no-GUI COMSOL session。
4. 通过临时 bootstrap 注入原始 config 路径，不再复制 `.sim\mph_tool_config.json`。
5. 删除 bootstrap，只断开本次创建的 session；复用的 session 保持不动。
6. 在 config 同目录写 `<config-stem>.session.json` 记录所有权。

调试时可加 `--keep-created-session`；仅验证 schema 时用 `--dry-run`。launcher 不自动杀死未知 server、COMSOL 进程或端口占用者。

`diff` 自动使用普通 Python，不启动 COMSOL。

## 2. Audit scopes 和 presets

Scopes：

- `summary`：默认。输出物理场/顶层节点摘要、study 和 dataset；不展开全部属性。
- `targeted`：仅保留明确请求的参数、变量和 feature property。
- `full`：展开完整树和属性；只在摘要不足时使用。

Presets：`voltage`、`capacity`、`heat_balance`、`solver`、`sweep`。对应证据清单见 `diagnostic_presets.md`。

```json
{
  "action": "audit",
  "options": {"scope": "summary", "preset": "capacity"},
  "models": [
    {
      "path": "D:\\models\\cell.mph",
      "tag": "capacity_audit",
      "parameters": ["SOC_init"],
      "variables": [{"component": "comp1", "group": "var1", "names": ["Q1", "Q2"]}],
      "features": [{"component": "comp1", "physics": "liion", "feature": "socicd1", "properties": ["CellVoltageInputType"]}]
    }
  ],
  "output": "D:\\runs\\case\\audit.json"
}
```

大型模型顺序加载和卸载。两个模型比较时分别审计，不同时驻留。

## 3. Diff

```json
{
  "action": "diff",
  "left": "D:\\runs\\case\\charge.json",
  "right": "D:\\runs\\case\\discharge.json",
  "ignore": ["models.0.source", "models.0.label"],
  "output": "D:\\runs\\case\\diff.json"
}
```

只比较相同 scope/preset 的审计结果，避免把输出范围差异误判成模型差异。

## 4. Patch 与回读

`patch` 支持 `set_param`、`set_variable`、`set_feature`、`create_heat_source` 和 `create_probe`。创建节点前必须从 audit 或导出 Java 确认 tag 和 selection。

```json
{
  "action": "patch",
  "source": "D:\\models\\cell.mph",
  "output_model": "D:\\runs\\case\\cell_fixed.mph",
  "operations": [{"op": "set_param", "name": "R_contact", "value": "0.02[mohm]"}],
  "assertions": [{"kind": "param_expr", "name": "R_contact", "equals": "0.02[mohm]"}],
  "output": "D:\\runs\\case\\patch.json"
}
```

工具拒绝覆盖源文件，并在保存后卸载、重载和执行 assertions。

## 5. Verify

```json
{
  "action": "verify",
  "source": "D:\\runs\\case\\cell_fixed.mph",
  "assertions": [{"kind": "feature_exists", "component": "comp1", "physics": "ht", "tag": "hs1"}],
  "output": "D:\\runs\\case\\verify.json"
}
```

支持 `param_expr`、`variable_expr`、`feature_property`、`probe_expr` 和 `feature_exists`。

## 6. Smoke

Smoke 只在内存中覆盖 study 设置，不保存缩短后的研究。每个 expression 必须给出输出单位；扫描结果应显式指定 `dataset`、`solnum` 或 `outersolnum`。

```json
{
  "action": "smoke",
  "source": "D:\\runs\\case\\cell_fixed.mph",
  "study": "std1",
  "dataset": "dset2",
  "overrides": [{"study_feature": "time", "property": "tlist", "value": "range(0,10,60)"}],
  "metrics": [{"name": "voltage", "expr": "liion.E_cell", "unit": "V"}],
  "output": "D:\\runs\\case\\smoke.json"
}
```

## 7. 故障边界

- session 获取失败：保留完整错误；先确认进程所有者，不自动杀未知进程。
- tag/property/selection 错误：缩窄到目标节点，参考实际导出 Java，不猜 API。
- dataset 无法读取：错误结果记录尝试过的 dataset；核对 solution number 和单位。
- License 错误：停止重试。
- 任何失败都保留源文件和此前成功产物；项目任务按 `AGENTS.md` 记录日志。
