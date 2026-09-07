# ADR-0021: Remote Worker transport and connection bootstrap

- Status: Accepted
- Date: 2026-09-08

This record does not reopen ADR-0009 or ADR-0044. It does not spend GPU,
rent a machine, or claim a live two-host proof.

## Context

ADR-0009 kept Worker meaning independent of byte transport and named
worker-initiated HTTPS/JSON long polling as the first remote binding
experiment. ADR-0044 landed that binding on **loopback** HTTPS with a
pinned CA, private Worker CAS, and reconnect. Calling that loopback path
a cross-machine Worker would hide missing bind, SAN, and bootstrap
rules.

There is no second machine in this tree. A pack that can be copied to a
second host is not a live proof.

## Decision

1. **Same semantic protocol.** Remote transport is still poll, heartbeat,
   grant-bound GET, artifact PUT, complete/fail, and reconnect
   (ADR-0009, ADR-0044). Adding a host MUST NOT change ResearchSpec or
   lease rules.
2. **Worker outbound only.** The Worker initiates HTTPS to the control
   plane. This slice does not open inbound ports on the Worker and does
   not require the researcher to paste a private key.
3. **Protected bind.** HTTP (no TLS) remains loopback-only. `0.0.0.0` /
   `::` stay forbidden. With TLS, a unicast IP or hostname MAY be bound.
   The advertised URL MUST be `https` without userinfo, query, or
   fragment. Certificate SAN MUST cover that host. The Worker receives
   the CA and fingerprint only; `tls-key.pem` MUST NOT enter the Worker
   directory.
4. **Isolation.** Control plane and Worker still MUST NOT share the
   EventStore file or CAS root (ADR-0044).
5. **Pending live.** `researchos workers pack` writes a runnable pack
   whose `STATUS.json` is `crossMachine: pending-live`. A loopback URL
   in that pack is **not** a cross-machine proof. Live two-host
   verification is a later researcher-approved step.

## Consequences

- `workers serve --host` default stays `127.0.0.1`. Unspecified binds
  fail closed even with TLS.
- SSH/Tailscale may still bootstrap connectivity; they are not the
  Worker protocol.
- Issue #38 stays open. This is not M2 acceptance.

## Validation

1. HTTP bind of `0.0.0.0` fails `bind-unspecified`; `localhost` without TLS
   fails `bind-not-loopback`.
2. TLS bind of an unspecified address fails `bind-unspecified`.
3. The pack copies the CA, never the key, and labels `pending-live`.
4. Isolated HTTPS still authenticates, downloads, uploads, and
   reconnects (ADR-0044 tests). Those tests remain loopback.

## References

- [ADR-0009](0009-worker-semantics-independent-of-transport.md)
- [ADR-0044](0044-isolated-control-plane-and-loopback-https.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
