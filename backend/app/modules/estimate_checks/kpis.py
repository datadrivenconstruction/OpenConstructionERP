# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure KPI arithmetic for the estimate check.

Everything here works on plain dicts (an estimate snapshot) and plain numbers, so
it is cheap to test and has no database or framework dependency.

Snapshot shape (built by :mod:`app.modules.estimate_checks.service`)::

    {
        "positions": [{"id", "ordinal", "description", "unit", "quantity", "unit_rate",
                       "total", "resources": [...], "metadata": {...}, "db_rate": float|None}],
        "markups": [{"category", "percentage", "is_active"}],
    }

Resource types follow the BOQ resource editor: ``labor``, ``material``,
``equipment``, ``subcontractor``, ``operator`` (counted as equipment), ``other``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

GROUPS = ("labour", "equipment", "materials", "subcontractors", "markup", "data_quality")
STATUS_NORMAL = "normal"
STATUS_SUSPECT = "suspect"
STATUS_WARNING = "warning"
STATUS_NO_DATA = "no_data"

_HOUR_UNITS = {"h", "hr", "hrs", "hour", "hours", "std", "ч", "час", "mh", "manhour", "man-hour"}


@dataclass(frozen=True)
class KpiDef:
    """Static description of one KPI and its fallback band."""

    kpi_id: str
    group: str
    unit: str  # "pct", "money", "ratio", "count"
    kind: str  # "historical" (compared with past estimates) or "count" (fixed thresholds)
    default_low: float | None = None
    default_high: float | None = None


KPI_DEFS: tuple[KpiDef, ...] = (
    KpiDef("labour_share", "labour", "pct", "historical", 20.0, 45.0),
    KpiDef("labour_cost_per_unit", "labour", "money", "historical"),
    KpiDef("avg_crew_rate", "labour", "money", "historical"),
    KpiDef("equipment_share", "equipment", "pct", "historical", 3.0, 15.0),
    KpiDef("equipment_to_labour_hours", "equipment", "ratio", "historical", 0.05, 0.6),
    KpiDef("material_share", "materials", "pct", "historical", 35.0, 65.0),
    KpiDef("avg_waste_pct", "materials", "pct", "historical", 2.0, 10.0),
    KpiDef("subcontractor_share", "subcontractors", "pct", "historical", 0.0, 40.0),
    KpiDef("single_quote_items", "subcontractors", "count", "count"),
    KpiDef("overhead_pct", "markup", "pct", "historical", 5.0, 15.0),
    KpiDef("profit_pct", "markup", "pct", "historical", 3.0, 10.0),
    KpiDef("risk_pct", "markup", "pct", "historical", 0.0, 10.0),
    KpiDef("total_markup_pct", "markup", "pct", "historical", 10.0, 30.0),
    KpiDef("zero_rate", "data_quality", "count", "count"),
    KpiDef("zero_quantity", "data_quality", "count", "count"),
    KpiDef("duplicates", "data_quality", "count", "count"),
    KpiDef("unpriced", "data_quality", "count", "count"),
    KpiDef("rate_far_from_database", "data_quality", "count", "count"),
)
KPI_BY_ID: dict[str, KpiDef] = {k.kpi_id: k for k in KPI_DEFS}

DEFAULT_SETTINGS: dict[str, Any] = {
    # "auto" narrows to same project type, currency and region, then widens until
    # enough comparables are found; "currency" only matches currency; "all" uses every estimate.
    "comparables": "auto",
    "min_comparables": 5,
    # A value beyond the usual range by more than this share of the range width is a warning.
    "warning_margin": 0.5,
    # Rate differs from the cost database rate by more than this percentage.
    "database_rate_tolerance_pct": 30.0,
    # Count KPIs: one hit is suspect; this share of positions (percent) or more is a warning.
    "count_warning_share_pct": 5.0,
    "kpis": {k.kpi_id: {"enabled": True} for k in KPI_DEFS},
}


def merge_settings(stored: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay stored workspace settings on the defaults (unknown keys dropped)."""
    out: dict[str, Any] = {k: v for k, v in DEFAULT_SETTINGS.items() if k != "kpis"}
    out["kpis"] = {k: dict(v) for k, v in DEFAULT_SETTINGS["kpis"].items()}
    if not stored:
        return out
    for key in ("comparables", "min_comparables", "warning_margin", "database_rate_tolerance_pct"):
        if key in stored and stored[key] is not None:
            out[key] = stored[key]
    if stored.get("count_warning_share_pct") is not None:
        out["count_warning_share_pct"] = stored["count_warning_share_pct"]
    for kpi_id, cfg in (stored.get("kpis") or {}).items():
        if kpi_id in out["kpis"] and isinstance(cfg, dict):
            for ck in ("enabled", "low", "high"):
                if ck in cfg:
                    out["kpis"][kpi_id][ck] = cfg[ck]
    return out


# ── number helpers ─────────────────────────────────────────────────────────


def num(value: Any) -> float:
    """Lenient float: strings, None and junk become 0.0; never NaN or infinite."""
    try:
        f = float(str(value).replace(",", ".")) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in 0..100) of a non-empty list."""
    if not values:
        raise ValueError("percentile of an empty list")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def confidence_for(n: int, *, fallback: bool = False) -> float:
    """Confidence of a rating: grows with the number of comparable estimates."""
    if fallback or n <= 0:
        return 0.3
    return round(min(0.95, 0.3 + 0.65 * (1 - math.exp(-n / 10.0))), 2)


def rate_against_range(value: float, low: float, high: float, margin: float) -> str:
    """Normal inside ``[low, high]``; warning beyond it by more than ``margin`` x width; else suspect."""
    if low <= value <= high:
        return STATUS_NORMAL
    width = max(high - low, abs(high) * 0.1, 1e-9)
    if value < low - margin * width or value > high + margin * width:
        return STATUS_WARNING
    return STATUS_SUSPECT


def rate_count(count: int, total_positions: int, warning_share_pct: float) -> str:
    """Count KPIs: none is normal, a few is suspect, a large share is a warning."""
    if count <= 0:
        return STATUS_NORMAL
    if total_positions > 0 and count * 100.0 / total_positions >= warning_share_pct:
        return STATUS_WARNING
    return STATUS_SUSPECT


# ── KPI computation ────────────────────────────────────────────────────────


@dataclass
class KpiValue:
    """A computed KPI: value (None when not measurable) and the positions behind it."""

    kpi_id: str
    value: float | None
    position_ids: list[str] = field(default_factory=list)
    unit_label: str | None = None  # e.g. the main quantity unit for cost per unit


def _rtype(res: dict[str, Any]) -> str:
    t = str(res.get("type") or "other").lower()
    if t in ("labour", "labor"):
        return "labor"
    if t in ("operator", "equipment", "plant"):
        return "equipment"
    if t.startswith("subcontract"):
        return "subcontractor"
    if t == "material":
        return "material"
    return "other"


def _res_cost(res: dict[str, Any], pos_qty: float) -> float:
    """Total cost of one resource line in the position (per-unit norm x position quantity)."""
    if res.get("total") is not None:
        per_unit = num(res.get("total"))
    else:
        per_unit = num(res.get("quantity")) * num(res.get("unit_rate"))
    return per_unit * pos_qty


def _res_hours(res: dict[str, Any], pos_qty: float) -> float:
    unit = str(res.get("unit") or "").strip().lower().rstrip(".")
    if unit in _HOUR_UNITS:
        return num(res.get("quantity")) * pos_qty
    return num(res.get("hours")) * pos_qty


def _priced_lines(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Leaf positions only: section headers carry no quantity and no resources."""
    out = []
    for p in snapshot.get("positions") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("node_type") or "").lower() in ("section", "group", "heading", "title"):
            continue
        if not str(p.get("unit") or "").strip() and not p.get("resources"):
            continue
        out.append(p)
    return out


def compute_kpis(snapshot: dict[str, Any], *, db_tolerance_pct: float = 30.0) -> dict[str, KpiValue]:
    """Compute every KPI of one estimate snapshot."""
    lines = _priced_lines(snapshot)
    by_type: dict[str, float] = defaultdict(float)
    hours: dict[str, float] = defaultdict(float)
    ids_by_type: dict[str, list[str]] = defaultdict(list)
    waste_sum = 0.0
    waste_weight = 0.0
    waste_ids: list[str] = []
    direct = 0.0
    qty_by_unit: dict[str, float] = defaultdict(float)
    cost_by_unit: dict[str, float] = defaultdict(float)
    labour_ids_by_unit: dict[str, list[str]] = defaultdict(list)
    labour_by_unit: dict[str, float] = defaultdict(float)
    out: dict[str, KpiValue] = {}

    zero_rate: list[str] = []
    zero_qty: list[str] = []
    unpriced: list[str] = []
    far_db: list[str] = []
    single_quote: list[str] = []
    seen: dict[tuple[str, str, str], str] = {}
    dupes: list[str] = []

    for p in lines:
        pid = str(p.get("id") or "")
        qty = num(p.get("quantity"))
        rate = num(p.get("unit_rate"))
        total = num(p.get("total")) or qty * rate
        unit = str(p.get("unit") or "").strip().lower()
        resources = [r for r in (p.get("resources") or []) if isinstance(r, dict)]
        direct += total
        qty_by_unit[unit] += qty
        cost_by_unit[unit] += total

        rolled = 0.0
        for r in resources:
            t = _rtype(r)
            c = _res_cost(r, qty)
            rolled += c
            by_type[t] += c
            if pid not in ids_by_type[t]:
                ids_by_type[t].append(pid)
            hours[t] += _res_hours(r, qty)
            if t == "labor":
                labour_by_unit[unit] += c
                labour_ids_by_unit[unit].append(pid)
            if t == "material" and r.get("waste_pct") is not None:
                waste_sum += num(r.get("waste_pct")) * max(c, 1e-9)
                waste_weight += max(c, 1e-9)
                waste_ids.append(pid)
        if not resources and total > 0:
            by_type["unclassified"] += total

        meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
        is_sub = any(_rtype(r) == "subcontractor" for r in resources) or bool(meta.get("subcontractor"))
        quotes = meta.get("quotes")
        quote_count = len(quotes) if isinstance(quotes, list) else int(num(meta.get("quote_count")))
        if is_sub and quote_count < 2:
            single_quote.append(pid)

        if qty > 0 and rate == 0:
            (zero_rate if rolled > 0 or resources else unpriced).append(pid)
        elif qty == 0 and rate > 0:
            zero_qty.append(pid)
        elif qty == 0 and rate == 0:
            unpriced.append(pid)

        db_rate = p.get("db_rate")
        if db_rate is not None and num(db_rate) > 0 and rate > 0:
            if abs(rate - num(db_rate)) * 100.0 / num(db_rate) > db_tolerance_pct:
                far_db.append(pid)

        key = (" ".join(str(p.get("description") or "").lower().split()), unit, f"{rate:.4f}")
        if key[0]:
            if key in seen:
                if seen[key] not in dupes:
                    dupes.append(seen[key])
                dupes.append(pid)
            else:
                seen[key] = pid

    def share(t: str) -> KpiValue:
        v = by_type[t] * 100.0 / direct if direct > 0 and any(by_type.values()) else None
        return KpiValue(t, v, ids_by_type[t])

    lab = share("labor")
    out["labour_share"] = KpiValue("labour_share", lab.value, lab.position_ids)
    main_unit = max(cost_by_unit, key=lambda u: cost_by_unit[u]) if cost_by_unit else None
    if main_unit and qty_by_unit[main_unit] > 0 and labour_by_unit[main_unit] > 0:
        out["labour_cost_per_unit"] = KpiValue(
            "labour_cost_per_unit",
            labour_by_unit[main_unit] / qty_by_unit[main_unit],
            labour_ids_by_unit[main_unit],
            unit_label=main_unit,
        )
    else:
        out["labour_cost_per_unit"] = KpiValue("labour_cost_per_unit", None, unit_label=main_unit)
    out["avg_crew_rate"] = KpiValue(
        "avg_crew_rate",
        by_type["labor"] / hours["labor"] if hours["labor"] > 0 else None,
        ids_by_type["labor"],
    )
    eq = share("equipment")
    out["equipment_share"] = KpiValue("equipment_share", eq.value, eq.position_ids)
    out["equipment_to_labour_hours"] = KpiValue(
        "equipment_to_labour_hours",
        hours["equipment"] / hours["labor"] if hours["labor"] > 0 and hours["equipment"] > 0 else None,
        ids_by_type["equipment"],
    )
    mat = share("material")
    out["material_share"] = KpiValue("material_share", mat.value, mat.position_ids)
    out["avg_waste_pct"] = KpiValue("avg_waste_pct", waste_sum / waste_weight if waste_weight else None, waste_ids)
    sub = share("subcontractor")
    out["subcontractor_share"] = KpiValue("subcontractor_share", sub.value, sub.position_ids)
    out["single_quote_items"] = KpiValue("single_quote_items", float(len(single_quote)), single_quote)

    pct: dict[str, float] = defaultdict(float)
    has_markups = False
    for m in snapshot.get("markups") or []:
        if not isinstance(m, dict) or not m.get("is_active", True):
            continue
        cat = str(m.get("category") or "other").lower()
        if cat == "tax":
            continue
        has_markups = True
        bucket = {"overhead": "overhead", "profit": "profit", "contingency": "risk", "risk": "risk"}.get(cat, "other")
        pct[bucket] += num(m.get("percentage"))
    for bucket, kpi_id in (("overhead", "overhead_pct"), ("profit", "profit_pct"), ("risk", "risk_pct")):
        out[kpi_id] = KpiValue(kpi_id, pct[bucket] if has_markups else None)
    out["total_markup_pct"] = KpiValue("total_markup_pct", sum(pct.values()) if has_markups else None)

    for kpi_id, ids in (
        ("zero_rate", zero_rate),
        ("zero_quantity", zero_qty),
        ("duplicates", dupes),
        ("unpriced", unpriced),
        ("rate_far_from_database", far_db),
    ):
        out[kpi_id] = KpiValue(kpi_id, float(len(ids)), ids)
    out["_meta"] = KpiValue("_meta", float(len(lines)))
    return out


def history_values(history: list[dict[str, Any]], kpi_id: str, unit_label: str | None = None) -> list[float]:
    """Values of one KPI over past estimates (each a ``{kpi_id: value, "_units": {...}}`` dict)."""
    vals = []
    for h in history:
        v = h.get(kpi_id)
        if v is None:
            continue
        if unit_label is not None and (h.get("_units") or {}).get(kpi_id) != unit_label:
            continue
        vals.append(float(v))
    return vals


def assess(
    kv: KpiValue,
    history: list[dict[str, Any]],
    settings: dict[str, Any],
    total_positions: int,
) -> dict[str, Any]:
    """Rate one KPI: status, usual range, comparables count, confidence and reason code."""
    kdef = KPI_BY_ID[kv.kpi_id]
    cfg = settings["kpis"].get(kv.kpi_id, {})
    base: dict[str, Any] = {
        "kpi_id": kv.kpi_id,
        "group": kdef.group,
        "unit": kdef.unit,
        "unit_label": kv.unit_label,
        "value": None if kv.value is None else round(kv.value, 4),
        "low": None,
        "high": None,
        "compared": 0,
        "position_ids": kv.position_ids[:200],
    }
    if kdef.kind == "count":
        count = int(kv.value or 0)
        status = rate_count(count, total_positions, float(settings["count_warning_share_pct"]))
        return {**base, "status": status, "confidence": 0.9, "reason": "count_none" if count == 0 else "count_found"}
    if kv.value is None:
        return {**base, "status": STATUS_NO_DATA, "confidence": 0.0, "reason": "not_measurable"}
    margin = float(settings["warning_margin"])
    if cfg.get("low") is not None and cfg.get("high") is not None:
        low, high = float(cfg["low"]), float(cfg["high"])
        status = rate_against_range(kv.value, low, high, margin)
        return {
            **base,
            "low": low,
            "high": high,
            "status": status,
            "confidence": 0.8,
            "reason": _reason(status, "custom"),
        }
    vals = history_values(history, kv.kpi_id, kv.unit_label if kv.kpi_id == "labour_cost_per_unit" else None)
    if len(vals) >= int(settings["min_comparables"]):
        low, high = percentile(vals, 10), percentile(vals, 90)
        status = rate_against_range(kv.value, low, high, margin)
        return {
            **base,
            "low": round(low, 4),
            "high": round(high, 4),
            "compared": len(vals),
            "status": status,
            "confidence": confidence_for(len(vals)),
            "reason": _reason(status, "history"),
        }
    if kdef.default_low is not None and kdef.default_high is not None:
        status = rate_against_range(kv.value, kdef.default_low, kdef.default_high, margin)
        return {
            **base,
            "low": kdef.default_low,
            "high": kdef.default_high,
            "compared": len(vals),
            "status": status,
            "confidence": confidence_for(0, fallback=True),
            "reason": _reason(status, "default"),
        }
    return {**base, "compared": len(vals), "status": STATUS_NO_DATA, "confidence": 0.0, "reason": "too_few_comparables"}


def _reason(status: str, source: str) -> str:
    if status == STATUS_NORMAL:
        return f"within_{source}"
    return f"outside_{source}"


def history_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compact KPI row of a past estimate for the comparables pool."""
    kpis = compute_kpis(snapshot)
    row: dict[str, Any] = {k: v.value for k, v in kpis.items() if not k.startswith("_")}
    row["_units"] = {"labour_cost_per_unit": kpis["labour_cost_per_unit"].unit_label}
    return row
