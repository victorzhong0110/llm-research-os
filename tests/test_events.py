from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.events.models import ResearchEvent
from llm_research_os.spec.io import load_document

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


def _valid_document() -> dict[object, object]:
    return load_document(EXAMPLES / "valid" / "minimal.json")


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.json")), ids=lambda p: p.name)
def test_valid_event_examples(path: Path) -> None:
    event = ResearchEvent.model_validate(load_document(path))
    assert event.specversion == "1.0"
    assert event.data.schema_version == "v0alpha1"
    dumped = event.model_dump(mode="json", by_alias=True)
    assert dumped["specversion"] == "1.0"
    assert dumped["data"]["schemaVersion"] == "v0alpha1"
    assert "schema_version" not in dumped["data"]


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "invalid").glob("*.json")), ids=lambda p: p.name
)
def test_invalid_event_examples(path: Path) -> None:
    with pytest.raises(ValidationError):
        ResearchEvent.model_validate(load_document(path))


def test_unknown_envelope_and_data_fields_are_rejected() -> None:
    document = _valid_document()
    document["surprise"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchEvent.model_validate(document)

    document = _valid_document()
    document["data"]["timestamp"] = "2026-08-21T12:00:00Z"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchEvent.model_validate(document)


def test_id_time_and_sequence_are_not_generated() -> None:
    for name in ("id", "time", "sequence"):
        field = ResearchEvent.model_fields[name]
        assert field.is_required()
        assert field.default_factory is None

    document = _valid_document()
    del document["id"]
    del document["time"]
    del document["sequence"]
    with pytest.raises(ValidationError) as exc_info:
        ResearchEvent.model_validate(document)
    locations = {error["loc"][0] for error in exc_info.value.errors()}
    assert locations >= {"id", "time", "sequence"}


def test_time_requires_a_timezone() -> None:
    document = _valid_document()
    document["time"] = "2026-08-21T12:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        ResearchEvent.model_validate(document)

    document["time"] = datetime(2026, 8, 21, 12, 0, 0)
    with pytest.raises(ValidationError, match="timezone"):
        ResearchEvent.model_validate(document)

    document["time"] = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
    event = ResearchEvent.model_validate(document)
    assert event.time.tzinfo is not None


def test_evidence_refs_must_be_unique() -> None:
    document = _valid_document()
    document["data"]["evidenceRefs"] = ["ev.one", "ev.two", "ev.one"]
    with pytest.raises(ValidationError, match="evidenceRefs entries must be unique"):
        ResearchEvent.model_validate(document)


def test_payload_rejects_non_finite_and_non_json_values() -> None:
    document = _valid_document()
    document["data"]["payload"] = {"loss": float("nan")}
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ResearchEvent.model_validate(document)

    document = _valid_document()
    document["data"]["payload"] = {"unsafe": object()}
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ResearchEvent.model_validate(document)


def test_payload_rejects_embedded_bodies() -> None:
    document = _valid_document()
    document["data"]["payload"] = {"artifact": {"content": "inline document"}}
    with pytest.raises(ValidationError, match="must not embed file bytes or document bodies"):
        ResearchEvent.model_validate(document)


def test_text_must_be_unicode_scalars() -> None:
    document = _valid_document()
    document["data"]["payload"] = {"note": "\ud800"}
    with pytest.raises(ValidationError, match="Unicode scalar"):
        ResearchEvent.model_validate(document)


def test_assignment_validation_preserves_invariants() -> None:
    event = ResearchEvent.model_validate(_valid_document())
    data = deepcopy(event.data)
    with pytest.raises(ValidationError, match="unique"):
        data.evidence_refs = ["ev.one", "ev.one"]


def test_optional_run_fields_round_trip_with_external_names() -> None:
    event = ResearchEvent.model_validate(load_document(EXAMPLES / "valid" / "correlated-run.json"))
    dumped = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["correlationid"] == "corr.train-loop"
    assert dumped["causationid"] == "evt.run.started.1"
    assert dumped["data"]["runId"] == "run.sim-1"
    assert dumped["data"]["attemptId"] == "attempt.1"
    assert dumped["data"]["blockId"] == "simulate"
    assert "correlation_id" not in dumped
    assert "run_id" not in dumped["data"]
