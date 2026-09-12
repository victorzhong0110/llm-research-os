# M2 cross-machine Worker (pending-live)

Constraint: [ADR-0021](../adr/0021-remote-worker-transport.md),
[ADR-0044](../adr/0044-isolated-control-plane-and-loopback-https.md).
Protocol: [Worker v0alpha1](../protocols/worker-v0alpha1.md).
Pack: [M2 remote Worker](m2-remote-worker.md).

This host has **no second machine**. This document is the clean-install
checklist. It is **not** a live two-host run, **not** GPU, and **not**
Issue #38 closure. This tree does not rent a host and does not ask for a
private key.

## Independent roots

Control plane and Worker MUST NOT share:

| Resource | Control host | Worker host |
|---|---|---|
| EventStore | `control/research.db` | absent |
| CAS | `control/cas` | `worker/cas` |
| Workdir | `control/` | `worker/` |
| TLS | `control-state/tls-key.pem` stays here | `worker/tls-cert.pem` only |

A loopback URL in the pack is `loopback-not-cross-machine`.

## Generate the pack (runnable now)

```bash
uv run researchos workers pack /tmp/remote-worker-pack \
  --url https://192.0.2.10:8443 \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal
```

Read `/tmp/remote-worker-pack/ENVIRONMENT.json` and
`ACCEPTANCE.md`. `STATUS.json` has `crossMachine: pending-live` and
`secondHost: not-provisioned`.

## Live steps (pending a named second host)

1. Register
2. Claim
3. Download inputs (digest check)
4. Upload outputs (digest only)
5. Reconnect (pending complete, no second spawn)
6. Cancel then observe stop (container stop ≠ cloud instance stop)

Loopback isolated HTTPS already exercises auth/download/upload/reconnect
in `tests/test_worker_isolate.py`. That is not this live checklist.

## Environment inventory

- Python ≥ 3.12, `uv`
- Two hosts with independent disks (not provisioned here)
- Control: HTTPS unicast bind whose cert SAN matches `--url`
- Worker: outbound HTTPS only; CA + fingerprint; no `tls-key.pem`
- Optional docker only for CPU OCI on Linux; GPU remains unpaid
