# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment account details carried by an e-invoice (BT-84, BT-86).

Validated at the point of entry because nothing downstream can. A receiver's
validator checks that the document is well formed, not that the account on it
is real, so a mistyped IBAN produces a perfectly valid invoice that cannot be
paid. The ISO 7064 check digits catch every single-character error and all but a
vanishing fraction of transpositions, which is exactly the class of mistake made
while typing an account number into a form.

BT-84 is the *payment account identifier* and BT-86 the *payment service
provider identifier*. Neither business term says IBAN or BIC: those are what
the identifiers happen to be across the single European area this standard was
written in. Most of the world pays into something else, a routing number and an
account number in the United States, a transit and institution number in
Canada, an IFSC code in India, a BSB in Australia, a CNAPS code in China, a BIK
and a correspondent account in Russia, and none of them starts with two letters
and two check digits.

So the strict primitives below, :func:`normalise_iban` and :func:`normalise_bic`,
say what a value *is*, and the two ``normalise_payment_*`` wrappers decide what
a given seller may *store*. The split matters because the strict answer is the
right one for a German seller and the wrong one for an American: refusing an
IBAN-shaped typo saves a payment, and refusing a nine-digit routing number
locks a company out of the only screen that can record how it gets paid.

No dependency: this is the whole of the algorithm, and a package for it would
cost more than it saves on an instance running in two gigabytes.
"""

from __future__ import annotations

import re

__all__ = [
    "InvalidBankDetail",
    "country_uses_iban",
    "iban_countries",
    "is_bic",
    "is_iban",
    "normalise_bic",
    "normalise_iban",
    "normalise_payment_account",
    "normalise_payment_provider",
]


class InvalidBankDetail(ValueError):
    """A payment detail that cannot be what the user meant."""


# Length per country from the IBAN registry. Deliberately not exhaustive and
# deliberately not authoritative: a country missing here is checked on its check
# digits alone rather than rejected, so the table falling behind the registry
# costs accuracy and never costs a user their bank account.
_IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22,
    "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20,
    "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "LY": 25, "MC": 27,
    "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24,
    "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "ST": 25, "SV": 28,
    "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}  # fmt: skip

_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{6,30}$")
# ISO 9362: four letters (institution), two letters (country), two alphanumerics
# (location), and optionally three more (branch). Eight or eleven, never between.
_BIC_SHAPE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def _mod_97(iban: str) -> int:
    """ISO 7064 MOD 97-10 over the rearranged account number."""
    rearranged = iban[4:] + iban[:4]
    # Each letter becomes its position in the alphabet plus nine, which is what
    # int(c, 36) already yields, and the digits pass through unchanged.
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97


def normalise_iban(value: str | None, *, allow_empty: bool = False) -> str:
    """Return the IBAN in wire format, or raise :class:`InvalidBankDetail`.

    Args:
        value: What the user typed, in any spacing or case.
        allow_empty: Treat a blank value as a deliberate clearing rather than
            an error. The settings screen needs this to remove an account.

    Returns:
        The account with separators removed and letters upper-cased, which is
        the only form that belongs in the document (BT-84).

    Raises:
        InvalidBankDetail: The value is not an IBAN, is the wrong length for a
            country whose length is known, or fails its check digits.
    """
    raw = (value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise InvalidBankDetail("an account number is required")

    compact = re.sub(r"[\s-]", "", raw).upper()
    if not _IBAN_SHAPE.match(compact):
        raise InvalidBankDetail(
            f"{raw!r} is not an IBAN: it must start with two letters and two check digits, "
            "then at least six more letters or digits"
        )

    expected = _IBAN_LENGTHS.get(compact[:2])
    if expected is not None and len(compact) != expected:
        raise InvalidBankDetail(f"an IBAN for {compact[:2]} is {expected} characters, and this one is {len(compact)}")

    if _mod_97(compact) != 1:
        raise InvalidBankDetail(
            f"the check digits of {raw!r} do not match the rest of the account number, "
            "so at least one character is wrong"
        )
    return compact


def normalise_bic(value: str | None, *, allow_empty: bool = False) -> str:
    """Return the BIC upper-cased, or raise :class:`InvalidBankDetail`.

    A BIC carries no check digit, so only its shape can be verified (BT-86).
    """
    raw = (value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise InvalidBankDetail("a BIC is required")

    compact = re.sub(r"\s", "", raw).upper()
    if not _BIC_SHAPE.match(compact):
        raise InvalidBankDetail(
            f"{raw!r} is not a BIC: it must be eight or eleven characters, "
            "beginning with four letters for the institution and two for the country"
        )
    return compact


# A domestic identifier, once its separators are gone. Deliberately loose: the
# national formats are not ours to enumerate, and a table of them would be wrong
# somewhere on the day it was written. Four characters is the floor because it
# is below every real scheme and above the fragments a half-typed field holds,
# and the ceilings are the columns these values are stored in.
_DOMESTIC_ACCOUNT = re.compile(r"^[A-Z0-9]{4,34}$")
_DOMESTIC_PROVIDER = re.compile(r"^[A-Z0-9]{4,11}$")


def country_uses_iban(country: str | None) -> bool:
    """Whether a seller in this country is known to be paid through an IBAN.

    Answered from the registry table above, which is the list of countries that
    issue one. A country absent from our copy returns ``False``, which is the
    lenient direction on purpose and the same direction the length check already
    leans: an absent country means we cannot assert that it uses an IBAN, not
    that we know it does not, and the cost of guessing wrong is a domestic
    identifier accepted from a country that would have preferred an IBAN. The
    opposite default would refuse a real account, which is the failure this
    whole module exists to avoid.

    Args:
        country: An ISO 3166-1 alpha-2 code, in any case. Empty is treated as
            unknown, because an unset country is the state a configuration
            starts in and must be able to be saved from.

    Returns:
        True only when the country is one we hold an IBAN length for.
    """
    return (country or "").strip().upper() in _IBAN_LENGTHS


def iban_countries() -> list[str]:
    """The countries this module knows to be paid through an IBAN, sorted.

    Exists so a caller that needs the whole list, such as a screen labelling a
    field before anything has been saved, can read the one table rather than
    keep a copy of it.
    """
    return sorted(_IBAN_LENGTHS)


def normalise_payment_account(value: str | None, *, country: str = "", allow_empty: bool = False) -> str:
    """Return BT-84 for a seller in ``country``, or raise :class:`InvalidBankDetail`.

    An IBAN is self-identifying, so anything shaped like one is checked as one
    whatever the seller's country: a contractor in Texas may perfectly well be
    paid into a Dutch account, and a typo in it is still a typo. Only when the
    value is *not* shaped like an IBAN does the country decide, and then it
    decides in the one direction that cannot lock anybody out. A seller in a
    country that issues IBANs is told to enter one, which is what keeps a bare
    German Kontonummer from reaching a document that nothing downstream will
    check, since BR-DE-19/20 are not implemented against the assembled invoice.
    A seller anywhere else keeps their own account identifier unaltered.

    Args:
        value: What the user typed, in any spacing or case.
        country: The seller's ISO 3166-1 alpha-2 country code (BT-40).
        allow_empty: Treat a blank value as a deliberate clearing.

    Returns:
        The identifier with separators removed and letters upper-cased.

    Raises:
        InvalidBankDetail: The value fails the IBAN checks it invited by being
            shaped like one, or the seller's country issues IBANs and this is
            not one, or it is not a plausible account identifier anywhere.
    """
    raw = (value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise InvalidBankDetail("an account number is required")

    compact = re.sub(r"[\s-]", "", raw).upper()
    if _IBAN_SHAPE.match(compact):
        return normalise_iban(compact)

    if country_uses_iban(country):
        code = country.strip().upper()
        raise InvalidBankDetail(
            f"{raw!r} is not an IBAN, and a seller in {code} is paid into one: it must start with two "
            f"letters and two check digits, then at least six more letters or digits"
        )

    if not _DOMESTIC_ACCOUNT.match(compact):
        raise InvalidBankDetail(
            f"{raw!r} is not an account identifier: it must be at least four letters or digits, "
            "and it may not carry punctuation other than spaces and hyphens"
        )
    return compact


def normalise_payment_provider(value: str | None, *, country: str = "", allow_empty: bool = False) -> str:
    """Return BT-86 for a seller in ``country``, or raise :class:`InvalidBankDetail`.

    The same split as :func:`normalise_payment_account`, over the identifier of
    the bank rather than of the account. A BIC is recognised on its own shape
    anywhere, and outside the IBAN area a national bank code is kept as typed:
    a nine-digit routing number, an eight-digit Canadian transit and institution
    pair, a six-digit BSB, an eleven-character IFSC.

    The ceiling is eleven characters because that is the width of the column and
    of a BIC. A twelve-digit Chinese CNAPS code does not fit and is refused
    here, which is a real gap rather than a decision, and widening the column is
    what closes it.

    Args:
        value: What the user typed, in any spacing or case.
        country: The seller's ISO 3166-1 alpha-2 country code (BT-40).
        allow_empty: Treat a blank value as a deliberate clearing.

    Returns:
        The identifier with spaces removed and letters upper-cased.

    Raises:
        InvalidBankDetail: The seller's country uses BICs and this is not one,
            or it is not a plausible bank identifier anywhere.
    """
    raw = (value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise InvalidBankDetail("a BIC is required")

    compact = re.sub(r"\s", "", raw).upper()
    if _BIC_SHAPE.match(compact):
        return compact

    if country_uses_iban(country):
        code = country.strip().upper()
        raise InvalidBankDetail(
            f"{raw!r} is not a BIC, and a bank in {code} is identified by one: it must be eight or "
            f"eleven characters, beginning with four letters for the institution and two for the country"
        )

    if not _DOMESTIC_PROVIDER.match(compact):
        raise InvalidBankDetail(
            f"{raw!r} is not a bank identifier: it must be between four and eleven letters or digits"
        )
    return compact


def is_iban(value: str | None) -> bool:
    """Whether a stored BT-84 is an IBAN, as opposed to a domestic identifier.

    Used where a document or a page has to name what it is printing. The value
    has already been through :func:`normalise_payment_account`, so this asks the
    cheap structural question rather than re-deriving the decision.
    """
    compact = re.sub(r"[\s-]", "", (value or "").strip()).upper()
    if not _IBAN_SHAPE.match(compact):
        return False
    expected = _IBAN_LENGTHS.get(compact[:2])
    if expected is not None and len(compact) != expected:
        return False
    return _mod_97(compact) == 1


def is_bic(value: str | None) -> bool:
    """Whether a stored BT-86 is a BIC, as opposed to a domestic bank code."""
    return bool(_BIC_SHAPE.match(re.sub(r"\s", "", (value or "").strip()).upper()))
