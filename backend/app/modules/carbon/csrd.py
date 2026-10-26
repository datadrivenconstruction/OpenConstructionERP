# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Company-level​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ climate reporting: GHG Protocol scopes to ESRS E1 data points.

Pure: ``build_e1_datapoints`` takes flat source rows and returns the data
points plus an audit trail (each figure back to its source records with a
data-quality flag). Exporters render the result to Excel, PDF and an
XBRL-ready CSV mapping. Country templates (ESRS E1, UK SECR, US state rules)
and embodied-carbon limits live in ``core/country_data/carbon_reporting.json``.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "carbon_reporting.json"

# Net calorific values (kWh per litre or m3) to turn fuel into energy for E1-5.
FUEL_KWH_PER_UNIT: dict[str, Decimal] = {
    "diesel": Decimal("10.0"),
    "petrol": Decimal("9.1"),
    "lpg": Decimal("6.6"),
    "natural_gas": Decimal("10.3"),
    "hvo": Decimal("9.4"),
}

# Data point id -> (label, unit, XBRL element suggestion). Element names follow
# the published ESRS taxonomy naming and need expert review before filing.
DATAPOINTS: dict[str, tuple[str, str, str]] = {
    "E1-5_energy_total": ("Total energy consumption", "MWh", "esrs:TotalEnergyConsumptionRelatedToOwnOperations"),
    "E1-5_energy_fossil": ("Energy from fossil sources", "MWh", "esrs:TotalEnergyConsumptionFromFossilSources"),
    "E1-5_energy_renewable": (
        "Energy from renewable sources",
        "MWh",
        "esrs:TotalEnergyConsumptionFromRenewableSources",
    ),
    "E1-6_scope1": ("Gross scope 1 GHG emissions", "tCO2e", "esrs:GrossScope1GreenhouseGasEmissions"),
    "E1-6_scope2_location": (
        "Gross location-based scope 2 GHG emissions",
        "tCO2e",
        "esrs:GrossLocationBasedScope2GreenhouseGasEmissions",
    ),
    "E1-6_scope2_market": (
        "Gross market-based scope 2 GHG emissions",
        "tCO2e",
        "esrs:GrossMarketBasedScope2GreenhouseGasEmissions",
    ),
    "E1-6_scope3": ("Gross scope 3 GHG emissions", "tCO2e", "esrs:GrossScope3GreenhouseGasEmissions"),
    "E1-6_total_location": ("Total GHG emissions (location-based)", "tCO2e", "esrs:TotalGHGEmissionsLocationBased"),
    "E1-6_total_market": ("Total GHG emissions (market-based)", "tCO2e", "esrs:TotalGHGEmissionsMarketBased"),
    "E1-6_intensity_location": (
        "GHG intensity per net revenue (location-based)",
        "tCO2e per million revenue",
        "esrs:GHGEmissionsIntensityPerNetRevenueLocationBased",
    ),
    "E1-4_targets": ("GHG reduction targets", "count", "esrs:GHGEmissionReductionTargets"),
}

_QUALITY_RANK = {"measured": 0, "calculated": 1, "estimated": 2}


@lru_cache(maxsize=1)
def load_country_data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def report_templates() -> dict[str, Any]:
    return load_country_data()["report_templates"]


def embodied_limit(country: str, building_type: str, on_date: str) -> dict[str, Any] | None:
    """Published embodied-carbon limit for a country, building type and date."""
    row = load_country_data()["embodied_limits"].get((country or "").upper())
    if not row:
        return None
    for v in row["values"]:
        if (
            v["building_type"] == building_type
            and v["valid_from"] <= on_date
            and (v["valid_to"] is None or on_date <= v["valid_to"])
        ):
            return {
                "country": country.upper(),
                "regulation": row["regulation"],
                "metric": row["metric"],
                "limit": v["limit"],
                "review_status": row["review_status"],
            }
    return None


def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))


def _worst(qualities: Iterable[str]) -> str:
    qs = [q for q in qualities if q in _QUALITY_RANK]
    return max(qs, key=_QUALITY_RANK.__getitem__) if qs else "estimated"


def build_e1_datapoints(
    rows: Iterable[dict[str, Any]],
    *,
    net_revenue: Any = 0,
    targets: Iterable[dict[str, Any]] = (),
    template: str = "esrs_e1",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Aggregate source rows into E1 data points and an audit trail.

    Each row: ``scope`` (1|2|3), ``co2e_kg``, optional ``market_co2e_kg``
    (scope 2), ``energy_kwh``, ``renewable_share_pct``, ``data_quality``,
    ``source`` (table name), ``source_id`` and ``project_id``.

    Returns ``(datapoints, audit)``; datapoints values are decimal strings,
    audit maps each data point id to its source rows.
    """
    sums: dict[str, Decimal] = {k: Decimal("0") for k in DATAPOINTS}
    audit: dict[str, list[dict[str, Any]]] = {k: [] for k in DATAPOINTS}

    def trace(dp: str, row: dict[str, Any], value: Decimal) -> None:
        audit[dp].append(
            {
                "source": row.get("source", ""),
                "source_id": str(row.get("source_id") or ""),
                "project_id": str(row.get("project_id") or "") or None,
                "value": str(value),
                "data_quality": row.get("data_quality") or "calculated",
            }
        )

    for row in rows:
        scope = int(row.get("scope") or 0)
        t = _dec(row.get("co2e_kg")) / Decimal("1000")
        if scope == 1:
            sums["E1-6_scope1"] += t
            trace("E1-6_scope1", row, t)
        elif scope == 2:
            sums["E1-6_scope2_location"] += t
            trace("E1-6_scope2_location", row, t)
            mkt = row.get("market_co2e_kg")
            tm = _dec(mkt) / Decimal("1000") if mkt is not None else t
            sums["E1-6_scope2_market"] += tm
            trace("E1-6_scope2_market", row, tm)
        elif scope == 3:
            sums["E1-6_scope3"] += t
            trace("E1-6_scope3", row, t)
        mwh = _dec(row.get("energy_kwh")) / Decimal("1000")
        if mwh:
            ren = mwh * _dec(row.get("renewable_share_pct")) / Decimal("100")
            sums["E1-5_energy_total"] += mwh
            sums["E1-5_energy_renewable"] += ren
            sums["E1-5_energy_fossil"] += mwh - ren
            for dp, v in (
                ("E1-5_energy_total", mwh),
                ("E1-5_energy_renewable", ren),
                ("E1-5_energy_fossil", mwh - ren),
            ):
                trace(dp, row, v)

    sums["E1-6_total_location"] = sums["E1-6_scope1"] + sums["E1-6_scope2_location"] + sums["E1-6_scope3"]
    sums["E1-6_total_market"] = sums["E1-6_scope1"] + sums["E1-6_scope2_market"] + sums["E1-6_scope3"]
    revenue_m = _dec(net_revenue) / Decimal("1000000")
    sums["E1-6_intensity_location"] = (sums["E1-6_total_location"] / revenue_m) if revenue_m > 0 else Decimal("0")
    target_list = list(targets)
    sums["E1-4_targets"] = Decimal(len(target_list))

    for dp in ("E1-6_total_location", "E1-6_total_market", "E1-6_intensity_location"):
        src = ["E1-6_scope1", "E1-6_scope3", "E1-6_scope2_location" if "location" in dp else "E1-6_scope2_market"]
        audit[dp] = [{"derived_from": s} for s in src]
    audit["E1-4_targets"] = [{"source": "oe_carbon_target", "source_id": str(t.get("id")), **t} for t in target_list]

    quality: dict[str, str] = {}
    for dp in DATAPOINTS:
        traced = [a["data_quality"] for a in audit[dp] if "data_quality" in a]
        quality[dp] = _worst(traced) if traced else "estimated"
    quality["E1-4_targets"] = "calculated"
    for dp in ("E1-6_total_location", "E1-6_total_market", "E1-6_intensity_location"):
        quality[dp] = _worst(quality[s] for s in _deps(dp) if audit[s])

    wanted = report_templates().get(template, report_templates()["esrs_e1"])["datapoints"]
    datapoints: dict[str, Any] = {}
    for dp in wanted:
        label, unit, element = DATAPOINTS[dp]
        datapoints[dp] = {
            "label": label,
            "unit": unit,
            "value": str(sums[dp].quantize(Decimal("0.001"))),
            "xbrl_element": element,
            "data_quality": quality[dp],
            "source_count": len(audit[dp]),
        }
    return datapoints, {k: v for k, v in audit.items() if k in wanted}


def _deps(dp: str) -> list[str]:
    s2 = "E1-6_scope2_market" if "market" in dp else "E1-6_scope2_location"
    return ["E1-6_scope1", s2, "E1-6_scope3"]


# ── Exports ──────────────────────────────────────────────────────────────


def to_xbrl_csv(report: dict[str, Any]) -> str:
    """XBRL-ready CSV: one row per data point with element, period and unit."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["datapoint_id", "xbrl_element", "period", "value", "unit", "data_quality", "review_status"])
    for dp, d in report["datapoints"].items():
        w.writerow(
            [dp, d["xbrl_element"], report["reporting_year"], d["value"], d["unit"], d["data_quality"], "needs_review"]
        )
    return buf.getvalue()


def to_xlsx(report: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "E1"
    ws.append(["Data point", "Label", "Value", "Unit", "Data quality", "Sources"])
    for dp, d in report["datapoints"].items():
        ws.append([dp, d["label"], float(Decimal(d["value"])), d["unit"], d["data_quality"], d["source_count"]])
    trail = wb.create_sheet("Audit trail")
    trail.append(["Data point", "Source table", "Source id", "Project id", "Value", "Data quality"])
    for dp, items in report["audit"].items():
        for a in items:
            trail.append(
                [dp, a.get("source") or a.get("derived_from", ""), a.get("source_id", ""), a.get("project_id") or ""]
                + [a.get("value", ""), a.get("data_quality", "")]
            )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(report: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, title=f"Climate report {report['reporting_year']}")
    styles = getSampleStyleSheet()
    head = f"{report.get('company_name') or 'Company'}: {report['template']} {report['reporting_year']}"
    data = [["Data point", "Label", "Value", "Unit", "Quality"]]
    data += [[dp, d["label"], d["value"], d["unit"], d["data_quality"]] for dp, d in report["datapoints"].items()]
    doc.build([Paragraph(head, styles["Title"]), Spacer(1, 12), Table(data, repeatRows=1)])
    return out.getvalue()
