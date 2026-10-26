# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor insurance demo data​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for the demo projects.

Gives the demo subcontractor of a project a realistic insurance file: public
liability valid for months, contractor's all risk expiring in eleven days (the
14-day alert), employer's liability expired twelve days ago and mandatory (so
the pay application awaiting payment is blocked), and professional indemnity
valid but not mandatory. Idempotent: certificates tagged with the demo id are
replaced on reinstall.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractors.models import Certificate, Subcontractor

#: (type, mandatory, days from today to expiry, cover amount)
_FILE = (
    ("public_liability", True, 240, Decimal("5000000")),
    ("contractors_all_risk", True, 11, Decimal("12000000")),
    ("employers_liability", True, -12, Decimal("10000000")),
    ("professional_indemnity", False, 400, Decimal("2000000")),
)
_INSURERS = ("Atlas Mutual Insurance", "Northbridge Underwriters", "Meridian Assurance", "Crest Insurance Group")


async def seed_insurance_demo(
    session: AsyncSession,
    demo_id: str,
    currency: str,
    *,
    today: date | None = None,
) -> dict[str, int]:
    """Seed the insurance certificates of the project's demo subcontractor."""
    ref = today or datetime.now(UTC).date()
    sub = None
    for s in (await session.execute(select(Subcontractor))).scalars():
        if (s.metadata_ or {}).get("demo_id") == demo_id:
            sub = s
            break
    if sub is None:
        return {}
    stale = [
        c.id
        for c in (await session.execute(select(Certificate).where(Certificate.subcontractor_id == sub.id))).scalars()
        if (c.metadata_ or {}).get("demo_id") == demo_id
    ]
    if stale:
        await session.execute(delete(Certificate).where(Certificate.id.in_(stale)))
    for i, (ctype, mandatory, days, cover) in enumerate(_FILE):
        until = ref + timedelta(days=days)
        session.add(
            Certificate(
                id=uuid.uuid4(),
                subcontractor_id=sub.id,
                cert_type=ctype,
                issued_by=_INSURERS[i % len(_INSURERS)],
                issue_date=until - timedelta(days=365),
                valid_until=until,
                status="expired" if days < 0 else "valid",
                revoked=False,
                is_mandatory=mandatory,
                policy_number=f"POL-{ref.year}-{1000 + i * 37}",
                coverage_amount=cover,
                coverage_currency=(currency or "")[:3] or None,
                metadata_={"demo_id": demo_id, "is_demo": True},
            )
        )
    await session.flush()
    return {"insurance_certificates": len(_FILE)}
