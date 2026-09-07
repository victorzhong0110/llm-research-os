# LLM Research OS（中文）

> 本文是 [README.md](README.md) 的中文版。英文版是权威文本，两者随同一 PR 更新（[ADR-0040](docs/adr/0040-english-primary-and-engineering-standards.md)）。
>
> 当前名称为临时工作名，正式名称将在公开发布前通过 ADR 确认。

LLM Research OS 是一个独立、开源、模型无关、训练后端无关、算力供应商无关的 LLM 研究操作系统。它用于表达研究问题、组合实验、让 AI 提出并反驳方案、在本地或远程 Worker 上执行，并记录训练、评测、系统、成本、血缘与 AI 决策。

它服务于人类的帮助对 AI 仍然必要的时期：把研究者提供的信息与授权做成便宜、高信息量、可持久、可审计的事实，研究者是教师而不只是审批者（[ADR-0039](docs/adr/0039-human-help-period-purpose.md)）。

## 当前状态

项目宪章 v0.1 及第 18 章技术基线已经接受。**M0 内核证明已于 2026-09-03 收口**，范围见
[ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)；原生进程里程碑勘误见
[ADR-0034](docs/adr/0034-m0-scope-clarification.md)。收口后的宪章勘误、M0 债务登记，以及
M1 的切片顺序、安全门、检查点与预算见 [ADR-0038](docs/adr/0038-charter-errata-after-m0.md)
与宪章 §23 勘误表。M1-1 研究决定对象见
[research-decision-objects-v0alpha1](docs/protocols/research-decision-objects-v0alpha1.md)。
M1-0 已在本树交付：schema v2 可重建查询表与已校验高水位缓存（[ADR-0041](docs/adr/0041-verified-high-water-cache-and-query-tables.md)）、类型化 [`SecretRef`](docs/protocols/secret-ref-v0alpha1.md)、可选的 ResearchEvent actor `kind` / `modelId`，以及 SimulatedRuntime 产出 `attempt.cancelled` / `run.cancelled`。M1-1 交付 `proposal.submitted` / `dissent.recorded` / `decision.recorded`、可重建 `ResearchLedger` 与对应 CLI。M1-2 交付 [`ModelProvider`](docs/adr/0017-minimal-model-interface.md)、确定性 mock 与仅存摘要的 `ai.call.*` 事实（事件中不内嵌 prompt/output）。M1-3 交付本地 Markdown/PDF 导入为 `evidence.imported`，默认 `LicenseRef-Unknown`。PDF 抽取在子进程中受页数、字符数与墙钟上限约束，且只继承最小环境。M1-4 交付 OpenAI 兼容 HTTP 适配器（默认回环），由 `SecretRef`、`read.external_api`、HTTPS、远端正数 CNY 上限/预留，以及原子 reserve-or-exceed 预算门控。M1-5 交付由 SimulatedRuntime 写出的种子化合成 `training.step` / `evaluation.metric` 事实，以及 `researchos report RUN` 静态 HTML/Markdown（React Flow 延后）。M1-6 让 SimulatedRuntime 按 `{eventId, sequence}` 消费本机 `plan.authorization.evaluated` 事实（[ADR-0042](docs/adr/0042-m1-local-authorization-consume-and-closure.md)），这不是签名启动凭证。Issue #19 的本机消费已交付；签名、过期与吊销见 Issue #53。提问通道为 `question.asked` / `question.answered`，命令为 `questions ask` / `questions answer`。`researchos m1 prove` 记录一条离线语料链（Mock 提案到模拟报告，或拒绝且不排队 Run）。伞形 #38 仍开放。编号切片不是 M1 检查点。M2-0 是免费回环 Worker CPU 闭环（[ADR-0043](docs/adr/0043-m2-loopback-worker-and-hmac-grants.md)）：带过期/吊销的 HMAC 授权绑定已授权的 `execute.local` 积木、CAS 钉死的 python 助手、制品与报告。独立控制面与 Worker 进程使用钉死的回环 HTTPS（[ADR-0044](docs/adr/0044-isolated-control-plane-and-loopback-https.md)），这不是跨机器证明。CPU OCIContainerRuntime 是按摘要钉死的 docker 适配器（[ADR-0045](docs/adr/0045-cpu-oci-container-runtime.md)）；缺少引擎时失败关闭，不得表述为容器实测成功。Worker 停止/故障恢复见 [ADR-0046](docs/adr/0046-worker-stop-fault-recovery.md)：取消请求不是已停止；完成事实与 Run/Attempt 必须对账；未知执行不得自动标成功。这不是 GPU 完成，不是 NativeProcessRuntime，不是内核沙箱，也不是 Issue #38。

已交付能力包括：ResearchSpec / ResearchEvent / BlockManifest 协议基础、纯静态规划内核、
SQLite 追加式事件事实源与可重建查询表、本地内容寻址制品对象层、纯 Run/Attempt 状态机、写入前预检并做
全局 CAS 的 RunControl、无需 GPU 与网络且可消费取消请求的确定性 SimulatedRuntime、绑定三摘要的计划授权门、
非凭证授权 CLI、仅审计的求值事件、只读 lineage、进程内 `decisionDigest`、SimulatedRuntime 对本机 `{eventId, sequence}` 的消费、显式模拟 Run /
取消请求 / 制品对象 / 研究决定 / mock 模型调用 / 资料导入 / OpenAI 兼容 / 静态报告 / M1 检查点 CLI，不可启动的 NativeProcessPreflight，以及回环 Worker 注册 / HMAC 授权 / `researchos m2 prove`（宿主 Python 助手不是 NativeProcessRuntime，也不是内核沙箱）与失败关闭的 CPU OCI 适配器和 `researchos m2 bench`（1 万/10 万事件耗时，不是 SLA）。

当前仍不执行任何训练任务或真实 GPU 工作负载。授权事件、预检报告、lineage 重建与
`decisionDigest` 都不是签名回执或启动许可。SimulatedRuntime 会消费本机 EventStore 上
一条 `{eventId, sequence}` 引用（ADR-0042）；lineage 仍为 `not-consumed`。取消请求 CLI 仍不发送进程信号；
观察到的 cancelled 结果是随后 SimulatedRuntime 写出的事实。真实 NativeProcessRuntime、非回环 Worker、付费 GPU 与 JWT 启动凭证均不属于 M0 或 M1 已交付能力。M2-0 回环 CPU 已在树中（ADR-0043）。独立回环 HTTPS 是 ADR-0044，不是跨机器 Worker。远程 Worker 传输是 ADR-0021：验收包标 `pending-live`，回环 URL 不是跨机器证明。CPU OCI 是 ADR-0045，不是 GPU 实测。指定的 Linux OCI CI（ADR-0049）不得靠 skip 过关；无 docker 的普通开发环境可以跳过 `oci_live`。Worker 停止/故障恢复是 ADR-0046。观察到的执行身份与取消监督是 ADR-0050：`cancel-observed` 必须确认进程或容器已退出。真实 CPU 故障验收是 ADR-0051：`plane.fail` 不是观察到的停止。EventStore 性能基线是 ADR-0047。Worker/RunControl 使用证据是 ADR-0052：`m2 usage` 不是 `EventStore.append` 填充。GPU 实验单是 ADR-0053：已点名 AutoDL 4090 与 ¥20 上限，未执行、未花费。进程观察是 ADR-0054：running/exited/unknown，探测失败不得推断已退出。钉死的 ms-swift 解析/计划适配器是 ADR-0048，不是 GPU 实测。

## M0 目标

下列历史目标已由 [ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md) 收口；条目保留为当时的验收清单。

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
- [Research decision objects v0alpha1](docs/protocols/research-decision-objects-v0alpha1.md)
- [SecretRef v0alpha1](docs/protocols/secret-ref-v0alpha1.md)
- [ModelProvider / ai.call v0alpha1](docs/protocols/model-provider-v0alpha1.md)
- [Evidence import v0alpha1](docs/protocols/evidence-import-v0alpha1.md)
- [OpenAI-compatible generate / budget v0alpha1](docs/protocols/openai-compat-v0alpha1.md)
- [Synthetic metrics and static Run report v0alpha1](docs/protocols/run-report-v0alpha1.md)
- [BlockManifest v0alpha1规范说明](docs/protocols/block-manifest-v0alpha1.md)
- [DryRunReport v0alpha1规范说明](docs/protocols/dry-run-report-v0alpha1.md)
- [Block 命令报告 v0alpha1](docs/protocols/block-command-report-v0alpha1.md)
- [ProblemReport v0alpha1](docs/protocols/problem-report-v0alpha1.md)
- [语义内容摘要 v0alpha1](docs/protocols/digest-v0alpha1.md)
- [Run/Attempt 状态 v0alpha1](docs/protocols/run-attempt-state-v0alpha1.md)
- [SimulationRequest v0alpha1](docs/protocols/simulation-request-v0alpha1.md)
- [RunCancellationRequest v0alpha1](docs/protocols/run-cancellation-request-v0alpha1.md)
- [ArtifactObjectReport v0alpha1](docs/protocols/artifact-object-report-v0alpha1.md)
- [PlanAuthorizationRequest/Report v0alpha1](docs/protocols/plan-authorization-v0alpha1.md)
- [PlanAuthorizationEventRequest v0alpha1](docs/protocols/plan-authorization-event-v0alpha1.md)
- [PlanAuthorizationLineageQuery/Report v0alpha1](docs/protocols/plan-authorization-lineage-v0alpha1.md)
- [NativeProcessPreflightRequest/Report v0alpha1](docs/protocols/native-process-preflight-v0alpha1.md)
- [静态规划内核导读](docs/guides/m0-static-planning.md)
- [M0 SQLite事件存储导读](docs/guides/m0-event-store.md)
- [M0 本地制品存储导读](docs/guides/m0-artifact-store.md)
- [M0 RunControl 导读](docs/guides/m0-run-control.md)
- [M0 确定性计划授权门](docs/guides/m0-plan-authorization.md)
- [M0 显式计划授权 CLI](docs/guides/m0-plan-authorization-cli.md)
- [M0 计划授权求值事件](docs/guides/m0-plan-authorization-events.md)
- [M0 计划授权血缘查询](docs/guides/m0-plan-authorization-lineage.md)
- [M0 Native Process Preflight](docs/guides/m0-native-process-preflight.md)
- [M0 SimulatedRuntime 导读](docs/guides/m0-simulated-runtime.md)
- [M0 Simulated Run CLI](docs/guides/m0-simulated-run-cli.md)
- [M0 Run Cancellation CLI](docs/guides/m0-run-cancellation-cli.md)
- [M1 研究决定 CLI](docs/guides/m1-research-decisions.md)
- [M1 ModelProvider mock CLI](docs/guides/m1-model-provider.md)
- [M1 资料导入 CLI](docs/guides/m1-evidence-import.md)
- [M1 OpenAI 兼容 generate CLI](docs/guides/m1-openai-compat.md)
- [M1 合成指标与静态 Run 报告](docs/guides/m1-run-report.md)
- [M1 检查点 CLI](docs/guides/m1-checkpoint.md)
- [Worker protocol v0alpha1](docs/protocols/worker-v0alpha1.md)
- [Authorization grant v0alpha1](docs/protocols/authorization-grant-v0alpha1.md)
- [M2 Worker CLI](docs/guides/m2-worker.md)
- [M2 CPU OCI](docs/guides/m2-oci.md)
- [M2 GPU 切片（仅方向）](docs/guides/m2-gpu-slice.md)
- [首次实验](docs/guides/first-experiment.md)
- [架构决策记录](docs/adr/README.md)
- [持续威胁模型](docs/security/threat-model.md)
- [工程规范](docs/engineering-standards.md)（英文）
- [Changelog](CHANGELOG.md)
- [参与贡献](CONTRIBUTING.zh-CN.md)

## 本地开发

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。训练后端不安装到核心控制面环境中。

```bash
uv sync --locked --all-groups
uv run researchos validate examples/valid/minimal.yaml
uv run researchos blocks list
uv run researchos dry-run examples/valid/minimal.yaml
uv run researchos schema --check-all
uv run ruff check .
uv run mypy src
uv run pytest --cov=llm_research_os --cov-fail-under=85
node conformance/digest/verify.mjs
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
schemas/plan-authorization-request/v0alpha1.schema.json
schemas/plan-authorization-report/v0alpha1.schema.json
schemas/native-process-preflight-request/v0alpha1.schema.json
schemas/native-process-preflight-report/v0alpha1.schema.json
```

不要手工编辑这些文件。`researchos schema --check-all` 按 CLI 契约注册表校验全部已提交
schema；新增契约只需在 `src/llm_research_os/cli/contracts.py` 登记一处。修改 Pydantic
编写模型后，使用对应的 `--contract` 选项重新生成并审查协议差异：

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

外部调用者可用版本化请求对当前输入重新生成的精确计划求值：

```bash
uv run researchos authorize \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  --format json
```

`authorized` 返回 `0`，有效的 `pending`/`denied` 返回 `1`，输入或摘要绑定错误返回 `2`。
报告固定声明 `not-authenticated`、`not-persisted` 与 `not-executed`；它不是签名或可撤销的授权
回执。详见 [M0 显式计划授权 CLI](docs/guides/m0-plan-authorization-cli.md)。

需要追加式审计时，可用另一份严格请求把重新计算的结果记录到已经存在的 EventStore：

```bash
uv run researchos authorizations record \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  examples/plan-authorization-events/valid/minimal.json \
  research.db --format json
```

该命令先完整验证事件库，再以全局 head CAS 追加一个
`plan.authorization.evaluated`；`authorized` 返回 `0`，已记录的 `pending`/`denied` 返回 `1`，
输入、完整性或并发错误返回 `2`。事件明确声明 `not-authenticated`、`audit-only` 与
`not-executed`，因此是可回放的审计事实而不是 runtime 凭证。详见
[M0 计划授权求值事件](docs/guides/m0-plan-authorization-events.md)。

同一份计划身份可再通过只读查询重建匹配的审计事实，而不把它们升格为 Run 引用或启动凭证：

```bash
uv run researchos authorizations find \
  examples/plan-authorization-lineage/valid/minimal.json \
  research.db --format json
```

成功退出 `0` 只表示已冻结的事件前缀被重建；`matchCount` 可以为 `0`。报告固定声明
`not-authenticated`、`audit-only`、`not-executed` 与 `not-consumed`。详见
[M0 计划授权血缘查询](docs/guides/m0-plan-authorization-lineage.md)。

## 原生进程预检

单个、已授权的 Python task 可进入纯预检，但不能进入进程执行：

```bash
uv run researchos native preflight \
  examples/native-process-preflight/spec.yaml \
  examples/native-process-preflight/authorization-request.json \
  examples/native-process-preflight/preflight-request.json \
  --registry examples/native-process-preflight/manifest.yaml \
  --format json
```

预检重新验证 ready plan、密封 registry、三摘要授权和授权决定摘要，只接受固定 JSON-stdio
runner、`shell=false`、network denied、空环境 allowlist、隔离临时 workspace 请求及有界输出/超时。
成功退出 `0` 只表示报告可复核；报告固定为 `launchAllowed=false`、
`isolation=not-enforced`、`execution=not-executed`，入口点仅以摘要出现。命令不解析解释器、导入
模块、创建 workspace、启动进程、发信号或写入持久存储。详见
[M0 Native Process Preflight](docs/guides/m0-native-process-preflight.md)。

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
capability 策略调用计划授权门，消费所引用的本机授权行，并仅当计划是单个
`simulated.experiment@0.1.0` 且 config 显式给出 `outcome` 时，才通过 RunControl
追加 Run/Attempt 生命周期事件。`id`/`time`/`streamid` 与授权引用仍由调用方提供；conflict
不会自动重试；`unknown` 不会被收敛成 failure 或 success。模拟 `completed` 只表示
受控生命周期结束，不表示训练成功或假设成立。先创建 EventStore、记录授权事实，再模拟。最小可运行示例见
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

一条命令记录 M1 检查点所要求的离线研究链。它不会关闭 Issue #38：

```bash
uv run researchos m1 prove \
  examples/m1-checkpoint \
  research.db \
  --format json
```

`--decision reject` 记录同样的研究事实，且不得排队 Run。
见 [M1 检查点 CLI](docs/guides/m1-checkpoint.md)。

一条命令记录回环 Worker CPU 闭环（CAS 积木、制品、报告）。它不花费 GPU，也不会关闭 Issue #38：

```bash
uv run researchos m2 prove \
  examples/m2-checkpoint \
  research.db \
  --format json
```

见 [M2 Worker CLI](docs/guides/m2-worker.md)、
[M2 CPU OCI](docs/guides/m2-oci.md)、
[M2 性能基线](docs/guides/m2-perf.md) 与
[首次实验](docs/guides/first-experiment.md)。

研究提案、异议、决定与提问是独立的 EventStore 事实。数据库必须已存在。`accept` 不是启动凭证。回答是带权利的数据，不是指令：

```bash
uv run researchos proposals submit \
  examples/research-decisions/valid/proposal-submit.json \
  research.db --format json
uv run researchos dissents record \
  examples/research-decisions/valid/dissent-record.json \
  research.db --format json
uv run researchos decisions record \
  examples/research-decisions/valid/decision-record.json \
  research.db --format json
uv run researchos questions ask \
  examples/research-decisions/valid/question-ask.json \
  research.db --format json
uv run researchos questions answer \
  examples/research-decisions/valid/question-answer.json \
  research.db --format json
uv run researchos research ledger research.db \
  --project example-minimal --format json
```

确定性 mock 模型调用写成一对 EventStore 事实。prompt 与 output 正文留在 fixture 文件中：

```bash
uv run researchos models generate \
  examples/model-generate-requests/valid/generate.json \
  research.db \
  --fixture examples/model-fixtures/valid/generate-json.json \
  --format json
```

OpenAI 兼容本地服务器是默认 HTTP 路径（上限 `0.00` CNY）。prompt 与 completion 不写入事件；预算事实会入账：

```bash
uv run researchos models generate \
  examples/openai-compat-requests/valid/local.json \
  research.db \
  --fixture examples/model-fixtures/valid/compat-local.json \
  --format json
```

本地 Markdown 或 PDF 笔记成为 `evidence.imported` 事实。文件路径与抽取正文不写入事件。PDF 抽取在子进程中受页数、字符数与墙钟上限约束，且只继承最小环境：

```bash
mkdir -m 700 artifacts
uv run researchos evidence import \
  examples/evidence/valid/import-markdown.json \
  research.db \
  --source examples/evidence/sources/eval-split.md \
  --artifacts artifacts \
  --format json
```

成功路径的 SimulationRequest 也可提供 `training.step` 与 `evaluation.metric` 身份。报告是静态投影：

```bash
uv run researchos report run.simulated \
  --database research.db \
  --format markdown
```

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

M0 内核证明已收口（[ADR-0037](docs/adr/0037-m0-kernel-proof-closure.md)）。下列边界仍是当前代码的安全事实，不因收口而消失。

M0 当前验证协议和差异、编译无副作用的静态计划，并以绑定三摘要的纯授权门逐项拒绝未授予的
capability、permission 或 approval；可向本地 SQLite 追加、查询和回放事件事实，
可将常规本地文件导入内容寻址制品目录，可通过 RunControl 在写入前拒绝非法生命周期事件，
并可通过 SimulatedRuntime 对单个内置 simulated task 追加确定性生命周期事实。
`authorize` 只重新构造静态计划并输出明确非凭证的版本化求值报告，不写事件、制品或数据库。
`authorizations record` 可向既有事件库追加精确四摘要绑定的求值事实，但 actor 仍未认证，事件
只具有审计意义，任何 runtime 都不能据此启动。
`native preflight` 只冻结单 task 的固定进程审查形状，明确禁止启动且不实施所声明的隔离。
`runs simulate` 只把严格的本地请求交给这条现有边界，且不自动重试冲突。
`runs cancel` 同样只通过 RunControl 追加单个请求事实，要求既有数据库，且不发送信号或
推断取消结果。
`artifacts put` / `verify` 只复用本地对象层，既不输出对象正文，也不建立索引或血缘。
`models generate` 把仅含摘要的 `ai.call.*` 事实写入既有库。mock 路径不打开网络。
OpenAI 兼容路径默认回环且上限 `0.00` CNY；远端端点需要 `SecretRef`、`read.external_api`、HTTPS、
已记录的项目 CNY 上限，以及与该上限一致的请求 cap。派发后结果不确定时保留预留。
`researchos m1 prove` 从语料向空库记录一条研究链；它不会关闭 Issue #38。
`researchos m2 prove` 从语料记录一条回环 Worker CPU 闭环；它不花费 GPU，不是内核沙箱，也不会关闭 Issue #38。
`researchos m2 oci` 在本机已有按摘要钉死的镜像时记录 CPU OCI 闭环；否则失败关闭，不得表述为容器实测成功。普通环境可以跳过 `oci_live`；GitHub 作业 `Linux OCI integration` 必须失败关闭。
`researchos m2 bench` 记录 1 万或 10 万事件的 EventStore 耗时；它不是 SLA，也不花费 GPU。`researchos m2 usage` 走 Worker/RunControl 路径，不是这次填充。
`researchos training plan` 打印钉死的 `swift sft` argv，且不得执行；它不是真实训练。
`researchos workers serve` / `workers run` 把该闭环拆成两个进程、经钉死的回环 HTTPS 通信；它们不证明远端 Worker。取消监督记录进程或容器身份并确认退出；它不停止云实例。
`evidence import` 把本地 Markdown/PDF 快照写入 CAS 并追加仅含摘要的 `evidence.imported`；
PDF 抽取在子进程中设上限且不继承进程密钥；未知权利不能授权训练。
`report` 重建静态 HTML 或 Markdown 投影；它不是事实源。
它不导入积木入口点，不执行任意训练框架、表达式、插件或非回环 Worker，不写 SQLite 制品索引
或持久化投影，也不提供对象导出/删除、真实 GPU 停止适配器、可执行的 NativeProcessRuntime 或训练制品网络上传。
模拟 `completed` 不是科学成功；`unknown` 保持未决。
任何真实 GPU 消费、外部账户操作或不可逆操作仍需单独批准。安全问题请参阅
[安全政策](SECURITY.md)。

## License

Copyright 2026 victorzhong0110.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
