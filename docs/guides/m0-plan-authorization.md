# M0 确定性计划授权门

## 它解决什么问题

`dry-run: ready` 只说明静态计划完整，不说明研究者或策略已经允许执行。计划中积木声明的
`capabilities`、`permissions` 以及 `policyRequirements` 都必须在可信内核中逐项求值，
低层 runtime 或 adapter 不能自行把它们解释成授权。

M0 的 `authorize_plan` 是一个纯、确定性的计划绑定门：输入同一份 ready report 和同一份
精确策略，得到同一个结果与 `decision_digest`，且不产生任何外部副作用。

## 最小使用

```python
from llm_research_os.blocks import build_registry
from llm_research_os.execution import (
    PlanAuthorizationPolicy,
    TrustedKernel,
    authorize_plan,
)
from llm_research_os.spec import load_spec

report = TrustedKernel(build_registry()).dry_run(load_spec("examples/valid/minimal.yaml"))
assert report.digests.plan is not None

policy = PlanAuthorizationPolicy(
    spec_digest=report.digests.spec,
    registry_digest=report.digests.registry,
    plan_digest=report.digests.plan,
    granted_capabilities=("simulate",),
)
decision = authorize_plan(report, policy)
assert decision.authorized
```

必须同时绑定 `specDigest + registryDigest + planDigest`。旧策略不能用于修改后的计划、另一份
Registry 或新的 ResearchSpec revision。

## 三种结果

| 状态 | 含义 | 可执行 |
|---|---|---|
| `authorized` | 所需 capability、permission 与 approval 全部精确满足 | 是 |
| `pending` | capability/permission 已满足，但仍缺显式 requirement 决定 | 否 |
| `denied` | 缺 capability/permission，或至少一个 requirement 被拒绝 | 否 |

如果同时存在 denied 与 pending，结果是 `denied`。这不会把尚未决定误写成批准，也不会让
一个拒绝被其他未决项遮蔽。

Planner 生成的 requirement 必须显式决定：

```python
from llm_research_os.execution import (
    RequirementDecision,
    RequirementDecisionValue,
)

RequirementDecision(
    "approval:/workflow/workflow.simulation/review",
    RequirementDecisionValue.APPROVED,
)
```

未知、重复、格式错误或本计划未使用的 grant/decision 都直接报错，而不是静默忽略。
capability 与 permission 会递归收集符号循环体中的任务，但循环不会展开，`until` 也不会求值。

## 安全边界

授权门只计算一个不可变结果。它不会验证“谁”批准、生成时间或身份、保存批准、发事件、读写
SQLite、执行积木、读取 secret、联网、申请 GPU 或花费资金。`decision_digest` 只是当前 Python
参考摘要约定下的内容身份，不是签名 token，也不是可撤销的持久授权凭据。

当前 SimulatedRuntime 在写第一条生命周期事实前调用此门，并只授予内置 T0 `simulate`
capability。真正的 Python/OCI/Worker、外部审批请求与回执 Schema、认证、过期/撤销、预算扣减
和审计事件仍未实现。
