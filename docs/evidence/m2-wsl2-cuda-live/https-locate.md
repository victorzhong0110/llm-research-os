# HTTPS locate (do not auto-restart)

Date: 2026-09-10T12:02:58Z

- `workers serve` PID 55564/55566 still LISTEN on 100.69.150.10:8443.
- EventStore `research.db` had no foreign lockers at probe time.
- Curl through `https_proxy=http://127.0.0.1:7890` timed out in TLS (CONNECT tunnel).
- Curl `--noproxy '*'` to the same URL completed TLS; GET `/v0alpha1/work/poll` returned HTTP 404 (POST-only path).
- openssl s_client to 100.69.150.10:8443 negotiated TLS 1.3. Serve was not restarted.

SSH: Tailscale `status` listed only this Mac. TCP 100.92.154.72:22 accepted then closed before the SSH banner (`kex_exchange_identification`). Checkpoint inventory and Worker PUT are blocked until the Windows peer is online.
