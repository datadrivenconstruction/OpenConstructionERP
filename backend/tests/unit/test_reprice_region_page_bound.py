"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Re-pricing a region must read it, and let go of it, one bounded page at a time.

``reprice_region`` used to pull the whole region into one buffered read - up to
its own 250 000-item ceiling - and then walk it. Measured against a synthetic
region, a work item costs ~4.6 KiB once its two JSON documents are decoded onto
the ORM instance, so the ceiling is ~1.1 GiB and a real 55 700-item base is
~250 MiB, held for the whole pass on a server whose floor is 3 GB.

Paging that read is only half of the bound, and the half that is easy to believe
in wrongly. These are entities the loop then MUTATES, so the session keeps every
one of them until the transaction ends whatever shape the read had. The page has
to be flushed and released as well, which is why the recorder below models an
identity map and why the peak it holds - not the size of a page - is what the
third test asserts. A recorder that forgot its rows would report a flat peak
whether or not the release happened and could not tell the two apart.

The bound is checked by watching what the pass asks for and holds, rather than
by measuring memory. Page size and retention are what this code decides;
resident bytes are decided by the driver, the allocator and the collector too,
and a test measuring them would fail for reasons unrelated to this loop.

The controls: one run with the bound raised out of reach, which is what removing
the paging would look like from inside the loop, and one comparing a paged pass
against an unpaged one on every number they report and every rate they write -
paging a walk is only correct if it changes nothing but the peak.

The last two cover the other half of the change. The 250 000-item ceiling is
itself a truncation, and it used to be a silent one: the pass stopped there and
reported ``items_total`` as if that were the region, with ``coverage`` computed
against it. Now it says so - and a region that ends exactly ON the ceiling is
complete and must not say so.

No database is involved: the session is replaced by a recorder that serves the
pages the statement asks for and holds them until they are expunged.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

import pytest

from app.modules.costs.models import CostItem, ResourcePrice
from app.modules.costs.resource_pricing import ResourcePriceService

SCAN = 7
ITEMS = 25
REGION = "XX_REPRICE_BOUND"
RESOURCE = "R0001"
UNIT_PRICE = Decimal("3.00")

# ``LIMIT n OFFSET m`` as the default dialect renders it with literal binds.
_LIMIT_OFFSET = re.compile(r"LIMIT (\d+) OFFSET (\d+)")


def _work_item(index: int) -> CostItem:
    """One work item whose recipe is a single line of ``index + 1`` units.

    The quantity carries the row's index, so the rates the pass writes are a
    census of which rows it saw: a page served twice or skipped changes the
    multiset of rates, which neither the page-size assertions nor the counters
    would notice on their own.
    """
    return CostItem(
        code=f"W{index:04d}",
        description=f"Work item {index}",
        unit="m3",
        rate="0.00",
        currency="EUR",
        region=REGION,
        components=[
            {
                "code": RESOURCE,
                "name": "Cement",
                "type": "material",
                "unit": "kg",
                "quantity": float(index + 1),
                "unit_rate": 0.0,
            }
        ],
        metadata_={},
    )


def _expected_rates(count: int) -> list[Decimal]:
    return [Decimal(index + 1) * UNIT_PRICE for index in range(count)]


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
    """Serves the work-item scan page by page and keeps what it handed out.

    The retention is the point. A real ``Session`` holds every entity it
    returns until the transaction ends, so releasing a page is a deliberate act
    and not a consequence of the read being paged. ``peak_held`` is therefore
    the measurement that separates a paged-and-released pass from a paged one
    that still accumulates.
    """

    def __init__(self, count: int, *, release: bool = True) -> None:
        self._count = count
        self._release = release
        self.identity: dict[int, CostItem] = {}
        self.served: list[CostItem] = []
        self.page_sizes: list[int] = []
        self.peak_held = 0
        self.flushes = 0
        self.commits = 0

    async def execute(self, statement: Any) -> _Rows:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if ResourcePrice.__tablename__ in sql:
            # The price sheet. Told apart by table name rather than by call
            # order, because the order is exactly what the paging changes.
            return _Rows([(RESOURCE, str(UNIT_PRICE))])
        match = _LIMIT_OFFSET.search(sql)
        assert match is not None, f"the work-item scan asked for no page at all: {sql}"
        limit, offset = int(match.group(1)), int(match.group(2))
        page = [_work_item(index) for index in range(min(offset, self._count), min(self._count, offset + limit))]
        for row in page:
            self.identity[id(row)] = row
        self.served.extend(page)
        self.page_sizes.append(len(page))
        self.peak_held = max(self.peak_held, len(self.identity))
        return _Rows(page)

    def expunge(self, obj: Any) -> None:
        if self._release:
            self.identity.pop(id(obj), None)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


async def _reprice(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bound: int = SCAN,
    items: int = ITEMS,
    cap: int | None = None,
    release: bool = True,
    dry_run: bool = False,
) -> tuple[_RecordingSession, Any]:
    """Run a reprice against a recording session and return the recorder and result."""
    monkeypatch.setattr(ResourcePriceService, "_REPRICE_SCAN_ROWS", bound)
    if cap is not None:
        monkeypatch.setattr(ResourcePriceService, "_MAX_REPRICE_ITEMS", cap)
    session = _RecordingSession(items, release=release)
    result = await ResourcePriceService(session).reprice_region(REGION, dry_run=dry_run)  # type: ignore[arg-type]
    return session, result


@pytest.fixture
async def bounded(monkeypatch: pytest.MonkeyPatch) -> tuple[_RecordingSession, Any]:
    return await _reprice(monkeypatch)


async def test_no_page_exceeds_the_reprice_bound(bounded: tuple[_RecordingSession, Any]) -> None:
    session, _ = bounded
    assert session.page_sizes, "the reprice read nothing, so the bound was never exercised"
    assert max(session.page_sizes) <= SCAN, f"a page of {max(session.page_sizes)} rows passed a bound of {SCAN}"


async def test_the_reprice_reads_more_than_one_page(bounded: tuple[_RecordingSession, Any]) -> None:
    # The assertion above is also satisfied by a pass that read one short page
    # and stopped, and by one that never entered the loop. This is the half that
    # says the paging happened.
    session, _ = bounded
    assert len(session.page_sizes) == math.ceil(ITEMS / SCAN)


async def test_the_pass_never_holds_more_than_one_page(bounded: tuple[_RecordingSession, Any]) -> None:
    # The assertion the paging alone does not buy. Every row the session hands
    # out stays in its identity map, and this loop mutates the rows it is given,
    # so without the flush-then-expunge at the end of each page the region
    # accumulates exactly as it did when the read was one buffered statement -
    # with the page-size assertions above still green.
    session, _ = bounded
    assert session.peak_held <= SCAN, (
        f"the session was holding {session.peak_held} work items at once under a page bound of {SCAN}; "
        "the pages were read but never released"
    )


async def test_a_page_is_written_out_before_it_is_released(bounded: tuple[_RecordingSession, Any]) -> None:
    # Releasing first would detach the instances with their UPDATEs unflushed
    # and the page's work would be lost. Every page must therefore have been
    # flushed, and the ones under 500 rows only get that from the page-end
    # flush, not from the every-500 counter inside the loop.
    session, _ = bounded
    assert session.flushes >= len(session.page_sizes)
    assert session.commits == 1


async def test_every_work_item_still_arrives(bounded: tuple[_RecordingSession, Any]) -> None:
    # Paging is only correct if it loses nothing and repeats nothing. An
    # off-by-one in the offset is invisible to the assertions above: here it
    # shows up as a page census that does not add up, or as a multiset of
    # written rates that is not the region's.
    session, result = bounded
    assert sum(session.page_sizes) == ITEMS
    assert result.items_total == ITEMS
    assert result.items_repriced == ITEMS
    assert result.items_fully_priced == ITEMS
    assert sorted(Decimal(item.rate) for item in session.served) == sorted(_expected_rates(ITEMS))


async def test_a_dry_run_also_lets_go_of_each_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # A dry run writes nothing, so it has nothing to flush - but it reads the
    # same rows and the session retains them just the same. The release has to
    # happen on this path too or the preview costs what the write cost.
    session, result = await _reprice(monkeypatch, dry_run=True)

    assert result.dry_run is True
    assert session.peak_held <= SCAN
    assert session.commits == 0
    assert all(Decimal(item.rate) == Decimal("0.00") for item in session.served)


async def test_an_unreachable_bound_produces_the_one_page_the_others_forbid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _ = await _reprice(monkeypatch, bound=10**9)

    assert session.page_sizes == [ITEMS]
    assert max(session.page_sizes) > SCAN
    assert len(session.page_sizes) != math.ceil(ITEMS / SCAN)
    assert session.peak_held == ITEMS


async def test_a_page_that_is_read_but_not_released_still_accumulates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control for the retention half specifically: same paged reads, same
    # page sizes, expunge made inert. The page assertions stay green and the
    # peak is the whole region - which is what makes them insufficient on their
    # own and why the peak is asserted separately.
    session, _ = await _reprice(monkeypatch, release=False)

    assert max(session.page_sizes) <= SCAN
    assert len(session.page_sizes) == math.ceil(ITEMS / SCAN)
    assert session.peak_held == ITEMS


async def test_paging_changes_the_peak_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    # The controls above prove the bound shaped the reads. This one proves the
    # shaping was free: a pass that paged and one that did not must agree on
    # every number they report and on every rate they write.
    paged_session, paged_result = await _reprice(monkeypatch, bound=SCAN)
    whole_session, whole_result = await _reprice(monkeypatch, bound=10**9)

    assert paged_result.as_dict() == whole_result.as_dict()
    assert [Decimal(item.rate) for item in paged_session.served] == [
        Decimal(item.rate) for item in whole_session.served
    ]


async def test_a_region_larger_than_the_ceiling_reports_the_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ceiling is a truncation and used to be a silent one: the pass stopped
    # there and handed back a summary in which ``items_total`` read as the size
    # of the region and ``coverage`` was computed against it, with nothing
    # anywhere to say the rest still carried its old rates.
    cap = 10
    session, result = await _reprice(monkeypatch, cap=cap)

    assert result.items_total == cap, "the ceiling did not bite, so there is no truncation to report"
    assert sum(session.page_sizes) == cap + 1, "the one-row look past the ceiling did not happen"
    assert result.items_truncated is True
    assert result.items_cap == cap
    assert result.as_dict()["items_truncated"] is True
    assert result.as_dict()["items_cap"] == cap


async def test_a_region_that_ends_on_the_ceiling_is_not_called_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The false alarm the look-ahead exists to prevent. A region of exactly the
    # ceiling's size was walked in full, and calling that one truncated would
    # send the reader after rows that are not there.
    cap = 10
    _, result = await _reprice(monkeypatch, items=cap, cap=cap)

    assert result.items_total == cap
    assert result.items_truncated is False
    assert result.items_cap == cap


async def test_a_region_inside_the_ceiling_is_not_called_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, result = await _reprice(monkeypatch)

    assert result.items_total == ITEMS
    assert result.items_truncated is False
    assert result.items_cap == ResourcePriceService._MAX_REPRICE_ITEMS
