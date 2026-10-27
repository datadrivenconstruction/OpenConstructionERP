# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Matching​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ quote lines to BOQ positions or tender package items.

The score blends three signals: text similarity of the descriptions (token
overlap and character sequence, so ``Stahlbeton C30/37 Decke`` meets ``Decke
Stahlbeton C30/37``), unit agreement after normalisation, and how close the quoted
quantity is to the reference quantity. When the platform's embedding model is
already loaded, the cosine similarity of the two descriptions joins the text
score, which carries a match across languages; the matcher never loads the model
itself, so a server without it pays nothing.

Every line gets its best candidate, a confidence and up to three alternatives.
A suggestion is never applied on its own: the reviewer confirms or picks another.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from app.modules.quote_capture.numbers import to_decimal
from app.modules.quote_capture.units import normalise_unit

MATCH_THRESHOLD = 0.35
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Candidate:
    position_id: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    unit_rate: Decimal


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.casefold()) if len(t) > 1}


def text_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    seq = SequenceMatcher(None, a.casefold(), b.casefold()).ratio()
    return max(jaccard, 0.6 * jaccard + 0.4 * seq)


def _qty_closeness(q: Decimal | None, ref: Decimal) -> float:
    if q is None or q <= 0 or ref <= 0:
        return 0.0
    ratio = float(min(q, ref) / max(q, ref))
    return ratio


def score(line: dict[str, Any], cand: Candidate, locale: str | None, semantic: float | None = None) -> float:
    text = text_similarity(str(line.get("description") or ""), cand.description)
    if semantic is not None:
        text = max(text, 0.5 * text + 0.5 * semantic)
    unit_ok = 1.0 if normalise_unit(line.get("unit"), locale) == normalise_unit(cand.unit, locale) else 0.0
    qty = _qty_closeness(to_decimal(line.get("quantity")), cand.quantity)
    return round(0.65 * text + 0.25 * unit_ok + 0.10 * qty, 3)


def match_lines(
    lines: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    locale: str | None = None,
    semantic: dict[tuple[int, int], float] | None = None,
) -> list[dict[str, Any] | None]:
    """Return one match suggestion per line (None when nothing clears the threshold).

    ``semantic`` maps ``(line_index, candidate_index)`` to a cosine similarity.
    """
    out: list[dict[str, Any] | None] = []
    for li, line in enumerate(lines):
        scored = sorted(
            ((score(line, cand, locale, (semantic or {}).get((li, ci))), cand) for ci, cand in enumerate(candidates)),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not scored or scored[0][0] < MATCH_THRESHOLD:
            out.append(
                {
                    "position_id": None,
                    "confidence": 0.0,
                    "status": "unmatched",
                    "alternatives": [_alt(s, c) for s, c in scored[:3] if s > 0.15],
                }
            )
            continue
        best_score, best = scored[0]
        out.append(
            {
                "position_id": best.position_id,
                "ordinal": best.ordinal,
                "description": best.description,
                "unit": best.unit,
                "confidence": best_score,
                "status": "suggested",
                "alternatives": [_alt(s, c) for s, c in scored[1:4] if s > 0.15],
            }
        )
    return out


def _alt(s: float, c: Candidate) -> dict[str, Any]:
    return {"position_id": c.position_id, "ordinal": c.ordinal, "description": c.description, "confidence": s}


async def semantic_scores(lines: list[dict[str, Any]], candidates: list[Candidate]) -> dict[tuple[int, int], float]:
    """Cosine similarities from the platform embedder, only when it is already loaded."""
    try:
        from app.core import vector

        if vector.embedder_status().get("state") != "ready" or not lines or not candidates:
            return {}
        texts = [str(ln.get("description") or "") for ln in lines] + [c.description for c in candidates]
        vectors = await vector.encode_texts_async(texts)
    except Exception:  # noqa: BLE001 - semantic boost is optional
        return {}
    qv, cv = vectors[: len(lines)], vectors[len(lines) :]

    def cos(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    return {(i, j): max(0.0, cos(q, c)) for i, q in enumerate(qv) for j, c in enumerate(cv)}
