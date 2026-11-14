# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo plant register for the demo estate, run by ``app.core.demo_enrichment``.

Each demo project gets a register that is some way into its life, so every
column and every chip of the page shows something: thirteen items from
``identified`` to ``handed_over`` and ``cancelled``, each with dated lead time
quotes (enquiry date, who answered, from what basis), need dates, delivery
limits, a spares concept, a held capacity slot for the transformer, a second
slot still on request with its fee, an approved decision paper for the
switchgear and the construction-phase IT services. Supplier names are generic
descriptions, never company names. Dates are relative to today.

Nothing is written past the rules. A state from ``ordered`` on is read from a
real purchase order or commissioning system the seed creates and links; the
decision paper is approved through a real approval route by the decider of the
demo cast, or else by a team member of the project other than its owner, never
by any other account of the installation (and stays a draft where the project
has no such person); the held slot carries no fee,
because a fee binds money only through a released commitment. ``installed`` is
read from an owner-furnished item of the delivery-model module and is not
seeded here. Money is in the project's own currency or left out.

A project that has not started building is told differently. Whether it has
is read from its governance model: the gate into the phase that enables
construction start exists and is not decided yet. Such a project stands before
that gate, so nothing in its register is ordered yet, every need date lies
after the construction start, each item whose lead time is longer than the
wait for that start must be ordered before the gate date (which is why it
cannot wait for the gate), and the construction-phase IT services are planned
from the mobilisation of the site on.
All of it in day offsets from the seed day, never a calendar date. A project
without a governance model, or past that gate, gets the full range of states.

Only projects carrying the demo marker are touched; a project that already has
plant items is skipped, so a re-run never duplicates.

A demo project of the active pack may bring its own story (``demo_module_story``):
the item table, delivery limits, decision paper, slot texts and offsets, the
construction-phase IT services, the site plant and the three day counts of the
pre-construction timeline. Each key replaces the default of the same name as a
whole when it is well formed and names only codes the shipped catalogue has;
otherwise that key keeps its default, said at info. The structural logic
(states, rules, four eyes) stays in code.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ROUTE = "contractor_furnished_installed"

_STATES = frozenset(
    {
        "identified",
        "specified",
        "enquired",
        "route_set",
        "ordered",
        "manufactured",
        "delivered",
        "commissioned",
        "handed_over",
        "cancelled",
    }
)
_LEAD_BASES = frozenset({"from_order", "from_approved_drawings"})
_SLOT_STATES = frozenset({"held", "requested"})

# A project before its construction gate, in days from the seed day.
GATE_TARGET_DAYS = 21
MOBILISATION_DAYS = 175
CONSTRUCTION_START_DAYS = 190
# The day counts a story may replace, by the constant they stand for.
_INT_KEYS = ("GATE_TARGET_DAYS", "MOBILISATION_DAYS", "CONSTRUCTION_START_DAYS")

# quotes: (source, source_name, enquiry offset days, response offset days, min weeks, max weeks, basis)
# reach: the state the item is taken to, by the rules; need_days: need date relative to today.
_ITEMS: list[dict[str, Any]] = [
    {
        "code": "PL-001",
        "title": "Main power transformer 20/0.4 kV, 2500 kVA",
        "class": "power_transformer",
        "quantity": "2",
        "redundancy": "N+1",
        "need_days": 900,
        "reach": "enquired",
        "route": True,
        "performance": [
            {"key": "rated_power", "value": "2500", "unit": "kVA"},
            {"key": "voltage_ratio", "value": "20/0.4", "unit": "kV"},
            {"key": "losses", "value": "low-loss core", "unit": ""},
        ],
        "quotes": [
            ("market_sounding", "Market sounding, three transformer manufacturers", -120, -105, 90, 128, "from_order"),
            ("supplier_quote", "Transformer manufacturer A (budget quote)", -40, -26, 96, 110, "from_order"),
        ],
        "slot": "held",
        "spares": [("strategic_spares", "Spare bushing set and tap changer contacts", "1", "set")],
    },
    {
        "code": "PL-002",
        "title": "Medium voltage switchgear, 12 panels",
        "class": "mv_switchgear",
        "quantity": "1",
        "redundancy": "",
        "need_days": 700,
        "reach": "route_set",
        "performance": [
            {"key": "rated_voltage", "value": "24", "unit": "kV"},
            {"key": "short_circuit_rating", "value": "20", "unit": "kA 1s"},
        ],
        "quotes": [
            ("supplier_quote", "Switchgear manufacturer A", -60, -46, 52, 60, "from_order"),
            ("supplier_quote", "Switchgear manufacturer B", -55, -38, 40, 44, "from_approved_drawings"),
        ],
        "paper": True,
        "spares": [
            ("strategic_spares", "Spare circuit breaker truck", "1", "pcs"),
            ("special_tools", "Racking and earthing tools", "1", "set"),
        ],
    },
    {
        "code": "PL-003",
        "title": "Standby diesel generator set 1250 kVA",
        "class": "generator",
        "quantity": "2",
        "redundancy": "N+1",
        "need_days": 520,
        "reach": "enquired",
        "route": True,
        "performance": [{"key": "prime_power", "value": "1250", "unit": "kVA"}],
        "quotes": [("supplier_quote", "Generator packager (budget quote)", -30, -18, 40, 48, "from_order")],
        "slot": "requested",
        "spares": [("operating_consumables", "Filters and belts for first two services", "2", "set")],
    },
    {
        "code": "PL-004",
        "title": "Water-cooled chiller 1.2 MW",
        "class": "chiller",
        "quantity": "3",
        "redundancy": "N+1",
        "need_days": 430,
        "reach": "enquired",
        "performance": [{"key": "cooling_capacity", "value": "1200", "unit": "kW"}],
        "quotes": [("expert_estimate", "Owner's engineer estimate", -15, None, 26, 34, "from_order")],
        "spares": [],
    },
    {
        "code": "PL-005",
        "title": "Passenger lifts, 1600 kg, 8 stops",
        "class": "lift",
        "quantity": "4",
        "redundancy": "",
        "need_days": 330,
        "reach": "ordered",
        "performance": [{"key": "rated_load", "value": "1600", "unit": "kg"}],
        "quotes": [("supplier_quote", "Lift manufacturer (firm quote)", -80, -66, 28, 36, "from_approved_drawings")],
        "spares": [("commissioning_spares", "Door operator spares", "1", "set")],
    },
    {
        "code": "PL-006",
        "title": "UPS system 2 x 800 kVA",
        "class": "ups",
        "quantity": "2",
        "redundancy": "2N",
        "need_days": 480,
        "reach": "specified",
        "performance": [{"key": "autonomy", "value": "10", "unit": "min"}],
        "quotes": [],
        "spares": [("strategic_spares", "Spare power module", "1", "pcs")],
    },
    {
        "code": "PL-007",
        "title": "Commercial kitchen equipment, staff restaurant",
        "class": "kitchen_equipment",
        "quantity": "1",
        "redundancy": "",
        "need_days": 600,
        "reach": "identified",
        "performance": [{"key": "covers_per_day", "value": "450", "unit": ""}],
        "quotes": [],
        "spares": [],
    },
    {
        "code": "PL-008",
        "title": "Core network switches and fibre backbone",
        "class": "it_core_network",
        "quantity": "2",
        "redundancy": "N+1",
        "need_days": 30,
        "reach": "delivered",
        "performance": [{"key": "uplink", "value": "100", "unit": "Gbit/s"}],
        "quotes": [("supplier_quote", "Network distributor (firm quote)", -150, -143, 10, 14, "from_order")],
        "spares": [("strategic_spares", "Spare line card and optics", "1", "set")],
    },
    {
        "code": "PL-009",
        "title": "Air handling units, 6 off, 40 000 m3/h",
        "class": "ahu",
        "quantity": "6",
        "redundancy": "",
        "need_days": 120,
        "reach": "manufactured",
        "performance": [{"key": "air_volume", "value": "40000", "unit": "m3/h"}],
        "quotes": [("supplier_quote", "Air handling unit manufacturer", -190, -176, 18, 22, "from_order")],
        "spares": [("operating_consumables", "First filter change set", "6", "set")],
    },
    {
        "code": "PL-010",
        "title": "Main low voltage switchboard 4000 A",
        "class": "lv_switchboard",
        "quantity": "2",
        "redundancy": "",
        "need_days": -20,
        "reach": "commissioned",
        "performance": [{"key": "rated_current", "value": "4000", "unit": "A"}],
        "quotes": [("supplier_quote", "Switchboard builder", -300, -288, 20, 24, "from_approved_drawings")],
        "spares": [],
    },
    {
        "code": "PL-011",
        "title": "Cooling towers, 2 cells",
        "class": "cooling_tower",
        "quantity": "2",
        "redundancy": "N+1",
        "need_days": -75,
        "reach": "handed_over",
        "performance": [{"key": "heat_rejection", "value": "1800", "unit": "kW"}],
        "quotes": [("supplier_quote", "Cooling tower manufacturer", -360, -349, 22, 26, "from_order")],
        "spares": [],
    },
    {
        "code": "PL-012",
        "title": "Ground source heat pump (dropped in value engineering)",
        "class": "heat_pump",
        "quantity": "1",
        "redundancy": "",
        "need_days": 400,
        "reach": "cancelled",
        "performance": [{"key": "heating_capacity", "value": "350", "unit": "kW"}],
        "quotes": [],
        "spares": [],
    },
    {
        "code": "PL-013",
        "title": "Escalators, entrance hall, 2 off",
        "class": "escalator",
        "quantity": "2",
        "redundancy": "",
        "need_days": 380,
        "reach": "route_set",
        "performance": [{"key": "rise", "value": "5.4", "unit": "m"}],
        "quotes": [
            ("supplier_quote", "Escalator manufacturer (budget quote)", -35, -24, 30, 34, "from_approved_drawings")
        ],
        "spares": [],
    },
]

# Construction-phase IT services: (kind, description, needed from, in days from the seed day).
_IT_SERVICES: list[tuple[str, str, int]] = [
    ("cde_access", "Common data environment access for all design and site parties", -30),
    ("site_network", "Site office network and wireless coverage", 60),
    ("access_control", "Turnstiles and badge system at the site gates", 60),
    ("drone_survey", "Monthly drone survey of earthworks and structure", 90),
]

# Site plant positions: (kind, name, x, y, reach in m, maximum load in t).
_SITE_PLANT: list[tuple[str, str, str, str, str | None, str | None]] = [
    ("tower_crane", "Tower crane 1", "42.0", "28.5", "60.00", "8.00"),
    ("mobile_crane_pad", "Crane pad for transformer delivery", "12.0", "64.0", "35.00", "120.00"),
    ("site_office", "Site office and meeting containers", "5.0", "5.0", None, None),
    ("temporary_power", "Temporary power distribution", "8.0", "12.0", None, None),
]

_LIMITS = {
    "supply": "supplier",
    "deliver_to_site": "supplier",
    "offload": "contractor",
    "set_in_place": "contractor",
    "connect": "contractor",
    "test": "supplier",
    "commission": "supplier",
    "accept": "owner",
    "train": "supplier",
    "document": "supplier",
}

# What the order (and the commissioning system) must say for the item to read each state.
_ORDER_FOR = {
    "ordered": ("issued", False),
    "manufactured": ("issued", False),
    "delivered": ("completed", False),
    "commissioned": ("completed", True),
    "handed_over": ("completed", True),
}

_PAPER = {
    "question": "Which switchgear offer secures the energisation date at acceptable risk?",
    "criteria": [
        {"code": "lead_time", "title": "Lead time", "weight": "4"},
        {"code": "cost", "title": "Cost", "weight": "3"},
        {"code": "service", "title": "Local service", "weight": "2"},
    ],
    "options": [
        {
            "code": "a",
            "title": "Manufacturer A, from order",
            "lead_weeks": 60,
            "scores": {"lead_time": "2", "cost": "4", "service": "4"},
        },
        {
            "code": "b",
            "title": "Manufacturer B, from approved drawings",
            "lead_weeks": 44,
            "scores": {"lead_time": "4", "cost": "3", "service": "3"},
        },
    ],
    "recommendation": "b",
    "rationale": "Option B gains about four months on the energisation path; the drawing review is planned.",
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_decimal(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _item_from_story(raw: Any, codes: dict[str, set[str]], locale: str) -> dict[str, Any] | None:
    """One plant item of a story, in the shape of :data:`_ITEMS`, or None when it is malformed."""
    from app.modules.project_governance.public import story_text

    if not isinstance(raw, dict):
        return None
    spec: dict[str, Any] = {
        "code": raw.get("code"),
        "title": story_text(raw.get("title"), locale),
        "class": raw.get("class"),
        "quantity": raw.get("quantity"),
        "redundancy": raw.get("redundancy", ""),
        "need_days": raw.get("need_days"),
        "reach": raw.get("reach"),
    }
    ok = (
        _is_text(spec["code"])
        and _is_text(spec["title"])
        and spec["class"] in codes["component_classes"]
        and _is_decimal(spec["quantity"])
        and (spec["redundancy"] == "" or spec["redundancy"] in codes["redundancy_schemes"])
        and _is_int(spec["need_days"])
        and spec["reach"] in _STATES
    )
    if not ok:
        return None
    spec["performance"] = []
    for entry in raw.get("performance", []):
        value = story_text(entry.get("value"), locale) if isinstance(entry, dict) else None
        if not (isinstance(entry, dict) and _is_text(entry.get("key")) and _is_text(value)):
            return None
        unit = story_text(entry.get("unit", ""), locale)
        if not isinstance(unit, str):
            return None
        spec["performance"].append({"key": entry["key"], "value": value, "unit": unit})
    spec["quotes"] = []
    for q in raw.get("quotes", []):
        if not (isinstance(q, list) and len(q) == 7):
            return None
        source, name, enq, resp, lo, hi, basis = q
        name = story_text(name, locale)
        if not (
            source in codes["lead_time_sources"]
            and _is_text(name)
            and _is_int(enq)
            and (resp is None or _is_int(resp))
            and _is_int(lo)
            and _is_int(hi)
            and 0 < lo <= hi
            and basis in _LEAD_BASES
        ):
            return None
        spec["quotes"].append((source, name, enq, resp, lo, hi, basis))
    spec["spares"] = []
    for sp in raw.get("spares", []):
        if not (isinstance(sp, list) and len(sp) == 4):
            return None
        category, text, qty, unit = sp
        text, unit = story_text(text, locale), story_text(unit, locale)
        if not (category in codes["spare_categories"] and _is_text(text) and _is_decimal(qty) and _is_text(unit)):
            return None
        spec["spares"].append((category, text, qty, unit))
    if raw.get("route"):
        spec["route"] = True
    if "slot" in raw:
        if raw["slot"] not in _SLOT_STATES:
            return None
        spec["slot"] = raw["slot"]
    if raw.get("paper"):
        spec["paper"] = True
    return spec


def _items_from_story(raw: Any, codes: dict[str, set[str]], locale: str) -> list[dict[str, Any]] | None:
    """The whole item table of a story, or None when any row is malformed or a code repeats."""
    if not isinstance(raw, list) or not raw:
        return None
    items = [_item_from_story(r, codes, locale) for r in raw]
    found = [i["code"] for i in items if i is not None]
    if len(found) != len(items) or len(set(found)) != len(found):
        return None
    return [i for i in items if i is not None]


def _limits_from_story(raw: Any, codes: dict[str, set[str]]) -> dict[str, str] | None:
    """Who carries each delivery step: every catalogue step named once, every party known."""
    if not isinstance(raw, dict) or set(raw) != codes["delivery_limit_steps"]:
        return None
    if not all(v in codes["parties"] for v in raw.values()):
        return None
    return dict(raw)


def _paper_from_story(raw: Any, locale: str) -> dict[str, Any] | None:
    """The decision paper of the item flagged ``paper``: criteria, options and a recommended option."""
    from app.modules.project_governance.public import story_text

    if not isinstance(raw, dict):
        return None
    criteria, options = raw.get("criteria"), raw.get("options")
    if not (_is_text(story_text(raw.get("question"), locale)) and isinstance(criteria, list) and criteria):
        return None
    if not (isinstance(options, list) and len(options) >= 2):
        return None
    crit_codes: list[str] = []
    for c in criteria:
        if not (isinstance(c, dict) and _is_text(c.get("code")) and _is_text(story_text(c.get("title"), locale))):
            return None
        if not _is_decimal(c.get("weight")):
            return None
        crit_codes.append(c["code"])
    opt_codes: list[str] = []
    for o in options:
        if not (isinstance(o, dict) and _is_text(o.get("code")) and _is_text(story_text(o.get("title"), locale))):
            return None
        scores = o.get("scores")
        if not (_is_int(o.get("lead_weeks")) and isinstance(scores, dict) and set(scores) == set(crit_codes)):
            return None
        if not all(_is_decimal(v) for v in scores.values()):
            return None
        opt_codes.append(o["code"])
    if raw.get("recommendation") not in opt_codes or not _is_text(story_text(raw.get("rationale"), locale)):
        return None
    out = dict(raw)
    out["question"] = story_text(raw["question"], locale)
    out["rationale"] = story_text(raw["rationale"], locale)
    out["criteria"] = [{**c, "title": story_text(c["title"], locale)} for c in criteria]
    out["options"] = [{**o, "title": story_text(o["title"], locale)} for o in options]
    return out


def _slots_from_story(raw: Any, locale: str) -> dict[str, dict[str, Any]] | None:
    """Per slot state (``held``, ``requested``): vendor, terms, optional fee and day offsets."""
    from app.modules.project_governance.public import story_text

    if not isinstance(raw, dict) or not set(raw) <= _SLOT_STATES:
        return None
    out: dict[str, dict[str, Any]] = {}
    for state, entry in raw.items():
        if not isinstance(entry, dict):
            return None
        clean: dict[str, Any] = {}
        for key in ("vendor_name", "terms"):
            if key in entry:
                text = story_text(entry[key], locale)
                if not _is_text(text):
                    return None
                clean[key] = text
        if "reservation_fee" in entry:
            if not _is_decimal(entry["reservation_fee"]):
                return None
            clean["reservation_fee"] = entry["reservation_fee"]
        for key in ("slot_from_days", "slot_to_days", "convert_by_days"):
            if key in entry:
                if not _is_int(entry[key]):
                    return None
                clean[key] = entry[key]
        out[state] = clean
    return out


def _it_services_from_story(raw: Any, codes: dict[str, set[str]], locale: str) -> list[tuple[str, str, int]] | None:
    """The construction-phase IT services: ``(kind, description, start day)``."""
    from app.modules.project_governance.public import story_text

    if not isinstance(raw, list) or not raw:
        return None
    out: list[tuple[str, str, int]] = []
    for r in raw:
        if not (isinstance(r, dict) and r.get("kind") in codes["it_service_kinds"] and _is_int(r.get("start_days"))):
            return None
        text = story_text(r.get("description"), locale)
        if not _is_text(text):
            return None
        out.append((r["kind"], text, r["start_days"]))
    return out


def _site_plant_from_story(raw: Any, codes: dict[str, set[str]], locale: str) -> list[tuple[Any, ...]] | None:
    """The site plant positions: ``(kind, name, x, y, reach_m or None, max_load_t or None)``."""
    from app.modules.project_governance.public import story_text

    if not isinstance(raw, list) or not raw:
        return None
    out: list[tuple[Any, ...]] = []
    for r in raw:
        if not (isinstance(r, dict) and r.get("kind") in codes["site_plant_kinds"]):
            return None
        name = story_text(r.get("name"), locale)
        if not (_is_text(name) and _is_decimal(r.get("x")) and _is_decimal(r.get("y"))):
            return None
        for key in ("reach_m", "max_load_t"):
            if r.get(key) is not None and not _is_decimal(r[key]):
                return None
        out.append((r["kind"], name, r["x"], r["y"], r.get("reach_m"), r.get("max_load_t")))
    return out


def resolve_story(story: dict[str, Any] | None, codes: dict[str, set[str]], locale: str = "en") -> dict[str, Any]:
    """The validated overrides of a demo story; a key that is absent or malformed is left out.

    ``codes`` holds the catalogue codes per group (see :func:`_catalogue_codes`). The result may
    carry ``items``, ``limits``, ``paper``, ``slots``, ``it_services``, ``site_plant`` and the day
    counts of :data:`_INT_KEYS`; whatever is not in it keeps the module default.
    """
    out: dict[str, Any] = {}
    if not story:
        return out
    builders = {
        "items": lambda v: _items_from_story(v, codes, locale),
        "limits": lambda v: _limits_from_story(v, codes),
        "paper": lambda v: _paper_from_story(v, locale),
        "slots": lambda v: _slots_from_story(v, locale),
        "it_services": lambda v: _it_services_from_story(v, codes, locale),
        "site_plant": lambda v: _site_plant_from_story(v, codes, locale),
    }
    for key, build in builders.items():
        if key not in story:
            continue
        value = build(story[key])
        if value is None:
            logger.info("plant_register demo story: key %r is malformed, the default is kept", key)
        else:
            out[key] = value
    from app.modules.project_governance.public import story_text

    for key in ("paper_route_name", "no_asset_reason"):
        if key in story:
            text = story_text(story[key], locale)
            if _is_text(text):
                out[key] = text
            else:
                logger.info("plant_register demo story: key %r is not usable text, the default is kept", key)
    for key in _INT_KEYS:
        if key.lower() in story:
            if _is_int(story[key.lower()]) and story[key.lower()] >= 0:
                out[key] = story[key.lower()]
            else:
                logger.info("plant_register demo story: key %r is not a day count, the default is kept", key.lower())
    return out


def _catalogue_codes() -> dict[str, set[str]]:
    from app.modules.plant_register.catalogue import shipped_default

    cat = shipped_default()
    return {
        group: cat.codes(group)
        for group in (
            "component_classes",
            "redundancy_schemes",
            "lead_time_sources",
            "spare_categories",
            "delivery_limit_steps",
            "parties",
            "site_plant_kinds",
            "it_service_kinds",
        )
    }


async def seed_plant_register_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, Any]:
    """Seed the register of every demo project in ``project_ids`` that has none. The caller commits.

    Returns the counts, and under ``notes`` one row per project for anything
    that was legally left out (``{"project_id", "note"}``): a project nobody
    owns is not seeded, a paper nobody may decide stays a draft.
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.plant_register.models import PlantItem
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    totals: dict[str, Any] = {"projects": 0, "items": 0, "quotes": 0, "papers_left_draft": 0, "notes": []}
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (
        await session.execute(
            select(Project.id, Project.metadata_, Project.owner_id, Project.currency).where(Project.id.in_(ids))
        )
    ).all()
    for pid, meta, owner, currency in rows:
        demo_id = demo_id_of(meta)
        if not demo_id:
            continue
        if owner is None:
            # Every write is attributed to a real user; a project nobody owns gets no invented one.
            logger.info("plant_register demo seed skipped for %s: the project has no owner", pid)
            totals["notes"].append({"project_id": str(pid), "note": "no_owner"})
            continue
        has = (
            await session.execute(select(PlantItem.id).where(PlantItem.project_id == pid).limit(1))
        ).scalar_one_or_none()
        if has is not None:
            continue
        project = await session.get(Project, pid)
        story = resolve_story(
            demo_module_story(demo_id, "plant_register"), _catalogue_codes(), getattr(project, "locale", None) or "en"
        )
        try:
            async with session.begin_nested():
                counts = await _seed_project(
                    session,
                    pid,
                    owner,
                    currency or "",
                    before_gate=await _before_construction_gate(session, pid),
                    story=story,
                )
        except Exception:
            logger.warning("plant_register demo seed skipped for %s", pid, exc_info=True)
            continue
        totals["projects"] += 1
        for k, v in counts.items():
            totals[k] += v
        if counts["papers_left_draft"]:
            totals["notes"].append({"project_id": str(pid), "note": "decision_paper_left_draft"})
    return totals


async def _before_construction_gate(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Whether the project still stands before the gate that lets construction start.

    Read through the governance port: the phases whose entry enables
    construction start, and the project's gate into one of them. No model, no
    such phase or a decided gate all mean the project is not (or no longer)
    before construction.
    """
    from app.modules.plant_register.hosting import CONSTRUCTION_START
    from app.modules.project_governance.public import phases_enabling, project_gates

    phases = set(await phases_enabling(session, project_id, CONSTRUCTION_START))
    if not phases:
        return False
    gates = [g for g in await project_gates(session, project_id) if g.to_phase in phases]
    return bool(gates) and any(g.status != "decided" for g in gates)


def _reach_before_gate(spec: dict[str, Any]) -> str:
    """How far an item may have got while the project is still in development."""
    from app.modules.plant_register import calc

    if not calc.at_least(spec["reach"], "ordered") or spec["reach"] == "cancelled":
        return spec["reach"]
    return "route_set"


async def _order_before_the_gate(
    svc: Any,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    today: date,
    slack_days: int,
    owner: uuid.UUID,
    start_days: int = CONSTRUCTION_START_DAYS,
) -> None:
    """Move the need date of a long-lead item so its latest order date falls ``slack_days`` from today.

    The latest order date is computed by the register (lead time, basis,
    buffers, review period), so the seed asks for it and shifts the need date
    by the difference instead of repeating that arithmetic. An item whose lead
    time is shorter than the wait for the construction start would then be
    needed before anything is built; it keeps its need date and can be ordered
    after the gate.
    """
    view = (await svc.item_views(project_id, today=today, only=[item_id]))[0]
    if not view["long_lead"] or view["latest_order_date"] is None or view["need_date"] is None:
        return
    shift = (today + timedelta(days=slack_days)) - view["latest_order_date"]
    need = view["need_date"] + shift
    if need <= today + timedelta(days=start_days):
        return
    await svc.update_item(project_id, item_id, {"need_date_fixed": need}, actor_id=owner)


async def _package(svc: Any, project_id: uuid.UUID) -> tuple[bool, uuid.UUID | None]:
    """``(a route can be set, the package to set it on)`` for this project.

    Without the delivery-model module a route is recorded without a package.
    With it, the route needs a package of the plan that supplies and installs;
    a project whose plan has none keeps its routes unset.
    """
    from app.modules.plant_register.errors import PlantError
    from app.modules.plant_register.ports import package_plan_provider

    if package_plan_provider() is None:
        return True, None
    try:
        plan = await svc._plan(project_id)
    except PlantError:
        return False, None
    package = next((p.id for p in (plan.packages if plan else ()) if p.supplies and p.installs), None)
    return package is not None, package


async def _deciders(session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    """The people who may decide a paper the owner submits (four eyes), with their role, preferred first.

    The decider of the demo cast, then the active team members of the project,
    the owner left out. Never another account of the installation: on a real
    install that would be somebody's own login, possibly another tenant's,
    signing a demo paper.
    """
    from app.core.demo_cast import find_cast
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    people: dict[uuid.UUID, str] = {}
    decider = (await find_cast(session)).get("decider")
    if decider is not None and decider != owner:
        role = (
            await session.execute(select(User.role).where(User.id == decider, User.is_active.is_(True)))
        ).scalar_one_or_none()
        if role is not None:
            people[decider] = role
    members = await session.execute(
        select(User.id, User.role)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == project_id, User.id != owner, User.is_active.is_(True))
        .order_by(TeamMembership.created_at, User.id)
    )
    for user_id, role in members:
        people.setdefault(user_id, role)
    return people


async def _approve_paper(
    session: AsyncSession,
    svc: Any,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    paper: Any,
    owner: uuid.UUID,
    route_name: str = "Plant decision paper sign-off",
) -> bool:
    """Take the paper through a real approval route, decided by somebody other than its submitter.

    False leaves the paper a draft: nobody of this demo may decide it, or the
    project already routes its papers to somebody the seed cannot speak for.
    """
    from app.modules.approval_routes.models import Route, Step
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService
    from app.modules.plant_register.service import PAPER_TARGET_KIND

    people = await _deciders(session, project_id, owner)
    if not people:
        logger.info("plant_register demo seed: no second person on %s, the decision paper stays a draft", project_id)
        return False
    routes = ApprovalRouteService(session)
    existing = [
        r
        for r in await routes.list_routes(project_id=project_id, target_kind=PAPER_TARGET_KIND, include_inactive=False)
        if r.project_id == project_id
    ]
    if existing:
        # A route the project already has decides who signs. If that is not one person of this demo, the
        # paper would wait on a desk the seed cannot speak for, so it is not submitted at all.
        signers: set[uuid.UUID | None] = set()
        for route in existing:
            steps = await routes.list_steps(route.id)
            signers.add(steps[0].approver_user_id if steps else None)
        signer = next(iter(signers)) if len(signers) == 1 else None
        if signer not in people:
            logger.info("plant_register demo seed: %s routes its papers elsewhere, the paper stays a draft", project_id)
            return False
    else:
        signer = next(iter(people))
        route = Route(project_id=project_id, name=route_name, target_kind=PAPER_TARGET_KIND, is_active=True)
        session.add(route)
        await session.flush()
        session.add(Step(route_id=route.id, ordinal=1, approver_user_id=signer, mode="any"))
        await session.flush()
    paper = await svc.submit_paper(project_id, item_id, paper.id, actor_id=owner)
    instance = await routes.get_instance(paper.approval_instance_id)
    step = (await routes.list_steps(instance.route_id))[0]
    await routes.submit_decision(
        instance.id,
        DecisionSubmit(step_id=step.id, decision="approved", comment=None),
        approver_id=signer,
        caller_role=people[signer],
    )
    # The route's event is handled outside this transaction; read the verdict from the route here.
    return await svc.reconcile_paper(paper)


#: Net order value per plant item, so an issued order never sits at zero.
_ORDER_VALUE: dict[str, str] = {
    "PL-001": "640000.00",
    "PL-002": "520000.00",
    "PL-003": "780000.00",
    "PL-004": "1260000.00",
    "PL-005": "340000.00",
    "PL-006": "360000.00",
    "PL-007": "240000.00",
    "PL-008": "310000.00",
    "PL-009": "468000.00",
    "PL-010": "420000.00",
    "PL-011": "290000.00",
    "PL-012": "210000.00",
    "PL-013": "330000.00",
}


async def _order(session: AsyncSession, project_id: uuid.UUID, code: str, status: str, currency: str) -> uuid.UUID:
    from app.core.demo_vat import demo_vat_rate
    from app.modules.procurement.models import PurchaseOrder

    net = Decimal(_ORDER_VALUE.get(code, "150000.00"))
    tax = (net * demo_vat_rate(currency)).quantize(Decimal("0.01"))
    po = PurchaseOrder(
        project_id=project_id,
        po_number=f"PO-{code}",
        status=status,
        currency_code=currency,
        amount_subtotal=str(net),
        tax_amount=str(tax),
        amount_total=str(net + tax),
    )
    session.add(po)
    await session.flush()
    return po.id


async def _commissioned_system(session: AsyncSession, project_id: uuid.UUID, title: str) -> uuid.UUID:
    from app.modules.commissioning.models import CxSystem

    cx = CxSystem(project_id=project_id, name=title, status="commissioned")
    session.add(cx)
    await session.flush()
    return cx.id


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner: uuid.UUID,
    currency: str,
    *,
    before_gate: bool = False,
    story: dict[str, Any] | None = None,
) -> dict[str, int]:
    from app.modules.plant_register import calc
    from app.modules.plant_register.service import PlantService

    story = story or {}
    items = story.get("items", _ITEMS)
    limits = story.get("limits", _LIMITS)
    paper_spec = story.get("paper", _PAPER)
    start_days = story.get("CONSTRUCTION_START_DAYS", CONSTRUCTION_START_DAYS)
    mobilisation_days = story.get("MOBILISATION_DAYS", MOBILISATION_DAYS)
    gate_days = story.get("GATE_TARGET_DAYS", GATE_TARGET_DAYS)
    svc = PlantService(session)
    today = datetime.now(UTC).date()
    money = currency if re.fullmatch(r"[A-Z]{3}", currency) else ""
    can_route, package = await _package(svc, project_id)
    counts = {"items": 0, "quotes": 0, "papers_left_draft": 0}
    for index, spec in enumerate(items):
        reach = _reach_before_gate(spec) if before_gate else spec["reach"]
        need_days = max(spec["need_days"], start_days + 15) if before_gate else spec["need_days"]
        item = await svc.create_item(
            project_id,
            {
                "code": spec["code"],
                "title": spec["title"],
                "component_class_code": spec["class"],
                "quantity": Decimal(spec["quantity"]),
                "unit": "pcs",
                "redundancy_scheme": spec["redundancy"],
                "performance": spec["performance"],
                "need_date_fixed": today + timedelta(days=need_days),
                "owner_user_id": owner,
            },
            actor_id=owner,
        )
        counts["items"] += 1
        for source, name, enq, resp, lo, hi, basis in spec["quotes"]:
            await svc.add_quote(
                project_id,
                item.id,
                {
                    "source": source,
                    "source_name": name,
                    "enquiry_date": today + timedelta(days=enq),
                    "response_date": today + timedelta(days=resp) if resp is not None else None,
                    "lead_weeks_min": lo,
                    "lead_weeks_max": hi,
                    "lead_basis": basis,
                    "set_basis": True,
                },
                actor_id=owner,
                today=today,
            )
            counts["quotes"] += 1
        if before_gate and spec["quotes"]:
            # Between a few days from now and just before the gate, a different day per item. The first
            # item, the transformer, is the most urgent: the commitment that releases its order reads this date.
            slack = 4 + (index * 5) % max(gate_days - 6, 1)
            await _order_before_the_gate(svc, project_id, item.id, today, slack, owner, start_days)
        for category, text, qty, unit in spec["spares"]:
            await svc.create_spare(
                project_id,
                item.id,
                {
                    "category": category,
                    "description": text,
                    "quantity": Decimal(qty),
                    "unit": unit,
                    "supply_by": "supplier",
                },
                actor_id=owner,
            )
        if spec.get("slot"):
            await _seed_slot(svc, project_id, item.id, spec["slot"], today, money, owner, story.get("slots", {}))
        approved = False
        if spec.get("paper"):
            paper = await svc.create_paper(project_id, item.id, paper_spec, actor_id=owner)
            approved = await _approve_paper(
                session,
                svc,
                project_id,
                item.id,
                paper,
                owner,
                story.get("paper_route_name", "Plant decision paper sign-off"),
            )
            counts["papers_left_draft"] += 0 if approved else 1
        if reach == "identified":
            continue
        await svc.transition_item(project_id, item.id, "specified", actor_id=owner, today=today)
        if reach == "cancelled":
            await svc.transition_item(project_id, item.id, "cancelled", actor_id=owner, today=today)
            continue
        if reach == "specified":
            continue
        await svc.transition_item(project_id, item.id, "enquired", actor_id=owner, today=today)
        wants_route = spec.get("route") or calc.at_least(reach, "route_set")
        if not (wants_route and can_route):
            continue
        await svc.set_route(project_id, item.id, route=ROUTE, contract_package_id=package, actor_id=owner)
        await svc.put_limits(project_id, item.id, [{"step": k, "party": v} for k, v in limits.items()], actor_id=owner)
        if not calc.at_least(reach, "route_set") or (spec.get("paper") and not approved):
            continue
        await svc.transition_item(project_id, item.id, "route_set", actor_id=owner, today=today)
        if reach not in _ORDER_FOR:
            continue
        # From here the state is read: the seed creates the order (and the system) and links them.
        order_status, commissioned = _ORDER_FOR[reach]
        links: dict[str, Any] = {
            "purchase_order_id": await _order(session, project_id, spec["code"], order_status, money)
        }
        if commissioned:
            links["cx_system_id"] = await _commissioned_system(session, project_id, spec["title"])
        await svc.update_item(project_id, item.id, links, actor_id=owner)
        if reach == "manufactured":
            await svc.transition_item(project_id, item.id, "manufactured", actor_id=owner, today=today)
        if reach == "handed_over":
            await svc.handover(
                project_id,
                item.id,
                confirm=True,
                service_contract_id=None,
                actor_id=owner,
                no_asset_reason=story.get(
                    "no_asset_reason", "Maintained by the operator's own staff; no service contract is let for it."
                ),
            )
    for kind, desc, start in story.get("it_services", _IT_SERVICES):
        await svc.create_it_service(
            project_id,
            {
                "kind": kind,
                "description": desc,
                # Before the gate nothing of the construction phase is in service yet.
                "needed_from": today + timedelta(days=max(start, mobilisation_days) if before_gate else start),
            },
            actor_id=owner,
        )
    await _seed_site_plant(session, project_id, today, story.get("site_plant", _SITE_PLANT))
    return counts


async def _seed_slot(
    svc: Any,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    state: str,
    today: date,
    money: str,
    owner: uuid.UUID,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    """A slot held free of charge, or one still on request with the fee the manufacturer asks.

    The held slot costs nothing and states no amount: the value of the order
    that converts it is the commitment module's to plan and release, and this
    seed runs before that module's, so it names no commitment and repeats no
    figure of it.
    """
    held = state == "held"
    own = (overrides or {}).get(state, {})
    data: dict[str, Any] = {
        "vendor_name": "Transformer manufacturer A" if held else "Generator packager",
        "slot_from": today + timedelta(days=own.get("slot_from_days", 300)),
        "slot_to": today + timedelta(days=own.get("slot_to_days", 360)),
        "fee_refundable": "full" if held else "none",
        "fee_credited_to_order": not held,
        "convert_by_date": today + timedelta(days=own.get("convert_by_days", 45)),
        "terms": (
            "The manufacturer holds the slot without a fee until the conversion date; the slot itself binds no "
            "money. Authority to sign the supply order is released as a commitment of the project, and the slot "
            "lapses if the order is not signed by that date."
            if held
            else "Fee non-refundable, credited in full to the order if signed by the conversion date."
        ),
    }
    data.update({k: v for k, v in own.items() if k in ("vendor_name", "terms")})
    if money:
        fee = own.get("reservation_fee", "0.00" if held else "25000.00")
        data["reservation_fee"] = Decimal("0.00") if held else Decimal(fee)
        data["currency"] = money
    slot = await svc.create_slot(project_id, item_id, data, actor_id=owner)
    if held and money:
        await svc.transition_slot(project_id, item_id, slot.id, "held", actor_id=owner)


async def _seed_site_plant(
    session: AsyncSession, project_id: uuid.UUID, today: date, positions: Iterable[tuple[Any, ...]] = _SITE_PLANT
) -> None:
    from app.modules.site_logistics.models import SitePlantPosition

    has = (
        await session.execute(select(SitePlantPosition.id).where(SitePlantPosition.project_id == project_id).limit(1))
    ).scalar_one_or_none()
    if has is not None:
        return
    for kind, name, x, y, reach, load in positions:
        session.add(
            SitePlantPosition(
                project_id=project_id,
                kind=kind,
                name=name,
                x=Decimal(x),
                y=Decimal(y),
                reach_m=Decimal(reach) if reach else None,
                max_load_t=Decimal(load) if load else None,
                from_date=today,
                to_date=today + timedelta(days=720),
                note="",
            )
        )
    await session.flush()
