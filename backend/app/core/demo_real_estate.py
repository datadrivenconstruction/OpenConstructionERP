# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real estate developer demo data: off-plan sales, leases and an owners' association.

Seeds, for one demo project, the property development (tower, units, buyers,
sales contracts, payment plans, escrow), two leases and an owners' association
with an approved service charge budget and its first demands. Country values
(currency, VAT, regulator) come from the regional package profile, so the same
seeder serves any region that has one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.regional_packages import country_profile

logger = logging.getLogger(__name__)

#: demo_id -> (regional package id, country)
REAL_ESTATE_DEMOS: dict[str, tuple[str, str]] = {
    "residential-riyadh-offplan": ("real_estate_gcc", "SA"),
}

_FLOORS = 14
_PER_FLOOR = 4
# (type label, bedrooms, bathrooms, area m2, base price SAR) per position on a floor
_UNIT_TYPES = (
    ("2BR A", 2, 2, Decimal("118"), Decimal("980000")),
    ("3BR B", 3, 3, Decimal("156"), Decimal("1290000")),
    ("3BR C", 3, 3, Decimal("162"), Decimal("1340000")),
    ("1BR D", 1, 1, Decimal("74"), Decimal("640000")),
)
_GIVEN = ("Abdullah", "Noura", "Faisal", "Reem", "Khalid", "Lama", "Turki", "Sara", "Majed", "Hessa", "Nasser", "Dana")
_FAMILY = ("Al Qahtani", "Al Otaibi", "Al Harbi", "Al Shehri", "Al Dossari", "Al Mutairi", "Al Zahrani")
_GIVEN_AR = ("عبدالله", "نورة", "فيصل", "ريم", "خالد", "لمى", "تركي", "سارة", "ماجد", "حصة", "ناصر", "دانة")
_FAMILY_AR = ("القحطاني", "العتيبي", "الحربي", "الشهري", "الدوسري", "المطيري", "الزهراني")
# Payment plan of an off-plan sale: share of price, milestone, construction progress that triggers it.
_PLAN = (
    (Decimal("0.10"), "Booking", "booking", 0),
    (Decimal("0.20"), "Structure 30%", "progress_30", 30),
    (Decimal("0.20"), "Structure 60%", "progress_60", 60),
    (Decimal("0.20"), "Finishes 90%", "progress_90", 90),
    (Decimal("0.30"), "Handover", "handover", 100),
)
_PROGRESS = Decimal("62")  # certified construction progress, percent


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _national_id(i: int) -> str:
    return f"1{(104_582_311 + i * 7_919) % 1_000_000_000:09d}"


async def seed_real_estate_demo(
    session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID, demo_id: str
) -> dict[str, int]:
    """Seed the real estate slice for ``demo_id``; empty dict for other demos."""
    if demo_id not in REAL_ESTATE_DEMOS:
        return {}
    package_id, country = REAL_ESTATE_DEMOS[demo_id]
    profile = country_profile(package_id, country)
    currency = profile.get("currency", "SAR")
    vat_rate = Decimal(str((profile.get("vat") or {}).get("standard_rate_percent", "0")))
    regulator = (profile.get("offplan_regulator") or {}).get("code", "")
    escrow_ref = (profile.get("offplan_regulator") or {}).get("escrow_regulator_ref", "other")
    owner = str(owner_id)
    out: dict[str, int] = {}

    from app.modules.contacts.models import Contact

    def contact(i: int, kind: str, *, company: str | None = None, tags: list[str] | None = None) -> Contact:
        given, family = _GIVEN[i % len(_GIVEN)], _FAMILY[(i * 3) % len(_FAMILY)]
        given_ar, family_ar = _GIVEN_AR[i % len(_GIVEN_AR)], _FAMILY_AR[(i * 3) % len(_FAMILY_AR)]
        props: dict[str, Any] = {"identifiers": [{"scheme": "national_id", "value": _national_id(i)}]}
        if company:
            props = {"identifiers": [{"scheme": "cr", "value": f"10{(10_293_847 + i * 131):08d}"}]}
        row = Contact(
            id=uuid.uuid4(),
            contact_type=kind,
            first_name=None if company else given,
            last_name=None if company else family,
            company_name=company,
            legal_name=company or f"{given_ar} {family_ar}",
            party_kind="legal_entity" if company else "natural_person",
            primary_email=f"{given.lower()}.{family.lower().replace(' ', '')}{i}@example.sa",
            primary_phone=f"+966 5{(5_120_000 + i * 3_517) % 10_000_000:08d}",
            country_code=country,
            is_active=True,
            created_by=owner,
            custom_properties=props,
            module_tags=tags or [],
            metadata_={"project_id": str(project_id), "demo_id": demo_id},
        )
        session.add(row)
        return row

    developer = contact(90, "client", company="Rawdat Al Nakheel Real Estate Development Co.")

    # ── Property development: tower, units, buyers, contracts, plans, escrow ──
    from app.modules.property_dev.models import (
        Block,
        Buyer,
        ContractParty,
        Development,
        EscrowAccount,
        EscrowTransaction,
        Instalment,
        PaymentSchedule,
        Phase,
        Plot,
        SalesContract,
    )

    dev = Development(
        project_id=project_id,
        code=f"RNR-{project_id.hex[:6].upper()}",
        name="Rawdat Al Nakheel Residences",
        description="14-storey residential tower, 56 apartments, sold off-plan with escrow.",
        dev_type="residential",
        location_address="Anas Ibn Malik Road, Al Narjis, Riyadh 13325",
        country_code=country,
        latitude=Decimal("24.8329000"),
        longitude=Decimal("46.6567000"),
        total_plots=_FLOORS * _PER_FLOOR,
        total_floors=_FLOORS,
        sales_phase="sales",
        start_date="2025-09-01",
        launch_date="2025-11-15",
        completion_date="2027-10-31",
        status="active",
        sales_target_amount=Decimal("0"),
        currency=currency,
        developer_name=developer.company_name,
        general_contractor_name="Talveen Engineering Contracting",
        metadata_={
            "regulator": regulator,
            "jurisdiction": country,
            "rega_licence_no": "WAFI-1447-03-0219",
            "authorised_signatory": "Faisal Al Harbi, Managing Director",
            "vat_rate_percent": str(vat_rate),
            "is_demo": True,
        },
    )
    session.add(dev)
    await session.flush()
    phase = Phase(
        development_id=dev.id,
        code="P1",
        name="Tower A",
        sequence=1,
        planned_start="2025-09-01",
        planned_end="2027-10-31",
        status="under_construction",
    )
    session.add(phase)
    await session.flush()
    block = Block(
        phase_id=phase.id,
        code="A",
        name="Tower A",
        levels_count=_FLOORS,
        units_per_level=_PER_FLOOR,
        status="under_construction",
    )
    session.add(block)
    await session.flush()

    plots: list[Plot] = []
    total_target = Decimal("0")
    for floor in range(1, _FLOORS + 1):
        for pos, (label, beds, baths, area, base) in enumerate(_UNIT_TYPES, start=1):
            price = _q(base * (Decimal("1") + Decimal(floor) * Decimal("0.012")))
            total_target += price
            plot = Plot(
                development_id=dev.id,
                plot_number=f"A-{floor:02d}{pos:02d}",
                block_id=block.id,
                level_in_block=floor,
                position_on_floor=str(pos),
                house_type_label=label,
                orientation=("N", "E", "S", "W")[pos - 1],
                bedrooms=beds,
                bathrooms=baths,
                parking_spaces=1 if beds < 3 else 2,
                price_base=price,
                currency=currency,
                status="planned",
                construction_status_percent=_PROGRESS,
                metadata_={"area_m2": str(area)},
            )
            session.add(plot)
            plots.append(plot)
    dev.sales_target_amount = total_target
    await session.flush()

    buyers: dict[str, Contact] = {}
    contracts = 0
    instalments = 0
    collected = Decimal("0")
    paid_rows: list[Instalment] = []
    for i, plot in enumerate(plots):
        # About 60% sold, 15% reserved, the rest available.
        bucket = i % 20
        if bucket >= 15:
            continue
        reserved = bucket >= 12
        person = contact(i, "client", tags=["property_dev"])
        buyers[plot.plot_number] = person
        plot.status = "reserved" if reserved else "sold"
        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id,
            contact_id=person.id,
            full_name=f"{person.first_name} {person.last_name}",
            email=person.primary_email or "",
            phone=person.primary_phone,
            language="ar",
            status="reserved" if reserved else "contracted",
            contract_value=plot.price_base if not reserved else Decimal("0"),
            currency=currency,
            contract_signed_at=None if reserved else f"2026-{1 + i % 9:02d}-{10 + i % 15:02d}",
            deposit_amount=_q(plot.price_base * _PLAN[0][0]),
            jurisdiction=country,
        )
        session.add(buyer)
        if reserved:
            continue
        await session.flush()
        contract = SalesContract(
            contract_number=f"SPA-{dev.code}-{plot.plot_number}",
            plot_id=plot.id,
            signing_date=buyer.contract_signed_at,
            governing_law=country,
            language="ar",
            total_value=plot.price_base,
            currency=currency,
            status="signed",
            terms_version="Wafi standard off-plan SPA",
            total_price_breakdown={"base": str(plot.price_base), "vat_note": "Residential sale outside VAT"},
        )
        session.add(contract)
        await session.flush()
        session.add(
            ContractParty(
                sales_contract_id=contract.id,
                buyer_id=buyer.id,
                ownership_pct=Decimal("100"),
                party_role="primary",
                signing_order=1,
                signed_at=datetime.now(UTC),
            )
        )
        sched = PaymentSchedule(
            sales_contract_id=contract.id,
            currency=currency,
            total_amount=plot.price_base,
            late_fee_pct=Decimal("0"),
            grace_period_days=15,
            status="active",
        )
        session.add(sched)
        await session.flush()
        running = Decimal("0")
        for seq, (share, label, event, trigger) in enumerate(_PLAN, start=1):
            amount = plot.price_base - running if seq == len(_PLAN) else _q(plot.price_base * share)
            running += amount
            paid = trigger <= _PROGRESS - 2 or (trigger <= _PROGRESS and i % 3 != 0)
            due = trigger <= _PROGRESS
            inst = Instalment(
                schedule_id=sched.id,
                sequence=seq,
                milestone_label=label,
                milestone_event=event,
                due_date=None if not due else f"2026-{min(12, 1 + seq * 2):02d}-01",
                amount=amount,
                amount_paid=amount if paid else Decimal("0"),
                paid_at=datetime(2026, min(12, 1 + seq * 2), 5, tzinfo=UTC) if paid else None,
                status="paid" if paid else ("due" if due else "pending"),
                metadata_={"progress_trigger_percent": trigger},
            )
            session.add(inst)
            instalments += 1
            if paid:
                collected += amount
                paid_rows.append(inst)
        contracts += 1
    await session.flush()

    escrow = EscrowAccount(
        development_id=dev.id,
        regulator_ref=escrow_ref,
        regulator_account_number="WAFI-ESC-0219",
        bank_name="Licensed escrow bank (demo)",
        iban="SA0380000000608010167519",
        swift_bic="RJHISARI",
        currency=currency,
        opened_at="2025-10-01",
        is_active=True,
        metadata_={"is_demo": True},
    )
    session.add(escrow)
    await session.flush()
    for inst in paid_rows:
        session.add(
            EscrowTransaction(
                escrow_account_id=escrow.id,
                direction="credit",
                amount=inst.amount_paid,
                currency=currency,
                source_type="instalment",
                source_instalment_id=inst.id,
                source_reference=inst.milestone_label,
                transaction_date=(inst.paid_at or datetime.now(UTC)).date().isoformat(),
                reconciliation_state="reconciled",
            )
        )
    # Release to the contractor stays below certified progress x collected.
    release = _q(collected * _PROGRESS / Decimal("100") * Decimal("0.8"))
    session.add(
        EscrowTransaction(
            escrow_account_id=escrow.id,
            direction="debit",
            amount=release,
            currency=currency,
            source_type="release",
            source_reference="Progress release, certificate IPC-07",
            transaction_date="2026-09-15",
            reconciliation_state="reconciled",
            metadata_={"certified_progress_percent": str(_PROGRESS)},
        )
    )
    await session.flush()
    out.update(
        {
            "property_dev_units": len(plots),
            "property_dev_buyers": len(buyers),
            "property_dev_contracts": contracts,
            "property_dev_instalments": instalments,
        }
    )

    # ── Leasing: two ground-floor shops let on commercial terms ──
    from app.modules.leasing.schemas import LeaseCreate
    from app.modules.leasing.service import LeasingService

    leasing = LeasingService(session)
    leases = []
    for n, (ref, label, rent, use) in enumerate(
        (
            ("A-G01", "Ground-floor shop G01 (pharmacy)", Decimal("15000"), "commercial"),
            ("A-G02", "Ground-floor shop G02 (cafe)", Decimal("12500"), "commercial"),
        ),
        start=1,
    ):
        tenant = contact(60 + n, "client", tags=["leasing"])
        lease = await leasing.create(
            LeaseCreate(
                project_id=project_id,
                code=f"LS-{n:03d}",
                unit_kind="unit",
                unit_ref=ref,
                unit_label=label,
                tenant_contact_id=str(tenant.id),
                start_date=date(2026, 1, 1),
                end_date=date(2028, 12, 31),
                rent_amount=rent,
                currency=currency,
                frequency="quarterly",
                deposit=rent,
                escalation_kind="fixed",
                escalation_rate=Decimal("3"),
                escalation_every_months=12,
                tax_code="S",
                tax_rate=vat_rate,
                payment_terms_days=10,
                ext_refs={"use": use},
            ),
            owner,
        )
        await leasing.activate(lease, date(2026, 1, 1), owner)
        leases.append(lease)
    try:
        async with session.begin_nested():
            await leasing.run_schedule(leases, date(2026, 10, 1), owner)
    except Exception:
        logger.warning("Demo lease invoices not raised for %s", demo_id, exc_info=True)
    out["leases"] = len(leases)

    # ── Owners' association, permille key by area, approved budget, first demands ──
    from app.modules.service_charges.schemas import AssociationCreate, BudgetCreate, BudgetLineIn, KeyCreate, KeyLineIn
    from app.modules.service_charges.service import ServiceChargesService

    svc = ServiceChargesService(session)
    assoc = await svc.create_association(
        AssociationCreate(
            project_id=project_id,
            name="Rawdat Al Nakheel Owners Association",
            registration={"registry": "Mullak (REGA)", "number": "OA-1447-0457", "regulator": regulator},
            currency=currency,
            fiscal_year_start_month=1,
        ),
        owner,
    )
    areas = [Decimal(p.metadata_["area_m2"]) for p in plots]
    total_area = sum(areas)
    shares = [_q(a * Decimal("1000") / total_area) for a in areas]
    shares[-1] += Decimal("1000") - sum(shares)
    lines = [
        KeyLineIn(
            unit_ref=p.plot_number,
            unit_label=f"{p.house_type_label}, floor {p.level_in_block}",
            share=s,
            payer_contact_id=str((buyers.get(p.plot_number) or developer).id),
        )
        for p, s in zip(plots, shares, strict=True)
    ]
    key = await svc.create_key(assoc, KeyCreate(name="Floor area (permille)", method="permille", lines=lines))
    budget_lines = [
        ("cleaning", "Common area cleaning", "186000"),
        ("security", "Security guarding 24/7", "264000"),
        ("lifts", "Lift maintenance contract (3 lifts)", "72000"),
        ("mep", "MEP and chiller maintenance", "158000"),
        ("insurance", "Building insurance", "54000"),
        ("utilities", "Common area electricity and water", "121000"),
        ("reserve", "Reserve fund contribution", "90000"),
    ]
    budget = await svc.create_budget(
        assoc,
        BudgetCreate(
            year=2026,
            demand_frequency="quarterly",
            default_key_id=key.id,
            notes="First operating budget, approved at the founding general assembly.",
            lines=[
                BudgetLineIn(category=c, description=d, amount=Decimal(a), key_id=key.id) for c, d, a in budget_lines
            ],
        ),
    )
    await svc.approve_budget(assoc, budget, owner)
    demands = 0
    for period in (1, 2, 3):
        try:
            async with session.begin_nested():
                res = await svc.run_demands(assoc, budget, period, None, 30, owner)
                demands += int(res.get("created", 0))
        except Exception:
            logger.warning("Demo service charge demands not raised for %s period %s", demo_id, period, exc_info=True)
    out.update({"service_charge_units": len(lines), "service_charge_demands": demands})
    await session.flush()
    return out
