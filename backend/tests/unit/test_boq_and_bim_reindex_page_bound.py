# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The two reindex endpoints that are NOT built by ``create_vector_routes``.

Six modules mount their vector routes from the factory, so bounding the factory
bounded six of the platform's eight reindex paths at once. The other two are
hand-written, for a reason that is not going away: each carries a permission
gate the factory has no vocabulary for (BOQ ownership, BIM model access) and a
second filter of its own (``boq_id``, ``model_id``). They were left reading
their whole table into one list.

They are the two paths where that costs most. Per-row the rows are light -
measured on this tree with tracemalloc, 2.65 KiB for a position and 3.12 KiB
for an element, against 29.71 KiB for the heaviest factory row - but weight per
row is not the exposure here, count is. A converted model contributes its
entire element set to one table and an imported BOQ its entire position set, so
these are the two collections that plausibly reach seven figures, where 2.65
KiB a row is 2.5 GiB held at once on a platform whose stated floor is a 3 GB
server that also runs PostgreSQL.

Both now hand their statement to ``reindex_statement_in_pages``, the same walk
the factory uses, so what is asserted below is asserted of one implementation
through two doors. The gate tests are here for the same reason: the rewiring
moved the read, and the read sits underneath a security check that must still
happen first.

No database is involved: the session is a recorder that serves the pages the
statement asks for and holds them until they are expunged, and the embedding
side is a recorder that counts what it was handed.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core import vector_index, vector_routes
from app.modules.bim_hub import router as bim_router
from app.modules.boq import router as boq_router

pytestmark = pytest.mark.asyncio

PAGE = 7
ROWS = 25
ADMIN = {"role": "admin"}


class _Row:
    """A row of either table. The walk only ever reads its id."""

    def __init__(self, index: int) -> None:
        self.id = uuid.UUID(f"00000000-0000-0000-0000-{index:012d}")


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
    """Serves the scan page by page and keeps what it handed out.

    The retention is the point. A real ``Session`` holds every entity it
    returns until the transaction ends, so releasing a page is a deliberate act
    and not a consequence of the read being paged. ``peak_held`` is therefore
    what separates a paged-and-released pass from a paged one that still
    accumulates.
    """

    def __init__(self, count: int = ROWS) -> None:
        self._count = count
        self.identity: dict[int, _Row] = {}
        self.page_sizes: list[int] = []
        self.statements: list[str] = []
        self.peak_held = 0
        self.flushes = 0
        self.events: list[str] = []

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(str(statement))
        limit = statement._limit
        offset = statement._offset or 0
        # ``limit is None`` is the unpaged read - what both endpoints did
        # before this change and what they would do again if the paging were
        # dropped - so the recorder answers it rather than refusing it.
        stop = self._count if limit is None else min(self._count, offset + limit)
        page = [_Row(index) for index in range(min(offset, self._count), stop)]
        for row in page:
            self.identity[id(row)] = row
        self.page_sizes.append(len(page))
        self.events.append(f"read:{len(page)}")
        self.peak_held = max(self.peak_held, len(self.identity))
        return _Rows(page)

    def expunge(self, obj: Any) -> None:
        self.events.append("expunge")
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
        self.batches.append([str(row.id) for row in rows])
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


async def _call_boq(session: Any, purge_first: bool) -> dict[str, Any]:
    """Tenant-wide BOQ reindex: no filter, so the admin branch of the gate."""
    return await boq_router.boq_vector_reindex(session, None, ADMIN, None, None, purge_first)


async def _call_bim(session: Any, purge_first: bool) -> dict[str, Any]:
    """Tenant-wide BIM reindex: no filter, so no per-object access check."""
    return await bim_router.bim_vector_reindex(session, None, None, None, purge_first)


ENDPOINTS = [pytest.param(_call_boq, id="boq_positions"), pytest.param(_call_bim, id="bim_elements")]


def _bound(monkeypatch: pytest.MonkeyPatch, *, page: int = PAGE, cap: int | None = None) -> _Indexer:
    """Patch the bound and the indexer for one run, and hand back the recorder.

    Both names for ``reindex_collection`` are patched on purpose. The walk
    resolves it through ``vector_routes``; the implementation these tests
    replace resolved it through ``vector_index`` at call time. Patching only
    one leaves the other run talking to the real embedding stack, which would
    fail for reasons that have nothing to do with the bound.

    ``raising=False`` is equally deliberate: an implementation with no bound at
    all must reach its own code and fail on what it did, not on a missing name.
    """
    monkeypatch.setattr(vector_routes, "_REINDEX_PAGE_ROWS", page, raising=False)
    if cap is not None:
        monkeypatch.setattr(vector_routes, "_REINDEX_MAX_ROWS", cap, raising=False)
    indexer = _Indexer()
    monkeypatch.setattr(vector_routes, "reindex_collection", indexer, raising=False)
    monkeypatch.setattr(vector_index, "reindex_collection", indexer, raising=False)
    return indexer


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_the_read_is_paged(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _bound(monkeypatch)
    session = _RecordingSession()
    await call(session, False)

    assert session.page_sizes, "the endpoint read nothing at all"
    biggest = max(session.page_sizes)
    assert biggest <= PAGE, f"a page of {biggest} rows passed a bound of {PAGE} ({ROWS} rows in the scan)"
    # More than one page, or the bound was never exercised and a single
    # unpaged read would satisfy the line above by accident.
    assert len(session.page_sizes) > 1, f"{ROWS} rows came back in {len(session.page_sizes)} read under a {PAGE} bound"


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_the_pass_never_holds_more_than_one_page(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _bound(monkeypatch)
    session = _RecordingSession()
    await call(session, False)

    assert session.peak_held <= PAGE, (
        f"the session was holding {session.peak_held} rows at once under a page bound of {PAGE}; "
        "the pages were read but never released"
    )


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_a_page_is_written_out_before_it_is_released(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _bound(monkeypatch)
    session = _RecordingSession()
    await call(session, False)

    assert session.flushes >= 1, "no page was flushed before it was released"
    # Order, not just presence. Expunging first detaches the instances with
    # their work still pending and drops it silently, which is the failure this
    # assertion exists for - it looks identical from the outside.
    first_flush = session.events.index("flush")
    first_expunge = session.events.index("expunge")
    assert first_flush < first_expunge, f"a page was released before it was flushed: {session.events[:6]}"


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_the_walk_is_ordered(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _bound(monkeypatch)
    session = _RecordingSession()
    await call(session, False)

    # An offset into an undefined ordering is not a position: the same row can
    # be served twice and another skipped, with every count still adding up.
    for statement in session.statements:
        assert "ORDER BY" in statement, f"a page was addressed by offset over an unordered read: {statement[:160]}"


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_every_row_is_embedded_exactly_once(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    indexer = _bound(monkeypatch)
    session = _RecordingSession()
    result = await call(session, False)

    assert len(indexer.ids) == ROWS
    assert len(set(indexer.ids)) == ROWS, "a row was embedded twice"
    assert result["indexed"] == ROWS
    assert result["scanned"] == ROWS


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_the_response_keeps_its_old_keys_and_reports_the_bound(
    call: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bound(monkeypatch)
    session = _RecordingSession()
    result = await call(session, False)

    # The card in Settings reads the first three of these, and both endpoints
    # returned exactly the dict ``reindex_collection`` produced before this
    # change. The bound may add keys; it may not take any away.
    for key in ("indexed", "skipped", "purged", "collection"):
        assert key in result, f"the response lost {key!r}"
    for key in ("scanned", "cap", "truncated"):
        assert key in result, f"the response does not report {key!r}"
    assert result["truncated"] is False


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_a_purge_is_paired_with_the_page_it_purges(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    indexer = _bound(monkeypatch)
    session = _RecordingSession()
    result = await call(session, True)

    # More than one page first: a pass that reads everything in one go pairs
    # its single purge with its single batch by construction, and would satisfy
    # the assertion below while saying nothing at all about paging.
    assert len(indexer.batches) > 1, f"{ROWS} rows reached the indexer in {len(indexer.batches)} call"
    # ``reindex_collection`` deletes the ids it is about to index, not the
    # collection, so every page carries its own purge and the pass as a whole
    # purges exactly the rows it re-indexes. A purge on the first page only
    # would leave later pages' stale vectors in the store.
    assert indexer.purge_calls == [True] * len(indexer.batches)
    assert result["purged"] is True


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_a_scan_past_the_ceiling_says_so(call: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _bound(monkeypatch, page=PAGE, cap=14)
    session = _RecordingSession()
    result = await call(session, False)

    assert result["scanned"] == 14
    assert result["cap"] == 14
    assert result["truncated"] is True
    # A number the reader cannot act on is not a report. The message has to
    # name the ceiling, because "indexed: 14" on a 25-row table is otherwise
    # indistinguishable from a 14-row table that was walked in full.
    assert "14" in result["message"]


@pytest.mark.parametrize("call", ENDPOINTS)
async def test_a_scan_that_ends_on_the_ceiling_is_not_called_truncated(
    call: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exactly ROWS rows and a ceiling of exactly ROWS: the walk stopped on the
    # ceiling AND on the end of the table at once. Calling that truncated sends
    # the operator hunting for rows that are all present.
    _bound(monkeypatch, page=PAGE, cap=ROWS)
    session = _RecordingSession()
    result = await call(session, False)

    assert result["scanned"] == ROWS
    assert result["truncated"] is False


async def test_the_boq_gate_still_refuses_a_tenant_wide_reindex_to_a_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The rewiring moved the read. The check that guards it has to keep
    # happening first, and has to keep happening at all.
    from fastapi import HTTPException

    _bound(monkeypatch)
    session = _RecordingSession()
    with pytest.raises(HTTPException) as raised:
        await boq_router.boq_vector_reindex(session, None, {"role": "estimator"}, None, None, False)

    assert raised.value.status_code == 403
    assert session.statements == [], "the endpoint read rows before deciding the caller was allowed to"


async def test_the_bim_gate_still_runs_before_any_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # Audit B2 turned a scoped BIM reindex into an ownership check. A reindex
    # that reads first and checks second is the same IDOR with extra steps.
    seen: list[uuid.UUID] = []

    async def _refuse(_session: Any, project_id: uuid.UUID, _user_id: Any) -> None:
        seen.append(project_id)
        raise PermissionError("not yours")

    _bound(monkeypatch)
    monkeypatch.setattr(bim_router, "_verify_project_access", _refuse)
    session = _RecordingSession()
    project_id = uuid.uuid4()
    with pytest.raises(PermissionError):
        await bim_router.bim_vector_reindex(session, None, project_id, None, False)

    assert seen == [project_id]
    assert session.statements == [], "the endpoint read rows before deciding the caller was allowed to"
