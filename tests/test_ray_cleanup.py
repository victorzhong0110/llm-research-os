"""Ray fixture teardown retries only its observed transient directory race."""

import errno
from pathlib import Path

import pytest
from test_ray_native_live import _remove_ray_scratch


def test_transient_log_writer_race_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    actual = shutil.rmtree
    calls = []

    def raced(path: str) -> None:
        calls.append(path)
        if len(calls) == 1:
            raise OSError(errno.ENOTEMPTY, "late log writer")
        actual(path)

    scratch = tmp_path / "owned"
    scratch.mkdir()
    monkeypatch.setattr(shutil, "rmtree", raced)
    _remove_ray_scratch(str(scratch))
    assert len(calls) == 2 and not scratch.exists()


def test_persistent_cleanup_error_is_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    def fail(path: str) -> None:
        raise OSError(errno.ENOTEMPTY, "still active")

    monkeypatch.setattr(shutil, "rmtree", fail)
    with pytest.raises(OSError, match="still active"):
        _remove_ray_scratch(str(tmp_path), timeout=0)
