# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Which classification code sits under which, for the two shapes every standard has."""

from __future__ import annotations

import pytest

from app.modules.economics.classification import covers, most_specific, normalise, overlaps, truncate


@pytest.mark.parametrize(
    "frame,code,expected",
    [
        ("300", "331", True),
        ("300", "300", True),
        ("330", "331", True),
        ("330", "341", False),
        ("331", "330", False),
        ("300", "400", False),
        ("2.6", "2.6.1", True),
        ("2.6", "2.60", False),
        ("2.6", "2.6", True),
        ("2.06", "2.6.1", True),
        ("03 30 00", "03 31 13", True),
        ("03 30 00", "04 20 00", False),
        ("000", "123", True),
        ("A1", "A12", True),
        ("300", "", False),
        ("", "300", False),
    ],
)
def test_covers(frame: str, code: str, expected: bool) -> None:
    assert covers(frame, code) is expected


def test_overlap_goes_both_ways() -> None:
    assert overlaps("300", "330") and overlaps("330", "300")
    assert not overlaps("330", "340")


def test_most_specific_picks_the_deepest_covering_line() -> None:
    assert most_specific(["300", "330", "340"], "331") == "330"
    assert most_specific(["300", "330"], "351") == "300"
    assert most_specific(["300"], "500") is None
    assert most_specific(["2", "2.6"], "2.6.1") == "2.6"


@pytest.mark.parametrize(
    "code,depth,expected",
    [
        ("331", 1, "300"),
        ("331", 2, "330"),
        ("331", 3, "331"),
        ("2.6.1", 2, "2.6"),
        ("33", 5, "33"),
        ("03 30 00", 2, "030000"),
    ],
)
def test_truncate(code: str, depth: int, expected: str) -> None:
    assert truncate(code, depth) == expected


def test_normalise_removes_spaces_and_dashes() -> None:
    assert normalise(" 03 30-00 ") == "033000"
    assert normalise(None) == ""
