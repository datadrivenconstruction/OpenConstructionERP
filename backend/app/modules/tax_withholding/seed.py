# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo records for the withholding-tax screens.

The module ships its schemes but no records, so the register, the party
standings and the deductions opened empty on every install. A demo pack that
wants the screens filled declares what a project of its country withholds on in
``DemoTemplate.withholding_showcase``; this seeder installs the shipped schemes
and writes that declaration, nothing more. The pack owns the parties, the
payment types and the amounts; the figures that follow from them (taxable base,
rate, tax withheld) come from the module's own :func:`compute_deduction`, so a
seeded row can never disagree with what the calculator would say.

Dates count from the seed day, so a demo opened long after it shipped still
shows the latest deduction as recent and the oldest as already returned.

Declaration shape::

    {
        "scheme": "SA_NONRESIDENT_WHT",
        "parties": [{"key": "a", "name": "...", "band": "SERVICES", "evidence": "...", "status": "active"}],
        "payments": [
            {"party": "a", "reference": "...", "gross": "250000", "materials": "0", "vat": "0",
             "months_ago": 3, "status": "returned"},
        ],
    }
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.tax_withholding import repository, service
from app.modules.tax_withholding.models import PartyTaxStatus, WithholdingDeduction

logger = logging.getLogger(__name__)

__all__ = ["seed_tax_withholding_demo"]

_NAMESPACE = uuid.UUID("5a2f6f0e-7c1b-4e0e-9b43-3d1c0a8d2b77")


def _month_start(day: date, months_back: int) -> date:
    index = day.year * 12 + (day.month - 1) - months_back
    return date(index // 12, index % 12 + 1, 1)


def _month_end(first: date) -> date:
    following = _month_start(first, -1)
    return following - timedelta(days=1)


def _showcase_for(demo_id: str) -> dict[str, Any]:
    from app.core.demo_projects import DEMO_TEMPLATES

    return dict(getattr(DEMO_TEMPLATES.get(demo_id), "withholding_showcase", None) or {})


async def _seed_project(session: AsyncSession, project: Project, showcase: dict[str, Any], today: date) -> int:
    regime = await repository.get_regime_by_scheme(
        session, country_code=_country_of(showcase), scheme_code=str(showcase["scheme"])
    )
    if regime is None:
        logger.info("withholding demo seed skipped: scheme %s is not installed", showcase["scheme"])
        return 0

    already = (
        await session.execute(
            select(WithholdingDeduction.id).where(WithholdingDeduction.project_id == project.id).limit(1)
        )
    ).scalar_one_or_none()
    if already is not None:
        return 0

    statuses: dict[str, PartyTaxStatus] = {}
    for party in showcase.get("parties", []):
        party_id = uuid.uuid5(_NAMESPACE, f"{project.id}:{party['key']}")
        verified_days = int(party.get("verified_days_ago") or 0)
        verified_on = today - timedelta(days=verified_days) if verified_days else None
        row = PartyTaxStatus(
            party_id=party_id,
            party_type=str(party.get("type") or "vendor"),
            party_name=str(party["name"]),
            regime_id=regime.id,
            band_code=str(party["band"]),
            verification_reference=str(party.get("verification_reference") or ""),
            verified_on=verified_on,
            valid_from=today - timedelta(days=int(party.get("valid_days") or 365)),
            valid_to=None,
            evidence_reference=str(party.get("evidence") or ""),
            status=str(party.get("status") or "active"),
            notes=str(party.get("notes") or ""),
        )
        await repository.add_party_status(session, row)
        statuses[str(party["key"])] = row

    written = 0
    for payment in showcase.get("payments", []):
        party = statuses.get(str(payment["party"]))
        if party is None:
            continue
        start = _month_start(today, int(payment["months_ago"]))
        figures = service.compute_deduction(
            regime,
            gross_amount=Decimal(str(payment["gross"])),
            currency_code=regime.currency_code,
            qualifying_materials=Decimal(str(payment.get("materials") or "0")),
            vat_amount=Decimal(str(payment.get("vat") or "0")),
            requested_band=party.band_code,
            party_status=party,
            as_of=start,
        )
        status = str(payment.get("status") or "calculated")
        end = _month_end(start)
        remitted_at = min(end + timedelta(days=10), today) if status in ("remitted", "returned") else None
        await repository.add_deduction(
            session,
            WithholdingDeduction(
                project_id=project.id,
                regime_id=regime.id,
                party_status_id=party.id,
                party_id=party.party_id,
                party_name=party.party_name,
                payment_reference=str(payment["reference"]),
                period_start=start,
                period_end=end,
                gross_amount=figures.gross_amount,
                qualifying_materials=figures.qualifying_materials,
                vat_amount=figures.vat_amount,
                taxable_base=figures.taxable_base,
                rate_pct=figures.rate_pct,
                band_code=figures.band_code,
                tax_withheld=figures.tax_withheld,
                currency_code=regime.currency_code,
                status=status,
                remitted_at=remitted_at,
                return_reference=str(payment.get("return_reference") or "") if status == "returned" else "",
                notes=str(payment.get("notes") or ""),
            ),
        )
        written += 1
    return written


def _country_of(showcase: dict[str, Any]) -> str:
    return str(showcase.get("country") or str(showcase["scheme"])[:2]).upper()


async def seed_tax_withholding_demo(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[str, int]:
    """Install the shipped schemes and write each demo pack's declared records.

    Only demo projects whose pack declares a ``withholding_showcase`` are
    touched; a customer's project never gets a deduction it did not make.

    Returns:
        ``{"deductions": n}``, or an empty dict when nothing was written.
    """
    if not project_ids:
        return {}
    projects = (await session.execute(select(Project).where(Project.id.in_(list(project_ids))))).scalars().all()
    plans: list[tuple[Project, dict[str, Any]]] = []
    for project in projects:
        meta = project.metadata_ if isinstance(project.metadata_, dict) else {}
        demo_id = str(meta.get("demo_id") or "").strip()
        showcase = _showcase_for(demo_id) if demo_id else {}
        if showcase.get("scheme"):
            plans.append((project, showcase))
    if not plans:
        return {}

    await service.seed_regimes(session)
    today = date.today()
    total = 0
    for project, showcase in plans:
        total += await _seed_project(session, project, showcase, today)
    await session.flush()
    return {"deductions": total} if total else {}
