"""Native-process preflight review, restricted run, and SSH onboarding."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.blocks.io import ManifestLoadError
from llm_research_os.blocks.registry import RegistryError, build_registry
from llm_research_os.cli.output import dumps_json, print_error, safe_text
from llm_research_os.execution import (
    NativeProcessDisposition,
    NativeProcessPreflightError,
    NativeProcessPreflightReport,
    NativeProcessRuntimeError,
    NativeSshError,
    PlanningInputError,
    TrustedKernel,
    execute_native_process,
    load_native_process_preflight_request,
    load_plan_authorization_request,
    native_runtime_receipt,
    parse_ssh_target,
    preflight_native_process,
    write_native_ssh_pack,
)
from llm_research_os.execution.errors import (
    NativeReviewedExecutionError,
    NativeReviewedPreparationError,
)
from llm_research_os.execution.native_reviewed import parse_native_reviewed_request
from llm_research_os.execution.native_reviewed_checkpoint import (
    NativeRestoreClaim,
    NativeRestoreError,
)
from llm_research_os.execution.native_reviewed_documents import (
    MAX_REVIEWED_REQUEST_BYTES,
    NativeReviewedExecutionRequest,
)
from llm_research_os.execution.native_reviewed_preparation import (
    diagnose_reviewed_environment,
    load_bounded_file,
    prepare_reviewed_environment,
)
from llm_research_os.execution.native_reviewed_recovery import reconcile_reviewed_native
from llm_research_os.execution.native_reviewed_runtime import (
    NativeLaunchError,
    execute_reviewed_native,
)
from llm_research_os.execution.native_ssh_live import probe_ssh_pack
from llm_research_os.runs.cancellation import (
    load_run_cancellation_request,
    request_cancellation,
)
from llm_research_os.spec.io import SpecLoadError, load_document
from llm_research_os.spec.models import ResearchSpec
from llm_research_os.storage import EventStore, EventStoreError
from llm_research_os.workers.errors import WorkerError
from llm_research_os.workers.plane import WorkerPlane


def run_native(args: argparse.Namespace) -> int:
    if args.native_command == "preflight":
        return _native_preflight(
            args.spec,
            args.authorization_request,
            args.preflight_request,
            args.workflow,
            args.registry,
            args.format,
        )
    if args.native_command == "run":
        return _native_run(
            args.spec,
            args.authorization_request,
            args.preflight_request,
            args.database,
            args.workflow,
            args.registry,
            args.authorization_event_id,
            args.authorization_sequence,
            args.transport,
            args.profile,
            args.format,
        )
    if args.native_command == "prepare":
        return _native_prepare(args)
    if args.native_command == "doctor":
        return _native_doctor(args)
    if args.native_command == "execute-reviewed":
        return _native_execute_reviewed(args)
    if args.native_command == "reconcile-reviewed":
        return _native_reconcile_reviewed(args)
    if args.native_command == "ssh-onboard":
        return _native_ssh_onboard(
            args.output,
            args.host,
            args.user,
            args.port,
            args.workdir,
            args.host_key,
            args.profile,
            args.project,
            args.source,
            args.format,
        )
    if args.native_command == "ssh-doctor":
        try:
            result = probe_ssh_pack(
                args.pack,
                identity_file=args.identity_file,
                operation=args.operation,
                wheel_dir=args.wheel_dir,
                worker_credential=args.worker_credential,
                ca_path=args.ca,
                port=args.port,
                tunnel_port=args.tunnel_port,
            )
        except (NativeSshError, OSError, ValueError) as exc:
            print_error(exc, args.format)
            return 2
        if args.format == "json":
            print(dumps_json(result))
        else:
            print(f"SSH {safe_text(args.operation)}: {safe_text(str(result['outcome']))}")
            if result["outcome"] == "blocked":
                print(f"repair: {safe_text(str(result.get('repair', 'inspect remote host')))}")
        return 0 if result["outcome"] == "ready" else 1
    raise AssertionError(f"unhandled native command: {args.native_command}")


def _native_preflight(
    spec_path: Path,
    authorization_request_path: Path,
    preflight_request_path: Path,
    workflow_id: str | None,
    registry_paths: list[Path],
    output_format: str,
) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(spec_path, reject_symlinks=True))
        authorization_request = load_plan_authorization_request(authorization_request_path)
        preflight_request = load_native_process_preflight_request(preflight_request_path)
        registry = build_registry(registry_paths)
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
        result = preflight_native_process(
            dry_run,
            registry,
            authorization_request.policy(),
            preflight_request.policy(),
        )
        report = NativeProcessPreflightReport.from_result(result)
    except (
        ManifestLoadError,
        NativeProcessPreflightError,
        OSError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_native_process_preflight(report, output_format)
    return 0


def _native_run(
    spec_path: Path,
    authorization_request_path: Path,
    preflight_request_path: Path,
    database: Path,
    workflow_id: str | None,
    registry_paths: list[Path],
    authorization_event_id: str,
    authorization_sequence: str,
    transport: str,
    profile: str,
    output_format: str,
) -> int:
    try:
        spec = ResearchSpec.model_validate(load_document(spec_path, reject_symlinks=True))
        authorization_request = load_plan_authorization_request(authorization_request_path)
        preflight_request = load_native_process_preflight_request(preflight_request_path)
        registry = build_registry(registry_paths)
        dry_run = TrustedKernel(registry).dry_run(spec, workflow_id=workflow_id)
        with EventStore(database, require_existing=True) as store:
            result = execute_native_process(
                store,
                dry_run,
                registry,
                authorization_request.policy(),
                preflight_request.policy(),
                authorization_event_id=authorization_event_id,
                authorization_sequence=authorization_sequence,
                project_id=str(spec.metadata.id),
                transport=transport,
                profile=profile,
            )
    except (
        EventStoreError,
        ManifestLoadError,
        NativeProcessPreflightError,
        NativeProcessRuntimeError,
        OSError,
        PlanningInputError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        ValueError,
    ) as exc:
        print_error(exc, output_format)
        return 2
    _print_native_run(native_runtime_receipt(result), result.diagnostics, output_format)
    return 0 if result.disposition is NativeProcessDisposition.SUCCEEDED else 1


def _native_ssh_onboard(
    output: Path,
    host: str,
    user: str,
    port: int,
    workdir: str,
    host_key: str,
    profile: str,
    project: str,
    source: str,
    output_format: str,
) -> int:
    try:
        target = parse_ssh_target(
            host=host,
            port=port,
            user=user,
            workdir=workdir,
            host_key=host_key,
            profile=profile,
        )
        status = write_native_ssh_pack(output, target, project_id=project, source=source)
    except (NativeSshError, OSError, ValueError) as exc:
        print_error(exc, output_format)
        return 2
    if output_format == "json":
        print(dumps_json(status))
        return 0
    print("ssh onboarding pack: pending-live")
    print(f"host: {safe_text(target.host)}")
    print(f"user: {safe_text(target.user)}")
    print(f"port: {target.port}")
    print(f"workdir: {safe_text(target.workdir)}")
    print(f"profile: {safe_text(target.profile)}")
    print("transport: ssh-pending")
    print("live status: pending-live")
    print("ssh execution: not-implemented")
    return 0


def _print_native_process_preflight(
    report: NativeProcessPreflightReport,
    output_format: str,
) -> None:
    if output_format == "json":
        payload = report.model_dump(mode="json", by_alias=True)
        print(dumps_json(payload))
        return
    print(f"native process preflight: {report.status}")
    print(f"preflight digest: {report.preflight_digest}")
    print(f"task path: /{'/'.join(report.task.task_path)}")
    print(f"entrypoint digest: {report.task.entrypoint_digest}")
    print("launch allowed: false")
    print("authorization authentication: not-authenticated")
    print("authorization persistence: not-persisted")
    print("process isolation enforced: false")
    print("execution performed: false")
    print(
        "side effects: 0 blocks, 0 entrypoint imports, 0 processes, 0 signals, "
        "0 network requests, 0 writes, 0 paid actions"
    )


def _print_native_run(
    receipt: dict[str, object],
    diagnostics: str | None,
    output_format: str,
) -> None:
    if output_format == "json":
        print(dumps_json(receipt))
        return
    print(f"native process run: {safe_text(receipt['disposition'])}")
    print(f"preflight digest: {safe_text(receipt['preflightDigest'])}")
    print(f"reason code: {safe_text(receipt['reasonCode'])}")
    print(f"transport: {safe_text(receipt['transport'])}")
    print(f"profile: {safe_text(receipt['profile'])}")
    print("entrypoint executed: false")
    print(f"isolation: {safe_text(receipt['isolation'])}")
    print(f"network enforcement: {safe_text(receipt['networkEnforcement'])}")
    print(f"observation: {safe_text(receipt['observation'])}")
    if diagnostics:
        print(f"diagnostics: {safe_text(diagnostics[:200])}")
    print("authorization: consumed local citation before spawn")
    print("paid cloud: not run")


def _native_prepare(args: argparse.Namespace) -> int:
    try:
        loaded = _load_preparation(args)
        receipt = prepare_reviewed_environment(
            request=loaded.request,
            store=loaded.store,
            artifacts=loaded.artifacts,
            workspace=loaded.workspace,
            grant_token=loaded.grant_token,
            hmac_key=loaded.hmac_key,
        )
    except (
        NativeReviewedPreparationError,
        NativeReviewedExecutionError,
        ValidationError,
        EventStoreError,
        OSError,
    ) as exc:
        print_error(exc, args.format)
        return 1
    payload = receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    if args.format == "json":
        print(dumps_json(payload))
        return 0
    print(f"outcome: {safe_text(payload['outcome'])}")
    print("launchAllowed: false")
    print(f"reasonCode: {safe_text(payload['reasonCode'])}")
    print("user code started: false")
    return 0


def _native_doctor(args: argparse.Namespace) -> int:
    try:
        loaded = _load_preparation(args)
        diagnosis = diagnose_reviewed_environment(
            request=loaded.request,
            store=loaded.store,
            artifacts=loaded.artifacts,
            workspace=loaded.workspace,
            grant_token=loaded.grant_token,
            hmac_key=loaded.hmac_key,
        )
    except (
        NativeReviewedPreparationError,
        NativeReviewedExecutionError,
        ValidationError,
        EventStoreError,
        OSError,
    ) as exc:
        print_error(exc, args.format)
        return 1
    payload = diagnosis.model_dump(mode="json", by_alias=True, exclude_none=True)
    if args.format == "json":
        print(dumps_json(payload))
    else:
        print(f"outcome: {safe_text(payload['outcome'])}")
        print("launchAllowed: false")
        print(f"reasonCode: {safe_text(payload['reasonCode'])}")
        print("user code started: false")
    return 0 if diagnosis.outcome == "ready" else 1


def _native_execute_reviewed(args: argparse.Namespace) -> int:
    try:
        loaded = _load_preparation(args)
        loaded.store.close()
        spec = ResearchSpec.model_validate(load_document(args.spec, reject_symlinks=True))
        registry = build_registry(args.registry)
        restore_claim = (
            NativeRestoreClaim.model_validate(
                load_document(args.restore_claim, reject_symlinks=True)
            )
            if args.restore_claim is not None
            else None
        )
        source_request = (
            parse_native_reviewed_request(
                load_bounded_file(args.source_request, limit=MAX_REVIEWED_REQUEST_BYTES)
            )
            if args.source_request is not None
            else None
        )
        with EventStore(args.database, require_existing=True) as store:
            result = execute_reviewed_native(
                request=loaded.request,
                spec=spec,
                registry=registry,
                plane=WorkerPlane(
                    store=store,
                    artifacts=loaded.artifacts,
                    hmac_key=loaded.hmac_key,
                    project_id=loaded.request.project_id,
                    source=f"https://researchos.dev/projects/{loaded.request.project_id}",
                    experiment_revision=int(loaded.request.revision_id),
                ),
                workspace=loaded.workspace,
                state_dir=args.state_dir,
                grant_token=loaded.grant_token,
                restore_claim=restore_claim,
                source_request=source_request,
            )
    except (
        NativeLaunchError,
        NativeRestoreError,
        NativeReviewedPreparationError,
        NativeReviewedExecutionError,
        WorkerError,
        ManifestLoadError,
        RegistryError,
        SpecLoadError,
        ValidationError,
        EventStoreError,
        OSError,
        ValueError,
    ) as exc:
        print_error(exc, args.format)
        return 1
    payload = {
        "leaseId": result.lease_id,
        "artifactDigest": result.artifact_digest,
        "resultDigest": result.result_digest,
        "output": result.output,
    }
    if args.format == "json":
        print(dumps_json(payload))
    else:
        print(f"native reviewed task completed: {safe_text(result.lease_id)}")
        print(f"artifact digest: {safe_text(result.artifact_digest)}")
    return 0


def _native_reconcile_reviewed(args: argparse.Namespace) -> int:
    try:
        loaded = _load_preparation(args)
        loaded.store.close()
        with EventStore(args.database, require_existing=True) as store:
            if args.cancel_request is not None:
                cancel = load_run_cancellation_request(args.cancel_request)
                if (
                    cancel.project_id != loaded.request.project_id
                    or cancel.run_id != loaded.request.run_id
                ):
                    raise NativeLaunchError("cancellation request targets another Run")
                target_attempt = getattr(cancel.target, "attempt_id", loaded.request.attempt_id)
                if target_attempt != loaded.request.attempt_id:
                    raise NativeLaunchError("cancellation request targets another Attempt")
                request_cancellation(store, cancel)
            plane = WorkerPlane(
                store=store,
                artifacts=loaded.artifacts,
                hmac_key=loaded.hmac_key,
                project_id=loaded.request.project_id,
                source=f"https://researchos.dev/projects/{loaded.request.project_id}",
                experiment_revision=int(loaded.request.revision_id),
            )
            result = reconcile_reviewed_native(
                request=loaded.request,
                plane=plane,
                state_dir=args.state_dir,
                grant_token=loaded.grant_token,
            )
    except (
        NativeLaunchError,
        NativeReviewedPreparationError,
        WorkerError,
        EventStoreError,
        ValidationError,
        OSError,
        ValueError,
    ) as exc:
        print_error(exc, args.format)
        return 1
    payload = {"disposition": result.disposition, "leaseId": result.lease_id}
    if args.format == "json":
        print(dumps_json(payload))
    else:
        print(f"reviewed Attempt: {safe_text(result.disposition)}")
    return 0 if result.disposition in {"completed", "cancelled", "failed"} else 1


@dataclass(frozen=True, slots=True)
class _LoadedPreparation:
    request: NativeReviewedExecutionRequest
    store: EventStore
    artifacts: LocalArtifactStore
    workspace: Path
    grant_token: str
    hmac_key: bytes


def _load_preparation(args: argparse.Namespace) -> _LoadedPreparation:
    request_bytes = load_bounded_file(args.request, limit=MAX_REVIEWED_REQUEST_BYTES)
    try:
        token = load_bounded_file(args.grant_token_file, limit=4096).decode("ascii")
    except UnicodeDecodeError:
        raise NativeReviewedPreparationError(
            "grant token was refused",
            code="grant-hmac-invalid",
        ) from None
    if token.endswith("\n"):
        token = token[:-1]
    if token.endswith("\r"):
        token = token[:-1]
    key = load_bounded_file(args.hmac_key_file, limit=32)
    if len(key) != 32:
        raise NativeReviewedPreparationError("grant token was refused", code="grant-hmac-invalid")
    return _LoadedPreparation(
        request=parse_native_reviewed_request(request_bytes),
        store=EventStore(args.database, create=False),
        artifacts=LocalArtifactStore(args.artifacts),
        workspace=args.workspace,
        grant_token=token,
        hmac_key=key,
    )
