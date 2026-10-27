# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment telematics​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: ISO 15143-3 (AEMP 2.0) and CSV parsing, daily utilisation math.

Pure functions, no database. The service feeds them rows and stores what they
return. A sample carries cumulative counters (engine hours, idle hours, fuel
used), as the standard reports them; a day's use is the difference between
the last sample of the day and the last sample before it.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from defusedxml import ElementTree as SafeET

__all__ = [
    "CSV_COLUMNS",
    "DayUse",
    "TelematicsParseError",
    "TelematicsSample",
    "daily_utilisation",
    "parse_aemp",
    "parse_csv",
]

_GALLON_L = Decimal("3.785411784")
_MILE_KM = Decimal("1.609344")
_DAY_HOURS = Decimal("24")
_ZERO = Decimal("0")

#: Columns of the CSV upload; only ``equipment`` and ``recorded_at`` are required.
CSV_COLUMNS = (
    "equipment",
    "recorded_at",
    "engine_hours",
    "idle_hours",
    "fuel_used_l",
    "fuel_level_pct",
    "lat",
    "lng",
    "odometer_km",
    "engine_status",
    "fault_codes",
)


class TelematicsParseError(ValueError):
    """The upload is not a readable telematics document."""


@dataclass
class TelematicsSample:
    """One machine snapshot, unit-normalised (hours, litres, km, WGS84)."""

    equipment_ref: str
    recorded_at: datetime
    serial: str | None = None
    engine_hours: Decimal | None = None
    idle_hours: Decimal | None = None
    fuel_used_l: Decimal | None = None
    fuel_level_pct: Decimal | None = None
    odometer_km: Decimal | None = None
    lat: float | None = None
    lng: float | None = None
    engine_status: str | None = None
    fault_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DayUse:
    """Worked, idle and off hours of one machine on one day, plus fuel burnt."""

    day: date
    worked_hours: Decimal
    idle_hours: Decimal
    off_hours: Decimal
    fuel_l: Decimal | None
    engine_hours_end: Decimal | None


def _dec(raw: Any) -> Decimal | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _float(raw: Any) -> float | None:
    d = _dec(raw)
    return float(d) if d is not None else None


def _when(raw: Any) -> datetime | None:
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _running(raw: Any) -> str | None:
    if raw is None:
        return None
    return "running" if str(raw).strip().lower() in {"true", "1"} else "off"


# ── ISO 15143-3 XML ─────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(node: Any, name: str) -> Any:
    if node is None:
        return None
    for c in node:
        if _local(c.tag) == name:
            return c
    return None


def _text(node: Any, name: str) -> str | None:
    c = _child(node, name)
    return c.text.strip() if c is not None and c.text else None


def _stamp(node: Any) -> datetime | None:
    if node is None:
        return None
    for k, v in node.attrib.items():
        if _local(k) == "datetime":
            return _when(v)
    return None


def _xml_equipment(eq: Any, snapshot: datetime | None) -> TelematicsSample | None:
    header = _child(eq, "equipmentheader")
    ref = _text(header, "equipmentid")
    serial = _text(header, "serialnumber")
    if not ref and not serial:
        return None
    sample = TelematicsSample(
        equipment_ref=ref or serial or "", serial=serial, recorded_at=snapshot or datetime.now(UTC)
    )
    stamps: list[datetime | None] = []

    loc = _child(eq, "location")
    if loc is not None:
        sample.lat = _float(_text(loc, "latitude"))
        sample.lng = _float(_text(loc, "longitude"))
        stamps.append(_stamp(loc))
    hours = _child(eq, "cumulativeoperatinghours")
    if hours is not None:
        sample.engine_hours = _dec(_text(hours, "hour"))
        stamps.append(_stamp(hours))
    idle = _child(eq, "cumulativeidlehours")
    if idle is not None:
        sample.idle_hours = _dec(_text(idle, "hour"))
        stamps.append(_stamp(idle))
    fuel = _child(eq, "fuelused")
    if fuel is not None:
        amount = _dec(_text(fuel, "fuelconsumed"))
        if amount is not None and (_text(fuel, "fuelunits") or "").lower().startswith("gal"):
            amount = amount * _GALLON_L
        sample.fuel_used_l = amount
        stamps.append(_stamp(fuel))
    sample.fuel_level_pct = _dec(_text(_child(eq, "fuelremaining"), "percent"))
    dist = _child(eq, "distance")
    if dist is not None:
        odo = _dec(_text(dist, "odometer"))
        if odo is not None and (_text(dist, "odometerunits") or "").lower().startswith("mi"):
            odo = odo * _MILE_KM
        sample.odometer_km = odo
    sample.engine_status = _running(_text(_child(eq, "enginestatus"), "running"))
    faults = _child(eq, "faultcodes")
    if faults is not None:
        for fc in faults:
            code = _text(fc, "codeidentifier") or _text(fc, "spn") or (fc.text or "").strip()
            if code:
                sample.fault_codes.append(code)
    known = [s for s in stamps if s is not None]
    if known:
        sample.recorded_at = max(known)
    return sample


def _parse_aemp_xml(payload: bytes) -> list[TelematicsSample]:
    try:
        root = SafeET.fromstring(payload)
    except Exception as exc:
        raise TelematicsParseError("not_xml") from exc
    if _local(root.tag) != "fleet":
        raise TelematicsParseError("not_aemp_fleet")
    snapshot = None
    for k, v in root.attrib.items():
        if _local(k) == "snapshottime":
            snapshot = _when(v)
    return [s for eq in root if _local(eq.tag) == "equipment" and (s := _xml_equipment(eq, snapshot)) is not None]


# ── ISO 15143-3 JSON ────────────────────────────────────────────────────


def _lower_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k).lower(): _lower_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_lower_keys(v) for v in obj]
    return obj


def _section(eq: dict[str, Any], name: str) -> dict[str, Any]:
    v = eq.get(name)
    return v if isinstance(v, dict) else {}


def _json_equipment(eq: dict[str, Any], snapshot: datetime | None) -> TelematicsSample | None:
    header = _section(eq, "equipmentheader")
    ref = header.get("equipmentid") or header.get("serialnumber")
    if not ref:
        return None
    loc, hours, idle = (
        _section(eq, "location"),
        _section(eq, "cumulativeoperatinghours"),
        _section(eq, "cumulativeidlehours"),
    )
    fuel, dist = _section(eq, "fuelused"), _section(eq, "distance")
    fuel_l = _dec(fuel.get("fuelconsumed"))
    if fuel_l is not None and str(fuel.get("fuelunits", "")).lower().startswith("gal"):
        fuel_l = fuel_l * _GALLON_L
    odo = _dec(dist.get("odometer"))
    if odo is not None and str(dist.get("odometerunits", "")).lower().startswith("mi"):
        odo = odo * _MILE_KM
    known = [s for s in (_when(x.get("datetime")) for x in (loc, hours, idle, fuel)) if s is not None]
    faults = eq.get("faultcodes") or []
    if isinstance(faults, dict):
        faults = faults.get("faultcode") or []
    if isinstance(faults, dict):
        faults = [faults]
    return TelematicsSample(
        equipment_ref=str(ref),
        serial=header.get("serialnumber"),
        recorded_at=max(known) if known else (snapshot or datetime.now(UTC)),
        engine_hours=_dec(hours.get("hour")),
        idle_hours=_dec(idle.get("hour")),
        fuel_used_l=fuel_l,
        fuel_level_pct=_dec(_section(eq, "fuelremaining").get("percent")),
        odometer_km=odo,
        lat=_float(loc.get("latitude")),
        lng=_float(loc.get("longitude")),
        engine_status=_running(_section(eq, "enginestatus").get("running")),
        fault_codes=[str(f.get("codeidentifier") if isinstance(f, dict) else f) for f in faults if f],
    )


def _parse_aemp_json(payload: bytes) -> list[TelematicsSample]:
    try:
        doc = _lower_keys(json.loads(payload.decode("utf-8-sig")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TelematicsParseError("not_json") from exc
    fleet = doc.get("fleet", doc) if isinstance(doc, dict) else {}
    if not isinstance(fleet, dict) or "equipment" not in fleet:
        raise TelematicsParseError("not_aemp_fleet")
    snapshot = _when(fleet.get("snapshottime"))
    units = fleet.get("equipment") or []
    if isinstance(units, dict):
        units = [units]
    return [s for eq in units if isinstance(eq, dict) and (s := _json_equipment(eq, snapshot)) is not None]


def parse_aemp(payload: bytes) -> list[TelematicsSample]:
    """Parse an ISO 15143-3 Fleet snapshot, XML or JSON, into samples.

    Raises:
        TelematicsParseError: the document is neither a Fleet XML nor a Fleet JSON.
    """
    head = payload.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head in (b"{", b"["):
        return _parse_aemp_json(payload)
    return _parse_aemp_xml(payload)


# ── CSV ─────────────────────────────────────────────────────────────────


def parse_csv(text: str) -> tuple[list[TelematicsSample], list[dict[str, Any]]]:
    """Parse the CSV upload. Returns the samples and the rejected rows with a reason.

    The delimiter, ``,`` or ``;``, is read from the header line.

    Raises:
        TelematicsParseError: the header has no ``equipment`` column.
    """
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames or "equipment" not in [f.strip().lower() for f in reader.fieldnames]:
        raise TelematicsParseError("csv_missing_equipment_column")
    samples: list[TelematicsSample] = []
    rejected: list[dict[str, Any]] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        when = _when(row.get("recorded_at"))
        if not row.get("equipment") or when is None:
            rejected.append({"line": line_no, "reason": "equipment_and_recorded_at_required"})
            continue
        faults = [f.strip() for f in (row.get("fault_codes") or "").replace(",", ";").split(";") if f.strip()]
        samples.append(
            TelematicsSample(
                equipment_ref=row["equipment"],
                recorded_at=when,
                engine_hours=_dec(row.get("engine_hours")),
                idle_hours=_dec(row.get("idle_hours")),
                fuel_used_l=_dec(row.get("fuel_used_l")),
                fuel_level_pct=_dec(row.get("fuel_level_pct")),
                odometer_km=_dec(row.get("odometer_km")),
                lat=_float(row.get("lat")),
                lng=_float(row.get("lng")),
                engine_status=row.get("engine_status") or None,
                fault_codes=faults,
            )
        )
    return samples, rejected


# ── Utilisation ─────────────────────────────────────────────────────────


def _clamp(v: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, v))


def daily_utilisation(samples: list[dict[str, Any]], day: date) -> DayUse | None:
    """One day's use from cumulative counters.

    Args:
        samples: Rows with ``recorded_at`` (aware datetime), ``engine_hours``,
            ``idle_hours`` and ``fuel_used_l`` (cumulative, any may be None), in
            any order; rows before ``day`` serve as the baseline.
        day: The UTC day to measure.

    Returns:
        None when the day has no sample with an engine-hour counter.
    """
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    rows = sorted((r for r in samples if r.get("engine_hours") is not None), key=lambda r: r["recorded_at"])
    before = [r for r in rows if r["recorded_at"] < start]
    inside = [r for r in rows if start <= r["recorded_at"] < end]
    if not inside:
        return None
    base = before[-1] if before else inside[0]
    last = inside[-1]
    engine = _clamp(Decimal(last["engine_hours"]) - Decimal(base["engine_hours"]), _ZERO, _DAY_HOURS)
    idle = _ZERO
    if last.get("idle_hours") is not None and base.get("idle_hours") is not None:
        idle = _clamp(Decimal(last["idle_hours"]) - Decimal(base["idle_hours"]), _ZERO, engine)
    fuel = None
    if last.get("fuel_used_l") is not None and base.get("fuel_used_l") is not None:
        fuel = max(_ZERO, Decimal(last["fuel_used_l"]) - Decimal(base["fuel_used_l"]))
    return DayUse(
        day=day,
        worked_hours=engine - idle,
        idle_hours=idle,
        off_hours=_DAY_HOURS - engine,
        fuel_l=fuel,
        engine_hours_end=Decimal(last["engine_hours"]),
    )
