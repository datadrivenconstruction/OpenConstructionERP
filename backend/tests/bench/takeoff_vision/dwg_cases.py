"""DXF entities with known areas and lengths, measured through the DWG takeoff path.

Each case is drawn with ezdxf, read back by ``dxf_processor.parse_dxf`` and
flattened by the service's ``_normalize_entity`` (what the viewer and the
auto-quantify get), then measured: shoelace area minus holes for closed rings,
path length for open ones.

    cd backend
    python -m tests.bench.takeoff_vision.dwg_cases
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Case:
    name: str
    kind: str  # area | length
    expected: float


def _draw(path: Path) -> list[Case]:
    import ezdxf  # noqa: PLC0415

    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    cases: list[Case] = []

    # 6 x 4 room whose east wall is a half-circle bay (bulge 1 = 180 degrees).
    msp.add_lwpolyline([(0, 0, 0), (6, 0, 1), (6, 4, 0), (0, 4, 0)], format="xyb", close=True)
    cases.append(Case("lwpolyline_bulged_room", "area", 24 + math.pi * 2**2 / 2))
    # Same rectangle drawn back onto its first vertex instead of the closed flag.
    msp.add_lwpolyline([(10, 0), (15, 0), (15, 3), (10, 3), (10, 0)])
    cases.append(Case("lwpolyline_closed_by_repeat", "area", 15.0))
    # Old-style POLYLINE with a quarter-circle corner (bulge tan(22.5 deg)).
    pl = msp.add_polyline2d([(20, 0), (24, 0), (26, 2), (26, 5), (20, 5)], close=True)
    pl.vertices[1].dxf.bulge = math.tan(math.pi / 8)
    cases.append(Case("polyline2d_rounded_corner", "area", 30 - 4 + math.pi))
    # Slab hatch 10 x 8 with a 2 x 3 shaft and a circular hole r = 0.5.
    h = msp.add_hatch()
    h.paths.add_polyline_path([(30, 0), (40, 0), (40, 8), (30, 8)], is_closed=True, flags=1)
    h.paths.add_polyline_path([(32, 2), (34, 2), (34, 5), (32, 5)], is_closed=True, flags=16)
    ep = h.paths.add_edge_path(flags=16)
    ep.add_arc((37, 4), 0.5, 0, 360)
    cases.append(Case("hatch_with_holes", "area", 80 - 6 - math.pi * 0.25))
    # One hatch over two separate slabs, the second with a hole holding an island.
    h2 = msp.add_hatch()
    h2.paths.add_polyline_path([(60, 0), (64, 0), (64, 4), (60, 4)], is_closed=True, flags=1)
    h2.paths.add_polyline_path([(70, 0), (76, 0), (76, 6), (70, 6)], is_closed=True, flags=1)
    h2.paths.add_polyline_path([(71, 1), (75, 1), (75, 5), (71, 5)], is_closed=True, flags=16)
    h2.paths.add_polyline_path([(72, 2), (73, 2), (73, 3), (72, 3)], is_closed=True, flags=16)
    cases.append(Case("hatch_disjoint_loops", "area", 16 + 36 - 16 + 1))
    # Open spline: a smooth run whose control polygon is much longer than the curve.
    fit = [(50, 0), (52, 2), (54, 0), (56, 2)]
    msp.add_spline(fit_points=fit)
    cases.append(Case("spline_open_run", "length", _spline_length(fit)))
    doc.saveas(path)
    return cases


def _spline_length(fit: list[tuple[float, float]]) -> float:
    import ezdxf  # noqa: PLC0415

    sp = ezdxf.new().modelspace().add_spline(fit_points=fit)
    pts = list(sp.flattening(1e-5))
    return sum(math.dist((pts[i - 1].x, pts[i - 1].y), (pts[i].x, pts[i].y)) for i in range(1, len(pts)))


def _area(vertices: list[dict[str, float]]) -> float:
    p = [(v["x"], v["y"]) for v in vertices]
    return abs(0.5 * sum(p[i - 1][0] * p[i][1] - p[i][0] * p[i - 1][1] for i in range(len(p))))


def measure(entity: dict[str, Any]) -> tuple[str, float]:
    verts = entity.get("vertices") or []
    if entity.get("closed") or entity["type"] == "HATCH":
        filled = _area(verts) + sum(_area(r) for r in entity.get("extra_loops") or [])
        return "area", filled - sum(_area(h) for h in entity.get("holes") or [])
    return "length", sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(verts, verts[1:], strict=False))


def run() -> list[dict[str, Any]]:
    # The service module builds an engine at import; nothing here connects to it.
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://bench:bench@127.0.0.1:1/bench")
    from app.modules.dwg_takeoff.dxf_processor import parse_dxf  # noqa: PLC0415
    from app.modules.dwg_takeoff.service import _normalize_entity  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cases.dxf"
        cases = _draw(path)
        raw = [e for e in parse_dxf(str(path))["entities"] if not e.get("block")]
    ents = [_normalize_entity(e, i) for i, e in enumerate(raw)]
    measurable = [e for e in ents if e["type"] in ("LWPOLYLINE", "POLYLINE", "HATCH")]
    rows = []
    for case, ent in zip(cases, measurable, strict=False):
        kind, value = measure(ent)
        err = abs(value - case.expected) / case.expected
        rows.append({"case": case.name, "kind": kind, "expected": case.expected, "got": value, "err_pct": 100 * err})
    return rows


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, indent=1))
    sys.exit(0 if all(r["err_pct"] < 0.05 for r in out) else 1)
