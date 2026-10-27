# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ extraction pipeline: rules first, the configured AI model second.

The rules parser always runs. When the user has an AI provider configured (any
provider the AI settings support, local ones included) the document text goes to
the model with a language-agnostic instruction; its answer is merged over the
rules result line by line. When no provider is configured, the call fails or the
answer is not JSON, the rules result stands and ``engine`` says so. Nothing the
model returns is trusted blindly: every value keeps a confidence the arithmetic
checks can lower, and a source anchor found by locating the model's quoted text
in the document.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from app.modules.quote_capture.documents import DocLine, QuoteDocument
from app.modules.quote_capture.numbers import plain, to_decimal
from app.modules.quote_capture.parsing import field, parse_quote
from app.modules.quote_capture.units import normalise_unit

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 24_000
HEADER_FIELDS = (
    "supplier",
    "quote_date",
    "valid_until",
    "currency",
    "payment_terms",
    "delivery",
    "quote_total",
    "tax_basis",
    "tax_rate",
)

SYSTEM_PROMPT = (
    "You read supplier and subcontractor quotations for construction work. The document can be written in any "
    "language and use any number format. Do not translate anything: copy descriptions and conditions verbatim in "
    "the document's own language and script. Return numbers as plain decimals with a point and no grouping "
    "(1234.5). Return dates as YYYY-MM-DD. Use ISO 4217 currency codes. For every value give a confidence between "
    "0 and 1 and the exact source text it was read from. Never invent a value that is not in the document: leave "
    "it null. Answer with one JSON object only."
)

_SCHEMA_HINT = (
    '{"header": {"supplier": {"value": str, "confidence": float, "source_text": str}, "quote_date": ..., '
    '"valid_until": ..., "currency": ..., "payment_terms": ..., "delivery": ..., "quote_total": ..., '
    '"tax_basis": "net"|"gross", "tax_rate": percent}, '
    '"lines": [{"description": str, "quantity": number, "unit": str, "unit_rate": number, "total": number, '
    '"confidence": float, "source_text": str}], '
    '"notes": [{"kind": "exclusion"|"qualification"|"escalation"|"validity"|"payment"|"delivery", '
    '"text": str, "confidence": float, "source_text": str}]}'
)

LlmCall = Callable[[str, str], Awaitable[str | None]]


def build_prompt(document_text: str) -> str:
    return (
        "Extract the quotation below into this JSON shape:\n"
        f"{_SCHEMA_HINT}\n"
        "Line items are the priced rows. Notes are scope exclusions, qualifications, price escalation clauses and "
        "other conditions; a tax remark such as 'excluding VAT' is not an exclusion.\n"
        "--- DOCUMENT ---\n"
        f"{document_text[:MAX_PROMPT_CHARS]}"
    )


def locate(source_text: str | None, lines: list[DocLine]) -> dict | None:
    """Anchor of the document line that best contains the model's quoted text."""
    if not source_text:
        return None
    needle = " ".join(str(source_text).split()).casefold()[:200]
    if not needle:
        return None
    best: tuple[float, DocLine | None] = (0.0, None)
    for line in lines:
        hay = " ".join(line.text.split()).casefold()
        if needle in hay:
            return line.anchor
        score = SequenceMatcher(None, needle, hay).ratio()
        if score > best[0]:
            best = (score, line)
    return best[1].anchor if best[1] is not None and best[0] >= 0.6 else None


def _conf(raw: Any, default: float = 0.5) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _arith_conf(qty: Decimal | None, rate: Decimal | None, total: Decimal | None, conf: float) -> float:
    if qty is None or rate is None:
        return min(conf, 0.3)
    if total is not None and abs(qty * rate - total) > max(Decimal("0.02"), abs(total) * Decimal("0.0005")):
        return min(conf, 0.45)
    return conf


def merge_llm(rules: dict[str, Any], llm: dict[str, Any], lines: list[DocLine], locale: str | None) -> dict[str, Any]:
    """Overlay the model's answer on the rules result, keeping anchors and honest confidences."""
    header = dict(rules["header"])
    for key in HEADER_FIELDS:
        got = (llm.get("header") or {}).get(key)
        if not isinstance(got, dict) or got.get("value") in (None, ""):
            continue
        value = got["value"]
        if key in {"quote_total", "tax_rate"}:
            number = to_decimal(value)
            if number is None:
                continue
            value = plain(number)
        conf = _conf(got.get("confidence"))
        anchor = locate(got.get("source_text"), lines) or (header.get(key) or {}).get("anchor")
        if anchor is None:
            conf = min(conf, 0.5)  # the model's text was not found in the document
        header[key] = field(str(value)[:255], conf, anchor, source="llm")
    items: list[dict[str, Any]] = []
    for row in llm.get("lines") or []:
        if not isinstance(row, dict) or not str(row.get("description") or "").strip():
            continue
        qty = to_decimal(row.get("quantity"))
        rate = to_decimal(row.get("unit_rate"))
        total = to_decimal(row.get("total"))
        if total is None and qty is not None and rate is not None:
            total = qty * rate
        anchor = locate(row.get("source_text") or row.get("description"), lines)
        conf = _arith_conf(qty, rate, total, _conf(row.get("confidence")))
        if anchor is None:
            conf = min(conf, 0.5)
        unit_raw = str(row.get("unit") or "")
        items.append(
            {
                "description": str(row["description"]).strip()[:1000],
                "quantity": plain(qty) if qty is not None else "",
                "unit_raw": unit_raw,
                "unit": normalise_unit(unit_raw, locale),
                "unit_rate": plain(rate) if rate is not None else "",
                "total": plain(total) if total is not None else "",
                "confidence": round(conf, 2),
                "anchor": anchor,
                "source": "llm",
            }
        )
    notes = list(rules["notes"])
    seen = {" ".join(n["text"].split()).casefold() for n in notes}
    for note in llm.get("notes") or []:
        if not isinstance(note, dict) or not note.get("text"):
            continue
        key = " ".join(str(note["text"]).split()).casefold()
        if any(key in s or s in key for s in seen):
            continue
        kind = str(note.get("kind") or "qualification")
        notes.append(
            {
                "kind": kind
                if kind in {"exclusion", "qualification", "escalation", "validity", "payment", "delivery"}
                else "qualification",
                "text": str(note["text"])[:500],
                "confidence": _conf(note.get("confidence")),
                "anchor": locate(note.get("source_text") or note.get("text"), lines),
                "source": "llm",
            }
        )
        seen.add(key)
    return {"header": header, "lines": items or rules["lines"], "notes": notes}


def finalise(result: dict[str, Any]) -> dict[str, Any]:
    """Give lines and notes stable ids, review flags and a frozen copy of the machine values."""
    for idx, line in enumerate(result["lines"], start=1):
        line.setdefault("id", f"L{idx}")
        line.setdefault("source", "rules")
        line.setdefault("field_anchors", {})
        line["reviewed"] = False
        line["match"] = None
        line["machine"] = {k: line.get(k) for k in ("description", "quantity", "unit", "unit_rate", "total")}
    for idx, note in enumerate(result["notes"], start=1):
        note.setdefault("id", f"N{idx}")
        note["acknowledged"] = False
    return result


async def extract(
    document: QuoteDocument,
    *,
    locale: str | None,
    llm_call: LlmCall | None,
    today: date | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run the pipeline. Returns ``(engine, {"header", "lines", "notes"})``.

    ``llm_call(system, prompt)`` returns the model's raw text, or None when no
    provider is configured; any exception it raises degrades to rules only.
    """
    rules = parse_quote(document.lines, locale, today=today)
    engine = "rules"
    if llm_call is not None and document.lines:
        raw: str | None = None
        try:
            raw = await llm_call(SYSTEM_PROMPT, build_prompt(document.text))
        except Exception:  # noqa: BLE001 - any provider failure falls back to the rules result
            logger.info("quote extraction: AI call failed, using rules only", exc_info=True)
        if raw:
            from app.modules.ai.ai_client import extract_json

            try:
                parsed = extract_json(raw)
            except Exception:  # noqa: BLE001 - unparsable answer is a degradation, not an error
                parsed = None
            if isinstance(parsed, dict):
                rules = merge_llm(rules, parsed, document.lines, locale)
                engine = "llm"
    return engine, finalise(rules)
