# Native input transfer v0alpha1

This additive R08 slice transfers immutable planned material over pinned TLS.
It is not a distributed native task executor or Checkpoint B acceptance.

`POST /v0alpha1/native/inputs` requires HTTPS, `Authorization: Bearer SESSION`
and `X-ResearchOS-Grant: TOKEN`. JSON contains exactly `digest` (sha256 digest)
and `sizeBytes` (integer, 0 through 256 MiB). Requests are capped at 4096 bytes
and have a ten-second socket timeout. Unknown keys and invalid sizes fail closed.

The controller verifies the session's Worker, signed grant, recorded grant
event and nonce, project, task, Run, Attempt, image and configuration digests,
expiry, revocation, and the immutable queued native execution object. Only the
planned code bundle, dependency lock, environment inventory and named input
digests are available. Named input sizes must match the plan; all downloaded
sizes must match the stored bytes. Arbitrary CAS objects and CAS listing are
unavailable. Interpreter identity is not permission to export host executables.
Cancellation denies fetches. An existing claimed lease must belong to the
same grant and remain unexpired and nonterminal. Fetching before claim is
permitted without creating or consuming a lease.

A successful response is `200 application/octet-stream` with exact
`Content-Length`. The client bounds reads by the requested size plus one and
verifies SHA-256. Disconnects, incomplete HTTP responses and truncated bytes
retry at most three times; authorization, size and hash failures do not retry.
The client closes every connection, refuses HTTP and origins containing
credentials, paths, queries or fragments, and uses the existing pinned CA
verification. No credential is placed in the URL or receipt.

Replay downloads the same immutable bytes without changing EventStore,
claiming work, launching processes or turning unknown into success. It is
transport replay only, not launch or completion replay. Output upload and committed-receipt replay are specified separately in
[the output protocol](native-output-transfer-v0alpha1.md). Durable remote staging
orchestration, remote native launch, full controller/worker restart integration
and real two-host/GPU acceptance remain outstanding.
Legacy M2 artifact endpoints retain their existing scope and are not the
native input protocol or a native launch authority.
