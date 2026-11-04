"""Stand-in for the vision model: recorded-style responses with known errors.

``realistic`` reproduces how vision models actually miss on floor plans:
vertex jitter of a fraction of a percent to about one percent of the image,
traces on the wall centreline instead of the inner face, extra vertices along
straight walls, L-shaped rooms returned as their bounding rectangle, adjacent
rooms merged, small rooms missed, an occasional duplicate or invented room,
symbol misses, duplicates and inventions, class names spelled two ways, a scale
reference whose endpoints are as jittery as everything else, now and then a
unit read wrong, and from time to time the whole answer in pixels. Self-scored
confidence is high and barely tracks quality, as it does in practice.

``adversarial`` adds one labelled attack per kind on top of a realistic answer,
so the scorer can check the deterministic belt catches each of them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from app.modules.takeoff.plan_read import DEFAULT_TARGET_LONG_EDGE_PX, clamp_dpi

from .plans import Plan, Point

ADVERSARIAL_KINDS = (
    "scale_unit_x1000",
    "scale_value_not_on_sheet",
    "scale_wrong_dimension",
    "room_self_intersecting",
    "room_out_of_page",
    "room_pixel_coords_mixed",
    "room_duplicate_exact",
    "room_duplicate_shifted",
    "room_hallucinated_margin",
    "room_hallucinated_title_block",
    "room_degenerate",
    "room_non_numeric",
    "symbol_duplicate_centers",
    "symbol_in_empty_space",
)


@dataclass
class Injection:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class MockResponse:
    plan_id: str
    profile: str
    body: dict[str, Any]
    injections: list[Injection]
    image_px: tuple[int, int]


def image_size_px(plan: Plan) -> tuple[int, int]:
    dpi = clamp_dpi(max(plan.page_w, plan.page_h), DEFAULT_TARGET_LONG_EDGE_PX)
    return round(plan.page_w * dpi / 72.0), round(plan.page_h * dpi / 72.0)


def _norm(plan: Plan, p: Point) -> list[float]:
    return [p[0] / plan.page_w, p[1] / plan.page_h]


def _jit(rng: random.Random, v: list[float], sigma: float) -> list[float]:
    return [v[0] + rng.gauss(0, sigma), v[1] + rng.gauss(0, sigma)]


def _bbox_poly(pts: list[Point]) -> list[Point]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]


def _class_name(rng: random.Random, base: str) -> str:
    return rng.choice([base, base.capitalize(), base + "s"])


def realistic_response(plan: Plan, seed: int) -> MockResponse:  # noqa: C901, PLR0912, PLR0915
    rng = random.Random(seed * 7919 + 17)
    sigma = rng.uniform(0.002, 0.008)
    rooms_out: list[dict[str, Any]] = []
    gt = list(plan.rooms)
    merged: set[int] = set()
    if len(gt) > 3 and rng.random() < 0.25:
        i = rng.randrange(len(gt))
        best = None
        for j in range(len(gt)):
            if j == i:
                continue
            d = min(math.dist(a, b) for a in gt[i].center_pt for b in gt[j].center_pt)
            if best is None or d < best[0]:
                best = (d, j)
        if best is not None:
            merged = {i, best[1]}
            rooms_out.append(
                {
                    "name": gt[i].name,
                    "polygon": [
                        _jit(rng, _norm(plan, p), sigma) for p in _bbox_poly(gt[i].inner_pt + gt[best[1]].inner_pt)
                    ],
                    "confidence": round(min(0.95, max(0.4, rng.gauss(0.72, 0.08))), 2),
                }
            )
    for k, room in enumerate(gt):
        if k in merged:
            continue
        miss_p = 0.05 + (0.12 if room.area_m2 < 4.0 else 0.0)
        if rng.random() < miss_p:
            continue
        base = room.center_pt if rng.random() < 0.3 else room.inner_pt
        if len(base) > 4 and rng.random() < 0.3:
            base = _bbox_poly(base)
        pts = [_jit(rng, _norm(plan, p), sigma) for p in base]
        if rng.random() < 0.3:
            i = rng.randrange(len(pts))
            a, b = pts[i], pts[(i + 1) % len(pts)]
            pts.insert(i + 1, _jit(rng, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], sigma))
        shift = rng.randrange(len(pts))
        pts = pts[shift:] + pts[:shift]
        if rng.random() < 0.5:
            pts.reverse()
        if rng.random() < 0.3:
            pts.append(list(pts[0]))
        rooms_out.append(
            {
                "name": room.name if rng.random() < 0.9 else "",
                "polygon": [[round(v, 4) for v in p] for p in pts],
                "confidence": round(min(0.97, max(0.4, rng.gauss(0.8, 0.08))), 2),
            }
        )
    if rooms_out and rng.random() < 0.1:
        src = rng.choice(rooms_out)
        rooms_out.append({**src, "polygon": [_jit(rng, p, sigma) for p in src["polygon"]]})
    injections: list[Injection] = []
    if rng.random() < 0.15:
        fb = plan.distractors.get("furniture")
        if fb and rng.random() < 0.6:
            a, b = fb[0], fb[1]
            poly = _bbox_poly([a, b])
            injections.append(Injection("room_hallucinated_furniture", {"polygon": poly}))
        else:
            a, b = plan.distractors["title_block"]
            poly = _bbox_poly([a, b])
            injections.append(Injection("room_hallucinated_title_block", {"polygon": poly}))
        rooms_out.append(
            {
                "name": "Storage",
                "polygon": [_jit(rng, _norm(plan, p), sigma) for p in poly],
                "confidence": round(rng.uniform(0.6, 0.85), 2),
            }
        )

    symbols: list[dict[str, Any]] = []
    for base, gts, p_hit in (("door", plan.doors, 0.9), ("window", plan.windows, 0.82)):
        centers = [_jit(rng, _norm(plan, c), sigma * 0.6) for c in gts if rng.random() < p_hit]
        for c in list(centers):
            if rng.random() < 0.06:
                centers.append(_jit(rng, c, sigma * 0.3))
        for _ in range(rng.choice([0, 0, 0, 1, 2])):
            centers.append([rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)])
        if not centers:
            continue
        if rng.random() < 0.15 and len(centers) > 2:
            cut = len(centers) // 2
            symbols.append({"element_class": base, "centers": centers[:cut], "confidence": 0.7})
            symbols.append({"element_class": base.capitalize() + "s", "centers": centers[cut:], "confidence": 0.65})
        else:
            symbols.append(
                {
                    "element_class": _class_name(rng, base),
                    "centers": centers,
                    "confidence": round(min(0.95, max(0.4, rng.gauss(0.75, 0.1))), 2),
                }
            )

    scale: dict[str, Any] | None = None
    if plan.dims and rng.random() < 0.92:
        dims = sorted(plan.dims, key=lambda d: -math.dist(d.p1, d.p2))
        d = dims[0] if rng.random() < 0.6 else rng.choice(dims)
        value, unit = d.value_m, "m"
        roll = rng.random()
        if roll < 0.06:
            value, unit = d.value_m * 1000, "m"  # millimetres read as metres
        elif roll < 0.1:
            value = rng.choice(plan.dims).value_m  # the neighbour's value
        scale = {
            "ref_pixels": [_jit(rng, _norm(plan, d.p1), sigma), _jit(rng, _norm(plan, d.p2), sigma)],
            "ref_real_value": round(value, 3),
            "ref_unit": unit,
            "source": "dimension_string",
            "confidence": round(min(0.95, max(0.5, rng.gauss(0.82, 0.06))), 2),
        }
    elif plan.doors:
        c = plan.doors[0]
        half = 0.45 * plan.ratio
        scale = {
            "ref_pixels": [
                _jit(rng, _norm(plan, (c[0] - half, c[1])), sigma),
                _jit(rng, _norm(plan, (c[0] + half, c[1])), sigma),
            ],
            "ref_real_value": 0.9,
            "ref_unit": "m",
            "source": "inferred",
            "confidence": 0.6,
        }

    body: dict[str, Any] = {"scale": scale, "rooms": rooms_out, "symbols": symbols}
    img = image_size_px(plan)
    if rng.random() < 0.05:
        body = _to_pixels(body, img)
    return MockResponse(plan.plan_id, "realistic", body, injections, img)


def _to_pixels(body: dict[str, Any], img: tuple[int, int]) -> dict[str, Any]:
    def px(p: list[float]) -> list[float]:
        return [round(p[0] * img[0], 1), round(p[1] * img[1], 1)]

    out = dict(body)
    if body.get("scale"):
        out["scale"] = {**body["scale"], "ref_pixels": [px(p) for p in body["scale"]["ref_pixels"]]}
    out["rooms"] = [{**r, "polygon": [px(p) for p in r["polygon"]]} for r in body["rooms"]]
    out["symbols"] = [{**s, "centers": [px(p) for p in s["centers"]]} for s in body["symbols"]]
    return out


def adversarial_response(plan: Plan, seed: int) -> MockResponse:  # noqa: C901
    """A realistic answer in normalized space plus one attack of every kind."""
    base = realistic_response(plan, seed)
    rng = random.Random(seed * 104729 + 3)
    body = base.body
    if body["rooms"] and max(abs(v) for r in body["rooms"] for p in r["polygon"] for v in p) > 1.5:
        base = realistic_response(plan, seed + 10_000)
        body = base.body
    body = {**body, "rooms": list(body["rooms"]), "symbols": list(body["symbols"])}
    inj: list[Injection] = list(base.injections)
    w, h = plan.page_w, plan.page_h
    gt0 = max(plan.rooms, key=lambda r: r.area_m2)
    g0 = [_norm(plan, p) for p in gt0.inner_pt]

    kinds = list(ADVERSARIAL_KINDS)
    rng.shuffle(kinds)
    scale_kind = next(k for k in kinds if k.startswith("scale_"))
    if plan.dims:
        d = max(plan.dims, key=lambda d: math.dist(d.p1, d.p2))
        if scale_kind == "scale_unit_x1000":
            value = d.value_m * 1000
            ends = [_norm(plan, d.p1), _norm(plan, d.p2)]
        elif scale_kind == "scale_value_not_on_sheet":
            value = round(d.value_m * rng.choice([0.62, 1.37, 1.9]), 2)
            ends = [_norm(plan, d.p1), _norm(plan, d.p2)]
        else:
            other = min(plan.dims, key=lambda o: math.dist(o.p1, o.p2))
            value = other.value_m
            ends = [_norm(plan, d.p1), _norm(plan, d.p2)]
        body["scale"] = {
            "ref_pixels": ends,
            "ref_real_value": value,
            "ref_unit": "m",
            "source": "dimension_string",
            "confidence": 0.9,
        }
        inj.append(Injection(scale_kind, {"true_ratio": plan.ratio}))

    def add_room(kind: str, polygon: Any, payload: dict[str, Any] | None = None) -> None:
        body["rooms"].append({"name": "Room", "polygon": polygon, "confidence": 0.93})
        inj.append(Injection(kind, payload or {}))

    bow = [g0[0], g0[2], g0[1], g0[3]] if len(g0) == 4 else [g0[0], g0[3], g0[1], g0[4]]
    add_room("room_self_intersecting", bow, {"polygon_n": bow})
    add_room("room_out_of_page", [[0.2, 0.2], [1.3, 0.2], [1.3, 0.5], [0.2, 0.5]])
    img = base.image_px
    add_room("room_pixel_coords_mixed", [[p[0] * img[0], p[1] * img[1]] for p in g0])
    add_room("room_duplicate_exact", [list(p) for p in g0], {"gt_name": gt0.name, "polygon_n": g0})
    add_room(
        "room_duplicate_shifted",
        [[p[0] + 0.004, p[1] - 0.003] for p in g0],
        {"gt_name": gt0.name, "polygon_n": g0},
    )
    m0 = [(30.0, h * 0.35), (30.0 + 0.06 * w, h * 0.35), (30.0 + 0.06 * w, h * 0.45), (30.0, h * 0.45)]
    add_room("room_hallucinated_margin", [_norm(plan, p) for p in m0], {"polygon_n": [_norm(plan, p) for p in m0]})
    a, b = plan.distractors["title_block"]
    tb = [_norm(plan, p) for p in _bbox_poly([a, b])]
    add_room("room_hallucinated_title_block", tb, {"polygon_n": tb})
    add_room("room_degenerate", [[0.3, 0.3], [0.4, 0.4], [0.5, 0.5]])
    add_room("room_non_numeric", [["a", "b"], [0.4, float("nan")], [0.5, 0.6]])

    door = plan.doors[0] if plan.doors else plan.rooms[0].label_pt
    dn = _norm(plan, door)
    body["symbols"].append({"element_class": "door", "centers": [dn, [dn[0] + 0.001, dn[1]], dn], "confidence": 0.9})
    inj.append(Injection("symbol_duplicate_centers", {"center": door}))
    ep = plan.empty_points
    body["symbols"].append(
        {"element_class": "door", "centers": [_norm(plan, p) for p in ep], "confidence": 0.9},
    )
    inj.append(Injection("symbol_in_empty_space", {"centers": ep}))
    return MockResponse(plan.plan_id, "adversarial", body, inj, base.image_px)
