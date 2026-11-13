"""Build the demo architectural drawing set (DXF) and optional PNG previews.

The seed authors the same file at install time (``app.scripts.demo_drawing_set``),
so nothing binary ships in the wheel. This CLI is for reviewing the drawing.

    python scripts/build_demo_drawing_set.py --out C:/tmp/demo_set.dxf [--png C:/tmp/demo_set.png]

DWG: no DWG writer ships with the platform (DDC DwgExporter reads DWG only), so
the DXF is the working file. The DWG original that ships beside it is produced
offline with LibreDWG's ``dxf2dwg`` (GNU, GPL-3.0; a build-time tool, never a
runtime dependency) by this same script:

    python scripts/build_demo_drawing_set.py --out C:/tmp/demo_set.dxf --dwg C:/tools/libredwg/dxf2dwg.exe

The DWG lands in ``backend/app/scripts/demo_drawing_assets/`` under a name that
carries ``SET_VERSION``; DWG R2000 is used because it is the version LibreDWG
writes and reads back without losing an entity. Block references are exploded
first (see ``build_drawing_set_for_dwg``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.scripts.demo_drawing_set import SET_VERSION, build_drawing_set, build_drawing_set_for_dwg  # noqa: E402

DWG_VERSION = "r2000"
DWG_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "scripts" / "demo_drawing_assets"


def _write_dwg(dxf: str, dxf2dwg: str, out: Path) -> None:
    """Write the set as a LibreDWG-friendly DXF beside ``dxf``, convert it to ``out``, drop stale versions."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    source = str(Path(dxf).with_suffix(".dwgsrc.dxf"))
    build_drawing_set_for_dwg(source)
    cmd = [dxf2dwg, "--as", DWG_VERSION, "-y", "-o", str(out), source]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)  # noqa: S603
    Path(source).unlink(missing_ok=True)
    if run.returncode != 0 or not out.is_file():
        raise SystemExit(f"dxf2dwg failed (exit {run.returncode}): {(run.stderr or run.stdout)[-500:]}")
    reader = Path(dxf2dwg).with_name("dwgread" + Path(dxf2dwg).suffix)
    if (
        reader.is_file()
        and subprocess.run([str(reader), str(out)], capture_output=True, timeout=600, check=False).returncode
    ):  # noqa: S603
        raise SystemExit("dwgread rejects the written DWG")
    for old in out.parent.glob("residential_block_set_v*.dwg"):
        if old != out:
            old.unlink()


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
    ap.add_argument("--dwg", metavar="DXF2DWG", help="path to LibreDWG dxf2dwg: also write the shipped DWG original")
    ap.add_argument("--dwg-out", help="DWG output path (default: the shipped asset directory)")
    ap.add_argument("--png", help="optional PNG preview of the whole set")
    args = ap.parse_args()
    build_drawing_set(args.out)
    print(f"{args.out}: {Path(args.out).stat().st_size} bytes")
    if args.dwg:
        dwg_out = Path(args.dwg_out) if args.dwg_out else DWG_DIR / f"residential_block_set_v{SET_VERSION}.dwg"
        _write_dwg(args.out, args.dwg, dwg_out)
        print(f"{dwg_out}: {dwg_out.stat().st_size} bytes")
    if args.png:
        _render_png(args.out, args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
