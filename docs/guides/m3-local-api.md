# Run the local workbench API

Requirements: [local API protocol](../protocols/local-api-v0alpha1.md).
Status: **R09 implemented, not accepted.**

## Start

```bash
researchos app init --root ./ws --project proj-alpha \
  --control-db ./ws/control.db --cas-root ./ws/cas --worker-root ./worker
researchos web serve --root ./ws --port 8787
```

The command prints the listening address and a one-time bootstrap URL:

```text
researchos local API listening on http://127.0.0.1:8787
Open once in your browser, then the secret is spent:
  http://127.0.0.1:8787/#bootstrap=<one-time secret>
```

Open that URL in your own browser. The fragment is never sent to the server,
so the secret does not land in an access log; same-origin script exchanges it
for a session cookie and then clears the fragment from the address bar.

The listener binds loopback only. A non-loopback `--host` is refused: this is a
single-user desktop surface, not a hosted service.

## What the browser gets

`GET /api/v0alpha1/capabilities` reports the API version, the limits the server
actually enforces, and the polling fallback interval. Read the limits from
there rather than hard-coding them in a client.

## Using it without a browser

```bash
# health needs no session
curl -s http://127.0.0.1:8787/api/health

# bootstrap, keep the cookie, then read
curl -s -c jar -X POST http://127.0.0.1:8787/api/v0alpha1/session \
  -H "X-ResearchOS-Bootstrap: <secret>" -H "Origin: http://127.0.0.1:8787"
curl -s -b jar http://127.0.0.1:8787/api/v0alpha1/events?limit=20
```

Unsafe requests need both the cookie, `Origin` equal to the server origin, and
the `X-ResearchOS-CSRF` value from the session body.

## Paging

Every page returns `nextCursor` and `highWaterMark`. Pass the cursor back
unchanged. The run index is newest-first, so its cursor means "older than
this"; event and revision cursors mean "after this sequence".

## Streaming

`GET /api/v0alpha1/stream` is Server-Sent Events. Save the `id:` value and
send it back as `Last-Event-ID` after a disconnect to resume without a gap. If
SSE does not work in the client, poll `/events` with the same cursor.

The stream closes with an `idle` event after 20 s without new events, or after
200 events. Reconnect to continue. It is not a durable queue.

## Previewing a document

```bash
curl -s -b jar -X POST \
  "http://127.0.0.1:8787/api/v0alpha1/preview/document?name=spec.json" \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:8787" \
  -H "X-ResearchOS-CSRF: <csrf>" \
  --data-binary @spec.json
```

This decodes a bounded document and returns it. It appends no fact and
validates no ResearchSpec. YAML aliases, duplicate keys, deep nesting, and
oversized bodies are refused rather than truncated.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `403 host-forbidden` | The request used a different `Host`. Use the exact printed address. |
| `409 bootstrap-consumed` | The secret was already used. Restart the server for a new one. |
| `401 session-expired` | The session is gone or idle-timed-out. Bootstrap again. |
| `503 concurrency-exhausted` | Eight requests are already in flight. Retry shortly. |
| `503 event-store-unavailable` | The control store is missing or unreadable. Check `--root`. |
| Nothing appears in a view | The project has no events yet, or the page is beyond the last cursor. |

## Limits

Boundaries, defaults and the reason for each are in the
[protocol](../protocols/local-api-v0alpha1.md). Do not raise the concurrency or
body caps to work around a slow client; that trades a refusal for an
unbounded read in the operator's own process.
