# ADR-0017: Minimal Model Interface and Capability Negotiation

- Status: Accepted
- Date: 2026-09-04

## Context

Chapter 18 decision `8-MC` chose a small owned `ModelProvider` over treating
OpenAI-compatible HTTP or LiteLLM as the core abstraction. ADR-0038 E4 scheduled
the interface, a deterministic mock, and `ai.call.*` facts as M1-2. Vendor
capability claims are not an execution contract: a missing tool, schema, or
modality must degrade or refuse in the open, never by silently simulating the
missing feature.

M1-4 will add an OpenAI-compatible adapter behind `SecretRef` and a budget cap.
This record freezes the kernel-facing interface before that adapter exists so
the mock and the later HTTP path share one event shape.

## Decision

1. Every model invocation goes through `ModelProvider`. Upper layers do not
   retain vendor response objects. `generate()` is the M1 surface; streaming is
   declared as a capability and not exposed until a later slice.
2. A call records three capability sets: **declared** (what the adapter claims),
   **measured** (what a local, side-effect-free probe observed), and **allowed**
   (the intersection with current policy). A requested capability absent from
   `allowed` fails closed.
3. `DeterministicMockProvider` is the first adapter. It reads fixtures, performs
   no network or process launch, and treats declared, measured, and allowed as
   the same closed set (`generate`, `seed`).
4. `ai.call.started` / `ai.call.completed` / `ai.call.failed` store prompt and
   output as semantic digests and optional artifact refs. The event payload MUST
   NOT contain prompt or output text (TM-007, TM-022).
5. The provider does not mint `id` / `time` / `streamid`. Caller-owned identity
   follows the SimulationRequest pattern.

This ADR does not authorize a live HTTP client, GPU, or paid call.

## Consequences

- A later OpenAI-compatible adapter cannot widen the kernel by returning native
  SDK types. It must map into `GenerateResult` and the three capability sets.
- Tests must tripwire `socket`, `subprocess`, and dynamic imports on the mock
  path.
- Missing ADR-0016 plugin isolation still applies: the built-in mock runs
  in-process as T0 (ADR-0038 E5).

## Validation

Fixture-driven generate records two CAS facts whose payloads contain digests
and not fixture text. Requesting a disallowed capability fails before any
event is appended. Replay of those facts does not require the fixture bytes.

## References

- [Chapter 18 decision 8-MC](../chapter-18-decision-guide-v0.1.md)
- [ADR-0038 E4 M1-2](0038-charter-errata-after-m0.md)
- [ADR-0033 JCS semantic digests](0033-normative-jcs-semantic-digests.md)
