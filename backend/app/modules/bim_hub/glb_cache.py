# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Convert a given DAE payload to GLB once per process.

The demo seed places the same two sample models into every showcase project,
and each copy used to go through a full trimesh DAE->GLB conversion: 26
conversions on one first start for two distinct inputs, each loading a 14 MB
mesh graph into memory. The output depends only on the input bytes, so a small
content-keyed cache returns the earlier result, and a per-key lock makes a
second caller wait for the first conversion rather than start its own.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Callable

# A handful of recent results. The GLBs are a few MB each and the repeats come
# in a burst during the seed, so this bounds memory without losing the reuse.
_MAX_ENTRIES = 4

_results: OrderedDict[str, bytes | None] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def _key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def convert_dae_once(data: bytes, convert: Callable[[bytes], bytes | None]) -> bytes | None:
    """Return ``convert(data)`` run in a worker thread, reusing a prior result.

    A failed conversion (``None``) is cached too: the same bytes fail the same
    way, and retrying them per project is the cost this exists to remove.
    Exceptions are not cached and propagate to the caller.
    """
    key = _key(data)
    if key in _results:
        _results.move_to_end(key)
        return _results[key]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
        try:
            result = await asyncio.to_thread(convert, data)
        finally:
            _locks.pop(key, None)
        _results[key] = result
        while len(_results) > _MAX_ENTRIES:
            _results.popitem(last=False)
        return result


def clear() -> None:
    """Drop every cached result. For tests."""
    _results.clear()
    _locks.clear()
