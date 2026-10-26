# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ life-cycle stage maths and EPD parsers (EN 15978 / EN 15804 / ISO 21930).

Database-free: every function takes plain values or duck-typed rows and returns
plain values, so the unit tests need no session.

Covers:
    * EN 15804 ILCD+EPD XML parsing and a flat CSV EPD import
    * A4 transport from supplier distance and mode
    * A5 site energy and fuel, and A5 construction waste
    * hotspots by classification group (DIN 276, NRM, MasterFormat)
    * carbon budget status against a project target
    * carbon checks used by the validation rules
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from defusedxml import ElementTree as SafeET

# Generic defaults, kgCO2e per tonne-km. A country pack or a user factor
# overrides them; they exist so an A4 estimate is never silently zero.
TRANSPORT_MODE_FACTORS: dict[str, Decimal] = {
    "road_truck": Decimal("0.107"),
    "road_van": Decimal("0.600"),
    "rail": Decimal("0.028"),
    "inland_barge": Decimal("0.031"),
    "sea_container": Decimal("0.016"),
    "air": Decimal("1.130"),
}
TRANSPORT_FACTOR_SOURCE = "Generic freight defaults (well-to-wheel, 2023), needs expert review per country"

# kgCO2e per litre (liquid) or per m3 (gas), combustion plus upstream.
FUEL_FACTORS: dict[str, Decimal] = {
    "diesel": Decimal("2.66"),
    "petrol": Decimal("2.31"),
    "lpg": Decimal("1.56"),
    "natural_gas": Decimal("2.02"),
    "hvo": Decimal("0.35"),
}
FUEL_FACTOR_SOURCE = "Generic combustion defaults (2023), needs expert review per country"

# kgCO2e per kg of waste by treatment route (generic, EN 15978 A5w / C3-C4).
WASTE_TREATMENT_FACTORS: dict[str, Decimal] = {
    "landfill_inert": Decimal("0.0013"),
    "landfill_mixed": Decimal("0.450"),
    "recycling": Decimal("0.010"),
    "incineration": Decimal("0.900"),
}

DATA_QUALITY = ("measured", "calculated", "estimated")
CLASSIFICATION_SYSTEMS = ("din276", "nrm", "masterformat")
FACTOR_SET_MAX_AGE_YEARS = 5

_GWP_HINTS = ("gwp", "global warming", "climate change", "treibhaus", "réchauffement")
_GWP_EXCLUDE = ("biogenic", "fossil", "luluc", "land use", "ghg")


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm_module(code: str) -> str | None:
    c = (code or "").strip().upper().replace(" ", "").replace("_", "-")
    mapping = {
        "A1-A3": "a1a3",
        "A1-3": "a1a3",
        "A1A3": "a1a3",
        "A4": "a4",
        "A5": "a5",
        "D": "d",
    }
    if c in mapping:
        return mapping[c]
    if c.startswith("B") and c[1:2].isdigit():
        return "b"
    if c.startswith("C") and c[1:2].isdigit():
        return "c"
    return None


# ── EPD parsers ──────────────────────────────────────────────────────────


def parse_ilcd_epd_xml(payload: bytes) -> dict[str, Any]:
    """Parse an EN 15804 ILCD+EPD process dataset into an EPD dict.

    Reads the dataset UUID, base name, validity, reference year and the GWP
    total indicator per declared module (``epd:amount module="A1-A3"``).
    B1-B7 and C1-C4 are summed into ``gwp_b_total`` / ``gwp_c_total``.

    Raises:
        ValueError: not XML, no process dataset, or no GWP result found.
    """
    try:
        root = SafeET.fromstring(payload)
    except Exception as exc:  # defusedxml raises several parse/forbidden types
        raise ValueError(f"not a valid XML document ({type(exc).__name__})") from None
    if _local(root.tag) != "processDataSet":
        raise ValueError("not an ILCD process dataset")

    out: dict[str, Any] = {
        "epd_id": "",
        "product_name": "",
        "declared_unit": "",
        "validity_until": None,
        "reference_year": None,
        "gwp_a1a3": Decimal("0"),
        "gwp_a4": None,
        "gwp_a5": None,
        "gwp_b_total": None,
        "gwp_c_total": None,
        "gwp_d_credits": None,
    }
    for el in root.iter():
        name = _local(el.tag)
        text = (el.text or "").strip()
        if name == "UUID" and not out["epd_id"] and text:
            out["epd_id"] = text
        elif name == "baseName" and not out["product_name"] and text:
            out["product_name"] = text
        elif name == "dataSetValidUntil" and text:
            out["validity_until"] = f"{text}-12-31" if len(text) == 4 else text[:10]
        elif name == "referenceYear" and text:
            out["reference_year"] = int(text[:4]) if text[:4].isdigit() else None
        elif name == "referenceToFlowDataSet" and not out["declared_unit"]:
            out["declared_unit"] = _declared_unit_hint(el)

    found = False
    for result in root.iter():
        if _local(result.tag) != "LCIAResult":
            continue
        label = " ".join(
            (d.text or "")
            for d in result.iter()
            if _local(d.tag) == "shortDescription" and _local_parent_is_method(result, d)
        ).lower()
        if not any(h in label for h in _GWP_HINTS) or any(x in label for x in _GWP_EXCLUDE):
            continue
        for amt in result.iter():
            if _local(amt.tag) != "amount":
                continue
            attrs = {_local(k): v for k, v in amt.attrib.items()}
            module = _norm_module(attrs.get("module", ""))
            if module is None or not (amt.text or "").strip() or attrs.get("scenario"):
                continue
            value = _d(amt.text)
            found = True
            key = {"a1a3": "gwp_a1a3", "a4": "gwp_a4", "a5": "gwp_a5", "d": "gwp_d_credits"}.get(module)
            if key:
                out[key] = value
            else:
                total_key = "gwp_b_total" if module == "b" else "gwp_c_total"
                out[total_key] = (out[total_key] or Decimal("0")) + value
        if found:
            break
    if not found:
        raise ValueError("no GWP total indicator found in the dataset")
    if not out["epd_id"]:
        raise ValueError("dataset has no UUID")
    out["declared_unit"] = out["declared_unit"] or "kg"
    return out


def _local_parent_is_method(result: Any, desc: Any) -> bool:
    for ref in result:
        if _local(ref.tag) == "referenceToLCIAMethodDataSet" and desc in list(ref):
            return True
    return False


def _declared_unit_hint(ref: Any) -> str:
    text = " ".join((c.text or "") for c in ref).lower()
    for token, unit in (("m3", "m3"), ("m³", "m3"), ("m2", "m2"), ("m²", "m2"), (" t ", "t"), ("kg", "kg")):
        if token in f" {text} ":
            return unit
    return ""


CSV_COLUMNS = (
    "epd_id",
    "product_name",
    "material_class",
    "manufacturer",
    "region",
    "declared_unit",
    "gwp_a1a3",
    "gwp_a4",
    "gwp_a5",
    "gwp_c_total",
    "gwp_d_credits",
    "validity_until",
)


def parse_epd_csv(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a flat EPD CSV (comma or semicolon). Returns ``(rows, errors)``.

    Required columns: ``epd_id``, ``product_name``, ``declared_unit``,
    ``gwp_a1a3``. A row with a bad number is reported, not imported.
    """
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter)
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = {"epd_id", "product_name", "declared_unit", "gwp_a1a3"} - headers
    if missing:
        return [], [f"missing columns: {', '.join(sorted(missing))}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not row.get("epd_id"):
            errors.append(f"line {line_no}: empty epd_id")
            continue
        try:
            parsed: dict[str, Any] = {
                "epd_id": row["epd_id"],
                "product_name": row.get("product_name") or row["epd_id"],
                "material_class": row.get("material_class") or "other",
                "manufacturer": row.get("manufacturer") or None,
                "region": (row.get("region") or "").upper()[:8],
                "declared_unit": row.get("declared_unit") or "kg",
                "gwp_a1a3": Decimal(row["gwp_a1a3"].replace(",", ".")),
            }
            for key in ("gwp_a4", "gwp_a5", "gwp_c_total", "gwp_d_credits"):
                parsed[key] = Decimal(row[key].replace(",", ".")) if row.get(key) else None
            vu = row.get("validity_until")
            parsed["validity_until"] = date.fromisoformat(vu[:10]).isoformat() if vu else None
        except (InvalidOperation, ValueError) as exc:
            errors.append(f"line {line_no}: {exc}")
            continue
        rows.append(parsed)
    return rows, errors


# ── Stage maths ──────────────────────────────────────────────────────────


def compute_a4_transport(
    mass_kg: Any,
    distance_km: Any,
    mode: str = "road_truck",
    factor_per_tkm: Any = None,
) -> Decimal:
    """A4 kgCO2e = tonnes x km x factor (kgCO2e/tkm)."""
    mass = _d(mass_kg)
    dist = _d(distance_km)
    if mass < 0 or dist < 0:
        raise ValueError("mass and distance must not be negative")
    if factor_per_tkm is not None:
        factor = _d(factor_per_tkm)
    elif mode in TRANSPORT_MODE_FACTORS:
        factor = TRANSPORT_MODE_FACTORS[mode]
    else:
        raise ValueError(f"unknown transport mode: {mode}")
    return (mass / Decimal("1000")) * dist * factor


def compute_a5_site_energy(
    fuel_litres: dict[str, Any] | None = None,
    electricity_kwh: Any = 0,
    grid_factor: Any = 0,
) -> dict[str, Decimal]:
    """A5 site energy: fuel per type x fuel factor plus kWh x grid factor."""
    fuel_total = Decimal("0")
    for fuel, litres in (fuel_litres or {}).items():
        qty = _d(litres)
        if qty < 0:
            raise ValueError("fuel quantity must not be negative")
        fuel_total += qty * FUEL_FACTORS.get(fuel, FUEL_FACTORS["diesel"])
    kwh = _d(electricity_kwh)
    if kwh < 0:
        raise ValueError("energy must not be negative")
    elec = kwh * _d(grid_factor)
    return {"fuel_kg": fuel_total, "electricity_kg": elec, "total_kg": fuel_total + elec}


def compute_a5_waste(
    material_carbon_kg: Any,
    material_mass_kg: Any,
    waste_rate_pct: Any,
    treatment: str = "landfill_mixed",
) -> Decimal:
    """A5 waste: the wasted share re-incurs its A1-A3 carbon plus treatment."""
    rate = _d(waste_rate_pct) / Decimal("100")
    if rate < 0 or rate > 1:
        raise ValueError("waste rate must be between 0 and 100 percent")
    treat = WASTE_TREATMENT_FACTORS.get(treatment)
    if treat is None:
        raise ValueError(f"unknown waste treatment: {treatment}")
    return rate * _d(material_carbon_kg) + rate * _d(material_mass_kg) * treat


def hotspots_by_group(
    entries: Iterable[Any],
    position_classification: dict[str, dict[str, Any]],
    system: str = "din276",
    top: int = 10,
) -> list[dict[str, Any]]:
    """Group embodied carbon by a classification code (first 3 chars / group).

    ``position_classification`` maps a BOQ position id to its classification
    dict. Entries without a BOQ link or code land in ``unclassified``.
    """
    if system not in CLASSIFICATION_SYSTEMS:
        raise ValueError(f"unknown classification system: {system}")
    buckets: dict[str, Decimal] = {}
    total = Decimal("0")
    for e in entries:
        meta = getattr(e, "metadata_", None) or {}
        pid = str(meta.get("boq_position_id") or "")
        code = str((position_classification.get(pid) or {}).get(system) or "").strip()
        group = _group_code(code, system) or "unclassified"
        carbon = _d(getattr(e, "carbon_kg", 0))
        buckets[group] = buckets.get(group, Decimal("0")) + carbon
        total += carbon
    rows = [
        {
            "group": g,
            "carbon_kg": str(v),
            "share_pct": float(v / total * 100) if total else 0.0,
        }
        for g, v in buckets.items()
    ]
    rows.sort(key=lambda r: Decimal(r["carbon_kg"]), reverse=True)
    return rows[:top]


def _group_code(code: str, system: str) -> str:
    if not code:
        return ""
    if system == "din276":
        digits = "".join(ch for ch in code if ch.isdigit())
        return digits[:3] if len(digits) >= 3 else digits
    if system == "masterformat":
        digits = "".join(ch for ch in code if ch.isdigit())
        return digits[:2] if digits else ""
    return code.split(".")[0]


def budget_status(actual_kg: Any, budget_kg: Any) -> dict[str, Any]:
    """Carbon budget: remaining, used percentage and an over-budget flag."""
    actual = _d(actual_kg)
    budget = _d(budget_kg)
    used = float(actual / budget * 100) if budget > 0 else 0.0
    return {
        "actual_kg": str(actual),
        "budget_kg": str(budget),
        "remaining_kg": str(budget - actual),
        "used_pct": round(used, 2),
        "over_budget": budget > 0 and actual > budget,
    }


def compare_swap(
    quantity: Any,
    current_factor: Any,
    current_unit_rate: Any,
    alt_factor: Any,
    alt_unit_rate: Any,
) -> dict[str, str]:
    """Alternative material swap: delta in CO2 and in cost (negative saves)."""
    q = _d(quantity)
    co2_now = q * _d(current_factor)
    co2_alt = q * _d(alt_factor)
    cost_now = q * _d(current_unit_rate)
    cost_alt = q * _d(alt_unit_rate)
    return {
        "co2_current_kg": str(co2_now),
        "co2_alternative_kg": str(co2_alt),
        "co2_delta_kg": str(co2_alt - co2_now),
        "cost_current": str(cost_now),
        "cost_alternative": str(cost_alt),
        "cost_delta": str(cost_alt - cost_now),
    }


def is_factor_set_outdated(factor_set_year: Any, today: date | None = None) -> bool:
    """A factor set older than ``FACTOR_SET_MAX_AGE_YEARS`` is outdated."""
    try:
        year = int(factor_set_year)
    except (TypeError, ValueError):
        return False
    return ((today or date.today()).year - year) > FACTOR_SET_MAX_AGE_YEARS


def is_epd_expired(validity_until: Any, today: date | None = None) -> bool:
    if not validity_until:
        return False
    try:
        d = validity_until if isinstance(validity_until, date) else date.fromisoformat(str(validity_until)[:10])
    except ValueError:
        return False
    return d < (today or date.today())
