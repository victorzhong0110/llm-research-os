# Dashboard composition v0alpha1

A DashboardDocument is a project-bound, versioned view of a workspace. A
DashboardWrite supplies the full state, expectedRevision, unique requestId,
author and authorKind. The generated dashboard-document schema is normative.

Components have stable identities, bounded geometry, optional containment by a
group, and bindings to workspace/runs/research/events/telemetry. Containment is
acyclic, at most eight levels deep; children fit inside the parent below its
48-unit header. Relations annotate view intent only; no relation is a command
or an execution fact. Custom renderers are closed presentation choices, not
JavaScript, HTML, arbitrary URLs, or plugin authority.

The local API GET /api/v0alpha1/dashboard returns the latest view; optional
revision reads retained history. POST accepts DashboardWrite under the existing
Host, Origin, session, CSRF, body-size and parser limits. A malformed document
is refused with 400; stale revision, project mismatch or pin conflict with 409.
The same request identity and content replay the original retained result;
reusing an identity with different content is refused. The same model and
transaction are used by `researchos dashboard show/apply --root ROOT`.

SQLite serializes compare-and-swap writes. The latest 30 revisions are retained;
revision zero is the empty map. Restoration is a new write against the current
revision. The sidecar dashboard.sqlite is independent from EventStore, CAS,
Worker roots and application receipts. Older workspace backup formats do not
include it: export a map separately before backup until integration is added.

Agent writes cannot remove, unpin, move, resize, reparent, retype or rebind pinned
components, nor move their ancestors. authorKind is cooperative attribution
inside the trusted local workspace, not authentication against a malicious
same-user process. No model is called and no credentials are read by composition.
The schema permits 2,000 components and 6,000 edges; actual documents must also
fit the advertised API byte/node/depth limits. Do not infer those cardinalities
are simultaneously available under every configured request limit.


## Agent inbox and external observations

GET/POST `/api/v0alpha1/dashboard/agents` lists tasks or accepts AgentAsk/AgentReply.
The existing session, origin, CSRF and body limits apply. Ask freezes the saved
map revision and scope transactionally. Reply is idempotent and immutable; it
never applies its proposal. A scoped DashboardWrite cannot change outside nodes,
global appearance/viewport or relations crossing outside the scope. New
contained descendants may extend a selected region. Pin and revision checks also
run at apply time. Attribution is cooperative, not proof of Agent identity.

`researchos dashboard observe` accepts the closed DashboardObservation contract;
GET `/api/v0alpha1/dashboard/observations` returns stored source reports. Browser
POST is not supported. The CLI bounds a source to 32 KiB and storage to 100
sources. Values are finite; timestamps are timezone-aware, history is ordered,
and sample times cannot exceed the report time. Reports more than five minutes
in the future are refused. An update must advance its source timestamp; exact
replays are idempotent. The UI evaluates expiry independently and labels origin,
measurement meaning, provenance and attributed interpretation.
