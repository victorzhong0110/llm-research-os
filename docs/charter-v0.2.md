# Project charter v0.2 — consolidated reading

Status: review candidate. This consolidation changes no accepted constitutional
decision and creates no release or spending approval. On acceptance, it replaces
the need to interpret the v0.1 errata in chronological order. The Chinese v0.1
and chapter 18 remain the preserved source texts.

## Scope and precedence

Unchanged clauses in [charter v0.1](charter-v0.1.md) and the
[chapter 18 decision guide](chapter-18-decision-guide-v0.1.md) are incorporated
by reference. The following consolidated clauses apply in their affected
sections. ADRs cited below explain the accepted changes; an implementation
status table never silently changes a constitutional requirement.

| Affected clauses | Consolidated rule | Original errata / authority |
| --- | --- | --- |
| Purpose; human/AI boundary | A model-, backend- and compute-neutral research control plane records research information and authority as distinct facts. The researcher teaches as well as approves. AI cannot infer spending or data-use consent. | E12; ADR-0039 |
| Core architecture | ResearchSpec is declarative intent; append-only ResearchEvent is the fact source. SQLite query tables are rebuildable projections; CAS stores bytes. Runtime observation must not be replaced by proposed or inferred success. | ADR-0015, ADR-0041 |
| M0 runtime scope | M0 is closed under ADR-0037. NativeProcessPreflight is non-launching; a real NativeProcessRuntime remains a separately reviewed delivery. Neither an audit event nor a preflight grants execution. | E1–E3; ADR-0034, ADR-0037, ADR-0038 |
| M1 checkpoint | Mock proposal with prediction and falsification → preserved dissent → reasoned researcher decision → simulated execution → event-linked static report, offline at ¥0. Include the question/answer channel and human-attention indicators. Rejecting a proposal must not queue a Run. Numbered slices alone are not acceptance. | E4, E14, E15, E17; ADR-0038, ADR-0039, ADR-0042 |
| Research objects | Decisions carry rationale and overridden dissent references. Questions explain uncertainty and why observation cannot resolve it. Answers carry rights and are data, not instructions. Only human/policy actors decide or answer; AI/system actors ask. These facts never enter training by default. | E13, E15; research-decision-objects-v0alpha1 |
| Authorization | Exact digest and capability binding is required. Unknown capability names fail closed. M1 local citation consumption is distinct from the M2 signed HMAC Worker credential lifecycle. No asymmetric/JWT or native execution claim follows from HMAC delivery. | E6, E17; ADR-0042, ADR-0043 |
| Adapter trust | Core-maintained Mock and HTTP adapters may execute in process under T0/T1. The T2 subprocess boundary must precede the first community adapter; it is not waived for public plugins. | E5; ADR-0038 |
| User surfaces | YAML, Python SDK and static report can represent the same experiment; an editable canvas is deferred beyond M2. M1's minimal view is a static report. Public usability still requires separate acceptance. | E4, E7 |
| Language and engineering | English is primary for maintained engineering documents and code. README and CONTRIBUTING retain synchronized Chinese translations; preserved charter originals remain Chinese. No comment-ratio target. Python 3.12/3.13 are required; 3.14 is forward compatibility. | E9, E16; ADR-0013, ADR-0040 |
| Contributions | External fork commits require DCO 1.1; no CLA. ADRs record constraints/tradeoffs; CLI details belong in protocols and guides. Changes to accepted decisions need an ADR. | E8, E10, E11 |

## M2 evidence and remaining public-MVP requirements

The [M2 matrix](evidence/m2-wsl2-cuda-live/m2-closure-matrix.md) is authoritative
for experiment claims. The nineteen-PR stack was integrated through #73 at
`229d1b0`; the evidence tip is `57ffdae`. CPU two-host execution, reconnect,
cancel, CUDA first training, checkpoint upload and cuda.11 full-state restore
were demonstrated on Windows/WSL2 + Docker Engine. The MPS profile is separate.
cuda.9 remains partial and cuda.10 remains failed; historical events are not
rewritten. Paid cloud remains untested at ¥0.

Charter §14.5 is still public-MVP acceptance, not a consequence of merging M2.
Usable SSH onboarding, a Web surface, a restricted non-OCI execution profile,
public-service parsing limits and plugin isolation require explicit M3 delivery
and security gates. Tags, releases and cloud payments remain separate actions.

## Maintenance interpretation

[ADR-0060](adr/0060-maintenance-boundaries-and-exact-quality-gates.md) proposes
strict coverage, explicit output ownership, centralized capability names and
generated core payload schemas without changing existing event payloads or
historical digests. The maintained [status index](status.json) distinguishes
implementation, platform evidence and public release; it is not an authorization.
