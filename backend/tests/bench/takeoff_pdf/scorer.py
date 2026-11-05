# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Score the offline takeoff detectors against the generated ground truth.

Usage (from ``backend/``)::

    python -m tests.bench.takeoff_pdf.scorer --n 40 --scans 16 --label baseline

Each page is read exactly the way the service reads it (``app.core.pdf_reader``:
vector layer if present, otherwise a 150 DPI render for the raster detector),
and the scale note is read from the text the PDF extract worker stores. One JSON
line per run is appended to ``ledger.jsonl`` next to this file.

Metrics per split and detector:

* areas: precision / recall / F1 with polygon IoU >= 0.5, median area error %,
* walls: precision / recall / F1 (same direction, centreline within half a wall,
  1-D overlap IoU >= 0.5), median length error %, median per-page total error %,
* counts: instance precision / recall / F1, exact count accuracy per class,
* scale: accuracy of the best candidate (a missing scale must stay missing),
* noise: share of noise-only pages with any candidate, candidates per noise page,
* confidence: AUC of TP vs FP candidates and precision per confidence band,
* runtime: mean and p95 ms per page, peak traced numpy memory.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

LEDGER = Path(__file__).with_name("ledger.jsonl")
IOU_MIN = 0.5
REAL_ASSETS = Path(__file__).resolve().parents[3] / "app" / "scripts" / "flagship_assets"


# ── detection, mirroring TakeoffService.recognize_candidates ─────────────────


def peak_rss_mb() -> float:
    """Peak resident memory of this process so far, what the 3 GB server rule is about.

    Native allocations (OpenCV, PDFium) count here; a Python-level tracer misses them.
    """
    try:
        import psutil

        info = psutil.Process().memory_info()
        return round(float(getattr(info, "peak_wset", info.rss)) / 1e6, 1)
    except ImportError:
        import resource  # noqa: PLC0415 - not on Windows, where psutil is the way in

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3, 1)


def detect(pdf: bytes, scale_ppu: float) -> dict[str, Any]:
    """Run the offline recognizer on page 1 the way the service does, with no time limit.

    The limit is wall-clock and would make a score depend on how busy the machine is.
    """
    from app.modules.takeoff import recognize

    run = getattr(recognize, "recognize_pdf_page", None)
    t0 = time.perf_counter()
    result = run(pdf, 1, scale_ppu, budget_s=None) if run is not None else _legacy_detect(pdf, scale_ppu)
    result["ms"] = (time.perf_counter() - t0) * 1000
    result["peak_rss_mb"] = peak_rss_mb()
    return result


def _legacy_detect(pdf: bytes, scale_ppu: float) -> dict[str, Any]:
    import numpy as np

    from app.core import pdf_reader
    from app.modules.takeoff import raster_recognize, recognize

    with pdf_reader.open_pdf(pdf) as doc:
        page = doc[0]
        drawings = page.drawings()
        w, h = float(page.rect.width), float(page.rect.height)
        if drawings:
            return {"candidates": recognize.recognize_candidates(drawings, scale_ppu), "source": "vector"}
        pix = page.render(dpi=150)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    bgr = np.ascontiguousarray(arr[:, :, ::-1])
    return {"candidates": raster_recognize.recognize_raster(bgr, w, h, scale_ppu), "source": "raster"}


def detect_scale(pdf: bytes) -> int | None:
    """Best scale ratio from the text the extract worker stores for the page."""
    from app.modules.takeoff import scale_detect
    from app.modules.takeoff.pdf_extract_worker import extract_pdf_data

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.pdf"
        path.write_bytes(pdf)
        data = extract_pdf_data(str(path))
    best, _ranked = scale_detect.detect_best_scale(data.get("pages") or [])
    return best.ratio if best is not None else None


# ── geometry ──────────────────────────────────────────────────────────────────


def _pts(cand: dict[str, Any]) -> list[tuple[float, float]]:
    return [(float(p["x"]), float(p["y"])) for p in cand.get("points") or []]


def shoelace(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def poly_iou(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    import cv2
    import numpy as np

    xs = [p[0] for p in a + b]
    ys = [p[1] for p in a + b]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return 0.0
    z = 400.0 / max(x1 - x0, y1 - y0)
    w, h = int((x1 - x0) * z) + 3, int((y1 - y0) * z) + 3
    ma = np.zeros((h, w), np.uint8)
    mb = np.zeros((h, w), np.uint8)
    cv2.fillPoly(
        ma, [np.round(np.array([((x - x0) * z + 1, (y - y0) * z + 1) for x, y in a]) * 8).astype(np.int32)], 1, shift=3
    )
    cv2.fillPoly(
        mb, [np.round(np.array([((x - x0) * z + 1, (y - y0) * z + 1) for x, y in b]) * 8).astype(np.int32)], 1, shift=3
    )
    inter = int(np.count_nonzero(ma & mb))
    union = int(np.count_nonzero(ma | mb))
    return inter / union if union else 0.0


def _bbox(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# ── per-page scoring ──────────────────────────────────────────────────────────


def score_areas(cands: list[dict[str, Any]], gt: dict[str, Any]) -> dict[str, Any]:
    preds = [c for c in cands if c.get("type") == "area" and len(c.get("points") or []) >= 3]
    gts = [[tuple(p) for p in r["polygon"]] for r in gt["rooms"]]
    pairs = []
    for i, c in enumerate(preds):
        pp = _pts(c)
        pb = _bbox(pp)
        for j, g in enumerate(gts):
            if _overlap(pb, _bbox(g)):
                iou = poly_iou(pp, g)
                if iou > 0.1:
                    pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_p, used_g, matches = set(), set(), []
    for iou, i, j in pairs:
        if iou < IOU_MIN or i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        matches.append((i, j, iou))
    errs = [abs(shoelace(_pts(preds[i])) - shoelace(gts[j])) / shoelace(gts[j]) * 100 for i, j, _ in matches]
    conf = [(float(c.get("confidence", 0)), i in used_p) for i, c in enumerate(preds)]
    return {
        "tp": len(matches),
        "np": len(preds),
        "ng": len(gts),
        "err": errs,
        "iou": [m[2] for m in matches],
        "conf": conf,
    }


def _seg_match(p: tuple, g: tuple, tol_perp: float) -> float:
    (ax, ay), (bx, by) = g
    L = math.hypot(bx - ax, by - ay)
    if L <= 0:
        return 0.0
    ux, uy = (bx - ax) / L, (by - ay) / L
    (px, py), (qx, qy) = p
    lp = math.hypot(qx - px, qy - py)
    if lp <= 0:
        return 0.0
    cosang = abs(((qx - px) * ux + (qy - py) * uy) / lp)
    if cosang < math.cos(math.radians(3)):
        return 0.0
    d1 = abs(-(px - ax) * uy + (py - ay) * ux)
    d2 = abs(-(qx - ax) * uy + (qy - ay) * ux)
    if max(d1, d2) > tol_perp:
        return 0.0
    s1 = (px - ax) * ux + (py - ay) * uy
    s2 = (qx - ax) * ux + (qy - ay) * uy
    lo, hi = min(s1, s2), max(s1, s2)
    inter = max(0.0, min(hi, L) - max(lo, 0.0))
    union = max(hi, L) - min(lo, 0.0)
    return inter / union if union > 0 else 0.0


def score_walls(cands: list[dict[str, Any]], gt: dict[str, Any]) -> dict[str, Any]:
    preds = [c for c in cands if c.get("type") == "distance" and len(c.get("points") or []) == 2]
    k = gt["pt_per_m"]
    gts = [((tuple(w["a"]), tuple(w["b"])), w["thickness_m"] * k) for w in gt["walls"]]
    pairs = []
    for i, c in enumerate(preds):
        pp = tuple(_pts(c))
        for j, (g, t) in enumerate(gts):
            iou = _seg_match(pp, g, max(2.0, 0.6 * t))
            if iou >= IOU_MIN:
                pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_p, used_g, errs = set(), set(), []
    for _iou, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        pl = math.dist(*_pts(preds[i]))
        gl = math.dist(*gts[j][0])
        errs.append(abs(pl - gl) / gl * 100)
    tot_p = sum(math.dist(*_pts(c)) for c in preds)
    tot_g = sum(math.dist(*g) for g, _ in gts)
    conf = [(float(c.get("confidence", 0)), i in used_p) for i, c in enumerate(preds)]
    total_err = abs(tot_p - tot_g) / tot_g * 100 if tot_g else None
    return {"tp": len(used_p), "np": len(preds), "ng": len(gts), "err": errs, "total_err": total_err, "conf": conf}


def score_counts(cands: list[dict[str, Any]], gt: dict[str, Any]) -> dict[str, Any]:
    clusters = [c for c in cands if c.get("type") == "count"]
    inst = [(cls, tuple(p), gt["symbol_radius"].get(cls, 6.0)) for cls, pts in gt["symbols"].items() for p in pts]
    pred_pts = [(ci, p) for ci, c in enumerate(clusters) for p in _pts(c)]
    pairs = []
    for pi, (_ci, p) in enumerate(pred_pts):
        for gi, (_cls, g, r) in enumerate(inst):
            d = math.dist(p, g)
            if d <= max(r, 3.0):
                pairs.append((d, pi, gi))
    pairs.sort()
    used_p, used_g, match = set(), set(), {}
    for _d, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        match[pi] = gi
    # exact count per GT class (classes with at least two instances)
    by_class: dict[str, int] = {}
    for cls, _g, _r in inst:
        by_class[cls] = by_class.get(cls, 0) + 1
    exact = 0
    classes = [c for c, n in by_class.items() if n >= 2]
    for cls in classes:
        best = None
        for ci, c in enumerate(clusters):
            hits = sum(1 for pi, gi in match.items() if pred_pts[pi][0] == ci and inst[gi][0] == cls)
            if hits and (best is None or hits > best[0]):
                best = (hits, len(_pts(c)))
        if best and best[0] == by_class[cls] and best[1] == by_class[cls]:
            exact += 1
    conf = []
    for ci, c in enumerate(clusters):
        n = len(_pts(c))
        hits = sum(1 for pi in match if pred_pts[pi][0] == ci)
        conf.append((float(c.get("confidence", 0)), n > 0 and hits / n >= 0.5))
    return {
        "tp": len(match),
        "np": len(pred_pts),
        "ng": len(inst),
        "classes": len(classes),
        "exact": exact,
        "conf": conf,
    }


def score_page(task: tuple[str, int, str]) -> dict[str, Any]:
    """Generate (or load), detect and score one page. Runs in a worker process."""
    from tests.bench.takeoff_pdf import generator

    split, seed, variant = task
    if split == "real":
        pdf, gt = real_page(seed)
    elif variant == "scan":
        pdf, gt = generator.make_scan(seed)
    else:
        pdf, gt = generator.make_page(seed)
    res = detect(pdf, gt["pt_per_m"])
    cands = res["candidates"]
    out: dict[str, Any] = {
        "split": split,
        "seed": seed,
        "variant": variant,
        "kind": gt["kind"],
        "source": res.get("source"),
        "ms": res["ms"],
        "peak_rss_mb": res["peak_rss_mb"],
        "n_cands": len(cands),
    }
    if gt["kind"] == "noise":
        out["noise_any"] = bool(cands)
    else:
        out["areas"] = score_areas(cands, gt)
        if gt.get("walls") is not None and split != "real":
            out["walls"] = score_walls(cands, gt)
        if gt.get("symbols") and variant == "vector":
            out["counts"] = score_counts(cands, gt)
    if variant == "vector":
        got = detect_scale(pdf)
        out["scale"] = {"gt": gt["scale"]["ratio"], "got": got}
    return out


# ── real sample sheets shipped with the demo data ─────────────────────────────


def real_page(index: int) -> tuple[bytes, dict[str, Any]]:
    """The German demo floor plan, issues A and B, with ground truth from its source."""
    from app.scripts import grundriss_plan as gp

    rev = (gp.REVISION_A, gp.REVISION_B)[index]
    name = ("grundriss_erdgeschoss.pdf", "grundriss_erdgeschoss_index_b.pdf")[index]
    pdf = (REAL_ASSETS / name).read_bytes()
    rooms = []
    for number in sorted(rev.rooms):
        poly = [list(gp.to_viewer_xy(x, y)) for x, y in rev.room_polygon_m(number)]
        rooms.append({"id": number, "polygon": poly, "area_m2": rev.rooms[number].area_m2})
    gt = {
        "kind": "plan",
        "pt_per_m": gp.PT_PER_M,
        "rooms": rooms,
        "walls": None,
        "symbols": {},
        "symbol_radius": {},
        "scale": {"ratio": gp.SCALE_RATIO},
    }
    return pdf, gt


# ── aggregation ───────────────────────────────────────────────────────────────


def _prf(tp: int, np_: int, ng: int) -> dict[str, float]:
    p = tp / np_ if np_ else (1.0 if ng == 0 else 0.0)
    r = tp / ng if ng else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"p": round(p, 4), "r": round(r, 4), "f1": round(f, 4)}


def _med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 3) if xs else None


def _auc(conf: list[tuple[float, bool]]) -> float | None:
    pos = [c for c, ok in conf if ok]
    neg = [c for c, ok in conf if not ok]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return round(wins / (len(pos) * len(neg)), 4)


def _bands(conf: list[tuple[float, bool]]) -> dict[str, Any]:
    out = {}
    for lo, hi in ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)):
        sel = [ok for c, ok in conf if lo <= c < hi]
        out[f"{lo:.2f}"] = {"n": len(sel), "precision": round(sum(sel) / len(sel), 3) if sel else None}
    return out


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant in ("vector", "scan"):
        rs = [r for r in rows if r["variant"] == variant]
        if not rs:
            continue
        plans = [r for r in rs if r["kind"] == "plan"]
        noise = [r for r in rs if r["kind"] == "noise"]
        block: dict[str, Any] = {"pages": len(rs), "plans": len(plans), "noise_pages": len(noise)}
        conf_all: list[tuple[float, bool]] = []
        for det in ("areas", "walls", "counts"):
            ds = [r[det] for r in plans if det in r]
            if not ds:
                continue
            tp, np_, ng = sum(d["tp"] for d in ds), sum(d["np"] for d in ds), sum(d["ng"] for d in ds)
            blk = _prf(tp, np_, ng)
            if det == "areas":
                errs = [e for d in ds for e in d["err"]]
                blk["area_err_med_pct"] = _med(errs)
                blk["area_err_p90_pct"] = round(sorted(errs)[int(0.9 * (len(errs) - 1))], 3) if errs else None
                blk["iou_mean"] = round(statistics.fmean([i for d in ds for i in d["iou"]]), 4) if tp else None
            if det == "walls":
                blk["length_err_med_pct"] = _med([e for d in ds for e in d["err"]])
                blk["total_len_err_med_pct"] = _med([d["total_err"] for d in ds if d["total_err"] is not None])
            if det == "counts":
                classes = sum(d["classes"] for d in ds)
                blk["count_exact_acc"] = round(sum(d["exact"] for d in ds) / classes, 4) if classes else None
            c = [x for d in ds for x in d["conf"]]
            blk["conf_auc"] = _auc(c)
            conf_all += c
            block[det] = blk
        if noise:
            block["noise_fp_page_rate"] = round(sum(r["noise_any"] for r in noise) / len(noise), 4)
            block["noise_cands_per_page"] = round(statistics.fmean(r["n_cands"] for r in noise), 2)
        sc = [r["scale"] for r in rs if "scale" in r]
        if sc:
            with_gt = [s for s in sc if s["gt"] is not None]
            without = [s for s in sc if s["gt"] is None]
            block["scale"] = {
                "acc": round(sum(s["gt"] == s["got"] for s in sc) / len(sc), 4),
                "acc_with_note": round(sum(s["gt"] == s["got"] for s in with_gt) / len(with_gt), 4)
                if with_gt
                else None,
                "false_on_none": round(sum(s["got"] is not None for s in without) / len(without), 4)
                if without
                else None,
                "n": len(sc),
            }
        block["confidence"] = {"auc": _auc(conf_all), "bands": _bands(conf_all)}
        ms = sorted(r["ms"] for r in rs)
        block["runtime_ms"] = {"mean": round(statistics.fmean(ms), 1), "p95": round(ms[int(0.95 * (len(ms) - 1))], 1)}
        block["peak_rss_mb_max"] = round(max(r["peak_rss_mb"] for r in rs), 1)
        out[variant] = block
    return out


def tasks_for(split: str, n: int, scans: int) -> list[tuple[str, int, str]]:
    from tests.bench.takeoff_pdf.generator import split_seeds

    if split == "real":
        return [("real", 0, "vector"), ("real", 1, "vector")]
    seeds = split_seeds(split, max(n, scans))
    return [(split, s, "vector") for s in seeds[:n]] + [(split, s, "scan") for s in seeds[:scans]]


def _score_independent(spec: dict[str, Any]) -> dict[str, Any]:
    from tests.bench.takeoff_pdf import independent

    return independent.score_sheet(spec, detect, detect_scale)


def evaluate_independent(split: str, workers: int = 1) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score the sheets this benchmark did not generate; ``split`` is ``tune`` or ``held``."""
    from tests.bench.takeoff_pdf import independent

    specs = independent.load_specs(split)
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            rows = list(ex.map(_score_independent, specs))
    else:
        rows = [_score_independent(s) for s in specs]
    missing = [r["id"] for r in rows if r.get("missing")]
    present = [r for r in rows if not r.get("missing")]
    block = independent.summarize(present)
    block["missing"] = missing
    return block, present


def evaluate(split: str, n: int, scans: int, workers: int = 1) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if split in ("tune", "held"):
        return evaluate_independent(split, workers)
    tasks = tasks_for(split, n, scans)
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            rows = list(ex.map(score_page, tasks))
    else:
        rows = [score_page(t) for t in tasks]
    return aggregate(rows), rows


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40, help="vector pages per split")
    ap.add_argument("--scans", type=int, default=16, help="scanned pages per split")
    ap.add_argument("--splits", default="train,holdout,fresh,real,tune,held")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--label", default="")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--rows", type=Path, help="also write per-page rows (JSON) here")
    args = ap.parse_args(argv)
    t0 = time.time()
    entry: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sha": _git_sha(), "label": args.label}
    entry["config"] = {"n": args.n, "scans": args.scans}
    all_rows = []
    for split in args.splits.split(","):
        metrics, rows = evaluate(split, args.n, args.scans, args.workers)
        entry[split] = metrics
        all_rows += rows
    entry["wall_s"] = round(time.time() - t0, 1)
    print(json.dumps(entry, indent=1, ensure_ascii=False))
    if args.rows:
        args.rows.write_text(json.dumps(all_rows, indent=0, default=str))
    if not args.no_ledger:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
