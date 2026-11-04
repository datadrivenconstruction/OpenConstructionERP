"""Run the plan-read accuracy benchmark and append one line to ``ledger.jsonl``.

    cd backend
    python -m tests.bench.takeoff_vision.run_bench --split train
    python -m tests.bench.takeoff_vision.run_bench --split holdout --pipeline current

Splits are seed ranges of the plan generator (``plans.TRAIN_SEEDS`` /
``HOLDOUT_SEEDS``); tune on ``train`` only. ``--no-ledger`` skips the append.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
import time
from functools import cache
from pathlib import Path
from typing import Any

from app.modules.takeoff import plan_read as pr

from .mock_model import adversarial_response, realistic_response
from .plans import FAST_SEEDS, HOLDOUT_SEEDS, TRAIN_SEEDS, Plan, generate_plan
from .score import aggregate, baseline_pipeline, catch_injections, current_pipeline, score_plan

LEDGER = Path(__file__).with_name("ledger.jsonl")
SPLITS = {"train": TRAIN_SEEDS, "holdout": HOLDOUT_SEEDS, "fast": FAST_SEEDS}


@cache
def plan_and_vector(seed: int) -> tuple[Plan, pr.VectorLayer | None]:
    plan = generate_plan(seed)
    return plan, pr.extract_vector_layer(plan.pdf, 1)


@cache
def page_png(seed: int) -> bytes | None:
    """The image the service sends to the model, for sheets without vector walls."""
    plan, vector = plan_and_vector(seed)
    if vector is not None and vector.has_walls():
        return None
    return pr.rasterize_page(plan.pdf, 1)[0]


def evaluate(seeds: list[int], pipeline: str) -> dict[str, Any]:
    """Score one pipeline on the given plans, realistic and adversarial."""
    real, adv, catches = [], [], []
    vector_scores, raster_scores = [], []
    for seed in seeds:
        plan, vector = plan_and_vector(seed)
        png = page_png(seed)
        for profile in ("realistic", "adversarial"):
            resp = realistic_response(plan, seed) if profile == "realistic" else adversarial_response(plan, seed)
            props = (
                baseline_pipeline(plan, resp) if pipeline == "baseline" else current_pipeline(plan, resp, vector, png)
            )
            sc = score_plan(plan, props)
            if profile == "realistic":
                real.append(sc)
                (vector_scores if vector is not None and vector.has_walls() else raster_scores).append(sc)
                catches.extend(catch_injections(plan, resp, props))
            else:
                adv.append(sc)
                catches.extend(catch_injections(plan, resp, props))
    return {
        "realistic": aggregate(real),
        "realistic_vector_pdf": aggregate(vector_scores),
        "realistic_raster_pdf": aggregate(raster_scores),
        "adversarial": aggregate(adv, catches),
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=sorted(SPLITS), default="train")
    ap.add_argument("--pipeline", choices=["baseline", "current", "both"], default="both")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    seeds = SPLITS[args.split]
    t0 = time.monotonic()
    pipelines = ["baseline", "current"] if args.pipeline == "both" else [args.pipeline]
    results = {p: evaluate(seeds, p) for p in pipelines}
    line = {
        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bench": "plan_read",
        "git": _git_sha(),
        "split": args.split,
        "seeds": [seeds[0], seeds[-1]],
        "model": "mock",
        "note": args.note,
        "seconds": round(time.monotonic() - t0, 1),
        "results": results,
    }
    print(json.dumps(line, indent=1))
    if not args.no_ledger:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
