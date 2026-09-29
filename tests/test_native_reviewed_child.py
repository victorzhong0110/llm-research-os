"""Fixed runner frame validation, with import replaced by a trusted stub."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_research_os.execution import native_reviewed_child as child


def _input(monkeypatch: pytest.MonkeyPatch, frame: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(frame)))


def _frame(root: Path, files: dict[str, str], *, entrypoint: str = "childunit:main") -> bytes:
    return (
        json.dumps({"root": str(root), "entrypoint": entrypoint, "files": files}).encode() + b"\n"
    )


def _root(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "material/code/childunit.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# reviewed bytes\n")
    return tmp_path, {
        "material/code/childunit.py": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    }


@pytest.mark.parametrize("frame", [b"", b"x" * 16_385 + b"\n", b"[]\n", b"{}\n"])
def test_missing_oversized_or_malformed_frame_refused(
    frame: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _input(monkeypatch, frame)
    assert child.main() == 70


def test_parent_traversal_and_symlink_refused_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, files = _root(tmp_path)
    monkeypatch.setattr(
        child, "importlib", SimpleNamespace(import_module=lambda *_: pytest.fail("import"))
    )
    _input(monkeypatch, _frame(root, {"material/code/../escape": next(iter(files.values()))}))
    assert child.main() == 70
    source = root / "material/code/childunit.py"
    source.unlink()
    source.symlink_to(root / "elsewhere")
    _input(monkeypatch, _frame(root, files))
    assert child.main() == 70


def test_digest_mismatch_refused_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, files = _root(tmp_path)
    monkeypatch.setattr(
        child, "importlib", SimpleNamespace(import_module=lambda *_: pytest.fail("import"))
    )
    files["material/code/childunit.py"] = "sha256:" + "0" * 64
    _input(monkeypatch, _frame(root, files))
    assert child.main() == 70


def test_verified_frame_invokes_fixed_entrypoint_and_serializes_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, files = _root(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        child,
        "importlib",
        SimpleNamespace(
            import_module=lambda name: SimpleNamespace(main=lambda: {"reviewed": name})
        ),
    )
    _input(monkeypatch, _frame(root, files))
    assert child.main() == 0
    assert json.loads(capsys.readouterr().out) == {"reviewed": "childunit"}


def test_entrypoint_error_fails_without_a_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, files = _root(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(root)

    def raise_task() -> None:
        raise ValueError("expected")

    monkeypatch.setattr(
        child,
        "importlib",
        SimpleNamespace(import_module=lambda _: SimpleNamespace(main=raise_task)),
    )
    _input(monkeypatch, _frame(root, files))
    assert child.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "ValueError" in output.err


def test_unlisted_bytecode_cannot_replace_reviewed_source(tmp_path: Path) -> None:
    source = tmp_path / "material/code/childunit.py"
    source.parent.mkdir(parents=True)
    source.write_text("def main(): return {'reviewed': True}\n")
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir()
    import importlib._bootstrap_external as bootstrap  # noqa: PLC0415

    replacement = compile("def main(): return {'unreviewed': True}\n", str(source), "exec")
    cache.write_bytes(bootstrap._code_to_hash_pyc(replacement, b"12345678", checked=False))
    frame = _frame(
        tmp_path,
        {"material/code/childunit.py": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()},
    )
    runner = Path(child.__file__)
    completed = subprocess.run(  # noqa: S603 - fixed trusted runner
        [sys.executable, "-I", "-B", str(runner)],
        input=frame,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"reviewed": True}


def test_dotted_reviewed_entrypoint(tmp_path: Path) -> None:
    source = tmp_path / "material/code/childunit.py"
    source.parent.mkdir(parents=True)
    source.write_text("class Task:\n    @staticmethod\n    def main(): return 42\n")
    frame = _frame(
        tmp_path,
        {"material/code/childunit.py": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()},
        entrypoint="childunit:Task.main",
    )
    completed = subprocess.run(  # noqa: S603 - fixed trusted runner
        [sys.executable, "-I", "-B", str(Path(child.__file__))],
        input=frame,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == 42
