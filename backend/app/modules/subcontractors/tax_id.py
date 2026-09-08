# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax numbers: the shape a country prints them in, and their identity.

Two questions are answered here and they are not the same question.

``validate_tax_id`` answers the form's: is this shaped like a number of that
country. It is a format check, deliberately permissive, and it echoes the
spelling it validated so the form can show what was understood.

``canonical_tax_id`` answers the register's: is this the firm we already hold.
The stored ``tax_id`` is kept exactly as typed, because the value on a
letterhead is the value people look for, so two spellings of one number sit
in the column as two strings. The identity key is what makes them one.

The module is a leaf on purpose: the repository needs the identity key to
compare rows and the service needs the validator, and neither can import the
other without a cycle.
"""

from __future__ import annotations

import re

from app.modules.subcontractors.schemas import TaxIdValidationResponse

# Country -> (standard_name, compiled regex).
# Patterns are *format* checks. They are deliberately permissive (no MOD-97 /
# checksum validation) - the goal is to reject obviously broken input at the
# UI boundary, not to authenticate against a registry. Live VIES checks are a
# follow-up module concern. Coverage: all 27 EU member states under the VAT
# prefix VIES publishes for each; Greece is keyed twice, as EL (its VAT
# prefix) and as GR (its ISO 3166 code), because callers arrive with either,
# so the EU block holds 28 keys. Outside the EU: GB (post-Brexit VRN), US
# (EIN), CH (UID), NO (Org.nr), AU (ABN), CA (BN9/15), BR (CNPJ), IN (GSTIN),
# AE (TRN), SA (TRN), TR (VKN), RU (INN), ZA (VAT).
_TAX_ID_RULES: dict[str, tuple[str, re.Pattern[str]]] = {
    # EU VAT - country prefix is OPTIONAL on input; we normalise to bare body.
    "AT": ("EU VAT (AT)", re.compile(r"^U\d{8}$")),
    "BE": ("EU VAT (BE)", re.compile(r"^[01]\d{9}$")),
    "BG": ("EU VAT (BG)", re.compile(r"^\d{9,10}$")),
    "CY": ("EU VAT (CY)", re.compile(r"^\d{8}[A-Z]$")),
    "CZ": ("EU VAT (CZ)", re.compile(r"^\d{8,10}$")),
    "DE": ("EU VAT (DE)", re.compile(r"^\d{9}$")),
    "DK": ("EU VAT (DK)", re.compile(r"^\d{8}$")),
    "EE": ("EU VAT (EE)", re.compile(r"^\d{9}$")),
    "EL": ("EU VAT (EL)", re.compile(r"^\d{9}$")),
    "ES": ("EU VAT (ES)", re.compile(r"^[A-Z0-9]\d{7}[A-Z0-9]$")),
    "FI": ("EU VAT (FI)", re.compile(r"^\d{8}$")),
    "FR": ("EU VAT (FR)", re.compile(r"^[A-HJ-NP-Z0-9]{2}\d{9}$")),
    "HR": ("EU VAT (HR)", re.compile(r"^\d{11}$")),
    "HU": ("EU VAT (HU)", re.compile(r"^\d{8}$")),
    "IE": ("EU VAT (IE)", re.compile(r"^\d{7}[A-Z]{1,2}$|^\d[A-Z0-9+*]\d{5}[A-Z]$")),
    "IT": ("EU VAT (IT)", re.compile(r"^\d{11}$")),
    "LT": ("EU VAT (LT)", re.compile(r"^\d{9}$|^\d{12}$")),
    "LU": ("EU VAT (LU)", re.compile(r"^\d{8}$")),
    "LV": ("EU VAT (LV)", re.compile(r"^\d{11}$")),
    "MT": ("EU VAT (MT)", re.compile(r"^\d{8}$")),
    "NL": ("EU VAT (NL)", re.compile(r"^\d{9}B\d{2}$")),
    "PL": ("EU VAT (PL)", re.compile(r"^\d{10}$")),
    "PT": ("EU VAT (PT)", re.compile(r"^\d{9}$")),
    "RO": ("EU VAT (RO)", re.compile(r"^\d{2,10}$")),
    "SE": ("EU VAT (SE)", re.compile(r"^\d{12}$")),
    "SI": ("EU VAT (SI)", re.compile(r"^\d{8}$")),
    "SK": ("EU VAT (SK)", re.compile(r"^\d{10}$")),
    "GR": ("EU VAT (GR)", re.compile(r"^\d{9}$")),
    # Outside EU
    "GB": ("GB VRN", re.compile(r"^\d{9}$|^\d{12}$|^GD\d{3}$|^HA\d{3}$")),
    "US": ("US EIN", re.compile(r"^\d{9}$")),
    # Written CHE-123.456.789 MWST. The E belongs to the number and survives
    # prefix stripping, and the VAT suffix is named in the language of the
    # canton, so MWST, TVA and IVA are the same number rather than three.
    "CH": ("CH UID", re.compile(r"^E?\d{9}(?:MWST|TVA|IVA)?$")),
    "NO": ("NO Org.nr", re.compile(r"^\d{9}MVA$|^\d{9}$")),
    "AU": ("AU ABN", re.compile(r"^\d{11}$")),
    "CA": ("CA BN9/15", re.compile(r"^\d{9}$|^\d{9}RT\d{4}$")),
    "BR": ("BR CNPJ", re.compile(r"^\d{14}$")),
    "IN": ("IN GSTIN", re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9]$")),
    "AE": ("AE TRN", re.compile(r"^\d{15}$")),
    "SA": ("SA TRN", re.compile(r"^\d{15}$")),
    "TR": ("TR VKN", re.compile(r"^\d{10}$|^\d{11}$")),
    "RU": ("RU INN", re.compile(r"^\d{10}$|^\d{12}$")),
    "ZA": ("ZA VAT", re.compile(r"^\d{10}$")),
}

#: Suffixes a register prints after the number to say the firm is in its VAT
#: register, in the language of the region: one number, written with or
#: without it. Dropped from the identity key only; the validator still
#: reports the spelling it was given.
_VAT_REGISTER_SUFFIXES: dict[str, re.Pattern[str]] = {
    "CH": re.compile(r"(?:MWST|TVA|IVA)$"),
    "NO": re.compile(r"MVA$"),
}

#: A Swiss UID body after the optional prefix and suffix are gone. The
#: standard prints ``CHE`` in front of the nine digits, and the identity key
#: keeps it, so a number typed bare and one typed off a letterhead agree.
_CH_UID_BODY = re.compile(r"^E?(\d{9})$")


def _tax_id_candidates(country: str, raw: str) -> tuple[str, list[str]]:
    """Return (country_upper, bodies to try) for a free-form input.

    * Drops whitespace, dashes, slashes, dots.
    * Upper-cases the result.
    * If the input starts with the same 2-letter country code as the
      ``country`` arg (e.g. ``DE123…`` with country=``DE``), the stripped
      body is offered first. EU VAT numbers commonly carry the country
      prefix in invoicing contexts but the format rules check only the body.

    The unstripped form stays as a second candidate, because those two
    letters are not always a prefix. A French VAT key is two characters that
    may themselves be letters, so a body can legitimately open with ``FR``.
    Offering both can only accept input that one candidate alone refused;
    anything that matched before still matches.

    With no country there is no prefix to strip: every string starts with the
    empty string, and without the guard the first two characters of a number
    typed against an unknown country were silently cut off.
    """
    country_u = country.upper()[:2]
    cleaned = re.sub(r"[\s\-./,_]", "", raw or "").upper()
    if country_u and cleaned.startswith(country_u) and len(cleaned) > 2:
        return country_u, [cleaned[2:], cleaned]
    return country_u, [cleaned]


def validate_tax_id(country: str, tax_id: str) -> TaxIdValidationResponse:
    """Validate a tax-ID's format against the country's published pattern.

    Returns a structured :class:`TaxIdValidationResponse` indicating whether
    the format is valid and which standard it was checked against. Countries
    with no rule registered return ``format_valid=True`` with ``standard=None``
    - we don't want to block payment in unknown jurisdictions.
    """
    country_u, candidates = _tax_id_candidates(country or "", tax_id or "")
    normalised = candidates[0]
    if not normalised:
        return TaxIdValidationResponse(
            country=country_u,
            tax_id_normalised="",
            format_valid=False,
            standard=None,
            reason="empty_after_normalisation",
        )
    rule = _TAX_ID_RULES.get(country_u)
    if rule is None:
        return TaxIdValidationResponse(
            country=country_u,
            tax_id_normalised=normalised,
            format_valid=True,
            standard=None,
            reason=None,
        )
    standard_name, pattern = rule
    for candidate in candidates:
        if pattern.fullmatch(candidate):
            return TaxIdValidationResponse(
                country=country_u,
                tax_id_normalised=candidate,
                format_valid=True,
                standard=standard_name,
                reason=None,
            )
    return TaxIdValidationResponse(
        country=country_u,
        tax_id_normalised=normalised,
        format_valid=False,
        standard=standard_name,
        reason=f"format_mismatch:{standard_name}",
    )


def canonical_tax_id(country: str | None, tax_id: str | None) -> str:
    """The identity of a tax number: what every spelling of one number shares.

    Separators and case are gone, the country prefix is gone where the rule
    treats it as optional, and the Swiss and Norwegian VAT suffixes are gone,
    because ``MWST``, ``TVA`` and ``IVA`` name one register in three languages
    and a firm is in it or not regardless of which language its letterhead
    uses. The Swiss key keeps the ``CHE`` the standard prints, so
    ``CHE-123.456.789 MWST``, ``CHE-123.456.789 TVA`` and ``che123456789``
    are one key, and so is a bare ``123456789`` typed against country CH.

    This is what the register compares; the stored ``tax_id`` stays as typed.
    Input the validator refuses still gets a deterministic key (its stripped,
    upper-cased form), so a comparison never widens to "matches nothing"
    because a number happened to be misspelt on both rows in the same way.

    Returns an empty string only when nothing but separators was given.
    """
    result = validate_tax_id(country or "", tax_id or "")
    key = result.tax_id_normalised
    suffix = _VAT_REGISTER_SUFFIXES.get(result.country)
    if suffix is not None:
        key = suffix.sub("", key)
    if result.country == "CH":
        body = _CH_UID_BODY.fullmatch(key)
        if body is not None:
            key = f"CHE{body.group(1)}"
    return key


def tax_id_digit_run(tax_id: str | None) -> str:
    """The digits of a tax number in order, nothing else.

    Every step of :func:`canonical_tax_id` removes letters and separators and
    never a digit, so two spellings with one identity key always share this
    run. It is the coarse key a query can compute in SQL to narrow the rows
    the exact Python comparison then decides between.
    """
    return re.sub(r"\D", "", tax_id or "")
