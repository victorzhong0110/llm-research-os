# M1 Evidence import CLI

## What the command does

`researchos evidence import` stores one local Markdown or PDF file in the
artifact CAS and appends `evidence.imported`. The database and artifact root
must already exist. The filesystem path and the extracted text stay off the
event.

```bash
mkdir -m 700 artifacts
uv run researchos evidence import \
  examples/evidence/valid/import-markdown.json \
  research.db \
  --source examples/evidence/sources/eval-split.md \
  --artifacts artifacts \
  --format json
```

Default license is `LicenseRef-Unknown`. Unknown rights cannot authorize
`training` or `redistribution`. Exit `0` means one fact was committed. JSON
stdout is a closed `EvidenceImportReceipt` (ids and digests only).

Exit `1` is a domain refusal (duplicate `evidenceId`, media-type mismatch,
empty PDF). Exit `2` is invalid input, a missing store or artifact root, or a
CAS conflict.

Imported notes are data. They cannot enable tools on `DeterministicMockProvider`
(TM-006).

PDF extraction runs in a subprocess. It refuses more than 64 pages, more than
400_000 extracted characters, or work that exceeds 5 seconds. The worker
receives a minimal environment and does not inherit API keys. A compressed PDF
that expands past those bounds fails closed; the problem report does not echo
the extracted text (TM-041).

This slice does not fetch GitHub, arXiv, or the web, and it does not promote
unknown rights to training.
