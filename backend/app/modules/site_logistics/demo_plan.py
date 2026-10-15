# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo logistics plan for a demo project, run from :func:`demo.seed_site_logistics_demo`.

The neutral example of SPEC section 11, country neutral and with no company or
person names: a 12 000 m2 site in two stages (earthworks, structure) whose area
balance closes; power for two tower cranes and the site offices against a
contracted connection with the reserve; a water connection still on request; a
concept with stock, kanban and direct-install flows; a heavy transformer
transport that is scheduled on a granted oversize permit (which also lifts the
gate's load limit for it) and a granted night-work permit for its night window;
a spoil run and a regular inbound delivery; an import
case under FCA with HS-coded lines and its document checklist; the neighbourhood
plan with quiet hours, two complaints and two coordination entries.

Everything goes through :class:`LogisticsPlanService`, so the rows obey the same
rules a user meets. Dates are anchored to the day the demo is seeded, and the
permit windows cover every weekday, so the plan is valid whatever day that is.
The site clock is set to UTC explicitly: a demo project states no location, and
the time rules do not run without a zone. A project that already has a stage is
skipped, so a re-run adds nothing.

The story follows where the project stands. A project still before its gate
into construction (read through the governance port, never from a catalogue or
a name) gets the plan of a site that does not run yet: both stages planned from
the start of construction, power, water and sewage applied for and telecom only
identified, the transformer planned well after the start with its oversize
permit in preparation, nothing scheduled, nothing ordered abroad and so no
customs case, no complaint. A project past that gate, or without a phase
model, gets the running site described above.

A refusal of the service fails the seed: a demo that silently lacks its plan is
found by a viewer, not by us.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_logistics.demo import DEMO_CONSTRUCTION_START_DAY

logger = logging.getLogger(__name__)


DEMO_SITE_TIMEZONE = "UTC"
# Days from the seed day, for a project that still stands before its gate into construction.
_CONSTRUCTION_START_DAY = DEMO_CONSTRUCTION_START_DAY
_TRANSFORMER_DAY = DEMO_CONSTRUCTION_START_DAY + 260
_EVERY_WEEKDAY = [0, 1, 2, 3, 4, 5, 6]


def _square(x0: int, y0: int, w: int, h: int) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0]]]}


# (code, kind, geometry or declared m2, stage-1 kind and m2, stage-2 kind and m2)
_AREAS: tuple[tuple[str, str, dict[str, Any] | None, str | None, tuple[str, str], tuple[str, str]], ...] = (
    ("SITE", "site_total", _square(0, 0, 120, 100), None, ("site_total", "12000"), ("site_total", "12000")),
    (
        "A-BLD",
        "building_footprint",
        _square(20, 20, 90, 60),
        None,
        ("expansion_reserve", "5400"),
        ("building_footprint", "5400"),
    ),
    ("A-LAY", "laydown", _square(0, 0, 60, 20), None, ("laydown", "1200"), ("laydown", "1200")),
    ("A-LAY2", "laydown", None, "1800", ("laydown", "1800"), ("laydown", "600")),
    ("A-SET", "site_setup", None, "800", ("site_setup", "800"), ("site_setup", "800")),
    ("A-TRF", "traffic_route", None, "2200", ("traffic_route", "2200"), ("traffic_route", "1600")),
    ("A-RES", "expansion_reserve", None, "2400", ("expansion_reserve", "600"), ("expansion_reserve", "2400")),
)


_STRATEGY_MODES = ("stock", "kanban", "direct_install")
_STORAGE_AREAS = ("A-LAY", "A-LAY2")

# What a story may replace in the plan, key by key. A key a story leaves out, or gets wrong, keeps this.
_PLAN_TEXT_DEFAULTS: dict[str, str] = {
    "stage_1_title": "Earthworks",
    "stage_2_title": "Structure",
    "power_connection_point": "Transformer kiosk at the north gate",
    "water_connection_point": "Hydrant south road",
    "water_consumer": "Concrete curing and wheel wash",
    "sewage_connection_point": "Manhole in the south road",
    "rules_text": "Book every delivery 48 hours ahead. No waiting on the public road. Wheel wash on exit.",
    "municipality_contact": "Municipal building department",
    "parking_note": "Site staff park on the leased lot east of the site.",
    "heavy_title": "Main transformer 62 t",
    "heavy_route_notes": "Ring road, then the industrial road.",
    "heavy_destination": "Site, north gate",
    "oversize_authority": "Road traffic authority",
    "night_authority": "Environmental authority",
    "spoil_title": "Excavated soil to the licensed tip",
    "rebar_title": "Reinforcement, first floor slab",
    "rebar_destination": "Laydown A",
    "dust_description": "Dust on parked cars on the east side after excavation.",
    "dust_response": "Water spraying twice a day; wheel wash moved to the exit.",
    "complaint_reporter": "Neighbour, anonymous",
    "noise_description": "Reversing alarms before 07:00 at the north gate.",
    "power_provider": "Local grid operator",
    "water_provider": "Municipal water utility",
    "sewage_provider": "Municipal drainage utility",
    "crane_1_consumer": "Tower crane 1",
    "crane_2_consumer": "Tower crane 2",
    "welfare_consumer": "Site offices and welfare",
    "telecom_point": "Duct at the north gate",
    "telecom_consumer": "Site offices data link",
    "heavy_carrier": "Heavy haulage carrier",
    "heavy_origin": "Manufacturer works",
    "oversize_conditions": "Route survey ordered; application to follow with the survey.",
    "spoil_carrier": "Earthworks haulier",
    "spoil_origin": "Site",
    "spoil_destination": "Licensed soil tip",
    "rebar_carrier": "Steel supplier transport",
    "rebar_origin": "Rebar yard",
    "customs_title": "Medium voltage switchgear",
    "customs_place": "Manufacturer works, loading dock",
    "customs_broker": "Customs broker",
    "customs_line_1": "Switchgear panels, 24 kV",
    "customs_line_2": "Control cabinets",
    "customs_unit": "pcs",
}
_DEFAULT_STRATEGY: tuple[tuple[str, str, str, str | None, int], ...] = (
    ("rebar", "Reinforcement, cut and bent", "stock", "A-LAY", 5),
    ("drywall", "Drywall boards by floor", "kanban", "A-LAY2", 2),
    ("precast", "Precast stair cores, set from the truck", "direct_install", None, 0),
)
_DEFAULT_COORDINATION: tuple[tuple[str, str, str, int, int | None], ...] = (
    ("municipality", "Road occupancy for the crane base", "Agreed in principle; written application to follow.", 9, 5),
    ("utility", "Water connection date", "Utility confirmed the connection in four weeks.", 2, None),
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _strategy_rows(flows: list, locale: str) -> tuple | None:
    from app.modules.project_governance.public import story_text

    rows = []
    for f in flows:
        if not isinstance(f, dict):
            return None
        storage = f.get("storage_area")
        desc = story_text(f.get("description"), locale)
        ok = (
            isinstance(f.get("flow_code"), str)
            and f["flow_code"]
            and desc
            and f.get("mode") in _STRATEGY_MODES
            and (storage is None or storage in _STORAGE_AREAS)
            and _is_int(f.get("buffer_days"))
            and f["buffer_days"] >= 0
        )
        if not ok:
            return None
        rows.append((f["flow_code"], desc, f["mode"], storage, f["buffer_days"]))
    return tuple(rows)


def _coordination_rows(entries: list, locale: str) -> tuple | None:
    from app.modules.project_governance.public import story_text

    rows = []
    for e in entries:
        if not isinstance(e, dict):
            return None
        topic, outcome = story_text(e.get("topic"), locale), story_text(e.get("outcome"), locale)
        nxt = e.get("next_action_in")
        ok = (
            e.get("body") in ("municipality", "utility", "police", "neighbours", "authority", "other")
            and topic
            and outcome
            and _is_int(e.get("days_ago"))
            and (nxt is None or _is_int(nxt))
        )
        if not ok:
            return None
        rows.append((e["body"], topic, outcome, e["days_ago"], nxt))
    return tuple(rows)


def resolve_plan_content(story: dict | None, locale: str) -> dict[str, Any]:
    """The content of the logistics plan for one project: today's defaults with the story applied on top.

    Text keys are those of ``_PLAN_TEXT_DEFAULTS``. Structured keys: ``area_names`` (area code to
    name), ``strategy`` (flow_code, description, mode, storage_area code, buffer_days),
    ``delivery_open`` / ``delivery_close`` (``HH:MM``), ``noise_zone_type``, ``day_dba`` /
    ``night_dba`` (numbers used when the catalogue has no limit for the zone) and ``coordination``
    (body, topic, outcome, days_ago, optional next_action_in). An unusable value keeps the default
    for that key and is logged at info level only.
    """
    from app.modules.project_governance.public import story_text
    from app.modules.site_logistics.demo import _hhmm

    out: dict[str, Any] = dict(_PLAN_TEXT_DEFAULTS)
    out.update(
        area_names={},
        strategy=_DEFAULT_STRATEGY,
        delivery_open="07:00",
        delivery_close="17:00",
        noise_zone_type="mixed",
        day_dba=Decimal("60"),
        night_dba=Decimal("45"),
        coordination=_DEFAULT_COORDINATION,
        customs_before_gate=False,
        complaints_before_gate=False,
    )
    if not isinstance(story, dict) or not story:
        return out

    for key in _PLAN_TEXT_DEFAULTS:
        if key in story:
            text = story_text(story[key], locale)
            if text:
                out[key] = text
            else:
                logger.info("site_logistics demo story: %s not usable, keeping the default", key)

    names = story.get("area_names")
    if isinstance(names, dict):
        known = {a[0] for a in _AREAS}
        out["area_names"] = {k: story_text(v, locale) for k, v in names.items() if k in known and story_text(v, locale)}

    flows = story.get("strategy")
    if isinstance(flows, list) and flows:
        rows = _strategy_rows(flows, locale)
        if rows:
            out["strategy"] = rows
        else:
            logger.info("site_logistics demo story: strategy not usable, keeping the default flows")

    open_t, close_t = story.get("delivery_open"), story.get("delivery_close")
    if _hhmm(open_t) and _hhmm(close_t) and open_t < close_t:
        out["delivery_open"], out["delivery_close"] = open_t, close_t

    if story.get("noise_zone_type") in ("residential", "mixed", "industrial"):
        out["noise_zone_type"] = story["noise_zone_type"]
    for key in ("day_dba", "night_dba"):
        value = story.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool) and 0 < value < 120:
            out[key] = Decimal(str(value))

    for key in ("customs_before_gate", "complaints_before_gate"):
        if story.get(key) is True:
            out[key] = True

    entries = story.get("coordination")
    if isinstance(entries, list) and entries:
        rows = _coordination_rows(entries, locale)
        if rows:
            out["coordination"] = rows
        else:
            logger.info("site_logistics demo story: coordination not usable, keeping the default entries")
    return out


async def seed_logistics_plan_demo(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[str, int]:
    """Seed the logistics plan of every project in ``project_ids`` that has no stage yet. The caller commits."""
    from app.modules.site_logistics.models import ExpansionStage

    totals = {"projects": 0, "transports": 0}
    for pid in project_ids:
        has = (
            await session.execute(select(ExpansionStage.id).where(ExpansionStage.project_id == pid).limit(1))
        ).scalar_one_or_none()
        if has is not None:
            continue
        written = await _seed_project(session, pid)
        totals["projects"] += 1
        totals["transports"] += written
    return totals


async def _seed_project(session: AsyncSession, pid: uuid.UUID) -> int:
    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project
    from app.modules.site_logistics import hosting
    from app.modules.site_logistics.models import Gate, LaydownZone
    from app.modules.site_logistics.plan_service import LogisticsPlanService

    project = await session.get(Project, pid)
    content = resolve_plan_content(
        demo_module_story(demo_id_of(getattr(project, "metadata_", None)), "site_logistics"),
        getattr(project, "locale", None) or "en",
    )
    svc = LogisticsPlanService(session)
    cat = await svc.catalogue(pid)
    today = datetime.now(UTC).date()
    actor = None
    # Before the gate into construction the site does not run: everything below is a plan.
    planned = await hosting.before_construction(session, pid)
    start = _CONSTRUCTION_START_DAY if planned else -14

    # The site clock first: every window below is checked on it.
    await svc.put_concept(pid, {"site_timezone": DEMO_SITE_TIMEZONE}, actor)

    # Stages: earthworks now, structure from week 8. The first write above created the initial stage.
    stage1 = (await svc.stages(pid))[0]
    await svc.update_stage(
        pid,
        stage1.id,
        {
            "code": "S1",
            "title": content["stage_1_title"],
            "ordinal": 1,
            "from_date": today + timedelta(days=start),
            "to_date": today + timedelta(days=start + 56),
        },
        actor,
    )
    if not planned:
        await svc.transition_stage(pid, stage1.id, "active", actor)
    stage2 = await svc.create_stage(
        pid,
        {
            "code": "S2",
            "title": content["stage_2_title"],
            "ordinal": 2,
            "from_date": today + timedelta(days=start + 57),
            "to_date": today + timedelta(days=start + 314),
        },
        actor,
    )

    # Areas and their allocation per stage: both balances close at 12 000 m2.
    areas = {}
    for code, kind, geometry, declared, s1, s2 in _AREAS:
        data: dict[str, Any] = {"code": code, "name": content["area_names"].get(code, code), "area_kind": kind}
        if geometry is not None:
            data["geometry"] = geometry
        else:
            data["area_m2_declared"] = Decimal(declared or "0")
        area = await svc.create_area(pid, data, actor)
        areas[code] = area
        await svc.put_allocations(
            pid,
            area.id,
            [
                {"stage_id": stage1.id, "area_kind": s1[0], "allocated_m2": Decimal(s1[1])},
                {"stage_id": stage2.id, "area_kind": s2[0], "allocated_m2": Decimal(s2[1])},
            ],
            actor,
        )

    # Gates get load limits; laydown zones map onto the planned laydown area.
    gates = list((await session.execute(select(Gate).where(Gate.project_id == pid).order_by(Gate.name))).scalars())
    limits = (("road_gate", "44", "4.00", "3.50"), ("road_gate", "18", "4.00", "3.00"))
    for gate, (kind, gross, height, width) in zip(gates, limits, strict=False):
        if gate.max_gross_t is None:
            gate.access_kind = kind
            gate.max_gross_t = Decimal(gross)
            gate.max_axle_load_t = Decimal("11.5")
            gate.max_height_m = Decimal(height)
            gate.max_width_m = Decimal(width)
    zones = list((await session.execute(select(LaydownZone).where(LaydownZone.project_id == pid))).scalars())
    for zone in zones[:1]:
        zone.site_area_id = areas["A-LAY"].id
    await session.flush()

    # Media: power contracted at 160 kVA covers 2 x 60 + 40 kVA at 0.8 plus 10 % (140.8 kVA).
    power = await svc.create_media(
        pid,
        {
            "media_kind": "power",
            "phase": "construction",
            "provider_name": content["power_provider"],
            "connection_point": content["power_connection_point"],
            "available_capacity": Decimal("250"),
            "contracted_capacity": Decimal("160"),
            "application_ref": "PWR-001",
            "applied_on": today - timedelta(days=20 if planned else 60),
            "promised_on": today + timedelta(days=30) if planned else today - timedelta(days=20),
        },
        actor,
    )
    # Applied for before construction; contracted and connected once the site runs.
    for target in ("requested",) if planned else ("requested", "offered", "contracted", "connected"):
        await svc.transition_media(pid, power.id, target, actor)
    for consumer, kva in (
        (content["crane_1_consumer"], "60"),
        (content["crane_2_consumer"], "60"),
        (content["welfare_consumer"], "40"),
    ):
        await svc.create_demand(
            pid,
            power.id,
            {
                "stage_id": stage2.id,
                "consumer": consumer,
                "peak_demand": Decimal(kva),
                "simultaneity_factor": Decimal("0.8"),
            },
            actor,
        )
    await svc.create_demand(
        pid,
        power.id,
        {
            "stage_id": stage1.id,
            "consumer": content["welfare_consumer"],
            "peak_demand": Decimal("40"),
            "simultaneity_factor": Decimal("0.8"),
        },
        actor,
    )
    water = await svc.create_media(
        pid,
        {
            "media_kind": "water",
            "provider_name": content["water_provider"],
            "connection_point": content["water_connection_point"],
            # A running site has its water contracted (12 m3/h covers the 6 m3/h peak with room);
            # a site still being planned has only asked for it.
            **({} if planned else {"contracted_capacity": Decimal("12")}),
            "application_ref": "WAT-014",
            "applied_on": today - timedelta(days=10 if planned else 45),
            "promised_on": today + timedelta(days=30) if planned else today - timedelta(days=15),
        },
        actor,
    )
    for target in ("requested",) if planned else ("requested", "offered", "contracted", "connected"):
        await svc.transition_media(pid, water.id, target, actor)
    await svc.create_demand(
        pid,
        water.id,
        {"stage_id": stage2.id, "consumer": content["water_consumer"], "peak_demand": Decimal("6")},
        actor,
    )

    if planned:
        sewage = await svc.create_media(
            pid,
            {
                "media_kind": "sewage",
                "provider_name": content["sewage_provider"],
                "connection_point": content["sewage_connection_point"],
                "available_capacity": Decimal("12"),
                "application_ref": "SEW-007",
                "applied_on": today - timedelta(days=10),
                "promised_on": today + timedelta(days=35),
            },
            actor,
        )
        await svc.transition_media(pid, sewage.id, "requested", actor)
        await svc.create_demand(
            pid,
            sewage.id,
            {"stage_id": stage2.id, "consumer": content["welfare_consumer"], "peak_demand": Decimal("4")},
            actor,
        )
        # Telecom is known to be needed and not applied for yet.
        telecom = await svc.create_media(
            pid, {"media_kind": "telecom", "connection_point": content["telecom_point"]}, actor
        )
        await svc.create_demand(
            pid,
            telecom.id,
            {"stage_id": stage1.id, "consumer": content["telecom_consumer"], "peak_demand": Decimal("100")},
            actor,
        )

    # Concept: delivery hours narrower than the gates, three flows.
    await svc.put_concept(
        pid,
        {
            "strategy": [
                {
                    "flow_code": code,
                    "description": desc,
                    "mode": mode,
                    **({"storage_area_id": areas[storage].id} if storage else {}),
                    "buffer_days": buf,
                }
                for code, desc, mode, storage, buf in content["strategy"]
            ],
            "delivery_open": content["delivery_open"],
            "delivery_close": content["delivery_close"],
            "max_deliveries_per_hour": 4,
            "rules_text": content["rules_text"],
        },
        actor,
    )

    # Neighbourhood: the catalogue's mixed-zone limit where the country has one, else a project value.
    limit = next(
        (n for n in cat.noise_limits if n.zone_type == content["noise_zone_type"] and not n.project_value_required),
        None,
    )
    hood: dict[str, Any] = {
        "zone_type": content["noise_zone_type"],
        "municipality_contact": content["municipality_contact"],
        "parking_note": content["parking_note"],
    }
    if limit is not None:
        hood["noise_limit_source"] = limit.code
    else:
        hood.update(
            {
                "noise_limit_source": "project",
                "day_dba": content["day_dba"],
                "night_dba": content["night_dba"],
                "quiet_hours": ["20:00", "07:00"],
            }
        )
    await svc.put_neighbourhood(pid, hood, actor)

    # Transports.
    gate = gates[0] if gates else None
    day = today + timedelta(days=_TRANSFORMER_DAY if planned else 21)
    heavy = await svc.create_transport(
        pid,
        {
            "direction": "inbound",
            "transport_kind": "heavy_oversize",
            "title": content["heavy_title"],
            "carrier_name": content["heavy_carrier"],
            "origin": content["heavy_origin"],
            "destination": content["heavy_destination"],
            "gate_id": gate.id if gate else None,
            "planned_window_start": datetime.combine(day, time(22, 0), tzinfo=UTC),
            "planned_window_end": datetime.combine(day + timedelta(days=1), time(4, 0), tzinfo=UTC),
            "gross_weight_t": Decimal("62"),
            "width_m": Decimal("3.20"),
            "height_m": Decimal("4.30"),
            "length_m": Decimal("22.00"),
            "escort_required": True,
            "route_notes": content["heavy_route_notes"],
        },
        actor,
    )
    await svc.transition_transport(pid, heavy.id, "permit_pending", actor)
    if planned:
        # The oversize permit is in preparation: a draft without a decision of the authority.
        await svc.create_permit(
            pid,
            {
                "transport_id": heavy.id,
                "permit_kind": "oversize_permit",
                "authority": content["oversize_authority"],
                "conditions": content["oversize_conditions"],
            },
            actor,
        )
        return await _seed_rest(session, svc, pid, today, gate, content, planned=True)
    oversize = await svc.create_permit(
        pid,
        {
            "transport_id": heavy.id,
            "permit_kind": "oversize_permit",
            "authority": content["oversize_authority"],
            "reference": "OS-2026-118",
            "valid_from": day - timedelta(days=3),
            "valid_to": day + timedelta(days=10),
            "allowed_windows": [{"weekdays": _EVERY_WEEKDAY, "from": "22:00", "to": "05:00"}],
        },
        actor,
    )
    night = await svc.create_permit(
        pid,
        {
            "transport_id": heavy.id,
            "permit_kind": "night_work",
            "authority": content["night_authority"],
            "reference": "NW-2026-031",
            "valid_from": day,
            "valid_to": day + timedelta(days=1),
        },
        actor,
    )
    for permit in (oversize, night):
        await svc.transition_permit(pid, permit.id, "applied", actor)
        await svc.transition_permit(pid, permit.id, "granted", actor)
    # 62 t through a 44 t gate: the granted oversize permit covers this transport and
    # this window, so the gate limit is lifted for it and it can hold its slot.
    await svc.transition_transport(pid, heavy.id, "scheduled", actor)
    return await _seed_rest(session, svc, pid, today, gate, content, planned=False)


async def _seed_rest(
    session: AsyncSession, svc: Any, pid: uuid.UUID, today: Any, gate: Any, content: dict[str, Any], *, planned: bool
) -> int:
    """The everyday transports, the customs case, complaints and coordination."""
    actor = None
    # On a site that does not run yet the first runs are planned for its first week.
    first = _CONSTRUCTION_START_DAY if planned else 0
    await svc.create_transport(
        pid,
        {
            "direction": "outbound",
            "transport_kind": "outbound_spoil",
            "title": content["spoil_title"],
            "carrier_name": content["spoil_carrier"],
            "origin": content["spoil_origin"],
            "destination": content["spoil_destination"],
            "gate_id": gate.id if gate else None,
            "planned_window_start": datetime.combine(today + timedelta(days=first + 2), time(8, 0), tzinfo=UTC),
            "planned_window_end": datetime.combine(today + timedelta(days=first + 2), time(15, 0), tzinfo=UTC),
            "gross_weight_t": Decimal("32"),
        },
        actor,
    )
    rebar = await svc.create_transport(
        pid,
        {
            "direction": "inbound",
            "transport_kind": "inbound_delivery",
            "title": content["rebar_title"],
            "carrier_name": content["rebar_carrier"],
            "origin": content["rebar_origin"],
            "destination": content["rebar_destination"],
            "gate_id": gate.id if gate else None,
            "planned_window_start": datetime.combine(today + timedelta(days=first + 4), time(9, 0), tzinfo=UTC),
            "planned_window_end": datetime.combine(today + timedelta(days=first + 4), time(10, 0), tzinfo=UTC),
            "gross_weight_t": Decimal("24"),
        },
        actor,
    )
    if not planned:
        await svc.transition_transport(pid, rebar.id, "scheduled", actor)

    # Nothing is ordered before the gate, so there is no shipment to clear yet, unless the story
    # tells a project that signed a supply order on a held slot ahead of it.
    if not planned or content["customs_before_gate"]:
        await _seed_customs(session, svc, pid, content)

    # Complaints come with a running site; coordination with the authorities starts before it.
    # A story may have the neighbours complain about the survey and clearing works already.
    if not planned or content["complaints_before_gate"]:
        await _seed_complaints(svc, pid, today, content)
    for body, topic, outcome, days_ago, next_in in content["coordination"]:
        await svc.create_coordination(
            pid,
            {
                "entry_date": today - timedelta(days=days_ago),
                "body": body,
                "topic": topic,
                "outcome": outcome,
                **({"next_action_due": today + timedelta(days=next_in)} if next_in is not None else {}),
            },
            actor,
        )
    await session.flush()
    return 3


async def _seed_complaints(svc: Any, pid: uuid.UUID, today: Any, content: dict[str, Any]) -> None:
    actor = None
    dust = await svc.create_complaint(
        pid,
        {
            "kind": "dust",
            "reported_on": today - timedelta(days=6),
            "reporter": content["complaint_reporter"],
            "description": content["dust_description"],
        },
        actor,
    )
    await svc.transition_complaint(pid, dust.id, "acknowledged", actor)
    await svc.update_complaint(pid, dust.id, {"response": content["dust_response"]}, actor)
    await svc.transition_complaint(pid, dust.id, "action_taken", actor)
    await svc.create_complaint(
        pid,
        {
            "kind": "noise",
            "reported_on": today - timedelta(days=1),
            "description": content["noise_description"],
        },
        actor,
    )


async def _seed_customs(session: AsyncSession, svc: Any, pid: uuid.UUID, content: dict[str, Any]) -> None:
    actor = None
    # Customs: imported switchgear under FCA, the buyer (us) clears import. Values are
    # in the project's currency; a project without one gets the case without values.
    from app.modules.projects.models import Project

    currency = (await session.execute(select(Project.currency).where(Project.id == pid))).scalar_one_or_none() or None
    case = await svc.create_customs(
        pid,
        {
            "direction": "import",
            "title": content["customs_title"],
            "incoterm": "FCA",
            "named_place": content["customs_place"],
            "transport_mode": "road",
            "country_of_origin": "CH",
            "declarant_party": "buyer",
            "broker_name": content["customs_broker"],
            **({"customs_value": Decimal("184500.00"), "currency": currency} if currency else {}),
        },
        actor,
        can_see_values=True,
    )
    for desc, hs, qty, value in (
        (content["customs_line_1"], "853720", "6", "171000.00"),
        (content["customs_line_2"], "853710", "2", "13500.00"),
    ):
        await svc.create_line(
            pid,
            case.id,
            {
                "description": desc,
                "hs_code": hs,
                "quantity": Decimal(qty),
                "unit": content["customs_unit"],
                **({"value": Decimal(value), "currency": currency} if currency else {}),
                "origin_country": "CH",
            },
            actor,
            can_see_values=True,
        )
    for doc in await svc.documents(pid, case.id):
        if doc.kind in ("commercial_invoice", "packing_list"):
            await svc.update_document(pid, doc.id, {"document_ref": f"CDE-{doc.kind}", "state": "received"}, actor)
