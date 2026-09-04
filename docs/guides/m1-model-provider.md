# M1 ModelProvider mock CLI

## What the command does

`researchos models generate` records one deterministic mock model call as two
EventStore facts (`ai.call.started`, then `ai.call.completed`). The database
must already exist. Prompt and output text stay in the fixture file; events
store semantic digests (and optional artifact refs) only.

```bash
uv run researchos models generate \
  examples/model-generate-requests/valid/generate.json \
  research.db \
  --fixture examples/model-fixtures/valid/generate-json.json \
  --format json
```

`--artifacts ROOT` is optional. When set, the root must already exist. The
command publishes JCS UTF-8 bytes of the fixture prompt and output objects
and writes `promptArtifact` / `outputArtifact` on the completed fact.

Caller-owned `id`, `time`, `source`, `subject`, and `streamid` come from the
request. The store assigns `sequence`, `sequencetype`, and `streamversion`.

## What success means

Exit `0` means both facts were committed. JSON stdout is a closed
`ModelCallReceipt` (`callId`, event ids, sequence, projectId, digests). It
does not echo fixture text.

Exit `1` is a domain refusal (disallowed capability, unknown fixture,
duplicate `callId`). Exit `2` is invalid input, a missing or corrupt
database, or a CAS conflict. Conflicts are not retried.

Requesting `tools` (or any capability outside the mock allowed set) fails
before any event is appended. The mock does not pretend to call tools.

This slice does not open a network connection, resolve a `SecretRef`, or
submit a proposal.
