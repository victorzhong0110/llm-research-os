# M2 WSL2 CUDA laptop acceptance (not M2 close)

Issue #38 stays open. Platform claim, when live evidence exists, is
**Windows/WSL2 + Docker Engine**. This is not native Linux or cloud GPU
acceptance.

Constraint: [ADR-0059](../adr/0059-wsl2-cuda-laptop-profile.md),
[ADR-0021](../adr/0021-remote-worker-transport.md),
[ADR-0056](../adr/0056-gpu-training-execution-profile.md).
Protocol: [wsl-cuda-training-plan-v0alpha1](../protocols/wsl-cuda-training-plan-v0alpha1.md).

Base SHA for this work package: branch `m2/wsl2-cuda-live` on top of
PR #72 `a6898a620b9ca0ee62d735d51a3b8f3298d25da9` (which includes #71).

`execute_gpu_training` / `training bind` stay `gpu-not-run`. Live start is
`run_gpu_training` after grant.

## Live evidence (this work package)

Issue #38 stays open. Do not merge this PR as M2 close.

Authoritative pack: [m2-wsl2-cuda-live](../evidence/m2-wsl2-cuda-live/README.md).

| Row | Status | Note |
| --- | --- | --- |
| EventStore | 142 events | Mac `~/researchos-control-wsl2/research.db`; seq 1–118 freeze plus cuda.8/9 tail |
| Mac Tailscale IPv4 | `100.69.150.10` | Serve bound here, not `26.0.0.1` |
| Control plane HTTPS | live | TLS timeout was local `https_proxy`; `--noproxy` works |
| WSL TCP + TLS + Worker register | live | `worker.wsl.1` and `worker.wsl.gpu.1` |
| CPU two-host OCI | live pass | `grant.wsl.oci.1` completed |
| Reconnect / cancel | live pass | reconnect completed; cancel `cancel-observed` |
| CUDA 20-step | live pass | `grant.wsl.cuda.7`; report semantics corrected in the pack |
| Checkpoint SHA256 + CAS PUT | live pass | Worker `POST /v0alpha1/artifacts`; retrieve via `artifacts verify` |
| Authorized restore | live pass | `grant.wsl.cuda.9` from checkpoint-10; cuda.8 failed and was not reused |
| `unknown ≠ rerun` | tests only | no dedicated live shot |
| Code SHA (both machines) | not a single HEAD | see `code-identity.md` |

## Windows Cursor command pack

This Mac session has no Windows/WSL shell. After you log into Tailscale on
the Mac, run `tailscale ip -4` and substitute that value for
`CONTROL_TS_IP` everywhere below (no quotes around a guessed address).
Port is `8443` unless that port is taken; then use the same free port on
both sides.

**PowerShell (Windows host, Tailscale only on the host):**

```powershell
# Confirm host Tailscale, not a second daemon in Ubuntu
tailscale status
tailscale ip -4
```

**Ubuntu (WSL) — TCP then TLS then Worker (after pack is on D:\llm-ros\worker-pack):**

```bash
export CONTROL_TS_IP='CONTROL_TS_IP'
export CONTROL_PORT=8443
python3 - <<'PY'
import os, socket
ip = os.environ["CONTROL_TS_IP"]
port = int(os.environ["CONTROL_PORT"])
s = socket.create_connection((ip, port), timeout=8)
s.close()
print("tcp-ok", ip, port)
PY
echo | openssl s_client -connect "${CONTROL_TS_IP}:${CONTROL_PORT}" \
  -servername "${CONTROL_TS_IP}" -verify_return_error \
  -CAfile /mnt/d/llm-ros/worker-pack/worker/tls-cert.pem
# Fill worker/credential.template.json with register/grant values from the Mac
# EventStore. Never copy control-state/tls-key.pem.
# then: uv run researchos workers run /mnt/d/llm-ros/worker-pack/worker/credential.json ...
```

If TCP from WSL fails while Windows host Tailscale works, measure
`ip route`, Windows firewall for the Tailscale interface, and
`/etc/resolv.conf` / WSL mirrored vs NAT networking. Do not disable the
firewall globally or skip TLS verify.

## Mac control plane

Install the official Tailscale macOS pkg (needs your password), then log
in the Tailscale app. Do not treat `26.0.0.1` as this Mac.

```bash
# after Tailscale is Connected
tailscale ip -4
tailscale status
```

Use the **100.x** address as `CONTROL_TS_IP`. Pick a free port (example
`8443`).

```bash
cd /Users/zhongxudong/Desktop/llm-research-os/llm-research-os
git fetch origin
git switch m2/wsl2-cuda-live
git rev-parse HEAD   # both machines must match this SHA

CONTROL_ROOT="$HOME/researchos-control-wsl2"
mkdir -p "$CONTROL_ROOT/cas" "$CONTROL_ROOT/state"
uv run python - <<'PY'
from pathlib import Path
from llm_research_os.storage import EventStore
root = Path.home() / "researchos-control-wsl2"
root.mkdir(parents=True, exist_ok=True)
with EventStore(root / "research.db"):
    pass
print(root / "research.db")
PY

# Serve on the Tailscale unicast address (not 0.0.0.0, not loopback for this proof)
uv run researchos workers serve \
  "$CONTROL_ROOT/research.db" \
  --artifacts "$CONTROL_ROOT/cas" \
  --state "$CONTROL_ROOT/state" \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal \
  --host "$CONTROL_TS_IP" \
  --port 8443
```

In another Mac terminal, pack **CA only**:

```bash
uv run researchos workers pack "$HOME/researchos-worker-pack" \
  --url "https://${CONTROL_TS_IP}:8443" \
  --project example-minimal \
  --source https://researchos.dev/projects/example-minimal \
  --state "$CONTROL_ROOT/state"
test ! -e "$HOME/researchos-worker-pack/tls-key.pem"
```

Copy the pack directory to Windows (`D:\llm-ros\worker-pack`). Never copy
`tls-key.pem`.

## Windows host Tailscale (not a second daemon inside WSL)

Install Tailscale for Windows on the **host**, same tailnet as the Mac.
Do not start a second Tailscale inside Ubuntu unless the host client
already forwards that path and you have measured it.

From **Ubuntu (WSL)**, after the Mac serve is up:

```bash
CONTROL_TS_IP='REPLACE_WITH_MAC_TAILSCALE_IPV4'
# TCP
python3 - <<'PY'
import socket, os
ip=os.environ.get("CONTROL_TS_IP") or "REPLACE_WITH_MAC_TAILSCALE_IPV4"
s=socket.create_connection((ip, 8443), timeout=8)
s.close()
print("tcp-ok", ip, 8443)
PY
# TLS + hostname/IP SAN (must match the serve --host)
echo | openssl s_client -connect "${CONTROL_TS_IP}:8443" -servername "${CONTROL_TS_IP}" -verify_return_error 2>/dev/null | openssl x509 -noout -ext subjectAltName
```

Ping failure is not enough to declare the control plane down.

## Same SHA on Windows WSL

```bash
# inside Ubuntu, on the ext4 filesystem (not /mnt/d for the git workdir)
mkdir -p "$HOME/src" && cd "$HOME/src"
git clone https://github.com/victorzhong0110/llm-research-os.git
cd llm-research-os
git fetch origin m2/wsl2-cuda-live
git switch --detach origin/m2/wsl2-cuda-live
git rev-parse HEAD
```

## Image (build on WSL amd64; record Id vs RepoDigest)

```bash
cd "$HOME/src/llm-research-os"
# Reuse already-downloaded wheels if present, e.g. pip download cache under /opt/llm-ros
docker build --platform linux/amd64 \
  -t researchos-ms-swift:4.5.2 \
  -f examples/m2-gpu-image/Dockerfile \
  examples/m2-gpu-image
docker image inspect --format '{{.Id}}' researchos-ms-swift:4.5.2
docker image inspect --format '{{json .RepoDigests}}' researchos-ms-swift:4.5.2
# Grant identity is the local Id `sha256:…`. A tag is not identity.
# RepoDigests is the registry manifest digest only after a pull/push.
```

`local/ubuntu-jammy:22.04` is not this training image.

## CPU two-host first

Use the existing `examples/m2-oci-checkpoint` corpus on the Worker with
`researchos workers run` against the packed credential. Register/grant on
the Mac EventStore. Do not share CAS directories.

## CUDA 20-step (after CPU two-host)

Plan: `examples/training-backend/valid/wsl-cuda-sft.json`.
Profile in the grant config: `wsl2-cuda-laptop-8g`, `device: nvidia.com/gpu=0`,
`memoryBytes: 3221225472`.

Worker:

```bash
uv run researchos workers run /path/to/credential.json \
  --artifacts "$HOME/worker-cas" \
  --gpu-data-dir "$HOME/work/data" \
  --gpu-model-dir "$HOME/work/model" \
  --gpu-output-dir "$HOME/work/output"
```

Collect with `--profile wsl2-cuda` (256 MiB), not the 1 MiB GPU fixture.

## Stop

Mac: Ctrl-C the `workers serve` process.
WSL: `docker ps` then `docker stop <id>` for leftover training containers.
Do not shut down the Windows host as a substitute for container stop.
