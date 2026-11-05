"""Generated floor plans with exact ground truth, drawn as real PDFs.

Each plan is a rectangular building cut into rooms on wall centerlines (some
merged into L shapes), drawn the way CAD exports draw it: walls as filled or
outlined bands with door and window openings, door leaves and swings, window
frames, furniture, tile hatching, dimension chains with ticks and values in
mm, cm, m or feet and inches, room names and printed areas, a frame and a
title block with a scale note. Styles vary per plan: lineweights real or
uniform, the scale standard or fit-to-page (with a stale note), and a share of
plans is flattened to a raster image with no vector or text layer at all.

Ground truth per room is the inner-face polygon (what an estimator measures as
net floor area), its area and perimeter in metres; openings are counted at
their centres; the scale is known exactly. Coordinates are PDF points with the
origin top left and y down, the convention of ``app.core.pdf_reader``.
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in metres, y down

PAGES_PT: dict[str, tuple[float, float]] = {
    "A4": (842.0, 595.0),
    "A3": (1191.0, 842.0),
    "A2": (1684.0, 1191.0),
    "A1": (2384.0, 1684.0),
}
PT_PER_M = 72.0 / 0.0254
GRID = 0.05
NAMES = ["Living", "Kitchen", "Bedroom", "Bedroom 2", "Office", "Bath", "WC", "Hall", "Storage", "Dining", "Utility"]


@dataclass
class GtRoom:
    name: str
    inner_pt: list[Point]
    center_pt: list[Point]
    area_m2: float
    perimeter_m: float
    label_pt: Point


@dataclass
class Dimension:
    p1: Point
    p2: Point
    value_m: float
    text: str


@dataclass
class Plan:
    plan_id: str
    pdf: bytes
    page_w: float
    page_h: float
    ratio: float  # PDF points per metre, exact
    rooms: list[GtRoom]
    doors: list[Point]
    windows: list[Point]
    dims: list[Dimension]
    style: dict[str, object]
    distractors: dict[str, list[Point]] = field(default_factory=dict)  # title block, furniture boxes
    empty_points: list[Point] = field(default_factory=list)  # points with nothing drawn near them


# ── Layout in metres ─────────────────────────────────────────────────────────


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _bsp(rng: random.Random, r: Rect, depth: int) -> list[Rect]:
    x0, y0, x1, y1 = r
    w, h = x1 - x0, y1 - y0
    can_x, can_y = w >= 5.0, h >= 5.0
    if depth >= 5 or not (can_x or can_y) or (depth > 0 and w * h < rng.uniform(12.0, 30.0)):
        return [r]
    vertical_cut = can_x and (not can_y or (w >= h if rng.random() < 0.75 else w < h))
    if vertical_cut:
        cut = _snap(x0 + w * rng.uniform(0.33, 0.67))
        cut = min(max(cut, x0 + 2.4), x1 - 2.4)
        return _bsp(rng, (x0, y0, cut, y1), depth + 1) + _bsp(rng, (cut, y0, x1, y1), depth + 1)
    cut = _snap(y0 + h * rng.uniform(0.33, 0.67))
    cut = min(max(cut, y0 + 2.4), y1 - 2.4)
    return _bsp(rng, (x0, y0, x1, cut), depth + 1) + _bsp(rng, (x0, cut, x1, y1), depth + 1)


def _rect_poly(r: Rect) -> list[Point]:
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _l_union(a: Rect, b: Rect) -> list[Point] | None:
    """Outline of two rectangles sharing part of an edge and one aligned side."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    eq = math.isclose
    if eq(ax1, bx0):  # b right of a
        if eq(ay0, by0) and by1 < ay1:
            return [(ax0, ay0), (bx1, by0), (bx1, by1), (ax1, by1), (ax1, ay1), (ax0, ay1)]
        if eq(ay1, by1) and by0 > ay0:
            return [(ax0, ay0), (ax1, ay0), (ax1, by0), (bx1, by0), (bx1, by1), (ax0, ay1)]
        if eq(ay0, by0) and ay1 < by1:
            return [(ax0, ay0), (bx1, by0), (bx1, by1), (bx0, by1), (bx0, ay1), (ax0, ay1)]
        if eq(ay1, by1) and ay0 > by0:
            return [(bx0, by0), (bx1, by0), (bx1, by1), (ax0, ay1), (ax0, ay0), (bx0, ay0)]
    if eq(ay1, by0):  # b below a
        if eq(ax0, bx0) and bx1 < ax1:
            return [(ax0, ay0), (ax1, ay0), (ax1, ay1), (bx1, ay1), (bx1, by1), (ax0, by1)]
        if eq(ax1, bx1) and bx0 > ax0:
            return [(ax0, ay0), (ax1, ay0), (ax1, by1), (bx0, by1), (bx0, ay1), (ax0, ay1)]
        if eq(ax0, bx0) and ax1 < bx1:
            return [(ax0, ay0), (ax1, ay0), (ax1, by0), (bx1, by0), (bx1, by1), (ax0, by1)]
        if eq(ax1, bx1) and ax0 > bx0:
            return [(ax0, ay0), (ax1, ay0), (ax1, by1), (bx0, by1), (bx0, by0), (ax0, by0)]
    return None


def _signed_area(p: list[Point]) -> float:
    return sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p))) / 2


def _inside(x: float, y: float, poly: list[Point]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@dataclass
class _Piece:
    horizontal: bool
    c: float  # the fixed coordinate
    a: float
    b: float
    t: float
    exterior: bool
    openings: list[tuple[float, float, str]] = field(default_factory=list)  # centre, width, kind


def _wall_pieces(polys: list[list[Point]], te: float, ti: float) -> list[_Piece]:
    xs = sorted({p[0] for poly in polys for p in poly})
    ys = sorted({p[1] for poly in polys for p in poly})
    raw: list[_Piece] = []
    for horizontal in (True, False):
        lines: dict[float, list[tuple[float, float]]] = {}
        for poly in polys:
            for i in range(len(poly)):
                p, q = poly[i], poly[(i + 1) % len(poly)]
                if horizontal and math.isclose(p[1], q[1]):
                    lines.setdefault(round(p[1], 6), []).append((min(p[0], q[0]), max(p[0], q[0])))
                elif not horizontal and math.isclose(p[0], q[0]):
                    lines.setdefault(round(p[0], 6), []).append((min(p[1], q[1]), max(p[1], q[1])))
        cuts = xs if horizontal else ys
        for c, ivs in lines.items():
            for lo, hi in ivs:
                inner = [v for v in cuts if lo < v < hi]
                bounds = [lo, *inner, hi]
                for u, v in zip(bounds, bounds[1:], strict=False):
                    mid = (u + v) / 2
                    if horizontal:
                        sides = [_any_inside(mid, c - 0.01, polys), _any_inside(mid, c + 0.01, polys)]
                    else:
                        sides = [_any_inside(c - 0.01, mid, polys), _any_inside(c + 0.01, mid, polys)]
                    exterior = not all(sides)
                    raw.append(_Piece(horizontal, c, u, v, te if exterior else ti, exterior))
    # Unique elementary pieces, then merge runs of the same kind.
    uniq: dict[tuple[bool, float, float, float], _Piece] = {}
    for p in raw:
        uniq[(p.horizontal, round(p.c, 6), round(p.a, 6), round(p.b, 6))] = p
    merged: list[_Piece] = []
    for p in sorted(uniq.values(), key=lambda p: (p.horizontal, p.c, p.a)):
        last = merged[-1] if merged else None
        if (
            last
            and last.horizontal == p.horizontal
            and math.isclose(last.c, p.c)
            and math.isclose(last.b, p.a)
            and last.exterior == p.exterior
        ):
            last.b = p.b
        else:
            merged.append(_Piece(p.horizontal, p.c, p.a, p.b, p.t, p.exterior))
    return merged


def _any_inside(x: float, y: float, polys: list[list[Point]]) -> bool:
    return any(_inside(x, y, poly) for poly in polys)


def _edge_thickness(p: Point, q: Point, pieces: list[_Piece]) -> float:
    horizontal = math.isclose(p[1], q[1])
    c = p[1] if horizontal else p[0]
    lo, hi = sorted((p[0], q[0]) if horizontal else (p[1], q[1]))
    ts = {
        pc.t
        for pc in pieces
        if pc.horizontal == horizontal and math.isclose(pc.c, c) and pc.a < hi - 1e-6 and pc.b > lo + 1e-6
    }
    if len(ts) != 1:
        raise ValueError("mixed wall thickness along one room edge")
    return ts.pop()


def _offset_ring(poly: list[Point], offsets: list[float]) -> list[Point]:
    """Move each edge inward by its offset and intersect consecutive lines."""
    sign = 1.0 if _signed_area(poly) > 0 else -1.0
    lines = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        length = math.dist(a, b)
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        nx, ny = -dy * sign, dx * sign
        lines.append((a[0] + nx * offsets[i], a[1] + ny * offsets[i], dx, dy))
    out = []
    for i in range(n):
        p1x, p1y, d1x, d1y = lines[i - 1]
        p2x, p2y, d2x, d2y = lines[i]
        den = d1x * d2y - d1y * d2x
        t = ((p2x - p1x) * d2y - (p2y - p1y) * d2x) / den
        out.append((p1x + d1x * t, p1y + d1y * t))
    return out


def _perimeter(p: list[Point]) -> float:
    return sum(math.dist(p[i], p[(i + 1) % len(p)]) for i in range(len(p)))


# ── Drawing ──────────────────────────────────────────────────────────────────


class _Pen:
    """A reportlab canvas addressed in metres with a top-left, y-down origin."""

    def __init__(self, c: canvas.Canvas, page_h: float, ratio: float, ox: float, oy: float) -> None:
        self.c, self.page_h, self.ratio, self.ox, self.oy = c, page_h, ratio, ox, oy

    def pt(self, x: float, y: float) -> Point:
        return (self.ox + x * self.ratio, self.oy + y * self.ratio)

    def _rl(self, p: Point) -> tuple[float, float]:
        return p[0], self.page_h - p[1]

    def line_pt(self, p: Point, q: Point, w: float) -> None:
        self.c.setLineWidth(w)
        a, b = self._rl(p), self._rl(q)
        self.c.line(a[0], a[1], b[0], b[1])

    def line(self, x1: float, y1: float, x2: float, y2: float, w: float) -> None:
        self.line_pt(self.pt(x1, y1), self.pt(x2, y2), w)

    def rect(self, x0: float, y0: float, x1: float, y1: float, *, w: float, fill: bool, stroke: bool) -> None:
        p, q = self.pt(min(x0, x1), max(y0, y1)), self.pt(max(x0, x1), min(y0, y1))
        a = self._rl(p)
        self.c.setLineWidth(w)
        self.c.rect(a[0], a[1], q[0] - p[0], p[1] - q[1], fill=1 if fill else 0, stroke=1 if stroke else 0)

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, w: float) -> None:
        # One cubic per quarter: the door swing.
        k = 4 / 3 * math.tan((a1 - a0) / 4)
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        p1 = (p0[0] - k * r * math.sin(a0), p0[1] + k * r * math.cos(a0))
        p2 = (p3[0] + k * r * math.sin(a1), p3[1] - k * r * math.cos(a1))
        pts = [self._rl(self.pt(*p)) for p in (p0, p1, p2, p3)]
        self.c.setLineWidth(w)
        path = self.c.beginPath()
        path.moveTo(*pts[0])
        path.curveTo(*pts[1], *pts[2], *pts[3])
        self.c.drawPath(path, stroke=1, fill=0)

    def text_pt(self, p: Point, s: str, size: float, *, angle: float = 0.0, center: bool = True) -> None:
        x, y = self._rl(p)
        self.c.saveState()
        self.c.setFont("Helvetica", size)
        self.c.translate(x, y)
        if angle:
            self.c.rotate(angle)
        if center:
            self.c.drawCentredString(0, 0, s)
        else:
            self.c.drawString(0, 0, s)
        self.c.restoreState()


def _fmt_length(v: float, unit: str) -> str:
    if unit == "mm":
        return str(round(v * 1000))
    if unit == "cm":
        return str(round(v * 100))
    if unit == "imperial":
        total_in = round(v / 0.0254)
        return f"{total_in // 12}'-{total_in % 12}\""
    return f"{v:.2f}"


def _real_of_text(text: str, unit: str) -> float:
    if unit == "mm":
        return int(text) / 1000
    if unit == "cm":
        return int(text) / 100
    if unit == "imperial":
        ft, rest = text.split("'-")
        return int(ft) * 0.3048 + int(rest.rstrip('"')) * 0.0254
    return float(text)


def generate_plan(seed: int, *, force: dict[str, object] | None = None) -> Plan:
    """Draw one plan from ``seed``; ``force`` pins style keys for targeted cases."""
    for attempt in range(40):
        try:
            return _generate(seed, attempt, force or {})
        except ValueError:
            continue
    raise RuntimeError(f"no valid plan for seed {seed}")


def _generate(seed: int, attempt: int, force: dict[str, object]) -> Plan:  # noqa: C901, PLR0912, PLR0915
    rng = random.Random(seed * 1000 + attempt)
    style: dict[str, object] = {
        "walls": rng.choices(["filled", "outline", "single"], [0.5, 0.42, 0.08])[0],
        "weights": rng.choices(["cad", "uniform"], [0.75, 0.25])[0],
        "dim_unit": rng.choices(["mm", "m", "cm", "imperial"], [0.35, 0.3, 0.2, 0.15])[0],
        "scale_mode": rng.choices(["standard", "fit"], [0.75, 0.25])[0],
        "note": rng.choices(["present", "missing"], [0.7, 0.3])[0],
        "hatch": rng.random() < 0.5,
        "furniture": rng.random() < 0.7,
        "area_labels": rng.random() < 0.6,
        "decimal_comma": rng.random() < 0.3,
        "raster": rng.random() < 0.12,
    }
    style.update(force)
    if style["walls"] == "single" and style["weights"] == "uniform":
        style["weights"] = "cad"
    w_tot, h_tot = _snap(rng.uniform(9.0, 18.0)), _snap(rng.uniform(7.0, 13.0))
    te = rng.choice([0.25, 0.30, 0.365])
    ti = rng.choice([0.115, 0.15, 0.175])
    if style["walls"] == "single":
        te = ti = 0.0
    cells = _bsp(rng, (0.0, 0.0, w_tot, h_tot), 0)
    if len(cells) < 3:
        raise ValueError("too few rooms")
    polys: list[list[Point]] = [_rect_poly(r) for r in cells]
    anchors: list[Point] = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in cells]
    if rng.random() < 0.6:
        order = list(range(len(cells)))
        rng.shuffle(order)
        used: set[int] = set()
        merges = 0
        for i in order:
            for j in order:
                if i == j or i in used or j in used or merges >= 2:
                    continue
                u = _l_union(cells[i], cells[j])
                if u is not None:
                    polys[i] = u
                    polys[j] = []
                    used.update({i, j})
                    merges += 1
        keep = [k for k in range(len(cells)) if polys[k]]
        polys = [polys[k] for k in keep]
        anchors = [anchors[k] for k in keep]

    pieces = _wall_pieces(polys, te, ti)
    rooms_m: list[tuple[list[Point], list[Point]]] = []
    for poly in polys:
        offsets = [_edge_thickness(poly[i], poly[(i + 1) % len(poly)], pieces) / 2 for i in range(len(poly))]
        rooms_m.append((poly, _offset_ring(poly, offsets)))

    # Openings.
    for pc in pieces:
        length = pc.b - pc.a
        margin = 0.3 + max(te, ti)
        if pc.exterior:
            nwin = 0 if length < 2.2 else (1 if length < 4.6 else 2)
            for k in range(nwin):
                wwin = rng.choice([1.0, 1.2, 1.5])
                c = pc.a + length * (k + 1) / (nwin + 1) + rng.uniform(-0.2, 0.2)
                if c - wwin / 2 > pc.a + margin and c + wwin / 2 < pc.b - margin:
                    pc.openings.append((_snap(c), wwin, "window"))
        elif length >= 1.7 and rng.random() < 0.8:
            wd = rng.choice([0.8, 0.9])
            lo, hi = pc.a + margin + wd / 2, pc.b - margin - wd / 2
            if hi > lo:
                pc.openings.append((_snap(rng.uniform(lo, hi)), wd, "door"))
    ext = [pc for pc in pieces if pc.exterior and pc.b - pc.a > 2.6 and not pc.openings]
    if ext:
        pc = rng.choice(ext)
        pc.openings.append((_snap((pc.a + pc.b) / 2), 1.0, "door"))

    # Scale and page.
    dim_unit = str(style["dim_unit"])
    ext_w, ext_h = w_tot + te, h_tot + te
    span_w, span_h = ext_w + 4.0, ext_h + 4.0
    if dim_unit == "imperial":
        standard = [48.0, 96.0]
    else:
        standard = [50.0, 100.0, 200.0]
    page_name = rng.choice(["A3", "A3", "A2", "A1", "A4"])
    pw, ph = PAGES_PT[page_name]
    usable_w, usable_h = pw - 60, ph - 130
    note_n: float | None = None
    if style["scale_mode"] == "standard":
        fitting = [n for n in standard if span_w * PT_PER_M / n <= usable_w and span_h * PT_PER_M / n <= usable_h]
        if not fitting:
            raise ValueError("does not fit")
        n = fitting[0] if rng.random() < 0.7 else fitting[-1]
        ratio = PT_PER_M / n
        note_n = n
    else:
        ratio = min(usable_w / span_w, usable_h / span_h) * rng.uniform(0.85, 0.97)
        nearest = min(standard, key=lambda n: abs(PT_PER_M / n - ratio))
        note_n = nearest if rng.random() < 0.5 else None  # a stale note from the original sheet
    if span_w * ratio > usable_w or span_h * ratio > usable_h or ratio * 0.9 < 4.0:
        raise ValueError("does not fit")
    ox = 30 + (usable_w - span_w * ratio) * rng.uniform(0.1, 0.9) + 2.8 * ratio + te / 2 * ratio
    oy = 30 + (usable_h - span_h * ratio) * rng.uniform(0.1, 0.9) + 2.8 * ratio + te / 2 * ratio

    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(pw, ph))
    cv.setStrokeColorRGB(0, 0, 0)
    pen = _Pen(cv, ph, ratio, ox, oy)
    cad = style["weights"] == "cad"
    lw_wall = 0.7 if cad else 0.3
    lw_thin = 0.25 if cad else 0.3
    lw_furn = 0.18 if cad else 0.3
    lw_dim = 0.18 if cad else 0.3
    lw_hatch = 0.1 if cad else 0.3
    distractors: dict[str, list[Point]] = {}

    def perpendicular_t(x: float, y: float, horizontal: bool) -> float:
        ts = [
            p.t
            for p in pieces
            if p.horizontal != horizontal
            and math.isclose(p.c, x if horizontal else y)
            and p.a - 1e-6 <= (y if horizontal else x) <= p.b + 1e-6
        ]
        return max(ts) if ts else 0.0

    doors_pt: list[Point] = []
    windows_pt: list[Point] = []
    for pc in pieces:
        ea = perpendicular_t(pc.a if pc.horizontal else pc.c, pc.c if pc.horizontal else pc.a, pc.horizontal) / 2
        eb = perpendicular_t(pc.b if pc.horizontal else pc.c, pc.c if pc.horizontal else pc.b, pc.horizontal) / 2
        spans = [(pc.a - ea, pc.b + eb)]
        for c, wo, _kind in pc.openings:
            nxt = []
            for lo, hi in spans:
                if lo < c - wo / 2 < hi:
                    nxt.append((lo, c - wo / 2))
                    nxt.append((c + wo / 2, hi))
                else:
                    nxt.append((lo, hi))
            spans = nxt
        for lo, hi in spans:
            if hi - lo <= 1e-6:
                continue
            if style["walls"] == "single":
                if pc.horizontal:
                    pen.line(lo, pc.c, hi, pc.c, lw_wall)
                else:
                    pen.line(pc.c, lo, pc.c, hi, lw_wall)
                continue
            h2 = pc.t / 2
            if pc.horizontal:
                box = (lo, pc.c - h2, hi, pc.c + h2)
            else:
                box = (pc.c - h2, lo, pc.c + h2, hi)
            if style["walls"] == "filled":
                cv.setFillColorRGB(0.25, 0.25, 0.25)
                pen.rect(*box, w=0, fill=True, stroke=False)
            else:
                pen.rect(*box, w=lw_wall, fill=False, stroke=True)
        for c, wo, kind in pc.openings:
            centre = (c, pc.c) if pc.horizontal else (pc.c, c)
            if kind == "window":
                windows_pt.append(pen.pt(*centre))
                h2 = max(pc.t / 2, 0.05)
                if pc.horizontal:
                    pen.rect(c - wo / 2, pc.c - h2, c + wo / 2, pc.c + h2, w=lw_thin, fill=False, stroke=True)
                    pen.line(c - wo / 2, pc.c, c + wo / 2, pc.c, lw_thin)
                else:
                    pen.rect(pc.c - h2, c - wo / 2, pc.c + h2, c + wo / 2, w=lw_thin, fill=False, stroke=True)
                    pen.line(pc.c, c - wo / 2, pc.c, c + wo / 2, lw_thin)
            else:
                doors_pt.append(pen.pt(*centre))
                side = rng.choice([-1.0, 1.0])
                if pc.horizontal:
                    hx, hy = c - wo / 2, pc.c + side * pc.t / 2
                    pen.line(hx, hy, hx, hy + side * wo, lw_thin)
                    a0, a1 = (0.0, math.pi / 2) if side > 0 else (-math.pi / 2, 0.0)
                    pen.arc(hx, hy, wo, a0, a1, lw_thin)
                else:
                    hx, hy = pc.c + side * pc.t / 2, c - wo / 2
                    pen.line(hx, hy, hx + side * wo, hy, lw_thin)
                    a0, a1 = (0.0, math.pi / 2) if side > 0 else (math.pi / 2, math.pi)
                    pen.arc(hx, hy, wo, a0, a1, lw_thin)

    # Room content: furniture, hatch, labels.
    names = list(NAMES)
    rng.shuffle(names)
    order = sorted(range(len(rooms_m)), key=lambda k: -abs(_signed_area(rooms_m[k][1])))
    room_names = {k: (["Living", "Kitchen"] + names)[i % (len(names) + 2)] for i, k in enumerate(order)}
    gt_rooms: list[GtRoom] = []
    furniture_boxes: list[Point] = []
    sep = "," if style["decimal_comma"] else "."
    for k, (center, inner) in enumerate(rooms_m):
        name = room_names[k]
        area = abs(_signed_area(inner))
        ax, ay = anchors[k]
        xs = [p[0] for p in inner]
        ys = [p[1] for p in inner]
        is_rect = len(inner) == 4
        if style["furniture"] and is_rect and area > 9 and rng.random() < 0.7:
            fw, fh = rng.choice([(1.6, 2.0), (0.9, 1.6), (1.2, 0.8)])
            fx = min(max(ax + rng.uniform(-0.8, 0.8), min(xs) + 0.4 + fw / 2), max(xs) - 0.4 - fw / 2)
            fy = min(max(ay + rng.uniform(0.6, 1.2), min(ys) + 0.4 + fh / 2), max(ys) - 0.4 - fh / 2)
            if min(xs) + 0.3 < fx - fw / 2 and fx + fw / 2 < max(xs) - 0.3:
                pen.rect(fx - fw / 2, fy - fh / 2, fx + fw / 2, fy + fh / 2, w=lw_furn, fill=False, stroke=True)
                furniture_boxes.append(pen.pt(fx, fy))
                distractors.setdefault("furniture", []).extend(
                    [pen.pt(fx - fw / 2, fy - fh / 2), pen.pt(fx + fw / 2, fy + fh / 2)]
                )
        if name == "Kitchen" and is_rect and style["furniture"]:
            x0, x1, y0 = min(xs), max(xs), min(ys)
            pen.rect(x0 + 0.2, y0, x1 - 0.2, y0 + 0.6, w=lw_furn, fill=False, stroke=True)
        if name in ("Bath", "WC") and is_rect and style["hatch"]:
            step = 0.3
            gx = min(xs) + step
            while gx < max(xs) - 1e-6:
                pen.line(gx, min(ys), gx, max(ys), lw_hatch)
                gx += step
            gy = min(ys) + step
            while gy < max(ys) - 1e-6:
                pen.line(min(xs), gy, max(xs), gy, lw_hatch)
                gy += step
        label_pt = pen.pt(ax, ay)
        pen.text_pt((label_pt[0], label_pt[1] - 2), name, 8.0)
        if style["area_labels"]:
            shown = area * (rng.uniform(1.1, 1.25) if rng.random() < 0.05 else 1.0)
            if dim_unit == "imperial":
                txt = f"{shown / 0.09290304:.0f} SF"
            else:
                # The base-14 fonts carry no ToUnicode map, so a drawn "²" reads
                # back as U+FFFD; CAD exports write "m2" just as often.
                txt = f"{shown:.2f}".replace(".", sep) + " m2"
            pen.text_pt((label_pt[0], label_pt[1] + 8), txt, 7.0)
        gt_rooms.append(
            GtRoom(
                name=name,
                inner_pt=[pen.pt(*p) for p in inner],
                center_pt=[pen.pt(*p) for p in center],
                area_m2=area,
                perimeter_m=_perimeter(inner),
                label_pt=label_pt,
            )
        )

    # Dimension chains (top and left), measured to outer faces and centrelines.
    dims: list[Dimension] = []
    xs_top = sorted(
        {0.0 - te / 2, w_tot + te / 2}
        | {pc.c for pc in pieces if not pc.horizontal and not pc.exterior and math.isclose(pc.a, 0.0)}
    )
    ys_left = sorted(
        {0.0 - te / 2, h_tot + te / 2}
        | {pc.c for pc in pieces if pc.horizontal and not pc.exterior and math.isclose(pc.a, 0.0)}
    )
    th = 6.5

    def dim_chain(positions: list[float], horizontal: bool, offset: float) -> None:
        for lo, hi in [*zip(positions, positions[1:], strict=False), (positions[0], positions[-1])]:
            if hi - lo < 0.5:
                continue
            off = offset - (0.7 if (lo, hi) == (positions[0], positions[-1]) else 0.0)
            text = _fmt_length(hi - lo, dim_unit)
            if horizontal:
                p1, p2 = pen.pt(lo, off), pen.pt(hi, off)
                pen.line_pt(p1, p2, lw_dim)
                for x in (lo, hi):
                    pen.line(x, -te / 2 - 0.15, x, off - 0.2, lw_dim)
                    q = pen.pt(x, off)
                    pen.line_pt((q[0] - 2.5, q[1] + 2.5), (q[0] + 2.5, q[1] - 2.5), lw_dim)
                pen.text_pt(((p1[0] + p2[0]) / 2, p1[1] - 2.0), text, th)
            else:
                p1, p2 = pen.pt(off, lo), pen.pt(off, hi)
                pen.line_pt(p1, p2, lw_dim)
                for y in (lo, hi):
                    pen.line(-te / 2 - 0.15, y, off - 0.2, y, lw_dim)
                    q = pen.pt(off, y)
                    pen.line_pt((q[0] - 2.5, q[1] + 2.5), (q[0] + 2.5, q[1] - 2.5), lw_dim)
                pen.text_pt((p1[0] - 2.0, (p1[1] + p2[1]) / 2), text, th, angle=90)
            dims.append(Dimension(p1=p1, p2=p2, value_m=_real_of_text(text, dim_unit), text=text))

    dim_chain(xs_top, True, -te / 2 - 1.2)
    dim_chain(ys_left, False, -te / 2 - 1.2)

    # Frame and title block.
    cv.setLineWidth(1.0 if cad else 0.3)
    cv.rect(20, 20, pw - 40, ph - 40, fill=0, stroke=1)
    tb = (pw - 20 - 200, ph - 20 - 70, pw - 20, ph - 20)  # x0, y0, x1, y1 top-left space
    cv.setLineWidth(0.5 if cad else 0.3)
    cv.rect(tb[0], ph - tb[3], tb[2] - tb[0], tb[3] - tb[1], fill=0, stroke=1)
    cv.line(tb[0], ph - tb[1] - 23, tb[2], ph - tb[1] - 23)
    cv.line(tb[0], ph - tb[1] - 46, tb[2], ph - tb[1] - 46)
    distractors["title_block"] = [(tb[0], tb[1]), (tb[2], tb[3])]
    pen.text_pt((tb[0] + 6, tb[1] + 15), "PROJECT Residence", 7.0, center=False)
    pen.text_pt((tb[0] + 6, tb[1] + 38), "DRAWING Ground floor plan", 7.0, center=False)
    if style["note"] == "present" and note_n is not None:
        if dim_unit == "imperial":
            note = 'SCALE 1/4" = 1\'-0"' if note_n == 48 else 'SCALE 1/8" = 1\'-0"'
        else:
            note = f"SCALE 1:{int(note_n)}"
        pen.text_pt((tb[0] + 6, tb[1] + 61), note, 7.0, center=False)
    cv.showPage()
    cv.save()
    pdf = buf.getvalue()

    # Points with nothing drawn near them: page margin inside the frame.
    empty = [(pw * 0.5, 26.0), (26.0, ph * 0.5)]
    plan = Plan(
        plan_id=f"p{seed}",
        pdf=pdf,
        page_w=pw,
        page_h=ph,
        ratio=ratio,
        rooms=gt_rooms,
        doors=doors_pt,
        windows=windows_pt,
        dims=dims,
        style=style,
        distractors=distractors,
        empty_points=empty,
    )
    if style["raster"]:
        plan.pdf = _flatten_to_raster(pdf, pw, ph)
    return plan


def _flatten_to_raster(pdf: bytes, pw: float, ph: float) -> bytes:
    """Re-issue the page as a 150 dpi image: a scan with no vector or text layer."""
    from app.core import pdf_reader

    doc = pdf_reader.open_pdf(pdf)
    try:
        png = doc[0].render(dpi=150).png()
    finally:
        doc.close()
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(pw, ph))
    cv.drawImage(ImageReader(io.BytesIO(png)), 0, 0, width=pw, height=ph)
    cv.showPage()
    cv.save()
    return buf.getvalue()


#: Seeds the pipeline is tuned on, and the held-out seeds it is never tuned on.
TRAIN_SEEDS = list(range(0, 24))
HOLDOUT_SEEDS = list(range(500, 524))
#: The fast CI slice: four plans from each split, whose vector-sheet metrics sit within 1% of both splits together.
FAST_SEEDS = [9, 12, 17, 22, 502, 505, 512, 521]
