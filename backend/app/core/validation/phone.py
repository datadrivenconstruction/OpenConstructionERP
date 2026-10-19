# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phone number validation engine - Wave 29 of the worldwide-parameterisation audit.

Per-country dial-code and national number patterns allow the engine to:

1. Validate a raw phone string (national or international form).
2. Normalise to E.164 format (``+<country_code><subscriber>``) where the
   country's dial code is known.

The engine deliberately avoids heavyweight libraries (phonenumbers, libphonenumber)
to stay within the platform's LIGHTWEIGHT principle.  Patterns cover the top
markets served by the regional packs and are based on ITU-T E.164 allocations
and national numbering plans (as of 2026).

Fourteen countries are covered and the rest of the world is not, so every
answer carries a :class:`~app.core.provenance.Provenance` saying which of the
two applied. Coverage is not a detail a caller can afford to be vague about
here: the generic pattern accepts six to fifteen digits, which is looser than
any national rule in the table, so a number a covered country rejects can be
accepted for its uncovered neighbour.

Usage::

    from app.core.validation.phone import validate_phone

    result = validate_phone("030-1234567", country_code="DE")
    assert result.passed
    assert result.e164 == "+49301234567"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.provenance import Provenance, declared, fell_back
from app.core.validation.identifiers import normalise_digits

# ── Per-country phone rules ───────────────────────────────────────────────────
#
# ``dial_code``          - ITU-T country calling code (without ``+``).
# ``national_regex``     - Regex matching the *stripped* national number
#                          (no spaces, dashes, parentheses).
# ``international_regex``- Regex matching the fully-prefixed string before
#                          any stripping (optional - used as alternate path).
# ``format_template``    - Human-readable template shown in the UI.
# ``strip_leading_zero`` - True when national numbers start with a trunk-prefix
#                          zero that must be removed in E.164.

_COUNTRY_PHONE_RULES: dict[str, dict[str, Any]] = {
    # ── DACH ─────────────────────────────────────────────────────────────
    "DE": {
        "dial_code": "49",
        # National: area code (2–5 digits) + subscriber (3–8 digits) = 6–11 digits total
        "national_regex": r"^[1-9]\d{6,11}$",
        "international_regex": r"^\+49[1-9]\d{6,11}$",
        "format_template": "+49 {area} {number}",
        "strip_leading_zero": True,
    },
    "AT": {
        "dial_code": "43",
        "national_regex": r"^[1-9]\d{3,11}$",
        "international_regex": r"^\+43[1-9]\d{3,11}$",
        "format_template": "+43 {area} {number}",
        "strip_leading_zero": True,
    },
    "CH": {
        "dial_code": "41",
        # Swiss numbers: always 9 digits without the leading 0, area 2 digits
        "national_regex": r"^[1-9]\d{8}$",
        "international_regex": r"^\+41[1-9]\d{8}$",
        "format_template": "+41 {area} {number}",
        "strip_leading_zero": True,
    },
    # ── UK ────────────────────────────────────────────────────────────────
    "GB": {
        "dial_code": "44",
        # UK subscriber numbers: 7–10 digits, never starts with 0 after stripping trunk
        "national_regex": r"^[1-9]\d{6,9}$",
        "international_regex": r"^\+44[1-9]\d{6,9}$",
        "format_template": "+44 {area} {number}",
        "strip_leading_zero": True,
    },
    "UK": {  # Alias
        "dial_code": "44",
        "national_regex": r"^[1-9]\d{6,9}$",
        "international_regex": r"^\+44[1-9]\d{6,9}$",
        "format_template": "+44 {area} {number}",
        "strip_leading_zero": True,
    },
    # ── US / Canada (NANP) ────────────────────────────────────────────────
    "US": {
        "dial_code": "1",
        # NANP: 10 digits, first digit of area code 2–9
        "national_regex": r"^[2-9]\d{9}$",
        "international_regex": r"^\+1[2-9]\d{9}$",
        "format_template": "+1 ({area}) {number}",
        "strip_leading_zero": False,
    },
    "CA": {
        "dial_code": "1",
        "national_regex": r"^[2-9]\d{9}$",
        "international_regex": r"^\+1[2-9]\d{9}$",
        "format_template": "+1 ({area}) {number}",
        "strip_leading_zero": False,
    },
    # ── India ─────────────────────────────────────────────────────────────
    "IN": {
        "dial_code": "91",
        # Indian mobile: 10 digits, starting 6–9; landlines also 10 digits (area+subs)
        "national_regex": r"^[6-9]\d{9}$",
        "international_regex": r"^\+91[6-9]\d{9}$",
        "format_template": "+91 {area} {number}",
        "strip_leading_zero": False,
    },
    # ── Brazil ────────────────────────────────────────────────────────────
    "BR": {
        "dial_code": "55",
        # Brazil: 2-digit area code + 8 or 9 digit number = 10 or 11 digits
        "national_regex": r"^[1-9]\d{9,10}$",
        "international_regex": r"^\+55[1-9]\d{9,10}$",
        "format_template": "+55 ({area}) {number}",
        "strip_leading_zero": False,
    },
    # ── Russia ────────────────────────────────────────────────────────────
    "RU": {
        "dial_code": "7",
        # Russian: 10 digits, first digit 3–9
        "national_regex": r"^[3-9]\d{9}$",
        "international_regex": r"^\+7[3-9]\d{9}$",
        "format_template": "+7 ({area}) {number}",
        "strip_leading_zero": False,
    },
    # ── UAE ───────────────────────────────────────────────────────────────
    "AE": {
        "dial_code": "971",
        # UAE: area code (2–3 digits) + subscriber; total digits after prefix: 7–9
        "national_regex": r"^[2-9]\d{6,8}$",
        "international_regex": r"^\+971[2-9]\d{6,8}$",
        "format_template": "+971 {area} {number}",
        "strip_leading_zero": True,
    },
    # ── Saudi Arabia ──────────────────────────────────────────────────────
    "SA": {
        "dial_code": "966",
        # KSA: 9 digits total after country code; mobile starts 5x
        "national_regex": r"^[15]\d{8}$",
        "international_regex": r"^\+966[15]\d{8}$",
        "format_template": "+966 {area} {number}",
        "strip_leading_zero": False,
    },
    # ── Egypt ─────────────────────────────────────────────────────────────
    # Mobile: 10, 11, 12 or 15 then 8 digits (11 digits nationally with the
    # trunk 0). Landline: Cairo/Giza area 2 then 8 digits; Alexandria 3 then 7;
    # other areas a 2-digit code then 7. Secondary source, awaiting review.
    "EG": {
        "dial_code": "20",
        "national_regex": r"^(?:1[0125]\d{8}|2\d{8}|3\d{7}|(?:1[3-9]|[4-9]\d)\d{7})$",
        "international_regex": r"^\+20(?:1[0125]\d{8}|2\d{8}|3\d{7}|(?:1[3-9]|[4-9]\d)\d{7})$",
        "format_template": "+20 {area} {number}",
        "strip_leading_zero": True,
        "source": "Telephone numbering plan of Egypt as documented (secondary)",
        "source_url": "https://en.wikipedia.org/wiki/Telephone_numbers_in_Egypt",
        "needs_expert_review": True,
    },
    # ── Japan ─────────────────────────────────────────────────────────────
    "JP": {
        "dial_code": "81",
        # Japan: mobile 090/080/070 → 10 digits; landline varies 10 digits
        "national_regex": r"^[1-9]\d{9,10}$",
        "international_regex": r"^\+81[1-9]\d{9,10}$",
        "format_template": "+81 {area} {number}",
        "strip_leading_zero": True,
    },
    # ── China ─────────────────────────────────────────────────────────────
    "CN": {
        "dial_code": "86",
        # China mobile: 11 digits starting 1; landlines shorter
        "national_regex": r"^1\d{10}$",
        "international_regex": r"^\+861\d{10}$",
        "format_template": "+86 {area} {number}",
        "strip_leading_zero": False,
    },
}

_DEFAULT_PHONE_RULES: dict[str, Any] = {
    "dial_code": None,
    "national_regex": r"^\d{6,15}$",
    "international_regex": r"^\+\d{7,15}$",
    "format_template": "+{dial_code} {number}",
    "strip_leading_zero": False,
}

#: What :data:`_DEFAULT_PHONE_RULES` is called when a provenance has to name it.
#:
#: Named for what it is rather than for the slot it fills. "DEFAULT" would tell
#: a reader only that the non-default did not answer, which ``answered`` already
#: says on its own. This says what did answer: a count of digits and nothing
#: else. No dial code, no numbering plan, no view on whether the number could be
#: reached. Deliberately not a country code either, since the generic rules are
#: not a jurisdiction.
#:
#: Descriptive, never a discriminant. A caller deciding whether it holds a
#: country-specific answer reads ``source``, or ``answered`` for the boolean;
#: comparing this token against a literal is the wrong idiom and would break the
#: moment a module named its stand-in accurately.
DIGIT_COUNT_ONLY = "DIGIT_COUNT_ONLY"

#: The one axis this module resolves. There is no second: a country either has
#: a row or it does not, and everything in the row - dial code, both regexes,
#: trunk-prefix handling - arrives together. The dial code was the candidate,
#: and it is perfectly correlated with coverage: all 14 entries carry one and
#: the generic rules carry none, so a separate provenance for it would repeat
#: this one in every case rather than distinguishing anything.
JURISDICTION = "jurisdiction"


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class PhoneValidationResult:
    """Result of :func:`validate_phone`.

    Attributes:
        passed:        True when the phone is syntactically valid. True on the
                       generic rules is a weaker statement than True on a
                       country's own; ``jurisdiction`` is what says which.
        e164:          E.164 normalised form (``+<cc><subscriber>``). Set only
                       when ``passed`` is True **and** the rules that answered
                       carry a dial code. A number accepted on the generic
                       rules has none to build from, so this stays None rather
                       than being prefixed with a guess - see
                       :func:`validate_phone`.
        country_code:  ISO 3166-1 alpha-2 country code passed in. It says what
                       was asked about and never what answered; read
                       ``jurisdiction.used`` for that.
        jurisdiction:  Whose rules judged the number. ``.answered`` is False
                       when no row exists for ``country_code`` and the generic
                       rules stood in.
        error_code:    Machine-readable error code when ``passed`` is False.
        error_message: Human-readable description when ``passed`` is False.
    """

    passed: bool
    country_code: str
    jurisdiction: Provenance
    e164: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    original: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_formatting(phone: str) -> str:
    """Remove spaces, dashes, dots, parentheses from a phone string.

    Arabic-Indic and Persian digits become ASCII digits first: a number typed
    on an Arabic keyboard is the same number, and an E.164 string built from
    it must be dialable.
    """
    return re.sub(r"[\s\-\.\(\)\/]", "", normalise_digits(phone))


def _already_e164(phone: str) -> bool:
    """Return True if the string looks like an E.164 number (``+CC...``)."""
    return bool(phone) and phone.startswith("+") and phone[1:].isdigit()


def _resolve_rules(country_code: str) -> tuple[dict[str, Any], Provenance]:
    """The rules that will answer for *country_code*, and where they came from.

    The single place the fallback happens, so that no caller can take the
    generic rules without also taking the record that says it did.

    Args:
        country_code: Upper-cased ISO 3166-1 alpha-2 code, or anything else -
            an unknown string is not an error here, it simply has no row.

    Returns:
        The rule dict, and a :class:`Provenance` on the ``jurisdiction`` axis.
    """
    rules = _COUNTRY_PHONE_RULES.get(country_code)
    if rules is not None:
        return rules, declared(JURISDICTION, country_code)
    return _DEFAULT_PHONE_RULES, fell_back(JURISDICTION, country_code, DIGIT_COUNT_ONLY)


# ── Validator ─────────────────────────────────────────────────────────────────


def validate_phone(
    phone: str,
    country_code: str,
) -> PhoneValidationResult:
    """Validate and normalise a phone number string.

    The function accepts national-format numbers (with or without trunk
    prefix), or full E.164 international strings.

    Only fourteen countries have rules here. Everything else is judged by the
    generic pattern, which accepts six to fifteen digits and knows no dial
    code, and ``.jurisdiction`` is what tells the two apart.

    Success no longer implies an E.164 form, and that is a deliberate change.
    A national number for a country with no row cannot be normalised, because
    there is no dial code to put in front of it; the previous behaviour was to
    prefix a bare ``+``, which produced a well-formed number belonging to
    somebody else - ``"301234567"`` for France came back as ``"+301234567"``,
    which is Greece, and with a trunk zero it came back as ``"+0301234567"``,
    which is not a possible E.164 number at all. Both were reported valid. A
    number that cannot be normalised now leaves ``.e164`` None rather than
    inventing one, and ``.passed`` still reports what the syntax check found.

    Args:
        phone:        Raw phone string (e.g. ``"030-1234567"``,
                      ``"+49301234567"``, ``"(030) 123 456 7"``).
        country_code: ISO 3166-1 alpha-2 upper-case country code (e.g.
                      ``"DE"``).  Controls which dial code and regex are
                      used when the number is in national form.

    Returns:
        :class:`PhoneValidationResult` - ``.passed``, ``.e164`` and
        ``.jurisdiction``. A caller that needs a storable number checks
        ``.e164 is not None``; one that needs to know whether the country's own
        rules judged it checks ``.jurisdiction.answered``.

    Examples::

        r = validate_phone("030-1234567", "DE")
        # r.passed == True, r.e164 == "+49301234567"
        # r.jurisdiction.answered == True

        r = validate_phone("301234567", "FR")
        # r.passed == True, r.e164 is None
        # r.jurisdiction.answered == False, r.jurisdiction.used == "DEFAULT"

        r = validate_phone("12", "DE")
        # r.passed == False, r.error_code == "too_short"
    """
    original = phone or ""
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    stripped = _strip_formatting(original)

    if not stripped:
        return PhoneValidationResult(
            passed=False,
            country_code=cc,
            jurisdiction=jurisdiction,
            original=original,
            error_code="empty",
            error_message="Phone number is empty.",
        )

    # ── Path 1: already E.164 ─────────────────────────────────────────────
    if _already_e164(stripped):
        int_regex: str | None = rules.get("international_regex")
        if int_regex and not re.fullmatch(int_regex, stripped):
            # Name the rules that actually rejected it. Saying "for country
            # 'FR'" when the generic pattern did the rejecting is the same
            # false statement about provenance this module is being cleaned of.
            reason = (
                f"the expected pattern for country '{cc}'"
                if jurisdiction.answered
                else f"the generic international pattern; no rules are published for country '{cc}'"
            )
            return PhoneValidationResult(
                passed=False,
                country_code=cc,
                jurisdiction=jurisdiction,
                original=original,
                error_code="invalid_format",
                error_message=f"International number '{stripped}' does not match {reason}.",
            )
        # The caller supplied a complete international number, so this is kept
        # whether or not the country has a row: nothing is being derived here,
        # and the dial code is the caller's rather than one we guessed. What
        # coverage changes is how thoroughly it was checked, which is what
        # jurisdiction records.
        return PhoneValidationResult(
            passed=True,
            country_code=cc,
            jurisdiction=jurisdiction,
            e164=stripped,
            original=original,
        )

    # ── Path 2: national number ───────────────────────────────────────────
    dial_code: str | None = rules.get("dial_code")
    national_regex: str | None = rules.get("national_regex")
    strip_leading_zero: bool = rules.get("strip_leading_zero", False)

    # Remove trunk prefix (leading 0) when country convention uses it
    national = stripped
    if strip_leading_zero and national.startswith("0"):
        national = national[1:]

    if national_regex and not re.fullmatch(national_regex, national):
        # As on the international path: the message may only name the country
        # when the country's own rules are what rejected the number.
        against = (
            f"country '{cc}'"
            if jurisdiction.answered
            else f"the generic format, no rules being published for country '{cc}'"
        )
        if len(national) < 6:
            code = "too_short"
            msg = f"Phone number '{original}' is too short for {against}."
        elif len(national) > 15:
            code = "too_long"
            msg = f"Phone number '{original}' is too long for {against}."
        else:
            code = "invalid_format"
            msg = f"Phone number '{original}' does not match the national format for {against}."
        return PhoneValidationResult(
            passed=False,
            country_code=cc,
            jurisdiction=jurisdiction,
            original=original,
            error_code=code,
            error_message=msg,
        )

    # A national number can only be turned into an E.164 by a dial code, and
    # only a country's own row carries one. Where there is none the number
    # stays un-normalised: passed says the digits are plausible, e164 being
    # None says nobody can dial them yet, and jurisdiction says why.
    e164 = f"+{dial_code}{national}" if dial_code else None

    return PhoneValidationResult(
        passed=True,
        country_code=cc,
        jurisdiction=jurisdiction,
        e164=e164,
        original=original,
    )


def get_phone_rules(country_code: str) -> dict[str, Any]:
    """Return the phone rule dict for a given country (for config endpoints).

    ``country_code`` in the returned dict is the code that was asked about and
    has always been that, which is why it could not be trusted: for a country
    with no row it sat on top of the generic patterns and read as though they
    were that country's. ``jurisdiction`` is the field that settles it, and a
    consumer deciding whether to present these as national rules reads
    ``jurisdiction.answered`` rather than the presence of a country code.

    Args:
        country_code: ISO 3166-1 alpha-2 code. Case and surrounding space are
            forgiven; an unknown code is answered by the generic rules rather
            than refused.

    Returns:
        The public subset of the rules, plus ``jurisdiction``. ``dial_code`` is
        None exactly when no row was found, so a caller formatting a number
        must check it rather than substituting into ``format_template`` blind.

    Examples::

        get_phone_rules("DE")["jurisdiction"].answered   # True
        get_phone_rules("FR")["jurisdiction"].answered   # False
        get_phone_rules("FR")["jurisdiction"].used       # "DEFAULT"
    """
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    # Expose public subset only - omit compiled internals if any
    return {
        "country_code": cc,
        "jurisdiction": jurisdiction,
        "dial_code": rules.get("dial_code"),
        "format_template": rules.get("format_template"),
        "national_regex": rules.get("national_regex"),
        "international_regex": rules.get("international_regex"),
    }
