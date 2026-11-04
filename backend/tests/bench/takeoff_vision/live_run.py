"""Opt-in: score a real vision model on generated plans and append to ``ledger.jsonl``.

Sends each plan's page image with the production prompt, then scores the raw
answer (``baseline``) and the belt's output (``current``) like the mock runs.
It costs money, so it never runs in CI. Set a key the app's ``call_ai`` accepts:

    cd backend
    set OE_BENCH_AI_PROVIDER=anthropic
    set OE_BENCH_AI_API_KEY=...
    python -m tests.bench.takeoff_vision.live_run --seeds 0 3 7 500 505

``OE_BENCH_AI_MODEL`` overrides the provider's default model.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as _dt
import json
import os
import sys
import time

from app.modules.ai.ai_client import call_ai, extract_json
from app.modules.ai.prompts import (
    PLAN_READ_ROOMS_INSTRUCTION,
    PLAN_READ_SCALE_INSTRUCTION,
    PLAN_READ_SYMBOLS_INSTRUCTION,
    PLAN_READ_VISION_PROMPT,
    PLAN_READ_VISION_SYSTEM_PROMPT,
)
from app.modules.takeoff import plan_read as pr

from .mock_model import MockResponse
from .run_bench import LEDGER, _git_sha, plan_and_vector
from .score import aggregate, baseline_pipeline, current_pipeline, score_plan


async def _read(seed: int, provider: str, key: str, model: str | None) -> tuple[MockResponse, bytes | None, int]:
    plan, vector = plan_and_vector(seed)
    png, media_type, dpi, w_pt, h_pt = pr.rasterize_page(plan.pdf, 1)
    prompt = PLAN_READ_VISION_PROMPT.format(
        mode_instructions="\n\n".join(
            [PLAN_READ_SCALE_INSTRUCTION, PLAN_READ_ROOMS_INSTRUCTION, PLAN_READ_SYMBOLS_INSTRUCTION]
        ),
        discipline_hint="",
    )
    raw, tokens = await call_ai(
        provider=provider,
        api_key=key,
        system=PLAN_READ_VISION_SYSTEM_PROMPT,
        prompt=prompt,
        image_base64=base64.b64encode(png).decode("ascii"),
        image_media_type=media_type,
        max_tokens=4096,
        model=model,
    )
    body = extract_json(raw) or {}
    px = (round(w_pt * dpi / 72.0), round(h_pt * dpi / 72.0))
    has_walls = vector is not None and vector.has_walls()
    return MockResponse(f"plan-{seed}", "live", body, [], px), (None if has_walls else png), int(tokens or 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 3, 7, 500, 505])
    ap.add_argument("--no-ledger", action="store_true")
    args = ap.parse_args(argv)
    key = os.environ.get("OE_BENCH_AI_API_KEY", "")
    provider = os.environ.get("OE_BENCH_AI_PROVIDER", "anthropic")
    model = os.environ.get("OE_BENCH_AI_MODEL") or None
    if not key:
        print("OE_BENCH_AI_API_KEY is not set; nothing to run.", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    scores: dict[str, list] = {"baseline": [], "current": []}
    tokens = 0
    for seed in args.seeds:
        plan, vector = plan_and_vector(seed)
        resp, png, used = asyncio.run(_read(seed, provider, key, model))
        tokens += used
        scores["baseline"].append(score_plan(plan, baseline_pipeline(plan, resp)))
        scores["current"].append(score_plan(plan, current_pipeline(plan, resp, vector, png)))
    line = {
        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bench": "plan_read",
        "git": _git_sha(),
        "split": "live",
        "seeds": args.seeds,
        "model": f"{provider}:{model or 'default'}",
        "tokens": tokens,
        "seconds": round(time.monotonic() - t0, 1),
        "results": {p: {"realistic": aggregate(s)} for p, s in scores.items()},
    }
    print(json.dumps(line, indent=1))
    if not args.no_ledger:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
