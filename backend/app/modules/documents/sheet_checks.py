"""Pure validation checks for a sheet in the drawing register.

Payload: ``sheet_number``, ``extraction`` (the sheet's OCR metadata), ``duplicates``
(other sheets of the same upload carrying the number) and ``current_revision``
(revision of the sheet already current for this number), ``revision``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.documents.sheet_fields import compare_revisions


@dataclass(frozen=True)
class Finding:
    element_ref: str
    params: dict[str, str] = field(default_factory=dict)


def _ref(sheet: dict[str, Any]) -> str:
    return str(sheet.get("sheet_number") or sheet.get("page_number") or "sheet")


def check_number_present(sheet: dict[str, Any]) -> list[Finding]:
    """A sheet with no number cannot be indexed or stacked on an earlier revision."""
    if str(sheet.get("sheet_number") or "").strip():
        return []
    return [Finding(_ref(sheet), {"page": str(sheet.get("page_number") or "")})]


def check_number_unique_in_set(sheet: dict[str, Any]) -> list[Finding]:
    """Two pages of one upload with the same number are a fault in the set."""
    count = int(sheet.get("duplicates") or 0)
    if count <= 0:
        return []
    return [Finding(_ref(sheet), {"sheet": _ref(sheet), "count": str(count + 1)})]


def check_revision_not_lower(sheet: dict[str, Any]) -> list[Finding]:
    """A scan whose revision is lower than the current one would supersede a newer sheet."""
    current = sheet.get("current_revision")
    if not current or not sheet.get("revision"):
        return []
    order = compare_revisions(sheet.get("revision"), current)
    if order is None or order >= 0:
        return []
    return [Finding(_ref(sheet), {"sheet": _ref(sheet), "revision": str(sheet["revision"]), "current": str(current)})]


def check_low_confidence_unconfirmed(sheet: dict[str, Any]) -> list[Finding]:
    """An OCR reading below the stacking confidence must be confirmed by a person."""
    extraction = sheet.get("extraction")
    if not isinstance(extraction, dict) or extraction.get("source") != "ocr" or not extraction.get("needs_review"):
        return []
    confidence = float(extraction.get("confidence") or 0.0)
    if confidence >= 0.6:
        return []
    return [Finding(_ref(sheet), {"sheet": _ref(sheet), "confidence": f"{round(confidence * 100)}%"})]
