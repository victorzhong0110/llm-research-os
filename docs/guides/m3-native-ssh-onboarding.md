# M3 native SSH onboarding (slice 1)

Usable onboarding checklist without live execution. Protocol:
[NativeProcessRuntime v0alpha1](../protocols/native-process-runtime-v0alpha1.md#ssh-onboarding-shape).
Constraint record:
[ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md).

This path does **not** dial SSH, does not prove a second host, does not spend
paid cloud, and does not start a public service. `STATUS.json` stays
`pending-live` until a researcher provisions a host.

## Write a pack

```bash
uv run researchos native ssh-onboard /tmp/native-ssh-pack \
  --host 192.0.2.10 \
  --user researcher \
  --port 22 \
  --workdir /home/researcher/native \
  --host-key ssh-ed25519:BASE64 \
  --project example-native \
  --source https://researchos.dev/projects/example-native \
  --format json
```

Requirements: non-root user, absolute isolated workdir (not `/`), pinned
host key (`ssh-ed25519:` / `ecdsa-sha2-nistp256:` / `ecdsa-sha2-nistp384:` /
`ssh-rsa:` plus base64; private-key material is refused), and profile
`restricted-v0alpha1`. Exit `0` writes `STATUS.json`, `ENVIRONMENT.json`,
`ONBOARDING.md`, `ACCEPTANCE.md`, `ssh_config.fragment`, and
`authorized_keys.fragment`. Exit `2` is a validation or filesystem error and
writes no pack. No socket is opened on either path.

## Onboard a host

1. Generate a dedicated key on the operator machine and never copy the
   private half into the pack or the repository:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/researchos_native_ed25519 -C researchos-native
   ```

2. Pin the host key before first use and compare it with `hostKey` in
   `STATUS.json`:

   ```bash
   ssh-keyscan -t ed25519 -p 22 192.0.2.10 | tee known_hosts.native
   ```

   Abort on mismatch.
3. Provision the isolated workdir on the target and append
   `authorized_keys.fragment` for the dedicated public key only. Keep the
   `command=` prefix and the `no-agent-forwarding`, `no-X11-forwarding`,
   `no-pty`, `no-port-forwarding` options.
4. Connect once in batch mode with the fragment:

   ```bash
   ssh -F ssh_config.fragment researchos-native true
   ```

## What stays pending

SSH transport execution is `ssh-transport-not-implemented` in this slice:

```bash
uv run researchos native run ... --transport ssh --format json
# exit 2, no process spawned, no socket opened
```

Live connect, workdir, restricted-command, and cancel steps are listed in
`ACCEPTANCE.md` and stay `pending-live`. Loopback targets are labeled
`loopback-not-cross-machine`. Do not treat onboarding as a live run, and do
not paste private keys, passwords, or agent forwarding into the flow.
