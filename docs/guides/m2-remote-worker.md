# M2 remote Worker (pending-live)

Constraint: [ADR-0021](../adr/0021-remote-worker-transport.md),
[ADR-0009](../adr/0009-worker-semantics-independent-of-transport.md),
[ADR-0044](../adr/0044-isolated-control-plane-and-loopback-https.md).
Protocol: [Worker v0alpha1](../protocols/worker-v0alpha1.md).

This path does **not** close Issue #38, does not spend GPU, and does not
claim a live two-host Worker. A loopback URL is **not** a cross-machine
proof.

## Pack

```bash
uv run researchos workers pack /tmp/remote-worker-pack \
  --url https://HOST:8443 \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal
```

`--state DIR` copies the existing CA only. The Worker side of the pack
MUST NOT contain `tls-key.pem`. Fill `credential.template.json` with a
`ws1` session and `rg1` grant issued on the control-plane host.

## Serve and run

Default `workers serve --host 127.0.0.1` remains loopback. Unspecified
binds (`0.0.0.0`) fail closed. A unicast `--host` with TLS is allowed;
the certificate SAN MUST cover that host. The Worker still dials out.

Auth, artifact GET, artifact PUT, and reconnect are the ADR-0044
isolated HTTPS tests. Those tests stay on loopback.

Live two-host verification stays `pending-live` until a researcher
approves a second machine. This tree does not rent hosts and does not
ask for a private key.

Clean-install inventory and the live step list:
[M2 cross-machine](m2-cross-machine.md).
