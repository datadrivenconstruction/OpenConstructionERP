"""Independent split: drawing sets this benchmark did not generate.

The sheets live outside the repository (they are not ours to redistribute); the
truth for them is in ``independent.json``. Point ``TAKEOFF_BENCH_SHEETS`` at the
folder holding them; ``house_plans.pdf`` ships with the platform's demo assets.

``tune`` sheets may be looked at while developing. ``held`` sheets are not: they
are scored and reported, nothing is changed because of a held result.

A room is right when a candidate holds its label, holds no other room's label
and, where the ledger gives an area, measures within 10 % of it.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

MANIFEST = Path(__file__).with_name("independent.json")
_ASSETS = Path(__file__).resolve().parents[3] / "app" / "scripts" / "flagship_assets"
_AREA_TOL = 0.10


def sheets_root() -> Path | None:
    env = os.environ.get("TAKEOFF_BENCH_SHEETS")
    if env:
        return Path(env)
    default = Path(__file__).resolve().parents[5] / "use_cases_ocerp" / "academy-2030"
    return default if default.is_dir() else None


def load_specs(split: str | None = None) -> list[dict[str, Any]]:
    specs = json.loads(MANIFEST.read_text(encoding="utf-8"))["sheets"]
    return [s for s in specs if split is None or s["split"] == split]


def sheet_pdf(spec: dict[str, Any]) -> bytes | None:
    """The sheet's bytes, degraded like a scan when the spec asks; None when it is not on this machine."""
    if "asset" in spec:
        path = _ASSETS / spec["asset"]
    else:
        root = sheets_root()
        if root is None:
            return None
        path = root / spec["file"]
    if not path.is_file():
        return None
    return path.read_bytes()


def prepared(spec: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]] | None:
    """(pdf, rooms) ready to detect, with label positions moved along with a simulated scan's skew."""
    pdf = sheet_pdf(spec)
    if pdf is None:
        return None
    rooms = spec.get("rooms") or []
    if spec.get("scan"):
        from tests.bench.takeoff_pdf import generator

        pdf, move, _skew = generator.degrade_to_scan(pdf, spec["scan_seed"])
        rooms = [{**r, "at": move(r["at"])} for r in rooms]
    return pdf, rooms


def _inside(pt: list[float], poly: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def _shoelace(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def score_sheet(spec: dict[str, Any], detect: Any, detect_scale: Any) -> dict[str, Any]:
    """Detect one sheet and score it against the manifest."""
    ready = prepared(spec)
    if ready is None:
        return {"id": spec["id"], "split": spec["split"], "missing": True}
    pdf, rooms = ready
    t0 = time.perf_counter()
    res = detect(pdf, spec.get("pt_per_m") or 0.0)
    ms = (time.perf_counter() - t0) * 1000
    cands = res["candidates"]
    k = spec.get("pt_per_m")
    areas = [c for c in cands if c.get("dimension") == "area"]
    lengths = [c for c in cands if c.get("dimension") == "length"]
    counts = [c for c in cands if c.get("dimension") == "count"]
    out: dict[str, Any] = {
        "id": spec["id"],
        "split": spec["split"],
        "kind": spec["kind"],
        "note": res.get("notes"),
        "truncated": res.get("truncated", 0),
        "ms": round(ms),
        "peak_rss_mb": res.get("peak_rss_mb"),
        "n_area": len(areas),
        "n_length": len(lengths),
        "n_count": len(counts),
        "max_conf": round(max((c.get("confidence", 0.0) for c in cands), default=0.0), 2),
    }
    if not spec.get("scan"):
        got = detect_scale(pdf)
        accept = spec.get("scale_accept") or [spec.get("scale_ratio")]
        out["scale"] = {"gt": spec.get("scale_ratio"), "got": got, "ok": got in accept}
    if spec["kind"] not in ("plan",):
        # Not a room plan: any room or wall proposal here is a false positive.
        out["non_plan_fp"] = len(areas) + len(lengths)
        return out
    polys = [[(float(p["x"]), float(p["y"])) for p in c["points"]] for c in areas]
    holds: list[list[str]] = [[r["label"] for r in rooms if _inside(r["at"], poly)] for poly in polys]
    errs: list[float] = []
    matched = 0
    wrong = 0
    outcomes: list[tuple[float, bool]] = []
    per_room = {}
    for i, labels in enumerate(holds):
        conf = float(areas[i].get("confidence", 0.0))
        if not labels:
            continue
        ok = len(labels) == 1
        if ok:
            truth = next(r for r in rooms if r["label"] == labels[0])
            if truth.get("area_m2") and k:
                err = abs(_shoelace(polys[i]) / (k * k) - truth["area_m2"]) / truth["area_m2"]
                errs.append(err * 100)
                ok = err <= _AREA_TOL
        outcomes.append((conf, ok))
        for lab in labels:
            per_room[lab] = ok
        matched += ok
        wrong += not ok
    unlabelled = sum(1 for labels in holds if not labels)
    junk = max(0, unlabelled - int(spec.get("allowed_unlabelled", 0)))
    for i, labels in enumerate(holds):
        if not labels and junk:
            outcomes.append((float(areas[i].get("confidence", 0.0)), False))
    np_ = matched + wrong + junk
    out["rooms"] = {
        "right": matched,
        "labelled": len(rooms),
        "wrong": wrong,
        "unlabelled": unlabelled,
        "junk": junk,
        "p": round(matched / np_, 3) if np_ else 0.0,
        "r": round(matched / len(rooms), 3) if rooms else 0.0,
        "missed": sorted(r["label"] for r in rooms if not per_room.get(r["label"])),
        "area_err_med_pct": round(statistics.median(errs), 2) if errs else None,
    }
    p, r = out["rooms"]["p"], out["rooms"]["r"]
    out["rooms"]["f1"] = round(2 * p * r / (p + r), 3) if p + r else 0.0
    out["conf_outcomes"] = outcomes
    if k and spec.get("total_room_area_m2"):
        total = sum(_shoelace(poly) for poly in polys) / (k * k)
        out["total_area_err_pct"] = round(abs(total - spec["total_room_area_m2"]) / spec["total_room_area_m2"] * 100, 1)
    if k and spec.get("wall_total_m"):
        total = sum(
            sum(
                ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
                for a, b in zip(c["points"], c["points"][1:], strict=False)
            )
            for c in lengths
        )
        out["wall_total_err_pct"] = round(abs(total / k - spec["wall_total_m"]) / spec["wall_total_m"] * 100, 1)
    if spec.get("door_count"):
        best = max((int(c.get("count") or 0) for c in counts), default=0)
        out["doors"] = {"gt": spec["door_count"], "largest_count": best}
    return out


def _auc(outcomes: list[tuple[float, bool]]) -> float | None:
    pos = [c for c, ok in outcomes if ok]
    neg = [c for c, ok in outcomes if not ok]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals for one group of sheets; per-sheet rows stay alongside."""
    plans = [r for r in rows if "rooms" in r]
    others = [r for r in rows if r.get("kind") and r["kind"] != "plan"]
    right = sum(r["rooms"]["right"] for r in plans)
    labelled = sum(r["rooms"]["labelled"] for r in plans)
    np_ = sum(r["rooms"]["right"] + r["rooms"]["wrong"] + r["rooms"]["junk"] for r in plans)
    p = right / np_ if np_ else 0.0
    rec = right / labelled if labelled else 0.0
    scales = [r["scale"]["ok"] for r in rows if "scale" in r]
    outcomes = [o for r in plans for o in r.pop("conf_outcomes", [])]
    return {
        "sheets": len(rows),
        "rooms_p": round(p, 3),
        "rooms_r": round(rec, 3),
        "rooms_f1": round(2 * p * rec / (p + rec), 3) if p + rec else 0.0,
        "non_plan_fp": sum(r.get("non_plan_fp", 0) for r in others),
        "non_plan_sheets_clean": sum(1 for r in others if not r.get("non_plan_fp")),
        "non_plan_sheets": len(others),
        "scale_acc": round(sum(scales) / len(scales), 3) if scales else None,
        "conf_auc": _auc(outcomes),
        "ms_max": max((r.get("ms", 0) for r in rows), default=0),
        "peak_rss_mb_max": max((r.get("peak_rss_mb") or 0.0 for r in rows), default=0.0),
        "rows": rows,
    }
