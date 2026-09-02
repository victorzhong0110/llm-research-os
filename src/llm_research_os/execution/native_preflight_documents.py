"""Strict external documents for native-process launch preflight."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from llm_research_os.canonical import content_digest
from llm_research_os.execution.native_preflight import (
    MAX_NATIVE_OUTPUT_BYTES,
    MAX_NATIVE_TASK_PATH_ITEMS,
    MAX_NATIVE_TERMINATION_GRACE_SECONDS,
    MAX_NATIVE_WALL_TIME_SECONDS,
    NATIVE_PROCESS_INTERPRETER_IDENTITY,
    NATIVE_PROCESS_NETWORK,
    NATIVE_PROCESS_PROTOCOL,
    NATIVE_PROCESS_RUNNER,
    NATIVE_PROCESS_TERMINATION,
    NATIVE_PROCESS_WORKSPACE,
    NativeProcessLimits,
    NativeProcessPreflightPolicy,
    NativeProcessPreflightResult,
    native_process_preflight_payload,
)
from llm_research_os.spec.io import load_document
from llm_research_os.spec.models import StrictModel

NATIVE_PROCESS_PREFLIGHT_REQUEST_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-process-preflight-request/v0alpha1.schema.json"
)
NATIVE_PROCESS_PREFLIGHT_REPORT_SCHEMA_ID = (
    "https://researchos.dev/schemas/native-process-preflight-report/v0alpha1.schema.json"
)
NATIVE_PROCESS_PREFLIGHT_API_VERSION: Literal["researchos.dev/v0alpha1"] = "researchos.dev/v0alpha1"

PreflightDigest = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]
PreflightIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
PreflightVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=(
            r"^(0|[1-9][0-9]*)\."
            r"(0|[1-9][0-9]*)\."
            r"(0|[1-9][0-9]*)"
            r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
            r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
        ),
    ),
]


class NativeProcessPreflightDocumentModel(StrictModel):
    """Frozen alias-only external model without coercion or repair."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=False,
        str_strip_whitespace=False,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
    )


class NativeProcessLimitsDocument(NativeProcessPreflightDocumentModel):
    """Bounded resource ceilings for a future process invocation."""

    wall_time_seconds: int = Field(ge=1, le=MAX_NATIVE_WALL_TIME_SECONDS, alias="wallTimeSeconds")
    stdout_bytes: int = Field(ge=0, le=MAX_NATIVE_OUTPUT_BYTES, alias="stdoutBytes")
    stderr_bytes: int = Field(ge=0, le=MAX_NATIVE_OUTPUT_BYTES, alias="stderrBytes")
    termination_grace_seconds: int = Field(
        ge=0,
        le=MAX_NATIVE_TERMINATION_GRACE_SECONDS,
        alias="terminationGraceSeconds",
    )

    def value(self) -> NativeProcessLimits:
        return NativeProcessLimits(
            wall_time_seconds=self.wall_time_seconds,
            stdout_bytes=self.stdout_bytes,
            stderr_bytes=self.stderr_bytes,
            termination_grace_seconds=self.termination_grace_seconds,
        )


class NativeProcessPreflightRequestDocument(NativeProcessPreflightDocumentModel):
    """Caller-owned review request for one exact authorized static plan."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeProcessPreflightRequest"]
    spec_digest: PreflightDigest = Field(alias="specDigest")
    registry_digest: PreflightDigest = Field(alias="registryDigest")
    plan_digest: PreflightDigest = Field(alias="planDigest")
    authorization_decision_digest: PreflightDigest = Field(alias="authorizationDecisionDigest")
    task_path: tuple[PreflightIdentifier, ...] = Field(
        min_length=1,
        max_length=MAX_NATIVE_TASK_PATH_ITEMS,
        alias="taskPath",
    )
    runner: Literal["researchos.python-worker/v0alpha1"]
    shell: Literal[False]
    network: Literal["denied"]
    workspace: Literal["isolated-temporary"]
    environment_allowlist: tuple[PreflightIdentifier, ...] = Field(
        max_length=0,
        alias="environmentAllowlist",
    )
    limits: NativeProcessLimitsDocument

    @field_validator("shell", mode="before")
    @classmethod
    def require_json_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("shell must be a JSON boolean")
        return value

    @field_validator("task_path", "environment_allowlist", mode="before")
    @classmethod
    def freeze_json_arrays(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("native preflight collections must be JSON arrays")
        return tuple(value)

    def policy(self) -> NativeProcessPreflightPolicy:
        return NativeProcessPreflightPolicy(
            spec_digest=self.spec_digest,
            registry_digest=self.registry_digest,
            plan_digest=self.plan_digest,
            authorization_decision_digest=self.authorization_decision_digest,
            task_path=tuple(self.task_path),
            runner=self.runner,
            shell=self.shell,
            network=self.network,
            workspace=self.workspace,
            environment_allowlist=tuple(self.environment_allowlist),
            limits=self.limits.value(),
        )


class NativeProcessPreflightBinding(NativeProcessPreflightDocumentModel):
    spec_digest: PreflightDigest = Field(alias="specDigest")
    registry_digest: PreflightDigest = Field(alias="registryDigest")
    plan_digest: PreflightDigest = Field(alias="planDigest")
    authorization_decision_digest: PreflightDigest = Field(alias="authorizationDecisionDigest")


class NativeProcessTaskIdentity(NativeProcessPreflightDocumentModel):
    task_path: tuple[PreflightIdentifier, ...] = Field(
        min_length=1,
        max_length=MAX_NATIVE_TASK_PATH_ITEMS,
        alias="taskPath",
    )
    block_id: PreflightIdentifier = Field(alias="blockId")
    block_version: PreflightVersion = Field(alias="blockVersion")
    manifest_digest: PreflightDigest = Field(alias="manifestDigest")
    config_digest: PreflightDigest = Field(alias="configDigest")
    entrypoint_digest: PreflightDigest = Field(alias="entrypointDigest")
    runtime_type: Literal["python"] = Field(alias="runtimeType")
    runner: Literal["researchos.python-worker/v0alpha1"]
    protocol: Literal["researchos.python-json-stdio/v0alpha1"]

    @field_validator("task_path", mode="before")
    @classmethod
    def freeze_task_path(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("taskPath must be an array")


class NativeProcessLaunchConstraints(NativeProcessPreflightDocumentModel):
    shell: Literal[False]
    network: Literal["denied"]
    workspace: Literal["isolated-temporary"]
    environment_allowlist: tuple[PreflightIdentifier, ...] = Field(
        max_length=0,
        alias="environmentAllowlist",
    )
    argv_mode: Literal["trusted-runner-fixed"] = Field(alias="argvMode")
    stdin: Literal["json-object"]
    stdout: Literal["bounded-capture"]
    stderr: Literal["bounded-capture"]
    termination: Literal["terminate-then-kill"]
    interpreter_identity: Literal["not-bound"] = Field(alias="interpreterIdentity")

    @field_validator("shell", mode="before")
    @classmethod
    def require_shell_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("shell must be a JSON boolean")
        return value

    @field_validator("environment_allowlist", mode="before")
    @classmethod
    def freeze_environment(cls, value: object) -> object:
        if type(value) is list:
            return tuple(value)
        if type(value) is tuple:
            return value
        raise ValueError("environmentAllowlist must be an array")


class NativeProcessPreflightSideEffects(NativeProcessPreflightDocumentModel):
    blocks_executed: Literal[0] = Field(alias="blocksExecuted")
    entrypoints_imported: Literal[0] = Field(alias="entrypointsImported")
    processes_spawned: Literal[0] = Field(alias="processesSpawned")
    signals_sent: Literal[0] = Field(alias="signalsSent")
    network_requests: Literal[0] = Field(alias="networkRequests")
    persistent_writes: Literal[0] = Field(alias="persistentWrites")
    paid_actions: Literal[0] = Field(alias="paidActions")

    @field_validator(
        "blocks_executed",
        "entrypoints_imported",
        "processes_spawned",
        "signals_sent",
        "network_requests",
        "persistent_writes",
        "paid_actions",
        mode="before",
    )
    @classmethod
    def require_integer_zero(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("side-effect counts must be JSON integers")
        return value


class NativeProcessPreflightReport(NativeProcessPreflightDocumentModel):
    """Normalized review report that can never authorize a process launch."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeProcessPreflightReport"]
    status: Literal["reviewable"]
    launch_allowed: Literal[False] = Field(alias="launchAllowed")
    preflight_digest: PreflightDigest = Field(alias="preflightDigest")
    binding: NativeProcessPreflightBinding
    task: NativeProcessTaskIdentity
    constraints: NativeProcessLaunchConstraints
    limits: NativeProcessLimitsDocument
    authorization_authentication: Literal["not-authenticated"] = Field(
        alias="authorizationAuthentication"
    )
    authorization_persistence: Literal["not-persisted"] = Field(alias="authorizationPersistence")
    isolation: Literal["not-enforced"]
    execution: Literal["not-executed"]
    side_effects: NativeProcessPreflightSideEffects = Field(alias="sideEffects")

    @field_validator("launch_allowed", mode="before")
    @classmethod
    def require_launch_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("launchAllowed must be a JSON boolean")
        return value

    @model_validator(mode="after")
    def digest_is_self_consistent(self) -> Self:
        result = self.result()
        if self.preflight_digest != content_digest(native_process_preflight_payload(result)):
            raise ValueError("preflightDigest does not match the native process report")
        return self

    def result(self) -> NativeProcessPreflightResult:
        return NativeProcessPreflightResult(
            spec_digest=self.binding.spec_digest,
            registry_digest=self.binding.registry_digest,
            plan_digest=self.binding.plan_digest,
            authorization_decision_digest=self.binding.authorization_decision_digest,
            preflight_digest=self.preflight_digest,
            task_path=tuple(self.task.task_path),
            block_id=self.task.block_id,
            block_version=self.task.block_version,
            manifest_digest=self.task.manifest_digest,
            config_digest=self.task.config_digest,
            entrypoint_digest=self.task.entrypoint_digest,
            limits=self.limits.value(),
        )

    @classmethod
    def from_result(cls, result: NativeProcessPreflightResult) -> NativeProcessPreflightReport:
        return cls(
            apiVersion=NATIVE_PROCESS_PREFLIGHT_API_VERSION,
            kind="NativeProcessPreflightReport",
            status="reviewable",
            launchAllowed=False,
            preflightDigest=result.preflight_digest,
            binding=NativeProcessPreflightBinding(
                specDigest=result.spec_digest,
                registryDigest=result.registry_digest,
                planDigest=result.plan_digest,
                authorizationDecisionDigest=result.authorization_decision_digest,
            ),
            task=NativeProcessTaskIdentity(
                taskPath=result.task_path,
                blockId=result.block_id,
                blockVersion=result.block_version,
                manifestDigest=result.manifest_digest,
                configDigest=result.config_digest,
                entrypointDigest=result.entrypoint_digest,
                runtimeType="python",
                runner=NATIVE_PROCESS_RUNNER,
                protocol=NATIVE_PROCESS_PROTOCOL,
            ),
            constraints=NativeProcessLaunchConstraints(
                shell=False,
                network=NATIVE_PROCESS_NETWORK,
                workspace=NATIVE_PROCESS_WORKSPACE,
                environmentAllowlist=(),
                argvMode="trusted-runner-fixed",
                stdin="json-object",
                stdout="bounded-capture",
                stderr="bounded-capture",
                termination=NATIVE_PROCESS_TERMINATION,
                interpreterIdentity=NATIVE_PROCESS_INTERPRETER_IDENTITY,
            ),
            limits=NativeProcessLimitsDocument(
                wallTimeSeconds=result.limits.wall_time_seconds,
                stdoutBytes=result.limits.stdout_bytes,
                stderrBytes=result.limits.stderr_bytes,
                terminationGraceSeconds=result.limits.termination_grace_seconds,
            ),
            authorizationAuthentication="not-authenticated",
            authorizationPersistence="not-persisted",
            isolation="not-enforced",
            execution="not-executed",
            sideEffects=NativeProcessPreflightSideEffects(
                blocksExecuted=0,
                entrypointsImported=0,
                processesSpawned=0,
                signalsSent=0,
                networkRequests=0,
                persistentWrites=0,
                paidActions=0,
            ),
        )


def validate_native_process_preflight_request_document(
    document: object,
) -> NativeProcessPreflightRequestDocument:
    return NativeProcessPreflightRequestDocument.model_validate(document)


def load_native_process_preflight_request(
    path: str | Path,
) -> NativeProcessPreflightRequestDocument:
    return validate_native_process_preflight_request_document(
        load_document(path, reject_symlinks=True)
    )
