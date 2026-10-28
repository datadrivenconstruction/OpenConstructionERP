# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Canadian GST filed as ``national`` is not a label problem, it is a wrong total.

``v3302_tax_combination`` backfilled ``combination`` on the thirteen Canadian
and United States rows, and a revision body never executes on the boot path, so
an upgraded install has all thirteen on the column's server default. Eleven of
them are sub-national and ``tax_subdivision_backfill`` rewrites them, because
the table's check constraint will not let it write a subdivision without saying
how the rate combines. The two country-wide rows are outside that: no
subdivision either way, no constraint breached, no repair reaching them.

They break nothing loudly, which is the reason to test them at all. The
resolver splits the active rows by ``combination`` and only the ``federal``
list is the base a sub-national rate is measured against, so a GST row filed as
``national`` empties that list and every Canadian answer that leans on the base
moves. The assertions below are on resolved rates rather than on the column,
because the column is the mechanism and the rate is what a quantity surveyor
puts in a tender.

The harmonised provinces are the trap and are asserted for that reason. Ontario
comes out at 13 % either way, because a ``replaces_federal`` rate never reads
the base - so the province most likely to be spot-checked is the one that looks
right while British Columbia is understated by five points.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.tax_federal_scope_repair import (
    SHIPPED_FEDERAL_COMBINATION,
    repair_federal_tax_scope,
)
from app.modules.i18n_foundation.tax_rules import resolve, row_from_orm

pytestmark = pytest.mark.asyncio


def _row(tax_code: str, rate: str, combination: str, subdivision: str | None) -> TaxConfiguration:
    """One Canadian rate as the shipped seed writes it."""
    return TaxConfiguration(
        country_code="CA",
        tax_name=tax_code,
        tax_code=tax_code,
        rate_pct=rate,
        tax_type="gst",
        combination=combination,
        subdivision_code=subdivision,
        effective_from="2008-01-01",
        effective_to=None,
        is_default=False,
    )


@pytest_asyncio.fixture
async def unrepaired(pg_session):
    """Canada as an install upgraded across v3302 holds it: every row ``national``.

    Only the country-wide row is written as ``national`` here. The provincial
    rows carry their real combination, because writing those as ``national``
    would breach ``subdivision_matches_combination`` and this fixture has to be
    a state a real database can actually be in. That is the whole shape of the
    defect: the constraint catches the eleven rows that are wrong in a way it
    can see, and the two it cannot see are the ones left unrepaired.
    """
    pg_session.add_all(
        [
            _row("GST", "5.0", "national", None),
            _row("PST_BC", "7.0", "stacks_on_federal", "CA-BC"),
            _row("HST_ON", "13.0", "replaces_federal", "CA-ON"),
        ]
    )
    await pg_session.commit()
    return pg_session


async def _rows(session) -> list:
    configs = (await session.execute(select(TaxConfiguration).where(TaxConfiguration.country_code == "CA"))).scalars()
    return [row_from_orm(c) for c in configs]


async def test_british_columbia_is_understated_until_the_repair_runs(unrepaired) -> None:
    """5 + 7 = 12, and 7 is what an unrepaired install answers."""
    before = resolve(await _rows(unrepaired), "CA", "CA-BC", on_date="2026-08-27")

    assert Decimal(before.combined_rate_pct) == Decimal("7.0"), (
        "this test is measuring nothing if the unrepaired database already answers 12"
    )
    assert before.federal_rate_pct is None

    changed = await repair_federal_tax_scope(unrepaired)
    await unrepaired.commit()

    assert changed == 1

    after = resolve(await _rows(unrepaired), "CA", "CA-BC", on_date="2026-08-27")

    assert Decimal(after.combined_rate_pct) == Decimal("12.0")
    assert Decimal(after.federal_rate_pct) == Decimal("5.0")


async def test_a_province_that_levies_nothing_stops_answering_zero(unrepaired) -> None:
    """Alberta. ``federal_only`` at 0 % is a status contradicting its own number."""
    before = resolve(await _rows(unrepaired), "CA", "CA-AB", on_date="2026-08-27")

    assert before.status == "federal_only"
    assert Decimal(before.combined_rate_pct) == Decimal("0")
    assert before.components == []

    await repair_federal_tax_scope(unrepaired)
    await unrepaired.commit()

    after = resolve(await _rows(unrepaired), "CA", "CA-AB", on_date="2026-08-27")

    assert after.status == "federal_only"
    assert Decimal(after.combined_rate_pct) == Decimal("5.0")
    assert [c.tax_code for c in after.components] == ["GST"]


async def test_a_harmonised_province_reads_the_same_either_way(unrepaired) -> None:
    """Ontario, asserted because it is the one that hides the defect.

    A ``replaces_federal`` rate never reads the federal base, so 13 % is correct
    before and after. Anybody who checked Canada by looking at Ontario saw a
    right answer.
    """
    before = resolve(await _rows(unrepaired), "CA", "CA-ON", on_date="2026-08-27")

    await repair_federal_tax_scope(unrepaired)
    await unrepaired.commit()

    after = resolve(await _rows(unrepaired), "CA", "CA-ON", on_date="2026-08-27")

    assert Decimal(before.combined_rate_pct) == Decimal("13.0")
    assert Decimal(after.combined_rate_pct) == Decimal("13.0")


async def test_the_repair_is_a_no_op_on_a_second_pass(unrepaired) -> None:
    """The registry's contract, held here as well as in the whole-registry sweep.

    Cheap to state and the failure it catches is expensive: a repair that keeps
    finding work rewrites rows on every restart forever.
    """
    assert await repair_federal_tax_scope(unrepaired) == 1
    await unrepaired.commit()

    assert await repair_federal_tax_scope(unrepaired) == 0


async def test_an_operators_own_answer_is_not_overwritten(pg_session) -> None:
    """Fill, never overwrite.

    A deployment that set the Canadian GST row to something other than the
    default said something, and this repair has no opinion about it. Only the
    server default ``national`` is treated as "nobody filled this in".
    """
    pg_session.add(_row("GST", "5.0", "federal", None))
    await pg_session.commit()

    assert await repair_federal_tax_scope(pg_session) == 0


async def test_a_row_carrying_a_subdivision_is_skipped_rather_than_broken(pg_session) -> None:
    """The guard that keeps the repair from failing on every boot instead of once.

    ``federal`` and a subdivision code together breach
    ``subdivision_matches_combination``, and a repair that raises is retried on
    every start forever. A GST row filed under a province is somebody's own edit
    and is left alone.
    """
    pg_session.add(_row("GST", "5.0", "stacks_on_federal", "CA-ON"))
    await pg_session.commit()

    assert await repair_federal_tax_scope(pg_session) == 0


async def test_the_repair_table_matches_what_the_seed_file_ships() -> None:
    """The repair replays the seed's answer, so it has to still be the seed's answer.

    Read from the shipped JSON rather than restated here: a repair table that
    drifts from the file it mirrors writes a value no fresh install has, and
    nothing else would notice.
    """
    import json
    from pathlib import Path

    import app.modules.i18n_foundation as module

    seed = json.loads(
        (Path(module.__file__).parent / "seed_data" / "tax_configurations.json").read_text(encoding="utf-8")
    )
    shipped = {
        (row["country_code"], row["tax_code"]): row["combination"]
        for row in seed
        if row.get("combination") == "federal"
    }

    assert shipped == SHIPPED_FEDERAL_COMBINATION
