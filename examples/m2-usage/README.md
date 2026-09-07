# M2 usage pack

Issue #38 stays open. This directory describes `researchos m2 usage`.
It is not a GPU run and not a two-host proof.

```bash
uv run researchos m2 usage /tmp/m2-usage --format json
```

The command:

1. Measures Worker/RunControl append, claim, cancel, and coordinate under
   mixed research and budget facts (not `EventStore.append` fill).
2. Starts an isolated control-plane process and a Worker with a private CAS.
3. Writes a report that cites spec, registry, plan, runtime, image, config,
   and output artifact.
4. Runs CPU OCI when docker is present; otherwise records
   `skipped-no-runtime`. Designated Linux OCI CI must not skip.

See [M2 usage](../../docs/guides/m2-usage.md).
