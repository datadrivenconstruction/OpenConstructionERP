# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An install seeded before 18.4 learns Switzerland's 2018 to 2023 rates, once.

The seed shipped only the Swiss rates in force from 2024-01-01, and 18.4 put
the 7.7, 2.5 and 3.7 % windows in front of them. Neither older tax repair
reaches that shape: the reconciler stops at a rate line the install already
holds, and the supersede repair only acts on a window still open. So on every
install seeded before 18.4, production included, a Swiss bill dated 2023 had
no rate of its own and was charged the DACH stack's 19, Germany's rate.

The cohorts are the reconstructed historical seed files from
``test_tax_seed_reconcile``, which carry no Swiss history, so the broken state
is asserted before every repair run rather than assumed.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.data_repairs import (
    DataRepairDelivery,
    discover_data_repairs,
    run_data_repairs,
    snapshot_table,
    verify_additive_shape,
)
from app.modules.boq.models import BOQ, BOQMarkup
from app.modules.boq.service import BOQService
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.tax_history_backfill import (
    REPAIR_ID,
    WINDOW_FIRST_SHIPPED,
    delivery_key,
)
from app.modules.i18n_foundation.tax_rules import resolve, row_from_orm
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests.pg.test_tax_seed_reconcile import (  # noqa: F401 - repair_factory is a fixture used by name
    _install,
    pre_v15_5_0,
    repair_factory,
    v15_9_1,
)

pytestmark = pytest.mark.asyncio

_LOGGER = "app.modules.i18n_foundation.tax_history_backfill"
_SWISS_KEYS = {delivery_key(window) for window in WINDOW_FIRST_SHIPPED}

#: What Switzerland resolves to on either side of the 2024 change, and today.
_SWISS_DATES = {
    "2017-12-31": None,
    "2018-01-01": "7.7",
    "2023-06-30": "7.7",
    "2023-12-31": "7.7",
    "2024-01-01": "8.1",
    "2026-10-04": "8.1",
}


async def _swiss(factory, on_date: str) -> str | None:
    async with factory() as session:
        rows = [row_from_orm(row) for row in (await session.execute(select(TaxConfiguration))).scalars().all()]
    outcome = resolve(rows, "CH", None, on_date=on_date)
    return outcome.combined_rate_pct if outcome.resolved else None


async def _swiss_windows(factory) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    TaxConfiguration.tax_code,
                    TaxConfiguration.rate_pct,
                    TaxConfiguration.effective_from,
                    TaxConfiguration.effective_to,
                )
                .where(TaxConfiguration.country_code == "CH")
                .order_by(TaxConfiguration.tax_code, TaxConfiguration.effective_from)
            )
        ).all()
    return [tuple(row) for row in rows]


async def _deliveries(factory) -> set[str]:
    async with factory() as session:
        rows = await session.execute(
            select(DataRepairDelivery.delivery_key).where(DataRepairDelivery.repair_id == REPAIR_ID)
        )
    return set(rows.scalars().all())


def _outcome(report):
    return next(o for o in report.outcomes if o.repair_id == REPAIR_ID)


@pytest.mark.parametrize("cohort", [pre_v15_5_0, v15_9_1], ids=["pre_v15_5_0", "v15_9_1"])
async def test_an_old_install_learns_the_swiss_rates_before_2024(repair_factory, cohort) -> None:
    await _install(repair_factory, cohort(), "2026-06-01")
    assert await _swiss(repair_factory, "2023-06-30") is None, "the fixture is not the cohort with the gap"

    report = await run_data_repairs(repair_factory)

    assert _outcome(report).rows_changed == 3
    for on_date, rate in _SWISS_DATES.items():
        assert await _swiss(repair_factory, on_date) == rate, f"Switzerland on {on_date}"
    assert await _swiss_windows(repair_factory) == [
        ("VAT", "7.7", "2018-01-01", "2023-12-31"),
        ("VAT", "8.1", "2024-01-01", None),
        ("VAT_REDUCED", "2.5", "2018-01-01", "2023-12-31"),
        ("VAT_REDUCED", "2.6", "2024-01-01", None),
        ("VAT_SPECIAL", "3.7", "2018-01-01", "2023-12-31"),
        ("VAT_SPECIAL", "3.8", "2024-01-01", None),
    ]
    assert await _deliveries(repair_factory) == _SWISS_KEYS


async def test_a_second_boot_changes_nothing(repair_factory) -> None:
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory)
    settled = await _swiss_windows(repair_factory)

    second = _outcome(await run_data_repairs(repair_factory))

    assert second.rows_changed == 0
    assert await _swiss_windows(repair_factory) == settled


async def test_a_delivered_window_the_customer_deletes_stays_deleted(repair_factory) -> None:
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory)
    async with repair_factory() as session:
        await session.execute(
            delete(TaxConfiguration).where(
                TaxConfiguration.country_code == "CH", TaxConfiguration.effective_from == "2018-01-01"
            )
        )
        await session.commit()

    again = _outcome(await run_data_repairs(repair_factory))

    assert again.rows_changed == 0
    assert await _swiss(repair_factory, "2023-06-30") is None, "a window the customer deleted came back"


async def test_an_install_seeded_after_the_windows_shipped_is_given_nothing(repair_factory) -> None:
    """Seeded from a file that had them, so their absence means somebody removed them."""
    await _install(repair_factory, v15_9_1(), "2026-10-04")

    report = await run_data_repairs(repair_factory)

    assert _outcome(report).rows_changed == 0
    assert await _deliveries(repair_factory) == set()
    assert await _swiss(repair_factory, "2023-06-30") is None


async def test_a_swiss_rate_the_customer_entered_for_those_years_is_not_doubled(repair_factory, caplog) -> None:
    """Their own 7.7 under their own code already answers 2023, so ours is not a gap there."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    async with repair_factory() as session:
        session.add(
            TaxConfiguration(
                country_code="CH",
                tax_name="Entered by the customer",
                tax_code="MWST_ALT",
                rate_pct="7.7",
                tax_type="vat",
                combination="national",
                effective_from="2018-01-01",
                effective_to="2023-12-31",
                is_default=True,
                metadata_={},
            )
        )
        await session.commit()

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        report = await run_data_repairs(repair_factory)

    assert _outcome(report).rows_changed == 0
    assert await _deliveries(repair_factory) == set(), "a refusal recorded a delivery, so it is never owed again"
    codes = [row[0] for row in await _swiss_windows(repair_factory) if row[2] == "2018-01-01"]
    assert codes == ["MWST_ALT"]
    warned = [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING]
    assert warned and "CH" in warned[0]


async def test_the_backfill_adds_rows_and_edits_none(repair_factory) -> None:
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    repair = next(r for r in discover_data_repairs() if r.repair_id == REPAIR_ID)
    assert repair.nature == "never_delivered"

    async with repair_factory() as session:
        before = await snapshot_table(session, "oe_i18n_tax_config")
    await run_data_repairs(repair_factory, repairs=(repair,))
    async with repair_factory() as session:
        after = await snapshot_table(session, "oe_i18n_tax_config")

    assert len(after) == len(before) + 3, "the pass under test delivered nothing, so the check below is vacuous"
    assert verify_additive_shape(repair, before, after) == ()


async def _swiss_bill_line(factory, base_date: str) -> BOQMarkup:
    """Seed a Swiss bill dated ``base_date`` and return its tax line."""
    async with factory() as session:
        tag = uuid.uuid4().hex[:8]
        owner = User(email=f"ch-{tag}@example.test", hashed_password="x", full_name="CH")
        session.add(owner)
        await session.flush()
        project = Project(name=f"Zurich {tag}", owner_id=owner.id, currency="CHF", country_code="CH")
        session.add(project)
        await session.flush()
        boq = BOQ(project_id=project.id, name=f"Bill {tag}", base_date=base_date)
        session.add(boq)
        await session.flush()
        await BOQService(session).apply_default_markups(boq.id)
        lines = (
            (await session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq.id, BOQMarkup.category == "tax")))
            .scalars()
            .all()
        )
        await session.commit()
    assert len(lines) == 1
    return lines[0]


async def test_a_swiss_bill_for_2023_is_charged_swiss_vat_after_the_backfill(repair_factory, caplog) -> None:
    """The money: Germany's 19 before the repair, Switzerland's own 7.7 after it."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    with caplog.at_level(logging.WARNING, logger="app.modules.boq.service"):
        before = await _swiss_bill_line(repair_factory, "2023-06-30")
    assert Decimal(before.percentage) == Decimal("19"), "the unrepaired cohort no longer shows the defect"
    assert before.metadata_["vat_rate_source"] == "region_template"
    # The stand-in says so on the line and in the log.
    assert before.metadata_["vat_rate_unresolved_on"] == "2023-06-30"
    assert any("2023-06-30" in r.getMessage() and "CH" in r.getMessage() for r in caplog.records)

    await run_data_repairs(repair_factory)

    after = await _swiss_bill_line(repair_factory, "2023-06-30")
    assert Decimal(after.percentage) == Decimal("7.7")
    assert after.metadata_["vat_rate_source"] == "country_seed"
    assert "vat_rate_unresolved_on" not in after.metadata_

    today = await _swiss_bill_line(repair_factory, "2026-06-30")
    assert Decimal(today.percentage) == Decimal("8.1"), "the backfill moved today's Swiss rate"
