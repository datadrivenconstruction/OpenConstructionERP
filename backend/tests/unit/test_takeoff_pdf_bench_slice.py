"""Regression slice of the PDF takeoff benchmark (``tests/bench/takeoff_pdf``).

A fixed handful of generated sheets covers the detectors end to end: double
and poche walls, a rotated page, a rotated building on a small 1:200 plan, a
sheet with no plan on it, and a scanned copy for the raster path. Thresholds
sit a little under today's numbers so a real regression fails while the
full benchmark (``python -m tests.bench.takeoff_pdf.scorer``) stays the place
to measure.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")
pytest.importorskip("reportlab")

from tests.bench.takeoff_pdf import generator, scorer  # noqa: E402

# train seeds: double walls on a page rotated 90, poche, 1:200 at 36.7 degrees, no plan
_VECTOR_SEEDS = (1, 9, 34, 3)
_SCAN_SEEDS = (1,)


def _f1(tp: int, np_: int, ng: int) -> float:
    p = tp / np_ if np_ else 0.0
    r = tp / ng if ng else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def _run(pages: list[tuple[bytes, dict]]) -> dict[str, list[int]]:
    tot = {"areas": [0, 0, 0], "walls": [0, 0, 0], "counts": [0, 0, 0], "noise": [0, 0], "scale": [0, 0]}
    for pdf, gt in pages:
        cands = scorer.detect(pdf, gt["pt_per_m"], trace_memory=False)["candidates"]
        if gt["kind"] == "noise":
            tot["noise"][0] += bool(cands)
            tot["noise"][1] += 1
            continue
        for key, fn in (("areas", scorer.score_areas), ("walls", scorer.score_walls)):
            s = fn(cands, gt)
            tot[key] = [a + b for a, b in zip(tot[key], (s["tp"], s["np"], s["ng"]), strict=True)]
        if gt.get("symbols") and not gt.get("scan"):
            s = scorer.score_counts(cands, gt)
            tot["counts"] = [a + b for a, b in zip(tot["counts"], (s["tp"], s["np"], s["ng"]), strict=True)]
    return tot


def test_vector_slice_holds_its_accuracy() -> None:
    pages = [generator.make_page(s) for s in _VECTOR_SEEDS]
    tot = _run(pages)
    assert _f1(*tot["areas"]) >= 0.92, tot
    assert _f1(*tot["walls"]) >= 0.85, tot
    assert _f1(*tot["counts"]) >= 0.75, tot
    assert tot["noise"] == [0, 1], "a sheet with no plan must yield no candidates"
    for pdf, gt in pages:
        assert scorer.detect_scale(pdf) == gt["scale"]["ratio"], gt["scale"]


def test_scan_slice_holds_its_accuracy() -> None:
    tot = _run([generator.make_scan(s) for s in _SCAN_SEEDS])
    assert _f1(*tot["areas"]) >= 0.8, tot
    assert _f1(*tot["walls"]) >= 0.75, tot
