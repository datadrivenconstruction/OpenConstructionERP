"""Persisted "applied partner pack" state - survives restarts.

A single global record (single-tenant, per the partner-pack ADR). Stored as
JSON alongside the database, mirroring ``module_state.py``. This lets an admin
*apply* a pack from inside the app (the /modules Partner Packs tab) rather than
only via the ``OE_PARTNER_PACK`` env var, and lets the app reverse the apply.

Precedence used by ``discovery.get_active_pack``:
    in-app applied (this file) -> ``OE_PARTNER_PACK`` env -> none.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.module_state import _resolve_data_dir

logger = logging.getLogger(__name__)

STATE_FILENAME = "partner_pack_state.json"


def _resolve_state_dir(data_dir: Path | None = None) -> Path:
    """Resolve the directory that holds ``partner_pack_state.json``.

    Resolution order:
      1. Explicit ``data_dir`` argument (tests, callers with a known dir).
      2. The ACTIVE runtime data dir: ``OE_CLI_DATA_DIR``, exported by the
         CLI/desktop launcher (``serve --data-dir``). Each instance keeps its
         applied pack inside its own data dir, so a custom ``--data-dir``
         never inherits (or gets hijacked by) the default install's state.
      3. Legacy fallback (no CLI env, e.g. bare uvicorn): the shared
         ``module_state._resolve_data_dir`` resolution, which ends at
         ``~/.openestimate`` - unchanged for existing default installs.
    """
    if data_dir is not None:
        return data_dir
    override = os.environ.get("OE_CLI_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return _resolve_data_dir(None)


@dataclass
class AppliedPackState:
    """The single applied-pack record."""

    slug: str
    pack_version: str = ""
    # Full public manifest at apply time - lets Update diff old vs new.
    manifest_snapshot: dict[str, Any] = field(default_factory=dict)
    # Ledger of what the apply changed, so Un-apply can reverse it.
    effects: dict[str, Any] = field(default_factory=dict)
    applied_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    applied_by: str | None = None


def load_applied_state(data_dir: Path | None = None) -> AppliedPackState | None:
    """Return the applied-pack record, or None if nothing has been applied."""
    path = _resolve_state_dir(data_dir) / STATE_FILENAME
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "slug" not in raw:
            return None
        return AppliedPackState(
            slug=raw["slug"],
            pack_version=raw.get("pack_version", ""),
            manifest_snapshot=raw.get("manifest_snapshot", {}),
            effects=raw.get("effects", {}),
            applied_at=raw.get("applied_at", ""),
            applied_by=raw.get("applied_by"),
        )
    except Exception:
        logger.exception("Failed to read %s - ignoring applied pack state", path)
        return None


def save_applied_state(state: AppliedPackState, data_dir: Path | None = None) -> None:
    """Persist the applied-pack record atomically."""
    resolved = _resolve_state_dir(data_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    path = resolved / STATE_FILENAME
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        logger.info("Applied partner pack state saved: %s v%s", state.slug, state.pack_version)
    except Exception:
        logger.exception("Failed to save applied pack state to %s", path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def clear_applied_state(data_dir: Path | None = None) -> None:
    """Remove the applied-pack record (Un-apply)."""
    path = _resolve_state_dir(data_dir) / STATE_FILENAME
    try:
        path.unlink(missing_ok=True)
        logger.info("Applied partner pack state cleared.")
    except Exception:
        logger.exception("Failed to clear applied pack state at %s", path)


def get_applied_slug(data_dir: Path | None = None) -> str | None:
    """Convenience: the applied slug, or None. Used by discovery resolution."""
    s = load_applied_state(data_dir)
    return s.slug if s else None
