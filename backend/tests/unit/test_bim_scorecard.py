"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠BIM quality scorecard - pure facet, composite, and trend tests (DB-free).

Feeds synthetic element sets (dicts and namespaces) into the pure facet and
scorecard functions and synthetic prior-report rows into the trend assembler.
No database, no async - every function under test is a pure library function.

Coverage:
    * grade banding across every band + None
    * discipline coverage: full vs missing, explicit tag vs type inference,
      custom expected set, empty model
    * property completeness: all-pass 1.0, blocking-error cap (shared formula),
      empty / no-rule-match not-applicable, element drill-down
    * naming rigor: threshold share, placeholders, missing identifier, dicts
    * information consistency: consistent vs peer-inconsistent, not-assessable
    * composite: weighted average, not-applicable facet renormalisation,
      status banding, element-level drill-down merge, empty model divide-by-zero
    * trend: ascending / descending / flat / insufficient, out-of-order dates,
      score coercion, run numbering, per-point grade, element_count passthrough
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.engine import SEVERITY_WEIGHTS, compute_quality_score
from app.modules.validation.bim_scorecard import (
    FACET_INFORMATION_CONSISTENCY,
    FACET_NAMING_RIGOR,
    FACET_ORDER,
    FACET_PROPERTY_COMPLETENESS,
    assemble_score_trend,
    build_bim_scorecard,
    classify_discipline,
    coerce_score,
    discipline_coverage_facet,
    grade_for_score,
    information_consistency_facet,
    is_well_formed_name,
    naming_rigor_facet,
    property_completeness_facet,
)


def ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def rep(**kw: Any) -> SimpleNamespace:
    """Synthetic ValidationReport-like row for the trend assembler."""
    base: dict[str, Any] = {
        "id": None,
        "score": None,
        "status": "",
        "created_at": None,
        "rule_set": "bim_universal",
        "metadata_": {},
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _clean_wall(i: int) -> SimpleNamespace:
    """A wall passing every applicable universal rule.

    Carries thickness, fire rating, storey, name AND (for the expanded rule set)
    a material, a classification code, a type/family name and a phase, so it
    passes the per-category required-property, classification-presence,
    type-name and phase checks too.
    """
    return ns(
        id=f"w{i}",
        stable_id=f"w{i}",
        element_type="wall",
        name=f"Wall {i}",
        storey="L1",
        discipline=None,
        properties={
            "fire_rating": "F90",
            "material": "concrete_c30_37",
            "classification": {"din276": "331"},
            "type_name": "WA-C30-200",
            "phase": "New Construction",
        },
        quantities={"thickness_m": 0.24},
    )


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, 12, 0, 0, tzinfo=UTC)


# --- Grade banding ---------------------------------------------------------


class TestGradeBanding:
    @pytest.mark.parametrize(
        ("score", "grade"),
        [
            (None, "N/A"),
            (1.0, "A"),
            (0.90, "A"),
            (0.89, "B"),
            (0.75, "B"),
            (0.74, "C"),
            (0.60, "C"),
            (0.59, "D"),
            (0.40, "D"),
            (0.39, "F"),
            (0.0, "F"),
        ],
    )
    def test_bands(self, score: float | None, grade: str) -> None:
        assert grade_for_score(score) == grade


# --- Discipline coverage ---------------------------------------------------


class TestDisciplineCoverage:
    def test_full_coverage_via_tag(self) -> None:
        els = [ns(discipline=d) for d in ("architectural", "structural", "mechanical", "electrical", "plumbing")]
        facet = discipline_coverage_facet(els)
        assert facet.applicable is True
        assert facet.score == 1.0
        assert facet.covered == 5
        assert facet.total == 5
        assert facet.details["missing"] == []

    def test_missing_disciplines(self) -> None:
        els = [ns(discipline="architectural"), ns(discipline="structural")]
        facet = discipline_coverage_facet(els)
        assert facet.score == pytest.approx(0.4)
        assert facet.covered == 2
        assert set(facet.details["missing"]) == {"mechanical", "electrical", "plumbing"}

    def test_coverage_via_element_type_inference(self) -> None:
        els = [
            ns(element_type="Wall"),
            ns(element_type="Column"),
            ns(element_type="Duct"),
            ns(element_type="Conduit"),
            ns(element_type="Pipe"),
        ]
        facet = discipline_coverage_facet(els)
        assert facet.score == 1.0
        assert facet.details["missing"] == []

    def test_ifc_prefix_stripped(self) -> None:
        assert classify_discipline(ns(element_type="IfcWallStandardCase")) == "architectural"
        assert classify_discipline(ns(element_type="IfcPile")) == "structural"
        assert classify_discipline(ns(discipline="HVAC")) == "mechanical"
        assert classify_discipline(ns(element_type="Mystery")) is None

    def test_custom_expected_set(self) -> None:
        facet = discipline_coverage_facet(
            [ns(discipline="architectural")],
            expected=["architectural", "structural"],
        )
        assert facet.score == 0.5
        assert facet.total == 2

    def test_empty_model_not_applicable(self) -> None:
        facet = discipline_coverage_facet([])
        assert facet.applicable is False
        assert facet.score is None


# --- Property completeness -------------------------------------------------


class TestPropertyCompleteness:
    def test_all_pass_is_one(self) -> None:
        facet = property_completeness_facet([_clean_wall(i) for i in range(3)])
        assert facet.applicable is True
        assert facet.score == 1.0
        assert facet.details["error_findings"] == 0
        assert facet.details["checks_failed"] == 0
        assert facet.element_refs == []

    def test_blocking_error_caps_score(self) -> None:
        # 7 clean walls + 1 wall failing only the thickness ERROR rule (it also
        # carries a type name and phase so it fails nothing but thickness).
        # 111.4/114.4 weighted would be ~0.97; a single error caps it to 0.25,
        # matching the shared compute_quality_score contract (E-XMOD-015 / E-VAL-007).
        bad = ns(
            id="bad",
            stable_id="bad",
            element_type="wall",
            name="Wall X",
            storey="L1",
            properties={
                "fire_rating": "F90",
                "material": "concrete_c30_37",
                "classification": {"din276": "331"},
                "type_name": "WA-C30-200",
                "phase": "New Construction",
            },
            quantities={"thickness_m": 0},
        )
        els = [_clean_wall(i) for i in range(7)]
        els.append(bad)
        facet = property_completeness_facet(els)
        assert facet.details["error_findings"] == 1
        assert facet.score == 0.25
        assert facet.score == compute_quality_score(111.4, 114.4, 1)
        assert facet.element_refs == ["bad"]

    def test_all_error_walls_score_floored_by_error_cap(self) -> None:
        # Walls that fail every property check. The thickness ERROR fails on each,
        # so with three blocking errors the shared contract floors the score at
        # the error cap 0.5 / (1 + 3) = 0.125 (the non-negative-quantity ERROR
        # passes vacuously on empty quantities, so this is not a literal zero).
        els = [
            ns(
                id=f"b{i}",
                stable_id=f"b{i}",
                element_type="wall",
                name="None",
                storey=None,
                properties={},
                quantities={},
            )
            for i in range(3)
        ]
        facet = property_completeness_facet(els)
        assert facet.score == 0.125
        assert facet.details["error_findings"] == 3
        assert len(facet.element_refs) == 3

    def test_uses_shared_severity_weights(self) -> None:
        # A single clean wall: 2 error-checks + 5 warning-checks + 2 info-checks,
        # all passing (thickness and non-negative-quantity = error; fire, storey,
        # name, category-required-property and classification-presence = warning;
        # type/family name and phase = info).
        facet = property_completeness_facet([_clean_wall(0)])
        expected_weight = 2 * SEVERITY_WEIGHTS["error"] + 5 * SEVERITY_WEIGHTS["warning"] + 2 * SEVERITY_WEIGHTS["info"]
        assert facet.details["total_weight"] == pytest.approx(expected_weight)
        assert facet.details["passed_weight"] == pytest.approx(expected_weight)

    def test_empty_model_not_applicable(self) -> None:
        facet = property_completeness_facet([])
        assert facet.applicable is False
        assert facet.score is None


# --- Naming rigor ----------------------------------------------------------


class TestNamingRigor:
    def test_threshold_share(self) -> None:
        els = [
            ns(id="1", name="Wall A"),
            ns(id="2", name="Beam B"),
            ns(id="3", name="Col C"),
            ns(id="4", name="None"),
        ]
        facet = naming_rigor_facet(els)
        assert facet.score == 0.75
        assert facet.covered == 3
        assert facet.total == 4
        assert "4" in facet.element_refs

    @pytest.mark.parametrize("bad", ["", "None", "N/A", "x", "  ", None, "unnamed"])
    def test_placeholder_names_rejected(self, bad: Any) -> None:
        assert is_well_formed_name(bad) is False

    @pytest.mark.parametrize("good", ["Wall", "W1", "Door-01", "Раздел 3"])
    def test_real_names_accepted(self, good: str) -> None:
        assert is_well_formed_name(good) is True

    def test_missing_identifier_fails(self) -> None:
        facet = naming_rigor_facet([ns(name="Wall A")])
        assert facet.covered == 0
        assert facet.score == 0.0

    def test_dict_elements(self) -> None:
        facet = naming_rigor_facet([{"id": "d1", "name": "Wall"}, {"id": "d2", "name": ""}])
        assert facet.total == 2
        assert facet.covered == 1

    def test_empty_model_not_applicable(self) -> None:
        facet = naming_rigor_facet([])
        assert facet.applicable is False


# --- Information consistency ------------------------------------------------


class TestInformationConsistency:
    def test_consistent_peers(self) -> None:
        els = [ns(id=f"w{i}", element_type="wall", properties={"a": 1, "b": 2, "c": 3}) for i in range(4)]
        facet = information_consistency_facet(els)
        assert facet.applicable is True
        assert facet.score == 1.0
        assert facet.details["flagged_elements"] == 0

    def test_peer_inconsistent_element_flagged(self) -> None:
        els = [ns(id=f"w{i}", element_type="wall", properties={"a": 1, "b": 2, "c": 3}) for i in range(3)]
        els.append(ns(id="w3", element_type="wall", properties={}))
        facet = information_consistency_facet(els)
        assert facet.score == pytest.approx(0.75)
        assert facet.details["flagged_elements"] == 1
        assert "w3" in facet.element_refs

    def test_not_assessable_when_categories_too_small(self) -> None:
        els = [
            ns(id="1", element_type="wall", properties={"a": 1}),
            ns(id="2", element_type="door", properties={"b": 2}),
        ]
        facet = information_consistency_facet(els)
        assert facet.applicable is False
        assert facet.score is None

    def test_empty_model_not_applicable(self) -> None:
        assert information_consistency_facet([]).applicable is False


# --- Composite scorecard ---------------------------------------------------


class TestBuildScorecard:
    def test_overall_is_weighted_average_of_applicable_facets(self) -> None:
        els = [_clean_wall(i) for i in range(4)]
        sc = build_bim_scorecard(els)
        applicable = [f for f in sc.facets if f.applicable and f.score is not None]
        denom = sum(f.weight for f in applicable)
        expected = round(sum(f.score * f.weight for f in applicable) / denom, 4)
        assert sc.overall_score == expected
        assert sc.overall_grade == grade_for_score(sc.overall_score)

    def test_four_clean_walls_grade_and_status(self) -> None:
        sc = build_bim_scorecard([_clean_wall(i) for i in range(4)])
        # prop 1.0*0.4 + discipline 0.2*0.2 + info 1.0*0.2 + naming 1.0*0.2 = 0.84
        assert sc.overall_score == pytest.approx(0.84)
        assert sc.overall_grade == "B"
        assert sc.status == "passed"

    def test_not_applicable_facet_renormalises(self) -> None:
        # Singleton categories -> information consistency not assessable; it must
        # drop out of the weighted overall rather than count as zero.
        els = [
            ns(
                id="1",
                stable_id="1",
                element_type="wall",
                name="Wall",
                storey="L1",
                properties={"fire_rating": "F"},
                quantities={"thickness_m": 0.2},
            ),
            ns(
                id="2",
                stable_id="2",
                element_type="door",
                name="Door",
                storey="L1",
                properties={"width": 0.9},
                quantities={"width_m": 0.9, "height_m": 2.1},
            ),
        ]
        sc = build_bim_scorecard(els)
        info = next(f for f in sc.facets if f.facet_id == FACET_INFORMATION_CONSISTENCY)
        assert info.applicable is False
        applicable = [f for f in sc.facets if f.applicable and f.score is not None]
        assert FACET_INFORMATION_CONSISTENCY not in {f.facet_id for f in applicable}
        denom = sum(f.weight for f in applicable)
        expected = round(sum(f.score * f.weight for f in applicable) / denom, 4)
        assert sc.overall_score == expected

    def test_status_errors_on_blocking_finding(self) -> None:
        els = [ns(id="b", stable_id="b", element_type="wall", name="None", storey=None, properties={}, quantities={})]
        sc = build_bim_scorecard(els)
        assert sc.status == "errors"
        assert sc.overall_score is not None

    def test_status_warnings_when_low_but_no_errors(self) -> None:
        els = [
            ns(
                id=f"x{i}",
                stable_id=f"x{i}",
                element_type="wall",
                name="None",
                storey=None,
                properties={},
                quantities={"thickness_m": 0.24},
            )
            for i in range(4)
        ]
        sc = build_bim_scorecard(els)
        prop = next(f for f in sc.facets if f.facet_id == FACET_PROPERTY_COMPLETENESS)
        assert prop.details["error_findings"] == 0
        assert sc.status == "warnings"
        assert sc.overall_score is not None
        assert sc.overall_score < 0.75

    def test_element_drilldown_merges_facets(self) -> None:
        els = [ns(id="b1", stable_id="b1", element_type="wall", name="None", storey=None, properties={}, quantities={})]
        sc = build_bim_scorecard(els)
        assert "b1" in sc.element_findings
        assert FACET_PROPERTY_COMPLETENESS in sc.element_findings["b1"]
        assert FACET_NAMING_RIGOR in sc.element_findings["b1"]

    def test_empty_model_skipped(self) -> None:
        sc = build_bim_scorecard([])
        assert sc.element_count == 0
        assert sc.overall_score is None
        assert sc.overall_grade == "N/A"
        assert sc.status == "skipped"
        assert len(sc.facets) == len(FACET_ORDER)
        assert all(f.applicable is False for f in sc.facets)
        assert sc.element_findings == {}

    def test_to_dict_is_serialisable(self) -> None:
        sc = build_bim_scorecard([_clean_wall(0), _clean_wall(1), _clean_wall(2)])
        data = sc.to_dict()
        assert data["overall_score"] is not None
        assert {f["facet_id"] for f in data["facets"]} == set(FACET_ORDER)


# --- Version trend ---------------------------------------------------------


class TestScoreTrend:
    def test_ascending_is_improving(self) -> None:
        reports = [
            rep(id="r1", score="0.5", status="warnings", created_at=_dt(1)),
            rep(id="r2", score="0.7", status="warnings", created_at=_dt(2)),
            rep(id="r3", score="0.9", status="passed", created_at=_dt(3)),
        ]
        trend = assemble_score_trend(reports, target_id="m1")
        assert trend.direction == "improving"
        assert trend.first_score == 0.5
        assert trend.latest_score == 0.9
        assert trend.delta == pytest.approx(0.4)
        assert [p.run for p in trend.points] == [1, 2, 3]
        assert trend.points[0].grade == grade_for_score(0.5)
        assert trend.points[-1].grade == "A"
        assert trend.target_id == "m1"

    def test_descending_is_regressing(self) -> None:
        reports = [
            rep(score="0.9", created_at=_dt(1)),
            rep(score="0.6", created_at=_dt(2)),
            rep(score="0.4", created_at=_dt(3)),
        ]
        trend = assemble_score_trend(reports)
        assert trend.direction == "regressing"
        assert trend.delta == pytest.approx(-0.5)

    def test_flat_series(self) -> None:
        reports = [rep(score="0.8", created_at=_dt(d)) for d in (1, 2, 3)]
        trend = assemble_score_trend(reports)
        assert trend.direction == "flat"
        assert trend.delta == 0.0

    def test_out_of_order_sorted_by_created_at(self) -> None:
        reports = [
            rep(score="0.9", created_at=_dt(3)),
            rep(score="0.5", created_at=_dt(1)),
            rep(score="0.7", created_at=_dt(2)),
        ]
        trend = assemble_score_trend(reports)
        assert [p.score for p in trend.points] == [0.5, 0.7, 0.9]
        assert trend.direction == "improving"

    def test_iso_string_dates_sorted(self) -> None:
        reports = [
            rep(score="0.9", created_at="2026-03-01T00:00:00"),
            rep(score="0.5", created_at="2026-01-01T00:00:00"),
        ]
        trend = assemble_score_trend(reports)
        assert [p.score for p in trend.points] == [0.5, 0.9]

    def test_empty_history_insufficient(self) -> None:
        trend = assemble_score_trend([], target_id="m1")
        assert trend.direction == "insufficient"
        assert trend.points == []
        assert trend.first_score is None
        assert trend.latest_score is None
        assert trend.delta is None

    def test_single_point_insufficient(self) -> None:
        trend = assemble_score_trend([rep(score="0.6", created_at=_dt(1))])
        assert trend.direction == "insufficient"

    def test_skipped_report_included_but_ignored_for_direction(self) -> None:
        reports = [
            rep(score=None, status="skipped", created_at=_dt(1)),
            rep(score="0.6", created_at=_dt(2)),
            rep(score="0.8", created_at=_dt(3)),
        ]
        trend = assemble_score_trend(reports)
        assert trend.direction == "improving"
        assert trend.first_score == 0.6
        assert trend.points[0].score is None
        assert trend.points[0].grade == "N/A"

    def test_element_count_from_metadata(self) -> None:
        trend = assemble_score_trend([rep(score="0.5", created_at=_dt(1), metadata_={"element_count": 42})])
        assert trend.points[0].element_count == 42


class TestCoerceScore:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0.5", 0.5),
            ("0.8734", 0.8734),
            (0.7, 0.7),
            (1, 1.0),
        ],
    )
    def test_valid(self, raw: Any, expected: float) -> None:
        assert coerce_score(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, "", "abc", True, float("nan"), float("inf")])
    def test_invalid_returns_none(self, raw: Any) -> None:
        assert coerce_score(raw) is None
