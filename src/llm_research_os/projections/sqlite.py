"""Rebuild SQLite query tables from verified ResearchEvent facts."""

from __future__ import annotations

import re
from collections.abc import Iterator

from llm_research_os.canonical import (
    SEMANTIC_DIGEST_PATTERN,
    legacy_canonical_json,
    legacy_content_digest,
)
from llm_research_os.events.models import ResearchEvent
from llm_research_os.projections.replay import replay_events
from llm_research_os.runs.models import TYPE_RUN_QUEUED, RunSnapshot, run_snapshot_document
from llm_research_os.runs.reducer import RunStateProjection
from llm_research_os.storage.errors import EventIntegrityError
from llm_research_os.storage.models import (
    ArtifactIndexRecord,
    ArtifactLinkRecord,
    RunProjectionRecord,
    SpecRevisionRecord,
)
from llm_research_os.storage.store import EventStore

_DIGEST = re.compile(SEMANTIC_DIGEST_PATTERN)
_PAYLOAD_DIGEST_ROLES = {
    "specDigest": "spec",
    "registryDigest": "registry",
    "planDigest": "plan",
    "decisionDigest": "decision",
}


def rebuild_query_tables(store: EventStore) -> None:
    """Replace projection tables from a frozen verified prefix of ``events``.

    EventStore remains the only authority. The query tables are consumers and
    must match a full replay of the same prefix (TM-011).
    """

    high_water = store.freeze_high_water()
    specs: dict[tuple[str, int], SpecRevisionRecord] = {}
    artifacts: dict[str, ArtifactIndexRecord] = {}
    links: list[ArtifactLinkRecord] = []
    folds: dict[tuple[str, str], tuple[RunStateProjection, RunSnapshot | None]] = {}
    for stored in replay_events(
        store,
        freeze_high_water=False,
        until_sequence=high_water,
        page_size=256,
    ):
        event = stored.event
        _index_spec_revision(specs, event, stored.sequence)
        for digest, role in _digest_refs(event):
            existing = artifacts.get(digest)
            if existing is None:
                artifacts[digest] = ArtifactIndexRecord(
                    digest=digest,
                    byte_length=None,
                    first_seen_sequence=stored.sequence,
                )
            links.append(
                ArtifactLinkRecord(
                    digest=digest,
                    event_sequence=stored.sequence,
                    role=role,
                )
            )
        run_id = event.data.run_id
        if run_id is None:
            continue
        key = (event.data.project_id, run_id)
        projection, snapshot = folds.get(
            key,
            (RunStateProjection(project_id=event.data.project_id, run_id=run_id), None),
        )
        folds[key] = (projection, projection.apply(snapshot, event))

    store.replace_query_tables(
        spec_revisions=tuple(
            sorted(specs.values(), key=lambda item: (item.first_seen_sequence, item.project_id))
        ),
        artifacts=tuple(
            sorted(artifacts.values(), key=lambda item: (item.first_seen_sequence, item.digest))
        ),
        artifact_links=tuple(links),
        run_projections=tuple(
            _run_projection_record(project_id, run_id, high_water, snapshot)
            for (project_id, run_id), (_projection, snapshot) in sorted(folds.items())
            if high_water > 0
        ),
    )


def _index_spec_revision(
    specs: dict[tuple[str, int], SpecRevisionRecord],
    event: ResearchEvent,
    sequence: int,
) -> None:
    if event.type != TYPE_RUN_QUEUED:
        return
    spec_digest = event.data.payload.get("specDigest")
    if type(spec_digest) is not str or _DIGEST.fullmatch(spec_digest) is None:
        return
    key = (event.data.project_id, event.data.experiment_revision)
    existing = specs.get(key)
    if existing is None:
        specs[key] = SpecRevisionRecord(
            project_id=event.data.project_id,
            revision=event.data.experiment_revision,
            spec_digest=spec_digest,
            first_seen_sequence=sequence,
        )
        return
    if existing.spec_digest != spec_digest:
        raise EventIntegrityError(
            "spec revision digest conflict for "
            f"{event.data.project_id} revision {event.data.experiment_revision}"
        )


def _digest_refs(event: ResearchEvent) -> Iterator[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for digest, role in _walk_digests(event.data.payload, default_role="payload"):
        key = (digest, role)
        if key in seen:
            continue
        seen.add(key)
        yield digest, role
    for ref in event.data.evidence_refs:
        if _DIGEST.fullmatch(ref) is None:
            continue
        key = (ref, "evidence")
        if key in seen:
            continue
        seen.add(key)
        yield ref, "evidence"


def _walk_digests(value: object, *, default_role: str) -> Iterator[tuple[str, str]]:
    if type(value) is dict:
        mapping = value
        for key, item in mapping.items():
            if (
                type(key) is str
                and key in _PAYLOAD_DIGEST_ROLES
                and type(item) is str
                and _DIGEST.fullmatch(item) is not None
            ):
                yield item, _PAYLOAD_DIGEST_ROLES[key]
                continue
            yield from _walk_digests(item, default_role=default_role)
        return
    if type(value) is list:
        for item in value:
            yield from _walk_digests(item, default_role=default_role)
        return
    if type(value) is str and _DIGEST.fullmatch(value) is not None:
        yield value, default_role


def _run_projection_record(
    project_id: str,
    run_id: str,
    last_sequence: int,
    snapshot: RunSnapshot | None,
) -> RunProjectionRecord:
    if snapshot is None:
        return RunProjectionRecord(
            project_id=project_id,
            run_id=run_id,
            last_sequence=last_sequence,
            snapshot_json=None,
            snapshot_digest=None,
        )
    payload = run_snapshot_document(snapshot)
    return RunProjectionRecord(
        project_id=project_id,
        run_id=run_id,
        last_sequence=last_sequence,
        snapshot_json=legacy_canonical_json(payload),
        snapshot_digest=legacy_content_digest(payload),
    )
