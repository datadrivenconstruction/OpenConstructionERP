# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Common data environment validation rules (rule set ``cde``).

Rules run over a plain dict built by the service, one record under one key::

    {"container": {"id", "container_code", "cde_state", "suitability_code"}}
    {"revision":  {"id", "file_size", "content_hash"}}

Naming conventions pinned by a project (design management) and the state-transition gates stay
where they are; these rules cover what neither of them looks at.
"""

from __future__ import annotations

import re

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule

CDE_RULE_SET = "cde"

CONTAINER_FIELDS = ("container_code", "cde_state", "suitability_code")

_SHARED_STATES = frozenset({"shared", "published"})
_BAD_CODE_CHARS = re.compile(r"[\s/\\]")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class _CdeRule(QualityRule):
    standard = CDE_RULE_SET
    message_section = "cde"


class ContainerCodeFormatRule(_CdeRule):
    """A container code is one token a file name and a transmittal can carry."""

    rule_id = "cde.container_code_format"
    name = "Container code has no spaces or slashes"
    description = "container_code must not contain whitespace or slashes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "container")
        ref = str(c.get("id", ""))
        code = str(c.get("container_code") or "")
        if code and _BAD_CODE_CHARS.search(code):
            return [self.fail(context, "container_code_format", ref=ref, code=code)]
        return [self.ok(ref)]


class SharedHasSuitabilityRule(_CdeRule):
    """Information shared or published states what it is suitable for (ISO 19650 suitability code)."""

    rule_id = "cde.shared_has_suitability"
    name = "Shared container states its suitability"
    severity = Severity.WARNING
    description = "a shared or published container should carry a suitability_code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "container")
        ref = str(c.get("id", ""))
        if c.get("cde_state") in _SHARED_STATES and blank(c.get("suitability_code")):
            return [self.fail(context, "suitability_missing", ref=ref, state=c.get("cde_state"))]
        return [self.ok(ref)]


class RevisionFileSizeRule(_CdeRule):
    """The recorded size of a revision's file is a whole number of bytes."""

    rule_id = "cde.revision_file_size"
    name = "Revision file size is a byte count"
    description = "file_size, when given, must be a non-negative whole number"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        r = section(context, "revision")
        ref = str(r.get("id", ""))
        raw = r.get("file_size")
        if not blank(raw) and not re.fullmatch(r"\d+", str(raw).strip()):
            return [self.fail(context, "file_size_invalid", ref=ref, value=str(raw).strip())]
        return [self.ok(ref)]


class RevisionHashFormatRule(_CdeRule):
    """A supplied content hash is a SHA-256 digest, so the same file can be recognised later."""

    rule_id = "cde.revision_hash_format"
    name = "Revision content hash is SHA-256"
    description = "content_hash, when given, must be 64 hexadecimal characters"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        r = section(context, "revision")
        ref = str(r.get("id", ""))
        raw = r.get("content_hash")
        if not blank(raw) and not _SHA256.match(str(raw).strip()):
            return [self.fail(context, "content_hash_invalid", ref=ref)]
        return [self.ok(ref)]


CDE_RULES = (
    ContainerCodeFormatRule,
    SharedHasSuitabilityRule,
    RevisionFileSizeRule,
    RevisionHashFormatRule,
)


def register_cde_validation_rules() -> None:
    """Register the common data environment rules with the platform rule registry."""
    for rule_class in CDE_RULES:
        rule_registry.register(rule_class(), [CDE_RULE_SET])


__all__ = ["CDE_RULES", "CDE_RULE_SET", "CONTAINER_FIELDS", "register_cde_validation_rules"]
