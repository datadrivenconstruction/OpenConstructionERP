"""Quick massing from a short brief: model quantities, an elemental cost range and the programme phases. Pure Python.

Every number carries provenance: a brief value, a generator source (``model_params``: editor spec.rs/rules.json),
the country data file (``app/core/country_data/design_massing.json``), the open reference band per m2 GFA
(``cost_benchmark_reference.json``) or a formula over those. A value without a source is ``None`` and flagged
``source_missing``; nothing is guessed. Optional brief values: floor height, depth, grid, window ratio, plot area,
height limit, slab zone, project currency and an exchange rate the person confirmed.
"""

from __future__ import annotations

import json
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import model_params as mp

_HERE = Path(__file__).resolve().parent
TYPOLOGIES = _HERE / "data" / "massing" / "typologies.json"
_CORE = _HERE.parents[1] / "core" / "country_data"
COUNTRY = _CORE / "design_massing.json"
BANDS = _CORE / "cost_benchmark_reference.json"
REF_TYPES = "app/modules/design/data/massing/typologies.json"
REF_COUNTRY = "app/core/country_data/design_massing.json"
REF_BANDS = "app/core/country_data/cost_benchmark_reference.json"
QUALITY = {"economy": "p10", "standard": "p50", "high": "p90"}
# DIN 276 element -> quantity code the line is measured in
ELEMENTS = {
    "330": "wall_ext",
    "340": "floor_area",
    "350": "floor_area",
    "360": "roof",
    "410": "floor_area",
    "420": "floor_area",
    "440": "floor_area",
}
POSITIVE = ("floor_height_m", "depth_m", "grid_m", "plot_area_m2", "max_height_m")
PHASES = ("substructure", "frame", "envelope", "services_fitout", "commissioning")


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(TYPOLOGIES.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _country() -> dict[str, Any]:
    return json.loads(COUNTRY.read_text(encoding="utf-8")).get("countries", {})


@lru_cache(maxsize=1)
def _bands() -> dict[str, Any]:
    return json.loads(BANDS.read_text(encoding="utf-8"))


def _gen(type_id: str) -> str | None:
    """Generator typology of a type, if the generator builds it."""
    cat = (_data()["types"].get(type_id) or {}).get("generator_category")
    return mp.CATEGORY.get(cat) if cat else None


def types() -> list[dict[str, Any]]:
    """Building types the quick massing knows, whether the generator builds them and whether a band prices them."""
    return [
        {"id": k, "generator": _gen(k) is not None, "priced": v["band"] is not None}
        for k, v in _data()["types"].items()
    ]


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _dec(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _issue(code: str, where: str, severity: str = "error", **params: Any) -> dict[str, Any]:
    return {"code": code, "field": where, "severity": severity, "params": params}


def _src(kind: str, ref: str, formula: str | None = None, status: str = "default") -> dict[str, Any]:
    return {"source": kind, "ref": ref, "formula": formula, "status": status}


def inputs(brief: dict[str, Any]) -> dict[str, tuple[Any, dict[str, Any]]]:
    """Every input value with where it came from: the brief (confirmed) or a generator source (default)."""
    typ = _gen(str(brief.get("building_type")))
    out: dict[str, tuple[Any, dict[str, Any]]] = {}
    mine = _src("brief", "brief", status="confirmed")
    gen = _src("generator", mp.GENERATOR_REF)
    floors = brief.get("storeys") if isinstance(brief.get("storeys"), int) else 1
    if typ:
        max_floors, height, band, corridor = mp.TYPOLOGY[typ]
        dflt = mp.defaults_for(typ, floors)
        out["floor_height_m"] = (height, gen)
        out["depth_m"] = (round(2 * band + corridor, 2), _src("generator", mp.GENERATOR_REF, "2 × band + corridor"))
        out["grid_m"] = (dflt["/structure/grid_m"], gen)
        out["roof"] = (dflt["/envelope/roof"], gen)
        out["lift"] = (dflt["/massing/lift"], gen)
        out["max_storeys"] = (max_floors, gen)
        out["depth_min_m"] = (round(2 * mp.BAND_MIN + corridor, 2), _src("generator", mp.GENERATOR_REF))
    for k in ("floor_height_m", "depth_m", "grid_m", "wwr", "slab_zone_m"):
        if _num(brief.get(k)) is not None:
            out[k] = (float(brief[k]), mine)
    return out


def from_brief_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The short brief inside a project's design brief document (``brief.schema.json``); None if it has no GFA.

    GFA is the brief's own ``gross_floor_area_m2``, else footprint width × depth × storeys (both brief values)."""
    if not isinstance(doc, dict) or (doc.get("use") or {}).get("category") not in _data()["types"]:
        return None
    massing, site = doc.get("massing") or {}, doc.get("site") or {}
    storeys = massing.get("floors_above")
    fp = massing.get("footprint") or {}
    gfa = _num(massing.get("gross_floor_area_m2"))
    if gfa is None and _num(fp.get("width_m")) and _num(fp.get("depth_m")) and isinstance(storeys, int):
        gfa = fp["width_m"] * fp["depth_m"] * storeys
    if gfa is None:
        return None
    out = {
        "building_type": (doc.get("use") or {}).get("category"),
        "gfa_m2": gfa,
        "storeys": storeys,
        "country": doc.get("country"),
        "floor_height_m": massing.get("floor_height_m"),
        "depth_m": fp.get("depth_m"),
        "max_height_m": site.get("max_height_m"),
    }
    return {k: v for k, v in out.items() if v is not None}


def project_fx(base: str, fx_rates: list | None) -> tuple[str | None, str | None]:
    """Rate of the band currency in the project's base currency from the project's own ``fx_rates`` (base units per
    1 foreign unit), with where it came from; (None, None) when the project does not list it."""
    band = _bands()["currency"]
    if base.upper() == band:
        return None, None
    for r in fx_rates or []:
        if isinstance(r, dict) and str(r.get("code", "")).upper() == band and _dec(r.get("rate")):
            return str(r["rate"]), f"project.fx_rates[{band}]"
    return None, None


def check(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Implausible, contradictory or unsourced brief values, every one at once."""
    out: list[dict[str, Any]] = []
    if brief.get("building_type") not in _data()["types"]:
        return [_issue("unknown_type", "building_type", value=brief.get("building_type"))]
    gfa, storeys = _num(brief.get("gfa_m2")), brief.get("storeys")
    if gfa is None or gfa <= 0:
        out.append(_issue("gfa_invalid", "gfa_m2"))
    if not isinstance(storeys, int) or isinstance(storeys, bool) or storeys < 1:
        out.append(_issue("storeys_invalid", "storeys"))
        return out
    v = inputs(brief)
    for k in ("floor_height_m", "depth_m"):
        if k not in v:
            out.append(_issue("source_missing", k, field=k))
    if "max_storeys" in v and storeys > v["max_storeys"][0]:
        out.append(_issue("storeys_over_type_max", "storeys", max=v["max_storeys"][0]))
    if brief.get("quality", "standard") not in QUALITY:
        out.append(_issue("quality_invalid", "quality"))
    height = v.get("floor_height_m", (None,))[0]
    lim = _num(brief.get("max_height_m"))
    if height and lim is not None and storeys * height > lim:
        out.append(_issue("height_over_limit", "storeys", height=round(storeys * height, 2), limit=lim))
    minimum = (_country().get(str(brief.get("country") or "").upper()) or {}).get("min_clear_height_m")
    if height and minimum is not None:
        if "slab_zone_m" not in v:
            # no source gives the slab zone: the clear height is unknown, so it is not checked
            out.append(_issue("source_missing", "slab_zone_m", "warning", field="slab_zone_m"))
        else:
            clear = round(height - v["slab_zone_m"][0], 3)
            if clear < minimum:
                out.append(_issue("clear_height_below_minimum", "floor_height_m", clear=clear, minimum=minimum))
    if gfa is not None and gfa > 0:
        footprint = gfa / storeys
        plot = _num(brief.get("plot_area_m2"))
        if plot is not None and footprint > plot:
            out.append(_issue("footprint_over_plot", "plot_area_m2", footprint=round(footprint, 1), plot=plot))
        depth = v.get("depth_m", (None,))[0]
        if depth and depth > math.sqrt(footprint):
            out.append(_issue("depth_clipped", "depth_m", "warning", depth=depth, used=round(math.sqrt(footprint), 2)))
        if "depth_min_m" in v:
            smallest = round(v["depth_min_m"][0] * mp.params_for({}, _gen(brief["building_type"]))[2].min, 1)
            if footprint < smallest:
                out.append(_issue("storey_too_small", "gfa_m2", footprint=round(footprint, 1), minimum=smallest))
    for k in POSITIVE:
        if k in brief and brief[k] is not None and not ((_num(brief[k]) or 0) > 0):
            out.append(_issue("value_invalid", k, field=k))
    zone = brief.get("slab_zone_m")
    if zone is not None and (_num(zone) is None or not 0 <= zone < (height or 0)):
        out.append(_issue("value_invalid", "slab_zone_m", field="slab_zone_m"))
    wwr = _num(brief.get("wwr"))
    if wwr is not None and not 0 <= wwr <= 1:
        out.append(_issue("wwr_invalid", "wwr"))
    fx = brief.get("fx_rate")
    if fx is not None and (_dec(fx) is None or _dec(fx) <= 0):
        out.append(_issue("fx_invalid", "fx_rate"))
    return out


def _model(brief: dict[str, Any], v: dict[str, tuple[Any, dict[str, Any]]]) -> dict[str, Any]:
    gfa, storeys = float(brief["gfa_m2"]), int(brief["storeys"])
    h, depth_in = v["floor_height_m"][0], v["depth_m"][0]
    area = gfa / storeys
    depth = min(depth_in, math.sqrt(area))
    inputs_out = {k: {"value": val, "provenance": p, "flag": None} for k, (val, p) in v.items()}
    if depth < depth_in:
        # the given depth cannot fit a footprint this small: the square footprint is used and said so
        inputs_out["depth_m"] = {
            "value": round(depth, 2),
            "provenance": _src("formula", REF_TYPES, "√(GFA ÷ storeys)", "derived"),
            "flag": "depth_clipped",
            "given": {"value": depth_in, "provenance": v["depth_m"][1]},
        }
    width = area / depth
    perim = 2 * (width + depth)
    grid = v.get("grid_m", (None,))[0]
    wwr = v.get("wwr", (None,))[0]
    wall_ext = perim * h * storeys
    f = "formula"

    def q(code: str, value: Any, unit: str, formula: str | None, src: dict | None = None) -> dict[str, Any]:
        val = round(value, 2) if isinstance(value, float) else value
        p = src or (_src(f, REF_TYPES, formula, "derived") if value is not None else _src("none", "", formula, "none"))
        return {
            "code": code,
            "value": val,
            "unit": unit,
            "provenance": p,
            "flag": None if value is not None else "source_missing",
        }

    roof_form = v.get("roof", (None,))[0]
    roof = area if roof_form == "flat" else None
    gridinfo = None
    if grid:
        bx, by = math.ceil(width / grid - 1e-9), math.ceil(depth / grid - 1e-9)
        gridinfo = {"spacing_m": grid, "bays_x": bx, "bays_y": by, "columns_per_storey": (bx + 1) * (by + 1)}
    lift = v.get("lift")
    return {
        "levels": [{"index": i, "elevation_m": round(i * h, 3), "height_m": h} for i in range(storeys)],
        "height_m": round(storeys * h, 3),
        "footprint": {"width_m": round(width, 2), "depth_m": round(depth, 2), "area_m2": round(area, 2)},
        "grid": gridinfo,
        "roof_form": roof_form,
        "inputs": inputs_out,
        "quantities": [
            q("floor_area", gfa, "m2", None, _src("brief", "brief", None, "confirmed")),
            q("slab_ground", area, "m2", "GFA ÷ storeys"),
            q("slab_suspended", area * (storeys - 1), "m2", "GFA ÷ storeys × (storeys − 1)"),
            q("roof", roof, "m2", "footprint (flat roof); pitched roof needs the slope"),
            q("wall_ext_length", perim * storeys, "m", "2 × (width + depth) × storeys"),
            q("wall_ext", wall_ext, "m2", "perimeter × storey height × storeys"),
            q("openings", wall_ext * wwr if wwr is not None else None, "m2", "external wall × window ratio (brief)"),
            q(
                "columns",
                gridinfo["columns_per_storey"] * storeys if gridinfo else None,
                "pcs",
                "(ceil(width ÷ grid) + 1) × (ceil(depth ÷ grid) + 1) × storeys",
            ),
            q(
                "lifts",
                (1 if lift[0] else 0) if lift else None,
                "pcs",
                "generator lift rule (defaults_for)",
                lift[1] if lift else None,
            ),
        ],
    }


def _s(d: Decimal | None) -> str | None:
    if d is None:
        return None
    return format(d.normalize(), "f") if d == d.to_integral_value() else format(d, "f")


def _cost(brief: dict[str, Any], model: dict[str, Any], fx_source: str | None) -> dict[str, Any]:
    ref = _bands()
    band_type = _data()["types"][brief["building_type"]]["band"]
    # only the band this market's own data names; never another market's prices converted by a rate
    std = (_country().get(str(brief.get("country") or "").upper()) or {}).get("cost_band_standard")
    band = next((b for b in ref["bands"] if b["project_type"] == band_type and b["standard"] == std), None)
    base = {
        "source": ref["source"],
        "ref": REF_BANDS,
        "base_date": ref["base_date"],
        "needs_expert_review": ref["needs_expert_review"],
    }
    if band is None:
        # the market names no band standard of its own, or its standard has no band for this type
        market_known = std is not None and any(b["standard"] == std for b in ref["bands"])
        return {
            **base,
            "total": None,
            "reason": "no_band_type" if market_known else "no_band_market",
            "flag": "source_missing",
            "market": std,
            "currency": brief.get("currency"),
            "lines": [],
        }
    cur = (brief.get("currency") or ref["currency"]).upper()
    fx = Decimal(1)
    if cur != ref["currency"]:
        rate = _dec(brief.get("fx_rate"))
        if rate is None or rate <= 0:
            return {**base, "total": None, "reason": "currency", "currency": cur, "band_currency": ref["currency"]}
        fx = rate
    pct = QUALITY[brief.get("quality") or "standard"]
    gfa = Decimal(str(brief["gfa_m2"]))
    qty = {x["code"]: x["value"] for x in model["quantities"]}
    # percentiles do not add up: each element and the total carry their own p10..p90, nothing is a remainder
    lines = []
    for code, qcode in ELEMENTS.items():
        el = band["elements"].get(code)
        if el is None:
            continue
        amount = Decimal(el[pct]) * gfa * fx
        q = qty.get(qcode)
        rate = (amount / Decimal(str(q))).quantize(Decimal("0.01"), ROUND_HALF_UP) if q else None
        lines.append(
            {
                "code": code,
                "quantity": q,
                "unit": "m2",
                "unit_rate": _s(rate),
                "amount": _s(amount),
                "range": {k: _s(Decimal(el[k]) * gfa * fx) for k in ("p10", "p50", "p90")},
                "provenance": {
                    "source": "benchmark",
                    "ref": f"{REF_BANDS} {band_type}/din276/{code}/{pct}",
                    "formula": "band rate per m2 GFA × GFA × fx; unit rate = amount ÷ quantity",
                },
            }
        )
    total = Decimal(band["total"][pct]) * gfa * fx
    lo, hi = Decimal(band["total"]["p10"]) * fx, Decimal(band["total"]["p90"]) * fx
    per = total / gfa
    return {
        **base,
        "currency": cur,
        "fx_rate": _s(fx) if cur != ref["currency"] else None,
        "fx_source": (fx_source or "brief") if cur != ref["currency"] else None,
        "quality": pct,
        "total": _s(total),
        "per_m2": _s(per),
        "lines": lines,
        "benchmark": {
            "low": _s(lo),
            "mid": _s(Decimal(band["total"]["p50"]) * fx),
            "high": _s(hi),
            "ref": f"{REF_BANDS} {band_type}/din276/total",
        },
        "reason": None,
    }


def _schedule() -> dict[str, Any]:
    """Phases only: no open source gives durations for a massing without a model, so every duration is flagged.
    Sourced durations come once a model exists (``schedule.py`` with ``data/schedule``)."""
    return {
        "phases": [{"code": c, "start_day": None, "days": None, "flag": "rate_missing"} for c in PHASES],
        "total_days": None,
        "reason": "rate_missing",
    }


def build(brief: dict[str, Any], *, fx_source: str | None = None) -> dict[str, Any]:
    """Model, cost and programme for a short brief; with blocking issues only the issues come back.

    ``fx_source`` names where a rate came from (the server sets it; a brief cannot claim one)."""
    issues = check(brief)
    if any(i["severity"] == "error" for i in issues):
        return {"issues": issues, "model": None, "cost": None, "schedule": None, "suggestions": [], "generator": None}
    v = inputs(brief)
    model = _model(brief, v)
    suggestions = [
        {"pointer": k, "value": val, "provenance": p}
        for k, (val, p) in v.items()
        if p["status"] == "default" and k in ("floor_height_m", "depth_m", "grid_m", "roof", "lift")
    ]
    country = _country().get(str(brief.get("country") or "").upper())
    if country:
        suggestions.append(
            {
                "pointer": "min_clear_height_m",
                "value": country["min_clear_height_m"],
                "provenance": {
                    "source": "country",
                    "ref": REF_COUNTRY,
                    "formula": None,
                    "status": "default",
                    "note": country["source"],
                },
            }
        )
    return {
        "issues": issues,
        "generator": _gen(brief["building_type"]) is not None,
        "model": model,
        "cost": _cost(brief, model, fx_source),
        "schedule": _schedule(),
        "suggestions": suggestions,
    }
