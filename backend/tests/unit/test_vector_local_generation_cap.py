"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Generating vectors locally must cover the catalogue, or say where it stopped.

When the pre-built embeddings cannot be fetched, this endpoint falls back to
generating them from the cost items already in the database. That fallback took
a fixed first slice - ``search(region=db_id, limit=5000)`` - and reported how
many rows it had indexed and nothing else. For any base bigger than the slice
the caller was handed a smaller, entirely plausible number, and the rest of the
catalogue was left out of the search index with nothing anywhere to say so. The
two values that would have said so, ``total`` and ``has_more``, came back from
the same call and were discarded on the spot.

A cap is still the right shape here, unlike on reads that merely buffer: every
row on this path goes through an embedding model inside the request, so removing
the ceiling would put unbounded CPU work on an open connection. What changes is
that the pass now walks the catalogue in pages up to that ceiling instead of
stopping at the first one, that the ceiling sits above every base the platform
ships so reaching it is an anomaly, and that reaching it is reported - with the
ceiling, how much was covered and how much there was.

The last two tests are the pair that matters. One puts a catalogue past the
ceiling and asserts the signal appears; the other puts one that ends exactly ON
the ceiling and asserts it does not, because a false alarm sends the reader
looking for rows that were never missing.

No database is involved: the repository is replaced by one that serves pages,
and the embedding model by a recorder.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from app.modules.costs import router

DB_ID = "XX_LOCAL_CAP"
PAGE = 7
ITEMS = 25
DIM = 8


class _Item:
    """The attributes the fallback reads off a cost item."""

    def __init__(self, index: int) -> None:
        self.id = f"00000000-0000-0000-0000-{index:012d}"
        self.code = f"R{index:04d}"
        self.description = f"Work item {index}"
        self.unit = "m3"
        self.rate = 10.0 + index
        self.region = DB_ID


class _Repo:
    """Serves ``CostItemRepository.search`` page by page and records the calls.

    Mirrors the real contract the paging leans on: a deterministic order, an
    honest ``has_more``, and a ``total`` only on the page that asked for one.
    """

    rows = ITEMS
    region_rows = ITEMS

    def __init__(self, _session: Any) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> tuple[list[_Item], int | None, bool]:
        self.calls.append(dict(kwargs))
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 50))
        available = self.region_rows if kwargs.get("region") is not None else self.rows
        items = [_Item(index) for index in range(min(offset, available), min(available, offset + limit))]
        total = None if kwargs.get("skip_count") else available
        return items, total, offset + len(items) < available


async def _load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    page: int = PAGE,
    cap: int | None = None,
    rows: int = ITEMS,
    region_rows: int | None = None,
) -> tuple[_Repo, list[dict[str, Any]], Any]:
    """Drive the offline branch of the loader and return the repo, the records and the response."""
    import app.core.vector as vector_module
    import app.modules.costs.repository as repository_module

    indexed_records: list[dict[str, Any]] = []
    made: list[_Repo] = []

    class _TrackedRepo(_Repo):
        rows = ITEMS
        region_rows = ITEMS

        def __init__(self, session: Any) -> None:
            super().__init__(session)
            made.append(self)

    _TrackedRepo.rows = rows
    _TrackedRepo.region_rows = rows if region_rows is None else region_rows

    def _encode(texts: list[str]) -> list[list[float]]:
        return [[float(position)] * DIM for position in range(len(texts))]

    def _index(records: list[dict[str, Any]]) -> int:
        indexed_records.extend(records)
        return len(records)

    def _no_download(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("no route to host")

    monkeypatch.setitem(router._GITHUB_CWICR_FILES, DB_ID, f"{DB_ID}/{DB_ID}.parquet")
    monkeypatch.setattr(router, "_CWICR_CACHE_DIR", tmp_path)
    monkeypatch.setattr(router, "_download_to_file", _no_download)
    monkeypatch.setattr(router, "_LOCAL_VECTOR_PAGE_ROWS", page)
    if cap is not None:
        monkeypatch.setattr(router, "_LOCAL_VECTOR_MAX_ROWS", cap)
    monkeypatch.setattr(repository_module, "CostItemRepository", _TrackedRepo)
    monkeypatch.setattr(vector_module, "encode_texts", _encode)
    monkeypatch.setattr(vector_module, "vector_index", _index)

    response = await router.load_vector_from_github(db_id=DB_ID, session=None, _user_id=None)  # type: ignore[arg-type]
    return made[0], indexed_records, response


@pytest.fixture
async def loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[_Repo, list[dict[str, Any]], Any]:
    return await _load(tmp_path, monkeypatch)


async def test_the_whole_catalogue_is_indexed_when_it_fits(
    loaded: tuple[_Repo, list[dict[str, Any]], Any],
) -> None:
    _, records, response = loaded

    assert response["source"] == "local", "the download was reachable, so the offline branch never ran"
    assert response["indexed"] == ITEMS
    assert response["scanned"] == ITEMS
    assert response["total"] == ITEMS
    assert len(records) == ITEMS
    assert sorted(record["code"] for record in records) == sorted(f"R{index:04d}" for index in range(ITEMS))


async def test_the_catalogue_is_read_in_bounded_pages(loaded: tuple[_Repo, list[dict[str, Any]], Any]) -> None:
    # Indexing all of it in one read would satisfy the assertions above while
    # putting the whole catalogue in memory, which is the shape this endpoint
    # shares with the import that runs before it.
    repo, _, _ = loaded

    assert max(call["limit"] for call in repo.calls) <= PAGE
    assert len(repo.calls) == math.ceil(ITEMS / PAGE)
    assert [call["offset"] for call in repo.calls] == [index * PAGE for index in range(len(repo.calls))]


async def test_only_the_first_page_pays_for_a_count(loaded: tuple[_Repo, list[dict[str, Any]], Any]) -> None:
    repo, _, response = loaded

    assert repo.calls[0]["skip_count"] is False
    assert all(call["skip_count"] is True for call in repo.calls[1:])
    assert response["total"] == ITEMS, "the count from the first page did not survive the later pages"


async def test_a_run_inside_the_ceiling_is_not_called_truncated(
    loaded: tuple[_Repo, list[dict[str, Any]], Any],
) -> None:
    _, _, response = loaded

    assert response["truncated"] is False
    assert response["cap"] == router._LOCAL_VECTOR_MAX_ROWS
    assert "ceiling" not in response["message"]


async def test_a_catalogue_past_the_ceiling_says_it_was_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole point. A caller reading ``indexed`` alone cannot tell a small
    # base from a truncated one, so the truncation has to be on the response in
    # its own right - with what was covered, what there was, and the ceiling
    # that stopped it.
    cap = 10
    _, records, response = await _load(tmp_path, monkeypatch, cap=cap)

    assert response["truncated"] is True
    assert response["cap"] == cap
    assert response["scanned"] == cap
    assert response["indexed"] == cap
    assert response["total"] == ITEMS
    assert len(records) == cap
    assert str(cap) in response["message"]
    assert "NOT in the search index" in response["message"]


async def test_the_truncated_run_still_reports_the_size_it_could_not_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``total`` and ``has_more`` were both available to the old fixed read and
    # both thrown away. This is the assertion that they are not any more: the
    # gap between what was walked and what exists has to be readable.
    cap = 10
    _, _, response = await _load(tmp_path, monkeypatch, cap=cap)

    assert response["total"] - response["scanned"] == ITEMS - cap


async def test_a_catalogue_that_ends_on_the_ceiling_is_not_called_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The false alarm the check exists to avoid. A catalogue of exactly the
    # ceiling's size was covered in full, and flagging it would send the reader
    # after rows that are not there.
    cap = 10
    _, _, response = await _load(tmp_path, monkeypatch, cap=cap, rows=cap)

    assert response["scanned"] == cap
    assert response["total"] == cap
    assert response["truncated"] is False


async def test_a_db_id_that_names_no_region_still_falls_back_to_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Long-standing behaviour of this endpoint, and easy to lose when the
    # single read becomes a loop: a db_id that is not a stored region tag must
    # still produce an index off the whole catalogue rather than a 400.
    repo, records, response = await _load(tmp_path, monkeypatch, region_rows=0)

    assert repo.calls[0]["region"] == DB_ID
    assert repo.calls[1]["region"] is None, "the empty region did not fall back to the whole catalogue"
    assert response["scanned"] == ITEMS
    assert len(records) == ITEMS


async def test_an_empty_catalogue_is_still_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await _load(tmp_path, monkeypatch, rows=0)

    assert raised.value.status_code == 400
