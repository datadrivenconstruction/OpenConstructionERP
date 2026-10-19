# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish business identifiers: NIP, REGON, KRS and the postal code.

Four identifiers a Polish counterparty prints on every invoice, contract and
letterhead, and what can be checked about each without asking a register.

* **NIP** (Numer Identyfikacji Podatkowej), the tax number. Ten digits, the
  last a check digit: the first nine are weighted 6, 5, 7, 2, 3, 4, 5, 6, 7,
  the sum is taken modulo 11, and the result must equal the tenth digit. A
  result of 10 cannot be written as one digit, so no NIP is ever issued with
  it and such a number is invalid. Printed in blocks (``123-456-32-18`` or
  ``123-45-63-218``) and, as an EU VAT number, with the prefix ``PL``.
* **REGON**, the statistical number kept by Statistics Poland (GUS). Nine
  digits for an entity, fourteen for a local unit of one. The nine-digit check
  digit weights the first eight by 8, 9, 2, 3, 4, 5, 6, 7; the fourteen-digit
  one weights the first thirteen by 2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8. In
  both, the sum modulo 11 is the check digit and a result of 10 is written 0.
  A local unit's number opens with its parent's nine-digit REGON, so those
  nine digits must be a valid REGON on their own.
* **KRS**, the National Court Register number. Ten digits, zero-padded. It
  is a sequence number assigned by the register and carries **no** check
  digit, so only its shape can be checked here.
* **Kod pocztowy**, the postal code: two digits, a hyphen, three digits
  (``00-950``). Poczta Polska prints it with the hyphen, before the city.

Standing of the algorithms. The NIP weights are those of the Minister of
Finance's regulation on the procedure for assigning NIP (the 1995 regulation
under the Act on the rules of registration and identification of taxpayers),
and the REGON weights those GUS publishes for its register. Neither primary
text was read for this module: what is implemented is the arithmetic every
Polish accounting system and public validator applies, practitioner standard
rather than a quoted statute. A number that fails it is almost certainly
mistyped; a number that passes it may still not exist, because nothing here
asks the register.

Standard library only, and no import from ``app.modules``: the subcontractor
register and the address validator both read it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = [
    "KRS_LENGTH",
    "PL_POSTCODE_REGEX",
    "krs_is_valid",
    "nip_is_valid",
    "normalise_pl_id",
    "pl_postcode_is_valid",
    "regon_is_valid",
]

#: NIP check-digit weights for the first nine digits.
NIP_WEIGHTS: tuple[int, ...] = (6, 5, 7, 2, 3, 4, 5, 6, 7)

#: REGON check-digit weights, nine-digit form (first eight digits).
REGON9_WEIGHTS: tuple[int, ...] = (8, 9, 2, 3, 4, 5, 6, 7)

#: REGON check-digit weights, fourteen-digit form (first thirteen digits).
REGON14_WEIGHTS: tuple[int, ...] = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)

#: A KRS number is always written with ten digits, leading zeros kept.
KRS_LENGTH = 10

#: Poczta Polska's postal code: NN-NNN.
PL_POSTCODE_REGEX = r"^\d{2}-\d{3}$"

_SEPARATORS = re.compile(r"[\s\-./,_]")
_DIGITS = re.compile(r"^\d+$")


def normalise_pl_id(value: str | None) -> str:
    """Drop separators and an optional ``PL`` prefix, upper-casing the rest.

    ``"PL 123-456-32-18"`` and ``"pl1234563218"`` both become
    ``"1234563218"``. Anything else that is not a digit is left in place, so
    the callers below refuse it rather than silently reading a different
    number.
    """
    cleaned = _SEPARATORS.sub("", value or "").upper()
    if cleaned.startswith("PL"):
        cleaned = cleaned[2:]
    return cleaned


def _weighted_mod11(digits: str, weights: Sequence[int]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11


def nip_is_valid(value: str | None) -> bool:
    """Whether ``value`` is a well-formed NIP with a correct check digit.

    Accepts the printed spellings: hyphen or space blocks and the ``PL`` EU
    VAT prefix. A first-nine-digit sum whose remainder is 10 is invalid: no
    NIP is issued with it.
    """
    body = normalise_pl_id(value)
    if len(body) != 10 or not _DIGITS.match(body):
        return False
    check = _weighted_mod11(body[:9], NIP_WEIGHTS)
    if check == 10:
        return False
    return check == int(body[9])


def _regon9_ok(body: str) -> bool:
    check = _weighted_mod11(body[:8], REGON9_WEIGHTS) % 10
    return check == int(body[8])


def regon_is_valid(value: str | None) -> bool:
    """Whether ``value`` is a well-formed nine- or fourteen-digit REGON.

    A fourteen-digit REGON (a local unit) must carry a correct check digit of
    its own and open with a valid nine-digit REGON (its parent entity).
    """
    body = _SEPARATORS.sub("", value or "")
    if not _DIGITS.match(body or "x"):
        return False
    if len(body) == 9:
        return _regon9_ok(body)
    if len(body) == 14:
        if not _regon9_ok(body[:9]):
            return False
        check = _weighted_mod11(body[:13], REGON14_WEIGHTS) % 10
        return check == int(body[13])
    return False


def krs_is_valid(value: str | None) -> bool:
    """Whether ``value`` has the shape of a KRS number: exactly ten digits.

    Shape only. The KRS number is a register sequence number and has no check
    digit, so a correctly shaped number that was never issued passes; only
    the register (ekrs.ms.gov.pl) can say whether it exists.
    """
    body = _SEPARATORS.sub("", value or "")
    return len(body) == KRS_LENGTH and bool(_DIGITS.match(body))


def pl_postcode_is_valid(value: str | None) -> bool:
    """Whether ``value`` is a Polish postal code written ``NN-NNN``.

    The hyphen is required: ``00950`` is refused, because a printed Polish
    address always carries it and the bare form is how a mangled import
    usually shows.
    """
    return bool(re.fullmatch(PL_POSTCODE_REGEX, (value or "").strip()))
