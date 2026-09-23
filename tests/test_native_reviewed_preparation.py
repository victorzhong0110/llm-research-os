"""R04 preparation binds reviewed bytes and does not start user code."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_research_os.artifacts.store import LocalArtifactStore
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.cli.native_commands import run_native
from llm_research_os.cli.parser import build_parser
from llm_research_os.events.models import RESEARCH_EVENT_SCHEMA_ID
from llm_research_os.execution.authorization_events import PlanAuthorizationEvaluatedPayload
from llm_research_os.execution.errors import NativeReviewedPreparationError
from llm_research_os.execution.native_reviewed import execution_object, request_digest
from llm_research_os.execution.native_reviewed_documents import (
    NATIVE_REVIEWED_MEDIA_TYPE,
    NativeReviewedExecutionRequest,
)
from llm_research_os.execution.native_reviewed_material import (
    NativeReviewedCodeReview,
    NativeReviewedDependencyInventory,
    NativeReviewedDependencyLock,
    NativeReviewedInterpreterIdentity,
    NativeReviewedPythonBundle,
)
from llm_research_os.execution.native_reviewed_preparation import (
    check_before_user_code,
    diagnose_reviewed_environment,
    load_bounded_file,
    prepare_reviewed_environment,
)
from llm_research_os.execution.native_reviewed_preparation_documents import (
    NativeReviewedPreparationDiagnosis,
    NativeReviewedPreparationReceipt,
)
from llm_research_os.storage import EventStore
from llm_research_os.workers.control import WorkerControl
from llm_research_os.workers.drafts import (
    grant_consumed_draft,
    grant_recorded_draft,
    grant_revoked_draft,
    registered_draft,
    work_leased_draft,
    work_queued_draft,
)
from llm_research_os.workers.tokens import issue_grant_token

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "native-reviewed-preparation"
BRICK = (EXAMPLES / "brick" / "task.py").read_bytes()
SOURCE = "https://researchos.dev/projects/project.reviewed"
PROJECT = "project.reviewed"
NOW = datetime(2026, 9, 23, tzinfo=UTC)
EXPIRES = "2027-01-01T00:00:00Z"


@dataclass
class World:
    root: Path
    request: NativeReviewedExecutionRequest
    database: Path
    artifacts: Path
    workspace: Path
    token: str
    hmac_key: bytes
    code: bytes
    high_water: int

    def prepare(self, workspace: Path | None = None, **overrides: object) -> object:
        return prepare_reviewed_environment(
            request=overrides.get("request", self.request),  # type: ignore[arg-type]
            store=EventStore(self.database, create=False),
            artifacts=LocalArtifactStore(self.artifacts),
            workspace=workspace or self.workspace,
            grant_token=overrides.get("grant_token", self.token),  # type: ignore[arg-type]
            hmac_key=overrides.get("hmac_key", self.hmac_key),  # type: ignore[arg-type]
            now=overrides.get("now", NOW),  # type: ignore[arg-type]
        )

    def diagnose(self, workspace: Path | None = None, **overrides: object) -> object:
        return diagnose_reviewed_environment(
            request=overrides.get("request", self.request),  # type: ignore[arg-type]
            store=EventStore(self.database, create=False),
            artifacts=LocalArtifactStore(self.artifacts),
            workspace=workspace or self.workspace,
            grant_token=overrides.get("grant_token", self.token),  # type: ignore[arg-type]
            hmac_key=overrides.get("hmac_key", self.hmac_key),  # type: ignore[arg-type]
            now=overrides.get("now", NOW),  # type: ignore[arg-type]
        )

    def before_start(self, workspace: Path | None = None) -> object:
        return check_before_user_code(
            request=self.request,
            store=EventStore(self.database, create=False),
            artifacts=LocalArtifactStore(self.artifacts),
            workspace=workspace or self.workspace,
            grant_token=self.token,
            hmac_key=self.hmac_key,
            now=NOW,
        )


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _abi() -> str:
    return {12: "cp312", 13: "cp313", 14: "cp314"}[sys.version_info.minor]


def _decision_digest(spec: str, registry: str, plan: str, capability: str) -> str:
    return content_digest(
        {
            "status": "authorized",
            "digests": {"spec": spec, "registry": registry, "plan": plan},
            "capabilities": [{"id": capability, "decision": "granted"}],
            "permissions": [],
            "requirements": [],
        }
    )


def _authorization_event(spec: str, registry: str, plan: str, capability: str) -> dict[str, object]:
    payload = PlanAuthorizationEvaluatedPayload.model_validate(
        {
            "workflowId": "workflow.reviewed",
            "binding": {
                "specDigest": spec,
                "registryDigest": registry,
                "planDigest": plan,
                "decisionDigest": _decision_digest(spec, registry, plan, capability),
            },
            "status": "authorized",
            "authorized": True,
            "requiredCapabilities": [capability],
            "requiredPermissions": [],
            "missingCapabilities": [],
            "missingPermissions": [],
            "approvedRequirements": [],
            "pendingRequirements": [],
            "deniedRequirements": [],
            "approvalAuthentication": "not-authenticated",
            "authority": "audit-only",
            "execution": "not-executed",
        }
    )
    return {
        "specversion": "1.0",
        "id": "evt.auth.1",
        "source": SOURCE,
        "type": "plan.authorization.evaluated",
        "time": "2026-09-23T00:00:00Z",
        "subject": "authorization.project.reviewed",
        "dataschema": RESEARCH_EVENT_SCHEMA_ID,
        "datacontenttype": "application/json",
        "streamid": PROJECT,
        "data": {
            "schemaVersion": "v0alpha1",
            "actor": {"id": "researcher.local", "kind": "human"},
            "projectId": PROJECT,
            "experimentRevision": 1,
            "payload": payload.model_dump(mode="json", by_alias=True),
            "evidenceRefs": [],
        },
    }


def _request_for(
    *,
    spec: str,
    registry: str,
    plan: str,
    capability: str,
    bundle_digest: str,
    review_digest: str,
    interpreter_digest: str,
    lock_digest: str,
    inventory_digest: str,
    input_digest: str,
    input_size: int,
) -> NativeReviewedExecutionRequest:
    system = platform.system().lower()
    architecture = platform.machine()
    version = platform.python_version()
    document = {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "NativeReviewedExecutionRequest",
        "profile": "native-reviewed-python/v0alpha1",
        "platform": {"os": system, "architecture": architecture},
        "projectId": PROJECT,
        "revisionId": "1",
        "workflowId": "workflow.reviewed",
        "taskId": "task.brick",
        "runId": "run.1",
        "attemptId": "attempt.1",
        "workerId": "worker.1",
        "actorId": "researcher.local",
        "authorizationEventId": "evt.auth.1",
        "authorizationSequence": "1",
        "specDigest": spec,
        "registryDigest": registry,
        "planDigest": plan,
        "decisionDigest": _decision_digest(spec, registry, plan, capability),
        "code": {
            "bundleDigest": bundle_digest,
            "mediaType": NATIVE_REVIEWED_MEDIA_TYPE,
            "entrypoint": "brick.task:main",
            "review": {"citationDigest": review_digest, "bundleDigest": bundle_digest},
        },
        "inputs": [
            {
                "name": "corpus",
                "digest": input_digest,
                "purpose": "dataset",
                "sizeBytes": input_size,
            }
        ],
        "configDigest": "jcs-sha256:" + "0" * 64,
        "environment": {
            "interpreterDigest": interpreter_digest,
            "pythonVersion": version,
            "abi": _abi(),
            "dependencyLockDigest": lock_digest,
            "inventoryDigest": inventory_digest,
            "platform": {"os": system, "architecture": architecture},
        },
        "limits": {
            "wallTimeSeconds": 60,
            "stdoutBytes": 4096,
            "stderrBytes": 4096,
            "artifactBytes": 1048576,
            "memoryBytes": {"ceiling": 268435456, "required": False},
        },
        "restrictions": {
            "network": {"requested": "denied", "required": False},
            "filesystem": {"requested": "confined", "required": False},
            "memory": {"requested": "bounded", "required": False},
        },
    }
    draft = NativeReviewedExecutionRequest.model_validate(document)
    return draft.model_copy(update={"config_digest": content_digest(execution_object(draft))})


def _build(tmp_path: Path, *, capability: str = "execute.native") -> World:
    code_path = tmp_path / "source" / "task.py"
    code_path.parent.mkdir()
    code_path.write_bytes(BRICK)
    code = code_path.read_bytes()
    code_path.write_bytes(b"changed-after-approval\n")
    corpus = b'{"rows":1}\n'
    interpreter = canonical_json(
        {
            "abi": _abi(),
            "apiVersion": "researchos.dev/v0alpha1",
            "implementation": "cpython",
            "kind": "NativeReviewedInterpreterIdentity",
            "platform": {
                "architecture": platform.machine(),
                "os": platform.system().lower(),
            },
            "pythonVersion": platform.python_version(),
        }
    ).encode("utf-8")
    empty = canonical_json(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeReviewedDependencyLock",
            "packages": [],
        }
    ).encode("utf-8")
    inventory = canonical_json(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "kind": "NativeReviewedDependencyInventory",
            "packages": [],
        }
    ).encode("utf-8")
    bundle = canonical_json(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "entrypoint": "brick.task:main",
            "files": [{"digest": _sha(code), "path": "brick/task.py"}],
            "kind": "NativeReviewedPythonBundle",
        }
    ).encode("utf-8")
    review = canonical_json(
        {
            "apiVersion": "researchos.dev/v0alpha1",
            "bundleDigest": _sha(bundle),
            "entrypoint": "brick.task:main",
            "kind": "NativeReviewedCodeReview",
            "mediaType": NATIVE_REVIEWED_MEDIA_TYPE,
        }
    ).encode("utf-8")
    spec = content_digest({"kind": "spec"})
    registry = content_digest({"kind": "registry"})
    plan = content_digest({"kind": "plan"})
    request = _request_for(
        spec=spec,
        registry=registry,
        plan=plan,
        capability=capability,
        bundle_digest=_sha(bundle),
        review_digest=content_digest(json.loads(review)),
        interpreter_digest=_sha(interpreter),
        lock_digest=_sha(empty),
        inventory_digest=_sha(inventory),
        input_digest=_sha(corpus),
        input_size=len(corpus),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    cas = LocalArtifactStore(artifacts)
    for payload in (code, corpus, interpreter, empty, inventory, bundle, review):
        cas.put_bytes(payload)
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.append(_authorization_event(spec, registry, plan, capability))
    control = WorkerControl(store, project_id=PROJECT)
    control.append(
        registered_draft(
            project_id=PROJECT,
            worker_id="worker.1",
            event_id="evt.worker.1",
            time="2026-09-23T00:00:01Z",
            source=SOURCE,
            actor_id="researcher.local",
        )
    )
    control.append(
        grant_recorded_draft(
            project_id=PROJECT,
            grant_id="grant.1",
            worker_id="worker.1",
            task_id="task.brick",
            run_id="run.1",
            attempt_id="attempt.1",
            nonce="nonce.1",
            expires_at=EXPIRES,
            event_id="evt.grant.1",
            time="2026-09-23T00:00:02Z",
            source=SOURCE,
            actor_id="researcher.local",
            authorization_event_id="evt.auth.1",
            authorization_sequence="1",
            image_digest=request.code.bundle_digest,
            config_digest=request.config_digest,
        )
    )
    key = b"k" * 32
    token = issue_grant_token(
        key,
        grant_id="grant.1",
        grant_event_id="evt.grant.1",
        worker_id="worker.1",
        task_id="task.brick",
        attempt_id="attempt.1",
        run_id="run.1",
        nonce="nonce.1",
        expires_at=EXPIRES,
        project_id=PROJECT,
        image_digest=request.code.bundle_digest,
        config_digest=request.config_digest,
    )
    high_water = store.freeze_high_water()
    store.close()
    return World(
        root=tmp_path,
        request=request,
        database=database,
        artifacts=artifacts,
        workspace=tmp_path / "workspace",
        token=token,
        hmac_key=key,
        code=code,
        high_water=high_water,
    )


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)


def _assert_not_started(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = world.root / "brick-ran"
    monkeypatch.setenv("R04_BRICK_RAN_MARKER", str(marker))
    assert "brick.task" not in sys.modules
    assert "brick" not in sys.modules
    assert not marker.exists()
    assert sys.executable not in (world.workspace / "receipt.json").read_text(encoding="utf-8")
    store = EventStore(world.database, create=False)
    try:
        assert store.freeze_high_water() == world.high_water
    finally:
        store.close()


def test_fresh_workspace_prepares_and_repeat_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    receipt = world.prepare()
    assert isinstance(receipt, NativeReviewedPreparationReceipt)
    assert receipt.launch_allowed is False
    assert receipt.interpreter_identity == "byte-digest"
    assert receipt.side_effects.entrypoints_imported == 0
    assert receipt.side_effects.packages_installed == 0
    materialized = world.workspace / "material" / "code" / "brick" / "task.py"
    assert materialized.read_bytes() == world.code
    assert b"changed-after-approval" not in materialized.read_bytes()
    diagnosis = world.diagnose()
    assert isinstance(diagnosis, NativeReviewedPreparationDiagnosis)
    assert diagnosis.outcome == "ready"
    assert diagnosis.launch_allowed is False
    assert diagnosis.reason_code == "preparation-ready"
    again = world.prepare()
    assert again == receipt
    before = check_before_user_code(
        request=world.request,
        store=EventStore(world.database, create=False),
        artifacts=LocalArtifactStore(world.artifacts),
        workspace=world.workspace,
        grant_token=world.token,
        hmac_key=world.hmac_key,
        now=NOW,
    )
    assert before.outcome == "ready"
    assert before.launch_allowed is False
    _assert_not_started(world, monkeypatch)


@pytest.mark.parametrize(
    ("relative", "reason"),
    [
        ("material/code/brick/task.py", "code-substituted"),
        ("material/bundle", "code-substituted"),
        ("material/config.json", "config-substituted"),
        ("material/inputs/corpus", "input-substituted"),
        ("material/environment/interpreter", "environment-substituted"),
        ("material/environment/dependency-lock", "environment-substituted"),
        ("material/environment/inventory", "environment-substituted"),
        ("material/environment/review", "environment-substituted"),
    ],
)
def test_substituted_bytes_invalidate_before_user_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    reason: str,
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    world.prepare()
    target = world.workspace / relative
    target.write_bytes(target.read_bytes() + b"\n")
    diagnosis = world.before_start()
    assert isinstance(diagnosis, NativeReviewedPreparationDiagnosis)
    assert diagnosis.outcome == "invalidated"
    assert diagnosis.launch_allowed is False
    if relative == "material/environment/review":
        assert diagnosis.reason_code == "review-substituted"
    else:
        assert diagnosis.reason_code == reason
    with pytest.raises(NativeReviewedPreparationError, match="not reusable") as caught:
        world.prepare()
    assert caught.value.code == diagnosis.reason_code
    _assert_not_started(world, monkeypatch)


def test_mismatched_existing_environment_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    world.prepare()
    original = (world.workspace / "receipt.json").read_bytes()
    receipt = json.loads(original)
    receipt["planDigest"] = "jcs-sha256:" + "ab" * 32
    (world.workspace / "receipt.json").write_bytes(canonical_json(receipt).encode("utf-8"))
    diagnosis = world.diagnose()
    assert isinstance(diagnosis, NativeReviewedPreparationDiagnosis)
    assert diagnosis.outcome == "mismatched"
    assert diagnosis.reason_code == "environment-mismatch"
    with pytest.raises(NativeReviewedPreparationError) as caught:
        world.prepare()
    assert caught.value.code == "environment-mismatch"
    assert (world.workspace / "material" / "code" / "brick" / "task.py").read_bytes() == world.code
    _assert_not_started(world, monkeypatch)


def test_incomplete_or_damaged_preparation_is_diagnosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    fresh = world.diagnose()
    assert isinstance(fresh, NativeReviewedPreparationDiagnosis)
    assert fresh.outcome == "incomplete"
    assert fresh.launch_allowed is False
    world.prepare()
    (world.workspace / "material" / "inputs" / "corpus").unlink()
    missing = world.diagnose()
    assert isinstance(missing, NativeReviewedPreparationDiagnosis)
    assert missing.outcome == "incomplete"
    assert missing.reason_code == "preparation-incomplete"
    with pytest.raises(NativeReviewedPreparationError) as caught:
        world.prepare()
    assert caught.value.code == "preparation-incomplete"
    (world.workspace / "planted").write_text("nope", encoding="utf-8")
    # The missing input is reported first only when no extra file rule wins.
    # Restore the input so the extra file is the remaining damage.
    (world.workspace / "material" / "inputs" / "corpus").write_bytes(b'{"rows":1}\n')
    damaged = world.diagnose()
    assert isinstance(damaged, NativeReviewedPreparationDiagnosis)
    assert damaged.outcome == "damaged"
    assert damaged.reason_code == "preparation-damaged"
    _assert_not_started(world, monkeypatch)


def test_revoked_expired_and_bad_grant_do_not_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    expired = world.diagnose(now=datetime(2028, 1, 1, tzinfo=UTC))
    assert isinstance(expired, NativeReviewedPreparationDiagnosis)
    assert expired.reason_code == "grant-expired"
    assert expired.launch_allowed is False
    forged = world.diagnose(hmac_key=b"x" * 32)
    assert isinstance(forged, NativeReviewedPreparationDiagnosis)
    assert forged.reason_code == "grant-hmac-invalid"
    store = EventStore(world.database)
    WorkerControl(store, project_id=PROJECT).append(
        grant_revoked_draft(
            project_id=PROJECT,
            grant_id="grant.1",
            run_id="run.1",
            attempt_id="attempt.1",
            event_id="evt.grant.revoked",
            time="2026-09-23T00:00:03Z",
            source=SOURCE,
            actor_id="researcher.local",
        )
    )
    store.close()
    revoked = world.diagnose()
    assert isinstance(revoked, NativeReviewedPreparationDiagnosis)
    assert revoked.reason_code == "grant-revoked"
    with pytest.raises(NativeReviewedPreparationError):
        world.prepare()
    assert not world.workspace.exists()


def test_consumed_grant_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    store = EventStore(world.database)
    control = WorkerControl(store, project_id=PROJECT)
    control.append(
        work_queued_draft(
            project_id=PROJECT,
            task_id="task.brick",
            run_id="run.1",
            attempt_id="attempt.1",
            image_digest=world.request.code.bundle_digest,
            config_digest=world.request.config_digest,
            event_id="evt.work.queued",
            time="2026-09-23T00:00:03Z",
            source=SOURCE,
        )
    )
    control.append(
        work_leased_draft(
            project_id=PROJECT,
            lease_id="lease.1",
            worker_id="worker.1",
            task_id="task.brick",
            grant_id="grant.1",
            run_id="run.1",
            attempt_id="attempt.1",
            expires_at=EXPIRES,
            event_id="evt.work.leased",
            time="2026-09-23T00:00:04Z",
            source=SOURCE,
        )
    )
    control.append(
        grant_consumed_draft(
            project_id=PROJECT,
            grant_id="grant.1",
            lease_id="lease.1",
            nonce="nonce.1",
            run_id="run.1",
            attempt_id="attempt.1",
            event_id="evt.grant.consumed",
            time="2026-09-23T00:00:05Z",
            source=SOURCE,
            worker_id="worker.1",
        )
    )
    store.close()
    diagnosis = world.diagnose()
    assert isinstance(diagnosis, NativeReviewedPreparationDiagnosis)
    assert diagnosis.reason_code == "grant-already-consumed"
    assert diagnosis.launch_allowed is False


def test_local_capability_and_symlink_source_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path, capability="execute.local")
    diagnosis = world.diagnose()
    assert isinstance(diagnosis, NativeReviewedPreparationDiagnosis)
    assert diagnosis.reason_code == "authorization-capability-mismatch"
    link = tmp_path / "linked-request.json"
    target = tmp_path / "request.json"
    target.write_text("{}", encoding="utf-8")
    link.symlink_to(target)
    with pytest.raises(NativeReviewedPreparationError) as caught:
        load_bounded_file(link, limit=100)
    assert caught.value.code == "source-path-rejected"


def _validate_example(name: str, document: object) -> None:
    if name.startswith("bundle"):
        NativeReviewedPythonBundle.model_validate(document)
    elif name.startswith("interpreter"):
        NativeReviewedInterpreterIdentity.model_validate(document)
    else:
        NativeReviewedPreparationReceipt.model_validate(document)


def test_examples_and_schemas_reject_tampering() -> None:
    NativeReviewedPythonBundle.model_validate_json((EXAMPLES / "valid" / "bundle.json").read_text())
    NativeReviewedCodeReview.model_validate_json((EXAMPLES / "valid" / "review.json").read_text())
    NativeReviewedInterpreterIdentity.model_validate_json(
        (EXAMPLES / "valid" / "interpreter-identity.json").read_text()
    )
    NativeReviewedDependencyLock.model_validate_json(
        (EXAMPLES / "valid" / "dependency-lock.json").read_text()
    )
    NativeReviewedDependencyInventory.model_validate_json(
        (EXAMPLES / "valid" / "dependency-inventory.json").read_text()
    )
    NativeReviewedPreparationReceipt.model_validate_json(
        (EXAMPLES / "valid" / "linux-receipt.json").read_text()
    )
    NativeReviewedPreparationDiagnosis.model_validate_json(
        (EXAMPLES / "valid" / "linux-diagnosis.json").read_text()
    )
    for name in (
        "receipt-launch-allowed.json",
        "bundle-absolute-path.json",
        "interpreter-path.json",
        "receipt-substituted-code.json",
    ):
        document = json.loads((EXAMPLES / "invalid" / name).read_text())
        with pytest.raises(ValidationError):
            _validate_example(name, document)


def test_cli_prepare_and_doctor_do_not_start_user_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_subprocess(monkeypatch)
    world = _build(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(world.request.model_dump(mode="json", by_alias=True, exclude_none=True)),
        encoding="utf-8",
    )
    token_path = tmp_path / "grant.token"
    token_path.write_text(world.token + "\n", encoding="utf-8")
    key_path = tmp_path / "hmac.key"
    key_path.write_bytes(world.hmac_key)
    parser = build_parser()
    prepare_args = parser.parse_args(
        [
            "native",
            "prepare",
            str(request_path),
            str(world.database),
            str(world.artifacts),
            str(world.workspace),
            "--grant-token-file",
            str(token_path),
            "--hmac-key-file",
            str(key_path),
            "--format",
            "json",
        ]
    )
    assert run_native(prepare_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["launchAllowed"] is False
    assert payload["outcome"] == "prepared"
    doctor_args = parser.parse_args(
        [
            "native",
            "doctor",
            str(request_path),
            str(world.database),
            str(world.artifacts),
            str(world.workspace),
            "--grant-token-file",
            str(token_path),
            "--hmac-key-file",
            str(key_path),
            "--format",
            "json",
        ]
    )
    assert run_native(doctor_args) == 0
    diagnosis = json.loads(capsys.readouterr().out)
    assert diagnosis["outcome"] == "ready"
    assert diagnosis["launchAllowed"] is False
    assert request_digest(world.request) == payload["requestDigest"]
    _assert_not_started(world, monkeypatch)


def test_missing_artifact_is_refused(tmp_path: Path) -> None:
    world = _build(tmp_path)
    empty = tmp_path / "empty-cas"
    empty.mkdir()
    diagnosis = diagnose_reviewed_environment(
        request=world.request,
        store=EventStore(world.database, create=False),
        artifacts=LocalArtifactStore(empty),
        workspace=world.workspace,
        grant_token=world.token,
        hmac_key=world.hmac_key,
        now=NOW,
    )
    assert diagnosis.reason_code == "artifact-missing"
    assert diagnosis.launch_allowed is False
