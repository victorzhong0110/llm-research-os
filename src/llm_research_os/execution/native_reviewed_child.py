"""Fixed, isolated-mode child entrypoint for the reviewed Python profile.

The first input frame is a start barrier: without a durably recorded parent
identity the child exits before it imports any reviewed code.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence


class _FrozenSourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import reviewed modules from the bytes checked at the start barrier."""

    def __init__(self, sources: dict[str, bytes], packages: set[str]) -> None:
        self.sources = sources
        self.packages = packages

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname not in self.sources and fullname not in self.packages:
            return None
        spec = importlib.machinery.ModuleSpec(fullname, self, is_package=fullname in self.packages)
        if fullname in self.packages:
            spec.submodule_search_locations = []
        return spec

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        name = module.__name__
        source = self.sources.get(name)
        if source is not None:
            exec(  # noqa: S102 - execution of verified reviewed bytes is the runner's purpose
                compile(source, f"<reviewed:{name}>", "exec"), module.__dict__
            )


def _verified_bytes(root: Path, relative: str) -> bytes:
    """Read a single file without following any workspace symlink."""

    parts = Path(relative).parts
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            return stream.read()
    finally:
        os.close(fd)


def main() -> int:
    frame = sys.stdin.buffer.readline(16_385)
    if len(frame) > 16_384 or not frame.endswith(b"\n"):
        return 70
    try:
        document = json.loads(frame)
        if type(document) is not dict or set(document) != {"root", "entrypoint", "files"}:
            return 70
        root = Path(document["root"]).resolve(strict=True)
        module, function = document["entrypoint"].split(":", 1)
        if not all(part.isidentifier() for part in module.split(".")) or not all(
            part.isidentifier() for part in function.split(".")
        ):
            return 70
        code = root / "material" / "code"
        if not code.is_dir():
            return 70
        files = document["files"]
        if type(files) is not dict or len(files) > 4096:
            return 70
        sources: dict[str, bytes] = {}
        packages: set[str] = set()
        for relative, digest in files.items():
            if type(relative) is not str or type(digest) is not str:
                return 70
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not relative.startswith("material/"):
                return 70
            try:
                payload = _verified_bytes(root, relative)
            except OSError:
                return 70
            if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
                return 70
            if path.parts[:2] == ("material", "code") and relative.endswith(".py"):
                components = list(path.parts[2:])
                if components[-1] == "__init__.py":
                    components.pop()
                else:
                    components[-1] = components[-1][:-3]
                if not components or not all(part.isidentifier() for part in components):
                    return 70
                name = ".".join(components)
                sources[name] = payload
                for index in range(1, len(components)):
                    packages.add(".".join(components[:index]))
                if relative.endswith("/__init__.py"):
                    packages.add(name)
        if module not in sources or any(name in sys.modules for name in sources.keys() | packages):
            return 70
        os.chdir(root)
        sys.meta_path.insert(0, _FrozenSourceFinder(sources, packages))
        entry: Any = importlib.import_module(module)
        for attribute in function.split("."):
            entry = getattr(entry, attribute)
        result = entry()
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False)
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        print(f"reviewed task failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
