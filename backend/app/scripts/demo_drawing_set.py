# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Author the demo architectural drawing set as a DXF.

A three-storey residential block (six apartments around a central stair core),
drawn the way an architect's set reads: eight A3 sheets laid out side by side in
model space, each with a frame and title block. Real dimensions in millimetres,
AIA layer names, room names with areas, door and window tags, grid, dimension
chains, section marks and a north arrow.

Sheets: A-001 site plan, A-101 ground floor, A-102 first floor, A-103 roof plan,
A-201 section A-A, A-301 south elevation, A-302 east elevation, A-501 schedule.

Everything is computed from one description of the building, so plan, section,
elevation and schedule agree. Geometry stays within what the DWG Takeoff viewer
draws (LINE, LWPOLYLINE, ARC, CIRCLE, TEXT, INSERT); dimensions and hatches are
drawn as explicit lines so they render without a DIMENSION/HATCH renderer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PROJECT_NAME = "Residential Block, 6 apartments"
PROJECT_NO = "OE-DEMO-2026-014"
SET_VERSION = 3  # bump when the drawing changes so seeded rows regenerate

# A3 sheet at 1:100 in model millimetres.
SHEET_W = 42000.0
SHEET_H = 29700.0
SHEET_GAP = 6000.0
TXT = 250.0  # 2.5 mm text at 1:100

EXT_T = 365.0
CORE_T = 240.0
PART_T = 115.0
FLOOR_H = 3000.0
SLAB_T = 220.0
STOREYS = 3
PARAPET = 600.0
W_SILL = 900.0
W_HEAD = 2250.0

LAYERS: dict[str, int] = {
    "A-ANNO-TTLB": 7,
    "A-ANNO-TEXT": 7,
    "A-ANNO-SYMB": 1,
    "A-AREA": 9,
    "A-AREA-GROS": 9,
    "A-GRID": 1,
    "A-WALL": 7,
    "A-WALL-PATT": 8,
    "A-WALL-PART": 7,
    "A-DOOR": 3,
    "A-GLAZ": 4,
    "A-FURN": 8,
    "A-FLOR-FIXT": 8,
    "A-STRS": 2,
    "A-DIMS": 2,
    "A-SECT": 7,
    "A-SECT-PATT": 8,
    "A-ELEV": 7,
    "A-ELEV-GLAZ": 4,
    "A-ROOF": 7,
    "A-BALC": 7,
    "C-BLDG": 7,
    "C-PROP": 1,
    "C-ROAD": 8,
    "C-PKNG": 8,
    "L-PLNT": 3,
}


# ── Building description (west flat; the east flat is its mirror at x=12000) ──


@dataclass(frozen=True)
class Wall:
    axis: str  # "h" runs along x at y=c, "v" runs along y at x=c
    c: float
    a: float  # start of the run (face to face)
    b: float
    t: float
    name: str
    layer: str = "A-WALL"


@dataclass(frozen=True)
class Opening:
    wall: str
    a: float
    b: float
    tag: str  # D1..D4 / W1..W4
    swing: int = 1  # doors: +1 swings to +normal side, -1 to the other
    hinge_at_a: bool = True


H_EXT = EXT_T / 2
WALLS_WEST: list[Wall] = [
    Wall("v", 10500, H_EXT, 12000 - H_EXT, CORE_T, "core_w"),
    Wall("h", 6500, H_EXT, 10500 - CORE_T / 2, CORE_T, "mid_w"),
    Wall("v", 6500, H_EXT, 6500 - CORE_T / 2, PART_T, "hall_w", "A-WALL-PART"),
    Wall("h", 3800, 6500 + PART_T / 2, 10500 - CORE_T / 2, PART_T, "kitchen_w", "A-WALL-PART"),
    Wall("v", 5000, 6500 + CORE_T / 2, 12000 - H_EXT, PART_T, "bed1_w", "A-WALL-PART"),
    Wall("v", 7500, 6500 + CORE_T / 2, 12000 - H_EXT, PART_T, "bath_w", "A-WALL-PART"),
]
WALLS_EXT: list[Wall] = [
    Wall("h", 0, -H_EXT, 24000 + H_EXT, EXT_T, "south"),
    Wall("h", 12000, -H_EXT, 24000 + H_EXT, EXT_T, "north"),
    Wall("v", 0, H_EXT, 12000 - H_EXT, EXT_T, "west"),
    Wall("v", 24000, H_EXT, 12000 - H_EXT, EXT_T, "east"),
]
OPEN_WEST: list[Opening] = [
    Opening("south", 1000, 2800, "W1"),
    Opening("south", 3700, 5500, "W1"),
    Opening("south", 7600, 9100, "W2"),
    Opening("north", 1900, 3400, "W2"),
    Opening("north", 5800, 6600, "W4"),
    Opening("north", 8250, 9750, "W2"),
    Opening("west", 2000, 3500, "W2"),
    Opening("west", 8500, 10000, "W2"),
    Opening("core_w", 4600, 5600, "D2", swing=-1),
    Opening("hall_w", 4800, 5700, "D3", swing=-1),
    Opening("kitchen_w", 8200, 9100, "D3", swing=-1),
    Opening("mid_w", 3700, 4600, "D3", swing=1, hinge_at_a=False),
    Opening("mid_w", 6600, 7400, "D4", swing=1),
    Opening("mid_w", 8600, 9500, "D3", swing=1, hinge_at_a=False),
]
OPEN_CORE_GROUND = Opening("south", 11400, 12600, "D1", swing=1)
OPEN_CORE_UPPER = Opening("south", 11400, 12600, "W3")
OPEN_CORE_STAIR = Opening("north", 11250, 12750, "W3")

TYPES: dict[str, tuple[str, float, float]] = {
    "D1": ("Entrance door, aluminium, glazed, double leaf", 1200, 2250),
    "D2": ("Apartment entrance door, fire rated EI30", 1000, 2125),
    "D3": ("Internal door, timber, flush", 900, 2125),
    "D4": ("Bathroom door, timber, with privacy lock", 800, 2125),
    "W1": ("Window, PVC, triple glazed, tilt and turn, 2 leaves", 1800, 1350),
    "W2": ("Window, PVC, triple glazed, tilt and turn", 1500, 1350),
    "W3": ("Stair window, fixed light", 1500, 1350),
    "W4": ("Bathroom window, obscured glass", 800, 900),
}

ROOMS_WEST: list[tuple[str, float, float, float, float]] = [
    ("LIVING / DINING", H_EXT, H_EXT, 6500 - PART_T / 2, 6500 - CORE_T / 2),
    ("KITCHEN", 6500 + PART_T / 2, H_EXT, 10500 - CORE_T / 2, 3800 - PART_T / 2),
    ("HALL", 6500 + PART_T / 2, 3800 + PART_T / 2, 10500 - CORE_T / 2, 6500 - CORE_T / 2),
    ("BEDROOM", H_EXT, 6500 + CORE_T / 2, 5000 - PART_T / 2, 12000 - H_EXT),
    ("BATHROOM", 5000 + PART_T / 2, 6500 + CORE_T / 2, 7500 - PART_T / 2, 12000 - H_EXT),
    ("BEDROOM", 7500 + PART_T / 2, 6500 + CORE_T / 2, 10500 - CORE_T / 2, 12000 - H_EXT),
]
CORE_ROOM = ("STAIR / LOBBY", 10500 + CORE_T / 2, H_EXT, 13500 - CORE_T / 2, 12000 - H_EXT)

GRID_X = [("1", 0.0), ("2", 10500.0), ("3", 13500.0), ("4", 24000.0)]
GRID_Y = [("A", 0.0), ("B", 6500.0), ("C", 12000.0)]


def _mx(x: float) -> float:
    return 24000.0 - x


def _mirror_wall(w: Wall) -> Wall:
    if w.axis == "v":
        return Wall("v", _mx(w.c), w.a, w.b, w.t, w.name + "_e", w.layer)
    return Wall("h", w.c, _mx(w.b), _mx(w.a), w.t, w.name + "_e", w.layer)


def _mirror_open(o: Opening) -> Opening:
    wall = {"west": "east", "south": "south", "north": "north"}.get(o.wall, o.wall + "_e")
    if wall in ("east",):
        return Opening(wall, o.a, o.b, o.tag, o.swing, o.hinge_at_a)
    if o.wall in ("core_w", "hall_w"):
        # Vertical walls mirror across x: positions along the wall (y) stay, the leaf swings the other way.
        return Opening(wall, o.a, o.b, o.tag, -o.swing, o.hinge_at_a)
    swing = o.swing
    return Opening(wall, _mx(o.b), _mx(o.a), o.tag, swing, not o.hinge_at_a)


def floor_walls() -> list[Wall]:
    return WALLS_EXT + WALLS_WEST + [_mirror_wall(w) for w in WALLS_WEST]


def floor_openings(level: int) -> list[Opening]:
    ops = OPEN_WEST + [_mirror_open(o) for o in OPEN_WEST]
    ops.append(OPEN_CORE_GROUND if level == 0 else OPEN_CORE_UPPER)
    ops.append(OPEN_CORE_STAIR)
    return ops


def floor_rooms() -> list[tuple[str, float, float, float, float]]:
    east = [(n, _mx(x1), y0, _mx(x0), y1) for n, x0, y0, x1, y1 in ROOMS_WEST]
    return ROOMS_WEST + east + [CORE_ROOM]


# ── Drawing helpers ───────────────────────────────────────────────────────


class Pen:
    """Thin wrapper that offsets everything by a sheet origin."""

    def __init__(self, msp: Any) -> None:
        self.msp = msp
        self.ox = 0.0
        self.oy = 0.0
        self.cm = 1.0  # coordinate multiplier, 2 only while the 1:200 site frame is drawn
        self.tm = 1.0  # annotation size multiplier, 2 on the 1:200 site content

    def at(self, ox: float, oy: float) -> Pen:
        self.ox, self.oy = ox, oy
        return self

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.cm + self.ox, y * self.cm + self.oy)

    def line(self, a: tuple[float, float], b: tuple[float, float], layer: str) -> None:
        self.msp.add_line(self.p(*a), self.p(*b), dxfattribs={"layer": layer})

    def poly(self, pts: Iterable[tuple[float, float]], layer: str, closed: bool = False) -> None:
        self.msp.add_lwpolyline([self.p(*q) for q in pts], close=closed, dxfattribs={"layer": layer})

    def rect(self, x0: float, y0: float, x1: float, y1: float, layer: str, closed: bool = True) -> None:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        self.poly(pts + ([] if closed else [(x0, y0)]), layer, closed)

    def circle(self, c: tuple[float, float], r: float, layer: str) -> None:
        self.msp.add_circle(self.p(*c), r * self.cm, dxfattribs={"layer": layer})

    def arc(self, c: tuple[float, float], r: float, a0: float, a1: float, layer: str) -> None:
        self.msp.add_arc(self.p(*c), r, a0, a1, dxfattribs={"layer": layer})

    def text(
        self, x: float, y: float, s: str, h: float = TXT, layer: str = "A-ANNO-TEXT", align: str = "L", rot: float = 0
    ) -> None:
        # The viewer places TEXT at its insert point, so alignment is resolved here.
        h *= self.cm * self.tm
        w = len(s) * h * 0.82
        dx = {"L": 0.0, "C": -w / 2, "R": -w}[align]
        if rot:
            r = math.radians(rot)
            x, y = x + dx * math.cos(r), y + dx * math.sin(r)
        else:
            x += dx
        self.msp.add_text(
            s, dxfattribs={"layer": layer, "height": h, "insert": self.p(x, y), "rotation": rot, "style": "OE_ARCH"}
        )

    def insert(self, block: str, x: float, y: float, sx: float = 1.0, sy: float = 1.0, rot: float = 0.0) -> None:
        self.msp.add_blockref(
            block, self.p(x, y), dxfattribs={"layer": "A-FURN", "xscale": sx, "yscale": sy, "rotation": rot}
        )

    def hatch_rect(self, x0: float, y0: float, x1: float, y1: float, layer: str, step: float = 150) -> None:
        """45-degree hatch lines clipped to an axis-aligned rectangle."""
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        k = x0 - (y1 - y0)
        while k < x1:
            # line y - y0 = x - k
            ax, bx = max(x0, k), min(x1, k + (y1 - y0))
            if bx - ax > 1:
                self.line((ax, y0 + ax - k), (bx, y0 + bx - k), layer)
            k += step

    def dim_h(self, x0: float, x1: float, y: float, ref_y: float, label: str | None = None) -> None:
        """Horizontal dimension with extension lines from ref_y and tick marks."""
        t = 100 * self.tm
        self.line((x0, y), (x1, y), "A-DIMS")
        for x in (x0, x1):
            d = 150 * self.tm if y > ref_y else -150 * self.tm
            self.line((x, ref_y + (d * 2 if y > ref_y else d * 2)), (x, y + d), "A-DIMS")
            self.line((x - t, y - t), (x + t, y + t), "A-DIMS")
        self.text((x0 + x1) / 2, y + 80 * self.tm, label or f"{round(abs(x1 - x0)):d}", 200, "A-DIMS", "C")

    def dim_v(self, y0: float, y1: float, x: float, ref_x: float, label: str | None = None) -> None:
        t = 100 * self.tm
        self.line((x, y0), (x, y1), "A-DIMS")
        for y in (y0, y1):
            d = 150 * self.tm if x > ref_x else -150 * self.tm
            self.line((ref_x + d * 2, y), (x + d, y), "A-DIMS")
            self.line((x - t, y - t), (x + t, y + t), "A-DIMS")
        self.text(x - 80 * self.tm, (y0 + y1) / 2, label or f"{round(abs(y1 - y0)):d}", 200, "A-DIMS", "C", rot=90)

    def chain_h(self, xs: list[float], y: float, ref_y: float) -> None:
        for a, b in zip(xs, xs[1:], strict=False):
            self.dim_h(a, b, y, ref_y)

    def chain_v(self, ys: list[float], x: float, ref_x: float) -> None:
        for a, b in zip(ys, ys[1:], strict=False):
            self.dim_v(a, b, x, ref_x)

    def bubble(self, x: float, y: float, label: str, r: float = 400) -> None:
        self.circle((x, y), r, "A-GRID")
        self.text(x, y - r * 0.4, label, r * 0.8, "A-GRID", "C")

    def level(self, x: float, y: float, label: str) -> None:
        """Level marker: triangle on the line plus the level text."""
        self.poly([(x - 200, y + 300), (x + 200, y + 300), (x, y), (x - 200, y + 300)], "A-ANNO-SYMB")
        self.line((x - 600, y), (x + 1800, y), "A-ANNO-SYMB")
        self.text(x + 300, y + 100, label, 220, "A-ANNO-SYMB")


def _blocks(doc: Any) -> None:
    def blk(name: str) -> Any:
        return doc.blocks.new(name=name)

    b = blk("FURN_BED_DOUBLE")  # 1600 x 2000, head at y=2000
    b.add_lwpolyline([(0, 0), (1600, 0), (1600, 2000), (0, 2000)], close=True)
    b.add_lwpolyline([(0, 1550), (1600, 1550)])
    for x in (100, 850):
        b.add_lwpolyline([(x, 1620), (x + 650, 1620), (x + 650, 1930), (x, 1930)], close=True)
    b.add_line((0, 1550), (1600, 900))
    b = blk("FURN_BED_SINGLE")  # 900 x 2000
    b.add_lwpolyline([(0, 0), (900, 0), (900, 2000), (0, 2000)], close=True)
    b.add_lwpolyline([(100, 1620), (800, 1620), (800, 1930), (100, 1930)], close=True)
    b.add_line((0, 1550), (900, 1550))
    b = blk("FURN_WARDROBE")  # 1800 x 600
    b.add_lwpolyline([(0, 0), (1800, 0), (1800, 600), (0, 600)], close=True)
    b.add_line((900, 0), (900, 600))
    b.add_line((0, 0), (900, 600))
    b.add_line((900, 0), (1800, 600))
    b = blk("FURN_SOFA")  # 2200 x 900, back at y=900
    b.add_lwpolyline([(0, 0), (2200, 0), (2200, 900), (0, 900)], close=True)
    b.add_lwpolyline([(200, 0), (200, 700), (2000, 700), (2000, 0)])
    b.add_line((1100, 0), (1100, 700))
    b = blk("FURN_TABLE_6")  # 1800 x 900 plus chairs
    b.add_lwpolyline([(0, 0), (1800, 0), (1800, 900), (0, 900)], close=True)
    for x in (150, 750, 1350):
        b.add_lwpolyline([(x, -500), (x + 450, -500), (x + 450, -80), (x, -80)], close=True)
        b.add_lwpolyline([(x, 980), (x + 450, 980), (x + 450, 1400), (x, 1400)], close=True)
    b = blk("FURN_KITCHEN_RUN")  # 3200 x 600 with sink and hob
    b.add_lwpolyline([(0, 0), (3200, 0), (3200, 600), (0, 600)], close=True)
    b.add_lwpolyline([(400, 100), (1200, 100), (1200, 500), (400, 500)], close=True)
    b.add_circle((800, 300), 60)
    for cx, cy in ((2050, 180), (2450, 180), (2050, 420), (2450, 420)):
        b.add_circle((cx, cy), 120)
    b.add_lwpolyline([(1700, 0), (1700, 600)])
    b.add_lwpolyline([(2800, 0), (2800, 600)])
    b = blk("FIXT_WC")  # 400 x 700, cistern at y=700
    b.add_lwpolyline([(0, 520), (400, 520), (400, 700), (0, 700)], close=True)
    b.add_arc((200, 300), 200, 180, 360)
    b.add_line((0, 300), (0, 520))
    b.add_line((400, 300), (400, 520))
    b.add_arc((200, 300), 140, 180, 360)
    b = blk("FIXT_BASIN")  # 600 x 450, wall at y=450
    b.add_lwpolyline([(0, 0), (600, 0), (600, 450), (0, 450)], close=True)
    b.add_circle((300, 200), 150)
    b = blk("FIXT_BATH")  # 1700 x 750
    b.add_lwpolyline([(0, 0), (1700, 0), (1700, 750), (0, 750)], close=True)
    b.add_lwpolyline([(80, 80), (1620, 80), (1620, 670), (80, 670)], close=True)
    b.add_circle((1500, 375), 40)
    b = blk("FIXT_WASHER")  # 600 x 600
    b.add_lwpolyline([(0, 0), (600, 0), (600, 600), (0, 600)], close=True)
    b.add_circle((300, 300), 220)
    b = blk("LAND_TREE")  # r=3000 at 1:1, inserted scaled
    b.add_circle((0, 0), 3000)
    for i in range(12):
        a = math.radians(i * 30)
        b.add_line((math.cos(a) * 600, math.sin(a) * 600), (math.cos(a) * 2700, math.sin(a) * 2700))
    b.add_circle((0, 0), 250)
    b = blk("SYMB_NORTH")  # r=900
    b.add_circle((0, 0), 900)
    b.add_lwpolyline([(0, 1100), (450, -650), (0, -300), (-450, -650)], close=True)
    b.add_line((0, -300), (0, 1100))
    b.add_text("N", dxfattribs={"height": 450, "insert": (-180, 1250)})


# ── Plan ──────────────────────────────────────────────────────────────────


def _wall_pieces(w: Wall, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces, pos = [], w.a
    for a, b in sorted(cuts):
        if a > pos:
            pieces.append((pos, a))
        pos = max(pos, b)
    if w.b > pos:
        pieces.append((pos, w.b))
    return pieces


def _wall_rect(w: Wall, a: float, b: float) -> tuple[float, float, float, float]:
    h = w.t / 2
    return (a, w.c - h, b, w.c + h) if w.axis == "h" else (w.c - h, a, w.c + h, b)


def _draw_plan(pen: Pen, level: int) -> None:
    walls = {w.name: w for w in floor_walls()}
    ops = floor_openings(level)
    for w in walls.values():
        cuts = [(o.a, o.b) for o in ops if o.wall == w.name]
        for a, b in _wall_pieces(w, cuts):
            x0, y0, x1, y1 = _wall_rect(w, a, b)
            pen.rect(x0, y0, x1, y1, w.layer)
            if w.t >= CORE_T:
                pen.hatch_rect(x0, y0, x1, y1, "A-WALL-PATT", 160)

    for o in ops:
        w = walls[o.wall]
        x0, y0, x1, y1 = _wall_rect(w, o.a, o.b)
        horiz = w.axis == "h"
        if o.tag.startswith("W"):
            # frame lines at both faces, glazing as a double line on the centre
            for off in (-w.t / 2, -20, 20, w.t / 2):
                if horiz:
                    pen.line((o.a, w.c + off), (o.b, w.c + off), "A-GLAZ")
                else:
                    pen.line((w.c + off, o.a), (w.c + off, o.b), "A-GLAZ")
            for e in (o.a, o.b):
                if horiz:
                    pen.line((e, y0), (e, y1), "A-GLAZ")
                else:
                    pen.line((x0, e), (x1, e), "A-GLAZ")
        else:
            width = o.b - o.a
            for e in (o.a, o.b):
                if horiz:
                    pen.line((e, y0), (e, y1), "A-DOOR")
                else:
                    pen.line((x0, e), (x1, e), "A-DOOR")
            face = w.c + o.swing * w.t / 2
            hinge = o.a if o.hinge_at_a else o.b
            sgn = 1 if o.hinge_at_a else -1
            leaves = [(hinge, width, sgn)] if o.tag != "D1" else [(o.a, width / 2, 1), (o.b, width / 2, -1)]
            for hp, leaf, s in leaves:
                if horiz:
                    hpt = (hp, face)
                    tip = (hp, face + o.swing * leaf)
                    a_close = 0 if s > 0 else 180
                    a_open = 90 if o.swing > 0 else 270
                else:
                    hpt = (face, hp)
                    tip = (face + o.swing * leaf, hp)
                    a_close = 90 if s > 0 else 270
                    a_open = 0 if o.swing > 0 else 180
                pen.line(hpt, tip, "A-DOOR")
                lo, hi = sorted((a_close, a_open))
                if hi - lo > 180:
                    lo, hi = hi, lo
                pen.arc(hpt, leaf, lo, hi, "A-DOOR")
        # tag on the outside / swing-free side
        mid = (o.a + o.b) / 2
        off = (w.t / 2 + 650) * (-1 if w.name in ("south", "west") else 1)
        if not o.tag.startswith("W"):
            off = -o.swing * (w.t / 2 + 400)
        tx, ty = (mid, w.c + off) if horiz else (w.c + off, mid)
        if o.tag.startswith("W"):
            pen.poly(
                [(tx - 330, ty - 220), (tx + 330, ty - 220), (tx + 330, ty + 220), (tx - 330, ty + 220)],
                "A-ANNO-SYMB",
                True,
            )
        else:
            pen.circle((tx, ty), 300, "A-ANNO-SYMB")
        pen.text(tx, ty - 90, o.tag, 180, "A-ANNO-SYMB", "C")

    # Rooms: boundary for takeoff, name, number, area.
    for i, (name, x0, y0, x1, y1) in enumerate(floor_rooms(), start=1):
        area = (x1 - x0) * (y1 - y0) / 1e6
        pen.rect(x0 + 30, y0 + 30, x1 - 30, y1 - 30, "A-AREA")
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if name == "STAIR / LOBBY":
            cy = 3200
        pen.text(cx, cy + 250, name, 220, "A-ANNO-TEXT", "C")
        pen.text(cx, cy - 50, f"{level}.{i:02d}", 200, "A-ANNO-TEXT", "C")
        pen.text(cx, cy - 350, f"{area:.2f} m2", 200, "A-ANNO-TEXT", "C")
        pen.text(cx, cy - 650, "FFL " + _lvl(level * FLOOR_H), 170, "A-ANNO-TEXT", "C")

    # Furniture, west flat then mirrored east.
    for sx, fx in ((1, lambda x: x), (-1, _mx)):
        pen.insert("FURN_SOFA", fx(800), 4800, sx, 1)
        pen.insert("FURN_TABLE_6", fx(1300), 1500, sx, 1)
        pen.insert("FURN_KITCHEN_RUN", fx(6800), H_EXT, sx, 1)
        pen.insert("FURN_BED_DOUBLE", fx(1600), 9700, sx, 1)
        pen.insert("FURN_WARDROBE", fx(2300), 6620, sx, 1)
        pen.insert("FURN_BED_SINGLE", fx(9200), 9600, sx, 1)
        pen.insert("FURN_WARDROBE", fx(7700), 11817.5, sx, -1)
        pen.insert("FIXT_BATH", fx(5110), 11000, sx, 1)
        pen.insert("FIXT_WC", fx(6850), 11817.5 - 700, sx, 1)
        pen.insert("FIXT_BASIN", fx(5250), 8000, sx, 1, rot=0)
        pen.insert("FIXT_WASHER", fx(5120), 6720, sx, 1)
    _draw_stair(pen, level)
    # Balconies on upper floors, outside the living rooms.
    if level > 0:
        for x0, x1 in ((600, 5600), (_mx(5600), _mx(600))):
            pen.rect(x0, -H_EXT - 1600, x1, -H_EXT, "A-BALC", closed=False)
            pen.line((x0 + 50, -H_EXT - 1550), (x1 - 50, -H_EXT - 1550), "A-BALC")

    # Grid
    for lab, x in GRID_X:
        pen.line((x, -4200), (x, 12000 + 3000), "A-GRID")
        pen.bubble(x, -4600, lab)
        pen.bubble(x, 12000 + 3400, lab)
    for lab, y in GRID_Y:
        pen.line((-4000, y), (24000 + 3000, y), "A-GRID")
        pen.bubble(-4400, y, lab)
        pen.bubble(24000 + 3400, y, lab)

    # Dimension chains
    south = [o for o in ops if o.wall == "south"]
    xs = [-H_EXT] + sorted({v for o in south for v in (o.a, o.b)}) + [24000 + H_EXT]
    pen.chain_h(xs, -2000, -H_EXT)
    pen.chain_h([-H_EXT] + [x for _, x in GRID_X[1:-1]] + [24000 + H_EXT], -2800, -H_EXT)
    pen.dim_h(-H_EXT, 24000 + H_EXT, -3600, -H_EXT)
    west = [o for o in ops if o.wall == "west"]
    ys = [-H_EXT] + sorted({v for o in west for v in (o.a, o.b)}) + [12000 + H_EXT]
    pen.chain_v(ys, -2000, -H_EXT)
    pen.dim_v(-H_EXT, 12000 + H_EXT, -2900, -H_EXT)
    # Section mark A-A through the living room and bedroom.
    for y, flip in ((-4300, 1), (15300, -1)):
        pen.line((3000, y), (3000, y + 900 * flip), "A-ANNO-SYMB")
        pen.circle((3000, y - 450 * flip), 450, "A-ANNO-SYMB")
        pen.text(3000, y - 450 * flip - 110, "A", 280, "A-ANNO-SYMB", "C")
        pen.poly([(3000, y - 900 * flip), (3600, y - 450 * flip), (3000, y)], "A-ANNO-SYMB")


def _draw_stair(pen: Pen, level: int) -> None:
    x0, x1 = 10500 + CORE_T / 2, 13500 - CORE_T / 2
    mid = (x0 + x1) / 2
    y_start, tread, n = 6200, 260, 17
    y_end = y_start + tread * (n // 2 + 1)
    gap = 120
    for xa, xb in ((x0, mid - gap), (mid + gap, x1)):
        for i in range(n // 2 + 2):
            y = y_start + i * tread
            pen.line((xa, y), (xb, y), "A-STRS")
    pen.rect(mid - gap, y_start, mid + gap, y_end, "A-STRS", closed=False)
    pen.line((x0, y_end), (x1, y_end), "A-STRS")
    # walking line and arrow
    pen.poly(
        [
            ((x0 + mid) / 2, y_start + 100),
            ((x0 + mid) / 2, y_end + 600),
            ((mid + x1) / 2, y_end + 600),
            ((mid + x1) / 2, y_start + 100),
        ],
        "A-STRS",
    )
    ax = (x0 + mid) / 2 if level < STOREYS - 1 else (mid + x1) / 2
    pen.poly([(ax - 120, y_end - 300), (ax, y_end - 80), (ax + 120, y_end - 300)], "A-STRS")
    pen.text(mid, y_start - 350, f"{n} x 176/{tread}", 170, "A-STRS", "C")
    if level < STOREYS - 1:
        pen.line((x0, y_start + 1700), (mid - gap, y_start + 2300), "A-STRS")


def _lvl(mm: float) -> str:
    v = mm / 1000
    return "+/-0.00" if abs(v) < 1e-9 else f"{v:+.2f}"


# ── Sheets ────────────────────────────────────────────────────────────────


def _frame(pen: Pen, number: str, title: str, scale: str, k: float = 1.0) -> None:
    pen.cm = k
    try:
        _frame_1x(pen, number, title, scale)
    finally:
        pen.cm = 1.0


def _frame_1x(pen: Pen, number: str, title: str, scale: str) -> None:
    layer = "A-ANNO-TTLB"
    pen.rect(0, 0, SHEET_W, SHEET_H, layer, closed=False)
    pen.rect(2000, 1000, SHEET_W - 1000, SHEET_H - 1000, layer, closed=False)
    tx0, ty1 = SHEET_W - 1000 - 17000, 6600
    tx1 = SHEET_W - 1000
    pen.rect(tx0, 1000, tx1, ty1, layer, closed=False)
    for y in (3000, 4300, 5500):
        pen.line((tx0, y), (tx1, y), layer)
    pen.line((tx0 + 8000, 1000), (tx0 + 8000, 3000), layer)
    pen.line((tx0 + 12500, 1000), (tx0 + 12500, 3000), layer)
    pen.text(tx0 + 250, 5850, f"OpenConstructionERP demo  |  Project no. {PROJECT_NO}", 230, layer)
    pen.text(tx0 + 250, 4700, f"Project: {PROJECT_NAME}", 280, layer)
    pen.text(tx0 + 250, 3420, title.upper(), 440, layer)
    pen.text(tx0 + 250, 2400, "Scale", 180, layer)
    pen.text(tx0 + 250, 1400, scale + "  (A3)", 380, layer)
    pen.text(tx0 + 8250, 2400, "Date / Rev", 180, layer)
    pen.text(tx0 + 8250, 1400, "2026-11  C", 330, layer)
    pen.text(tx0 + 12750, 2400, "Sheet", 180, layer)
    pen.text(tx0 + 12750, 1300, number, 600, layer)
    pen.text(
        tx0 + 300, ty1 + 300, "All dimensions in millimetres. Levels in metres above FFL ground floor.", 200, layer
    )


def _sheet_plan(pen: Pen, level: int) -> None:
    ox, oy = 6500, 12000
    pen.at(pen.ox + ox, pen.oy + oy)
    _draw_plan(pen, level)
    pen.text(0, -6200, f"{['GROUND', 'TYPICAL UPPER (1st/2nd)'][level]} FLOOR PLAN   1:100", 500, "A-ANNO-TEXT")
    pen.insert("SYMB_NORTH", 31000, 13000)
    if level == 0:
        pen.poly(
            [(-H_EXT, -H_EXT), (24000 + H_EXT, -H_EXT), (24000 + H_EXT, 12000 + H_EXT), (-H_EXT, 12000 + H_EXT)],
            "A-AREA-GROS",
            True,
        )
        gfa = (24000 + EXT_T) * (12000 + EXT_T) / 1e6
        pen.text(
            0,
            -7000,
            f"Gross floor area per storey {gfa:.1f} m2   Storeys {STOREYS}   GFA total {gfa * STOREYS:.1f} m2",
            260,
        )
    pen.at(pen.ox - ox, pen.oy - oy)


def _sheet_roof(pen: Pen) -> None:
    ox, oy = 6500, 12000
    pen.at(pen.ox + ox, pen.oy + oy)
    a, b = -H_EXT, 24000 + H_EXT
    c, d = -H_EXT, 12000 + H_EXT
    pen.rect(a, c, b, d, "A-ROOF")
    pen.rect(a + 300, c + 300, b - 300, d - 300, "A-ROOF")
    pen.hatch_rect(a, c, a + 300, d, "A-WALL-PATT", 120)
    # falls to two outlets
    for ox2 in (6000, 18000):
        pen.circle((ox2, 6000), 200, "A-ROOF")
        pen.circle((ox2, 6000), 80, "A-ROOF")
        for tx, ty in ((ox2 - 4500, 6000), (ox2 + 4500, 6000), (ox2, 2000), (ox2, 10000)):
            pen.line((tx, ty), (ox2 + (tx - ox2) * 0.15, 6000 + (ty - 6000) * 0.15), "A-ROOF")
        pen.text(ox2 - 2500, 6200, "2 %", 220, "A-ANNO-TEXT")
        pen.text(ox2 + 300, 5500, "RO DN100", 180, "A-ANNO-TEXT")
    pen.line((12000, c + 300), (12000, d - 300), "A-ROOF")
    pen.rect(10800, 8400, 13200, 10800, "A-ROOF")
    pen.line((10800, 8400), (13200, 10800), "A-ROOF")
    pen.line((10800, 10800), (13200, 8400), "A-ROOF")
    pen.text(12000, 7800, "ROOF HATCH 1000x1000", 200, "A-ANNO-TEXT", "C")
    pen.text(12000, 3000, "FLAT ROOF, GRAVEL ON TPO MEMBRANE, PIR 200 mm", 260, "A-ANNO-TEXT", "C")
    pen.text(12000, 2500, f"TOP OF PARAPET {_lvl(STOREYS * FLOOR_H + PARAPET)}", 220, "A-ANNO-TEXT", "C")
    for lab, x in GRID_X:
        pen.line((x, -2500), (x, 12000 + 1500), "A-GRID")
        pen.bubble(x, -2900, lab)
    pen.dim_h(a, b, -1600, c)
    pen.dim_v(c, d, -1600, a)
    pen.text(0, -6200, "ROOF PLAN   1:100", 500, "A-ANNO-TEXT")
    pen.insert("SYMB_NORTH", 31000, 13000)
    pen.at(pen.ox - ox, pen.oy - oy)


def _sheet_site(pen: Pen) -> None:
    # True model millimetres. The A3 frame is drawn at 1:200 (twice the 1:100 size, see _frame),
    # and annotation sizes double with it, so takeoff on this sheet measures real distances.
    s = 1.0
    ox, oy = 10000, 21000
    pen.tm = 2.0

    def q(x: float, y: float) -> tuple[float, float]:
        return (ox + x * s, oy + y * s)

    plot = [(0, 0), (44000, 0), (44000, 32000), (6000, 35000), (0, 30000), (0, 0)]
    pen.poly([q(*p) for p in plot], "C-PROP")
    for x, y in plot[:-1]:
        pen.circle(q(x, y), 240, "C-PROP")
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(plot, plot[1:], strict=False))) / 2e6
    pen.poly([q(-6000, -1500), q(36000, -1500)], "C-ROAD")
    pen.poly([q(-6000, -3000), q(36000, -3000)], "C-ROAD")
    pen.poly([q(-6000, -10000), q(36000, -10000)], "C-ROAD")
    pen.text(*q(14000, -7000), "RESIDENTIAL STREET", 300, "C-ROAD")
    bx, by = 10000, 9000  # building placement on the plot (outer faces)
    pen.poly([q(bx, by), q(bx + 24365, by), q(bx + 24365, by + 12365), q(bx, by + 12365), q(bx, by)], "C-BLDG")
    pen.hatch_rect(*q(bx, by), *q(bx + 24365, by + 12365), "A-WALL-PATT", 300)
    pen.text(*q(bx + 12182, by + 6800), "RESIDENTIAL BLOCK, 3 STOREYS, FLAT ROOF", 260, align="C")
    pen.text(*q(bx + 12182, by + 4800), "FFL +/-0.00 = 212.35 m ASL", 220, align="C")
    # entrance path and parking
    pen.poly([q(bx + 11400, -1500), q(bx + 11400, by), q(bx + 12600, by), q(bx + 12600, -1500)], "C-PKNG")
    for i in range(7):
        x = 2500 + i * 2500
        pen.poly([q(x, 1000), q(x, 6000)], "C-PKNG")
    pen.poly([q(2500, 6000), q(17500, 6000)], "C-PKNG")
    pen.text(*q(10000, 3200), "6 PARKING SPACES 2500 x 5000", 200, "C-PKNG", "C")
    for tx, ty in ((4000, 16000), (5000, 26000), (38000, 28000), (40000, 5000), (24000, 29000), (40000, 16000)):
        pen.insert("LAND_TREE", *q(tx, ty), s * 0.8, s * 0.8)
    pen.dim_h(ox, ox + bx * s, oy + (by + 15000) * s, oy + (by + 12365) * s, "10000")
    pen.dim_v(oy, oy + by * s, ox + (bx + 26500) * s, ox + (bx + 24365) * s, "9000")
    pen.dim_h(ox, ox + 44000 * s, oy - 4400, oy - 1500, "44000")
    pen.text(*q(16000, 29500), f"PLOT 1187/4   AREA {area:.0f} m2", 260, "C-PROP")
    pen.insert("SYMB_NORTH", 72000, 48000, 2.0, 2.0)
    pen.text(ox, 4400, "SITE PLAN   1:200", 500, "A-ANNO-TEXT")
    pen.tm = 1.0


def _section_frame(pen: Pen) -> None:
    ox, oy = 12000, 9000
    pen.at(pen.ox + ox, pen.oy + oy)
    ys = [0, 6500, 12000]  # wall axes along the cut (plan y)
    ts = [EXT_T, CORE_T, EXT_T]
    top = STOREYS * FLOOR_H
    pen.line((-6000, -150), (18000, -150), "A-SECT")
    pen.hatch_rect(-6000, -900, 18000, -150, "A-SECT-PATT", 400)
    for y, t in zip(ys, ts, strict=False):
        pen.rect(y - 400, -SLAB_T - 700, y + 400, -SLAB_T, "A-SECT")  # strip footing
        pen.hatch_rect(y - 400, -SLAB_T - 700, y + 400, -SLAB_T, "A-SECT-PATT", 120)
    for k in range(STOREYS + 1):
        z = k * FLOOR_H
        pen.rect(-H_EXT, z - SLAB_T, 12000 + H_EXT, z, "A-SECT")
        pen.hatch_rect(-H_EXT, z - SLAB_T, 12000 + H_EXT, z, "A-SECT-PATT", 120)
        if k < STOREYS:
            pen.level(-3500, z, _lvl(z))
            for b0, b1 in ((-H_EXT - 1600, -H_EXT),) if k > 0 else ():
                pen.rect(b0, z - 180, b1, z, "A-BALC")
                pen.line((b0, z), (b0, z + 1000), "A-BALC")
                pen.line((b0, z + 1000), (b1, z + 1000), "A-BALC")
    pen.level(-3500, top, _lvl(top) + " ROOF")
    pen.level(-3500, top + PARAPET, _lvl(top + PARAPET))
    for k in range(STOREYS):
        z0, z1 = k * FLOOR_H, (k + 1) * FLOOR_H - SLAB_T
        for y, t in zip(ys, ts, strict=False):
            if t == EXT_T:
                # cut window in the facade wall: sill to head
                pen.rect(y - t / 2, z0, y + t / 2, z0 + W_SILL, "A-SECT")
                pen.rect(y - t / 2, z0 + W_HEAD, y + t / 2, z1, "A-SECT")
                pen.hatch_rect(y - t / 2, z0, y + t / 2, z0 + W_SILL, "A-SECT-PATT", 120)
                pen.hatch_rect(y - t / 2, z0 + W_HEAD, y + t / 2, z1, "A-SECT-PATT", 120)
                pen.line((y - 20, z0 + W_SILL), (y - 20, z0 + W_HEAD), "A-ELEV-GLAZ")
                pen.line((y + 20, z0 + W_SILL), (y + 20, z0 + W_HEAD), "A-ELEV-GLAZ")
            else:
                pen.rect(y - t / 2, z0, y + t / 2, z1, "A-SECT")
                pen.hatch_rect(y - t / 2, z0, y + t / 2, z1, "A-SECT-PATT", 120)
        pen.text(3200, z0 + 1300, "LIVING / DINING", 240, "A-ANNO-TEXT", "C")
        pen.text(9250, z0 + 1300, "BEDROOM", 240, "A-ANNO-TEXT", "C")
        pen.dim_v(z0, z0 + FLOOR_H, 14500, 12000 + H_EXT)
        pen.dim_v(z0 + W_SILL, z0 + W_HEAD, 13500, 12000 + H_EXT)
    for y in (-H_EXT, 12000 + H_EXT - 240):
        pen.rect(y, top, y + 240, top + PARAPET, "A-SECT")
    pen.text(
        6000, top + 250, "ROOF BUILD-UP: GRAVEL 50, TPO, PIR 200, VAPOUR BARRIER, RC SLAB 220", 200, "A-ANNO-TEXT", "C"
    )
    for lab, y in GRID_Y:
        pen.line((y, -1800), (y, top + 1600), "A-GRID")
        pen.bubble(y, -2200, lab)
    pen.chain_h([-H_EXT, 6500, 12000 + H_EXT], -3300, -900)
    pen.dim_v(-150, top + PARAPET, 15500, 12000 + H_EXT)
    pen.text(-6000, -5200, "SECTION A-A   1:100", 500, "A-ANNO-TEXT")
    pen.at(pen.ox - ox, pen.oy - oy)


def _elevation(pen: Pen, face: str) -> None:
    ox, oy = 6500, 11000
    pen.at(pen.ox + ox, pen.oy + oy)
    top = STOREYS * FLOOR_H + PARAPET
    if face == "south":
        width, x_of = 24000 + EXT_T, (lambda x: x + H_EXT)
        wall = "south"
    else:
        width, x_of = 12000 + EXT_T, (lambda y: y + H_EXT)
        wall = "east"
    pen.line((-4000, -150), (width + 4000, -150), "A-ELEV")
    pen.line((-4000, -200), (width + 4000, -200), "A-ELEV")
    pen.rect(0, -150, width, top, "A-ELEV")
    pen.line((0, top - 80), (width, top - 80), "A-ELEV")
    pen.line((0, 0), (width, 0), "A-ELEV")
    for k in range(STOREYS):
        z = k * FLOOR_H
        ops = [o for o in floor_openings(k) if o.wall == wall]
        for o in ops:
            name, w, h = TYPES[o.tag]
            a, b = x_of(o.a), x_of(o.b)
            if o.tag.startswith("D"):
                z0, z1 = z, z + h
            else:
                z1 = z + W_HEAD
                z0 = z1 - h
            pen.rect(a, z0, b, z1, "A-ELEV")
            pen.rect(a + 60, z0 + 60, b - 60, z1 - 60, "A-ELEV-GLAZ")
            if o.tag in ("W1", "D1"):
                pen.line(((a + b) / 2, z0 + 60), ((a + b) / 2, z1 - 60), "A-ELEV-GLAZ")
            if o.tag.startswith("W"):
                pen.rect(a - 40, z0 - 60, b + 40, z0, "A-ELEV")
                # opening-sash triangle, apex at hinge side
                pen.poly([(a + 60, z0 + 60), ((a + b) / 2, z1 - 60), (b - 60, z0 + 60)], "A-ELEV-GLAZ")
        if face == "south" and k > 0:
            for x0, x1 in ((600, 5600), (_mx(5600), _mx(600))):
                a, b = x_of(x0), x_of(x1)
                pen.rect(a, z - 180, b, z, "A-BALC")
                pen.rect(a, z, b, z + 1000, "A-BALC")
                for i in range(1, 25):
                    x = a + (b - a) * i / 25
                    pen.line((x, z), (x, z + 1000), "A-BALC")
        pen.level(width + 1200, z, _lvl(z))
    pen.level(width + 1200, top, _lvl(top))
    if face == "south":
        pen.text(x_of(12000), FLOOR_H - 600, "No. 14", 300, "A-ELEV", "C")
        for lab, x in GRID_X:
            pen.line((x_of(x), top + 600), (x_of(x), top + 2000), "A-GRID")
            pen.bubble(x_of(x), top + 2400, lab)
    else:
        for lab, y in GRID_Y:
            pen.line((x_of(y), top + 600), (x_of(y), top + 2000), "A-GRID")
            pen.bubble(x_of(y), top + 2400, lab)
    pen.text(
        width * 0.5, top - 900, "RENDER ON ETICS 160 mm, WHITE  |  PLINTH: FIBRE CEMENT, GREY", 220, "A-ANNO-TEXT", "C"
    )
    pen.dim_h(0, width, -1600, -200)
    pen.dim_v(-150, top, -1500, 0)
    pen.text(0, -3600, f"{face.upper()} ELEVATION   1:100", 500, "A-ANNO-TEXT")
    pen.at(pen.ox - ox, pen.oy - oy)


def opening_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for k in range(STOREYS):
        for o in floor_openings(k):
            counts[o.tag] = counts.get(o.tag, 0) + 1
    return counts


def _schedule(pen: Pen) -> None:
    x0, y_top = 4000, 26000
    cols = [0, 2200, 18000, 21500, 25000, 28500]
    heads = ["TAG", "DESCRIPTION", "WIDTH", "HEIGHT", "COUNT"]
    counts = opening_counts()
    rows = sorted(TYPES)
    rh = 1100
    y_bot = y_top - rh * (len(rows) + 1)
    pen.rect(x0, y_bot, x0 + cols[-1], y_top, "A-ANNO-TTLB", closed=False)
    for c in cols[1:-1]:
        pen.line((x0 + c, y_bot), (x0 + c, y_top), "A-ANNO-TTLB")
    for i in range(1, len(rows) + 1):
        pen.line((x0, y_top - i * rh), (x0 + cols[-1], y_top - i * rh), "A-ANNO-TTLB")
    for c, h in zip(cols, heads, strict=False):
        pen.text(x0 + c + 250, y_top - rh + 380, h, 300, "A-ANNO-TTLB")
    for i, tag in enumerate(rows, start=2):
        desc, w, h = TYPES[tag]
        y = y_top - i * rh + 380
        vals = [tag, desc, f"{w:.0f}", f"{h:.0f}", str(counts.get(tag, 0))]
        for c, v in zip(cols, vals, strict=False):
            pen.text(x0 + c + 250, y, v, 280, "A-ANNO-TEXT")
    pen.text(x0, y_top + 800, "DOOR AND WINDOW SCHEDULE", 500, "A-ANNO-TEXT")
    pen.text(
        x0,
        y_bot - 900,
        "Sizes are structural opening sizes in mm. Windows: Uw <= 0.9 W/m2K. Counts for all storeys.",
        250,
    )
    # elevation thumbnails of each type
    for i, tag in enumerate(rows):
        _desc, w, h = TYPES[tag]
        gx, gy = x0 + i * 4500, 9500
        pen.rect(gx, gy, gx + w * 1.6, gy + h * 1.6, "A-ELEV")
        pen.rect(gx + 90, gy + 90, gx + w * 1.6 - 90, gy + h * 1.6 - 90, "A-ELEV-GLAZ")
        pen.text(gx, gy - 600, f"{tag}  {w:.0f} x {h:.0f}", 260)
    pen.text(x0, 14000, "TYPES (VIEW FROM OUTSIDE)  1:60", 300)


def build_drawing_set(path: str) -> None:
    """Write the demo drawing set to ``path`` as DXF R2010, units mm."""
    import ezdxf

    doc = ezdxf.new(dxfversion="R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.styles.add("OE_ARCH", font="arial.ttf")
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    _blocks(doc)
    pen = Pen(doc.modelspace())

    sheets = [
        ("A-101", "Ground floor plan", "1:100", lambda: _sheet_plan(pen, 0)),
        ("A-001", "Site plan", "1:200", lambda: _sheet_site(pen)),
        ("A-102", "First and second floor plan", "1:100", lambda: _sheet_plan(pen, 1)),
        ("A-103", "Roof plan", "1:100", lambda: _sheet_roof(pen)),
        ("A-201", "Section A-A", "1:100", lambda: _section_frame(pen)),
        ("A-301", "South elevation", "1:100", lambda: _elevation(pen, "south")),
        ("A-302", "East elevation", "1:100", lambda: _elevation(pen, "east")),
        ("A-501", "Door and window schedule", "1:60", lambda: _schedule(pen)),
    ]
    order = ["A-001", "A-101", "A-102", "A-103", "A-201", "A-301", "A-302", "A-501"]
    # Ground floor is authored first so the takeoff seed pins its room names.
    for number, title, scale, draw in sheets:
        i = order.index(number)
        col, row = i % 4, i // 4
        pen.at(col * (SHEET_W + SHEET_GAP), (1 - row) * (SHEET_H + SHEET_GAP))
        k = 1.0
        if number == "A-001":
            # 1:200 sheet: twice the model size of a 1:100 one, parked left of the set.
            k = 2.0
            pen.at(-(2 * SHEET_W + SHEET_GAP), 0)
        draw()
        _frame(pen, number, title, scale, k)
    doc.saveas(path)
