"""Worker registration and HMAC grant commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.spec.io import SpecLoadError, load_spec
from llm_research_os.storage import EventStore, EventStoreError
from llm_research_os.storage.models import StoredEvent
from llm_research_os.workers.binding import require_authorized_execution_binding
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.errors import WorkerError, WorkerRequestError
from llm_research_os.workers.requests import (
    load_authorization_grant_request,
    load_worker_register_request,
)

_INPUT_ERRORS = (
    EventStoreError,
    ManifestLoadError,
    OSError,
    RegistryError,
    SpecLoadError,
    ValidationError,
    ValueError,
)


def run_grants(args: argparse.Namespace) -> int:
    if args.grants_command == "record":
        return _record_grant(
            args.spec,
            args.request,
            args.database,
            args.format,
            args.registry,
            args.workflow,
        )
    raise AssertionError(f"unhandled grants command: {args.grants_command}")


def run_workers(args: argparse.Namespace) -> int:
    if args.workers_command == "register":
        return _register_worker(args.request, args.database, args.format)
    if args.workers_command == "serve":
        return _serve_worker_plane(
            args.database,
            args.artifacts,
            args.state,
            args.project,
            args.source,
            args.revision,
            args.host,
            args.port,
        )
    if args.workers_command == "run":
        return _run_isolated_worker(
            args.credential,
            args.artifacts,
            gpu_data_dir=args.gpu_data_dir,
            gpu_model_dir=args.gpu_model_dir,
            gpu_output_dir=args.gpu_output_dir,
        )
    if args.workers_command == "pack":
        return _pack_remote_worker(args.output, args.url, args.project, args.source, args.state)
    raise AssertionError(f"unhandled workers command: {args.workers_command}")


def _record_grant(
    spec_path: Path,
    request_path: Path,
    database: Path,
    output_format: str,
    registry_paths: list[Path],
    workflow_id: str | None,
) -> int:
    try:
        request = load_authorization_grant_request(request_path)
        spec = load_spec(spec_path)
        registry = build_registry(registry_paths)
        with EventStore(database, require_existing=True) as store:
            require_authorized_execution_binding(
                store,
                spec,
                registry,
                project_id=request.project_id,
                experiment_revision=request.experiment_revision,
                planned_task_id=request.task_id,
                event_id=request.authorization_event_id,
                sequence=request.authorization_sequence,
                image_digest=request.image_digest,
                config_digest=request.config_digest,
                workflow_id=workflow_id,
            )
            stored = WorkerControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except WorkerRequestError as exc:
        print_error(exc, output_format)
        return 2
    except WorkerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(stored, output_format)
    return 0


def _register_worker(request_path: Path, database: Path, output_format: str) -> int:
    try:
        request = load_worker_register_request(request_path)
        with EventStore(database, require_existing=True) as store:
            stored = WorkerControl(store, project_id=request.project_id).append(
                request.event_draft()
            )
    except WorkerRequestError as exc:
        print_error(exc, output_format)
        return 2
    except WorkerError as exc:
        print_error(exc, output_format)
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, output_format)
        return 2
    _print_receipt(stored, output_format)
    return 0


def _serve_worker_plane(
    database: Path,
    artifacts: Path,
    state: Path,
    project_id: str,
    source: str,
    revision: int,
    host: str,
    port: int,
) -> int:
    from llm_research_os.workers.serve import serve_isolated_control_plane

    try:
        serve_isolated_control_plane(
            database=database,
            artifacts_root=artifacts,
            state_dir=state,
            project_id=project_id,
            source=source,
            experiment_revision=revision,
            host=host,
            port=port,
        )
    except WorkerError as exc:
        print_error(exc, "json")
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, "json")
        return 2
    return 0


def _run_isolated_worker(
    credential_path: Path,
    artifacts: Path,
    *,
    gpu_data_dir: Path | None,
    gpu_model_dir: Path | None,
    gpu_output_dir: Path | None,
) -> int:
    from llm_research_os.workers.credentials import load_worker_credential, redact_worker_log
    from llm_research_os.workers.isolated import run_isolated_worker

    secrets: tuple[str, ...] = ()
    try:
        secrets = load_worker_credential(credential_path).secrets()
        completed = run_isolated_worker(
            credential_path=credential_path,
            artifacts_root=artifacts,
            gpu_data_dir=gpu_data_dir,
            gpu_model_dir=gpu_model_dir,
            gpu_output_dir=gpu_output_dir,
        )
    except WorkerError as exc:
        print_error(
            WorkerError(redact_worker_log(str(exc), *secrets), code=exc.code),
            "text",
        )
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, "text")
        return 2
    print(
        dumps_json(
            {
                "eventId": completed["eventId"],
                "type": completed["type"],
                "sequence": completed["sequence"],
            }
        )
    )
    return 0


def _pack_remote_worker(
    output: Path,
    url: str,
    project_id: str,
    source: str,
    state: Path | None,
) -> int:
    from llm_research_os.workers.remote_pack import write_remote_worker_pack

    try:
        status = write_remote_worker_pack(
            output,
            control_plane_url=url,
            project_id=project_id,
            source=source,
            state_dir=state,
        )
    except WorkerError as exc:
        print_error(exc, "json")
        return 1
    except _INPUT_ERRORS as exc:
        print_error(exc, "json")
        return 2
    print(dumps_json(status))
    return 0


def _print_receipt(stored: StoredEvent, output_format: str) -> int | None:
    if output_format == "json":
        print(
            dumps_json(
                {
                    "eventId": stored.event.id,
                    "type": stored.event.type,
                    "sequence": stored.sequence,
                    "projectId": stored.event.data.project_id,
                }
            )
        )
        return None
    print(f"event: {safe_text(stored.event.id)}")
    print(f"type: {safe_text(stored.event.type)}")
    print(f"sequence: {stored.sequence}")
    print(f"project: {safe_text(stored.event.data.project_id)}")
    return None
