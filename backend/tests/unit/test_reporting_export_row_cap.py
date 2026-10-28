# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Defensive row cap on the reporting export entry point.

``export_report`` builds the CSV / XLSX / PDF download entirely in memory (the
XLSX writer holds a cell object per value), so a report whose snapshot carries a
runaway row count - a project with a very large BoQ or incident log - could push
the single worker into swap while assembling the file. These tests pin the
front-door guard: an oversized snapshot is turned away with a clear error before
any writer runs, while a normal snapshot still exports byte-for-byte as before
and the html path is left ungated.

Pure unit tests: no DB, no app boot. ``exporters`` imports cleanly on its own.
"""

from __future__ import annotations

import pytest

from app.modules.reporting import exporters
from app.modules.reporting.exporters import (
    ExportFormatError,
    _snapshot_row_count,
    export_report,
)

_META = {
    "report_type": "summary",
    "title": "Quarterly cost report",
    "project_name": "Demo project",
    "currency": "EUR",
    "generated_at": "2026-07-13T00:00:00Z",
    "template_data": None,
}


# ── row counter ───────────────────────────────────────────────────────────


def test_row_count_ignores_non_dict_snapshot() -> None:
    assert _snapshot_row_count(None) == 0
    assert _snapshot_row_count([1, 2, 3]) == 0  # type: ignore[arg-type]


def test_row_count_sums_every_section_shape() -> None:
    snapshot = {
        "breakdown": [{"trade": "a"}, {"trade": "b"}, {"trade": "c"}],  # record list -> 3
        "totals": {"net": "1", "vat": "2", "gross": "3"},  # dict -> 3
        "notes": ["one", "two"],  # scalar list -> 2
        "headline": "single value",  # scalar -> 1
    }
    assert _snapshot_row_count(snapshot) == 9


def test_row_count_skips_empty_sections() -> None:
    snapshot = {"a": None, "b": {}, "c": [], "d": {"only": "row"}}
    assert _snapshot_row_count(snapshot) == 1


# ── guard on the file builders ─────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
def test_oversized_snapshot_rejected(monkeypatch: pytest.MonkeyPatch, fmt: str) -> None:
    monkeypatch.setattr(exporters, "_MAX_EXPORT_ROWS", 3)
    snapshot = {"breakdown": [{"trade": str(i)} for i in range(10)]}  # 10 rows > cap 3
    with pytest.raises(ExportFormatError) as exc:
        export_report(fmt=fmt, data_snapshot=snapshot, **_META)
    # The message must name the offending count and the limit so the caller
    # knows to narrow scope rather than see an opaque failure.
    assert "10" in str(exc.value)
    assert "3" in str(exc.value)


def test_snapshot_at_cap_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exporters, "_MAX_EXPORT_ROWS", 3)
    snapshot = {"breakdown": [{"trade": str(i)} for i in range(3)]}  # exactly at cap
    _fn, media, blob = export_report(fmt="csv", data_snapshot=snapshot, **_META)
    assert media.startswith("text/csv")
    assert isinstance(blob, bytes) and blob


def test_normal_snapshot_still_exports_csv() -> None:
    snapshot = {"summary": {"total_cost": "1234.56 EUR", "positions": 12}}
    filename, media, blob = export_report(fmt="csv", data_snapshot=snapshot, **_META)
    assert filename.endswith(".csv")
    assert media.startswith("text/csv")
    assert b"1234.56 EUR" in blob


def test_normal_snapshot_still_exports_xlsx() -> None:
    pytest.importorskip("openpyxl")
    snapshot = {"summary": {"total_cost": "1234.56 EUR", "positions": 12}}
    _fn, media, blob = export_report(fmt="xlsx", data_snapshot=snapshot, **_META)
    assert "spreadsheetml" in media
    assert isinstance(blob, bytes) and blob[:2] == b"PK"  # a real .xlsx zip


def test_html_export_is_not_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    # The html path serves a pre-rendered / streamed body and must not be
    # blocked by the file-builder row cap even when the snapshot is huge.
    monkeypatch.setattr(exporters, "_MAX_EXPORT_ROWS", 1)
    snapshot = {"breakdown": [{"trade": str(i)} for i in range(50)]}
    _fn, media, blob = export_report(fmt="html", data_snapshot=snapshot, html_body="<p>ok</p>", **_META)
    assert media.startswith("text/html")
    assert blob == b"<p>ok</p>"
