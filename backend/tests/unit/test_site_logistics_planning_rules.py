"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of the site-logistics plan (framework module 11): no database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.modules.site_logistics import planning as pl
from app.modules.site_logistics.catalogue import (
    INCOTERM_CODES_2020,
    DocumentRule,
    SiteLogisticsCatalogue,
    has_figure,
    resolved_shipped,
    shipped_catalogues,
    validate_site_logistics_catalogue,
)
from app.modules.site_logistics.geometry import GeometryError, polygon_area_m2, polygons_overlap, validate_polygon

D = Decimal


def _square(x: float, y: float, side: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + side, y], [x + side, y + side], [x, y + side], [x, y]]],
    }


# ── State machines ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fsm", "current", "target", "allowed"),
    [
        (pl.STAGE_FSM, "planned", "active", True),
        (pl.STAGE_FSM, "planned", "closed", False),
        (pl.STAGE_FSM, "closed", "active", False),
        (pl.TRANSPORT_FSM, "planned", "scheduled", True),
        (pl.TRANSPORT_FSM, "planned", "in_transit", False),
        (pl.TRANSPORT_FSM, "in_transit", "cancelled", False),
        (pl.TRANSPORT_FSM, "arrived", "closed", True),
        (pl.PERMIT_FSM, "draft", "granted", False),
        (pl.PERMIT_FSM, "applied", "granted", True),
        (pl.PERMIT_FSM, "refused", "applied", False),
        (pl.CUSTOMS_FSM, "open", "declared", False),
        (pl.CUSTOMS_FSM, "held", "cleared", True),
        (pl.MEDIA_FSM, "offered", "contracted", True),
        (pl.MEDIA_FSM, "identified", "connected", False),
        (pl.COMPLAINT_FSM, "received", "closed", False),
        (pl.COMPLAINT_FSM, "acknowledged", "closed", True),
        (pl.CUSTOMS_DOCUMENT_FSM, "missing", "verified", False),
    ],
)
def test_state_machines(fsm, current, target, allowed) -> None:
    assert pl.can_move(fsm, current, target) is allowed


def test_terminal_states_have_no_exit() -> None:
    for fsm, terminal in (
        (pl.TRANSPORT_FSM, ("closed", "cancelled")),
        (pl.PERMIT_FSM, ("refused", "expired")),
        (pl.CUSTOMS_FSM, ("closed",)),
        (pl.COMPLAINT_FSM, ("closed",)),
    ):
        for state in terminal:
            assert fsm[state] == ()


def test_unknown_state_is_refused() -> None:
    assert pl.can_move(pl.TRANSPORT_FSM, "nonsense", "scheduled") is False


# ── Area balance ───────────────────────────────────────────────────────────


class _Kind:
    def __init__(self, group: str, counts: bool = True) -> None:
        self.balance_group = group
        self.counts_in_balance = counts


KINDS = {
    "building": _Kind("built"),
    "storage": _Kind("logistics"),
    "reserve": _Kind("reserve"),
    "public_road": _Kind("external", counts=False),
}


def _alloc(kind: str, m2: str, area_id: str | None = None, **kw) -> pl.AllocationFact:
    return pl.AllocationFact(area_id or kind, kind, D(m2), **kw)


def test_balance_closes_exactly() -> None:
    bal = pl.area_balance(
        [_alloc("site_total", "10000"), _alloc("building", "6000"), _alloc("storage", "4000")], KINDS, D("2")
    )
    assert bal.closed is True
    assert bal.difference_m2 == 0
    assert bal.by_group == {"built": D("6000"), "logistics": D("4000")}


@pytest.mark.parametrize(("counted", "closed"), [("9800", True), ("10200", True), ("9799", False), ("10201", False)])
def test_balance_tolerance_edge(counted: str, closed: bool) -> None:
    building = D(counted) - D("1000")
    bal = pl.area_balance(
        [_alloc("site_total", "10000"), _alloc("building", str(building)), _alloc("storage", "1000")], KINDS, D("2")
    )
    assert bal.closed is closed


def test_balance_ignores_kinds_that_do_not_count() -> None:
    bal = pl.area_balance(
        [_alloc("site_total", "100"), _alloc("building", "100"), _alloc("public_road", "500")], KINDS, D("0")
    )
    assert bal.closed is True
    assert bal.by_kind["public_road"] == D("500")


def test_balance_without_site_total_uses_fallback_then_reports() -> None:
    fallback = pl.area_balance([_alloc("building", "100")], KINDS, D("0"), site_total_fallback_m2=D("100"))
    assert fallback.closed is True
    missing = pl.area_balance([_alloc("building", "100")], KINDS, D("0"))
    assert (missing.closed, missing.reason) == (False, "no_site_total")


def test_balance_as_dict_is_json_safe() -> None:
    bal = pl.area_balance([_alloc("site_total", "10"), _alloc("building", "9.5")], KINDS, D("10"))
    json.dumps(bal.as_dict())


def test_allocation_exceeds_area() -> None:
    assert pl.allocation_exceeds_area(D("101"), D("100")) is True
    assert pl.allocation_exceeds_area(D("100"), D("100")) is False
    assert pl.allocation_exceeds_area(D("1e6"), None) is False


def test_stage_gaps() -> None:
    assert pl.stage_gaps(["laydown", "site_setup"]) == []
    assert pl.stage_gaps(["building"]) == ["stage_without_storage", "stage_without_site_setup"]


# ── Geometry and overlap ───────────────────────────────────────────────────


def test_polygon_area_local_and_wgs84() -> None:
    assert polygon_area_m2(_square(0, 0, 50)) == D("2500.00")
    # 0.001 degree square at the equator is about 111.2 m on each side.
    area = polygon_area_m2(_square(0, 0, 0.001), frame="wgs84")
    assert D("12300") < area < D("12400")


@pytest.mark.parametrize(
    ("b", "overlap"),
    [
        (_square(5, 5, 10), True),  # edges cross
        (_square(2, 2, 2), True),  # fully inside
        (_square(10, 0, 10), False),  # shares an edge only
        (_square(20, 20, 5), False),  # apart
    ],
)
def test_polygons_overlap(b: dict, overlap: bool) -> None:
    assert polygons_overlap(_square(0, 0, 10), b) is overlap


def test_identical_polygons_overlap() -> None:
    assert polygons_overlap(_square(0, 0, 10), _square(0, 0, 10)) is True


def _rect(x0: float, y0: float, w: float, h: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0]]]}


@pytest.mark.parametrize(
    ("a", "b", "overlap"),
    [
        # Inside the other and flush with two of its sides: no edge crosses, no vertex is strictly inside.
        (_rect(0, 0, 10, 10), _rect(0, 0, 5, 5), True),
        # Same width, half the height: every vertex of the small one lies on the boundary of the large one.
        (_rect(0, 0, 10, 10), _rect(0, 0, 10, 5), True),
        # A cross: neither has a vertex inside the other.
        (_rect(4, -5, 2, 20), _rect(-5, 4, 20, 2), True),
        # Neighbours along a whole side, and along part of one: they share a boundary, not an area.
        (_rect(0, 0, 10, 10), _rect(10, 0, 10, 10), False),
        (_rect(0, 0, 10, 10), _rect(10, 2, 4, 4), False),
        # Touching in one corner only.
        (_rect(0, 0, 10, 10), _rect(10, 10, 5, 5), False),
    ],
)
def test_polygons_sharing_a_boundary(a: dict, b: dict, overlap: bool) -> None:
    assert polygons_overlap(a, b) is overlap
    assert polygons_overlap(b, a) is overlap


@pytest.mark.parametrize(
    ("geometry", "frame"),
    [
        (_rect(0, 0, 2e7, 10), "local"),  # farther than any site reaches
        (_rect(170, 0, 20, 1), "wgs84"),  # longitude 190
        (_rect(0, 80, 1, 20), "wgs84"),  # latitude 100
        ({"type": "Polygon", "coordinates": [[[0, 0], [float("nan"), 0], [1, 1], [0, 0]]]}, "local"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [float("inf"), 0], [1, 1], [0, 0]]]}, "local"),
    ],
)
def test_coordinates_are_bounded(geometry: dict, frame: str) -> None:
    with pytest.raises(GeometryError):
        validate_polygon(geometry, frame)


def test_hole_is_subtracted_and_must_lie_inside() -> None:
    outer = _rect(0, 0, 10, 10)["coordinates"][0]
    inner = _rect(2, 2, 4, 4)["coordinates"][0]
    assert polygon_area_m2({"type": "Polygon", "coordinates": [outer, inner]}) == D("84.00")
    outside = _rect(20, 20, 4, 4)["coordinates"][0]
    with pytest.raises(GeometryError):
        polygon_area_m2({"type": "Polygon", "coordinates": [outer, outside]})


def test_overlapping_pairs_skip_same_kind_and_site_total() -> None:
    rows = [
        _alloc("building", "1", "a", geometry=_square(0, 0, 10)),
        _alloc("storage", "1", "b", geometry=_square(5, 5, 10)),
        _alloc("storage", "1", "c", geometry=_square(6, 6, 10)),
        _alloc("site_total", "1", "t", geometry=_square(0, 0, 100)),
    ]
    assert pl.overlapping_pairs(rows) == [("a", "b"), ("a", "c")]


@pytest.mark.parametrize(
    "geometry",
    [{"type": "Point", "coordinates": [0, 0]}, {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}, {}],
)
def test_validate_polygon_rejects(geometry: dict) -> None:
    with pytest.raises(GeometryError):
        validate_polygon(geometry)


# ── Heavy loads and permits ────────────────────────────────────────────────

GATE = {"max_axle_load_t": D("11.5"), "max_gross_t": D("40"), "max_height_m": D("4"), "max_width_m": D("2.55")}


def test_exceeded_limits() -> None:
    truck = {"axle_load_t": "10", "gross_weight_t": "38", "height_m": "3.9"}
    assert pl.exceeded_limits(truck, GATE) == []
    over = {**truck, "gross_weight_t": "84", "width_m": "3.4"}
    assert pl.exceeded_limits(over, GATE) == ["gross_weight_t", "width_m"]


CLASSES = {"class_40": {"max_gross_t": D("40")}, "class_44": {"max_gross_t": D("44")}}


def test_heavy_is_measured_against_the_chosen_class() -> None:
    truck = {"gross_weight_t": "42"}
    assert pl.is_heavy(truck, CLASSES, chosen="class_40") is True
    assert pl.is_heavy(truck, CLASSES, chosen="class_44") is False


def test_heavy_without_a_choice_uses_the_most_permissive_class() -> None:
    # 42 t exceeds the 40 t class, but the 44 t class admits it: an ordinary truck, not a heavy transport.
    assert pl.is_heavy({"gross_weight_t": "42"}, CLASSES) is False
    assert pl.is_heavy({"gross_weight_t": "62"}, CLASSES) is True
    assert pl.is_heavy({"gross_weight_t": "38"}, CLASSES) is False


def test_heavy_by_kind_and_without_classes() -> None:
    assert pl.is_heavy({"gross_weight_t": "5"}, CLASSES, always_heavy=True) is True
    assert pl.is_heavy({"gross_weight_t": "500"}, {}) is False


def test_unset_values_and_limits_are_not_exceeded() -> None:
    assert pl.exceeded_limits({"gross_weight_t": "99"}, {}) == []
    assert pl.limits_unknown({}) is True
    assert pl.limits_unknown(GATE) is False


def test_limits_from_class() -> None:
    class Cls:
        axle_load_t = D("11.5")
        gross_weight_t = D("40")
        max_height_m = D("4")
        max_width_m = None
        max_length_m = None
        turning_radius_m = None

    limits = pl.limits_from_class(Cls())
    assert limits["max_gross_t"] == D("40")
    assert pl.exceeded_limits({"axle_load_t": "12"}, limits) == ["axle_load_t"]


# The site clock of these tests. Not UTC on purpose: in October 2026 it is two
# hours ahead until the 25th and one hour after, so a rule that reads the UTC
# clock, or the offset a client sent, gives a different answer.
SITE = ZoneInfo("Europe/Berlin")


def _dt(day: int, h: int, m: int = 0) -> datetime:
    """A moment on the site clock."""
    return datetime(2026, 10, day, h, m, tzinfo=SITE)


def _utc(day: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=UTC)


NIGHT = [{"weekdays": [0, 1, 2, 3, 4], "from": "22:00", "to": "06:00"}]


def test_overnight_window_contains_a_run_across_midnight() -> None:
    # 2026-10-12 is a Monday.
    assert pl.window_in_allowed(NIGHT, _dt(12, 23), _dt(13, 4), SITE) is True
    assert pl.window_in_allowed(NIGHT, _dt(13, 1), _dt(13, 5), SITE) is True  # started Monday night
    assert pl.window_in_allowed(NIGHT, _dt(12, 21), _dt(12, 23), SITE) is False
    assert pl.window_in_allowed(NIGHT, _dt(13, 5), _dt(13, 7), SITE) is False


def test_overnight_window_respects_weekday_of_start() -> None:
    # Saturday 2026-10-17 night is not allowed; neither is the Sunday morning after it.
    assert pl.window_in_allowed(NIGHT, _dt(17, 23), _dt(18, 2), SITE) is False
    assert pl.window_in_allowed(NIGHT, _dt(18, 1), _dt(18, 2), SITE) is False


def test_no_windows_means_no_time_restriction() -> None:
    assert pl.window_in_allowed(None, _dt(12, 12), _dt(12, 13), SITE) is True


def test_windows_are_read_on_the_site_clock_not_on_the_offset_sent() -> None:
    # 20:30 to 21:30 UTC on Monday is 22:30 to 23:30 on site: inside the night window.
    assert pl.window_in_allowed(NIGHT, _utc(12, 20, 30), _utc(12, 21, 30), SITE) is True
    # 22:30 UTC is 00:30 on site on Tuesday, still the Monday night occurrence.
    assert pl.window_in_allowed(NIGHT, _utc(12, 22, 30), _utc(12, 23, 30), SITE) is True
    # 04:30 to 05:30 UTC is 06:30 to 07:30 on site: outside, though the UTC clock reads "before 06:00".
    assert pl.window_in_allowed(NIGHT, _utc(13, 4, 30), _utc(13, 5, 30), SITE) is False
    # Friday 22:30 UTC is Saturday 00:30 on site, which belongs to the Friday night occurrence.
    assert pl.window_in_allowed(NIGHT, _utc(16, 22, 30), _utc(16, 23, 30), SITE) is True
    # Sunday 20:30 UTC is Sunday 22:30 on site: Sunday is not an allowed weekday.
    assert pl.window_in_allowed(NIGHT, _utc(18, 20, 30), _utc(18, 21, 30), SITE) is False


def test_site_zone_names() -> None:
    assert pl.site_zone("Europe/Berlin") == SITE
    assert pl.site_zone(None) is None
    assert pl.site_zone("") is None
    assert pl.site_zone("Mars/Olympus") is None


def test_local_refuses_a_naive_moment() -> None:
    with pytest.raises(ValueError, match="naive"):
        pl.local(datetime(2026, 10, 12, 8, 0), SITE)


def test_within_hours_on_the_site_clock() -> None:
    # 05:30 UTC is 07:30 on site: inside 07:00 to 18:00 although the UTC clock reads 05:30.
    assert pl.within_hours("07:00", "18:00", _utc(12, 5, 30), _utc(12, 6, 30), SITE) is True
    # 16:30 UTC is 18:30 on site: after closing although the UTC clock reads 16:30.
    assert pl.within_hours("07:00", "18:00", _utc(12, 15, 30), _utc(12, 16, 30), SITE) is False
    # 22:30 to 23:30 UTC is one UTC day but crosses the site's midnight.
    assert pl.within_hours("00:00", "23:59", _utc(12, 21, 30), _utc(12, 22, 30), SITE) is False


def test_starts_per_hour_counts_site_hours() -> None:
    counts = pl.starts_per_hour([_utc(12, 6, 5), _utc(12, 6, 55), _dt(12, 8, 30), _dt(12, 9, 0)], SITE)
    assert counts == {_dt(12, 8): 3, _dt(12, 9): 1}


def _permit(state: str = "granted", **kw) -> dict:
    return {
        "permit_kind": "oversize",
        "state": state,
        "valid_from": date(2026, 10, 1),
        "valid_to": date(2026, 10, 31),
        "allowed_windows": NIGHT,
        **kw,
    }


def test_heavy_permit_finding() -> None:
    start, end = _dt(12, 23), _dt(13, 3)
    assert pl.heavy_permit_finding([], start, end, ["oversize"], SITE) == "heavy_without_permit"
    assert pl.heavy_permit_finding([_permit("applied")], start, end, ["oversize"], SITE) == "heavy_without_permit"
    assert pl.heavy_permit_finding([_permit()], start, end, ["night_work"], SITE) == "heavy_without_permit"
    assert pl.heavy_permit_finding([_permit()], start, end, ["oversize"], SITE) is None
    assert pl.heavy_permit_finding([_permit()], _dt(12, 10), _dt(12, 12), ["oversize"], SITE) == "window_outside_permit"
    assert pl.heavy_permit_finding([_permit()], None, None, ["oversize"], SITE) == "window_outside_permit"


def test_covering_permit_names_the_permit_that_covers() -> None:
    start, end = _dt(12, 23), _dt(13, 3)
    granted = _permit(reference="OS-1")
    assert pl.covering_permit([_permit("applied"), granted], start, end, ["oversize"], SITE) is granted
    assert pl.covering_permit([granted], start, end, ["night_work"], SITE) is None
    assert pl.covering_permit([granted], _dt(12, 10), _dt(12, 12), ["oversize"], SITE) is None
    assert pl.covering_permit([granted], None, None, ["oversize"], SITE) is None


def test_permit_validity_bounds() -> None:
    late = datetime(2026, 11, 2, 23, tzinfo=SITE)
    assert pl.permit_covers(_permit(), late, late + timedelta(hours=2), SITE) is False


def test_permit_validity_is_in_site_dates() -> None:
    # Valid from the 13th. 22:30 UTC on the 12th is 00:30 on the 13th on site: covered.
    permit = _permit(valid_from=date(2026, 10, 13), allowed_windows=None)
    assert pl.permit_covers(permit, _utc(12, 22, 30), _utc(12, 23, 30), SITE) is True
    # Valid to the 13th. 22:30 UTC on the 13th is already the 14th on site: not covered.
    permit = _permit(valid_to=date(2026, 10, 13), allowed_windows=None)
    assert pl.permit_covers(permit, _utc(13, 22, 30), _utc(13, 23, 30), SITE) is False


def test_permit_expiry() -> None:
    today = date(2026, 10, 12)
    assert pl.permit_expiry(None, today, 14) == "ok"
    assert pl.permit_expiry(date(2026, 10, 11), today, 14) == "expired"
    assert pl.permit_expiry(date(2026, 10, 12), today, 14) == "expiring"
    assert pl.permit_expiry(date(2026, 10, 26), today, 14) == "expiring"
    assert pl.permit_expiry(date(2026, 10, 27), today, 14) == "ok"


def test_narrower_hours() -> None:
    assert pl.narrower_hours(("06:00", "20:00"), ("07:00", "22:00")) == ("07:00", "20:00")
    assert pl.narrower_hours(("06:00", "20:00"), None) == ("06:00", "20:00")
    assert pl.narrower_hours((None, None), ("07:00", "18:00")) == ("07:00", "18:00")
    assert pl.narrower_hours(("06:00", "20:00"), ("bad", "18:00")) == ("06:00", "20:00")


@pytest.mark.parametrize(
    ("value", "minutes"), [("00:00", 0), ("23:59", 1439), ("24:00", None), ("7", None), (None, None)]
)
def test_hhmm(value, minutes) -> None:
    assert pl.hhmm(value) == minutes


# ── Media ──────────────────────────────────────────────────────────────────


def test_media_required_and_short() -> None:
    required = pl.media_required([(D("100"), D("0.8")), (D("60"), D("1"))], D("10"))
    assert required == D("154.000")
    assert pl.media_short(required, D("154")) is False
    assert pl.media_short(required, D("140.8")) is True
    assert pl.media_short(D("1"), None) is True
    assert pl.media_short(D("0"), None) is False


def test_media_late() -> None:
    today = date(2026, 10, 12)
    stage = date(2026, 11, 1)
    assert pl.media_late("requested", date(2026, 11, 2), stage, today) is True
    assert pl.media_late("requested", date(2026, 10, 30), stage, today) is False
    assert pl.media_late("contracted", date(2026, 12, 1), stage, today) is False
    assert pl.media_late("requested", None, stage, today) is False
    assert pl.media_late("requested", None, date(2026, 10, 1), today) is True
    assert pl.media_late("requested", None, None, today) is False


# ── Just in time and quiet hours ───────────────────────────────────────────


def test_jit_finding() -> None:
    takt = date(2026, 10, 20)
    assert pl.jit_finding(date(2026, 10, 18), takt, 2) is None
    assert pl.jit_finding(date(2026, 10, 20), takt, 2) is None
    assert pl.jit_finding(date(2026, 10, 17), takt, 2) == "jit_too_early"
    assert pl.jit_finding(date(2026, 10, 21), takt, 2) == "jit_late"
    assert pl.jit_finding(date(2026, 10, 1), None, 2) is None


def test_quiet_hours_across_midnight() -> None:
    quiet = ("20:00", "07:00")
    assert pl.quiet_hours_conflict(quiet, _dt(12, 8), _dt(12, 19), SITE) is False
    assert pl.quiet_hours_conflict(quiet, _dt(12, 19), _dt(12, 21), SITE) is True
    assert pl.quiet_hours_conflict(quiet, _dt(13, 6), _dt(13, 8), SITE) is True
    assert pl.quiet_hours_conflict(quiet, _dt(12, 7), _dt(12, 20), SITE) is False  # touches both edges only
    assert pl.quiet_hours_conflict(None, _dt(12, 1), _dt(12, 2), SITE) is False


def test_quiet_hours_are_site_hours() -> None:
    quiet = ("20:00", "07:00")
    # 17:30 to 18:30 UTC is 19:30 to 20:30 on site: it runs into the quiet hours.
    assert pl.quiet_hours_conflict(quiet, _utc(12, 17, 30), _utc(12, 18, 30), SITE) is True
    # 05:30 to 06:30 UTC is 07:30 to 08:30 on site: clear, though the UTC clock reads "before 07:00".
    assert pl.quiet_hours_conflict(quiet, _utc(12, 5, 30), _utc(12, 6, 30), SITE) is False


# ── Customs ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "ok"), [("853720", True), ("8537200000", True), ("85372", False), ("8537.20", False), ("", False)]
)
def test_hs_code_valid(code: str, ok: bool) -> None:
    assert pl.hs_code_valid(code, 6) is ok


# Independent of the shipped catalogue: who clears export and import under each
# Incoterms 2020 rule (A7/B7), and which rules are for sea and inland waterway only.
ICC_2020 = {
    "EXW": ("buyer", "buyer", False),
    "FCA": ("seller", "buyer", False),
    "CPT": ("seller", "buyer", False),
    "CIP": ("seller", "buyer", False),
    "DAP": ("seller", "buyer", False),
    "DPU": ("seller", "buyer", False),
    "DDP": ("seller", "seller", False),
    "FAS": ("seller", "buyer", True),
    "FOB": ("seller", "buyer", True),
    "CFR": ("seller", "buyer", True),
    "CIF": ("seller", "buyer", True),
}


@pytest.fixture(scope="module")
def neutral() -> SiteLogisticsCatalogue:
    return resolved_shipped("neutral")


def test_shipped_incoterms_match_icc(neutral: SiteLogisticsCatalogue) -> None:
    assert set(ICC_2020) == set(INCOTERM_CODES_2020) == neutral.codes("incoterms")
    for code, (export_by, import_by, sea_only) in ICC_2020.items():
        term = neutral.entry("incoterms", code)
        assert (term.export_clearance_by, term.import_clearance_by, term.sea_only) == (export_by, import_by, sea_only)


@pytest.mark.parametrize("code", sorted(ICC_2020))
@pytest.mark.parametrize("direction", ["import", "export"])
def test_document_template_per_incoterm(neutral, code: str, direction: str) -> None:
    """We are the buyer on an import and the seller on an export; we need each declaration we clear."""
    export_by, import_by, _ = ICC_2020[code]
    ours = "buyer" if direction == "import" else "seller"
    docs = pl.required_documents(direction, neutral.entry("incoterms", code), neutral.document_rules, "road")
    assert docs[:2] == ["commercial_invoice", "packing_list"]
    assert "cmr" in docs
    assert ("certificate_of_origin" in docs) is (direction == "import")
    assert ("export_declaration" in docs) is (export_by == ours)
    assert ("import_declaration" in docs) is (import_by == ours)


def test_declarations_follow_who_clears_not_the_direction(neutral) -> None:
    rules = neutral.document_rules
    exw, ddp, fca = (neutral.entry("incoterms", c) for c in ("EXW", "DDP", "FCA"))
    # EXW: the buyer clears export too, so our import needs both declarations.
    exw_import = pl.required_documents("import", exw, rules, "road")
    assert "export_declaration" in exw_import
    assert "import_declaration" in exw_import
    # DDP: the seller clears import too, so our export needs both declarations.
    ddp_export = pl.required_documents("export", ddp, rules, "road")
    assert "export_declaration" in ddp_export
    assert "import_declaration" in ddp_export
    # The other side of the same two rules clears nothing.
    assert not {"export_declaration", "import_declaration"} & set(pl.required_documents("export", exw, rules, "road"))
    assert not {"export_declaration", "import_declaration"} & set(pl.required_documents("import", ddp, rules, "road"))
    # FCA is the ordinary split.
    assert "export_declaration" not in pl.required_documents("import", fca, rules, "road")
    assert "import_declaration" not in pl.required_documents("export", fca, rules, "road")


def test_unknown_incoterm_assigns_no_clearance(neutral) -> None:
    docs = pl.required_documents("import", None, neutral.document_rules, "road")
    assert "commercial_invoice" in docs
    assert not {"export_declaration", "import_declaration"} & set(docs)


def test_document_template_mode_and_preference(neutral) -> None:
    fob = neutral.entry("incoterms", "FOB")
    rules = neutral.document_rules
    assert "bill_of_lading" in pl.required_documents("import", fob, rules, "sea")
    assert "air_waybill" in pl.required_documents("import", fob, rules, "air")
    assert "preferential_origin_statement" in pl.required_documents("import", fob, rules, None, preferential=True)
    assert "preferential_origin_statement" not in pl.required_documents("import", fob, rules, None)


def test_document_template_is_catalogue_data(neutral) -> None:
    """A catalogue that states other rules gets other documents: nothing is fixed in code."""
    rules = [DocumentRule(kind="commercial_invoice", directions=["export"])]
    fca = neutral.entry("incoterms", "FCA")
    assert pl.required_documents("export", fca, rules, "road") == ["commercial_invoice"]
    assert pl.required_documents("import", fca, rules, "road") == []
    assert pl.required_documents("import", fca, [], "road") == []


def test_permit_roles_are_catalogue_data(neutral) -> None:
    assert "oversize_permit" in neutral.permit_kinds_for("heavy_transport")
    assert list(neutral.permit_kinds_for("gate_load")) == ["oversize_permit"]
    assert "night_work" in neutral.permit_kinds_for("quiet_hours")
    assert "night_work" not in neutral.permit_kinds_for("gate_load")
    for national in ("de", "uk", "us"):
        cat = resolved_shipped(national)
        assert set(cat.permit_kinds_for("gate_load")) <= cat.codes("permit_kinds")
        assert cat.permit_kinds_for("heavy_transport")
        assert cat.document_rules


def test_sea_only_and_declarant(neutral) -> None:
    fob, fca, ddp = (neutral.entry("incoterms", c) for c in ("FOB", "FCA", "DDP"))
    assert pl.sea_only_mismatch(fob, "road") is True
    assert pl.sea_only_mismatch(fob, "sea") is False
    assert pl.sea_only_mismatch(fca, "road") is False
    assert pl.declarant_matches("import", fca, "buyer") is True
    assert pl.declarant_matches("import", ddp, "buyer") is False
    assert pl.declarant_matches("export", ddp, "buyer") is True
    assert pl.declarant_matches("import", None, "buyer") is True


def test_missing_required() -> None:
    docs = [
        {"kind": "commercial_invoice", "required": True, "state": "missing"},
        {"kind": "packing_list", "required": True, "state": "received"},
        {"kind": "insurance", "required": False, "state": "missing"},
    ]
    assert pl.missing_required(docs) == ["commercial_invoice"]


def test_complaint_overdue() -> None:
    today = date(2026, 10, 12)
    assert pl.complaint_overdue("received", date(2026, 10, 11), today) is True
    assert pl.complaint_overdue("received", today, today) is False
    assert pl.complaint_overdue("acknowledged", date(2026, 10, 1), today) is False
    assert pl.complaint_overdue("received", None, today) is False


# ── Catalogues ─────────────────────────────────────────────────────────────


def test_shipped_catalogues_validate_and_merge() -> None:
    shipped = shipped_catalogues()
    assert {"neutral", "de", "uk", "us"} <= set(shipped)
    for cat_id, cat in shipped.items():
        assert validate_site_logistics_catalogue(cat, "shipped") == [], cat_id
        merged = resolved_shipped(cat_id)
        assert merged.codes("incoterms") == set(INCOTERM_CODES_2020)
        assert {"site_total", "storage", "laydown", "site_setup"} <= merged.codes("area_kinds")


def test_national_figures_are_sourced_and_unconfirmed() -> None:
    for cat_id in ("de", "uk", "us"):
        cat = shipped_catalogues()[cat_id]
        for group in ("load_classes", "permit_kinds", "noise_limits"):
            for entry in getattr(cat, group):
                ref = f"{cat_id}:{group}:{entry.code}"
                # An entry without a figure (a method, "project enters its own value") needs no source.
                if has_figure(entry):
                    assert entry.source_url, ref
                if entry.review_status is not None:
                    assert entry.review_status.value == "unconfirmed", ref
                if getattr(entry, "project_value_required", False):
                    assert entry.day_dba is None and entry.night_dba is None, ref


def test_validator_flags_figure_without_source() -> None:
    body = resolved_shipped("neutral").model_dump()
    body["id"] = "probe"
    body["load_classes"] = [{"code": "probe", "gross_weight_t": "40"}]
    errors = validate_site_logistics_catalogue(SiteLogisticsCatalogue.model_validate(body), "tenant")
    assert "statutory_figure_without_source: load_classes:probe" in errors


def test_validator_flags_incomplete_incoterms() -> None:
    body = resolved_shipped("neutral").model_dump()
    body["id"] = "probe"
    body["extends"] = None
    body["incoterms"] = body["incoterms"][:3]
    errors = validate_site_logistics_catalogue(SiteLogisticsCatalogue.model_validate(body), "tenant")
    assert "incoterms_2020_incomplete" in errors


@pytest.mark.parametrize(
    ("country", "expected"), [("DE", "de"), ("GB", "uk"), ("us", "us"), ("FR", "neutral"), (None, "neutral")]
)
def test_the_governance_port_names_the_catalogue_of_a_country(country, expected, monkeypatch) -> None:
    """The shipped files name their countries and the port reads them; ``None`` is the neutral file."""
    from app.modules.project_governance import catalogue_packs, catalogue_store, public
    from app.modules.site_logistics import catalogue as cat

    cat.register_kind()
    # No active pack and no regional pack has a say here: the shipped files answer alone.
    monkeypatch.setattr(
        catalogue_packs, "pack_default_candidates", lambda kind, country_code=None, subdivision_code=None: ()
    )
    monkeypatch.setattr(catalogue_store, "regional_pack_entry", lambda kind, country_code: None)
    pin = public.default_catalogue_pin(cat.SITE_LOGISTICS_KIND, country)
    assert (pin.catalogue_id if pin is not None else cat.DEFAULT_CATALOGUE_ID) == expected
    if pin is not None:
        assert (pin.source, pin.version) == ("shipped", cat.shipped_catalogues()[expected].version)


def test_the_port_is_the_only_country_default_in_the_module() -> None:
    """No function of the module maps a country to a catalogue; the default pin asks the port once."""
    import inspect
    import pathlib

    from app.modules.site_logistics import catalogue as cat
    from app.modules.site_logistics import plan_service

    assert not hasattr(cat, "default_catalogue_id")
    module = pathlib.Path(cat.__file__).parent
    readers = [
        p.name
        for p in sorted(module.glob("*.py"))
        if "jurisdiction_countries" in p.read_text(encoding="utf-8") and p.name != "catalogue.py"
    ]
    assert readers == [], "only the governance port reads the countries of a catalogue"
    source = inspect.getsource(plan_service.LogisticsPlanService._default_pin)
    assert (
        source.count('default_catalogue_pin(SITE_LOGISTICS_KIND, country, getattr(project, "subdivision_code", None)')
        == 1
    )
    assert "DEFAULT_CATALOGUE_ID" in source
    shipped = cat.shipped_catalogues()
    assert {c.id: c.jurisdiction_countries for c in shipped.values()} == {
        "neutral": (),
        "de": ("DE",),
        "uk": ("GB",),
        "us": ("US",),
    }


def test_a_catalogue_with_a_country_that_is_not_a_code_is_refused() -> None:
    from app.modules.site_logistics import catalogue as cat

    body = cat.shipped_catalogues()["de"].model_dump(mode="json")
    body["jurisdiction_countries"] = ["Germany"]
    errors = validate_site_logistics_catalogue(SiteLogisticsCatalogue.model_validate(body), "tenant")
    assert "bad_country_code: Germany" in errors


# ── JSON columns ───────────────────────────────────────────────────────────


def test_json_safe_dumps() -> None:
    value = {
        "when": datetime(2026, 10, 12, 8, tzinfo=UTC),
        "day": date(2026, 10, 12),
        "amount": D("12.50"),
        "id": uuid.UUID(int=1),
        "pair": ("a", D("1")),
        "nested": [{"x": {D("1")}}],
    }
    safe = pl.json_safe(value)
    text = json.dumps(safe)
    assert safe["amount"] == "12.50"
    assert safe["day"] == "2026-10-12"
    assert "Decimal" not in text
