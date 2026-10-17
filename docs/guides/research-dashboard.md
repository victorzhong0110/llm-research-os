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


## Open the map

Start the existing `researchos web serve --root WORKSPACE` command and open its
bootstrap URL. Dashboard is the default view, including for a manifest with no
EventStore yet. Browse previews and inspects; Edit exposes geometry, containment,
pins, source bindings and view arrows; AI opens the workspace Agent inbox. Map
state stays in memory when visiting another workbench view. Save before reloading.
The default regions are editable presets, not fixed departments.

Use Graphite, Warm paper or a custom background/accent, text size and density.
Search, zoom, pan, fit and the minimap navigate larger arrangements. Custom cards
choose summary, metric, table, chart or timeline renderers and explicit bindings;
they do not execute arbitrary frontend code. Run/research/event snapshots state
their bounded coverage. Activity contains the latest 100 project events, in append
order, and explicitly marks older records outside the snapshot. Telemetry is missing until an observation is supplied.

## Start with a research brief

Choose **Create my first brief** on an unsaved map, **Research brief** in the
header, or the entry in Quick guide. Describe a goal and what would count as
progress. Materials and resources are optional: undecided items remain explicitly
unidentified rather than appearing connected or allocated. Review the text, then
**Save brief to map** creates a region with four editable planning notes and saves
the current arrangement in the same revision-bound write.

Closing the panel or visiting another view retains the draft in this browser tab.
Save before reloading; unsaved drafts trigger the browser's leave-page warning.
An unconfirmed save offers **Retry saving this brief** with the same identity and
frozen content, including after closing and reopening the panel. A conflict needs
review/reload; it is never silently rebased. Existing components and pins remain
in place. Saved notes are edited with the ordinary Edit mode and map history.

After saving, **View my research brief** locates the region. **Discuss this brief
with my Agent** opens the inbox with that region selected; it sends no message
until the user writes and submits one. The brief works with no EventStore, model
connection or Worker. It does not create a proposal, decision, resource grant or
Run, and does not upload the named materials. Preparing/importing actual material,
connecting resources and reviewing an executable plan are subsequent work.

## Connect your own Agent

After saving the map, send a message in AI mode. This records a durable request;
it does not launch an Agent or contact a model provider. Configure your own Agent
to poll `researchos dashboard inbox --root WORKSPACE`. Each task includes the
frozen prompt, selected component IDs (or null for the whole map), saved revision
and map snapshot. Selection changes in the browser cannot redirect it.

Return a DashboardAgentReply, optionally including a DashboardWrite proposal,
with `researchos dashboard reply --root WORKSPACE reply.json`. Examples are in
`examples/dashboard/valid`. The proposal must use the task's project, revision
and exact scope; authorKind must be agent. Scoped changes preserve other nodes,
global viewport and appearance. New descendants may be added inside a selected
region. All human pins remain protected. The browser shows the explanation and
proposal; only Apply reviewed Agent proposal writes the new map. Stale proposals
need a new reviewed request, not a rewritten revision number.

The current inbox retains at most 100 tasks and returns the latest 20; capacity
refusal is explicit. Conversation archival and full inbox navigation remain
follow-up work. No hidden reasoning or unobserved background activity is shown.

## Add official provider status

Choose **Add → OpenAI official status** or **Claude official status**. Select the
new component and click **Refresh OpenAI status** / **Refresh Claude status**.
Save the map to retain its source binding. The refresh itself stores the report
independently, and a later failed refresh leaves that report intact until it
becomes stale. The official-page link opens the full provider page.

No API key is required. This retrieves public aggregate status, not your own
request success rate, account limits, region health or available model capacity.
The card shows provenance and retrieval/expiry times; the page's last update is
retained separately. Component and incident counts are counts in the source,
not measured availability percentages. Refresh is manual in this slice.

Agents and operators can use the same collector:

```bash
researchos dashboard provider-status --root WORKSPACE openai
researchos dashboard provider-status --root WORKSPACE claude
```

Only the two fixed HTTPS endpoints are supported. Redirects, environment proxies
and custom URLs are not used. If DNS, TLS or the provider endpoint is unavailable,
the UI reports failure and preserves previous data. It does not retry through a
different host or turn a fetch error into healthy status.

## Connect infrastructure and status sources

A collector or your Agent may supply a DashboardObservation with:

`researchos dashboard observe --root WORKSPACE observation.json`

It identifies project, source, entity, category, reporter and provenance;
observedAt and expiresAt are timezone-aware timestamps. Metrics distinguish
observed, allocated, reserved and estimated values. Time series have strictly
ordered timestamps. Optional explanation text requires a named author. Synthetic
fixtures stay labeled; expired reports show stale. Reports are source assertions,
not independent verification of that host or provider's availability.

Select the source in the component's Edit panel. A category binds automatically
only when exactly one source matches. Provider official status and your own
request health must use different sources. No arbitrary URL is fetched by a
binding. The current slice supplies ingestion/display and manual fixed official-status
collectors, not a bundled host exporter or automatic provider-status poller. Each
source is bounded to 32 KiB,
100 source identities per workspace; time must advance on replacement. These
observations do not create Run/Attempt facts or authorize execution.

## Candidate limits

Older workspace backup formats omit dashboard.sqlite; export the map separately.
The Agent inbox needs an external Agent to consume it. No live provider call,
paid host or participant study is part of this slice. Source-backed execution
edges, guided domain operations, automatic collector installation, conversational
archival and complete onboarding acceptance remain separately reviewable work.

## Evaluate first use

Use the versioned [dashboard-v1 acceptance pack](dashboard-acceptance.md) for
participant journeys and real-host presentation checks. Old CLI trials and
synthetic browser fixtures do not establish current-map comprehension. Missing
guided setup or Dashboard-store restore is recorded as a blocker.
