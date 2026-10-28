"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Seeding the resource sheet must read the region in bounded pages.

``seed_region`` runs inside the same request as a cost-base import, directly
after it, and it walks the components breakdown of every work item in the
region. Reading that in one buffered result put tens of thousands of those JSON
breakdowns in memory at once, on a machine that had just finished holding the
import, and the kernel killed the process. The operator saw a server that
stopped, not a seed that failed, so nothing pointed at this loop.

The bound is checked by watching the page sizes the scan asks the session for,
rather than by measuring memory. The page size is what this code decides;
resident memory is decided by the driver, the allocator and the garbage
collector too, and a test measuring it would fail for reasons unrelated to this
loop. The limit is read back off the compiled statement so the assertions are
about what the scan requested, not about what a fake chose to hand it.

The last two tests are the control. One runs the same seed with the bound
raised out of reach, which is what removing the paging would look like from
inside the loop, and asserts the single unbounded page that would then appear.
The other asserts the bounded and unbounded runs agree on every number and on
every row written, because paging a scan is only correct if it changes nothing
but the peak.

No database is involved: the session is replaced by a recorder that serves the
pages the statement asks for.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pytest

from app.modules.costs.models import ResourcePrice
from app.modules.costs.resource_pricing import ResourcePriceService

SCAN = 7
ITEMS = 25
REGION = "XX_SCAN_BOUND"

# ``LIMIT n OFFSET m`` as the default dialect renders it with literal binds.
_LIMIT_OFFSET = re.compile(r"LIMIT (\d+) OFFSET (\d+)")


def _work_items(count: int) -> list[tuple[list[dict[str, Any]], str]]:
    """One ``(components, currency)`` row per work item, each naming its own resource.

    Distinct resource codes mean the seed's own counters double as a row census:
    a page the scan skipped loses a resource, and one it served twice would be
    folded into the same key rather than counted twice, which is why the page
    sizes are asserted separately below.
    """
    return [
        (
            [
                {
                    "code": f"R{index:04d}",
                    "name": f"Resource {index}",
                    "type": "material",
                    "unit": "hr",
                    "quantity": 1.0,
                    "unit_rate": 10.0 + index,
                }
            ],
            "EUR",
        )
        for index in range(count)
    ]


class _Rows:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Rows:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class _RecordingSession:
    """Serves the work-item scan page by page and records what it was asked for."""

    def __init__(self, rows: list[tuple[list[dict[str, Any]], str]]) -> None:
        self._rows = rows
        self.page_sizes: list[int] = []
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Rows:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if ResourcePrice.__tablename__ in sql:
            # The existing-sheet lookup: nothing has been seeded yet. The two
            # queries are told apart by table name rather than by call order,
            # because the order is what the paging changes. The names are
            # disjoint, so a scan statement can never fall into this branch and
            # be silently answered with no rows.
            return _Rows([])
        match = _LIMIT_OFFSET.search(sql)
        assert match is not None, f"the work-item scan asked for no page at all: {sql}"
        limit, offset = int(match.group(1)), int(match.group(2))
        page = self._rows[offset : offset + limit]
        self.page_sizes.append(len(page))
        return _Rows(page)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None


async def _seed_with_bound(bound: int, monkeypatch: pytest.MonkeyPatch) -> tuple[_RecordingSession, Any]:
    """Run a seed against a recording session and return the recorder and result."""
    monkeypatch.setattr(ResourcePriceService, "_SEED_SCAN_ROWS", bound)
    session = _RecordingSession(_work_items(ITEMS))
    result = await ResourcePriceService(session).seed_region(REGION)  # type: ignore[arg-type]
    return session, result


@pytest.fixture
async def bounded(monkeypatch: pytest.MonkeyPatch) -> tuple[_RecordingSession, Any]:
    return await _seed_with_bound(SCAN, monkeypatch)


async def test_no_page_exceeds_the_scan_bound(bounded: tuple[_RecordingSession, Any]) -> None:
    session, _ = bounded
    assert session.page_sizes, "the seed read nothing, so the bound was never exercised"
    assert max(session.page_sizes) <= SCAN, f"a page of {max(session.page_sizes)} rows passed a bound of {SCAN}"


async def test_the_scan_reads_more_than_one_page(bounded: tuple[_RecordingSession, Any]) -> None:
    # The assertion above is also satisfied by a scan that read one short page
    # and stopped, and by one that never entered the loop. This is the half
    # that says the paging happened.
    session, _ = bounded
    assert len(session.page_sizes) == math.ceil(ITEMS / SCAN)


async def test_every_work_item_still_arrives(bounded: tuple[_RecordingSession, Any]) -> None:
    # Paging is only correct if it loses nothing and repeats nothing. An
    # off-by-one in the offset is invisible to the two assertions above: it
    # shows up here as a page census that does not add up to the region.
    session, result = bounded
    assert sum(session.page_sizes) == ITEMS
    assert result.resources == ITEMS
    assert result.created == ITEMS
    assert len(session.added) == ITEMS


async def test_an_unreachable_bound_produces_the_one_page_the_others_forbid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = await _seed_with_bound(10**9, monkeypatch)

    assert session.page_sizes == [ITEMS]
    assert max(session.page_sizes) > SCAN
    assert len(session.page_sizes) != math.ceil(ITEMS / SCAN)


async def test_paging_changes_the_peak_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    # The control above proves the bound shaped the reads. This one proves the
    # shaping was free: a seed that paged and a seed that did not must agree on
    # every number they report and on every row they write.
    bounded_session, bounded_result = await _seed_with_bound(SCAN, monkeypatch)
    whole_session, whole_result = await _seed_with_bound(10**9, monkeypatch)

    assert bounded_result.as_dict() == whole_result.as_dict()
    assert [(row.resource_key, row.unit_price, row.currency) for row in bounded_session.added] == [
        (row.resource_key, row.unit_price, row.currency) for row in whole_session.added
    ]
