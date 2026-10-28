"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A vector reindex must read the collection, and let go of it, one page at a time.

``create_vector_routes`` is the factory behind ``POST /vector/reindex/`` in six
modules, so whatever shape it reads in is the shape all six read in. It read the
whole table in one buffered statement and then held every entity for the length
of the pass. Measured on this tree with tracemalloc, one loaded row costs
2.5 KiB (a requirement) to 29.7 KiB (a validation report, whose ``results`` JSON
carries one entry per rule fired), with documents at 2.7 and tasks, risks and
chat messages between 4.7 and 7.3 - so a 100 000-row collection of the heaviest
kind
is ~2.9 GiB held at once, on a platform whose stated floor is a 3 GB server that
also runs PostgreSQL.

Paging that read is only half of the bound, and the half that is easy to believe
in wrongly: a ``Session`` keeps every entity it hands out until the transaction
ends, whatever shape the read had. The page has to be released as well, which is
why the recorder below models an identity map and why the peak it holds - not
the size of a page - is what the third test asserts. A recorder that forgot its
rows would report a flat peak whether or not the release happened and could not
tell the two apart.

The controls: one run with the bound raised out of reach, which is what removing
the paging would look like from inside the handler, and one comparing a paged
pass against an unpaged one on every key it returns and every row it embeds -
paging a walk is only correct if it changes nothing but the peak.

The ceiling is the other half. Every row on this path goes through the embedding
model inside the request, so a cap belongs here - but a cap that is not reported
hands the caller a plausible ``indexed`` count and nothing to say the rest of the
collection is not searchable. A collection that ends exactly ON the ceiling is
complete and must not raise that flag.

The last two cover the custom-scope branch. A scope used to return its rows,
which defeated any bound the factory could apply, so it now returns the SELECT
and the factory owns the walk for every module at once.

No database is involved: the session is replaced by a recorder that serves the
pages the statement asks for and holds them until they are expunged, and the
embedding side by a recorder that counts what it was handed.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest
from sqlalchemy import Select, String, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core import vector_routes

PAGE = 7
ROWS = 25
COLLECTION = "vec_reindex_bound"
PROJECT = "11111111-1111-1111-1111-111111111111"


class _Base(DeclarativeBase):
    """Private registry - this row exists for the walk, not for the schema."""


class _VecRow(_Base):
    __tablename__ = "vec_reindex_bound_row"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36))
    body: Mapped[str] = mapped_column(Text)


def _row(index: int) -> _VecRow:
    return _VecRow(id=f"00000000-0000-0000-0000-{index:012d}", project_id=PROJECT, body=f"row {index}")


class _Adapter:
    """The two attributes the handler reads off an embedding adapter."""

    collection_name = COLLECTION
    module_name = "vec_reindex_bound"


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
    """Serves the row scan page by page and keeps what it handed out.

    The retention is the point. A real ``Session`` holds every entity it returns
    until the transaction ends, so releasing a page is a deliberate act and not
    a consequence of the read being paged. ``peak_held`` is therefore the
    measurement that separates a paged-and-released pass from a paged one that
    still accumulates.
    """

    def __init__(self, count: int, *, release: bool = True) -> None:
        self._count = count
        self._release = release
        self.identity: dict[int, _VecRow] = {}
        self.page_sizes: list[int] = []
        self.statements: list[str] = []
        self.peak_held = 0
        self.flushes = 0
        # Every read / flush / release in the order they happened, so the test
        # that cares about the ORDER of the last two can see it.
        self.events: list[str] = []

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(str(statement))
        limit = statement._limit
        offset = statement._offset or 0
        # ``limit is None`` is the unpaged read: it is what the handler did
        # before the bound, and what it would do again if the paging were
        # dropped, so the recorder answers it rather than refusing it.
        stop = self._count if limit is None else min(self._count, offset + limit)
        page = [_row(index) for index in range(min(offset, self._count), stop)]
        for row in page:
            self.identity[id(row)] = row
        self.page_sizes.append(len(page))
        self.events.append(f"read:{len(page)}")
        self.peak_held = max(self.peak_held, len(self.identity))
        return _Rows(page)

    def expunge(self, obj: Any) -> None:
        self.events.append("expunge")
        if self._release:
            self.identity.pop(id(obj), None)

    async def flush(self) -> None:
        self.flushes += 1
        self.events.append("flush")


class _Indexer:
    """Stands in for ``reindex_collection`` and records what it was handed."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self.purge_calls: list[bool] = []

    async def __call__(self, adapter: Any, rows: list[Any], *, purge_first: bool = False, **_: Any) -> dict[str, Any]:
        self.batches.append([row.id for row in rows])
        self.purge_calls.append(purge_first)
        return {
            "indexed": len(rows),
            "skipped": 0,
            "purged": bool(purge_first and rows),
            "collection": adapter.collection_name,
        }

    @property
    def ids(self) -> list[str]:
        return [row_id for batch in self.batches for row_id in batch]


def _handler(**kwargs: Any) -> Any:
    """Pull the reindex endpoint out of a freshly built sub-router."""
    router = vector_routes.create_vector_routes(
        collection=COLLECTION,
        adapter=_Adapter(),  # type: ignore[arg-type]
        read_permission=None,
        write_permission=None,
        **kwargs,
    )
    return next(route.endpoint for route in router.routes if route.path == "/vector/reindex/")  # type: ignore[attr-defined]


async def _statement(_session: Any, project_id: uuid.UUID | None) -> Select[Any]:
    """A custom scope, in the shape the factory now requires: the SELECT itself."""
    stmt = select(_VecRow)
    if project_id is not None:
        stmt = stmt.where(_VecRow.project_id == str(project_id))
    return stmt


async def _reindex(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bound: int = PAGE,
    rows: int = ROWS,
    cap: int | None = None,
    release: bool = True,
    purge_first: bool = False,
    custom_scope: bool = False,
) -> tuple[_RecordingSession, _Indexer, dict[str, Any]]:
    """Run one reindex against the recorders and return both plus the response.

    ``raising=False`` on the two bounds is deliberate: an implementation that
    has no bound at all must reach its own code and fail on what it did, not on
    the missing name. ``test_the_bounds_exist`` is where a typo in either name
    is caught instead.
    """
    monkeypatch.setattr(vector_routes, "_REINDEX_PAGE_ROWS", bound, raising=False)
    if cap is not None:
        monkeypatch.setattr(vector_routes, "_REINDEX_MAX_ROWS", cap, raising=False)
    indexer = _Indexer()
    monkeypatch.setattr(vector_routes, "reindex_collection", indexer)
    handler = _handler(statement_factory=_statement) if custom_scope else _handler(model=_VecRow)
    session = _RecordingSession(rows, release=release)
    result = await handler(session, None, None, purge_first)
    return session, indexer, result


@pytest.fixture
async def bounded(monkeypatch: pytest.MonkeyPatch) -> tuple[_RecordingSession, _Indexer, dict[str, Any]]:
    return await _reindex(monkeypatch)


async def test_the_bounds_exist() -> None:
    # The tests below patch these two names with ``raising=False`` so that an
    # unbounded implementation reaches its own code and fails on what it did.
    # That makes this the one place a renamed or deleted bound is caught.
    assert isinstance(vector_routes._REINDEX_PAGE_ROWS, int)
    assert isinstance(vector_routes._REINDEX_MAX_ROWS, int)
    assert 0 < vector_routes._REINDEX_PAGE_ROWS <= vector_routes._REINDEX_MAX_ROWS


async def test_no_page_exceeds_the_reindex_bound(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    session, _, _ = bounded
    assert session.page_sizes, "the reindex read nothing, so the bound was never exercised"
    assert max(session.page_sizes) <= PAGE, f"a page of {max(session.page_sizes)} rows passed a bound of {PAGE}"


async def test_the_reindex_reads_more_than_one_page(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    # The assertion above is also satisfied by a pass that read one short page
    # and stopped, and by one that never entered the loop. This is the half that
    # says the paging happened.
    session, _, _ = bounded
    assert len(session.page_sizes) == math.ceil(ROWS / PAGE)


async def test_the_pass_never_holds_more_than_one_page(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    # The assertion the paging alone does not buy. Every row the session hands
    # out stays in its identity map until the transaction ends, so without the
    # release at the end of each page the collection accumulates exactly as it
    # did when the read was one buffered statement - with the page-size
    # assertions above still green.
    session, _, _ = bounded
    assert session.peak_held <= PAGE, (
        f"the session was holding {session.peak_held} rows at once under a page bound of {PAGE}; "
        "the pages were read but never released"
    )


async def test_a_page_is_written_out_before_it_is_released(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    # Releasing first detaches the instances with anything pending on them still
    # unflushed, and that work is dropped on the floor. This pass only reads, so
    # the flush is a no-op today - the order is what keeps the release safe the
    # day an adapter or an event handler touches a row.
    session, _, _ = bounded
    assert session.flushes >= len(session.page_sizes)
    for position, event in enumerate(session.events):
        if event == "expunge":
            assert "flush" in session.events[:position], "a page was released before anything was flushed"
            last_read = max(index for index, name in enumerate(session.events[:position]) if name.startswith("read:"))
            assert "flush" in session.events[last_read:position], "the page was released before its own flush"


async def test_the_walk_is_ordered(bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]]) -> None:
    # Offsets into an undefined ordering are not positions: the same row can be
    # served twice and another skipped, silently, with every count still adding
    # up. The recorder serves rows by index whatever the statement says, so this
    # is the only place the ordering itself can be asserted.
    session, _, _ = bounded
    assert session.statements
    for sql in session.statements:
        assert "ORDER BY" in sql, f"a page was addressed by offset over an unordered read: {sql}"
        assert "vec_reindex_bound_row.id" in sql.split("ORDER BY", 1)[1]


async def test_every_row_is_embedded_exactly_once(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    # Paging is only correct if it loses nothing and repeats nothing. An
    # off-by-one in the offset is invisible to the assertions above: here it
    # shows up as a census that does not add up.
    session, indexer, result = bounded
    assert sum(session.page_sizes) == ROWS
    assert indexer.ids == [_row(index).id for index in range(ROWS)]
    assert len(set(indexer.ids)) == ROWS
    assert result["indexed"] == ROWS
    assert result["scanned"] == ROWS


async def test_the_response_still_carries_the_keys_it_always_did(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    # The settings page reads ``indexed`` and ``skipped`` to decide which toast
    # to show and reads ``purged`` beside them. Bounding the read must not move
    # any of that.
    _, _, result = bounded
    assert set(result) >= {"indexed", "skipped", "purged", "collection"}
    assert result["collection"] == COLLECTION
    assert result["skipped"] == 0
    assert result["purged"] is False


async def test_a_purge_is_paired_with_the_page_it_purges(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``purge_first`` drops the ids it is about to index, so doing it per page
    # and doing it once over the union of the pages leave the same rows in the
    # store - but only if every page asks for it.
    _, indexer, result = await _reindex(monkeypatch, purge_first=True)

    assert indexer.purge_calls == [True] * math.ceil(ROWS / PAGE)
    assert result["purged"] is True


async def test_an_unreachable_bound_produces_the_one_page_the_others_forbid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = await _reindex(monkeypatch, bound=10**9)

    assert session.page_sizes == [ROWS]
    assert max(session.page_sizes) > PAGE
    assert len(session.page_sizes) != math.ceil(ROWS / PAGE)
    assert session.peak_held == ROWS


async def test_a_page_that_is_read_but_not_released_still_accumulates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control for the retention half specifically: same paged reads, same
    # page sizes, expunge made inert. The page assertions stay green and the
    # peak is the whole collection - which is what makes them insufficient on
    # their own and why the peak is asserted separately.
    session, _, _ = await _reindex(monkeypatch, release=False)

    assert max(session.page_sizes) <= PAGE
    assert len(session.page_sizes) == math.ceil(ROWS / PAGE)
    assert session.peak_held == ROWS


async def test_paging_changes_the_peak_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    # The controls above prove the bound shaped the reads. This one proves the
    # shaping was free: a pass that paged and one that did not must agree on
    # every key they return and on every row they embed.
    paged_session, paged_indexer, paged = await _reindex(monkeypatch, bound=PAGE)
    whole_session, whole_indexer, whole = await _reindex(monkeypatch, bound=10**9)

    assert paged == whole
    assert paged_indexer.ids == whole_indexer.ids
    assert paged_session.peak_held < whole_session.peak_held


async def test_a_collection_larger_than_the_ceiling_reports_the_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ceiling is a truncation and a silent one is the worse half of the
    # defect: the caller gets a plausible ``indexed`` count and nothing at all
    # to say the rest of the collection is not searchable.
    cap = 10
    session, indexer, result = await _reindex(monkeypatch, cap=cap)

    assert result["scanned"] == cap, "the ceiling did not bite, so there is no truncation to report"
    assert len(indexer.ids) == cap
    assert sum(session.page_sizes) == cap + 1, "the one-row look past the ceiling did not happen"
    assert result["truncated"] is True
    assert result["cap"] == cap
    assert str(cap) in result["message"]
    assert session.peak_held <= PAGE


async def test_a_collection_that_ends_on_the_ceiling_is_not_called_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The false alarm the look-ahead exists to prevent. A collection of exactly
    # the ceiling's size was walked in full, and calling that one truncated
    # sends the reader after rows that are all there.
    cap = 10
    _, _, result = await _reindex(monkeypatch, rows=cap, cap=cap)

    assert result["scanned"] == cap
    assert result["truncated"] is False
    assert result["cap"] == cap


async def test_a_collection_inside_the_ceiling_is_not_called_truncated(
    bounded: tuple[_RecordingSession, _Indexer, dict[str, Any]],
) -> None:
    _, _, result = bounded

    assert result["scanned"] == ROWS
    assert result["truncated"] is False
    assert result["cap"] == vector_routes._REINDEX_MAX_ROWS


async def test_a_custom_scope_is_paged_and_released_like_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # The branch the six consumers split on. Two of them scope their rows
    # through a parent table, and while that scope returned rows it decided the
    # shape of its own read - so the bound the other four got did not exist for
    # chat messages or requirements. Returning the SELECT moves that decision
    # into the factory, and this is the assertion that it landed there.
    session, indexer, result = await _reindex(monkeypatch, custom_scope=True)

    assert max(session.page_sizes) <= PAGE
    assert len(session.page_sizes) == math.ceil(ROWS / PAGE)
    assert session.peak_held <= PAGE
    assert indexer.ids == [_row(index).id for index in range(ROWS)]
    assert result["scanned"] == ROWS
    for sql in session.statements:
        assert "ORDER BY" in sql


async def test_a_scope_that_returns_its_rows_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # The contract, stated where it can be enforced. A scope handing back a list
    # has already read the whole collection, and no amount of paging downstream
    # can undo that - so the factory refuses the old keyword by name instead of
    # letting it through as an unexpected argument.
    async def _rows_loader(session: Any, _project_id: uuid.UUID | None) -> list[Any]:
        return list((await session.execute(select(_VecRow))).scalars().all())

    with pytest.raises(ValueError, match="statement_factory") as excinfo:
        _handler(loader=_rows_loader)

    assert "loader" in str(excinfo.value)

    # And the two that were always mutually exclusive still are.
    with pytest.raises(ValueError, match="exactly one"):
        _handler(model=_VecRow, statement_factory=_statement)
    with pytest.raises(ValueError, match="exactly one"):
        _handler()
