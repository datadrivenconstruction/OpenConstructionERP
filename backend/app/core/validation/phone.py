"""Phone number validation engine — Wave 29 of the worldwide-parameterisation audit.

Per-country dial-code and national number patterns allow the engine to:

1. Validate a raw phone string (national or international form).
2. Normalise to E.164 format (``+<country_code><subscriber>``) on success.

The engine deliberately avoids heavyweight libraries (phonenumbers, libphonenumber)
to stay within the platform's LIGHTWEIGHT principle.  Patterns cover the top
markets served by the regional packs and are based on ITU-T E.164 allocations
and national numbering plans (as of 2026).

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

# ── Per-country phone rules ───────────────────────────────────────────────────
#
# ``dial_code``          — ITU-T country calling code (without ``+``).
# ``national_regex``     — Regex matching the *stripped* national number
#                          (no spaces, dashes, parentheses).
# ``international_regex``— Regex matching the fully-prefixed string before
#                          any stripping (optional — used as alternate path).
# ``format_template``    — Human-readable template shown in the UI.
# ``strip_leading_zero`` — True when national numbers start with a trunk-prefix
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


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class PhoneValidationResult:
    """Result of :func:`validate_phone`.

    Attributes:
        passed:        True when the phone is syntactically valid.
        e164:          E.164 normalised form (``+<cc><subscriber>``) — set
                       only when ``passed`` is True.
        country_code:  ISO 3166-1 alpha-2 country code passed in.
        error_code:    Machine-readable error code when ``passed`` is False.
        error_message: Human-readable description when ``passed`` is False.
    """

    passed: bool
    country_code: str
    e164: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    original: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_formatting(phone: str) -> str:
    """Remove spaces, dashes, dots, parentheses from a phone string."""
    return re.sub(r"[\s\-\.\(\)\/]", "", phone)


def _already_e164(phone: str) -> bool:
    """Return True if the string looks like an E.164 number (``+CC...``)."""
    return bool(phone) and phone.startswith("+") and phone[1:].isdigit()


# ── Validator ─────────────────────────────────────────────────────────────────


def validate_phone(
    phone: str,
    country_code: str,
) -> PhoneValidationResult:
    """Validate and normalise a phone number string.

    The function accepts national-format numbers (with or without trunk
    prefix), or full E.164 international strings.  On success it always
    returns the E.164 form.

    Args:
        phone:        Raw phone string (e.g. ``"030-1234567"``,
                      ``"+49301234567"``, ``"(030) 123 456 7"``).
        country_code: ISO 3166-1 alpha-2 upper-case country code (e.g.
                      ``"DE"``).  Controls which dial code and regex are
                      used when the number is in national form.

    Returns:
        :class:`PhoneValidationResult` — ``.passed`` and ``.e164``.

    Examples::

        r = validate_phone("030-1234567", "DE")
        # r.passed == True, r.e164 == "+49301234567"

        r = validate_phone("+49301234567", "DE")
        # r.passed == True, r.e164 == "+49301234567"

        r = validate_phone("12", "DE")
        # r.passed == False, r.error_code == "too_short"
    """
    original = phone or ""
    cc = (country_code or "").upper().strip()
    rules = _COUNTRY_PHONE_RULES.get(cc, _DEFAULT_PHONE_RULES)
    stripped = _strip_formatting(original)

    if not stripped:
        return PhoneValidationResult(
            passed=False,
            country_code=cc,
            original=original,
            error_code="empty",
            error_message="Phone number is empty.",
        )

    # ── Path 1: already E.164 ─────────────────────────────────────────────
    if _already_e164(stripped):
        int_regex: str | None = rules.get("international_regex")
        if int_regex and not re.fullmatch(int_regex, stripped):
            return PhoneValidationResult(
                passed=False,
                country_code=cc,
                original=original,
                error_code="invalid_format",
                error_message=(
                    f"International number '{stripped}' does not match the expected pattern for country '{cc}'."
                ),
            )
        # Accept as-is (even if country_code has no int_regex we accept it)
        return PhoneValidationResult(
            passed=True,
            country_code=cc,
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
        if len(national) < 6:
            code = "too_short"
            msg = f"Phone number '{original}' is too short for country '{cc}'."
        elif len(national) > 15:
            code = "too_long"
            msg = f"Phone number '{original}' is too long for country '{cc}'."
        else:
            code = "invalid_format"
            msg = f"Phone number '{original}' does not match the national format for country '{cc}'."
        return PhoneValidationResult(
            passed=False,
            country_code=cc,
            original=original,
            error_code=code,
            error_message=msg,
        )

    if dial_code:
        e164 = f"+{dial_code}{national}"
    else:
        # No country-specific rules: return as-is with a best-effort prefix
        e164 = f"+{national}" if not national.startswith("+") else national

    return PhoneValidationResult(
        passed=True,
        country_code=cc,
        e164=e164,
        original=original,
    )


def get_phone_rules(country_code: str) -> dict[str, Any]:
    """Return the phone rule dict for a given country (for config endpoints)."""
    cc = (country_code or "").upper().strip()
    rules = dict(_COUNTRY_PHONE_RULES.get(cc, _DEFAULT_PHONE_RULES))
    # Expose public subset only — omit compiled internals if any
    return {
        "country_code": cc,
        "dial_code": rules.get("dial_code"),
        "format_template": rules.get("format_template"),
        "national_regex": rules.get("national_regex"),
        "international_regex": rules.get("international_regex"),
    }
