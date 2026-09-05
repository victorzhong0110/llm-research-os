"""Local content-addressed artifact objects stored outside SQLite."""

from __future__ import annotations

import errno
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
MAX_PUT_BYTES: Final[int] = 1_048_576
DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRIVATE_FILE_MODE: Final[int] = stat.S_IRUSR | stat.S_IWUSR
_PRIVATE_DIR_MODE: Final[int] = stat.S_IRWXU
_SYMLINK_ERRNOS: Final[frozenset[int]] = frozenset({errno.ELOOP, errno.EPERM})


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


def _hook_after_trusted_root_open() -> None:
    """Test hook after the trusted root dirfd is open and identity-checked."""


def _hook_after_shard_dir_open() -> None:
    """Test hook after the digest shard dirfd is open, before object open/link."""


class LocalArtifactStore:
    """Immutable local file object store addressed by raw-byte SHA-256 digests.

    Artifact bytes are hashed as the source file's raw contents. This path must
    not call :func:`llm_research_os.canonical.content_digest`, which hashes
    canonical JSON rather than file bytes.

    Every object operation re-opens the recorded root inode and walks
    ``tmp`` / ``objects`` / ``sha256`` / shard through held directory
    descriptors. Intermediate symlinks are not followed.
    """

    __slots__ = ("_root", "_root_dev", "_root_ino")

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).absolute()
        root_fd = _open_root_path(self._root)
        try:
            identity = os.fstat(root_fd)
            self._root_dev = identity.st_dev
            self._root_ino = identity.st_ino
        finally:
            _close_quietly(root_fd)

    @property
    def root(self) -> Path:
        """Return the absolute store root directory."""

        return self._root

    def put(self, source: str | Path) -> ArtifactRecord:
        """Import a regular local file, publishing an object only after the digest is known."""

        source_fd = _open_regular_source(Path(source))
        owned: list[int] = []
        tmp_fd: int | None = None
        temp_name: str | None = None
        try:
            root_fd = self._open_trusted_root()
            owned.append(root_fd)
            _hook_after_trusted_root_open()
            tmp_fd = _ensure_child_dir(root_fd, "tmp", parent_reason="tmp")
            owned.append(tmp_fd)
            temp_name, temp_fd = _create_temp(tmp_fd)
            owned.append(temp_fd)
            digest, size = _copy_hashed(source_fd, temp_fd)
            _fsync_file(temp_fd)
            shard_name, object_name = _object_components(digest)
            objects_fd = _ensure_child_dir(root_fd, "objects", parent_reason="objects")
            owned.append(objects_fd)
            algorithm_fd = _ensure_child_dir(objects_fd, "sha256", parent_reason="sha256")
            owned.append(algorithm_fd)
            shard_fd = _ensure_child_dir(algorithm_fd, shard_name, parent_reason="shard")
            owned.append(shard_fd)
            _hook_after_shard_dir_open()
            return _publish(
                tmp_fd=tmp_fd,
                temp_name=temp_name,
                shard_fd=shard_fd,
                object_name=object_name,
                digest=digest,
                size=size,
            )
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("could not import artifact") from exc
        finally:
            if tmp_fd is not None and temp_name is not None:
                _unlink_at(tmp_fd, temp_name)
            _close_all(owned)
            _close_quietly(source_fd)

    def put_bytes(self, payload: bytes) -> ArtifactRecord:
        """Publish in-memory bytes as one content-addressed object.

        Intended for small protocol objects (prompt/output JSON). Source-file
        ``put`` remains the path for arbitrary local files.
        """

        if type(payload) is not bytes:
            raise ArtifactPathError("artifact payload must be bytes")
        if len(payload) > MAX_PUT_BYTES:
            raise ArtifactPathError("artifact payload exceeds put_bytes limit")
        owned: list[int] = []
        tmp_fd: int | None = None
        temp_name: str | None = None
        try:
            root_fd = self._open_trusted_root()
            owned.append(root_fd)
            _hook_after_trusted_root_open()
            tmp_fd = _ensure_child_dir(root_fd, "tmp", parent_reason="tmp")
            owned.append(tmp_fd)
            temp_name, temp_fd = _create_temp(tmp_fd)
            owned.append(temp_fd)
            digest, size = _write_hashed(temp_fd, payload)
            _fsync_file(temp_fd)
            shard_name, object_name = _object_components(digest)
            objects_fd = _ensure_child_dir(root_fd, "objects", parent_reason="objects")
            owned.append(objects_fd)
            algorithm_fd = _ensure_child_dir(objects_fd, "sha256", parent_reason="sha256")
            owned.append(algorithm_fd)
            shard_fd = _ensure_child_dir(algorithm_fd, shard_name, parent_reason="shard")
            owned.append(shard_fd)
            _hook_after_shard_dir_open()
            return _publish(
                tmp_fd=tmp_fd,
                temp_name=temp_name,
                shard_fd=shard_fd,
                object_name=object_name,
                digest=digest,
                size=size,
            )
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("could not import artifact") from exc
        finally:
            if tmp_fd is not None and temp_name is not None:
                _unlink_at(tmp_fd, temp_name)
            _close_all(owned)

    def exists(self, digest: str) -> bool:
        """Return whether a regular object exists for a verified digest."""

        parsed = parse_artifact_digest(digest)
        owned: list[int] = []
        try:
            shard_fd = self._open_shard(parsed, owned, allow_missing=True)
            if shard_fd is None:
                return False
            return _probe_object(shard_fd, _object_components(parsed)[1], parsed) is not None
        finally:
            _close_all(owned)

    def verify(self, digest: str) -> ArtifactRecord:
        """Re-hash a stored object and fail closed on size or digest mismatch."""

        expected = parse_artifact_digest(digest)
        owned: list[int] = []
        try:
            shard_fd = self._open_shard(expected, owned, allow_missing=False)
            if shard_fd is None:
                raise ArtifactNotFoundError(f"artifact object does not exist: {expected}")
            descriptor = _open_stored_object(
                shard_fd,
                _object_components(expected)[1],
                expected,
                missing=ArtifactNotFoundError,
            )
            owned.append(descriptor)
            actual, size = _hash_fd(descriptor)
            if actual != expected:
                raise ArtifactIntegrityError(f"artifact digest mismatch: {expected}")
            return ArtifactRecord(
                digest=expected,
                size_bytes=size,
                storage_key=storage_key_for(expected),
            )
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError(f"could not read artifact object: {expected}") from exc
        finally:
            _close_all(owned)

    def open(self, digest: str) -> BinaryIO:
        """Open a stored object read-only after verifying the path is a regular file."""

        expected = parse_artifact_digest(digest)
        owned: list[int] = []
        descriptor: int | None = None
        try:
            shard_fd = self._open_shard(expected, owned, allow_missing=False)
            if shard_fd is None:
                raise ArtifactNotFoundError(f"artifact object does not exist: {expected}")
            descriptor = _open_stored_object(
                shard_fd,
                _object_components(expected)[1],
                expected,
                missing=ArtifactNotFoundError,
            )
            handle = os.fdopen(descriptor, "rb")
            descriptor = None
            return handle
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError(f"could not open artifact object: {expected}") from exc
        finally:
            if descriptor is not None:
                _close_quietly(descriptor)
            _close_all(owned)

    def _open_trusted_root(self) -> int:
        root_fd = _open_root_path(self._root)
        try:
            identity = os.fstat(root_fd)
            if identity.st_dev != self._root_dev or identity.st_ino != self._root_ino:
                raise ArtifactPathError("artifact store root identity changed")
            if not stat.S_ISDIR(identity.st_mode):
                raise ArtifactPathError(f"artifact store root must be a directory: {self._root}")
            return root_fd
        except ArtifactStoreError:
            _close_quietly(root_fd)
            raise
        except OSError as exc:
            _close_quietly(root_fd)
            raise ArtifactPathError(f"could not reopen artifact store root: {self._root}") from exc

    def _open_shard(self, digest: str, owned: list[int], *, allow_missing: bool) -> int | None:
        root_fd = self._open_trusted_root()
        owned.append(root_fd)
        _hook_after_trusted_root_open()
        shard_name, _object_name = _object_components(digest)
        objects_fd = _open_child_dir(
            root_fd, "objects", allow_missing=allow_missing, role="artifact directory"
        )
        if objects_fd is None:
            return None
        owned.append(objects_fd)
        algorithm_fd = _open_child_dir(
            objects_fd, "sha256", allow_missing=allow_missing, role="artifact directory"
        )
        if algorithm_fd is None:
            return None
        owned.append(algorithm_fd)
        shard_fd = _open_child_dir(
            algorithm_fd, shard_name, allow_missing=allow_missing, role="artifact directory"
        )
        if shard_fd is None:
            return None
        owned.append(shard_fd)
        _hook_after_shard_dir_open()
        return shard_fd


def _flag(*names: str) -> int:
    value = 0
    for name in names:
        flag = getattr(os, name, None)
        if not isinstance(flag, int):
            raise ArtifactStoreError(f"artifact store requires {name}")
        value |= flag
    return value


def _dir_flags() -> int:
    return _flag("O_RDONLY", "O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")


def _file_read_flags() -> int:
    return _flag("O_RDONLY", "O_CLOEXEC", "O_NONBLOCK", "O_NOFOLLOW")


def _file_create_flags() -> int:
    return _flag("O_WRONLY", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW")


def _require_relative_name(name: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ArtifactPathError("invalid artifact path component")
    return name


def _object_components(digest: str) -> tuple[str, str]:
    hex_digest = parse_artifact_digest(digest).removeprefix("sha256:")
    return hex_digest[:2], hex_digest[2:]


def _open_root_path(path: Path) -> int:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        raise ArtifactPathError(f"artifact store root does not exist: {path}") from None
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect artifact store root: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ArtifactPathError(f"artifact store root must not be a symbolic link: {path}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactPathError(f"artifact store root must be a directory: {path}")
    try:
        descriptor = os.open(path, _dir_flags())
    except OSError as exc:
        raise _directory_open_error(exc, "artifact store root", str(path)) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ArtifactPathError(f"artifact store root must be a directory: {path}")
        return descriptor
    except ArtifactStoreError:
        _close_quietly(descriptor)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        raise ArtifactPathError(f"could not inspect artifact store root: {path}") from exc


def _directory_open_error(exc: OSError, role: str, name: str) -> ArtifactStoreError:
    if exc.errno in _SYMLINK_ERRNOS:
        return ArtifactPathError(f"{role} must not be a symbolic link: {name}")
    if exc.errno in {errno.ENOTDIR, errno.EEXIST}:
        return ArtifactPathError(f"{role} must be a directory: {name}")
    if exc.errno == errno.ENOENT:
        return ArtifactNotFoundError(f"{role} does not exist: {name}")
    return ArtifactPathError(f"could not open {role}: {name}")


def _open_child_dir(
    parent_fd: int,
    name: str,
    *,
    allow_missing: bool,
    role: str,
) -> int | None:
    name = _require_relative_name(name)
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise ArtifactNotFoundError(f"{role} does not exist: {name}") from None
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect {role}: {name}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ArtifactPathError(f"{role} must not be a symbolic link: {name}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactPathError(f"{role} must be a directory: {name}")
    try:
        descriptor = os.open(name, _dir_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise ArtifactNotFoundError(f"{role} does not exist: {name}") from None
    except OSError as exc:
        raise _directory_open_error(exc, role, name) from exc
    try:
        opened = os.fstat(descriptor)
        if stat.S_ISLNK(opened.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise ArtifactPathError(f"{role} must be a directory: {name}")
        return descriptor
    except ArtifactStoreError:
        _close_quietly(descriptor)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        raise ArtifactPathError(f"could not inspect {role}: {name}") from exc


def _ensure_child_dir(parent_fd: int, name: str, *, parent_reason: str) -> int:
    name = _require_relative_name(name)
    try:
        os.mkdir(name, _PRIVATE_DIR_MODE, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ArtifactPathError(f"could not create directory: {name}") from exc
    descriptor = _open_child_dir(parent_fd, name, allow_missing=False, role="artifact directory")
    if descriptor is None:
        raise ArtifactPathError(f"artifact directory does not exist: {name}")
    try:
        _fsync_fd(parent_fd, reason=parent_reason)
        return descriptor
    except BaseException:
        _close_quietly(descriptor)
        raise


def _reject_non_regular_source(path: Path, metadata: os.stat_result) -> None:
    mode = metadata.st_mode
    if stat.S_ISLNK(mode):
        raise ArtifactPathError(f"import source must not be a symbolic link: {path}")
    if stat.S_ISDIR(mode):
        raise ArtifactPathError(f"import source must be a regular file, not a directory: {path}")
    if stat.S_ISFIFO(mode):
        raise ArtifactPathError(f"import source must be a regular file, not a FIFO: {path}")
    if stat.S_ISSOCK(mode):
        raise ArtifactPathError(f"import source must be a regular file, not a socket: {path}")
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        raise ArtifactPathError(f"import source must be a regular file, not a device: {path}")
    if not stat.S_ISREG(mode):
        raise ArtifactPathError(f"import source must be a regular file: {path}")


def _open_regular_source(path: Path) -> int:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        raise ArtifactPathError(f"import source does not exist: {path}") from None
    except OSError as exc:
        raise ArtifactPathError(f"could not inspect import source: {path}") from exc
    _reject_non_regular_source(path, metadata)
    try:
        descriptor = os.open(path, _file_read_flags())
    except FileNotFoundError:
        raise ArtifactPathError(f"import source does not exist: {path}") from None
    except OSError as exc:
        if exc.errno in _SYMLINK_ERRNOS:
            raise ArtifactPathError(f"import source must not be a symbolic link: {path}") from exc
        raise ArtifactPathError(f"could not open import source: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        _reject_non_regular_source(path, opened)
        return descriptor
    except ArtifactStoreError:
        _close_quietly(descriptor)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        raise ArtifactPathError(f"could not inspect import source: {path}") from exc


def _open_stored_object(
    shard_fd: int,
    name: str,
    digest: str,
    *,
    missing: type[ArtifactStoreError],
) -> int:
    name = _require_relative_name(name)
    try:
        metadata = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise missing(f"artifact object does not exist: {digest}") from None
    except OSError as exc:
        raise ArtifactStoreError(f"could not inspect artifact object: {digest}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArtifactIntegrityError(f"artifact object is not a regular file: {digest}")
    try:
        descriptor = os.open(name, _file_read_flags(), dir_fd=shard_fd)
    except FileNotFoundError:
        raise missing(f"artifact object does not exist: {digest}") from None
    except OSError as exc:
        if exc.errno in _SYMLINK_ERRNOS:
            raise ArtifactIntegrityError(
                f"artifact object is not a regular file: {digest}"
            ) from exc
        raise ArtifactStoreError(f"could not open artifact object: {digest}") from exc
    try:
        opened = os.fstat(descriptor)
        if stat.S_ISLNK(opened.st_mode) or not stat.S_ISREG(opened.st_mode):
            raise ArtifactIntegrityError(f"artifact object is not a regular file: {digest}")
        return descriptor
    except ArtifactStoreError:
        _close_quietly(descriptor)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        raise ArtifactStoreError(f"could not inspect artifact object: {digest}") from exc


def _probe_object(shard_fd: int, name: str, digest: str) -> os.stat_result | None:
    try:
        descriptor = _open_stored_object(shard_fd, name, digest, missing=ArtifactNotFoundError)
    except ArtifactNotFoundError:
        return None
    try:
        return os.fstat(descriptor)
    except OSError as exc:
        raise ArtifactStoreError(f"could not inspect artifact object: {digest}") from exc
    finally:
        _close_quietly(descriptor)


def _create_temp(tmp_fd: int) -> tuple[str, int]:
    name = f"tmp-{os.getpid()}-{secrets.token_hex(16)}"
    try:
        descriptor = os.open(name, _file_create_flags(), _PRIVATE_FILE_MODE, dir_fd=tmp_fd)
    except OSError as exc:
        raise ArtifactStoreError("could not create temporary artifact file") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ArtifactStoreError("temporary artifact file is not regular")
        return name, descriptor
    except ArtifactStoreError:
        _close_quietly(descriptor)
        _unlink_at(tmp_fd, name)
        raise
    except OSError as exc:
        _close_quietly(descriptor)
        _unlink_at(tmp_fd, name)
        raise ArtifactStoreError("could not inspect temporary artifact file") from exc


def _copy_hashed(source_fd: int, destination_fd: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    for chunk in _read_chunks(source_fd):
        hasher.update(chunk)
        _write_all(destination_fd, chunk)
        size += len(chunk)
    return f"sha256:{hasher.hexdigest()}", size


def _write_hashed(destination_fd: int, payload: bytes) -> tuple[str, int]:
    hasher = hashlib.sha256()
    hasher.update(payload)
    _write_all(destination_fd, payload)
    return f"sha256:{hasher.hexdigest()}", len(payload)


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


def _publish(
    *,
    tmp_fd: int,
    temp_name: str,
    shard_fd: int,
    object_name: str,
    digest: str,
    size: int,
) -> ArtifactRecord:
    storage_key = storage_key_for(digest)
    try:
        os.link(
            temp_name,
            object_name,
            src_dir_fd=tmp_fd,
            dst_dir_fd=shard_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        _require_matching_object(shard_fd, object_name, digest, size)
        _fsync_fd(shard_fd, reason="publish")
        return ArtifactRecord(digest=digest, size_bytes=size, storage_key=storage_key)
    except OSError as exc:
        raise ArtifactStoreError("could not publish artifact object") from exc
    _fsync_fd(shard_fd, reason="publish")
    return ArtifactRecord(digest=digest, size_bytes=size, storage_key=storage_key)


def _require_matching_object(shard_fd: int, name: str, digest: str, size: int) -> None:
    descriptor = _open_stored_object(shard_fd, name, digest, missing=ArtifactIntegrityError)
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


def _fsync_file(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise ArtifactStoreError("could not persist temporary artifact file") from exc


def _fsync_fd(descriptor: int, *, reason: str) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise ArtifactStoreError(f"could not persist directory ({reason})") from exc


def _unlink_at(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        return
    except OSError:
        return


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        return


def _close_all(descriptors: list[int]) -> None:
    while descriptors:
        _close_quietly(descriptors.pop())
