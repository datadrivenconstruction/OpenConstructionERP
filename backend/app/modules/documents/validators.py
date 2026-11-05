# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document hub validation rules (rule set ``documents``).

Rules run over a plain dict built by the service, one record under one key::

    {"document": {"id", "category", "file_size", "cde_state", "revision_code", "drawing_number",
                  "is_current_revision"}}
    {"photo":    {"id", "gps_lat", "gps_lon"}}

A rule looks only at the record kind and stage it guards, so a freshly uploaded drawing still in
work in progress passes without a drawing number.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule

DOCUMENTS_RULE_SET = "documents"

DOCUMENT_FIELDS = ("category", "file_size", "cde_state", "revision_code", "drawing_number", "is_current_revision")
PHOTO_FIELDS = ("gps_lat", "gps_lon")


class _DocumentRule(QualityRule):
    standard = DOCUMENTS_RULE_SET
    message_section = "documents"


class FileNotEmptyRule(_DocumentRule):
    """A stored file has content: a zero-byte upload is a failed transfer, not a document."""

    rule_id = "documents.file_not_empty"
    name = "Uploaded file is not empty"
    description = "file_size must be above zero when the file size is known"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "document")
        ref = str(doc.get("id", ""))
        size = to_dec(doc.get("file_size"))
        if size is not None and size <= 0:
            return [self.fail(context, "file_empty", ref=ref)]
        return [self.ok(ref)]


class PublishedDrawingIdentifiedRule(_DocumentRule):
    """A published drawing carries the drawing number and revision the site will quote."""

    rule_id = "documents.published_drawing_identified"
    name = "Published drawing has a number and revision"
    severity = Severity.WARNING
    description = "a published drawing needs drawing_number and revision_code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "document")
        ref = str(doc.get("id", ""))
        if doc.get("category") == "drawing" and doc.get("cde_state") == "published":
            missing = [n for n in ("drawing_number", "revision_code") if blank(doc.get(n))]
            if missing:
                return [self.fail(context, "published_unidentified", ref=ref, missing=", ".join(missing))]
        return [self.ok(ref)]


class ArchivedNotCurrentRule(_DocumentRule):
    """An archived document is no longer the current revision."""

    rule_id = "documents.archived_not_current"
    name = "Archived document is not the current revision"
    description = "a document in the archived state must not be flagged is_current_revision"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "document")
        ref = str(doc.get("id", ""))
        if doc.get("cde_state") == "archived" and doc.get("is_current_revision") is True:
            return [self.fail(context, "archived_current", ref=ref)]
        return [self.ok(ref)]


class PhotoLocationRule(_DocumentRule):
    """A site photo's coordinates come as a pair and lie on the globe."""

    rule_id = "documents.photo_location"
    name = "Photo coordinates are a valid pair"
    description = "gps_lat in -90..90 and gps_lon in -180..180, both or neither"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        photo = section(context, "photo")
        ref = str(photo.get("id", ""))
        lat, lon = photo.get("gps_lat"), photo.get("gps_lon")
        if (lat is None) != (lon is None):
            return [self.fail(context, "photo_location", ref=ref, lat=lat, lon=lon)]
        if lat is not None and lon is not None:
            la, lo = to_dec(lat), to_dec(lon)
            if la is None or lo is None or not (-90 <= la <= 90) or not (-180 <= lo <= 180):
                return [self.fail(context, "photo_location", ref=ref, lat=lat, lon=lon)]
        return [self.ok(ref)]


DOCUMENTS_RULES = (
    FileNotEmptyRule,
    PublishedDrawingIdentifiedRule,
    ArchivedNotCurrentRule,
    PhotoLocationRule,
)


def register_documents_validation_rules() -> None:
    """Register the document hub rules with the platform rule registry."""
    for rule_class in DOCUMENTS_RULES:
        rule_registry.register(rule_class(), [DOCUMENTS_RULE_SET])


__all__ = [
    "DOCUMENTS_RULES",
    "DOCUMENTS_RULE_SET",
    "DOCUMENT_FIELDS",
    "PHOTO_FIELDS",
    "register_documents_validation_rules",
]
