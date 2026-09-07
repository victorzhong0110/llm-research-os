"""Load weights on CPU. PyTorch 2.14 ``device_map=mps`` deadlocks Metal copies.

The HuggingFace Trainer on this host already uses ``args.device == mps``.
Returning None from Swift's default device map lets ``from_pretrained``
finish on CPU; the Trainer then calls ``model.to("mps")``.

Patch both ``swift.model.utils`` and ``swift.model.register``: register
binds ``get_default_device_map`` by name at import time.
"""

from __future__ import annotations


def _patch_default_device_map() -> None:
    try:
        import swift.model.register as register
        import swift.model.utils as utils
    except ImportError:
        return

    original = utils.get_default_device_map

    def patched() -> object:
        mapped = original()
        if type(mapped) is str and mapped.startswith("mps"):
            return None
        return mapped

    utils.get_default_device_map = patched
    register.get_default_device_map = patched


_patch_default_device_map()
