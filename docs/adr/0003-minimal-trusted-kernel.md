# ADR-0003: Minimal Trusted Kernel

- Status: Accepted
- Date: 2026-08-21

## Context

Making every rule pluggable would allow extensions to bypass identity, revision, approval, budget and audit guarantees. Putting every capability in the core would make experimentation and independent contributions impractical.

## Decision

The trusted kernel owns protocol validation, immutable revisions, append-only facts, policy enforcement, task state, artifact integrity and secret references. Training backends, model providers, evidence connectors, visualizations and most execution capabilities remain replaceable.

## Consequences

- Kernel changes receive stricter review and tests.
- Plugins cannot override constitutional invariants.
- The initial kernel stays small enough for a single maintainer to understand.

## Validation

Unknown structural fields fail validation, while backend-specific parameters are confined to explicit `config` and `extensions` objects.

