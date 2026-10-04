# Local API and browser authority boundary (v0alpha1)

Status: **Implemented in R09; not accepted.** Checkpoint C is not accepted.
Requirements: [M3 plan](../plans/m3-development-plan.md#r09-local-api-and-browser-authority-boundaries).
Ownership: [development governance](../development-governance.md).

## Scope

The local API is a read-only HTTP surface over one project's verified
EventStore folds and CAS. It exists so a browser can inspect real project,
experiment, execution and evidence data before R11 adds reviewed mutating
commands. It is not a second execution system, and it holds no authority the
CLI does not already have.

## Deviation from the R09 plan, proposed for review

The plan described "optional FastAPI/ASGI". This implementation is a
standard-library WSGI application served by `wsgiref` on loopback. The reason
is dependency restraint: the installed core carries five dependencies, and a
web framework plus an ASGI server would add several more, including compiled
ones, to every installation and to the supply chain this project already
tracks as TM-016. The external contract below is unchanged. A framework would
not have supplied the Host, Origin, CSRF, or parser-budget controls below; they
are explicit code either way.

## Transport

| Property | Value |
| --- | --- |
| Bind address | `127.0.0.1` only; a non-loopback host is refused |
| Base path | `/api/v0alpha1` |
| Health | `GET /api/health` (no session) |
| Errors | `{"apiVersion","kind":"LocalApiError","code","message"}` with a fixed operator message |
| Cache | `Cache-Control: no-store` on every response |

Error `code` is a closed set. `message` never contains a request echo, a
document body, a host path, a stack trace, or a credential.

## Authority boundary

1. **Bootstrap.** `researchos web serve` prints a 256-bit secret once, in a URL
   *fragment*. A fragment is never sent to a server, so the secret does not
   appear in an access log, a `Referer`, or a proxy trace. Same-origin script
   reads it and posts it in `X-ResearchOS-Bootstrap`. The secret is single-use;
   a second attempt is `409 bootstrap-consumed`.
2. **Session.** A successful exchange sets `researchos_session`, an opaque
   32-byte token, `HttpOnly; SameSite=Strict; Path=/`. Sessions live in memory
   only, are bounded to eight, and expire after twelve idle hours. Nothing is
   written to disk.
3. **Host.** Only the exact configured authority answers. A request with any
   other `Host` is `403 host-forbidden`, which closes DNS rebinding.
4. **Origin.** `POST`, `PUT`, `PATCH` and `DELETE` require an `Origin` equal to
   the server's own origin. An absent `Origin` on an unsafe method is refused.
5. **CSRF.** Unsafe methods require `X-ResearchOS-CSRF` matching the session's
   double-submit token, which is returned in the session body because the
   cookie is `HttpOnly`.
6. **Not a Worker credential.** No route accepts a Worker HMAC grant, a TLS
   client certificate, or a bearer token. A browser session is not usable
   anywhere the Worker plane accepts, and no route forwards it to one.

## Resource bounds

| Bound | Default |
| --- | --- |
| Request body | 1 MiB, refused from a declared length without reading |
| Concurrent requests | 8, refused with `503` rather than queued |
| Decoded depth / nodes | 128 / 100 000, shared with the existing document loader |
| Evidence size / extracted chars / PDF pages | 8 MiB / 400 000 / 64 |
| SQLite query work | 2 s per dedicated read connection |
| Socket idle / absolute request deadline | 10 s / 30 s, including incomplete headers |
| SSE idle | 20 s, then a closing `idle` event |

Body bounds are not treated as parser bounds. JSON and YAML go through the
existing duplicate-key, alias-rejecting loader; PDF goes through the existing
isolated PDF worker (5 s wall, 4 s CPU, 256 MiB address space). The service
limits socket handler threads before creation, retains an application concurrency
slot for the entire SSE lifetime, and opens SQLite in read-only mode.
A `Content-Length` that understates the body is cut off at
the cap rather than trusted.

## Project scoping

The artifact index is global by content digest. Artifact access is therefore
proven from linked events: a digest is visible only when a verified event of
*this* project references it. Event, revision and run pages are filtered by
`projectId`, and every page reports the `highWaterMark` it was frozen against.

Cursors bind the project, filters, and frozen high-water mark. Filtering occurs
in SQL before limiting, and continuation excludes facts appended after that mark.
Cursors are opaque and issued by the server. A run index is newest-first, so
its cursor means "strictly older than this"; event and revision cursors mean
"after this sequence".

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness, no session |
| POST/GET/DELETE | `/api/v0alpha1/session` | Bootstrap, inspect, end a session |
| GET | `/api/v0alpha1/capabilities` | API version, enforced limits, polling interval |
| GET | `/api/v0alpha1/workspace` | Project identity, manifest-relative paths, high-water mark |
| GET | `/api/v0alpha1/events` | Bounded, project-scoped event page |
| GET | `/api/v0alpha1/revisions` | Bounded spec-revision page |
| GET | `/api/v0alpha1/runs` | Bounded run index, newest first |
| GET | `/api/v0alpha1/artifacts/{digest}` | Project-scoped artifact, inlined below 256 KiB |
| POST | `/api/v0alpha1/preview/document` | Bounded JSON/YAML/PDF decode preview; writes nothing |
| GET | `/api/v0alpha1/stream` | Resumable SSE with a polling fallback |

`/preview/document` is a decode preview only. It appends no fact, mints no
receipt, and does not validate against a `ResearchSpec`; R10 and R12 add the
views that do.

## Streaming

`GET /api/v0alpha1/stream` emits `id:`, `data:` pairs, a `high-water` event
carrying the frozen mark, and a closing `idle` event. A reconnect sends
`Last-Event-ID` (or `?cursor=`) and resumes strictly after that sequence, so a
dropped connection replays nothing. Each poll opens its own verified read,
because the request's store connection is already closed when the first byte is
written. A client that cannot hold SSE polls `/events` with the same cursor
semantics.

## Out of scope for R09

Mutating commands, restore, proposal and decision writes, and evaluation
comparison arrive with R11–R13 and reuse the shared application services. This
surface cannot launch a task, consume a grant, or record a fact.

## Sources

- [M3 plan R09](../plans/m3-development-plan.md)
- [Threat model](../security/threat-model.md) TM-079 – TM-083
- [Guide: local API](../guides/m3-local-api.md)
