# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic tests for the defects-liability / DLP register core.

Every test drives :mod:`app.modules.defects_liability.register` from plain
dataclasses with no database, mirroring the sibling temporary-works and
interface-management register test suites. The focus is the boundary behaviour
that decides real money: when a defects liability period counts as expiring or
expired, which defects are outstanding or overdue, and - above all - when an entry
is clear for the final retention to be released.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.defects_liability import register
from app.modules.defects_liability.register import DefectRow, WarrantyRow

# A fixed reference date so every boundary assertion is exact and stable.
AS_OF = date(2026, 7, 16)


# -- Builders ----------------------------------------------------------------


def _defect(
    status: str = "open",
    *,
    severity: str | None = None,
    due_date: date | None = None,
) -> DefectRow:
    """Build a defect row with sensible defaults."""
    return DefectRow(status=status, severity=severity, due_date=due_date)


def _warranty(
    *,
    id: str = "w1",
    reference: str = "DLP-001",
    title: str = "Entry",
    status: str = "in_dlp",
    subcontractor_name: str | None = None,
    work_package: str | None = None,
    warranty_type: str | None = None,
    dlp_end_date: date | None = None,
    warranty_end_date: date | None = None,
    defects: list[DefectRow] | None = None,
) -> WarrantyRow:
    """Build a warranty row with sensible defaults."""
    return WarrantyRow(
        id=id,
        reference=reference,
        title=title,
        status=status,
        subcontractor_name=subcontractor_name,
        work_package=work_package,
        warranty_type=warranty_type,
        dlp_end_date=dlp_end_date,
        warranty_end_date=warranty_end_date,
        defects=defects or [],
    )


# -- safe_percent ------------------------------------------------------------


def test_safe_percent_zero_denominator_is_none() -> None:
    assert register.safe_percent(0, 0) is None
    assert register.safe_percent(5, 0) is None


def test_safe_percent_basic() -> None:
    assert register.safe_percent(1, 2) == Decimal("50.00")
    assert register.safe_percent(2, 2) == Decimal("100.00")
    assert register.safe_percent(0, 2) == Decimal("0.00")


def test_safe_percent_rounds_half_up_to_two_dp() -> None:
    assert register.safe_percent(2, 3) == Decimal("66.67")
    assert register.safe_percent(1, 3) == Decimal("33.33")


# -- is_expiring -------------------------------------------------------------


def test_is_expiring_dlp_end_exactly_as_of_included() -> None:
    w = _warranty(dlp_end_date=AS_OF)
    assert register.is_expiring(w, AS_OF, 30) is True


def test_is_expiring_dlp_end_exactly_horizon_end_included() -> None:
    horizon_end = AS_OF + timedelta(days=30)
    w = _warranty(dlp_end_date=horizon_end)
    assert register.is_expiring(w, AS_OF, 30) is True


def test_is_expiring_one_day_beyond_horizon_excluded() -> None:
    beyond = AS_OF + timedelta(days=31)
    w = _warranty(dlp_end_date=beyond)
    assert register.is_expiring(w, AS_OF, 30) is False


def test_is_expiring_mid_horizon_true() -> None:
    w = _warranty(dlp_end_date=AS_OF + timedelta(days=15))
    assert register.is_expiring(w, AS_OF, 30) is True


def test_is_expiring_already_past_is_not_expiring() -> None:
    # A DLP end before as_of is expired, not expiring (as_of <= dlp_end fails).
    w = _warranty(dlp_end_date=AS_OF - timedelta(days=1))
    assert register.is_expiring(w, AS_OF, 30) is False


def test_is_expiring_closed_excluded_even_in_window() -> None:
    w = _warranty(status="closed", dlp_end_date=AS_OF + timedelta(days=5))
    assert register.is_expiring(w, AS_OF, 30) is False


def test_is_expiring_on_hold_included_in_window() -> None:
    # Only 'closed' is excluded; on_hold in the window still counts as expiring.
    w = _warranty(status="on_hold", dlp_end_date=AS_OF + timedelta(days=5))
    assert register.is_expiring(w, AS_OF, 30) is True


def test_is_expiring_none_dlp_end_is_false() -> None:
    w = _warranty(dlp_end_date=None)
    assert register.is_expiring(w, AS_OF, 30) is False


def test_is_expiring_zero_horizon_only_today() -> None:
    assert register.is_expiring(_warranty(dlp_end_date=AS_OF), AS_OF, 0) is True
    assert register.is_expiring(_warranty(dlp_end_date=AS_OF + timedelta(days=1)), AS_OF, 0) is False


# -- is_expired --------------------------------------------------------------


def test_is_expired_before_as_of_true() -> None:
    w = _warranty(dlp_end_date=AS_OF - timedelta(days=1))
    assert register.is_expired(w, AS_OF) is True


def test_is_expired_equal_as_of_is_false() -> None:
    # Strict "<": DLP ending exactly on as_of is not yet expired.
    w = _warranty(dlp_end_date=AS_OF)
    assert register.is_expired(w, AS_OF) is False


def test_is_expired_future_false() -> None:
    w = _warranty(dlp_end_date=AS_OF + timedelta(days=10))
    assert register.is_expired(w, AS_OF) is False


def test_is_expired_closed_excluded() -> None:
    w = _warranty(status="closed", dlp_end_date=AS_OF - timedelta(days=100))
    assert register.is_expired(w, AS_OF) is False


def test_is_expired_none_dlp_end_false() -> None:
    assert register.is_expired(_warranty(dlp_end_date=None), AS_OF) is False


def test_is_expired_far_past_unclosed_true() -> None:
    w = _warranty(status="expired", dlp_end_date=AS_OF - timedelta(days=400))
    assert register.is_expired(w, AS_OF) is True


# -- open_defect_count -------------------------------------------------------


def test_open_defect_count_open_and_rectifying_counted() -> None:
    w = _warranty(defects=[_defect("open"), _defect("rectifying")])
    assert register.open_defect_count(w) == 2


def test_open_defect_count_settled_not_counted() -> None:
    w = _warranty(defects=[_defect("rectified"), _defect("rejected"), _defect("closed")])
    assert register.open_defect_count(w) == 0


def test_open_defect_count_empty_is_zero() -> None:
    assert register.open_defect_count(_warranty()) == 0


def test_open_defect_count_mixed() -> None:
    w = _warranty(
        defects=[
            _defect("open"),
            _defect("rectifying"),
            _defect("rectified"),
            _defect("rejected"),
            _defect("closed"),
        ],
    )
    assert register.open_defect_count(w) == 2


def test_open_defect_count_unknown_status_not_counted() -> None:
    # A stray out-of-vocabulary status must not inflate the outstanding load.
    w = _warranty(defects=[_defect("banana"), _defect("open")])
    assert register.open_defect_count(w) == 1


# -- DefectRow.is_overdue / overdue_defect_count -----------------------------


def test_defect_overdue_past_due_and_open_true() -> None:
    d = _defect("open", due_date=AS_OF - timedelta(days=1))
    assert d.is_overdue(AS_OF) is True


def test_defect_overdue_due_equals_as_of_is_false() -> None:
    # Strict "<": due today is not yet overdue.
    d = _defect("open", due_date=AS_OF)
    assert d.is_overdue(AS_OF) is False


def test_defect_overdue_settled_is_false() -> None:
    # A rectified defect past its (former) due date is not overdue.
    d = _defect("rectified", due_date=AS_OF - timedelta(days=10))
    assert d.is_overdue(AS_OF) is False


def test_defect_overdue_no_due_date_false() -> None:
    assert _defect("open", due_date=None).is_overdue(AS_OF) is False


def test_defect_overdue_future_due_false() -> None:
    assert _defect("open", due_date=AS_OF + timedelta(days=3)).is_overdue(AS_OF) is False


def test_overdue_defect_count_counts_only_outstanding_past_due() -> None:
    w = _warranty(
        defects=[
            _defect("open", due_date=AS_OF - timedelta(days=2)),
            _defect("rectifying", due_date=AS_OF - timedelta(days=1)),
            _defect("open", due_date=AS_OF),  # due today - not overdue
            _defect("closed", due_date=AS_OF - timedelta(days=5)),  # settled
        ],
    )
    assert register.overdue_defect_count(w, AS_OF) == 2


# -- retention_release_ready (the money signal) ------------------------------


def test_retention_ready_dlp_past_no_defects_true() -> None:
    w = _warranty(dlp_end_date=AS_OF - timedelta(days=1), defects=[])
    assert register.retention_release_ready(w, AS_OF) is True


def test_retention_ready_dlp_equals_as_of_true() -> None:
    # "<=": a DLP ending exactly today is already eligible for release.
    w = _warranty(dlp_end_date=AS_OF, defects=[])
    assert register.retention_release_ready(w, AS_OF) is True


def test_retention_ready_open_defect_blocks() -> None:
    w = _warranty(dlp_end_date=AS_OF - timedelta(days=5), defects=[_defect("open")])
    assert register.retention_release_ready(w, AS_OF) is False


def test_retention_ready_rectifying_defect_blocks() -> None:
    w = _warranty(dlp_end_date=AS_OF - timedelta(days=5), defects=[_defect("rectifying")])
    assert register.retention_release_ready(w, AS_OF) is False


def test_retention_ready_dlp_in_future_false() -> None:
    w = _warranty(dlp_end_date=AS_OF + timedelta(days=1), defects=[])
    assert register.retention_release_ready(w, AS_OF) is False


def test_retention_ready_no_dlp_end_false() -> None:
    w = _warranty(dlp_end_date=None, defects=[])
    assert register.retention_release_ready(w, AS_OF) is False


def test_retention_ready_only_settled_defects_true() -> None:
    # Rectified / rejected / closed defects do not hold a release back.
    w = _warranty(
        dlp_end_date=AS_OF - timedelta(days=1),
        defects=[_defect("rectified"), _defect("rejected"), _defect("closed")],
    )
    assert register.retention_release_ready(w, AS_OF) is True


def test_retention_ready_one_open_among_settled_blocks() -> None:
    w = _warranty(
        dlp_end_date=AS_OF - timedelta(days=1),
        defects=[_defect("closed"), _defect("open")],
    )
    assert register.retention_release_ready(w, AS_OF) is False


# -- has_open_or_overdue -----------------------------------------------------


def test_has_open_or_overdue_true_when_open() -> None:
    w = _warranty(defects=[_defect("open")])
    assert register.has_open_or_overdue(w, AS_OF) is True


def test_has_open_or_overdue_false_when_all_settled() -> None:
    w = _warranty(defects=[_defect("rectified"), _defect("closed")])
    assert register.has_open_or_overdue(w, AS_OF) is False


# -- status_counts -----------------------------------------------------------


def test_status_counts_zero_filled_all_statuses() -> None:
    counts = register.status_counts([])
    assert counts == {
        "in_dlp": 0,
        "expiring": 0,
        "expired": 0,
        "closed": 0,
        "on_hold": 0,
    }


def test_status_counts_tallies_by_status() -> None:
    warranties = [
        _warranty(status="in_dlp"),
        _warranty(status="in_dlp"),
        _warranty(status="closed"),
    ]
    counts = register.status_counts(warranties)
    assert counts["in_dlp"] == 2
    assert counts["closed"] == 1
    assert counts["expired"] == 0


def test_status_counts_unknown_status_still_shown() -> None:
    counts = register.status_counts([_warranty(status="mystery")])
    assert counts["mystery"] == 1


# -- warranty_type_counts ----------------------------------------------------


def test_warranty_type_counts_none_goes_to_unassigned() -> None:
    counts = register.warranty_type_counts([_warranty(warranty_type=None)])
    assert counts["unassigned"] == 1


def test_warranty_type_counts_zero_filled_all_types() -> None:
    counts = register.warranty_type_counts([])
    for key in ("workmanship", "manufacturer", "latent_defect", "extended", "other", "unassigned"):
        assert counts[key] == 0


def test_warranty_type_counts_unknown_type_still_shown() -> None:
    counts = register.warranty_type_counts([_warranty(warranty_type="bespoke")])
    assert counts["bespoke"] == 1


def test_warranty_type_counts_sum_equals_total() -> None:
    warranties = [
        _warranty(warranty_type="workmanship"),
        _warranty(warranty_type="manufacturer"),
        _warranty(warranty_type=None),
        _warranty(warranty_type="workmanship"),
    ]
    counts = register.warranty_type_counts(warranties)
    assert sum(counts.values()) == len(warranties)


# -- total_open_defects ------------------------------------------------------


def test_total_open_defects_across_entries() -> None:
    warranties = [
        _warranty(id="a", defects=[_defect("open"), _defect("rectifying")]),
        _warranty(id="b", defects=[_defect("closed")]),
        _warranty(id="c", defects=[_defect("open")]),
    ]
    assert register.total_open_defects(warranties) == 3


def test_total_open_defects_empty_zero() -> None:
    assert register.total_open_defects([]) == 0


# -- overdue_defects (collection) --------------------------------------------


def test_overdue_defects_list_content_and_shape() -> None:
    w = _warranty(
        id="w9",
        reference="DLP-009",
        title="Roof",
        defects=[_defect("open", severity="major", due_date=AS_OF - timedelta(days=3))],
    )
    result = register.overdue_defects([w], AS_OF)
    assert len(result) == 1
    row = result[0]
    assert row["warranty_id"] == "w9"
    assert row["warranty_reference"] == "DLP-009"
    assert row["title"] == "Roof"
    assert row["severity"] == "major"
    assert row["status"] == "open"
    assert row["due_date"] == (AS_OF - timedelta(days=3)).isoformat()


def test_overdue_defects_boundary_due_equals_as_of_excluded() -> None:
    w = _warranty(defects=[_defect("open", due_date=AS_OF)])
    assert register.overdue_defects([w], AS_OF) == []


def test_overdue_defects_empty_when_none_overdue() -> None:
    w = _warranty(defects=[_defect("open", due_date=AS_OF + timedelta(days=5))])
    assert register.overdue_defects([w], AS_OF) == []


def test_overdue_defects_flattens_across_warranties() -> None:
    w1 = _warranty(id="w1", defects=[_defect("open", due_date=AS_OF - timedelta(days=1))])
    w2 = _warranty(
        id="w2",
        defects=[
            _defect("rectifying", due_date=AS_OF - timedelta(days=2)),
            _defect("closed", due_date=AS_OF - timedelta(days=2)),
        ],
    )
    result = register.overdue_defects([w1, w2], AS_OF)
    assert len(result) == 2
    assert {r["warranty_id"] for r in result} == {"w1", "w2"}


# -- overall_health_score ----------------------------------------------------


def test_overall_health_score_all_clean_is_100() -> None:
    warranties = [_warranty(id="a"), _warranty(id="b")]
    assert register.overall_health_score(warranties, AS_OF) == Decimal("100.00")


def test_overall_health_score_half_when_one_has_open() -> None:
    warranties = [
        _warranty(id="a", defects=[_defect("open")]),
        _warranty(id="b"),
    ]
    assert register.overall_health_score(warranties, AS_OF) == Decimal("50.00")


def test_overall_health_score_empty_is_none() -> None:
    assert register.overall_health_score([], AS_OF) is None


def test_overall_health_score_all_dirty_is_zero() -> None:
    warranties = [
        _warranty(id="a", defects=[_defect("open")]),
        _warranty(id="b", defects=[_defect("rectifying")]),
    ]
    assert register.overall_health_score(warranties, AS_OF) == Decimal("0.00")


# -- is_clean ----------------------------------------------------------------


def test_is_clean_empty_is_true() -> None:
    assert register.is_clean([], AS_OF) is True


def test_is_clean_open_defect_makes_false() -> None:
    w = _warranty(defects=[_defect("open")])
    assert register.is_clean([w], AS_OF) is False


def test_is_clean_expired_unclosed_makes_false() -> None:
    w = _warranty(status="expired", dlp_end_date=AS_OF - timedelta(days=1))
    assert register.is_clean([w], AS_OF) is False


def test_is_clean_expired_but_closed_stays_true() -> None:
    # A closed entry never counts as expired, so it does not spoil cleanliness.
    w = _warranty(status="closed", dlp_end_date=AS_OF - timedelta(days=30))
    assert register.is_clean([w], AS_OF) is True


def test_is_clean_all_good_true() -> None:
    warranties = [
        _warranty(id="a", status="in_dlp", dlp_end_date=AS_OF + timedelta(days=10)),
        _warranty(id="b", status="closed", defects=[_defect("closed")]),
    ]
    assert register.is_clean(warranties, AS_OF) is True


# -- per-subcontractor health + grouping -------------------------------------


def test_subcontractor_grouping_named_sorted_then_unassigned_last() -> None:
    warranties = [
        _warranty(id="1", subcontractor_name="Beta Ltd"),
        _warranty(id="2", subcontractor_name="Alpha Co"),
        _warranty(id="3", subcontractor_name=None),
        _warranty(id="4", subcontractor_name="   "),
    ]
    health = register.subcontractor_health(warranties, AS_OF)
    assert [h.subcontractor for h in health] == ["Alpha Co", "Beta Ltd", "unassigned"]


def test_subcontractor_none_and_blank_share_unassigned_bucket() -> None:
    warranties = [
        _warranty(id="3", subcontractor_name=None),
        _warranty(id="4", subcontractor_name="  "),
    ]
    health = register.subcontractor_health(warranties, AS_OF)
    assert len(health) == 1
    assert health[0].subcontractor == "unassigned"
    assert health[0].total == 2


def test_subcontractor_health_counts_defects() -> None:
    warranties = [
        _warranty(
            id="1",
            subcontractor_name="Acme",
            defects=[
                _defect("open", due_date=AS_OF - timedelta(days=1)),
                _defect("rectifying"),
            ],
        ),
        _warranty(id="2", subcontractor_name="Acme", defects=[_defect("closed")]),
    ]
    health = register.subcontractor_health(warranties, AS_OF)
    assert len(health) == 1
    acme = health[0]
    assert acme.total == 2
    assert acme.open_defects == 2  # one open + one rectifying
    assert acme.overdue_defects == 1  # only the past-due open one
    # One of two entries carries open/overdue defects -> 50 percent healthy.
    assert acme.health_score == Decimal("50.00")


def test_subcontractor_health_score_guarded_none_for_empty_register() -> None:
    assert register.subcontractor_health([], AS_OF) == []


def test_subcontractor_totals_sum_to_register_total() -> None:
    warranties = [
        _warranty(id="1", subcontractor_name="A"),
        _warranty(id="2", subcontractor_name="B"),
        _warranty(id="3", subcontractor_name=None),
    ]
    health = register.subcontractor_health(warranties, AS_OF)
    assert sum(h.total for h in health) == len(warranties)


def test_subcontractor_clean_group_scores_100() -> None:
    warranties = [_warranty(id="1", subcontractor_name="Clean Co", defects=[_defect("closed")])]
    health = register.subcontractor_health(warranties, AS_OF)
    assert health[0].health_score == Decimal("100.00")


# -- build_report ------------------------------------------------------------


def test_build_report_empty_no_crash_and_none_scores() -> None:
    report = register.build_report([], AS_OF)
    assert report.total == 0
    assert report.overall_health_score is None
    assert report.is_clean is True
    assert report.expiring == []
    assert report.expired == []
    assert report.overdue_defects == []
    assert report.retention_release_ready == []
    assert report.subcontractors == []
    # per_status / per_warranty_type are zero-filled, never empty.
    assert report.per_status["in_dlp"] == 0
    assert report.per_warranty_type["unassigned"] == 0


def test_build_report_default_horizon_is_30() -> None:
    report = register.build_report([], AS_OF)
    assert report.horizon_days == 30


def test_build_report_counts_and_totals() -> None:
    warranties = [
        _warranty(id="1", status="in_dlp", warranty_type="workmanship", defects=[_defect("open")]),
        _warranty(id="2", status="closed", warranty_type="manufacturer", defects=[_defect("closed")]),
    ]
    report = register.build_report(warranties, AS_OF)
    assert report.total == 2
    assert report.per_status["in_dlp"] == 1
    assert report.per_status["closed"] == 1
    assert report.per_warranty_type["workmanship"] == 1
    assert report.per_warranty_type["manufacturer"] == 1
    assert report.total_open_defects == 1


def test_build_report_expiring_and_expired_lists() -> None:
    expiring = _warranty(id="e1", reference="EXP-1", dlp_end_date=AS_OF + timedelta(days=5))
    expired = _warranty(id="e2", reference="EXP-2", status="expired", dlp_end_date=AS_OF - timedelta(days=5))
    healthy = _warranty(id="e3", reference="OK-3", dlp_end_date=AS_OF + timedelta(days=365))
    report = register.build_report([expiring, expired, healthy], AS_OF, horizon_days=30)
    assert [w.reference for w in report.expiring] == ["EXP-1"]
    assert [w.reference for w in report.expired] == ["EXP-2"]


def test_build_report_retention_release_ready_list() -> None:
    ready = _warranty(id="r1", reference="RDY-1", dlp_end_date=AS_OF - timedelta(days=1))
    blocked = _warranty(
        id="r2",
        reference="BLK-2",
        dlp_end_date=AS_OF - timedelta(days=1),
        defects=[_defect("open")],
    )
    not_yet = _warranty(id="r3", reference="FUT-3", dlp_end_date=AS_OF + timedelta(days=30))
    report = register.build_report([ready, blocked, not_yet], AS_OF)
    assert [w.reference for w in report.retention_release_ready] == ["RDY-1"]


def test_build_report_overdue_defects_boundary() -> None:
    # due == as_of is not overdue; due before as_of on an open defect is.
    on_time = _warranty(id="1", defects=[_defect("open", due_date=AS_OF)])
    late = _warranty(id="2", defects=[_defect("open", due_date=AS_OF - timedelta(days=1))])
    report = register.build_report([on_time, late], AS_OF)
    assert len(report.overdue_defects) == 1
    assert report.overdue_defects[0]["warranty_id"] == "2"


def test_build_report_is_clean_flag_reacts_to_open_defect() -> None:
    dirty = _warranty(defects=[_defect("open")])
    assert register.build_report([dirty], AS_OF).is_clean is False


def test_build_report_horizon_widens_expiring() -> None:
    w = _warranty(dlp_end_date=AS_OF + timedelta(days=100))
    assert register.build_report([w], AS_OF, horizon_days=30).expiring == []
    assert len(register.build_report([w], AS_OF, horizon_days=120).expiring) == 1


def test_build_report_to_dict_structure() -> None:
    ready = _warranty(id="r1", reference="RDY-1", subcontractor_name="Acme", dlp_end_date=AS_OF - timedelta(days=1))
    payload = register.build_report([ready], AS_OF).to_dict()
    assert payload["as_of"] == AS_OF.isoformat()
    assert payload["horizon_days"] == 30
    assert payload["total"] == 1
    assert isinstance(payload["per_status"], dict)
    assert isinstance(payload["per_warranty_type"], dict)
    # Ready list entries are JSON-ready dicts carrying the derived readiness flag.
    assert payload["retention_release_ready"][0]["reference"] == "RDY-1"
    assert payload["retention_release_ready"][0]["retention_release_ready"] is True
    # Score stays a Decimal (or None) at the core edge; the schema serialises it.
    assert payload["overall_health_score"] == Decimal("100.00")
    assert payload["subcontractors"][0]["subcontractor"] == "Acme"


def test_build_report_to_dict_empty_score_is_none() -> None:
    payload = register.build_report([], AS_OF).to_dict()
    assert payload["overall_health_score"] is None


def test_warranty_to_ref_carries_open_defect_count_and_readiness() -> None:
    w = _warranty(
        id="w1",
        dlp_end_date=AS_OF - timedelta(days=1),
        defects=[_defect("open"), _defect("closed")],
    )
    ref = w.to_ref(AS_OF)
    assert ref["open_defect_count"] == 1
    assert ref["retention_release_ready"] is False  # has one open defect
