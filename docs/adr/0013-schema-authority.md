# ADR-0013: Schema Authority and Generation Chain

- Status: Accepted
- Date: 2026-08-21
- Supersedes: ADR-0002 shorthand

## Context

Python is the first implementation language, but third-party Workers, UIs and plugins must not depend on Python internals. Maintaining separate handwritten Python, JSON Schema and TypeScript definitions would cause silent drift.

## Decision

Pydantic models are the M0 authoring entry point. CI deterministically generates and commits a versioned JSON Schema Draft 2020-12 document. The published JSON Schema is the external language-neutral contract. Future TypeScript types are generated from that committed schema, never maintained independently.

Rules not expressible in JSON Schema require normative prose, positive and negative examples, and cross-language conformance tests.

## Consequences

- Generated schema changes are protocol changes and must be reviewed in diffs.
- Unknown structural fields are rejected; open-ended backend data only appears in declared extension points.
- Breaking compatibility requires a protocol version change, not only a Python package version change.

## Validation

`researchos schema --check` fails when the committed schema differs from current authoring models. Valid and invalid examples are exercised in tests.

## References

- [Pydantic JSON Schema generation](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
