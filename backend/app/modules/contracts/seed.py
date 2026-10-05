# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic seed data for the contracts module.

Four jobs, all idempotent:

1. **Catalog fabrication** - 10 contracts spanning all primary types
   (3 lump-sum, 2 GMP, 1 cost-plus, 2 T&M, 1 unit-price, 1 design-build),
   each with 5-15 SoV lines, 4 progress claims and 2 closed with a
   FinalAccount. Fabricated only into projects that hold no contract at
   all: the demo installer authors each demo project's own head contract
   and trade subcontracts, and stacking a generic catalog on top of those
   would bury the authored register under filler.

2. **Progress-claim backfill** - every authored contract shipped without a
   single progress claim, so the payment side of the register was empty on
   every install. For each live contract that has no claims yet, a staged
   claim run is written along the contract's own calendar: earlier periods
   paid, then one under approval, the latest submitted, the current period
   still a draft. German-market projects number their claims AZ-nn
   (Abschlagszahlung); everything else keeps PC-nnnn.

3. **Schedule-of-values backfill** - the catalog in job 1 writes SoV lines,
   but only into projects holding no contract at all, so on a real demo
   estate it never runs and every authored contract had an agreed value
   with nothing behind it. Each line-less contract gets a schedule shaped
   by how it is priced, summing to the contract value to the cent. The
   projects whose contracts are worded in German get theirs from a German
   catalogue of DIN 276 cost groups and Leistungsverzeichnis positions,
   chosen by the trade the contract's own title names.

4. **Claim breakdown** - each progress claim is apportioned across that
   schedule, filling each line up to its remaining room. Without it the
   G703 continuation sheet joins a priced schedule to nothing and the G702
   certificate face, a pure roll-up of those rows, reads zero earned on a
   contract the register says is part billed.

All decisions are seeded from fixed ``random.Random`` instances so output
is reproducible.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_showcase import GERMAN_SHOWCASE_DEMO_IDS
from app.modules.contracts.country_defaults import resolve_retention_basis
from app.modules.contracts.models import (
    Contract,
    ContractLine,
    ContractTypeConfiguration,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
    RetentionSchedule,
)
from app.modules.contracts.periods import claim_dates_for_write
from app.modules.contracts.retention import on_retention_basis
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)


_TYPE_CONFIG_CATALOG: list[dict[str, object]] = [
    {
        "contract_type": "lump_sum",
        "display_name": "Lump-Sum",
        "allowed_fields": ["total_value", "retention_percent"],
        "default_fee_structure": {},
    },
    {
        "contract_type": "gmp",
        "display_name": "Guaranteed Maximum Price",
        "allowed_fields": ["gmp_cap", "target_cost", "gainshare_split_pct"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 4},
    },
    {
        "contract_type": "cost_plus",
        "display_name": "Cost-Plus",
        "allowed_fields": ["fee_percent", "max_fee"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 8},
    },
    {
        "contract_type": "tm",
        "display_name": "Time & Materials",
        "allowed_fields": ["tm_nte_cap", "labor_rates", "material_markup"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 5},
    },
    {
        "contract_type": "unit_price",
        "display_name": "Unit Price",
        "allowed_fields": ["measurement_method", "qty_variance_threshold"],
        "default_fee_structure": {},
    },
    {
        "contract_type": "design_build",
        "display_name": "Design-Build",
        "allowed_fields": ["design_phase_fee", "construction_phase_fee"],
        "default_fee_structure": {"fee_type": "fixed", "fee_fixed_amount": 0},
    },
    {
        "contract_type": "combination",
        "display_name": "Combination / Hybrid",
        "allowed_fields": ["component_breakdown"],
        "default_fee_structure": {},
    },
    {
        "contract_type": "remeasurement",
        "display_name": "Remeasurement",
        "allowed_fields": ["measurement_method", "qty_variance_threshold"],
        "default_fee_structure": {},
    },
]


# How each procurement route is named on a contract cover sheet. The stored
# value stays the machine code; this is only what the register shows.
_TYPE_LABELS: dict[str, str] = {
    "lump_sum": "Lump sum",
    "gmp": "Guaranteed maximum price",
    "cost_plus": "Cost plus fee",
    "tm": "Time and materials",
    "unit_price": "Unit price",
    "design_build": "Design and build",
}


_TYPE_DISTRIBUTION: list[str] = [
    "lump_sum",
    "lump_sum",
    "lump_sum",
    "gmp",
    "gmp",
    "cost_plus",
    "tm",
    "tm",
    "unit_price",
    "design_build",
]


async def seed_type_configurations(session: AsyncSession) -> int:
    """Insert ContractTypeConfiguration catalog rows if missing."""
    from sqlalchemy import select

    existing = (await session.execute(select(ContractTypeConfiguration.contract_type))).scalars().all()
    inserted = 0
    for cfg in _TYPE_CONFIG_CATALOG:
        if cfg["contract_type"] in existing:
            continue
        row = ContractTypeConfiguration(
            contract_type=cfg["contract_type"],  # type: ignore[arg-type]
            display_name=cfg["display_name"],  # type: ignore[arg-type]
            allowed_fields=cfg["allowed_fields"],
            default_fee_structure=cfg["default_fee_structure"],
            schema_version="1.0",
        )
        session.add(row)
        inserted += 1
    if inserted:
        await session.flush()
    return inserted


def _parse_seed_date(value: str | None) -> date | None:
    """Parse a contract date column (bare date or ISO datetime) to a date."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _month_starts(first: date, last: date) -> list[date]:
    """First-of-month dates from ``first``'s month through ``last``'s month."""
    out: list[date] = []
    cursor = first.replace(day=1)
    stop = last.replace(day=1)
    while cursor <= stop:
        out.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return out


def _stamp(day: date, hour: int) -> str:
    """A business-hours ISO timestamp on ``day``, never later than right now.

    The clamp is the whole point and it belongs here rather than at the call
    sites. A caller that has already limited a claim to ``today`` has limited
    the date and nothing else, so a business hour laid on top of it lands in
    the future for every hour of the morning before that one. The demo estate
    is seeded at whatever time of day the installation is created, and a
    progress claim submitted at a time that has not arrived yet is a defect a
    reader would report, not a rounding of the clock.

    Clamping to the seeding instant keeps the ladder monotonic, because every
    later stage of a claim is derived from a day at or after the one before it
    and the same ceiling applies to all of them.
    """
    at = datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=UTC)
    return min(at, datetime.now(UTC)).isoformat()


#: How many claim periods a single contract materializes at most. Enough to
#: show the full lifecycle ladder without flooding an old contract's register.
_MAX_CLAIM_PERIODS = 6


async def seed_progress_claims_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Backfill a staged progress-claim run onto claim-less live contracts.

    The demo installer authors each project's head contract and trade
    subcontracts but no payment history, so every register opened on an empty
    claims tab. For each ``active`` / ``completed`` contract of the given
    projects that still has no claims, this writes one claim per elapsed
    calendar month (capped at :data:`_MAX_CLAIM_PERIODS`, anchored on the
    contract's own start date): the oldest periods are paid, one sits at
    approval / certification, the latest full period is submitted and the
    running period is still a draft. Amounts are a plausible monthly slice of
    the contract value with the contract's own retention held, and the
    cumulative ``prior_claims_total`` re-adds exactly.

    Self-guarding and demo-safe by construction: a contract that already has
    any claim (seeded or user-written) is left alone, and the caller passes
    demo projects only. German-market projects (``country_code == "DE"``)
    number claims AZ-nn, the Abschlagszahlung convention their users expect;
    other markets keep PC-nnnn.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Projects whose contracts are eligible. Empty list is a
            no-op.

    Returns:
        Dict with ``claims_backfilled`` / ``contracts_backfilled`` counts.
    """
    if not project_ids:
        return {"claims_backfilled": 0, "contracts_backfilled": 0}

    from app.modules.projects.models import Project

    contracts = (
        (
            await session.execute(
                select(Contract)
                .where(Contract.project_id.in_(project_ids))
                .where(Contract.status.in_(("active", "completed")))
                .order_by(Contract.code)
            )
        )
        .scalars()
        .all()
    )
    if not contracts:
        return {"claims_backfilled": 0, "contracts_backfilled": 0}

    claimed_ids = set(
        (
            await session.execute(
                select(ProgressClaim.contract_id.distinct()).where(
                    ProgressClaim.contract_id.in_([c.id for c in contracts])
                )
            )
        )
        .scalars()
        .all()
    )

    german_rows = await session.execute(
        select(Project.id, Project.default_vat_rate)
        .where(Project.id.in_(project_ids))
        .where(Project.country_code == "DE")
    )
    german_projects = {project_id: vat_rate for project_id, vat_rate in german_rows.all()}

    today = datetime.now(UTC).date()
    claims_written = 0
    contracts_touched = 0

    for contract in contracts:
        if contract.id in claimed_ids:
            continue
        total_value = contract.total_value or Decimal("0")
        start = _parse_seed_date(contract.start_date)
        if total_value <= 0 or start is None or start >= today:
            continue

        end = _parse_seed_date(contract.end_date)
        contract_months = max(len(_month_starts(start, end)) if end and end > start else 12, 1)
        periods = _month_starts(start, today)[-_MAX_CLAIM_PERIODS:]
        if not periods:
            continue

        rng = random.Random(f"progress-claims:{contract.code}")
        retention_pct = (contract.retention_percent or Decimal("0")) / Decimal("100")
        # A German claim is cut by its rate of the payment with VAT in it, as
        # the service holds it (ContractsService.retention_basis); a seeded
        # Abschlagsrechnung must not hold less than a real one would.
        basis_vat = None
        if contract.project_id in german_projects:
            einvoice = (contract.metadata_ or {}).get("einvoice") if isinstance(contract.metadata_, dict) else None
            basis_vat = resolve_retention_basis(
                "DE",
                agreed_vat_rate=einvoice.get("vat_rate") if isinstance(einvoice, dict) else None,
                project_vat_rate=german_projects[contract.project_id],
                subcontract=(contract.counterparty_type or "client") == "subcontractor",
            ).vat_percent
        monthly_base = total_value / Decimal(contract_months)

        # Lifecycle ladder, newest period first: the running month is still in
        # draft, the last full month is submitted, one is under approval or
        # certification, everything older is paid.
        ladder = ["draft", "submitted", rng.choice(("approved", "certified"))]
        statuses: list[str] = []
        for idx_from_end in range(len(periods)):
            statuses.append(ladder[idx_from_end] if idx_from_end < len(ladder) else "paid")
        statuses.reverse()
        if statuses[-1] == "draft" and len(statuses) == 1:
            # A register whose only claim is an untouched draft reads dead.
            statuses[-1] = "submitted"

        prior_total = Decimal("0.00")
        for seq, (period_start, status) in enumerate(zip(periods, statuses, strict=True), start=1):
            period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            wobble = Decimal(str(rng.uniform(0.72, 1.28)))
            gross = (monthly_base * wobble).quantize(Decimal("1")) + Decimal("0.00")
            if gross <= 0:
                gross = Decimal("100.00")
            retention = (on_retention_basis(gross, basis_vat) * retention_pct).quantize(Decimal("0.01"))

            # Never stamp a submission in the future: a contract young enough
            # to have only its running period gets "submitted today".
            submitted_day = min(period_end + timedelta(days=3), today)
            approved_day = submitted_day + timedelta(days=14)
            paid_day = approved_day + timedelta(days=12)
            is_submitted = status != "draft"
            is_approved = status in ("approved", "certified", "paid")

            number = f"AZ-{seq:02d}" if contract.project_id in german_projects else f"PC-{seq:04d}"
            period = {
                "period_start": period_start.isoformat(),
                "period_end": min(period_end, today).isoformat(),
                "claim_date": submitted_day.isoformat() if is_submitted else None,
            }
            session.add(
                ProgressClaim(
                    contract_id=contract.id,
                    claim_number=number,
                    **period,
                    # The service writes the dates beside the strings, so the
                    # seed does too rather than leaving them to the boot repair.
                    **claim_dates_for_write(period),
                    gross_amount=gross,
                    retention_amount=retention,
                    prior_claims_total=prior_total,
                    net_due=gross - retention,
                    status=status,
                    submitted_at=_stamp(submitted_day, 10) if is_submitted else None,
                    approved_at=_stamp(approved_day, 14) if is_approved else None,
                    paid_at=_stamp(paid_day, 11) if status == "paid" else None,
                    currency=contract.currency or "",
                    metadata_=dict((contract.metadata_ or {}), seeded=True),
                )
            )
            prior_total += gross
            claims_written += 1
        contracts_touched += 1

    if claims_written:
        await session.flush()
        logger.info(
            "seed_progress_claims_demo: %d claims across %d contracts",
            claims_written,
            contracts_touched,
        )
    return {"claims_backfilled": claims_written, "contracts_backfilled": contracts_touched}


_CENT = Decimal("0.01")
_RATE_STEP = Decimal("0.0001")

#: A lump-priced package is billed as a lump, so its quantity is one and its
#: rate is the whole line. Any other unit gets a quantity worked back from a
#: plausible rate.
_LUMP = "lsum"


@dataclass(frozen=True)
class _SovTemplate:
    """One row of a schedule-of-values shape.

    ``weight`` is relative, never absolute, so the same shape fits a 400k
    subcontract and a 40m head contract. The rate band decides the quantity
    rather than the other way round, which is what keeps a rate per m3
    believable at either size: fixing the quantity instead would price a
    cubic metre of concrete at four figures on a large job.
    """

    description: str
    line_type: str
    unit: str
    weight: Decimal
    rate_low: Decimal
    rate_high: Decimal
    #: Position number as the schedule itself numbers it. The English shapes
    #: leave it empty and are numbered by position; the German shapes carry
    #: real DIN 276 cost-group and Leistungsverzeichnis numbers, which are the
    #: reference a Kalkulator reads the row by and are not sequential.
    code: str = ""


def _tpl(
    description: str,
    line_type: str,
    unit: str,
    weight: str,
    low: str = "0",
    high: str = "0",
    code: str = "",
) -> _SovTemplate:
    return _SovTemplate(description, line_type, unit, Decimal(weight), Decimal(low), Decimal(high), code)


#: A contract priced as a whole is broken down by work section, the way a
#: building contract's schedule of values reads on a G703 continuation sheet.
_SOV_SECTIONAL: tuple[_SovTemplate, ...] = (
    _tpl("Preliminaries and site establishment", "work", _LUMP, "6"),
    _tpl("Substructure and foundations", "work", "m3", "14", "160", "280"),
    _tpl("Superstructure frame and slabs", "work", "m3", "18", "300", "620"),
    _tpl("Roofing and external envelope", "work", "m2", "13", "90", "190"),
    _tpl("Internal walls and partitions", "work", "m2", "8", "40", "95"),
    _tpl("Windows, doors and glazing", "material", "pcs", "7", "400", "1600"),
    _tpl("Mechanical and plumbing services", "work", _LUMP, "12"),
    _tpl("Electrical services and lighting", "work", _LUMP, "10"),
    _tpl("Finishes and fit-out", "work", "m2", "8", "60", "150"),
    # Smallest weight on purpose: this is the line that carries the rounding
    # remainder, and a remainder belongs on the narrowest item in the schedule.
    _tpl("Commissioning, testing and handover", "work", _LUMP, "4"),
)

#: A contract remeasured against what was actually built is broken down by
#: measured item, so almost every line carries a real unit and quantity.
_SOV_MEASURED: tuple[_SovTemplate, ...] = (
    _tpl("Site establishment and access", "work", _LUMP, "5"),
    _tpl("Excavation and earthworks", "work", "m3", "16", "20", "48"),
    _tpl("Reinforcement supply and fixing", "material", "kg", "18", "1.2", "2.6"),
    _tpl("Formwork to slabs and walls", "work", "m2", "15", "35", "75"),
    _tpl("Concrete placement and curing", "work", "m3", "20", "120", "230"),
    _tpl("Blockwork and masonry", "work", "m2", "12", "45", "98"),
    _tpl("Waterproofing and movement joints", "work", "m", "10", "25", "62"),
    # The remainder line, as above.
    _tpl("Testing, records and as-built information", "work", _LUMP, "4"),
)

#: Which shape a contract takes. A remeasurement or unit-price agreement is
#: measured; everything else is priced in sections.
_MEASURED_TYPES: frozenset[str] = frozenset({"remeasurement", "unit_price", "tm"})


@dataclass(frozen=True)
class SovLine:
    """One schedule-of-values line, arithmetic already closed.

    ``total_value`` is always exactly ``quantity * unit_rate``. Nothing here
    stores a total that its own rate and quantity cannot produce.
    """

    code: str
    description: str
    line_type: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal
    total_value: Decimal


def split_to_cents(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Split ``total`` across ``weights`` so the parts re-add to it exactly.

    Rounding each share independently leaves a remainder of a few cents. That
    remainder is given to the smallest share rather than spread or dropped:
    on the narrowest line a cent is invisible, and on a broad one it is the
    difference between a schedule that sums to the contract value and a
    schedule that nearly does.

    Args:
        total: Amount to divide. May be any sign; zero yields zero parts.
        weights: Relative, non-negative weights. Must not sum to zero.

    Returns:
        One Decimal per weight, quantized to cents, summing to ``total``.
    """
    if not weights:
        return []
    weight_sum = sum(weights, Decimal("0"))
    if weight_sum <= 0:
        raise ValueError("schedule-of-values weights must sum to more than zero")
    parts = [(total * weight / weight_sum).quantize(_CENT, rounding=ROUND_HALF_UP) for weight in weights]
    remainder = total.quantize(_CENT, rounding=ROUND_HALF_UP) - sum(parts, Decimal("0"))
    if remainder:
        narrowest = min(range(len(parts)), key=lambda i: (parts[i], i))
        parts[narrowest] += remainder
    return parts


def build_schedule_of_values(
    contract_value: Decimal,
    contract_type: str,
    rng: random.Random,
) -> list[SovLine]:
    """Build a schedule of values that sums to ``contract_value`` exactly.

    Two invariants hold for every result, and both are asserted by the tests
    rather than trusted:

    1. Each line's ``total_value`` is exactly ``quantity * unit_rate``.
    2. The lines sum to ``contract_value`` to the cent.

    Holding both at once is the whole difficulty. A quantity times a rate
    rounded to four places does not land on the share the split asked for, so
    the shares drift by fractions of a cent. The drift is collected and
    settled on the final line, which every shape defines as its smallest and
    prices as a lump: with a quantity of one, a rate can absorb any value and
    still multiply out exactly.

    Args:
        contract_value: The contract sum the schedule must add up to.
        contract_type: Machine code, for instance ``lump_sum`` or
            ``remeasurement``, deciding which shape is used.
        rng: Seeded generator, so a given contract always yields the same
            schedule.

    Returns:
        The lines, in schedule order. Empty when ``contract_value`` is too
        small to break down, which the caller reports rather than swallows.
    """
    if contract_value is None or contract_value <= 0:
        return []
    templates = _SOV_MEASURED if contract_type in _MEASURED_TYPES else _SOV_SECTIONAL
    return _materialize(contract_value, templates, rng)


def _materialize(
    contract_value: Decimal,
    templates: tuple[_SovTemplate, ...],
    rng: random.Random,
) -> list[SovLine]:
    """Turn one shape into priced lines whose arithmetic closes.

    The only place either invariant is enforced, so the English and German
    catalogues cannot drift apart on the arithmetic: a catalogue chooses
    wording, weights and rate bands, and this decides every number.

    Args:
        contract_value: The sum the lines must add up to.
        templates: The shape, whose last entry carries the remainder.
        rng: Seeded generator for the rate inside each band.

    Returns:
        The lines, or empty when the value is too small to carry the shape.
    """
    parts = split_to_cents(contract_value, [tpl.weight for tpl in templates])

    lines: list[SovLine] = []
    running = Decimal("0")
    for index, (tpl, part) in enumerate(zip(templates[:-1], parts[:-1], strict=True)):
        if tpl.unit == _LUMP or tpl.rate_high <= 0:
            quantity = Decimal("1")
            unit_rate = part
        else:
            target_rate = Decimal(str(rng.uniform(float(tpl.rate_low), float(tpl.rate_high))))
            whole = int((part / target_rate).to_integral_value(rounding=ROUND_HALF_UP))
            quantity = Decimal(max(whole, 1))
            unit_rate = (part / quantity).quantize(_RATE_STEP, rounding=ROUND_HALF_UP)
        total = quantity * unit_rate
        running += total
        lines.append(
            SovLine(
                code=tpl.code or f"{index + 1:02d}",
                description=tpl.description,
                line_type=tpl.line_type,
                unit=tpl.unit,
                quantity=quantity,
                unit_rate=unit_rate,
                total_value=total,
            )
        )

    # The closing line takes whatever the rest did not, so the schedule adds
    # up. Quantity one keeps rate times quantity exact for any value it lands
    # on; a remainder that made this line worthless or negative means the
    # contract was too small to carry this shape, and no schedule is written.
    final = templates[-1]
    closing = contract_value - running
    if closing <= 0:
        return []
    lines.append(
        SovLine(
            code=final.code or f"{len(templates):02d}",
            description=final.description,
            line_type=final.line_type,
            unit=_LUMP,
            quantity=Decimal("1"),
            unit_rate=closing,
            total_value=closing,
        )
    )
    return lines


def apportion_claim(gross: Decimal, capacities: Sequence[Decimal]) -> list[Decimal]:
    """Spread one claim's gross amount across the schedule's remaining room.

    A continuation sheet reads down the schedule in order: the early trades
    finish, the middle ones are part done, the late ones have not started. So
    the amount fills each line up to what is left of it before moving to the
    next, which is both what a real claim run looks like and what guarantees
    no line is ever billed past its scheduled value.

    Args:
        gross: The claim's gross amount, taken as given.
        capacities: Room left on each schedule line, in schedule order.

    Returns:
        One amount per line, summing to ``gross`` unless the schedule ran out
        of room first, in which case the total is the room there was. The
        caller is expected to notice the shortfall rather than hide it.
    """
    taken = [Decimal("0")] * len(capacities)
    remaining = gross
    for index, capacity in enumerate(capacities):
        if remaining <= 0:
            break
        if capacity <= 0:
            continue
        take = capacity if capacity < remaining else remaining
        taken[index] = take
        remaining -= take
    return taken


#: Demo projects whose contracts are worded in German, and whose schedules are
#: therefore written by :func:`build_schedule_of_values_de` instead of the
#: generic English shapes above. A German main contract reading "Substructure
#: and foundations" underneath it is the most visible half-translated thing a
#: viewer of the filmed cases can see.
#:
#: Deliberately a superset of :data:`~app.core.demo_showcase.GERMAN_SHOWCASE_DEMO_IDS`
#: rather than that set itself, because the two ask different questions. That
#: set means "this project's register is hand-authored in German"; this one
#: means "this project's contracts are worded in German". ``residential-berlin``
#: is the project where the answers differ: its subcontracts are "Baugrube /
#: Erdbau", "Gründung" and "Außenwände", but ``seed_variations_showcase_de`` and
#: ``seed_daily_diary_showcase_de`` hold hand-authored content for the other
#: four demo ids only. Adding Berlin to the shared set would filter it out of
#: the generic English sprinkles and hand it nothing in return, emptying its
#: variations register to fix its contract wording.
_GERMAN_CONTRACT_PROJECTS: frozenset[str] = GERMAN_SHOWCASE_DEMO_IDS | {"residential-berlin"}

#: Positions for a German subcontract, keyed by the trade its title names.
#: The wording, units and rate bands are harvested from the bills this estate
#: already ships - the DIN 276 Kostenberechnung in :mod:`app.core.demo_projects`
#: and the Leistungsverzeichnis in the retail-market demo packs - rather than
#: translated from the English shapes, because a schedule of values is read by
#: people who know what these positions are called.
#:
#: Units stay in the schema's own vocabulary (``m``, ``m2``, ``m3``, ``t``,
#: ``pcs``, ``lsum``). German belongs in the description; a unit is a code.
_DE_TRADES: dict[str, tuple[_SovTemplate, ...]] = {
    "baustelleneinrichtung": (
        _tpl("Baustelle einrichten und räumen, An- und Abtransport Geräte", "work", _LUMP, "18", code="01.01"),
        _tpl("Bauzaun mobil h = 2,0 m, Vorhaltung für die Bauzeit", "work", "m", "6", "18", "26", code="01.02"),
        _tpl("Bauzufahrt und Baustraße Schotter, herstellen und rückbauen", "work", "m2", "9", "16", "23", "01.03"),
        _tpl("Büro- und Sozialcontainer, Vorhaltung für die Bauzeit", "material", "pcs", "11", "2400", "3400", "01.04"),
        _tpl("Baustromversorgung inkl. Verteiler und Verbrauch", "work", _LUMP, "10", code="01.05"),
        _tpl("Bauwasseranschluss inkl. Verbrauch", "work", _LUMP, "6", code="01.06"),
        _tpl("Turmdrehkran, Montage, Vorhaltung und Betrieb", "work", _LUMP, "20", code="01.07"),
        _tpl("Bauleitung und Bauüberwachung", "work", _LUMP, "14", code="01.08"),
        _tpl("Sicherheits- und Gesundheitsschutzkoordination nach BaustellV", "work", _LUMP, "4", code="01.09"),
    ),
    "rohbau": (
        _tpl("Sauberkeitsschicht C12/15", "work", "m2", "4", "10", "16", code="04.01"),
        _tpl("Streifen- und Einzelfundamente C25/30", "work", "m3", "12", "205", "270", code="04.02"),
        _tpl("Bodenplatte C30/37, d = 25 cm, bewehrt", "work", "m3", "18", "250", "320", code="04.03"),
        _tpl("Bewehrung BSt 500 S, geschnitten und gebogen", "material", "t", "16", "1650", "2050", code="04.04"),
        _tpl("Schalung Wände und Decken, Rahmenschalung", "work", "m2", "12", "28", "39", code="04.05"),
        _tpl("Stahlbetonstützen und -unterzüge", "work", "m3", "13", "375", "480", code="04.06"),
        _tpl("Mauerwerk KS-Plansteine, d = 24 cm", "work", "m2", "10", "60", "86", code="04.07"),
        _tpl("Industrieboden Hartstoffeinstreu, maschinell geglättet", "work", "m2", "11", "36", "54", "04.08"),
        _tpl("Nebenleistungen und Stundenlohnarbeiten", "work", _LUMP, "4", code="04.09"),
    ),
    "erdbau": (
        _tpl("Baustraße Schottertragschicht", "work", "m2", "5", "24", "34", code="02.01"),
        _tpl("Spundwandverbau Larssen 603", "work", "m2", "16", "82", "110", code="02.02"),
        _tpl("Aushub Baugrube, Bodenklasse 3 bis 5", "work", "m3", "20", "12", "19", code="02.03"),
        _tpl("Bodenabtransport und Entsorgung", "work", "m3", "17", "18", "27", code="02.04"),
        _tpl("Grundwasserabsenkung und offene Wasserhaltung", "work", _LUMP, "13", code="02.05"),
        _tpl("Verfüllung und Hinterfüllung, lagenweise verdichtet", "work", "m3", "10", "14", "20", "02.06"),
        _tpl("Böschungssicherung", "work", "m2", "7", "32", "45", code="02.07"),
        _tpl("Verdichtung Planum, Proctordichte 98 Prozent", "work", "m2", "6", "4", "7", code="02.08"),
        _tpl("Kampfmittelsondierung", "work", "m2", "3", "2.6", "4.2", code="02.09"),
        _tpl("Nebenleistungen und Stundenlohnarbeiten", "work", _LUMP, "3", code="02.10"),
    ),
    "gruendung": (
        _tpl("Sauberkeitsschicht C12/15", "work", "m2", "4", "10", "16", code="320.01"),
        _tpl("Bohrpfähle d = 600 mm", "work", "m", "20", "125", "168", code="320.02"),
        _tpl("Pfahlkopfplatten", "work", "m3", "10", "270", "350", code="320.03"),
        _tpl("Grundbalken", "work", "m3", "11", "260", "330", code="320.04"),
        _tpl("Bodenplatte C30/37, d = 30 cm, bewehrt", "work", "m3", "19", "250", "320", code="320.05"),
        _tpl("Abdichtung KMB unter Bodenplatte", "work", "m2", "12", "36", "49", code="320.06"),
        _tpl("Perimeterdämmung XPS 120 mm", "material", "m2", "10", "42", "55", code="320.07"),
        _tpl("Drainageleitung DN 150", "work", "m", "8", "56", "75", code="320.08"),
        _tpl("Nebenleistungen und Stundenlohnarbeiten", "work", _LUMP, "3", code="320.09"),
    ),
    "aussenwaende": (
        _tpl("Stahlbetonwände C30/37, d = 25 cm", "work", "m3", "18", "340", "425", code="330.01"),
        _tpl("Schalung Wände, Rahmenschalung", "work", "m2", "13", "28", "39", code="330.02"),
        _tpl("Bewehrung BSt 500 S, inkl. Biegen", "material", "t", "15", "1650", "2050", code="330.03"),
        _tpl("Kelleraußenwand WU-Beton, d = 30 cm", "work", "m3", "11", "355", "440", code="330.04"),
        _tpl("WDVS Mineralwolle 160 mm", "work", "m2", "16", "88", "115", code="330.05"),
        _tpl("Mineralischer Oberputz", "work", "m2", "9", "24", "34", code="330.06"),
        _tpl("Fenstersturz Stahlbeton", "work", "m", "6", "58", "76", code="330.07"),
        _tpl("Fensterbänke außen, Aluminium", "material", "m", "5", "37", "49", code="330.08"),
        _tpl("Dehnungsfugen Fassade", "work", "m", "4", "30", "41", code="330.09"),
        _tpl("Nebenleistungen und Stundenlohnarbeiten", "work", _LUMP, "3", code="330.10"),
    ),
}

#: Which trade a German contract title names. Ordered, and the first hit wins:
#: "LV 04 - Rohbau: Gruendung, Bodenplatte, Industrieboden, Massivbau" names
#: two trades and is a Rohbau package, so Rohbau has to be tested before
#: Gruendung. Matching is on the title because that is what the estate
#: actually varies; a contract naming no trade gets the ladder for its project.
_DE_TRADE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("baustelleneinrichtung", ("Baustelleneinrichtung", "Gemeinkosten")),
    ("rohbau", ("Rohbau", "Massivbau")),
    ("erdbau", ("Baugrube", "Erdbau", "Erschließung", "Erschliessung")),
    ("gruendung", ("Gründung", "Gruendung", "Unterbau", "Bodenplatte")),
    ("aussenwaende", ("Außenwände", "Aussenwaende", "Fassade", "Baukonstruktionen")),
)

#: A German building contract taken as a whole, broken down by DIN 276 cost
#: group. This is how the Kostenberechnung in this estate is already
#: structured, so the head contract's schedule and the project's own bill
#: speak the same ladder. KG 700 closes it: Baunebenkosten is genuinely the
#: last group in DIN 276, so the line that carries the rounding remainder is
#: also the line that belongs at the bottom.
_DE_KG_LADDER: tuple[_SovTemplate, ...] = (
    _tpl("KG 300 - Baugrube und Erdbau", "work", "m3", "6", "20", "42", code="300"),
    _tpl("KG 320 - Gründung und Unterbau", "work", "m3", "10", "240", "335", code="320"),
    _tpl("KG 330 - Außenwände und Fassade", "work", "m2", "14", "185", "330", code="330"),
    _tpl("KG 340 - Innenwände", "work", "m2", "8", "52", "115", code="340"),
    _tpl("KG 350 - Decken und Bodenbeläge", "work", "m2", "11", "125", "245", code="350"),
    _tpl("KG 360 - Dächer und Abdichtung", "work", "m2", "7", "115", "215", code="360"),
    _tpl("KG 370 - Baukonstruktive Einbauten", "work", _LUMP, "3", code="370"),
    _tpl("KG 390 - Baustelleneinrichtung und sonstige Maßnahmen", "work", _LUMP, "5", code="390"),
    _tpl("KG 410 - Abwasser, Wasser, Gas", "work", _LUMP, "6", code="410"),
    _tpl("KG 420 - Wärmeversorgungsanlagen", "work", _LUMP, "7", code="420"),
    _tpl("KG 430 - Raumlufttechnische Anlagen", "work", _LUMP, "8", code="430"),
    _tpl("KG 440 - Elektrotechnische Anlagen", "work", _LUMP, "10", code="440"),
    _tpl("KG 500 - Aufzugsanlagen", "material", "pcs", "4", "62000", "98000", code="500"),
    _tpl("KG 540 - Außenanlagen und Freiflächen", "work", "m2", "4", "58", "145", code="540"),
    _tpl("KG 700 - Baunebenkosten", "work", _LUMP, "3", code="700"),
)

#: A German retail-market contract taken as a whole, broken down by the
#: Leistungsverzeichnis sections those projects are actually procured in. The
#: numbering is theirs, gaps included: the packs run 01, 02, 04 to 09 and 14 to
#: 19, and inventing an LV 03 to make the list look tidy would put a section
#: number in the register that the procurement side has never heard of.
_DE_LV_LADDER: tuple[_SovTemplate, ...] = (
    _tpl("LV 01 - Baustelleneinrichtung und Gemeinkosten", "work", _LUMP, "5", code="01"),
    _tpl("LV 02 - Erdbau und Erschließung", "work", "m3", "11", "18", "34", code="02"),
    _tpl("LV 04 - Rohbau: Gründung, Bodenplatte, Industrieboden, Massivbau", "work", "m3", "16", "240", "330", "04"),
    _tpl("LV 05 - Dach: Trapezblech, Dämmung, Abdichtung, RWA", "work", "m2", "11", "95", "185", code="05"),
    _tpl("LV 06 - Stahlbeton-Fertigteile und BSH-Binder", "material", "m3", "10", "420", "680", code="06"),
    _tpl("LV 07 - Fassade: Sandwichpaneele, Sockel", "work", "m2", "8", "120", "230", code="07"),
    _tpl("LV 08 - Fenster, Türen, Tore, Pfosten-Riegel-Fassade", "material", "pcs", "5", "850", "3200", "08"),
    _tpl("LV 09 - Innenausbau: Trockenbau, Fliesen, Maler, Innentüren, Decken", "work", "m2", "6", "58", "135", "09"),
    _tpl("LV 14 - HLS: Sanitär, Wärmepumpe, Fußbodenheizung, RLT", "work", _LUMP, "12", code="14"),
    _tpl("LV 15 - Kältetechnik CO2-Verbund und Kühlmöbel", "work", _LUMP, "9", code="15"),
    _tpl("LV 16 - Elektrotechnik inkl. BMA und GLT", "work", _LUMP, "8", code="16"),
    _tpl("LV 17 - PV-Anlage, Batteriespeicher, Ladeinfrastruktur", "work", _LUMP, "5", code="17"),
    _tpl("LV 18 - Außenanlagen, Stellplätze, Entwässerung", "work", "m2", "4", "55", "130", code="18"),
    _tpl("LV 19 - Werbepylon, Einkaufswagen-Boxen, Anfahrschutz", "work", _LUMP, "2", code="19"),
)

#: Demo ids procured as a Leistungsverzeichnis rather than by DIN 276 cost
#: group. Both are German and both are correct; which one a contract uses is a
#: property of how the job was tendered, not of the language.
_DE_LV_PROJECTS: frozenset[str] = frozenset(
    {"retail-market-heidelberg", "retail-market-karlsruhe", "retail-market-heilbronn"}
)


def pick_german_shape(title: str, demo_id: str) -> tuple[_SovTemplate, ...]:
    """Choose the German schedule shape for one contract.

    A subcontract is broken down into the positions of the trade its title
    names. A contract naming no trade is a main contract, and takes the ladder
    its project was procured under.

    Only the scope half of the title is read. The estate writes subcontracts as
    "Subcontract - <scope> (<company>)", and a construction company is very
    often named after a trade it does not hold on this job: "Subcontract -
    Außenwände (Kessmar Rohbau GmbH)" is an external-walls package let to a
    firm with Rohbau in its name, and matching the whole string would give it
    a shell-and-core schedule.

    Args:
        title: The contract's title, as the estate wrote it.
        demo_id: The owning project's demo marker, deciding the ladder.

    Returns:
        The templates for this contract, never empty.
    """
    haystack = (title or "").split("(", 1)[0]
    for trade, keywords in _DE_TRADE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return _DE_TRADES[trade]
    return _DE_LV_LADDER if demo_id in _DE_LV_PROJECTS else _DE_KG_LADDER


def build_schedule_of_values_de(
    contract_value: Decimal,
    title: str,
    demo_id: str,
    rng: random.Random,
) -> list[SovLine]:
    """Build a German schedule of values that sums to ``contract_value`` exactly.

    Same two invariants as :func:`build_schedule_of_values`, and the same
    closing-lump mechanism for holding both at once. What differs is only the
    catalogue: real Kostengruppen and LV positions in place of translated
    English section names, numbered the way the schedule itself numbers them.

    Args:
        contract_value: The contract sum the schedule must add up to.
        title: The contract's title, used to find the trade it covers.
        demo_id: The owning project's demo marker.
        rng: Seeded generator, so a given contract always yields the same
            schedule.

    Returns:
        The lines, in schedule order. Empty when ``contract_value`` is too
        small to carry the shape.
    """
    if contract_value is None or contract_value <= 0:
        return []
    return _materialize(contract_value, pick_german_shape(title, demo_id), rng)


async def seed_contract_lines_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Give every line-less contract of the given projects a schedule of values.

    The catalog fabricated by :func:`seed_contracts_demo` writes its own SoV
    lines, but it only ever runs on a project holding no contract at all, and
    a demo project arrives with an authored head contract and trade
    subcontracts. So on a real demo estate that code path never executes and
    every contract has an agreed value with nothing behind it: no continuation
    sheet, no claim broken down by line, nothing for anything reading a
    contract's own breakdown to read.

    The guard is per contract, not per project. A project whose head contract
    already had a schedule would otherwise stand in for its subcontracts and
    leave them empty, which is the same shape of mistake as letting an
    installer's thin rows pass for a seeded estate.

    Draft contracts are included on purpose: a schedule of values is what a
    contract is agreed against, so it exists before signature, not after.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Projects whose contracts are eligible. Empty is a no-op.

    Returns:
        Dict with ``lines_backfilled``, ``contracts_scheduled`` and
        ``contracts_unpriced`` counts, the last being contracts skipped for
        having no value to break down.
    """
    if not project_ids:
        return _no_schedules()

    demo_ids = await _demo_ids_by_project(session, project_ids)
    # The German-worded projects are served by seed_contract_lines_showcase_de
    # and are dropped here rather than in it, so the English catalogue is never
    # even offered a German contract. The guard below is per contract, so the
    # two seeders could not overwrite each other in any order; this filter is
    # about which catalogue a contract is entitled to, not about collisions.
    english = [pid for pid in project_ids if demo_ids.get(pid, "") not in _GERMAN_CONTRACT_PROJECTS]
    if not english:
        return _no_schedules()

    def build(contract: Contract, _demo_id: str) -> list[SovLine]:
        rng = random.Random(f"contract-lines:{contract.code}")
        return build_schedule_of_values(
            contract.total_value or Decimal("0"),
            contract.contract_type or "",
            rng,
        )

    return await _backfill_schedules(session, english, demo_ids, build, "seed_contract_lines_demo")


def _no_schedules() -> dict[str, int]:
    """The report shape every schedule seeder returns when it writes nothing."""
    return {"lines_backfilled": 0, "contracts_scheduled": 0, "contracts_unpriced": 0}


async def _demo_ids_by_project(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Map project id -> its demo marker (empty string for a real project)."""
    rows = await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(project_ids)))
    return {pid: (str(meta.get("demo_id") or "").strip() if isinstance(meta, dict) else "") for pid, meta in rows.all()}


async def _backfill_schedules(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    demo_ids: dict[uuid.UUID, str],
    build: Callable[[Contract, str], list[SovLine]],
    log_label: str,
) -> dict[str, int]:
    """Write a schedule for each contract of ``project_ids`` that has none.

    Shared by the English and German seeders so the guard, the ordering and
    the row writing exist once. Only the catalogue differs between them, and
    that is what ``build`` supplies.

    The guard is per contract, not per project. A project whose head contract
    already had a schedule would otherwise stand in for its subcontracts and
    leave them empty, which is the same shape of mistake as letting an
    installer's thin rows pass for a seeded estate.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Projects whose contracts are eligible.
        demo_ids: Demo marker per project, passed to ``build``.
        build: Turns one contract into its schedule, empty to skip it.
        log_label: Seeder name for the log line.

    Returns:
        Dict with ``lines_backfilled``, ``contracts_scheduled`` and
        ``contracts_unpriced`` counts.
    """
    contracts = (
        (await session.execute(select(Contract).where(Contract.project_id.in_(project_ids)).order_by(Contract.code)))
        .scalars()
        .all()
    )
    if not contracts:
        return _no_schedules()

    scheduled_ids = set(
        (
            await session.execute(
                select(ContractLine.contract_id.distinct()).where(
                    ContractLine.contract_id.in_([c.id for c in contracts])
                )
            )
        )
        .scalars()
        .all()
    )

    lines_written = 0
    contracts_touched = 0
    unpriced = 0

    for contract in contracts:
        if contract.id in scheduled_ids:
            continue
        schedule = build(contract, demo_ids.get(contract.project_id, ""))
        if not schedule:
            unpriced += 1
            continue
        for order_index, line in enumerate(schedule):
            session.add(
                ContractLine(
                    contract_id=contract.id,
                    code=line.code,
                    description=line.description,
                    line_type=line.line_type,
                    unit=line.unit,
                    quantity=line.quantity,
                    unit_rate=line.unit_rate,
                    total_value=line.total_value,
                    order_index=order_index,
                )
            )
            lines_written += 1
        contracts_touched += 1

    if lines_written:
        await session.flush()
        logger.info(
            "%s: %d lines across %d contracts (%d unpriced)",
            log_label,
            lines_written,
            contracts_touched,
            unpriced,
        )
    return {
        "lines_backfilled": lines_written,
        "contracts_scheduled": contracts_touched,
        "contracts_unpriced": unpriced,
    }


async def seed_contract_lines_showcase_de(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Give the German-worded demo contracts a German schedule of values.

    The counterpart to :func:`seed_contract_lines_demo`, which filters these
    projects out. A contract titled "Subcontract - Baugrube / Erdbau" is read
    by people who call those positions Aushub and Verbau, and a continuation
    sheet listing "Excavation and earthworks" underneath it is the kind of
    half-translated surface that a viewer notices before anything else on the
    screen. These are the filmed projects, so the schedule is written in the
    language the rest of their register is already in.

    The breakdown follows the contract, not just the language: a subcontract
    is split into the positions of the trade its title names, and a main
    contract into the ladder its project was procured under, DIN 276 cost
    groups for the buildings and the Leistungsverzeichnis for the retail
    markets.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Projects to consider. Non-German ones are ignored here,
            so callers can pass the whole estate.

    Returns:
        Same counts as :func:`seed_contract_lines_demo`.
    """
    if not project_ids:
        return _no_schedules()

    demo_ids = await _demo_ids_by_project(session, project_ids)
    german = [pid for pid in project_ids if demo_ids.get(pid, "") in _GERMAN_CONTRACT_PROJECTS]
    if not german:
        return _no_schedules()

    def build(contract: Contract, demo_id: str) -> list[SovLine]:
        rng = random.Random(f"contract-lines-de:{contract.code}")
        return build_schedule_of_values_de(
            contract.total_value or Decimal("0"),
            contract.title or "",
            demo_id,
            rng,
        )

    return await _backfill_schedules(session, german, demo_ids, build, "seed_contract_lines_showcase_de")


async def seed_progress_claim_lines_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Break each existing progress claim down against the schedule of values.

    Without this the payment application is two halves that do not meet. The
    claim carries a gross amount, the schedule carries the agreed values, and
    the G703 continuation sheet joining them reads every line as nil, so the
    G702 certificate face, which is a pure roll-up of those rows, certifies
    zero earned on a contract the register says is part billed.

    Each claim's stored ``gross_amount`` is taken as given and apportioned, so
    the certificate agrees with the register instead of quietly restating it.
    The run is filled in claim order and clamped to each line's remaining
    room, so a line is never billed past its scheduled value and the
    cumulative figure a continuation sheet prints is the real running total.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Projects whose contracts are eligible. Empty is a no-op.

    Returns:
        Dict with ``claim_lines_backfilled``, ``claims_broken_down`` and
        ``claims_over_schedule``, the last counting claims whose gross could
        not be placed because the schedule had no room left.
    """
    if not project_ids:
        return {"claim_lines_backfilled": 0, "claims_broken_down": 0, "claims_over_schedule": 0}

    contracts = (
        (await session.execute(select(Contract).where(Contract.project_id.in_(project_ids)).order_by(Contract.code)))
        .scalars()
        .all()
    )
    if not contracts:
        return {"claim_lines_backfilled": 0, "claims_broken_down": 0, "claims_over_schedule": 0}

    contract_ids = [c.id for c in contracts]
    broken_down = set(
        (
            await session.execute(
                select(ProgressClaim.id)
                .join(ProgressClaimLine, ProgressClaimLine.progress_claim_id == ProgressClaim.id)
                .where(ProgressClaim.contract_id.in_(contract_ids))
                .distinct()
            )
        )
        .scalars()
        .all()
    )

    lines_written = 0
    claims_touched = 0
    over_schedule = 0

    for contract in contracts:
        schedule = (
            (
                await session.execute(
                    select(ContractLine)
                    .where(ContractLine.contract_id == contract.id)
                    .order_by(ContractLine.order_index, ContractLine.code)
                )
            )
            .scalars()
            .all()
        )
        if not schedule:
            continue
        claims = (
            (
                await session.execute(
                    select(ProgressClaim)
                    .where(ProgressClaim.contract_id == contract.id)
                    .order_by(ProgressClaim.period_start, ProgressClaim.claim_number)
                )
            )
            .scalars()
            .all()
        )
        if not claims:
            continue

        # The running total per line has to survive the whole claim run, so
        # it is built once here rather than re-read per claim.
        billed = [Decimal("0")] * len(schedule)
        for claim in claims:
            gross = claim.gross_amount or Decimal("0")
            capacities = [(line.total_value or Decimal("0")) - billed[i] for i, line in enumerate(schedule)]
            amounts = apportion_claim(gross, capacities)
            placed = sum(amounts, Decimal("0"))
            if placed < gross:
                over_schedule += 1
            if claim.id in broken_down:
                # Already broken down by hand or by an earlier pass. The
                # running total still has to advance, or every later claim
                # would be measured against room this one already used.
                for i, amount in enumerate(amounts):
                    billed[i] += amount
                continue
            wrote_any = False
            for i, amount in enumerate(amounts):
                line = schedule[i]
                billed[i] += amount
                # A row is written for every line with any history, not only
                # for the ones moving this period. ``build_g703`` reads a
                # missing claim line as never billed and zeroes its
                # "completed from previous applications" column, so a line
                # finished last period would vanish from this period's
                # continuation sheet and the certificate would understate
                # what has been earned. A line not yet started has no history
                # and is correctly left absent.
                if amount <= 0 and billed[i] <= 0:
                    continue
                scheduled = line.total_value or Decimal("0")
                rate = line.unit_rate or Decimal("0")
                session.add(
                    ProgressClaimLine(
                        progress_claim_id=claim.id,
                        contract_line_id=line.id,
                        period_completed_qty=(
                            (amount / rate).quantize(_RATE_STEP, rounding=ROUND_HALF_UP) if rate > 0 else Decimal("0")
                        ),
                        period_completed_value=amount,
                        period_completed_pct=(
                            (amount / scheduled * Decimal("100")).quantize(_RATE_STEP, rounding=ROUND_HALF_UP)
                            if scheduled > 0
                            else Decimal("0")
                        ),
                        cumulative_completed_value=billed[i],
                    )
                )
                lines_written += 1
                wrote_any = True
            if wrote_any:
                claims_touched += 1

    if lines_written:
        await session.flush()
        logger.info(
            "seed_progress_claim_lines_demo: %d claim lines across %d claims (%d over schedule)",
            lines_written,
            claims_touched,
            over_schedule,
        )
    return {
        "claim_lines_backfilled": lines_written,
        "claims_broken_down": claims_touched,
        "claims_over_schedule": over_schedule,
    }


async def seed_contracts_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Generate demo contracts and backfill claim runs onto authored ones.

    The 10-type catalog is fabricated round-robin, but only into projects
    that hold no contract yet: demo projects arrive with an authored head
    contract plus trade subcontracts, and those registers must not be
    diluted with generic filler. Afterwards
    :func:`seed_progress_claims_demo` gives every claim-less live contract
    of the given projects its staged payment history.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: List of existing project UUIDs to distribute contracts to
            (round-robin). Empty list returns zero counts.

    Returns:
        Dict with counts: contracts, lines, claims, final_accounts,
        type_configs, fee_structures, gainshare_configs, claims_backfilled,
        contracts_backfilled.
    """
    if not project_ids:
        logger.info("seed_contracts_demo: no project_ids → skipping")
        return {
            "contracts": 0,
            "lines": 0,
            "claims": 0,
            "final_accounts": 0,
            "type_configs": 0,
            "fee_structures": 0,
            "gainshare_configs": 0,
            "claims_backfilled": 0,
            "contracts_backfilled": 0,
        }

    rng = random.Random(42)
    type_configs = await seed_type_configurations(session)

    # Contract codes are deterministic and the column is unique, so a second
    # run used to abort on the first duplicate rather than skip it. Re-seeding
    # is how the demo estate is refreshed, so it has to be a no-op here. The
    # existing codes are read once instead of probed per contract.
    existing_codes = set((await session.execute(select(Contract.code))).scalars().all())

    # Fabricate the catalog only into projects that own no contract at all.
    # The demo installer authors each demo project's own head contract and
    # subcontracts; those projects need the claim backfill below, not ten
    # more generic agreements on top of the authored register.
    occupied = set(
        (await session.execute(select(Contract.project_id.distinct()).where(Contract.project_id.in_(project_ids))))
        .scalars()
        .all()
    )
    empty_projects = [pid for pid in project_ids if pid not in occupied]

    contracts_count = 0
    lines_count = 0
    claims_count = 0
    final_account_count = 0
    fee_count = 0
    gainshare_count = 0

    for idx, c_type in enumerate(_TYPE_DISTRIBUTION):
        if not empty_projects:
            break
        project_id = empty_projects[idx % len(empty_projects)]
        code = f"CT-{idx + 1:03d}-{c_type.upper()[:3]}"
        if code in existing_codes:
            continue
        terms: dict[str, object] = {}
        if c_type == "gmp":
            terms = {
                "gmp_cap": str(Decimal("1000000") + idx * 100000),
                "target_cost": str(Decimal("900000") + idx * 100000),
                "gainshare_split_pct": "50",
            }
        elif c_type == "cost_plus":
            terms = {"fee_percent": "7.5"}
        elif c_type == "tm":
            terms = {"tm_nte_cap": str(Decimal("250000") + idx * 25000)}

        total_value = Decimal("100000") * (idx + 5)
        contract = Contract(
            code=code,
            title=f"{_TYPE_LABELS.get(c_type, c_type)} agreement {code}",
            contract_type=c_type,
            counterparty_type="subcontractor" if idx % 2 else "client",
            counterparty_id=uuid.uuid4(),
            project_id=project_id,
            total_value=total_value,
            currency="EUR",
            retention_percent=Decimal("5"),
            retention_release_event="substantial_completion",
            status="active",
            terms=terms,
        )
        session.add(contract)
        await session.flush()
        contracts_count += 1

        # SoV lines (5-15 per contract)
        line_count = rng.randint(5, 15)
        for li in range(line_count):
            qty = Decimal(str(rng.randint(1, 500)))
            rate = Decimal(str(rng.randint(50, 5000)))
            session.add(
                ContractLine(
                    contract_id=contract.id,
                    code=f"{idx + 1:02d}.{li + 1:03d}",
                    description=f"{_TYPE_LABELS.get(c_type, c_type)} works, item {li + 1}",
                    line_type=rng.choice(
                        ("work", "material", "labor", "fee", "contingency"),
                    ),
                    unit=rng.choice(("m", "m2", "m3", "kg", "pcs", "lsum")),
                    quantity=qty,
                    unit_rate=rate,
                    total_value=qty * rate,
                    order_index=li,
                )
            )
            lines_count += 1

        # FeeStructure for cost_plus / tm / design_build
        if c_type in ("cost_plus", "tm", "design_build"):
            session.add(
                FeeStructure(
                    contract_id=contract.id,
                    fee_type="percent_of_cost",
                    fee_percent=Decimal("7.5") if c_type == "cost_plus" else Decimal("5"),
                    fee_fixed_amount=None,
                    max_fee=None,
                    sliding_scale=[],
                )
            )
            fee_count += 1

        # GainshareConfiguration for GMP
        if c_type == "gmp":
            session.add(
                GainshareConfiguration(
                    contract_id=contract.id,
                    target_cost=Decimal(terms.get("target_cost") or 0),  # type: ignore[arg-type]
                    gmp_cap=Decimal(terms.get("gmp_cap") or 0),  # type: ignore[arg-type]
                    savings_split_owner_pct=Decimal("50"),
                    savings_split_contractor_pct=Decimal("50"),
                    overrun_responsibility="contractor",
                )
            )
            gainshare_count += 1

        # RetentionSchedule
        session.add(
            RetentionSchedule(
                contract_id=contract.id,
                accrual_rule={"per_claim_percent": 5},
                release_rule={"on_event": "practical_completion"},
                notes="Standard 5% retention",
            )
        )

        # LDClause
        session.add(
            LDClause(
                contract_id=contract.id,
                per_day_amount=Decimal("500"),
                currency="EUR",
                max_amount=Decimal("50000"),
                enforcement_status="active",
            )
        )

        # 4 progress claims
        statuses = ("paid", "approved", "submitted", "draft")
        for ci, st in enumerate(statuses):
            gross = total_value * Decimal(str(0.1 * (ci + 1)))
            retention = gross * Decimal("0.05")
            period = {
                "period_start": f"2026-0{ci + 1}-01",
                "period_end": f"2026-0{ci + 1}-28",
                "claim_date": f"2026-0{ci + 1}-28",
            }
            session.add(
                ProgressClaim(
                    contract_id=contract.id,
                    claim_number=f"PC-{ci + 1:04d}",
                    **period,
                    **claim_dates_for_write(period),
                    gross_amount=gross,
                    retention_amount=retention,
                    prior_claims_total=gross * Decimal(str(ci)),
                    net_due=gross - retention,
                    status=st,
                    currency="EUR",
                )
            )
            claims_count += 1

        # Close two of the contracts with a FinalAccount
        if idx in (0, 5):
            paid_amount = total_value * Decimal("0.95")
            session.add(
                FinalAccount(
                    contract_id=contract.id,
                    final_contract_value=total_value,
                    total_paid=paid_amount,
                    retention_held=total_value * Decimal("0.05"),
                    retention_released=Decimal("0"),
                    final_balance=total_value - paid_amount,
                    sign_off_date="2026-12-31",
                    status="closed",
                    notes="Final account agreed, 5% retention held to defects liability expiry.",
                )
            )
            final_account_count += 1

    await session.flush()

    # A schedule of values first, because the claim breakdown below is written
    # against it. The authored demo contracts all arrive with a value and no
    # lines, and the catalog above never reaches them.
    schedules = await seed_contract_lines_demo(session, project_ids)

    # The German-worded projects take theirs from the German catalogue. Two
    # calls rather than one switch, so neither language's schedule can be
    # reached by the other's projects. The claim breakdown below is language
    # agnostic: it apportions whatever schedule it finds, so it serves both.
    schedules_de = await seed_contract_lines_showcase_de(session, project_ids)

    # Backfill staged claim runs onto every claim-less live contract of the
    # given projects - the authored demo contracts above all, which is what
    # makes the payment-application registers non-empty out of the box.
    backfill = await seed_progress_claims_demo(session, project_ids)

    # Then break those claims down against the schedule. Until this runs the
    # G703 continuation sheet joins a priced schedule to nothing and the G702
    # face, a pure roll-up of it, certifies zero on a part-billed contract.
    claim_lines = await seed_progress_claim_lines_demo(session, project_ids)

    # The two schedule seeders report the same keys over disjoint projects, so
    # the estate-wide figure is their sum. The German half is reported on its
    # own key as well, because "how many contracts got a schedule" and "how
    # many got a German one" are different questions and a caller checking the
    # showcase wants the second.
    scheduled = {
        key: schedules[key] + schedules_de[key]
        for key in ("lines_backfilled", "contracts_scheduled", "contracts_unpriced")
    }

    logger.info(
        "seed_contracts_demo: %d contracts, %d lines, %d claims, %d final_accounts, %d type_configs, "
        "%d claims backfilled onto %d contracts, %d schedule lines onto %d contracts "
        "(%d lines on %d German contracts), %d claim lines",
        contracts_count,
        lines_count,
        claims_count,
        final_account_count,
        type_configs,
        backfill["claims_backfilled"],
        backfill["contracts_backfilled"],
        scheduled["lines_backfilled"],
        scheduled["contracts_scheduled"],
        schedules_de["lines_backfilled"],
        schedules_de["contracts_scheduled"],
        claim_lines["claim_lines_backfilled"],
    )
    return {
        "contracts": contracts_count,
        "lines": lines_count,
        "claims": claims_count,
        "final_accounts": final_account_count,
        "type_configs": type_configs,
        "fee_structures": fee_count,
        "gainshare_configs": gainshare_count,
        "claims_backfilled": backfill["claims_backfilled"],
        "contracts_backfilled": backfill["contracts_backfilled"],
        **scheduled,
        "schedule_lines_de": schedules_de["lines_backfilled"],
        "contracts_scheduled_de": schedules_de["contracts_scheduled"],
        **claim_lines,
    }
