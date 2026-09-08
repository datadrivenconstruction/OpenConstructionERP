# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Address validation engine - Wave 26 of the worldwide-parameterisation audit.

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

from app.core.provenance import Provenance, declared, fell_back

# ── Locality shapes ───────────────────────────────────────────────────────────
#
# ``field_order`` says which parts an address has and in what sequence. It
# cannot say which of them share a line, and that is most of what makes a
# printed address look native: "10115 Berlin" and "Berlin 10115" are the same
# sequence of two fields under any ordering that puts one before the other.
# A shape is the missing half, and there are few enough of them to name.
#
# A shape is a rendering decision only. Nothing here changes what an address is
# required to carry, which stays with ``required_fields``.

#: "Hauptstrasse 17" / "10115 Berlin". DACH, and everywhere uncovered.
POSTCODE_BEFORE_CITY = "POSTCODE_BEFORE_CITY"

#: "1600 Pennsylvania Ave" / "Washington, DC 20500". The post code closes the
#: locality line behind the region. Also Australia, New Zealand, Singapore,
#: India and the Gulf, whose region part is simply absent more often.
POSTCODE_AFTER_CITY_AND_STATE = "POSTCODE_AFTER_CITY_AND_STATE"

#: "10 Downing St" / "London" / "SW1A 2AA". The post code takes a line of its
#: own under the city, which is what Royal Mail asks for and what Russian post
#: does with the index at the foot of the address.
POSTCODE_ON_ITS_OWN_LINE = "POSTCODE_ON_ITS_OWN_LINE"

#: "Av. Paulista 1578" / "01310-200 Sao Paulo - SP". Correios opens the last
#: line with the CEP and closes it with the state abbreviation.
POSTCODE_BEFORE_CITY_AND_STATE = "POSTCODE_BEFORE_CITY_AND_STATE"

#: One field per line, in the order the country's own row declares. This is
#: how the CJK addresses are written: largest unit first, the exact reverse of
#: the Western sequence, and no two parts sharing a line. The row is the
#: authority because Japan and China do not agree with each other about where
#: the country name goes, so a single hard-coded reversal would be wrong for
#: one of them.
DECLARED_FIELD_ORDER = "DECLARED_FIELD_ORDER"

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
        "field_order": ["street", "postcode", "city", "country"],
        "locality_shape": POSTCODE_BEFORE_CITY,
        "state_required": False,
    },
    "AT": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "postcode", "city", "country"],
        "locality_shape": POSTCODE_BEFORE_CITY,
        "state_required": False,
    },
    "CH": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "postcode", "city", "country"],
        "locality_shape": POSTCODE_BEFORE_CITY,
        "state_required": False,
    },
    # ── UK ────────────────────────────────────────────────────────────────
    # British Postcode format (Royal Mail specification):
    # AN NAA / ANN NAA / AAN NAA / AANN NAA / ANA NAA / AANA NAA
    "GB": {
        "postcode_regex": r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "locality_shape": POSTCODE_ON_ITS_OWN_LINE,
        "state_required": False,
        "postcode_note": "Format: e.g. SW1A 1AA, EC2A 4BH",
    },
    # Alias for GB - incoming addresses often carry "UK"
    "UK": {
        "postcode_regex": r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "locality_shape": POSTCODE_ON_ITS_OWN_LINE,
        "state_required": False,
        "postcode_note": "Format: e.g. SW1A 1AA, EC2A 4BH",
    },
    # ── US ────────────────────────────────────────────────────────────────
    "US": {
        "postcode_regex": r"^\d{5}(-\d{4})?$",
        "required_fields": ["street", "city", "state", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": True,
    },
    # ── India ─────────────────────────────────────────────────────────────
    "IN": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "state", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": True,
    },
    # ── Australia and New Zealand ─────────────────────────────────────────
    # Reached by the ``peppol_aunz`` profile, which this product ships. The
    # generic shape would print "3000 Melbourne", which is not an address
    # anyone in either country writes, so these two rows exist to render
    # rather than to validate.
    "AU": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "state", "postcode", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": True,
    },
    "NZ": {
        "postcode_regex": r"^\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": False,
    },
    # ── Singapore ─────────────────────────────────────────────────────────
    # Reached by the ``peppol_sg`` profile. No region line, and the postal
    # code follows the city: "Singapore 238877".
    "SG": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": False,
    },
    # ── Brazil (LATAM anchor) ─────────────────────────────────────────────
    # CEP: 99999-999 or 99999999
    "BR": {
        "postcode_regex": r"^\d{5}-?\d{3}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "postcode", "city", "state", "country"],
        "locality_shape": POSTCODE_BEFORE_CITY_AND_STATE,
        "state_required": False,
    },
    # ── Russia ────────────────────────────────────────────────────────────
    # The index closes a Russian address rather than opening it, which is the
    # one respect in which it does not follow its DACH neighbours.
    "RU": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["street", "city", "postcode", "country"],
        "locality_shape": POSTCODE_ON_ITS_OWN_LINE,
        "state_required": False,
    },
    # ── Middle East - UAE (postcode optional) ─────────────────────────────
    "AE": {
        "postcode_regex": None,  # No formal postcode system
        "required_fields": ["street", "city", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": False,
        "postcode_optional": True,
    },
    # ── Middle East - Saudi Arabia (postcode optional) ────────────────────
    # Saudi Post introduced a 5-digit postcode system but it is not yet
    # universally enforced.
    "SA": {
        "postcode_regex": r"^\d{5}$",
        "required_fields": ["street", "city", "country"],
        "field_order": ["street", "city", "state", "postcode", "country"],
        "locality_shape": POSTCODE_AFTER_CITY_AND_STATE,
        "state_required": False,
        "postcode_optional": True,
    },
    # ── Japan ─────────────────────────────────────────────────────────────
    # Format: 〒999-9999 → stored as "999-9999" or "9999999"
    "JP": {
        "postcode_regex": r"^\d{3}-?\d{4}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["postcode", "state", "city", "street", "country"],
        "locality_shape": DECLARED_FIELD_ORDER,
        "state_required": False,
    },
    # ── China ─────────────────────────────────────────────────────────────
    "CN": {
        "postcode_regex": r"^\d{6}$",
        "required_fields": ["street", "city", "postcode", "country"],
        "field_order": ["country", "postcode", "state", "city", "street"],
        "locality_shape": DECLARED_FIELD_ORDER,
        "state_required": False,
    },
}

# Default rules used when no country-specific entry exists.
#
# The order and the shape are the continental-European one rather than a
# neutral-looking street-city-state-postcode, and that is a decision about
# being wrong less often rather than a claim to knowledge. Every uncovered
# country whose address a document is likely to carry - France, Spain, Italy,
# the Netherlands, Norway, Poland, Sweden - writes the post code before the
# city, and it is what every page this product has printed already said.
# ``jurisdiction`` remains the only thing that separates the stand-in from a
# country that really was consulted.
_DEFAULT_RULES: dict[str, Any] = {
    "postcode_regex": None,
    "required_fields": ["street", "city", "country"],
    "field_order": ["street", "postcode", "city", "state", "country"],
    "locality_shape": POSTCODE_BEFORE_CITY,
    "state_required": False,
    "postcode_optional": True,
}

#: What :data:`_DEFAULT_RULES` is called when a provenance has to name it.
#:
#: Named for what it is rather than for the slot it fills. What stands in here
#: checks that street, city and country are non-empty and stops: no postcode
#: pattern, no state requirement, no format checked anywhere. A reader seeing
#: this token knows an address passed without a single one of its parts being
#: examined for shape, which "DEFAULT" would not have told them.
#:
#: Its own token rather than one shared with the phone table, because what
#: stands in for a missing address row is a different thing from what stands in
#: for a missing phone row, and a token that suited both would be describing
#: neither.
#:
#: Descriptive, never a discriminant. Branch on ``source`` or ``answered``.
PRESENCE_ONLY = "PRESENCE_ONLY"

#: The one axis resolved here. Postcode pattern, required fields, field order
#: and the state flag all arrive from the same row, so there is nothing a
#: second provenance could disagree with.
JURISDICTION = "jurisdiction"


def _resolve_rules(country_code: str) -> tuple[dict[str, Any], Provenance]:
    """The rules that will answer for *country_code*, and where they came from.

    The single place the fallback happens, so no caller can take the generic
    rules without also taking the record that says it did.

    Args:
        country_code: Upper-cased ISO 3166-1 alpha-2 code, or anything else -
            an unknown code has no row, which is not an error.

    Returns:
        The rule dict, and a :class:`Provenance` on the ``jurisdiction`` axis.
    """
    rules = _COUNTRY_RULES.get(country_code)
    if rules is not None:
        return rules, declared(JURISDICTION, country_code)
    return _DEFAULT_RULES, fell_back(JURISDICTION, country_code, PRESENCE_ONLY)


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

    Attributes:
        passed: True when nothing failed. Passing under the generic rules is a
            much weaker statement than passing under a country's own, since the
            generic rules require only street, city and country and check no
            postcode at all; ``jurisdiction`` is what distinguishes them.
        country_code: The code that was asked about, never what answered.
        jurisdiction: Whose rules judged the address.
        errors: Field-level failures, in the order they were found.
    """

    passed: bool
    country_code: str
    jurisdiction: Provenance
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

        # Invalid UK postcode - missing space
        r = validate_address(
            {"street": "10 Downing St", "city": "London",
             "postcode": "SW1A2AA", "country": "GB"},
            "GB",
        )
        assert not r.passed
        assert r.error_fields == ["postcode"]
    """
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    errors: list[AddressFieldError] = []

    # Every message below names whatever actually imposed the requirement. A
    # country with no row here has its requirements set by the generic rules,
    # and saying "required for country 'FR'" would put France's name on a rule
    # France had no part in.
    imposed_by = f"country '{cc}'" if jurisdiction.answered else f"the generic rules; country '{cc}' has none published"

    # 1. Required-field check
    for fname in rules.get("required_fields", []):
        value = address.get(fname)
        if not value or not str(value).strip():
            errors.append(
                AddressFieldError(
                    field=fname,
                    code="required",
                    message=f"Field '{fname}' is required for {imposed_by}.",
                )
            )

    # 2. Postcode format check (only when a value is present or mandatory)
    #
    # This check and the state check below both name the country outright, and
    # that stays correct: the generic rules carry no postcode pattern and do
    # not require a state, so neither branch is reachable unless a real row
    # answered. Only the required-field check above can fire on generic rules.
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
        # Already caught by required-field check above - don't double-report.
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
        jurisdiction=jurisdiction,
        errors=errors,
    )


def get_address_field_order(country_code: str) -> tuple[list[str], Provenance]:
    """Return the display field order for the given country, and its source.

    Used by the UI to reorder address form fields without a round-trip. Falls
    back to the default order when the country has no dedicated entry, which is
    why the order alone was never enough to act on: street-postcode-city is a
    real order for the DACH countries and the stand-in for all the rest, and
    the two come back indistinguishable. A form that wants to say "we know how
    addresses are written here" needs the second half of this return value.

    To print an address rather than to lay out a form, use
    :func:`format_address_lines`. A field order cannot say which fields share a
    line, and a renderer that reads this alone has to invent that half.

    Returns:
        The field order, and a :class:`Provenance` on the ``jurisdiction`` axis.
    """
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    return list(rules.get("field_order", _DEFAULT_RULES["field_order"])), jurisdiction


# ── Rendering ─────────────────────────────────────────────────────────────────

#: The fields an address can answer with, and the only keys read from the dict
#: handed to :func:`format_address_lines`. Callers holding another spelling -
#: ``line1`` in the e-invoice party, ``postal_code`` in the project JSONB - map
#: it themselves rather than having a tolerant reader guess here, because a key
#: this module silently ignored would print an address with a part missing and
#: nothing anywhere would say so.
ADDRESS_FIELDS: tuple[str, ...] = ("street", "postcode", "city", "state", "country")


def _joined(separator: str, *parts: str) -> str:
    """Join the parts that carry a value, so a separator never leads or doubles."""
    return separator.join(part for part in parts if part)


def _postcode_before_city(f: dict[str, str], _rules: dict[str, Any]) -> list[str]:
    return [f["street"], _joined(" ", f["postcode"], f["city"]), f["state"], f["country"]]


def _postcode_after_city_and_state(f: dict[str, str], _rules: dict[str, Any]) -> list[str]:
    return [f["street"], _joined(" ", _joined(", ", f["city"], f["state"]), f["postcode"]), f["country"]]


def _postcode_on_its_own_line(f: dict[str, str], _rules: dict[str, Any]) -> list[str]:
    return [f["street"], f["city"], f["state"], f["postcode"], f["country"]]


def _postcode_before_city_and_state(f: dict[str, str], _rules: dict[str, Any]) -> list[str]:
    return [f["street"], _joined(" ", f["postcode"], _joined(" - ", f["city"], f["state"])), f["country"]]


def _declared_field_order(f: dict[str, str], rules: dict[str, Any]) -> list[str]:
    return [f[name] for name in rules["field_order"] if name in f]


_LOCALITY_SHAPES = {
    POSTCODE_BEFORE_CITY: _postcode_before_city,
    POSTCODE_AFTER_CITY_AND_STATE: _postcode_after_city_and_state,
    POSTCODE_ON_ITS_OWN_LINE: _postcode_on_its_own_line,
    POSTCODE_BEFORE_CITY_AND_STATE: _postcode_before_city_and_state,
    DECLARED_FIELD_ORDER: _declared_field_order,
}


def format_address_lines(
    address: dict[str, Any],
    country_code: str,
) -> tuple[list[str], Provenance]:
    """Render an address as the lines a recipient in that country expects.

    A German address printed in US order is not a formatting preference, it is
    an address a German recipient reads as malformed, and the reverse holds. The
    two facts that decide it are the sequence of the parts and which of them
    share a line; ``field_order`` carries the first and ``locality_shape`` the
    second, both off the same country row.

    A field the address does not answer produces no line rather than an empty
    one, so this never draws a gap at an offset a reader will take for a missing
    part of a real address. Whitespace counts as unanswered: the contacts
    directory stores addresses as a free-form dict, and a key present with a
    space in it is a shape that reaches here.

    On the fallback. It is the continental-European shape, not a neutral one,
    and it is what this product already printed for every country including the
    covered ones. So an uncovered country is not being guessed at any harder
    than it was before this function existed; it is the same statement, now with
    a record attached saying nobody published a rule for it. Read the
    ``Provenance`` before telling a user the address is written the way their
    country writes it.

    Args:
        address: Flat dict keyed by :data:`ADDRESS_FIELDS`. Unknown keys are
            ignored, and a caller with another spelling maps it first.
        country_code: ISO 3166-1 alpha-2, upper or lower case.

    Returns:
        The lines, top to bottom, and a :class:`Provenance` on the
        ``jurisdiction`` axis saying whose rules produced them.

    Examples::

        lines, _ = format_address_lines(
            {"street": "Hauptstr. 1", "postcode": "10115", "city": "Berlin"}, "DE"
        )
        assert lines == ["Hauptstr. 1", "10115 Berlin"]

        lines, _ = format_address_lines(
            {"street": "1 Main St", "city": "Boston", "state": "MA", "postcode": "02108"}, "US"
        )
        assert lines == ["1 Main St", "Boston, MA 02108"]
    """
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    fields = {name: str(address.get(name) or "").strip() for name in ADDRESS_FIELDS}
    shape = rules.get("locality_shape", _DEFAULT_RULES["locality_shape"])
    lines = _LOCALITY_SHAPES[shape](fields, rules)
    return [line for line in lines if line], jurisdiction


def get_address_rules(country_code: str) -> dict[str, Any]:
    """Return the full rule dict for a country (for config endpoints).

    Unlike the phone equivalent this never stamped a country code onto the
    generic rules, so it stated nothing false. It stated nothing at all: the
    dict for an uncovered country was byte-identical to the dict for another
    uncovered country, with no way to tell either from a real one.
    ``jurisdiction`` is that missing statement.

    Note that the rule dicts are not of uniform shape and this function does
    not make them so. ``postcode_optional`` is carried by the generic rules and
    by none of the country rows, and ``postcode_note`` only by GB and UK, so a
    consumer reading either key directly gets a value for an uncovered country
    and a ``KeyError`` for a covered one. Normalising that would mean deciding
    what ``postcode_optional`` means for eleven countries whose authors never
    said, which is a data question rather than a provenance one.

    Returns:
        A copy of the rules, plus ``jurisdiction``.
    """
    cc = (country_code or "").upper().strip()
    rules, jurisdiction = _resolve_rules(cc)
    return {**rules, "jurisdiction": jurisdiction}
