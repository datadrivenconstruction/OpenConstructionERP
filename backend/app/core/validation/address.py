"""Address validation engine — Wave 26 of the worldwide-parameterisation audit.

Per-country postcode patterns, required-field lists, and field ordering are
loaded from the regional-pack ``address_validation`` keys.  The validator can
also be called without a regional pack loaded: it falls back to a minimal set
of rules (postcode optional, street + city required).

Usage::

    from app.core.validation.address import validate_address

    result = validate_address(
        {"street": "Hauptstr. 1", "city": "Berlin", "postcode": "10115"},
        country_code="DE",
    )
    assert result.passed
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Per-country definitions ───────────────────────────────────────────────────
#
# Each entry mirrors exactly what the regional pack config.py exposes so
# the engine and the pack configuration stay in sync.  Both are the source of
# truth: the pack config is the authoritative *public* key (used by the UI and
# exporters), this dict is the *runtime* lookup (used by the validator at
# every request).

_COUNTRY_RULES: dict[str, dict[str, Any]] = {
    # ── DACH ─────────────────────────────────────────────────────────────
    "DE": {
        "postcode_regex": r"^\d{5}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
    },
    "AT": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
    },
    "CH": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
    },
    # ── UK ────────────────────────────────────────────────────────────────
    # British Postcode format (Royal Mail specification):
    # AN NAA / ANN NAA / AAN NAA / AANN NAA / ANA NAA / AANA NAA
    "GB": {
        "postcode_regex": r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
        "postcode_note": "Format: e.g. SW1A 1AA, EC2A 4BH",
    },
    # Alias for GB — incoming addresses often carry "UK"
    "UK": {
        "postcode_regex": r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
        "postcode_note": "Format: e.g. SW1A 1AA, EC2A 4BH",
    },
    # ── US ────────────────────────────────────────────────────────────────
    "US": {
        "postcode_regex": r"^\d{5}(-\d{4})?$",
        "required_fields": ["street", "city", "state", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "state_required": True,
    },
    # ── India ─────────────────────────────────────────────────────────────
    "IN": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "state", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "state_required": True,
    },
    # ── Brazil (LATAM anchor) ─────────────────────────────────────────────
    # CEP: 99999-999 or 99999999
    "BR": {
        "postcode_regex": r"^\d{5}-?\d{3}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "state_required": False,
    },
    # ── Russia ────────────────────────────────────────────────────────────
    "RU": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "state_required": False,
    },
    # ── Middle East — UAE (postcode optional) ─────────────────────────────
    "AE": {
        "postcode_regex": None,  # No formal postcode system
        "required_fields": ["street", "city", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "state_required": False,
        "postcode_optional": True,
    },
    # ── Middle East — Saudi Arabia (postcode optional) ────────────────────
    # Saudi Post introduced a 5-digit postcode system but it is not yet
    # universally enforced.
    "SA": {
        "postcode_regex": r"^\d{5}$",
        "required_fields": ["street", "city", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "state_required": False,
        "postcode_optional": True,
    },
    # ── Japan ─────────────────────────────────────────────────────────────
    # Format: 〒999-9999 → stored as "999-9999" or "9999999"
    "JP": {
        "postcode_regex": r"^\d{3}-?\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["postcode", "state", "city", "street", "country"],
        "state_required": False,
    },
    # ── China ─────────────────────────────────────────────────────────────
    "CN": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["country", "postcode", "state", "city", "street"],
        "state_required": False,
    },
}

# Default rules used when no country-specific entry exists.
_DEFAULT_RULES: dict[str, Any] = {
    "postcode_regex": None,
    "required_fields": ["street", "city", "country"],
    "field_order": ["street", "city", "state", "postcode", "country"],
    "state_required": False,
    "postcode_optional": True,
}


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class AddressFieldError:
    """A single field-level validation failure."""

    field: str
    """The field that failed (e.g. ``"postcode"``)."""
    code: str
    """Machine-readable error code (e.g. ``"invalid_format"``)."""
    message: str
    """Human-readable description."""


@dataclass
class AddressValidationResult:
    """Result of :func:`validate_address`.

    Mirrors the ``ValidationResult`` shape used elsewhere in the platform:
    ``.passed`` for a boolean gate, ``.errors`` for drill-down detail.
    """

    passed: bool
    country_code: str
    errors: list[AddressFieldError] = field(default_factory=list)

    @property
    def error_fields(self) -> list[str]:
        """Convenience: unique list of fields that failed."""
        return list(dict.fromkeys(e.field for e in self.errors))


# ── Validator ─────────────────────────────────────────────────────────────────


def validate_address(
    address: dict[str, Any],
    country_code: str,
) -> AddressValidationResult:
    """Validate a flat address dict against the per-country rules.

    Args:
        address: Flat dict with string keys matching the field names used in
            the platform (``street``, ``city``, ``state``, ``postcode``,
            ``country``).  Unknown keys are silently ignored.
        country_code: ISO 3166-1 alpha-2 upper-case country code (e.g.
            ``"DE"``).  If the country has no dedicated rule set the default
            rules apply (postcode optional, street + city required).

    Returns:
        :class:`AddressValidationResult` with ``.passed`` and ``.errors``.

    Examples::

        # Valid German address
        r = validate_address(
            {"street": "Unter den Linden 1", "city": "Berlin",
             "postcode": "10117", "country": "DE"},
            "DE",
        )
        assert r.passed

        # Invalid UK postcode — missing space
        r = validate_address(
            {"street": "10 Downing St", "city": "London",
             "postcode": "SW1A2AA", "country": "GB"},
            "GB",
        )
        assert not r.passed
        assert r.error_fields == ["postcode"]
    """
    cc = (country_code or "").upper().strip()
    rules = _COUNTRY_RULES.get(cc, _DEFAULT_RULES)
    errors: list[AddressFieldError] = []

    # 1. Required-field check
    for fname in rules.get("required_fields", []):
        value = address.get(fname)
        if not value or not str(value).strip():
            errors.append(
                AddressFieldError(
                    field=fname,
                    code="required",
                    message=f"Field '{fname}' is required for country '{cc}'.",
                )
            )

    # 2. Postcode format check (only when a value is present or mandatory)
    postcode_value = str(address.get("postcode") or "").strip()
    postcode_regex: str | None = rules.get("postcode_regex")
    postcode_optional: bool = rules.get("postcode_optional", False)

    if postcode_value:
        if postcode_regex and not re.fullmatch(postcode_regex, postcode_value):
            note = rules.get("postcode_note", "")
            suffix = f" {note}" if note else ""
            errors.append(
                AddressFieldError(
                    field="postcode",
                    code="invalid_format",
                    message=(
                        f"Postcode '{postcode_value}' does not match the expected format for country '{cc}'.{suffix}"
                    ),
                )
            )
    elif not postcode_optional and "postcode" in rules.get("required_fields", []):
        # Already caught by required-field check above — don't double-report.
        pass

    # 3. State/province check (when country requires it)
    if rules.get("state_required", False):
        state_value = str(address.get("state") or "").strip()
        if not state_value:
            # Only append if not already reported via required_fields
            already_reported = any(e.field == "state" for e in errors)
            if not already_reported:
                errors.append(
                    AddressFieldError(
                        field="state",
                        code="required",
                        message=f"Field 'state' is required for country '{cc}'.",
                    )
                )

    return AddressValidationResult(
        passed=len(errors) == 0,
        country_code=cc,
        errors=errors,
    )


def get_address_field_order(country_code: str) -> list[str]:
    """Return the display field order for the given country.

    Used by the UI to reorder address form fields without a round-trip.
    Falls back to the default order when the country has no dedicated entry.
    """
    cc = (country_code or "").upper().strip()
    rules = _COUNTRY_RULES.get(cc, _DEFAULT_RULES)
    return list(rules.get("field_order", _DEFAULT_RULES["field_order"]))


def get_address_rules(country_code: str) -> dict[str, Any]:
    """Return the full rule dict for a country (for config endpoints)."""
    cc = (country_code or "").upper().strip()
    return dict(_COUNTRY_RULES.get(cc, _DEFAULT_RULES))
