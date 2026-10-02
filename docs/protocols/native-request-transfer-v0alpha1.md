# Native request context transfer v0alpha1

This R08 slice reconstructs the existing closed reviewed-native request from
recorded facts. It does not create a new authorization record, persist a second
copy of execution identity, issue launch credentials, or execute an entrypoint.

`POST /v0alpha1/native/request` requires pinned HTTPS, exactly one
`Authorization: Bearer SESSION`, `X-ResearchOS-Grant: TOKEN`,
`Content-Type: application/json`, and `Content-Length`. The JSON body is the empty
object, capped at 4096 bytes. Content/transfer encodings, duplicate authority
headers, query parameters and nonempty bodies refuse. Socket timeout is ten
seconds. The existing signed/recorded grant and immutable native execution
binding are rechecked; revocation, grant/claimed-lease expiry, terminal claimed
leases and cancellation refuse. Fetching before claim is allowed. No lease or
fact is created.

The controller derives the request's project/revision/workflow/actor and four
reviewed digests from the cited human authorization fact at its exact recorded
sequence; task/Run/Attempt/Worker and authorization references come from the
recorded grant. Profile/platform/code/inputs/environment/limits/restrictions
come from the immutable queued native execution. The source must be a human
`authorized` evaluation including `execute.native`, and the full reconstructed
execution must match the recorded image/configuration digests. Live context
and new output also require the source revision to match the controller.
A read-only completed receipt retains its original revision when replayed. An audit-only
source fact by itself cannot obtain this endpoint; live signed and recorded
Worker authority is also required. Reconstruction does not recompute the source
specification or imply a supported remote execution path.

A successful response is `200 application/json`: the exact canonical UTF-8
[NativeReviewedExecutionRequest](../../schemas/native-reviewed-execution-request/v0alpha1.schema.json),
with exact `Content-Length` no greater than 65536 and `X-ResearchOS-Request`
containing its JCS digest. The client verifies the closed schema, canonical bytes,
Worker identity and digest, reads at most the declared size plus one, and closes
every connection. Only disconnects or truncated responses retry, at most three
times; refusals, integrity errors and invalid documents do not retry. Credentials
stay in request headers, never in the returned document or URL.

The native output endpoint independently reconstructs this same request from
the immutable records and requires the output's `requestDigest` to equal its
JCS digest before CAS publication or completed-receipt replay. A syntactically
valid citation to a different full request is refused. A completed receipt's
read-only replay keeps its existing expiry/revocation semantics; it does not
fetch live request metadata or create launch authority.

The returned request remains review/context data. Preparation still must verify
all material and the actual Worker environment; remote launch and restart must
preserve the consumed grant and durable process-identity boundary. This endpoint
does not copy the controller database or HMAC key to a Worker, append Run/Attempt
success, or satisfy new two-host acceptance. Scientific results and process
observations remain separate evidence.
