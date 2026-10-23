"""Regexes fed with request or document text stay linear on long whitespace runs."""

from __future__ import annotations

import time

import pytest

from app.core.demo_read_only import classify_statement
from app.modules.documents import sheet_fields

_BUDGET_SECONDS = 1.0


def _timed(func, *args) -> object:
    started = time.perf_counter()
    result = func(*args)
    assert time.perf_counter() - started < _BUDGET_SECONDS
    return result


def test_demo_read_only_classifier_on_long_whitespace() -> None:
    assert _timed(classify_statement, " " * 200_000 + "!") is None
    assert _timed(classify_statement, "\n  -- note\n  DELETE FROM boq_positions")[0] == "DELETE"


@pytest.mark.parametrize(
    ("pattern", "head", "pad", "tail"),
    [
        ("_FIELD_LABEL_BREAK", "a", "\t", ""),
        ("_NUMBER_LABEL", "dwg", "\t", ""),
        ("_DATE", "date", "\t", ""),
        ("_LEADING_ZEROS", "", "0", "x"),
    ],
    ids=["field-break", "number-label", "date", "leading-zeros"],
)
def test_sheet_field_patterns_on_long_padding(pattern: str, head: str, pad: str, tail: str) -> None:
    regex = getattr(sheet_fields, pattern)
    text = head + pad * 50_000 + tail
    _timed(lambda: list(regex.finditer(text)))


def test_sheet_field_patterns_still_read_labels() -> None:
    assert sheet_fields._NUMBER_LABEL.search("DWG NO.: A-101").group("value") == "A-101"
    assert sheet_fields._DATE.search("Datum : 12.03.2024").group("a") == "12"
    assert sheet_fields._FIELD_LABEL_BREAK.search("Title  Scale: 1").start() == 5
