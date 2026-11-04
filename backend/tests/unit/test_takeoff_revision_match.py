"""Pure sheet matching and geometry alignment behind the carry-over preview."""

from __future__ import annotations

import pytest

from app.modules.takeoff import revision_match as rm


def _meta(*rows: tuple[int, str | None, str | None]) -> list[dict]:
    return [{"page": p, "number": n, "title": t} for p, n, t in rows]


def _by_old(matches: list[rm.PageMatch]) -> dict[int, rm.PageMatch]:
    return {m.old: m for m in matches}


def test_identity_by_sheet_number() -> None:
    old = _meta((1, "A-101", "Plan"), (2, "A-102", "Section"))
    got = _by_old(rm.match_pages(old, old))
    assert (got[1].new, got[1].score, got[1].method) == (1, 1.0, "title")
    assert got[2].new == 2


def test_inserted_sheet_follows_the_number_not_the_position() -> None:
    old = _meta((1, "A-101", None), (2, "A-102", None))
    new = _meta((1, "A-100", None), (2, "A-101", None), (3, "A-102", None))
    got = _by_old(rm.match_pages(old, new))
    assert (got[1].new, got[2].new) == (2, 3)


def test_missing_sheet_is_not_paired_by_position() -> None:
    old = _meta((1, "A-101", None), (2, "A-102", None))
    new = _meta((1, "A-101", None), (2, "A-103", None))
    got = _by_old(rm.match_pages(old, new))
    assert got[1].new == 1
    assert got[2].new is None


def test_near_title_matches_below_a_number_match() -> None:
    got = _by_old(rm.match_pages(_meta((1, None, "Ground floor plan")), _meta((4, None, "Ground floor plan."))))
    assert got[1].new == 4 and 0.85 <= got[1].score <= 0.9


def test_no_identity_falls_back_to_index() -> None:
    same = _by_old(rm.match_pages(_meta((1, None, None), (2, None, None)), _meta((1, None, None), (2, None, None))))
    assert (same[2].new, same[2].method, same[2].score) == (2, "index", 0.7)
    diff = _by_old(rm.match_pages(_meta((1, None, None)), _meta((1, None, None), (2, None, None))))
    assert diff[1].score == 0.5


def test_manual_page_map_wins() -> None:
    old = _meta((1, "A-101", None))
    new = _meta((1, "A-101", None), (2, "A-999", None))
    got = _by_old(rm.match_pages(old, new, {1: 2}))
    assert (got[1].new, got[1].method, got[1].score) == (2, "manual", 1.0)


def test_pure_shift() -> None:
    t = rm.estimate_transform([(0, 0), (100, 0)], [(10, 20), (110, 20)])
    assert t.ok and t.scale == pytest.approx(1.0) and (t.dx, t.dy) == (pytest.approx(10), pytest.approx(20))
    assert t.residual == pytest.approx(0, abs=1e-9)
    assert rm.apply_transform([{"x": 5, "y": 5}], t) == [{"x": 15.0, "y": 25.0}]


def test_half_percent_scale() -> None:
    t = rm.estimate_transform([(0, 0), (1000, 0), (0, 1000)], [(0, 0), (1005, 0), (0, 1005)])
    assert t.scale == pytest.approx(1.005)


def test_fewer_than_two_anchors_is_not_ok() -> None:
    assert not rm.estimate_transform([(1, 1)], [(2, 2)]).ok
    assert not rm.estimate_transform([(1, 1), (1, 1)], [(2, 2), (3, 3)]).ok
    assert not rm.estimate_transform([], []).ok


def test_confidence_falls_with_residual_and_unaligned_never_high() -> None:
    values = [
        rm.confidence(1.0, rm.Transform(residual=r, ok=True), 1000.0, "same") for r in (0.0, 2.0, 5.0, 10.0, 20.0)
    ]
    assert values == sorted(values, reverse=True) and values[0] == 1.0 and values[-1] == 0.0
    unaligned = rm.confidence(1.0, rm.Transform(), None, "same")
    assert rm.band(unaligned) == rm.BAND_REVIEW


def test_bands() -> None:
    assert (rm.band(0.85), rm.band(0.84), rm.band(0.6), rm.band(0.59)) == ("high", "review", "review", "remeasure")
