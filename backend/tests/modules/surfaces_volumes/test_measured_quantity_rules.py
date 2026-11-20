# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measured quantity to certificate rules (MQ-001..004) and the hauled vs excavated arithmetic."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.contracts.measured_quantity import evaluate, measured_pct, measured_pct_of_entry, norm_unit
from app.modules.haul_tickets import logic
from app.modules.haul_tickets.validators import VARIANCE_RULE_SET, register_haul_tickets_rules
from app.modules.haul_tickets.validators import evaluate as haul_evaluate

BASE = {
    "quantity": "1470.000",
    "unit": "m3",
    "boq_quantity": "1500",
    "ordinal": "1.02",
    "line_found": True,
    "line_unit": "m³",
    "contract_code": "RY-SUB-EW-01",
    "claim_status": "draft",
    "claim_number": "PC-01",
}


async def _ids(**over: object) -> list[tuple[str, str]]:
    return [(f["rule_id"], f["key"]) for f in await evaluate({**BASE, **over})]


async def test_the_course_quantity_passes_every_rule() -> None:
    assert await _ids() == []


async def test_over_the_bill_is_a_warning_only() -> None:
    found = await evaluate({**BASE, "quantity": "1837.500"})
    assert [(f["rule_id"], f["severity"], f["key"]) for f in found] == [("MQ-001", "warning", "over_boq")]
    assert found[0]["params"] == {"quantity": "1837.500", "boq_quantity": "1500", "unit": "m3"}


async def test_unit_mismatch_blocks() -> None:
    assert await _ids(line_unit="t") == [("MQ-002", "unit_mismatch")]


@pytest.mark.parametrize("status", ["submitted", "approved", "certified", "paid"])
async def test_a_certificate_past_draft_is_locked(status: str) -> None:
    assert await _ids(claim_status=status) == [("MQ-003", "certificate_locked")]


async def test_no_certificate_and_no_line() -> None:
    assert await _ids(claim_status="", claim_number="") == [("MQ-003", "no_open_certificate")]
    assert await _ids(line_found=False, line_unit="") == [("MQ-004", "no_schedule_line")]


def test_units_and_percent() -> None:
    assert {norm_unit(u) for u in ("m3", "M3", "m³", "cu m", "cbm")} == {"m3"}
    line = SimpleNamespace(quantity=Decimal("1500"), unit="m3")
    assert measured_pct(Decimal("1470"), "m3", line) == Decimal("98.0000")
    assert measured_pct(Decimal("1470"), "t", line) is None
    assert measured_pct(Decimal("1470"), "m3", SimpleNamespace(quantity=0, unit="m3")) is None
    entry = SimpleNamespace(metadata_={"measured_quantity": "1470.0", "measured_unit": "m3"})
    assert measured_pct_of_entry(entry, line) == Decimal("98.0000")
    assert measured_pct_of_entry(SimpleNamespace(metadata_={}), line) is None


def test_hauled_m3_in_order_of_trust() -> None:
    d = Decimal("1.5")
    kw = {"unit": "load", "net_t": None, "loads": 12, "capacity": Decimal("14"), "density": d}
    assert logic.hauled_m3(volume_m3=Decimal("150"), **kw) == ("volume", Decimal("150"))
    assert logic.hauled_m3(volume_m3=None, **kw) == ("capacity", Decimal("168.000"))
    weighed = {**kw, "unit": "t", "net_t": Decimal("231.0"), "capacity": None}
    assert logic.hauled_m3(volume_m3=None, **weighed) == ("weighbridge", Decimal("154.000"))
    tonnes_cap = {**kw, "unit": "t", "capacity": Decimal("21")}
    assert logic.hauled_m3(volume_m3=None, **tonnes_cap) == ("capacity", Decimal("168.000"))
    assert logic.hauled_m3(volume_m3=None, **{**kw, "capacity": None}) == ("unresolved", Decimal("0"))
    assert logic.variance_pct(Decimal("1680"), Decimal("1470")) == Decimal("14.29")
    assert logic.variance_pct(Decimal("1680"), Decimal("1837.5")) == Decimal("-8.57")
    assert logic.variance_pct(Decimal("1680"), None) is None


async def test_variance_rules() -> None:
    register_haul_tickets_rules()
    snap = {"code": "V-001", "excavated_m3": "1470", "hauled_m3": "1680", "threshold_pct": 10, "unresolved": 0}
    over = await haul_evaluate({"variance": {**snap, "difference_pct": "14.29"}}, rule_set=VARIANCE_RULE_SET)
    assert [f.rule_id for f in over] == ["haul_variance.hauled_vs_excavated"]
    within = await haul_evaluate({"variance": {**snap, "difference_pct": "-8.57"}}, rule_set=VARIANCE_RULE_SET)
    assert within == []
    lost = await haul_evaluate(
        {"variance": {**snap, "difference_pct": "-8.57", "unresolved": 2}}, rule_set=VARIANCE_RULE_SET
    )
    assert [f.rule_id for f in lost] == ["haul_variance.unresolved_tickets"]
