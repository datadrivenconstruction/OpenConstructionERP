"""‌⁠‍Demo-data seeder for the Service & Maintenance module.

Function ``seed_service_demo(session)`` populates:
    - 3 SLA definitions (gold / silver / bronze)
    - 5 service contracts across 5 fictional customers
    - 80 customer assets distributed across the 5 contracts
    - 30 open tickets (mix of priorities + assignments)
    - 200 historical work orders in ``billed`` state with line items
    - 20 active PPM schedules

Idempotent only at the *no-existing-rows* level: if any contract already
exists for the seeded customer ids the function returns early.

Never auto-executed — call it explicitly from a CLI / Alembic data-only
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
    ServiceSchedule,
    ServiceTicket,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
    SLADefinition,
)

logger = logging.getLogger(__name__)

# Localised customer names — small, neutral list spanning EN/DE/RU markets.
_CUSTOMER_NAMES: list[str] = [
    "ACME Facilities Ltd",
    "Bauhaus Wartung GmbH",
    "ООО Тепло-Сервис",
    "Northwind Property Group",
    "Aurora Tower Management",
]

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


async def _customer_id_for(session: AsyncSession, idx: int) -> uuid.UUID:
    """‌⁠‍Resolve the i-th demo customer's ``Contact`` id, creating it on demand.

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
            primary_email=f"demo-{idx}@service.openconstructionerp.local",
            is_active=True,
        )
        session.add(contact)
        await session.flush()
        return contact.id
    except Exception:
        # Fallback: deterministic UUID derived from the customer name. The FK
        # is RESTRICT-on-delete — orphan ids are tolerated for demos.
        logger.warning("Could not resolve/create demo Contact; using synthetic UUID")
        return uuid.uuid5(uuid.NAMESPACE_DNS, f"openconstructionerp/service/demo/{name}")


async def seed_service_demo(session: AsyncSession) -> dict[str, int]:
    """‌⁠‍Populate the database with deterministic demo Service & Maintenance data.

    Returns a dict with row counts of each entity created.
    """
    rng = random.Random(42)
    today = datetime.now(UTC).date()
    now = datetime.now(UTC)

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
            description=f"Demo {tier} SLA tier",
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

    # ── Contracts (5) ────────────────────────────────────────────────────
    contracts: list[ServiceContract] = []
    contract_statuses = ["active", "active", "active", "draft", "expired"]
    currencies = ["EUR", "EUR", "RUB", "USD", "GBP"]
    for idx in range(5):
        customer_id = await _customer_id_for(session, idx)
        contract = ServiceContract(
            customer_id=customer_id,
            project_id=None,
            contract_number=f"SC-DEMO-{idx + 1:02d}",
            title=f"Service contract — {_CUSTOMER_NAMES[idx]}",
            description="Demo seed contract for the Service & Maintenance module.",
            period_start=(today - timedelta(days=180)).isoformat(),
            period_end=(today + timedelta(days=185)).isoformat(),
            sla_definition_id=slas[idx % len(slas)].id,
            sla_tier=slas[idx % len(slas)].name,
            status=contract_statuses[idx],
            value=Decimal(rng.randint(20_000, 250_000)),
            currency=currencies[idx],
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
            manufacturer=rng.choice(["Siemens", "Carrier", "ABB", "Daikin", "Bosch"]),
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

    # ── Open tickets (30) ────────────────────────────────────────────────
    priorities = ["low", "med", "high", "critical"]
    statuses_open = ["new", "assigned", "in_progress"]
    for i in range(30):
        contract = contracts[rng.randrange(len(contracts))]
        asset = rng.choice([a for a in assets if a.contract_id == contract.id])
        priority = priorities[rng.randrange(len(priorities))]
        reported_at = now - timedelta(hours=rng.randint(0, 72))
        sla = slas[0] if contract.sla_definition_id == slas[0].id else slas[1]
        sla_minutes = sla.severity_levels.get(priority, {}).get(
            "response_time_minutes",
            sla.response_time_minutes,
        )
        sla_due = reported_at + timedelta(minutes=sla_minutes)
        ticket = ServiceTicket(
            contract_id=contract.id,
            asset_id=asset.id,
            ticket_number=f"T-DEMO-O-{i + 1:04d}",
            title=f"Demo open ticket #{i + 1}",
            description=f"Issue reported on {asset.name}.",
            priority=priority,
            reported_at=reported_at.isoformat(),
            sla_due_at=sla_due.isoformat(),
            status=statuses_open[rng.randrange(len(statuses_open))],
            assigned_to=f"tech-{rng.randint(1, 6):02d}" if rng.random() > 0.3 else None,
        )
        session.add(ticket)
        counters["tickets"] += 1
    await session.flush()

    # ── 200 closed/billed work orders + tickets ──────────────────────────
    for i in range(200):
        contract = contracts[rng.randrange(len(contracts))]
        contract_assets = [a for a in assets if a.contract_id == contract.id]
        if not contract_assets:
            continue
        asset = rng.choice(contract_assets)
        days_ago = rng.randint(1, 365)
        reported_at = now - timedelta(days=days_ago, hours=rng.randint(0, 8))
        ticket = ServiceTicket(
            contract_id=contract.id,
            asset_id=asset.id,
            ticket_number=f"T-DEMO-H-{i + 1:05d}",
            title=f"Historical ticket #{i + 1}",
            description="Resolved demo ticket.",
            priority=priorities[rng.randrange(len(priorities))],
            reported_at=reported_at.isoformat(),
            sla_due_at=(reported_at + timedelta(hours=4)).isoformat(),
            status="closed",
            resolved_at=(reported_at + timedelta(hours=rng.randint(1, 24))).isoformat(),
            closed_at=(reported_at + timedelta(days=1)).isoformat(),
            assigned_to=f"tech-{rng.randint(1, 6):02d}",
        )
        session.add(ticket)
        await session.flush()
        counters["tickets"] += 1

        wo = ServiceWorkOrder(
            ticket_id=ticket.id,
            work_order_number=f"WO-DEMO-{i + 1:06d}",
            scheduled_for=(reported_at + timedelta(hours=2)).isoformat(),
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
        # — the row is still in the session).
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
