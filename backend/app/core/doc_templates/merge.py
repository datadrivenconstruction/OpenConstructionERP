# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Merge engine for document and email wording.

User text is data. The only construct is ``{{ path }}`` where ``path`` is a
dotted lower-case name the generator supplies (``project.name``,
``doc.total``). There are no expressions, filters, loops, attribute access or
calls; anything else between double braces is a malformed token that renders
empty and fails validation. Values are looked up in a flat dict and inserted as
plain text; escaping for HTML or reportlab is the caller's job (see
:mod:`app.core.doc_templates.markup`).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping

__all__ = ["FIELD_RE", "TOKEN_RE", "fields_in", "malformed_tokens", "render", "unknown_fields"]

#: Any double-brace token, shortest match, single line.
TOKEN_RE = re.compile(r"\{\{([^{}\n]{0,120})\}\}")
#: A well-formed field path inside a token.
FIELD_RE = re.compile(r"^\s*([a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){0,3})\s*$")


def _path(inner: str) -> str | None:
    match = FIELD_RE.match(inner)
    return match.group(1) if match else None


def fields_in(text: str | None) -> list[str]:
    """Well-formed field paths used in *text*, in order, without duplicates."""
    seen: dict[str, None] = {}
    for token in TOKEN_RE.finditer(text or ""):
        path = _path(token.group(1))
        if path:
            seen.setdefault(path, None)
    return list(seen)


def malformed_tokens(text: str | None) -> list[str]:
    """Double-brace tokens that are not a plain field path (``{{ a + b }}``, ``{{x|upper}}``)."""
    return [m.group(0) for m in TOKEN_RE.finditer(text or "") if _path(m.group(1)) is None]


def unknown_fields(text: str | None, known: Collection[str]) -> list[str]:
    """Tokens in *text* that are not a field of the document, as written by the user."""
    out: list[str] = []
    for token in TOKEN_RE.finditer(text or ""):
        path = _path(token.group(1))
        if path is None or path not in known:
            out.append(path or token.group(0))
    return list(dict.fromkeys(out))


def render(text: str | None, values: Mapping[str, object], known: Collection[str] | None = None) -> str:
    """Replace every token in *text* by its value.

    A known field without a value, an unknown field and a malformed token all
    render as an empty string, so a broken template never prints braces or
    leaks anything to the reader. Never raises.

    Args:
        text: The user's wording.
        values: Flat ``path -> value`` dict built by the generator.
        known: The kind's declared fields; a value whose path is not declared is
            ignored, so a generator cannot leak an undeclared value either.
    """

    def _sub(match: re.Match[str]) -> str:
        path = _path(match.group(1))
        if path is None or (known is not None and path not in known):
            return ""
        value = values.get(path)
        return "" if value is None else str(value)

    try:
        return TOKEN_RE.sub(_sub, text or "")
    except Exception:  # noqa: BLE001 - a render must never raise to the user
        return ""
