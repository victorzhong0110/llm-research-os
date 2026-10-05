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

## The `type` vocabulary

`type` is a **stable machine identifier**, and a caller may branch on it. It is not a
class name and must not be parsed as one. An error that defines a closed set of codes
surfaces that code; an error that has none surfaces its exception class name. A given
`type` may therefore appear across several command families, and a new command is free to
add a `type` without a protocol revision — but **must not** change the meaning of one that
already exists, because scripts branch on it.

Event-store errors use the `event-store-*` family: `event-store-absent` when the control
store does not exist, `event-store-unwritable` and `event-store-unreadable` for open
failures, and `event-store-schema-invalid` for a database that does not match the
supported schema. Before this rule was adopted, these surfaced as `EventStoreSchemaError`,
which was both an implementation name and non-specific about what actually went wrong;
three CLI tests asserted it and were updated.

Error messages may contain caller-supplied filenames and parser details. They never echo
rejected task-config values or dynamic config keys, but M0 still has no typed `SecretRef` or
general secret scanner; callers must not put credentials in protocol documents.

Control-store error messages deliberately carry **no filesystem path**, including in
`EventStoreSchemaError`, because these reach CLI output, logs, and issue reports. The
fspath is available to the caller that constructed the error.

```bash
uv run researchos schema --contract problem-report \
  --check schemas/problem-report/v0alpha1.schema.json
```
