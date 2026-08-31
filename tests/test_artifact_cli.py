from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from llm_research_os.artifacts import LocalArtifactStore
from llm_research_os.cli import main

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "schemas" / "artifact-object-report" / "v0alpha1.schema.json"


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _command(*args: object) -> list[str]:
    return ["artifacts", *(str(arg) for arg in args)]


def test_put_and_verify_emit_versioned_schema_valid_reports(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    source = tmp_path / "checkpoint.bin"
    payload = b"deterministic artifact bytes\x00\xff"
    source.write_bytes(payload)

    assert main(_command("put", root, source, "--format", "json")) == 0
    put_output = capsys.readouterr()  # type: ignore[attr-defined]
    put_report = json.loads(put_output.out)
    assert put_output.err == ""
    assert put_report == {
        "apiVersion": "researchos.dev/v0alpha1",
        "kind": "ArtifactObjectReport",
        "operation": "put",
        "digest": _digest(payload),
        "sizeBytes": len(payload),
        "storageKey": (f"objects/sha256/{_digest(payload)[7:9]}/{_digest(payload)[9:]}"),
    }
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    validator.validate(put_report)
    assert (root / put_report["storageKey"]).read_bytes() == payload

    assert main(_command("verify", root, put_report["digest"], "--format", "json")) == 0
    verify_output = capsys.readouterr()  # type: ignore[attr-defined]
    verify_report = json.loads(verify_output.out)
    assert verify_output.err == ""
    assert verify_report == {**put_report, "operation": "verify"}
    validator.validate(verify_report)


def test_text_output_contains_identity_without_caller_paths(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "private-artifacts"
    root.mkdir()
    source = tmp_path / "secret-source-name.bin"
    source.write_bytes(b"payload")

    assert main(_command("put", root, source, "--format", "text")) == 0
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.err == ""
    assert "artifact operation: put" in output.out
    assert f"digest: {_digest(b'payload')}" in output.out
    assert "size bytes: 7" in output.out
    assert "integrity verified: true" in output.out
    assert str(root) not in output.out
    assert str(source) not in output.out
    assert "secret-source-name" not in output.out


def test_repeated_put_is_idempotent_and_returns_the_same_identity(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    reports = []
    for source in (first, second):
        assert main(_command("put", root, source, "--format", "json")) == 0
        output = capsys.readouterr()  # type: ignore[attr-defined]
        assert output.err == ""
        reports.append(json.loads(output.out))
    assert reports[0] == reports[1]
    objects = [path for path in (root / "objects").rglob("*") if path.is_file()]
    assert len(objects) == 1


def test_missing_root_and_symlink_source_fail_without_creating_objects(
    tmp_path: Path,
    capsys: object,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    missing_root = tmp_path / "missing-root"
    assert main(_command("put", missing_root, source, "--format", "json")) == 2
    missing_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert missing_output.out == ""
    assert json.loads(missing_output.err)["errors"][0]["type"] == "ArtifactPathError"
    assert not missing_root.exists()

    root = tmp_path / "artifacts"
    root.mkdir()
    root_link = tmp_path / "artifact-root-link"
    root_link.symlink_to(root, target_is_directory=True)
    assert main(_command("put", root_link, source, "--format", "json")) == 2
    root_link_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert root_link_output.out == ""
    assert json.loads(root_link_output.err)["errors"][0]["type"] == "ArtifactPathError"
    assert list(root.iterdir()) == []

    link = tmp_path / "source-link.bin"
    link.symlink_to(source)
    assert main(_command("put", root, link, "--format", "json")) == 2
    link_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert link_output.out == ""
    assert json.loads(link_output.err)["errors"][0]["type"] == "ArtifactPathError"
    assert list(root.iterdir()) == []


def test_missing_object_is_domain_negative_and_invalid_digest_is_input_error(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    missing = "sha256:" + "0" * 64
    assert main(_command("verify", root, missing, "--format", "json")) == 1
    missing_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert missing_output.out == ""
    assert json.loads(missing_output.err)["errors"][0]["type"] == ("ArtifactNotFoundError")

    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    assert main(_command("verify", root, "../../outside", "--format", "json")) == 2
    invalid_output = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid_output.out == ""
    assert json.loads(invalid_output.err)["errors"][0]["type"] == "ArtifactPathError"
    assert outside.read_bytes() == b"unchanged"
    assert list(root.iterdir()) == []


def test_verify_detects_corruption_and_never_repairs_it(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    record = LocalArtifactStore(root).put(source)
    object_path = root / record.storage_key
    object_path.write_bytes(b"tampered")

    assert main(_command("verify", root, record.digest, "--format", "json")) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert json.loads(output.err)["errors"][0]["type"] == "ArtifactIntegrityError"
    assert object_path.read_bytes() == b"tampered"


def test_text_errors_escape_terminal_control_characters(
    tmp_path: Path,
    capsys: object,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    hostile = tmp_path / "missing\n\x1b[31m.bin"
    assert main(_command("put", root, hostile, "--format", "text")) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert output.out == ""
    assert "\\n" in output.err
    assert "\\u001b" in output.err
    assert "\x1b" not in output.err
    assert "\nnext" not in output.err
