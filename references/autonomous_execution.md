# 自主执行管线: 编译 / 求解 / debug 循环

本文档面向 **Autonomous Mode**,详述 AI 自主跑通 COMSOL 模型的完整管线:从 .java 编译到 .mph 求解,到错误识别、自动 debug、收敛策略。

> 本文档假设用户已在 STEP A 提供路径配置。所有命令以 Windows 为主,Linux/Mac 用对应工具。

---

## 1. COMSOL 6.4 命令行工具速查

### 1.1 用户给的路径配置

| 工具 | 典型路径 (Windows) | 作用 |
|---|---|---|
| `java.exe` | `<COMSOL_ROOT>\java\win64\jre\bin\java.exe` | 运行 .class (不是编译) |
| `javac.exe` | `<COMSOL_ROOT>\java\win64\jre\bin\javac.exe` | 编译 .java (注意:JRE 可能没有 javac,需要 JDK) |
| `comsolcompile.exe` | `<COMSOL_ROOT>\bin\win64\comsolcompile.exe` | ★ **推荐**: 一键编译 .java → .class,自动处理 classpath |
| `comsolbatch.exe` | `<COMSOL_ROOT>\bin\win64\comsolbatch.exe` | 无 GUI 跑 .class/.mph |
| `comsol.exe` (Desktop) | `<COMSOL_ROOT>\bin\win64\comsol.exe` | GUI |

**Linux 等价**: 把 `bin\win64` 换成 `bin/glnxa64`,`.exe` 去掉。

### 1.2 一句话理解三个工具

- `javac` / `comsolcompile` — **编译**: .java → .class (静态检查 Java 语法)
- `comsolbatch` — **求解**: 跑 .class 或 .mph,产生数值结果
- `comsol` — **GUI**: 人在用

AI 在 Autonomous Mode 用 `comsolcompile`(可选 `javac`) + `comsolbatch`,**不要用 `comsol.exe`**(它会卡住等 GUI)。

---

## 2. 编译阶段 (.java → .class)

### 2.1 推荐: comsolcompile

```bash
"<COMSOL_ROOT>\bin\win64\comsolcompile.exe" \
    GeneratedModel.java
```

- 自动处理所有 COMSOL classpath
- 输出 `GeneratedModel.class` 到同目录
- 失败时 stderr 给出标准 Java 编译错误

### 2.2 备选: 直接 javac (需 JDK)

```bash
"<JDK-path>/bin/javac.exe" \
    -cp "<COMSOL_ROOT>\plugins\*" \
    -d <output-dir> \
    GeneratedModel.java
```

⚠️ COMSOL 6.4 自带的是 **JRE**(只有 java.exe,可能没有 javac.exe)。
如果只有 JRE,用户给的 `java.exe` 路径**不能直接编译 Java**。必须用 `comsolcompile.exe`,或者用户单独装 JDK。

### 2.3 编译错误模式库 (按出现频率)

| 错误现象 (stderr) | 根因 | 修复策略 |
|---|---|---|
| `cannot find symbol\n  symbol: variable XXX` | 引用了未定义的参数 | 在 `model.param().set` 段添加该参数 |
| `cannot find symbol\n  symbol: method foo(...)` | API 方法名错或版本不匹配 | 查 `references/comsol_64_api_notes.md`,或检索 Javadoc |
| `';' expected` 或 `'(' expected` | Java 语法错(漏分号/括号) | 定位行号,补语法 |
| `incompatible types: String cannot be converted to int` | `setIndex(...)` 第3参数 (index) 应为 int 不是字符串 | 把 `"0"` 改为 `0` |
| `cannot find symbol\n  symbol: class XXX` | 引用了不存在的类(如 `LithiumIonBattry` 漏字母) | 拼写检查,正确是 `LithiumIonBattery` |
| `ModelUtil.create(...) returned null` | 模型名重复或工作目录无写权限 | 改 model.label,或换工作目录 |
| `Selection has no entities` | 选区配置错误,边界/域索引不存在 | 检查 geom 实际产生了多少 domain/boundary,修正 index |
| `Property "XXX" is not defined for feature "YYY"` | 6.4 改了属性键名 | 查 `comsol_64_api_notes.md`,如 `Ee` → `Eeq` |

### 2.4 编译错误的处理伪代码

```python
def compile_with_retry(java_file, max_attempts=8):
    history = []
    for attempt in range(1, max_attempts + 1):
        result = run("comsolcompile.exe", java_file)
        if result.returncode == 0:
            return {"success": True, "history": history}
        # 解析 stderr
        errors = parse_compile_errors(result.stderr)
        if not errors:
            history.append({"attempt": attempt, "error": "Unknown", "raw": result.stderr})
            return {"success": False, "history": history}
        # 对第一个错误尝试修复
        fix = lookup_fix_strategy(errors[0])
        if fix is None:
            # 落到检索官方文档
            fix = consult_official_docs(errors[0])
        # 应用修复到 java_file
        apply_fix(java_file, fix)
        history.append({"attempt": attempt, "error": errors[0], "fix": fix})
    return {"success": False, "history": history, "reason": "Max attempts exceeded"}
```

完整实现见 `examples/scripts/parse_comsol_errors.py`。

---

## 3. 求解阶段 (.class → .mph)

### 3.1 标准命令

```bash
"<COMSOL_ROOT>\bin\win64\comsolbatch.exe" \
    -inputfile GeneratedModel.class \
    -outputfile result.mph \
    -batchlog run.log \
    -recover \
    -alivetime 300
```

| 选项 | 说明 |
|---|---|
| `-inputfile` | 可以是 .class 或 .mph |
| `-outputfile` | 求解后保存的 .mph |
| `-batchlog` | 求解日志(进度 + 错误) |
| `-recover` | 出错时保留中间状态 |
| `-alivetime N` | 心跳间隔(秒),N秒内无进度判定为卡死 |
| `-mphtype off` | 关闭 mph 验证(加速,但风险) |
| `-nn N` | 节点数(集群用) |
| `-np N` | 每节点核数 |

### 3.2 求解失败模式库

| 错误现象 (run.log) | 根因 | 修复策略 (按优先级) |
|---|---|---|
| `Newton method did not converge` | 求解器发散,常见于刚启动 | 1. 减小初始时间步: `tlist` 改 `range(0,0.01,T_end)` <br>2. 提高 reltol: `1e-3` → `1e-5` <br>3. 改用 Backward Euler |
| `Failed to find consistent initial values` | 初值矛盾 | 检查 `init1` 设置;对 P2D 模型确保 `phis - phil ≈ OCV(SOC_init)` |
| `Out of memory` | RAM 不够 | 1. 减少网格 (mesh size factor 改 1.0→1.5)<br>2. 减少时间输出点 (`tlist` 步长加大)<br>3. 关闭无用 Probe |
| `License error` 或 `Could not check out license` | 授权问题 | **停止重试**,告诉用户检查 license,可能 GUI 也占了一个名额 |
| `Stop condition met before simulation ended` | Stop condition 触发(CC到截止) | **这不一定是错误** — 对 CC/CP 工况是预期行为,检查终止时电压是否在合理范围 |
| `Singular matrix` | 网格质量差或参数不物理 | 检查活性物质体积分数 > 0,孔隙率合理,网格密度 |
| `Maximum number of segregated iterations exceeded` | Segregated solver 内部不收敛 | 改 Fully Coupled,或增加 maxiter 到 50 |
| `NaN or Inf encountered` | 中间数值爆炸 | 通常是 LFP 在低 SOC 段 OCV 函数 → 检查 OCV 函数定义域 [0,1] 覆盖完整 |

### 3.3 LFP/Gr 模型的特殊收敛技巧

LFP 平台型 OCV 会让 dV/dSOC 几乎为零,导致 Newton 收敛慢。专门策略:

```java
// 在 std1.time 设置中,加这几条提高 LFP 模型稳定性
model.study("std1").feature("time").set("tstepsbdf", "intermediate");  // 中等时间步
model.study("std1").feature("time").set("rtol", "1e-4");                // 比默认松一档
model.study("std1").feature("time").set("atolglobalvaluemethod", "factor");
model.study("std1").feature("time").set("atolfactor", "0.05");          // 松绝对误差

// Time-Dependent Solver 配置
model.sol("sol1").feature("t1").set("rtolactive", true);
model.sol("sol1").feature("t1").set("estrat", "exclude");               // OCV 平台不影响误差估计
```

### 3.4 监控求解进度

求解 P2D 可能要几分钟到几小时。AI 应该:
1. 启动求解时记下 PID
2. 每 30 秒 tail `-n 20 run.log` 检查进度
3. 5 分钟无进度 → 怀疑卡死,kill PID 并报错

伪代码:
```python
proc = subprocess.Popen([comsolbatch_path, ...])
last_log_size = 0
last_progress_time = time.time()
while proc.poll() is None:
    time.sleep(30)
    current_size = os.path.getsize("run.log")
    if current_size > last_log_size:
        last_progress_time = time.time()
        last_log_size = current_size
    elif time.time() - last_progress_time > 300:  # 5min
        proc.kill()
        return {"error": "Solver stalled"}
```

---

## 4. 结果提取阶段

求解完成后从 .mph 提取关键指标。两种方式:

### 4.1 推荐: 求解时直接导出 CSV

在 .java 的 `main()` 末尾加:

```java
// 计算关键指标
model.result().numerical().create("gev_metrics", "EvalGlobal");
model.result().numerical("gev_metrics").set("expr", new String[]{
    "min(liion.E_cell)",          // 最低电压
    "max(T)-273.15",              // 最高温度 (°C)
    "max(T)-min(T)",              // 最大温差
    "timeint(0,t_end,abs(I_app_var))/3600"  // 累积容量 (Ah)
});
model.result().numerical("gev_metrics").set("descr", new String[]{
    "min_voltage_V", "max_temp_C", "max_dT_K", "capacity_Ah"
});

// 创建Table
model.result().table().create("tbl_metrics", "Table");
model.result().numerical("gev_metrics").set("table", "tbl_metrics");
model.result().numerical("gev_metrics").setResult();

// 导出CSV
model.result().export().create("exp_metrics", "Table");
model.result().export("exp_metrics").set("table", "tbl_metrics");
model.result().export("exp_metrics").set("filename", "metrics.csv");
model.result().export("exp_metrics").set("header", true);
model.result().export("exp_metrics").run();

// 也导出时变曲线
model.result().export().create("exp_voltage", "Data");
model.result().export("exp_voltage").set("expr", new String[]{"liion.E_cell"});
model.result().export("exp_voltage").set("filename", "voltage_vs_time.csv");
model.result().export("exp_voltage").set("header", true);
model.result().export("exp_voltage").run();
```

### 4.2 备选: 求解后用 comsolbatch -methodcall

如果原 .java 没加导出代码,可以用 method call 后处理:

```bash
"<comsolbatch>" -inputfile result.mph \
                -methodcall "exportMetrics" \
                -methodcall-args "metrics.csv"
```

需要先在 .mph 里定义 method (本 skill 一般不用这条路径,直接路径4.1)。

### 4.3 解析 CSV 转 JSON

```python
import pandas as pd
import json

df = pd.read_csv("metrics.csv", encoding="gbk")  # Windows默认GBK
metrics = {row[0]: row[1] for _, row in df.iterrows()}
with open("metrics.json", "w") as f:
    json.dump(metrics, f, indent=2, ensure_ascii=False)
```

---

## 5. Debug 循环主流程

```
┌─────────────────────────────────────────┐
│ 1. 加载 acceptance_criteria.yaml         │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ 2. 生成/修改 .java                       │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ 3. comsolcompile → .class                │
│    失败 → 第2节错误库 → 修改 .java → 回 2 │
└─────────────────────────────────────────┘
                  │ 成功
                  ▼
┌─────────────────────────────────────────┐
│ 4. comsolbatch → .mph                    │
│    失败 → 第3节错误库 → 修改 .java → 回 2 │
└─────────────────────────────────────────┘
                  │ 成功
                  ▼
┌─────────────────────────────────────────┐
│ 5. 提取 metrics                          │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ 6. 对照 acceptance_criteria              │
└─────────────────────────────────────────┘
                  │
            ┌─────┴─────┐
        通过 │           │ 未通过
            │           │
            ▼           ▼
        STEP F     第6节物理调参 → 回 2
                  达到 max_iter → 报告失败终止
```

### 5.1 max_iterations 默认值

| 阶段 | 默认 max attempts | 理由 |
|---|---|---|
| 编译 (STEP C) | 8 | 编译错误多是语法/拼写,8 次足够 |
| 求解 (STEP D) | 5 | 求解失败多是数值问题,5 次内调出来或彻底失败 |
| 验收 (STEP E) | 8 | 物理调参可能多轮,8 次平衡探索 vs 时间 |
| **整体 wall-clock** | 2 hours | 防止失控 |

用户可在 STEP A 自定义这些上限。

### 5.2 物理调参映射 (验收不通过时如何改)

| 验收未通过项 | 物理含义 | 候选调参 (按影响排序) |
|---|---|---|
| 容量低于阈值 | 放电不充分 | 1. `Ds_pos` 调高 (LFP 扩散慢)<br>2. `k_pos` 调高 (反应速率)<br>3. 检查 `socinit_neg/pos` 与 OCV 边界对齐 |
| 容量高于阈值 | 模型放电过多 | `Ds_pos` / `k_pos` 调低,或检查截止电压设置 |
| 最高温度过高 | 散热不足 | 1. `h_amb` 调高 (对流系数)<br>2. 检查 `T_amb` 边界条件覆盖 |
| 端电压低于 V_min 终止 | 提前到 V_min | 检查 `socinit_pos` (太低就会快到截止),检查 `Crate` |
| 与实验数据 RMSE 过大 | 模型与实验偏差 | 1. OCV 函数微调 (如有实测 OCV 优先用插值)<br>2. `Ds`/`k` 系数校准 (Levenberg-Marquardt 反演,见 matlab_livelink) |
| 收敛失败 | 数值问题 | 见第3.2/3.3节 |

### 5.3 调参日志格式

每次调参记录到 `debug_history.json`:

```json
[
  {
    "iteration": 1,
    "phase": "solve",
    "outcome": "failed",
    "error": "Newton did not converge",
    "diagnosis": "LFP plateau region causing dV/dSOC≈0",
    "action": "set rtol from 1e-5 to 1e-4, change estrat to exclude",
    "files_modified": ["GeneratedModel.java line 234-238"]
  },
  {
    "iteration": 2,
    "phase": "acceptance",
    "outcome": "partial",
    "metrics": {"min_voltage": 2.6, "capacity_Ah": 275, "max_temp_C": 45.2},
    "criteria_failed": ["capacity_retention > 0.95: actual 0.98 PASS",
                         "min_voltage > 2.5: actual 2.6 PASS",
                         "rmse_vs_experiment < 0.05V: actual 0.08V FAIL"],
    "diagnosis": "OCV plateau in 0.3-0.7 SOC range shifted +20mV vs experiment",
    "action": "calibrate OCV_pos table offset by -20mV",
    "files_modified": ["GeneratedModel.java line 89 (OCV_pos function)"]
  }
]
```

报告生成器会读这个 JSON 渲染成 Debug 章节。

---

## 6. 安全护栏

### 6.1 时间预算管理

每次启动前估算:
- 编译: ~30s 每次
- 求解: 1D P2D 几十秒, P2D+热 几分钟, 3D 几十分钟
- 单次完整 cycle: 编译 + 求解 + 验证 ~ 几分钟

8 次迭代 × 几分钟 = 几十分钟。如果预估 > max_wall_clock,提前告诉用户。

### 6.2 文件保护

- **永远不覆盖**用户提供的参考 .java
- 每次迭代的 .java 保留 `GeneratedModel_iter_<N>.java`(可选,默认开)
- `result.mph` 每次覆盖,但中间状态保存到 `result_iter_<N>.mph`

### 6.3 License 错误

License 错误**禁止自动重试** — 可能是用户在 GUI 里开了模型占了名额。AI 应该:
1. 立即停止
2. 把 license 错误日志摘要给用户
3. 等待用户人工解决(关 GUI / 增加 license / 改时间)

### 6.4 长尾错误的兜底

如果遇到错误模式库和官方文档都解决不了的错误:
1. 把完整 stderr/run.log 摘要给用户
2. 列出已尝试的修复
3. 询问用户是否继续(可能需要人工介入)
4. 不要无意义地循环

---

## 7. 典型完整执行 (Pseudocode)

```python
# == STEP A: 对齐(假设已完成) ==
paths = {
    "comsolcompile": r"<COMSOL_ROOT>\bin\win64\comsolcompile.exe",
    "comsolbatch":   r"<COMSOL_ROOT>\bin\win64\comsolbatch.exe",
    "workdir":       r"D:\models\auto_sim_001"
}
criteria = load_yaml("acceptance.yaml")
max_iter = 8

# == STEP B: 生成 .java ==
java_path = generate_complete_java(task_spec, criteria, paths["workdir"])

# == STEP C-E: Debug 循环 ==
history = []
for iter in range(1, max_iter + 1):
    # 编译
    rc = compile_with_retry(java_path, comsolcompile=paths["comsolcompile"])
    if not rc.success:
        history.append({"iter": iter, "stage": "compile", "fail": rc.error})
        continue  # 编译里已经 retry 过,这里直接下一轮整体重试

    # 求解
    rs = solve_with_retry(java_path, comsolbatch=paths["comsolbatch"])
    if not rs.success:
        history.append({"iter": iter, "stage": "solve", "fail": rs.error})
        adjustment = suggest_solver_fix(rs.error)
        apply_to_java(java_path, adjustment)
        continue

    # 验证
    metrics = extract_metrics(rs.mph_path)
    eval_result = compare_with_criteria(metrics, criteria)
    history.append({"iter": iter, "metrics": metrics, "result": eval_result})
    if eval_result.all_passed:
        break  # 完成

    # 物理调参
    adjustment = suggest_physical_fix(eval_result.failed_criteria, metrics)
    apply_to_java(java_path, adjustment)

# == STEP F: 报告 ==
generate_report(
    java_path, rs.mph_path, metrics, criteria, history,
    out_path=os.path.join(paths["workdir"], "simulation_report.docx")
)
```

完整实现见 `examples/scripts/comsol_batch_runner.py`。

---

## 8. 已知局限与待实测项 (诚实清单)

本 skill 的 Autonomous Mode 在**没有真实 COMSOL 环境**的情况下编写,以下几点**首次部署时必须在你的 COMSOL 6.4 上验证**:

### 8.1 执行模型: class vs comsolbatch (重要)

本文档第 2-3 节同时给了两条路径,但它们的衔接需要实测确认:

- 如果 .java 的 `main()` 里已写 `study.run()` + `model.save()`,那么**直接运行这个 class 就会求解并存 mph**,理论上不需要再用 `comsolbatch -inputfile`。
- `comsolbatch -inputfile xxx.class` 这个用法在不同 COMSOL 版本行为不同。更可靠的方式可能是:
  - 方式1: `comsolbatch -inputfile model.mph`(先用别的方式生成 mph)
  - 方式2: 直接 `"<comsol>/bin/win64/comsol.exe" batch -inputfile GeneratedModel.class`
  - 方式3: 用 `comsolcompile` 编译后,`java -cp "<plugins>/*;." GeneratedModel`(靠 main 自驱动)

**首次使用请先手动验证哪条路径在你的环境可行**,然后据此微调 `comsol_batch_runner.py` 的 `solve_with_comsolbatch()` 命令构造。脚本里的 `-inputfile GeneratedModel.class` 是占位实现。

### 8.2 metrics.csv 格式

`comsol_batch_runner.py` 的 `load_metrics()` 假设 metrics.csv 是"单行多列、列名=指标名、UTF-8 或 GBK 编码"。但 COMSOL `EvalGlobal` + `export Table` 实际导出的 CSV 可能:
- 带 `%` 注释头行
- 列名是表达式本身而非 descr
- 数值用科学计数法或带单位

**首次跑通后,检查 metrics.csv 实际格式**,必要时调整 `load_metrics()` 的解析(跳过注释行、列名映射)。

### 8.3 complete_model_template.md 的 golden 模板

模板基于 COMSOL Java API 惯例编写,**节点顺序和结构是对的**,但部分属性键名(如 `epss`/`epsl`/`phis_max`/停止条件语法)只能在真实环境验证。首次预计 1-3 轮 debug 修属性键名。这是正常的,不是模板的缺陷 —— 它的价值在于省去从零拼装的结构性错误。

### 8.4 OCV 函数

模板里的 Analytic OCV 是**示意性拟合**(`3.42 + 0.05*tanh(...)`),不是真实 LFP 实测曲线。正式仿真**必须替换为你的实测 OCV**(用方式B Interpolation 从 CSV 读),否则容量和电压平台会与实验有偏差。

### 8.5 这些局限如何影响使用

- Autonomous Mode **首次跑某类模型时**,把它当"AI 辅助的半自动",盯着前几轮
- 一旦某类模型在你的环境跑通,把**确认可用的 .java 存为该类任务的 golden 模板**,后续同类任务直接复用,真正全自动
- 即: skill 提供"冷启动脚手架",你的环境验证沉淀出"热启动模板"
