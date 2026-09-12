"""Output preparation cannot write through links or acquire host privileges."""

import os
from pathlib import Path

import pytest

from llm_research_os.workers import gpu
from llm_research_os.workers.errors import WorkerSandboxError


@pytest.mark.parametrize("intermediate", [False, True])
def test_install_rejects_symlink_escape(tmp_path: Path, intermediate: bool) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "state"
    victim.write_bytes(b"original")
    root = tmp_path / "output"
    root.mkdir()
    if intermediate:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        target = root / "linked" / "state"
    else:
        target = root / "state"
        target.symlink_to(victim)
    with pytest.raises(WorkerSandboxError, match="operator-provisioned"):
        gpu._install_bytes(target, b"replacement")
    assert victim.read_bytes() == b"original"


def test_hardlink_is_not_truncated(tmp_path: Path) -> None:
    victim = tmp_path / "original"
    victim.write_bytes(b"keep")
    linked = tmp_path / "linked"
    os.link(victim, linked)
    with pytest.raises(WorkerSandboxError, match="operator-provisioned"):
        gpu._install_bytes(linked, b"overwrite")
    assert victim.read_bytes() == b"keep"


def test_nonroot_never_runs_privileged_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "output"
    target.mkdir()
    monkeypatch.setattr(gpu.os, "geteuid", lambda: 12345)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("permission preparation must not spawn a command")

    monkeypatch.setattr(gpu.subprocess, "run", forbidden)
    assert gpu._grant_container_user_write(target, 65534, 65534) is False


def test_install_create_replace_and_mode(tmp_path: Path) -> None:
    target = tmp_path / "identity"
    gpu._install_bytes(target, b"long old value")
    target.chmod(0o666)
    gpu._install_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == gpu.GPU_OUTPUT_FILE_MODE


def test_prepare_rejects_symlink_directory(tmp_path: Path) -> None:
    target = tmp_path / "directory"
    target.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorkerSandboxError, match="operator-provisioned"):
        gpu._ensure_gpu_dir(target)


def test_no_chmod_through_links(tmp_path: Path) -> None:
    victim = tmp_path / "original"
    victim.write_text("original")
    victim.chmod(0o666)
    link = tmp_path / "link"
    link.symlink_to(victim)
    with pytest.raises(WorkerSandboxError, match="world-writable"):
        gpu._clear_world_write(link)
    assert victim.stat().st_mode & 0o777 == 0o666


def test_root_chown_failure_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "directory"
    target.mkdir()
    monkeypatch.setattr(gpu.os, "geteuid", lambda: 0)

    def deny(*args: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(gpu.os, "fchown", deny)
    assert gpu._grant_container_user_write(target, 65534, 65534) is False


def test_directory_not_replaced_by_bytes(tmp_path: Path) -> None:
    with pytest.raises(WorkerSandboxError, match="operator-provisioned"):
        gpu._install_bytes(tmp_path, b"bad")
    assert tmp_path.is_dir()
