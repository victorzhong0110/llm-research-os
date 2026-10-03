"""Private controller/Worker state names and nonblocking Worker-local locks."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from llm_research_os.execution.native_reviewed_documents import NativeReviewedExecutionRequest
from llm_research_os.execution.native_transfer import _directory
from llm_research_os.workers.errors import WorkerError


def start_journal_name(database: Path, request: NativeReviewedExecutionRequest) -> str:
    identity = f"{database.name}:{request.project_id}:{request.run_id}:{request.attempt_id}"
    return "native-start-" + hashlib.sha256(identity.encode()).hexdigest() + ".json"


@contextmanager
def private_state_lock(root: Path, name: str) -> Iterator[int]:
    with _directory(root, create=False) as directory:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkerError("native state root is not private", code="native-state-invalid")
        descriptor = os.open(
            name + ".lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size != 0
            ):
                raise WorkerError("native state lock is unsafe", code="native-state-invalid")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkerError("native executor is busy", code="native-state-busy") from None
            yield directory
        finally:
            os.close(descriptor)
