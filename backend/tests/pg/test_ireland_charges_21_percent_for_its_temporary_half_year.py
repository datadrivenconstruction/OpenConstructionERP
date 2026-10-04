# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An install seeded before 18.4 learns Ireland's 21 % half year, and nothing else moves.

Ireland charged 21 % instead of 23 % from 1 September 2020 to 28 February 2021.
Every install seeded before 18.4 holds one open 23 % row from 2012-01-01, so a
document dated in that half year resolves at 23. ``tax_window_supersede`` closes
that row at 2020-08-31 and adds the 21 % window and the 23 % window after it.

Asserted on the resolved rate, through the product's resolver, on both sides of
both boundaries: a repair that rewrote the 23 % row in place, or that forgot the
second 23 % window, would get one of these four dates wrong. Today's answer is
asserted too, because the change must leave the rate billed now exactly where
it was.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.data_repairs import run_data_repairs
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.tax_rules import resolve, row_from_orm
from tests.pg.test_tax_seed_reconcile import (  # noqa: F401 - repair_factory is a fixture used by name
    _install,
    pre_v15_5_0,
    repair_factory,
    v15_9_1,
)

pytestmark = pytest.mark.asyncio

_DATES = {
    "2020-08-31": "23",
    "2020-09-01": "21",
    "2021-02-28": "21",
    "2021-03-01": "23",
    "2026-10-04": "23",
}


async def _ireland(factory, on_date: str) -> str | None:
    async with factory() as session:
        rows = [row_from_orm(row) for row in (await session.execute(select(TaxConfiguration))).scalars().all()]
    outcome = resolve(rows, "IE", None, on_date=on_date)
    return outcome.combined_rate_pct if outcome.resolved else None


async def _irish_vat_windows(factory) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(TaxConfiguration.rate_pct, TaxConfiguration.effective_from, TaxConfiguration.effective_to)
                .where(TaxConfiguration.country_code == "IE", TaxConfiguration.tax_code == "VAT")
                .order_by(TaxConfiguration.effective_from)
            )
        ).all()
    return [tuple(row) for row in rows]


@pytest.mark.parametrize("cohort", [pre_v15_5_0, v15_9_1], ids=["pre_v15_5_0", "v15_9_1"])
async def test_an_old_install_charges_each_irish_date_its_own_rate(repair_factory, cohort) -> None:
    await _install(repair_factory, cohort(), "2026-06-01")

    # The broken state first, or the assertions after the run prove nothing.
    assert await _ireland(repair_factory, "2020-09-01") == "23", "the fixture is not the cohort with the defect"

    await run_data_repairs(repair_factory)

    for on_date, rate in _DATES.items():
        assert await _ireland(repair_factory, on_date) == rate, f"Ireland on {on_date}"
    assert await _irish_vat_windows(repair_factory) == [
        ("23.0", "2012-01-01", "2020-08-31"),
        ("21.0", "2020-09-01", "2021-02-28"),
        ("23.0", "2021-03-01", None),
    ]


async def test_a_second_boot_leaves_the_irish_windows_alone(repair_factory) -> None:
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory)
    settled = await _irish_vat_windows(repair_factory)

    await run_data_repairs(repair_factory)

    assert await _irish_vat_windows(repair_factory) == settled


async def test_an_irish_rate_somebody_edited_is_left_alone(repair_factory) -> None:
    """A 23 % row an operator re-dated is theirs, and the half year is not forced onto it."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    async with repair_factory() as session:
        await session.execute(
            TaxConfiguration.__table__.update()
            .where(TaxConfiguration.country_code == "IE", TaxConfiguration.tax_code == "VAT")
            .values(effective_from="2012-02-01")
        )
        await session.commit()

    await run_data_repairs(repair_factory)

    assert await _irish_vat_windows(repair_factory) == [("23.0", "2012-02-01", None)]
