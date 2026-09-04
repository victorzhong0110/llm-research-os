# SecretRef v0alpha1

## Status and authority

`SecretRef` is the typed handle for a secret slot. The committed Draft 2020-12
JSON Schema is the structural contract:

```text
schemas/secret-ref/v0alpha1.schema.json
```

The document MUST NOT contain the secret value (TM-007). Resolvers MUST NOT put
the value in exception messages, logs, events, or problem reports (TM-022).

M1-0 lands the type, redaction helper, and `env` resolver. Remote model
endpoints in M1-4 MUST use a `SecretRef` rather than an inline token. File and
keyring backends still fail closed.

## Document shape

| Field | Rule |
|---|---|
| `apiVersion` | exactly `researchos.dev/v0alpha1` |
| `kind` | exactly `SecretRef` |
| `backend` | `env`, `file`, or `keyring` |
| `name` | closed identifier for the slot (environment variable, file label, or keyring key). Not the secret |

Unknown fields are invalid. `file` and `keyring` backends fail closed until a
later slice implements them.

## Normative env reference

```json
{
  "apiVersion": "researchos.dev/v0alpha1",
  "kind": "SecretRef",
  "backend": "env",
  "name": "OPENAI_API_KEY"
}
```

## Conformance commands

```bash
uv run researchos schema --contract secret-ref \
  --check schemas/secret-ref/v0alpha1.schema.json
uv run pytest tests/test_secret_ref.py
```
