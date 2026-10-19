# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Saudi Arabia: VAT registration number and Commercial Registration number.

``vat``
    The 15-digit VAT registration number ZATCA issues. It starts and ends with
    ``3``; the 11th digit is ``1`` for a VAT group (XML Implementation Standard
    v1.2, BR-KSA-39/40 and the CSR rules of the Security Features standard).
    ZATCA publishes no check digit, so the shape is all that can be checked
    offline.
``cr``
    The Commercial Registration number, 10 digits. It is the ``CRN`` scheme of a
    ZATCA e-invoice's seller or buyer identification (BR-KSA-08).
``unified_700``
    The unified national number of an establishment, 10 digits starting with
    ``7``. It is the ``700`` scheme of a ZATCA e-invoice (BR-KSA-08).

Arabic-Indic digits are normalised to ASCII digits first: they are how the
numbers are often printed on Saudi documents, and they are the same number.
"""

from __future__ import annotations

from app.core.party_identifiers import IdentifierCheck, register

_ZATCA_XML_STANDARD = (
    "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/"
    "20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf"
)

# Arabic-Indic (U+0660..U+0669) and Extended Arabic-Indic (U+06F0..U+06F9).
_DIGITS = str.maketrans(
    {**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}}
)


def _normalise(value: str) -> str:
    text = (value or "").translate(_DIGITS)
    return "".join(ch for ch in text if not ch.isspace() and ch != "-")


def _result(scheme: str, normalised: str, reason: str | None, **details: str) -> IdentifierCheck:
    return IdentifierCheck(
        valid=reason is None,
        normalised=normalised,
        scheme=scheme,
        country="SA",
        reason=reason,
        source=_ZATCA_XML_STANDARD,
        details=dict(details),
    )


@register("SA", "vat")
def check_vat(value: str) -> IdentifierCheck:
    """A ZATCA VAT registration number: 15 digits, first and last ``3``."""
    number = _normalise(value)
    if not number.isdigit():
        return _result("vat", number, "A Saudi VAT number has digits only.")
    if len(number) != 15:
        return _result("vat", number, f"A Saudi VAT number has 15 digits, this one has {len(number)}.")
    if number[0] != "3" or number[-1] != "3":
        return _result("vat", number, "A Saudi VAT number starts and ends with 3.")
    return _result("vat", number, None, vat_group="yes" if number[10] == "1" else "no")


@register("SA", "cr")
def check_cr(value: str) -> IdentifierCheck:
    """A Commercial Registration number: 10 digits."""
    number = _normalise(value)
    if not number.isdigit():
        return _result("cr", number, "A Commercial Registration number has digits only.")
    if len(number) != 10:
        return _result("cr", number, f"A Commercial Registration number has 10 digits, this one has {len(number)}.")
    return _result("cr", number, None)


@register("SA", "unified_700")
def check_unified_700(value: str) -> IdentifierCheck:
    """The unified national establishment number: 10 digits starting with ``7``."""
    number = _normalise(value)
    if not number.isdigit() or len(number) != 10:
        return _result("unified_700", number, "A unified national number has 10 digits.")
    if number[0] != "7":
        return _result("unified_700", number, "A unified national number starts with 7.")
    return _result("unified_700", number, None)
