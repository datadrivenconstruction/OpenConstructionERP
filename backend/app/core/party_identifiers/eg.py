# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Egyptian party identifiers: tax registration number, national ID, commercial register.

The rules themselves, with their source, date read, confidence and expert
review flag, are data rows in :mod:`app.core.validation.identifiers`. This
module only exposes those rows through the shared registry, so a caller that
asks ``check("EG", "rin", value)`` and the subcontractor tax check read one
and the same row and can never disagree.
"""

from __future__ import annotations

from app.core.party_identifiers import IdentifierCheck, register
from app.core.validation.identifiers import validate_identifier

__all__ = ["check_commercial_register", "check_national_id", "check_rin"]


def _from_catalogue(scheme: str, kind: str, value: str) -> IdentifierCheck:
    result = validate_identifier("EG", kind, value)
    rule = result.rule
    details = dict(result.details)
    if rule is not None:
        details.setdefault("confidence", rule.confidence)
        details.setdefault("effective_from", rule.effective_from.isoformat())
        details.setdefault("needs_expert_review", "yes" if rule.needs_expert_review else "no")
        if rule.source_url:
            details.setdefault("source_url", rule.source_url)
    details.setdefault("checksum_verified", "yes" if result.checksum_verified else "no")
    return IdentifierCheck(
        valid=result.passed,
        normalised=result.normalised,
        scheme=scheme,
        country="EG",
        reason=result.reason,
        source=rule.source if rule is not None else None,
        details=details,
    )


@register("EG", "rin")
def check_rin(value: str) -> IdentifierCheck:
    """Tax registration number: nine digits; no public check digit is applied."""
    return _from_catalogue("rin", "tax_registration", value)


@register("EG", "national_id")
def check_national_id(value: str) -> IdentifierCheck:
    """National ID: fourteen digits carrying century, birth date and governorate."""
    return _from_catalogue("national_id", "national_id", value)


@register("EG", "commercial_register")
def check_commercial_register(value: str) -> IdentifierCheck:
    """Commercial register number: digits only, length is not published."""
    return _from_catalogue("commercial_register", "company_register", value)
