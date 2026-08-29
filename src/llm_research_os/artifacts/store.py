"""Local content-addressed artifact objects stored outside SQLite."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Final

from llm_research_os.artifacts.errors import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreError,
)
from llm_research_os.artifacts.models import ArtifactRecord

CHUNK_SIZE: Final[int] = 65_536
DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_DIGITS: Final[str] = "0123456789abcdef"
_PRIVATE_FILE_MODE: Final[int] = stat.S_IRUSR | stat.S_IWUSR
_PRIVATE_DIR_MODE: Final[int] = stat.S_IRWXU


def parse_artifact_digest(value: object) -> str:
    """Return a tagged SHA-256 digest after a full-string match.

    User input never becomes an object-path component. Only this verified
    ``sha256:`` + 64 lowercase hex form may derive ``storage_key``.
    """

    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ArtifactPathError("artifact digest must match sha256:<64 lowercase hex>")
    return value


def storage_key_for(digest: str) -> str:
    """Return the relative object key derived from a verified digest."""

    hex_digest = parse_artifact_digest(digest).removeprefix("sha256:")
    return f"objects/sha256/{hex_digest[:2]}/{hex_digest[2:]}"


class LocalArtifactStore:
    """Immutable local file object store addressed by raw-byte SHA-256 digests.

    Artifact bytes are hashed as the source file's raw contents. This path must
    not call :func:`llm_research_os.canonical.content_digest`, which hashes
    canonical JSON rather than file bytes.
    """

    __slots__ = ("_root",)

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).absolute()
        _validate_directory(self._root, role="artifact store root")

    @property
    def root(self) -> Path:
        """Return the absolute store root directory."""

        return self._root

    def put(self, source: str | Path) -> ArtifactRecord:
        """Import a regular local file, publishing an object only after the digest is known."""

        root = self._require_root()
        source_path = Path(source)
        source_fd = _open_regular_file(source_path, role="import source")
        temp_path: Path | None = None
        temp_fd: int | None = None
        try:
            temp_path, temp_fd = _create_temp(root)
            digest, size = _copy_hashed(source_fd, temp_fd)
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            return _publish(root, temp_path, digest, size)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("could not import artifact") from exc
        finally:
            _close_quietly(source_fd)
            if temp_fd is not None:
                _close_quietly(temp_fd)
            if temp_path is not None:
                _unlink_quietly(temp_path)

    def exists(self, digest: str) -> bool:
        """Return whether a regular object exists for a verified digest."""

        path = self._object_path(digest)
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ArtifactStoreError(f"could not inspect artifact object: {digest}") from exc
        _require_regular_object(metadata, what=digest)
        return True

    def verify(self, digest: str) -> ArtifactRecord:
        """Re-hash a stored object and fail closed on size or digest mismatch."""

        expected = parse_artifact_digest(digest)
        path = self._object_path(expected)
        descriptor = _open_regular_file(
            path,
            role="artifact object",
            missing=ArtifactNotFoundError,
        )
        try:
            actual, size = _hash_fd(descriptor)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError(f"could not read artifact object: {expected}") from exc
        finally:
            _close_quietly(descriptor)
        if actual != expected:
            raise ArtifactIntegrityError(f"artifact digest mismatch: {expected}")
        return ArtifactRecord(
            digest=expected,
            size_bytes=size,
            storage_key=storage_key_for(expected),
        )

    def open(self, digest: str) -> BinaryIO:
        """Open a stored object read-only after verifying the path is a regular file."""

        path = self._object_path(digest)
        descriptor = _open_regular_file(
            path,
            role="artifact object",
            missing=ArtifactNotFoundError,
        )
        try:
            return os.fdopen(descriptor, "rb")
        except OSError as exc:
            _close_quietly(descriptor)
            raise ArtifactStoreError(f"could not open artifact object: {digest}") from exc

    def _require_root(self) -> Path:
        _validate_directory(self._root, role="artifact store root")
        return self._root

    def _object_path(self, digest: str) -> Path:
        self._require_root()
        return _object_path(self._root, storage_key_for(digest))


def _flag(*names: str) -> int:
    value = 0
    for name in names:
        flag = getattr(os, name, None)
        if not isinstance(flag, int):
            raise ArtifactStoreError(f"artifact store requires {name}")
        value |= flag
    return value


def _validate_directory(path: Path, *, role: str) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        raise ArtifactPathError(f"{role} does not exist: {path}") from None
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect {role}: {path}") from exc
    _reject_symlink(path, metadata, role=role)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactPathError(f"{role} must be a directory: {path}")

    flags = _flag("O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactPathError(f"could not open {role}: {path}") from exc
    try:
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect {role}: {path}") from exc
    finally:
        _close_quietly(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        raise ArtifactPathError(f"{role} must be a directory: {path}")


def _reject_symlink(path: Path, metadata: os.stat_result, *, role: str) -> None:
    if stat.S_ISLNK(metadata.st_mode):
        raise ArtifactPathError(f"{role} must not be a symbolic link: {path}")


def _reject_non_regular_source(path: Path, metadata: os.stat_result, *, role: str) -> None:
    _reject_symlink(path, metadata, role=role)
    mode = metadata.st_mode
    if stat.S_ISDIR(mode):
        raise ArtifactPathError(f"{role} must be a regular file, not a directory: {path}")
    if stat.S_ISFIFO(mode):
        raise ArtifactPathError(f"{role} must be a regular file, not a FIFO: {path}")
    if stat.S_ISSOCK(mode):
        raise ArtifactPathError(f"{role} must be a regular file, not a socket: {path}")
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        raise ArtifactPathError(f"{role} must be a regular file, not a device: {path}")
    if not stat.S_ISREG(mode):
        raise ArtifactPathError(f"{role} must be a regular file: {path}")


def _require_regular_object(metadata: os.stat_result, *, what: str) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArtifactIntegrityError(f"artifact object is not a regular file: {what}")


def _open_regular_file(
    path: Path,
    *,
    role: str,
    missing: type[ArtifactStoreError] = ArtifactPathError,
) -> int:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        raise missing(f"{role} does not exist: {path}") from None
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect {role}: {path}") from exc

    if role == "artifact object":
        _require_regular_object(metadata, what=str(path))
    else:
        _reject_non_regular_source(path, metadata, role=role)

    flags = _flag("O_RDONLY", "O_CLOEXEC", "O_NONBLOCK", "O_NOFOLLOW")
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise missing(f"{role} does not exist: {path}") from None
    except OSError as exc:
        if role == "artifact object":
            raise ArtifactIntegrityError(f"could not open artifact object: {path}") from exc
        raise ArtifactPathError(f"could not open {role}: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if role == "artifact object":
            _require_regular_object(opened, what=str(path))
        else:
            _reject_non_regular_source(path, opened, role=role)
    except ArtifactStoreError:
        _close_quietly(descriptor)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        raise ArtifactPathError(f"could not inspect {role}: {path}") from exc
    return descriptor


def _create_temp(root: Path) -> tuple[Path, int]:
    tmp_dir = root / "tmp"
    _ensure_private_dir(tmp_dir)
    name = f"tmp-{os.getpid()}-{secrets.token_hex(16)}"
    temp_path = tmp_dir / name
    flags = _flag("O_WRONLY", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW")
    try:
        descriptor = os.open(temp_path, flags, _PRIVATE_FILE_MODE)
    except OSError as exc:
        raise ArtifactStoreError(f"could not create temporary artifact file: {temp_path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ArtifactStoreError(f"temporary artifact file is not regular: {temp_path}")
    except ArtifactStoreError:
        _close_quietly(descriptor)
        _unlink_quietly(temp_path)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        _unlink_quietly(temp_path)
        raise ArtifactStoreError(f"could not inspect temporary artifact file: {temp_path}") from exc
    return temp_path, descriptor


def _ensure_private_dir(path: Path) -> None:
    try:
        os.mkdir(path, _PRIVATE_DIR_MODE)
    except FileExistsError:
        _validate_directory(path, role="artifact directory")
        return
    except OSError as exc:
        raise ArtifactPathError(f"could not create directory: {path}") from exc


def _copy_hashed(source_fd: int, destination_fd: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    for chunk in _read_chunks(source_fd):
        hasher.update(chunk)
        _write_all(destination_fd, chunk)
        size += len(chunk)
    return f"sha256:{hasher.hexdigest()}", size


def _hash_fd(descriptor: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    for chunk in _read_chunks(descriptor):
        hasher.update(chunk)
        size += len(chunk)
    return f"sha256:{hasher.hexdigest()}", size


def _read_chunks(descriptor: int) -> Iterator[bytes]:
    while True:
        try:
            chunk = os.read(descriptor, CHUNK_SIZE)
        except OSError as exc:
            raise ArtifactStoreError("could not read artifact bytes") from exc
        if not chunk:
            return
        yield chunk


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        try:
            written = os.write(descriptor, view[offset:])
        except OSError as exc:
            raise ArtifactStoreError("could not write artifact bytes") from exc
        if written == 0:
            raise ArtifactStoreError("could not write artifact bytes")
        offset += written


def _publish(root: Path, temp_path: Path, digest: str, size: int) -> ArtifactRecord:
    storage_key = storage_key_for(digest)
    destination = _object_path(root, storage_key)
    _ensure_private_dir(destination.parent.parent.parent)
    _ensure_private_dir(destination.parent.parent)
    _ensure_private_dir(destination.parent)
    try:
        os.link(temp_path, destination)
    except FileExistsError:
        return _require_matching_object(destination, digest, size, storage_key)
    except OSError as exc:
        raise ArtifactStoreError("could not publish artifact object") from exc
    try:
        _fsync_directory(destination.parent)
    except ArtifactStoreError:
        raise
    except OSError as exc:
        raise ArtifactStoreError("could not persist artifact object directory") from exc
    return ArtifactRecord(digest=digest, size_bytes=size, storage_key=storage_key)


def _require_matching_object(
    destination: Path,
    digest: str,
    size: int,
    storage_key: str,
) -> ArtifactRecord:
    descriptor = _open_regular_file(
        destination,
        role="artifact object",
        missing=ArtifactIntegrityError,
    )
    try:
        actual, actual_size = _hash_fd(descriptor)
    except ArtifactStoreError:
        raise
    except OSError as exc:
        raise ArtifactStoreError(f"could not read existing artifact object: {digest}") from exc
    finally:
        _close_quietly(descriptor)
    if actual != digest or actual_size != size:
        raise ArtifactIntegrityError(f"existing artifact object does not match digest {digest}")
    return ArtifactRecord(digest=digest, size_bytes=size, storage_key=storage_key)


def _object_path(root: Path, storage_key: str) -> Path:
    parts = storage_key.split("/")
    if (
        parts[:2] != ["objects", "sha256"]
        or len(parts) != 4
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts[2]) != 2
        or len(parts[3]) != 62
        or any(character not in _HEX_DIGITS for character in parts[2] + parts[3])
    ):
        raise ArtifactPathError("invalid artifact storage key")
    path = root.joinpath(*parts).absolute()
    if not path.is_relative_to(root.absolute()):
        raise ArtifactPathError("artifact object path escaped store root")
    return path


def _fsync_directory(path: Path) -> None:
    flags = _flag("O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactStoreError(f"could not persist directory: {path}") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise ArtifactStoreError(f"could not persist directory: {path}") from exc
    finally:
        _close_quietly(descriptor)


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        return


def _unlink_quietly(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        return
