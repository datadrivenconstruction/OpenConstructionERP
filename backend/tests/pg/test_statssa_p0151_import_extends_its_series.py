# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Importing Stats SA P0151.1 Table 1 twice extends each work group series and keeps revisions.

A later release repeats earlier months, some revised. The second import must
add the new month, overwrite the revised value, leave the rest alone and not
create a second series. All numbers are SAMPLE values, not Stats SA figures.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.price_index.models import CostIndexPoint, CostIndexSeries
from app.modules.price_index.statssa_p0151 import ACKNOWLEDGEMENT, import_p0151_table, parse_p0151_table1

pytestmark = pytest.mark.asyncio

_FIRST = b"Work group,Jan 2026,Feb 2026\n9910,Sample group,100.0,101.0\n"
_SECOND = b"Work group,Jan 2026,Feb 2026,Mar 2026\n9910,Sample group,100.0,101.5,103.0\n"


async def test_second_release_extends_and_revises(pg_session) -> None:
    first = await import_p0151_table(pg_session, parse_p0151_table1(_FIRST, "r1.csv"))
    assert (first.series_created, first.points_created) == (1, 2)

    second = await import_p0151_table(pg_session, parse_p0151_table1(_SECOND, "r2.csv"))
    assert (second.series_created, second.points_created, second.points_updated, second.points_unchanged) == (
        0,
        1,
        1,
        1,
    )

    series = (
        (await pg_session.execute(select(CostIndexSeries).where(CostIndexSeries.name.like("ZA P0151.1 WG9910%"))))
        .scalars()
        .all()
    )
    assert len(series) == 1
    assert ACKNOWLEDGEMENT in series[0].description
    points = (
        await pg_session.execute(select(CostIndexPoint).where(CostIndexPoint.series_id == series[0].id))
    ).scalars()
    assert {p.period: Decimal(str(p.factor)) for p in points} == {
        "2026-01": Decimal("100.0"),
        "2026-02": Decimal("101.5"),
        "2026-03": Decimal("103.0"),
    }
