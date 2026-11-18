# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export profiles: one certified payroll week, written in the format an agency accepts.

The week is rendered once by :func:`wh347.render_form`'s inputs (the header and
the worker lines). A profile turns that into a file. The core ships the
neutral CSV; a regional pack contributes its agency's format from a module named
``payroll_export`` beside its config, exposing ``PAYROLL_EXPORT_PROFILES``.

A profile never invents a value the agency checks. Anything the week does not
hold (a registration number, a worker's address, a tax id) is left empty and
named in ``missing``, so the person filing sees the gap before the portal does.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.certified_payroll.wh347 import render_csv, render_form

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """The rendered file and the fields the person filing still has to supply."""

    content: str
    missing: list[str] = field(default_factory=list)


#: ``render(header, lines, extra) -> ExportResult``; ``extra`` carries agency ids typed at export time.
Renderer = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, str]], ExportResult]


@dataclass(frozen=True)
class ExportProfile:
    """One agency file format."""

    code: str
    label: str
    media_type: str
    extension: str
    render: Renderer
    #: Agency ids the export screen asks for, e.g. ``("contractor_registration",)``.
    extra_fields: tuple[str, ...] = ()
    #: Pack module that contributes it; ``None`` for the core profile.
    backend_module: str | None = None


def _wh347_csv(header: dict[str, Any], lines: list[dict[str, Any]], extra: dict[str, str]) -> ExportResult:
    return ExportResult(content=render_csv(render_form(header, lines)))


CORE_PROFILES: tuple[ExportProfile, ...] = (
    ExportProfile(
        code="us_wh347_csv",
        label="Weekly payroll form (CSV)",
        media_type="text/csv",
        extension="csv",
        render=_wh347_csv,
    ),
)


def _pack_profiles() -> list[ExportProfile]:
    from app.core.regional_packs import PACK_CONFIG_MODULES

    found: list[ExportProfile] = []
    for dotted in PACK_CONFIG_MODULES:
        package = dotted.rsplit(".", 1)[0]
        target = f"{package}.payroll_export"
        try:
            if importlib.util.find_spec(target) is None:
                continue
            module = importlib.import_module(target)
        except Exception:  # noqa: BLE001 - one broken pack must not hide the others
            logger.warning("export_profiles: cannot import %s", target, exc_info=True)
            continue
        found.extend(getattr(module, "PAYROLL_EXPORT_PROFILES", ()))
    return found


def _loaded(profile: ExportProfile) -> bool:
    if profile.backend_module is None:
        return True
    try:
        from app.core.module_loader import module_loader

        manifests = getattr(module_loader, "_manifests", {}) or {}
    except Exception:  # noqa: BLE001
        return True
    return not manifests or profile.backend_module in manifests


def available_profiles(codes: list[str] | None = None) -> list[ExportProfile]:
    """Profiles of loaded packs, in ``codes`` order when given (a jurisdiction's list)."""
    every = {p.code: p for p in (*CORE_PROFILES, *_pack_profiles()) if _loaded(p)}
    if codes is None:
        return list(every.values())
    return [every[c] for c in codes if c in every]


def get_profile(code: str) -> ExportProfile | None:
    """The profile called ``code`` when a loaded pack (or the core) provides it."""
    return next((p for p in available_profiles() if p.code == code), None)


def split_name(name: str) -> tuple[str, str, str]:
    """``("first", "middle", "last")`` from a display name; the last word is the surname."""
    parts = [p for p in str(name or "").replace(",", " ").split() if p]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    return parts[0], " ".join(parts[1:-1]), parts[-1]


__all__ = [
    "CORE_PROFILES",
    "ExportProfile",
    "ExportResult",
    "available_profiles",
    "get_profile",
    "split_name",
]
