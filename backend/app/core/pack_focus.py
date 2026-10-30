# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pack focus: after installing a pack, show only the modules it works with.

Every pack in the catalogue (country, industry, partner, showcase, and the
solution packages) resolves to a module list. A manifest that names its
``default_modules`` gets exactly those; one that names none gets a fallback by
pack type. Focusing hides every other gateable module through the same tenant
state the solution packages use, so nothing is uninstalled and no data is
touched; one module can be shown again with ``solution_packages.set_module`` and
``show_all`` reverses the whole focus.
"""

from __future__ import annotations

from typing import Any

from app.core import solution_packages as sp

# Prefix that names a solution package in the pack slug space.
PACKAGE_PREFIX = "package:"

_ESTIMATING = (
    "boq",
    "validation",
    "cost_match",
    "match",
    "tendering",
    "bid_management",
    "procurement",
    "contracts",
    "variations",
    "changeorders",
    "schedule",
    "finance",
    "reporting",
    "documents",
    "daily_diary",
    "rfi",
)

# Fallback when a manifest declares no modules: what a firm of that kind of
# pack opens first. Only modules that exist on disk survive ``pack_modules``.
FALLBACK_BY_TYPE: dict[str, tuple[str, ...]] = {
    "country": _ESTIMATING,
    "industry": (*_ESTIMATING, "inspections", "punchlist", "safety", "tasks", "takeoff"),
    "partner": (
        "boq",
        "validation",
        "cost_match",
        "tendering",
        "procurement",
        "supplier_catalogs",
        "documents",
        "reporting",
    ),
    "showcase": (*_ESTIMATING, "takeoff", "cad", "bim_hub", "inspections", "punchlist"),
}


def _strip(mod: str) -> str:
    return mod.removeprefix("oe_")


def pack_modules(manifest: Any) -> tuple[list[str], str]:
    """Modules a pack turns on and where the list came from (``manifest`` or ``fallback``)."""
    known = sp.known_modules()
    declared = [_strip(m) for m in (getattr(manifest, "default_modules", None) or [])]
    declared = [m for m in declared if m in known]
    source = "manifest" if declared else "fallback"
    base = declared or list(FALLBACK_BY_TYPE.get(manifest.type, FALLBACK_BY_TYPE["country"]))
    # Core and infrastructure modules are always on, so only menu-gated ones are listed.
    shown = sp.gateable_modules() & known
    return sorted(m for m in sp.dependency_closure(base) if m in shown), source


def _package_preview(package_id: str) -> dict[str, Any] | None:
    pkg = sp.get_package(package_id)
    if pkg is None:
        return None
    mods = sorted(m for m in sp.resolve_modules([pkg.id]) if m in sp.gateable_modules() & sp.known_modules())
    return {
        "slug": f"{PACKAGE_PREFIX}{pkg.id}",
        "name": pkg.id,
        "name_key": pkg.name_key,
        "type": "package",
        "source": "manifest",
        "modules": mods,
        "demo_template_ids": [pkg.demo_id] if pkg.demo_id else [],
        "rule_sets": [],
        "standard": None,
        "cwicr_regions": [],
        "currency": None,
        "menu": list(pkg.menu),
    }


def preview(slug: str) -> dict[str, Any] | None:
    """What focusing on ``slug`` turns on, plus the facts the guided start needs; ``None`` if unknown."""
    if slug.startswith(PACKAGE_PREFIX):
        out = _package_preview(slug.removeprefix(PACKAGE_PREFIX))
    else:
        from app.core.partner_pack.discovery import get_pack_by_slug

        manifest = get_pack_by_slug(slug)
        if manifest is None:
            return None
        mods, source = pack_modules(manifest)
        meta = manifest.metadata or {}
        out = {
            "slug": manifest.slug,
            "name": manifest.partner_name,
            "name_key": None,
            "type": manifest.type,
            "source": source,
            "modules": mods,
            "demo_template_ids": list(manifest.demo_template_ids or []),
            "rule_sets": list(manifest.validation_rule_sets or []),
            "standard": meta.get("classification_standard"),
            "cwicr_regions": list(manifest.cwicr_regions or []),
            "currency": manifest.default_currency,
            "menu": [],
        }
    if out is None:
        return None
    gateable = sp.gateable_modules() & sp.known_modules()
    out["hidden"] = sorted(gateable - set(out["modules"]))
    return out


def focus(metadata: dict[str, Any], slug: str, modules: list[str]) -> dict[str, Any]:
    """Show only ``modules`` (gateable ones) and remember the pack; returns new metadata."""
    metadata = dict(metadata)
    state = sp.read_state(metadata)
    wanted = sp.dependency_closure(modules)
    states = {m: m in wanted for m in sp.gateable_modules()}
    metadata[sp.STATE_KEY] = {**state, "modules": states, "focus_pack": slug}
    sp._sync_preferences(metadata, states)
    return metadata


def show_all(metadata: dict[str, Any]) -> dict[str, Any]:
    """Show every module again and forget the focus; data was never touched."""
    metadata = dict(metadata)
    state = sp.read_state(metadata)
    states = dict.fromkeys(sp.gateable_modules(), True)
    metadata[sp.STATE_KEY] = {**state, "modules": states, "focus_pack": None}
    sp._sync_preferences(metadata, states)
    return metadata


def validate_packs(manifests: list[Any]) -> list[str]:
    """Problems that would leave a pack without a usable module list; empty means sound."""
    known = sp.known_modules()
    issues: list[str] = []
    for m in manifests:
        mods, _ = pack_modules(m)
        if not mods:
            issues.append(f"{m.slug}: resolves to no modules")
        issues.extend(f"{m.slug}: unknown module '{x}'" for x in mods if x not in known)
    for pid in sp.SOLUTION_PACKAGES:
        p = _package_preview(pid)
        if not p or not p["modules"]:
            issues.append(f"{PACKAGE_PREFIX}{pid}: resolves to no modules")
    for kind, mods in FALLBACK_BY_TYPE.items():
        issues.extend(f"fallback {kind}: unknown module '{x}'" for x in mods if x not in known)
    return issues
