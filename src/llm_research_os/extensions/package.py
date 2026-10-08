"""Versioned packages for explicit reviewed brick/evaluator/provider adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from llm_research_os.extensions.contracts import Document, ExtensionDeclaration, Identifier
from llm_research_os.extensions.manifest import (
    MAX_MANIFEST_BYTES,
    ExtensionError,
    parse_manifest,
)
from llm_research_os.internal.jsonclone import snapshot_json_document

Role = Literal["brick", "evaluator", "provider"]


class Dependency(Document):
    extension_id: Identifier = Field(alias="id")
    version: Identifier


class Interface(Document):
    role: Role
    version: Literal["v0alpha1"]
    # These are data-only request/response interfaces, not Worker grants.
    request_kind: Literal["BrickInput", "EvaluationInput", "ProviderInput"] = Field(
        alias="requestKind"
    )
    response_kind: Literal["BrickOutput", "EvaluationOutput", "ProviderOutput"] = Field(
        alias="responseKind"
    )

    @model_validator(mode="after")
    def coherent(self) -> Interface:
        names = {"brick": "Brick", "evaluator": "Evaluation", "provider": "Provider"}
        prefix = names[self.role]
        if self.request_kind != prefix + "Input" or self.response_kind != prefix + "Output":
            raise ValueError("role and message kinds differ")
        return self


class ExtensionPackage(Document):
    api_version: Literal["researchos.dev/extension-package/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["ExtensionPackage"]
    manifest: ExtensionDeclaration
    interfaces: list[Interface] = Field(min_length=1, max_length=3)
    host_contracts: list[Literal["v0alpha1"]] = Field(
        alias="hostContracts", min_length=1, max_length=1
    )
    dependencies: list[Dependency] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique(self) -> ExtensionPackage:
        roles = [i.role for i in self.interfaces]
        deps = [(d.extension_id, d.version) for d in self.dependencies]
        if len(set(roles)) != len(roles) or len(set(deps)) != len(deps):
            raise ValueError("duplicate interfaces or dependencies")
        if (self.manifest.extension_id, self.manifest.version) in deps:
            raise ValueError("an extension cannot depend on itself")
        return self


def parse_package(document: dict[str, Any]) -> ExtensionPackage:
    try:
        bounded = snapshot_json_document(document)
        if len(json.dumps(bounded).encode()) > MAX_MANIFEST_BYTES:
            raise ValueError("package too large")
        package = ExtensionPackage.model_validate(bounded)
        parse_manifest(package.manifest.model_dump(mode="json", by_alias=True, exclude_none=True))
        return package
    except (ValueError, TypeError, RecursionError, ValidationError) as exc:
        raise ExtensionError(
            "package-invalid", "the extension package is incompatible or invalid"
        ) from exc


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_package(path: Path) -> ExtensionPackage:
    # Reuse the existing no-symlink, regular-file, bounded inert loader discipline.
    # A package is not a v1 manifest; validate its bytes directly with no imports.
    import os
    import stat

    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not regular")
        raw = os.read(fd, MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("too large")
        return parse_package(json.loads(raw, object_pairs_hook=_unique_pairs))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ExtensionError("package-invalid", "the package could not be read") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def existing_cpu_evaluator() -> dict[str, Any]:
    """Adapt the already-reviewed pure CPU evaluator without importing on install."""
    from llm_research_os.evaluation import iris

    source = Path(iris.__file__).read_text(encoding="utf-8")
    entry = source + "\nimport json,sys\nr=json.load(sys.stdin)\n"
    entry += (
        'if r.get("kind") != "EvaluationInput" or '
        'r.get("payload") != {"task":"pinned-iris"}:\n'
        '    raise ValueError("unsupported evaluation input")\n'
    )
    entry += (
        'print(json.dumps({"kind":"EvaluationOutput","version":"v0alpha1","payload":main()}))\n'
    )
    return {
        "apiVersion": "researchos.dev/extension-package/v0alpha1",
        "kind": "ExtensionPackage",
        "hostContracts": ["v0alpha1"],
        "dependencies": [],
        "interfaces": [
            {
                "role": "evaluator",
                "version": "v0alpha1",
                "requestKind": "EvaluationInput",
                "responseKind": "EvaluationOutput",
            }
        ],
        "manifest": {
            "apiVersion": "researchos.dev/extension/v0alpha1",
            "kind": "Extension",
            "id": "researchos.pinned-iris",
            "version": "1.0.0",
            "contractVersion": "v0alpha1",
            "permissions": [],
            "diagnostics": {
                "provenance": (
                    "existing reviewed CPU development evaluator; no independent confirmation"
                )
            },
            "entryModule": entry,
        },
    }


class AdapterInput(Document):
    kind: Literal["BrickInput", "EvaluationInput", "ProviderInput"]
    version: Literal["v0alpha1"]
    payload: dict[str, Any] = Field(max_length=1024)


class AdapterOutput(Document):
    kind: Literal["BrickOutput", "EvaluationOutput", "ProviderOutput"]
    version: Literal["v0alpha1"]
    payload: dict[str, Any] = Field(max_length=1024)
