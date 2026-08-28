from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.events.models import ResearchEvent, validate_event_document
from llm_research_os.spec.io import load_document

EXAMPLES = Path(__file__).parents[1] / "examples" / "events"


def _valid_document() -> dict[str, object]:
    return load_document(EXAMPLES / "valid" / "minimal.json")


@pytest.mark.parametrize("path", sorted((EXAMPLES / "valid").glob("*.json")), ids=lambda p: p.name)
def test_valid_event_examples(path: Path) -> None:
    event = validate_event_document(load_document(path))
    assert event.specversion == "1.0"
    assert event.data.schema_version == "v0alpha1"
    dumped = event.model_dump(mode="json", by_alias=True)
    assert dumped["specversion"] == "1.0"
    assert dumped["sequencetype"] == "Integer"
    assert dumped["data"]["schemaVersion"] == "v0alpha1"
    assert "schema_version" not in dumped["data"]
    assert isinstance(dumped["sequence"], str)


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "invalid").glob("*.json")), ids=lambda p: p.name
)
def test_invalid_event_examples(path: Path) -> None:
    with pytest.raises(ValidationError):
        validate_event_document(load_document(path))


def test_unknown_envelope_and_data_fields_are_rejected() -> None:
    document = _valid_document()
    document["surprise"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_event_document(document)

    document = _valid_document()
    document["data"]["timestamp"] = "2026-08-21T12:00:00Z"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_event_document(document)


def test_python_field_names_are_rejected_on_external_documents() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["schema_version"] = data.pop("schemaVersion")
    data["project_id"] = data.pop("projectId")
    data["experiment_revision"] = data.pop("experimentRevision")
    data["evidence_refs"] = data.pop("evidenceRefs")
    with pytest.raises(ValidationError):
        validate_event_document(document)


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
        validate_event_document(document)
    locations = {error["loc"][0] for error in exc_info.value.errors()}
    assert locations >= {"id", "time", "sequence"}


def test_time_requires_an_rfc3339_timezone_string() -> None:
    document = _valid_document()
    document["time"] = "2026-08-21T12:00:00"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["time"] = datetime(2026, 8, 21, 12, 0, 0)
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["time"] = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["time"] = 1_724_241_600
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["time"] = "2026-08-21T12:00:00Z"
    event = validate_event_document(document)
    assert event.time == "2026-08-21T12:00:00Z"


def test_numeric_fields_reject_string_and_bool_coercion() -> None:
    document = _valid_document()
    document["sequence"] = 1
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document = _valid_document()
    document["sequence"] = True
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document = _valid_document()
    document["streamversion"] = "0"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document = _valid_document()
    document["streamversion"] = True
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["experimentRevision"] = "1"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["experimentRevision"] = True
    with pytest.raises(ValidationError):
        validate_event_document(document)


def test_sequence_zero_and_out_of_range_values_are_rejected() -> None:
    document = _valid_document()
    document["sequence"] = "0"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["sequence"] = "2147483648"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["sequence"] = "01"
    with pytest.raises(ValidationError):
        validate_event_document(document)


def test_cloudevents_identity_strings_are_not_trimmed() -> None:
    document = _valid_document()
    document["id"] = " evt.minimal.1 "
    event = validate_event_document(document)
    assert event.id == " evt.minimal.1 "

    document = _valid_document()
    document["type"] = " run.started "
    with pytest.raises(ValidationError):
        validate_event_document(document)


def test_source_rejects_invalid_uri_references_and_forbidden_characters() -> None:
    document = _valid_document()
    document["source"] = "https://researchos.dev/projects/%zz"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["source"] = "https://researchos.dev/projects/\x00"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["source"] = "https://researchos.dev/projects/\u007f"
    with pytest.raises(ValidationError):
        validate_event_document(document)

    document["id"] = "evt\u0000hidden"
    document["source"] = "https://researchos.dev/projects/example-minimal"
    with pytest.raises(ValidationError):
        validate_event_document(document)


def test_evidence_refs_must_be_unique() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["evidenceRefs"] = ["ev.one", "ev.two", "ev.one"]
    with pytest.raises(ValidationError, match="evidenceRefs entries must be unique"):
        validate_event_document(document)


def test_payload_rejects_non_finite_and_non_json_values() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["payload"] = {"loss": float("nan")}
    with pytest.raises(ValidationError, match="JSON-compatible"):
        validate_event_document(document)

    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["payload"] = {"unsafe": object()}
    with pytest.raises(ValidationError, match="JSON object, array, string, number"):
        validate_event_document(document)


def test_payload_rejects_embedded_bodies() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["payload"] = {"artifact": {"content": "inline document"}}
    with pytest.raises(ValidationError, match="must not embed file bytes or document bodies"):
        validate_event_document(document)


def test_payload_rejects_embedded_bodies_inside_tuples() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["payload"] = {"items": ({"body": "inline"},)}
    with pytest.raises(ValidationError, match="JSON object, array, string, number"):
        validate_event_document(document)


def test_text_must_be_unicode_scalars() -> None:
    document = _valid_document()
    data = document["data"]
    assert isinstance(data, dict)
    data["payload"] = {"note": "\ud800"}
    with pytest.raises(ValidationError, match="Unicode scalar"):
        validate_event_document(document)


def test_assignment_validation_preserves_invariants() -> None:
    event = validate_event_document(_valid_document())
    data = deepcopy(event.data)
    with pytest.raises(ValidationError, match="unique"):
        data.evidence_refs = ["ev.one", "ev.one"]


def test_optional_run_fields_round_trip_with_external_names() -> None:
    event = validate_event_document(load_document(EXAMPLES / "valid" / "correlated-run.json"))
    dumped = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["correlationid"] == "corr.train-loop"
    assert dumped["causationid"] == "evt.run.started.1"
    assert dumped["sequence"] == "7"
    assert dumped["sequencetype"] == "Integer"
    assert dumped["data"]["runId"] == "run.sim-1"
    assert dumped["data"]["attemptId"] == "attempt.1"
    assert dumped["data"]["blockId"] == "simulate"
    assert "correlation_id" not in dumped
    assert "run_id" not in dumped["data"]
