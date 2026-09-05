# ResearchEvent v0alpha1

> Status: Experimental external contract  
> Envelope: CloudEvents 1.0 structured JSON  
> Domain version: `v0alpha1`  
> JSON Schema: `schemas/research-event/v0alpha1.schema.json`

ResearchEvent is the append-only fact document for research, planning, execution, training,
evaluation, system, cost, AI and artifact history. Dashboards are projections of these
facts, not a second source of truth.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative requirements in
this document.

## 1. Authority layers

1. The committed JSON Schema is the language-neutral structural contract.
2. This document defines semantic rules that JSON Schema cannot express completely.
3. Positive and negative examples form an initial conformance corpus.
4. The Python package is the first reference implementation, not an additional hidden
   protocol.

An implementation that only validates JSON Schema is a **structural validator**. A
conforming v0alpha1 implementation MUST also enforce the semantic rules below.

This slice validates documents only. It MUST NOT write events, open a database, project
state, execute a run, or contact a network, process, GPU, model API or paid service.

External documents MUST use the JSON Schema field names. Python attribute names such as
`schema_version`, `project_id`, `experiment_revision` and `evidence_refs` are not part of
the document contract. Numeric fields MUST be JSON numbers, not strings or booleans.
CloudEvents identity strings MUST be stored as supplied; validators MUST NOT trim or
otherwise normalize them.

## 2. CloudEvents envelope

Every document MUST be a single JSON object using CloudEvents 1.0 structured-mode attribute
names. The following example is the committed minimal valid event:

```json
{
  "specversion": "1.0",
  "id": "evt.minimal.1",
  "source": "https://researchos.dev/projects/example-minimal",
  "type": "run.started",
  "time": "2026-08-21T12:00:00Z",
  "subject": "example-minimal",
  "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
  "datacontenttype": "application/json",
  "sequence": "1",
  "sequencetype": "Integer",
  "streamid": "example-minimal",
  "streamversion": 0,
  "data": {
    "schemaVersion": "v0alpha1",
    "actor": {
      "id": "researcher.alice"
    },
    "projectId": "example-minimal",
    "experimentRevision": 1,
    "payload": {},
    "evidenceRefs": []
  }
}
```

- `specversion` MUST be `1.0`.
- `id`, `source` and `type` are CloudEvents required context attributes and are required
  here.
- `time` is required in v0alpha1. In an external document it MUST be an RFC3339 string with
  a timezone offset or `Z`. Offset hours MUST be `00`–`23` and minutes `00`–`59`; values
  such as `+00:60` are invalid. Naive timestamps, numeric Unix times and native datetime
  values are invalid document input.
- `subject`, `dataschema` and `datacontenttype` are present in v0alpha1. `dataschema` MUST
  be the committed schema URI. `datacontenttype` MUST be `application/json`.
- `source` MUST be a non-empty RFC 3986 URI-reference and MUST match the URI-reference
  component grammar, not only the allowed character set. Invalid percent-encoding (for
  example `%zz`), more than one fragment (`a#b#c`), an unclosed IP-literal (`http://[`),
  a `[` outside an IP-literal (`foo[bar`), NUL, control characters and other
  CloudEvents-disallowed Unicode code points are invalid.
- CloudEvents String attributes (`id`, `source`, `type`, `subject`, `sequence`,
  `sequencetype`, `streamid`, `correlationid`, `causationid`) MUST NOT contain control
  characters (U+0000–U+001F, U+007F–U+009F), Unicode noncharacters, or unpaired surrogates.
- `sequence` and `sequencetype` follow the CloudEvents Sequence extension. `sequencetype`
  MUST be `Integer`. `sequence` MUST be the string encoding of a signed 32-bit Integer in
  the closed range `"1"` through `"2147483647"`. `"0"`, leading zeros, JSON numbers and
  booleans are invalid.
- The reference validator MUST NOT generate, default or mint `sequence`. The SQLite EventStore
  defined by ADR-0015 atomically allocates the next Integer sequence when persisting; validation
  alone does not perform that allocation.
- `streamid` is required. `streamversion` is a JSON integer in `0` through `2147483647`.
- `correlationid` and `causationid` MAY be omitted.
- `id` and `time` MUST be supplied by the caller. Implementations MUST NOT mint them during
  validation or schema generation.

v0alpha1 does not implement CloudEvents HTTP, Kafka, AMQP or binary-mode bindings.

## 3. Domain data

`data` MUST contain the versioned ResearchEvent payload:

- `schemaVersion` MUST be `v0alpha1`;
- `actor` is a closed object with required `id`. It MAY include `kind` (`human`,
  `ai`, `system`, or `policy`). It MAY include `modelId` only when `kind` is
  `ai`. Omitting `kind` remains valid so existing v0alpha1 events still
  validate. Role and display-name fields remain open;
- `projectId` identifies the research project;
- `experimentRevision` is the positive ResearchSpec revision the fact refers to;
- `runId`, `attemptId` and `blockId` MAY be omitted;
- `payload` is a JSON object of finite, JSON-compatible Unicode scalar data;
- `evidenceRefs` is a list of unique identifiers.

Envelope identity stays on the CloudEvents attributes. Domain data MUST NOT repeat
`eventId` or `timestamp` under other names.

## 4. Closed structure

Unknown structural fields on the envelope, `data` or `actor` MUST fail validation. This
catches misspellings and prevents hidden protocol behavior.

`payload` is the only declared open object. It MUST contain finite JSON-compatible values
(no NaN, Infinity, bytes, tuples or other non-JSON types). Nested values MUST be JSON
objects, arrays, strings, numbers, booleans or null. Cyclic object or array graphs MUST be
rejected. All text, including payload keys and strings, MUST be valid Unicode scalar
values. Lone surrogates are invalid.

## 5. References instead of bodies

Events MUST NOT embed file bytes or document bodies. Large artifacts, logs, prompts, notes
and model outputs belong in the artifact store and are referenced by URI and digest.

v0alpha1 rejects `payload` objects that contain any of these keys at any JSON depth:
`content`, `body`, `bytes`, `fileBytes`, `inlineContent`, `rawBody`. Sequence types that are
not JSON arrays, including tuples, are not payload containers and MUST be rejected.
`evidenceRefs` entries MUST be unique; they are identifiers, not inlined evidence documents.

Secrets MUST NOT be placed in envelope context attributes.

Individual domain protocols MAY reserve and semantically validate exact event types while the
generic envelope remains open. `plan.authorization.evaluated` is currently defined by
[PlanAuthorizationEventRequest v0alpha1](plan-authorization-event-v0alpha1.md); its payload is
audit-only and is not executable authority. Locating those facts by plan identity is defined by
[PlanAuthorizationLineage v0alpha1](plan-authorization-lineage-v0alpha1.md) and likewise is not
executable authority. `ai.call.started` / `ai.call.completed` / `ai.call.failed` are defined by
[ModelProvider v0alpha1](model-provider-v0alpha1.md); payloads store prompt and output digests
and optional artifact refs, never inline text. `evidence.imported` is defined by
[Evidence import v0alpha1](evidence-import-v0alpha1.md); payloads store snapshot and text
digests, never source paths or extracted bodies. `budget.reserved` /
`budget.consumed` / `budget.exceeded` / `budget.released` are defined by
[OpenAI-compatible generate v0alpha1](openai-compat-v0alpha1.md); amounts are CNY
decimal strings, never floats. Outstanding reservations hold the cap until
consume or full release.

## 6. Conformance commands

```bash
uv run researchos schema --contract research-event \
  --check schemas/research-event/v0alpha1.schema.json
uv run pytest tests/test_events.py tests/test_event_schema.py
```

Valid examples MUST pass both Draft 2020-12 structural validation and reference semantic
validation. Invalid examples may target either layer. Embedded bodies are a semantic rule:
JSON Schema MAY accept them while the reference implementation MUST reject them. Documents
rejected by the committed JSON Schema MUST also be rejected by the reference validator.

## 7. Open questions

The following items remain undecided and MUST NOT be filled in by adapters:

- a complete catalog of `type` values beyond types frozen by individual domain protocols;
- actor role or display-name fields;
- stream identity (per project, run, attempt or other);
- charset parameters on `datacontenttype`;
- UUID-only `id` syntax;
- whether `subject` should become optional to match CloudEvents;
- whether omitted `payload` / `evidenceRefs` equal `{}` / `[]`;
- `correlationid` / `causationid` reference and self-causation rules;
- whether `dataschema` may use fragments or redirects;
- a complete inline-content denylist and payload size/depth limits;
- projection, run state machines or runtime emission;
- artifact indexing and the remaining SQLite schema migrations.

`sequence` type, the invalidity of `0`, and allocation ownership are decided above: the
document uses CloudEvents `sequencetype: Integer` string values `"1"`–`"2147483647"`; the
validator never mints them; the SQLite EventStore allocates them atomically.
