"""The installation-wide switch for semantic search.

Semantic search loads a sentence-transformers model (several hundred MB of
RAM once torch is in) and opens the vector store. On a machine with little
memory headroom that load is what took the desktop backend down, so the
platform no longer does it unasked: semantic search is OFF until someone turns
it on in Settings, and every module that uses it says it is off and where the
switch is.

Weights already on disk do not count as a yes. A machine that downloaded the
model months ago and then crashed loading it is exactly the case this exists
for.

Resolution, first answer wins:

1. ``OE_SEMANTIC_SEARCH`` set to a truthy or falsy value. An operator policy:
   the UI shows the switch locked in that position.
2. ``semantic_search.json`` in the data directory, written by the Settings
   switch.
3. Off.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_SWITCH = "OE_SEMANTIC_SEARCH"
STATE_FILENAME = "semantic_search.json"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

_lock = threading.Lock()
# (path, mtime_ns, size) -> enabled. Keyed on size as well as mtime because
# Windows hands out identical mtimes for writes made close together.
_cache: tuple[str, int, int, bool] | None = None


class SemanticSearchDisabled(RuntimeError):
    """Raised by the encode path while semantic search is switched off."""

    def __init__(self) -> None:
        super().__init__("Semantic search is switched off. Turn it on in Settings to use it.")


def _env_override() -> bool | None:
    raw = os.environ.get(ENV_SWITCH, "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return None


def locked_by_env() -> bool:
    """Whether an operator fixed the switch through :data:`ENV_SWITCH`."""
    return _env_override() is not None


def _state_path() -> Path:
    from app.core.storage import resolve_data_dir

    return resolve_data_dir() / STATE_FILENAME


def _read_file() -> bool:
    global _cache
    try:
        path = _state_path()
        stat = path.stat()
    except OSError:
        return False
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _cache
    if cached is not None and cached[:3] == key:
        return cached[3]
    try:
        enabled = bool(json.loads(path.read_text(encoding="utf-8")).get("enabled", False))
    except (OSError, ValueError, AttributeError):
        logger.warning("Could not read %s; semantic search stays off", path)
        enabled = False
    _cache = (*key, enabled)
    return enabled


def semantic_search_enabled() -> bool:
    """Whether this installation may load the embedding model and vector store."""
    override = _env_override()
    if override is not None:
        return override
    return _read_file()


def set_semantic_search_enabled(enabled: bool) -> bool:
    """Persist the Settings switch and return the effective state.

    The environment override still wins, so the return value can differ from
    ``enabled`` when an operator locked the switch.
    """
    global _cache
    with _lock:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"enabled": bool(enabled)}), encoding="utf-8")
        os.replace(tmp, path)
        _cache = None
    return semantic_search_enabled()
