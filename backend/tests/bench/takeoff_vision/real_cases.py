"""The "real" split: sheets the generator did not draw, read by a fixed model answer.

Two shipped sample sheets (``app/scripts/flagship_assets``):

* ``grundriss_erdgeschoss.pdf``: a vector office floor whose exterior walls are
  a dark slab under a white room mask. Ground truth is the sheet's own area
  labels: a room traced around exactly one label is that room; a trace holding
  two labels (two rooms read as one) or none (corridor slice, outside the
  building) is invented.
* ``house_plans.pdf``: a scanned sheet with two floors side by side and no text
  layer. No areas to check; it scores invented rooms and floor isolation.

The model answers are hand-traced with the errors a vision model makes (jitter,
wall centreline, outer face, merged rooms, invented rooms). They are fixed: no
constant may be tuned on this split.

    cd backend
    python -m tests.bench.takeoff_vision.run_bench --split real
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from statistics import median
from types import ModuleType
from typing import Any

from app.modules.takeoff import plan_read as _pr

ASSETS = Path(__file__).resolve().parents[3] / "app" / "scripts" / "flagship_assets"
MEDIUM = 0.62
CORRECT_AREA = 0.03

# (name, box in image px or polygon, model confidence)
GRUNDRISS = {
    "file": "grundriss_erdgeschoss.pdf",
    "view": (2001, 1415),
    "scale": {
        "ref_pixels": [[268, 1120], [526, 1120]],
        "ref_real_value": 5.39,
        "ref_unit": "m",
        "source": "dimension_string",
        "confidence": 0.85,
    },
    "rooms": [
        ("Buero 1.01 (inner, jitter)", (271, 801, 523, 1059), 0.8),
        ("Buero 1.02 (centreline)", (528, 795, 791, 1066), 0.8),
        ("Besprechung (outer face)", (787, 792, 1112, 1072), 0.8),
        ("Grossraumbuero (inner)", (268, 411, 789, 692), 0.3),
        ("Lager 1.10", (1300, 405, 1588, 699), 0.8),
        ("Flur 1.11 (inner)", (268, 697, 1580, 793), 0.8),
        ("WC H+D merged", (793, 411, 1103, 692), 0.85),
        ("corridor slice", (858, 700, 1100, 790), 0.85),
        ("Teekueche+Technik merged", (1110, 798, 1580, 1062), 0.85),
        ("outside building", (1640, 420, 1900, 680), 0.8),
    ],
}
HOUSE = {
    "file": "house_plans.pdf",
    "view": (700, 990),
    "scale": {
        "ref_pixels": [[241, 757], [548, 757]],
        "ref_real_value": 34.5,
        "ref_unit": "ft",
        "source": "dimension_string",
        "confidence": 0.8,
    },
    "rooms": [
        ("Living room", (247, 606, 424, 728), 0.8),
        ("Dining room", (431, 606, 543, 732), 0.8),
        ("Chamber mid", (346, 229, 440, 352), 0.8),
        ("Chamber left", (246, 229, 340, 352), 0.8),
        ("living+dining merged", (247, 606, 543, 732), 0.85),
        ("roof area", (340, 398, 548, 433), 0.8),
        ("margin", (600, 600, 660, 700), 0.8),
    ],
    "invented": {"living+dining merged", "roof area", "margin"},
}


def _body(case: dict[str, Any]) -> dict[str, Any]:
    w, h = case["view"]
    sc = dict(case["scale"], ref_pixels=[[x / w, y / h] for x, y in case["scale"]["ref_pixels"]])
    rooms = []
    for name, box, conf in case["rooms"]:
        x0, y0, x1, y1 = box
        poly = [[x0 / w, y0 / h], [x1 / w, y0 / h], [x1 / w, y1 / h], [x0 / w, y1 / h]]
        rooms.append({"name": name, "polygon": poly, "confidence": conf})
    return {"scale": sc, "rooms": rooms, "symbols": []}


@cache
def _sheet(fname: str) -> tuple[bytes, bytes, float, float, float]:
    data = (ASSETS / fname).read_bytes()
    png, _media, dpi, pw, ph = _pr.rasterize_page(data, 1)
    return data, png, dpi, pw, ph


def read_case(case: dict[str, Any], pr: ModuleType = _pr) -> tuple[Any, Any, list[tuple[float, float, str]]]:
    """Run the belt of module ``pr`` on a case; returns (result, refinement, label lines)."""
    data, png, dpi, pw, ph = _sheet(case["file"])
    vec = pr.extract_vector_layer(data, 1)
    res, ref, _rep = pr.check_plan_read(
        _body(case),
        page=1,
        page_width_pt=pw,
        page_height_pt=ph,
        image_px=(pw * dpi / 72, ph * dpi / 72),
        vector=vec,
        image_png=png,
    )
    lines = _pr._label_lines(vec) if vec is not None and vec.words else []
    return res, ref, lines


def ground_truth(res: Any, lines: list[tuple[float, float, str]], pw: float, ph: float) -> dict[str, float | None]:
    """Room name -> its labelled area, ``None`` for an invented trace."""
    out: dict[str, float | None] = {}
    for room in res.rooms:
        raw = _pr.norm_polygon_to_pdf_points(room.polygon, pw, ph)
        values = [_pr._area_label(t) for cx, cy, t in lines if _pr.point_in_polygon(cx, cy, raw)]
        values = [v for v in values if v is not None]
        out[room.name] = values[0] if len(values) == 1 else None
    return out


def evaluate(pr: ModuleType = _pr) -> dict[str, Any]:
    # Vector sheet: areas against the sheet's own labels.
    _d, _png, _dpi, pw, ph = _sheet(GRUNDRISS["file"])
    res, ref, lines = read_case(GRUNDRISS, pr)
    gt = ground_truth(res, lines, pw, ph)
    ratio = ref.scale.ratio
    errs, confident, confident_ok, invented_conf, above_model = [], 0, 0, 0, 0
    for r in ref.rooms:
        conf_ok = r.confidence >= MEDIUM and r.verdict != "error"
        truth = gt.get(r.name)
        corroborated = getattr(r, "corroborated", False)
        if r.confidence > r.model_confidence + 1e-9 and not corroborated:
            above_model += 1
        if truth is None:
            invented_conf += int(conf_ok)
            continue
        err = abs(_pr.shoelace_area(r.points) / (ratio * ratio) - truth) / truth if ratio else 1.0
        errs.append(err)
        if conf_ok:
            confident += 1
            confident_ok += int(err <= CORRECT_AREA)
    real_gt = sum(1 for v in gt.values() if v is not None)
    # Scanned sheet: invented rooms and the two floors.
    hres, href, _ = read_case(HOUSE, pr)
    h_invented_conf = sum(
        1 for r in href.rooms if r.name in HOUSE["invented"] and r.confidence >= MEDIUM and r.verdict != "error"
    )
    h_isolated = sum(1 for r in href.rooms if r.name not in HOUSE["invented"] and "room:isolated" in r.flags)
    return {
        "vector_rooms_labelled": real_gt,
        "vector_rooms_kept": len(errs),
        "area_err_median_pct": round(100 * median(errs), 3) if errs else None,
        "area_err_max_pct": round(100 * max(errs), 3) if errs else None,
        "area_within_2pct": round(sum(e <= 0.02 for e in errs) / len(errs), 4) if errs else 0.0,
        "confident_precision": round(confident_ok / confident, 4) if confident else 0.0,
        "confident_share": round(confident / real_gt, 4) if real_gt else 0.0,
        "invented_confident": invented_conf + h_invented_conf,
        "invented_total": sum(1 for v in gt.values() if v is None) + len(HOUSE["invented"]),
        "real_rooms_flagged_isolated": h_isolated,
        "conf_above_model_uncorroborated": above_model,
        "scale_err_pct_vs_sheet": round(100 * abs(ratio - 28.3465) / 28.3465, 3) if ratio else None,
    }
