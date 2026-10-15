# Compose a research workspace map

Export current view state with `researchos dashboard show --root WORKSPACE`.
Use `--revision N` to inspect retained history. A user-owned Agent can read this
state and return a DashboardWrite; apply it with
`researchos dashboard apply --root WORKSPACE write.json`.

Set expectedRevision to the revision read, choose a fresh requestId and set
authorKind to agent. Preserve human pins and change only the requested scope.
Retry an uncertain write with the same identity and content. If another edit
won, reload, review the difference, and produce a new proposal. Never blindly
retry a stale proposal with a newer revision.

Bindings describe sources, not measurements. Missing telemetry stays missing.
Grouping and view arrows do not alter experiment dependencies or resource
allocation. Operational commands keep their normal preflight and authority.
Export the saved map separately when using older workspace backup formats.
