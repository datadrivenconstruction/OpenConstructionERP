# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Group signature normalization.

A signature is the canonical fingerprint that lets the system recognise
"the same kind of group" across projects. When the user confirms a
match in Project A and a group in Project B has the same signature,
the cross-project library auto-suggests the same CWICR position.

Signatures are SHA-1 hex digests of a normalized string built from the
group-by attribute values. We normalise:

  * lowercase
  * unicode NFKD strip + accent fold
  * collapse runs of whitespace
  * sort attribute keys to make ``ifc_class+material`` and
    ``material+ifc_class`` produce the same fingerprint
  * scrub units (the matcher quantities live elsewhere, not in the key)

The plain-text label is kept alongside the digest so the library UI
can render "IfcWall · Stahlbeton · 240mm" — the digest itself is just
for fast equality lookup.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

_WS_RE = re.compile(r"\s+")
# Only strip unit suffixes that follow a digit — otherwise word
# boundaries swallow trailing letters from IFC class names ("element"
# → "elemen" because "t" was treated as the mass-tonne unit). The
# lookbehind enforces a preceding digit so "240mm" / "1.5kg" / "3t"
# still collapse while "IfcFurnishingElement" stays intact.
_UNIT_SUFFIX_RE = re.compile(
    r"(?<=\d)\s*(mm|cm|m|m2|m3|kg|t|stk|pcs)\b",
    flags=re.IGNORECASE,
)


def _normalize_value(value: Any) -> str:
    """‌⁠‍Lower-case, accent-fold, whitespace-collapse a free-form value."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _WS_RE.sub(" ", text)
    return text


def normalize_signature(
    fields: list[str],
    values: dict[str, Any],
) -> tuple[str, str]:
    """‌⁠‍Compute (label, sha1_hex) for a group.

    Args:
        fields: Attribute keys that participate in the signature, in the
            order the user picked them. Empty list → empty signature.
        values: Map of attribute → value for the group's representative
            element (or rolled-up value).

    Returns:
        ``(human_label, signature_hex)``. The label preserves field
        order and uses ``·`` as a separator. The hex is a 40-char SHA-1.
    """
    if not fields:
        return ("", "")
    parts: list[str] = []
    label_parts: list[str] = []
    for field in fields:
        norm = _normalize_value(values.get(field))
        if not norm:
            continue
        parts.append(f"{field.lower()}={norm}")
        label_parts.append(str(values.get(field)))
    if not parts:
        return ("", "")
    parts.sort()
    canonical = "|".join(parts)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    label = " · ".join(label_parts)
    return (label, digest)


def derive_group_key(group_by: list[str], values: dict[str, Any]) -> str:
    """Human-readable composite key for a group, e.g.
    ``"ifc_class:IfcWall|material:Stahlbeton|thickness:240"``.

    Field order is preserved (unlike the canonical signature, which
    sorts) so the UI can render group-by columns in the user's chosen
    order.
    """
    pieces: list[str] = []
    for field in group_by:
        raw = values.get(field)
        if raw is None or str(raw).strip() == "":
            pieces.append(f"{field}:∅")
            continue
        # Strip unit suffixes from numeric-ish strings so "240mm" and
        # "240 mm" produce the same key. Material/class strings pass
        # through untouched because they don't end in unit suffixes.
        text = str(raw).strip()
        text = _UNIT_SUFFIX_RE.sub("", text).strip()
        pieces.append(f"{field}:{text}")
    return "|".join(pieces)
