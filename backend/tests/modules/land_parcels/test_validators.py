# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PAR rules on plain contexts, and the pack hook that supplies a national tolerance."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.land_parcels.profiles import (
    NEUTRAL,
    ParcelProfile,
    k_mt_sqrt_area,
    profile_for,
    register_parcel_profile,
    unregister_parcel_profile,
)
from app.modules.land_parcels.validators import (
    AreaMatchesLegalRule,
    NoOverlapRule,
    NoSliverGapRule,
    ParcelIdFormatRule,
    RingValidRule,
    WorkZoneAcquiredRule,
)

E0, N0 = 389000.0, 5819000.0


def _rect(e1: float, n1: float, e2: float, n2: float) -> list[list[float]]:
    return [[E0 + e1, N0 + n1], [E0 + e2, N0 + n1], [E0 + e2, N0 + n2], [E0 + e1, N0 + n2]]


def _parcel(ref: str, ring: list[list[float]], **extra) -> dict:
    return {"id": f"id-{ref}", "ref": ref, "status": "needed", "closed": True, "ring": ring, **extra}


def _ctx(parcels: list[dict], zones: list[dict] | None = None, gap: str = "0.05") -> ValidationContext:
    return ValidationContext(
        data={"parcels": parcels, "work_zones": zones or [], "settings": {"gap_tolerance_m": gap}},
        metadata={"locale": "en"},
    )


async def _failed(rule, ctx: ValidationContext) -> list:
    return [r for r in await rule.validate(ctx) if not r.passed]


async def test_par001_silent_at_one_percent_for_worked_example() -> None:
    p = _parcel("P-001", _rect(0, 0, 1, 1), legal_area="1203", computed_area="1202.67", tolerance_m2="12.03")
    assert await _failed(AreaMatchesLegalRule(), _ctx([p])) == []


async def test_par001_fires_beyond_tolerance_with_numbers_in_message() -> None:
    p = _parcel("P-009", _rect(0, 0, 1, 1), legal_area="1203", computed_area="1150.00", tolerance_m2="12.03",
                tolerance_text="1% config")  # fmt: skip
    out = await _failed(AreaMatchesLegalRule(), _ctx([p]))
    assert len(out) == 1
    assert out[0].rule_id == "PAR-001"
    assert "1,150.00" in out[0].message and "1,203.00" in out[0].message and "1% config" in out[0].message
    assert out[0].element_ref == "id-P-009"


def test_pack_formula_from_worked_example_1() -> None:
    tol = k_mt_sqrt_area(Decimal("3.5"), Decimal("0.10"))
    assert tol(Decimal("1203")) == Decimal("12.14")


def test_profile_only_for_active_market() -> None:
    profile = ParcelProfile(country="ZZ", id_pattern=r"\d{2}:\d{2}", area_decimals=0)
    register_parcel_profile(profile)
    try:
        assert profile_for(["ZZ"]) is profile
        assert profile_for(["DE"]) is NEUTRAL
        assert profile_for(["*"]) is NEUTRAL
        assert profile.id_valid("12:34")
        assert not profile.id_valid("P-001")
        assert NEUTRAL.id_valid("anything")
    finally:
        unregister_parcel_profile("ZZ")


async def test_par002_open_ring_and_bow_tie() -> None:
    open_p = _parcel("A", _rect(0, 0, 10, 10), closed=False)
    bow = _parcel("B", [[0, 0], [10, 10], [10, 0], [0, 10]])
    ok = _parcel("C", _rect(20, 0, 30, 10))
    out = await _failed(RingValidRule(), _ctx([open_p, bow, ok]))
    assert sorted(r.element_ref for r in out) == ["id-A", "id-B"]


async def test_par003_on_not_acquired_parcel_only() -> None:
    zone = {"id": "z", "name": "Access road", "ring": _rect(100, 10, 160, 20)}
    p2 = _parcel("P-002", _rect(50, 0, 80, 40), status="acquired")
    p3 = _parcel("P-003", _rect(120, 0, 145, 40), status="negotiating")
    out = await _failed(WorkZoneAcquiredRule(), _ctx([p2, p3], [zone]))
    assert [r.element_ref for r in out] == ["id-P-003"]
    assert "250.00" in out[0].message
    p3["status"] = "acquired"
    assert await _failed(WorkZoneAcquiredRule(), _ctx([p2, p3], [zone])) == []


async def test_par004_overlap_between_neighbours() -> None:
    a = _parcel("A", _rect(0, 0, 10, 10))
    b = _parcel("B", _rect(8, 0, 18, 10))
    c = _parcel("C", _rect(18, 0, 28, 10))
    out = await _failed(NoOverlapRule(), _ctx([a, b, c]))
    assert len(out) == 1
    assert "20.00" in out[0].message
    assert out[0].details["other"] == "id-B"


async def test_par005_sliver_gap_but_not_shared_edge() -> None:
    a = _parcel("A", _rect(0, 0, 10, 10))
    b = _parcel("B", _rect(10.03, 0, 20, 10))
    c = _parcel("C", _rect(-10, 0, 0, 10))
    out = await _failed(NoSliverGapRule(), _ctx([a, b, c]))
    assert len(out) == 1
    assert "0.030" in out[0].message
    assert await _failed(NoSliverGapRule(), _ctx([a, b, c], gap="0.01")) == []


async def test_par006_only_when_pack_says_invalid() -> None:
    p = _parcel("P-001", _rect(0, 0, 1, 1), id_valid=False, id_label="Cadastral number", id_example="12:34")
    q = _parcel("P-002", _rect(5, 0, 6, 1), id_valid=None)
    out = await _failed(ParcelIdFormatRule(), _ctx([p, q]))
    assert [r.element_ref for r in out] == ["id-P-001"]


@pytest.mark.parametrize("rule", [AreaMatchesLegalRule, RingValidRule, WorkZoneAcquiredRule, NoOverlapRule])
async def test_empty_context_passes(rule) -> None:
    assert await _failed(rule(), _ctx([])) == []
