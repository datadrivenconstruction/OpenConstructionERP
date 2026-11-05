"""A sheet is read for what it says it is, in the languages drawings are titled in."""

from __future__ import annotations

import pytest

from app.modules.takeoff import sheet_type as st

PAGE = (2384.0, 1684.0)


def _line(text: str, x: float, y: float, height: float = 10.0) -> list[tuple[float, float, float, float, str]]:
    out = []
    for word in text.split():
        w = 0.6 * height * len(word)
        out.append((x, y, x + w, y + height, word))
        x += w + 0.4 * height
    return out


def _sheet(title: str, *, body: tuple[str, ...] = ()) -> list[tuple[float, float, float, float, str]]:
    words = _line(title, 1900.0, 1400.0, 14.0)
    for i, text in enumerate(body):
        words += _line(text, 200.0, 200.0 + 30.0 * i, 8.0)
    for i in range(30):
        words += _line(str(1000 + i), 300.0 + 40.0 * i, 900.0, 8.0)
    return words


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("GROUND FLOOR PLAN", st.PLAN),
        ("TYPICAL FLOOR PLAN LEVELS 2-5", st.PLAN),
        ("Grundriss Erdgeschoss", st.PLAN),
        ("Plan du rez-de-chaussée", st.PLAN),
        ("Planta baja", st.PLAN),
        ("План 1 этажа", st.PLAN),
        ("Rzut parteru", st.PLAN),
        ("一层平面图", st.PLAN),
        ("ELEVATIONS", st.ELEVATION),
        ("Ansicht Nord", st.ELEVATION),
        ("Фасад 1-8", st.ELEVATION),
        ("Section A-A", st.SECTION),
        ("Schnitt B-B", st.SECTION),
        ("Разрез 1-1", st.SECTION),
        ("DOOR AND WINDOW SCHEDULES", st.SCHEDULE),
        ("Ведомость отделки помещений", st.SCHEDULE),
        ("Wall details", st.DETAIL),
        ("Узлы", st.DETAIL),
        ("FOUNDATION PLAN", st.STRUCTURAL),
        ("ROOF PLAN", st.STRUCTURAL),
        ("План фундаментов", st.STRUCTURAL),
        ("SITE PLAN", st.SITE),
        ("Lageplan", st.SITE),
        ("COVER SHEET", st.COVER),
    ],
)
def test_the_title_says_what_the_sheet_is(title: str, kind: str) -> None:
    assert st.classify(_sheet(title), *PAGE).kind == kind


def test_a_reference_in_a_note_does_not_outvote_the_title() -> None:
    words = _sheet("GROUND FLOOR PLAN", body=("SEE SECTION A-A", "REFER TO ELEVATIONS", "KEY PLAN"))
    assert st.classify(words, *PAGE).kind == st.PLAN


def test_a_key_plan_does_not_make_an_elevation_a_plan() -> None:
    assert st.classify(_sheet("SOUTH ELEVATION", body=("KEY PLAN",)), *PAGE).kind == st.ELEVATION


def test_a_line_of_prose_is_not_a_title() -> None:
    words = _line("Contractor shall check every section of the wall against the plan before any work starts", 200, 200)
    assert st.classify(words, *PAGE).kind == st.UNKNOWN


def test_a_word_inside_another_word_does_not_count() -> None:
    assert st.classify(_line("Explanation", 200, 200), *PAGE).kind == st.UNKNOWN
    assert st.classify(_line("Bisection", 200, 200), *PAGE).kind == st.UNKNOWN


def test_a_page_with_no_words_is_unknown() -> None:
    assert st.classify([], *PAGE).kind == st.UNKNOWN


def test_what_stands_under_a_title_label_wins() -> None:
    words = _line("Drawing title", 1900.0, 1400.0, 8.0) + _line("Elevations", 1900.0, 1412.0, 8.0)
    words += _line("Plan", 300.0, 300.0, 8.0)
    assert st.classify(words, *PAGE).kind == st.ELEVATION
