# LLM Research OS

> 当前名称为临时工作名，正式名称将在公开发布前通过 ADR 确认。

LLM Research OS 是一个独立、开源、模型无关、训练后端无关、算力供应商无关的 LLM 研究操作系统。它用于表达研究问题、组合实验、让 AI 提出并反驳方案、在本地或远程 Worker 上执行，并记录训练、评测、系统、成本、血缘与 AI 决策。

## 当前状态

项目宪章 v0.1 及第 18 章技术基线已经接受。M0 已完成 ResearchSpec、ResearchEvent
协议基础、纯静态规划内核、SQLite 追加式事件事实源、本地内容寻址制品对象层、纯
Run/Attempt 状态机、在写入前预检并做全局 CAS 的 RunControl 边界，以及无需 GPU
与网络的确定性 SimulatedRuntime 纵向闭环，以及绑定三摘要、逐项能力/权限/审批的纯计划
授权门；现在也可通过严格版本化请求和 CLI 创建或
恢复该模拟 Run，为既有 Run 或 active Attempt 追加显式取消请求，并通过 CLI 导入或
完整校验本地内容寻址制品对象。当前仍不执行任何训练任务或真实 GPU 工作负载，也不会
把取消请求误报为已停止。

## M0 目标

1. 编写短版 ADR 与持续更新的威胁模型；
2. 定义 `ResearchSpec v0alpha1` 的 Pydantic 模型；
3. 生成版本化 JSON Schema，并提供正反例；
4. 实现验证器与语义差异；
5. 定义 CloudEvents 兼容的 `ResearchEvent`；
6. 建立 SQLite 最小事实源与 `SimulatedRuntime`；
7. 在无 GPU 条件下跑通首个纵向闭环。

## 已接受基线

- Python 3.12+、`pyproject.toml`、uv；
- Pydantic 是 M0 编写入口，版本化 JSON Schema 是对外契约；
- 追加式事件、可重建投影与内容寻址制品；
- 独立 Research IR，不附属于 NeMo、ms-swift 或任何 Agent 框架；
- 研究者默认拥有最终决定权，AI 可以并应当提交异议；
- 任何真实 GPU 消费、外部账户操作或不可逆操作仍需单独批准。

## 项目文档

- [项目宪章与最小内核规格 v0.1](docs/charter-v0.1.md)
- [第 18 章决策指南与确认记录 v0.1](docs/chapter-18-decision-guide-v0.1.md)
- [ResearchSpec v0alpha1规范说明](docs/protocols/research-spec-v0alpha1.md)
- [ResearchEvent v0alpha1规范说明](docs/protocols/research-event-v0alpha1.md)
- [BlockManifest v0alpha1规范说明](docs/protocols/block-manifest-v0alpha1.md)
- [DryRunReport v0alpha1规范说明](docs/protocols/dry-run-report-v0alpha1.md)
- [Block 命令报告 v0alpha1](docs/protocols/block-command-report-v0alpha1.md)
- [ProblemReport v0alpha1](docs/protocols/problem-report-v0alpha1.md)
- [参考摘要约定 v0alpha1](docs/protocols/digest-v0alpha1.md)
- [Run/Attempt 状态 v0alpha1](docs/protocols/run-attempt-state-v0alpha1.md)
- [SimulationRequest v0alpha1](docs/protocols/simulation-request-v0alpha1.md)
- [RunCancellationRequest v0alpha1](docs/protocols/run-cancellation-request-v0alpha1.md)
- [ArtifactObjectReport v0alpha1](docs/protocols/artifact-object-report-v0alpha1.md)
- [静态规划内核导读](docs/guides/m0-static-planning.md)
- [M0 SQLite事件存储导读](docs/guides/m0-event-store.md)
- [M0 本地制品存储导读](docs/guides/m0-artifact-store.md)
- [M0 RunControl 导读](docs/guides/m0-run-control.md)
- [M0 确定性计划授权门](docs/guides/m0-plan-authorization.md)
- [M0 SimulatedRuntime 导读](docs/guides/m0-simulated-runtime.md)
- [M0 Simulated Run CLI](docs/guides/m0-simulated-run-cli.md)
- [M0 Run Cancellation CLI](docs/guides/m0-run-cancellation-cli.md)
- [架构决策记录](docs/adr/README.md)
- [持续威胁模型](docs/security/threat-model.md)

## 本地开发

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。训练后端不安装到核心控制面环境中。

```bash
uv sync --locked --all-groups
uv run researchos validate examples/valid/minimal.yaml
uv run researchos blocks list
uv run researchos dry-run examples/valid/minimal.yaml
uv run researchos schema --check schemas/research-spec/v0alpha1.schema.json
uv run researchos schema --contract research-event \
  --check schemas/research-event/v0alpha1.schema.json
uv run researchos schema --contract run-state \
  --check schemas/run-state/v0alpha1.schema.json
uv run researchos schema --contract simulation-request \
  --check schemas/simulation-request/v0alpha1.schema.json
uv run researchos schema --contract run-cancellation-request \
  --check schemas/run-cancellation-request/v0alpha1.schema.json
uv run researchos schema --contract artifact-object-report \
  --check schemas/artifact-object-report/v0alpha1.schema.json
uv run ruff check .
uv run mypy src
uv run pytest
```

生成的 JSON Schema 是第三方实现使用的语言中立契约：

```text
schemas/research-spec/v0alpha1.schema.json
schemas/research-event/v0alpha1.schema.json
schemas/block-manifest/v0alpha1.schema.json
schemas/block-command-report/v0alpha1.schema.json
schemas/dry-run-report/v0alpha1.schema.json
schemas/problem-report/v0alpha1.schema.json
schemas/run-state/v0alpha1.schema.json
schemas/simulation-request/v0alpha1.schema.json
schemas/run-cancellation-request/v0alpha1.schema.json
schemas/artifact-object-report/v0alpha1.schema.json
```

不要手工编辑这些文件。修改 Pydantic 编写模型后，使用对应的 `--contract` 选项重新生成并审查协议差异：

```bash
uv run researchos schema --output schemas/research-spec/v0alpha1.schema.json
```

## 静态 dry-run

```bash
uv run researchos dry-run examples/valid/minimal.yaml --format json
```

`ready`只表示规范、积木解析、端口、资源和静态计划完整，不表示实验已批准、
已执行或科学上正确。循环不会展开，`until`不会求值，配置与审批正文只以摘要进入报告。

附加积木清单只能从用户明确提供的普通 YAML/JSON 文件或非递归目录读取：

```bash
uv run researchos blocks validate examples/manifests/example-train.yaml
uv run researchos dry-run examples/valid/bounded-loop.yaml \
  --registry examples/manifests/example-train.yaml
```

## 计划授权门

`authorize_plan` 对 ready report 重新做语义校验，并把授权策略同时绑定到
`specDigest`、`registryDigest` 与 `planDigest`。声明的 capability/permission 必须精确授予，
planner 产生的每个 requirement 必须显式批准；缺权限或拒绝得到 `denied`，尚缺审批得到
`pending`，只有 `authorized` 可进入执行路径。它不认证审批者、不持久化决定，也不产生事件或
运行时副作用。详见 [M0 确定性计划授权门](docs/guides/m0-plan-authorization.md)。

## 事件查询与回放

只读命令打开既有 SQLite 数据库，不会在路径缺失时创建文件，也不会追加事件：

```bash
uv run researchos events get research.db evt.example.1 --format json
uv run researchos events list research.db --after-sequence 0 --limit 100
uv run researchos events replay research.db --page-size 100
uv run researchos events verify research.db --format json
```

`replay` 输出 JSON Lines，并在开始时冻结高水位，因此执行期间追加的新事件不会进入本次结果。

## RunControl

`RunControl` 在 EventStore 写入前用冻结的全局 head 回放并预检 Run/Attempt 生命周期事件，
再用 `expected_last_sequence` 做全局 CAS。它不生成 `id`/`time`/`streamid`，不自动重试
conflict，也不执行任何积木。CAS 失败后必须由调用者再次 `append`，以重新回放和验证。

## SimulatedRuntime

`SimulatedRuntime` 对冻结的 ResearchSpec 快照重新 dry-run，通过固定的 T0 `simulate`
capability 策略调用计划授权门，并仅当计划是单个
`simulated.experiment@0.1.0` 且 config 显式给出 `outcome` 时，才通过 RunControl
追加 Run/Attempt 生命周期事件。`id`/`time`/`streamid` 仍由调用方提供；conflict
不会自动重试；`unknown` 不会被收敛成 failure 或 success。模拟 `completed` 只表示
受控生命周期结束，不表示训练成功或假设成立。最小可运行示例见
[M0 SimulatedRuntime 导读](docs/guides/m0-simulated-runtime.md)。

命令行纵向闭环使用单独的显式请求文件；不会生成 `id`、`time` 或 `streamid`：

```bash
uv run researchos runs simulate \
  examples/valid/minimal.yaml \
  examples/simulation-requests/valid/success.json \
  research.db --format json
```

JSON stdout 是已发布 Schema 约束的 `RunSnapshot`。退出码 `0` 仅表示模拟生命周期
`completed`；`failed`、`unknown`、`unresolved` 返回 `1`，输入、完整性或并发错误返回
`2`。可随后用 `events verify` / `events replay` 独立检查事实。

取消一个既有 Run 或 active Attempt 必须使用另一份显式请求。命令只追加
`*.cancel.requested` 事实，不发送进程信号，也不生成 `*.cancelled` 结果：

```bash
uv run researchos runs cancel \
  examples/run-cancellation-requests/valid/run.json \
  research.db --format json
```

数据库必须已经存在；缺失路径不会被创建。退出码 `0` 仅说明取消请求事实已提交，
应检查返回的 `RunSnapshot.cancellationRequested`，不能据此声称任务已经停止。

本地制品对象根目录必须预先创建。导入与完整校验都返回版本化对象报告，不打印对象正文：

```bash
mkdir -m 700 artifacts
uv run researchos artifacts put artifacts checkpoint.bin --format json
uv run researchos artifacts verify artifacts \
  sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --format json
```

`put` 不覆盖摘要冲突的既有对象；`verify` 会完整重算摘要且不会修复损坏。两者都不写
SQLite、不发 ResearchEvent，也不赋予对象 project/Run、media type 或 URI 语义。

## 当前安全边界

M0 当前验证协议和差异、编译无副作用的静态计划，并以绑定三摘要的纯授权门逐项拒绝未授予的
capability、permission 或 approval；可向本地 SQLite 追加、查询和回放事件事实，
可将常规本地文件导入内容寻址制品目录，可通过 RunControl 在写入前拒绝非法生命周期事件，
并可通过 SimulatedRuntime 对单个内置 simulated task 追加确定性生命周期事实。
`runs simulate` 只把严格的本地请求交给这条现有边界，且不自动重试冲突。
`runs cancel` 同样只通过 RunControl 追加单个请求事实，要求既有数据库，且不发送信号或
推断取消结果。
`artifacts put` / `verify` 只复用本地对象层，既不输出对象正文，也不建立索引或血缘。
它不导入积木入口点，不执行任意训练代码、表达式、插件或远程 Worker，不写 SQLite 制品索引
或持久化投影，也不提供对象导出/删除、实际停止适配器、NativeProcessRuntime 或网络上传。
模拟 `completed` 不是科学成功；`unknown` 保持未决。
任何真实 GPU 消费、外部账户操作或不可逆操作仍需单独批准。安全问题请参阅
[安全政策](SECURITY.md)。

## License

Apache License 2.0. See [LICENSE](LICENSE).
