# M3 native SSH onboarding (slices 1–3)

Usable onboarding checklist without live execution. Protocol:
[NativeProcessRuntime v0alpha1](../protocols/native-process-runtime-v0alpha1.md#ssh-onboarding-shape)
and [v0alpha2](../protocols/native-process-runtime-v0alpha2.md#local-web-onboarding-shape).
Constraint records:
[ADR-0063](../adr/0063-m3-native-process-runtime-slice-1.md),
[ADR-0064](../adr/0064-m3-native-runtime-slice-2.md), and
[ADR-0065](../adr/0065-m3-pack-output-hardening.md).

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
`restricted-v0alpha1` or `restricted-v0alpha2`. The output path must be a
real directory: symlinks and non-directory paths are refused with
`pack-output-invalid`, and a non-empty directory is refused with
`pack-exists` — no files are written on either refusal path. Exit `0`
writes `STATUS.json`, `ENVIRONMENT.json`, `ONBOARDING.md`, `ACCEPTANCE.md`,
`ssh_config.fragment`, and `authorized_keys.fragment`. `STATUS.json`
(embeds the pinned host-key body) and `ssh_config.fragment` are written
owner-only (`0600`) on POSIX. Exit `2` is a validation or filesystem error
and writes no pack. No socket is opened on either path.

With `--web`, the pack additionally contains a static local
`ONBOARDING.html` page (see [Web onboarding](m3-native-web-onboarding.md))
and `STATUS.json` records `"webPage": "ONBOARDING.html"`.

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
