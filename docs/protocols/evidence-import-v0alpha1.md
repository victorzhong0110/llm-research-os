# Evidence import and citation v0alpha1

> Status: Experimental external contract for local Markdown/PDF import,
> `evidence.imported`, and `EvidenceCitation`. JSON Schema files are the
> structural contracts.

This slice realises [ADR-0019](../adr/0019-evidence-rights-by-use.md)
(chapter 18 `14-RB`) for **local files only**. It does not fetch the web,
GitHub, or arXiv.

## 1. Rights by use

Every imported object records `rights`, `license`, and `allowedUses`.

- Default license is `LicenseRef-Unknown`.
- Default rights are `unknown`.
- Default `allowedUses` is `["research-read"]`.
- `rights: unknown` MUST NOT list `training` or `redistribution`.
- A human review that establishes adequate rights MUST append a new fact; it
  MUST NOT silently reinterpret `unknown`.

This is an operational gate, not a legal opinion.

## 2. Import

`EvidenceImportRequest` plus a CLI `--source` path and `--artifacts` root:

1. Read a regular local `.md` / `.markdown` / `.pdf` file (no symlinks).
2. Put the raw bytes in the artifact store (`snapshotDigest`). The digest MUST
   match SHA-256 of the bytes that were extracted from; a change between read
   and `put` fails closed.
3. Extract UTF-8 text (Markdown decode, PDF via pypdf). Put the text bytes
   (`textArtifact`) and record `textDigest` as `jcs-sha256` of `{"text": ...}`.
4. CAS-append `evidence.imported`.

The filesystem path (`--source`) and the extracted body MUST NOT appear on the
event. Request field `source` is the CloudEvents event source. `sourceUri` is a
caller-owned logical URI (`researchos://local/...`), not a host path.

## 2.1 PDF work bounds

Imported PDFs are adversarial (TM-006, TM-041). File-byte caps are not enough:
a small FlateDecode stream can expand into large text, CPU, or memory.

PDF extraction MUST:

- run in a subprocess (not in the CLI process);
- abort when the page count exceeds 64;
- extract page text incrementally and refuse when extracted characters would
  exceed 400_000 (the same cap as `textCharacters`);
- terminate within 5 seconds of wall time;
- apply best-effort `RLIMIT_CPU` (4 seconds) and address-space (256 MiB)
  limits in the worker. macOS may not enforce `RLIMIT_AS`;
- start with a minimal environment (PATH/locale/temp plus `LROS_PDF_WORKER=1`).
  The worker MUST NOT inherit the parent process environment, `PYTHONPATH`,
  proxy variables, or secret-bearing keys (TM-041).

Oversized or slow PDFs fail closed (`pdf-page-limit`, `text-too-large`,
`pdf-timeout`, `pdf-resource`, `pdf-extract`). The importer MUST NOT truncate
silently and MUST NOT echo extracted text or source paths in errors (TM-022).

## 3. Citation

An `EvidenceCitation` is `{evidenceId, snapshotDigest, span}` where `span` is
a half-open `[start, end)` character range in the extracted text. Citations
are data. They do not grant capabilities or tools (TM-006).

## 4. Non-goals

Git, GitHub, arXiv, web crawl, MCP, training-eligibility promotion, and
inline evidence bodies are out of scope.
