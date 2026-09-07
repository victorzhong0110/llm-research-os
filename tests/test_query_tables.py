from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_research_os.canonical import legacy_canonical_json, legacy_content_digest
from llm_research_os.projections.sqlite import rebuild_query_tables
from llm_research_os.runs import RunControl, RunSnapshot, RunStateProjection
from llm_research_os.runs.models import run_snapshot_document
from llm_research_os.storage import EventStore
from llm_research_os.storage.errors import EventStoreError
from llm_research_os.storage.models import RunProjectionRecord

SPEC = "sha256:" + "11" * 32
REGISTRY = "sha256:" + "22" * 32
PLAN = "sha256:" + "33" * 32
PROJECT = "project.example"
RUN = "run.example"
RUN_OTHER = "run.other"


def _queued_draft(*, run_id: str = RUN, event_id: str = "evt.run.queued.1") -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": "https://researchos.dev/projects/example",
        "type": "run.queued",
        "time": "2026-08-29T12:00:00Z",
        "subject": run_id,
        "dataschema": "https://researchos.dev/schemas/research-event/v0alpha1.schema.json",
        "datacontenttype": "application/json",
        "streamid": "stream.example",
        "data": {
            "schemaVersion": "v0alpha1",
            "actor": {"id": "researcher.alice"},
            "projectId": PROJECT,
            "experimentRevision": 1,
            "payload": {
                "workflowId": "wf.train",
                "specDigest": SPEC,
                "registryDigest": REGISTRY,
                "planDigest": PLAN,
                "maxAttempts": 1,
            },
            "evidenceRefs": [],
            "runId": run_id,
        },
    }


def test_rebuild_query_tables_indexes_spec_and_artifact_digests(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        stored = store.append(_queued_draft())
        rebuild_query_tables(store)
        specs = store.list_spec_revisions()
        assert len(specs) == 1
        assert specs[0].project_id == PROJECT
        assert specs[0].revision == 1
        assert specs[0].spec_digest == SPEC
        assert specs[0].first_seen_sequence == stored.sequence
        artifacts = {item.digest: item for item in store.list_artifact_index()}
        assert set(artifacts) == {SPEC, REGISTRY, PLAN}
        roles = {(item.digest, item.role) for item in store.list_artifact_links()}
        assert roles == {
            (SPEC, "spec"),
            (REGISTRY, "registry"),
            (PLAN, "plan"),
        }
        projection = store.get_run_projection(PROJECT, RUN)
        assert projection is not None
        assert projection.last_sequence == stored.sequence
        snapshot = RunSnapshot.model_validate_json(projection.snapshot_json or "")
        folded = RunStateProjection(project_id=PROJECT, run_id=RUN).apply(None, stored.event)
        assert snapshot == folded


def test_query_tables_rebuild_from_events_after_tamper(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        store.append(_queued_draft())
        rebuild_query_tables(store)
        original_specs = store.list_spec_revisions()
        original_artifacts = store.list_artifact_index()
        original_links = store.list_artifact_links()
        store._connection.execute("DELETE FROM spec_revisions")
        store._connection.execute("DELETE FROM artifact_links")
        store._connection.execute("DELETE FROM artifacts")
        assert store.list_spec_revisions() == ()
        rebuild_query_tables(store)
        assert store.list_spec_revisions() == original_specs
        assert store.list_artifact_index() == original_artifacts
        assert store.list_artifact_links() == original_links


def test_run_control_discards_tampered_projection_and_refolds(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())
        cached = store.get_run_projection(PROJECT, RUN)
        assert cached is not None
        assert cached.snapshot_json is not None
        tampered = cached.snapshot_json.replace(PROJECT, "project.tampered", 1)
        store._connection.execute(
            """
            UPDATE run_projections
            SET snapshot_json = ?, snapshot_digest = ?
            WHERE project_id = ? AND run_id = ?
            """,
            (tampered, legacy_content_digest({"tampered": True}), PROJECT, RUN),
        )
        rebuilt = control.rebuild()
        assert rebuilt.snapshot is not None
        assert rebuilt.snapshot.project_id == PROJECT
        assert rebuilt.last_sequence == 1


def test_run_control_rejects_foreign_run_snapshot_under_cache_key(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        other = RunControl(store, project_id=PROJECT, run_id=RUN_OTHER)
        first = control.append(_queued_draft())
        second = other.append(_queued_draft(run_id=RUN_OTHER, event_id="evt.run.queued.other"))
        foreign = store.get_run_projection(PROJECT, RUN_OTHER)
        assert foreign is not None
        store._connection.execute(
            """
            UPDATE run_projections
            SET last_sequence = ?, snapshot_json = ?, snapshot_digest = ?
            WHERE project_id = ? AND run_id = ?
            """,
            (
                foreign.last_sequence,
                foreign.snapshot_json,
                foreign.snapshot_digest,
                PROJECT,
                RUN,
            ),
        )
        rebuilt = control.rebuild()
        assert rebuilt.snapshot is not None
        assert rebuilt.snapshot.run_id == RUN
        assert rebuilt.snapshot.last_event_id == first.stored.event.id
        assert rebuilt.snapshot.last_event_id != second.stored.event.id


def test_run_control_rejects_fabricated_same_run_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        committed = control.append(_queued_draft())
        cached = store.get_run_projection(PROJECT, RUN)
        assert cached is not None
        assert cached.snapshot_json is not None
        forged = RunSnapshot.model_validate_json(cached.snapshot_json).model_copy(
            update={"last_event_id": "evt.forged.not-from-log"}
        )
        payload = run_snapshot_document(forged)
        store.upsert_run_projection(
            RunProjectionRecord(
                project_id=PROJECT,
                run_id=RUN,
                last_sequence=cached.last_sequence,
                snapshot_json=legacy_canonical_json(payload),
                snapshot_digest=legacy_content_digest(payload),
            )
        )
        rebuilt = control.rebuild()
        assert rebuilt.snapshot is not None
        assert rebuilt.snapshot.last_event_id == committed.stored.event.id
        assert rebuilt.snapshot.last_event_id != "evt.forged.not-from-log"


def test_run_control_append_succeeds_when_cache_write_fails(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)

        def boom(_record: RunProjectionRecord) -> None:
            raise EventStoreError("projection cache write failed")

        store.upsert_run_projection = boom  # type: ignore[method-assign]
        result = control.append(_queued_draft())
        assert result.stored.sequence == 1
        assert result.snapshot is not None
        assert store.get_event("evt.run.queued.1") is not None


def test_run_control_rebuild_matches_after_projection_cache_hit(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())
        first = control.rebuild()
        second = control.rebuild()
        assert first.snapshot == second.snapshot
        assert first.last_sequence == second.last_sequence == 1
