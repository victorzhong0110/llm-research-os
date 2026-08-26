# ProblemReport v0alpha1

> Status: Experimental machine-readable diagnostic output
> JSON Schema: `schemas/problem-report/v0alpha1.schema.json`

Commands that cannot validate or interpret their input emit a `ProblemReport` to stderr.
Every report has `valid: false` and one or more errors with an RFC 6901 JSON Pointer `path`,
stable type/code and human-readable message. The document root is the empty string `""`;
`/` means a member whose name is empty, and segments use the standard `~0` and `~1` escapes.
Dry-run and block commands render the same information as escaped
plain text unless `--format json` is selected.

A ProblemReport is a diagnostic, not a DryRunReport and never contains a partial plan. Exit
code `2` means invalid/unreadable input. Some lookup operations use exit code `1` with a
ProblemReport because the requested exact object was not found.

Error messages may contain caller-supplied filenames and parser details. They never echo
rejected task-config values or dynamic config keys, but M0 still has no typed `SecretRef` or
general secret scanner; callers must not put credentials in protocol documents.

```bash
uv run researchos schema --contract problem-report \
  --check schemas/problem-report/v0alpha1.schema.json
```
