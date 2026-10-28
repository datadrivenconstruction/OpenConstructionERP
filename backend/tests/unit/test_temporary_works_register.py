# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the temporary-works pure register core.

Every test constructs plain :class:`RegisterItem` / :class:`RegisterPermit` value
objects and asserts against exact results. No database, no ORM, no FastAPI - the
whole point of :mod:`app.modules.temporary_works.register` is that the
safety-critical clearance logic (cleared to load, cleared to strike, design
clearance progress, overdue detection, and above all the "bearing load without a
valid permit" breach) can be pinned down from first principles here. The tail of
the file also proves the pure ``to_dict`` output validates cleanly against the
Pydantic response schemas and serialises the percentage to a plain string, so the
API contract cannot silently drift from the core.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.temporary_works.register import (
    ALL_DESIGN_CHECK_CATEGORIES,
    ALL_ITEM_STATUSES,
    ALL_PERMIT_STATUSES,
    ALL_PERMIT_TYPES,
    ALL_TW_TYPES,
    UNASSIGNED_CATEGORY,
    ItemGateStatus,
    RegisterItem,
    RegisterPermit,
    TemporaryWorksRegister,
    build_report,
    category_counts,
    compliance_breaches,
    design_check_accepted,
    design_clearance_pct,
    design_cleared_count,
    is_compliant,
    is_overdue_to_load,
    is_overdue_to_strike,
    item_gate_status,
    load_gate,
    overdue_to_load_items,
    overdue_to_strike_items,
    safe_percent,
    status_counts,
    strike_gate,
    valid_permit,
)
from app.modules.temporary_works.schemas import (
    TemporaryWorksLoadStatusResponse,
    TemporaryWorksRegisterResponse,
)

_AS_OF = date(2026, 7, 16)
_PAST = date(2026, 7, 1)
_FUTURE = date(2026, 7, 26)


def _permit(
    permit_type: str = "permit_to_load",
    status: str = "issued",
    *,
    valid_from: date | None = None,
    valid_to: date | None = None,
    design_ok: bool = True,
    inspection_ok: bool = True,
) -> RegisterPermit:
    """Build a :class:`RegisterPermit` with sensible defaults (a good load permit)."""
    return RegisterPermit(
        permit_type=permit_type,
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        prereq_design_check_accepted=design_ok,
        prereq_inspection_passed=inspection_ok,
    )


def _item(
    reference: str = "TW-001",
    status: str = "identified",
    *,
    tw_type: str = "falsework",
    design_check_category: str | None = None,
    required_load_date: date | None = None,
    required_strike_date: date | None = None,
    permits: list[RegisterPermit] | None = None,
    item_id: str | None = "1",
    title: str = "item",
) -> RegisterItem:
    """Build a :class:`RegisterItem` with sensible defaults."""
    return RegisterItem(
        id=item_id,
        reference=reference,
        title=title,
        tw_type=tw_type,
        design_check_category=design_check_category,
        status=status,
        required_load_date=required_load_date,
        required_strike_date=required_strike_date,
        permits=list(permits or []),
    )


# -- vocabularies ------------------------------------------------------------


def test_vocabularies_are_the_expected_sets() -> None:
    assert ALL_TW_TYPES == (
        "falsework",
        "formwork",
        "propping",
        "excavation_support",
        "scaffold",
        "facade_retention",
        "crane_base",
        "edge_protection",
        "dewatering",
        "hoarding",
        "other",
    )
    assert ALL_ITEM_STATUSES == (
        "identified",
        "design_brief",
        "design_submitted",
        "design_checked",
        "approved_to_load",
        "loaded",
        "in_use",
        "approved_to_strike",
        "struck",
        "removed",
        "on_hold",
    )
    assert ALL_PERMIT_TYPES == ("permit_to_load", "permit_to_strike", "permit_to_dismantle")
    assert ALL_PERMIT_STATUSES == ("draft", "issued", "active", "expired", "closed")
    assert ALL_DESIGN_CHECK_CATEGORIES == ("0", "1", "2", "3")


# -- safe_percent (the guarded primitive) ------------------------------------


def test_safe_percent_zero_denominator_is_none() -> None:
    assert safe_percent(0, 0) is None
    assert safe_percent(5, 0) is None


def test_safe_percent_basic_and_type() -> None:
    result = safe_percent(1, 4)
    assert result == Decimal("25.00")
    assert isinstance(result, Decimal)


def test_safe_percent_rounds_half_up_to_two_dp() -> None:
    assert safe_percent(1, 3) == Decimal("33.33")
    assert safe_percent(2, 3) == Decimal("66.67")
    assert safe_percent(1, 800) == Decimal("0.13")  # 0.125 -> 0.13
    assert safe_percent(3, 800) == Decimal("0.38")  # 0.375 -> 0.38


def test_safe_percent_full_and_zero() -> None:
    assert safe_percent(4, 4) == Decimal("100.00")
    assert safe_percent(0, 4) == Decimal("0.00")


# -- RegisterPermit predicates -----------------------------------------------


def test_permit_is_live_only_for_issued_or_active() -> None:
    assert _permit(status="issued").is_live() is True
    assert _permit(status="active").is_live() is True
    assert _permit(status="draft").is_live() is False
    assert _permit(status="expired").is_live() is False
    assert _permit(status="closed").is_live() is False


def test_permit_window_open_ended_both_sides() -> None:
    # No bounds -> valid at any date.
    assert _permit().is_in_window(_AS_OF) is True


def test_permit_window_respects_from_and_to_inclusive() -> None:
    p = _permit(valid_from=_PAST, valid_to=_FUTURE)
    assert p.is_in_window(_AS_OF) is True
    assert p.is_in_window(_PAST) is True  # inclusive lower bound
    assert p.is_in_window(_FUTURE) is True  # inclusive upper bound
    assert p.is_in_window(date(2026, 6, 30)) is False  # before from
    assert p.is_in_window(date(2026, 7, 27)) is False  # after to


def test_permit_is_valid_combines_live_and_window() -> None:
    assert _permit(status="issued", valid_from=_PAST, valid_to=_FUTURE).is_valid(_AS_OF) is True
    # Live but out of window.
    assert _permit(status="active", valid_from=_FUTURE).is_valid(_AS_OF) is False
    # In window but not live.
    assert _permit(status="draft", valid_from=_PAST, valid_to=_FUTURE).is_valid(_AS_OF) is False


# -- valid_permit ------------------------------------------------------------


def test_valid_permit_true_for_live_in_window_of_type() -> None:
    item = _item(status="loaded", permits=[_permit("permit_to_load", "issued")])
    assert valid_permit(item, "permit_to_load", _AS_OF) is True


def test_valid_permit_false_for_wrong_type() -> None:
    item = _item(permits=[_permit("permit_to_strike", "active")])
    assert valid_permit(item, "permit_to_load", _AS_OF) is False


def test_valid_permit_false_when_not_live() -> None:
    for spent in ("draft", "expired", "closed"):
        item = _item(permits=[_permit("permit_to_load", spent)])
        assert valid_permit(item, "permit_to_load", _AS_OF) is False


def test_valid_permit_false_when_out_of_window() -> None:
    before = _item(permits=[_permit("permit_to_load", "issued", valid_from=_FUTURE)])
    after = _item(permits=[_permit("permit_to_load", "issued", valid_to=_PAST)])
    assert valid_permit(before, "permit_to_load", _AS_OF) is False
    assert valid_permit(after, "permit_to_load", _AS_OF) is False


def test_valid_permit_false_with_no_permits() -> None:
    assert valid_permit(_item(), "permit_to_load", _AS_OF) is False


def test_valid_permit_picks_any_matching_permit() -> None:
    # A spent permit plus a good one still reads valid.
    item = _item(
        permits=[
            _permit("permit_to_load", "expired"),
            _permit("permit_to_load", "active", valid_from=_PAST, valid_to=_FUTURE),
        ],
    )
    assert valid_permit(item, "permit_to_load", _AS_OF) is True


# -- design_check_accepted ---------------------------------------------------


def test_design_check_accepted_true_with_both_prereqs_on_valid_permit() -> None:
    item = _item(permits=[_permit("permit_to_load", "issued", design_ok=True, inspection_ok=True)])
    assert design_check_accepted(item, _AS_OF) is True


def test_design_check_accepted_false_when_a_prereq_missing() -> None:
    no_design = _item(permits=[_permit("permit_to_load", "issued", design_ok=False, inspection_ok=True)])
    no_insp = _item(permits=[_permit("permit_to_load", "issued", design_ok=True, inspection_ok=False)])
    assert design_check_accepted(no_design, _AS_OF) is False
    assert design_check_accepted(no_insp, _AS_OF) is False


def test_design_check_accepted_false_when_permit_not_valid() -> None:
    expired = _item(permits=[_permit("permit_to_load", "expired", design_ok=True, inspection_ok=True)])
    assert design_check_accepted(expired, _AS_OF) is False


# -- load_gate ---------------------------------------------------------------


def test_load_gate_true_with_valid_load_permit_and_both_prereqs() -> None:
    item = _item(
        status="approved_to_load",
        permits=[_permit("permit_to_load", "issued", valid_from=_PAST, valid_to=_FUTURE)],
    )
    assert load_gate(item, _AS_OF) is True


def test_load_gate_false_without_any_permit() -> None:
    assert load_gate(_item(status="approved_to_load"), _AS_OF) is False


def test_load_gate_false_when_design_check_not_accepted() -> None:
    item = _item(permits=[_permit("permit_to_load", "issued", design_ok=False, inspection_ok=True)])
    assert load_gate(item, _AS_OF) is False


def test_load_gate_false_when_inspection_not_passed() -> None:
    item = _item(permits=[_permit("permit_to_load", "issued", design_ok=True, inspection_ok=False)])
    assert load_gate(item, _AS_OF) is False


def test_load_gate_false_when_permit_expired() -> None:
    item = _item(permits=[_permit("permit_to_load", "expired", design_ok=True, inspection_ok=True)])
    assert load_gate(item, _AS_OF) is False


def test_load_gate_false_when_permit_out_of_window() -> None:
    item = _item(permits=[_permit("permit_to_load", "issued", valid_from=_FUTURE)])
    assert load_gate(item, _AS_OF) is False


def test_load_gate_false_when_only_strike_permit_present() -> None:
    item = _item(permits=[_permit("permit_to_strike", "issued")])
    assert load_gate(item, _AS_OF) is False


# -- strike_gate -------------------------------------------------------------


def test_strike_gate_true_with_valid_strike_permit() -> None:
    item = _item(status="approved_to_strike", permits=[_permit("permit_to_strike", "active")])
    assert strike_gate(item, _AS_OF) is True


def test_strike_gate_false_without_strike_permit() -> None:
    item = _item(permits=[_permit("permit_to_load", "issued")])
    assert strike_gate(item, _AS_OF) is False


def test_strike_gate_false_with_expired_strike_permit() -> None:
    item = _item(permits=[_permit("permit_to_strike", "expired")])
    assert strike_gate(item, _AS_OF) is False


# -- overdue detection -------------------------------------------------------


def test_overdue_to_load_true_when_past_due_and_not_settled() -> None:
    for waiting in ("identified", "design_submitted", "design_checked", "on_hold"):
        assert is_overdue_to_load(_item(status=waiting, required_load_date=_PAST), _AS_OF) is True


def test_overdue_to_load_false_once_settled() -> None:
    for settled in ("approved_to_load", "loaded", "in_use", "approved_to_strike", "struck", "removed"):
        assert is_overdue_to_load(_item(status=settled, required_load_date=_PAST), _AS_OF) is False


def test_overdue_to_load_boundary_and_undated() -> None:
    # As-of exactly on the required date is NOT overdue.
    assert is_overdue_to_load(_item(status="identified", required_load_date=_AS_OF), _AS_OF) is False
    assert is_overdue_to_load(_item(status="identified", required_load_date=_FUTURE), _AS_OF) is False
    assert is_overdue_to_load(_item(status="identified", required_load_date=None), _AS_OF) is False


def test_overdue_to_strike_true_when_past_due_and_not_settled() -> None:
    for waiting in ("loaded", "in_use", "approved_to_strike", "on_hold"):
        assert is_overdue_to_strike(_item(status=waiting, required_strike_date=_PAST), _AS_OF) is True


def test_overdue_to_strike_false_once_struck_or_removed() -> None:
    for settled in ("struck", "removed"):
        assert is_overdue_to_strike(_item(status=settled, required_strike_date=_PAST), _AS_OF) is False


def test_overdue_to_strike_boundary_and_undated() -> None:
    assert is_overdue_to_strike(_item(status="in_use", required_strike_date=_AS_OF), _AS_OF) is False
    assert is_overdue_to_strike(_item(status="in_use", required_strike_date=_FUTURE), _AS_OF) is False
    assert is_overdue_to_strike(_item(status="in_use", required_strike_date=None), _AS_OF) is False


def test_overdue_collections_filter_and_preserve_order() -> None:
    items = [
        _item(reference="a", status="identified", required_load_date=_PAST),
        _item(reference="b", status="loaded", required_load_date=_PAST),  # settled -> not overdue
        _item(reference="c", status="design_checked", required_load_date=_PAST),
    ]
    assert [i.reference for i in overdue_to_load_items(items, _AS_OF)] == ["a", "c"]

    strike_items = [
        _item(reference="x", status="in_use", required_strike_date=_PAST),
        _item(reference="y", status="struck", required_strike_date=_PAST),  # settled
    ]
    assert [i.reference for i in overdue_to_strike_items(strike_items, _AS_OF)] == ["x"]


# -- status_counts / category_counts -----------------------------------------


def test_status_counts_zero_fills_every_status() -> None:
    counts = status_counts([])
    assert set(counts.keys()) == set(ALL_ITEM_STATUSES)
    assert all(v == 0 for v in counts.values())
    assert list(counts.keys()) == list(ALL_ITEM_STATUSES)


def test_status_counts_tallies_each_status() -> None:
    items = [_item(status="loaded"), _item(status="loaded"), _item(status="in_use"), _item(status="removed")]
    counts = status_counts(items)
    assert counts["loaded"] == 2
    assert counts["in_use"] == 1
    assert counts["removed"] == 1
    assert counts["identified"] == 0


def test_status_counts_defensive_on_unknown_status() -> None:
    counts = status_counts([_item(status="mystery")])
    assert counts["mystery"] == 1
    for known in ALL_ITEM_STATUSES:
        assert known in counts


def test_category_counts_zero_fills_and_buckets_unassigned() -> None:
    counts = category_counts([])
    assert counts == {"0": 0, "1": 0, "2": 0, "3": 0, UNASSIGNED_CATEGORY: 0}


def test_category_counts_tallies_and_sums_to_total() -> None:
    items = [
        _item(design_check_category="0"),
        _item(design_check_category="2"),
        _item(design_check_category="2"),
        _item(design_check_category=None),
    ]
    counts = category_counts(items)
    assert counts["0"] == 1
    assert counts["2"] == 2
    assert counts["3"] == 0
    assert counts[UNASSIGNED_CATEGORY] == 1
    assert sum(counts.values()) == len(items)


def test_category_counts_defensive_on_unknown_category() -> None:
    counts = category_counts([_item(design_check_category="9")])
    assert counts["9"] == 1
    assert sum(counts.values()) == 1


# -- design clearance --------------------------------------------------------


def test_design_cleared_count_counts_checked_or_later() -> None:
    items = [
        _item(status="identified"),
        _item(status="design_submitted"),  # not yet cleared
        _item(status="design_checked"),  # cleared
        _item(status="loaded"),  # cleared
        _item(status="removed"),  # cleared
        _item(status="on_hold"),  # excluded
    ]
    assert design_cleared_count(items) == 3


def test_design_clearance_pct_empty_is_none() -> None:
    assert design_clearance_pct([]) is None


def test_design_clearance_pct_ratio_over_total() -> None:
    items = [
        _item(status="design_checked"),
        _item(status="approved_to_load"),
        _item(status="identified"),
        _item(status="design_brief"),
    ]
    # 2 cleared out of 4 total.
    result = design_clearance_pct(items)
    assert result == Decimal("50.00")
    assert isinstance(result, Decimal)


def test_design_clearance_pct_full() -> None:
    items = [_item(status="loaded"), _item(status="struck")]
    assert design_clearance_pct(items) == Decimal("100.00")


# -- compliance breaches (the safety red flag) -------------------------------


def test_breach_when_loaded_without_any_permit() -> None:
    breaches = compliance_breaches([_item(reference="TW-9", status="loaded", permits=[])], _AS_OF)
    assert len(breaches) == 1
    assert breaches[0]["reference"] == "TW-9"
    assert set(breaches[0].keys()) == {"item_id", "reference", "title", "reason"}


def test_breach_when_in_use_without_any_permit() -> None:
    breaches = compliance_breaches([_item(status="in_use", permits=[])], _AS_OF)
    assert len(breaches) == 1


def test_no_breach_when_loaded_with_valid_load_permit() -> None:
    item = _item(status="loaded", permits=[_permit("permit_to_load", "active", valid_from=_PAST, valid_to=_FUTURE)])
    assert compliance_breaches([item], _AS_OF) == []


def test_breach_when_load_permit_expired() -> None:
    item = _item(status="loaded", permits=[_permit("permit_to_load", "expired")])
    breaches = compliance_breaches([item], _AS_OF)
    assert len(breaches) == 1


def test_breach_when_load_permit_out_of_window() -> None:
    # An active permit whose window has already closed is not "in force".
    item = _item(status="in_use", permits=[_permit("permit_to_load", "active", valid_to=_PAST)])
    assert len(compliance_breaches([item], _AS_OF)) == 1


def test_no_breach_for_non_load_bearing_status_without_permit() -> None:
    # Not yet loaded -> no permit required yet, so not a breach.
    for pre in ("identified", "design_checked", "approved_to_load", "struck", "removed"):
        assert compliance_breaches([_item(status=pre, permits=[])], _AS_OF) == []


def test_no_breach_when_valid_permit_present_even_without_prereqs() -> None:
    # A valid permit-to-load exists (breach cleared) though its prereq flags are
    # unset - the breach check keys off a valid permit, not the load gate.
    item = _item(status="loaded", permits=[_permit("permit_to_load", "issued", design_ok=False, inspection_ok=False)])
    assert compliance_breaches([item], _AS_OF) == []
    # ... yet the load gate is (correctly) shut for that same item.
    assert load_gate(item, _AS_OF) is False


def test_is_compliant_reflects_breaches() -> None:
    clean = [_item(status="loaded", permits=[_permit("permit_to_load", "issued")])]
    dirty = [_item(status="loaded", permits=[])]
    assert is_compliant(clean, _AS_OF) is True
    assert is_compliant(dirty, _AS_OF) is False


# -- item_gate_status --------------------------------------------------------


def test_item_gate_status_packages_both_flags() -> None:
    item = _item(
        reference="TW-77",
        status="in_use",
        permits=[
            _permit("permit_to_load", "active"),
            _permit("permit_to_strike", "issued"),
        ],
    )
    gs = item_gate_status(item, _AS_OF)
    assert isinstance(gs, ItemGateStatus)
    assert gs.reference == "TW-77"
    assert gs.cleared_to_load is True
    assert gs.cleared_to_strike is True


# -- build_report ------------------------------------------------------------


def _sample_items() -> list[RegisterItem]:
    return [
        _item(
            reference="TW-1",
            status="in_use",
            design_check_category="2",
            item_id="1",
            permits=[_permit("permit_to_load", "active", valid_from=_PAST, valid_to=_FUTURE)],
        ),
        _item(
            reference="TW-2",
            status="loaded",
            design_check_category="3",
            item_id="2",
            permits=[],  # loaded with no permit -> breach
        ),
        _item(
            reference="TW-3",
            status="design_checked",
            design_check_category="1",
            required_load_date=_PAST,  # overdue to load
            item_id="3",
        ),
        _item(
            reference="TW-4",
            status="identified",
            design_check_category=None,
            item_id="4",
        ),
    ]


def test_build_report_totals_and_counts() -> None:
    report = build_report(_sample_items(), as_of=_AS_OF)
    assert isinstance(report, TemporaryWorksRegister)
    assert report.total == 4
    assert report.status_counts["in_use"] == 1
    assert report.status_counts["loaded"] == 1
    assert report.status_counts["design_checked"] == 1
    assert report.status_counts["identified"] == 1
    assert report.category_counts["1"] == 1
    assert report.category_counts["2"] == 1
    assert report.category_counts["3"] == 1
    assert report.category_counts[UNASSIGNED_CATEGORY] == 1


def test_build_report_design_clearance() -> None:
    # 2 of 4 are design_checked-or-later (in_use, loaded, design_checked = 3 actually).
    report = build_report(_sample_items(), as_of=_AS_OF)
    # in_use, loaded, design_checked are cleared; identified is not -> 3/4.
    assert report.design_clearance_pct == Decimal("75.00")


def test_build_report_flags_the_breach() -> None:
    report = build_report(_sample_items(), as_of=_AS_OF)
    assert report.is_compliant is False
    assert [b["reference"] for b in report.compliance_breaches] == ["TW-2"]


def test_build_report_overdue_and_gates() -> None:
    report = build_report(_sample_items(), as_of=_AS_OF)
    assert [i.reference for i in report.overdue_to_load] == ["TW-3"]
    assert report.overdue_to_strike == []
    # One gate status per item, in item order.
    assert [g.reference for g in report.gate_statuses] == ["TW-1", "TW-2", "TW-3", "TW-4"]
    # TW-1 has a valid load permit with both prereqs -> cleared to load.
    assert report.gate_statuses[0].cleared_to_load is True
    assert report.gate_statuses[1].cleared_to_load is False


def test_build_report_empty_is_well_formed() -> None:
    report = build_report([], as_of=_AS_OF)
    assert report.total == 0
    assert report.design_clearance_pct is None  # guarded, not a crash
    assert report.is_compliant is True
    assert report.compliance_breaches == []
    assert report.overdue_to_load == []
    assert report.overdue_to_strike == []
    assert report.gate_statuses == []
    # Counts are still fully zero-filled.
    assert set(report.status_counts.keys()) == set(ALL_ITEM_STATUSES)
    assert report.category_counts[UNASSIGNED_CATEGORY] == 0


# -- to_dict shapes ----------------------------------------------------------


def test_item_to_ref_has_iso_dates() -> None:
    item = _item(reference="TW-5", required_load_date=_PAST, required_strike_date=_FUTURE)
    ref = item.to_ref()
    assert ref["reference"] == "TW-5"
    assert ref["required_load_date"] == "2026-07-01"
    assert ref["required_strike_date"] == "2026-07-26"


def test_item_to_ref_null_dates() -> None:
    ref = _item().to_ref()
    assert ref["required_load_date"] is None
    assert ref["required_strike_date"] is None


def test_register_to_dict_keeps_decimal_and_shapes() -> None:
    report = build_report(_sample_items(), as_of=_AS_OF)
    d = report.to_dict()
    assert d["as_of"] == "2026-07-16"
    assert d["total"] == 4
    assert d["is_compliant"] is False
    # Percentage stays a Decimal in the pure dict (schema serialises to string).
    assert d["design_clearance_pct"] == Decimal("75.00")
    assert isinstance(d["design_clearance_pct"], Decimal)
    assert d["compliance_breaches"][0]["reference"] == "TW-2"
    assert d["overdue_to_load"][0]["reference"] == "TW-3"
    assert d["gate_statuses"][0]["cleared_to_load"] is True


def test_register_to_dict_empty_percent_is_none() -> None:
    d = build_report([], as_of=_AS_OF).to_dict()
    assert d["design_clearance_pct"] is None


# -- schema alignment (pure core <-> API contract) ---------------------------


def test_register_dict_validates_against_response_schema() -> None:
    report = build_report(_sample_items(), as_of=_AS_OF)
    payload = report.to_dict()
    payload["project_id"] = "11111111-1111-1111-1111-111111111111"
    model = TemporaryWorksRegisterResponse.model_validate(payload)
    assert model.total == 4
    assert model.is_compliant is False
    assert model.compliance_breaches[0].reference == "TW-2"
    assert model.overdue_to_load[0].reference == "TW-3"
    # Percentage serialises to a plain decimal string in JSON mode.
    dumped = model.model_dump(mode="json")
    assert dumped["design_clearance_pct"] == "75.00"


def test_register_response_serialises_none_percent() -> None:
    payload = build_report([], as_of=_AS_OF).to_dict()
    payload["project_id"] = "22222222-2222-2222-2222-222222222222"
    model = TemporaryWorksRegisterResponse.model_validate(payload)
    assert model.model_dump(mode="json")["design_clearance_pct"] is None


def test_load_status_dict_validates_against_response_schema() -> None:
    # Mirror exactly how TemporaryWorksService.get_load_status assembles its dict,
    # so the schema contract for that endpoint is exercised without a database.
    items = _sample_items()
    gate_statuses = [item_gate_status(i, _AS_OF) for i in items]
    breaches = compliance_breaches(items, _AS_OF)
    payload = {
        "project_id": "33333333-3333-3333-3333-333333333333",
        "as_of": _AS_OF.isoformat(),
        "total": len(items),
        "is_compliant": not breaches,
        "gate_statuses": [g.to_dict() for g in gate_statuses],
        "compliance_breaches": breaches,
    }
    model = TemporaryWorksLoadStatusResponse.model_validate(payload)
    assert model.total == 4
    assert model.is_compliant is False
    assert [g.reference for g in model.gate_statuses] == ["TW-1", "TW-2", "TW-3", "TW-4"]
    assert [b.reference for b in model.compliance_breaches] == ["TW-2"]
