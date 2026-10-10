# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Turkish identifiers an e-Fatura carries: VKN, TCKN, document ID and UUID.

Two kinds of check live here and they do not have the same standing.

The *shape* checks (ten digits, eleven digits, the document ID pattern, the
UUID pattern) restate assertions of the official UBL-TR Schematron
(``UBL-TR_Common_Schematron.xml`` in the e-Fatura package published at
https://ebelge.gib.gov.tr/efaturamevzuat.html, revision 2026-07-01):
``PartyIdentificationTCKNVKNCheck``, ``InvoiceIDCheck`` and ``UUIDCheck``.
A document that fails one of them is rejected by GİB.

The *check digit* algorithms have no official text behind them. Neither the
UBL-TR guides, the Schematron, nor the pages of the Revenue Administration and
of the population directorate that were searched on 2026-10-10 describe them,
and the Schematron itself tests length only. What is implemented below is the
arithmetic every public validator uses (it is the arithmetic of the open
``python-stdnum`` library, modules ``stdnum.tr.vkn`` and ``stdnum.tr.tckimlik``,
which was read for comparison and not copied), and it was measured on
2026-10-10 against the identifiers inside GİB's own sample documents: 10 of
the 20 distinct ten digit VKN values and 2 of the 4 eleven digit TCKN values
pass, where a wrong algorithm would pass about one in ten and one in a hundred
by chance. The values that fail are fillers (one digit repeated, a repeating
triplet) or near copies of a passing value. That is corroboration, not proof.
See :data:`CHECK_DIGIT_REVIEW_STATUS`.

Two consequences follow, and callers must respect both. A number that fails
the check digit is almost certainly mistyped, which is why the rule engine
reports it. But GİB's own samples use fillers that fail it, so a test
environment may legitimately need a number this module calls invalid, and the
rule that reports it is kept separate from the rule that reports a wrong
length.
"""

from __future__ import annotations

import re
from typing import Literal

#: Standing of the check digit algorithms, in the vocabulary the statutory data
#: rows use. ``unconfirmed`` because no official text describing them was found.
CHECK_DIGIT_REVIEW_STATUS = "unconfirmed"

#: ``InvoiceIDCheck``: three characters of unit code, the four digit year, nine
#: digits of sequence. Sixteen characters, upper case.
DOCUMENT_ID_PATTERN = re.compile(r"^[A-Z0-9]{3}20[0-9]{2}[0-9]{9}$")

#: ``UUIDCheck``: 8-4-4-4-12 hexadecimal, either case.
UUID_PATTERN = re.compile(r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")

_VKN_SHAPE = re.compile(r"^[0-9]{10}$")
_TCKN_SHAPE = re.compile(r"^[0-9]{11}$")

TaxNumberKind = Literal["VKN", "TCKN"]


def classify_tax_number(value: str | None) -> TaxNumberKind | None:
    """Say which identifier a tax number is, by its shape alone.

    Ten digits are a VKN (legal entities, and natural persons registered as
    taxpayers before the personal number took over), eleven digits are a TCKN
    (natural persons). The value is taken as written: no separators are
    stripped, because the document must carry the digits and nothing else.

    Args:
        value: the tax number as entered.

    Returns:
        ``"VKN"``, ``"TCKN"``, or ``None`` when it is neither shape.
    """
    text = value or ""
    if _VKN_SHAPE.fullmatch(text):
        return "VKN"
    if _TCKN_SHAPE.fullmatch(text):
        return "TCKN"
    return None


def vkn_check_digit(first_nine: str) -> int:
    """Compute the tenth digit of a VKN from its first nine.

    For the digit at position ``i`` (1 to 9, left to right): add ``10 - i`` to
    it and keep the last digit; when that is not zero, multiply it by
    ``2 ** (10 - i)``, take the remainder modulo 9 and read a remainder of zero
    as nine. The check digit is what brings the sum of the nine results up to
    a multiple of ten.

    Args:
        first_nine: exactly nine digits.

    Raises:
        ValueError: when ``first_nine`` is not nine digits.
    """
    if not re.fullmatch(r"[0-9]{9}", first_nine or ""):
        raise ValueError("a VKN check digit is computed from exactly nine digits")
    total = 0
    for index, char in enumerate(first_nine):
        weight = 9 - index
        step = (int(char) + weight) % 10
        if step:
            step = (step * 2**weight) % 9 or 9
        total += step
    return (10 - total % 10) % 10


def is_valid_vkn(value: str | None) -> bool:
    """True when ``value`` is ten digits whose last digit is the check digit."""
    text = value or ""
    if not _VKN_SHAPE.fullmatch(text):
        return False
    return vkn_check_digit(text[:9]) == int(text[9])


def tckn_check_digits(first_nine: str) -> tuple[int, int]:
    """Compute the tenth and eleventh digits of a TCKN from its first nine.

    The tenth digit is seven times the sum of the digits in the odd positions
    (first, third, fifth, seventh, ninth) less the sum of the digits in the
    even positions (second, fourth, sixth, eighth), modulo ten. The eleventh is
    the sum of the first ten digits, modulo ten.

    Args:
        first_nine: exactly nine digits.

    Raises:
        ValueError: when ``first_nine`` is not nine digits.
    """
    if not re.fullmatch(r"[0-9]{9}", first_nine or ""):
        raise ValueError("TCKN check digits are computed from exactly nine digits")
    digits = [int(char) for char in first_nine]
    tenth = (7 * sum(digits[0::2]) - sum(digits[1::2])) % 10
    eleventh = (sum(digits) + tenth) % 10
    return tenth, eleventh


def is_valid_tckn(value: str | None) -> bool:
    """True when ``value`` is eleven digits, not starting with zero, with both check digits right."""
    text = value or ""
    if not _TCKN_SHAPE.fullmatch(text) or text[0] == "0":
        return False
    tenth, eleventh = tckn_check_digits(text[:9])
    return (tenth, eleventh) == (int(text[9]), int(text[10]))


def is_valid_tax_number(value: str | None) -> bool:
    """True when ``value`` is a VKN or a TCKN with correct check digits."""
    kind = classify_tax_number(value)
    if kind == "VKN":
        return is_valid_vkn(value)
    if kind == "TCKN":
        return is_valid_tckn(value)
    return False


def is_valid_document_id(value: str | None) -> bool:
    """True when ``value`` has the sixteen character e-Fatura document ID shape."""
    return bool(DOCUMENT_ID_PATTERN.fullmatch(value or ""))


def is_valid_uuid(value: str | None) -> bool:
    """True when ``value`` has the 8-4-4-4-12 hexadecimal shape GİB calls the ETTN."""
    return bool(UUID_PATTERN.fullmatch(value or ""))
