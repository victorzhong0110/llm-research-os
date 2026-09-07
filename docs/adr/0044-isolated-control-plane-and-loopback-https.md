# ADR-0044: Isolated control plane and loopback HTTPS Worker

- Status: Accepted
- Date: 2026-09-07

This record does not reopen ADR-0008, ADR-0009, ADR-0021, or ADR-0043. It
adds process isolation and a pinned loopback HTTPS/JSON binding. It is not
a cross-machine Worker proof, not NativeProcessRuntime, and not paid GPU.

## Context

ADR-0009 chose worker-initiated HTTPS/JSON long polling as the first
transport experiment. ADR-0043 landed the semantic plane on in-process
loopback HTTP so grants, leases, and the CPU helper could be tested without
Docker. That binding shares one process, one working directory, and one
local CAS: the Worker client can open the same SQLite file and the same
object store as the control plane.

Chapter 18 5-WA still wants an outbound HTTPS/JSON binding. Treating a
shared-CAS loopback test as remote verification would hide missing
download, upload, credential, and reconnect paths.

## Decision

1. **Process isolation.** The control plane and the Worker are separate
   processes with separate working directories and separate artifact
   roots. The Worker MUST NOT open the control-plane SQLite EventStore
   and MUST NOT use the control-plane CAS as its execution store.
2. **Protected connection.** The isolated binding is worker-initiated
   **loopback HTTPS/JSON** (TLS 1.2+) with a locally minted certificate
   pinned by SHA-256 fingerprint. HTTP remains an in-process test adapter
   for ADR-0043 semantics. Non-loopback bind still fails closed. This is
   not ADR-0021 remote bootstrap and MUST NOT be described as
   cross-machine verification.
3. **Identity.** Worker sessions (`ws1`) and HMAC grants (`rg1`) stay on
   the control plane's HMAC key. The Worker receives a 0600 credential
   file (URL, worker id, session, grant, CA path, fingerprint). Tokens
   MUST NOT be logged (TM-007). Restarting the control plane reloads the
   same HMAC key from the state directory.
4. **Transfer.** After poll, the Worker GETs
   `/v0alpha1/artifacts/sha256/<hex>` with the grant header, verifies the
   digest, and stores the object in its private CAS. Results are PUT to
   the control-plane CAS, then `work.complete` cites that digest. Reconnect
   retries transport disconnects; it does not re-execute a resumed lease.
5. **OpenSSL.** Minting loopback TLS material requires `openssl`. Missing
   openssl fails closed (`tls-openssl-missing`); tests do not mock TLS.

## Consequences

- `researchos workers serve` and `researchos workers run` exercise the
  isolated path. `researchos m2 prove` remains the in-process CPU corpus
  loop from ADR-0043.
- Heartbeats stay off the EventStore (ADR-0041).
- OCI CPU execution is ADR-0045. Non-loopback transport and paid GPU remain later slices.

## Validation

1. Private-CAS download, grant-bound GET, reconnect after disconnect,
   pinned loopback HTTPS, HMAC-key reload, credential 0600 + log
   redaction, two-process serve/run without sharing CAS.
2. The isolated Worker module does not import `llm_research_os.storage`.
3. `researchos schema --check-all`, ruff, mypy, pytest, coverage ≥ 85%.

## References

- [ADR-0009](0009-worker-semantics-independent-of-transport.md)
- [ADR-0043](0043-m2-loopback-worker-and-hmac-grants.md)
- [Worker protocol v0alpha1](../protocols/worker-v0alpha1.md)
- [Issue #38](https://github.com/victorzhong0110/llm-research-os/issues/38)
