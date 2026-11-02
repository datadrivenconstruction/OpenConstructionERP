# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Market scope: which country-specific things a tenant should see.

A tenant's *market profile* names its primary market, any extra markets, the
company type and the standards it works to. Modules, partner packs and rule
sets carry a ``markets`` tag (ISO 3166-1 alpha-2 codes, ``"*"`` for every
market); the resolver intersects the two so a German contractor never sees a
UK, US or Saudi row, and a Saudi one sees its GCC things.

The profile is stored next to the solution package state in the tenant's
metadata (the signed-in owner today, see :mod:`app.core.tenant_scope`). A
tenant that never saved one gets a profile derived from what it already uses:
the applied country pack, installed regional packages and its projects'
countries. Tagged modules it explicitly switched on stay visible, so an
upgrade never hides anything in use. With nothing to go on the scope is every
market, which is the behaviour before market scoping existed.

Country values live in the packs (module manifests, partner pack manifests,
``regional_packs`` configs, ``regional_solution_packages.json``), never here.
"""

from __future__ import annotations

import importlib
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Metadata key the stored profile lives under.
PROFILE_KEY = "market_profile"

#: The tag meaning "every market".
ALL_MARKETS = "*"

_SUPRANATIONAL_FILE = Path(__file__).resolve().parent / "country_data" / "supranational_markets.json"


@lru_cache(maxsize=1)
def supranational_markets() -> dict[str, frozenset[str]]:
    """Supranational market -> member states, from ``country_data`` (read once)."""
    import json

    try:
        raw = json.loads(_SUPRANATIONAL_FILE.read_text(encoding="utf-8")).get("markets") or {}
    except (OSError, ValueError):
        logger.warning("market: %s unreadable, no supranational markets", _SUPRANATIONAL_FILE.name)
        return {}
    return {_code(k): frozenset(_code(c) for c in v) for k, v in raw.items() if isinstance(v, list)}


UNITS_SYSTEMS: tuple[str, ...] = ("metric", "imperial", "both")

#: Rule sets every market runs.
UNIVERSAL_RULE_SETS: tuple[str, ...] = ("boq_quality",)

#: A partner pack ``metadata["country"]`` value meaning "spans regions".
_CROSS_REGION = "XX"


def _code(value: Any) -> str:
    return str(value or "").strip().upper()


# ── Tags ────────────────────────────────────────────────────────────────────


def normalise_tags(tags: Iterable[Any] | None) -> tuple[str, ...]:
    """Upper-cased, de-duplicated tags; empty or missing means every market."""
    out: list[str] = []
    for tag in tags or ():
        code = _code(tag)
        if code and code not in out:
            out.append(code)
    return tuple(out) or (ALL_MARKETS,)


def expand_markets(markets: Iterable[str]) -> frozenset[str]:
    """Active market codes plus the supranational markets they belong to."""
    codes = {_code(m) for m in markets if _code(m)}
    for market, members in supranational_markets().items():
        if codes & members:
            codes.add(market)
    return frozenset(codes)


def is_visible(tags: Iterable[Any] | None, markets: Iterable[str]) -> bool:
    """Whether an artefact tagged ``tags`` shows for the active ``markets``.

    ``"*"`` on either side matches everything; a tagged artefact with no
    overlap fails closed.
    """
    wanted = normalise_tags(tags)
    active = expand_markets(markets)
    if ALL_MARKETS in wanted or ALL_MARKETS in active:
        return True
    return bool(active & set(wanted))


# ── Tagged artefacts ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _scanned_module_markets() -> dict[str, tuple[str, ...]]:
    modules_dir = Path(__file__).resolve().parent.parent / "modules"
    out: dict[str, tuple[str, ...]] = {}
    for manifest_file in sorted(modules_dir.glob("*/manifest.py")):
        try:
            mod = importlib.import_module(f"app.modules.{manifest_file.parent.name}.manifest")
        except Exception:  # noqa: BLE001 - one broken manifest must not hide every other
            logger.debug("market_scope: cannot import %s", manifest_file, exc_info=True)
            continue
        manifest = getattr(mod, "manifest", None)
        if manifest is not None:
            out[manifest.name] = normalise_tags(getattr(manifest, "markets", None))
    return out


def module_markets() -> dict[str, tuple[str, ...]]:
    """``{"oe_uk_pack": ("GB",), ...}`` for every module, from the manifests."""
    from app.core.module_loader import module_loader

    manifests = getattr(module_loader, "_manifests", {}) or {}
    if manifests:
        return {name: normalise_tags(getattr(m, "markets", None)) for name, m in manifests.items()}
    return _scanned_module_markets()


def pack_markets(manifest: Any) -> tuple[str, ...]:
    """Markets of a partner pack, from its ``metadata["country"]``."""
    country = _code((getattr(manifest, "metadata", None) or {}).get("country"))
    if not country or country == _CROSS_REGION:
        return (ALL_MARKETS,)
    return (country,)


def _partner_packs() -> list[Any]:
    try:
        from app.core.partner_pack.discovery import discover_packs

        return list(discover_packs())
    except Exception:  # noqa: BLE001 - packs are optional, scope must still resolve
        logger.debug("market_scope: partner pack discovery failed", exc_info=True)
        return []


# ── Profile ─────────────────────────────────────────────────────────────────


def _market_entry(value: Any) -> dict[str, str] | None:
    if isinstance(value, str):
        value = {"country": value}
    if not isinstance(value, dict):
        return None
    country = _code(value.get("country"))
    if len(country) != 2 or not (country.isascii() and country.isalpha()):
        return None
    return {"country": country, "subdivision": _code(value.get("subdivision"))}


def sanitise_profile(raw: Any) -> dict[str, Any]:
    """Coerce stored or submitted data into a market profile.

    Unknown or malformed values are dropped field by field, never raised.
    """
    raw = raw if isinstance(raw, dict) else {}
    primary = _market_entry(raw.get("primary"))
    extras: list[dict[str, str]] = []
    for item in raw.get("extra_markets") or []:
        entry = _market_entry(item)
        if entry and entry["country"] != (primary or {}).get("country") and entry not in extras:
            extras.append(entry)
    standards_raw = raw.get("standards") if isinstance(raw.get("standards"), dict) else {}
    standards = {
        key: str(standards_raw.get(key) or "").strip()[:64]
        for key in ("classification", "measurement", "contract_family", "tax_profile")
    }
    units = str(standards_raw.get("units") or "").strip().lower()
    standards["units"] = units if units in UNITS_SYSTEMS else ""
    return {
        "primary": primary,
        "extra_markets": extras,
        "company_type": str(raw.get("company_type") or "").strip()[:64] or None,
        "standards": standards,
        "keep_modules": sorted({str(m) for m in raw.get("keep_modules") or [] if isinstance(m, str)}),
    }


def stored_profile(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The saved profile, or ``None`` when the tenant never saved one."""
    raw = (metadata or {}).get(PROFILE_KEY)
    if not isinstance(raw, dict):
        return None
    profile = sanitise_profile(raw)
    return profile if profile["primary"] else None


def save_profile(metadata: Mapping[str, Any], payload: Any) -> dict[str, Any]:
    """Return new metadata carrying the sanitised profile."""
    out = dict(metadata or {})
    out[PROFILE_KEY] = sanitise_profile(payload)
    return out


def _regional_package_countries(metadata: Mapping[str, Any]) -> list[str]:
    from app.core import regional_packages

    installed = ((metadata or {}).get("solution_packages") or {}).get("installed") or []
    countries: list[str] = []
    for package_id in installed:
        pkg = regional_packages.get_regional_package(package_id) or {}
        countries.extend(_code(c) for c in (pkg.get("profiles") or {}))
    return countries


def derive_profile(
    metadata: Mapping[str, Any] | None,
    *,
    project_countries: Iterable[str] = (),
    active_pack_country: str | None = None,
    markets_by_module: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Build a profile from what the tenant already uses.

    Order: applied country pack, installed regional packages, then the most
    common project country. Every other project country becomes an extra
    market and every tagged module the tenant switched on explicitly is kept,
    so nothing in use disappears.
    """
    metadata = metadata or {}
    candidates: list[str] = []
    pack_country = _code(active_pack_country)
    if pack_country and pack_country != _CROSS_REGION:
        candidates.append(pack_country)
    candidates.extend(_regional_package_countries(metadata))
    counted = Counter(c for c in (_code(p) for p in project_countries) if len(c) == 2)
    candidates.extend(c for c, _ in counted.most_common())
    ordered = list(dict.fromkeys(c for c in candidates if c))
    onboarding = metadata.get("onboarding") if isinstance(metadata.get("onboarding"), dict) else {}
    profile = sanitise_profile(
        {
            "primary": ordered[0] if ordered else None,
            "extra_markets": ordered[1:],
            "company_type": onboarding.get("company_type"),
        }
    )
    tagged = markets_by_module if markets_by_module is not None else module_markets()
    prefs = metadata.get("module_preferences") or {}
    markets = [profile["primary"]["country"]] if profile["primary"] else []
    markets += [m["country"] for m in profile["extra_markets"]]
    profile["keep_modules"] = sorted(
        name
        for name, tags in tagged.items()
        if markets
        and prefs.get(name.removeprefix("oe_")) is True
        and ALL_MARKETS not in normalise_tags(tags)
        and not is_visible(tags, markets)
    )
    return profile


def profile_markets(profile: Mapping[str, Any]) -> list[str]:
    """Primary then extra market codes; ``["*"]`` when the profile names none."""
    codes = [profile["primary"]["country"]] if profile.get("primary") else []
    codes += [m["country"] for m in profile.get("extra_markets") or []]
    return codes or [ALL_MARKETS]


# ── Contributions ───────────────────────────────────────────────────────────


def default_units(markets: Iterable[str]) -> str:
    """Units system the markets' regional packs declare: metric, imperial or both."""
    from app.core.regional_packs import resolve_measurement_system

    systems = {resolve_measurement_system(country_code=m) for m in markets if m != ALL_MARKETS}
    systems.discard(None)
    if ALL_MARKETS in markets or len(systems) > 1:
        return "both"
    return systems.pop() if systems else "metric"


def standards_options(markets: Iterable[str]) -> dict[str, list[str]]:
    """Classification, measurement and contract codes the markets' packs declare."""
    from app.core.regional_packs import pack_configs, packs_for_country

    markets = list(markets)
    configs = pack_configs() if ALL_MARKETS in markets else [c for m in markets for c in packs_for_country(m)]
    standards: list[str] = []
    contracts: list[str] = []
    for config in configs:
        standards += [
            str(s.get("code")) for s in config.get("standards") or [] if isinstance(s, dict) and s.get("code")
        ]
        contracts += [
            str(c.get("code")) for c in config.get("contract_types") or [] if isinstance(c, dict) and c.get("code")
        ]
    return {"standards": list(dict.fromkeys(standards)), "contract_forms": list(dict.fromkeys(contracts))}


def rule_sets_for(
    markets: Iterable[str],
    classification: str | None = None,
    *,
    packs: Iterable[Any] | None = None,
    registered: Iterable[str] | None = None,
) -> list[str]:
    """Rule sets a run should use: universal ones, the market packs' sets, the classification's.

    The market sets come from the partner packs' ``validation_rule_sets``,
    the one place a country names its rules. Only registered sets survive.
    """
    markets = [m for m in markets if m != ALL_MARKETS]
    sets: list[str] = list(UNIVERSAL_RULE_SETS)
    for pack in _partner_packs() if packs is None else packs:
        tags = pack_markets(pack)
        if ALL_MARKETS not in tags and markets and is_visible(tags, markets):
            sets += [str(s) for s in getattr(pack, "validation_rule_sets", None) or []]
    std = (classification or "").strip().lower()
    if std:
        sets.append(std)
    if registered is None:
        from app.core.validation.engine import rule_registry

        registered = rule_registry.list_rule_sets()
    known = set(registered)
    return [s for s in dict.fromkeys(sets) if s in known or s in UNIVERSAL_RULE_SETS]


def resolve(
    profile: Mapping[str, Any],
    *,
    project_country: str | None = None,
    project_classification: str | None = None,
    markets_by_module: Mapping[str, Iterable[str]] | None = None,
    packs: Iterable[Any] | None = None,
    registered_rule_sets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Everything the frontend needs to scope its menus, pickers and rule sets.

    A ``project_country`` narrows the scope to that project's market, and a
    ``project_classification`` picks that project's classification rule set.
    """
    markets = profile_markets(profile)
    if _code(project_country):
        markets = [_code(project_country)]
    tagged = markets_by_module if markets_by_module is not None else module_markets()
    keep = set(profile.get("keep_modules") or [])
    other: list[str] = []
    for name, tags in sorted(tagged.items()):
        if not is_visible(tags, markets) and name not in keep:
            other.append(name.removeprefix("oe_"))
    pack_list = _partner_packs() if packs is None else list(packs)
    standards = dict(profile.get("standards") or {})
    units = standards.get("units") or default_units(markets)
    return {
        "markets": markets,
        "expanded_markets": sorted(expand_markets(markets)),
        "all_markets": ALL_MARKETS in markets,
        "hidden_modules": other,
        "module_markets": {
            name.removeprefix("oe_"): list(tags)
            for name, tags in sorted(tagged.items())
            if ALL_MARKETS not in normalise_tags(tags)
        },
        "packs": [p.slug for p in pack_list if is_visible(pack_markets(p), markets)],
        "units_system": units,
        "standards": standards,
        "options": standards_options(markets),
        "rule_sets": rule_sets_for(
            markets,
            project_classification or standards.get("classification"),
            packs=pack_list,
            registered=registered_rule_sets,
        ),
    }
