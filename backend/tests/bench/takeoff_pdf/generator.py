# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Synthetic floor-plan PDFs with exact ground truth for the takeoff benchmark.

Every page is drawn with reportlab (a base dependency) from a seeded random plan,
so the corpus needs no stored binaries: the same seed always yields the same bytes
and the same ground truth. A plan is a guillotine tiling of a rectangular or
L-shaped building into rooms (some merged into L-shaped rooms, some with a
chamfered corner), with exterior and interior walls of different thickness, doors
with swing arcs, windows, sockets, lights, columns, furniture and chairs, plus the
noise a real sheet carries: dimension chains, grid axes with bubbles, hatching,
room labels (text or stroked "SHX" text), a frame, a title block with a scale note
in one of many languages and notations, notes with ratio-like distractors, detail
callouts, legends and scale bars. Pages may be rotated, content may be rotated,
and a scanned variant rasterises the page and degrades it (skew, blur, noise,
JPEG) for the raster detector.

Ground truth (all coordinates in PDF points, origin top-left of the UNROTATED page,
the space ``PdfPage.drawings()`` and the takeoff canvas use):

* ``rooms``: clear (inner face) polygons with ``area_m2``,
* ``walls``: centreline runs (through openings) with ``thickness_m``,
* ``symbols``: per block class, the bbox centre of every placed instance (plan
  area only; legend samples are excluded) with a matching radius,
* ``scale``: the main drawing scale ratio ``N`` of ``1:N`` (``None`` if the sheet
  carries none).
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MM = 72.0 / 25.4
_FONT_DIR = Path(__file__).resolve().parents[3] / "app" / "core" / "fonts"
FONT = "BenchSans"
_FONTS_READY = False

HOLDOUT_OFFSET = 1_000_000
# Pages nobody looked at while fixing anything. ``holdout`` lost that standing when a fix
# was made after seeing it; these stay unseen until a change is finished.
FRESH_OFFSET = 2_000_000
SPLITS = ("train", "holdout", "fresh")


def split_seeds(split: str, n: int) -> list[int]:
    """Seeds of a split. Splits never overlap."""
    base = {"train": 0, "holdout": HOLDOUT_OFFSET, "fresh": FRESH_OFFSET}[split]
    return [base + i for i in range(n)]


# ── national conventions ──────────────────────────────────────────────────────

LANGS: dict[str, dict[str, Any]] = {
    "en": {
        "rooms": ["Living", "Bedroom", "Kitchen", "Bath", "Hall", "Office", "Store", "WC", "Dining", "Utility"],
        "title": "Ground floor plan",
        "scale": ["SCALE 1:{r}", "Scale: 1:{r}", "SCALE  1 : {r}", "Scale 1:{r} @ A3"],
        "label": "SCALE",
    },
    "de": {
        "rooms": ["Wohnen", "Schlafen", "Küche", "Bad", "Flur", "Büro", "Abstellraum", "WC", "Essen", "Technik"],
        "title": "Grundriss Erdgeschoss",
        "scale": ["M 1:{r}", "Maßstab 1:{r}", "Maßstab: 1:{r}", "M. 1:{r}", "M 1 : {r}"],
        "label": "Maßstab",
    },
    "fr": {
        "rooms": ["Séjour", "Chambre", "Cuisine", "Salle de bain", "Entrée", "Bureau", "Rangement", "WC", "Repas"],
        "title": "Plan du rez-de-chaussée",
        "scale": ["Échelle 1/{r}", "ECHELLE : 1/{r}", "Éch. 1:{r}", "Echelle 1:{r}"],
        "label": "Échelle",
    },
    "es": {
        "rooms": ["Salón", "Dormitorio", "Cocina", "Baño", "Pasillo", "Oficina", "Almacén", "Aseo", "Comedor"],
        "title": "Planta baja",
        "scale": ["ESCALA 1:{r}", "E 1:{r}", "Esc. 1/{r}", "Escala: 1/{r}"],
        "label": "Escala",
    },
    "it": {
        "rooms": ["Soggiorno", "Camera", "Cucina", "Bagno", "Corridoio", "Ufficio", "Ripostiglio", "Pranzo"],
        "title": "Pianta piano terra",
        "scale": ["Scala 1:{r}", "SCALA 1:{r}", "Scala 1/{r}"],
        "label": "Scala",
    },
    "nl": {
        "rooms": ["Woonkamer", "Slaapkamer", "Keuken", "Badkamer", "Hal", "Kantoor", "Berging", "Toilet"],
        "title": "Plattegrond begane grond",
        "scale": ["Schaal 1:{r}", "SCHAAL 1:{r}"],
        "label": "Schaal",
    },
    "pl": {
        "rooms": ["Salon", "Sypialnia", "Kuchnia", "Łazienka", "Korytarz", "Biuro", "Schowek", "Jadalnia"],
        "title": "Rzut parteru",
        "scale": ["Skala 1:{r}", "SKALA 1:{r}", "Skala 1/{r}"],
        "label": "Skala",
    },
    "ru": {
        "rooms": ["Гостиная", "Спальня", "Кухня", "Ванная", "Коридор", "Кабинет", "Кладовая", "Санузел"],
        "title": "План первого этажа",
        "scale": ["Масштаб 1:{r}", "М 1:{r}", "М1:{r}", "Масштаб: 1:{r}"],
        "label": "Масштаб",
    },
    "cs": {
        "rooms": ["Obývací pokoj", "Ložnice", "Kuchyně", "Koupelna", "Chodba", "Kancelář", "Sklad", "Jídelna"],
        "title": "Půdorys přízemí",
        "scale": ["Měřítko 1:{r}", "M 1:{r}"],
        "label": "Měřítko",
    },
    "sv": {
        "rooms": ["Vardagsrum", "Sovrum", "Kök", "Badrum", "Hall", "Kontor", "Förråd", "Matsal"],
        "title": "Planritning",
        "scale": ["Skala 1:{r}", "SKALA 1:{r}"],
        "label": "Skala",
    },
    "tr": {
        "rooms": ["Salon", "Yatak odası", "Mutfak", "Banyo", "Koridor", "Ofis", "Depo", "Yemek odası"],
        "title": "Zemin kat planı",
        "scale": ["Ölçek 1/{r}", "ÖLÇEK 1:{r}"],
        "label": "Ölçek",
    },
    "fi": {
        "rooms": ["Olohuone", "Makuuhuone", "Keittiö", "Kylpyhuone", "Eteinen", "Työhuone", "Varasto"],
        "title": "Pohjapiirustus",
        "scale": ["Mittakaava 1:{r}", "MK 1:{r}"],
        "label": "Mittakaava",
    },
    "pt": {
        "rooms": ["Sala", "Quarto", "Cozinha", "Banheiro", "Corredor", "Escritório", "Depósito", "Lavabo"],
        "title": "Planta térreo",
        "scale": ["Escala 1:{r}", "ESC. 1:{r}", "Escala 1/{r}"],
        "label": "Escala",
    },
}
IMPERIAL_LANG = {
    "rooms": ["LIVING", "BEDROOM", "KITCHEN", "BATH", "HALL", "OFFICE", "CLOSET", "LAUNDRY", "DINING", "DEN"],
    "title": "FIRST FLOOR PLAN",
    "scale": ["SCALE: {i}", "Scale {i}", "{i}", "SCALE {i}"],
    "label": "SCALE",
}
# (ratio, paper inches per foot as written)
IMPERIAL_SCALES = [(48, "1/4"), (96, "1/8"), (64, "3/16"), (32, "3/8")]
METRIC_RATIOS = [50, 100, 100, 100, 200]
METRIC_PAGES = [("A3", 420 * MM, 297 * MM), ("A2", 594 * MM, 420 * MM), ("A1", 841 * MM, 594 * MM)]
IMPERIAL_PAGES = [("ANSI B", 17 * 72.0, 11 * 72.0), ("ARCH C", 24 * 72.0, 18 * 72.0), ("ARCH D", 36 * 72.0, 24 * 72.0)]
SCAN_PAGES = {"A3", "A2", "ANSI B", "ARCH C"}

# Ratio-like strings a sheet carries that are NOT the drawing scale.
DISTRACTORS = [
    "Mortar mix 1:4",
    "Ramp slope max. 1:12",
    "Plotted 14:30",
    "Screen 16:9",
    "Concrete C25/30, mix 1:2:3",
    "Fall to drain 1:80",
]
DETAIL_TITLES = ["DETAIL A 1:{r}", "SECTION B-B 1:{r}", "Detail 1 - 1:{r}", "Schnitt A-A M 1:{r}"]


def _imperial_text(rng: random.Random, inch: str) -> str:
    form = rng.choice(['{i}" = 1\'-0"', '{i}"=1\'-0"', "{i}″ = 1′-0″", '{i}" = 1\'0"'])
    return form.format(i=inch)


# ── small geometry helpers (metres, y up) ─────────────────────────────────────

Pt = tuple[float, float]
Rect = tuple[float, float, float, float]


def _q(v: float) -> float:
    return round(v, 4)


def _snap(v: float, step: float = 0.05) -> float:
    return _q(round(v / step) * step)


def shoelace(pts: list[Pt]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _line_isect(a: Pt, da: Pt, b: Pt, db: Pt) -> Pt | None:
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-12:
        return None
    t = ((b[0] - a[0]) * db[1] - (b[1] - a[1]) * db[0]) / den
    return (a[0] + da[0] * t, a[1] + da[1] * t)


def offset_loop(edges: list[tuple[Pt, Pt, float]]) -> list[Pt]:
    """Offset a closed CCW chain of directed edges to the left by per-edge distances."""
    lines = []
    for a, b, d in edges:
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln, dx / ln
        lines.append(((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d), (dx, dy)))
    out: list[Pt] = []
    for i in range(len(lines)):
        pa, pb, pd = lines[i - 1]
        ca, cb, cd = lines[i]
        p = _line_isect(pa, pd, ca, cd)
        if p is None:  # collinear edges with different offsets: a step
            out.append(pb)
            out.append(ca)
        else:
            out.append(p)
    return out


def _merge_collinear(edges: list[tuple[Pt, Pt, float]]) -> list[tuple[Pt, Pt, float]]:
    out: list[tuple[Pt, Pt, float]] = []
    for e in edges:
        if out:
            a, b, d = out[-1]
            same_dir = abs((b[0] - a[0]) * (e[1][1] - e[0][1]) - (b[1] - a[1]) * (e[1][0] - e[0][0])) < 1e-9
            if same_dir and d == e[2] and _close(b, e[0]):
                out[-1] = (a, e[1], d)
                continue
        out.append(e)
    if len(out) > 1:
        a, b, d = out[-1]
        f = out[0]
        same_dir = abs((b[0] - a[0]) * (f[1][1] - f[0][1]) - (b[1] - a[1]) * (f[1][0] - f[0][0])) < 1e-9
        if same_dir and d == f[2] and _close(b, f[0]):
            out[0] = (a, f[1], d)
            out.pop()
    return out


def _close(p: Pt, q: Pt, tol: float = 1e-6) -> bool:
    return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol


def _chain(edges: list[tuple[Pt, Pt, float]]) -> list[tuple[Pt, Pt, float]]:
    by_start = {(_q(a[0]), _q(a[1])): (a, b, d) for a, b, d in edges}
    first = edges[0]
    out = [first]
    cur = first
    for _ in range(len(edges)):
        nxt = by_start.get((_q(cur[1][0]), _q(cur[1][1])))
        if nxt is None or nxt is first:
            break
        out.append(nxt)
        cur = nxt
    return out


# ── plan model ────────────────────────────────────────────────────────────────


@dataclass
class Opening:
    kind: str  # "door" | "window"
    key: tuple  # elementary wall edge key
    s0: float
    s1: float
    t: float
    room_side: int = 1  # door leaf side: +1 towards +normal, -1 towards -normal
    hinge_at_s0: bool = True


@dataclass
class Plan:
    tiles: list[Rect]
    tile_room: list[int]
    te: float
    ti: float
    edges: dict[tuple, dict[str, int]] = field(default_factory=dict)
    walls: dict[tuple, float] = field(default_factory=dict)
    room_clear: dict[int, list[Pt]] = field(default_factory=dict)
    outer_face: list[Pt] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    chamfers: dict[int, tuple[Pt, Pt, Pt, Pt, Pt]] = field(default_factory=dict)
    corridor: int | None = None


def _split(rect: Rect, rng: random.Random, min_side: float, max_side: float, out: list[Rect]) -> None:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    can_x, can_y = w >= 2 * min_side, h >= 2 * min_side
    if not (can_x or can_y) or (w <= max_side and h <= max_side and rng.random() < 0.5):
        out.append(rect)
        return
    axis_x = can_x and (w >= h or not can_y)
    if can_x and can_y and rng.random() < 0.2:
        axis_x = not axis_x
    if axis_x:
        c = min(max(_snap(x0 + w * rng.uniform(0.3, 0.7)), _q(x0 + min_side)), _q(x1 - min_side))
        _split((x0, y0, c, y1), rng, min_side, max_side, out)
        _split((c, y0, x1, y1), rng, min_side, max_side, out)
    else:
        c = min(max(_snap(y0 + h * rng.uniform(0.3, 0.7)), _q(y0 + min_side)), _q(y1 - min_side))
        _split((x0, y0, x1, c), rng, min_side, max_side, out)
        _split((x0, c, x1, y1), rng, min_side, max_side, out)


def build_plan(rng: random.Random, width: float, depth: float) -> Plan:
    """Random building tiled into rooms; walls, faces and clear polygons derived."""
    W = _snap(width, 0.1)
    D = _snap(depth, 0.1)
    te = rng.choice([0.24, 0.3, 0.365, 0.42])
    ti = rng.choice([0.1, 0.115, 0.15, 0.175])
    min_side, max_side = 1.8, rng.uniform(4.5, 7.0)
    tiles: list[Rect] = []
    corridor_tile: Rect | None = None
    if rng.random() < 0.35 and W >= 9 and D >= 8:
        yc = _snap(D * rng.uniform(0.4, 0.55))
        cw = _snap(rng.uniform(1.2, 1.8))
        corridor_tile = (0.0, yc, W, _q(yc + cw))
        _split((0.0, 0.0, W, yc), rng, min_side, max_side, tiles)
        _split((0.0, _q(yc + cw), W, D), rng, min_side, max_side, tiles)
        tiles.append(corridor_tile)
    elif rng.random() < 0.4 and W >= 10 and D >= 8:
        nx = _snap(W * rng.uniform(0.3, 0.5))
        ny = _snap(D * rng.uniform(0.3, 0.5))
        for r in (
            (0.0, 0.0, _q(W - nx), _q(D - ny)),
            (_q(W - nx), 0.0, W, _q(D - ny)),
            (0.0, _q(D - ny), _q(W - nx), D),
        ):
            _split(r, rng, min_side, max_side, tiles)
    else:
        _split((0.0, 0.0, W, D), rng, min_side, max_side, tiles)
    tile_room = list(range(len(tiles)))
    plan = Plan(tiles=tiles, tile_room=tile_room, te=te, ti=ti)
    if corridor_tile is not None:
        plan.corridor = tiles.index(corridor_tile)
    _edges(plan)
    # Merge one or two pairs of tiles that share a partial edge into L-shaped rooms.
    if rng.random() < 0.45:
        _merge_rooms(plan, rng, 1 if rng.random() < 0.7 else 2)
        _edges(plan)
    _walls_and_faces(plan)
    return plan


def _edges(plan: Plan) -> None:
    xs = sorted({_q(v) for t in plan.tiles for v in (t[0], t[2])})
    ys = sorted({_q(v) for t in plan.tiles for v in (t[1], t[3])})
    edges: dict[tuple, dict[str, int]] = {}
    for ti_, (x0, y0, x1, y1) in enumerate(plan.tiles):
        rid = plan.tile_room[ti_]
        hx = [x for x in xs if x0 - 1e-6 <= x <= x1 + 1e-6]
        vy = [y for y in ys if y0 - 1e-6 <= y <= y1 + 1e-6]
        for xa, xb in zip(hx, hx[1:], strict=False):
            edges.setdefault(("h", _q(y0), xa, xb), {})["above"] = rid
            edges.setdefault(("h", _q(y1), xa, xb), {})["below"] = rid
        for ya, yb in zip(vy, vy[1:], strict=False):
            edges.setdefault(("v", _q(x0), ya, yb), {})["right"] = rid
            edges.setdefault(("v", _q(x1), ya, yb), {})["left"] = rid
    plan.edges = edges


def _merge_rooms(plan: Plan, rng: random.Random, n: int) -> None:
    pairs: list[tuple[int, int]] = []
    for i, a in enumerate(plan.tiles):
        for j, b in enumerate(plan.tiles):
            if j <= i or plan.corridor in (i, j):
                continue
            if plan.tile_room[i] == plan.tile_room[j]:
                continue
            if abs(a[2] - b[0]) < 1e-6 or abs(b[2] - a[0]) < 1e-6:
                lo, hi = max(a[1], b[1]), min(a[3], b[3])
                partial = abs(a[1] - b[1]) > 1e-6 or abs(a[3] - b[3]) > 1e-6
            elif abs(a[3] - b[1]) < 1e-6 or abs(b[3] - a[1]) < 1e-6:
                lo, hi = max(a[0], b[0]), min(a[2], b[2])
                partial = abs(a[0] - b[0]) > 1e-6 or abs(a[2] - b[2]) > 1e-6
            else:
                continue
            if hi - lo >= 1.8 and partial:
                pairs.append((i, j))
    rng.shuffle(pairs)
    used: set[int] = set()
    for i, j in pairs:
        if n <= 0:
            break
        if i in used or j in used:
            continue
        old = plan.tile_room[j]
        plan.tile_room = [plan.tile_room[i] if r == old else r for r in plan.tile_room]
        used |= {i, j}
        n -= 1


def _directed(key: tuple, side: str) -> tuple[Pt, Pt]:
    kind, c, a, b = key
    if kind == "h":
        return ((a, c), (b, c)) if side == "above" else ((b, c), (a, c))
    return ((c, b), (c, a)) if side == "right" else ((c, a), (c, b))


def _walls_and_faces(plan: Plan) -> None:
    walls: dict[tuple, float] = {}
    room_edges: dict[int, list[tuple[Pt, Pt, float]]] = {}
    outer: list[tuple[Pt, Pt, float]] = []
    for key, sides in plan.edges.items():
        rids = set(sides.values())
        if len(sides) == 1:
            walls[key] = plan.te
            side, rid = next(iter(sides.items()))
            a, b = _directed(key, side)
            room_edges.setdefault(rid, []).append((a, b, plan.te / 2))
            outer.append((a, b, -plan.te / 2))
        elif len(rids) == 2:
            walls[key] = plan.ti
            for side, rid in sides.items():
                a, b = _directed(key, side)
                room_edges.setdefault(rid, []).append((a, b, plan.ti / 2))
    plan.walls = walls
    plan.room_clear = {rid: offset_loop(_merge_collinear(_chain(es))) for rid, es in room_edges.items()}
    plan.outer_face = offset_loop(_merge_collinear(_chain(outer)))


def wall_runs(plan: Plan) -> list[tuple[Pt, Pt, float]]:
    """Maximal collinear centreline runs of equal thickness (through openings)."""
    groups: dict[tuple, list[tuple[float, float]]] = {}
    for (kind, c, a, b), t in plan.walls.items():
        groups.setdefault((kind, c, t), []).append((a, b))
    runs: list[tuple[Pt, Pt, float]] = []
    for (kind, c, t), spans in groups.items():
        spans.sort()
        cur = list(spans[0])
        merged = []
        for a, b in spans[1:]:
            if abs(a - cur[1]) < 1e-6:
                cur[1] = b
            else:
                merged.append(tuple(cur))
                cur = [a, b]
        merged.append(tuple(cur))
        for a, b in merged:
            runs.append(((a, c), (b, c), t) if kind == "h" else ((c, a), (c, b), t))
    return runs


# ── stroked "SHX" text ────────────────────────────────────────────────────────

_SEG = {
    "a": ((0, 2), (1, 2)),
    "b": ((1, 2), (1, 1)),
    "c": ((1, 1), (1, 0)),
    "d": ((0, 0), (1, 0)),
    "e": ((0, 0), (0, 1)),
    "f": ((0, 1), (0, 2)),
    "g": ((0, 1), (1, 1)),
    "m": ((0.5, 2), (0.5, 0)),
    "n": ((0, 2), (1, 0)),
    "r": ((0.5, 1), (1, 0)),
    "s": ((1, 2), (0, 0)),
    "k": ((1, 2), (0, 1)),
}
_GLYPHS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "A": "abcefg", "B": "abcdefg", "C": "adef", "D": "bcdeg",
    "E": "adefg", "F": "aefg", "G": "acdef", "H": "bcefg", "I": "m", "K": "efgk", "L": "def",
    "M": "abcefm", "N": "efbcn", "O": "abcdef", "P": "abefg", "R": "abefgr", "S": "afgcd", "T": "am",
    "U": "bcdef", "V": "bcdef", "W": "bcdefm", "Y": "fgbcd", "Z": "asd", "-": "g", "/": "s",
}  # fmt: skip


def _shx_text(c: Any, text: str, x: float, y: float, size: float, angle: float = 0.0) -> None:
    """Text as stroked line geometry, like SHX fonts exploded by a CAD export."""
    w = size * 0.5
    ca, sa = math.cos(angle), math.sin(angle)
    p = c.beginPath()
    cx = 0.0
    for ch in text.upper():
        segs = _GLYPHS.get(ch)
        if segs:
            for s in segs:
                (ax, ay), (bx, by) = _SEG[s]
                for (u, v), first in (((ax, ay), True), ((bx, by), False)):
                    lx, ly = cx + u * w, v * size / 2
                    px, py = x + lx * ca - ly * sa, y + lx * sa + ly * ca
                    if first:
                        p.moveTo(px, py)
                    else:
                        p.lineTo(px, py)
        elif ch == ".":
            px, py = x + cx * ca, y + cx * sa
            p.moveTo(px, py)
            p.lineTo(px + 0.3 * ca, py + 0.3 * sa)
        cx += w * 1.6
    c.drawPath(p, stroke=1, fill=0)


# ── page composition ──────────────────────────────────────────────────────────


@dataclass
class Sheet:
    """Everything decided about one page before drawing."""

    seed: int
    rng: random.Random
    page_name: str
    W: float
    H: float
    imperial: bool
    ratio: int
    lang: dict[str, Any]
    lang_code: str
    k: float  # PDF points per metre
    angle: float  # content rotation, radians
    page_rotation: int
    style: str
    shx: bool
    ox: float = 0.0
    oy: float = 0.0
    bcx: float = 0.0
    bcy: float = 0.0
    gt: dict[str, Any] = field(default_factory=dict)

    def P(self, x: float, y: float) -> Pt:
        dx, dy = (x - self.bcx) * self.k, (y - self.bcy) * self.k
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        return (self.ox + dx * ca - dy * sa, self.oy + dx * sa + dy * ca)

    def tl(self, p: Pt) -> list[float]:
        """reportlab bottom-left point -> top-left ground-truth point.

        A rotated sheet is drawn into a portrait media box (see ``make_page``);
        ground truth lives in that unrotated space, as ``drawings()`` reports it.
        """
        if self.page_rotation:
            return [round(self.H - p[1], 3), round(self.W - p[0], 3)]
        return [round(p[0], 3), round(self.H - p[1], 3)]

    def vec(self, dx: float, dy: float) -> Pt:
        """Rotate a plan-direction vector into page space (unit-free)."""
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        return (dx * ca - dy * sa, dx * sa + dy * ca)


def _register_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(FONT, str(_FONT_DIR / "DejaVuSans.ttf")))
    _FONTS_READY = True


def _choose_sheet(seed: int, *, scan: bool, force_kind: str | None = None) -> tuple[Sheet, str]:
    rng = random.Random(seed * 7919 + (17 if scan else 3))
    kind = force_kind or ("noise" if rng.random() < 0.12 else "plan")
    imperial = rng.random() < 0.25
    if imperial:
        pages = [p for p in IMPERIAL_PAGES if not scan or p[0] in SCAN_PAGES]
        lang, code = IMPERIAL_LANG, "en_us"
        ratios = sorted(r for r, _ in IMPERIAL_SCALES)
    else:
        pages = [p for p in METRIC_PAGES if not scan or p[0] in SCAN_PAGES]
        code = rng.choice(sorted(LANGS))
        lang = LANGS[code]
        ratios = sorted(set(METRIC_RATIOS))
    name, w, h = rng.choice(pages)
    angle = 0.0
    if not scan:
        r = rng.random()
        if r < 0.05:
            angle = math.pi / 2
        elif r < 0.17:
            angle = math.radians(rng.choice([-1, 1]) * rng.uniform(8, 40))
    left = 20 * MM if rng.random() < 0.5 else 10 * MM
    area = (left + 10 * MM, 90 * MM, w - 20 * MM, h - 20 * MM)
    bw = rng.uniform(9.0, 22.0)
    bd = rng.uniform(7.0, min(14.0, bw))
    ca, sa = abs(math.cos(angle)), abs(math.sin(angle))

    def fits(ratio: int) -> bool:
        k = 72.0 / (0.0254 * ratio)
        ext_w = (bw * ca + bd * sa) * k + 60 * MM
        ext_h = (bw * sa + bd * ca) * k + 50 * MM
        return ext_w <= area[2] - area[0] and ext_h <= area[3] - area[1]

    allowed = [r for r in ratios if fits(r)]
    while not allowed and bw > 7:
        bw, bd = bw * 0.85, max(5.5, bd * 0.85)
        allowed = [r for r in ratios if fits(r)]
    if not allowed:
        allowed = [ratios[-1]]
    ratio = allowed[0] if (len(allowed) == 1 or rng.random() < 0.75) else allowed[1]
    inch = dict(IMPERIAL_SCALES).get(ratio, "") if imperial else ""
    sheet = Sheet(
        seed=seed,
        rng=rng,
        page_name=name,
        W=w,
        H=h,
        imperial=imperial,
        ratio=ratio,
        lang=lang,
        lang_code=code,
        k=72.0 / (0.0254 * ratio),
        angle=angle,
        page_rotation=90 if (not scan and rng.random() < 0.12) else 0,
        style=rng.choices(["double", "poche", "hatch", "double_fill", "paint"], [0.4, 0.2, 0.15, 0.1, 0.15])[0],
        shx=rng.random() < 0.15,
    )
    sheet.gt.update({"scale_inch": inch, "frame_left": left, "area": area, "bw": bw, "bd": bd})
    return sheet, kind


def make_page(seed: int, *, scan: bool = False, force_kind: str | None = None) -> tuple[bytes, dict[str, Any]]:
    """Build one page. Returns ``(pdf_bytes, ground_truth)``."""
    from reportlab.pdfgen import canvas as rl_canvas

    _register_fonts()
    sheet, kind = _choose_sheet(seed, scan=scan, force_kind=force_kind)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(sheet.W, sheet.H), invariant=1)
    c.setTitle(f"bench {seed}")
    if sheet.page_rotation:
        # reportlab swaps the media box to portrait; draw the landscape sheet into
        # it so the viewer's 90-degree turn shows it upright, as a scanned-in
        # CAD export with /Rotate does.
        c.setPageRotation(sheet.page_rotation)
        c.transform(0, 1, -1, 0, sheet.H, 0)
    gt: dict[str, Any] = {
        "seed": seed,
        "kind": kind,
        "variant": "vector",
        "page": {"name": sheet.page_name, "w": round(sheet.W, 3), "h": round(sheet.H, 3)},
        "rotation": sheet.page_rotation,
        "content_angle_deg": round(math.degrees(sheet.angle), 2),
        "style": sheet.style,
        "lang": sheet.lang_code,
        "pt_per_m": sheet.k,
        "rooms": [],
        "walls": [],
        "symbols": {},
        "symbol_radius": {},
    }
    frame = _frame(c, sheet)
    tb = _title_block(c, sheet, frame, kind, gt)
    if kind == "plan":
        _draw_plan(c, sheet, frame, tb, gt)
    else:
        _draw_noise_sheet(c, sheet, frame, tb)
    c.showPage()
    c.save()
    return buf.getvalue(), gt


def _frame(c: Any, s: Sheet) -> Rect:
    m = 10 * MM
    left = s.gt["frame_left"]
    c.setStrokeGray(0)
    c.setLineWidth(s.rng.choice([0.5, 0.7, 1.0, 1.4]))
    c.rect(left, m, s.W - left - m, s.H - 2 * m, stroke=1, fill=0)
    return (left, m, s.W - m, s.H - m)


def _font(c: Any, size: float) -> None:
    c.setFont(FONT, size)


def _title_block(c: Any, s: Sheet, frame: Rect, kind: str, gt: dict[str, Any]) -> Rect:
    rng = s.rng
    tw, th = 175 * MM, 52 * MM
    x1, y0 = frame[2], frame[1]
    x0, y1 = x1 - tw, y0 + th
    c.setLineWidth(rng.choice([0.35, 0.5, 0.7]))
    c.rect(x0, y0, tw, th, stroke=1, fill=0)
    rows = [y0 + th * f for f in (0.25, 0.5, 0.75)]
    for y in rows:
        c.line(x0, y, x1, y)
    for f in (0.35, 0.7):
        c.line(x0 + tw * f, y0, x0 + tw * f, rows[1])
    c.setFillGray(0)
    _font(c, 7)
    # scale note
    if kind == "plan":
        roll = rng.random()
        ratio: int | None = s.ratio if roll > 0.08 else None
    else:
        roll = rng.random()
        ratio = rng.choice([5, 10, 20]) if roll > 0.3 else None
    if ratio is not None and s.imperial and kind == "plan":
        value = _imperial_text(rng, s.gt["scale_inch"])
        text = rng.choice(s.lang["scale"]).format(i=value)
    elif ratio is not None:
        text = rng.choice(s.lang["scale"] if not s.imperial else ["SCALE 1:{r}"]).format(r=ratio)
    else:
        text = rng.choice(["SCALE: NTS", "NOT TO SCALE", ""])
    split_label = ratio is not None and rng.random() < 0.3 and not text.startswith("{")
    title = s.lang["title"] if kind == "plan" else rng.choice(["DETAILS", "SCHEDULES", "GENERAL NOTES"])
    c.drawString(x0 + 4, rows[2] + 6, "Example Architects - Residential building")
    c.setFont(FONT, 10)
    c.drawString(x0 + 4, rows[1] + 8, title)
    _font(c, 7)
    c.drawString(x0 + 4, y0 + 6, f"A-{100 + s.seed % 400}")
    c.drawString(x0 + tw * 0.35 + 4, y0 + 6, "2026-11-04")
    if split_label:
        c.drawString(x0 + tw * 0.7 + 4, rows[0] + 6, s.lang["label"])
        value_only = text
        for prefix in (s.lang["label"], "SCALE", "Scale"):
            if value_only.startswith(prefix):
                value_only = value_only[len(prefix) :].lstrip(" :.")
        c.drawString(x0 + tw * 0.7 + 4, y0 + 6, value_only)
    elif text:
        c.drawString(x0 + tw * 0.7 + 4, y0 + 6, text)
    c.drawString(x0 + tw * 0.35 + 4, rows[0] + 6, "Rev. B")
    gt["scale"] = {"ratio": ratio, "text": text}
    # notes with ratio-like distractors
    nx, ny = x0, y1 + 8 * MM
    _font(c, 6.5)
    c.drawString(nx, ny + 40, "NOTES:")
    notes = ["All dimensions to be checked on site.", "Do not scale from this drawing."]
    notes += rng.sample(DISTRACTORS, k=rng.randint(0, 2))
    for i, note in enumerate(notes):
        c.drawString(nx, ny + 32 - 8 * i, f"{i + 1}. {note}")
    return (x0, y0, x1, ny + 48)


def _draw_noise_sheet(c: Any, s: Sheet, frame: Rect, tb: Rect) -> None:
    """A sheet with no building: schedule table, details with hatching, legend."""
    rng = s.rng
    x, y = frame[0] + 20 * MM, frame[3] - 30 * MM
    # schedule table
    c.setLineWidth(0.3)
    cols, rows, cw, rh = rng.randint(4, 7), rng.randint(6, 14), 28 * MM, 6 * MM
    for r in range(rows + 1):
        c.line(x, y - r * rh, x + cols * cw, y - r * rh)
    for k in range(cols + 1):
        c.line(x + k * cw, y, x + k * cw, y - rows * rh)
    _font(c, 6)
    for r in range(rows):
        for k in range(cols):
            c.drawString(x + k * cw + 2, y - (r + 1) * rh + 2, f"D{r + 1:02d}" if k == 0 else f"{rng.randint(60, 240)}")
    # wall-section details: layered strips with hatch and dims
    for d in range(rng.randint(1, 3)):
        dx = frame[0] + 30 * MM + d * 110 * MM
        dy = frame[1] + 70 * MM
        if dx + 90 * MM > tb[0]:
            break
        _detail(c, rng, dx, dy)
    if rng.random() < 0.5:
        _legend(c, s, frame[0] + 20 * MM, frame[1] + 20 * MM)


def _detail(c: Any, rng: random.Random, x: float, y: float) -> None:
    layers = [rng.uniform(4, 25) for _ in range(rng.randint(3, 5))]
    hgt = rng.uniform(60, 110)
    cx = x
    c.setLineWidth(0.5)
    for i, w in enumerate(layers):
        c.rect(cx, y, w, hgt, stroke=1, fill=0)
        if i % 2 == 0:
            c.setLineWidth(0.2)
            step = rng.uniform(2.0, 4.0)
            t = -hgt
            while t < w:
                xa, ya = cx + max(t, 0), y + max(-t, 0)
                xb_t = min(t + hgt, w)
                c.line(xa, ya, cx + xb_t, y + (xb_t - t))
                t += step
            c.setLineWidth(0.5)
        cx += w
    _font(c, 7)
    c.drawString(x, y - 12, rng.choice(DETAIL_TITLES).format(r=rng.choice([5, 10, 20])))


def _legend(c: Any, s: Sheet, x: float, y: float) -> None:
    _font(c, 6)
    c.drawString(x, y + 60, "LEGEND")
    for i, sym in enumerate(["socket", "light"]):
        _symbol(c, s, sym, (x + 10, y + 45 - 18 * i), 0.0)
        c.drawString(x + 25, y + 43 - 18 * i, sym.upper())


# ── symbols (paper-size, in page points) ──────────────────────────────────────


def _symbol(c: Any, s: Sheet, kind: str, at: Pt, rot: float) -> list[Pt]:
    """Draw a paper-size symbol centred at ``at``; return its drawn points."""
    ca, sa = math.cos(rot), math.sin(rot)

    def T(u: float, v: float) -> Pt:
        return (at[0] + u * ca - v * sa, at[1] + u * sa + v * ca)

    c.setLineWidth(0.3)
    c.setStrokeGray(0)
    pts: list[Pt] = []
    if kind == "socket":
        r = 1.3 * MM
        p = c.beginPath()
        _circle_path(p, T(0, r * 0.4), r, pts)
        a, b = T(0, -r * 0.6), T(0, -r * 1.6)
        p.moveTo(*a)
        p.lineTo(*b)
        e, f = T(-r, -r * 1.6), T(r, -r * 1.6)
        p.moveTo(*e)
        p.lineTo(*f)
        pts += [a, b, e, f]
        c.drawPath(p, stroke=1, fill=0)
    elif kind == "light":
        r = 2.2 * MM
        p = c.beginPath()
        _circle_path(p, at, r, pts)
        q = r * 0.7071
        for u, v in ((-q, -q), (-q, q)):
            a, b = T(u, v), T(-u, -v)
            p.moveTo(*a)
            p.lineTo(*b)
            pts += [a, b]
        c.drawPath(p, stroke=1, fill=0)
    return pts


def _circle_path(p: Any, ctr: Pt, r: float, pts: list[Pt]) -> None:
    k = 0.5523 * r
    x, y = ctr
    p.moveTo(x + r, y)
    p.curveTo(x + r, y + k, x + k, y + r, x, y + r)
    p.curveTo(x - k, y + r, x - r, y + k, x - r, y)
    p.curveTo(x - r, y - k, x - k, y - r, x, y - r)
    p.curveTo(x + k, y - r, x + r, y - k, x + r, y)
    pts += [(x - r, y - r), (x + r, y + r)]


def _bbox_centre(pts: list[Pt]) -> Pt:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


# ── the floor plan ────────────────────────────────────────────────────────────


def _draw_plan(c: Any, s: Sheet, frame: Rect, tb: Rect, gt: dict[str, Any]) -> None:
    rng = s.rng
    area = s.gt["area"]
    plan = build_plan(rng, s.gt["bw"], s.gt["bd"])
    xs = [p[0] for p in plan.outer_face]
    ys = [p[1] for p in plan.outer_face]
    s.bcx, s.bcy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    s.ox = (area[0] + area[2]) / 2 + rng.uniform(-10, 10) * MM
    s.oy = (area[1] + area[3]) / 2 + rng.uniform(-5, 5) * MM
    _place_openings(plan, rng)
    _chamfer(plan, rng)

    # ground truth: rooms and walls
    for rid, poly in sorted(plan.room_clear.items()):
        area = shoelace(poly)
        gt["rooms"].append(
            {"id": rid, "polygon": [s.tl(s.P(*p)) for p in poly], "area_m2": round(area, 4), "n_vertices": len(poly)}
        )
    for a, b, t in wall_runs(plan):
        gt["walls"].append(
            {"a": s.tl(s.P(*a)), "b": s.tl(s.P(*b)), "thickness_m": t, "length_m": round(math.dist(a, b), 4)}
        )
    for rid, (p1, p1o, _v, p2o, p2) in plan.chamfers.items():
        a = ((p1[0] + p1o[0]) / 2, (p1[1] + p1o[1]) / 2)
        b = ((p2[0] + p2o[0]) / 2, (p2[1] + p2o[1]) / 2)
        gt["walls"].append(
            {"a": s.tl(s.P(*a)), "b": s.tl(s.P(*b)), "thickness_m": plan.ti, "length_m": round(math.dist(a, b), 4)}
        )
    gt["building"] = {"outer_face": [s.tl(s.P(*p)) for p in plan.outer_face], "te": plan.te, "ti": plan.ti}

    occupied: dict[int, list[Rect]] = {rid: [] for rid in plan.room_clear}
    _draw_walls(c, s, plan)
    _draw_openings(c, s, plan, gt, occupied)
    if rng.random() < 0.85:
        _dimensions(c, s, plan)
    if rng.random() < 0.45:
        _grid(c, s, plan)
    _room_contents(c, s, plan, gt, occupied)
    if rng.random() < 0.3:
        _legend(c, s, frame[0] + 8 * MM, frame[1] + 8 * MM)
    if rng.random() < 0.25:
        _scale_bar(c, s, tb[0] - 70 * MM, frame[1] + 6 * MM)
    if rng.random() < 0.2:
        _detail(c, rng, frame[0] + 70 * MM, frame[1] + 18 * MM)


def _place_openings(plan: Plan, rng: random.Random) -> None:
    margin = max(plan.te, plan.ti) / 2 + 0.12
    by_room: dict[int, list[tuple]] = {}
    for key, sides in plan.edges.items():
        if key not in plan.walls:
            continue
        for rid in set(sides.values()):
            by_room.setdefault(rid, []).append(key)
    used: set[tuple] = set()
    door_w = [0.8, 0.9, 1.0]

    def add(key: tuple, kind: str, width: float) -> bool:
        _, _c, a, b = key
        if key in used or b - a < width + 2 * margin:
            return False
        s0 = _snap(rng.uniform(a + margin, b - margin - width), 0.01)
        plan.openings.append(
            Opening(kind, key, s0, _q(s0 + width), plan.walls[key], rng.choice([1, -1]), rng.random() < 0.5)
        )
        used.add(key)
        return True

    rooms = sorted(by_room)
    for rid in rooms:
        interior = [k for k in by_room[rid] if plan.walls[k] == plan.ti]
        rng.shuffle(interior)
        if plan.corridor is not None:
            corr = plan.tile_room[plan.corridor]
            interior.sort(key=lambda k: 0 if corr in plan.edges[k].values() else 1)
        n_doors = 1 if rng.random() < 0.75 else 2
        for key in interior:
            if n_doors <= 0:
                break
            if add(key, "door", rng.choice(door_w)):
                n_doors -= 1
    ext = [k for k, t in plan.walls.items() if t == plan.te]
    rng.shuffle(ext)
    if ext:
        add(ext[0], "door", 1.0)
    for key in ext[1:]:
        if rng.random() < 0.6:
            add(key, "window", _snap(rng.uniform(0.9, 2.0)))
    # A door opening into the exterior goes inward; interior doors any side.
    for op in plan.openings:
        if op.kind == "door" and plan.walls[op.key] == plan.te:
            side = next(iter(plan.edges[op.key]))
            op.room_side = 1 if side in ("above", "right") else -1


def _chamfer(plan: Plan, rng: random.Random) -> None:
    if rng.random() > 0.3:
        return
    counts: dict[int, int] = {}
    for r in plan.tile_room:
        counts[r] = counts.get(r, 0) + 1
    cands = [rid for rid, poly in plan.room_clear.items() if counts.get(rid) == 1 and len(poly) == 4]
    rng.shuffle(cands)
    for rid in cands:
        poly = plan.room_clear[rid]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        if max(xs) - min(xs) < 2.6 or max(ys) - min(ys) < 2.6:
            continue
        i = rng.randrange(4)
        v = poly[i]
        prev_, next_ = poly[i - 1], poly[(i + 1) % 4]
        cs = _snap(rng.uniform(0.6, 1.0))
        # keep doors and windows clear of the cut corner
        clash = False
        for op in plan.openings:
            kind, cc, _a, _b = op.key
            for sv in (op.s0, op.s1):
                q = (sv, cc) if kind == "h" else (cc, sv)
                if math.dist(q, v) < cs + 0.5:
                    clash = True
        if clash:
            continue
        u1 = ((prev_[0] - v[0]) / math.dist(prev_, v), (prev_[1] - v[1]) / math.dist(prev_, v))
        u2 = ((next_[0] - v[0]) / math.dist(next_, v), (next_[1] - v[1]) / math.dist(next_, v))
        d = plan.ti * math.sqrt(2)
        p1 = (v[0] + u1[0] * cs, v[1] + u1[1] * cs)
        p2 = (v[0] + u2[0] * cs, v[1] + u2[1] * cs)
        p1o = (v[0] + u1[0] * (cs - d), v[1] + u1[1] * (cs - d))
        p2o = (v[0] + u2[0] * (cs - d), v[1] + u2[1] * (cs - d))
        plan.chamfers[rid] = (p1, p1o, v, p2o, p2)
        plan.room_clear[rid] = poly[:i] + [p1, p2] + poly[i + 1 :]
        return


def _cut(segs: list[tuple[Pt, Pt]], plan: Plan, kinds: tuple[str, ...]) -> list[tuple[Pt, Pt]]:
    """Remove the parts of axis faces that fall inside openings."""
    out = segs
    for op in plan.openings:
        if op.kind not in kinds:
            continue
        kind, cc, _a, _b = op.key
        lo, hi = cc - op.t / 2 - 1e-6, cc + op.t / 2 + 1e-6
        nxt = []
        for p, q in out:
            if kind == "h" and abs(p[1] - q[1]) < 1e-9 and lo <= p[1] <= hi:
                a, b = sorted((p[0], q[0]))
                if b <= op.s0 or a >= op.s1:
                    nxt.append((p, q))
                    continue
                if a < op.s0:
                    nxt.append(((a, p[1]), (op.s0, p[1])))
                if b > op.s1:
                    nxt.append(((op.s1, p[1]), (b, p[1])))
            elif kind == "v" and abs(p[0] - q[0]) < 1e-9 and lo <= p[0] <= hi:
                a, b = sorted((p[1], q[1]))
                if b <= op.s0 or a >= op.s1:
                    nxt.append((p, q))
                    continue
                if a < op.s0:
                    nxt.append(((p[0], a), (p[0], op.s0)))
                if b > op.s1:
                    nxt.append(((p[0], op.s1), (p[0], b)))
            else:
                nxt.append((p, q))
        out = nxt
    return out


def _face_segments(plan: Plan) -> list[tuple[Pt, Pt]]:
    segs: list[tuple[Pt, Pt]] = []
    for rid, poly in plan.room_clear.items():
        ring = poly
        if rid in plan.chamfers:  # faces behind the diagonal wall stay drawn
            p1, _p1o, v, _p2o, p2 = plan.chamfers[rid]
            i = ring.index(p1)
            ring = ring[: i + 1] + [v] + ring[i + 1 :]
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            if plan.chamfers.get(rid) and {a, b} == {plan.chamfers[rid][0], plan.chamfers[rid][4]}:
                continue
            segs.append((a, b))
    for i in range(len(plan.outer_face)):
        segs.append((plan.outer_face[i], plan.outer_face[(i + 1) % len(plan.outer_face)]))
    return segs


def _wall_rects(plan: Plan) -> list[tuple[Pt, Pt, Pt, Pt]]:
    out = []
    for (kind, cc, a, b), t in plan.walls.items():
        spans = [(a - t / 2, b + t / 2)]
        for op in plan.openings:
            if op.key == (kind, cc, a, b):
                spans = [(spans[0][0], op.s0), (op.s1, spans[0][1])]
        for lo, hi in spans:
            if kind == "h":
                out.append(((lo, cc - t / 2), (hi, cc - t / 2), (hi, cc + t / 2), (lo, cc + t / 2)))
            else:
                out.append(((cc - t / 2, lo), (cc + t / 2, lo), (cc + t / 2, hi), (cc - t / 2, hi)))
    return out


def _poly(c: Any, s: Sheet, pts: list[Pt], *, stroke: int, fill: int) -> None:
    p = c.beginPath()
    p.moveTo(*s.P(*pts[0]))
    for q in pts[1:]:
        p.lineTo(*s.P(*q))
    p.close()
    c.drawPath(p, stroke=stroke, fill=fill)


def _draw_walls(c: Any, s: Sheet, plan: Plan) -> None:
    rng = s.rng
    style = s.style
    lw = rng.choice([0.35, 0.5, 0.7])
    c.setLineWidth(lw)
    c.setStrokeGray(rng.choice([0.0, 0.0, 0.2]))
    if style == "paint":
        c.setFillGray(rng.choice([0.25, 0.45, 0.6]))
        _poly(c, s, plan.outer_face, stroke=0, fill=1)
        c.setFillGray(1.0)
        for rid, poly in plan.room_clear.items():
            _poly(c, s, poly, stroke=0, fill=1)
        for op in plan.openings:
            kind, cc, _a, _b = op.key
            t = op.t + 0.02
            if kind == "h":
                r = [(op.s0, cc - t / 2), (op.s1, cc - t / 2), (op.s1, cc + t / 2), (op.s0, cc + t / 2)]
            else:
                r = [(cc - t / 2, op.s0), (cc + t / 2, op.s0), (cc + t / 2, op.s1), (cc - t / 2, op.s1)]
            _poly(c, s, r, stroke=0, fill=1)
        c.setFillGray(rng.choice([0.25, 0.45]))
        for _rid, (_p1, p1o, v, p2o, _p2) in plan.chamfers.items():
            _poly(c, s, [p1o, v, p2o], stroke=0, fill=1)
        return
    if style in ("poche", "double_fill"):
        c.setFillGray(rng.choice([0.0, 0.2, 0.35]) if style == "poche" else rng.choice([0.75, 0.85]))
        outline = style == "poche" and rng.random() < 0.4
        for quad in _wall_rects(plan):
            if rng.random() < 0.5:
                lo = s.P(*quad[0])
                hi = s.P(*quad[2])
                if s.angle == 0.0:
                    c.rect(lo[0], lo[1], hi[0] - lo[0], hi[1] - lo[1], stroke=int(outline), fill=1)
                    continue
            _poly(c, s, list(quad), stroke=int(outline), fill=1)
        for _rid, (_p1, p1o, v, p2o, _p2) in plan.chamfers.items():
            _poly(c, s, [p1o, v, p2o], stroke=0, fill=1)
            p = c.beginPath()
            p.moveTo(*s.P(*_p1))
            p.lineTo(*s.P(*_p2))
            p.lineTo(*s.P(*p2o))
            p.lineTo(*s.P(*p1o))
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        if style == "poche":
            return
    # double lines (also over the light fill of double_fill)
    segs = _cut(_face_segments(plan), plan, ("door", "window"))
    for op in plan.openings:
        kind, cc, _a, _b = op.key
        for sv in (op.s0, op.s1):
            if kind == "h":
                segs.append(((sv, cc - op.t / 2), (sv, cc + op.t / 2)))
            else:
                segs.append(((cc - op.t / 2, sv), (cc + op.t / 2, sv)))
    for _rid, (p1, p1o, _v, p2o, p2) in plan.chamfers.items():
        segs += [(p1, p2), (p1o, p2o)]
    pieces: list[tuple[Pt, Pt]] = []
    for a, b in segs:
        if math.dist(a, b) > 2.0 and rng.random() < 0.3:
            t = rng.uniform(0.3, 0.7)
            m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            pieces += [(a, m), (m, b)]
        else:
            pieces.append((a, b))
    rng.shuffle(pieces)
    jit = 0.15 / s.k  # 0.15 pt CAD imprecision at joints
    mode = rng.choice(["each", "batch", "batch"])
    p = c.beginPath()
    for i, (a, b) in enumerate(pieces):
        a2 = (a[0] + rng.uniform(-jit, jit), a[1] + rng.uniform(-jit, jit))
        b2 = (b[0] + rng.uniform(-jit, jit), b[1] + rng.uniform(-jit, jit))
        p.moveTo(*s.P(*a2))
        p.lineTo(*s.P(*b2))
        if mode == "each" or i % 25 == 24:
            c.drawPath(p, stroke=1, fill=0)
            p = c.beginPath()
    c.drawPath(p, stroke=1, fill=0)
    if style == "hatch":
        _hatch_walls(c, s, plan)
    for _rid, (_p1, p1o, v, p2o, _p2) in plan.chamfers.items():
        c.setFillGray(0.5)
        _poly(c, s, [p1o, v, p2o], stroke=0, fill=1)


def _hatch_walls(c: Any, s: Sheet, plan: Plan) -> None:
    c.setLineWidth(0.15)
    step = s.rng.uniform(1.6, 3.0) / s.k  # paper spacing in metres
    p = c.beginPath()
    for quad in _wall_rects(plan):
        (x0, y0), (x1, y1) = quad[0], quad[2]
        if abs(x1 - x0) < 1e-9 or plan.te not in (round(abs(x1 - x0), 4), round(abs(y1 - y0), 4)):
            continue
        t = -(y1 - y0)
        while t < x1 - x0:
            xa = x0 + max(t, 0.0)
            ya = y0 + max(-t, 0.0)
            xb = x0 + min(t + (y1 - y0), x1 - x0)
            yb = y0 + (xb - x0) - t
            p.moveTo(*s.P(xa, ya))
            p.lineTo(*s.P(xb, yb))
            t += step
    c.drawPath(p, stroke=1, fill=0)


def _draw_openings(c: Any, s: Sheet, plan: Plan, gt: dict[str, Any], occupied: dict[int, list[Rect]]) -> None:
    rng = s.rng
    c.setStrokeGray(0)
    for op in plan.openings:
        kind, cc, _a, _b = op.key
        t = op.t
        if op.kind == "window":
            c.setLineWidth(0.25)
            p = c.beginPath()
            for f in (-1 / 6, 1 / 6):
                if kind == "h":
                    a, b = (op.s0, cc + f * t), (op.s1, cc + f * t)
                else:
                    a, b = (cc + f * t, op.s0), (cc + f * t, op.s1)
                p.moveTo(*s.P(*a))
                p.lineTo(*s.P(*b))
            c.drawPath(p, stroke=1, fill=0)
            continue
        w = op.s1 - op.s0
        n = op.room_side
        hs, os_ = (op.s0, op.s1) if op.hinge_at_s0 else (op.s1, op.s0)
        if kind == "h":
            hinge = (hs, cc + n * t / 2)
            tip = (hs, cc + n * (t / 2 + w))
            other = (os_, cc + n * t / 2)
        else:
            hinge = (cc + n * t / 2, hs)
            tip = (cc + n * (t / 2 + w), hs)
            other = (cc + n * t / 2, os_)
        H, Tp, O = s.P(*hinge), s.P(*tip), s.P(*other)
        c.setLineWidth(rng.choice([0.25, 0.35]))
        r = math.dist(H, Tp)
        a0 = math.atan2(Tp[1] - H[1], Tp[0] - H[0])
        a1 = math.atan2(O[1] - H[1], O[0] - H[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        kk = 4 / 3 * math.tan(da / 4) * r
        c1 = (Tp[0] - kk * math.sin(a0), Tp[1] + kk * math.cos(a0))
        c2 = (O[0] + kk * math.sin(a1), O[1] - kk * math.cos(a1))
        p = c.beginPath()
        p.moveTo(*H)
        p.lineTo(*Tp)
        if rng.random() < 0.5:
            c.drawPath(p, stroke=1, fill=0)
            p = c.beginPath()
        p.moveTo(*Tp)
        p.curveTo(*c1, *c2, *O)
        c.drawPath(p, stroke=1, fill=0)
        cls = f"door_{round(w * 100)}"
        gt["symbols"].setdefault(cls, []).append(s.tl(_bbox_centre([H, Tp, O, c1, c2])))
        gt["symbol_radius"][cls] = round(0.5 * w * s.k, 2)
        lo = (min(hinge[0], tip[0], other[0]) - 0.1, min(hinge[1], tip[1], other[1]) - 0.1)
        hi = (max(hinge[0], tip[0], other[0]) + 0.1, max(hinge[1], tip[1], other[1]) + 0.1)
        for rid in plan.edges[op.key].values():
            occupied.setdefault(rid, []).append((lo[0], lo[1], hi[0], hi[1]))


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _room_contents(c: Any, s: Sheet, plan: Plan, gt: dict[str, Any], occupied: dict[int, list[Rect]]) -> None:
    rng = s.rng
    names = s.lang["rooms"]
    counted: dict[str, list[list[float]]] = gt["symbols"]
    for idx, (rid, poly) in enumerate(sorted(plan.room_clear.items())):
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        # the largest clear rectangle we use for contents: the room's tile(s) bbox, inset
        box = (min(xs), min(ys), max(xs), max(ys))
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        occ = occupied.setdefault(rid, [])
        if rid in plan.chamfers:
            v = plan.chamfers[rid][2]
            occ.append((v[0] - 1.2, v[1] - 1.2, v[0] + 1.2, v[1] + 1.2))
        # label
        area = shoelace(poly)
        name = names[idx % len(names)]
        if s.imperial:
            label2 = f"{area * 10.7639:.0f} SF"
        else:
            label2 = f"{area:.2f} m²" if s.lang_code != "de" else f"{area:.2f} m²".replace(".", ",")
        size = rng.choice([6.0, 7.0, 8.0])
        lx, ly = s.P(cx, cy)
        c.setFillGray(0)
        if s.shx:
            c.setLineWidth(0.25)
            _shx_text(c, name[:8], lx - 12, ly + 2, size, s.angle if abs(s.angle) < 1 else 0.0)
            _shx_text(c, f"{area:.2f}", lx - 12, ly - size - 2, size, s.angle if abs(s.angle) < 1 else 0.0)
        else:
            _font(c, size)
            c.drawString(lx - 12, ly + 2, name)
            c.drawString(lx - 12, ly - size - 2, label2)
        tw = 70 / s.k
        occ.append((cx - 14 / s.k - 0.1, cy - (size + 4) / s.k, cx + tw, cy + (size + 6) / s.k))
        # light fixture
        lr = 2.6 * MM / s.k
        bw_, bh_ = box[2] - box[0], box[3] - box[1]
        spots = [
            (cx, box[3] - bh_ * 0.22),
            (cx, box[1] + bh_ * 0.22),
            (box[0] + bw_ * 0.22, cy),
            (box[2] - bw_ * 0.22, cy),
        ]
        for light_at in spots:
            lb = (light_at[0] - lr, light_at[1] - lr, light_at[0] + lr, light_at[1] + lr)
            if not any(_rects_overlap(lb, o) for o in occ) and _inside(lb, box):
                break
        if rng.random() < 0.85 and not any(_rects_overlap(lb, o) for o in occ) and _inside(lb, box):
            pts = _symbol(c, s, "light", s.P(*light_at), 0.0)
            counted.setdefault("light", []).append(s.tl(_bbox_centre(pts)))
            gt["symbol_radius"]["light"] = round(2.2 * MM, 2)
            occ.append(lb)
        # sockets on the clear faces
        n_sock = rng.randint(0, 3)
        for _ in range(n_sock * 3):
            if n_sock <= 0:
                break
            i = rng.randrange(len(poly))
            a, b = poly[i], poly[(i + 1) % len(poly)]
            if abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9:
                continue
            L = math.dist(a, b)
            if L < 1.0:
                continue
            f = rng.uniform(0.15, 0.85)
            q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = -uy, ux  # CCW ring: left normal points into the room
            off = 2.4 * MM / s.k
            ctr = (q[0] + nx * off, q[1] + ny * off)
            sb = (ctr[0] - off, ctr[1] - off, ctr[0] + off, ctr[1] + off)
            if any(_rects_overlap(sb, o) for o in occ) or _near_opening(plan, q, 0.4):
                continue
            pv = s.vec(nx, ny)
            rot = math.atan2(pv[1], pv[0]) - math.pi / 2
            pts = _symbol(c, s, "socket", s.P(*ctr), rot)
            counted.setdefault("socket", []).append(s.tl(_bbox_centre(pts)))
            gt["symbol_radius"]["socket"] = round(1.8 * MM, 2)
            occ.append(sb)
            n_sock -= 1
        # furniture
        _furniture(c, s, plan, rid, box, occ, gt)
    if not counted.get("light"):
        counted.pop("light", None)


def _inside(r: Rect, box: Rect, m: float = 0.15) -> bool:
    return r[0] >= box[0] + m and r[1] >= box[1] + m and r[2] <= box[2] - m and r[3] <= box[3] - m


def _near_opening(plan: Plan, q: Pt, d: float) -> bool:
    for op in plan.openings:
        kind, cc, _a, _b = op.key
        if kind == "h" and abs(q[1] - cc) < op.t and op.s0 - d < q[0] < op.s1 + d:
            return True
        if kind == "v" and abs(q[0] - cc) < op.t and op.s0 - d < q[1] < op.s1 + d:
            return True
    return False


def _furniture(c: Any, s: Sheet, plan: Plan, rid: int, box: Rect, occ: list[Rect], gt: dict[str, Any]) -> None:
    rng = s.rng
    c.setLineWidth(0.2)
    c.setStrokeGray(rng.choice([0.0, 0.3]))
    w, h = box[2] - box[0], box[3] - box[1]
    pick = rng.random()
    if pick < 0.3 and w > 3.2 and h > 3.0:
        # table with chairs (chairs are counted blocks)
        tw, td = 1.6, 0.9
        for _ in range(8):
            x0 = rng.uniform(box[0] + 0.8, box[2] - 0.8 - tw)
            y0 = rng.uniform(box[1] + 0.8, box[3] - 0.8 - td)
            r = (x0 - 0.6, y0 - 0.6, x0 + tw + 0.6, y0 + td + 0.6)
            if not any(_rects_overlap(r, o) for o in occ):
                break
        else:
            return
        _poly(c, s, [(x0, y0), (x0 + tw, y0), (x0 + tw, y0 + td), (x0, y0 + td)], stroke=1, fill=0)
        cs = 0.45
        spots = [(x0 + 0.2, y0 - 0.55, 0), (x0 + tw - 0.65, y0 - 0.55, 0)]
        spots += [(x0 + 0.2, y0 + td + 0.1, 2), (x0 + tw - 0.65, y0 + td + 0.1, 2)]
        for sx, sy, rot in spots:
            pts = [(sx, sy), (sx + cs, sy), (sx + cs, sy + cs), (sx, sy + cs)]
            _poly(c, s, pts, stroke=1, fill=0)
            back = (pts[0], pts[1]) if rot == 0 else (pts[3], pts[2])
            inset = 0.07 if rot == 0 else -0.07
            p = c.beginPath()
            p.moveTo(*s.P(back[0][0], back[0][1] + inset))
            p.lineTo(*s.P(back[1][0], back[1][1] + inset))
            c.drawPath(p, stroke=1, fill=0)
            centre = s.tl(_bbox_centre([s.P(*q) for q in pts]))
            gt["symbols"].setdefault("chair", []).append(centre)
            gt["symbol_radius"]["chair"] = round(0.3 * s.k, 2)
        occ.append(r)
    elif pick < 0.55 and w > 3.0 and h > 3.0:
        # bed or sofa: unique furniture, never counted
        bw, bd = rng.choice([(1.6, 2.0), (0.9, 2.0), (2.2, 0.9)])
        for _ in range(8):
            x0 = rng.uniform(box[0] + 0.2, box[2] - 0.2 - bw)
            y0 = rng.uniform(box[1] + 0.2, box[3] - 0.2 - bd)
            r = (x0, y0, x0 + bw, y0 + bd)
            if not any(_rects_overlap(r, o) for o in occ):
                break
        else:
            return
        _poly(c, s, [(x0, y0), (x0 + bw, y0), (x0 + bw, y0 + bd), (x0, y0 + bd)], stroke=1, fill=0)
        _poly(c, s, [(x0 + 0.1, y0 + bd - 0.5), (x0 + bw - 0.1, y0 + bd - 0.5), (x0 + bw - 0.1, y0 + bd - 0.1),
                     (x0 + 0.1, y0 + bd - 0.1)], stroke=1, fill=0)  # fmt: skip
        occ.append(r)
    elif pick < 0.7 and w > 2.4:
        # kitchen counter along the bottom clear face
        cw = min(w - 0.4, rng.uniform(1.8, 3.6))
        x0 = box[0] + 0.0
        r = (x0, box[1], x0 + cw, box[1] + 0.6)
        if any(_rects_overlap(r, o) for o in occ):
            return
        _poly(c, s, [(x0, box[1]), (x0 + cw, box[1]), (x0 + cw, box[1] + 0.6), (x0, box[1] + 0.6)], stroke=1, fill=0)
        occ.append(r)
    elif pick < 0.82 and w * h > 22:
        # free-standing columns (counted)
        for _ in range(rng.randint(1, 3)):
            q = (rng.uniform(box[0] + 1.0, box[2] - 1.0), rng.uniform(box[1] + 1.0, box[3] - 1.0))
            r = (q[0] - 0.3, q[1] - 0.3, q[0] + 0.3, q[1] + 0.3)
            if any(_rects_overlap(r, o) for o in occ):
                continue
            c.setFillGray(0.0)
            sq = [(q[0] - 0.15, q[1] - 0.15), (q[0] + 0.15, q[1] - 0.15), (q[0] + 0.15, q[1] + 0.15),
                  (q[0] - 0.15, q[1] + 0.15)]  # fmt: skip
            _poly(c, s, sq, stroke=0, fill=1)
            gt["symbols"].setdefault("column", []).append(s.tl(s.P(*q)))
            gt["symbol_radius"]["column"] = round(0.2 * s.k, 2)
            occ.append(r)


def _dimensions(c: Any, s: Sheet, plan: Plan) -> None:
    rng = s.rng
    xs = [p[0] for p in plan.outer_face]
    ys = [p[1] for p in plan.outer_face]
    x0, x1, y0 = min(xs), max(xs), min(ys)
    y_top = max(ys)
    off = 12 * MM / s.k
    gap = 2 * MM / s.k
    tick = rng.choice(["slash", "dot", "arrow"])
    c.setLineWidth(0.2)
    c.setStrokeGray(0)
    c.setFillGray(0)
    # bottom chain at interior wall centrelines that meet the south face
    cuts = sorted({x0, x1} | {k[1] for k in plan.walls if k[0] == "v" and abs(k[2] - 0.0) < 1e-6})
    cuts = [x0] + [v for v in cuts if x0 + 0.3 < v < x1 - 0.3] + [x1]
    for level, pts in ((1, cuts), (2, [x0, x1])):
        yd = y0 - off * level
        _seg(c, s, (pts[0] - 0.3 * off, yd), (pts[-1] + 0.3 * off, yd))
        for v in pts:
            _seg(c, s, (v, y0 - gap), (v, yd - gap))
            _tick(c, s, (v, yd), tick)
        for a, b in zip(pts, pts[1:], strict=False):
            txt = _dim_text(s, b - a)
            tp = s.P((a + b) / 2, yd + gap * 0.6)
            if s.shx:
                _shx_text(c, txt, tp[0] - 8, tp[1], 5.0, s.angle if abs(s.angle) < 1 else 0.0)
            else:
                _font(c, 5.5)
                c.drawCentredString(tp[0], tp[1], txt)
    # left chain
    yc = sorted({y0, y_top} | {k[1] for k in plan.walls if k[0] == "h" and abs(k[2] - 0.0) < 1e-6})
    yc = [y0] + [v for v in yc if y0 + 0.3 < v < y_top - 0.3] + [y_top]
    xd = x0 - off
    _seg(c, s, (xd, yc[0] - 0.3 * off), (xd, yc[-1] + 0.3 * off))
    for v in yc:
        _seg(c, s, (x0 - gap, v), (xd - gap, v))
        _tick(c, s, (xd, v), tick)


def _dim_text(s: Sheet, metres: float) -> str:
    if s.imperial:
        inches = metres / 0.0254
        return f"{int(inches // 12)}'-{int(round(inches % 12))}\""
    return s.rng.choice([f"{metres:.2f}", f"{metres * 100:.0f}", f"{metres * 1000:.0f}"])


def _seg(c: Any, s: Sheet, a: Pt, b: Pt) -> None:
    p = c.beginPath()
    p.moveTo(*s.P(*a))
    p.lineTo(*s.P(*b))
    c.drawPath(p, stroke=1, fill=0)


def _tick(c: Any, s: Sheet, at: Pt, kind: str) -> None:
    x, y = s.P(*at)
    r = 1.2 * MM
    if kind == "slash":
        c.setLineWidth(0.6)
        c.line(x - r * 0.7, y - r * 0.7, x + r * 0.7, y + r * 0.7)
        c.setLineWidth(0.2)
    elif kind == "dot":
        c.circle(x, y, 0.5 * MM, stroke=0, fill=1)
    else:
        p = c.beginPath()
        p.moveTo(x, y)
        p.lineTo(x - r, y + 0.35 * r)
        p.lineTo(x - r, y - 0.35 * r)
        p.close()
        c.drawPath(p, stroke=0, fill=1)


def _grid(c: Any, s: Sheet, plan: Plan) -> None:
    rng = s.rng
    xs = sorted({k[1] for k in plan.walls if k[0] == "v"})
    ys = [p[1] for p in plan.outer_face]
    lo, hi = min(ys) - 18 * MM / s.k, max(ys) + 18 * MM / s.k
    picks = [xs[0], xs[-1]] + rng.sample(xs[1:-1], k=min(2, max(0, len(xs) - 2)))
    exploded = rng.random() < 0.35
    c.setLineWidth(0.18)
    c.setStrokeGray(0.3)
    dash = [12.0, 3.0, 2.0, 3.0]
    for i, x in enumerate(sorted(picks)):
        a, b = s.P(x, lo), s.P(x, hi)
        if exploded:
            L = math.dist(a, b)
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
            t, k = 0.0, 0
            p = c.beginPath()
            while t < L:
                seg = dash[k % 4]
                if k % 2 == 0:
                    e = min(L, t + seg)
                    p.moveTo(a[0] + u[0] * t, a[1] + u[1] * t)
                    p.lineTo(a[0] + u[0] * e, a[1] + u[1] * e)
                t += seg
                k += 1
            c.drawPath(p, stroke=1, fill=0)
        else:
            c.setDash(dash, 0)
            c.line(*a, *b)
            c.setDash()
        for end in (a, b):
            bx, by = end[0], end[1]
            c.circle(bx, by, 4 * MM, stroke=1, fill=0)
            _font(c, 8)
            c.setFillGray(0)
            c.drawCentredString(bx, by - 3, "ABCDEFGH"[i])


def _scale_bar(c: Any, s: Sheet, x: float, y: float) -> None:
    seg = 1.0 * s.k
    for i in range(5):
        c.setFillGray(0 if i % 2 == 0 else 1)
        c.rect(x + i * seg, y, seg, 2 * MM, stroke=1, fill=1)
    _font(c, 5)
    c.setFillGray(0)
    c.drawString(x, y + 3 * MM, "0      1      2      3      4      5 m")


# ── scanned variant ───────────────────────────────────────────────────────────


def degrade_to_scan(pdf: bytes, seed: int, *, dpi: int = 150) -> tuple[bytes, Any, float]:
    """Rasterise a page, degrade it like a scan, embed it as the only page content.

    Returns the new PDF, a function moving page points along with the skew, and the skew in degrees.
    """
    import cv2
    import numpy as np
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    from app.core import pdf_reader

    rng = random.Random(seed * 31 + 5)
    with pdf_reader.open_pdf(pdf) as doc:
        page = doc[0]
        img = page.render(dpi=dpi)
        W, H = page.rect.width, page.rect.height
    arr = np.frombuffer(img.samples, dtype=np.uint8).reshape(img.height, img.width, 3)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY).astype(np.float32)
    h, w = gray.shape
    skew = rng.uniform(-1.5, 1.5)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), skew, 1.0)
    gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255.0)
    paper, ink = rng.uniform(215, 245), rng.uniform(15, 70)
    gray = ink + (gray / 255.0) * (paper - ink)
    # uneven illumination
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    gray += rng.uniform(-12, 12) * (xx / w - 0.5) + rng.uniform(-12, 12) * (yy / h - 0.5)
    gray = cv2.GaussianBlur(gray, (0, 0), rng.uniform(0.4, 1.1))
    nrng = np.random.default_rng(seed)
    gray += nrng.normal(0, rng.uniform(3, 12), gray.shape).astype(np.float32)
    specks = nrng.random(gray.shape) < rng.uniform(0.0, 0.0008)
    gray[specks] = ink
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, rng.randint(35, 80)])
    assert ok
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H), invariant=1)
    c.drawImage(ImageReader(io.BytesIO(jpg.tobytes())), 0, 0, W, H)
    c.showPage()
    c.save()

    px = dpi / 72.0

    def tf(p: list[float]) -> list[float]:
        x, y = p[0] * px, p[1] * px
        return [
            round((M[0, 0] * x + M[0, 1] * y + M[0, 2]) / px, 3),
            round((M[1, 0] * x + M[1, 1] * y + M[1, 2]) / px, 3),
        ]

    return buf.getvalue(), tf, skew


def make_scan(seed: int, *, dpi: int = 150, force_kind: str | None = None) -> tuple[bytes, dict[str, Any]]:
    """A generated page with its ground truth, degraded like a scan."""
    pdf, gt = make_page(seed, scan=True, force_kind=force_kind)
    scan, tf, skew = degrade_to_scan(pdf, seed, dpi=dpi)
    for room in gt["rooms"]:
        room["polygon"] = [tf(p) for p in room["polygon"]]
    for wall in gt["walls"]:
        wall["a"], wall["b"] = tf(wall["a"]), tf(wall["b"])
    gt["symbols"] = {k: [tf(p) for p in v] for k, v in gt["symbols"].items()}
    gt["variant"] = "scan"
    gt["scan"] = {"dpi": dpi, "skew_deg": round(skew, 3)}
    return scan, gt


def dump(out_dir: Path, split: str, n: int, *, scans: bool = True) -> None:
    """Write the corpus to disk (PDF + ground-truth JSON) for inspection."""
    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    for seed in split_seeds(split, n):
        for variant, fn in (("vector", make_page), ("scan", make_scan)):
            if variant == "scan" and not scans:
                continue
            pdf, gt = fn(seed)
            (out_dir / f"{split}-{seed}-{variant}.pdf").write_bytes(pdf)
            (out_dir / f"{split}-{seed}-{variant}.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1))
