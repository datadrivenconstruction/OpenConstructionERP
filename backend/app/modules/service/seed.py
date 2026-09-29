# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo-data seeder for the Service & Maintenance module.

Function ``seed_service_demo(session, project_ids)`` populates:
    - 3 SLA definitions (gold / silver / bronze)
    - one service contract per demo project, cycling a list of fictional customers
    - 80 customer assets distributed across the contracts
    - 30 open tickets (mix of priorities + assignments)
    - 200 historical work orders in ``billed`` state with line items
    - 20 active PPM schedules

Contracts are the module's only project-scoped row. Tickets, work orders and
assets reach a project through their contract, so a contract with no project
takes everything under it out of the per-project view as well.

Ticket timing is drawn against each contract's own SLA tier rather than a
fixed window, so the estate reports a believable spread of met, near-miss and
breached rather than a uniform 100% breach. See :data:`_SLA_OUTCOME_MIX`.

Idempotent only at the *no-existing-rows* level: if any contract already
exists for the seeded customer ids the function returns early.

Never auto-executed - call it explicitly from a CLI / Alembic data-only
migration if you want the demo data.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.service.models import (
    AssetInspectionChecklist,
    DebriefReport,
    ServiceAsset,
    ServiceContract,
    ServiceRecurringSchedule,
    ServiceSchedule,
    ServiceTicket,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
    SLADefinition,
)

logger = logging.getLogger(__name__)

# What each tier actually promises, in the words a customer would read on the
# contract. The seeder stored "Demo gold SLA tier", which names the tier twice
# and says nothing about the commitment, on a screen whose whole subject is
# whether the commitment was met.
_SLA_TEXT: dict[str, str] = {
    "gold": "One hour to respond, four hours to resolve. Critical plant, cover around the clock.",
    "silver": "Four hours to respond, one working day to resolve. Business hours cover.",
    "bronze": "Eight hours to respond, three working days to resolve. Standard cover.",
}

# Faults a building-services desk actually logs. One list serves the open and
# the closed tickets so the register reads consistently; the asset each one is
# raised against comes from the row, so repeated fault types across different
# assets look like the recurrence they would be in real life.
_FAULTS: tuple[str, ...] = (
    "Cold aisle drifting above setpoint overnight",
    "Condensate tray overflowing onto the floor",
    "Compressor short-cycling on the CO2 pack",
    "Sliding entrance door not closing fully",
    "Air handling unit left running on manual override",
    "Lighting circuit tripping the RCD after close",
    "Heat pump reporting a low-pressure fault",
    "Noise complaint from the staff area ventilation",
    "Freezer cabinet defrost cycle not completing",
    "Building management system lost comms with the chiller",
    "Water leak traced to a cabinet drain",
    "Emergency lighting test failed on two fittings",
)

# Localised customer names - small, neutral list spanning EN/DE/RU markets.
# Each maintenance customer with the address its Contact record carries. One
# mapping rather than two parallel lists, so a name cannot end up without an
# address. ``.example`` is reserved by RFC 2606 and is what the rest of the
# seeded estate uses, which keeps these off a real company's domain.
_CUSTOMER_CONTACT_EMAILS: dict[str, str] = {
    "Zellbrandt Wartung GmbH": "service@zellbrandt-wartung.example",
    "ООО Тепло-Сервис": "dispatch@teplo-servis.example",
    "Northwind Property Group": "estates@northwind-property.example",
    "Aurora Tower Management": "building@aurora-tower.example",
}

_CUSTOMER_NAMES: list[str] = list(_CUSTOMER_CONTACT_EMAILS)

# How the seed names each contract. ``seed_service_demo`` writes contracts from
# these and ``seeded_row_ids`` recognises them by the same helpers.
_CONTRACT_DESCRIPTION = "Planned maintenance and reactive callout cover for the site plant."


def _contract_number(idx: int) -> str:
    return f"SC-{idx + 1:02d}"


def _contract_title(idx: int) -> str:
    return f"Service contract - {_CUSTOMER_NAMES[idx % len(_CUSTOMER_NAMES)]}"


_ASSET_TYPES: list[str] = [
    "boiler",
    "chiller",
    "ahu",
    "fan_coil",
    "lift",
    "generator",
    "ups",
    "fire_panel",
    "bms_controller",
    "heat_pump",
]

_ROOT_CAUSE_CATEGORIES: list[str] = [
    "wear_and_tear",
    "operator_error",
    "design_flaw",
    "environmental",
    "consumable_depleted",
]

# How a maintenance desk actually performs against its own SLA, expressed as
# a fraction of the target window. The seeder used a fixed four-hour due date
# against a one-to-twenty-four-hour resolution, so every historical ticket
# breached and the register reported 100% failure - which reads as a broken
# feature rather than a struggling contractor.
#
# Each entry is (weight, low, high): the elapsed time is drawn as
# ``target * uniform(low, high)``. Anything below 1.0 met the target, the
# 0.82-0.99 band is the "approaching" state the dashboard highlights, and only
# the last band is a genuine breach.
_SLA_OUTCOME_MIX: tuple[tuple[int, float, float], ...] = (
    (72, 0.10, 0.75),  # comfortably inside the window
    (18, 0.82, 0.99),  # ran close to the wire
    (10, 1.05, 2.20),  # breached
)


def _sla_elapsed_fraction(rng: random.Random) -> float:
    """Draw how much of an SLA window a ticket consumed.

    Returns a multiplier to apply to the target window. Values below ``1.0``
    met the SLA; at or above ``1.0`` the ticket breached. The mix is
    :data:`_SLA_OUTCOME_MIX`, so a seeded estate reports mostly-green with a
    minority of breaches rather than a uniform wall of red.
    """
    weights = [w for w, _, _ in _SLA_OUTCOME_MIX]
    low, high = rng.choices(
        [(lo, hi) for _, lo, hi in _SLA_OUTCOME_MIX],
        weights=weights,
        k=1,
    )[0]
    return rng.uniform(low, high)


def _sla_offsets(sla: SLADefinition, priority: str) -> tuple[timedelta, timedelta]:
    """Return the ``(response, resolution)`` windows this tier promises.

    Delegates to the module's own
    :func:`app.modules.service.service.compute_sla_response_and_resolution`
    rather than re-reading ``severity_levels`` here, so the target the seeder
    measures a ticket against is the same target the running product computes
    for it. Reading the override dict a second way is how the seeded estate
    ends up disagreeing with the screen that reports on it.
    """
    from app.modules.service.service import compute_sla_response_and_resolution

    base = datetime(2000, 1, 1, tzinfo=UTC)
    response_due, resolution_due = compute_sla_response_and_resolution(base, sla, priority=priority)
    # ``sla`` is never None here, so neither return value can be.
    return (
        (response_due or base) - base,
        (resolution_due or base) - base,
    )


async def _customer_id_for(session: AsyncSession, idx: int) -> uuid.UUID:
    """Resolve the i-th demo customer's ``Contact`` id, creating it on demand.

    Kept tolerant of running outside a fully-bootstrapped DB: when the
    Contact table does not yet contain the seed customer we generate a
    deterministic UUID and the FK is satisfied at the application layer
    (FK ON DELETE RESTRICT triggers only on actual DELETE attempts).
    """
    name = _CUSTOMER_NAMES[idx % len(_CUSTOMER_NAMES)]
    try:
        from app.modules.contacts.models import Contact

        stmt = select(Contact).where(Contact.company_name == name).limit(1)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing.id
        contact = Contact(
            contact_type="customer",
            company_name=name,
            primary_email=_CUSTOMER_CONTACT_EMAILS[name],
            is_active=True,
        )
        session.add(contact)
        await session.flush()
        return contact.id
    except Exception:
        # Fallback: deterministic UUID derived from the customer name. The FK
        # is RESTRICT-on-delete - orphan ids are tolerated for demos.
        logger.warning("Could not resolve/create demo Contact; using synthetic UUID")
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"openconstructionerp/service/demo/{name}")


async def _project_currencies(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Return ``{project_id: currency}`` for the projects that declare one.

    A contract that sits on a project prints its own currency on a screen that
    prints the project's, so the two have to agree or the estate reads as
    careless. ``Project.currency`` defaults to the empty string, so a project
    that declares nothing is simply absent from this mapping and the caller
    falls back to its own list rather than stamping a guess.
    """
    if not project_ids:
        return {}
    try:
        from app.modules.projects.models import Project

        rows = (await session.execute(select(Project.id, Project.currency).where(Project.id.in_(project_ids)))).all()
    except Exception:  # noqa: BLE001 - a currency lookup must not abort the seeder
        logger.warning("Project currency lookup failed; contracts fall back to the declared list", exc_info=True)
        return {}
    return {row[0]: row[1] for row in rows if row[1]}


async def seed_service_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Populate the database with deterministic demo Service & Maintenance data.

    ``project_ids`` are the demo projects the contract register is spread
    across, one contract each. Passing none is still valid and produces the
    older tenant-wide register, which the module's own screen shows and the
    per-project tab cannot.

    Returns a dict with row counts of each entity created.
    """
    project_ids = list(project_ids or [])
    rng = random.Random(42)
    # One clock, read once. Taking ``today`` from a second ``now()`` call lets
    # a seed run that straddles midnight date rows one day apart from the
    # timestamps they belong to.
    now = datetime.now(UTC)
    today = now.date()

    counters: dict[str, int] = {
        "sla_definitions": 0,
        "contracts": 0,
        "assets": 0,
        "tickets": 0,
        "work_orders": 0,
        "work_order_items": 0,
        "debriefs": 0,
        "schedules": 0,
        "checklists": 0,
    }

    # Short-circuit: bail out if we already have contracts.
    existing_contracts = (await session.execute(select(ServiceContract).limit(1))).scalar_one_or_none()
    if existing_contracts is not None:
        logger.info("Service demo seed: contracts already exist, skipping")
        return counters

    # ── SLA definitions ──────────────────────────────────────────────────
    slas: list[SLADefinition] = []
    for tier, response, resolution in (
        ("gold", 60, 240),  # 1h response / 4h resolution
        ("silver", 240, 1440),  # 4h / 24h
        ("bronze", 480, 4320),  # 8h / 72h
    ):
        sla = SLADefinition(
            name=tier,
            description=_SLA_TEXT[tier],
            response_time_minutes=response,
            resolution_time_minutes=resolution,
            severity_levels={
                "critical": {"response_time_minutes": max(15, response // 4)},
                "high": {"response_time_minutes": max(30, response // 2)},
                "med": {"response_time_minutes": response},
                "low": {"response_time_minutes": response * 2},
            },
        )
        session.add(sla)
        slas.append(sla)
        counters["sla_definitions"] += 1
    await session.flush()

    # ── Checklists ───────────────────────────────────────────────────────
    checklists: list[AssetInspectionChecklist] = []
    for at in _ASSET_TYPES[:5]:
        cl = AssetInspectionChecklist(
            name=f"{at.title()} routine inspection",
            description=f"Quarterly PPM checklist for {at}",
            asset_type=at,
            items=[
                {"question": "Visual inspection complete?", "type": "bool", "required": True},
                {"question": "Operating noise levels acceptable?", "type": "bool", "required": True},
                {"question": "Note unusual observations", "type": "text", "required": False},
            ],
        )
        session.add(cl)
        checklists.append(cl)
        counters["checklists"] += 1
    await session.flush()

    # ── Contracts (one per demo project) ─────────────────────────────────
    contracts: list[ServiceContract] = []
    contract_statuses = ["active", "active", "active", "draft", "expired"]
    fallback_currencies = ["EUR", "EUR", "RUB", "USD", "GBP"]
    # One contract per project, cycling the customer list, rather than one per
    # customer with no project at all. The register used to leave ``project_id``
    # NULL on every row, which looks right on the flat /service screen and
    # leaves /projects/:id/service empty on every project, so the module read
    # as doing nothing from the one place a visitor arrives at it from.
    #
    # The customer list is still the only place a customer name exists, so it
    # is indexed modulo its own length: a shorter list means repeated customers
    # rather than an IndexError, which is what the previous wording of this
    # comment was protecting and is still true. Same for the status list, which
    # is a shape rather than a register. The currency list is neither and is
    # read only where no project answers - see the contract body below.
    project_currency = await _project_currencies(session, project_ids)
    contract_count = len(project_ids) or len(_CUSTOMER_NAMES)
    for idx in range(contract_count):
        pid = project_ids[idx] if idx < len(project_ids) else None
        customer_id = await _customer_id_for(session, idx)
        status = contract_statuses[idx % len(contract_statuses)]
        # An expired contract whose period runs another six months is a number
        # that does not add up, and it was harmless only while no contract sat
        # on a named project. It does now, so the period follows the status:
        # an expired one ended last month, everything else still has a year to
        # run. The start moves with it so the term stays the same length.
        period_end = today - timedelta(days=30) if status == "expired" else today + timedelta(days=185)
        period_start = period_end - timedelta(days=365)
        # A contract that sits on a project takes the project's currency, and an
        # absent one is an answer rather than a gap. ``Project.currency`` is
        # optional on purpose - the owner has not chosen yet, and the backend
        # refuses to assume a default - so a contract on such a project is left
        # blank too. Stamping the list here would put the seed data on the wrong
        # side of a question the product has already decided, and seed data is
        # the one population that would otherwise never exercise it.
        #
        # The list still answers where there is no project at all, which is the
        # tenant-wide register: nobody there has declined a currency, so nothing
        # is being overruled.
        if pid is not None:
            currency = project_currency.get(pid, "")
        else:
            currency = fallback_currencies[idx % len(fallback_currencies)]
        contract = ServiceContract(
            customer_id=customer_id,
            project_id=pid,
            contract_number=_contract_number(idx),
            title=_contract_title(idx),
            description=_CONTRACT_DESCRIPTION,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            sla_definition_id=slas[idx % len(slas)].id,
            sla_tier=slas[idx % len(slas)].name,
            status=status,
            value=Decimal(rng.randint(20_000, 250_000)),
            currency=currency,
            auto_renew=(idx % 2 == 0),
        )
        session.add(contract)
        contracts.append(contract)
        counters["contracts"] += 1
    await session.flush()

    # ── Assets (80) distributed across contracts ─────────────────────────
    assets: list[ServiceAsset] = []
    for i in range(80):
        contract = contracts[i % len(contracts)]
        at = _ASSET_TYPES[i % len(_ASSET_TYPES)]
        asset = ServiceAsset(
            contract_id=contract.id,
            asset_tag=f"AST-{i + 1:04d}",
            asset_type=at,
            name=f"{at.title()} unit #{i + 1}",
            location=f"Building {chr(65 + (i % 5))} / Level {1 + (i % 4)}",
            manufacturer=rng.choice(
                [
                    "Wendhorst Controls",
                    "Alderkyn Climate",
                    "Vehlmar Electric",
                    "Nishibe Air",
                    "Reidenau Systems",
                ],
            ),
            model=f"M-{rng.randint(100, 9999)}",
            serial=f"SN-{i:06d}-{rng.randint(0, 9999):04d}",
            install_date=(today - timedelta(days=rng.randint(365, 3650))).isoformat(),
            warranty_until=(today + timedelta(days=rng.randint(-365, 730))).isoformat(),
            status="active",
        )
        session.add(asset)
        assets.append(asset)
        counters["assets"] += 1
    await session.flush()

    # Every contract points at one of the three tiers, so the tier a ticket is
    # measured against has to be looked up by id. Picking gold-or-else-silver
    # measured every bronze contract against silver's four-hour promise, which
    # is a different (and much harsher) target than the one the customer bought.
    sla_by_id = {sla.id: sla for sla in slas}

    # ── Open tickets (30) ────────────────────────────────────────────────
    priorities = ["low", "med", "high", "critical"]
    for i in range(30):
        # One pass round the register before drawing, so every contract - and
        # therefore every project - holds at least one open ticket by
        # construction. Thirty drawn over thirteen leaves a given contract
        # empty about one time in ten, and "populated on most runs" is not a
        # property a demo estate can rest on.
        contract = contracts[i] if i < len(contracts) else contracts[rng.randrange(len(contracts))]
        asset = rng.choice([a for a in assets if a.contract_id == contract.id])
        priority = priorities[rng.randrange(len(priorities))]
        sla = sla_by_id.get(contract.sla_definition_id) or slas[0]

        # Age the ticket against its OWN response window rather than against a
        # flat 0-72h. An open ticket breaches when ``sla_due_at`` passes
        # (``ServiceService.scan_sla_breaches``), so drawing the age as a
        # fraction of the target is what decides the outcome, and drawing it
        # in absolute hours is what made the whole queue overdue.
        response_due_offset, resolution_due_offset = _sla_offsets(sla, priority)
        elapsed = _sla_elapsed_fraction(rng)
        reported_at = now - response_due_offset * elapsed
        response_due = reported_at + response_due_offset
        resolution_due = reported_at + resolution_due_offset

        # Status follows the age: nobody has picked up a ticket raised two
        # minutes ago, and a ticket sitting at 90% of its window has been
        # looked at. An assigned ticket always names the engineer it went to.
        if elapsed < 0.35:
            status = "new"
        elif elapsed < 0.85:
            status = "assigned"
        else:
            status = "in_progress"
        assigned_to = None if status == "new" else f"tech-{rng.randint(1, 6):02d}"

        ticket = ServiceTicket(
            contract_id=contract.id,
            asset_id=asset.id,
            # Open and closed tickets share one sequence with a gap between the
            # blocks, so the numbers stay unique without a letter in the middle
            # that only ever meant "this row came from the seeder".
            ticket_number=f"SR-{i + 1:05d}",
            title=_FAULTS[i % len(_FAULTS)],
            description=f"Reported on {asset.name} by the site team.",
            priority=priority,
            reported_at=reported_at.isoformat(),
            sla_due_at=response_due.isoformat(),
            # Both clocks were left NULL, so the two-clock SLA view the module
            # gained in R7 had nothing to read on any seeded ticket.
            response_due_at=response_due.isoformat(),
            resolution_due_at=resolution_due.isoformat(),
            # Ground truth the dashboard reads, stamped only when the response
            # window has actually run out.
            sla_breached_at=response_due.isoformat() if elapsed >= 1.0 else None,
            status=status,
            assigned_to=assigned_to,
        )
        session.add(ticket)
        counters["tickets"] += 1
    await session.flush()

    # ── 200 closed/billed work orders + tickets ──────────────────────────
    for i in range(200):
        # Same first pass as the open tickets above, for the same reason: a
        # project whose service history is empty says the module was never
        # used here, which is the one thing a worked example must not say.
        contract = contracts[i] if i < len(contracts) else contracts[rng.randrange(len(contracts))]
        contract_assets = [a for a in assets if a.contract_id == contract.id]
        if not contract_assets:
            continue
        asset = rng.choice(contract_assets)
        days_ago = rng.randint(1, 365)
        reported_at = now - timedelta(days=days_ago, hours=rng.randint(0, 8))
        priority = priorities[rng.randrange(len(priorities))]
        sla = sla_by_id.get(contract.sla_definition_id) or slas[0]
        response_due_offset, resolution_due_offset = _sla_offsets(sla, priority)

        # A closed ticket is judged on the RESOLUTION clock. The seeder stamped
        # a flat four hours due against a one-to-twenty-four-hour resolution, so
        # roughly five in six historical tickets breached by construction and
        # the register read as a total SLA failure. Drawing the time taken as a
        # fraction of the tier's own resolution window fixes both the
        # distribution and the ordering: reported <= resolved <= closed holds
        # for every row because each is built from the one before it.
        elapsed = _sla_elapsed_fraction(rng)
        resolved_at = reported_at + resolution_due_offset * elapsed
        # First response landed inside its own window on everything that met
        # the resolution target; a breached job was the one nobody got to.
        responded_late = elapsed >= 1.0
        # Administrative close follows the fix by a few hours to a day - never
        # before it.
        closed_at = resolved_at + timedelta(hours=rng.randint(2, 26))
        ticket = ServiceTicket(
            contract_id=contract.id,
            asset_id=asset.id,
            ticket_number=f"SR-{1000 + i + 1:05d}",
            title=_FAULTS[i % len(_FAULTS)],
            description=f"Reported on {asset.name} and attended on the same visit.",
            priority=priority,
            reported_at=reported_at.isoformat(),
            sla_due_at=(reported_at + response_due_offset).isoformat(),
            response_due_at=(reported_at + response_due_offset).isoformat(),
            resolution_due_at=(reported_at + resolution_due_offset).isoformat(),
            sla_breached_at=((reported_at + resolution_due_offset).isoformat() if responded_late else None),
            status="closed",
            resolved_at=resolved_at.isoformat(),
            closed_at=closed_at.isoformat(),
            assigned_to=f"tech-{rng.randint(1, 6):02d}",
        )
        session.add(ticket)
        await session.flush()
        counters["tickets"] += 1

        wo = ServiceWorkOrder(
            ticket_id=ticket.id,
            work_order_number=f"WO-{i + 1:06d}",
            # The visit is booked shortly before the engineer fixes it, not a
            # flat two hours after the call: on a job that took three days to
            # resolve, a visit scheduled on day one and completed on day three
            # describes an attendance that never happened.
            scheduled_for=(resolved_at - timedelta(hours=rng.randint(1, 3))).isoformat(),
            technician_id=ticket.assigned_to,
            status="billed",
            debrief_summary="Replaced consumable and verified operation.",
            currency=contract.currency,
            completed_at=ticket.resolved_at,
            billed_at=ticket.closed_at,
        )
        session.add(wo)
        await session.flush()
        counters["work_orders"] += 1

        # Items: 1-3 labor + 0-2 material
        items_total = Decimal("0")
        labor_qty = Decimal(rng.randint(1, 4))
        labor_rate = Decimal(rng.choice([45, 60, 75, 90]))
        labor_total = (labor_qty * labor_rate).quantize(Decimal("0.01"))
        items_total += labor_total
        session.add(
            ServiceWorkOrderItem(
                work_order_id=wo.id,
                item_type="labor",
                description="On-site service",
                quantity=labor_qty,
                unit="h",
                unit_rate=labor_rate,
                total=labor_total,
            )
        )
        counters["work_order_items"] += 1
        if rng.random() < 0.7:
            mat_qty = Decimal(1)
            mat_rate = Decimal(rng.randint(20, 400))
            mat_total = (mat_qty * mat_rate).quantize(Decimal("0.01"))
            items_total += mat_total
            session.add(
                ServiceWorkOrderItem(
                    work_order_id=wo.id,
                    item_type="material",
                    description="Replacement part",
                    quantity=mat_qty,
                    unit="pcs",
                    unit_rate=mat_rate,
                    total=mat_total,
                )
            )
            counters["work_order_items"] += 1

        # Patch the WO total via the loaded object (no extra UPDATE needed
        # - the row is still in the session).
        wo.billed_amount = items_total

        # Debrief
        session.add(
            DebriefReport(
                work_order_id=wo.id,
                problem="Equipment alarm raised.",
                cause="Worn consumable.",
                solution="Replaced consumable and tested.",
                root_cause_category=_ROOT_CAUSE_CATEGORIES[rng.randrange(len(_ROOT_CAUSE_CATEGORIES))],
                follow_up_required=(rng.random() < 0.1),
            )
        )
        counters["debriefs"] += 1

    await session.flush()

    # ── PPM schedules (20) ───────────────────────────────────────────────
    frequencies = ["monthly", "quarterly", "semiannual", "annual"]
    for i in range(20):
        asset = assets[i * 4 % len(assets)]
        next_due = today + timedelta(days=rng.randint(1, 60))
        cl = checklists[i % len(checklists)] if checklists else None
        sched = ServiceSchedule(
            asset_id=asset.id,
            frequency=frequencies[i % len(frequencies)],
            next_due_date=next_due.isoformat(),
            checklist_template_id=cl.id if cl else None,
            is_active=True,
        )
        session.add(sched)
        counters["schedules"] += 1
    await session.flush()

    logger.info("Service demo seeded: %s", counters)
    return counters


def _seed_payload_for_test() -> dict[str, Any]:
    """Hook used by unit tests to introspect the seeder's expected shape."""
    return {
        "customers": len(_CUSTOMER_NAMES),
        "asset_types": _ASSET_TYPES,
        "root_cause_categories": _ROOT_CAUSE_CATEGORIES,
    }


# ── Recurring schedules ─────────────────────────────────────────────────
# The register a maintenance planner actually works from: the jobs that come
# round again, rather than the ones somebody raised this morning. Each row is a
# rule plus the ticket it stamps, and the module's own tab reads as an unbuilt
# feature until they exist.
#
# The wordings are the job as a planner would write it on a schedule of rates,
# not a description of the software. Statutory names are kept generic rather
# than tied to one country's regulation, because the estate spans five.
_RECURRING_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "Fire alarm and emergency lighting test",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "high",
        "Call point test on a rotating zone, with a discharge test of the emergency lighting.",
    ),
    (
        "Air handling filter change and coil clean",
        "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15",
        "med",
        "Filter replacement, coil clean and belt tension check across the air handling units.",
    ),
    (
        "Standby generator run-up",
        "FREQ=WEEKLY;BYDAY=MO",
        "med",
        "Off-load run to operating temperature, recording fuel level and battery condition.",
    ),
    (
        "Lifting equipment thorough examination",
        "FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=1",
        "high",
        "Statutory examination of hoists, cranes and lifting accessories in use on site.",
    ),
    (
        "Water hygiene temperature monitoring",
        "FREQ=MONTHLY;BYMONTHDAY=20",
        "med",
        "Sentinel outlet temperatures, with a flush of the outlets that see little use.",
    ),
)

# How many rules each project takes. Three reads as a register rather than a
# single row, and the list is long enough that two projects opened side by side
# do not look like copies of each other.
_RECURRING_PER_PROJECT = 3


def _next_occurrence(rrule: str, after: datetime) -> str | None:
    """First occurrence of ``rrule`` strictly after ``after``, as an ISO string.

    Computed rather than typed, so a seeded row carries the same
    ``next_run_at`` the materialiser would work out for it. A rule the library
    cannot read leaves the field empty, which the cron worker treats as "not
    due" rather than as "due now".
    """
    from dateutil.rrule import rrulestr

    try:
        occurrence = rrulestr(f"RRULE:{rrule}", dtstart=after).after(after)
    except Exception:  # noqa: BLE001 - a bad rule must not take the whole seed down
        logger.warning("Recurring schedule seed: could not read the rule %s", rrule, exc_info=True)
        return None
    return occurrence.isoformat() if occurrence is not None else None


async def seed_service_recurring_schedules(
    session: AsyncSession,
    project_ids: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Seed the RRULE-driven recurring schedules for the projects named.

    Deliberately separate from :func:`seed_service_demo`. That function returns
    early as soon as any service contract exists, which on an install that has
    been seeded once is always, so a register wired into it would only ever
    appear on a database that started empty. This one asks the question per
    project, so a project that is still empty is filled on the next run whatever
    the rest of the estate looks like.

    That is only safe because of what it is handed: the caller passes the
    projects it has proved are demo projects, so filling an empty one cannot
    reach into somebody's own work. A project that already has a schedule is
    left alone, including one a user wrote.

    Args:
        session: Open async DB session.
        project_ids: Projects to seed. Every one of them is seeded.

    Returns:
        A mapping of entity name to the number of rows inserted.
    """
    counters: dict[str, int] = {"recurring_schedules": 0, "projects_skipped": 0}
    pids = list(project_ids or [])
    if not pids:
        logger.info("Service recurring schedule seed skipped: no project ids provided")
        return counters

    now = datetime.now(UTC)
    for idx, pid in enumerate(pids):
        existing = (
            await session.execute(
                select(ServiceRecurringSchedule.id).where(ServiceRecurringSchedule.project_id == pid).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            counters["projects_skipped"] += 1
            continue

        # Every occurrence stamps a ticket against a contract, so a project
        # without one would carry rules that can never materialise into
        # anything. Better an empty tab than a register of rules that fail.
        contract_id = (
            await session.execute(
                select(ServiceContract.id)
                .where(ServiceContract.project_id == pid)
                .order_by(ServiceContract.contract_number)
                .limit(1)
            )
        ).scalar_one_or_none()
        if contract_id is None:
            logger.info("Service recurring schedule seed: no contract for project %s, skipping", pid)
            counters["projects_skipped"] += 1
            continue

        for offset in range(_RECURRING_PER_PROJECT):
            name, rrule, priority, description = _RECURRING_SPECS[(idx + offset) % len(_RECURRING_SPECS)]
            session.add(
                ServiceRecurringSchedule(
                    project_id=pid,
                    contract_id=contract_id,
                    name=name,
                    rrule=rrule,
                    template_ticket_data={
                        "contract_id": str(contract_id),
                        "title": name,
                        "description": description,
                        "priority": priority,
                    },
                    next_run_at=_next_occurrence(rrule, now),
                    # One rule per project is paused, so the register shows both
                    # states rather than a column that reads the same all the
                    # way down and teaches the reader nothing about the toggle.
                    enabled=(offset != _RECURRING_PER_PROJECT - 1),
                    metadata_={"source": "service_demo_seed"},
                )
            )
            counters["recurring_schedules"] += 1

    await session.flush()
    logger.info("Service recurring schedules seeded: %s", counters)
    return counters


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Service contracts in ``project_ids`` exactly as :func:`seed_service_demo` wrote them.

    A contract matches on number, title and description of the seed contract
    with the same index, all three at once. The seed numbers contracts
    ``SC-01`` onwards by position in the project list, so the index is read
    from the number and the title must be the customer that index names.

    Assets, tickets, work orders with their items and debriefs, and asset
    schedules hang off the contract with CASCADE and go with it.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(
                ServiceContract.id,
                ServiceContract.contract_number,
                ServiceContract.title,
                ServiceContract.description,
            ).where(ServiceContract.project_id.in_(project_ids))
        )
    ).all()
    ids = []
    for r in rows:
        number = str(r.contract_number or "")
        if not number.startswith("SC-") or not number[3:].isdigit():
            continue
        idx = int(number[3:]) - 1
        if (
            idx >= 0
            and number == _contract_number(idx)
            and r.title == _contract_title(idx)
            and r.description == _CONTRACT_DESCRIPTION
        ):
            ids.append(r.id)
    return [(ServiceContract, ids, "service_contracts")]
