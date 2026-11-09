# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests: custom sensor definitions, readings a person enters, and the rules that check them."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.site_sensors.schemas import DeviceCreate, MixUpdate, UserReadingsIn, check_limits
from app.modules.site_sensors.validators import run_rules

PID = uuid.uuid4()


@pytest.mark.parametrize(
    ("kind", "unit", "upper", "lower", "record_only", "expected"),
    [
        ("custom", "kN", Decimal("120"), None, False, None),
        ("custom", "m3/h", Decimal("60"), Decimal("18"), False, None),
        ("custom", "%RH", None, Decimal("30"), False, None),
        ("custom", "kN", None, None, True, None),
        ("custom", " ", Decimal("1"), None, False, "custom_unit_required"),
        ("custom", "kN", None, None, False, "custom_limit_or_record_only"),
        ("custom", "kN", Decimal("10"), Decimal("10"), False, "lower_limit_not_below_upper"),
        ("noise", "", Decimal("70"), Decimal("80"), False, "lower_limit_not_below_upper"),
        ("noise", "", None, None, False, None),
    ],
)
def test_check_limits(kind, unit, upper, lower, record_only, expected) -> None:
    assert check_limits(kind, unit, upper, lower, record_only) == expected


def test_a_custom_device_without_unit_is_refused() -> None:
    with pytest.raises(ValidationError, match="custom_unit_required"):
        DeviceCreate(project_id=PID, code="X", kind="custom", limit_value=Decimal("5"))
    ok = DeviceCreate(project_id=PID, code="X", kind="custom", unit="kN", record_only=True)
    assert ok.record_only is True


def test_user_readings_accept_manual_and_import_only() -> None:
    body = {"readings": [{"recorded_at": "2026-11-02T08:00:00Z", "value": 1.5, "note": "n"}]}
    assert UserReadingsIn.model_validate(body).source == "manual"
    assert UserReadingsIn.model_validate({**body, "source": "import"}).source == "import"
    with pytest.raises(ValidationError):
        UserReadingsIn.model_validate({**body, "source": "device"})


def test_mix_datum_is_bounded() -> None:
    assert MixUpdate(datum_temp_c=Decimal("-10")).datum_temp_c == Decimal("-10")
    with pytest.raises(ValidationError):
        MixUpdate(datum_temp_c=Decimal("-50"))


async def test_custom_and_override_rules() -> None:
    payload = {
        "devices": [
            {"id": "c1", "code": "FL-1", "kind": "custom", "active": True, "unit": "m3/h", "upper": 60, "lower": 18},
            {"id": "c2", "code": "LC-1", "kind": "custom", "active": True, "unit": "kN", "record_only": True},
            {"id": "c3", "code": "BAD", "kind": "custom", "active": True, "unit": "", "upper": 5},
            {"id": "o1", "code": "PM-1", "kind": "dust_pm10", "active": True, "overrides_country": True},
            {
                "id": "o2",
                "code": "NS-1",
                "kind": "noise",
                "active": True,
                "overrides_country": True,
                "limit_note": "Planning consent",
            },
        ]
    }
    results = await run_rules(payload)
    custom = {r["element_ref"]: r["passed"] for r in results if r["rule_id"] == "site_sensors.custom_sensor_defined"}
    assert custom == {"c1": True, "c2": True, "c3": False}
    override = {
        r["element_ref"]: r["passed"] for r in results if r["rule_id"] == "site_sensors.limit_override_explained"
    }
    assert override == {"o1": False, "o2": True}
