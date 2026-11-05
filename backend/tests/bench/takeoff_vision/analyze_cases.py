"""Bench for the document text analyzer's belt (``takeoff.text_analyze``).

Generated specification texts in three number styles (1,234.5 / 1.234,5 /
1 234,5) and a mock model answer per text: the true items with unit spelling
noise, the same item listed for a second floor, and invented quantities, some
copied from a date or drawing number in the header. Scored: invented quantities
kept below the medium band, true items kept at or above it, second-floor rows
kept (quantity not lost), and that no score ever rises above the model's.

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
    day, month, sheet = rng.randint(10, 28), rng.randint(10, 12), rng.randint(11, 99)
    lines = [f"Bill of quantities, lot {seed}, issued {day}.{month}.2026, drawing {sheet}"]
    items, labels = [], []
    for i, (desc, unit, cat, spellings) in enumerate(works, 1):
        qty = round(rng.uniform(1.5, 2500.0), 2)
        lines.append(f"{i:02d}  Ground floor: {desc}  {_fmt(qty, style)} {unit}")
        conf = round(rng.uniform(0.65, 0.95), 2)
        items.append(
            {"description": desc, "quantity": qty, "unit": rng.choice(spellings), "category": cat, "confidence": conf}
        )
        labels.append("true")
    for it in rng.sample(items[:6], 2):
        lines.append(
            f"    Upper floor: {it['description']}  {_fmt(it['quantity'], style)} {canon_unit(it['description'])}"
        )
        items.append(dict(it))
        labels.append("repeat")
    unused = [w for w in _WORKS if w not in works]
    for k, (desc, unit, cat, _sp) in enumerate(rng.sample(unused, 2)):
        qty = float(f"{day}.{month}") if k == 0 else float(sheet)
        if seed % 2:
            qty = round(rng.uniform(1.5, 2500.0), 2)
        items.append({"description": desc, "quantity": qty, "unit": unit, "category": cat, "confidence": 0.8})
        labels.append("invented")
    return "\n".join(lines), items, labels


def canon_unit(desc: str) -> str:
    return next(w[1] for w in _WORKS if w[0] == desc)


def evaluate(seeds: list[int], pipeline: str = "current") -> dict[str, Any]:
    inv_caught = inv = true_kept = true_n = rep_kept = rep_n = raised = 0
    unit_buckets = 0
    canon = {w[0]: w[1] for w in _WORKS}
    for seed in seeds:
        text, items, labels = make_case(seed)
        if pipeline == "baseline":
            rows = [(it["description"], it["unit"], it["quantity"], it["confidence"]) for it in items]
        else:
            checked = check_items(items, text)
            rows = [(r.description, r.unit, r.quantity, r.confidence) for r in checked]
            raised += sum(r.confidence > it["confidence"] + 1e-9 for r, it in zip(checked, items, strict=True))
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
                rep_kept += int(len(hits) == 2)
    return {
        "cases": len(seeds),
        "invented_caught": round(inv_caught / inv, 4),
        "true_kept_confident": round(true_kept / true_n, 4),
        "second_floor_rows_kept": round(rep_kept / rep_n, 4),
        "scores_raised": raised,
        "extra_unit_spellings": unit_buckets,
    }


if __name__ == "__main__":
    seeds = list(range(60))
    print(json.dumps({"baseline": evaluate(seeds, "baseline"), "current": evaluate(seeds, "current")}, indent=1))
    sys.exit(0)
