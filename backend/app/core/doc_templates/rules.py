# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Checks every template text passes before it is saved or published.

Rule ids are ``doctpl.*``; the UI translates ``validation.doctpl.<id>``.
Errors block a publish; warnings and infos are shown and stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from app.core.doc_templates.markup import has_raw_html, unsafe_links
from app.core.doc_templates.merge import unknown_fields
from app.core.doc_templates.registry import DocumentKind

__all__ = [
    "MAX_BLOCK_CHARS",
    "MAX_TEMPLATE_BYTES",
    "Issue",
    "check_blocks",
    "has_errors",
]

MAX_BLOCK_CHARS = 8_000
MAX_TEMPLATE_BYTES = 64 * 1024

UNKNOWN_FIELD = "doctpl.unknown_merge_field"
SUBJECT_EMPTY = "doctpl.email_subject_empty"
UNSAFE_LINK = "doctpl.unsafe_link"
RAW_HTML = "doctpl.raw_html"
BLOCK_TOO_LONG = "doctpl.block_too_long"
TEMPLATE_TOO_LARGE = "doctpl.template_too_large"
BLOCK_REQUIRED = "doctpl.block_required"
UNKNOWN_BLOCK = "doctpl.unknown_block"
LOCALE_FALLBACK = "doctpl.locale_fallback"
DRAFT_UNPUBLISHED = "doctpl.draft_unpublished"
LEGAL_DATA_MISSING = "doctpl.legal_data_missing"


@dataclass(frozen=True)
class Issue:
    """One finding. ``params`` fill the translated message (``field``, ``language``, ``source``)."""

    rule_id: str
    severity: str
    block: str = ""
    params: Mapping[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        """JSON-ready form."""
        out = asdict(self)
        out["params"] = dict(self.params or {})
        return out


def check_blocks(kind: DocumentKind, blocks: Mapping[str, str]) -> list[Issue]:
    """Validate a set of block texts against *kind*. Never raises."""
    issues: list[Issue] = []
    total = 0
    for name, raw in blocks.items():
        if name not in kind.blocks:
            issues.append(Issue(UNKNOWN_BLOCK, "error", name))
            continue
        text = raw if isinstance(raw, str) else ""
        total += len(text.encode("utf-8"))
        if len(text) > MAX_BLOCK_CHARS:
            issues.append(Issue(BLOCK_TOO_LONG, "error", name, {"max": str(MAX_BLOCK_CHARS)}))
        for token in unknown_fields(text, kind.field_paths):
            issues.append(Issue(UNKNOWN_FIELD, "error", name, {"field": token}))
        if has_raw_html(text):
            issues.append(Issue(RAW_HTML, "error", name))
        for url in unsafe_links(text):
            issues.append(Issue(UNSAFE_LINK, "error", name, {"url": url[:80]}))
    if total > MAX_TEMPLATE_BYTES:
        issues.append(Issue(TEMPLATE_TOO_LARGE, "error", "", {"max": str(MAX_TEMPLATE_BYTES)}))
    if kind.channel == "email" and "subject" in kind.blocks and "subject" in blocks:
        if not (blocks.get("subject") or "").strip():
            issues.append(Issue(SUBJECT_EMPTY, "error", "subject"))
    for name in kind.required_blocks:
        if name in blocks and not (blocks.get(name) or "").strip():
            issues.append(Issue(BLOCK_REQUIRED, "error", name))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    """Whether any issue blocks a publish."""
    return any(i.severity == "error" for i in issues)
