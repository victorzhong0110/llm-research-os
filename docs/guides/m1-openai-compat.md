# M1 OpenAI-compatible generate CLI

## What the command does

`researchos models generate` accepts either a mock `ModelGenerateRequest` or an
`OpenAICompatGenerateRequest`. The HTTP path defaults to a local OpenAI-compatible
server and records budget facts plus digest-only `ai.call.*` facts.

```bash
uv run researchos models generate \
  examples/openai-compat-requests/valid/local.json \
  research.db \
  --fixture examples/model-fixtures/valid/compat-local.json \
  --format json
```

Loopback calls MUST use cap `0.00` CNY and MUST NOT carry a `secretRef`.
Remote calls require `SecretRef` (`env`), `read.external_api`, and HTTPS.
Exit `0` on loopback commits reserved, started, consumed, and completed.
Remote success commits reserved, started, and completed; the reservation stays
open because cost is unknown. Exit `1` is a domain refusal (missing secret,
disallowed capability, budget exceeded). Exit `2` is invalid input or a CAS
conflict. A transport error after reserve+start commits released and
`ai.call.failed`, then exits `1`.

JSON stdout is still `ModelCallReceipt` (ids and digests). It does not echo
prompt, completion, or secret values.
