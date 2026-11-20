# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRM demo seed data.

Loads:
    * 6 standard pipeline stages (Lead → Qualified → Proposal → Negotiation
      → Won / Lost)
    * 8 win/loss reasons
    * 100 accounts (mix of industries, sizes, countries)
    * 80 leads (mix of statuses)
    * 200 opportunities (60 open across stages, 100 won, 30 lost, 10 abandoned)
    * 300 activities
    * 4 forecasts for the last four quarters

Deterministic via ``random.seed(42)``.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.models import (
    Account,
    CrmActivity,
    Forecast,
    Lead,
    Opportunity,
    OpportunityStageHistory,
    PipelineStage,
    WinLossReason,
)

logger = logging.getLogger(__name__)


_STAGES = (
    ("lead", "Lead", 0, 10, False, False, False, "#94a3b8"),
    ("qualified", "Qualified", 1, 25, False, False, False, "#38bdf8"),
    ("bidding", "Bidding", 2, 35, False, False, False, "#06b6d4"),
    ("proposal", "Proposal", 3, 50, False, False, False, "#a78bfa"),
    ("negotiation", "Negotiation", 4, 75, False, False, False, "#f59e0b"),
    ("won", "Won", 5, 100, True, True, False, "#22c55e"),
    ("lost", "Lost", 6, 0, True, False, True, "#ef4444"),
)


_REASONS = (
    ("price_too_high", "Price too high", "price", False, True),
    ("schedule_mismatch", "Schedule mismatch", "timing", False, True),
    ("lost_relationship", "Lost relationship", "relationship", False, True),
    ("scope_too_narrow", "Scope too narrow", "scope", False, True),
    ("competitor_won", "Competitor won", "competitor", False, True),
    ("budget_cut", "Budget cut", "price", False, True),
    ("best_price", "Best price won deal", "price", True, False),
    ("relationship_strength", "Relationship strength won deal", "relationship", True, False),
)


_INDUSTRIES = (
    "Residential",
    "Commercial",
    "Healthcare",
    "Education",
    "Infrastructure",
    "Industrial",
    "Hospitality",
    "Retail",
)


_SIZE_CATS = ("sme", "mid", "enterprise")


# An account name is composed from the sector, size band and country already
# drawn for that row, rather than from a list of coined trading names. Two
# reasons. A made-up company name collides with a real firm surprisingly often,
# and a descriptive name still tells the reader what the account is, so the
# register stops looking like a hundred copies of one row.
_SIZE_ROLE = {
    "sme": "Contracting",
    "mid": "Construction Group",
    "enterprise": "Development Holding",
}


_COUNTRIES = (
    "DE",
    "AT",
    "CH",
    "FR",
    "IT",
    "ES",
    "NL",
    "PL",
    "GB",
    "US",
    "AE",
    "SA",
    "BR",
    "MX",
    "JP",
    "AU",
)


_LEAD_SOURCES = ("web", "referral", "event", "trade_show", "cold_outreach", "inbound")
_LEAD_STATUSES = ("new", "qualifying", "qualified", "disqualified", "converted")
_OPP_SOURCES = _LEAD_SOURCES
_ACTIVITY_KINDS = ("call", "meeting", "email", "task", "note")
_ACTIVITY_OUTCOMES = (None, "no_answer", "voicemail", "positive", "negative", "neutral")


# What the pursuit is actually for. Combined with the account's sector this
# gives a pipeline a salesperson can read, instead of 200 rows of one string
# with the counter moved along.
_OPP_SCOPES = (
    "design and build tender",
    "fit-out package",
    "framework renewal",
    "shell and core package",
    "refurbishment programme",
    "MEP subpackage",
    "early contractor involvement",
    "phase 2 extension",
    "cost plan and estimate",
    "term maintenance contract",
)


# One subject line per activity kind. The register shows what was done, which
# is the only thing the subject column is for.
_ACTIVITY_SUBJECTS = {
    "call": "Follow-up call on {scope}",
    "meeting": "Site meeting - {scope}",
    "email": "Sent revised pricing for {scope}",
    "task": "Prepare submission pack for {scope}",
    "note": "Handover note on {scope}",
}


async def seed_crm_demo(session: AsyncSession) -> dict[str, int]:
    """Seed CRM demo data (idempotent: skips if any account already exists).

    Returns a dict with counts of records created per table.
    """
    rng = random.Random(42)

    counts: dict[str, int] = {
        "stages": 0,
        "reasons": 0,
        "accounts": 0,
        "leads": 0,
        "opportunities": 0,
        "activities": 0,
        "forecasts": 0,
    }

    # ── Idempotency guard ────────────────────────────────────────────────
    existing = await session.execute(select(Account).limit(1))
    if existing.scalar_one_or_none() is not None:
        logger.info("CRM seed: accounts already exist, skipping demo seed.")
        return counts

    # ── Pipeline stages ──────────────────────────────────────────────────
    stage_objs: list[PipelineStage] = []
    for code, name, order, prob, is_final, is_won, is_lost, color in _STAGES:
        existing_stage = (
            await session.execute(select(PipelineStage).where(PipelineStage.code == code))
        ).scalar_one_or_none()
        if existing_stage is not None:
            stage_objs.append(existing_stage)
            continue
        stage = PipelineStage(
            code=code,
            name=name,
            display_order=order,
            default_probability_percent=prob,
            is_final=is_final,
            is_won=is_won,
            is_lost=is_lost,
            color=color,
        )
        session.add(stage)
        stage_objs.append(stage)
        counts["stages"] += 1
    await session.flush()

    open_stages = [s for s in stage_objs if not s.is_final]
    won_stage = next(s for s in stage_objs if s.is_won)
    lost_stage = next(s for s in stage_objs if s.is_lost)

    # ── Win/loss reasons ────────────────────────────────────────────────
    reason_objs: list[WinLossReason] = []
    for code, label, cat, is_win, is_loss in _REASONS:
        existing_reason = (
            await session.execute(select(WinLossReason).where(WinLossReason.code == code))
        ).scalar_one_or_none()
        if existing_reason is not None:
            reason_objs.append(existing_reason)
            continue
        reason = WinLossReason(
            code=code,
            label=label,
            category=cat,
            is_win_reason=is_win,
            is_loss_reason=is_loss,
        )
        session.add(reason)
        reason_objs.append(reason)
        counts["reasons"] += 1
    await session.flush()

    loss_reasons = [r for r in reason_objs if r.is_loss_reason]

    # ── Accounts ─────────────────────────────────────────────────────────
    account_objs: list[Account] = []
    for i in range(100):
        industry = rng.choice(_INDUSTRIES)
        size_category = rng.choice(_SIZE_CATS)
        country = rng.choice(_COUNTRIES)
        account = Account(
            name=f"{industry} {_SIZE_ROLE[size_category]} {country}-{i + 1:03d}",
            industry=industry,
            size_category=size_category,
            country=country,
            website=f"https://example-{i + 1:03d}.test",
            description=f"{industry.lower()} client account, {country}",
            status="active",
            tags=[],
        )
        session.add(account)
        account_objs.append(account)
        counts["accounts"] += 1
    await session.flush()

    # ── Leads ────────────────────────────────────────────────────────────
    for i in range(80):
        account = rng.choice(account_objs) if rng.random() < 0.7 else None
        lead = Lead(
            account_id=account.id if account else None,
            contact_name=f"Lead Contact {i + 1:03d}",
            contact_email=f"lead{i + 1:03d}@example.test",
            contact_phone=f"+1-555-{i:04d}",
            source=rng.choice(_LEAD_SOURCES),
            status=rng.choice(_LEAD_STATUSES[:3]),  # bias toward open states
            qualification_notes="",
        )
        session.add(lead)
        counts["leads"] += 1
    await session.flush()

    # ── Opportunities ────────────────────────────────────────────────────
    now = datetime.now(UTC)
    opp_objs: list[Opportunity] = []

    def _make_opp(
        idx: int,
        status: str,
        stage: PipelineStage,
    ) -> Opportunity:
        value = Decimal(rng.randint(10_000, 5_000_000))
        prob = stage.default_probability_percent
        close_date = (now.date() + timedelta(days=rng.randint(-180, 180))).isoformat()
        account = rng.choice(account_objs)
        scope = rng.choice(_OPP_SCOPES)
        opp = Opportunity(
            account_id=account.id,
            title=f"{account.industry} {scope} {idx + 1:04d}",
            description=f"{account.industry} {scope} for {account.name} ({account.country}).",
            estimated_value=value,
            currency=rng.choice(("EUR", "USD", "GBP", "")),
            expected_close_date=close_date,
            probability_percent=prob,
            stage_id=stage.id,
            weighted_value=(value * Decimal(prob) / Decimal(100)).quantize(Decimal("0.01")),
            source=rng.choice(_OPP_SOURCES),
            status=status,
        )
        return opp

    # 60 open
    for i in range(60):
        stage = rng.choice(open_stages)
        opp = _make_opp(i, "open", stage)
        session.add(opp)
        opp_objs.append(opp)
    # 100 won
    for i in range(100):
        opp = _make_opp(60 + i, "won", won_stage)
        opp.probability_percent = 100
        opp.weighted_value = opp.estimated_value
        opp.won_at = (now.date() - timedelta(days=rng.randint(1, 365))).isoformat()
        session.add(opp)
        opp_objs.append(opp)
    # 30 lost
    for i in range(30):
        opp = _make_opp(160 + i, "lost", lost_stage)
        opp.probability_percent = 0
        opp.weighted_value = Decimal("0")
        opp.lost_at = (now.date() - timedelta(days=rng.randint(1, 365))).isoformat()
        opp.lost_reason_code = rng.choice(loss_reasons).code
        session.add(opp)
        opp_objs.append(opp)
    # 10 abandoned
    for i in range(10):
        opp = _make_opp(190 + i, "abandoned", rng.choice(open_stages))
        opp.weighted_value = Decimal("0")
        session.add(opp)
        opp_objs.append(opp)
    counts["opportunities"] += len(opp_objs)
    await session.flush()

    # ── Stage history (initial entry per opportunity) ────────────────────
    for opp in opp_objs:
        session.add(
            OpportunityStageHistory(
                opportunity_id=opp.id,
                from_stage_id=None,
                to_stage_id=opp.stage_id,
                changed_at=now.isoformat(),
            )
        )
    await session.flush()

    # ── Activities ───────────────────────────────────────────────────────
    for i in range(300):
        attach_to = rng.choice(("account", "opportunity", "lead", "none"))
        linked_account = rng.choice(account_objs) if attach_to == "account" else None
        linked_opp = rng.choice(opp_objs) if attach_to == "opportunity" else None
        target_lead = None  # leads list not retained, skip lead-linked
        completed = rng.random() < 0.6
        kind = rng.choice(_ACTIVITY_KINDS)
        # Say what the activity was about. An activity hanging off an
        # opportunity borrows that pursuit's own wording so the two registers
        # agree with each other; the rest fall back to a generic scope.
        if linked_opp is not None:
            scope = linked_opp.title
        elif linked_account is not None:
            scope = linked_account.name
        else:
            scope = rng.choice(_OPP_SCOPES)
        activity = CrmActivity(
            account_id=linked_account.id if linked_account is not None else None,
            opportunity_id=linked_opp.id if linked_opp is not None else None,
            lead_id=target_lead,
            kind=kind,
            subject=_ACTIVITY_SUBJECTS[kind].format(scope=scope),
            body=f"{kind.capitalize()} logged against {scope}.",
            due_at=(now + timedelta(days=rng.randint(-30, 30))).isoformat() if rng.random() < 0.7 else None,
            completed_at=now.isoformat() if completed else None,
            outcome=rng.choice(_ACTIVITY_OUTCOMES),
        )
        session.add(activity)
        counts["activities"] += 1
    await session.flush()

    # ── Forecasts: last 4 quarters ──────────────────────────────────────
    today = now.date()
    current_q = (today.month - 1) // 3 + 1
    quarters: list[str] = []
    y = today.year
    q = current_q
    for _ in range(4):
        quarters.append(f"{y}-Q{q}")
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    for period in quarters:
        forecast = Forecast(
            period=period,
            pipeline_value=Decimal(rng.randint(1_000_000, 50_000_000)),
            weighted_value=Decimal(rng.randint(500_000, 30_000_000)),
            won_value=Decimal(rng.randint(0, 20_000_000)),
            committed_value=Decimal(rng.randint(0, 10_000_000)),
            computed_at=now.isoformat(),
        )
        session.add(forecast)
        counts["forecasts"] += 1
    await session.commit()

    logger.info("CRM demo seed completed: %s", counts)
    return counts
