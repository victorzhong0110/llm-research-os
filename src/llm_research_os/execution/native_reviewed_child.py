"""Fixed, isolated-mode child entrypoint for the reviewed Python profile.

The first input frame is a start barrier: without a durably recorded parent
identity the child exits before it imports any reviewed code.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path


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
        if not module.replace(".", "_").isidentifier() or not function.isidentifier():
            return 70
        code = root / "material" / "code"
        if not code.is_dir():
            return 70
        files = document["files"]
        if type(files) is not dict or len(files) > 4096:
            return 70
        for relative, digest in files.items():
            if type(relative) is not str or type(digest) is not str:
                return 70
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or not relative.startswith("material/"):
                return 70
            candidate = root / path
            if candidate.is_symlink() or not candidate.is_file():
                return 70
            if "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
                return 70
        os.chdir(root)
        sys.path.insert(0, str(code))
        result = getattr(importlib.import_module(module), function)()
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False)
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        print(f"reviewed task failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
