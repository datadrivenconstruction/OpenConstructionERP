# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition scales: shipped, carried by the active pack, or defined per project.

A scale is data, never code. It lists its levels best first (level 1 is the
best condition), a display label and colour per level, the maintenance action a
level calls for, and the level from which an action is required. The core ships
one neutral six-level scale. A country pack that follows a national condition
grading names its scale files under ``condition_scales`` in its manifest, the
same mechanism code lists use, and the scale appears here with no code change.
A project can also define its own scale, stored by this module.

Precedence mirrors code lists: a pack cannot replace a shipped key, and a
project scale cannot shadow either.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.condition.planning import ACTION_TYPES

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SCALE_KEY",
    "SOURCE_BUILTIN",
    "SOURCE_CUSTOM",
    "SOURCE_PACK",
    "ScaleError",
    "builtin_scales",
    "pack_scales",
    "reset_cache",
    "validate_scale",
]

DEFAULT_SCALE_KEY = "default_6"
SOURCE_BUILTIN = "builtin"
SOURCE_PACK = "pack"
SOURCE_CUSTOM = "custom"

_DATA_DIR = Path(__file__).resolve().parent / "data"
_MIN_LEVELS = 2
_MAX_LEVELS = 10


class ScaleError(ValueError):
    """A scale document that cannot be used, with every problem found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_scale(doc: Any) -> dict[str, Any]:
    """Check a scale document and return a clean copy.

    Levels must be the integers 1..N with N between 2 and 10, each with a
    label; an action, when given, must name a known type and non-negative
    year counts; ``action_threshold`` must be one of the levels.

    Raises:
        ScaleError: listing every problem, not only the first.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        raise ScaleError(["scale must be an object"])
    key = str(doc.get("key") or "").strip()
    if not key or len(key) > 60:
        problems.append("key is required (at most 60 characters)")
    raw_levels = doc.get("levels")
    levels: list[dict[str, Any]] = []
    if not isinstance(raw_levels, list) or not (_MIN_LEVELS <= len(raw_levels) <= _MAX_LEVELS):
        problems.append(f"levels must list {_MIN_LEVELS} to {_MAX_LEVELS} entries")
        raw_levels = raw_levels if isinstance(raw_levels, list) else []
    for idx, raw in enumerate(raw_levels, start=1):
        if not isinstance(raw, dict):
            problems.append(f"level {idx} must be an object")
            continue
        try:
            number = int(raw.get("level"))
        except (TypeError, ValueError):
            number = -1
        if number != idx:
            problems.append(f"level {idx} must carry level={idx} (levels are 1..N, best first)")
        label = str(raw.get("label") or "").strip()
        if not label:
            problems.append(f"level {idx} needs a label")
        action = raw.get("action")
        clean_action = None
        if action is not None:
            if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
                problems.append(f"level {idx}: action type must be one of {', '.join(ACTION_TYPES)}")
            else:
                clean_action = {"type": action["type"], "label": str(action.get("label") or action["type"])[:120]}
                for field, low in (("within_years", 0), ("interval_years", 1), ("priority", 1)):
                    if action.get(field) in (None, ""):
                        continue
                    try:
                        value = int(action[field])
                    except (TypeError, ValueError):
                        value = low - 1
                    if value < low:
                        problems.append(f"level {idx}: action {field} must be >= {low}")
                    clean_action[field] = value
        levels.append(
            {
                "level": idx,
                "label": label[:80],
                "label_key": str(raw.get("label_key") or "")[:120] or None,
                "description": str(raw.get("description") or "")[:500] or None,
                "color": str(raw.get("color") or "")[:20] or None,
                "action": clean_action,
            }
        )
    threshold = doc.get("action_threshold")
    if threshold is not None:
        try:
            threshold_i = int(threshold)
        except (TypeError, ValueError):
            threshold_i = 0
        if not 1 <= threshold_i <= max(1, len(levels)):
            problems.append("action_threshold must be one of the levels")
    else:
        threshold_i = max(1, (len(levels) + 1) // 2 + 1)
    if problems:
        raise ScaleError(problems)
    return {
        "key": key,
        "name": str(doc.get("name") or key)[:120],
        "description": str(doc.get("description") or "")[:500] or None,
        "action_threshold": threshold_i,
        "levels": levels,
    }


@lru_cache(maxsize=1)
def builtin_scales() -> tuple[dict[str, Any], ...]:
    """Scales shipped with the core, read once per process."""
    out: list[dict[str, Any]] = []
    for path in sorted(_DATA_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("kind") != "condition_scale":
                continue
            out.append({**validate_scale(doc), "source": SOURCE_BUILTIN, "pack_slug": None})
        except (OSError, ValueError) as exc:
            logger.error("Shipped condition scale %s cannot be read: %s", path.name, exc)
    return tuple(out)


def pack_scales() -> tuple[dict[str, Any], ...]:
    """Scales the active pack names under ``condition_scales`` in its manifest."""
    try:
        from app.core.partner_pack.discovery import get_active_pack, read_pack_file
    except ImportError:  # pragma: no cover - the pack system is part of the core
        return ()
    pack = get_active_pack()
    if pack is None:
        return ()
    out: list[dict[str, Any]] = []
    for rel in getattr(pack, "condition_scales", None) or []:
        raw = read_pack_file(pack.slug, rel)
        if raw is None:
            logger.warning("Pack %s names condition scale %s but does not carry it", pack.slug, rel)
            continue
        try:
            out.append(
                {**validate_scale(json.loads(raw.decode("utf-8"))), "source": SOURCE_PACK, "pack_slug": pack.slug}
            )
        except (UnicodeDecodeError, ValueError) as exc:
            logger.warning("Pack %s condition scale %s cannot be read: %s", pack.slug, rel, exc)
    return tuple(out)


def reset_cache() -> None:
    """Forget the shipped scales read so far (tests)."""
    builtin_scales.cache_clear()
