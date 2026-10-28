"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The cost import must hand rows over in bounded slices, never in one list.

This pins the shape of the memory the import holds while it runs, which
nothing else observes. The import used to build every row of a region before
the first insert; a catalogue of tens of thousands of items then needed more
resident memory than the small servers the platform promises to run on, and
the kernel killed the process part way through. What the operator saw was a
server that stopped, not an import that failed, so the symptom pointed at
everything except the import.

The bound is checked by watching the sizes the inserter is called with rather
than by measuring memory. The size is the thing this code actually decides;
resident memory is decided by the allocator, the reader and the garbage
collector as well, and a test that measured it would fail for reasons that had
nothing to do with this loop.

The last test is the control. It runs the same import with the bound raised
out of reach, which is what removing the flush would look like from inside the
loop, and asserts the single unbounded batch that would then appear. Without
it the other three only prove that an import happened, not that the bound is
what shaped it.

No database is involved: the single function that touches PostgreSQL is
replaced, so what remains is the parquet reader and the batching loop.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

# The import writes cost items, so the ORM has to be importable even though
# this test never reaches a database.
import app.modules.costs.models  # noqa: F401

FLUSH = 7
ITEMS = 25


def _write_parquet(path: Path, items: int) -> None:
    """A minimal CWICR parquet: one labour resource per work item."""
    import pandas as pd

    pd.DataFrame(
        [
            {
                "rate_code": f"R{index:04d}",
                "rate_original_name": f"Work item {index}",
                "rate_final_name": f"Work item {index}",
                "rate_unit": "m3",
                "collection_name": "Works",
                "department_name": "Structural",
                "section_name": "Demolition",
                "resource_code": "L1",
                "resource_name": "Labour",
                "resource_unit": "hr",
                "resource_quantity": 1.0,
                "resource_price_per_unit_current": 10.0,
                "resource_cost": 10.0,
                "row_type": "Labour",
                "is_labor": True,
                "is_material": False,
                "is_machine": False,
            }
            for index in range(items)
        ]
    ).to_parquet(path, index=False)


def _import_with_bound(bound: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Run an import against a recording inserter and return the batch sizes."""
    from app.modules.costs import router

    sizes: list[int] = []

    def _record(_url: str, rows: list[Any]) -> int:
        # The loop clears the list it passed, so the length has to be taken
        # now. Keeping the list itself would record every batch as empty and
        # the assertions below would all pass against a broken import.
        sizes.append(len(rows))
        return len(rows)

    monkeypatch.setattr(router, "_pg_bulk_insert_cost_rows", _record)
    monkeypatch.setattr(router, "_INSERT_FLUSH_ROWS", bound)

    parquet = tmp_path / "cwicr.parquet"
    _write_parquet(parquet, ITEMS)
    router._process_and_insert_cwicr(str(parquet), "flush-test", "postgresql+psycopg2://unused/unused")
    return sizes


@pytest.fixture
def flush_sizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return _import_with_bound(FLUSH, tmp_path, monkeypatch)


def test_no_batch_exceeds_the_flush_bound(flush_sizes: list[int]) -> None:
    assert flush_sizes, "the import inserted nothing, so the bound was never exercised"
    assert max(flush_sizes) <= FLUSH, f"a batch of {max(flush_sizes)} rows passed a bound of {FLUSH}"


def test_the_import_flushes_more_than_once(flush_sizes: list[int]) -> None:
    # The assertion above is also satisfied by an import that silently dropped
    # every row but one, and by one that never entered the loop at all. This
    # is the half that says the slicing happened.
    assert len(flush_sizes) == math.ceil(ITEMS / FLUSH)


def test_every_row_still_arrives(flush_sizes: list[int]) -> None:
    # Bounding the batches is only correct if the bound loses nothing. An
    # off-by-one in the flush is the failure this catches, and it is invisible
    # to the two assertions above.
    assert sum(flush_sizes) == ITEMS


def test_an_unreachable_bound_produces_the_one_batch_the_others_forbid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes = _import_with_bound(10**9, tmp_path, monkeypatch)

    assert sizes == [ITEMS]
    assert max(sizes) > FLUSH
    assert len(sizes) != math.ceil(ITEMS / FLUSH)
