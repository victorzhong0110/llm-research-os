# OpenAI-compatible generate and budget facts v0alpha1

> Status: Experimental external contract for `OpenAICompatGenerateRequest`,
> loopback-default HTTP generate, and `budget.reserved` / `budget.consumed` /
> `budget.exceeded` / `budget.released`. JSON Schema files are the structural
> contracts.

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
a 302 off-machine. The adapter does not honor `HTTP_PROXY` / `HTTPS_PROXY`
(the classified endpoint is contacted directly).

The secret value MUST NOT appear in events, receipts, or problem reports
(TM-007). Prompt and completion text stay off `ai.call.*` payloads (TM-040).

Loopback identity is cost-known (`costKnown=true`). Remote identity is
cost-unknown (`costKnown=false`): the adapter MUST NOT append
`budget.consumed` from caller `consumeAmount`.

## 2. Recording order

Capability refusal leaves the log empty. A reservation that would exceed
`budgetCap` given project lifetime `budget.consumed` plus outstanding
reservations CAS-appends `budget.exceeded` and does not open a socket.

Otherwise the adapter CAS-appends `budget.reserved`, then `ai.call.started`
(prompt digest from the fixture; capabilities from `provider.capabilities()`),
then POSTs `/chat/completions`.

On HTTP success with cost known: `budget.consumed` (amount ≤ reserved; same
`budgetId`, `callId`, currency, and cap as the reservation), then
`ai.call.completed`. On HTTP success with cost unknown: `ai.call.completed`
only; the reservation stays open and continues to hold the cap.

On `ModelTransportError` after reserve+start: `budget.released` (full reserved
amount) then `ai.call.failed`, then the transport error is re-raised. A digest
mismatch after HTTP 200 does not release: the call may already be billed.

`consumeAmount` / `callId` / currency / cap that do not match the open
reservation are rejected before commit (`reservation-mismatch` or
`consume-exceeds-reserve`).

Amounts are I-JSON decimal strings with two fraction digits, currency `CNY`.
The request `events` map MUST include started, completed, failed, reserved,
consumed, exceeded, and released identities.

## 3. Non-goals

No OpenAI Python SDK, LiteLLM, streaming `generate()`, tool execution, or a
live billed smoke against a public API in CI. The ¥30 remote envelope remains
an operator approval, not a test. Hostname-literal loopback classification
does not follow DNS or other private/metadata addresses.
