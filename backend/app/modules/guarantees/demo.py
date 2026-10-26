# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ guarantees for the demo projects.

Every demo project gets a register a site manager recognises: the performance
bond given to the client, an advance payment guarantee that has already been
reduced over three interim payments, a retention bond standing in for cash
retention that expires within the month, the bid bonds of the tender bidders
(the losers released at award, the winner's held), a warranty bond received from
a subcontractor, and a bank credit line the bonds draw on.

Dates are anchored to the install day, because an expiry alert is about the
distance to today. Bank names are invented and generic.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guarantees import logic
from app.modules.guarantees.models import Guarantee, GuaranteeEvent, GuaranteeFacility

logger = logging.getLogger(__name__)

_BANKS: dict[str, tuple[str, str]] = {
    "AED": ("Meridian Trade Bank", "Harbourline Bank"),
    "EUR": ("Northbridge Bank", "Rhine Valley Credit"),
    "GBP": ("Thameside Commercial Bank", "Northbridge Bank"),
    "USD": ("Lakeshore National Bank", "Meridian Trade Bank"),
}
_FALLBACK_VALUE = Decimal("12500000")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def _facility(session: AsyncSession, bank: str, currency: str, limit: Decimal) -> GuaranteeFacility:
    name = f"Guarantee line {currency}"
    found = (
        await session.execute(
            select(GuaranteeFacility).where(
                GuaranteeFacility.bank_name == bank,
                GuaranteeFacility.currency == currency,
                GuaranteeFacility.name == name,
            )
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    row = GuaranteeFacility(name=name, bank_name=bank, currency=currency, limit_amount=limit)
    session.add(row)
    await session.flush()
    return row


def _event(row: Guarantee, action: str, when: date, **kw: Any) -> GuaranteeEvent:
    from datetime import UTC, datetime, time

    stamp = datetime.combine(when, time(9, 0), tzinfo=UTC)
    return GuaranteeEvent(guarantee_id=row.id, action=action, created_at=stamp, updated_at=stamp, **kw)


async def seed_demo_guarantees(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    currency: str,
    client_name: str,
    contractor_name: str,
    bidders: list[str],
    total_months: int,
    created_by: str | None = None,
    today: date | None = None,
) -> int:
    """Seed the demo register for one project; idempotent (skips a project that has guarantees)."""
    existing = (await session.execute(select(Guarantee.id).where(Guarantee.project_id == project_id))).first()
    if existing is not None:
        return 0
    today = today or date.today()
    currency = (currency or "EUR").upper()[:3]
    bank_a, bank_b = _BANKS.get(currency, ("Northbridge Bank", "Meridian Trade Bank"))

    contract = None
    package_id = None
    winning_bid = None
    try:
        from app.modules.contracts.models import Contract

        contract = (
            (
                await session.execute(
                    select(Contract).where(Contract.project_id == project_id).order_by(Contract.created_at.asc())
                )
            )
            .scalars()
            .first()
        )
    except ImportError:  # pragma: no cover
        contract = None
    try:
        from app.modules.tendering.models import TenderBid, TenderPackage

        package = (
            await session.execute(select(TenderPackage).where(TenderPackage.project_id == project_id).limit(1))
        ).scalar_one_or_none()
        if package is not None:
            package_id = package.id
            bids = (await session.execute(select(TenderBid).where(TenderBid.package_id == package.id))).scalars().all()
            winning_bid = next((b for b in bids if b.status == "accepted"), bids[0] if bids else None)
    except Exception:  # noqa: BLE001 - tendering absent or shaped differently
        package_id = None

    value = Decimal(str(contract.total_value)) if contract is not None and contract.total_value else _FALLBACK_VALUE
    start = today - timedelta(days=150)
    completion = logic.add_months(start, max(total_months, 12))
    facility = await _facility(session, bank_a, currency, _q(value * Decimal("0.6")))
    contract_id = contract.id if contract is not None else None
    rows: list[Guarantee] = []

    def make(reference: str, gtype: str, status: str, amount: Decimal, **kw: Any) -> Guarantee:
        row = Guarantee(
            id=uuid.uuid4(),
            project_id=project_id,
            reference=reference,
            guarantee_type=gtype,
            status=status,
            currency=currency,
            amount=_q(amount),
            original_amount=_q(kw.pop("original_amount", amount)),
            advance_recovered=kw.pop("advance_recovered", Decimal("0")),
            created_by=created_by,
            metadata_={"is_demo": True},
            documents=[],
            **kw,
        )
        rows.append(row)
        return row

    perf = make(
        "PB-0001",
        "performance_bond",
        "issued",
        value * Decimal("0.10"),
        direction="given",
        issuer_bank=bank_a,
        bank_reference="LG-PB-24118",
        beneficiary=client_name,
        applicant=contractor_name,
        percent_of_contract=Decimal("10"),
        contract_value=value,
        issue_date=start - timedelta(days=10),
        expiry_date=logic.add_months(completion, 12),
        claim_period_days=28,
        defects_period_months=12,
        commission_rate_pct=Decimal("1.25"),
        facility_id=facility.id,
        contract_id=contract_id,
        form_code="FIDIC-2017-ANNEX-C",
    )
    advance = _q(value * Decimal("0.10"))
    recovered = _q(advance * Decimal("0.42"))
    apg = make(
        "APG-0001",
        "advance_payment",
        "reduced",
        advance - recovered,
        original_amount=advance,
        advance_recovered=recovered,
        direction="given",
        issuer_bank=bank_a,
        bank_reference="LG-AP-24131",
        beneficiary=client_name,
        applicant=contractor_name,
        percent_of_contract=Decimal("10"),
        contract_value=value,
        issue_date=start - timedelta(days=5),
        expiry_date=completion,
        advance_amount=advance,
        advance_recovery_pct=Decimal("20"),
        claim_period_days=28,
        commission_rate_pct=Decimal("1.0"),
        facility_id=facility.id,
        contract_id=contract_id,
        form_code="FIDIC-2017-ANNEX-E",
    )
    rb = make(
        "RB-0001",
        "retention_bond",
        "issued",
        value * Decimal("0.05"),
        direction="given",
        issuer_bank=bank_b,
        bank_reference="LG-RT-30772",
        beneficiary=client_name,
        applicant=contractor_name,
        percent_of_contract=Decimal("5"),
        contract_value=value,
        issue_date=today - timedelta(days=340),
        expiry_date=today + timedelta(days=21),
        auto_extend=False,
        claim_period_days=28,
        replaces_cash_retention=True,
        contract_id=contract_id,
        notes="Expires before completion: extend or replace before the call period starts.",
    )
    names = bidders or ["Bidder A", "Bidder B", "Bidder C"]
    bid_bonds = []
    for i, name in enumerate(names[:3], start=1):
        won = i == 1
        bid_bonds.append(
            make(
                f"BB-{i:04d}",
                "bid_bond",
                "issued" if won else "released",
                value * Decimal("0.02") / Decimal(i),
                direction="received",
                issuer_bank=bank_b,
                beneficiary=contractor_name,
                applicant=name,
                issue_date=start - timedelta(days=75),
                expiry_date=start + timedelta(days=45),
                tender_id=package_id,
                bid_id=winning_bid.id if (won and winning_bid is not None) else None,
                notes="Winning bidder: released once the subcontract performance bond is in."
                if won
                else "Released at award.",
            )
        )
    make(
        "WB-0001",
        "warranty_bond",
        "issued",
        value * Decimal("0.015"),
        direction="received",
        issuer_bank=bank_b,
        beneficiary=contractor_name,
        applicant=names[0],
        issue_date=start + timedelta(days=30),
        expiry_date=logic.add_months(completion, 24),
        defects_period_months=24,
        claim_period_days=30,
    )
    session.add_all(rows)
    await session.flush()

    events: list[GuaranteeEvent] = []
    for row in rows:
        events.append(
            _event(
                row,
                "created",
                row.issue_date or start,
                to_status="requested",
                amount_after=row.original_amount,
                actor_id=created_by,
            )
        )
        if row.status != "draft":
            events.append(
                _event(
                    row,
                    "status_changed",
                    row.issue_date or start,
                    from_status="requested",
                    to_status="issued",
                    amount_before=row.original_amount,
                    amount_after=row.original_amount,
                )
            )
    # Three certified interim payments recovered 14% of the advance each.
    amount = advance
    for n in range(1, 4):
        after = _q(advance - advance * Decimal("0.14") * n)
        events.append(
            _event(
                apg,
                "reduced",
                start + timedelta(days=30 * n + 10),
                from_status="issued" if n == 1 else "reduced",
                to_status="reduced",
                amount_before=amount,
                amount_after=after,
                source="progress_claim",
                changes={"advance_recovered": format(_q(advance * Decimal("0.14") * n), "f")},
                note=f"Interim payment certificate {n}",
            )
        )
        amount = after
    apg.amount = amount
    apg.advance_recovered = _q(advance - amount)
    for bond in bid_bonds[1:]:
        events.append(
            _event(
                bond,
                "released",
                start - timedelta(days=20),
                from_status="issued",
                to_status="released",
                amount_before=bond.amount,
                amount_after=bond.amount,
                source="tender_award",
                note="Tender awarded to another bidder",
            )
        )
    session.add_all(events)
    await session.flush()

    if contract_id is not None:
        from app.modules.guarantees.service import GuaranteesService

        service = GuaranteesService(session)
        for row in (perf, apg, rb):
            await service._project_to_contract(row)  # noqa: SLF001 - the seeder writes the same projection
        await session.flush()
    logger.info("Seeded %d demo guarantees for project %s", len(rows), project_id)
    return len(rows)
