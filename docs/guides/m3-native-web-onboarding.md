# M3 local Web onboarding foundation (slice 2)

Local-only static page inside the pending-live SSH pack. Protocol:
[NativeProcessRuntime v0alpha2](../protocols/native-process-runtime-v0alpha2.md#local-web-onboarding-shape).
Constraint record:
[ADR-0064](../adr/0064-m3-native-runtime-slice-2.md).

This page is **not** a public MVP, not a server, and not a live proof. Open
it from disk (`file://`). It makes no network requests, runs no script,
collects nothing, and never embeds the host-key body.

## Write a pack with the page

```bash
uv run researchos native ssh-onboard /tmp/native-ssh-pack \
  --host 192.0.2.10 \
  --user researcher \
  --port 22 \
  --workdir /home/researcher/native \
  --host-key ssh-ed25519:BASE64 \
  --project example-native \
  --source https://researchos.dev/projects/example-native \
  --web \
  --format json
```

Without `--web`, the pack is exactly the slice-1 file set and `STATUS.json`
records `"webPage": null`. With `--web`, the pack additionally contains
`ONBOARDING.html` and records `"webPage": "ONBOARDING.html"`.

## What the page contains

- Pending-live banner: transport `ssh-pending`, second host
  `not-provisioned`.
- Target summary (host, user, port, workdir, profile, host-key *type* only).
- The five checklist steps with the `ssh_config.fragment` and restricted
  `authorized_keys.fragment` contents inline for copying.
- Acceptance checklist and a local-file-only footer.

All operator text is HTML-escaped at pack-writing time. There is no
`<script>`, no link, and no fetch surface to audit.

## What is not claimed

Two-host execution, paid cloud, public service, plugin isolation, and
entrypoint execution remain out of scope. `researchos native run
--transport ssh` still fails closed for every profile.
