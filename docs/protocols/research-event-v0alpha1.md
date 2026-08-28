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

## 2. CloudEvents envelope

Every document MUST be a single JSON object using CloudEvents 1.0 structured-mode attribute
names:

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
  "sequence": 0,
  "streamid": "example-minimal",
  "streamversion": 0,
  "data": {}
}
```

- `specversion` MUST be `1.0`.
- `id`, `source` and `type` are CloudEvents required context attributes and are required
  here.
- `time` is required in v0alpha1 and MUST include a timezone offset or `Z`. Naive local
  timestamps are invalid.
- `subject`, `dataschema` and `datacontenttype` are present in v0alpha1. `dataschema` MUST
  be the committed schema URI. `datacontenttype` MUST be `application/json`.
- `source` is a CloudEvents URI-reference: non-empty, without whitespace, at most 2048
  characters.
- `sequence`, `streamid` and `streamversion` are required extension attributes.
- `correlationid` and `causationid` MAY be omitted.
- `id`, `time` and `sequence` MUST be supplied by the caller. Implementations MUST NOT mint
  them during validation or schema generation.

v0alpha1 does not implement CloudEvents HTTP, Kafka, AMQP or binary-mode bindings.

## 3. Domain data

`data` MUST contain the versioned ResearchEvent payload:

- `schemaVersion` MUST be `v0alpha1`;
- `actor` is a closed object whose only v0alpha1 field is `id`;
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
(no NaN, Infinity, bytes or non-JSON types). All text, including payload keys and strings,
MUST be valid Unicode scalar values. Lone surrogates are invalid.

## 5. References instead of bodies

Events MUST NOT embed file bytes or document bodies. Large artifacts, logs, prompts, notes
and model outputs belong in the artifact store and are referenced by URI and digest.

v0alpha1 rejects `payload` objects that contain any of these keys at any depth: `content`,
`body`, `bytes`, `fileBytes`, `inlineContent`, `rawBody`. `evidenceRefs` entries MUST be
unique; they are identifiers, not inlined evidence documents.

Secrets MUST NOT be placed in envelope context attributes.

## 6. Conformance commands

```bash
uv run researchos schema --contract research-event \
  --check schemas/research-event/v0alpha1.schema.json
uv run pytest tests/test_events.py tests/test_event_schema.py
```

Valid examples MUST pass both Draft 2020-12 structural validation and reference semantic
validation. Invalid examples may target either layer. Embedded bodies are a semantic rule:
JSON Schema MAY accept them while the reference implementation MUST reject them.

## 7. Deliberate v0alpha1 limitations

v0alpha1 does not yet define:

- a catalog of `type` values;
- actor kind, role or display-name fields;
- whether a later append-only store assigns `sequence` instead of requiring producers to
  supply it;
- stream identity (per project, run, attempt or other);
- CloudEvents `sequencetype` or string-valued `sequence`;
- charset parameters on `datacontenttype`;
- UUID-only `id` syntax;
- persistence, projection, run state machines or runtime emission.

These omissions are explicit. Adapters MUST NOT fill them with hidden, incompatible
semantics and call the result conforming v0alpha1 behavior.
