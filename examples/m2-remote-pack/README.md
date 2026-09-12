# Remote Worker pack (pending-live)

Issue #38 stays open. This directory is the **committed** description of
the ADR-0021 pack. It is not a live two-host run.

Generate a runnable copy (CA, scripts, `STATUS.json`) with:

```bash
uv run researchos workers pack /tmp/remote-worker-pack \
  --url https://192.0.2.10:8443 \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal
```

`STATUS.json` always has `"crossMachine": "pending-live"`. Generated
`ENVIRONMENT.json` forbids shared SQLite/CAS/workdirs. `secondHost` is
`not-provisioned`. If `--url` is loopback, `"binding"` is
`loopback-not-cross-machine`. Do not rename a localhost test to a
cross-machine proof.

The generated `worker/` directory receives `tls-cert.pem` only. Never copy
`tls-key.pem`. Do not paste a private key into the Worker host.

See [M2 remote Worker](../../docs/guides/m2-remote-worker.md) and
[M2 cross-machine](../../docs/guides/m2-cross-machine.md).
