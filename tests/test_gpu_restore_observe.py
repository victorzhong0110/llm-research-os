from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_research_os.workers.gpu_restore_observe import (
    OBSERVE_KIND,
    OBSERVE_PATH_ENV,
    after_summary,
    file_digest,
    install,
    observe_path,
)


class _State:
    def __init__(self) -> None:
        self._state: dict[str, object] = {"init": 1}

    def state_dict(self) -> dict[str, object]:
        return dict(self._state)

    def load_state_dict(self, state: object) -> None:
        if type(state) is dict:
            self._state = dict(state)


class _Trainer:
    def __init__(self) -> None:
        self.optimizer = _State()
        self.lr_scheduler = _State()

    def _load_optimizer_and_scheduler(self, checkpoint: str | None) -> None:
        return None

    def _load_rng_state(self, checkpoint: str | None) -> None:
        return None


class _LoadingTrainer(_Trainer):
    def _load_optimizer_and_scheduler(self, checkpoint: str | None) -> None:
        assert checkpoint is not None
        self.optimizer.load_state_dict({"loaded": "optimizer", "from": checkpoint})
        self.lr_scheduler.load_state_dict({"loaded": "scheduler", "from": checkpoint})

    def _load_rng_state(self, checkpoint: str | None) -> None:
        import random

        random.setstate(random.getstate())


class _PrepareLogTrainer(_Trainer):
    def _load_optimizer_and_scheduler(self, checkpoint: str | None) -> None:
        _ = f"Loading optimizer states from {checkpoint}"

    def _load_rng_state(self, checkpoint: str | None) -> None:
        _ = "loading rng_state.pth"


def _checkpoint(root: Path) -> Path:
    directory = root / "checkpoint-10"
    directory.mkdir()
    (directory / "optimizer.pt").write_bytes(b"optimizer-bytes")
    (directory / "scheduler.pt").write_bytes(b"scheduler-bytes")
    (directory / "rng_state.pth").write_bytes(b"rng-bytes")
    return directory


def _records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            document = json.loads(line)
            assert type(document) is dict
            out.append(document)
    return out


def test_prepare_log_without_load_state_dict_does_not_emit_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observe = tmp_path / "observe.jsonl"
    monkeypatch.setenv(OBSERVE_PATH_ENV, str(observe))
    checkpoint = _checkpoint(tmp_path)
    assert install(_PrepareLogTrainer) is True
    trainer = _PrepareLogTrainer()
    trainer._load_optimizer_and_scheduler(str(checkpoint))
    trainer._load_rng_state(str(checkpoint))
    assert _records(observe_path()) == []


def test_missing_checkpoint_files_do_not_emit_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observe = tmp_path / "observe.jsonl"
    monkeypatch.setenv(OBSERVE_PATH_ENV, str(observe))
    empty = tmp_path / "checkpoint-missing"
    empty.mkdir()
    assert install(_LoadingTrainer) is True
    trainer = _LoadingTrainer()
    trainer._load_optimizer_and_scheduler(str(empty))
    trainer._load_rng_state(str(empty))
    assert _records(observe_path()) == []


def test_successful_load_emits_source_digest_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observe = tmp_path / "observe.jsonl"
    monkeypatch.setenv(OBSERVE_PATH_ENV, str(observe))
    checkpoint = _checkpoint(tmp_path)
    assert install(_LoadingTrainer) is True
    trainer = _LoadingTrainer()
    trainer._load_optimizer_and_scheduler(str(checkpoint))
    trainer._load_rng_state(str(checkpoint))
    records = {item["name"]: item for item in _records(observe_path())}
    assert set(records) == {"optimizer", "scheduler", "rng"}
    for name, source_name in (
        ("optimizer", "optimizer.pt"),
        ("scheduler", "scheduler.pt"),
        ("rng", "rng_state.pth"),
    ):
        item = records[name]
        source = checkpoint / source_name
        assert item["kind"] == OBSERVE_KIND
        assert item["phase"] == "loaded"
        assert item["sourcePath"] == str(source)
        assert item["sourceDigest"] == file_digest(source)
        after = item["after"]
        assert type(after) is dict
        assert after
        if name != "rng":
            target = trainer.optimizer if name == "optimizer" else trainer.lr_scheduler
            assert after == after_summary(target)
        else:
            assert type(after.get("pythonStateDigest")) is str
            assert str(after["pythonStateDigest"]).startswith("sha256:")
