# ModelProvider and ai.call facts v0alpha1

> Status: Experimental external contract for `ModelProvider`, `ModelFixture`,
> `ModelGenerateRequest`, and `ai.call.started` / `ai.call.completed` /
> `ai.call.failed`. JSON Schema files are the structural contracts.

This slice realises [ADR-0017](../adr/0017-minimal-model-interface.md)
(chapter 18 `8-MC`). It does **not** open a socket, call a vendor SDK, or
spend money. The OpenAI-compatible adapter is M1-4.

## 1. Capability triple

Every call records three closed sets:

| Set | Meaning |
|---|---|
| `declaredCapabilities` | What the adapter claims |
| `measuredCapabilities` | What a local, side-effect-free probe observed |
| `allowedCapabilities` | Intersection with current policy |

Known names: `generate`, `stream`, `json-schema`, `tools`, `image`,
`embedding`, `logprobs`, `seed`. A requested name absent from `allowed`
fails closed. Adapters MUST NOT silently simulate a missing capability.

The deterministic mock declares, measures, and allows
`generate`, `json-schema`, and `seed`. It is local, cost-known, and
`dataLeavesMachine=false`.

## 2. Digests, not bodies

`ai.call.*` payloads MUST NOT contain prompt or output text. Forbidden keys at
any JSON depth include `prompt`, `output`, `completion`, `response`,
`messages`, `input`, `choices`, and `delta`, in addition to the generic
ResearchEvent inline-body denylist.

Prompt and output are referenced as:

- `promptDigest` / `outputDigest`: `jcs-sha256:` of the fixture JSON objects
- optional `promptArtifact` / `outputArtifact`: `sha256:` of the same RFC 8785
  JCS UTF-8 bytes in the local artifact store

The hex portion of the two digest families matches when the artifact bytes are
exactly that JCS encoding.

## 3. `ModelGenerateRequest`

Caller-owned identity follows SimulationRequest: `id`, `time`, `source`,
`subject`, and `streamid` are never minted by the provider. `events` MUST
contain `ai.call.started` and `ai.call.completed` with distinct ids. Actor
`kind` is `ai` and `modelId` is required.

The fixture document is a separate `ModelFixture` file passed on the CLI
(`--fixture`). The request carries only `fixtureId`.

M1-2 accepts `providerId=mock.deterministic` only.

## 4. Recording

`ModelCallControl` freezes the EventStore high-water mark, folds this
project's `ai.call.*` facts into an in-memory call index, preflights each
draft, and CAS-appends. The mock `generate()` runs **before** any append: a
capability or fixture refusal leaves the log empty. Conflicts are not retried.
`callId` is unique per project.

`ai.call.failed` is reserved for later adapters that emit a start and then
fail. This slice does not write it.

## 5. Non-goals

HTTP, GPU, streaming `generate()`, LiteLLM, secret resolution for remote
endpoints, and treating a mock call as a `proposal.submitted` are out of
scope.
