"""‌⁠‍Deterministic demo seed for the bid_management module.

``seed_bid_management_demo(session, project_ids)`` creates:
    - 10 packages per project (5 closed + 3 open + 2 draft)
    - 5 bidders per package
    - 4 submissions per closed package (across leveling outcomes)
    - 30 Q&A entries (spread)
    - 5 awards + 25 rejections (one full award per closed package)

The seed is idempotent: re-running it does NOT create duplicates — it
short-circuits when a package with the expected ``code`` already exists.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bid_management.models import (
    BidAward,
    Bidder,
    BidInvitation,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidRejection,
    BidSubmission,
    BidSubmissionLine,
)

logger = logging.getLogger(__name__)


_PACKAGE_SEED = [
    # (suffix, status, title, currency, budget)
    ("ELEC", "closed", "Electrical works", "EUR", "120000"),
    ("HVAC", "closed", "HVAC supply & install", "EUR", "240000"),
    ("PLMB", "closed", "Plumbing works", "EUR", "85000"),
    ("STRC", "closed", "Structural steel", "EUR", "320000"),
    ("FACD", "closed", "Facade cladding", "EUR", "510000"),
    ("FIRE", "open", "Fire protection", "EUR", "65000"),
    ("INSL", "open", "Thermal insulation", "EUR", "45000"),
    ("ROOF", "open", "Roofing", "EUR", "180000"),
    ("SCAF", "draft", "Scaffolding rental", "EUR", "32000"),
    ("DEMO", "draft", "Demolition phase 1", "EUR", "95000"),
]

_BIDDER_NAMES = [
    "Alpha Construction Ltd",
    "Beta Builders GmbH",
    "Gamma Contractors Inc",
    "Delta Engineering Co",
    "Epsilon Works S.A.",
]

_QA_QUESTIONS = [
    ("What is the expected start date?", "We expect a kickoff within 2 weeks of award."),
    ("Are alternates allowed for items 3.2 and 3.4?", "Yes — please submit clearly labelled."),
    ("Is on-site storage available?", "Limited 200 m^2 — coordinate with site manager."),
    ("Is retention 5% or 10%?", "5% retention per contract template."),
    ("Are working hours restricted?", "Weekdays 07:00–18:00, no Sunday work."),
    ("Can we submit a partial bid?", "No — full scope only."),
    ("Are materials provided by GC?", "No — bidder supplies all materials unless flagged."),
]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _seed_one_project(session: AsyncSession, project_id: uuid.UUID, project_index: int) -> dict[str, int]:
    """‌⁠‍Seed a single project's bid_management data.

    Returns counts for logging.
    """
    counts = {
        "packages": 0,
        "lines": 0,
        "bidders": 0,
        "invitations": 0,
        "submissions": 0,
        "submission_lines": 0,
        "qa": 0,
        "awards": 0,
        "rejections": 0,
    }
    now = _now()

    for pkg_idx, (suffix, status, title, currency, budget) in enumerate(_PACKAGE_SEED):
        code = f"BP-P{project_index:02d}-{suffix}"
        existing = await session.execute(select(BidPackage).where(BidPackage.code == code))
        if existing.scalar_one_or_none() is not None:
            continue

        deadline = now - timedelta(days=14) if status == "closed" else now + timedelta(days=14)

        package = BidPackage(
            project_id=project_id,
            tender_id=None,
            code=code,
            title=title,
            scope_description=f"Demo scope for {title}",
            instructions_to_bidders="Standard ITB applies. Submit envelope by deadline.",
            submission_deadline=_iso(deadline),
            decision_due_by=_iso(deadline + timedelta(days=7)),
            currency=currency,
            total_budget_estimate=budget,
            status=status,
            confidentiality_level="limited",
            published_at=_iso(now - timedelta(days=21)) if status != "draft" else None,
            closed_at=_iso(now - timedelta(days=7)) if status == "closed" else None,
            awarded_at=_iso(now - timedelta(days=2)) if status == "closed" else None,
            metadata_={"seed": True, "demo": True},
        )
        session.add(package)
        await session.flush()
        counts["packages"] += 1

        # 5 mandatory + 3 optional lines
        lines: list[BidPackageLineItem] = []
        for li in range(8):
            line = BidPackageLineItem(
                package_id=package.id,
                code=f"{li + 1:02d}",
                description=f"Item {li + 1} for {title}",
                unit="m2" if li % 2 == 0 else "lsum",
                quantity=str(Decimal("100") + Decimal(li * 10)),
                alternative_allowed=(li == 3),
                order_index=li,
                is_mandatory=(li < 5),
            )
            session.add(line)
            lines.append(line)
            counts["lines"] += 1
        await session.flush()

        # 5 bidders
        bidders: list[Bidder] = []
        for bi, name in enumerate(_BIDDER_NAMES):
            bidder = Bidder(
                package_id=package.id,
                company_name=name,
                contact_name=f"Contact {bi + 1}",
                contact_email=f"contact{bi + 1}@{name.split()[0].lower()}.example",
                contact_phone=f"+49 30 555 {1000 + bi}",
                country="DE" if bi % 2 == 0 else "AT",
                status="active",
                notes="Seeded demo bidder",
            )
            session.add(bidder)
            bidders.append(bidder)
            counts["bidders"] += 1
        await session.flush()

        # invitations (one per bidder)
        invitations: list[BidInvitation] = []
        for bi, bidder in enumerate(bidders):
            invitation = BidInvitation(
                package_id=package.id,
                bidder_ref_id=None,
                invitee_email=bidder.contact_email,
                invitee_company_name=bidder.company_name,
                sent_at=_iso(now - timedelta(days=20)) if status != "draft" else None,
                status="submitted" if status == "closed" and bi < 4 else ("sent" if status != "draft" else "pending"),
            )
            session.add(invitation)
            invitations.append(invitation)
            counts["invitations"] += 1
        await session.flush()

        # 4 submissions per closed package
        if status == "closed":
            for bi in range(4):
                bidder = bidders[bi]
                invitation = invitations[bi]
                # Spread totals across 95% .. 130% of budget
                multiplier = Decimal("0.95") + (Decimal(bi) * Decimal("0.12"))
                total = Decimal(budget) * multiplier
                submission = BidSubmission(
                    invitation_id=invitation.id,
                    bidder_id=bidder.id,
                    submitted_at=_iso(now - timedelta(days=15, hours=bi)),
                    total_amount=str(total.quantize(Decimal("0.01"))),
                    currency=currency,
                    completeness_score=str(Decimal("85") + Decimal(bi * 5)),
                    notes_to_owner=f"Bid {bi + 1} notes",
                    exclusions=["bonds_excluded"] if bi == 1 else [],
                    qualifications=["weather_dependent"] if bi == 2 else [],
                    is_valid=True,
                    open_after_deadline=False,
                    envelope_payload={"technical_score": str(70 + bi * 5)},
                )
                session.add(submission)
                counts["submissions"] += 1
                await session.flush()

                # Submission lines (price the 5 mandatory items)
                for li, pkg_line in enumerate(lines[:5]):
                    unit_price = Decimal("250") + Decimal(li * 30) + Decimal(bi * 10)
                    qty = Decimal(pkg_line.quantity)
                    total_price = (unit_price * qty).quantize(Decimal("0.01"))
                    sub_line = BidSubmissionLine(
                        submission_id=submission.id,
                        line_item_id=pkg_line.id,
                        unit_price=str(unit_price),
                        quantity_priced=str(qty),
                        total_price=str(total_price),
                        alternative_offered=False,
                        alternative_description="",
                        comment="",
                    )
                    session.add(sub_line)
                    counts["submission_lines"] += 1
                await session.flush()

            # Award + rejections for closed packages.
            award_bidder = bidders[0]
            award = BidAward(
                package_id=package.id,
                awarded_bidder_id=award_bidder.id,
                awarded_amount=str((Decimal(budget) * Decimal("0.95")).quantize(Decimal("0.01"))),
                currency=currency,
                decision_summary=f"Awarded to {award_bidder.company_name} (lowest valid bid)",
                decision_signed_by=None,
                decision_signed_at=_iso(now - timedelta(days=2)),
                contract_template_ref=f"contract-tpl-{suffix.lower()}",
                notified_others_at=_iso(now - timedelta(days=2, hours=2)),
            )
            session.add(award)
            counts["awards"] += 1

            for rej_bidder in bidders[1:]:
                rejection = BidRejection(
                    package_id=package.id,
                    bidder_id=rej_bidder.id,
                    rejection_code="price",
                    rejection_reason="Not the lowest valid bid",
                    notified_at=_iso(now - timedelta(days=2, hours=2)),
                )
                session.add(rejection)
                counts["rejections"] += 1
            await session.flush()

        # Q&A — spread 3 entries on this package
        for qi in range(3):
            q, a = _QA_QUESTIONS[(pkg_idx + qi) % len(_QA_QUESTIONS)]
            qa = BidQA(
                package_id=package.id,
                bidder_id=bidders[qi % len(bidders)].id if qi % 2 == 0 else None,
                question=q,
                asked_at=_iso(now - timedelta(days=10, hours=qi)),
                asked_by_email=bidders[qi % len(bidders)].contact_email,
                answer=a if status != "draft" else "",
                answered_at=_iso(now - timedelta(days=9)) if status != "draft" else None,
                answered_by=None,
                is_public=(qi == 0),
                visible_to_bidder_ids=[],
            )
            session.add(qa)
            counts["qa"] += 1
        await session.flush()

    return counts


async def seed_bid_management_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """‌⁠‍Seed deterministic demo data for the bid_management module.

    Args:
        session: Open async DB session.
        project_ids: Projects to seed against.

    Returns:
        Aggregated counts dictionary.
    """
    totals = {
        "packages": 0,
        "lines": 0,
        "bidders": 0,
        "invitations": 0,
        "submissions": 0,
        "submission_lines": 0,
        "qa": 0,
        "awards": 0,
        "rejections": 0,
    }
    for idx, pid in enumerate(project_ids):
        counts = await _seed_one_project(session, pid, idx)
        for k, v in counts.items():
            totals[k] += v
    logger.info("bid_management seed complete: %s", totals)
    return totals
