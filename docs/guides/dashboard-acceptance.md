# Dashboard acceptance: participant journeys and real-host evidence

Task pack: **dashboard-v1**, 2026-10-18 Asia/Taipei.
Status: **specified, not performed; the earlier checkpoint campaign remains paused**.
Decision: [ADR-0067](../adr/0067-dashboard-acceptance-rebaseline.md).

The map redesign changes the journey being tested. An old CLI task, screenshot
or browser smoke cannot demonstrate that a newcomer understands the current
Dashboard. This pack replaces the old R16 participant task wording for future
Dashboard trials. It adds presentation checks to real-host scenarios; it does
not erase historical evidence or waive the underlying execution checks.

## Readiness and setup

Use at least two intended users who did not implement the system. The maintainer
handles invitations and authorized remote access. Do not begin a new campaign
merely because this document exists.

Before freezing a trial build, review #159 and identify incomplete entry points.
Current blockers include guided material/resource/executable-plan setup and
Dashboard-store backup coverage. If a required path is missing, record the task
as blocked; do not complete it privately through the CLI and count that as the
participant completing the map journey. An early formative session can still
identify confusion, but is not full product acceptance.

Freeze the source SHA, wheel SHA-256, bundle identity, task-pack revision and
exact task text. Use a clean installed wheel outside the checkout, supported
Mac/Linux environments, and the default map. Record viewport, browser, input
method, theme, locale and accessibility needs. Node, a model key and a GPU are
not prerequisites for the core participant tasks.

The operator may stage a clearly labeled recorded project and reviewed CPU
fixture for tasks that need data. The scenario manifest identifies synthetic
actors/data, actual CPU results and unavailable sources separately. It must not
claim an LLM connection, utilization or live availability from a fixture.
Do not prefill the participant's question, decision or conclusion.

Give the fixed task text without a click-by-click script. Product help is
available; record which help the person used. Record every facilitator hint,
intervention, confusion, recovery and elapsed time. A hinted or CLI-rescued
journey is assisted completion, not independent success. Do not invent a time
cutoff after seeing results; record timing to identify friction.

## Fixed participant tasks

Prefix the recorded task text with `[dashboard-v1]`. Keep all sub-observations
in the attached evidence, even if only one T1–T5 record represents the task.

| Task | Text given to the participant | Observable success |
| --- | --- | --- |
| T1 — Install, open and understand | Install the supplied wheel using the provided installation guide. Open the workspace in your browser. In the supplied recorded project, explain what the research aims to learn, what work is recorded as active, what resource it uses, what recently finished and what needs a human decision. Point to the evidence for your answer and identify anything you cannot know. | The installed bundle opens without a checkout/Node. The participant finds and explains the five subjects from actual sources, distinguishes unavailable/synthetic/stale observations, and does not invent status when the scenario lacks evidence. |
| T2 — Create and arrange your research | Start a fresh workspace, write your own research question and success criterion, and save it. Arrange related material in a way that makes sense to you, locate it again and reload. Change the appearance. Ask your Agent for help with this region and explain what happens if no Agent is connected. | The brief and saved arrangement survive reload. Browse/Edit/AI scopes are understood; moving, grouping, resizing, pins and view arrows do not change execution. Theme changes preserve meaning. A saved inbox request is distinguished from an Agent running or replying. |
| T3 — Follow a reviewed CPU experiment to a conclusion | Prepare the supplied small experiment through the available user flow. Inspect the material and resource choices, review the proposal and record your own decision. For an accepted plan with existing valid authority, execute the reviewed CPU fixture, follow its activity and open the result. Compare baseline and candidate, inspect data/code/configuration/decision provenance, and write your own evidence-linked conclusion. | The participant completes the supported flow without raw JSON or memorized internal IDs. Rejecting a proposal starts no work. Accepted decisions and launch authority are distinct. Actual CPU execution, recomputable evaluation and the participant's own conclusion are evidenced. Missing preparation UI is a blocker, not a successful workaround. |
| T4 — Recover without duplicating work | Save a personal arrangement. Follow the supplied disconnect, reload and recovery scenario. Request cancellation of the authorized long-running fixture, then explain whether it has actually stopped. Back up and restore to a new workspace, identifying what was restored and what still needs reconciliation. | View persistence, uncertain-response retry and original task identity are preserved. Requested cancellation, observed stop and unknown are distinguished. Restored event/artifact identities match and nothing relaunches automatically. Map/brief/Agent state coverage is explicitly checked; missing Dashboard-store restore prevents claiming complete workspace recovery. |
| T5 — Inspect reliability and share a diagnostic safely | Use the supplied missing, stale, failed-refresh and provider-incident scenarios to decide what needs attention. Explain whether the official provider report proves your own requests work. Find the supporting source, chart or interpretation author. Produce a diagnostic, inspect it and identify what you would share with a maintainer. | Status provenance, retrieval/expiry, units, history and attributed interpretation are understood. Failure retains and labels old data; missing sources are actionable. Official status is distinguished from request health. Diagnostic review is recorded without posting anything or exposing credentials. |

Run the core task set for both participants. Exercise both Graphite and Warm
paper across the programme, including a theme change by each participant.
Include keyboard navigation/focus and a narrow viewport or touch journey;
record which participant/platform covered each path. Search, pan/zoom, collapse,
minimap and optional arrows must preserve orientation in a supplied large map.
Participant failure to understand an indicator is a product finding even when
the underlying API value is correct.

## Real-host scenario mapping

Retain the R07/R08 fault inventory and exact platform/profile limits. Add a
Dashboard observation for each host outcome. A frontend state and a backend
receipt must refer to the same project/Run/Attempt/Worker and source snapshot.

| Host scenario / evidence | Dashboard behavior to observe |
| --- | --- |
| Pinned onboarding, TLS registration and refusal cases | Connectivity, CPU capability and GPU capability are separate; a tunnel alone does not become available compute. Failures identify the next supported action. |
| Real reviewed CPU start and output transfer | Activity appears on the relevant work/resource; drilldown resolves the same lifecycle and artifact identities. Measured utilization appears only if an actual source supplies it. |
| Disconnect before/after claim, lost response, controller/Worker restart | The UI marks stale or unconfirmed observations, retains request identity and resumes observation. Reconnect cannot start a duplicate task or fabricate completion. |
| Cancel while disconnected and unavailable process identity | Request, verified group stop and unknown remain visibly distinct. No guessed PID kill, inferred stop or automatic rerun. |
| Interrupted transfer, corruption, path/size/count bounds | No partial result is presented as verified; retained work or an explicit refusal explains recovery. |
| Checkpoint restore to a new authorized Attempt | Source checkpoint, compatibility, new identity and actual restored state are inspectable, or unsupported restore is clearly refused. Map reload is not checkpoint restore. |
| Whole-workspace backup/restore | Verify event/CAS/receipt integrity plus the explicitly supported map, brief, theme, pins and Agent state. Older images omit dashboard.sqlite; a separate export is a documented workaround and does not prove integrated recovery. |
| Supported GPU profile, where claimed by the M3 scope | Keep its actual device/runtime/task evidence separate from CPU availability and provider health. Existing pending GPU rows remain pending until performed. |

At least one **authorized remote journey** remains required for R16. Use the
same map-to-host identity checks and record platform, permissions and source
freshness. This does not require every participant to administer SSH credentials.
The [existing real-host runbook](r08-live-acceptance.md) supplies fault mechanics;
this pack supplies the current user journey and presentation checks.

## Evidence compatibility and records

Use a separate directory per task-pack revision and frozen build. Never pool
legacy-cli and dashboard-v1 records to complete one participant's task coverage.
Historical M1/M2 acceptance and #150 observations retain their original SHA,
platform and scope. They may support a technical baseline; they do not establish
current-map comprehension or current-build host behavior.

The existing TrialRecord v0alpha1 can carry this pack without a schema change:

- `trialId`: include the pack, participant alias and task, for example
  `dashboard-v1.participant-a.T1`.
- `taskTextGiven`: start with `[dashboard-v1]` and store the exact fixed prompt.
- `buildUnderTest`: identify the wheel/build; attach a scenario manifest with
  source/bundle identities, pack revision and setup details.
- `evidenceAttached`: include the manifest, observed journey, participant-confirmed
  notes, relevant redacted receipts and linked defects. Do not attach secrets.
- Keep confirmation, intervention, confusion, recovery and verdict fields under
  the existing contract. An implementer cannot confirm for a participant.

`trial scaffold` creates incomplete T1–T5/REMOTE slots, not a validated task-pack
version. Fill each slot with the prompt above. `trial aggregate` checks confirmed
task coverage; it does **not** verify pack/build consistency, usability, participant
independence or host authorization. Review those explicitly before acceptance.
Its `checkpointD: false` remains correct until the separate closure review.

## Review outcome

Report three conclusions separately: technical host verification, independent
map-journey completion, and scoped product/phase acceptance. Both participants
must complete the core journeys independently for a full first-use claim.
Material blockers require fixes and repetition of affected tasks on the repaired
build; earlier failed/assisted records remain available. Report absent Agent,
provider, host and GPU sources honestly.

A formative review may accept a narrow implemented subset and list blocked
steps, but cannot close full R16/Checkpoint D. A recorded result includes the
exact scope, unresolved defects and reviewer decision. No result, invitation,
credential use, model call or live trial is performed by updating this plan.
