"""The cost import reads its parquet in batches and still writes what it always wrote.

A country cost base used to be read into one pandas frame, which peaked at 2 to
8 GiB on a server that has about 1.8 GiB to give an import. The loader now
reads a few thousand rows at a time and processes a work item only once all
of its rows have been read. These tests hold it to the old behaviour, row for
row, against a frozen copy of the whole-frame import
(``tests/_cwicr_whole_frame_import.py``), on a parquet built so that the hard
cases fall across batch boundaries (``tests/_cwicr_import_cases.py``).

What is compared is everything that reaches the database layer: every row in
the order it was handed over (all fourteen columns but the random id), the size
of every flush, and the result the caller reports. A test of the stored set
alone would pass an import that reordered its rows across flushes, and that
changes which of two colliding codes is kept and what an interrupted import
leaves behind.

The control test runs the stream with each row treated as complete on its own,
which is what a loader that forgot about items spanning batches would do, and
asserts that the comparison then fails. Without it, the equality tests could
pass on a fixture that never put an item across a boundary.

No database is involved: the one function that talks to PostgreSQL is replaced
by a recorder that, like PostgreSQL, refuses a NUL character.
"""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path
from typing import Any

import psycopg2
import pytest

# The import writes cost items, so the ORM has to be importable even though
# this test never reaches a database.
import app.modules.costs.models  # noqa: F401
from app.modules.costs import router
from tests._cwicr_import_cases import (
    LONG_A,
    hard_case_rows,
    write_far_return_parquet,
    write_hard_case_parquet,
    write_orphan_scattered_parquet,
    write_synthetic_parquet,
)
from tests._cwicr_whole_frame_import import whole_frame_import

REGION = "ZZ_STREAM_TEST"
URL = "postgresql+psycopg2://unused/unused"


class _Recorder:
    """Stands in for ``_pg_bulk_insert_cost_rows``: keeps what each flush handed over."""

    def __init__(self, *, fail_on_call: int | None = None, keep: bool = True) -> None:
        self.flushes: list[int] = []
        self.rows: list[tuple] = []
        self.calls = 0
        self.fail_on_call = fail_on_call
        self.keep = keep

    def __call__(self, _url: str, rows: list[tuple]) -> int:
        self.calls += 1
        if self.fail_on_call is not None and self.calls == self.fail_on_call:
            # A lost connection, not a bad row: it must stop the import.
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        if any("\x00" in str(value) for row in rows for value in row):
            raise psycopg2.DataError("invalid byte sequence for encoding UTF8: 0x00")
        # The caller clears the list it passed, so copy what matters now.
        self.flushes.append(len(rows))
        if self.keep:
            self.rows.extend(tuple(row[1:]) for row in rows)
        return len(rows)


def _run(
    fn: Any,
    parquet: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    flush: int,
    read_rows: int = 3,
    recorder: _Recorder | None = None,
) -> tuple[dict[str, Any], _Recorder]:
    recorder = recorder or _Recorder()
    monkeypatch.setattr(router, "_pg_bulk_insert_cost_rows", recorder)
    monkeypatch.setattr(router, "_INSERT_FLUSH_ROWS", flush)
    monkeypatch.setattr(router, "_PARQUET_READ_ROWS", read_rows)
    return fn(str(parquet), REGION, URL), recorder


@pytest.fixture
def hard_case(tmp_path: Path) -> Path:
    path = tmp_path / "hard_case.parquet"
    write_hard_case_parquet(path)
    return path


@pytest.mark.parametrize("flush", [1, 4, 1000])
@pytest.mark.parametrize("read_rows", [1, 2, 3, 7, 16, 1_000_000])
def test_the_stream_hands_over_what_the_whole_frame_did(
    hard_case: Path, monkeypatch: pytest.MonkeyPatch, read_rows: int, flush: int
) -> None:
    expected, before = _run(whole_frame_import, hard_case, monkeypatch, flush=flush)
    result, after = _run(router._process_and_insert_cwicr, hard_case, monkeypatch, flush=flush, read_rows=read_rows)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected


def test_the_fixture_reaches_every_hard_case(hard_case: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison above is only as good as what the oracle makes of this file."""
    import json

    result, recorded = _run(whole_frame_import, hard_case, monkeypatch, flush=1000)
    by_code: dict[str, list[tuple]] = {}
    for row in recorded.rows:
        by_code.setdefault(row[0], []).append(row)

    # A: unit from its second row, category from its second visit, the
    # resources of both visits, and the variant catalogue on the concrete slot.
    (a_row,) = by_code["A"]
    assert a_row[2] == "m3"
    assert json.loads(a_row[6])["category"] == "Structural"
    components = json.loads(a_row[8])
    assert [c["name"] for c in components] == ["Carpenter", "Concrete"]
    assert [v["label"] for v in components[1]["available_variants"]] == ["C20/25", "C25/30"]
    assert json.loads(a_row[12])["scope_of_work"] == ["Set up formwork.", "Pour and vibrate."]
    # B: its last visit's mortar and category.
    (b_row,) = by_code["B"]
    assert [c["name"] for c in json.loads(b_row[8])][-1] == "Mortar"
    assert json.loads(b_row[6])["category"] == "Masonry"
    # " D " and "D" both store as "D", and each gets the scope steps of both,
    # because scope steps are matched on the stripped code.
    d_rows = by_code["D"]
    assert len(d_rows) == 2
    assert all(json.loads(row[12])["scope_of_work"] == ["Spaced step.", "Plain step."] for row in d_rows)
    # The two long codes collide on their first 100 characters.
    assert len(by_code[LONG_A[:100]]) == 2
    # "H" and " H" are handed over by the first row of each raw code, with K
    # between them, not together.
    assert [row[0] for row in recorded.rows if row[0] in {"H", "K"}] == ["H", "K", "H"]
    # E is skipped, N is refused, the rows without a code are never stored.
    assert "E" not in by_code
    assert result["skipped"] == 1
    assert result["failed_codes"] == ["N"]
    # Orphan resources still count towards the components the base carries.
    stored_components = sum(len(json.loads(row[8])) for row in recorded.rows)
    assert result["resource_components"] > stored_components
    # Some resource codes are integers read as floats, so the integer column
    # reached the transform with a missing value in it.
    assert any(c["code"] == "200.0" for c in json.loads(by_code["F00"][0][8]))


def test_a_stream_that_ignores_items_spanning_batches_is_caught(
    hard_case: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: treat every row as a complete item and the comparison must fail."""
    import numpy as np

    expected, before = _run(whole_frame_import, hard_case, monkeypatch, flush=4)

    def _every_row_alone(parquet: Any, *_args: Any) -> Any:
        rows = np.arange(parquet.metadata.num_rows, dtype=np.int64)
        return rows, rows

    monkeypatch.setattr(router, "_cwicr_unit_ids", _every_row_alone)
    result, after = _run(router._process_and_insert_cwicr, hard_case, monkeypatch, flush=4, read_rows=3)

    assert after.rows != before.rows
    assert result != expected


def test_pandas_written_parquets_convert_the_same_in_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pandas metadata (a range index, a nullable integer column) survives batching."""
    import pandas as pd

    frame = pd.DataFrame(hard_case_rows())
    # Mostly missing, so most batches hold none of it; pandas metadata asks for
    # the nullable integer type, which the batches must keep rather than float.
    frame["price_abstract_resource_position_count"] = frame["price_abstract_resource_position_count"].astype("Int64")
    path = tmp_path / "pandas_written.parquet"
    frame.to_parquet(path, index=False)

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=5)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=5, read_rows=4)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected


def test_a_dictionary_encoded_column_reads_the_same_in_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stream decodes a dictionary column, whose categories would differ batch to batch.

    Read whole, pandas makes it a categorical; the transform only takes the
    first value per item and stringifies it, so the rows must not change.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    plain = tmp_path / "plain.parquet"
    write_hard_case_parquet(plain)
    table = pq.read_table(plain)
    index = table.schema.get_field_index("category_type")
    table = table.set_column(index, "category_type", table.column(index).dictionary_encode())
    assert pa.types.is_dictionary(table.schema.field("category_type").type)
    encoded = tmp_path / "encoded.parquet"
    pq.write_table(table, encoded)

    expected, before = _run(whole_frame_import, encoded, monkeypatch, flush=4)
    result, after = _run(router._process_and_insert_cwicr, encoded, monkeypatch, flush=4, read_rows=3)

    assert after.rows == before.rows
    assert result == expected


def test_an_empty_base_and_a_base_without_codes_report_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandas as pd

    empty = tmp_path / "empty.parquet"
    write_hard_case_parquet(empty, [])
    no_codes = tmp_path / "no_codes.parquet"
    pd.DataFrame({"rate_unit": ["m3"], "resource_name": ["Labour"]}).to_parquet(no_codes, index=False)

    for path in (empty, no_codes):
        expected, _ = _run(whole_frame_import, path, monkeypatch, flush=4)
        result, recorder = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=4)
        assert result == expected
        assert recorder.flushes == []


@pytest.mark.parametrize("failing_flush", [1, 3, 6])
def test_an_import_cut_off_mid_way_keeps_what_the_old_one_kept_and_resumes(
    hard_case: Path, monkeypatch: pytest.MonkeyPatch, failing_flush: int
) -> None:
    """Each flush commits on its own, so a cut-off import keeps the flushes before it.

    That is the promise the import makes, not all-or-nothing: a rerun goes
    through ``ON CONFLICT (code, region) DO NOTHING`` and adds what is missing.
    The stream must stop on exactly the rows the whole-frame import stopped on,
    and a rerun must end with the same rows as an import that never failed.
    """
    flush = 4
    old_partial = _Recorder(fail_on_call=failing_flush)
    with pytest.raises(psycopg2.OperationalError):
        _run(whole_frame_import, hard_case, monkeypatch, flush=flush, recorder=old_partial)
    new_partial = _Recorder(fail_on_call=failing_flush)
    with pytest.raises(psycopg2.OperationalError):
        _run(router._process_and_insert_cwicr, hard_case, monkeypatch, flush=flush, read_rows=3, recorder=new_partial)

    assert new_partial.rows == old_partial.rows
    assert new_partial.flushes == old_partial.flushes

    # Resume into the same table: what was committed stays, the rest is added,
    # and a code already present is not written again.
    table: dict[str, tuple] = {}
    for row in new_partial.rows:
        table.setdefault(row[0], row)
    committed = len(table)
    resumed, rerun = _run(router._process_and_insert_cwicr, hard_case, monkeypatch, flush=flush, read_rows=3)
    for row in rerun.rows:
        table.setdefault(row[0], row)

    clean: dict[str, tuple] = {}
    _, full = _run(whole_frame_import, hard_case, monkeypatch, flush=flush)
    for row in full.rows:
        clean.setdefault(row[0], row)
    assert table == clean
    assert len(table) > committed
    assert resumed["failed_codes"] == ["N"]


def _spy_on_frames(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the row count of every frame the stream hands to the transform."""
    sizes: list[int] = []
    transform = router._import_cwicr_codes

    def _spy(df: Any, db_id: str, tally: Any) -> None:
        sizes.append(len(df))
        transform(df, db_id, tally)

    monkeypatch.setattr(router, "_import_cwicr_codes", _spy)
    return sizes


def test_rows_without_a_code_do_not_hold_the_base_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A resource row with no rate code, every so often, must not chain the file into one set.

    Every missing code stringifies to the same word, so keyed by that word the
    rows without a code form one set whose last row is the last of them in the
    file. Nothing after its first row could be released before then, and the
    stream would hand the transform nearly the whole base as one frame, which
    is the peak it exists to avoid. They belong to no item, so each stands alone.
    """
    path = tmp_path / "orphans.parquet"
    total = write_orphan_scattered_parquet(path, 2000, 100)
    read_rows = 100

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=250)
    sizes = _spy_on_frames(monkeypatch)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=250, read_rows=read_rows)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected
    assert sum(sizes) == total
    # An item is two rows, so a frame is one read plus the item it spilled into.
    assert max(sizes) <= read_rows + 2, (max(sizes), total)


@pytest.mark.parametrize("read_rows", [1, 7, 100])
def test_an_item_coded_none_still_collects_the_rows_without_a_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_rows: int
) -> None:
    """Under pandas 2 the transform files a missing code's resources under the word ``None``.

    So there an item that is literally coded ``None`` gets every one of them as
    its own components, wherever in the file they sit. That is the old
    behaviour and the stream keeps it, which means those rows must travel with
    that item rather than alone. pandas 3 keeps a missing code missing through
    ``astype(str)``, so the whole frame files them under no item, and the
    stream has to agree with that instead.
    """
    import json

    path = tmp_path / "literal_none.parquet"
    write_orphan_scattered_parquet(path, 300, 40, literal_none_at=150)

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=64)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=64, read_rows=read_rows)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected
    (none_row,) = [row for row in before.rows if row[0] == "None"]
    names = [c["name"] for c in json.loads(none_row[8])]
    if _missing_code_stringifies():
        # The case is only a case if the orphans reach the item from both sides of it.
        assert "Orphan resource 0" in names
        assert "Orphan resource 280" in names
    else:
        assert names == ["Plain resource of 150"]


def _missing_code_stringifies() -> bool:
    """Whether a missing code reaches the transform's ``astype(str)`` as the word ``None``.

    Probed on the dtype the stream actually hands the transform, since that is
    what decides it: object strings under pandas 2, ``str`` under pandas 3.
    """
    import pyarrow as pa

    codes = router._cwicr_arrow_frame(pa.table({"rate_code": pa.array(["A", None])}), frozenset()).iloc[:, 0]
    return not codes.astype(str).isna().any()


@pytest.mark.parametrize(("read_rows", "flush"), [(7, 64), (20, 250), (50, 7)])
def test_items_that_come_back_far_down_do_not_hold_the_rows_between(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_rows: int, flush: int
) -> None:
    """A few items finished near the end of the file must not keep everything in between waiting.

    The AR and FR bases open about 600 items near row 158 000 and give each its
    last rows near row 726 000. Holding until then put 570 000 rows into one
    frame, about 4 GiB of the import on its own. Those late rows are read ahead
    instead, so the frames stay near one read, and the rows and flushes still
    match the whole frame.
    """
    path = tmp_path / "far_return.parquet"
    total = write_far_return_parquet(path, 1000, range(100, 130))

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=flush)
    sizes = _spy_on_frames(monkeypatch)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=flush, read_rows=read_rows)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected
    assert sum(sizes) == total
    # Held, the first frame after item 100 would carry the 1 800 rows up to the
    # late block. Read ahead, a frame is what was pending plus the late rows.
    assert max(sizes) <= 3 * read_rows + 2 * 30, (max(sizes), total)


@pytest.mark.parametrize("read_rows", [3, 7])
def test_far_rows_over_the_read_ahead_cap_are_held_and_still_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_rows: int
) -> None:
    """Past the cap the stream holds the rest as before, which is slower on memory but still exact."""
    path = tmp_path / "far_return_capped.parquet"
    write_far_return_parquet(path, 400, range(10, 60))
    monkeypatch.setattr(router, "_CWICR_FAR_ROWS_PER_READ", 2)

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=32)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=32, read_rows=read_rows)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected


def test_a_late_row_that_opens_a_raw_code_is_not_read_ahead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: when the late rows open a raw code of their own, moving them would reorder the output.

    ``" R000100"`` stores as ``R000100`` but first appears at the end of the
    file, so the whole frame hands its row over after every item in between.
    Read ahead, it would come right after ``R000100``. The rows have to stay in
    the stream, held with everything in between, and the output must match.
    """
    path = tmp_path / "far_return_variant.parquet"
    total = write_far_return_parquet(path, 300, range(100, 103), late_variant=True)

    expected, before = _run(whole_frame_import, path, monkeypatch, flush=16)
    sizes = _spy_on_frames(monkeypatch)
    result, after = _run(router._process_and_insert_cwicr, path, monkeypatch, flush=16, read_rows=7)

    assert after.rows == before.rows
    assert after.flushes == before.flushes
    assert result == expected
    # The case is only a case if the stream did hold the rows between.
    assert max(sizes) > 400, (max(sizes), total)


def test_the_copy_text_goes_over_in_bounded_buffers_that_add_up_to_one() -> None:
    """A flush of large rows is sent as several COPYs, together exactly the one CSV it used to be."""
    import csv
    import io

    big = "\\u0436" * 4000
    rows = [
        (
            f"id{i}",
            f"C{i}",
            'say "hi"\nnext line',
            "m3",
            "1.5",
            "RUB",
            "cwicr",
            "{}",
            "[]",
            big,
            "{}",
            i % 2,
            "RU",
            "{}",
        )
        for i in range(50)
    ]
    whole = io.StringIO()
    writer = csv.writer(whole, quoting=csv.QUOTE_ALL)
    for row in rows:
        out = list(row)
        out[11] = "true" if row[11] else "false"
        writer.writerow(out)

    buffers = [buf.read() for buf in router._cost_rows_as_csv(rows, max_chars=100_000)]

    assert "".join(buffers) == whole.getvalue()
    assert len(buffers) > 1
    # A buffer closes on the first row that takes it past the limit.
    assert max(len(b) for b in buffers) < 100_000 + 30_000
    assert list(router._cost_rows_as_csv([])) == []


def _peak_traced_bytes(fn: Any, parquet: Path, monkeypatch: pytest.MonkeyPatch, read_rows: int) -> int:
    recorder = _Recorder(keep=False)
    gc.collect()
    tracemalloc.start()
    try:
        _run(fn, parquet, monkeypatch, flush=500, read_rows=read_rows, recorder=recorder)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def test_the_memory_an_import_holds_does_not_grow_with_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Double the base and the streamed peak stays put, while the whole frame's doubles.

    ``tracemalloc`` sees the pandas and Python objects, which is where the
    import's memory went, and not the Arrow buffers below them. The bound is
    relative so it does not depend on the allocator or the platform.
    """
    small = tmp_path / "small.parquet"
    large = tmp_path / "large.parquet"
    write_synthetic_parquet(small, 1500)
    write_synthetic_parquet(large, 3000)
    # First calls import modules and fill caches; keep that out of the peaks.
    _peak_traced_bytes(router._process_and_insert_cwicr, small, monkeypatch, 500)
    _peak_traced_bytes(whole_frame_import, small, monkeypatch, 500)

    streamed_small = _peak_traced_bytes(router._process_and_insert_cwicr, small, monkeypatch, 500)
    streamed_large = _peak_traced_bytes(router._process_and_insert_cwicr, large, monkeypatch, 500)
    whole_small = _peak_traced_bytes(whole_frame_import, small, monkeypatch, 500)
    whole_large = _peak_traced_bytes(whole_frame_import, large, monkeypatch, 500)

    # The control: reading the whole frame grows with the base.
    assert whole_large > 1.6 * whole_small, (whole_small, whole_large)
    # The stream does not, and stays well under the whole frame.
    assert streamed_large < 1.25 * streamed_small, (streamed_small, streamed_large)
    assert streamed_large < 0.5 * whole_large, (streamed_large, whole_large)
