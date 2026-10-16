# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Commissioning demo seed - a populated Cx register per demo project.

Commissioning shipped routed, permissioned and empty, so every demo project
opened the page on the same "no systems yet" card. This fills it with the
register a commissioning authority actually keeps: seven to sixteen
commissionable systems per project, each with its prefunctional and functional
checklist, the results recorded against those checks, and the deficiencies
raised against the system.

What a reader sees on the screen afterwards is a building being handed over
system by system. Some systems have not been energised yet, some are part way
through their functional tests, some have finished testing and are waiting -
one because a critical deficiency is still open, another because the
commissioning certificate has simply not been issued yet - and some are
commissioned and dated.

The register is coherent rather than merely non-empty:

* every check reads like a check for *that* system. An air handling unit is
  asked about its economiser changeover and a fire alarm panel about its
  detector-to-zone map, because the checks come from a per-system-type
  catalogue rather than one generic list;
* a system's lifecycle label agrees with its own results. Every
  ``commissioned`` system passes :func:`compute_readiness` - the same gate the
  ``commission`` action applies - so nothing on the screen claims a system was
  signed off while an item is still open or a critical deficiency unresolved;
* a functional item that failed has a matching open deficiency, and a closed
  deficiency carries its resolution, its closer and its closing date.

Dates are anchored to the run date, never hardcoded, so a demo opened a year
from now still shows a building commissioned over the last few months.

Idempotent per project: a project that already carries a commissionable system
is left untouched, so a re-run never doubles the register.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissioning import seed_texts_de as de_texts
from app.modules.commissioning.models import CxChecklist, CxChecklistItem, CxIssue, CxSystem
from app.modules.commissioning.validators import (
    ITEM_FAIL,
    ITEM_NA,
    ITEM_PASS,
    ITEM_PENDING,
    compute_readiness,
)

logger = logging.getLogger(__name__)

_SEED = 42

# Lifecycle statuses (the module's own vocabulary, see validators.SYSTEM_STATUSES).
_NOT_STARTED = "not_started"
_IN_PROGRESS = "in_progress"
_TESTS_COMPLETE = "tests_complete"
_COMMISSIONED = "commissioned"
_LIFECYCLES = frozenset({_NOT_STARTED, _IN_PROGRESS, _TESTS_COMPLETE, _COMMISSIONED})

# Checklist kinds. Only ``functional`` items gate readiness.
_PREFUNCTIONAL = "prefunctional"
_FUNCTIONAL = "functional"

# Deficiency vocabulary.
_ISSUE_OPEN = "open"
_ISSUE_CLOSED = "closed"
_SEVERITIES = ("low", "medium", "high", "critical")

# How many systems a project gets, by its position among the demo projects being
# seeded rather than drawn from its id: two demo projects opened side by side
# have to show two different buildings, and a draw hands two of them the same
# count often enough that a two-project test would stay green. Every value here
# is distinct and the tuple is longer than the demo estate, so no two demo
# projects can render the same sized register.
_SYSTEM_COUNTS = (11, 8, 13, 9, 12, 10, 14, 7, 15, 16)

# The lifecycle a system is in, by its position in the project's own list. Fixed
# rather than drawn so every project shows all four states, including the two
# that teach the gate: a system whose tests are done but whose critical
# deficiency is open, and one that is ready and simply not certified yet.
_LIFECYCLE_ORDER = (
    _COMMISSIONED,
    _IN_PROGRESS,
    _TESTS_COMPLETE,
    _IN_PROGRESS,
    _NOT_STARTED,
    _COMMISSIONED,
    _TESTS_COMPLETE,
    _IN_PROGRESS,
)

# A "tests complete" system alternates between the two honest reasons it is not
# yet commissioned: an open critical deficiency, or nothing but the certificate.
# Counted over the tests-complete systems themselves, not over every position in
# the register: every position that lands on ``tests_complete`` is an even one,
# so alternating on position parity would only ever produce the first reason and
# the ready-and-uncertified system would never appear on any project.
_BLOCKED_BY_CRITICAL = 0

#: Per system type: (tag prefix, name templates, locations, prefunctional checks,
#: functional checks). The checks are what makes a checklist belong to its
#: system - a generic list would read as filler on a screenshot.
_SYSTEM_CATALOGUE: dict[str, dict[str, tuple[str, ...]]] = {
    "hvac": {
        "tags": ("AHU", "FCU", "CHW"),
        "names": (
            "Air handling unit {n} - office floors",
            "Fan coil circuit {n} - open plan",
            "Chilled water circuit {n}",
        ),
        "locations": ("Roof plant room", "Level 3 riser", "Basement plant room", "Level 6 plant room"),
        "prefunctional": (
            "Unit installed to the approved shop drawings, with the specified service clearances free.",
            "Ductwork cleaned, pressure tested and leakage within the specified class.",
            "Filters fitted, of the specified grade, and the pressure differential switch set.",
            "Vibration isolators loaded correctly and shipping restraints removed.",
            "Motor rotation, current draw and overload settings checked against the nameplate.",
            "Drain pans fall to the outlet and the condensate trap is charged.",
        ),
        "functional": (
            "Supply air temperature holds setpoint within 1 K over a thirty minute run.",
            "Economiser changes over at the scheduled outdoor condition and returns cleanly.",
            "Fan ramps across its full speed range without hunting or nuisance alarm.",
            "Smoke detection stops the unit and the damper drives to its safe position.",
            "Air volumes balanced to the design schedule within the specified tolerance.",
            "Setpoint reset and night setback follow the written control narrative.",
        ),
    },
    "electrical": {
        "tags": ("DB", "MSB", "GEN"),
        "names": (
            "Distribution board {n} - office floors",
            "Main switchboard {n}",
            "Standby generator {n}",
        ),
        "locations": ("Main intake room", "Level 2 electrical riser", "Substation", "Basement switchroom"),
        "prefunctional": (
            "Circuits identified, labelled and matched to the as-installed schedule.",
            "Torque settings on busbar and cable terminations checked and marked.",
            "Insulation resistance and earth continuity measured on every final circuit.",
            "Protective device settings match the discrimination study.",
            "Enclosure IP rating intact and all unused gland plates blanked.",
        ),
        "functional": (
            "Phase rotation and phase balance verified under load.",
            "Protective devices trip within the times required by the discrimination study.",
            "Changeover to standby supply completes inside the contracted break time.",
            "Load bank test held at full rated load for the specified duration.",
            "Metering reports the measured load to the monitoring system within tolerance.",
        ),
    },
    "fire": {
        "tags": ("FA", "SPR", "SMK"),
        "names": (
            "Fire alarm panel {n} - main zone group",
            "Sprinkler zone {n}",
            "Smoke control system {n}",
        ),
        "locations": ("Fire control room", "Level 1 lobby", "Sprinkler valve room", "Stair core B"),
        "prefunctional": (
            "Detector and call point addresses match the as-installed zone map.",
            "Cable type, segregation and fire rating verified against the specification.",
            "Sprinkler pipework flushed, pressure tested and hydraulically signed off.",
            "Batteries sized, installed and the standby duration calculated.",
            "Interfaces to lifts, dampers and door holders wired and terminated.",
        ),
        "functional": (
            "Every detector and call point raises the correct zone at the panel.",
            "Sounder levels meet the specified sound pressure in each occupied area.",
            "Cause and effect matrix executed in full, including lift homing.",
            "Smoke control fans reach design flow and the stair pressure stays in band.",
            "Panel runs the full standby duration on battery and recharges within specification.",
        ),
    },
    "plumbing": {
        "tags": ("DHW", "CWS", "DRN"),
        "names": (
            "Domestic hot water plant {n}",
            "Cold water service riser {n}",
            "Above ground drainage stack {n}",
        ),
        "locations": ("Basement tank room", "Level 4 riser", "Roof plant room", "Core A riser"),
        "prefunctional": (
            "Pipework pressure tested and held for the specified period without loss.",
            "System flushed, chlorinated and the water sample results received.",
            "Insulation and vapour barrier continuous, with valves and flanges boxed.",
            "Valve schedule matches the as-installed layout and every valve is labelled.",
            "Expansion vessels charged to the calculated cold fill pressure.",
        ),
        "functional": (
            "Hot water reaches the specified temperature at the furthest outlet inside a minute.",
            "Thermostatic mixing valves deliver within the safe temperature band.",
            "Booster set maintains pressure across the design flow range.",
            "Drainage stack passes the air test with no loss of trap seal.",
            "Legionella control regime demonstrated over a full cycle.",
        ),
    },
    "mechanical": {
        "tags": ("BLR", "PMP", "HX"),
        "names": (
            "Boiler plant {n}",
            "Pump set {n} - heating primary",
            "Heat exchanger {n}",
        ),
        "locations": ("Basement plant room", "Roof plant room", "Energy centre", "Level 5 plant room"),
        "prefunctional": (
            "Plant set out, levelled and anchored to the structural drawing.",
            "Flue and combustion air routes complete and clear of obstruction.",
            "Water treatment dosed and the system water sample within specification.",
            "Strainers cleaned after flushing and differential pressures logged.",
            "Safety valves and pressure relief set to the calculated pressures.",
        ),
        "functional": (
            "Plant modulates across its firing range and holds flow temperature.",
            "Pumps achieve design duty and the standby pump takes over on failure.",
            "Heat exchanger reaches design duty at the scheduled approach temperature.",
            "Interlocks shut the plant down safely on flow failure and overtemperature.",
            "Seasonal control strategy demonstrated against the written narrative.",
        ),
    },
    "controls": {
        "tags": ("BMS", "CTL", "MET"),
        "names": (
            "Building management system - {n} field panel",
            "Controls network segment {n}",
            "Energy metering system {n}",
        ),
        "locations": ("Control room", "Level 3 plant room", "Main intake room", "Roof plant room"),
        "prefunctional": (
            "Every point on the datapoint schedule installed, addressed and reading.",
            "Field devices calibrated against a reference instrument and the offsets logged.",
            "Network segments terminated and the topology matches the as-installed drawing.",
            "Graphics reflect the as-installed plant, with no orphan or duplicate point.",
            "Alarm thresholds loaded from the approved alarm schedule.",
        ),
        "functional": (
            "Each control loop is stable, with no hunting over a two hour observation.",
            "Time schedules and setback modes execute exactly as the narrative describes.",
            "Alarms raise, latch and clear correctly at the panel and at the head end.",
            "Trend logging records every point in the schedule at the required interval.",
            "Head end recovers the full point list after a controlled power failure.",
        ),
    },
    "elevator": {
        "tags": ("LFT", "ESC"),
        "names": (
            "Passenger lift {n}",
            "Goods lift {n}",
            "Escalator {n}",
        ),
        "locations": ("Core A", "Core B", "Service core", "Retail atrium"),
        "prefunctional": (
            "Guide rails aligned within the manufacturer's stated tolerance.",
            "Shaft clear of building debris, with lighting and shaft ventilation complete.",
            "Machine room environment within the temperature range the drive requires.",
            "Landing doors set, gibs engaged and the door gap measured at every floor.",
            "Safety gear and overspeed governor tested and certified.",
        ),
        "functional": (
            "Levelling accuracy at every floor within the specified tolerance, loaded and empty.",
            "Full load and overload tests completed and countersigned.",
            "Fire service and evacuation modes behave as the cause and effect matrix requires.",
            "Emergency communication reaches the monitoring centre and identifies the car.",
            "Ride quality measured, with vibration and noise inside the contract limits.",
        ),
    },
    "security": {
        "tags": ("ACS", "CCTV", "INT"),
        "names": (
            "Access control system {n}",
            "Camera system {n} - public areas",
            "Intruder detection zone {n}",
        ),
        "locations": ("Security control room", "Main reception", "Loading bay", "Level 1 lobby"),
        "prefunctional": (
            "Door hardware, readers and locks installed and matched to the door schedule.",
            "Camera positions and fields of view agreed against the coverage drawing.",
            "Cabling tested, labelled and segregated from the power containment.",
            "Head end servers built, patched and backed up before handover.",
            "Access levels and card groups loaded from the approved matrix.",
        ),
        "functional": (
            "Every controlled door grants, denies and logs against the access matrix.",
            "Fire alarm releases the controlled doors on the designated escape routes.",
            "Recorded footage meets the retention period and identification quality required.",
            "Intruder zones set, unset and report to the monitoring centre.",
            "System recovers its full configuration after a controlled restart.",
        ),
    },
    "other": {
        "tags": ("PV", "RWH", "EVC"),
        "names": (
            "Photovoltaic array {n}",
            "Rainwater harvesting plant {n}",
            "Electric vehicle charging bank {n}",
        ),
        "locations": ("Roof", "Basement tank room", "Car park level -1", "Plant yard"),
        "prefunctional": (
            "Array or plant installed to the approved layout and mechanically secured.",
            "Isolation, labelling and signage complete for a safe first energisation.",
            "Metering installed and communicating to the monitoring system.",
            "Manufacturer commissioning sheets received and filed with the record set.",
            "Protection settings agreed with the network operator where required.",
        ),
        "functional": (
            "Output measured against the design yield for the observed conditions.",
            "Export and import limits behave as the connection agreement requires.",
            "Plant shuts down and restarts safely on loss and return of supply.",
            "Monitoring reports live output and cumulative totals to the head end.",
            "Full duty cycle demonstrated over an uninterrupted operating period.",
        ),
    },
}

# The order the types are handed out, so a project reads as a building rather
# than as one trade repeated. Rotated per project by the project's position.
_TYPE_ORDER = (
    "hvac",
    "electrical",
    "fire",
    "controls",
    "plumbing",
    "mechanical",
    "elevator",
    "security",
    "hvac",
    "electrical",
    "other",
    "fire",
    "controls",
)

# Deficiencies raised against a system, by severity. Factual and about the work.
_ISSUE_TEXT: dict[str, tuple[str, ...]] = {
    "critical": (
        "Safety interlock does not shut the plant down on the simulated fault; retest required after rework.",
        "Cause and effect step fails: the interface does not drive the connected plant to its safe position.",
        "Measured performance is outside the contract limit and the plant cannot be accepted as installed.",
    ),
    "high": (
        "Control loop hunts around setpoint and has not held stable over the observation period.",
        "Standby unit does not take over automatically on failure of the duty unit.",
        "Alarm reaches the panel but is not presented at the head end.",
    ),
    "medium": (
        "Two field devices read outside the calibration tolerance and need re-calibrating.",
        "Access for maintenance is obstructed by later trade works and has to be released.",
        "Labelling does not match the as-installed schedule in one section.",
    ),
    "low": (
        "Graphics page shows a superseded plant arrangement and needs updating.",
        "One trend log is recording at the wrong interval.",
        "Record drawing has not yet been marked up with the final valve positions.",
    ),
}

_ISSUE_RESOLUTION = (
    "Reworked by the installing contractor and retested in the presence of the commissioning engineer.",
    "Corrected on site and verified against the original test sheet.",
    "Settings amended, the affected test repeated in full and the result recorded.",
)


_PREFUNCTIONAL_DESCRIPTION = "Static installation checks completed before the system is energised."
_FUNCTIONAL_DESCRIPTION = "Dynamic performance tests witnessed by the commissioning authority."


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the register."""
    return random.Random(f"{_SEED}:{project_id}")


def _iso(moment: datetime) -> str:
    """ISO-8601 with the microseconds dropped.

    The timestamp columns here are ``String(32)`` and a microsecond ISO string
    is exactly 32 characters, leaving no margin: PostgreSQL rejects the overflow
    where SQLite would truncate it. Dropping microseconds is 25 characters and
    is all a commissioning record needs anyway.
    """
    return moment.replace(microsecond=0).isoformat()


def _system_count(ordinal: int) -> int:
    """How many systems this project gets, kept apart from its neighbours."""
    return _SYSTEM_COUNTS[ordinal % len(_SYSTEM_COUNTS)]


def _lifecycle_plan(total: int) -> list[str]:
    """Lifecycle status per system (by position), covering all four states."""
    return [_LIFECYCLE_ORDER[i % len(_LIFECYCLE_ORDER)] for i in range(total)]


def _item_statuses(
    rng: random.Random,
    lifecycle: str,
    count: int,
    *,
    functional: bool,
) -> list[str]:
    """Result per checklist item, derived from the system's lifecycle.

    This is where the register's coherence is decided. A system that has not
    started has nothing recorded; one in progress is part way down its
    prefunctional list and barely into its functional tests, and the test it
    stopped on has failed; one whose tests are complete, and one that is
    commissioned, have every applicable item passed with a single item marked
    not applicable.
    """
    if lifecycle == _NOT_STARTED:
        return [ITEM_PENDING] * count

    if lifecycle == _IN_PROGRESS:
        done = max(1, round(count * (0.7 if not functional else 0.4)))
        statuses = [ITEM_PASS] * done + [ITEM_PENDING] * (count - done)
        # One item on the prefunctional list does not apply to this arrangement.
        if not functional and count >= 4:
            statuses[done - 1] = ITEM_NA
        # The functional test the system stopped on failed. Without this no
        # checklist item anywhere in the estate ever reads ``fail``, and the
        # readiness breakdown shows a failed count that is always zero.
        if functional and count > done:
            statuses[done] = ITEM_FAIL
        return statuses

    # tests_complete / commissioned: every applicable item has passed. Exactly
    # one item is not applicable, which keeps ``applicable`` above zero so the
    # readiness figure stays defined.
    statuses = [ITEM_PASS] * count
    if count >= 4:
        statuses[rng.randrange(count)] = ITEM_NA
    return statuses


def _issue_plan(
    rng: random.Random,
    lifecycle: str,
    tests_complete_index: int,
    *,
    has_failed_item: bool,
) -> list[tuple[str, str]]:
    """``(severity, status)`` for each deficiency raised against a system.

    A system that has not started has no deficiencies. A commissioned system may
    carry deficiencies but every one of them is closed - that is the gate. A
    system whose tests are complete alternates between the two reasons it is not
    commissioned: an open critical deficiency, or none at all and simply no
    certificate yet.

    Args:
        rng: Per-project generator.
        lifecycle: The system's status.
        tests_complete_index: How many ``tests_complete`` systems this project
            has already produced, so the alternation runs over those systems
            rather than over their positions in the register.
        has_failed_item: Whether the system's functional list carries a failed
            test. When it does, the deficiency explaining it is raised at high
            severity and left open, so no failed test on any screen is missing
            the entry that accounts for it.
    """
    if lifecycle == _NOT_STARTED:
        return []
    if lifecycle == _COMMISSIONED:
        return [(rng.choice(("low", "medium", "high")), _ISSUE_CLOSED) for _ in range(rng.randint(1, 2))]
    if lifecycle == _TESTS_COMPLETE:
        if tests_complete_index % 2 == _BLOCKED_BY_CRITICAL:
            return [("critical", _ISSUE_OPEN), (rng.choice(("low", "medium")), _ISSUE_CLOSED)]
        return [(rng.choice(("low", "medium")), _ISSUE_CLOSED)]
    # in_progress: live work, so a mix that is mostly open.
    first = "high" if has_failed_item else rng.choice(_SEVERITIES[:3])
    plan = [(first, _ISSUE_OPEN)]
    plan += [(rng.choice(_SEVERITIES[:3]), _ISSUE_OPEN) for _ in range(rng.randint(0, 1))]
    if rng.random() < 0.5:
        plan.append((rng.choice(("low", "medium")), _ISSUE_CLOSED))
    return plan


async def _actors(session: AsyncSession, owner_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(commissioning_engineer_id, authority_id)`` as strings.

    Results are recorded by one account and the commissioning signed off by
    another where the estate has two, because a system is never certified by the
    person who ran the test. Falls back to the project owner for either side.
    """
    engineer = authority = str(owner_id)
    try:
        from app.modules.users.models import User

        rows = (await session.execute(select(User.id, User.role).order_by(User.email))).all()
    except Exception:
        logger.debug("User lookup unavailable; commissioning records signed by the project owner")
        return engineer, authority
    by_role: dict[str, str] = {}
    for uid, role in rows:
        by_role.setdefault(str(role or ""), str(uid))
    engineer = by_role.get("editor") or engineer
    authority = by_role.get("manager") or by_role.get("admin") or authority
    return engineer, authority


#: The note shown beside a result that is not a plain pass. A failed test with
#: no note reads as an unexplained red row.
_ITEM_NOTES = {
    ITEM_NA: "Not applicable to this arrangement.",
    ITEM_FAIL: "Measured performance outside the specified band. Retest after the deficiency is cleared.",
}


def _is_german(locale: str | None) -> bool:
    """Whether the project reads German, so the register is written in German."""
    return (locale or "").lower().replace("_", "-").split("-")[0] == "de"


def _story_systems(story: dict[str, Any], locale: str) -> list[dict[str, str]]:
    """The systems a pack story names for a project, in order; an entry that is not usable is skipped.

    A story entry is ``{"type", "tag", "name", "location", "description", "status"}`` with the texts as plain
    strings or ``{locale: text}`` maps. ``status`` is optional and one of the four lifecycles: a project still
    in its pit stage has no system under test, so its story says ``not_started``. Without it the system takes
    the lifecycle of its position. Without a usable entry the project takes the built-in catalogue of systems.
    """
    from app.modules.project_governance.public import story_text

    out: list[dict[str, str]] = []
    raw = story.get("systems") if isinstance(story, dict) else None
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        system_type = item.get("type")
        name = story_text(item.get("name"), locale) if isinstance(item.get("name"), (str, dict)) else ""
        if system_type not in _SYSTEM_CATALOGUE or not isinstance(name, str) or not name.strip():
            logger.info("Cx demo story: system %r ignored", item.get("tag") or item.get("name"))
            continue
        entry = {"type": system_type, "name": name.strip()[:255]}
        for key, limit in (("tag", 100), ("location", 255), ("description", 2000)):
            value = item.get(key)
            text = story_text(value, locale) if isinstance(value, (str, dict)) else ""
            if isinstance(text, str) and text.strip():
                entry[key] = text.strip()[:limit]
        status = item.get("status")
        if status in _LIFECYCLES:
            entry["status"] = status
        elif status is not None:
            logger.info("Cx demo story: status %r of system %r ignored", status, entry.get("tag") or name)
        out.append(entry)
    return out


def _build_items(
    rng: random.Random,
    checklist_id: uuid.UUID,
    checks: Sequence[str],
    statuses: Sequence[str],
    *,
    verified_by: str,
    window_start: datetime,
    notes: dict[str, str] | None = None,
) -> list[CxChecklistItem]:
    """One checklist's items, with a result stamp only where a result exists."""
    items: list[CxChecklistItem] = []
    for index, (description, item_status) in enumerate(zip(checks, statuses, strict=True)):
        recorded = item_status != ITEM_PENDING
        verified_at = _iso(window_start + timedelta(days=index, hours=9 + rng.randrange(6))) if recorded else None
        items.append(
            CxChecklistItem(
                checklist_id=checklist_id,
                sequence=index + 1,
                description=description,
                status=item_status,
                result_note=(notes or _ITEM_NOTES).get(item_status),
                verified_by=verified_by if recorded else None,
                verified_at=verified_at,
                metadata_={},
            )
        )
    return items


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    ordinal: int,
    story: dict[str, Any] | None = None,
    locale: str | None = None,
) -> dict[str, int]:
    """Seed one project's Cx register. Returns per-entity counts (zeros when skipped).

    ``story`` is the pack's commissioning story for the project, if any: it names the systems the building
    really has. ``locale`` selects the wording of checks and deficiencies.
    """
    empty = {"projects": 0, "systems": 0, "checklists": 0, "items": 0, "issues": 0}

    already = (
        (await session.execute(select(CxSystem.id).where(CxSystem.project_id == project_id).limit(1))).scalars().first()
    )
    if already is not None:
        return empty

    rng = _rng_for(project_id)
    engineer, authority = await _actors(session, owner_id)
    german = _is_german(locale)
    named = _story_systems(story or {}, locale or "en")
    total = len(named) or _system_count(ordinal)
    lifecycles = _lifecycle_plan(total)
    now = datetime.now(UTC)
    counts = {"projects": 1, "systems": 0, "checklists": 0, "items": 0, "issues": 0}
    tests_complete_seen = 0

    for position in range(total):
        entry = named[position] if named else None
        system_type = entry["type"] if entry else _TYPE_ORDER[(position + ordinal) % len(_TYPE_ORDER)]
        spec = dict(_SYSTEM_CATALOGUE[system_type])
        if german:
            spec["prefunctional"], spec["functional"] = de_texts.CHECKS[system_type]
        lifecycle = (entry or {}).get("status") or lifecycles[position]
        unit_no = position + 1
        variant = position % len(spec["names"])
        description = (
            de_texts.SYSTEM_DESCRIPTION
            if german
            else f"Commissionable {system_type.replace('_', ' ')} system, "
            f"handed over as part of the building services acceptance."
        )

        system = CxSystem(
            project_id=project_id,
            name=entry["name"] if entry else spec["names"][variant].format(n=unit_no),
            system_type=system_type,
            tag=(entry or {}).get("tag") or f"{spec['tags'][variant % len(spec['tags'])]}-{unit_no:02d}",
            location=(entry or {}).get("location") or spec["locations"][position % len(spec["locations"])],
            description=(entry or {}).get("description") or description,
            status=lifecycle,
            created_by=engineer,
            metadata_={},
        )
        session.add(system)
        await session.flush()
        counts["systems"] += 1

        # Prefunctional checks run first, functional tests behind them. The
        # window walks backwards from now by the system's position so the whole
        # register reads as a building commissioned over the past few months.
        window_start = now - timedelta(days=90 - position * 4)
        functional_statuses: list[str] = []

        for kind, checks in ((_PREFUNCTIONAL, spec["prefunctional"]), (_FUNCTIONAL, spec["functional"])):
            checklist = CxChecklist(
                system_id=system.id,
                kind=kind,
                title=(
                    (de_texts.PREFUNCTIONAL_TITLE if german else "Prefunctional checklist")
                    if kind == _PREFUNCTIONAL
                    else (de_texts.FUNCTIONAL_TITLE if german else "Functional performance test")
                )
                + f" - {system.tag}",
                description=(
                    (de_texts.PREFUNCTIONAL_DESCRIPTION if german else _PREFUNCTIONAL_DESCRIPTION)
                    if kind == _PREFUNCTIONAL
                    else (de_texts.FUNCTIONAL_DESCRIPTION if german else _FUNCTIONAL_DESCRIPTION)
                ),
                created_by=engineer,
                metadata_={},
            )
            session.add(checklist)
            await session.flush()
            counts["checklists"] += 1

            statuses = _item_statuses(rng, lifecycle, len(checks), functional=(kind == _FUNCTIONAL))
            if kind == _FUNCTIONAL:
                functional_statuses = list(statuses)
            items = _build_items(
                rng,
                checklist.id,
                checks,
                statuses,
                verified_by=engineer,
                window_start=window_start + (timedelta(days=0) if kind == _PREFUNCTIONAL else timedelta(days=14)),
                notes=de_texts.ITEM_NOTES if german else None,
            )
            session.add_all(items)
            counts["items"] += len(items)

        # Drawn once. The commission gate below reads the same plan, and a
        # second draw from the same RNG would hand it a different one - the
        # register would then be signed off against deficiencies it does not
        # have, which is exactly the incoherence this seeder exists to avoid.
        issue_plan = _issue_plan(
            rng,
            lifecycle,
            tests_complete_seen,
            has_failed_item=ITEM_FAIL in functional_statuses,
        )
        if lifecycle == _TESTS_COMPLETE:
            tests_complete_seen += 1
        for severity, issue_status in issue_plan:
            closed = issue_status == _ISSUE_CLOSED
            session.add(
                CxIssue(
                    system_id=system.id,
                    description=rng.choice((de_texts.ISSUES if german else _ISSUE_TEXT)[severity]),
                    severity=severity,
                    status=issue_status,
                    resolution=(rng.choice(de_texts.RESOLUTIONS if german else _ISSUE_RESOLUTION) if closed else None),
                    raised_by=engineer,
                    closed_by=(authority if closed else None),
                    closed_at=(_iso(window_start + timedelta(days=21, hours=11)) if closed else None),
                    metadata_={},
                )
            )
            counts["issues"] += 1

        if lifecycle == _COMMISSIONED:
            # The gate the ``commission`` action applies, applied here too. A
            # plan that could not pass it is a bug in this seeder, not data to
            # ship: the system is left at tests_complete instead of claiming a
            # sign-off the module itself would have refused.
            open_critical = sum(
                1 for severity, issue_status in issue_plan if severity == "critical" and issue_status == _ISSUE_OPEN
            )
            readiness = compute_readiness(functional_statuses, open_critical)
            if readiness["can_commission"]:
                system.status = _COMMISSIONED
                system.commissioned_at = _iso(window_start + timedelta(days=28, hours=10))
                system.commissioned_by = authority
            else:
                system.status = _TESTS_COMPLETE
                logger.debug(
                    "Cx demo: system %s left at tests_complete, readiness gate refused it",
                    system.tag,
                )
            session.add(system)

    await session.flush()
    return counts


async def seed_commissioning_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the commissioning register for the given demo projects.

    Afterwards the Commissioning page of every seeded demo project shows a
    building being accepted system by system: a systems list spread across
    ``not_started`` / ``in_progress`` / ``tests_complete`` / ``commissioned``,
    each system carrying its own prefunctional and functional checklists with
    results recorded against checks that belong to that kind of plant, and the
    deficiency list that explains why the systems still waiting are waiting.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider. A project is skipped when it is not a
            demo project, or when it already carries a commissionable system, so
            a customer's live project is never written to and a re-run never
            doubles the register.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "systems": 0, "checklists": 0, "items": 0, "issues": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.core.demo_marker import demo_id_of
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.metadata_, Project.locale).where(Project.id.in_(ids))
        )
    ).all()
    # ``enrich_all`` hands this seeder every project in the database, which on a
    # real installation means a customer's own work. Only the demo estate is
    # ours to fill, and the demo project seeder marks its rows.
    #
    # The marker is ``demo_id`` and not ``is_demo``. The ten template projects
    # stamp both, but the flagship reference project is installed from its own
    # baked fixture and carries only ``demo_id``, so a gate on ``is_demo`` skips
    # the one project users actually land on.
    demo = {
        pid: (owner, meta, locale)
        for pid, owner, meta, locale in rows
        if isinstance(meta, dict) and str(meta.get("demo_id") or "").strip()
    }
    # Numbered within the demo estate, not within the caller's list. The list is
    # every project in the database, so on an installation that also carries a
    # customer's own work the same demo project would otherwise land on a
    # different position - and a different sized register - than on a fresh one.
    demo_ids = [pid for pid in ids if pid in demo]

    for ordinal, project_id in enumerate(demo_ids):
        owner_id, meta, locale = demo[project_id]
        # What the active pack says this building has; without a pack story the built-in systems are used.
        story = demo_module_story(demo_id_of(meta), "commissioning")
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded
            # costs only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owner_id, ordinal, story, locale)
        except Exception:
            logger.warning("Commissioning demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
