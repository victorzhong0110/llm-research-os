# ADR-0023: Inert Manifests and Pure Deterministic Dry-Run

- Status: Proposed
- Date: 2026-08-22

## Context

M0 needs to prove that ResearchSpec workflows can resolve replaceable blocks and become an
inspectable plan. Calling a handler before ResearchEvent, append-only storage and the Run
state machine exist would make failures indistinguishable from success and would violate the
current threat-model gates.

Unversioned or mutable block lookup would also allow the same immutable ResearchSpec to
resolve to different behavior as a registry evolves.

## Decision

BlockManifest is inert structured data. A task binds an exact semantic `blockVersion`; the
registry resolves only `(blockType, blockVersion)`, rejects duplicate keys, seals before
planning and records canonical manifest and registry digests.

The M0 `dry-run` command is a pure static compiler. It:

- creates a defensive ResearchSpec snapshot;
- validates manifest configuration and explicit data ports;
- preserves control edges and exact data-port bindings in the plan;
- groups nodes into stable lexical topological stages;
- represents loops symbolically and never evaluates `until`;
- records resource and approval requirements without authorizing them;
- retains execution-relevant resource provider/model and all declared bounds;
- emits no runtime, network, filesystem, GPU, secret, database or paid side effect.

There is no plugin discovery or entrypoint import in this slice. A `ready` report means only
that a complete static plan exists.

## Consequences

- Requiring `blockVersion` is a deliberate breaking adjustment inside the unreleased,
  experimental v0alpha1 contract. Existing examples migrate by adding an exact semantic
  version; no persisted Run or released compatibility promise exists yet.
- Plans are reviewable and content-addressed before execution exists.
- v0alpha1 digests remain a Python reference convention; a normative cross-language
  canonicalization ADR is required before stable multi-language verification.
- Exact versions plus manifest digests expose registry substitution instead of silently
  choosing “latest”.
- The static compiler cannot yet prove runtime success, cancellation, retry or recovery.
- ADR-0026 implements SimulatedRuntime on top of this dry-run boundary, the
  ADR-0024 reducer, and the ADR-0025 append gate. Simulated completion is still
  not training success, and unknown remains distinct from failure.
- ADR-0030 adds an exact three-digest authorization gate without changing the
  meaning of `ready`; the report itself remains unapproved and inert.

## Validation

Tests cover exact resolution, duplicate rejection, configuration and port failures, stable
ordering and digests, symbolic loops, immutable snapshots and tripwires for process, import,
network and expression execution.
