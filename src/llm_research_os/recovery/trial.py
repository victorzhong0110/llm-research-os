"""The R16 independent-trial record, as a validated document rather than prose.

R16 is the only package whose evidence is produced by people. A record kept as
free text cannot be checked, cannot be aggregated, and — most importantly —
cannot be distinguished from a record someone filled in on the implementer's
behalf. Making it a closed contract means an empty field is a validation error
and a filled field is a checkable claim.

Two fields are the measurement and cannot be defaulted:
``interventions`` and ``confusionObserved``. An implementer must not write them
for a participant, so a record that omits them fails validation rather than
silently looking like a clean trial.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from llm_research_os.events.models import Rfc3339Timestamp
from llm_research_os.recovery.backup import _regular_reader
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.recovery.models import _RecoveryModel

_MAX_RECORD_BYTES = 1 << 20
_MAX_KIT_BYTES = 32 << 20

TRIAL_API_VERSION = "researchos.dev/trial/v0alpha1"
TRIAL_RECORD_SCHEMA_ID = "https://researchos.dev/schemas/trial-record/v0alpha1.schema.json"

#: The fixed task identifiers a record may name. A trial that reports an
#: unlisted task is not part of the agreed kit and cannot be aggregated with
#: the rest of R16's evidence.
TRIAL_TASKS: tuple[str, ...] = ("T1", "T2", "T3", "T4", "T5", "REMOTE")

#: How a trial ended, from the participant's side rather than the system's.
Verdict = Literal["core-journey-completed", "blocked", "abandoned"]

#: What the trial kit refuses to accept. A record claiming a key was present
#: while also needing one is a contradiction, not a finding.
KeyAvailability = Literal["absent", "present-but-unused"]


class TrialRecord(_RecoveryModel):
    """One participant's result on one fixed task."""

    api_version: str = Field(default=TRIAL_API_VERSION, alias="apiVersion")
    kind: Literal["TrialRecord"] = "TrialRecord"
    trial_id: str = Field(alias="trialId", min_length=3, max_length=128)
    task: Literal["T1", "T2", "T3", "T4", "T5", "REMOTE"]
    participant_alias: str = Field(alias="participantAlias", min_length=1, max_length=64)
    recorded_at: Rfc3339Timestamp = Field(alias="recordedAt")
    recorded_by: Literal["participant", "observer", "implementer"] = Field(
        default="observer", alias="recordedBy"
    )
    #: Whether the participant themself confirmed this account. An observer may
    #: write a faithful record of what a participant did, but the account is
    #: still pending until the participant says it is theirs. Only a confirmed
    #: record moves Checkpoint D.
    participant_confirmed: bool = Field(default=False, alias="participantConfirmed")
    confirmed_at: Rfc3339Timestamp | None = Field(default=None, alias="confirmedAt")

    build_under_test: str = Field(alias="buildUnderTest", min_length=1, max_length=256)
    platform: str = Field(min_length=1, max_length=256)
    python_version: str = Field(alias="pythonVersion", min_length=1, max_length=32)
    model_key: KeyAvailability = Field(alias="modelKey")
    gpu: KeyAvailability = "absent"
    node: KeyAvailability = "absent"
    source_checkout: KeyAvailability = Field(alias="sourceCheckout")

    task_text_given: str = Field(alias="taskTextGiven", min_length=1, max_length=4096)
    completed: bool
    exit_state: str = Field(alias="exitState", min_length=1, max_length=1024)
    elapsed_seconds: int = Field(alias="elapsedSeconds", ge=0, le=86_400)

    #: The measurement. An empty list is a valid observation ("nothing was
    #: needed"), but the field must be present and deliberately chosen.
    interventions: list[str] = Field(max_length=64)
    confusion_observed: list[str] = Field(alias="confusionObserved", max_length=64)
    recovery_observed: list[str] = Field(alias="recoveryObserved", max_length=64)

    defects_found: list[str] = Field(alias="defectsFound", max_length=64)
    evidence_attached: list[str] = Field(alias="evidenceAttached", min_length=1, max_length=64)
    verdict: Verdict

    @field_validator("task")
    @classmethod
    def _known_task(cls, value: str) -> str:
        # A record naming a task outside the agreed kit cannot be aggregated with
        # the rest of R16's evidence, so it is refused rather than noted.
        if value not in TRIAL_TASKS:
            raise ValueError(f"task must be one of {', '.join(TRIAL_TASKS)}")
        return value

    @model_validator(mode="after")
    def _evidence_is_attachable(self) -> Self:
        # An evidence list is what makes a record auditable later. A trial that
        # completed with nothing attached cannot be reviewed after the fact, and
        # an abandoned one is exactly the case worth reviewing.
        if self.completed != (self.verdict == "core-journey-completed"):
            raise ValueError("completed must agree with verdict")
        if not self.evidence_attached or any(not item.strip() for item in self.evidence_attached):
            raise ValueError("evidenceAttached must name at least one attachable report or path")
        if self.recorded_by == "implementer" and (self.interventions or self.confusion_observed):
            raise ValueError(
                "an implementer-recorded trial may not author interventions or "
                "confusionObserved; those are the participant's account"
            )
        # Confirmation is the participant's own act. An implementer cannot
        # confirm on someone's behalf, and a confirmation without a time cannot
        # be audited later, so both are refused rather than defaulted.
        if self.participant_confirmed and self.recorded_by == "implementer":
            raise ValueError(
                "participantConfirmed may only be set by the participant or an "
                "observer who has the participant's confirmation; an implementer "
                "cannot confirm on a participant's behalf"
            )
        if self.participant_confirmed and self.confirmed_at is None:
            raise ValueError("a confirmed record must carry confirmedAt")
        if self.confirmed_at is not None and not self.participant_confirmed:
            raise ValueError("confirmedAt requires participantConfirmed")
        return self

    def is_measureable(self) -> bool:
        """Report whether the record carries a participant-authored measurement."""

        return self.recorded_by != "implementer" or bool(self.interventions)

    def is_confirmed(self) -> bool:
        """Report whether the participant themself stands behind this account.

        An unconfirmed record is not evidence of a trial, however faithfully it
        was written down. This is the difference between "an observer saw
        something" and "a person confirms this happened to them".
        """

        return self.participant_confirmed and self.confirmed_at is not None


class TrialKit(_RecoveryModel):
    """The state of the R16 trial programme, aggregated from individual records."""

    api_version: str = Field(default=TRIAL_API_VERSION, alias="apiVersion")
    kind: Literal["TrialKit"] = "TrialKit"
    records: list[TrialRecord] = Field(max_length=1024)
    blockers: list[str] = Field(max_length=64)

    @model_validator(mode="after")
    def _unique_records(self) -> Self:
        identifiers = [record.trial_id for record in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("trialId must be unique within a kit")
        return self

    def participants(self) -> tuple[str, ...]:
        return tuple(sorted({record.participant_alias for record in self.records}))

    def confirmed_participants(self) -> tuple[str, ...]:
        """Participants who have themself confirmed at least one record.

        This is the set the plan's acceptance language refers to. A record an
        observer filed on someone's behalf is not that person having taken part.
        """

        return tuple(
            sorted({record.participant_alias for record in self.records if record.is_confirmed()})
        )

    def pending_confirmation(self) -> tuple[str, ...]:
        """Record ids written but not yet confirmed by the participant."""

        return tuple(
            sorted(record.trial_id for record in self.records if not record.is_confirmed())
        )

    def tasks_covered(self) -> tuple[str, ...]:
        return tuple(sorted({record.task for record in self.records}))

    def completed_tasks(self) -> int:
        return sum(
            1
            for record in self.records
            if record.verdict == "core-journey-completed" and record.is_confirmed()
        )

    def remote_journeys_recorded(self) -> int:
        return sum(
            1 for record in self.records if record.task == "REMOTE" and record.is_confirmed()
        )

    def completed_core_participants(self) -> tuple[str, ...]:
        tasks: dict[str, set[str]] = {}
        for record in self.records:
            if record.is_confirmed() and record.completed:
                tasks.setdefault(record.participant_alias, set()).add(record.task)
        return tuple(
            sorted(alias for alias, covered in tasks.items() if set(TRIAL_TASKS[:-1]) <= covered)
        )

    def completed_remote_journeys(self) -> int:
        return sum(
            1
            for record in self.records
            if record.task == "REMOTE" and record.completed and record.is_confirmed()
        )

    def unresolved_blocks(self) -> tuple[str, ...]:
        """Derive task coverage; a record name cannot clear a requirement."""

        completed = len(self.completed_core_participants())
        cleared = set()
        if completed >= 1:
            cleared.add("TRIAL-01")
        if completed >= 2:
            cleared.add("TRIAL-02")
        if self.completed_remote_journeys():
            cleared.add("TRIAL-03")
        return tuple(
            blocker for blocker in self.blockers if blocker.split(":", 1)[0] not in cleared
        )

    def describe(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


def _read_document(path: Path, limit: int) -> bytes:
    with _regular_reader(path) as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise RecoveryError("trial-document-too-large", "the trial document exceeds the read limit")
    return content


def load_trial_record(path: Path) -> TrialRecord:
    """Read and validate one trial record from disk."""

    try:
        return TrialRecord.model_validate_json(_read_document(path, _MAX_RECORD_BYTES))
    except (OSError, RecoveryError) as exc:
        raise RecoveryError(
            "trial-record-unreadable", "the trial record could not be read"
        ) from exc
    except ValueError as exc:
        raise RecoveryError(
            "trial-record-invalid", "the trial record is not a valid contract"
        ) from exc


def load_trial_kit(path: Path) -> TrialKit:
    """Read and validate an aggregated trial kit from disk."""

    try:
        return TrialKit.model_validate_json(_read_document(path, _MAX_KIT_BYTES))
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("trial-kit-unreadable", "the trial kit could not be read") from exc
    except ValueError as exc:
        raise RecoveryError("trial-kit-invalid", "the trial kit is not a valid contract") from exc


__all__ = [
    "TRIAL_API_VERSION",
    "TRIAL_RECORD_SCHEMA_ID",
    "TRIAL_TASKS",
    "KeyAvailability",
    "TrialKit",
    "TrialRecord",
    "Verdict",
    "load_trial_kit",
    "load_trial_record",
]
