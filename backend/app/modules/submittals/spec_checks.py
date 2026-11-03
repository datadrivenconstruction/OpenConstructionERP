"""Pure validation checks for the spec book to submittal register flow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.submittals.spec_parser import required_kinds

_SECTION_FORMAT = re.compile(r"^(?:\d{2} \d{2} \d{2}(?:\.\d{1,2})?|\d{5}|LB \d{3}|[A-Z]\d{2})$")


@dataclass(frozen=True)
class Finding:
    element_ref: str
    params: dict[str, str] = field(default_factory=dict)


def check_spec_section_format(item: dict[str, Any]) -> list[Finding]:
    """A section number the register can sort and group on: MasterFormat, LB or NBS."""
    section = str(item.get("spec_section") or "").strip()
    if _SECTION_FORMAT.match(section):
        return []
    return [Finding(section or str(item.get("title") or "item"), {"section": section or "-"})]


def check_duplicate_in_register(item: dict[str, Any]) -> list[Finding]:
    """Same section, type and title already in the register: confirming would double it."""
    if not item.get("duplicate"):
        return []
    return [
        Finding(
            str(item.get("title") or "item"),
            {"title": str(item.get("title") or ""), "section": str(item.get("spec_section") or "")},
        )
    ]


def check_no_sections_found(spec_import: dict[str, Any]) -> list[Finding]:
    """No SECTION headers read: the book is scanned, or laid out in a way the parser does not know."""
    if int(spec_import.get("section_count") or 0) > 0 or not int(spec_import.get("pages_done") or 0):
        return []
    return [Finding("spec_import", {"pages": str(spec_import.get("pages_done"))})]


def check_required_type_missing(section: dict[str, Any]) -> list[Finding]:
    """Some sections cannot be built without a given submittal (concrete without a mix design)."""
    have = set(section.get("kinds") or [])
    missing = [k for k in required_kinds(str(section.get("spec_section") or "")) if k not in have]
    if not missing:
        return []
    return [
        Finding(str(section["spec_section"]), {"section": str(section["spec_section"]), "kind": ", ".join(missing)})
    ]
