# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The bank account an e-invoice tells the buyer to pay into (BT-84, BT-86).

A mistyped IBAN is not caught downstream by anything the sender sees. The
receiver's validator checks the syntax of the document, not whether the account
exists, so the invoice passes, gets sent, and the payment fails weeks later. The
check-digit test is the only one available at the point of entry, and it catches
every single-character slip and almost every transposition.
"""

from __future__ import annotations

import pytest

from app.modules.einvoice.bank import (
    InvalidBankDetail,
    country_uses_iban,
    iban_countries,
    is_bic,
    is_iban,
    normalise_bic,
    normalise_iban,
    normalise_payment_account,
    normalise_payment_provider,
)

# Synthetic throughout, and deliberately so: none of these is a real account at
# a real bank. The IBANs in ``TestIban`` are the examples published by the
# scheme itself (the ECBS German specimen and its national equivalents), which
# is the one class of real-looking value it is safe to commit. The non-IBAN
# identifiers below are made up digit runs, and they can be, because the whole
# point of the country branch is that this product does not check them.
_SYNTHETIC_US_ACCOUNT = "000123456789"
# Nine nines: the right length for an ABA routing number, not a real one. Real
# routing numbers carry their own check digit and belong to a named bank, so no
# real one appears here even as an illustration.
_SYNTHETIC_US_ROUTING = "999999999"
_SYNTHETIC_IFSC = "ZZZZ0123456"
_PUBLISHED_DE_IBAN = "DE02120300000000202051"


class TestIban:
    def test_a_valid_account_is_accepted_and_stored_without_its_spacing(self):
        """Printed in groups of four, stored as the wire format."""
        assert normalise_iban("DE02 1203 0000 0000 2020 51") == "DE02120300000000202051"

    def test_lower_case_is_accepted_and_normalised(self):
        assert normalise_iban("de02120300000000202051") == "DE02120300000000202051"

    def test_a_single_mistyped_digit_is_refused(self):
        """The whole point: this is the error no later step can catch."""
        with pytest.raises(InvalidBankDetail):
            normalise_iban("DE02120300000000202052")

    def test_two_transposed_digits_are_refused(self):
        with pytest.raises(InvalidBankDetail):
            normalise_iban("DE02120300000000200251")

    def test_the_wrong_length_for_a_known_country_is_refused(self):
        """A German account is 22 characters, and a 21-character one is a typo."""
        with pytest.raises(InvalidBankDetail):
            normalise_iban("DE0212030000000020205")

    def test_an_untabulated_country_is_accepted_on_its_check_digits_alone(self):
        """A country we did not tabulate must not lock a firm out of the screen.

        The length table is a convenience, not the standard, and it will fall
        behind the registry. Anything structurally plausible whose check digits
        agree is accepted, because refusing it would be this product asserting
        that a country does not exist.
        """
        unknown = _synthetic_iban("QQ")  # QQ is unassigned, so it cannot be in the table
        assert normalise_iban(unknown) == unknown

    def test_something_that_is_not_an_account_at_all_is_refused(self):
        for junk in ["", "   ", "DE", "1234567890", "DE02-1203/0000", "DEAA120300000000202051"]:
            with pytest.raises(InvalidBankDetail):
                normalise_iban(junk)

    def test_a_country_code_that_is_not_two_letters_is_refused(self):
        with pytest.raises(InvalidBankDetail):
            normalise_iban("D102120300000000202051")

    @pytest.mark.parametrize(
        "iban",
        [
            "DE02120300000000202051",
            "FR1420041010050500013M02606",
            "GB29NWBK60161331926819",
            "NL91ABNA0417164300",
            "IT60X0542811101000000123456",
            "ES9121000418450200051332",
            "PL61109010140000071219812874",
            "NO9386011117947",
        ],
    )
    def test_published_examples_from_eight_countries_pass(self, iban: str):
        """A sender's own country is not the only one it invoices from."""
        assert normalise_iban(iban) == iban

    def test_an_empty_value_can_be_cleared_when_that_is_allowed(self):
        """Leaving the account blank is how a user removes it, not an error."""
        assert normalise_iban("", allow_empty=True) == ""
        assert normalise_iban("   ", allow_empty=True) == ""


def _synthetic_iban(country: str) -> str:
    """Build a checksum-correct IBAN for a country outside the length table."""
    body = "CBZZ12345678901234"
    rearranged = body + country + "00"
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    check = 98 - (int(numeric) % 97)
    return f"{country}{check:02d}{body}"


class TestPaymentAccountFollowsTheSellersCountry:
    """BT-84 is a payment account identifier, and only sometimes an IBAN.

    The failure this class exists to prevent is a lockout, not a bad document.
    A contractor in Houston has a routing number and an account number, and a
    screen that refuses both leaves the company with no way to say how it is
    paid. Refusing a real account is worse than storing an odd one, because the
    user cannot proceed at all and is told only that their account "is not an
    IBAN", which is true and useless.

    Every assertion below is paired, because a validator that accepts
    everything passes the American half on its own. The strictness that
    protects a German seller has to survive the widening that rescues an
    American one, so each country is asserted against the value that belongs to
    the other.
    """

    def test_the_population_this_is_decided_against(self):
        """The country list is the whole mechanism, so state its size out loud."""
        countries = iban_countries()
        assert len(countries) == 79, f"IBAN registry population changed: {len(countries)} countries"
        # The nine markets the audit was written against, split the way the
        # product must split them.
        assert [c for c in ("DE", "FR", "GB", "TR") if country_uses_iban(c)] == ["DE", "FR", "GB", "TR"]
        assert [c for c in ("US", "CA", "IN", "CN", "RU", "AU") if country_uses_iban(c)] == []

    @pytest.mark.parametrize(
        ("country", "value"),
        [
            ("US", _SYNTHETIC_US_ACCOUNT),
            ("US", _SYNTHETIC_US_ROUTING),
            ("IN", _SYNTHETIC_IFSC),
            ("CA", "12345678901"),
            ("AU", "123456789"),
            ("CN", "123456789012345678"),
            ("RU", "40702810000000012345"),
        ],
    )
    def test_a_domestic_account_is_kept_where_the_country_issues_no_iban(self, country: str, value: str):
        """The half that is broken today: none of these can be stored at all."""
        assert normalise_payment_account(value, country=country) == value

    @pytest.mark.parametrize("country", ["DE", "FR", "NL", "TR"])
    def test_the_same_value_is_still_refused_where_the_country_does_issue_one(self, country: str):
        """The other direction, and the reason this is not just a widening.

        Nothing downstream checks an IBAN. BR-DE-19/20 are recorded in
        ``rules.py`` as real gaps, so if a bare domestic number were accepted
        here for a German seller it would reach the buyer unchecked. This is the
        only place that mistake can still be caught.
        """
        with pytest.raises(InvalidBankDetail):
            normalise_payment_account(_SYNTHETIC_US_ACCOUNT, country=country)

    def test_an_iban_is_still_checked_in_full_for_a_seller_who_uses_no_iban(self):
        """A Texan contractor may well be paid into a European account.

        The value is self-identifying, so the country does not get to switch the
        check digits off. A typo in an IBAN is a typo wherever the seller sits.
        """
        assert normalise_payment_account(_PUBLISHED_DE_IBAN, country="US") == _PUBLISHED_DE_IBAN
        with pytest.raises(InvalidBankDetail):
            normalise_payment_account("DE02120300000000202052", country="US")

    def test_an_unset_country_permits_rather_than_blocks(self):
        """The state every configuration starts in must be savable.

        The seller's country is a field on the same form. Refusing the account
        until the country is filled in would make the order the two fields are
        typed in decide whether the form can be submitted.
        """
        assert normalise_payment_account(_SYNTHETIC_US_ACCOUNT, country="") == _SYNTHETIC_US_ACCOUNT

    def test_what_is_not_an_account_anywhere_is_still_refused(self):
        """Widening is not the same as accepting anything."""
        for junk in ["", "   ", "AB", "12", "12/34/56"]:
            with pytest.raises(InvalidBankDetail):
                normalise_payment_account(junk, country="US")

    def test_a_bank_code_follows_the_same_split(self):
        """BT-86 is a payment service provider identifier, not a BIC."""
        assert normalise_payment_provider(_SYNTHETIC_US_ROUTING, country="US") == _SYNTHETIC_US_ROUTING
        assert normalise_payment_provider("cobadeff", country="US") == "COBADEFF"
        with pytest.raises(InvalidBankDetail):
            normalise_payment_provider(_SYNTHETIC_US_ROUTING, country="DE")

    def test_a_twelve_digit_chinese_bank_code_does_not_fit_and_says_so(self):
        """A known gap, asserted so it is a decision rather than a surprise.

        BT-86 is stored in an eleven-character column, which is the width of a
        BIC. A CNAPS code is twelve digits. Widening the column is what closes
        this, and until then the refusal is at least legible.
        """
        with pytest.raises(InvalidBankDetail):
            normalise_payment_provider("123456789012", country="CN")

    def test_what_the_document_writers_ask_before_naming_the_instrument(self):
        """``is_iban`` decides IBANID versus ProprietaryID, so pin it here."""
        assert is_iban(_PUBLISHED_DE_IBAN)
        assert not is_iban(_SYNTHETIC_US_ACCOUNT)
        assert not is_iban("DE02120300000000202052")
        assert is_bic("COBADEFFXXX")
        assert not is_bic(_SYNTHETIC_US_ROUTING)


class TestBic:
    def test_an_eight_character_code_is_accepted(self):
        assert normalise_bic("cobadeff") == "COBADEFF"

    def test_an_eleven_character_code_with_a_branch_is_accepted(self):
        assert normalise_bic("COBADEFFXXX") == "COBADEFFXXX"

    def test_a_nine_character_code_is_refused(self):
        """ISO 9362 has no nine or ten character form."""
        with pytest.raises(InvalidBankDetail):
            normalise_bic("COBADEFFX")

    def test_a_code_whose_country_is_not_letters_is_refused(self):
        with pytest.raises(InvalidBankDetail):
            normalise_bic("COBA12FF")

    def test_an_empty_value_can_be_cleared_when_that_is_allowed(self):
        assert normalise_bic("", allow_empty=True) == ""
