"""‌⁠‍Deterministic demo seed for the subcontractors module.

Generates 50 subcontractors with varied trades / statuses, 2-3 certificates
each (mix of valid / expiring / expired), 20 active agreements, 80 payment
applications across statuses, and 24 monthly rating rollups for the top 10.

All randomness is seeded from 42 so re-runs produce identical IDs / values.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractors.models import (
    Certificate,
    PaymentApplication,
    PrequalificationApplication,
    RetentionLedger,
    SubcontractAgreement,
    Subcontractor,
    SubcontractorContact,
    SubcontractorRating,
    WorkPackage,
)
from app.modules.subcontractors.service import (
    DEFAULT_RATING_WEIGHTS,
    _clamp,
    derive_cert_status,
)

logger = logging.getLogger(__name__)

_TRADES = [
    "earthworks",
    "concrete",
    "steel_erection",
    "carpentry",
    "roofing",
    "waterproofing",
    "facade",
    "drywall",
    "tiling",
    "painting",
    "plumbing",
    "hvac",
    "electrical",
    "fire_protection",
    "elevators",
    "scaffolding",
    "demolition",
    "landscaping",
    "asphalt",
    "joinery",
]

_CERT_TYPES = ("insurance", "license", "iso", "safety", "bond")
_STATUSES = ("pending", "approved", "suspended", "rejected")
_PAYMENT_STATUSES = (
    "submitted",
    "foreman_approved",
    "finance_approved",
    "paid",
    "rejected",
)
_AGREEMENT_STATUSES = ("active", "completed")


async def _existing_count(session: AsyncSession, model: Any) -> int:
    stmt = select(model)
    rows = (await session.execute(stmt)).scalars().all()
    return len(list(rows))


async def seed_subcontractors_demo(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    seed: int = 42,
) -> dict[str, int]:
    """‌⁠‍Seed demo subcontractor data.

    Args:
        session: Async DB session (caller commits).
        project_id: Project to attach agreements to. If None, agreements
            are skipped (no project context to link).
        seed: RNG seed for deterministic output.

    Returns:
        Counts of inserted entities per table.
    """
    rng = random.Random(seed)
    counts: dict[str, int] = {
        "subcontractors": 0,
        "contacts": 0,
        "prequalifications": 0,
        "certificates": 0,
        "agreements": 0,
        "work_packages": 0,
        "payment_applications": 0,
        "payment_application_lines": 0,
        "retention_entries": 0,
        "ratings": 0,
    }

    if await _existing_count(session, Subcontractor) > 0:
        logger.info("Subcontractor demo data already present — skipping seed")
        return counts

    today = date.today()

    subcontractors: list[Subcontractor] = []
    for i in range(50):
        trade_count = rng.randint(1, 3)
        trades = rng.sample(_TRADES, trade_count)
        prequal_status = rng.choices(
            _STATUSES,
            weights=[3, 5, 1, 1],
            k=1,
        )[0]
        sub = Subcontractor(
            legal_name=f"Demo Subcontractor {i + 1:02d} GmbH",
            trade_name=f"DS-{i + 1:02d}",
            tax_id=f"DE{100000000 + i:09d}",
            trade_categories=trades,
            prequalification_status=prequal_status,
            rating_score=Decimal(str(rng.randint(50, 95))),
            country=rng.choice(["DE", "CH", "AT", "GB", "FR", "ES", "IT"]),
            address={"city": rng.choice(["Berlin", "Munich", "Hamburg", "Köln"])},
            website=f"https://demo-sub-{i + 1:02d}.example.com",
            is_active=True,
        )
        session.add(sub)
        subcontractors.append(sub)
    await session.flush()
    counts["subcontractors"] = len(subcontractors)

    # 1-2 contacts each (primary + optional secondary).
    for sub in subcontractors:
        session.add(
            SubcontractorContact(
                subcontractor_id=sub.id,
                name=f"Primary {sub.trade_name}",
                role="account_manager",
                email=f"contact@{(sub.website or '').replace('https://', '')}",
                phone=f"+49 30 {rng.randint(1000000, 9999999)}",
                primary=True,
            )
        )
        counts["contacts"] += 1
        if rng.random() < 0.4:
            session.add(
                SubcontractorContact(
                    subcontractor_id=sub.id,
                    name=f"Site Lead {sub.trade_name}",
                    role="site_lead",
                    email=f"site@{(sub.website or '').replace('https://', '')}",
                    primary=False,
                )
            )
            counts["contacts"] += 1
    await session.flush()

    # Certificates: 2-3 per subcontractor, mix of valid / expiring / expired.
    for sub in subcontractors:
        n_certs = rng.randint(2, 3)
        chosen_types = rng.sample(_CERT_TYPES, n_certs)
        for cert_type in chosen_types:
            offset_days = rng.choice([-180, -30, 10, 45, 90, 200, 365])
            valid_until = today + timedelta(days=offset_days)
            issue_date = valid_until - timedelta(days=365)
            session.add(
                Certificate(
                    subcontractor_id=sub.id,
                    cert_type=cert_type,
                    issued_by=f"Authority {cert_type.upper()}",
                    issue_date=issue_date,
                    valid_until=valid_until,
                    document_url=f"https://docs.example.com/{cert_type}-{sub.id}.pdf",
                    status=derive_cert_status(valid_until, revoked=False, today=today),
                    revoked=False,
                )
            )
            counts["certificates"] += 1
    await session.flush()

    # Prequalification applications — one per subcontractor.
    for sub in subcontractors:
        sub_status = sub.prequalification_status
        prequal_status = (
            "approved" if sub_status == "approved" else ("rejected" if sub_status == "rejected" else "submitted")
        )
        decision_at = (
            datetime.now(UTC) - timedelta(days=rng.randint(1, 180))
            if prequal_status in ("approved", "rejected")
            else None
        )
        session.add(
            PrequalificationApplication(
                subcontractor_id=sub.id,
                submitted_at=datetime.now(UTC) - timedelta(days=rng.randint(30, 365)),
                status=prequal_status,
                answers={"years_in_business": rng.randint(2, 40)},
                reviewer_id=None,
                decision_at=decision_at,
            )
        )
        counts["prequalifications"] += 1
    await session.flush()

    # Agreements: 20 active. Skip when no project_id provided.
    agreements: list[SubcontractAgreement] = []
    if project_id is not None:
        approved_subs = [s for s in subcontractors if s.prequalification_status == "approved"]
        if not approved_subs:
            approved_subs = subcontractors[:20]
        for i, sub in enumerate(rng.sample(approved_subs, min(20, len(approved_subs)))):
            value = Decimal(str(rng.randint(50_000, 2_500_000)))
            ag_status = rng.choices(_AGREEMENT_STATUSES, weights=[8, 2], k=1)[0]
            agreement = SubcontractAgreement(
                subcontractor_id=sub.id,
                project_id=project_id,
                title=f"Subcontract {i + 1:02d} — {sub.trade_name}",
                total_value=value,
                currency="EUR",
                start_date=today - timedelta(days=rng.randint(30, 365)),
                end_date=today + timedelta(days=rng.randint(60, 365)),
                retention_percent=Decimal("5.0"),
                retention_release_event="practical_completion",
                status=ag_status,
            )
            session.add(agreement)
            agreements.append(agreement)
            counts["agreements"] += 1
        await session.flush()

        # Work packages — 1-3 per agreement.
        for ag in agreements:
            for k in range(rng.randint(1, 3)):
                session.add(
                    WorkPackage(
                        agreement_id=ag.id,
                        name=f"WP-{k + 1} {ag.title}",
                        scope=f"Scope for package {k + 1}",
                        planned_value=ag.total_value / Decimal("3"),
                        completion_percent=Decimal(str(rng.randint(0, 100))),
                        status=rng.choice(["planned", "in_progress", "completed"]),
                    )
                )
                counts["work_packages"] += 1
        await session.flush()

        # 80 payment applications distributed across the agreements.
        target_payment_count = 80
        for i in range(target_payment_count):
            ag = agreements[i % len(agreements)]
            gross = (ag.total_value / Decimal(str(rng.randint(6, 18)))).quantize(Decimal("0.01"))
            retention = (gross * Decimal("0.05")).quantize(Decimal("0.01"))
            net = gross - retention
            pay_status = rng.choices(
                _PAYMENT_STATUSES,
                weights=[3, 3, 3, 5, 1],
                k=1,
            )[0]
            now = datetime.now(UTC) - timedelta(days=rng.randint(1, 240))
            pa = PaymentApplication(
                agreement_id=ag.id,
                application_number=f"PA-{ag.id.hex[:4]}-{i + 1:03d}",
                period_start=today - timedelta(days=rng.randint(60, 300)),
                period_end=today - timedelta(days=rng.randint(1, 59)),
                gross_amount=gross,
                retention_amount=retention,
                net_amount=net,
                currency="EUR",
                status=pay_status,
                submitted_at=now,
                foreman_approved_at=now + timedelta(days=2)
                if pay_status in ("foreman_approved", "finance_approved", "paid")
                else None,
                finance_approved_at=now + timedelta(days=5) if pay_status in ("finance_approved", "paid") else None,
                paid_at=now + timedelta(days=10) if pay_status == "paid" else None,
            )
            session.add(pa)
            counts["payment_applications"] += 1

            # Retention ledger entry.
            session.add(
                RetentionLedger(
                    agreement_id=ag.id,
                    payment_application_id=None,
                    accrued_amount=retention,
                    released_amount=Decimal("0"),
                )
            )
            counts["retention_entries"] += 1
        await session.flush()

    # Ratings: 24 months of rollups for the top 10 subcontractors by rating.
    top_subs = sorted(subcontractors, key=lambda s: s.rating_score, reverse=True)[:10]
    for sub in top_subs:
        year = today.year
        month = today.month
        for _ in range(24):
            quality = Decimal(str(rng.randint(60, 100)))
            hse = Decimal(str(rng.randint(60, 100)))
            schedule = Decimal(str(rng.randint(60, 100)))
            cost = Decimal(str(rng.randint(60, 100)))
            overall = _clamp(
                quality * DEFAULT_RATING_WEIGHTS["quality"]
                + hse * DEFAULT_RATING_WEIGHTS["hse"]
                + schedule * DEFAULT_RATING_WEIGHTS["schedule"]
                + cost * DEFAULT_RATING_WEIGHTS["cost"]
            )
            session.add(
                SubcontractorRating(
                    subcontractor_id=sub.id,
                    period=f"{year:04d}-{month:02d}",
                    quality_score=quality,
                    hse_score=hse,
                    schedule_score=schedule,
                    cost_score=cost,
                    overall_score=overall,
                    basis={"source": "seed"},
                )
            )
            counts["ratings"] += 1
            month -= 1
            if month == 0:
                month = 12
                year -= 1
    await session.flush()

    logger.info("Subcontractors seed complete: %s", counts)
    return counts
