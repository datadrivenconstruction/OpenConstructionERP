"""Validation rules of the progress sheet and the imported-source check, plus import-source helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.modules.schedule.validators  # noqa: F401  (registers the rules)
from app.core.validation.engine import validation_engine
from app.modules.schedule.import_source import deviation_days, source_id_of, stable_export_uids
from app.modules.schedule.validators import PROGRESS_SHEET_RULE_SET


def _row(**kw):
    base = {
        "row_number": 2,
        "activity_id": "a-1",
        "activity_ref": "A1",
        "duplicate": False,
        "parse_errors": [],
        "percent_complete": 40.0,
        "remaining_duration": None,
        "actual_start": "2026-05-05",
        "actual_finish": None,
        "recorded_actual_start": None,
        "recorded_actual_finish": None,
        "current_percent": 20.0,
        "stale": False,
        "status_date": "2026-05-20",
    }
    return {**base, **kw}


def _codes(rows, locale: str = "en") -> dict[int, set[str]]:
    report = asyncio.run(
        validation_engine.validate(
            data={"rows": rows}, rule_sets=[PROGRESS_SHEET_RULE_SET], metadata={"locale": locale}
        )
    )
    out: dict[int, set[str]] = {}
    for r in report.results:
        if not r.passed:
            out.setdefault(int(r.element_ref), set()).add(r.details["code"])
    return out


def test_a_clean_row_passes_every_rule() -> None:
    assert _codes([_row()]) == {}


def test_unknown_and_duplicate_rows() -> None:
    codes = _codes([_row(activity_id=None), _row(row_number=3, duplicate=True)])
    assert codes[2] == {"fail"}
    assert codes[3] == {"duplicate"}


def test_values_out_of_range_and_parse_errors() -> None:
    codes = _codes([_row(percent_complete=150.0, remaining_duration=-1, parse_errors=["actual_start_not_a_date"])])
    assert {"percent_out_of_range", "remaining_negative", "actual_start_not_a_date"} <= codes[2]


def test_date_logic() -> None:
    codes = _codes(
        [
            _row(actual_start="2026-05-10", actual_finish="2026-05-08", percent_complete=100.0),
            _row(row_number=3, actual_start="2026-06-01"),
            _row(row_number=4, actual_finish="2026-05-12", percent_complete=80.0),
            _row(row_number=5, actual_start=None, actual_finish="2026-05-12", percent_complete=100.0),
        ]
    )
    assert "finish_before_start" in codes[2]
    assert "after_status_date" in codes[3]
    assert "finish_needs_complete" in codes[4]
    assert "finish_without_start" in codes[5]


def test_recorded_actual_start_satisfies_the_finish() -> None:
    codes = _codes(
        [
            _row(
                actual_start=None,
                recorded_actual_start="2026-05-04",
                actual_finish="2026-05-12",
                percent_complete=100.0,
            )
        ]
    )
    assert "finish_without_start" not in codes.get(2, set())


def test_stale_and_plausibility_are_warnings() -> None:
    report = asyncio.run(
        validation_engine.validate(
            data={"rows": [_row(stale=True, percent_complete=10.0, actual_start=None)]},
            rule_sets=[PROGRESS_SHEET_RULE_SET],
        )
    )
    failed = [r for r in report.results if not r.passed]
    codes = {r.details["code"] for r in failed}
    assert {"fail", "progress_decreased", "started_without_start"} <= codes
    assert all(str(r.severity.value) == "warning" for r in failed)


def test_messages_are_translated() -> None:
    report = asyncio.run(
        validation_engine.validate(
            data={"rows": [_row(activity_id=None, activity_ref="X9")]},
            rule_sets=[PROGRESS_SHEET_RULE_SET],
            metadata={"locale": "en"},
        )
    )
    message = next(r.message for r in report.results if not r.passed)
    assert "X9" in message and "{" not in message


def test_dates_match_source_rule() -> None:
    payload = {
        "activities": [
            {"id": "a", "name": "Moved", "end_date": "2026-05-20", "source_dates": {"finish": "2026-05-15"}},
            {
                "id": "b",
                "name": "Kept",
                "end_date": "2026-05-15",
                "metadata": {"source_dates": {"finish": "2026-05-15"}},
            },
            {"id": "c", "name": "Native", "end_date": "2026-05-15"},
        ]
    }
    report = asyncio.run(validation_engine.validate(data=payload, rule_sets=["schedule_quality"]))
    mine = [r for r in report.results if r.rule_id == "schedule_quality.dates_match_source"]
    assert {r.element_ref: r.passed for r in mine} == {"a": False, "b": True}
    accepted = asyncio.run(
        validation_engine.validate(data={**payload, "import_source_status": "accepted"}, rule_sets=["schedule_quality"])
    )
    assert not [r for r in accepted.results if r.rule_id == "schedule_quality.dates_match_source"]


def test_stable_export_uids_keep_source_ids() -> None:
    acts = [
        SimpleNamespace(id="x", metadata_={"msp_uid": "10"}),
        SimpleNamespace(id="y", metadata_={"xer_task_id": "4711"}),
        SimpleNamespace(id="z", metadata_={}),
        SimpleNamespace(id="w", metadata_={"msp_uid": "10"}),
    ]
    uids = stable_export_uids(acts)
    assert uids["x"] == 10
    assert uids["y"] == 4711
    assert uids["z"] == 4712
    assert uids["w"] == 4713
    assert len(set(uids.values())) == 4


def test_deviation_and_source_id_helpers() -> None:
    assert deviation_days("2026-05-15", "2026-05-20") == 5
    assert deviation_days("2026-05-15", None) is None
    assert source_id_of({"xer_task_id": "77"}) == "77"
    assert source_id_of({"msp_uid": "3", "xer_task_id": "77"}) == "3"
    assert source_id_of(None) is None
