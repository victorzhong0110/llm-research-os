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

`STATUS.json` always has `"crossMachine": "pending-live"`. If `--url` is
loopback, `"binding"` is `loopback-not-cross-machine`. Do not rename a
localhost test to a cross-machine proof.

The generated `worker/` directory receives `tls-cert.pem` only. Never copy
`tls-key.pem`. Do not paste a private key into the Worker host.

Control plane and Worker MUST use different working directories and
different CAS roots. Auth, input download, result upload, and reconnect
are the isolated HTTPS path already tested in
`tests/test_worker_isolate.py` (loopback). A second machine is a later,
researcher-approved step.

See [M2 remote Worker](../../docs/guides/m2-remote-worker.md).
