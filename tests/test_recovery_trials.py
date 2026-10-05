"""R16 trial kit: an unrun trial can never be mistaken for a clean one.

The point of these tests is negative space. A trial programme is mostly empty,
so the failure this guards against is a record that *looks* complete because
nobody checked whether the participant's account was ever written down.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from llm_research_os.cli.contracts import SCHEMA_CONTRACTS
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.recovery.trial import (
    TRIAL_TASKS,
    TrialKit,
    TrialRecord,
    load_trial_kit,
    load_trial_record,
)

ROOT = Path(__file__).parents[1]
BASE_TIME = "2026-10-06T09:00:00Z"


def _record(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "apiVersion": "researchos.dev/trial/v0alpha1",
        "kind": "TrialRecord",
        "trialId": "TRIAL-01/A/2026-10-06",
        "task": "T1",
        "participantAlias": "participant-a",
        "recordedAt": BASE_TIME,
        "recordedBy": "observer",
        "buildUnderTest": "llm_research_os-0.0.0-py3-none-any.whl",
        "platform": "Linux 6.8, x86_64",
        "pythonVersion": "3.12.14",
        "modelKey": "absent",
        "gpu": "absent",
        "node": "absent",
        "sourceCheckout": "absent",
        "taskTextGiven": "Install the wheel and run the demonstration.",
        "completed": True,
        "exitState": "workspace demo reported a healthy workspace",
        "elapsedSeconds": 240,
        "interventions": [],
        "confusionObserved": [],
        "recoveryObserved": [],
        "defectsFound": [],
        "evidenceAttached": ["doctor.json"],
        "verdict": "core-journey-completed",
    }
    document.update(overrides)
    return document


def _cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "llm_research_os", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.parametrize("name", ("trial-record", "trial-kit"))
def test_trial_contract_is_registered_and_current(name: str) -> None:
    contract = SCHEMA_CONTRACTS[name]
    assert contract.matches(ROOT / contract.committed_path), f"{name} schema is stale"


def test_trial_record_validates_against_the_published_schema() -> None:
    record = TrialRecord.model_validate(_record())
    schema = Draft202012Validator(
        json.loads((ROOT / SCHEMA_CONTRACTS["trial-record"].committed_path).read_text("utf-8"))
    )

    schema.validate(record.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_a_complete_record_is_valid_and_measureable() -> None:
    record = TrialRecord.model_validate(_record())

    assert record.verdict == "core-journey-completed"
    assert record.is_measureable() is True
    assert record.task in TRIAL_TASKS


def test_a_record_without_evidence_is_refused() -> None:
    """An unreviewable record cannot be aggregated later, so it is refused now."""

    with pytest.raises(ValueError, match="evidenceAttached"):
        TrialRecord.model_validate(_record(evidenceAttached=[]))


def test_an_implementer_may_not_author_the_measurement() -> None:
    """The measurement is the participant's account, not the implementer's."""

    with pytest.raises(ValueError, match="implementer-recorded"):
        TrialRecord.model_validate(
            _record(recordedBy="implementer", interventions=["told them the command"])
        )
    # The same author with no authored measurement is still a valid record.
    assert TrialRecord.model_validate(_record(recordedBy="implementer")).is_measureable() is False


def test_an_implementer_record_is_reported_as_unmeasureable() -> None:
    record = TrialRecord.model_validate(_record(recordedBy="implementer"))

    assert record.is_measureable() is False


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("verdict", "went-well", "verdict"),
        ("modelKey", "used", "modelKey"),
        ("sourceCheckout", "present", "sourceCheckout"),
        ("elapsedSeconds", -1, "elapsedSeconds"),
        ("completed", "yes", "completed"),
        ("task", "T9", "task"),
    ),
)
def test_a_record_refuses_values_outside_the_contract(
    field: str, value: object, expected: str
) -> None:
    with pytest.raises(ValueError, match=expected):
        TrialRecord.model_validate(_record(**{field: value}))


def test_kit_aggregates_participants_tasks_and_blockers() -> None:
    kit = TrialKit(
        records=[
            TrialRecord.model_validate(_record()),
            TrialRecord.model_validate(
                _record(
                    trialId="TRIAL-01/B/2026-10-06", task="T2", participantAlias="participant-b"
                )
            ),
        ],
        blockers=[
            "TRIAL-01: one independent participant has completed T1-T5",
            "TRIAL-02: a second independent participant has completed T1-T5",
        ],
    )

    assert kit.participants() == ("participant-a", "participant-b")
    assert kit.tasks_covered() == ("T1", "T2")
    assert kit.completed_tasks() == 2
    assert kit.remote_journeys_recorded() == 0
    assert kit.unresolved_blocks() == (
        "TRIAL-01: one independent participant has completed T1-T5",
        "TRIAL-02: a second independent participant has completed T1-T5",
    )


def test_kit_reports_a_recorded_remote_journey() -> None:
    kit = TrialKit(
        records=[
            TrialRecord.model_validate(
                _record(
                    trialId="TRIAL-03/A/2026-10-06",
                    task="REMOTE",
                    completed=False,
                    verdict="blocked",
                )
            )
        ],
        blockers=[],
    )

    assert kit.remote_journeys_recorded() == 1
    assert kit.completed_tasks() == 0


def test_scaffold_writes_slots_that_do_not_validate(tmp_path: Path) -> None:
    """The scaffold is intentionally incomplete, so an unrun trial reads as unrun."""

    result = _cli("trial", "scaffold", "--root", str(tmp_path / "kit"), "--participant", "a")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert len(payload["scaffolded"]) == len(TRIAL_TASKS)
    assert len(payload["blockers"]) == 3

    for task in TRIAL_TASKS:
        slot = tmp_path / "kit" / task / "trial-record.json"
        assert slot.is_file()
        with pytest.raises(RecoveryError) as info:
            load_trial_record(slot)
        assert info.value.code == "trial-record-invalid"

    kit = load_trial_kit(tmp_path / "kit" / "trial-kit.json")
    assert kit.records == []
    assert len(kit.unresolved_blocks()) == 3


def test_scaffold_refuses_a_non_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "kit"
    root.mkdir()
    (root / "mine.txt").write_text("keep", encoding="utf-8")

    result = _cli("trial", "scaffold", "--root", str(root), "--participant", "a")

    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "trial-path-occupied"
    assert (root / "mine.txt").read_text(encoding="utf-8") == "keep"


def test_aggregate_reports_that_nothing_is_measured_yet(tmp_path: Path) -> None:
    assert (
        _cli("trial", "scaffold", "--root", str(tmp_path / "kit"), "--participant", "a").returncode
        == 1
    )

    result = _cli("trial", "aggregate", "--root", str(tmp_path / "kit"))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["records"] == 0
    assert payload["participants"] == []
    assert len(payload["unresolvedBlockers"]) == 3
    assert payload["checkpointD"] is False


def test_validate_accepts_a_filled_record_and_rejects_an_unrun_one(tmp_path: Path) -> None:
    filled = tmp_path / "filled.json"
    filled.write_text(json.dumps(_record()), encoding="utf-8")
    unrun = tmp_path / "unrun.json"
    unrun.write_text(json.dumps({"apiVersion": "researchos.dev/trial/v0alpha1"}), encoding="utf-8")

    good = _cli("trial", "validate", str(filled))
    bad = _cli("trial", "validate", str(unrun))

    assert good.returncode == 0
    assert json.loads(good.stdout)["measureable"] is True
    assert bad.returncode == 2
    assert json.loads(bad.stderr)["code"] == "trial-record-invalid"


def test_load_trial_kit_rejects_an_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(RecoveryError) as info:
        load_trial_kit(tmp_path / "absent.json")
    assert info.value.code == "trial-kit-unreadable"


def test_load_trial_kit_rejects_a_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "kit.json"
    path.write_text('{"records": "not a list"}', encoding="utf-8")

    with pytest.raises(RecoveryError) as info:
        load_trial_kit(path)
    assert info.value.code == "trial-kit-invalid"


def test_the_kit_is_prepared_and_no_trial_is_recorded() -> None:
    """Checkpoint D is blocked on people, and this asserts the absence explicitly."""

    kit = TrialKit(records=[], blockers=["TRIAL-01: pending"])
    described = kit.describe()

    assert described["records"] == []
    assert described["blockers"] == ["TRIAL-01: pending"]
    assert kit.participants() == ()
