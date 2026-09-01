# M0 显式计划授权 CLI

## 用途

`researchos authorize` 把纯 `authorize_plan` 门暴露成一个可审查的本地协议入口。它会重新读取
ResearchSpec 和明确提供的 BlockManifest，生成新的静态计划，然后只对这一个计划求值。它不会
执行积木、写数据库或生成授权回执。

## 先检查计划

```bash
uv run researchos dry-run examples/valid/minimal.yaml --format json
```

从输出中核对：

- `digests.spec`、`digests.registry` 和 `digests.plan`；
- 每个任务声明的 capability 与 permission；
- `plan.policyRequirements` 中必须逐项决定的 requirement ID。

随后编写 `PlanAuthorizationRequest`。最小示例已经提交在
`examples/plan-authorization-requests/valid/minimal.json`。三个摘要必须与本次重新生成的计划完全
一致，不能把旧请求用于新 revision、不同 registry 或变更后的计划。

## 求值

```bash
uv run researchos authorize \
  examples/valid/minimal.yaml \
  examples/plan-authorization-requests/valid/minimal.json \
  --format json
```

使用额外积木清单时，请把同一来源再次明确交给命令：

```bash
uv run researchos authorize \
  examples/valid/bounded-loop.yaml request.json \
  --registry examples/manifests/example-train.yaml \
  --format json
```

命令不会接受请求自带的计划正文。Registry 与 DryRunReport 始终由当前本地输入重新构造。

## 结果与退出码

| 状态 | 退出码 | 含义 |
|---|---:|---|
| `authorized` | `0` | 精确 grants 与 requirement approvals 完整 |
| `pending` | `1` | 仍有 requirement 未明确决定 |
| `denied` | `1` | 缺 grant 或存在明确拒绝 |
| 无报告 | `2` | 输入、规划、registry、摘要绑定或语义校验失败 |

JSON stdout 是 `PlanAuthorizationReport v0alpha1`。它包含排序后的 required/missing access 与
approved/pending/denied requirements，且可从这些字段重算 `decisionDigest`。错误只写 stderr；输入
错误不会输出半成品授权报告。

## 为什么报告不是回执

报告固定包含：

- `approvalAuthentication: not-authenticated`；
- `persistence: not-persisted`；
- `execution: not-executed`；
- blocks、network、persistent writes 与 paid actions 四项均为 `0`。

因此 `status: authorized` 的准确含义只是：“这份调用者声明的策略，按当前参考实现，对这个精确
计划求值得到允许。”它不证明审批者身份，不带签名、时间、过期或撤销信息，也没有进入事件
事实源。真正的 NativeProcessRuntime、远程 Worker 或付费任务不能只凭这份报告执行。

## 协议检查

```bash
uv run researchos schema --contract plan-authorization-request \
  --check schemas/plan-authorization-request/v0alpha1.schema.json
uv run researchos schema --contract plan-authorization-report \
  --check schemas/plan-authorization-report/v0alpha1.schema.json
```

完整字段与规范语义见
[PlanAuthorizationRequest and PlanAuthorizationReport v0alpha1](../protocols/plan-authorization-v0alpha1.md)。
