from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_research_os.canonical import legacy_content_digest
from llm_research_os.projections.sqlite import rebuild_query_tables
from llm_research_os.runs import RunControl, RunSnapshot, RunStateProjection
from llm_research_os.storage import EventStore

SPEC = "sha256:" + "11" * 32
REGISTRY = "sha256:" + "22" * 32
PLAN = "sha256:" + "33" * 32
PROJECT = "project.example"
RUN = "run.example"


def _queued_draft() -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "id": "evt.run.queued.1",
        "source": "https://researchos.dev/projects/example",
        "type": "run.queued",
        "time": "2026-08-29T12:00:00Z",
        "subject": RUN,
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
            "runId": RUN,
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


def test_run_control_skips_prefix_when_projection_matches_high_water(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with EventStore(database) as store:
        control = RunControl(store, project_id=PROJECT, run_id=RUN)
        control.append(_queued_draft())
        first = control.rebuild()
        second = control.rebuild()
        assert first.snapshot == second.snapshot
        assert first.last_sequence == second.last_sequence == 1
