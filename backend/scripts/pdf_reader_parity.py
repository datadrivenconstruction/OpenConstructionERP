# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compare ``app.core.pdf_reader`` against the reader it replaced, PyMuPDF.

PyMuPDF is AGPL and is not a dependency of this project. This script needs it
only as a reference and must be run in a throwaway environment, for example::

    cd backend
    uv run --no-project --with pymupdf --with pypdfium2 --with pdfplumber \\
        --with opencv-python-headless --with numpy --with reportlab --with psutil \\
        python scripts/pdf_reader_parity.py [extra.pdf | folder ...]

It walks every PDF tracked in the repository, the generated drawings in
``tests/_pdf_samples.py`` and any extra files or folders given, and compares
per page: page count and size, every vector path (operators, endpoints, box,
colours, widths), text, rendered pixels, takeoff recognition, similar-symbol
search and BOQ text rows. ``--perf FILE`` measures time and peak RSS of both
readers on one file, each in its own process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

MAX_PAGES = 12
PT_TOL = 0.5


def _pm():
    import pymupdf  # noqa: PLC0415 - reference reader, never a dependency

    return pymupdf


# ── normalisation ──────────────────────────────────────────────────────────


def _pts(item: tuple) -> list[tuple[float, float]]:
    op = item[0]
    if op == "re":
        r = item[1]
        return [(r[0], r[1]), (r[2], r[3])]
    if op == "qu":
        return [(p[0], p[1]) for p in item[1]]
    return [(p[0], p[1]) for p in item[1:]]


def _close(a, b, tol: float) -> bool:
    if a is None or b is None or a == () or b == ():
        return (a in (None, ())) == (b in (None, ()))
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=False)) and len(a) == len(b)


def compare_drawings(ref: list[dict], new: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "paths_ref": len(ref),
        "paths_new": len(new),
        "items_ref": sum(len(p["items"]) for p in ref),
        "items_new": sum(len(p["items"]) for p in new),
        "ops_ref": dict(Counter(it[0] for p in ref for it in p["items"])),
        "ops_new": dict(Counter(it[0] for p in new for it in p["items"])),
        "max_pt_err": 0.0,
        "op_mismatch": 0,
        "type_mismatch": 0,
        "color_mismatch": 0,
        "fill_mismatch": 0,
        "width_mismatch": 0,
        "rect_mismatch": 0,
        "dash_mismatch": 0,
        "even_odd_mismatch": 0,
        "examples": [],
    }
    for i, (a, b) in enumerate(zip(ref, new, strict=False)):
        ops_a = [it[0] for it in a["items"]]
        ops_b = [it[0] for it in b["items"]]
        if ops_a != ops_b:
            out["op_mismatch"] += 1
            if len(out["examples"]) < 6:
                out["examples"].append(
                    {"path": i, "ref": [_fmt(it) for it in a["items"][:6]], "new": [_fmt(it) for it in b["items"][:6]]}
                )
            continue
        for ia, ib in zip(a["items"], b["items"], strict=True):
            for pa, pb in zip(_pts(ia), _pts(ib), strict=True):
                out["max_pt_err"] = max(out["max_pt_err"], abs(pa[0] - pb[0]), abs(pa[1] - pb[1]))
        if a["type"] != b["type"]:
            out["type_mismatch"] += 1
        if not _close(a.get("color"), b.get("color"), 2.5 / 255):
            out["color_mismatch"] += 1
            if len(out["examples"]) < 6:
                out["examples"].append({"path": i, "color_ref": a.get("color"), "color_new": b.get("color")})
        if not _close(a.get("fill"), b.get("fill"), 2.5 / 255):
            out["fill_mismatch"] += 1
            if len(out["examples"]) < 6:
                out["examples"].append({"path": i, "fill_ref": a.get("fill"), "fill_new": b.get("fill")})
        wa, wb = a.get("width"), b.get("width")
        if (wa is None) != (wb is None) or (wa is not None and abs(wa - wb) > 1e-3 * max(1.0, abs(wa))):
            out["width_mismatch"] += 1
            if len(out["examples"]) < 6:
                out["examples"].append({"path": i, "width_ref": wa, "width_new": wb})
        if not _close(tuple(a["rect"]), tuple(b["rect"]), PT_TOL):
            out["rect_mismatch"] += 1
        if a.get("dashes") != b.get("dashes"):
            out["dash_mismatch"] += 1
            if len(out["examples"]) < 6:
                out["examples"].append({"path": i, "dash_ref": a.get("dashes"), "dash_new": b.get("dashes")})
        if a.get("even_odd") != b.get("even_odd"):
            out["even_odd_mismatch"] += 1
    if len(ref) != len(new) and len(out["examples"]) < 6:
        out["examples"].append({"count_ref": len(ref), "count_new": len(new)})
    return out


def _fmt(item: tuple) -> str:
    return item[0] + " " + " ".join(f"({x:.2f},{y:.2f})" for x, y in _pts(item))


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def compare_text(ref: str, new: str) -> dict[str, Any]:
    ta, tb = _tokens(ref), _tokens(new)
    ca, cb = Counter(ta), Counter(tb)
    common = sum((ca & cb).values())
    return {
        "tokens_ref": len(ta),
        "tokens_new": len(tb),
        "token_bag_equal": ca == cb,
        "token_overlap": round(common / max(1, max(len(ta), len(tb))), 4),
        "lines_ref": sum(1 for ln in ref.splitlines() if ln.strip()),
        "lines_new": sum(1 for ln in new.splitlines() if ln.strip()),
    }


def compare_render(ref_pix, new_render) -> dict[str, Any]:
    import numpy as np  # noqa: PLC0415

    a = np.frombuffer(ref_pix.samples, dtype=np.uint8).reshape(ref_pix.h, ref_pix.w, ref_pix.n)[:, :, :3]
    b = np.frombuffer(new_render.samples, dtype=np.uint8).reshape(new_render.height, new_render.width, 3)
    out = {"size_ref": [ref_pix.w, ref_pix.h], "size_new": [new_render.width, new_render.height]}
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    d = np.abs(a[:h, :w].astype(np.int16) - b[:h, :w].astype(np.int16)).max(axis=2)
    out["mean_abs_diff"] = round(float(d.mean()), 3)
    out["pct_px_diff_gt_64"] = round(float((d > 64).mean() * 100), 3)
    return out


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, 2)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    return obj


def compare_recognition(ref: list[dict], new: list[dict]) -> dict[str, Any]:
    from app.modules.takeoff import recognize  # noqa: PLC0415

    ca = _round(recognize.recognize_candidates(ref, 12.5, max_candidates=10_000))
    cb = _round(recognize.recognize_candidates(new, 12.5, max_candidates=10_000))
    out = {"candidates_ref": len(ca), "candidates_new": len(cb), "candidates_equal": ca == cb}
    prims = recognize.primitives_from_drawings(ref)
    seeds = recognize._symbol_primitives(prims)[:25]
    hits_eq = 0
    hits_ref = hits_new = 0
    for _prim, (cx, cy), *_ in seeds:
        ha = recognize.find_similar_symbols(ref, cx, cy)
        hb = recognize.find_similar_symbols(new, cx, cy)
        hits_ref += len(ha["hits"])
        hits_new += len(hb["hits"])
        hits_eq += _round(ha) == _round(hb)
    out.update(
        {
            "symbol_seeds": len(seeds),
            "symbol_seed_results_equal": hits_eq,
            "symbol_hits_ref": hits_ref,
            "symbol_hits_new": hits_new,
        }
    )
    return out


def compare_raster_recognition(ref_pix, new_render, page_w: float, page_h: float) -> dict[str, Any]:
    import numpy as np  # noqa: PLC0415

    from app.modules.takeoff import raster_recognize  # noqa: PLC0415

    a = np.frombuffer(ref_pix.samples, dtype=np.uint8).reshape(ref_pix.h, ref_pix.w, ref_pix.n)
    b = np.frombuffer(new_render.samples, dtype=np.uint8).reshape(new_render.height, new_render.width, 3)
    ra = raster_recognize.recognize_raster(np.ascontiguousarray(a[:, :, 2::-1]), page_w, page_h, 12.5)
    rb = raster_recognize.recognize_raster(np.ascontiguousarray(b[:, :, ::-1]), page_w, page_h, 12.5)
    return {"raster_candidates_ref": len(ra), "raster_candidates_new": len(rb)}


def compare_boq_rows(ref_text: str, new_text: str) -> dict[str, Any]:
    from app.modules.match_elements.pdf_import import _rows_from_text  # noqa: PLC0415

    ra, rb = _rows_from_text(ref_text), _rows_from_text(new_text)
    key = lambda r: json.dumps(r, sort_keys=True, default=str)  # noqa: E731
    return {
        "boq_rows_ref": len(ra),
        "boq_rows_new": len(rb),
        "boq_rows_equal": sorted(map(key, ra)) == sorted(map(key, rb)),
    }


# ── corpus ─────────────────────────────────────────────────────────────────


def boq_sample() -> bytes:
    """A BOQ printed by reportlab, the shape a tender PDF usually has."""
    import io  # noqa: PLC0415

    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    rows = [
        ("01.001", "Excavation of topsoil, depth 30 cm", "120.5", "m3"),
        ("01.002", "Concrete C30/37 for strip foundations", "48", "m3"),
        ("02.010", "Reinforcement steel B500B", "3.2", "t"),
        ("03.120", "Masonry wall 24 cm, sand-lime brick", "212.75", "m2"),
        ("04.001", "Interior plaster, two coats", "640", "m2"),
    ]
    y = 780
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Pos.")
    c.drawString(100, y, "Description")
    c.drawString(420, y, "Qty")
    c.drawString(480, y, "Unit")
    c.setFont("Helvetica", 10)
    for code, desc, qty, unit in rows * 6:
        y -= 18
        c.drawString(40, y, code)
        c.drawString(100, y, desc)
        c.drawRightString(460, y, qty)
        c.drawString(480, y, unit)
        c.line(40, y - 4, 540, y - 4)
    c.showPage()
    c.save()
    return buf.getvalue()


def corpus(extra: list[str]) -> list[tuple[str, bytes]]:
    from tests._pdf_samples import sample_pages  # noqa: PLC0415

    seen: set[str] = set()
    out: list[tuple[str, bytes]] = []

    def add(name: str, data: bytes) -> None:
        h = hashlib.sha1(data).hexdigest()  # noqa: S324 - dedup only
        if h not in seen:
            seen.add(h)
            out.append((name, data))

    tracked = subprocess.run(["git", "ls-files", "*.pdf"], cwd=REPO, capture_output=True, text=True, check=False)
    for rel in tracked.stdout.splitlines():
        p = REPO / rel
        if p.is_file():
            add(rel, p.read_bytes())
    for name, data in sample_pages():
        add(f"sample:{name}", data)
    add("sample:boq_reportlab", boq_sample())
    for arg in extra:
        p = Path(arg)
        files = sorted(p.rglob("*.pdf")) if p.is_dir() else [p]
        for f in files:
            try:
                add(str(f), f.read_bytes())
            except OSError:
                continue
    return out


# ── main comparison ────────────────────────────────────────────────────────


def compare_file(name: str, data: bytes) -> dict[str, Any]:
    from app.core import pdf_reader  # noqa: PLC0415

    pymupdf = _pm()
    res: dict[str, Any] = {"file": name, "pages": []}
    try:
        ref_doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        ref_doc = None
        res["ref_error"] = str(exc)
    try:
        new_doc = pdf_reader.open_pdf(data)
    except pdf_reader.PdfReaderError as exc:
        new_doc = None
        res["new_error"] = str(exc)
    if ref_doc is None or new_doc is None:
        res["open_parity"] = (ref_doc is None) == (new_doc is None)
        return res
    res["page_count_ref"], res["page_count_new"] = ref_doc.page_count, new_doc.page_count
    for i in range(min(ref_doc.page_count, new_doc.page_count, MAX_PAGES)):
        rp, np_ = ref_doc[i], new_doc[i]
        page: dict[str, Any] = {"page": i + 1, "rotation": rp.rotation}
        page["rect_ref"] = [round(v, 3) for v in rp.rect]
        page["rect_new"] = [round(v, 3) for v in np_.rect]
        rd, nd = rp.get_drawings(), np_.drawings()
        page["drawings"] = compare_drawings(rd, nd)
        page["recognition"] = compare_recognition(rd, nd)
        rt, nt = rp.get_text(), np_.text()
        page["text"] = compare_text(rt, nt)
        page["boq"] = compare_boq_rows(rt, nt)
        rpix = rp.get_pixmap(dpi=72, alpha=False)
        nren = np_.render(dpi=72)
        page["render"] = compare_render(rpix, nren)
        if not rd:
            rpix150 = rp.get_pixmap(dpi=150, alpha=False)
            nren150 = np_.render(dpi=150)
            page["raster"] = compare_raster_recognition(rpix150, nren150, rp.rect.width, rp.rect.height)
        np_.close()
        res["pages"].append(page)
    new_doc.close()
    ref_doc.close()
    return res


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    s: Counter = Counter()
    worst_pt = 0.0
    render_mean: list[float] = []
    for r in results:
        s["files"] += 1
        s["page_count_equal"] += r.get("page_count_ref") == r.get("page_count_new")
        for p in r["pages"]:
            s["pages"] += 1
            d = p["drawings"]
            s["rect_equal"] += p["rect_ref"] == p["rect_new"]
            s["paths_ref"] += d["paths_ref"]
            s["paths_new"] += d["paths_new"]
            s["items_ref"] += d["items_ref"]
            s["items_new"] += d["items_new"]
            for k in (
                "op_mismatch",
                "type_mismatch",
                "color_mismatch",
                "fill_mismatch",
                "width_mismatch",
                "rect_mismatch",
                "dash_mismatch",
                "even_odd_mismatch",
            ):
                s[k] += d[k]
            s["pages_drawings_identical_ops"] += d["paths_ref"] == d["paths_new"] and d["op_mismatch"] == 0
            worst_pt = max(worst_pt, d["max_pt_err"])
            rec = p["recognition"]
            s["pages_candidates_equal"] += rec["candidates_equal"]
            s["candidates_ref"] += rec["candidates_ref"]
            s["candidates_new"] += rec["candidates_new"]
            s["symbol_seeds"] += rec["symbol_seeds"]
            s["symbol_seed_results_equal"] += rec["symbol_seed_results_equal"]
            t = p["text"]
            s["pages_text_bag_equal"] += t["token_bag_equal"]
            s["text_tokens_ref"] += t["tokens_ref"]
            s["text_tokens_new"] += t["tokens_new"]
            s["pages_boq_rows_equal"] += p["boq"]["boq_rows_equal"]
            s["pages_render_size_equal"] += p["render"]["size_ref"] == p["render"]["size_new"]
            render_mean.append(p["render"]["mean_abs_diff"])
            if "raster" in p:
                s["raster_pages"] += 1
                s["raster_candidates_equal"] += (
                    p["raster"]["raster_candidates_ref"] == p["raster"]["raster_candidates_new"]
                )
    out = dict(s)
    out["max_endpoint_err_pt"] = round(worst_pt, 4)
    out["render_mean_abs_diff_avg"] = round(sum(render_mean) / max(1, len(render_mean)), 3)
    out["render_mean_abs_diff_max"] = max(render_mean, default=0.0)
    return out


def _perf_child(engine: str, path: str) -> None:
    import psutil  # noqa: PLC0415

    proc = psutil.Process()
    t = time.perf_counter()
    n_paths = 0
    if engine == "pymupdf":
        pymupdf = _pm()
        doc = pymupdf.open(path)
        for page in doc:
            n_paths += len(page.get_drawings())
            page.get_text()
            page.get_pixmap(dpi=150, alpha=False)
        doc.close()
    else:
        from app.core import pdf_reader  # noqa: PLC0415

        with pdf_reader.open_pdf(path) as doc:
            for page in doc:
                n_paths += len(page.drawings())
                page.text()
                page.render(dpi=150)
    elapsed = time.perf_counter() - t
    mem = proc.memory_info()
    peak = getattr(mem, "peak_wset", None) or getattr(mem, "peak_rss", None) or mem.rss
    print(
        json.dumps(
            {"engine": engine, "seconds": round(elapsed, 3), "peak_rss_mb": round(peak / 2**20, 1), "paths": n_paths}
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("extra", nargs="*", help="extra PDF files or folders to compare")
    ap.add_argument("--json", help="write the full per-page report here")
    ap.add_argument("--perf", help="measure both readers on this PDF")
    ap.add_argument("--perf-child", nargs=2, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.perf_child:
        _perf_child(*args.perf_child)
        return 0
    if args.perf:
        for engine in ("pymupdf", "pdfium"):
            r = subprocess.run(
                [sys.executable, __file__, "--perf-child", engine, args.perf],
                capture_output=True,
                text=True,
                check=False,
            )
            print(r.stdout.strip() or r.stderr.strip()[-2000:])
        return 0
    results = []
    for name, data in corpus(args.extra):
        t = time.perf_counter()
        results.append(compare_file(name, data))
        print(f"{time.perf_counter() - t:7.1f}s  {name}", file=sys.stderr, flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    summary = summarise(results)
    print(json.dumps(summary, indent=1))
    bad = [
        (r["file"], p["page"])
        for r in results
        for p in r["pages"]
        if p["drawings"]["op_mismatch"]
        or p["drawings"]["paths_ref"] != p["drawings"]["paths_new"]
        or not p["recognition"]["candidates_equal"]
    ]
    for f, pg in bad[:30]:
        print("DIFF", f, "page", pg)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
