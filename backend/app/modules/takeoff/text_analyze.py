"""Deterministic checks on BOQ items an LLM extracted from a document's text.

The model reads the text and proposes items; this module decides how much of
each proposal the text actually supports. A quantity that appears nowhere in
the source (on a line that describes the item, with no other unit) is the
typical hallucination, so it caps the item below the medium confidence band.
Finding the number never raises the model's score. Repeated rows are kept (the
same door on two floors is two doors) and flagged; unit spellings are
normalised so subtotals do not split ``m2`` from ``sqm``. Pure, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Below the 0.62 medium band: an ungrounded quantity always needs a human look.
UNGROUNDED_MAX_CONFIDENCE = 0.55
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


def source_numbers(text: str) -> list[tuple[float, int, int]]:
    """Every number in the text with its span, both readings of an ambiguous ``1,250``.

    Parts of dates (``12.05.2024``) are skipped.
    """
    out: list[tuple[float, int, int]] = []
    text = text or ""
    for m in _NUMBER.finditer(text):
        tok = m.group(0)
        if re.match(r"[.,/]\d", text[m.end() : m.end() + 2]) or re.search(
            r"\d[./]$", text[max(0, m.start() - 2) : m.start()]
        ):
            continue
        v = _to_float(tok)
        if v is not None:
            out.append((v, m.start(), m.end()))
        if re.fullmatch(r"\d{1,3}[.,]\d{3}", tok):
            alt = float(tok.replace(",", ".")) if "," in tok else float(tok.replace(".", ""))
            if alt != v:
                out.append((alt, m.start(), m.end()))
    return out


def _norm_desc(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


_UNIT_AFTER = re.compile(r"[ \t]*([^\W\d_][\w.²³^/ ]{0,7})")


def _unit_after(text: str, end: int) -> str | None:
    m = _UNIT_AFTER.match(text, end)
    if not m:
        return None
    words = m.group(1).split()
    for n in (2, 1):
        if len(words) >= n:
            u = normalize_unit(" ".join(words[:n]))
            if u in _UNIT_ALIASES.values():
                return u
    return None


def _words(text: str) -> set[str]:
    """Words that can tie a line to an item; short ones only when nothing longer exists."""
    folded = text.casefold()
    return set(re.findall(r"[^\W\d_]{4,}", folded)) or set(re.findall(r"[^\W\d_]{2,}", folded))


def _share_a_word(a: set[str], b: set[str]) -> bool:
    # A shared stem counts: Mauerwerk / Mauerwerks, door / doors.
    return any(x.startswith(y) or y.startswith(x) for x in a for y in b if min(len(x), len(y)) >= 4) or bool(a & b)


def _context_line(text: str, start: int, end: int) -> str:
    """The line describing a number: its own, or the one above when it holds only the number.

    PDF text often breaks a table row into one line per cell.
    """
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    b = b if b >= 0 else len(text)
    own = text[a:start] + " " + text[end:b]
    if any(normalize_unit(w) not in _UNIT_ALIASES.values() for w in re.findall(r"[^\W\d_]{2,}", own)):
        return own
    above = text[:a].rstrip()
    return above[above.rfind("\n") + 1 :]


def _grounding(qty: float, unit: str, desc: str, text: str, numbers: list[tuple[float, int, int]]) -> int | None:
    """Offset of the source number that backs ``qty``, or ``None``.

    The number's line must describe the item (share a word with it) and must not
    carry a different unit. A matching value and unit alone back nothing: an
    invented item can copy ``140.00 m2`` from another row.
    """
    words = _words(desc)
    for v, start, end in numbers:
        if abs(v - qty) > _REL_TOL * max(abs(qty), 1e-9):
            continue
        found_unit = _unit_after(text, end)
        if found_unit is not None and found_unit != unit:
            continue
        if _share_a_word(words, _words(_context_line(text, start, end))):
            return start
    return None


def check_items(items: list[dict[str, Any]], source_text: str) -> list[CheckedItem]:
    """Ground and normalise parsed items; never merge or drop one.

    Each item needs ``description``, ``quantity`` (float, already band-clamped),
    ``unit``, ``category`` and ``confidence`` (the model's score or the router's
    heuristic). Order is preserved; a row identical to an earlier one is kept
    and flagged ``repeated_line`` for the estimator to confirm.
    """
    numbers = source_numbers(source_text)
    out: list[CheckedItem] = []
    seen: set[tuple[str, str, float]] = set()
    for it in items:
        qty = float(it.get("quantity") or 0.0)
        unit = normalize_unit(str(it.get("unit") or ""))
        desc = str(it.get("description") or "").strip()
        key = (_norm_desc(desc), unit, round(qty, 3))
        llm = float(it.get("confidence") or 0.0)
        flags: list[str] = []
        if key in seen:
            flags.append("repeated_line")
        seen.add(key)
        grounded, evidence = False, ""
        if qty > 0:
            hit = _grounding(qty, unit, desc, source_text, numbers)
            if hit is not None:
                grounded = True
                evidence = source_text[max(0, hit - 40) : hit + 40].replace("\n", " ").strip()
                conf = llm
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
        out.append(row)
    return out
