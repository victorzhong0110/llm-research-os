"""CLI façade for the R16 independent-trial kit.

The kit is prepared; the trials are not performed. These commands make the
absence checkable rather than implied: ``scaffold`` writes the exact record
slots a trial must fill, and ``validate`` refuses a record that is incomplete or
that an implementer authored on a participant's behalf.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.cli.output import dumps_json
from llm_research_os.recovery.errors import RecoveryError
from llm_research_os.recovery.trial import (
    TRIAL_TASKS,
    TrialKit,
    load_trial_kit,
    load_trial_record,
)

RECORD_NAME = "trial-record.json"
KIT_NAME = "trial-kit.json"

# The blockers that keep Checkpoint D open, named so a record can clear one and
# so the aggregate can report which remain.
TRIAL_BLOCKERS: tuple[str, ...] = (
    "TRIAL-01: one independent participant has completed T1-T5",
    "TRIAL-02: a second independent participant has completed T1-T5",
    "TRIAL-03: one authorized remote journey has been evidenced",
)


def add_trial_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    trial = subparsers.add_parser(
        "trial",
        help="independent-trial kit: scaffold and validate trial records",
    )
    commands = trial.add_subparsers(dest="trial_command", required=True)

    scaffold = commands.add_parser(
        "scaffold",
        help="write the empty record and kit slots a trial programme needs",
    )
    scaffold.add_argument("--root", type=Path, required=True, help="empty kit directory")
    scaffold.add_argument(
        "--participant",
        required=True,
        help="participant alias; must not be the implementer's own name",
    )
    scaffold.add_argument(
        "--recorded-by",
        choices=("participant", "observer", "implementer"),
        default="observer",
        help="who authored the record; an implementer may not author the measurement",
    )

    validate = commands.add_parser("validate", help="validate one filled trial record")
    validate.add_argument("record", type=Path, help="filled trial record JSON")

    aggregate = commands.add_parser(
        "aggregate",
        help="validate a record set and report what the phase still lacks",
    )
    aggregate.add_argument("--root", type=Path, required=True, help="kit directory")


def run_trial(args: argparse.Namespace) -> int:
    try:
        if args.trial_command == "scaffold":
            return _scaffold(args)
        if args.trial_command == "validate":
            return _validate(args)
        if args.trial_command == "aggregate":
            return _aggregate(args)
    except RecoveryError as exc:
        print(dumps_json({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValidationError, ValueError):
        print(
            dumps_json(
                {"code": "trial-invalid", "message": "the trial kit could not be processed"}
            ),
            file=sys.stderr,
        )
        return 2
    raise AssertionError(f"unhandled trial command: {args.trial_command}")


def _scaffold(args: argparse.Namespace) -> int:
    """Write empty, already-invalid record slots so a trial cannot skip a field."""

    root = args.root.absolute()
    if root.exists() and any(root.iterdir()):
        raise RecoveryError("trial-path-occupied", "the trial kit directory is not empty")
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for task in TRIAL_TASKS:
        record = root / task
        record.mkdir()
        path = record / RECORD_NAME
        # The scaffold is deliberately incomplete: `validate` rejects it until a
        # participant's outcome is actually recorded, so an unrun trial can
        # never look like a clean one. participantConfirmed is written explicitly
        # and false, so "not yet confirmed by the person" is a recorded state
        # rather than an absent field someone could read as an oversight.
        path.write_text(
            json.dumps(
                {
                    "apiVersion": "researchos.dev/trial/v0alpha1",
                    "task": task,
                    "participantAlias": args.participant,
                    "recordedBy": args.recorded_by,
                    "participantConfirmed": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written.append(str(path.relative_to(root)))
    kit = TrialKit(records=[], blockers=list(TRIAL_BLOCKERS))
    kit_path = root / KIT_NAME
    kit_path.write_text(
        json.dumps(kit.describe(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        dumps_json(
            {
                "root": str(root),
                "scaffolded": written,
                "kit": str(kit_path.relative_to(root)),
                "blockers": list(TRIAL_BLOCKERS),
                "valid": False,
            }
        )
    )
    return 1


def _validate(args: argparse.Namespace) -> int:
    record = load_trial_record(args.record)
    print(
        dumps_json(
            {
                "trialId": record.trial_id,
                "task": record.task,
                "participantAlias": record.participant_alias,
                "verdict": record.verdict,
                "measureable": record.is_measureable(),
                "confirmed": record.is_confirmed(),
                "pendingConfirmation": not record.is_confirmed(),
                "valid": True,
            }
        )
    )
    return 0


def _aggregate(args: argparse.Namespace) -> int:
    kit = load_trial_kit(args.root / KIT_NAME)
    # Checkpoint D counts people who took part, not records that exist. A record
    # an observer filed stays pending until the participant themself confirms
    # it, so both the count and the remote-journey tally are confirmed-only.
    participants = kit.confirmed_participants()
    # Always evaluate the fixed requirements, even if a caller omits blockers.
    requirements = TrialKit(records=kit.records, blockers=list(TRIAL_BLOCKERS))
    missing = list(dict.fromkeys((*requirements.unresolved_blocks(), *kit.unresolved_blocks())))
    coverage_complete = not missing
    # Participant independence, remote authorization, attached evidence, defect
    # resolution and preceding-package acceptance require reviewer verification.
    # A roll-up of self-reported records never accepts the phase.
    checkpoint_d = False
    print(
        dumps_json(
            {
                "records": len(kit.records),
                "participants": list(participants),
                "observedParticipants": list(kit.participants()),
                "pendingConfirmation": list(kit.pending_confirmation()),
                "tasksCovered": list(kit.tasks_covered()),
                "completedTasks": kit.completed_tasks(),
                "remoteJourneys": kit.remote_journeys_recorded(),
                "unresolvedBlockers": missing,
                "trialTaskCoverageComplete": coverage_complete,
                "completedCoreParticipants": list(kit.completed_core_participants()),
                "completedRemoteJourneys": kit.completed_remote_journeys(),
                "checkpointD": checkpoint_d,
                "acceptance": "requires-maintainer-review",
                "valid": True,
            }
        )
    )
    return 0
