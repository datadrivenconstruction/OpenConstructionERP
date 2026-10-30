# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Solution packages: ready bundles of modules a company picks during onboarding.

A package is a layer over the company presets in ``onboarding_presets``: it
names the modules a kind of work needs (required and optional), the menu rows
it puts first, the dashboard widgets it shows and the demo project it seeds.
Only data lives here. Packages are worldwide; language and country data come
from the locale and the country packs, never from a package.

Installing is additive and idempotent. The first install hides every gateable
module outside the chosen packages; a later install only switches modules on,
so nothing a user already sees disappears and no data is ever deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.onboarding_presets import _ALL_FUNCTIONAL, _ALL_MODULES, _CORE_MODULES

_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


@dataclass(frozen=True)
class SolutionPackage:
    """One worldwide solution package."""

    id: str
    icon: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    menu: tuple[str, ...] = ()
    widgets: tuple[str, ...] = ()
    demo_id: str | None = None
    depends_on: tuple[str, ...] = field(default=())

    @property
    def name_key(self) -> str:
        return f"packages.{self.id}.name"

    @property
    def value_key(self) -> str:
        return f"packages.{self.id}.value"

    @property
    def audience_key(self) -> str:
        return f"packages.{self.id}.audience"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "icon": self.icon,
            "image": f"illustration:{self.id}",
            "name_key": self.name_key,
            "value_key": self.value_key,
            "audience_key": self.audience_key,
            "required": list(self.required),
            "optional": list(self.optional),
            "menu": list(self.menu),
            "widgets": list(self.widgets),
            "demo_id": self.demo_id,
            "depends_on": list(self.depends_on),
        }


# Demo ids are DEMO_TEMPLATES keys, except the supply-chain one which is seeded
# by ``solution_package_demos`` from data.
SUPPLY_CHAIN_DEMO_ID = "rebar-cage-supply-chain"

SOLUTION_PACKAGES: dict[str, SolutionPackage] = {
    p.id: p
    for p in [
        SolutionPackage(
            id="estimate_quote",
            icon="Calculator",
            required=("boq", "validation", "cost_match", "match", "estimate_rollup", "preliminaries"),
            optional=("estimate_basis", "rom_estimate", "quote_capture", "cost_benchmarks", "reporting"),
            menu=("/boq", "/costs", "/assemblies", "/cost-match", "/validation", "/reports"),
            widgets=("continue_work", "projects", "estimate_resources", "kpi", "validation_portfolio"),
            demo_id="residential-berlin",
        ),
        SolutionPackage(
            id="trades",
            icon="Hammer",
            required=("boq", "crm", "tasks", "field_time", "finance", "daily_diary"),
            optional=("service", "equipment", "quote_capture", "punchlist"),
            menu=("/crm", "/boq", "/tasks", "/field-time", "/finance", "/daily-diary"),
            widgets=("today", "continue_work", "finance_summary", "labour_cost", "inbox"),
            demo_id="residential-regensburg",
        ),
        SolutionPackage(
            id="takeoff",
            icon="Ruler",
            required=("takeoff", "dwg_takeoff", "cad", "boq", "markups"),
            optional=("drawing_compare", "plan_room", "documents"),
            menu=("/takeoff", "/dwg-takeoff", "/quantities", "/boq", "/markups"),
            widgets=("continue_work", "quick_upload", "projects", "estimate_resources"),
            demo_id="office-frankfurt",
        ),
        SolutionPackage(
            id="tender_procurement",
            icon="Gavel",
            required=("tendering", "bid_management", "rfq_bidding", "procurement", "supplier_catalogs"),
            optional=("quote_capture", "contracts", "subcontractors", "cost_benchmarks"),
            menu=("/tendering", "/bid-management", "/procurement", "/supplier-catalogs", "/quotes"),
            widgets=("continue_work", "projects", "finance_summary", "inbox", "activity"),
            demo_id="commercial-london",
            depends_on=("estimate_quote",),
        ),
        SolutionPackage(
            id="site_field",
            icon="HardHat",
            required=("daily_diary", "fieldreports", "field_diary", "inspections", "punchlist", "safety", "rfi"),
            optional=("ncr", "field_time", "site_logistics", "equipment", "hse_advanced", "tasks"),
            menu=("/daily-diary", "/field-reports", "/inspections", "/punchlist", "/safety", "/rfi"),
            widgets=("today", "on_site_now", "weather_site", "punch_quality", "inspections_quality", "latest_photos"),
            demo_id="hospital-lyon",
        ),
        SolutionPackage(
            id="project_controls",
            icon="LineChart",
            required=("schedule", "costmodel", "eac", "project_controls", "bi_dashboards", "risk", "changeorders"),
            optional=("schedule_advanced", "full_evm", "cvr", "wip_report", "reporting", "portfolio"),
            menu=("/schedule", "/5d", "/project-controls", "/risks", "/changeorders", "/bi-dashboards"),
            widgets=(
                "kpi",
                "finance_summary",
                "portfolio",
                "operations_snapshot",
                "upcoming_milestones",
                "wip_summary",
            ),
            demo_id="commercial-denver",
        ),
        SolutionPackage(
            id="subcontractor",
            icon="Handshake",
            required=("bid_management", "contracts", "variations", "finance", "payment_clock", "daily_diary"),
            optional=("claims_evidence", "changeorders", "tax_withholding", "field_time"),
            menu=("/bid-management", "/contracts", "/variations", "/payment-clock", "/finance", "/daily-diary"),
            widgets=("continue_work", "finance_summary", "today", "upcoming_milestones", "inbox"),
            demo_id="office-dublin",
            depends_on=("estimate_quote",),
        ),
        SolutionPackage(
            id="service_maintenance",
            icon="Wrench",
            required=("service", "assets", "equipment", "condition", "defects_liability", "tasks"),
            optional=("inspections", "portal", "site_sensors", "commissioning"),
            menu=("/service", "/equipment", "/condition", "/defects-liability", "/tasks"),
            widgets=("today", "inbox", "fleet_utilisation", "sensor_alerts", "guarantees_summary"),
            demo_id="data-center-melbourne",
        ),
        SolutionPackage(
            id="developer_owner",
            icon="Landmark",
            required=("property_dev", "portfolio", "funding", "cost_plan", "contracts", "reporting"),
            optional=("accommodation", "economics", "design_options", "stakeholders", "carbon"),
            menu=("/property-dev", "/portfolio", "/funding", "/contracts", "/reports"),
            widgets=("kpi", "portfolio", "finance_summary", "map", "carbon_budget", "upcoming_milestones"),
            demo_id="mixed-use-barcelona",
        ),
        SolutionPackage(
            id="real_estate_gcc",
            icon="Building2",
            required=(
                "property_dev",
                "leasing",
                "service_charges",
                "finance",
                "contacts",
                "documents",
                "projects",
                "boq",
                "costs",
            ),
            optional=("contracts", "funding", "crm", "portal", "reporting"),
            menu=("/property-dev", "/leasing", "/service-charges", "/finance", "/contacts", "/documents"),
            widgets=("kpi", "portfolio", "finance_summary", "upcoming_milestones", "activity"),
            demo_id="residential-riyadh-offplan",
        ),
        SolutionPackage(
            id="supply_chain",
            icon="Truck",
            required=("prefab", "procurement", "site_logistics", "site_inventory", "rebar_schedule"),
            optional=("supplier_catalogs", "cutting", "formwork", "inspections"),
            menu=("/prefab", "/rebar-schedule", "/procurement", "/site-logistics", "/site-inventory"),
            widgets=("today", "operations_snapshot", "on_site_now", "upcoming_milestones", "activity"),
            demo_id=SUPPLY_CHAIN_DEMO_ID,
        ),
        SolutionPackage(
            id="bim_model",
            icon="Boxes",
            required=("bim_hub", "bim_requirements", "match_elements", "cad", "boq", "clash", "coordination_hub"),
            optional=("bcf", "opencde_api", "carbon", "design_options", "bimlv"),
            menu=("/bim", "/bim/rules", "/clash", "/coordination", "/boq"),
            widgets=("bim_coverage", "continue_work", "projects", "estimate_resources", "quick_upload"),
            demo_id="office-amsterdam",
        ),
    ]
}


def get_package(package_id: str) -> SolutionPackage | None:
    """Return a package by id, or ``None``."""
    return SOLUTION_PACKAGES.get(package_id)


def list_packages() -> list[dict[str, Any]]:
    """All packages as serialisable dicts, in display order."""
    return [p.to_dict() for p in SOLUTION_PACKAGES.values()]


# ── Module graph (read from the manifests on disk) ────────────────────────────

_DEPENDS_RE = re.compile(r"depends\s*=\s*\[([^\]]*)\]")


@lru_cache(maxsize=1)
def module_dependencies() -> dict[str, tuple[str, ...]]:
    """Map every module directory to its manifest ``depends`` (as directory names)."""
    graph: dict[str, tuple[str, ...]] = {}
    for manifest in sorted(_MODULES_DIR.glob("*/manifest.py")):
        text = manifest.read_text(encoding="utf-8")
        match = _DEPENDS_RE.search(text)
        deps = re.findall(r"[\"']([^\"']+)[\"']", match.group(1)) if match else []
        graph[manifest.parent.name] = tuple(d.removeprefix("oe_") for d in deps)
    return graph


def known_modules() -> frozenset[str]:
    """Every module that really exists (has a manifest)."""
    return frozenset(module_dependencies())


@lru_cache(maxsize=1)
def gateable_modules() -> frozenset[str]:
    """Modules a package may hide: functional preset modules plus every package module.

    Core modules and platform infrastructure (file services, notifications,
    jobs) are never gated, so a package can never lock a user out of them.
    """
    mods = set(_ALL_FUNCTIONAL)
    for pkg in SOLUTION_PACKAGES.values():
        mods.update(pkg.required)
        mods.update(pkg.optional)
    return frozenset(mods - set(_CORE_MODULES))


def dependency_closure(modules: set[str] | list[str] | tuple[str, ...]) -> set[str]:
    """``modules`` plus everything they transitively depend on."""
    graph = module_dependencies()
    out: set[str] = set()
    stack = list(modules)
    while stack:
        mod = stack.pop()
        if mod in out:
            continue
        out.add(mod)
        stack.extend(graph.get(mod, ()))
    return out


def package_closure(package_ids: list[str]) -> list[str]:
    """Package ids plus the packages they build on, in registry order."""
    wanted: set[str] = set()
    stack = list(package_ids)
    while stack:
        pid = stack.pop()
        pkg = SOLUTION_PACKAGES.get(pid)
        if pkg is None or pid in wanted:
            continue
        wanted.add(pid)
        stack.extend(pkg.depends_on)
    return [pid for pid in SOLUTION_PACKAGES if pid in wanted]


def resolve_modules(package_ids: list[str], optional: list[str] | None = None) -> set[str]:
    """Modules the packages switch on: required, chosen optional, and their dependencies."""
    chosen = set(optional or [])
    mods: set[str] = set()
    for pid in package_closure(package_ids):
        pkg = SOLUTION_PACKAGES[pid]
        mods.update(pkg.required)
        mods.update(m for m in pkg.optional if m in chosen)
    return dependency_closure(mods)


def dependents_of(module: str, enabled: set[str]) -> list[str]:
    """Enabled modules that (transitively) need ``module``."""
    return sorted(m for m in enabled if m != module and module in dependency_closure([m]))


# ── Validation of the registry ────────────────────────────────────────────────


def validate_registry() -> list[str]:
    """Consistency problems in the registry; an empty list means it is sound.

    Every module id must exist on disk, every dependency of a package module
    must exist too (the closure is closed), package dependencies must name
    real packages, and no module may be both required and optional.
    """
    issues: list[str] = []
    known = known_modules()
    graph = module_dependencies()
    for pkg in SOLUTION_PACKAGES.values():
        for mod in (*pkg.required, *pkg.optional):
            if mod not in known:
                issues.append(f"{pkg.id}: unknown module '{mod}'")
        for mod in set(pkg.required) & set(pkg.optional):
            issues.append(f"{pkg.id}: module '{mod}' is both required and optional")
        for dep in pkg.depends_on:
            if dep not in SOLUTION_PACKAGES:
                issues.append(f"{pkg.id}: unknown package dependency '{dep}'")
        for mod in dependency_closure([*pkg.required, *pkg.optional]):
            for dep in graph.get(mod, ()):
                if dep not in known:
                    issues.append(f"{pkg.id}: module '{mod}' depends on missing '{dep}'")
        if not pkg.required:
            issues.append(f"{pkg.id}: no required modules")
    return issues


# ── Per-tenant state (stored in the user's metadata, the tenant today) ───────

STATE_KEY = "solution_packages"


def read_state(metadata: dict[str, Any]) -> dict[str, Any]:
    """The stored package state, normalised."""
    raw = metadata.get(STATE_KEY) or {}
    return {
        "installed": [p for p in raw.get("installed", []) if p in SOLUTION_PACKAGES],
        "optional": list(raw.get("optional", [])),
        "modules": {k: bool(v) for k, v in (raw.get("modules") or {}).items()},
        "focus_pack": raw.get("focus_pack") or None,
    }


def enabled_set(state: dict[str, Any]) -> set[str]:
    """Gateable modules switched on in ``state``."""
    return {k for k, v in state["modules"].items() if v}


def _sync_preferences(metadata: dict[str, Any], modules: dict[str, bool]) -> None:
    prefs = dict(metadata.get("module_preferences") or {})
    for key, on in modules.items():
        if key in _ALL_MODULES:
            prefs[key] = on
    for key in _CORE_MODULES:
        prefs[key] = True
    metadata["module_preferences"] = prefs


def install(
    metadata: dict[str, Any],
    package_ids: list[str],
    optional: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Install packages into ``metadata`` (returns a new dict) and the newly added package ids.

    Idempotent and additive: re-installing changes nothing, and installing a
    package later only switches modules on.
    """
    unknown = [p for p in package_ids if p not in SOLUTION_PACKAGES]
    if unknown:
        raise ValueError(f"unknown package(s): {', '.join(unknown)}")
    metadata = dict(metadata)
    state = read_state(metadata)
    first = not state["installed"]
    installed = package_closure([*state["installed"], *package_ids])
    added = [p for p in installed if p not in state["installed"]]
    chosen_optional = sorted(set(state["optional"]) | set(optional or []))
    switch_on = resolve_modules(installed, chosen_optional)

    modules = dict(state["modules"])
    if first:
        modules = dict.fromkeys(gateable_modules(), False)
    for mod in switch_on:
        if mod in gateable_modules():
            modules[mod] = True

    metadata[STATE_KEY] = {
        "installed": installed,
        "optional": chosen_optional,
        "modules": modules,
        # The first install focuses the menu on it; /packs/focus then explains what was hidden.
        "focus_pack": f"package:{installed[0]}" if first else state["focus_pack"],
    }
    _sync_preferences(metadata, modules)
    return metadata, added


def remove(metadata: dict[str, Any], package_id: str) -> tuple[dict[str, Any], list[str]]:
    """Remove an installed package; returns new metadata and the modules it hides.

    Only modules no remaining package (or its optional picks) needs are
    hidden, and nothing is deleted. Packages that build on the removed one are
    removed with it.
    """
    metadata = dict(metadata)
    state = read_state(metadata)
    if package_id not in state["installed"]:
        raise ValueError(f"package '{package_id}' is not installed")
    gone = {p for p in state["installed"] if p == package_id or package_id in package_closure([p])}
    remaining = [p for p in state["installed"] if p not in gone]
    still_needed = resolve_modules(remaining, state["optional"])
    was_needed = resolve_modules(sorted(gone), state["optional"])
    modules = dict(state["modules"])
    hidden = sorted(m for m in was_needed - still_needed if m in gateable_modules() and modules.get(m) is not False)
    for mod in hidden:
        modules[mod] = False
    metadata[STATE_KEY] = {**state, "installed": remaining, "modules": modules}
    _sync_preferences(metadata, modules)
    return metadata, hidden


def set_module(
    metadata: dict[str, Any],
    module: str,
    enabled: bool,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Switch one module on (with its dependencies) or off.

    Returns the new metadata and the list of affected modules: dependencies
    switched on, or the enabled dependents that block (``force=False``) or
    are switched off with it (``force=True``). A blocked change returns the
    metadata unchanged.
    """
    if module not in gateable_modules():
        raise ValueError(f"module '{module}' cannot be switched")
    metadata = dict(metadata)
    state = read_state(metadata)
    modules = dict(state["modules"]) or dict.fromkeys(gateable_modules(), True)
    current = {k for k, v in modules.items() if v}
    if enabled:
        affected = sorted(m for m in dependency_closure([module]) if m in gateable_modules() and m not in current)
        for mod in [module, *affected]:
            modules[mod] = True
    else:
        affected = dependents_of(module, current)
        if affected and not force:
            return metadata, affected
        for mod in [module, *affected]:
            modules[mod] = False
    metadata[STATE_KEY] = {**state, "modules": modules}
    _sync_preferences(metadata, modules)
    return metadata, affected


def is_blocked(metadata: dict[str, Any] | None, module: str) -> bool:
    """Whether the tenant's packages hide ``module`` (fail-open when no packages)."""
    if not metadata:
        return False
    raw = metadata.get(STATE_KEY) or {}
    if not raw.get("modules"):
        return False
    return raw["modules"].get(module) is False
