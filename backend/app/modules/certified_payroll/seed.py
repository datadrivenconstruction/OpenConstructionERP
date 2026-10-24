# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo data for certified payroll on the US showcase projects.

A federal wage determination with six trade classifications, eight workers
placed under them, four weeks of daily payroll, three weeks certified and the
latest left in draft, so the WH-347 form, the compliance check and the signing
step all have something to show. Runs only for US projects and never twice.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.certified_payroll.models import WageClassification, WageDetermination
from app.modules.certified_payroll.schemas import (
    AssignmentCreate,
    CertifiedWeekCreate,
    CertifyRequest,
    WageClassificationCreate,
    WageDeterminationCreate,
)
from app.modules.certified_payroll.service import CertifiedPayrollService
from app.modules.payroll.models import PayrollBatch, PayrollEntry
from app.modules.projects.models import Project

# Locality and contractor per showcase; rates are typical published building
# rates for the area, rounded, and marked as demo data in the source note.
_SITES: dict[str, dict[str, str]] = {
    "commercial-denver": {
        "locality": "Denver County, Colorado",
        "jurisdiction": "US-CO",
        "identifier": "CO20260012",
        "contractor": "Front Range Builders LLC",
        "address": "1550 Wewatta St, Denver, CO 80202",
        "contract": "GS-08P-26-DEN-0147",
    },
    "medical-us": {
        "locality": "Maricopa County, Arizona",
        "jurisdiction": "US-AZ",
        "identifier": "AZ20260004",
        "contractor": "Desert Ridge Construction Inc.",
        "address": "2400 N Central Ave, Phoenix, AZ 85004",
        "contract": "VA-262-26-C-0031",
    },
}

# code, title, basic, fringe
_TRADES: list[tuple[str, str, str, str]] = [
    ("CARP0055-001", "Carpenter", "31.40", "11.85"),
    ("ELEC0068-002", "Electrician", "40.25", "15.60"),
    ("LABO0720-003", "Laborer: common or general", "23.10", "7.45"),
    ("PLUM0003-004", "Plumber", "39.80", "14.30"),
    ("IRON0024-005", "Ironworker, structural", "34.60", "16.90"),
    ("ENGI0009-006", "Power equipment operator: excavator", "36.15", "13.20"),
]

# name, last four, trade index, paid basic above the minimum
_CREW: list[tuple[str, str, int, str]] = [
    ("Marcus Reyes", "4417", 0, "2.10"),
    ("Daniel Okafor", "2290", 0, "0.00"),
    ("Linda Hart", "8031", 1, "1.75"),
    ("Jose Alvarez", "5562", 2, "0.90"),
    ("Kevin Brooks", "1178", 2, "0.00"),
    ("Samuel Pike", "6604", 3, "1.20"),
    ("Tyler Nguyen", "3349", 4, "0.50"),
    ("Robert Castillo", "9920", 5, "1.40"),
]

_WEEKS = 4
_SIGNATORY = ("Karen Whitfield", "Payroll Administrator")


def _last_saturday(today: date) -> date:
    return today - timedelta(days=(today.weekday() - 5) % 7 or 7)


def _hours(worker_ix: int, week_ix: int, day_ix: int) -> str:
    """Eight hours Monday to Friday, a short Saturday for part of the crew in some weeks."""
    if day_ix == 0:  # Sunday
        return "0"
    if day_ix == 6:  # Saturday
        return "4" if (worker_ix + week_ix) % 3 == 0 else "0"
    return "9" if (worker_ix + day_ix + week_ix) % 5 == 0 else "8"


async def seed_certified_payroll(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    today: date | None = None,
) -> dict[str, int]:
    """Seed certified payroll for one US showcase project. Returns counts, empty when skipped."""
    project = await session.get(Project, project_id)
    if project is None:
        return {}
    site = _SITES.get(str((project.metadata_ or {}).get("demo_id") or ""))
    if site is None:
        return {}
    existing = await session.execute(
        select(func.count()).select_from(WageDetermination).where(WageDetermination.project_id == project_id)
    )
    if existing.scalar_one():
        return {}

    svc = CertifiedPayrollService(session)
    week_end = _last_saturday(today or date.today())
    first_day = week_end - timedelta(days=7 * _WEEKS - 1)

    determination = await svc.create_determination(
        project_id,
        WageDeterminationCreate(
            authority="federal",
            authority_name="U.S. Department of Labor, Wage and Hour Division",
            jurisdiction=site["jurisdiction"],
            locality=site["locality"],
            identifier=site["identifier"],
            title=f"Building construction, {site['locality']}",
            decision_date=(first_day - timedelta(days=60)).isoformat(),
            effective_date=(first_day - timedelta(days=30)).isoformat(),
            statute_reference="Davis-Bacon Act, 40 U.S.C. 3141-3148; 29 CFR Parts 1, 3, 5",
            source_note="Demo data: rates are representative, not the published decision.",
            currency="USD",
            classifications=[
                WageClassificationCreate(code=c, title=t, basic_hourly_rate=b, fringe_rate=f, ordinal=i)
                for i, (c, t, b, f) in enumerate(_TRADES)
            ],
        ),
    )
    rows = await session.execute(
        select(WageClassification).where(WageClassification.determination_id == determination.id)
    )
    by_code = {c.code: c for c in rows.scalars()}

    for name, ssn4, trade_ix, premium in _CREW:
        code, _title, basic, fringe = _TRADES[trade_ix]
        await svc.create_assignment(
            project_id,
            AssignmentCreate(
                worker_name=name,
                worker_identifier=f"XXX-XX-{ssn4}",
                classification_id=by_code[code].id,
                valid_from=first_day.isoformat(),
                paid_basic_rate=str(Decimal(basic) + Decimal(premium)),
                paid_fringe_rate=fringe,
                fringe_election="plan",
            ),
        )

    batch = PayrollBatch(
        project_id=project_id,
        period_label=f"{first_day.isoformat()} to {week_end.isoformat()}",
        period_start=first_day.isoformat(),
        period_end=week_end.isoformat(),
        status="approved",
        currency="USD",
        notes="Demo payroll from the daily field reports.",
    )
    session.add(batch)
    await session.flush()

    total_hours = Decimal(0)
    total_amount = Decimal(0)
    entries = 0
    for week_ix in range(_WEEKS):
        start = first_day + timedelta(days=7 * week_ix)
        for day_ix in range(7):
            work_date = (start + timedelta(days=day_ix)).isoformat()
            for worker_ix, (name, _ssn4, trade_ix, premium) in enumerate(_CREW):
                hours = Decimal(_hours(worker_ix, week_ix, day_ix))
                if not hours:
                    continue
                rate = Decimal(_TRADES[trade_ix][2]) + Decimal(premium)
                amount = (hours * rate).quantize(Decimal("0.01"))
                session.add(
                    PayrollEntry(
                        batch_id=batch.id,
                        worker=name,
                        work_date=work_date,
                        hours=str(hours),
                        rate=str(rate),
                        amount=str(amount),
                        net_amount=str(amount),
                        currency="USD",
                        source="fieldreport",
                    )
                )
                total_hours += hours
                total_amount += amount
                entries += 1
    batch.total_hours = str(total_hours)
    batch.total_amount = str(total_amount)
    batch.total_net = str(total_amount)
    batch.entry_count = entries
    await session.flush()

    certified = 0
    for week_ix in range(_WEEKS):
        ending = first_day + timedelta(days=7 * week_ix + 6)
        week = await svc.create_week(
            project_id,
            CertifiedWeekCreate(
                week_ending=ending.isoformat(),
                batch_id=batch.id,
                payroll_number=str(week_ix + 1),
                contractor_name=site["contractor"],
                contractor_address=site["address"],
                project_name=project.name,
                project_location=site["locality"],
                contract_number=site["contract"],
                covered_authorities=["federal"],
                fringe_election="plan",
                weekly_overtime_threshold="40",
            ),
        )
        # The latest week stays a draft, so the demo still shows signing.
        if week_ix < _WEEKS - 1:
            await svc.certify_week(
                week.id,
                CertifyRequest(signatory_name=_SIGNATORY[0], signatory_title=_SIGNATORY[1]),
            )
            certified += 1

    return {
        "determinations": 1,
        "classifications": len(_TRADES),
        "assignments": len(_CREW),
        "payroll_entries": entries,
        "weeks": _WEEKS,
        "certified": certified,
    }
