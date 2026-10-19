# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""French company identifiers: SIREN and SIRET.

Both end in a Luhn key (INSEE). The shape failure and the key failure are kept
apart on purpose: the public e-invoicing platform only tests "nine digits"
(external specifications v3.2, annex 7, rule G1.89), so a caller may treat a
bad key as a warning where a bad shape is an error.

La Poste's establishments are numbered outside the Luhn key; the rule they
follow instead (digit sum of the SIRET a multiple of five) is documented by
secondary sources only, so a number accepted on it is valid but carries
``needs_expert_review`` in its details.
"""

from __future__ import annotations

import re

from app.core.party_identifiers import IdentifierCheck, register

REASON_SHAPE = "shape"
REASON_CHECKSUM = "checksum"
REASON_EXCEPTION = "documented_exception"

#: ISO/IEC 6523 ICDs the identifiers are written under in e-invoices (annex 1).
SIREN_ICD = "0002"
SIRET_ICD = "0009"

#: La Poste's SIREN, whose establishments follow the digit-sum rule.
LA_POSTE_SIREN = "356000000"

_SIREN_SOURCE = "https://www.insee.fr/fr/metadonnees/definition/c2047"
_SIRET_SOURCE = "https://www.insee.fr/fr/metadonnees/definition/c1841"
_LA_POSTE_SOURCE = "https://lookuptax.com/validate/france/siret"
_READ_DATE = "2026-10-19"
_SEPARATORS = re.compile(r"[\s\-./]")


def normalise(value: str | None) -> str:
    """Drop the separators people type (spaces, dashes, dots, slashes)."""
    return _SEPARATORS.sub("", value or "").upper()


def luhn_valid(digits: str) -> bool:
    """Luhn (mod 10) over a string of digits, the rightmost digit being the key."""
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def siren_of_siret(siret: str | None) -> str:
    """The SIREN a SIRET belongs to: its first nine digits."""
    return normalise(siret)[:9]


def _check(value: str, *, scheme: str, label: str, length: int, icd: str, source: str) -> IdentifierCheck:
    normalised = normalise(value)
    details = {"label": label, "icd": icd, "read_date": _READ_DATE}
    if not re.fullmatch(rf"\d{{{length}}}", normalised):
        return IdentifierCheck(
            valid=False,
            normalised=normalised,
            scheme=scheme,
            country="FR",
            reason=REASON_SHAPE,
            source=source,
            details={**details, "message": f"A {label} has {length} digits."},
        )
    if luhn_valid(normalised):
        return IdentifierCheck(
            valid=True, normalised=normalised, scheme=scheme, country="FR", source=source, details=details
        )
    if scheme == "siret" and normalised[:9] == LA_POSTE_SIREN and sum(int(c) for c in normalised) % 5 == 0:
        return IdentifierCheck(
            valid=True,
            normalised=normalised,
            scheme=scheme,
            country="FR",
            reason=REASON_EXCEPTION,
            source=_LA_POSTE_SOURCE,
            details={
                **details,
                "needs_expert_review": "true",
                "message": "Accepted on La Poste's digit-sum exception, documented by secondary sources only.",
            },
        )
    return IdentifierCheck(
        valid=False,
        normalised=normalised,
        scheme=scheme,
        country="FR",
        reason=REASON_CHECKSUM,
        source=source,
        details={**details, "message": f"The {label} fails its check digit; it is probably mistyped."},
    )


@register("FR", "siren")
def check_siren(value: str) -> IdentifierCheck:
    """SIREN: nine digits, the ninth a Luhn key (INSEE)."""
    return _check(value, scheme="siren", label="SIREN", length=9, icd=SIREN_ICD, source=_SIREN_SOURCE)


@register("FR", "siret")
def check_siret(value: str) -> IdentifierCheck:
    """SIRET: the SIREN plus a five-digit establishment number, Luhn over all fourteen (INSEE)."""
    return _check(value, scheme="siret", label="SIRET", length=14, icd=SIRET_ICD, source=_SIRET_SOURCE)


__all__ = [
    "LA_POSTE_SIREN",
    "REASON_CHECKSUM",
    "REASON_EXCEPTION",
    "REASON_SHAPE",
    "SIREN_ICD",
    "SIRET_ICD",
    "check_siren",
    "check_siret",
    "luhn_valid",
    "normalise",
    "siren_of_siret",
]
