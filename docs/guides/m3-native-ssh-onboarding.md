# M3 native SSH onboarding (R07 candidate)

The pack records one user-owned SSH target and its pinned host key. `ssh-doctor`
uses the pack to check the actual host, optionally install an offline wheelhouse,
and verify a registered Worker through its existing HTTPS control-plane endpoint.
It does not run training or turn the native `--transport ssh` option into a task
executor. No second host has yet been authorized for the R07 live acceptance;
the pack's `pending-live` record remains pending.

## Prepare the target and pack

Create a dedicated non-root account and private workdir on an authorized Linux
or macOS machine. Install Python 3.12 or newer with `venv` and `pip`; provide at
least 100 MiB of free space. Allow SSH access from the operator and HTTPS from
the target to the Worker control plane. Create a dedicated SSH key on the
operator machine. Put its public half in the target's `authorized_keys` with
`no-agent-forwarding,no-X11-forwarding,no-pty,no-port-forwarding`. The generated
fragment is an example. Older packs with a `command=` forced command cannot run
the doctor; update that authorized-key entry after reviewing the target account.

Verify the host key through a trusted channel before writing the pack. Output
from `ssh-keyscan` alone is untrusted and should only be compared to the
independently obtained key. Rotation requires a newly verified key and a new
pack; changing `known_hosts.native` in place is rejected.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/researchos_native_ed25519 -C researchos-native
researchos native ssh-onboard /tmp/native-ssh-pack \
  --host 192.0.2.10 --user researcher --port 22 \
  --workdir /home/researcher/native --host-key ssh-ed25519:BASE64 \
  --project example-native --source https://researchos.dev/projects/example-native
researchos native ssh-doctor /tmp/native-ssh-pack \
  --identity-file ~/.ssh/researchos_native_ed25519 --format json
```

The doctor requires a private user-owned identity file with mode `0600` and
uses an isolated OpenSSH configuration, the exact pack host key, batch mode,
no agent forwarding, no port forwarding, and a fixed remote Python program.
Target and credentials travel through bounded stdin, not interpolated remote
shell input. Probe reports platform, architecture, Python, available space,
workdir and installer, or a repair code. `--port N` also checks a free target
loopback port. Exit `0` means this operation returned `ready`; `1` is a
prerequisite or verification block; `2` is a local input/SSH/response error.

## Install the pinned package

Supply a locally reviewed directory containing the exact
`llm_research_os-*.whl` and all compatible dependency wheels for the target.
The doctor builds a deterministic SHA-256 manifest, sends at most 32 MiB to the
target, verifies every wheel, and installs offline into a private venv under
`WORKDIR/.researchos/runtime-DIGEST`. A repeat with identical bytes returns
`installed: false`. A failed install removes only the newly created runtime;
an existing conflicting runtime is left for manual inspection.

```bash
researchos native ssh-doctor /tmp/native-ssh-pack \
  --identity-file ~/.ssh/researchos_native_ed25519 \
  --operation install --wheel-dir /path/to/pinned-wheels --format json
```

The install does not copy control SQLite, CAS, TLS private keys, task grants,
or training inputs. Wheel installation runs package installation code with the
permissions of the dedicated account; review the wheels and use a separate
account/workdir for this purpose.

## Verify the Worker

Register the Worker on the control plane using the existing Worker workflow.
Provide a local JSON credential with `controlPlaneUrl` (HTTPS origin),
`workerId`, `session`, and `tlsFingerprint` (`sha256:` of the CA PEM file), plus
the public CA certificate. Keep the credential private. The doctor sends the
session through stdin to the target; the remote program validates hostname,
certificate chain, and the pinned CA fingerprint, then calls the authenticated,
read-only `/v0alpha1/work/identity` endpoint. A reachable TLS listener alone
does not count as registration.

```bash
researchos native ssh-doctor /tmp/native-ssh-pack \
  --identity-file ~/.ssh/researchos_native_ed25519 \
  --operation verify-worker --worker-credential /path/to/worker.json \
  --ca /path/to/control-ca.pem --format json
```

For a control server bound to the operator's loopback, use
`--tunnel-port N` with `verify-worker`. The doctor requests exactly one reverse
SSH forwarding from the target's `127.0.0.1:N` to the operator's local Worker
port, requires it to bind, and verifies the same TLS CA and hostname remotely.
The credential must name a local HTTPS origin without paths or userinfo.
Review a dedicated key and server policy allowing only that remote loopback
listener. The generated key fragment disables forwarding by default and will
refuse this operation; it must not be silently relaxed. Tunnel creation alone
is not Worker registration evidence. No credentials are copied into the Worker
root. `native run --transport ssh`
still refuses (`ssh-transport-not-implemented`). A local fake SSH transport in
tests proves protocol behavior, not a cross-machine onboarding acceptance.
