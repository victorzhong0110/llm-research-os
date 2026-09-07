# M2 usage evidence

Constraint: [ADR-0052](../adr/0052-control-path-usage-evidence.md),
[ADR-0047](../adr/0047-eventstore-performance-and-metric-sampling.md).
This path does **not** close Issue #38, does not spend GPU, and is not
an SLA.

`researchos m2 bench` fills EventStore with foreign facts. That is **not**
this command. `m2 usage` measures append, claim, cancel, and coordinate on
the Worker/RunControl path, under mixed research and budget events, then
runs an isolated Worker process and a cited report.

```bash
uv run researchos m2 usage /tmp/m2-usage --format json
```

`USAGE.json` has `"usedEventStoreAppendFill": false` and
`"gpu": "not-run"`. A loopback isolated Worker is **not** a cross-machine
proof. OCI is `observed`, `skipped-no-runtime`, or `skipped-no-image`;
designated Linux OCI CI (`RESEARCHOS_OCI_REQUIRED=1`) must not skip.
