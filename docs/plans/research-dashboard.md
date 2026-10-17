# Research dashboard: design direction and delivery plan

Status: **Maintainer-confirmed product direction, 2026-10-15; full implementation
authorized 2026-10-16. Map, composition and observation slice merged in #156;
main CI 38962991931 passed at 0a67da5d. Guided research-brief preparation is a
follow-up candidate; guided execution setup and human first-use evidence remain pending.**
Constraint record: [ADR-0066](../adr/0066-semantic-research-dashboard.md).
Canonical package and acceptance authority remains the
[M3 plan](m3-development-plan.md) and its
[acceptance matrix](../evidence/m3/acceptance-matrix.md).

Baseline: `main@fe61937072db21258e01e2ca685ef1d07afa0a0c`, after #149 and
#150; [main CI 38699740458](https://github.com/victorzhong0110/llm-research-os/actions/runs/38699740458)
passed. The maintainer identified first-use comprehension as the current product
priority and paused the existing checkpoint trial campaign. Required engineering
checks continue to apply to implementation changes; outstanding checkpoint rows
remain open or pending-live. This plan does not resume that campaign.

## Product outcome

On opening a project, a newcomer can understand what the research is trying to
achieve, what the AI is doing, which resources it uses, what recently finished,
and what needs a human decision. They can inspect the evidence behind a result
and take the next meaningful action without reconstructing the workflow across
many tabs or editing internal JSON.

The dashboard is a spatial overview, with a useful default arrangement. It is
not a blank canvas that the user must assemble before working. The map summarizes
all major work areas; it does not attempt to render every raw object at once.
Groups, collapse, filtering, and zoom reveal detail while preserving orientation.
AI conversation helps explain or change the map, but the map remains the primary
work surface and usable without an active model connection.

## One person, all responsibilities

The maintainer clarified that this map brings together the functions and views
normally spread across an AI company's roles: research, data, training,
evaluation, model lifecycle, serving, infrastructure, scheduling/load balancing,
provider availability, observability, cost, access and recovery. These are useful
presets around shared entities, not independent departmental dashboards. Users
and their own Agents may rearrange, extend and maintain the composition.

Large maps require pan/zoom, search, collapse and an overview navigator. Arrows
are optional and contextual. Distinguish containment and view annotations from
source-backed dependencies. Never fill missing operational integrations with
invented live status, costs, utilization or Agent activity.

## Confirmed visual direction

| Skin | Treatment | Common behavior |
| --- | --- | --- |
| Graphite | Black/white and neutral gray; clear typography, restrained borders and shadows, black primary actions | Same component structure, relationships, information and actions |
| Warm paper | Pale cream paper, warm dark text and low-saturation separators; comfortable reading | Same component structure, relationships, information and actions |
| Custom | User-selected palette, typography, text size, density and corner treatment within readability constraints | Retain recognizable states, provenance, focus indicators and interaction semantics |

These are design references, not copies of company branding. Theme selection is
available without becoming a first-run setup requirement. Keep normal surfaces
quiet; reserve visual emphasis for active work, changed results, and attention
requests. State must also be expressed with text or shape, not color alone.
Small activity marks belong near the work they describe. Animation should be
subtle and respect reduced-motion settings.

The maintainer's follow-up sketch adds a compact Agent marker attached to the
component where it is working, plus size, color and shape as visual signals.
Use size for relative prominence within a region, accent for current focus or
attention, and a consistent shape/icon vocabulary for component types. Resizing
expresses view intent; component area is not a measurement of compute, cost or
importance in the underlying research. Quantitative charts retain their own
labeled scales. Stable state labels and focus outlines distinguish attention
from a warning, and the meaning survives theme changes.

## Spatial and relationship vocabulary

The map combines semantic relationships with a user's view of the work. A region
can represent an actual domain container or a named visual grouping; those two
meanings must be distinguishable in its label/inspection and edit behavior.

| Relationship | Overview treatment | Meaning and limits |
| --- | --- | --- |
| Containment | A labeled enclosing region with collapsible contents | A project or experiment group contains its members; view-only regions are labeled as such |
| Subordination | Attached badge, small card, or activity mark | An Agent, current activity, or subordinate detail belongs to the displayed subject according to its source |
| Peers / comparison | Similar scale and aligned local grouping | Candidates are viewed together; geometric alignment alone does not establish scientific comparability |
| Dependency / sequence | Selective directed, labeled edges | A recorded input or execution dependency, not merely two nearby objects |
| Evidence / reference | Citation mark and relationship highlight on selection | A claim or result can be traced to its source without every reference line remaining visible |
| Shared resource / dataset | One entity with several contextual references | Several tasks may use it; nesting one reference does not transfer exclusive ownership |

Hard constraints include validated containment, explicit semantic relations and
user-fixed placement. Soft layout concerns include spacing, local direction,
alignment and visual balance. Resolve conflicts visibly instead of silently
discarding a user's pins or rewriting domain facts. The detailed validator must
define constraints per relationship type; a generic tree model is insufficient.

Example: a research project contains a comparison region with two peer
experiments. Each experiment shows its own activity, curve and recent artifact.
Both reference the same dataset and Worker. A review marker attaches to the
result needing a decision. Provider health sits at the edge of the map and
highlights affected work when selected. No fixed global pipeline is required.

## Interaction and human intent

### Side toolbox and interaction modes

The maintainer requested a toolbox alongside the map with ordinary clicking,
manual modification, and AI conversation as distinct modes. Use a compact edge
toolbox with visible labels and a clear active state. Keep it available while
inspecting details; a conversation panel must not replace the map. Exact edge,
dimensions and icon treatment remain prototype decisions.

| Mode | Pointer and keyboard behavior | Visible affordances |
| --- | --- | --- |
| Browse (default) | Hover/focus previews; click/tap opens details; drag empty canvas to pan | No component movement or resize handles; status and Agent markers remain inspectable |
| Edit | Click selects; drag moves; handles resize; selection supports grouping, alignment and pinning | Selected bounds, resize handles and local edit controls; an explicit Details action remains available |
| AI | Open conversation about the map, selected components or a named region | A visible target chip and selection highlight, plus proposed/applied view changes and undo |

In AI mode the user can say, for example, "place these two experiments side by
side," "add provider health beside this project," or "make the comparison more
prominent." Keep the target scope visible and editable before submission. A
request binds its target identities and view revision when submitted; later
selection changes must not silently retarget an in-flight request. With no
selection, explicitly show that the scope is the current map.

Switching modes preserves selection, viewport and edit history. Switching back
to Browse ends manual layout manipulation. Escape dismisses the active temporary
interaction first, then returns to Browse; it does not silently discard a draft
message or stop a running research task. Editing a component's layout does not
activate its domain actions. Provide keyboard/non-drag equivalents.

Keep component insertion, undo/redo, fit-to-view and appearance in a compact
secondary toolbox area. Do not present every operation as a new global mode.
Read-only details and source evidence remain accessible in all three modes.

The attached Agent marker opens that Agent's recorded task/activity and relevant
conversation. The toolbox AI opens composition assistance with explicit map or
selection scope. These may use the same Agent infrastructure, but their entry
points make the task context clear. A quiet or unavailable marker does not imply
that no work is happening; show the last observation and freshness. A view-edit
request is not authorization to launch, cancel, or reconfigure research work.

### Interaction semantics

| Interaction | Visible response | Persisted meaning |
| --- | --- | --- |
| Hover or keyboard focus | Brief status, current activity, freshness and next relevant action | No change to facts or layout |
| Select / tap | Browse opens details; Edit selects the component; AI makes the conversation target visible; Details remains available | Selection or explicit target scope; closing details restores map context |
| Move / resize | Nearby layout adapts without moving the whole map | View position and preferred prominence, not a new dependency |
| Pin / unpin | Clear anchor indicator | An explicit layout constraint respected by AI updates |
| Create / name a visual group | Preview the members and title | Explicit organizational intent; domain membership unchanged |
| Change semantic membership or dependency | Name the operation, targets and effect before applying | A domain edit through its validated application operation |
| Request AI reorganization | Inspectable proposed changes with affected components | A versioned view update that preserves pins and can be undone |

Plain movement needs no approval dialog. Dropping near or into a region must not
silently become an ownership or execution edit: distinguish arrange mode from
the explicit semantic operation. Provide non-drag alternatives for grouping,
ordering and moving. Touch and keyboard access must expose the hover information.

AI may interpret repeated proximity or prominence as a possible comparison or
attention preference. It must label that interpretation as an inference. A named
group or pinned position is stronger explicit intent. Suggestions can offer a
comparison chart; inferred intent cannot approve a run, move data, change a
budget, or become an accepted research conclusion.

Updates preserve entity identity, selection, zoom and nearby spatial anchors.
New work appears locally or in a visible staging area when it cannot fit. The
user can undo a view edit, inspect its author and restore a prior arrangement.
Undoing layout does not imply rolling back an already executed research action.

## Framework and component contracts

The framework owns consistent interaction, theming, data access boundaries,
composition validation and versioned view state. The user's AI selects and
maintains components using inspectable definitions. A built-in default view is
available before any AI composition. Human edits and reusable templates remain
first-class inputs.

The following are contract requirements, not a published schema. The relevant
implementation slice must specify versioning, migration, bounded inputs and
failure behavior before publishing generated contracts.

| Surface | Required information or behavior |
| --- | --- |
| Entity reference | Stable project-scoped identity and reference to authoritative domain data; contextual instances share that identity |
| Relationship | Type, endpoints, domain or view scope, source and applicable validation; no interpretation of raw coordinates as domain facts |
| Component definition | Stable type/version, configurable inputs, supported data bindings, size behavior and overview/detail rendering |
| Data binding | Source identity, field meaning, unit, observation/update time, loading/error/missing/stale state and access scope |
| Interpretation | Author/model when available, creation time, cited evidence, and explicit separation from observations and human conclusions |
| View definition | Component instances, positions, grouping, pins, theme, author and revision; meaningful diffs and undo |
| Action | Human-readable effect and prerequisites; route domain changes through existing application operations and authority checks |
| AI edit | Patch against a known view revision; validate targets, relation semantics, pins and component compatibility; stale conflicts must not overwrite human edits |
| Custom component | Common theme, lifecycle, bounded rendering/data access, failure isolation and accessibility conventions |

Start with composition of built-in primitives. A custom component requiring new
executable code, network access or plugin capability needs its own reviewed
extension boundary and threat-model update. The existing Python extension
boundary does not automatically authorize arbitrary browser code. Component
configuration and view-edit permission are not execution grants. Allow supported
automatic local maintenance, such as refreshing bindings or adding new results,
without requiring confirmation for every update; global reorganization remains
an explicit user request or an inspectable proposal.

## Data truth and preset components

The inventory below is a product backlog. It is not a claim that all sources,
integrations, or measurements already exist. Before binding a component, classify
its source as available, needing an adapter, or unavailable. Bind the first real
dashboard to existing verified project/run/result APIs. Examples are visibly
labeled and separated from actual project data.

| Component family | Useful presets | Required distinction |
| --- | --- | --- |
| Research state | Project goal, experiment groups, active work, recent completions, attention queue | Recorded state versus inferred priority |
| AI activity | Current task/tool activity, waiting input, session timeline and produced artifacts | Observable activity versus generated interpretation; no fabricated internal reasoning |
| Compute | Workers, CPU/GPU/VRAM, queues, assigned tasks, resource history | Connectivity, requested/assigned resources and measured utilization are different fields |
| Provider health | Service components, incidents, maintenance, affected work | Official aggregate status versus this project's observed request health |
| Model usage | Tokens, cost/budget, latency, time to first token, errors and rate limits | Measured, estimated and unknown quantities retain units and provenance |
| Experiment and evaluation | Curves, parameter differences, benchmarks, ablations, prediction/error comparisons | Comparable inputs and evaluation settings must be inspectable |
| Prompt and model work | Version comparison, sample outputs and regressions | Model/configuration/prompt identity attached to each result |
| Data and retrieval | Dataset versions, splits/distributions, quality, indexing, retrieval and citations | Observed coverage versus missing checks or unsupported sources |
| Knowledge and artifacts | Papers, notes, code, reports and checkpoints | Source rights/provenance and artifact identity retained |
| Human decisions | Questions, review requests, AI proposals, evidence and human conclusions | Suggested, reviewed, authorized and executed remain distinct |

Candidate official status sources include [OpenAI Status](https://status.openai.com/)
and [Claude Status](https://status.claude.com/). Validate their available feeds and
service identifiers when implementing adapters. Show source and freshness;
unreachable or stale status is not healthy. A provider incident can suggest an
affected task but does not establish the cause of its failure. Status adapters
must not silently introduce API credential use or paid model calls.

The initial template chooses a few relevant components, with additional presets
discoverable in a library. A component added from the library explains the data
it needs and offers a useful missing-data state. The default is not every widget
on every project.

## Proposed sequential delivery slices

These are subdivisions of the current product continuation, not new R package
identities. Map each PR to the existing R09–R16 responsibilities where applicable.
Proceed sequentially from verified main, with independently reviewable changes.

| Slice | Deliverable | Review evidence |
| --- | --- | --- |
| 1. Interaction model | A complete representative map with containment, peers, shared references, activity and review marks; both skins; Browse/Edit/AI side toolbox; source inventory and draft component/view contracts | Inspect overview, hover/focus, drilldown, mode switching, move/group/pin, explicit AI targets and semantic-edit distinction using clearly labeled examples; resolve comprehension problems before production layout work |
| 2. Real overview | Production map shell with the two themes, readable component states, existing project/run/result data, and evidence-linked detail | Follow a real recorded task from overview to its result; missing/stale/error cases and keyboard navigation remain usable; no fake resource telemetry |
| 3. First useful workflow | Guided entry for an empty or existing project; choose a goal/template, review prerequisites, use existing approval/execution paths, inspect a result and record a conclusion | Complete one supported end-to-end workflow without raw JSON or internal-ID knowledge; errors explain the next action, authority and unknown-state semantics preserved |
| 4. Durable human arrangement | Persist position, groups, pins, collapse and view revisions; undo and restore without changing domain facts | Reload preserves layout; shared references stay consistent; explicit semantic edits use domain operations; view undo cannot undo execution |
| 5. AI composition | Validated composition patches, local maintenance and explanations using the user's AI and the shared contracts | Human/AI edit conflict, stale revision, invalid relation, pin preservation and unavailable-model behavior; inspect who changed what and why |
| 6. Presets and extension | Expand the catalog in small slices, starting with provider status and the highest-value available usage/experiment sources; support custom composition | Source-backed examples, adapter failure/freshness handling, shared theme/interaction behavior; separately review any new executable extension capability |
| 7. First-use evaluation | Evaluate a complete workflow with people unfamiliar with the system, fix observed confusion, and preserve the evidence | Record independent task completion, assistance needed, comprehension errors and time to useful outcome; screenshots and synthetic browser tests alone are insufficient |

First-use review starts with slice 1 and informs every slice; slice 7 consolidates
the evidence rather than postponing usability until the end. Detailed API/schema
choices, layout/rendering libraries and quantitative usability thresholds are
still to be specified. Do not turn these proposals into claimed acceptance.

## Review scenarios and completion evidence

- A newcomer identifies active work, its resources, the last meaningful result
  and the pending human decision, then explains the relationship between them.
- Selecting a result reveals a useful chart, AI explanation and original
  evidence. Missing telemetry and unsupported comparisons are understandable.
- Moving two experiments together changes view intent only. An explicit
  dependency edit has a distinct preview and uses the domain operation.
- Browse clicks open details without moving components. Edit exposes handles;
  AI exposes its target scope. Switching modes preserves context, and a later
  selection cannot redirect an already submitted AI request.
- Two tasks sharing a dataset or Worker retain one authoritative identity.
  Grouping, collapse and multiple representations do not duplicate the facts.
- New activity arrives without displacing pinned work or losing the current
  selection. An AI update conflicting with a human edit is inspectable and
  recoverable.
- An empty workspace offers a clear first action; absent credentials, a provider
  outage or unavailable compute explains what can be done next. The user is not
  required to understand internal identifiers to navigate those states.
- Switching skins preserves layout and information; keyboard, touch,
  reduced-motion and readable-contrast paths remain functional.

Record implementation SHA, actual sources, environment, participant/task evidence
and remaining limitations. Engineering regressions cover new behavior and
contracts; existing CI gates remain in place. No live campaign is resumed or
checkpoint accepted by this document. Historical B/C/D gaps retain their original
meaning in the matrix.
