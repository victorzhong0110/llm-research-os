"""Private, bounded persistent extension state; installation never runs code."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from llm_research_os.application.workspace import load_workspace
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.extensions.manifest import ExtensionError, parse_manifest, run_adapter
from llm_research_os.extensions.package import (
    AdapterInput,
    AdapterOutput,
    ExtensionPackage,
    Role,
    load_package,
    parse_package,
)

REGISTRY_DDL = (
    "CREATE TABLE extensions (id TEXT,version TEXT,package TEXT NOT NULL,"
    "digest TEXT NOT NULL,trust TEXT NOT NULL CHECK(trust IN ('inert','reviewed-same-user')),"
    "enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),PRIMARY KEY(id,version))"
)


class PersistentExtensions:
    def __init__(self, root: Path) -> None:
        workspace = load_workspace(root)
        self.path = workspace.root / "extensions.sqlite"
        if self.path.is_symlink() or (
            self.path.exists() and self.path.stat().st_size > 16 * 1024 * 1024
        ):
            raise ExtensionError("registry-invalid", "the extension registry cannot be opened")
        self.project_id = workspace.project_id
        with self._db() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                db.execute(REGISTRY_DDL)
                db.execute("PRAGMA user_version=1")
            elif tables != {"extensions"} or db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ExtensionError("registry-invalid", "unrecognized extension registry")
            structure = db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if len(structure) != 1 or tuple(structure[0]) != ("table", "extensions", REGISTRY_DDL):
                raise ExtensionError(
                    "registry-invalid", "unrecognized extension registry structure"
                )
            self._rows(db)
        self.path.chmod(0o600)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = list(db.execute("SELECT * FROM extensions ORDER BY id,version LIMIT 33"))
        if len(rows) > 32:
            raise ExtensionError("registry-invalid", "too many installed extensions")
        result = []
        for row in rows:
            if len(row["package"]) > 262144:
                raise ExtensionError("registry-invalid", "oversized installed declaration")
            package = parse_package(json.loads(row["package"]))
            document = package.model_dump(mode="json", by_alias=True, exclude_none=True)
            if (
                (row["id"], row["version"])
                != (package.manifest.extension_id, package.manifest.version)
                or row["digest"] != content_digest(document)
                or row["trust"] not in {"inert", "reviewed-same-user"}
                or row["enabled"] not in (0, 1)
            ):
                raise ExtensionError("registry-invalid", "installed identity mismatch")
            result.append(
                {
                    "id": row["id"],
                    "version": row["version"],
                    "package": document,
                    "packageDigest": row["digest"],
                    "trust": row["trust"],
                    "enabled": bool(row["enabled"]),
                }
            )
        return result

    def inspect(self) -> dict[str, Any]:
        with self._db() as db:
            rows = self._rows(db)
        missing = []
        enabled = {(r["id"], r["version"]) for r in rows if r["enabled"]}
        for row in rows:
            for dep in row["package"]["dependencies"]:
                if (dep["id"], dep["version"]) not in enabled:
                    missing.append({"id": row["id"], "dependency": dep})
        return {
            "projectId": self.project_id,
            "installed": rows,
            "digest": content_digest(rows),
            "missingDependencies": missing,
            "grantedPermissions": [],
            "isolation": "reviewed same-user only; no verified untrusted isolation",
            "backup": (
                "operator declarations require explicit reinstallation after workspace restore"
            ),
        }

    def install(
        self, path: Path, *, trust: Literal["inert", "reviewed-same-user", "untrusted"] = "inert"
    ) -> dict[str, Any]:
        return self.install_package(load_package(path), trust=trust)

    def install_package(self, package: ExtensionPackage, *, trust: str = "inert") -> dict[str, Any]:
        if trust not in {"inert", "reviewed-same-user"}:
            raise ExtensionError(
                "trust-unsupported", "no verified isolation profile for untrusted code"
            )
        package = parse_package(package.model_dump(mode="json", by_alias=True, exclude_none=True))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._rows(db)
            keys = {(r["id"], r["version"]) for r in rows if r["enabled"]}
            key = (package.manifest.extension_id, package.manifest.version)
            if key in {(r["id"], r["version"]) for r in rows}:
                raise ExtensionError("extension-duplicate", "already installed")
            if len(rows) >= 32:
                raise ExtensionError("registry-full", "the extension limit is reached")
            if any((d.extension_id, d.version) not in keys for d in package.dependencies):
                raise ExtensionError("dependency-missing", "an exact enabled dependency is missing")
            document = package.model_dump(mode="json", by_alias=True, exclude_none=True)
            db.execute(
                "INSERT INTO extensions VALUES (?,?,?,?,?,1)",
                (*key, canonical_json(document), content_digest(document), trust),
            )
        return self.inspect()

    def change(
        self, extension_id: str, version: str, action: Literal["enable", "disable", "uninstall"]
    ) -> dict[str, Any]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = self._rows(db)
            if (extension_id, version) not in {(r["id"], r["version"]) for r in rows}:
                raise ExtensionError("extension-unknown", "not installed")
            if action == "uninstall":
                db.execute(
                    "DELETE FROM extensions WHERE id=? AND version=?", (extension_id, version)
                )
            else:
                db.execute(
                    "UPDATE extensions SET enabled=? WHERE id=? AND version=?",
                    (int(action == "enable"), extension_id, version),
                )
        return self.inspect()

    def run(
        self,
        extension_id: str,
        version: str,
        role: Role,
        payload: dict[str, Any],
        *,
        timeout: float = 10,
    ) -> dict[str, Any]:
        # This read transaction is the dispatch boundary. Disable prevents future
        # dispatch; it does not claim to cancel already-running reviewed processes.
        with self._db() as db:
            db.execute("BEGIN")
            rows = self._rows(db)
            row = next(
                (r for r in rows if (r["id"], r["version"]) == (extension_id, version)), None
            )
            if row is None or not row["enabled"]:
                raise ExtensionError("extension-disabled", "the extension is missing or disabled")
            if row["trust"] != "reviewed-same-user":
                raise ExtensionError("trust-unsupported", "inert declarations cannot dispatch")
            enabled = {(r["id"], r["version"]) for r in rows if r["enabled"]}
            package = parse_package(row["package"])
            if any((d.extension_id, d.version) not in enabled for d in package.dependencies):
                raise ExtensionError("dependency-missing", "an enabled dependency is missing")
            interface = next((i for i in package.interfaces if i.role == role), None)
            if interface is None:
                raise ExtensionError("interface-missing", "the role is not declared")
            manifest = parse_manifest(
                package.manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
            )
        try:
            request = AdapterInput.model_validate(
                {"kind": interface.request_kind, "version": interface.version, "payload": payload}
            )
        except (ValueError, TypeError, RecursionError) as exc:
            raise ExtensionError("message-invalid", "invalid adapter input envelope") from exc
        result = run_adapter(
            manifest,
            request.model_dump(mode="json"),
            timeout=timeout,
        )
        document = result.public_document()
        if result.outcome != "ok":
            return {"adapter": document, "response": None, "packageDigest": row["packageDigest"]}
        try:
            response = json.loads(result.stdout)
            if (
                not isinstance(response, dict)
                or set(response) != {"kind", "version", "payload"}
                or response["kind"] != interface.response_kind
                or response["version"] != interface.version
                or not isinstance(response["payload"], dict)
            ):
                raise ValueError("response contract")
            # Reject NaN/deep/foreign JSON before passing an adapter response on.
            from llm_research_os.internal.jsonclone import snapshot_json_document

            # jsonclone rejects host types/cycles but preserves floats. JSON encoding
            # must reject non-finite values, including overflow such as 1e999.
            json.dumps(response, allow_nan=False)
            response = snapshot_json_document(response)
            AdapterOutput.model_validate(response)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ExtensionError(
                "response-invalid", "the adapter response violates its interface"
            ) from exc
        return {"adapter": document, "response": response, "packageDigest": row["packageDigest"]}
