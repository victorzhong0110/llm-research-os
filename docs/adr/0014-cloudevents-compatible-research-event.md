# ADR-0014: CloudEvents-Compatible ResearchEvent Envelope

- Status: Accepted
- Date: 2026-08-21

## Context

ResearchEvent is the append-only fact stream for humans, AI and training systems. A fully
custom envelope would be slightly smaller, but every later message bus, audit export or
OpenTelemetry bridge would need a private mapping. Adopting CloudEvents transport bindings
in M0 would pull HTTP, Kafka and binary-mode constraints into a slice that only needs a
local, inspectable JSON document.

CloudEvents 1.0 separates event format from transport. The required context attributes are
`id`, `source`, `specversion` and `type`; domain data belongs in `data`. The Sequence
extension defines `sequence` as a string and `sequencetype`; when `sequencetype` is
`Integer`, values start at `1` and use signed 32-bit Integer string encoding.

## Decision

Use a CloudEvents 1.0 compatible structured JSON envelope (decision `4-EC`):

- The envelope carries `specversion=1.0`, `id`, `source`, `type`, `time`, `subject`,
  `dataschema`, `datacontenttype` and `data`.
- Versioned ResearchEvent fields live in `data` with `schemaVersion: v0alpha1`.
- Internal ordering and causality use lowercase CloudEvents extension attributes:
  `sequence`, `sequencetype`, `streamid`, `streamversion`, `correlationid` and
  `causationid`.
- `sequencetype` is required and MUST be `Integer`. `sequence` is a string-encoded Integer
  in `"1"` through `"2147483647"`; `"0"` is invalid.
- The reference validator does not generate `sequence`. A later SQLite append-only store
  atomically allocates the next Integer sequence when persisting.
- `source` is an RFC 3986 URI-reference and is checked against the URI-reference grammar,
  not only the allowed character set. CloudEvents String attributes reject control
  characters, noncharacters and unpaired surrogates.
- External documents use Schema field names only, exact JSON types, RFC3339 `time` strings
  with a timezone whose offset hours are `00`–`23` and minutes `00`–`59`, and no silent
  trimming of identity values.
- M0 commits only to structured JSON. It does not implement HTTP, Kafka, AMQP or binary-mode
  bindings.
- Large files and document bodies are referenced, never embedded. Secrets must not appear in
  widely logged context attributes.
- Producers supply `id` and `time` explicitly. The contract does not mint them.

This slice defines the external document contract only. It does not write events, open
SQLite, build projections or implement a run state machine.

## Consequences

- Third parties can validate events against the committed JSON Schema without Python.
- Field names on the envelope follow CloudEvents lowercase attribute rules; domain fields
  inside `data` keep the project's existing camelCase aliases.
- Once events are persisted, envelope mapping becomes compatibility history. Changing it
  requires a protocol version change.
- Append order is a store concern: validation of a complete document still requires
  `sequence` and `sequencetype`, but allocation is not performed here.

## Validation

`researchos schema --contract research-event --check` fails when the committed schema
differs from the authoring models. Valid and invalid examples, including unknown fields,
timezone-less timestamps, duplicate `evidenceRefs`, invalid URI percent-encoding, sequence
`0` and embedded bodies, are exercised in tests. Schema-invalid documents MUST also fail
the reference validator.

## References

- [CloudEvents 1.0 specification](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md)
- [CloudEvents JSON event format](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/formats/json-format.md)
- [CloudEvents Sequence extension](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/extensions/sequence.md)
- [Chapter 18 decision 4-EC](../chapter-18-decision-guide-v0.1.md)
