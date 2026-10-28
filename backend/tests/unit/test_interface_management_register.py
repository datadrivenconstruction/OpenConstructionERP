# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the interface-register pure core.

Every test constructs plain :class:`InterfaceRow` / :class:`ActionRow` value
objects and asserts against exact results. No database, no ORM, no FastAPI - the
whole point of :mod:`app.modules.interface_management.register` is that the
coordination logic (overdue detection, agreement percentage, per-work-package
health, dispute tracking and the single overall health flag) can be pinned down
from first principles here. The tail of the file also proves the pure ``to_dict``
output validates cleanly against the Pydantic response schemas and serialises the
percentages to plain strings, so the API contract cannot silently drift from the
core.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.interface_management.register import (
    ALL_ACTION_STATUSES,
    ALL_INTERFACE_STATUSES,
    ALL_INTERFACE_TYPES,
    ALL_PRIORITIES,
    UNASSIGNED,
    ActionRow,
    InterfaceRegister,
    InterfaceRow,
    WorkPackageHealth,
    agreed_pct,
    build_report,
    can_be_overdue,
    disputed_interfaces,
    is_healthy,
    is_overdue,
    open_action_count,
    overall_health_score,
    overdue_interfaces,
    priority_counts,
    resolved_count,
    safe_percent,
    status_counts,
    total_open_actions,
    type_counts,
    work_package_health,
)
from app.modules.interface_management.schemas import (
    InterfaceRegisterResponse,
    WorkPackageHealthReportResponse,
)

_AS_OF = date(2026, 7, 16)
_PAST = date(2026, 7, 1)
_FUTURE = date(2026, 7, 26)


def _action(status: str = "open", due_date: date | None = None) -> ActionRow:
    """Build an :class:`ActionRow` (an open action by default)."""
    return ActionRow(status=status, due_date=due_date)


def _iface(
    reference: str = "IF-001",
    status: str = "identified",
    *,
    priority: str | None = None,
    interface_type: str | None = None,
    owner_party: str | None = None,
    accepter_party: str | None = None,
    work_package_from: str | None = None,
    need_by_date: date | None = None,
    agreed_date: date | None = None,
    actions: list[ActionRow] | None = None,
    iface_id: str | None = "1",
    title: str = "iface",
) -> InterfaceRow:
    """Build an :class:`InterfaceRow` with sensible defaults."""
    return InterfaceRow(
        id=iface_id,
        reference=reference,
        title=title,
        status=status,
        priority=priority,
        interface_type=interface_type,
        owner_party=owner_party,
        accepter_party=accepter_party,
        work_package_from=work_package_from,
        need_by_date=need_by_date,
        agreed_date=agreed_date,
        actions=list(actions or []),
    )


# -- vocabularies ------------------------------------------------------------


def test_vocabularies_are_the_expected_sets() -> None:
    assert ALL_INTERFACE_TYPES == (
        "physical",
        "functional",
        "contractual",
        "spatial",
        "information",
        "schedule",
    )
    assert ALL_INTERFACE_STATUSES == (
        "identified",
        "open",
        "in_progress",
        "agreed",
        "closed",
        "disputed",
        "on_hold",
    )
    assert ALL_PRIORITIES == ("low", "medium", "high", "critical")
    assert ALL_ACTION_STATUSES == ("open", "done", "cancelled")
    assert UNASSIGNED == "unassigned"


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


# -- ActionRow / open_action_count -------------------------------------------


def test_action_is_open_only_for_open_status() -> None:
    assert _action("open").is_open is True
    assert _action("done").is_open is False
    assert _action("cancelled").is_open is False
    assert _action("mystery").is_open is False  # unknown never counts as open


def test_open_action_count_counts_only_open() -> None:
    iface = _iface(actions=[_action("open"), _action("open"), _action("done"), _action("cancelled")])
    assert open_action_count(iface) == 2


def test_open_action_count_zero_when_no_actions() -> None:
    assert open_action_count(_iface()) == 0


def test_total_open_actions_sums_across_interfaces() -> None:
    interfaces = [
        _iface(reference="a", actions=[_action("open"), _action("open")]),
        _iface(reference="b", actions=[_action("done")]),
        _iface(reference="c", actions=[_action("open")]),
    ]
    assert total_open_actions(interfaces) == 3


# -- InterfaceRow status predicates ------------------------------------------


def test_is_resolved_only_for_agreed_or_closed() -> None:
    for settled in ("agreed", "closed"):
        assert _iface(status=settled).is_resolved is True
    for live in ("identified", "open", "in_progress", "disputed", "on_hold"):
        assert _iface(status=live).is_resolved is False


def test_is_open_is_the_complement_of_resolved() -> None:
    for live in ("identified", "open", "in_progress", "disputed", "on_hold"):
        assert _iface(status=live).is_open is True
    for settled in ("agreed", "closed"):
        assert _iface(status=settled).is_open is False


def test_is_disputed_only_for_disputed() -> None:
    assert _iface(status="disputed").is_disputed is True
    for other in ("identified", "open", "in_progress", "agreed", "closed", "on_hold"):
        assert _iface(status=other).is_disputed is False


# -- is_overdue --------------------------------------------------------------


def test_overdue_true_when_past_due_and_not_settled() -> None:
    for live in ("identified", "open", "in_progress", "disputed"):
        assert is_overdue(_iface(status=live, need_by_date=_PAST), _AS_OF) is True


def test_overdue_false_when_settled_or_on_hold_even_if_past_due() -> None:
    # agreed / closed / on_hold are never overdue, even with a past need-by date.
    for exempt in ("agreed", "closed", "on_hold"):
        assert is_overdue(_iface(status=exempt, need_by_date=_PAST), _AS_OF) is False


def test_overdue_boundary_is_not_overdue() -> None:
    # need_by_date exactly equal to as_of is NOT overdue (strict less-than).
    assert is_overdue(_iface(status="open", need_by_date=_AS_OF), _AS_OF) is False


def test_overdue_false_for_future_or_undated() -> None:
    assert is_overdue(_iface(status="open", need_by_date=_FUTURE), _AS_OF) is False
    assert is_overdue(_iface(status="open", need_by_date=None), _AS_OF) is False


def test_overdue_interfaces_filters_and_preserves_order() -> None:
    interfaces = [
        _iface(reference="a", status="open", need_by_date=_PAST),
        _iface(reference="b", status="agreed", need_by_date=_PAST),  # exempt
        _iface(reference="c", status="disputed", need_by_date=_PAST),
        _iface(reference="d", status="open", need_by_date=_FUTURE),  # not yet due
    ]
    assert [i.reference for i in overdue_interfaces(interfaces, _AS_OF)] == ["a", "c"]


def test_disputed_interfaces_filters_and_preserves_order() -> None:
    interfaces = [
        _iface(reference="a", status="disputed"),
        _iface(reference="b", status="open"),
        _iface(reference="c", status="disputed"),
    ]
    assert [i.reference for i in disputed_interfaces(interfaces)] == ["a", "c"]


# -- status_counts -----------------------------------------------------------


def test_status_counts_zero_fills_every_status() -> None:
    counts = status_counts([])
    assert set(counts.keys()) == set(ALL_INTERFACE_STATUSES)
    assert all(v == 0 for v in counts.values())
    assert list(counts.keys()) == list(ALL_INTERFACE_STATUSES)


def test_status_counts_tallies_each_status() -> None:
    interfaces = [
        _iface(status="open"),
        _iface(status="open"),
        _iface(status="agreed"),
        _iface(status="disputed"),
    ]
    counts = status_counts(interfaces)
    assert counts["open"] == 2
    assert counts["agreed"] == 1
    assert counts["disputed"] == 1
    assert counts["closed"] == 0


def test_status_counts_defensive_on_unknown_status() -> None:
    counts = status_counts([_iface(status="mystery")])
    assert counts["mystery"] == 1
    for known in ALL_INTERFACE_STATUSES:
        assert known in counts


# -- priority_counts ---------------------------------------------------------


def test_priority_counts_zero_fills_and_buckets_unassigned() -> None:
    counts = priority_counts([])
    assert counts == {"low": 0, "medium": 0, "high": 0, "critical": 0, UNASSIGNED: 0}


def test_priority_counts_tallies_and_sums_to_total() -> None:
    interfaces = [
        _iface(priority="high"),
        _iface(priority="critical"),
        _iface(priority="critical"),
        _iface(priority=None),
    ]
    counts = priority_counts(interfaces)
    assert counts["high"] == 1
    assert counts["critical"] == 2
    assert counts["low"] == 0
    assert counts[UNASSIGNED] == 1
    assert sum(counts.values()) == len(interfaces)


def test_priority_counts_defensive_on_unknown_priority() -> None:
    counts = priority_counts([_iface(priority="blocker")])
    assert counts["blocker"] == 1
    assert sum(counts.values()) == 1


# -- type_counts -------------------------------------------------------------


def test_type_counts_zero_fills_and_buckets_unassigned() -> None:
    counts = type_counts([])
    assert set(counts.keys()) == {*ALL_INTERFACE_TYPES, UNASSIGNED}
    assert all(v == 0 for v in counts.values())


def test_type_counts_tallies_and_sums_to_total() -> None:
    interfaces = [
        _iface(interface_type="physical"),
        _iface(interface_type="functional"),
        _iface(interface_type="functional"),
        _iface(interface_type=None),
    ]
    counts = type_counts(interfaces)
    assert counts["physical"] == 1
    assert counts["functional"] == 2
    assert counts["spatial"] == 0
    assert counts[UNASSIGNED] == 1
    assert sum(counts.values()) == len(interfaces)


def test_type_counts_defensive_on_unknown_type() -> None:
    counts = type_counts([_iface(interface_type="thermal")])
    assert counts["thermal"] == 1
    assert sum(counts.values()) == 1


# -- resolved_count / agreed_pct ---------------------------------------------


def test_resolved_count_counts_agreed_and_closed() -> None:
    interfaces = [
        _iface(status="agreed"),
        _iface(status="closed"),
        _iface(status="open"),
        _iface(status="disputed"),
    ]
    assert resolved_count(interfaces) == 2


def test_agreed_pct_empty_is_none() -> None:
    assert agreed_pct([]) is None


def test_agreed_pct_ratio_over_total() -> None:
    interfaces = [
        _iface(status="agreed"),
        _iface(status="closed"),
        _iface(status="open"),
        _iface(status="identified"),
    ]
    result = agreed_pct(interfaces)
    assert result == Decimal("50.00")
    assert isinstance(result, Decimal)


def test_agreed_pct_full() -> None:
    assert agreed_pct([_iface(status="agreed"), _iface(status="closed")]) == Decimal("100.00")


# -- overall_health_score / is_healthy ---------------------------------------


def test_overall_health_score_empty_is_none() -> None:
    assert overall_health_score([], _AS_OF) is None


def test_overall_health_score_all_healthy_is_100() -> None:
    interfaces = [_iface(status="agreed"), _iface(status="open", need_by_date=_FUTURE)]
    assert overall_health_score(interfaces, _AS_OF) == Decimal("100.00")


def test_overall_health_score_counts_overdue_share() -> None:
    interfaces = [
        _iface(reference="a", status="open", need_by_date=_PAST),  # overdue
        _iface(reference="b", status="open", need_by_date=_PAST),  # overdue
        _iface(reference="c", status="agreed"),
        _iface(reference="d", status="open", need_by_date=_FUTURE),
    ]
    # 2 overdue of 4 -> (4-2)/4 = 50.
    assert overall_health_score(interfaces, _AS_OF) == Decimal("50.00")


def test_is_healthy_true_when_no_overdue_and_no_disputed() -> None:
    interfaces = [_iface(status="agreed"), _iface(status="open", need_by_date=_FUTURE)]
    assert is_healthy(interfaces, _AS_OF) is True


def test_is_healthy_false_when_overdue() -> None:
    interfaces = [_iface(status="open", need_by_date=_PAST)]
    assert is_healthy(interfaces, _AS_OF) is False


def test_is_healthy_false_when_disputed_even_if_nothing_overdue() -> None:
    # A dispute with no need-by date is not overdue, but still makes the
    # register unhealthy.
    interfaces = [_iface(status="disputed", need_by_date=None)]
    assert is_healthy(interfaces, _AS_OF) is False


def test_is_healthy_empty_is_vacuously_true() -> None:
    assert is_healthy([], _AS_OF) is True


# -- work_package_health -----------------------------------------------------


def test_work_package_health_groups_and_orders_unassigned_last() -> None:
    interfaces = [
        _iface(reference="a", work_package_from="WP-B"),
        _iface(reference="b", work_package_from="WP-A"),
        _iface(reference="c", work_package_from=None),
        _iface(reference="d", work_package_from="   "),  # blank -> unassigned
    ]
    packages = work_package_health(interfaces, _AS_OF)
    assert [p.work_package for p in packages] == ["WP-A", "WP-B", UNASSIGNED]
    # None and blank both fold into the single unassigned bucket.
    unassigned = next(p for p in packages if p.work_package == UNASSIGNED)
    assert unassigned.total == 2


def test_work_package_health_counts_and_score() -> None:
    interfaces = [
        _iface(reference="a", status="agreed", work_package_from="WP-A"),
        _iface(reference="b", status="open", work_package_from="WP-A", need_by_date=_PAST),  # overdue
        _iface(reference="c", status="open", work_package_from="WP-A", need_by_date=_FUTURE),
    ]
    (wp_a,) = work_package_health(interfaces, _AS_OF)
    assert wp_a.work_package == "WP-A"
    assert wp_a.total == 3
    assert wp_a.overdue == 1
    assert wp_a.open == 2  # the two open interfaces (agreed one excluded)
    assert wp_a.agreed == 1  # the agreed interface
    # (3 - 1) / 3 = 66.67
    assert wp_a.health_score == Decimal("66.67")


def test_work_package_health_score_zero_when_all_overdue() -> None:
    interfaces = [_iface(reference="a", status="open", work_package_from="WP-Z", need_by_date=_PAST)]
    (wp,) = work_package_health(interfaces, _AS_OF)
    assert wp.health_score == Decimal("0.00")


def test_work_package_health_empty_is_empty_list() -> None:
    assert work_package_health([], _AS_OF) == []


# -- build_report ------------------------------------------------------------


def _sample_interfaces() -> list[InterfaceRow]:
    return [
        _iface(
            reference="IF-1",
            status="agreed",
            priority="high",
            interface_type="physical",
            work_package_from="WP-A",
            iface_id="1",
            actions=[_action("open"), _action("done")],
        ),
        _iface(
            reference="IF-2",
            status="disputed",
            priority="critical",
            interface_type="functional",
            work_package_from="WP-A",
            need_by_date=_PAST,  # disputed + past due -> overdue
            iface_id="2",
            actions=[_action("open")],
        ),
        _iface(
            reference="IF-3",
            status="open",
            priority="medium",
            interface_type=None,
            work_package_from="WP-B",
            need_by_date=_PAST,  # overdue
            iface_id="3",
        ),
        _iface(
            reference="IF-4",
            status="closed",
            priority=None,
            interface_type="schedule",
            work_package_from=None,
            iface_id="4",
        ),
    ]


def test_build_report_returns_register_and_totals() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert isinstance(report, InterfaceRegister)
    assert report.total == 4


def test_build_report_per_status_counts() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert report.per_status["agreed"] == 1
    assert report.per_status["disputed"] == 1
    assert report.per_status["open"] == 1
    assert report.per_status["closed"] == 1
    assert report.per_status["identified"] == 0


def test_build_report_per_priority_counts() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert report.per_priority["high"] == 1
    assert report.per_priority["critical"] == 1
    assert report.per_priority["medium"] == 1
    assert report.per_priority[UNASSIGNED] == 1  # IF-4 has no priority
    assert report.per_priority["low"] == 0
    assert sum(report.per_priority.values()) == 4


def test_build_report_per_type_counts() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert report.per_type["physical"] == 1
    assert report.per_type["functional"] == 1
    assert report.per_type["schedule"] == 1
    assert report.per_type[UNASSIGNED] == 1  # IF-3 has no type
    assert report.per_type["spatial"] == 0
    assert sum(report.per_type.values()) == 4


def test_build_report_overdue_and_disputed() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert [i.reference for i in report.overdue] == ["IF-2", "IF-3"]
    assert [i.reference for i in report.disputed] == ["IF-2"]


def test_build_report_agreement_health_and_actions() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    # Resolved = IF-1 (agreed) + IF-4 (closed) = 2 of 4.
    assert report.agreed_pct == Decimal("50.00")
    # Overdue = IF-2, IF-3 -> (4-2)/4 = 50.
    assert report.overall_health_score == Decimal("50.00")
    # Open actions: IF-1 has 1, IF-2 has 1, others 0.
    assert report.total_open_actions == 2
    # Overdue present -> not healthy.
    assert report.is_healthy is False


def test_build_report_work_packages() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    assert [p.work_package for p in report.work_packages] == ["WP-A", "WP-B", UNASSIGNED]
    wp_a = report.work_packages[0]
    assert wp_a.total == 2
    assert wp_a.overdue == 1  # IF-2
    assert wp_a.agreed == 1  # IF-1
    assert wp_a.open == 1  # IF-2 (disputed) is open; IF-1 (agreed) is not
    assert wp_a.health_score == Decimal("50.00")
    unassigned = report.work_packages[2]
    assert unassigned.total == 1
    assert unassigned.agreed == 1  # IF-4 closed
    assert unassigned.health_score == Decimal("100.00")


def test_build_report_healthy_sample() -> None:
    interfaces = [
        _iface(reference="H-1", status="agreed", work_package_from="WP-A"),
        _iface(reference="H-2", status="open", work_package_from="WP-A", need_by_date=_FUTURE),
    ]
    report = build_report(interfaces, _AS_OF)
    assert report.is_healthy is True
    assert report.overall_health_score == Decimal("100.00")
    assert report.overdue == []
    assert report.disputed == []


def test_build_report_empty_is_well_formed() -> None:
    report = build_report([], _AS_OF)
    assert report.total == 0
    assert report.agreed_pct is None  # guarded, not a crash
    assert report.overall_health_score is None  # guarded
    assert report.total_open_actions == 0
    assert report.is_healthy is True
    assert report.overdue == []
    assert report.disputed == []
    assert report.work_packages == []
    # Counts are still fully zero-filled.
    assert set(report.per_status.keys()) == set(ALL_INTERFACE_STATUSES)
    assert report.per_priority[UNASSIGNED] == 0
    assert report.per_type[UNASSIGNED] == 0


# -- to_ref / to_dict shapes -------------------------------------------------


def test_interface_to_ref_has_iso_dates_and_open_actions() -> None:
    iface = _iface(
        reference="IF-5",
        need_by_date=_PAST,
        agreed_date=_FUTURE,
        actions=[_action("open"), _action("done")],
    )
    ref = iface.to_ref()
    assert ref["reference"] == "IF-5"
    assert ref["need_by_date"] == "2026-07-01"
    assert ref["agreed_date"] == "2026-07-26"
    assert ref["open_action_count"] == 1


def test_interface_to_ref_null_dates() -> None:
    ref = _iface().to_ref()
    assert ref["need_by_date"] is None
    assert ref["agreed_date"] is None


def test_work_package_health_to_dict_keeps_decimal() -> None:
    wp = WorkPackageHealth(
        work_package="WP-A",
        total=2,
        open=1,
        overdue=1,
        agreed=1,
        health_score=Decimal("50.00"),
    )
    d = wp.to_dict()
    assert d["work_package"] == "WP-A"
    assert d["health_score"] == Decimal("50.00")
    assert isinstance(d["health_score"], Decimal)


def test_register_to_dict_keeps_decimal_and_shapes() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    d = report.to_dict()
    assert d["as_of"] == "2026-07-16"
    assert d["total"] == 4
    assert d["is_healthy"] is False
    # Percentages stay Decimal in the pure dict (schema serialises to string).
    assert d["agreed_pct"] == Decimal("50.00")
    assert d["overall_health_score"] == Decimal("50.00")
    assert isinstance(d["agreed_pct"], Decimal)
    assert d["disputed"][0]["reference"] == "IF-2"
    assert d["overdue"][0]["reference"] == "IF-2"
    assert d["work_packages"][0]["work_package"] == "WP-A"


def test_register_to_dict_empty_percents_are_none() -> None:
    d = build_report([], _AS_OF).to_dict()
    assert d["agreed_pct"] is None
    assert d["overall_health_score"] is None


# -- schema alignment (pure core <-> API contract) ---------------------------


def test_register_dict_validates_against_response_schema() -> None:
    report = build_report(_sample_interfaces(), _AS_OF)
    payload = report.to_dict()
    payload["project_id"] = "11111111-1111-1111-1111-111111111111"
    model = InterfaceRegisterResponse.model_validate(payload)
    assert model.total == 4
    assert model.is_healthy is False
    assert model.disputed[0].reference == "IF-2"
    assert model.overdue[0].reference == "IF-2"
    assert model.work_packages[0].work_package == "WP-A"
    # Percentages serialise to plain decimal strings in JSON mode.
    dumped = model.model_dump(mode="json")
    assert dumped["agreed_pct"] == "50.00"
    assert dumped["overall_health_score"] == "50.00"
    assert dumped["work_packages"][0]["health_score"] == "50.00"


def test_register_response_serialises_none_percents() -> None:
    payload = build_report([], _AS_OF).to_dict()
    payload["project_id"] = "22222222-2222-2222-2222-222222222222"
    model = InterfaceRegisterResponse.model_validate(payload)
    dumped = model.model_dump(mode="json")
    assert dumped["agreed_pct"] is None
    assert dumped["overall_health_score"] is None


def test_work_package_health_dict_validates_against_report_schema() -> None:
    # Mirror exactly how InterfaceManagementService.get_work_package_health
    # assembles its dict, so the schema contract for that endpoint is exercised
    # without a database.
    interfaces = _sample_interfaces()
    packages = work_package_health(interfaces, _AS_OF)
    overdue = overdue_interfaces(interfaces, _AS_OF)
    disputed = disputed_interfaces(interfaces)
    payload = {
        "project_id": "33333333-3333-3333-3333-333333333333",
        "as_of": _AS_OF.isoformat(),
        "total": len(interfaces),
        "is_healthy": is_healthy(interfaces, _AS_OF),
        "work_packages": [p.to_dict() for p in packages],
        "overdue": [i.to_ref() for i in overdue],
        "disputed": [i.to_ref() for i in disputed],
    }
    model = WorkPackageHealthReportResponse.model_validate(payload)
    assert model.total == 4
    assert model.is_healthy is False
    assert [p.work_package for p in model.work_packages] == ["WP-A", "WP-B", UNASSIGNED]
    assert [i.reference for i in model.overdue] == ["IF-2", "IF-3"]
    assert [i.reference for i in model.disputed] == ["IF-2"]
    # Per-package health score serialises to a plain string in JSON mode.
    dumped = model.model_dump(mode="json")
    assert dumped["work_packages"][0]["health_score"] == "50.00"


def test_the_seeder_reserved_prefix_satisfies_the_registers_own_overdue_rule() -> None:
    """The demo seeder's reserved prefix has to hold against this core, not beside it.

    The register exempts three statuses from ever being overdue and the seeder
    picks a status before it holds a row, so the two have to agree on which
    ones can carry the overdue tile. They disagreed once - the seeder reused
    its own settled pair and handed paused (on_hold) rows a past date the
    report then refused to count - which left the tile empty on roughly one
    register in eighty. Asserted here across many draws because the failure is
    a draw, and without a database because it is a property of the two rules
    rather than of anything written down.
    """
    import random

    from app.modules.interface_management.seed import (
        _RESERVED_OVERDUE_INDEX,
        _SETTLED,
        _dates_for,
        _reserved_statuses,
    )

    today = date(2026, 6, 30)
    for seed in range(2000):
        rng = random.Random(seed)
        reserved = _reserved_statuses(rng)
        assert len(set(reserved)) == 4, f"the reserved prefix repeats a status: {reserved}"
        assert len([status for status in reserved if status in _SETTLED]) == 2, (
            f"the reserved prefix leaves the agreed figure with nothing behind it: {reserved}"
        )
        for status in reserved:
            assert status in ALL_INTERFACE_STATUSES, f"{status!r} is not a status this register knows"

        # The whole chain the guarantee rests on, walked end to end rather than
        # asserted at its first link: the reserved position holds a status this
        # register can call overdue, the seeder dates that row into the past,
        # and the register's own predicate then says so. Every seeded register
        # carries this row, so a register with an empty overdue tile cannot be
        # drawn - which is the property, not an observation about one run.
        status = reserved[_RESERVED_OVERDUE_INDEX]
        assert can_be_overdue(status), (
            f"the reserved overdue position holds {status!r}, which this register never counts as overdue"
        )
        need_by, _agreed, _closed = _dates_for(rng, status, today=today, overdue=True)
        assert need_by < today, f"the reserved overdue row is dated {need_by}, which is not in the past"
        assert is_overdue(_iface(status=status, need_by_date=need_by), today), (
            f"a {status!r} row dated {need_by} is not overdue to the register that has to display it"
        )
