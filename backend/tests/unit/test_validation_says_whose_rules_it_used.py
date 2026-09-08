# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phone and address rules must say whose rules they are.

Fourteen countries have phone rules here and thirteen have address rules. Every
other country in the world is answered by a generic table, and until now the
answer said so nowhere: ``get_phone_rules("FR")`` returned the generic patterns
under ``country_code: "FR"``, and ``validate_phone`` stamped the requested
country onto a result the generic rules had produced.

The tests below are written so that they cannot pass against an implementation
that reports a fixed verdict. A covered country is asserted to be *declared*
rather than merely not-a-fallback, and an uncovered one is asserted to be
*fallback* rather than merely not-declared; an implementation that answered
UNAVAILABLE for everything would satisfy neither. Where the two cases diverge
they are asserted twice, once for what the value must be and once for what it
must not, because "not the old wrong answer" and "the right answer" are
different claims and only both together pin the behaviour.
"""

from __future__ import annotations

import pytest

from app.core.provenance import Source
from app.core.validation.address import (
    PRESENCE_ONLY,
    get_address_field_order,
    get_address_rules,
    validate_address,
)
from app.core.validation.phone import DIGIT_COUNT_ONLY, get_phone_rules, validate_phone

# Nine digits that Germany accepts and Canada does not, which is the pair the
# whole file turns on. Spelled once so no test can drift onto a different
# number and quietly stop testing the same thing.
NATIONAL = "301234567"


# ── Phone: which rules answered ──────────────────────────────────────────────


@pytest.mark.parametrize("cc", ["DE", "GB", "US", "CA", "JP"])
def test_a_country_with_its_own_phone_rules_reports_them_as_declared(cc: str) -> None:
    """Declared, not merely non-fallback.

    An implementation that stamped ``fallback: false`` on everything would pass
    a test asserting only ``not fallback``. This asserts the source itself, and
    that the country named as used is the country asked about.
    """
    jurisdiction = get_phone_rules(cc)["jurisdiction"]

    assert jurisdiction.source is Source.DECLARED
    assert jurisdiction.answered is True
    assert jurisdiction.requested == cc
    assert jurisdiction.used == cc
    assert jurisdiction.used != DIGIT_COUNT_ONLY


@pytest.mark.parametrize("cc", ["FR", "MX", "ZA", "XX"])
def test_a_country_without_phone_rules_is_judged_on_digit_count_and_says_so(cc: str) -> None:
    """Fallback, not merely non-declared, and naming the table that answered.

    ``XX`` is in the list deliberately: it is not a country at all, and the
    module has no concept of an unknown one. It is answered by the generic
    rules like any other uncovered code, and the point is that it says so.
    """
    jurisdiction = get_phone_rules(cc)["jurisdiction"]

    assert jurisdiction.source is Source.FALLBACK
    assert jurisdiction.answered is False
    assert jurisdiction.requested == cc
    assert jurisdiction.used == DIGIT_COUNT_ONLY
    assert jurisdiction.used != cc


def test_the_covered_and_uncovered_verdicts_are_not_the_same_verdict() -> None:
    """The control for a constant answer, stated as a single comparison.

    Every assertion above could be satisfied by two separate constants. This
    one cannot: it asks the two cases to disagree with each other.
    """
    assert get_phone_rules("DE")["jurisdiction"].source is not get_phone_rules("FR")["jurisdiction"].source


# ── Phone: the number itself ─────────────────────────────────────────────────


def test_a_covered_country_still_normalises_to_e164() -> None:
    """The fix must not have cost the working case."""
    result = validate_phone(NATIONAL, country_code="DE")

    assert result.passed is True
    assert result.e164 == "+49301234567"
    assert result.jurisdiction.source is Source.DECLARED


@pytest.mark.parametrize("cc", ["FR", "MX", "ZA", "XX"])
def test_the_generic_rules_never_invent_an_e164(cc: str) -> None:
    """The defect this file exists for, asserted as both halves.

    The generic rules carry no dial code, so there is nothing to build an
    E.164 from. The old code prefixed a bare plus, which produced a number
    belonging to whichever country owns that dial code - here ``+30``, which is
    Greece - and reported it valid. The two spellings it produced are named
    outright rather than covered by ``is None`` alone, so that a future
    implementation cannot reintroduce either and still pass.
    """
    result = validate_phone(NATIONAL, country_code=cc)

    assert result.e164 is None
    assert result.e164 != f"+{NATIONAL}"
    assert result.jurisdiction.source is Source.FALLBACK
    # The syntax check still ran and still has an opinion; it is the
    # normalisation that is unavailable, not the validation.
    assert result.passed is True


def test_a_trunk_zero_cannot_become_an_impossible_e164() -> None:
    """The sharper half of the same defect.

    ``+0...`` is not a possible E.164 number under any numbering plan, so this
    case needs no knowledge of dial codes to be recognised as broken. It was
    returned with ``passed`` True.
    """
    uncovered = validate_phone("0" + NATIONAL, country_code="FR")

    assert uncovered.e164 is None
    assert uncovered.e164 != "+0301234567"

    # The control that says the trunk zero is still handled where it is known.
    covered = validate_phone("0" + NATIONAL, country_code="DE")
    assert covered.e164 == "+49301234567"


def test_an_international_number_the_caller_supplied_is_not_thrown_away() -> None:
    """A fallback is an answer, and this one is the caller's own number.

    Nothing is being derived here, so the E.164 stays. What coverage changes is
    how thoroughly it was checked, and that is what the provenance records.
    """
    result = validate_phone("+33123456789", country_code="FR")

    assert result.passed is True
    assert result.e164 == "+33123456789"
    assert result.jurisdiction.source is Source.FALLBACK


def test_the_generic_rules_accept_what_a_covered_country_rejects() -> None:
    """Coverage turns a rejection into an acceptance, and the answer says which.

    This is the measurement that made the finding: the generic pattern accepts
    six to fifteen digits, which is looser than any national rule in the table,
    so the same digits are invalid for Canada and valid for its uncovered
    neighbours. Pinned here so that tightening the generic rule, or loosening
    Canada's, cannot quietly make the rest of this file vacuous.
    """
    rejected = validate_phone(NATIONAL, country_code="CA")
    accepted = validate_phone(NATIONAL, country_code="FR")

    assert rejected.passed is False
    assert rejected.jurisdiction.source is Source.DECLARED

    assert accepted.passed is True
    assert accepted.jurisdiction.source is Source.FALLBACK


def test_an_error_message_does_not_credit_rules_that_did_not_judge() -> None:
    """A message naming a jurisdiction is a claim about provenance too.

    Asserted as a difference between the two cases rather than by matching a
    phrase, because the wording will change and the distinction should not.
    """
    covered = validate_phone("12", country_code="DE").error_message
    uncovered = validate_phone("12", country_code="FR").error_message

    assert covered is not None
    assert uncovered is not None
    assert covered != uncovered
    assert "generic" in uncovered
    assert "generic" not in covered


# ── Address: the same question, a different shape of answer ──────────────────


@pytest.mark.parametrize("cc", ["DE", "GB", "US", "JP"])
def test_a_country_with_its_own_address_rules_reports_them_as_declared(cc: str) -> None:
    jurisdiction = get_address_rules(cc)["jurisdiction"]

    assert jurisdiction.source is Source.DECLARED
    assert jurisdiction.answered is True
    assert jurisdiction.used == cc


@pytest.mark.parametrize("cc", ["CA", "FR", "MX"])
def test_a_country_without_address_rules_reports_a_fallback(cc: str) -> None:
    jurisdiction = get_address_rules(cc)["jurisdiction"]

    assert jurisdiction.source is Source.FALLBACK
    assert jurisdiction.answered is False
    assert jurisdiction.requested == cc
    assert jurisdiction.used == PRESENCE_ONLY


def test_canada_has_phone_rules_and_no_address_rules() -> None:
    """The coverage tables disagree with each other, and that is not a typo here.

    Pinned because it is the case most likely to be reasoned about wrongly: the
    same country code is declared on one surface and a fallback on the other,
    so neither surface's answer can be assumed from the other's.
    """
    assert get_phone_rules("CA")["jurisdiction"].source is Source.DECLARED
    assert get_address_rules("CA")["jurisdiction"].source is Source.FALLBACK


def test_two_uncovered_countries_are_no_longer_indistinguishable() -> None:
    """What was actually wrong with the address getters.

    They never stamped a country code, so unlike the phone equivalent they
    stated nothing false. They stated nothing at all: these two dicts were
    byte-identical, and a caller holding one could not tell which country it
    had asked about, nor that it had been given a stand-in.
    """
    canada = get_address_rules("CA")
    france = get_address_rules("FR")

    rules_only = {k: v for k, v in canada.items() if k != "jurisdiction"}
    assert rules_only == {k: v for k, v in france.items() if k != "jurisdiction"}

    assert canada["jurisdiction"] != france["jurisdiction"]
    assert canada["jurisdiction"].requested == "CA"
    assert france["jurisdiction"].requested == "FR"


def test_the_field_order_carries_the_source_that_produced_it() -> None:
    """A real order and a stand-in order came back looking the same.

    Street-postcode-city is both the genuine order for the DACH countries and
    the generic one for all the rest, so the list alone was never enough for a
    form that wants to claim it knows how addresses are written here.

    The two differ here only by the state slot the generic order keeps for
    countries that might have one, and Germany does not. Nothing but the
    provenance separates the shape.
    """
    covered_order, covered = get_address_field_order("DE")
    uncovered_order, uncovered = get_address_field_order("CA")

    assert covered.source is Source.DECLARED
    assert uncovered.source is Source.FALLBACK
    assert covered_order == ["street", "postcode", "city", "country"]
    assert uncovered_order == ["street", "postcode", "city", "state", "country"]


def test_validate_address_says_whose_requirements_it_applied() -> None:
    """Required-field messages are the one address check the generic rules reach.

    The postcode and state checks cannot fire on the generic rules, which carry
    no pattern and require no state, so only this message could ever have
    credited a country that had nothing to do with the requirement.
    """
    covered = validate_address({"city": "Berlin", "country": "DE"}, "DE")
    uncovered = validate_address({"city": "Lyon", "country": "FR"}, "FR")

    assert covered.jurisdiction.source is Source.DECLARED
    assert uncovered.jurisdiction.source is Source.FALLBACK

    covered_message = next(e.message for e in covered.errors if e.field == "street")
    uncovered_message = next(e.message for e in uncovered.errors if e.field == "street")
    assert covered_message != uncovered_message
    assert "generic" in uncovered_message
    assert "generic" not in covered_message


# ── A recorded gap, pinned rather than fixed ─────────────────────────────────


def test_postcode_optional_is_present_only_on_the_rules_that_are_not_a_country() -> None:
    """A known defect, written down so it cannot be rediscovered by a crash.

    ``postcode_optional`` is carried by the generic rules and by none of the
    country rows, and ``postcode_note`` by GB and UK alone. So a consumer that
    branches on either key gets a usable value for every country we do not
    support and a ``KeyError`` for every country we do, which is the wrong way
    round twice over from a single cause.

    This is asserted as it currently stands rather than fixed. Filling the key
    in would mean deciding what "postcode optional" means for eleven countries
    whose authors never said, and that is a question about the data rather than
    about provenance. If someone answers it, this test fails and points at the
    decision instead of letting it happen silently.
    """
    covered = get_address_rules("DE")
    uncovered = get_address_rules("FR")

    assert "postcode_optional" in uncovered
    assert uncovered["postcode_optional"] is True
    assert "postcode_optional" not in covered

    with pytest.raises(KeyError):
        _ = covered["postcode_optional"]


@pytest.mark.parametrize("cc", ["AT", "AU", "BR", "CH", "CN", "DE", "IN", "JP", "NZ", "RU", "SG", "US"])
def test_no_country_row_answers_the_postcode_optional_question(cc: str) -> None:
    """The gap above is every country row, not one that was missed.

    Parametrised so the finding is a property of the table rather than of the
    one pair the previous test happens to compare. GB and UK are absent from
    this list because they carry a different extra key of their own, which is
    the same inconsistency seen from the other side.
    """
    assert "postcode_optional" not in get_address_rules(cc)
