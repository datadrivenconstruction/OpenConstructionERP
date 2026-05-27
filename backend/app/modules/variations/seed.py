"""‌⁠‍Deterministic seed data for the variations module."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.variations.models import (
    DayworkSheet,
    DayworkSheetLine,
    DisruptionClaim,
    ExtensionOfTimeClaim,
    FinalAccount,
    Notice,
    SiteMeasurement,
    VariationCostImpact,
    VariationOrder,
    VariationRequest,
    VariationScheduleImpact,
)

_SEED = 42


def _date_offset(rng: random.Random, days_back_max: int = 180) -> str:
    delta = rng.randint(1, days_back_max)
    return (datetime.now(UTC) - timedelta(days=delta)).isoformat()


def _short_date_offset(rng: random.Random, days_back_max: int = 180) -> str:
    delta = rng.randint(1, days_back_max)
    return (datetime.now(UTC) - timedelta(days=delta)).date().isoformat()


_NOTICE_RECIPIENTS = ("owner", "contractor", "architect", "engineer")
_VR_STATUSES = ("draft", "submitted", "under_review", "approved", "rejected", "converted_to_vo")
_VR_CLASSIFICATIONS = (
    "scope_change",
    "unforeseen",
    "owner_change",
    "design_dev",
    "regulatory",
    "other",
)
_VO_STATUSES = ("issued", "in_progress", "completed", "voided")
_COST_CATEGORIES = (
    "labor",
    "material",
    "equipment",
    "subcontractor",
    "overhead",
    "profit",
)
_LINE_TYPES = ("labor", "material", "equipment")
_DW_STATUSES = ("draft", "signed", "disputed", "billed")
_DISRUPTION_STATUSES = ("draft", "submitted", "under_review", "agreed", "rejected")
_EOT_CAUSES = ("employer_caused", "neutral", "contractor_caused", "concurrent")


async def seed_variations_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """‌⁠‍Populate variations tables with deterministic demo data.

    Distribution (per spec):
      * 30 Notices
      * 40 Variation Requests
      * 25 Variation Orders
      * 60 cost-impact lines
      * 35 schedule-impact lines
      * 50 Site Measurements
      * 80 Daywork Sheets
      * 10 Disruption Claims
      * 5 EOT Claims
      * 2 closed Final Accounts

    Returns a counts dict for caller-side logging/asserts.
    """
    projects = list(project_ids)
    if not projects:
        return {"projects": 0}

    rng = random.Random(_SEED)

    # ── Notices ───────────────────────────────────────────────────────────
    notices: list[Notice] = []
    for i in range(30):
        pid = rng.choice(projects)
        recipient = rng.choice(_NOTICE_RECIPIENTS)
        notice = Notice(
            project_id=pid,
            code=f"NOT-{i + 1:04d}",
            title=f"Notice of variation {i + 1}",
            description=f"Demo notice #{i + 1} -- automated seed",
            raised_at=_date_offset(rng),
            raised_by=None,
            recipient_type=recipient,
            recipient_name=f"{recipient.title()} contact",
            target_response_date=_short_date_offset(rng, days_back_max=30),
            status=rng.choice(["issued", "acknowledged", "responded", "closed"]),
        )
        session.add(notice)
        notices.append(notice)
    await session.flush()

    # ── Variation Requests ────────────────────────────────────────────────
    vrs: list[VariationRequest] = []
    for i in range(40):
        pid = rng.choice(projects)
        notice_id = rng.choice(notices).id if notices and rng.random() < 0.4 else None
        classification = rng.choice(_VR_CLASSIFICATIONS)
        vr = VariationRequest(
            project_id=pid,
            notice_id=notice_id,
            code=f"VR-{i + 1:04d}",
            title=f"Variation request {i + 1}",
            description=f"Seed VR #{i + 1} ({classification})",
            requested_at=_date_offset(rng),
            classification=classification,
            urgency=rng.choice(["low", "med", "high"]),
            estimated_cost_impact=Decimal(str(rng.randint(500, 50000))),
            estimated_schedule_days=rng.randint(0, 30),
            currency="EUR",
            status=rng.choice(_VR_STATUSES),
        )
        session.add(vr)
        vrs.append(vr)
    await session.flush()

    # ── Variation Orders ──────────────────────────────────────────────────
    vos: list[VariationOrder] = []
    for i in range(25):
        pid = rng.choice(projects)
        source_vr = (
            rng.choice([v for v in vrs if v.project_id == pid]) if any(v.project_id == pid for v in vrs) else None
        )
        vo = VariationOrder(
            project_id=pid,
            variation_request_id=source_vr.id if source_vr else None,
            code=f"VO-{i + 1:04d}",
            title=f"Variation order {i + 1}",
            final_cost_impact=Decimal(str(rng.randint(1000, 80000))),
            final_schedule_days=rng.randint(0, 21),
            currency="EUR",
            agreed_at=_date_offset(rng),
            status=rng.choice(_VO_STATUSES),
        )
        session.add(vo)
        vos.append(vo)
    await session.flush()

    # ── Cost-impact lines (60) ────────────────────────────────────────────
    if vos:
        for _ in range(60):
            vo = rng.choice(vos)
            qty = Decimal(str(rng.randint(1, 100)))
            rate = Decimal(str(rng.randint(20, 500)))
            line = VariationCostImpact(
                variation_order_id=vo.id,
                category=rng.choice(_COST_CATEGORIES),
                description="Seed cost-impact line",
                quantity=qty,
                unit=rng.choice(["m2", "m3", "h", "pcs"]),
                unit_rate=rate,
                total=qty * rate,
                currency="EUR",
                source=rng.choice(["manual", "from_bom", "from_estimate"]),
            )
            session.add(line)

    # ── Schedule-impact lines (35) ────────────────────────────────────────
    if vos:
        for i in range(35):
            vo = rng.choice(vos)
            si = VariationScheduleImpact(
                variation_order_id=vo.id,
                affected_activity_ref=f"Task #{i + 1}",
                original_finish_date=_short_date_offset(rng),
                revised_finish_date=_short_date_offset(rng),
                days_added=rng.randint(0, 14),
                is_critical_path=rng.random() < 0.3,
                justification="Seed schedule impact",
            )
            session.add(si)
    await session.flush()

    # ── Site Measurements (50) ────────────────────────────────────────────
    for i in range(50):
        pid = rng.choice(projects)
        sm = SiteMeasurement(
            project_id=pid,
            recorded_at=_date_offset(rng),
            location=f"Block {chr(65 + (i % 6))} - L{i % 5}",
            item_description=f"Quantity #{i + 1}",
            unit=rng.choice(["m2", "m3", "m", "pcs"]),
            measured_quantity=Decimal(str(rng.randint(5, 500))),
            owner_signature_ref=f"sig-{i + 1:04d}",
            photos=[f"https://files.example/{i + 1}-{n}.jpg" for n in range(rng.randint(0, 3))],
            notes="Seed measurement",
            variation_order_id=rng.choice(vos).id if vos and rng.random() < 0.4 else None,
        )
        session.add(sm)
    await session.flush()

    # ── Daywork Sheets (80) ───────────────────────────────────────────────
    sheets: list[DayworkSheet] = []
    for i in range(80):
        pid = rng.choice(projects)
        ds = DayworkSheet(
            project_id=pid,
            sheet_number=f"DW-{i + 1:04d}",
            work_date=_short_date_offset(rng),
            description=f"Seed daywork sheet #{i + 1}",
            total_amount=Decimal("0"),
            currency="EUR",
            status=rng.choice(_DW_STATUSES),
            owner_signature_ref=f"dw-sig-{i + 1:04d}" if rng.random() < 0.5 else "",
        )
        session.add(ds)
        sheets.append(ds)
    await session.flush()

    # Two lines per sheet (160 lines) + recompute totals.
    for sheet in sheets:
        sheet_total = Decimal("0")
        for _ in range(2):
            qty = Decimal(str(rng.randint(1, 12)))
            rate = Decimal(str(rng.randint(20, 200)))
            total = qty * rate
            line = DayworkSheetLine(
                sheet_id=sheet.id,
                line_type=rng.choice(_LINE_TYPES),
                description="Seed line",
                quantity=qty,
                unit=rng.choice(["h", "m2", "pcs"]),
                unit_rate=rate,
                total=total,
                worker_name="Demo Worker",
            )
            session.add(line)
            sheet_total += total
        sheet.total_amount = sheet_total
    await session.flush()

    # ── Disruption Claims (10) ────────────────────────────────────────────
    for i in range(10):
        pid = rng.choice(projects)
        amount = Decimal(str(rng.randint(2000, 100_000)))
        st = rng.choice(_DISRUPTION_STATUSES)
        claim = DisruptionClaim(
            project_id=pid,
            raised_at=_date_offset(rng),
            claim_period_start=_short_date_offset(rng, days_back_max=200),
            claim_period_end=_short_date_offset(rng, days_back_max=60),
            description=f"Seed disruption claim #{i + 1}",
            root_cause="Owner-caused delay (seed)",
            cost_amount=amount,
            schedule_days=rng.randint(0, 30),
            currency="EUR",
            evidence_refs=[f"diary-{i + 1}", f"rfi-{i + 1}"],
            status=st,
            decided_amount=amount if st == "agreed" else None,
            decision_at=_date_offset(rng) if st in {"agreed", "rejected"} else None,
        )
        session.add(claim)

    # ── EOT Claims (5) ────────────────────────────────────────────────────
    for i in range(5):
        pid = rng.choice(projects)
        st = rng.choice(["draft", "submitted", "under_review", "granted", "rejected"])
        requested = rng.randint(5, 60)
        claim = ExtensionOfTimeClaim(
            project_id=pid,
            raised_at=_date_offset(rng),
            claim_period_start=_short_date_offset(rng, days_back_max=200),
            claim_period_end=_short_date_offset(rng, days_back_max=60),
            description=f"Seed EOT claim #{i + 1}",
            root_cause_category=rng.choice(_EOT_CAUSES),
            requested_days=requested,
            granted_days=requested if st == "granted" else None,
            critical_path_impact=rng.random() < 0.5,
            status=st,
            decision_at=_date_offset(rng) if st in {"granted", "rejected"} else None,
        )
        session.add(claim)
    await session.flush()

    # ── Final Accounts (2 closed) ─────────────────────────────────────────
    closed = 0
    for pid in projects:
        if closed >= 2:
            break
        fa = FinalAccount(
            project_id=pid,
            original_contract_value=Decimal("1500000"),
            variations_total=Decimal("125000"),
            daywork_total=Decimal("35000"),
            claims_total=Decimal("18000"),
            retention_held=Decimal("75000"),
            retention_released=Decimal("75000"),
            final_value=Decimal("1678000"),
            currency="EUR",
            status="closed",
            agreed_at=_date_offset(rng),
            closed_at=_date_offset(rng),
        )
        session.add(fa)
        closed += 1
    await session.flush()

    return {
        "notices": 30,
        "variation_requests": 40,
        "variation_orders": 25,
        "cost_impact_lines": 60,
        "schedule_impact_lines": 35,
        "site_measurements": 50,
        "daywork_sheets": 80,
        "daywork_lines": 160,
        "disruption_claims": 10,
        "eot_claims": 5,
        "final_accounts": closed,
    }
