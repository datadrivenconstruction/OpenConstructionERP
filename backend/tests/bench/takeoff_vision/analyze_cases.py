"""Bench for the document text analyzer's belt (``takeoff.text_analyze``).

Generated specification texts in three number styles (1,234.5 / 1.234,5 /
1 234,5) and a mock model answer per text: the true items with unit spelling
noise, repeated rows, and invented quantities. Scored: how many invented
quantities stay below the medium band, how many true items stay at or above
it, how many repeats are merged.

    cd backend
    python -m tests.bench.takeoff_vision.analyze_cases
"""

from __future__ import annotations

import json
import random
import sys
from typing import Any

from app.modules.takeoff.text_analyze import check_items

MEDIUM = 0.62
_WORKS = [
    ("Concrete slab C30/37, 200 mm", "m3", "Concrete", ["m3", "m³", "cbm"]),
    ("Floor screed 50 mm", "m2", "Finishes", ["m2", "m²", "sqm"]),
    ("Brick wall 240 mm", "m2", "Masonry", ["m2", "qm"]),
    ("Skirting board oak", "m", "Finishes", ["m", "lm"]),
    ("Internal door 0.9 x 2.1 m", "pcs", "Doors", ["pcs", "nr", "Stk"]),
    ("Reinforcement B500B", "t", "Concrete", ["t", "to"]),
    ("Ceramic wall tiles", "m2", "Finishes", ["m2", "sq m"]),
    ("Gypsum partition 100 mm", "m2", "Drywall", ["m2", "m²"]),
]


def _fmt(v: float, style: int) -> str:
    s = f"{v:,.2f}"
    if style == 1:
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    if style == 2:
        return s.replace(",", " ").replace(".", ",")
    return s


def make_case(seed: int) -> tuple[str, list[dict[str, Any]], list[str]]:
    rng = random.Random(seed)
    style = seed % 3
    works = rng.sample(_WORKS, 6)
    lines, items, labels = [f"Bill of quantities, lot {seed}"], [], []
    for i, (desc, unit, cat, spellings) in enumerate(works, 1):
        qty = round(rng.uniform(1.5, 2500.0), 2)
        lines.append(f"{i:02d}  {desc}  {_fmt(qty, style)} {unit}")
        items.append(
            {"description": desc, "quantity": qty, "unit": rng.choice(spellings), "category": cat, "confidence": 0.85}
        )
        labels.append("true")
    for it in rng.sample(items[:6], 2):
        items.append(dict(it, unit=it["unit"]))
        labels.append("repeat")
    for desc, unit, cat, _sp in rng.sample([w for w in _WORKS if w not in works], 2):
        items.append(
            {
                "description": desc,
                "quantity": round(rng.uniform(1.5, 2500.0), 2),
                "unit": unit,
                "category": cat,
                "confidence": 0.8,
            }
        )
        labels.append("invented")
    return "\n".join(lines), items, labels


def evaluate(seeds: list[int], pipeline: str = "current") -> dict[str, Any]:
    inv_caught = inv = true_kept = true_n = rep_merged = rep_n = 0
    unit_buckets = 0
    canon = {w[0]: w[1] for w in _WORKS}
    for seed in seeds:
        text, items, labels = make_case(seed)
        if pipeline == "baseline":
            rows = [(it["description"], it["unit"], it["quantity"], it["confidence"]) for it in items]
        else:
            checked = check_items(items, text)
            rows = [(r.description, r.unit, r.quantity, r.confidence) for r in checked]
        spellings: dict[str, set[str]] = {}
        for d, u, _q, _c in rows:
            spellings.setdefault(canon[d], set()).add(u)
        unit_buckets += sum(len(v) - 1 for v in spellings.values())
        by_key = {}
        for d, u, q, c in rows:
            by_key.setdefault((d, round(q, 3)), []).append((u, c))
        for it, lab in zip(items, labels, strict=True):
            hits = by_key.get((it["description"], round(it["quantity"], 3)), [])
            if lab == "invented":
                inv += 1
                inv_caught += int(all(c < MEDIUM for _u, c in hits))
            elif lab == "true":
                true_n += 1
                true_kept += int(any(c >= MEDIUM for _u, c in hits))
            else:
                rep_n += 1
                rep_merged += int(len(hits) == 1)
    return {
        "cases": len(seeds),
        "invented_caught": round(inv_caught / inv, 4),
        "true_kept_confident": round(true_kept / true_n, 4),
        "repeats_merged": round(rep_merged / rep_n, 4),
        "extra_unit_spellings": unit_buckets,
    }


if __name__ == "__main__":
    import datetime as _dt

    from .run_bench import LEDGER, _git_sha

    seeds = list(range(60))
    line = {
        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bench": "text_analyze",
        "git": _git_sha(),
        "results": {"baseline": evaluate(seeds, "baseline"), "current": evaluate(seeds, "current")},
    }
    print(json.dumps(line, indent=1))
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.exit(0)
