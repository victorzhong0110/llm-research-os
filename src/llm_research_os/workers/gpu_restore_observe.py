"""Observe ms-swift / transformers Trainer checkpoint loads inside the GPU container.

Host pytest imports this module. The container copies it onto PYTHONPATH as
``sitecustomize`` so ``swift sft`` wraps Trainer without changing argv.
A record is emitted only after a successful load_state_dict / setstate, with
the source file digest and a post-load summary. File presence, argv, and
prepare-to-load strings must not produce ``phase=loaded``.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

OBSERVE_KIND = "GpuRestoreObserve"
OBSERVE_FILENAME = "researchos-restore-observe.jsonl"
OBSERVE_ENV = "RESEARCHOS_GPU_RESTORE_OBSERVE"
OBSERVE_PATH_ENV = "RESEARCHOS_GPU_RESTORE_OBSERVE_PATH"
CONTAINER_OBSERVE_DIR = "/work/output/.researchos"
CONTAINER_PYTHONPATH = CONTAINER_OBSERVE_DIR
_OPTIMIZER_NAMES = ("optimizer.pt", "optimizer.bin")
_SCHEDULER_NAMES = ("scheduler.pt", "scheduler.bin")
_RNG_NAMES = ("rng_state.pth", "rng_state.bin")
_CHUNK = 65_536


def observe_path() -> Path:
    raw = os.environ.get(OBSERVE_PATH_ENV)
    if type(raw) is str and raw != "":
        return Path(raw)
    return Path("/work/output") / OBSERVE_FILENAME


def file_digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def after_summary(obj: object) -> dict[str, object]:
    """Compact post-load fingerprint. Missing state_dict is not success."""

    state_fn = getattr(obj, "state_dict", None)
    if not callable(state_fn):
        return {}
    try:
        state = state_fn()
    except Exception:
        return {}
    payload = _fingerprint(state)
    digest = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    keys = list(state) if isinstance(state, dict) else []
    return {"stateDigest": digest, "keyCount": len(keys)}


def rng_after_summary() -> dict[str, object]:
    python_state = repr(random.getstate())
    digest = "sha256:" + hashlib.sha256(python_state.encode("utf-8")).hexdigest()
    return {"pythonStateDigest": digest}


def emit_loaded(
    *,
    name: str,
    source_path: str,
    source_digest: str,
    after: dict[str, object],
    trainer_class: str,
) -> None:
    if name not in {"optimizer", "scheduler", "rng"}:
        return
    if type(source_path) is not str or source_path == "":
        return
    if type(source_digest) is not str or not source_digest.startswith("sha256:"):
        return
    if type(after) is not dict or not after:
        return
    record = {
        "kind": OBSERVE_KIND,
        "phase": "loaded",
        "name": name,
        "sourcePath": source_path,
        "sourceDigest": source_digest,
        "after": after,
        "trainerClass": trainer_class,
    }
    path = observe_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def install(trainer_cls: type[Any] | None = None) -> bool:
    """Wrap Trainer load hooks. Idempotent. Missing transformers is not success."""

    resolved: type[Any]
    if trainer_cls is None:
        try:
            from transformers.trainer import Trainer as imported  # type: ignore[import-not-found]
        except ImportError:
            return False
        resolved = imported
    else:
        resolved = trainer_cls
    if getattr(resolved, "_researchos_restore_observe", False) is True:
        return True
    original_opt = resolved._load_optimizer_and_scheduler
    original_rng = resolved._load_rng_state
    trainer_name = f"{resolved.__module__}.{resolved.__qualname__}"

    def wrapped_opt(self: Any, checkpoint: str | None) -> None:
        _run_optimizer_scheduler(self, checkpoint, original_opt, trainer_name)

    def wrapped_rng(self: Any, checkpoint: str | None) -> None:
        _run_rng(self, checkpoint, original_rng, trainer_name)

    resolved._load_optimizer_and_scheduler = wrapped_opt
    resolved._load_rng_state = wrapped_rng
    resolved._researchos_restore_observe = True
    return True


def _run_optimizer_scheduler(
    trainer: Any,
    checkpoint: str | None,
    original: Callable[..., None],
    trainer_name: str,
) -> None:
    opt_loaded: list[tuple[str, str, dict[str, object]]] = []
    sch_loaded: list[tuple[str, str, dict[str, object]]] = []
    optimizer = getattr(trainer, "optimizer", None)
    scheduler = getattr(trainer, "lr_scheduler", None)
    opt_restore = _wrap_load_state_dict(optimizer, "optimizer", checkpoint, opt_loaded)
    sch_restore = _wrap_load_state_dict(scheduler, "scheduler", checkpoint, sch_loaded)
    try:
        original(trainer, checkpoint)
    finally:
        opt_restore()
        sch_restore()
    for source, digest, after in opt_loaded:
        emit_loaded(
            name="optimizer",
            source_path=source,
            source_digest=digest,
            after=after,
            trainer_class=trainer_name,
        )
    for source, digest, after in sch_loaded:
        emit_loaded(
            name="scheduler",
            source_path=source,
            source_digest=digest,
            after=after,
            trainer_class=trainer_name,
        )


def _run_rng(
    trainer: Any,
    checkpoint: str | None,
    original: Callable[..., None],
    trainer_name: str,
) -> None:
    rng_file = _existing_file(checkpoint, _RNG_NAMES)
    called = False
    original_setstate = random.setstate

    def wrapped_setstate(state: Any) -> None:
        nonlocal called
        original_setstate(state)
        called = True

    random.setstate = wrapped_setstate
    try:
        original(trainer, checkpoint)
    finally:
        random.setstate = original_setstate
    if not called or rng_file is None:
        return
    emit_loaded(
        name="rng",
        source_path=rng_file,
        source_digest=file_digest(rng_file),
        after=rng_after_summary(),
        trainer_class=trainer_name,
    )


def _wrap_load_state_dict(
    obj: Any,
    name: str,
    checkpoint: str | None,
    loaded: list[tuple[str, str, dict[str, object]]],
) -> Callable[[], None]:
    if obj is None or not callable(getattr(obj, "load_state_dict", None)):
        return lambda: None
    names = _OPTIMIZER_NAMES if name == "optimizer" else _SCHEDULER_NAMES
    source = _existing_file(checkpoint, names)
    original = obj.load_state_dict

    def wrapped(state: object, *args: object, **kwargs: object) -> object:
        result = original(state, *args, **kwargs)
        after = after_summary(obj)
        if source is not None and after:
            loaded.append((source, file_digest(source), after))
        return result

    obj.load_state_dict = wrapped

    def restore() -> None:
        obj.load_state_dict = original

    return restore


def _existing_file(checkpoint: str | None, names: tuple[str, ...]) -> str | None:
    if type(checkpoint) is not str or checkpoint == "":
        return None
    root = Path(checkpoint)
    for name in names:
        path = root / name
        if path.is_file():
            return str(path)
    return None


def _fingerprint(value: object) -> str:
    try:
        return json.dumps(_jsonable(value), ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _jsonable(value: object) -> object:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in list(value.items())[:32]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in list(value)[:32]]
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    if shape is not None:
        return {"shape": [int(item) for item in shape], "dtype": str(dtype)}
    return type(value).__name__
