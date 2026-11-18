# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of jurisdiction rule tables contributed by regional packs.

The neutral engines (the notice calendar in ``deadlines``, the retention limits
in ``contracts``, the tax treatment engine and the statutory checks) know no
law. A regional pack contributes the law as data: its ``config`` module exports
``JURISDICTION_RULES``, one dict per subdivision or country, keyed by an ISO
3166 code such as ``US-CA``.

Only packs whose backend module is loaded contribute. A tenant whose market
profile does not install the California pack therefore gets no California table,
and every surface built on this registry shows nothing for it.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

#: Keys every jurisdiction table must carry.
REQUIRED_KEYS: tuple[str, ...] = ("code", "name", "country", "backend_module")


def _config_modules() -> tuple[str, ...]:
    from app.core.regional_packs import PACK_CONFIG_MODULES

    return PACK_CONFIG_MODULES


@lru_cache(maxsize=1)
def _all_tables() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for dotted in _config_modules():
        try:
            module = importlib.import_module(dotted)
        except Exception:  # noqa: BLE001 - one broken pack must not hide the others
            logger.warning("jurisdiction_rules: cannot import %s", dotted, exc_info=True)
            continue
        tables = getattr(module, "JURISDICTION_RULES", None)
        if tables is None:
            continue
        for table in tables if isinstance(tables, list) else [tables]:
            missing = [key for key in REQUIRED_KEYS if not table.get(key)]
            if missing:
                logger.warning("jurisdiction_rules: %s table lacks %s", dotted, missing)
                continue
            out[str(table["code"]).upper()] = table
    return out


def _module_loaded(name: str) -> bool:
    try:
        from app.core.module_loader import module_loader

        manifests = getattr(module_loader, "_manifests", {}) or {}
    except Exception:  # noqa: BLE001
        return True
    # No manifests means no application boot (unit tests, scripts): every pack counts.
    return not manifests or name in manifests


def all_jurisdictions() -> dict[str, dict[str, Any]]:
    """Every table a loaded pack contributes, keyed by upper-case code."""
    return {code: t for code, t in _all_tables().items() if _module_loaded(str(t["backend_module"]))}


def get_jurisdiction(code: str | None) -> dict[str, Any] | None:
    """The table for ``code`` (``US-CA``), or ``None`` when no loaded pack carries it."""
    if not code:
        return None
    return all_jurisdictions().get(code.strip().upper())


def clear_cache() -> None:
    """Forget the scanned tables (tests that patch a pack)."""
    _all_tables.cache_clear()


__all__ = ["REQUIRED_KEYS", "all_jurisdictions", "clear_cache", "get_jurisdiction"]
