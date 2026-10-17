# ADR-0067: Rebaseline acceptance around the research map

Status: Accepted direction under the maintainer's 2026-10-18 request; execution
and acceptance results remain pending.

## Context

ADR-0066 made the semantic Dashboard the primary work surface. The original R16
kit tests a CLI-oriented installation/recovery journey and cannot establish
comprehension of the new interface. The maintainer explicitly requested revised
real-host/human acceptance and a README reflecting the current product.

## Decision

Use the versioned **dashboard-v1** task pack in
[Dashboard acceptance](../guides/dashboard-acceptance.md) for future participant
journeys. Preserve T1–T5/REMOTE identifiers and record exact task text/build/pack
identity through existing TrialRecord fields and an attached manifest. Separate
packs/builds; record-count aggregation cannot certify their consistency.

Review map comprehension and independent task completion alongside the actual
host evidence. Add checks for source freshness, meaningful relationships,
Browse/Edit/AI scope, view-versus-domain changes, evidence drilldown and recovery
of personal arrangement. Preserve at least two independent users and one
authorized remote journey for R16, and the existing execution/authority,
identity, integrity, cancellation/unknown and platform-profile requirements.

Historical evidence remains attributed to its original scope and identity.
Interface evidence is superseded when the journey changes; a UI redesign does
not make old host observations new or erase their historical validity. Re-run
changed paths on the current build and record other pending real-host checks.

## Consequences

Missing guided execution setup or Dashboard backup coverage is a visible trial
blocker. Facilitator CLI workarounds cannot count as independent map completion.
Technical host verification, human usability and scoped acceptance are reviewed
separately. Existing aggregate output remains coverage-only and never closes
Checkpoint D. The old campaign stays paused until subsequently resumed under
existing maintainer authorization; this decision supplies no trial results,
credentials, spending or release authority.
