# OpenAI-compatible generate and budget facts v0alpha1

> Status: Experimental external contract for `OpenAICompatGenerateRequest`,
> loopback-default HTTP generate, and `budget.reserved` / `budget.consumed` /
> `budget.exceeded`. JSON Schema files are the structural contracts.

This slice realises [ADR-0017](../adr/0017-minimal-model-interface.md) for an
OpenAI-compatible `/v1/chat/completions` adapter and the first runtime-enforced
CNY caps (ADR-0038 E4 M1-4, `12-SECB` gate 2). Built-in adapters stay in-process
(ADR-0038 E5).

## 1. Local default, remote gates

Default `endpoint` is `http://127.0.0.1:8080/v1` (MLX-LM / llama.cpp). Loopback
hosts are `127.0.0.1`, `localhost`, and `::1`.

| Kind | SecretRef | Kernel grant | Budget | TLS |
|---|---|---|---|---|
| Loopback | forbidden | none | cap, reserve, and consume MUST be `0.00` CNY | http or https |
| Remote | required (`env`) | `read.external_api` | cap required; reserve ≤ cap | https only |

Unknown kernel capability names fail closed (ADR-0038 E6). Endpoints MUST NOT
contain userinfo. HTTP redirects are rejected so a loopback call cannot follow
a 302 off-machine.

The secret value MUST NOT appear in events, receipts, or problem reports
(TM-007). Prompt and completion text stay off `ai.call.*` payloads (TM-040).

## 2. Recording order

Capability refusal leaves the log empty. A reservation that would exceed
`budgetCap` given project lifetime `budget.consumed` CAS-appends
`budget.exceeded` and does not open a socket.

Otherwise the adapter POSTs `/chat/completions`, then CAS-appends
`budget.reserved`, `budget.consumed`, `ai.call.started`, `ai.call.completed`.
Amounts are I-JSON decimal strings with two fraction digits, currency `CNY`.

`ai.call.failed` is still unused: a transport error before append leaves the
log empty (except an already-written `budget.exceeded`).

## 3. Non-goals

No OpenAI Python SDK, LiteLLM, streaming `generate()`, tool execution, or a
live billed smoke against a public API in CI. The ¥30 remote envelope remains
an operator approval, not a test.
