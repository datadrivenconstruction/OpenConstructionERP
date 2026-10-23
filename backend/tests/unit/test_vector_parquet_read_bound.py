"""The pre-built embedding parquet must be read in bounded batches.

The file carries one embedding per cost item beside its text columns, so for a
large region it is tens of thousands of rows and hundreds of megabytes once
decoded. Reading it whole put all of that in memory before a single record
reached the vector store - the same shape that made a cost-base import kill a
small server, on the same machines, often in the same session.

The bound is checked by watching the batches that come off the reader rather
than by measuring memory. The batch size is what this code decides; resident
memory is decided by the parquet decoder, the allocator and the garbage
collector as well, and a test that measured it would fail for reasons unrelated
to this loop. The batches are observed at the vector store because the loop
hands each one straight over, so their sizes are the reader's sizes.

The third test is the control. It runs the same load with the bound raised out
of reach, which is what reading the file whole looks like from inside the loop,
and asserts the single unbounded batch that would then appear. The fixture
writes the file as one row group precisely so that control means what it says:
the reader never buffers less than a row group, so a file split into several
would come back in several batches whatever the bound.

The last test covers the other half of this endpoint. The vector store is an
optional dependency, and an installation without it used to get an unexplained
500 from here while the sibling indexing endpoint returned a readable message.

No database is involved and nothing is downloaded: the cache directory is
redirected at a temporary file that is already there.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from app.modules.costs import router

READ = 7
ITEMS = 25
DIM = 16
DB_ID = "XX_VECTOR_BOUND"


def _write_vector_parquet(path: Path, items: int) -> None:
    """A minimal pre-built embedding parquet, written as a single row group."""
    import pandas as pd

    pd.DataFrame(
        [
            {
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "vector": [float(index)] * DIM,
                "code": f"R{index:04d}",
                "description": f"Work item {index}",
                "unit": "m3",
                "rate": 10.0 + index,
                "region": DB_ID,
            }
            for index in range(items)
        ]
    ).to_parquet(path, index=False, row_group_size=items * 10)


def _prepare(
    bound: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    indexer: Any,
) -> None:
    """Point the endpoint at a local cache that already holds the file."""
    import app.core.vector as vector_module

    monkeypatch.setitem(router._GITHUB_CWICR_FILES, DB_ID, f"{DB_ID}/{DB_ID}.parquet")
    monkeypatch.setattr(router, "_CWICR_CACHE_DIR", tmp_path)
    monkeypatch.setattr(router, "_VECTOR_READ_ROWS", bound)
    monkeypatch.setattr(vector_module, "vector_index", indexer)

    cache_dir = tmp_path / "vectors"
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet = cache_dir / f"{DB_ID}_vectors.parquet"
    _write_vector_parquet(parquet, ITEMS)
    # The endpoint treats a file under 1000 bytes as a failed download and goes
    # to the network. If that ever became true of this fixture the tests below
    # would be exercising the wrong branch in silence.
    assert parquet.stat().st_size > 1000


async def _load_with_bound(bound: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Run a load against a recording vector store and return the batch sizes."""
    sizes: list[int] = []

    def _record(records: list[dict[str, Any]]) -> int:
        sizes.append(len(records))
        return len(records)

    _prepare(bound, tmp_path, monkeypatch, _record)
    await router.load_vector_from_github(db_id=DB_ID, session=None, _user_id=None)  # type: ignore[arg-type]
    return sizes


@pytest.fixture
async def read_sizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return await _load_with_bound(READ, tmp_path, monkeypatch)


async def test_no_batch_exceeds_the_read_bound(read_sizes: list[int]) -> None:
    assert read_sizes, "the load indexed nothing, so the bound was never exercised"
    assert max(read_sizes) <= READ, f"a batch of {max(read_sizes)} rows passed a bound of {READ}"


async def test_the_file_is_read_in_more_than_one_batch(read_sizes: list[int]) -> None:
    # The assertion above is also satisfied by a load that read one short batch
    # and stopped. This is the half that says the file was streamed, and it is
    # the assertion the old whole-file read could not have satisfied: its batch
    # size was a literal 256, so a file of 25 rows arrived in exactly one piece
    # no matter what this bound said.
    assert len(read_sizes) == math.ceil(ITEMS / READ)


async def test_every_row_still_arrives(read_sizes: list[int]) -> None:
    # Bounding the batches is only correct if the bound loses nothing. A row
    # dropped at a batch seam is invisible to both assertions above.
    assert sum(read_sizes) == ITEMS


async def test_an_unreachable_bound_produces_the_one_batch_the_others_forbid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes = await _load_with_bound(10**9, tmp_path, monkeypatch)

    assert sizes == [ITEMS]
    assert max(sizes) > READ
    assert len(sizes) != math.ceil(ITEMS / READ)


async def test_a_missing_vector_store_is_reported_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _absent(_records: list[dict[str, Any]]) -> int:
        raise RuntimeError("LanceDB not available")

    _prepare(READ, tmp_path, monkeypatch, _absent)
    response = await router.load_vector_from_github(db_id=DB_ID, session=None, _user_id=None)  # type: ignore[arg-type]

    assert response["indexed"] == 0
    # The cause stays in the server log; the response names the condition without the exception text.
    assert "LanceDB not available" not in response["message"]
    assert "vector store" in response["message"]
