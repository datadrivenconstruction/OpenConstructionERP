# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Starter labor rate template library.

Loads a small set of all-in rate build-ups so the rate library, the template
picker on the labor rates page and the labour-rate selector on the norm
expansion page are all useful out of the box. Without it a fresh install opens
the build panel on an empty picker and answers with "No labour-rate templates
yet. Create one on the Labour Rates page first.", which is a dead end on the
one screen that turns a production norm into a priced assembly.

The figures are generic starting points an estimator is expected to tune per
project, trade and region. They name no employer, no agreement and no supplier,
only the trade and the kind of charge, and each template is hand-authored in
its own currency rather than converted from one base, so the number reads the
way a rate sheet in that market is actually written.

Templates are owner-scoped, which is what makes this seeder different from the
other library seeds in the platform. A row with a NULL ``owner_id`` is readable
only by an admin (``labor_rates.router._scope_owner_id`` drops the owner filter
for the admin role, and ``_load_owned_template`` answers 404 on a NULL owner for
everybody else), so a platform-wide seed would fill the page for the one persona
least likely to build a rate and leave it empty for the estimator. The library
is therefore seeded against a real user id and the caller says which one.

Module import stays light on purpose: only :data:`DEFAULT_RATE_TEMPLATES` and
stdlib live at module top, and the ORM / session imports are deferred inside
:func:`seed_labor_rates`, so the pure default data can be imported (and
unit-tested) without a database or SQLAlchemy on the path.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# name, currency, base_wage, description, and the on-cost components that
# burden the wage into a fully loaded hourly rate. A component is either a
# percentage of the base wage or a flat amount of currency per hour, which is
# the only two kinds the build-up math knows (see ``rate_math``).
DEFAULT_RATE_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Bricklayer, journeyman",
        "currency": "EUR",
        "base_wage": Decimal("22.50"),
        "description": "Productive bricklayer wage burdened with statutory charges, leave and supervision.",
        "components": [
            ("Statutory social charges", "percentage", Decimal("21.5")),
            ("Leave and holiday provision", "percentage", Decimal("13.0")),
            ("Supervision", "percentage", Decimal("8.0")),
            ("Small tools and consumables", "fixed", Decimal("1.10")),
        ],
    },
    {
        "name": "Carpenter, journeyman",
        "currency": "EUR",
        "base_wage": Decimal("24.50"),
        "description": "Formwork and joinery carpenter, same on-cost structure as the bricklayer build-up.",
        "components": [
            ("Statutory social charges", "percentage", Decimal("21.5")),
            ("Leave and holiday provision", "percentage", Decimal("13.0")),
            ("Supervision", "percentage", Decimal("8.0")),
            ("Small tools and consumables", "fixed", Decimal("1.40")),
        ],
    },
    {
        "name": "General site labourer",
        "currency": "EUR",
        "base_wage": Decimal("17.00"),
        "description": "Unskilled site labour for clearing, handling and attendance work.",
        "components": [
            ("Statutory social charges", "percentage", Decimal("21.5")),
            ("Leave and holiday provision", "percentage", Decimal("13.0")),
            ("Supervision", "percentage", Decimal("6.0")),
            ("Small tools and consumables", "fixed", Decimal("0.60")),
        ],
    },
    {
        "name": "Groundworker",
        "currency": "GBP",
        "base_wage": Decimal("17.50"),
        "description": "Groundworks operative with employer national insurance and a holiday pay provision.",
        "components": [
            ("Employer national insurance", "percentage", Decimal("13.8")),
            ("Holiday pay provision", "percentage", Decimal("12.07")),
            ("Site supervision", "percentage", Decimal("7.0")),
            ("Small tools and PPE", "fixed", Decimal("0.80")),
        ],
    },
    {
        "name": "Carpenter, agreement scale",
        "currency": "USD",
        "base_wage": Decimal("36.00"),
        "description": "Agreement-scale carpenter with payroll taxes, workers compensation and fringe benefits.",
        "components": [
            ("Payroll taxes", "percentage", Decimal("9.0")),
            ("Workers compensation insurance", "percentage", Decimal("12.5")),
            ("Fringe benefits", "percentage", Decimal("24.0")),
            ("Small tools and consumables", "fixed", Decimal("1.75")),
        ],
    },
    {
        "name": "General labourer, Gulf site",
        "currency": "AED",
        "base_wage": Decimal("15.00"),
        "description": "Site labour on a Gulf project, where accommodation and transport are carried per hour.",
        "components": [
            ("End of service gratuity provision", "percentage", Decimal("8.33")),
            ("Site supervision", "percentage", Decimal("6.0")),
            ("Accommodation and transport", "fixed", Decimal("3.20")),
            ("Medical insurance and visa", "fixed", Decimal("1.10")),
        ],
    },
]


def _egyptian_templates() -> list[dict[str, Any]]:
    """Two Egyptian build-ups whose statutory on-costs come from the labour catalogue.

    The social insurance rate and the leave provision are read from
    ``app/core/country_data/labour_standards.json`` rather than typed here, so
    a corrected statutory figure reaches the template without a second edit.
    The leave provision spreads the paid annual leave and public holidays over
    the remaining days of a five-day week: (21 + 15) / (260 - 36) = 16.07%.

    Social insurance is the general-scheme employer rate on the wage. On a
    construction contract the authority also assesses a deemed wage from the
    contract value, which is not modelled; the description says so, because an
    estimator should not carry both. Base wages are starting points above the
    statutory minimum, not a market survey.
    """
    from datetime import date as _date

    from app.core.labour_standards import hard_standard

    on = _date(2026, 1, 1)

    def fact(key: str) -> Decimal:
        row = hard_standard("EG", key, on)
        if row is None:
            raise RuntimeError(f"labour standard EG/{key} is missing or awaits review")
        return row.value

    leave = fact("annual_leave_days") + fact("public_holiday_days")
    provision = (leave / (Decimal(5 * 52) - leave) * 100).quantize(Decimal("0.01"))
    insurance = fact("employer_social_insurance_pct")
    note = (
        " Social insurance is the general-scheme employer share; a contract assessed on a deemed wage "
        "from its value should drop it here."
    )
    return [
        {
            "name": "General site labourer, Egypt",
            "currency": "EGP",
            "base_wage": Decimal("50.00"),
            "description": "Unskilled site labour on an Egyptian project, Sunday to Thursday week." + note,
            "components": [
                ("Employer social insurance, general scheme", "percentage", insurance),
                ("Annual leave and public holiday provision", "percentage", provision),
                ("Site supervision", "percentage", Decimal("6.0")),
                ("Transport and site meals", "fixed", Decimal("6.00")),
            ],
        },
        {
            "name": "Mason, Egypt",
            "currency": "EGP",
            "base_wage": Decimal("90.00"),
            "description": "Blockwork and plaster mason on an Egyptian project." + note,
            "components": [
                ("Employer social insurance, general scheme", "percentage", insurance),
                ("Annual leave and public holiday provision", "percentage", provision),
                ("Site supervision", "percentage", Decimal("8.0")),
                ("Small tools and consumables", "fixed", Decimal("2.50")),
                ("Transport and site meals", "fixed", Decimal("6.00")),
            ],
        },
    ]


DEFAULT_RATE_TEMPLATES.extend(_egyptian_templates())


async def seed_labor_rates(session: AsyncSession, owner_id: UUID) -> dict[str, int]:
    """Idempotently insert the starter rate templates for one owner.

    Skips any template whose name the owner already carries, so repeated calls
    never duplicate a build-up and a user's own correction to a seeded rate
    survives the next restart. Safe to run on every startup.

    Args:
        session: Active async SQLAlchemy session. The caller commits.
        owner_id: The user the seeded templates belong to. Required rather
            than defaulted to ``None``, because a NULL owner is a platform-wide
            row that only an admin can read.

    Returns:
        A ``{"inserted", "skipped", "total_after"}`` count summary, where
        ``total_after`` is the number of distinct template names the owner
        carries once the seed has run.
    """
    from sqlalchemy import select

    from app.modules.labor_rates.models import LaborRateTemplate, OnCostComponent

    existing_rows = (
        await session.execute(select(LaborRateTemplate.name).where(LaborRateTemplate.owner_id == owner_id))
    ).scalars()
    existing = {str(name).strip().casefold() for name in existing_rows}

    inserted = 0
    skipped = 0
    for row in DEFAULT_RATE_TEMPLATES:
        name = str(row["name"])
        if name.strip().casefold() in existing:
            skipped += 1
            continue
        template = LaborRateTemplate(
            owner_id=owner_id,
            name=name,
            base_wage=Decimal(str(row["base_wage"])),
            currency=str(row["currency"]),
            description=str(row["description"]),
        )
        for sort_order, (label, kind, value) in enumerate(row["components"]):
            template.components.append(
                OnCostComponent(label=label, kind=kind, value=Decimal(str(value)), sort_order=sort_order),
            )
        session.add(template)
        existing.add(name.strip().casefold())
        inserted += 1

    await session.flush()
    logger.info("Labor rate seed: inserted=%d skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped, "total_after": len(existing)}
