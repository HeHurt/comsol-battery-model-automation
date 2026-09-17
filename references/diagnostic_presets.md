# `.mph` 症状诊断 Preset

## 目录

1. 公共证据链
2. `voltage`
3. `capacity`
4. `heat_balance`
5. `solver`
6. `sweep`

Preset 用于限制审计内容，不替代物理判断。先运行 `summary + preset`；明确节点后改用 `targeted`；只有仍缺证据时才用 `full`。

## 公共证据链

每次诊断按以下顺序组织结论：

1. 用户看到的 observable 来自哪个 probe、expression、dataset 和 solution number。
2. 工况由哪个 physics feature、variable、event 或 study step 消费。
3. 初始状态、材料函数和截止条件是否与工况一致。
4. 区分模型中已确认事实、基于事实的推断、尚未运行验证的项。

配置示例：

```json
{
  "action": "audit",
  "options": {"scope": "summary", "preset": "voltage"},
  "models": [{"path": "D:\\models\\cell.mph", "tag": "cell_audit"}],
  "output": "D:\\runs\\case\\audit.json"
}
```

单个模型可以用 `models[].options` 覆盖全局 options。

## `voltage`

检查：

- 实际绘图或探针表达式是否为端电压，而非单侧 `phis`、局部电位或旧 dataset。
- 正负极 OCP/OCV 函数、文件来源、单位和额外 offset。
- 初始 SOC/stoichiometry、正负极映射方向和静置 OCV。
- 电流表达式、方向、CC/CP/CV 类型和 event 状态。
- 高低压截止、隐式事件触发后的状态切换。

不要把端子截止电压直接当作 SOC 端点的静置 OCV。

## `capacity`

检查：

- 容量积分变量的真实名称和单位；不要假定所有模型都叫 `Q1`。
- 正负极可用容量、限制电极、N/P 和 `csmax`。
- 充放电模型的 SOC 窗口、倍率、截止和 CV 逻辑是否一致。
- 结果读取使用的 dataset、outer solution 和时间终点。

## `heat_balance`

先完成 preset 审计，再读取 `electrothermal_audit.md`。必须分别输出电化学热、接触热、金属焦耳热、映射热和相对守恒残差。

## `solver`

检查顺序：参数/单位 → geometry/selection → material → boundary condition → mesh → initial values → study/solver feature。放宽 tolerance 仅用于定位，不作为最终修复。

记录实际 solver tag、study step、initial solution、time list、stop condition 和失败时刻。不要先重装环境；只有错误明确指向连接、路径或 license 才检查环境。

## `sweep`

检查：

- `pname`、`plistarr`、`punit` 数量和顺序一致。
- sweep 是笛卡尔积还是 specified combinations。
- Global Evaluation 显式选择参数扫描 dataset。
- 输出明确 `solnum`/`outersolnum`，不要用默认单解冒充全部 case。
- 正式扫描前已有一个通过验收的 baseline case。
