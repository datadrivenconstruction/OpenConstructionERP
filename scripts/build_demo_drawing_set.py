"""Build the demo architectural drawing set (DXF) and optional PNG previews.

The seed authors the same file at install time (``app.scripts.demo_drawing_set``),
so nothing binary ships in the wheel. This CLI is for reviewing the drawing.

    python scripts/build_demo_drawing_set.py --out C:/tmp/demo_set.dxf [--png C:/tmp/demo_set.png]

DWG: no DWG writer ships with the platform (DDC DwgExporter reads DWG only), so
the set is produced as DXF, which the DWG Takeoff module opens natively.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.scripts.demo_drawing_set import build_drawing_set  # noqa: E402


def _render_png(dxf: str, png: str) -> None:
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf)
    fig = plt.figure(figsize=(40, 15), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace())
    fig.savefig(png, facecolor="white")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="DXF output path")
    ap.add_argument("--png", help="optional PNG preview of the whole set")
    args = ap.parse_args()
    build_drawing_set(args.out)
    print(f"{args.out}: {Path(args.out).stat().st_size} bytes")
    if args.png:
        _render_png(args.out, args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
