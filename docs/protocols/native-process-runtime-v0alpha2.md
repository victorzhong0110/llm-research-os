# NativeProcessRuntime v0alpha2

> Status: M3 slice 2 local profiles with pinned identity + local Web onboarding
>
> Constraint record:
> [ADR-0064](../adr/0064-m3-native-runtime-slice-2.md)
>
> Supersedes nothing: v0alpha1 stays frozen for `restricted-v0alpha1`
> ([v0alpha1](./native-process-runtime-v0alpha1.md)). This document adds the
> profile matrix, the pinning rule, per-profile non-goals, and the Web page.

This protocol binds one sealed `NativeProcessPreflight` result and one local
authorization citation to a bounded host process. It is not OCI, MPS, GPU,
paid cloud, or a public service.

## Profile matrix

| Surface | `restricted-v0alpha1` | `restricted-v0alpha2` |
|---|---|---|
| transport | `local` executes; `ssh` refused | same |
| argv | fixed noop helper | same |
| entrypoint | not executed | not executed |
| shell | `false` | `false` |
| network | requested `denied`, enforced `not-enforced` | same |
| workspace | isolated temporary cwd | same |
| environment | empty allowlist | same allowlist, digest-pinned per spawn |
| interpreter | host recorded by version (`host-recorded-not-pinned`) | digest-pinned and re-verified (`pinned-reverified`) |
| isolation | `process-group` | same |
| receipt extras | `interpreterDigest`, `environmentDigest`, `interpreterPinned: false` | same keys, `interpreterPinned: true` |

`NATIVE_RUNTIME_PROFILES` is the single allowlist. Any other profile is
`native-profile-invalid` (run) or `ssh-profile-invalid` (onboarding).

## Pinning rule

Before `Popen`, the runtime resolves the interpreter binary (real path plus
version plus file bytes under a domain-separated SHA-256) and digests the
exact environment mapping that `Popen` will receive (sorted JCS SHA-256,
which therefore binds the isolated cwd too). `restricted-v0alpha2`
re-resolves immediately before spawn and refuses with
`native-interpreter-changed` on any drift; unreadable or empty binaries
refuse with `native-interpreter-unpinned`. Errors never carry paths.

Pinning detects substitution; it is not a sandbox and it confers no
authority beyond this spawn.

## Explicit non-goals per profile

These hold for **both** local profiles:

- Manifest entrypoint import or call. Needs a module-digest allowlist bound
  at preflight plus a mount jail; future slice, not this one.
- Network denial enforcement, namespaces, cgroups, seccomp, mount jails,
  OCI/MPS/GPU isolation.
- Lifecycle facts, grants, artifact collection, projection writes.
- SSH execution: `transport=ssh` passes checks 1–3 of v0alpha1 and is then
  refused with `ssh-transport-not-implemented` without opening a socket,
  for every profile, until a researcher-approved host exists (none does).
- Paid cloud, public service, plugin isolation, scientific conclusions.

## Local Web onboarding shape

`researchos native ssh-onboard ... --web` additionally writes
`ONBOARDING.html` into the pending-live pack and records
`"webPage": "ONBOARDING.html"` in `STATUS.json` (else `null`). The page is
a static local file: no server, no JavaScript, no external resources, no
network calls, all operator text HTML-escaped, host-key body never rendered
(key type only). Open it from disk; it proves no second host.

## CLI behavior

```bash
uv run researchos native run ... --profile restricted-v0alpha2 --format json
# exit 0 with interpreterPinned: true, or exit 2 with
# native-interpreter-unpinned / native-interpreter-changed before any spawn
```

```bash
uv run researchos native ssh-onboard /tmp/native-ssh-pack \
  --host 192.0.2.10 --user researcher --port 22 \
  --workdir /home/researcher/native \
  --host-key ssh-ed25519:BASE64 \
  --project example-native \
  --source https://researchos.dev/projects/example-native \
  --profile restricted-v0alpha2 \
  --web --format json
```

A `succeeded` receipt means the fixed helper echoed the sealed preflight
digest under bounds with the pinned identity above, not that research
succeeded.
