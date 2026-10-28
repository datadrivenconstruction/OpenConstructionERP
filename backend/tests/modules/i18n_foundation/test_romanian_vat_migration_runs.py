# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v3308`` run against a real database, not just read.

Why this file exists separately from the repair's own tests
-----------------------------------------------------------
The repair that reaches a customer is
``app.modules.i18n_foundation.romania_vat.repair_romanian_vat_rates``, run from
the boot-path registry, and ``test_romanian_vat_repair.py`` covers it. The
revision is the second half, written for operators who run ``alembic upgrade``
by hand, and it is written twice on purpose - the registry docstring explains
why a generic replayer was rejected.

Written twice means it can be wrong twice, and the revision half is the half
nobody exercises. Its statements are raw SQL: a cast that does not match the
``id`` column's type, a JSON bind the driver renders as the text of a dict, an
INSERT naming a column that does not exist. None of that is visible by reading,
and none of it is caught by the repair's tests, which never touch this file.

So these tests side-load the revision and run its ``_repair_rows`` against the
same PostgreSQL the rest of the suite uses. The assertions deliberately mirror
``test_romanian_vat_repair.py``: the two halves have to agree about what the
database looks like afterwards, and asserting different things about them would
be how they drift.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import TaxConfiguration
from tests.modules.i18n_foundation.conftest import make_tax

_MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3308_romania_vat_2025.py"

BEFORE = "2025-07-31"
AFTER = "2025-08-01"


def _migration() -> Any:
    """Side-load the revision; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("v3308_romania_vat_2025", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(session: AsyncSession) -> tuple[int, int]:
    """Run the revision's statements over the session's own connection."""
    module = _migration()
    return await session.run_sync(lambda sync_session: module._repair_rows(sync_session.connection()))


async def _rows(session: AsyncSession) -> list[TaxConfiguration]:
    session.expire_all()
    result = await session.execute(
        select(TaxConfiguration).where(TaxConfiguration.country_code == "RO").order_by(TaxConfiguration.rate_pct)
    )
    return list(result.scalars().all())


async def _seed_pre_reform(session: AsyncSession) -> None:
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        combination="national",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=True,
    )


async def test_the_statements_execute_and_land_the_reformed_rates(session: AsyncSession) -> None:
    """The SQL runs, and what it wrote reads back as rows the ORM can load.

    Loading them back through the model is the point: a row the INSERT wrote
    with a mistyped id or a JSON column holding the text of a dict inserts
    without complaint and fails only when something reads it.
    """
    await _seed_pre_reform(session)

    closed, inserted = await _run(session)

    assert (closed, inserted) == (1, 2)
    stored = {(r.tax_code, r.rate_pct, r.effective_from, r.effective_to, r.is_default) for r in await _rows(session)}
    assert stored == {
        ("TVA", "19.0", "2017-01-01", BEFORE, False),
        ("TVA", "21.0", AFTER, None, True),
        ("TVA_RED", "11.0", AFTER, None, False),
    }


async def test_the_inserted_rows_carry_readable_translations(session: AsyncSession) -> None:
    """``tax_name_translations`` is a JSON column, and the bind has to know that.

    A driver handed a dict for a JSON column without the type declared writes
    the repr of the dict. It inserts fine and the column then holds a string
    that no consumer can index.
    """
    await _seed_pre_reform(session)

    await _run(session)

    new = [r for r in await _rows(session) if r.effective_from == AFTER]
    assert len(new) == 2
    for row in new:
        assert isinstance(row.tax_name_translations, dict), row.tax_name_translations
        assert row.tax_name_translations["ro"].startswith("TVA ")


async def test_running_the_revision_twice_writes_nothing_the_second_time(session: AsyncSession) -> None:
    """An operator who re-runs a partially applied upgrade gets no duplicates."""
    await _seed_pre_reform(session)

    first = await _run(session)
    before = sorted((r.tax_code, r.rate_pct, r.effective_from, r.effective_to) for r in await _rows(session))
    second = await _run(session)
    after = sorted((r.tax_code, r.rate_pct, r.effective_from, r.effective_to) for r in await _rows(session))

    assert (first, second) == ((1, 2), (0, 0))
    assert before == after


async def test_a_database_with_no_romanian_rows_is_left_empty(session: AsyncSession) -> None:
    """Nothing Romanian seeded here; the corrected seed file is the whole answer."""
    assert await _run(session) == (0, 0)
    assert await _rows(session) == []


async def test_an_operator_edited_rate_survives_the_revision(session: AsyncSession) -> None:
    """Same guard as the boot repair, proved against the SQL rather than the ORM."""
    await make_tax(
        session,
        country_code="RO",
        tax_name="Local TVA",
        tax_code="TVA",
        rate_pct="20.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=True,
    )

    closed, inserted = await _run(session)

    assert closed == 0
    standard = [(r.rate_pct, r.effective_to) for r in await _rows(session) if r.tax_code == "TVA"]
    assert standard == [("20.0", None)]
    # The reduced band is still added - it is missing from this install too,
    # and it does not contradict whatever the operator decided about 20 %.
    assert inserted == 1


# ── The two halves must refuse the same installs ─────────────────────────────
#
# The revision restates the resolver's "exactly one default" rule instead of
# importing it, so that an applied upgrade keeps meaning what it meant when it
# was written. Restating it is how it drifts, so these mirror the refusal cases
# in ``test_romanian_vat_repair.py`` against the SQL.


async def test_the_revision_declines_an_install_with_no_flagged_default(session: AsyncSession) -> None:
    """One unflagged row: adding the band would leave no resolvable rate."""
    await make_tax(
        session,
        country_code="RO",
        tax_name="Local TVA",
        tax_code="TVA",
        rate_pct="20.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=False,
    )

    assert await _run(session) == (0, 0)
    assert [(r.tax_code, r.rate_pct, r.effective_to) for r in await _rows(session)] == [("TVA", "20.0", None)]


async def test_the_revision_declines_to_add_a_second_flagged_default(session: AsyncSession) -> None:
    """Its own 21 % row would be the second default beside an operator's."""
    await make_tax(
        session,
        country_code="RO",
        tax_name="Negotiated TVA",
        tax_code="TVA_LOCAL",
        rate_pct="24.0",
        tax_type="vat",
        effective_from="2020-01-01",
        effective_to=None,
        is_default=True,
    )
    await make_tax(
        session,
        country_code="RO",
        tax_name="VAT Standard (TVA)",
        tax_code="TVA",
        rate_pct="19.0",
        tax_type="vat",
        effective_from="2017-01-01",
        effective_to=None,
        is_default=False,
    )

    assert await _run(session) == (0, 0)
    stored = {(r.tax_code, r.rate_pct, r.effective_to) for r in await _rows(session)}
    assert stored == {("TVA_LOCAL", "24.0", None), ("TVA", "19.0", None)}
