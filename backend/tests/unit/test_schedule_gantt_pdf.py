"""Printable Gantt PDF: rows, timescale, pagination and the drawn sheet.

Worked example used throughout: a small programme with a summary, two tasks
and a milestone, an approved baseline B1 whose dates are earlier than the live
plan, one task already started (actual start, 40 % progress) and on the
critical path. Pure: no database.
"""

from __future__ import annotations

import io
import string
from datetime import date

import pypdf
import pytest

from app.core.document_forms_i18n import form_strings, load_document_forms
from app.core.i18n import SUPPORTED_LOCALES
from app.modules.schedule import gantt_pdf
from app.modules.schedule.gantt_pdf import GanttMeta, build_rows, choose_scale, plan_sheets, render_gantt_pdf

SUMMARY = "00000000-0000-0000-0000-000000000001"
EXCAVATE = "00000000-0000-0000-0000-000000000002"
FOUNDATIONS = "00000000-0000-0000-0000-000000000003"
HANDOVER = "00000000-0000-0000-0000-000000000004"


def _activities() -> list[dict]:
    return [
        {
            "id": HANDOVER,
            "parent_id": None,
            "wbs_code": "2",
            "name": "Handover",
            "start_date": "2026-03-20",
            "end_date": "2026-03-20",
            "activity_type": "milestone",
            "sort_order": 2,
        },
        {
            "id": FOUNDATIONS,
            "parent_id": SUMMARY,
            "wbs_code": "1.2",
            "name": "Foundations",
            "start_date": "2026-02-02",
            "end_date": "2026-03-13",
            "progress_pct": "0",
            "sort_order": 2,
        },
        {
            "id": SUMMARY,
            "parent_id": None,
            "wbs_code": "1",
            "name": "Substructure",
            "start_date": "2026-01-05",
            "end_date": "2026-03-13",
            "activity_type": "summary",
            "sort_order": 1,
        },
        {
            "id": EXCAVATE,
            "parent_id": SUMMARY,
            "wbs_code": "1.1",
            "name": "Excavation",
            "start_date": "2026-01-05",
            "end_date": "2026-01-30",
            "actual_start": "2026-01-07",
            "progress_pct": "40",
            "is_critical": True,
            "sort_order": 1,
        },
    ]


BASELINE = {
    "activities": [
        {"id": EXCAVATE, "start_date": "2026-01-05", "end_date": "2026-01-23"},
        # Captured from an import with other ids: matched by WBS code instead.
        {"id": "imported-7", "wbs_code": "1.2", "start_date": "2026-01-26", "end_date": "2026-03-06"},
    ]
}


def test_rows_follow_the_outline_with_levels_and_types() -> None:
    rows = build_rows(_activities(), None)
    assert [r.wbs for r in rows] == ["1", "1.1", "1.2", "2"]
    assert [r.level for r in rows] == [0, 1, 1, 0]
    assert rows[0].summary and rows[3].milestone
    assert rows[1].critical and rows[1].progress == 40.0
    assert rows[1].actual_start == date(2026, 1, 7)
    assert rows[1].baseline_start is None


def test_baseline_dates_match_by_id_then_by_wbs_code() -> None:
    rows = {r.wbs: r for r in build_rows(_activities(), BASELINE)}
    assert (rows["1.1"].baseline_start, rows["1.1"].baseline_end) == (date(2026, 1, 5), date(2026, 1, 23))
    assert (rows["1.2"].baseline_start, rows["1.2"].baseline_end) == (date(2026, 1, 26), date(2026, 3, 6))
    assert rows["2"].baseline_start is None


def test_an_orphan_parent_or_a_cycle_does_not_lose_rows() -> None:
    acts = [
        {"id": "a", "parent_id": "b", "name": "A", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {"id": "b", "parent_id": "a", "name": "B", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        {"id": "c", "parent_id": "missing", "name": "C", "start_date": "2026-01-01", "end_date": "2026-01-02"},
    ]
    assert sorted(r.name for r in build_rows(acts, None)) == ["A", "B", "C"]


@pytest.mark.parametrize(
    ("span_days", "unit"),
    [(30, "day"), (100, "day"), (150, "week"), (500, "week"), (900, "month"), (3000, "quarter")],
)
def test_the_scale_is_the_finest_that_fits_two_sheets_wide(span_days: int, unit: str) -> None:
    assert choose_scale(span_days, 800.0).unit == unit


def test_sheets_cover_every_row_and_every_day_exactly_once() -> None:
    sheets = plan_sheets(
        row_count=95, rows_per_sheet=40, start=date(2026, 1, 1), end=date(2026, 12, 31), days_per_sheet=150
    )
    # 3 row bands x 3 time slices, row band first so a band's slices sit together.
    assert len(sheets) == 9
    assert [(s.row_start, s.row_end) for s in sheets[:3]] == [(0, 40)] * 3
    for band in (0, 40, 80):
        slices = [s for s in sheets if s.row_start == band]
        assert slices[0].day_start == date(2026, 1, 1)
        assert slices[-1].day_end == date(2026, 12, 31)
        for prev, nxt in zip(slices, slices[1:], strict=False):
            assert (nxt.day_start - prev.day_end).days == 1
    assert sheets[-1].row_end == 95


def test_an_empty_schedule_still_plans_one_sheet() -> None:
    sheets = plan_sheets(
        row_count=0, rows_per_sheet=40, start=date(2026, 1, 1), end=date(2026, 1, 1), days_per_sheet=30
    )
    assert len(sheets) == 1


def _meta(**kw: object) -> GanttMeta:
    values = {
        "project_name": "Riverside Clinic",
        "schedule_name": "Contract programme",
        "baseline_label": "B1",
        "exported_on": date(2026, 11, 17),
        "data_date": date(2026, 1, 20),
    }
    values.update(kw)
    return GanttMeta(**values)  # type: ignore[arg-type]


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_the_sheet_carries_header_legend_rows_and_landscape_a3() -> None:
    pdf = render_gantt_pdf(build_rows(_activities(), BASELINE), _meta(), paper="A3", locale="en")
    assert pdf.startswith(b"%PDF")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    box = reader.pages[0].mediabox
    assert float(box.width) > float(box.height)  # landscape
    assert round(float(box.width)) == 1191
    text = _text(pdf)
    for needle in ("Riverside Clinic", "Contract programme", "B1", "Excavation", "Handover", "2026-11-17"):
        assert needle in text, needle
    labels = form_strings("gantt_pdf")["en"]
    for key in ("legend_current", "legend_baseline", "legend_actual", "legend_critical", "legend_milestone"):
        assert labels[key] in text, key


def test_a_long_schedule_paginates_without_dropping_rows() -> None:
    acts = [
        {
            "id": f"id-{i}",
            "wbs_code": f"{i}",
            "name": f"Activity {i:03d}",
            "start_date": f"2026-{1 + i % 12:02d}-01",
            "end_date": f"2027-{1 + i % 12:02d}-10",
            "sort_order": i,
        }
        for i in range(120)
    ]
    pdf = render_gantt_pdf(build_rows(acts, None), _meta(baseline_label=None), paper="A4", locale="en")
    text = _text(pdf)
    assert len(pypdf.PdfReader(io.BytesIO(pdf)).pages) > 2
    for i in range(120):
        assert f"Activity {i:03d}" in text, i


def test_an_empty_schedule_prints_one_explained_sheet() -> None:
    pdf = render_gantt_pdf([], _meta(baseline_label=None), paper="A3", locale="en")
    assert len(pypdf.PdfReader(io.BytesIO(pdf)).pages) == 1
    assert form_strings("gantt_pdf")["en"]["no_activities"] in _text(pdf)


def test_german_labels_are_used_when_asked() -> None:
    pdf = render_gantt_pdf(build_rows(_activities(), BASELINE), _meta(), paper="A3", locale="de")
    assert form_strings("gantt_pdf")["de"]["legend_baseline"] in _text(pdf)


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


def test_every_language_translates_a_subset_with_the_same_placeholders() -> None:
    english = load_document_forms("en")["gantt_pdf"]["strings"]
    for code in SUPPORTED_LOCALES:
        own = (load_document_forms(code).get("gantt_pdf") or {}).get("strings", {})
        assert set(own) <= set(english), code
        for key, text in own.items():
            assert text, (code, key)
            assert _placeholders(text) == _placeholders(english[key]), (code, key)


def test_supported_locales_include_the_translated_ones() -> None:
    assert {"en", "de", "ru", "zh", "ar"} <= set(gantt_pdf.pdf_locales())


@pytest.mark.parametrize("locale", ["ar", "fa", "he", "hi", "th", "ja", "zh", "ko", "el", "kk"])
def test_every_script_draws_with_a_glyph_for_each_character(locale: str) -> None:
    from tests.unit.test_registers_set_mixed_scripts_in_runs import _missing_glyphs

    pdf = render_gantt_pdf(build_rows(_activities(), BASELINE), _meta(), paper="A3", locale=locale)
    assert _missing_glyphs(pdf) == []
