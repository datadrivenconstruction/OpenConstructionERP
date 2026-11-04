"""Turn plan-read proposals into accuracy metrics against generated ground truth.

Two pipelines are scored the same way. ``baseline`` is the proposal builder as
it shipped before the belt (schema validation, scale plausibility, shoelace
area, self-intersection cap; the model's polygons and confidences as given).
``current`` is :func:`app.modules.takeoff.plan_read.check_plan_read`, the call
the service makes, fed the page's own vector layer.

Room metrics match proposals to ground truth by IoU (greedy, highest first).
A room proposal is *correct* when IoU >= 0.85 and its area is within 3 percent;
that label is what confidence calibration (ECE, Brier) is measured against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from app.modules.takeoff import plan_read as pr

from .mock_model import MockResponse
from .plans import Plan, Point

MATCH_IOU = 0.5
GOOD_IOU = 0.75
CORRECT_IOU = 0.85
CORRECT_AREA = 0.03
MEDIUM = 0.62


@dataclass
class Proposals:
    ratio: float | None
    scale_confidence: float
    rooms: list[dict[str, Any]] = field(default_factory=list)  # points, area, perimeter, confidence, verdict
    symbols: dict[str, list[Point]] = field(default_factory=dict)


def baseline_pipeline(plan: Plan, resp: MockResponse) -> Proposals:
    result, _dropped = pr.parse_plan_read_response(
        resp.body, page=1, page_width_pt=plan.page_w, page_height_pt=plan.page_h
    )
    ratio, _ = pr.resolve_scale_ratio(None, result.scale, plan.page_w, plan.page_h)
    out = Proposals(ratio=ratio, scale_confidence=float(result.scale.confidence) if result.scale else 0.0)
    for room in result.rooms:
        pts = pr.norm_polygon_to_pdf_points(room.polygon, plan.page_w, plan.page_h)
        bad = pr.polygon_self_intersects(pts)
        conf = min(room.confidence, MEDIUM - 0.01) if bad else room.confidence
        out.rooms.append(_room_row(pts, ratio, conf, "error" if bad else "ok"))
    for sym in result.symbols:
        key = _symbol_key(sym.element_class)
        out.symbols.setdefault(key, []).extend(pr.norm_polygon_to_pdf_points(sym.centers, plan.page_w, plan.page_h))
    return out


def current_pipeline(
    plan: Plan, resp: MockResponse, vector: pr.VectorLayer | None, image_png: bytes | None = None
) -> Proposals:
    _result, ref, _repairs = pr.check_plan_read(
        resp.body,
        page=1,
        page_width_pt=plan.page_w,
        page_height_pt=plan.page_h,
        image_px=resp.image_px,
        vector=vector,
        image_png=image_png,
    )
    out = Proposals(ratio=ref.scale.ratio, scale_confidence=ref.scale.confidence)
    for room in ref.rooms:
        out.rooms.append(_room_row(room.points, ref.scale.ratio, room.confidence, room.verdict))
    for sym in ref.symbols:
        out.symbols.setdefault(_symbol_key(sym.element_class), []).extend(sym.centers)
    return out


def _room_row(pts: list[Point], ratio: float | None, conf: float, verdict: str) -> dict[str, Any]:
    area = pr.shoelace_area(pts) / (ratio * ratio) if ratio else None
    perim = pr.polygon_perimeter(pts) / ratio if ratio else None
    return {"points": pts, "area": area, "perimeter": perim, "confidence": float(conf), "verdict": verdict}


def _symbol_key(name: str) -> str:
    low = (name or "").lower()
    if "door" in low:
        return "door"
    if "window" in low:
        return "window"
    return low


@dataclass
class PlanScore:
    gt_rooms: int = 0
    proposals: int = 0
    matched: int = 0
    good: int = 0
    ious: list[float] = field(default_factory=list)
    area_err: list[float] = field(default_factory=list)
    perim_err: list[float] = field(default_factory=list)
    scale_err: float | None = None
    count_acc: list[float] = field(default_factory=list)
    count_exact: list[int] = field(default_factory=list)
    calib: list[tuple[float, int]] = field(default_factory=list)  # (confidence, correct)
    confident: int = 0
    confident_correct: int = 0


def score_plan(plan: Plan, props: Proposals) -> PlanScore:
    s = PlanScore(gt_rooms=len(plan.rooms), proposals=len(props.rooms))
    if props.ratio:
        s.scale_err = abs(props.ratio - plan.ratio) / plan.ratio
    pairs = []
    for i, room in enumerate(props.rooms):
        for j, gt in enumerate(plan.rooms):
            iou = pr.polygon_iou(room["points"], gt.inner_pt, grid=160)
            if iou >= MATCH_IOU:
                pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    match: dict[int, tuple[int, float]] = {}
    for iou, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        match[i] = (j, iou)
    for i, room in enumerate(props.rooms):
        correct = 0
        if i in match:
            j, iou = match[i]
            gt = plan.rooms[j]
            s.matched += 1
            s.ious.append(iou)
            if iou >= GOOD_IOU:
                s.good += 1
            if room["area"] is not None:
                ae = abs(room["area"] - gt.area_m2) / gt.area_m2
                s.area_err.append(ae)
                s.perim_err.append(abs(room["perimeter"] - gt.perimeter_m) / gt.perimeter_m)
                correct = int(iou >= CORRECT_IOU and ae <= CORRECT_AREA)
        s.calib.append((room["confidence"], correct))
        if room["confidence"] >= MEDIUM and room["verdict"] != "error":
            s.confident += 1
            s.confident_correct += correct
    for key, gts in (("door", plan.doors), ("window", plan.windows)):
        if not gts:
            continue
        n = len(props.symbols.get(key, []))
        s.count_acc.append(max(0.0, 1.0 - abs(n - len(gts)) / len(gts)))
        s.count_exact.append(int(n == len(gts)))
    return s


def catch_injections(plan: Plan, resp: MockResponse, props: Proposals) -> list[tuple[str, bool]]:
    """For each injected attack, did the belt keep it out of the confident set?"""
    out: list[tuple[str, bool]] = []
    confident = [r for r in props.rooms if r["confidence"] >= MEDIUM and r["verdict"] != "error"]
    for inj in resp.injections:
        k = inj.kind
        if k.startswith("scale_"):
            bad = props.ratio is not None and abs(props.ratio - plan.ratio) / plan.ratio > 0.05
            out.append((k, not (bad and props.scale_confidence >= MEDIUM)))
        elif k in ("room_duplicate_exact", "room_duplicate_shifted"):
            gt = next(r for r in plan.rooms if r.name == inj.payload["gt_name"])
            # An error row (crossed ring) is blocked at accept, so it cannot double-count a room.
            live = [r for r in props.rooms if r["verdict"] != "error"]
            hits = [r for r in live if pr.polygon_iou(r["points"], gt.inner_pt) >= MATCH_IOU]
            out.append((k, len(hits) <= 1))
        elif k == "room_self_intersecting":
            pts = pr.norm_polygon_to_pdf_points(inj.payload["polygon_n"], plan.page_w, plan.page_h)
            hit = any(_same_ring(r["points"], pts) for r in confident)
            out.append((k, not hit))
        elif k in ("room_hallucinated_margin", "room_hallucinated_title_block", "room_hallucinated_furniture"):
            poly = inj.payload.get("polygon_n")
            pts = (
                pr.norm_polygon_to_pdf_points(poly, plan.page_w, plan.page_h)
                if poly is not None
                else inj.payload["polygon"]
            )
            hit = any(pr.polygon_iou(r["points"], pts) >= MATCH_IOU for r in confident)
            out.append((k, not hit))
        elif k in ("room_out_of_page", "room_pixel_coords_mixed", "room_degenerate", "room_non_numeric"):
            # These carry no on-page geometry worth keeping: nothing confident may
            # sit outside the ground-truth rooms because of them.
            stray = [
                r for r in confident if not any(pr.polygon_iou(r["points"], g.inner_pt) >= 0.3 for g in plan.rooms)
            ]
            out.append((k, not stray))
        elif k == "symbol_duplicate_centers":
            c = inj.payload["center"]
            near = [p for p in props.symbols.get("door", []) if math.dist(p, c) <= 0.3 * plan.ratio]
            out.append((k, len(near) <= 1))
        elif k == "symbol_in_empty_space":
            pts = inj.payload["centers"]
            near = [p for p in props.symbols.get("door", []) if any(math.dist(p, c) <= 3.0 for c in pts)]
            out.append((k, not near))
    return out


def _same_ring(a: list[Point], b: list[Point]) -> bool:
    """Same vertices in the same cyclic order (either direction)."""
    if len(a) != len(b):
        return False
    n = len(a)
    for ring in (b, b[::-1]):
        for shift in range(n):
            if all(math.dist(a[i], ring[(i + shift) % n]) < 1.0 for i in range(n)):
                return True
    return False


def aggregate(scores: list[PlanScore], catches: list[tuple[str, bool]] | None = None) -> dict[str, Any]:
    gt = sum(s.gt_rooms for s in scores)
    props = sum(s.proposals for s in scores)
    good = sum(s.good for s in scores)
    ious = [v for s in scores for v in s.ious]
    area = [v for s in scores for v in s.area_err]
    perim = [v for s in scores for v in s.perim_err]
    scale = [s.scale_err for s in scores if s.scale_err is not None]
    calib = [c for s in scores for c in s.calib]
    counts = [v for s in scores for v in s.count_acc]
    exact = [v for s in scores for v in s.count_exact]
    confident = sum(s.confident for s in scores)
    out: dict[str, Any] = {
        "plans": len(scores),
        "rooms_gt": gt,
        "room_recall": _r(good / gt if gt else 0.0),
        "room_precision": _r(good / props if props else 0.0),
        "room_iou_mean": _r(sum(ious) / len(ious) if ious else 0.0),
        "area_err_median_pct": _r(100 * median(area) if area else None),
        "area_err_p90_pct": _r(100 * _pct(area, 0.9) if area else None),
        "area_within_2pct": _r(sum(1 for v in area if v <= 0.02) / len(area) if area else 0.0),
        "perimeter_err_median_pct": _r(100 * median(perim) if perim else None),
        "scale_found": _r(len(scale) / len(scores) if scores else 0.0),
        "scale_err_median_pct": _r(100 * median(scale) if scale else None),
        "scale_within_1pct": _r(sum(1 for v in scale if v <= 0.01) / len(scores) if scores else 0.0),
        "count_accuracy": _r(sum(counts) / len(counts) if counts else 0.0),
        "count_exact": _r(sum(exact) / len(exact) if exact else 0.0),
        "confident_precision": _r(sum(s.confident_correct for s in scores) / confident if confident else 0.0),
        "confident_share": _r(confident / props if props else 0.0),
        "ece": _r(_ece(calib)),
        "brier": _r(sum((c - y) ** 2 for c, y in calib) / len(calib) if calib else None),
    }
    if catches is not None:
        out["belt_catch_rate"] = _r(sum(1 for _k, ok in catches if ok) / len(catches) if catches else 1.0)
        missed: dict[str, int] = {}
        for k, ok in catches:
            if not ok:
                missed[k] = missed.get(k, 0) + 1
        out["belt_missed"] = missed
    return out


def _pct(values: list[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def _ece(pairs: list[tuple[float, int]], bins: int = 5) -> float | None:
    if not pairs:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(c, y) for c, y in pairs if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if sel:
            conf = sum(c for c, _ in sel) / len(sel)
            acc = sum(y for _, y in sel) / len(sel)
            total += len(sel) / len(pairs) * abs(conf - acc)
    return total


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 4)
