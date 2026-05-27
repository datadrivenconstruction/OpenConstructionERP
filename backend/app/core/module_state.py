"""‌⁠‍Persistent module state -- tracks enabled/disabled status across restarts.

Stores state in a JSON file alongside the database.  Core modules cannot be disabled.

File location resolution:
1. Explicit ``data_dir`` argument
2. Directory containing the SQLite database (from ``DATABASE_URL``)
3. ``~/.openestimate/``
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILENAME = "module_states.json"


@dataclass
class ModuleState:
    """‌⁠‍Persisted state for a single module."""

    name: str
    enabled: bool = True
    installed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    disabled_at: str | None = None


def _resolve_data_dir(data_dir: Path | None = None) -> Path:
    """‌⁠‍Determine the directory where ``module_states.json`` should live."""
    if data_dir is not None:
        return data_dir

    # Try to derive from DATABASE_URL (SQLite path)
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if "sqlite" in db_url:
        # sqlite+aiosqlite:///./openestimate.db  or  sqlite+aiosqlite:////abs/path.db
        parts = db_url.split("///", 1)
        if len(parts) == 2:
            db_path = Path(parts[1]).resolve()
            if db_path.parent.exists():
                return db_path.parent

    # Fallback
    fallback = Path.home() / ".openestimate"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def load_module_states(data_dir: Path | None = None) -> dict[str, ModuleState]:
    """Load persisted module states from disk.

    Returns an empty dict if the file does not exist yet.
    """
    resolved = _resolve_data_dir(data_dir)
    path = resolved / STATE_FILENAME

    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        states: dict[str, ModuleState] = {}
        for name, data in raw.items():
            if isinstance(data, dict):
                states[name] = ModuleState(
                    name=data.get("name", name),
                    enabled=data.get("enabled", True),
                    installed_at=data.get("installed_at", ""),
                    disabled_at=data.get("disabled_at"),
                )
            else:
                # Legacy format: simple bool
                states[name] = ModuleState(name=name, enabled=bool(data))
        return states
    except Exception:
        logger.exception("Failed to read %s — starting with empty state", path)
        return {}


def save_module_states(
    states: dict[str, ModuleState],
    data_dir: Path | None = None,
) -> None:
    """Persist module states to disk as JSON."""
    resolved = _resolve_data_dir(data_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / STATE_FILENAME

    payload = {name: asdict(state) for name, state in states.items()}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        logger.debug("Module states saved to %s (%d entries)", path, len(states))
    except Exception:
        logger.exception("Failed to save module states to %s", path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def get_module_state(
    module_name: str,
    data_dir: Path | None = None,
) -> ModuleState:
    """Return persisted state for a single module, defaulting to enabled."""
    states = load_module_states(data_dir)
    return states.get(module_name, ModuleState(name=module_name, enabled=True))


def set_module_enabled(
    module_name: str,
    enabled: bool,
    *,
    core_modules: set[str] | None = None,
    data_dir: Path | None = None,
) -> ModuleState:
    """Enable or disable a module and persist the change.

    Raises:
        ValueError: If ``module_name`` is a core module (cannot be disabled).
    """
    if core_modules and module_name in core_modules:
        raise ValueError(f"Module '{module_name}' is a core module and cannot be disabled.")

    states = load_module_states(data_dir)
    now = datetime.now(UTC).isoformat()

    if module_name in states:
        state = states[module_name]
        state.enabled = enabled
        if not enabled:
            state.disabled_at = now
        else:
            state.disabled_at = None
    else:
        state = ModuleState(
            name=module_name,
            enabled=enabled,
            installed_at=now,
            disabled_at=now if not enabled else None,
        )
        states[module_name] = state

    save_module_states(states, data_dir)
    return state
