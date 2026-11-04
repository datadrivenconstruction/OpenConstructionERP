# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contract tests​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for the ISO 15143-3 (AEMP 2.0) and CSV telematics parsers, and day utilisation.

The XML and JSON documents below follow the Fleet snapshot shape of ISO
15143-3: a ``Fleet`` root with one ``Equipment`` per machine, each with an
``EquipmentHeader`` and dated cumulative counters. Units the standard allows
(gallons, miles) are normalised to litres and kilometres.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.site_monitoring import emission_class_meets, fuel_co2_kg_per_l, sensor_limit
from app.modules.equipment.telematics import (
    MAX_BURN_L_PER_H,
    TelematicsParseError,
    daily_utilisation,
    parse_aemp,
    parse_csv,
)

AEMP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Fleet xmlns="http://standards.iso.org/iso/15143/-3" version="2" snapshotTime="2026-10-20T12:00:00Z">
  <Links><rel>self</rel><href>https://example.invalid/fleet/1</href></Links>
  <Equipment>
    <EquipmentHeader>
      <OEMName>Generic</OEMName><Model>EX220</Model>
      <EquipmentID>EQ-0001</EquipmentID><SerialNumber>SN-77</SerialNumber>
    </EquipmentHeader>
    <Location datetime="2026-10-20T11:58:00Z"><Latitude>48.1372</Latitude><Longitude>11.5755</Longitude></Location>
    <CumulativeOperatingHours datetime="2026-10-20T11:59:00Z"><Hour>1234.5</Hour></CumulativeOperatingHours>
    <CumulativeIdleHours datetime="2026-10-20T11:59:00Z"><Hour>210.25</Hour></CumulativeIdleHours>
    <FuelUsed datetime="2026-10-20T11:59:00Z"><FuelUnits>litre</FuelUnits><FuelConsumed>15000</FuelConsumed></FuelUsed>
    <FuelRemaining datetime="2026-10-20T11:59:00Z"><Percent>62</Percent></FuelRemaining>
    <Distance datetime="2026-10-20T11:59:00Z"><OdometerUnits>kilometre</OdometerUnits><Odometer>88</Odometer></Distance>
    <EngineStatus datetime="2026-10-20T11:59:00Z"><Running>true</Running></EngineStatus>
    <FaultCodes datetime="2026-10-20T11:00:00Z">
      <FaultCode><CodeIdentifier>SPN-110-FMI-0</CodeIdentifier><CodeSeverity>high</CodeSeverity></FaultCode>
    </FaultCodes>
  </Equipment>
  <Equipment>
    <EquipmentHeader><SerialNumber>SN-99</SerialNumber></EquipmentHeader>
    <CumulativeOperatingHours datetime="2026-10-20T10:00:00Z"><Hour>50</Hour></CumulativeOperatingHours>
    <FuelUsed datetime="2026-10-20T10:00:00Z"><FuelUnits>gallon</FuelUnits><FuelConsumed>10</FuelConsumed></FuelUsed>
    <Distance><OdometerUnits>mile</OdometerUnits><Odometer>10</Odometer></Distance>
    <EngineStatus><Running>false</Running></EngineStatus>
  </Equipment>
  <Equipment><EquipmentHeader><OEMName>No identity</OEMName></EquipmentHeader></Equipment>
</Fleet>
"""

AEMP_JSON = b"""{"Fleet": {"version": "2", "snapshotTime": "2026-10-20T12:00:00Z", "Equipment": [
  {"EquipmentHeader": {"EquipmentID": "EQ-0002", "SerialNumber": "SN-88"},
   "Location": {"Latitude": 52.52, "Longitude": 13.405, "Datetime": "2026-10-20T11:00:00Z"},
   "CumulativeOperatingHours": {"Hour": 900, "Datetime": "2026-10-20T11:30:00Z"},
   "CumulativeIdleHours": {"Hour": 100},
   "FuelUsed": {"FuelUnits": "gallon", "FuelConsumed": 100},
   "EngineStatus": {"Running": true},
   "FaultCodes": [{"CodeIdentifier": "P0101"}]}
]}}"""


def test_aemp_xml_reads_every_counter_of_the_fleet_snapshot() -> None:
    samples = parse_aemp(AEMP_XML)
    assert [s.equipment_ref for s in samples] == ["EQ-0001", "SN-99"]
    s = samples[0]
    assert s.serial == "SN-77"
    assert s.engine_hours == Decimal("1234.5")
    assert s.idle_hours == Decimal("210.25")
    assert s.fuel_used_l == Decimal("15000")
    assert s.fuel_level_pct == Decimal("62")
    assert s.odometer_km == Decimal("88")
    assert (s.lat, s.lng) == (48.1372, 11.5755)
    assert s.engine_status == "running"
    assert s.fault_codes == ["SPN-110-FMI-0"]
    assert s.recorded_at == datetime(2026, 10, 20, 11, 59, tzinfo=UTC)


def test_aemp_xml_normalises_gallons_and_miles() -> None:
    s = parse_aemp(AEMP_XML)[1]
    assert s.fuel_used_l == Decimal("37.85411784")
    assert s.odometer_km == Decimal("16.09344")
    assert s.engine_status == "off"


def test_aemp_json_variant_reads_the_same_fields() -> None:
    [s] = parse_aemp(AEMP_JSON)
    assert s.equipment_ref == "EQ-0002"
    assert s.engine_hours == Decimal("900")
    assert s.idle_hours == Decimal("100")
    assert s.fuel_used_l == Decimal("378.5411784")
    assert s.fault_codes == ["P0101"]
    assert s.recorded_at == datetime(2026, 10, 20, 11, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"<NotFleet/>", "not_aemp_fleet"),
        (b"<Fleet><unclosed>", "not_xml"),
        (b'{"Other": 1}', "not_aemp_fleet"),
        (b"{broken", "not_json"),
    ],
)
def test_aemp_rejects_what_is_not_a_fleet_snapshot(payload: bytes, reason: str) -> None:
    with pytest.raises(TelematicsParseError, match=reason):
        parse_aemp(payload)


def test_aemp_refuses_entity_expansion() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Fleet>&a;</Fleet>'
    with pytest.raises(TelematicsParseError):
        parse_aemp(bomb)


def test_csv_reads_semicolons_and_reports_bad_rows() -> None:
    text = (
        "equipment;recorded_at;engine_hours;idle_hours;fuel_used_l;lat;lng;fault_codes\n"
        "EQ-0001;2026-10-20T08:00:00Z;100;10;500;48.1;11.5;A1;B2\n"
        ";2026-10-20T09:00:00Z;101;;;;;\n"
        "EQ-0001;not a date;101;;;;;\n"
    )
    samples, rejected = parse_csv(text)
    assert len(samples) == 1
    assert samples[0].engine_hours == Decimal("100")
    assert [r["line"] for r in rejected] == [3, 4]


def test_csv_without_equipment_column_is_refused() -> None:
    with pytest.raises(TelematicsParseError):
        parse_csv("machine,recorded_at\nX,2026-10-20T08:00:00Z\n")


def _row(h: int, engine: str, idle: str, fuel: str | None = None, day: int = 20) -> dict:
    return {
        "recorded_at": datetime(2026, 10, day, h, tzinfo=UTC),
        "engine_hours": Decimal(engine),
        "idle_hours": Decimal(idle),
        "fuel_used_l": Decimal(fuel) if fuel else None,
    }


def test_day_use_is_the_difference_to_the_last_sample_before_the_day() -> None:
    rows = [_row(17, "100", "10", "1000", day=19), _row(8, "101", "10.5", "1010"), _row(16, "108", "12", "1090")]
    use = daily_utilisation(rows, date(2026, 10, 20))
    assert use is not None
    assert use.worked_hours == Decimal("6")
    assert use.idle_hours == Decimal("2")
    assert use.off_hours == Decimal("16")
    assert use.fuel_l == Decimal("90")


def test_day_use_flags_a_counter_reset_and_skips_an_empty_day() -> None:
    rows = [_row(17, "500", "50", day=19), _row(9, "3", "1")]
    use = daily_utilisation(rows, date(2026, 10, 20))
    # The restarted counter reads 3 h since the swap: counted, never negative, and flagged.
    assert use is not None and use.counter_reset is True
    assert use.worked_hours + use.idle_hours == 3 and use.off_hours == 21
    assert daily_utilisation(rows, date(2026, 10, 21)) is None


def test_country_data_limits_and_classes() -> None:
    assert sensor_limit("DE", "dust_pm10").value == Decimal("50")
    assert sensor_limit("US", "dust_pm10").value == Decimal("150")
    assert sensor_limit("ZZ", "noise") is None
    assert sensor_limit("DE", "water_level") is None
    assert emission_class_meets("DE", "eu_stage_v") is True
    assert emission_class_meets("DE", "eu_stage_iv") is False
    assert emission_class_meets("US", "eu_stage_v") is None
    assert emission_class_meets("US", "electric") is True
    assert fuel_co2_kg_per_l() == Decimal("2.68")


# ── Counter reset and rule ──────────────────────────────────────────────


def _cum(ts: str, eng: str, idle: str | None = None, fuel: str | None = None) -> dict:
    return {
        "recorded_at": datetime.fromisoformat(ts),
        "engine_hours": Decimal(eng),
        "idle_hours": Decimal(idle) if idle is not None else None,
        "fuel_used_l": Decimal(fuel) if fuel is not None else None,
    }


def test_counter_that_restarts_counts_from_zero_and_is_flagged() -> None:
    from datetime import date

    rows = [
        _cum("2026-10-01T22:00:00+00:00", "1000"),
        _cum("2026-10-02T08:00:00+00:00", "1002"),
        _cum("2026-10-02T16:00:00+00:00", "3", "1", "5"),
    ]
    use = daily_utilisation(rows, date(2026, 10, 2))
    assert use is not None
    assert use.counter_reset is True
    assert use.worked_hours + use.idle_hours == Decimal("5")


def test_a_steady_counter_is_not_flagged() -> None:
    from datetime import date

    rows = [_cum("2026-10-01T22:00:00+00:00", "1000"), _cum("2026-10-02T16:00:00+00:00", "1006")]
    use = daily_utilisation(rows, date(2026, 10, 2))
    assert use is not None
    assert use.counter_reset is False
    assert use.worked_hours == Decimal("6")


def test_sensor_jitter_below_tolerance_is_not_a_reset() -> None:
    from datetime import date

    rows = [
        _cum("2026-10-01T22:00:00+00:00", "1000"),
        _cum("2026-10-02T08:00:00+00:00", "1004"),
        _cum("2026-10-02T16:00:00+00:00", "1003.8"),
    ]
    use = daily_utilisation(rows, date(2026, 10, 2))
    assert use is not None
    assert use.counter_reset is False
    assert use.worked_hours == Decimal("4")


def test_silent_device_rule_only_judges_hired_machines_with_a_device() -> None:
    import asyncio

    from app.modules.equipment.validators import run_rules

    machines = [
        {"equipment_id": "a", "code": "A", "has_device": True, "allocated_project_id": "p", "device_silent_hours": 30},
        {
            "equipment_id": "b",
            "code": "B",
            "has_device": True,
            "allocated_project_id": "p",
            "device_silent_hours": None,
        },
        {"equipment_id": "c", "code": "C", "has_device": False, "allocated_project_id": "p"},
        {"equipment_id": "d", "code": "D", "has_device": True, "allocated_project_id": None, "device_silent_hours": 50},
    ]
    res = [r for r in asyncio.run(run_rules({"machines": machines})) if r["rule_id"].endswith("device_silent")]
    assert {r["element_ref"]: r["passed"] for r in res} == {"a": False, "b": True}


def test_restart_to_a_high_counter_cannot_exceed_the_time_between_readings() -> None:
    from datetime import date

    rows = [
        _cum("2026-10-02T06:00:00+00:00", "1000"),
        _cum("2026-10-02T08:00:00+00:00", "600"),
    ]
    use = daily_utilisation(rows, date(2026, 10, 2))
    assert use is not None
    assert use.counter_reset is True
    assert use.worked_hours + use.idle_hours <= Decimal("2")


def test_fuel_after_a_counter_restart_is_capped_by_time_times_max_burn() -> None:
    rows = [
        _cum("2026-10-02T06:00:00+00:00", "100", fuel="90000"),
        _cum("2026-10-02T08:00:00+00:00", "102", fuel="50000"),
    ]
    use = daily_utilisation(rows, date(2026, 10, 2))
    assert use is not None and use.counter_reset is True
    assert use.fuel_l is not None
    assert use.fuel_l <= Decimal("2") * MAX_BURN_L_PER_H
