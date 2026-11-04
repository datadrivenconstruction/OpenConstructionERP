"""Deterministic checks on BOQ items an LLM extracted from a document's text.

The model reads the text and proposes items; this module decides how much of
each proposal the text actually supports. A quantity that appears nowhere in
the source is the typical hallucination, so it caps the item below the medium
confidence band; repeated rows are merged; unit spellings are normalised so
category subtotals do not split ``m2`` from ``sqm``. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Below the 0.62 medium band: an ungrounded quantity always needs a human look.
UNGROUNDED_MAX_CONFIDENCE = 0.55
GROUNDED_EVIDENCE = 0.95
_REL_TOL = 0.001  # a model may round 1,234.56 to 1234.6, not further

_UNIT_ALIASES: dict[str, str] = {
    "m2": "m2",
    "m²": "m2",
    "sqm": "m2",
    "sq.m": "m2",
    "sq m": "m2",
    "qm": "m2",
    "m^2": "m2",
    "m3": "m3",
    "m³": "m3",
    "cbm": "m3",
    "cu.m": "m3",
    "cu m": "m3",
    "m^3": "m3",
    "m": "m",
    "lm": "m",
    "rm": "m",
    "lfm": "m",
    "meter": "m",
    "metre": "m",
    "meters": "m",
    "metres": "m",
    "pcs": "pcs",
    "pc": "pcs",
    "pce": "pcs",
    "nr": "pcs",
    "no": "pcs",
    "no.": "pcs",
    "ea": "pcs",
    "each": "pcs",
    "stk": "pcs",
    "st": "pcs",
    "unit": "pcs",
    "units": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "kg": "kg",
    "t": "t",
    "to": "t",
    "tonne": "t",
    "tonnes": "t",
    "ton": "t",
    "l": "l",
    "ltr": "l",
    "litre": "l",
    "liter": "l",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "std": "h",
    "ls": "lsum",
    "lump sum": "lsum",
    "psch": "lsum",
    "lsum": "lsum",
    "item": "lsum",
    "sqft": "ft2",
    "sq ft": "ft2",
    "ft2": "ft2",
    "ft²": "ft2",
    "sf": "ft2",
    "lf": "ft",
    "ft": "ft",
    "cy": "yd3",
    "yd3": "yd3",
    "cu yd": "yd3",
    "sy": "yd2",
    "yd2": "yd2",
}

# 1,234.56 | 1.234,56 | 1 234,5 | 12.5 | 12,5 | 1234
_NUMBER = re.compile(r"(?<![\w.,])\d{1,3}(?:[   .,]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])\d+(?:[.,]\d+)?")


@dataclass
class CheckedItem:
    description: str
    quantity: float
    unit: str
    category: str
    confidence: float
    grounded: bool
    flags: list[str] = field(default_factory=list)
    evidence: str = ""


def normalize_unit(raw: str) -> str:
    """Canonical spelling of a unit; unknown units come back trimmed, as given."""
    key = re.sub(r"\s+", " ", (raw or "").strip().lower()).rstrip(".")
    if not key:
        return "pcs"
    return _UNIT_ALIASES.get(key, _UNIT_ALIASES.get(key + ".", raw.strip()))


def _to_float(token: str) -> float | None:
    t = token.replace(" ", " ").replace(" ", " ")
    if " " in t:
        t = t.replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = (
            head.replace(",", "") + tail
            if len(tail) == 3 and head.isdigit() and len(head) <= 3
            else t.replace(",", ".")
        )
    try:
        return float(t)
    except ValueError:
        return None


def source_numbers(text: str) -> list[tuple[float, int]]:
    """Every number in the text with its offset, both readings of an ambiguous ``1,250``."""
    out: list[tuple[float, int]] = []
    for m in _NUMBER.finditer(text or ""):
        tok = m.group(0)
        v = _to_float(tok)
        if v is not None:
            out.append((v, m.start()))
        if re.fullmatch(r"\d{1,3}[.,]\d{3}", tok):
            alt = float(tok.replace(",", ".")) if "," in tok else float(tok.replace(".", ""))
            if alt != v:
                out.append((alt, m.start()))
    return out


def _norm_desc(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def check_items(items: list[dict[str, Any]], source_text: str) -> list[CheckedItem]:
    """Ground, normalise and de-duplicate parsed items.

    Each item needs ``description``, ``quantity`` (float, already band-clamped),
    ``unit``, ``category`` and ``confidence`` (the model's score or the router's
    heuristic). Order is preserved; a repeat of an earlier row is dropped and
    noted on the row it repeats.
    """
    numbers = source_numbers(source_text)
    out: list[CheckedItem] = []
    seen: dict[tuple[str, str, float], CheckedItem] = {}
    for it in items:
        qty = float(it.get("quantity") or 0.0)
        unit = normalize_unit(str(it.get("unit") or ""))
        desc = str(it.get("description") or "").strip()
        key = (_norm_desc(desc), unit, round(qty, 3))
        if key in seen:
            if "merged_duplicate" not in seen[key].flags:
                seen[key].flags.append("merged_duplicate")
            continue
        llm = float(it.get("confidence") or 0.0)
        flags: list[str] = []
        grounded, evidence = False, ""
        if qty > 0:
            hit = next((pos for v, pos in numbers if abs(v - qty) <= _REL_TOL * max(abs(qty), 1e-9)), None)
            if hit is not None:
                grounded = True
                evidence = source_text[max(0, hit - 40) : hit + 40].replace("\n", " ").strip()
                conf = 0.5 * llm + 0.5 * GROUNDED_EVIDENCE
            else:
                flags.append("quantity_not_in_source")
                conf = min(llm, UNGROUNDED_MAX_CONFIDENCE)
        else:
            flags.append("no_quantity")
            conf = min(llm, 0.4)
        if unit != str(it.get("unit") or "").strip():
            flags.append("unit_normalized")
        row = CheckedItem(
            description=desc,
            quantity=qty,
            unit=unit,
            category=str(it.get("category") or "General").strip() or "General",
            confidence=round(max(0.0, min(1.0, conf)), 2),
            grounded=grounded,
            flags=flags,
            evidence=evidence,
        )
        seen[key] = row
        out.append(row)
    return out
