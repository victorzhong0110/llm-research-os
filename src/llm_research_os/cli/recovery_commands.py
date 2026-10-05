"""CLI façade for installation, doctor, backup, and restore commands."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.application.errors import ApplicationError
from llm_research_os.application.workspace import load_workspace
from llm_research_os.cli.output import dumps_json
from llm_research_os.m1 import M1CheckpointError
from llm_research_os.recovery.backup import create_backup, restore_backup, verify_backup
from llm_research_os.recovery.demo import run_demo
from llm_research_os.recovery.doctor import diagnose, plan_migration
from llm_research_os.recovery.errors import BackupIntegrityError, RecoveryError
from llm_research_os.storage.errors import EventStoreError


def add_recovery_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workspace = subparsers.add_parser(
        "workspace",
        help="initialize, diagnose, and plan migrations for a workspace",
    )
    workspace_commands = workspace.add_subparsers(dest="workspace_command", required=True)

    doctor = workspace_commands.add_parser("doctor", help="redacted workspace diagnostics")
    doctor.add_argument("--root", type=Path, required=True, help="workspace root")
    doctor.add_argument(
        "--deep",
        action="store_true",
        help="re-verify every referenced object instead of checking presence",
    )

    migrate = workspace_commands.add_parser("migrate", help="report supported schema migrations")
    migrate.add_argument("--root", type=Path, required=True, help="workspace root")

    demo = workspace_commands.add_parser(
        "demo",
        help="create and populate one offline workspace from the packaged corpus",
    )
    demo.add_argument("--root", type=Path, required=True, help="empty demonstration root")

    backup = subparsers.add_parser("backup", help="create, verify, and restore backups")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)

    create = backup_commands.add_parser("create", help="write a verified prefix backup")
    create.add_argument("--root", type=Path, required=True, help="workspace root to back up")
    create.add_argument(
        "--out", type=Path, required=True, help="new image directory (this command's output)"
    )

    verify = backup_commands.add_parser("verify", help="re-verify a backup image")
    verify.add_argument("--image", type=Path, required=True, help="backup image directory")

    restore = backup_commands.add_parser("restore", help="restore a verified image")
    restore.add_argument("--image", type=Path, required=True, help="backup image directory")
    # `--root` on create names the source and on restore it names the
    # destination, so a user moving from one subcommand to the other guessed
    # wrong. `--out` means "what this command produces" on both, and is accepted
    # here as the clearer name; `--root` stays so existing scripts keep working.
    restore.add_argument("--root", type=Path, default=None, help="new workspace root")
    restore.add_argument(
        "--out",
        type=Path,
        default=None,
        dest="out",
        help="new workspace root (this command's output); same as --root",
    )
    restore.add_argument(
        "--project",
        help=(
            "restore under a different project id; refused when the image contains no "
            "event for that project"
        ),
    )


def run_workspace(args: argparse.Namespace) -> int:
    try:
        if args.workspace_command == "doctor":
            report = diagnose(args.root, now=datetime.now(UTC), deep=args.deep)
            print(dumps_json(report.describe()))
            return 0 if report.healthy else 1
        if args.workspace_command == "migrate":
            print(dumps_json(plan_migration(args.root)))
            return 0
        if args.workspace_command == "demo":
            result = run_demo(args.root, now=datetime.now(UTC))
            print(
                dumps_json(
                    {
                        "projectId": result.project_id,
                        "highWater": result.high_water,
                        "eventTypes": list(result.event_types),
                        "runId": result.run_id,
                        "queued": result.queued,
                        "healthy": result.healthy,
                        "next": [
                            result.evidence_import_command,
                            result.backup_command,
                            result.serve_command,
                        ],
                    }
                )
            )
            return 0 if result.healthy else 1
    except RecoveryError as exc:
        print(dumps_json({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    except (ApplicationError, EventStoreError, M1CheckpointError, OSError, ValueError):
        print(
            dumps_json({"code": "workspace-invalid", "message": "the workspace could not be read"}),
            file=sys.stderr,
        )
        return 2
    raise AssertionError(f"unhandled workspace command: {args.workspace_command}")


def run_backup(args: argparse.Namespace) -> int:
    try:
        if args.backup_command == "create":
            workspace = load_workspace(args.root)
            created = create_backup(workspace, args.out, now=datetime.now(UTC))
            print(dumps_json(created.model_dump(mode="json", by_alias=True, exclude_none=True)))
            return 0
        if args.backup_command == "verify":
            verified = verify_backup(args.image)
            print(dumps_json(verified.model_dump(mode="json", by_alias=True, exclude_none=True)))
            return 0
        if args.backup_command == "restore":
            # A RecoveryError, not SystemExit: every other failure in this
            # command renders as a closed code and a message on stderr with exit
            # 2, and an argument mistake is no different. A bare SystemExit would
            # print a sentence and exit 1, which no caller can branch on.
            destination = args.root or args.out
            if args.root is not None and args.out is not None and args.root != args.out:
                raise RecoveryError(
                    "backup-restore-ambiguous",
                    "--root and --out name different directories; pass one of them",
                )
            if destination is None:
                raise RecoveryError(
                    "backup-restore-destination-missing",
                    "a destination directory is required; pass --out or --root",
                )
            restored = restore_backup(args.image, destination, project_id=args.project)
            print(dumps_json(restored.model_dump(mode="json", by_alias=True, exclude_none=True)))
            return 0
    except (BackupIntegrityError, RecoveryError) as exc:
        print(dumps_json({"code": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2
    except (ApplicationError, EventStoreError, OSError, ValidationError, ValueError):
        print(
            dumps_json({"code": "backup-failed", "message": "the backup operation failed"}),
            file=sys.stderr,
        )
        return 2
    raise AssertionError(f"unhandled backup command: {args.backup_command}")
