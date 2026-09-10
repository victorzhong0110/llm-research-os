# HTTPS locate (do not auto-restart)

Date: 2026-09-10T12:02:58Z

- `workers serve` PID 55564/55566 still LISTEN on 100.69.150.10:8443.
- EventStore `research.db` had no foreign lockers at probe time.
- Curl through `https_proxy=http://127.0.0.1:7890` timed out in TLS (CONNECT tunnel).
- Curl `--noproxy '*'` to the same URL completed TLS; GET `/v0alpha1/work/poll` returned HTTP 404 (POST-only path).
- openssl s_client to 100.69.150.10:8443 negotiated TLS 1.3. Serve was not restarted.

SSH: Tailscale `status` listed only this Mac. TCP 100.92.154.72:22 accepted then closed before the SSH banner (`kex_exchange_identification`). Checkpoint inventory and Worker PUT were blocked until the Windows peer came back.

## After the peer returned (2026-09-10T12:38Z+)

- `tailscale status` showed `laptop-6dgbgvg3` again; ping ~5 ms.
- OpenSSH on `100.92.154.72:22` accepted the pinned ED25519 host key.
- Serve PID 55566 was **not** restarted.
- EventStore was still 118 before cuda.8/9 grants.
