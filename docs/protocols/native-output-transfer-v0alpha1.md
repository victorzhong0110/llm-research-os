# Native output transfer v0alpha1

This R08 slice uploads one canonical native result over pinned HTTPS and returns
an existing durable Worker completion fact. It does not launch a task or append
Run/Attempt lifecycle facts. Remote execution, durable worker staging/recovery,
and new authorized two-host evidence remain separate work.

## Request and authorization

`POST /v0alpha1/native/outputs` uses a TLS origin without query parameters.
Exactly one each of `Authorization: Bearer SESSION`, `X-ResearchOS-Grant: TOKEN`,
`X-ResearchOS-Lease: LEASE`, `X-ResearchOS-Artifact: sha256:HEX`,
`Content-Type: application/json`, and `Content-Length` is required.
Transfer/content encodings and ambiguous duplicate headers are refused.
The ten-second socket timeout bounds an interrupted request.

The body is the exact RFC 8785 UTF-8 encoding of
[NativeReviewedTaskOutput](../../schemas/native-reviewed-task-output/v0alpha1.schema.json).
The declared length must be positive and no larger than both the immutable
native configuration's reviewed `artifactBytes` and the 256 MiB transport cap.
Authorization and size checks precede allocation of the body. The controller
checks the signed and recorded grant, nonce, Worker session, project, task,
Run/Attempt, execution image/configuration, consumed claim and lease ownership.
A new result requires live unrevoked authority, an unexpired nonterminal lease,
and no recorded cancellation request.

Body SHA-256 must equal the header digest. Task/Run/Attempt identifiers must
match the claimed lease. Unknown keys, malformed JSON, duplicate keys,
noncanonical bytes and unsupported canonical numbers are refused before CAS
publication. `requestDigest` must equal the full request reconstructed from the exact
recorded human authorization, grant and immutable queued native execution
([request context protocol](native-request-transfer-v0alpha1.md)). A syntactically
valid digest of a different request refuses before publication. A controller
integrating this receipt into Run success must still verify the actual process
result and original specification/registry execution binding. A Worker completion is a
report from the trusted Worker, not independent proof that a process stopped or
that an experiment's scientific claims are valid.

## Publication and replay

Publication uses a controller-owned, zero-byte, owner-only regular lock beside
the database; a busy, linked, symlinked, foreign-owned or malformed lock is
refused. The parent directory and its stable lock are trusted controller
resources and must not be replaced or deleted by an untrusted actor. Linux and
macOS controllers are supported. CAS bytes are digest/size verified before a
single `work.completed` fact is appended. Existing verified bytes need no new
artifact disk; new bytes require the payload size plus 4096 available bytes.
Grant expiry, revocation, cancellation and the EventStore head are rechecked
after CAS I/O. Any intervening fact forces reauthorization, at most three times.

A `200 application/json` response is a
[NativeOutputReceipt](../../schemas/native-output-receipt/v0alpha1.schema.json)
with exactly `digest`, `sizeBytes`, `resultDigest`, `leaseId`, `eventId`, `type`
and `sequence`. `resultDigest` covers the output envelope using JCS; `sequence`
is the positive integer of `evt.work.completed.LEASE`. No credential is returned.
Valid and invalid examples live in `examples/native-output-transfer/`.

After response loss or controller restart, repeating the identical payload
returns that same receipt and sequence. A completed replay still checks the
session, signed/recorded grant and binding and requires the original verified
CAS object and recorded result digest. Grant expiry or revocation cannot create
new facts but does not prevent reading this already committed receipt. A missing
or damaged CAS object refuses replay; uploading the old payload does not repair
it. Changed output refuses before publication. A crash or cancellation after
CAS publication but before the fact may leave an unreferenced immutable object;
it is not a completion and is not automatically deleted by this endpoint.

The client pins both CA and certificate fingerprint, reads at most 4097 receipt
bytes, validates every receipt field against the sent payload and lease, and
closes every connection. Disconnects and truncated receipts retry the identical
request at most three times. Refusals and integrity/schema mismatches do not
retry. Native Workers cannot bypass this protocol through the legacy artifact
upload or generic HTTP completion endpoints. Trusted local native execution's
existing completion API and other Worker runtimes retain their behavior.

Per-request bounds do not provide aggregate rate limits, admission control or
a public multi-tenant parser sandbox. Repeated transport requests never poll,
consume another grant, launch or relaunch a process, or mark a Run completed.
