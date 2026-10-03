"""Real TLS controller outcome reconciliation; Worker reports are explicit fixtures."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from test_native_output_transport import _payload
from test_native_remote_start import _document, _run, _transport

from llm_research_os.workers import native_outcome
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.native_outcome_client import publish_native_outcome
from llm_research_os.workers.native_outcome_documents import NativeOutcomeRequest
from llm_research_os.workers.native_start_client import publish_native_start


def _outcome(start, phase="completed", observed="exited"):  # type: ignore[no-untyped-def]
    return NativeOutcomeRequest.model_validate(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeOutcomeRequest",
            "start": start.model_dump(mode="json", by_alias=True, exclude_none=True),
            "observation": observed,
            "outcome": phase,
        }
    )


def test_completion_requires_output_and_reported_exit_and_replays_after_expiry(tmp_path):  # type: ignore[no-untyped-def]
    world, plane, _, clock, server, client = _transport(tmp_path)
    try:
        client.poll()
        start = _document(world)
        publish_native_start(client, start)
        report = _outcome(start)
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            publish_native_outcome(client, report)
        assert plane.store.last_sequence() == before
        assert not list(tmp_path.glob("native-outcome-*.json"))
        client.upload_native_output(lease_id=start.lease_id, payload=_payload(world))
        result = publish_native_outcome(client, report)
        assert result.disposition == "completed" and result.launch_allowed is False
        assert _run(world, plane).rebuild().snapshot.status.value == "completed"
        before = plane.store.last_sequence()
        clock[0] += timedelta(days=1)
        assert publish_native_outcome(replace(client), report) == result
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("phase", ["failed", "cancelled", "unknown"])
def test_bound_failure_cancel_and_unknown_are_distinct(tmp_path, phase):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        start = _document(world)
        publish_native_start(client, start)
        if phase == "cancelled":
            plane.revoke_grant(
                grant_id="grant.native",
                actor_id=world.request.actor_id,
                event_id="evt.revoke.outcome",
            )
        result = publish_native_outcome(
            client, _outcome(start, phase, "unknown" if phase == "unknown" else "exited")
        )
        assert result.disposition == phase
        assert _run(world, plane).rebuild().snapshot.status.value == phase
        before = plane.store.last_sequence()
        assert (
            publish_native_outcome(
                client, _outcome(start, phase, "unknown" if phase == "unknown" else "exited")
            )
            == result
        )
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


def test_running_is_passive_and_unknown_can_settle_verified_completion(tmp_path):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        start = _document(world)
        publish_native_start(client, start)
        before = plane.store.last_sequence()
        receipt = publish_native_outcome(client, _outcome(start, "unknown", "running"))
        assert receipt.disposition == "running" and plane.store.last_sequence() == before
        publish_native_outcome(client, _outcome(start, "unknown", "unknown"))
        client.upload_native_output(lease_id=start.lease_id, payload=_payload(world))
        receipt = publish_native_outcome(client, _outcome(start))
        assert receipt.disposition == "completed"
        with pytest.raises(WorkerError, match="refused"):
            publish_native_outcome(client, _outcome(start, "unknown", "unknown"))
        assert _run(world, plane).rebuild().snapshot.status.value == "completed"
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize(
    "fault", ["no-start", "identity", "preparation", "session", "corrupt-journal", "wrong-phase"]
)
def test_outcome_cannot_adopt_foreign_or_missing_start(tmp_path, fault):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        start = _document(world)
        if fault != "no-start":
            publish_native_start(client, start)
        if fault == "identity":
            start = start.model_copy(update={"identity_digest": "jcs-sha256:" + "b" * 64})
        elif fault == "preparation":
            start = start.model_copy(
                update={
                    "preparation": start.preparation.model_copy(update={"grant_id": "grant.other"})
                }
            )
        elif fault == "session":
            client = replace(client, session=server.session_for("worker.other"))
        elif fault == "corrupt-journal":
            next(tmp_path.glob("native-start-*.json")).write_bytes(b"x")
        if fault == "wrong-phase":
            publish_native_outcome(client, _outcome(start, "failed"))
        before = plane.store.last_sequence()
        with pytest.raises(WorkerError, match="refused"):
            publish_native_outcome(client, _outcome(start, "cancelled"))
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("fault", ["attempt", "run"])
def test_partial_terminal_lifecycle_replays_same_report(tmp_path, monkeypatch, fault):  # type: ignore[no-untyped-def]
    world, plane, _, _, server, client = _transport(tmp_path)
    try:
        client.poll()
        start = _document(world)
        publish_native_start(client, start)
        client.upload_native_output(lease_id=start.lease_id, payload=_payload(world))
        report = _outcome(start)
        original = native_outcome._append_bound

        def interrupt(*args, **kwargs):  # type: ignore[no-untyped-def]
            if args[3] == ("attempt.succeeded" if fault == "attempt" else "run.completed"):
                raise OSError("crash")
            return original(*args, **kwargs)

        monkeypatch.setattr(native_outcome, "_append_bound", interrupt)
        with pytest.raises(WorkerError, match="refused"):
            publish_native_outcome(client, report)
        monkeypatch.setattr(native_outcome, "_append_bound", original)
        receipt = publish_native_outcome(client, report)
        assert receipt.disposition == "completed"
        assert publish_native_outcome(client, report) == receipt
    finally:
        server.stop()
        plane.store.close()


@pytest.mark.parametrize("filename", ["request.valid.json", "receipt.valid.json"])
def test_outcome_examples_python_and_schema_match(filename):  # type: ignore[no-untyped-def]
    import json
    from pathlib import Path

    import jsonschema
    from pydantic import ValidationError

    from llm_research_os.workers.native_outcome_documents import NativeOutcomeReceipt

    root = Path(__file__).parents[1]
    is_request = filename.startswith("request")
    contract = "native-outcome-request" if is_request else "native-outcome-receipt"
    schema = json.loads((root / "schemas" / contract / "v0alpha1.schema.json").read_text())
    examples = root / "examples/native-remote-outcome"
    model = NativeOutcomeRequest if is_request else NativeOutcomeReceipt
    document = json.loads((examples / filename).read_text())
    model.model_validate(document)
    jsonschema.validate(document, schema)
    invalid = "request.invalid-unobserved.json" if is_request else "receipt.invalid-launch.json"
    document = json.loads((examples / invalid).read_text())
    with pytest.raises(ValidationError):
        model.model_validate(document)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)
    if not is_request:
        document["launchAllowed"] = 0
        with pytest.raises(ValidationError):
            model.model_validate(document)


@pytest.mark.parametrize("phase", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("observation", ["running", "unknown"])
def test_terminal_phase_requires_actual_exit_report(tmp_path, phase, observation):  # type: ignore[no-untyped-def]
    from pydantic import ValidationError

    world, plane, _, _, server, _ = _transport(tmp_path)
    try:
        before = plane.store.last_sequence()
        with pytest.raises(ValidationError):
            _outcome(_document(world), phase, observation)
        assert plane.store.last_sequence() == before
    finally:
        server.stop()
        plane.store.close()
