# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the site-prep pure readiness core.

Every test constructs plain :class:`ReadinessItem` value objects and asserts
against exact results. No database, no ORM, no FastAPI - the whole point of
:mod:`app.modules.site_prep.readiness` is that the mobilisation readiness numbers,
gate logic and blocked / overdue detection can be pinned down from first
principles here. The tail of the file also proves the pure ``to_dict`` output
validates cleanly against the Pydantic response schemas, so the API contract
cannot silently drift from the core.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.site_prep.readiness import (
    ALL_CATEGORIES,
    ALL_STATUSES,
    CategoryReadiness,
    ReadinessItem,
    ReadinessReport,
    applicable_count,
    blocked_items,
    blocking_gate_items,
    build_report,
    category_readiness,
    days_to_target,
    gate_items,
    gate_ready,
    on_track,
    overall_readiness,
    overdue_items,
    readiness_percent,
    ready_count,
    safe_percent,
    status_counts,
)
from app.modules.site_prep.schemas import (
    CategoryReadinessResponse,
    GateStatusResponse,
    ReadinessReportResponse,
)

_AS_OF = date(2026, 7, 16)


def _item(
    category: str = "access",
    status: str = "not_started",
    *,
    is_gate: bool = False,
    due_date: date | None = None,
    title: str = "item",
    item_id: str | None = None,
    completed_date: date | None = None,
) -> ReadinessItem:
    """Build a :class:`ReadinessItem` with sensible defaults."""
    return ReadinessItem(
        category=category,
        status=status,
        is_gate=is_gate,
        due_date=due_date,
        title=title,
        item_id=item_id,
        completed_date=completed_date,
    )


# -- vocabularies ------------------------------------------------------------


def test_vocabularies_are_the_expected_sets() -> None:
    assert ALL_CATEGORIES == (
        "access",
        "accommodation_welfare",
        "temporary_utilities",
        "security_hoarding",
        "temporary_works",
        "environmental_controls",
        "logistics_laydown",
        "permits_consents",
        "inductions_training",
        "other",
    )
    assert ALL_STATUSES == (
        "not_started",
        "in_progress",
        "ready",
        "blocked",
        "not_applicable",
    )


# -- safe_percent (the guarded primitive) ------------------------------------


def test_safe_percent_zero_denominator_is_none() -> None:
    assert safe_percent(0, 0) is None
    assert safe_percent(5, 0) is None


def test_safe_percent_basic_and_type() -> None:
    result = safe_percent(1, 4)
    assert result == Decimal("25.00")
    assert isinstance(result, Decimal)


def test_safe_percent_rounds_half_up_to_two_dp() -> None:
    # 1/3 -> 33.333... rounds down; 2/3 -> 66.666... rounds up.
    assert safe_percent(1, 3) == Decimal("33.33")
    assert safe_percent(2, 3) == Decimal("66.67")
    # Exact .xx5 third decimal must round up (ROUND_HALF_UP), not to-even.
    assert safe_percent(1, 800) == Decimal("0.13")  # 0.125 -> 0.13
    assert safe_percent(3, 800) == Decimal("0.38")  # 0.375 -> 0.38


def test_safe_percent_full_and_zero() -> None:
    assert safe_percent(4, 4) == Decimal("100.00")
    assert safe_percent(0, 4) == Decimal("0.00")


# -- status_counts -----------------------------------------------------------


def test_status_counts_zero_fills_every_status() -> None:
    counts = status_counts([])
    assert counts == {
        "not_started": 0,
        "in_progress": 0,
        "ready": 0,
        "blocked": 0,
        "not_applicable": 0,
    }
    # Insertion order follows the canonical status order.
    assert list(counts.keys()) == list(ALL_STATUSES)


def test_status_counts_tallies_each_status() -> None:
    items = [
        _item(status="ready"),
        _item(status="ready"),
        _item(status="blocked"),
        _item(status="not_applicable"),
        _item(status="in_progress"),
    ]
    counts = status_counts(items)
    assert counts["ready"] == 2
    assert counts["blocked"] == 1
    assert counts["not_applicable"] == 1
    assert counts["in_progress"] == 1
    assert counts["not_started"] == 0


def test_status_counts_defensive_on_unknown_status() -> None:
    # An out-of-vocabulary status must never be silently dropped.
    counts = status_counts([_item(status="mystery")])
    assert counts["mystery"] == 1
    # The five known statuses are still present and zeroed.
    for known in ALL_STATUSES:
        assert known in counts


# -- applicable_count / ready_count ------------------------------------------


def test_applicable_count_excludes_not_applicable() -> None:
    items = [
        _item(status="ready"),
        _item(status="blocked"),
        _item(status="not_applicable"),
        _item(status="not_applicable"),
        _item(status="in_progress"),
    ]
    assert applicable_count(items) == 3


def test_ready_count_counts_only_ready() -> None:
    items = [_item(status="ready"), _item(status="ready"), _item(status="blocked")]
    assert ready_count(items) == 2


def test_counts_on_empty() -> None:
    assert applicable_count([]) == 0
    assert ready_count([]) == 0


# -- readiness_percent (guarded) ---------------------------------------------


def test_readiness_percent_empty_is_none() -> None:
    assert readiness_percent([]) is None


def test_readiness_percent_all_not_applicable_is_none() -> None:
    # applicable base is zero -> guarded to None, never a division error or 0.
    items = [_item(status="not_applicable"), _item(status="not_applicable")]
    assert readiness_percent(items) is None


def test_readiness_percent_is_ready_over_applicable() -> None:
    # 2 ready out of 3 applicable (the 4th is not_applicable, excluded).
    items = [
        _item(status="ready"),
        _item(status="ready"),
        _item(status="in_progress"),
        _item(status="not_applicable"),
    ]
    result = readiness_percent(items)
    assert result == Decimal("66.67")
    assert isinstance(result, Decimal)


def test_readiness_percent_full() -> None:
    items = [_item(status="ready"), _item(status="not_applicable")]
    assert readiness_percent(items) == Decimal("100.00")


# -- ReadinessItem properties ------------------------------------------------


def test_item_status_predicates() -> None:
    assert _item(status="ready").is_ready is True
    assert _item(status="ready").is_applicable is True
    assert _item(status="not_applicable").is_applicable is False
    assert _item(status="blocked").is_blocked is True
    assert _item(status="in_progress").is_blocked is False


def test_non_gate_item_is_always_gate_satisfied() -> None:
    assert _item(status="blocked", is_gate=False).is_gate_satisfied is True
    assert _item(status="not_started", is_gate=False).is_gate_satisfied is True


def test_gate_item_satisfied_only_when_ready_or_na() -> None:
    assert _item(status="ready", is_gate=True).is_gate_satisfied is True
    assert _item(status="not_applicable", is_gate=True).is_gate_satisfied is True
    assert _item(status="in_progress", is_gate=True).is_gate_satisfied is False
    assert _item(status="blocked", is_gate=True).is_gate_satisfied is False
    assert _item(status="not_started", is_gate=True).is_gate_satisfied is False


# -- overdue detection -------------------------------------------------------


def test_overdue_true_when_past_due_and_unresolved() -> None:
    past = date(2026, 7, 15)
    assert _item(status="in_progress", due_date=past).is_overdue(_AS_OF) is True
    assert _item(status="blocked", due_date=past).is_overdue(_AS_OF) is True
    assert _item(status="not_started", due_date=past).is_overdue(_AS_OF) is True


def test_overdue_false_when_resolved() -> None:
    past = date(2026, 7, 15)
    assert _item(status="ready", due_date=past).is_overdue(_AS_OF) is False
    assert _item(status="not_applicable", due_date=past).is_overdue(_AS_OF) is False


def test_overdue_false_on_due_today_or_future_or_undated() -> None:
    assert _item(status="in_progress", due_date=_AS_OF).is_overdue(_AS_OF) is False
    assert _item(status="in_progress", due_date=date(2026, 7, 17)).is_overdue(_AS_OF) is False
    assert _item(status="in_progress", due_date=None).is_overdue(_AS_OF) is False


def test_overdue_items_collection() -> None:
    past = date(2026, 7, 1)
    items = [
        _item(status="in_progress", due_date=past, title="a"),
        _item(status="ready", due_date=past, title="b"),
        _item(status="blocked", due_date=past, title="c"),
        _item(status="not_started", due_date=None, title="d"),
    ]
    overdue = overdue_items(items, _AS_OF)
    assert [i.title for i in overdue] == ["a", "c"]


# -- gate logic --------------------------------------------------------------


def test_gate_items_filters_gates() -> None:
    items = [_item(is_gate=True, title="g1"), _item(is_gate=False), _item(is_gate=True, title="g2")]
    assert [i.title for i in gate_items(items)] == ["g1", "g2"]


def test_gate_ready_vacuously_true_without_gates() -> None:
    assert gate_ready([_item(status="blocked"), _item(status="not_started")]) is True


def test_gate_ready_true_when_all_gates_ready_or_na() -> None:
    items = [
        _item(status="ready", is_gate=True),
        _item(status="not_applicable", is_gate=True),
        _item(status="blocked", is_gate=False),  # non-gate blocker does not count
    ]
    assert gate_ready(items) is True


def test_gate_ready_false_when_any_gate_unsatisfied() -> None:
    items = [
        _item(status="ready", is_gate=True),
        _item(status="in_progress", is_gate=True),
    ]
    assert gate_ready(items) is False


def test_blocking_gate_items_lists_only_unsatisfied_gates() -> None:
    items = [
        _item(status="ready", is_gate=True, title="done"),
        _item(status="blocked", is_gate=True, title="blocked-gate"),
        _item(status="in_progress", is_gate=True, title="wip-gate"),
        _item(status="blocked", is_gate=False, title="non-gate"),
    ]
    blocking = blocking_gate_items(items)
    assert [i.title for i in blocking] == ["blocked-gate", "wip-gate"]


def test_blocked_items_collection() -> None:
    items = [_item(status="blocked", title="x"), _item(status="ready", title="y"), _item(status="blocked", title="z")]
    assert [i.title for i in blocked_items(items)] == ["x", "z"]


# -- days_to_target ----------------------------------------------------------


def test_days_to_target_none_when_unset() -> None:
    assert days_to_target(None, _AS_OF) is None


def test_days_to_target_sign() -> None:
    assert days_to_target(date(2026, 7, 26), _AS_OF) == 10  # future
    assert days_to_target(_AS_OF, _AS_OF) == 0  # today
    assert days_to_target(date(2026, 7, 6), _AS_OF) == -10  # past


# -- on_track ----------------------------------------------------------------


def test_on_track_true_when_gate_ready_even_if_start_passed() -> None:
    items = [_item(status="ready", is_gate=True)]
    assert on_track(items, date(2026, 1, 1), _AS_OF) is True


def test_on_track_true_when_lead_time_remains() -> None:
    items = [_item(status="in_progress", is_gate=True)]  # not gate ready
    assert on_track(items, date(2026, 7, 26), _AS_OF) is True


def test_on_track_false_when_not_gate_ready_and_no_slack() -> None:
    items = [_item(status="in_progress", is_gate=True)]
    assert on_track(items, _AS_OF, _AS_OF) is False  # start today, gates open
    assert on_track(items, date(2026, 7, 6), _AS_OF) is False  # start passed


def test_on_track_false_when_not_gate_ready_and_no_target() -> None:
    items = [_item(status="blocked", is_gate=True)]
    assert on_track(items, None, _AS_OF) is False


def test_on_track_true_without_gates_regardless_of_date() -> None:
    # No gate items -> gate_ready vacuously True -> on track.
    assert on_track([_item(status="blocked")], date(2026, 1, 1), _AS_OF) is True


# -- category_readiness / overall_readiness ----------------------------------


def test_category_readiness_scopes_to_one_category() -> None:
    items = [
        _item(category="access", status="ready"),
        _item(category="access", status="blocked"),
        _item(category="permits_consents", status="ready"),
    ]
    cr = category_readiness(items, "access", _AS_OF)
    assert cr.category == "access"
    assert cr.total == 2
    assert cr.applicable == 2
    assert cr.ready == 1
    assert cr.readiness_percent == Decimal("50.00")
    assert cr.blocked == 1


def test_overall_readiness_spans_all_items() -> None:
    items = [
        _item(category="access", status="ready", is_gate=True),
        _item(category="permits_consents", status="ready"),
        _item(category="temporary_works", status="not_applicable"),
    ]
    overall = overall_readiness(items, _AS_OF)
    assert overall.category == "overall"
    assert overall.total == 3
    assert overall.applicable == 2
    assert overall.ready == 2
    assert overall.readiness_percent == Decimal("100.00")
    assert overall.gate_total == 1
    assert overall.gate_ready is True


def test_category_readiness_percent_none_when_all_na() -> None:
    items = [_item(category="access", status="not_applicable")]
    cr = category_readiness(items, "access", _AS_OF)
    assert cr.applicable == 0
    assert cr.readiness_percent is None


# -- build_report ------------------------------------------------------------


def _sample_items() -> list[ReadinessItem]:
    past = date(2026, 7, 1)
    return [
        _item(category="access", status="ready", is_gate=True, title="road", item_id="1"),
        _item(category="access", status="blocked", title="crossing", due_date=past, item_id="2"),
        _item(category="accommodation_welfare", status="ready", title="welfare", item_id="3"),
        _item(category="permits_consents", status="in_progress", is_gate=True, title="permit", item_id="4"),
        _item(category="temporary_works", status="not_applicable", title="props", item_id="5"),
    ]


def test_build_report_overall_matches_manual_rollup() -> None:
    report = build_report(_sample_items(), target_start_date=date(2026, 7, 26), as_of=_AS_OF)
    assert isinstance(report, ReadinessReport)
    # 5 items, 4 applicable (props is N/A), 2 ready.
    assert report.overall.total == 5
    assert report.overall.applicable == 4
    assert report.overall.ready == 2
    assert report.overall.readiness_percent == Decimal("50.00")
    # One gate is in_progress -> not gate ready, but 10 days of slack remain.
    assert report.gate_ready is False
    assert report.days_to_target == 10
    assert report.on_track is True


def test_build_report_category_totals_sum_to_overall() -> None:
    items = _sample_items()
    report = build_report(items, target_start_date=None, as_of=_AS_OF)
    assert sum(c.total for c in report.categories) == report.overall.total
    assert sum(c.applicable for c in report.categories) == report.overall.applicable
    assert sum(c.ready for c in report.categories) == report.overall.ready


def test_build_report_categories_in_canonical_order() -> None:
    report = build_report(_sample_items(), target_start_date=None, as_of=_AS_OF)
    labels = [c.category for c in report.categories]
    # Present categories only, ordered as in ALL_CATEGORIES.
    assert labels == [
        "access",
        "accommodation_welfare",
        "temporary_works",
        "permits_consents",
    ] or labels == sorted(labels, key=ALL_CATEGORIES.index)
    # Precise canonical ordering check.
    assert labels == sorted(labels, key=ALL_CATEGORIES.index)


def test_build_report_lists_blocked_and_overdue() -> None:
    report = build_report(_sample_items(), target_start_date=None, as_of=_AS_OF)
    assert [i.title for i in report.blocked_items] == ["crossing"]
    # "crossing" is blocked AND past due -> also overdue.
    assert [i.title for i in report.overdue_items] == ["crossing"]


def test_build_report_empty_is_well_formed() -> None:
    report = build_report([], target_start_date=None, as_of=_AS_OF)
    assert report.overall.total == 0
    assert report.overall.applicable == 0
    assert report.overall.readiness_percent is None
    assert report.categories == []
    assert report.blocked_items == []
    assert report.overdue_items == []
    # No gates -> vacuously gate ready -> on track even without a target date.
    assert report.gate_ready is True
    assert report.on_track is True
    assert report.days_to_target is None


def test_build_report_orders_noncanonical_categories_last() -> None:
    items = [
        _item(category="zzz_custom", status="ready", title="custom"),
        _item(category="access", status="ready", title="road"),
    ]
    report = build_report(items, target_start_date=None, as_of=_AS_OF)
    labels = [c.category for c in report.categories]
    assert labels == ["access", "zzz_custom"]
    # Overall still counts the non-canonical item.
    assert report.overall.total == 2


def test_build_report_gate_ready_drives_on_track_when_start_passed() -> None:
    # All gates satisfied -> on track even though the planned start is in the past.
    items = [_item(category="access", status="ready", is_gate=True)]
    report = build_report(items, target_start_date=date(2026, 1, 1), as_of=_AS_OF)
    assert report.gate_ready is True
    assert report.days_to_target < 0
    assert report.on_track is True


# -- to_dict shapes ----------------------------------------------------------


def test_category_readiness_to_dict_percent_is_float_or_none() -> None:
    cr = CategoryReadiness(
        category="access",
        total=3,
        applicable=3,
        ready=2,
        counts=status_counts([_item(status="ready"), _item(status="ready"), _item(status="blocked")]),
        readiness_percent=Decimal("66.67"),
        gate_total=0,
        gate_ready=True,
        blocked=1,
        overdue=0,
    )
    d = cr.to_dict()
    assert d["readiness_percent"] == 66.67
    assert isinstance(d["readiness_percent"], float)

    none_cr = CategoryReadiness(
        category="access",
        total=0,
        applicable=0,
        ready=0,
        counts=status_counts([]),
        readiness_percent=None,
        gate_total=0,
        gate_ready=True,
        blocked=0,
        overdue=0,
    )
    assert none_cr.to_dict()["readiness_percent"] is None


def test_report_to_dict_has_iso_dates_and_expected_keys() -> None:
    report = build_report(_sample_items(), target_start_date=date(2026, 7, 26), as_of=_AS_OF)
    d = report.to_dict()
    assert d["as_of"] == "2026-07-16"
    assert d["target_start_date"] == "2026-07-26"
    assert d["days_to_target"] == 10
    assert d["total_items"] == 5
    assert d["applicable_items"] == 4
    assert d["ready_items"] == 2
    assert d["readiness_percent"] == 50.0
    # Blocked / overdue refs carry ISO due dates.
    assert d["blocked_items"][0]["due_date"] == "2026-07-01"
    assert set(d["overall"].keys()) == {
        "category",
        "total",
        "applicable",
        "ready",
        "counts",
        "readiness_percent",
        "gate_total",
        "gate_ready",
        "blocked",
        "overdue",
    }


def test_report_to_dict_null_target_date() -> None:
    d = build_report([], target_start_date=None, as_of=_AS_OF).to_dict()
    assert d["target_start_date"] is None
    assert d["days_to_target"] is None
    assert d["readiness_percent"] is None


# -- schema alignment (pure core <-> API contract) ---------------------------


def test_report_dict_validates_against_response_schema() -> None:
    # The service adds project_id; everything else comes straight from to_dict().
    report = build_report(_sample_items(), target_start_date=date(2026, 7, 26), as_of=_AS_OF)
    payload = report.to_dict()
    payload["project_id"] = "11111111-1111-1111-1111-111111111111"
    model = ReadinessReportResponse.model_validate(payload)
    assert model.total_items == 5
    assert model.overall.category == "overall"
    assert model.categories  # non-empty
    assert model.blocked_items[0].title == "crossing"


def test_category_dict_validates_against_response_schema() -> None:
    report = build_report(_sample_items(), target_start_date=None, as_of=_AS_OF)
    for category in report.categories:
        model = CategoryReadinessResponse.model_validate(category.to_dict())
        assert model.total >= 1


def test_gate_status_dict_validates_against_response_schema() -> None:
    # Mirror exactly how SitePrepService.get_gate_status assembles its dict, so
    # the schema contract for that endpoint is exercised without a database.
    items = _sample_items()
    target = date(2026, 7, 26)
    gates = gate_items(items)
    blocking = blocking_gate_items(items)
    payload = {
        "project_id": "22222222-2222-2222-2222-222222222222",
        "as_of": _AS_OF.isoformat(),
        "target_start_date": target.isoformat(),
        "days_to_target": days_to_target(target, _AS_OF),
        "gate_ready": gate_ready(items),
        "on_track": on_track(items, target, _AS_OF),
        "gate_total": len(gates),
        "gate_ready_count": len(gates) - len(blocking),
        "gate_blocking": [i.to_dict() for i in blocking],
    }
    model = GateStatusResponse.model_validate(payload)
    assert model.gate_total == 2
    assert model.gate_ready is False
    assert model.gate_ready_count == 1
    assert [b.title for b in model.gate_blocking] == ["permit"]
