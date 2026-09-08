# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A subcontractor's tax number, typed the way its own country prints it.

The failure this file exists to prevent is a lockout, and it is invisible from
the inside. A Swiss firm writes ``CHE-123.456.789 TVA`` because the number is
registered in a French-speaking canton; the form answers that the number is not
a Swiss VAT number, which is both wrong and unarguable, and the firm cannot be
registered at all. Nobody in the office that built the form ever types that
value, so the screen looks correct to everyone who tests it.

Two things therefore have to hold for every country in ``_TAX_ID_RULES``. The
canonical written form is accepted with its spacing, dots, hyphens and country
prefix, exactly as it comes off a letterhead. And every one of those spellings
reduces to one stored value, because a company entered off a letter and the same
company entered off an invoice must be the same number rather than two rows.

The third thing matters just as much and is easier to forget: a value that is
genuinely wrong for that country is still refused. A validator that accepts
everything satisfies the first two clauses perfectly, so each country here is
asserted against a value that belongs to nobody.

Sources
~~~~~~~
Each case names the authority that issues the identifier. The EU block follows
the VAT identification number structure the European Commission publishes for
VIES, which is what the ``EU VAT (xx)`` standard names in the table refer to;
that table was read in secondary documentation reproducing it, because the
Commission serves its own copy from script and it could not be fetched
directly. The non-EU cases were checked one by one against the national
authority named beside them. One case, the GB ``GD`` and ``HA`` series, is
covered only by the shape the product's own pattern declares: the variant
formats for government departments and health authorities are documented as
existing, but the two letters plus three digits were not confirmed from HMRC.

Synthetic values
~~~~~~~~~~~~~~~~
Every identifier in this file is made up. The digit runs are sequential or
repeating on purpose: these patterns are format checks with no checksum step, so
a structurally correct fake exercises them exactly as a real number would, and
committing a real company's tax number to a public repository would be worse
than useless. ``CHE-123.456.789 MWST`` is the specimen the Swiss Federal Tax
Administration itself prints in its own guidance, which is the one class of
real-looking value that is safe here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.modules.subcontractors.tax_id import _TAX_ID_RULES, validate_tax_id


@dataclass(frozen=True)
class TaxIdCase:
    """One shape of one country's identifier, and how people write it.

    ``written`` holds spellings of the *same* number that must all be accepted
    and must all reduce to ``canonical``. Where a country has two genuinely
    different shapes (a bare organisation number and the same number once it is
    VAT registered, say) they get two cases, not two entries in ``written``,
    because they are not the same value and must not collapse into one.
    """

    country: str
    standard: str
    canonical: str
    written: tuple[str, ...]
    refused: tuple[str, ...]


# ── EU VAT ──────────────────────────────────────────────────────────────
#
# Structure per member state as published by the European Commission for VIES.
# The country prefix is part of the printed number and optional on input; the
# table's patterns check the body alone.
_EU_CASES: tuple[TaxIdCase, ...] = (
    # AT: "ATU" + 8 digits. The U is part of the number, not of the prefix, so
    # it has to survive the prefix strip. (Umsatzsteuer-Identifikationsnummer,
    # Bundesministerium für Finanzen.)
    TaxIdCase(
        country="AT",
        standard="EU VAT (AT)",
        canonical="U12345678",
        written=("ATU 123 456 78", "ATU12345678", "atu12345678", "U12345678"),
        # A bare 8-digit run is the domestic Steuernummer, not the UID.
        refused=("12345678", "ATU1234567", "ATU123456789"),
    ),
    # BE: 10 digits, the enterprise number, always opening 0 or 1.
    TaxIdCase(
        country="BE",
        standard="EU VAT (BE)",
        canonical="0123456749",
        written=("BE 0123.456.749", "BE0123456749", "0123456749"),
        refused=("BE2123456749", "123456749"),
    ),
    # BG: 9 digits for a legal entity, 10 for a sole trader.
    TaxIdCase(
        country="BG",
        standard="EU VAT (BG)",
        canonical="123456789",
        written=("BG 123456789", "BG123456789", "123456789"),
        refused=("BG12345678", "BG12345678901"),
    ),
    TaxIdCase(
        country="BG",
        standard="EU VAT (BG)",
        canonical="1234567890",
        written=("BG 1234567890", "1234567890"),
        refused=("BG123456789012",),
    ),
    # CY: 8 digits plus one trailing letter.
    TaxIdCase(
        country="CY",
        standard="EU VAT (CY)",
        canonical="12345678L",
        written=("CY 12345678L", "CY12345678L", "12345678L"),
        refused=("CY123456789", "CYL2345678"),
    ),
    # CZ: 8 digits (legal entity) through 10 (individual).
    TaxIdCase(
        country="CZ",
        standard="EU VAT (CZ)",
        canonical="12345678",
        written=("CZ 12345678", "CZ12345678", "12345678"),
        refused=("CZ1234567", "CZ12345678901"),
    ),
    # DE: 9 digits, printed in threes.
    TaxIdCase(
        country="DE",
        standard="EU VAT (DE)",
        canonical="123456789",
        written=("DE 123 456 789", "DE123456789", "de-123.456.789", "123456789"),
        refused=("DE12345678", "DE1234567890", "DE12345678A"),
    ),
    # DK: 8 digits, the CVR number, printed in pairs.
    TaxIdCase(
        country="DK",
        standard="EU VAT (DK)",
        canonical="12345678",
        written=("DK 12 34 56 78", "DK12345678", "12345678"),
        refused=("DK123456789", "DK1234567"),
    ),
    # EE: 9 digits (KMKR number).
    TaxIdCase(
        country="EE",
        standard="EU VAT (EE)",
        canonical="123456789",
        written=("EE 123456789", "EE123456789", "123456789"),
        refused=("EE12345678", "EE1234567890"),
    ),
    # EL: 9 digits. Greece prints its VAT numbers with EL, not with its ISO
    # 3166 code GR; both keys exist in the table. See the GR case below and
    # ``TestGreecePrintsELAndIsFiledUnderGR``.
    TaxIdCase(
        country="EL",
        standard="EU VAT (EL)",
        canonical="123456789",
        written=("EL 123456789", "EL123456789", "123456789"),
        refused=("EL12345678", "EL1234567890"),
    ),
    # ES: the NIF, one leading character then 7 digits then one control
    # character. A company's opens with a letter for its legal form.
    TaxIdCase(
        country="ES",
        standard="EU VAT (ES)",
        canonical="A12345674",
        written=("ES A12345674", "ESA12345674", "A12345674"),
        refused=("ESA1234567", "ESAB1234567"),
    ),
    # FI: 8 digits (the business ID without its check-digit hyphen).
    TaxIdCase(
        country="FI",
        standard="EU VAT (FI)",
        canonical="12345671",
        written=("FI 12345671", "FI12345671", "12345671"),
        refused=("FI1234567", "FI123456712"),
    ),
    # FR: a 2-character key then the 9-digit SIREN. The key is alphanumeric
    # and excludes I and O, so a French body can legitimately open with two
    # letters - see ``TestAFrenchKeyThatIsItselfTwoLetters``.
    TaxIdCase(
        country="FR",
        standard="EU VAT (FR)",
        canonical="40123456789",
        written=("FR 40 123456789", "FR40123456789", "40123456789"),
        refused=("FR4012345678", "FRIO123456789"),
    ),
    # HR: 11 digits (OIB).
    TaxIdCase(
        country="HR",
        standard="EU VAT (HR)",
        canonical="12345678901",
        written=("HR 12345678901", "HR12345678901", "12345678901"),
        refused=("HR1234567890", "HR123456789012"),
    ),
    # HU: 8 digits (the first block of the domestic tax number).
    TaxIdCase(
        country="HU",
        standard="EU VAT (HU)",
        canonical="12345676",
        written=("HU 12345676", "HU12345676", "12345676"),
        refused=("HU1234567", "HU12345676-2-42"),
    ),
    # IE: 7 digits then one or two letters, the shape issued since 2013.
    TaxIdCase(
        country="IE",
        standard="EU VAT (IE)",
        canonical="1234567FA",
        written=("IE 1234567FA", "IE1234567FA", "1234567FA"),
        refused=("IE12345678", "IE1234567FAB"),
    ),
    # IE: the older 7 digits plus a single letter is still in circulation.
    TaxIdCase(
        country="IE",
        standard="EU VAT (IE)",
        canonical="1234567T",
        written=("IE 1234567T", "IE1234567T", "1234567T"),
        refused=("IE123456T",),
    ),
    # IT: 11 digits (partita IVA).
    TaxIdCase(
        country="IT",
        standard="EU VAT (IT)",
        canonical="12345678901",
        written=("IT 12345678901", "IT12345678901", "12345678901"),
        refused=("IT1234567890", "IT123456789012"),
    ),
    # LT: 9 digits for a legal entity, 12 for a natural person.
    TaxIdCase(
        country="LT",
        standard="EU VAT (LT)",
        canonical="123456789",
        written=("LT 123456789", "LT123456789", "123456789"),
        refused=("LT1234567890", "LT12345678"),
    ),
    TaxIdCase(
        country="LT",
        standard="EU VAT (LT)",
        canonical="123456789012",
        written=("LT 123456789012", "123456789012"),
        refused=("LT12345678901",),
    ),
    # LU: 8 digits.
    TaxIdCase(
        country="LU",
        standard="EU VAT (LU)",
        canonical="12345613",
        written=("LU 12345613", "LU12345613", "12345613"),
        refused=("LU1234561", "LU123456134"),
    ),
    # LV: 11 digits.
    TaxIdCase(
        country="LV",
        standard="EU VAT (LV)",
        canonical="12345678901",
        written=("LV 12345678901", "LV12345678901", "12345678901"),
        refused=("LV1234567890", "LV123456789012"),
    ),
    # MT: 8 digits.
    TaxIdCase(
        country="MT",
        standard="EU VAT (MT)",
        canonical="12345634",
        written=("MT 12345634", "MT12345634", "12345634"),
        refused=("MT1234563", "MT123456341"),
    ),
    # NL: 9 digits, then B, then a 2-digit sub-number. The B is part of the
    # number and is printed, so it has to be accepted.
    TaxIdCase(
        country="NL",
        standard="EU VAT (NL)",
        canonical="123456789B01",
        written=("NL 123456789B01", "NL123456789B01", "123456789B01"),
        refused=("NL123456789", "NL123456789B1", "NL123456789C01"),
    ),
    # PL: 10 digits (NIP), printed in blocks with hyphens.
    TaxIdCase(
        country="PL",
        standard="EU VAT (PL)",
        canonical="1234563218",
        written=("PL 123-456-32-18", "PL1234563218", "1234563218"),
        refused=("PL123456321", "PL12345632189"),
    ),
    # PT: 9 digits (NIF / NIPC).
    TaxIdCase(
        country="PT",
        standard="EU VAT (PT)",
        canonical="123456789",
        written=("PT 123 456 789", "PT123456789", "123456789"),
        refused=("PT12345678", "PT1234567890"),
    ),
    # RO: 2 to 10 digits (CIF). Short numbers are real and old.
    TaxIdCase(
        country="RO",
        standard="EU VAT (RO)",
        canonical="123456",
        written=("RO 123456", "RO123456", "123456"),
        refused=("RO1", "RO12345678901"),
    ),
    # SE: 12 digits, the organisation number plus a 2-digit suffix that is
    # almost always 01.
    TaxIdCase(
        country="SE",
        standard="EU VAT (SE)",
        canonical="123456789001",
        written=("SE 123456789001", "SE123456789001", "123456789001"),
        refused=("SE12345678900", "SE1234567890012"),
    ),
    # SI: 8 digits.
    TaxIdCase(
        country="SI",
        standard="EU VAT (SI)",
        canonical="12345679",
        written=("SI 12345679", "SI12345679", "12345679"),
        refused=("SI1234567", "SI123456799"),
    ),
    # SK: 10 digits.
    TaxIdCase(
        country="SK",
        standard="EU VAT (SK)",
        canonical="1234567890",
        written=("SK 1234567890", "SK1234567890", "1234567890"),
        refused=("SK123456789", "SK12345678901"),
    ),
    # GR: the same Greek number as EL above, reached through the ISO 3166 code.
    # Only the unprefixed body and a GR-prefixed body get through; the printed
    # EL form does not, which is pinned separately below.
    TaxIdCase(
        country="GR",
        standard="EU VAT (GR)",
        canonical="123456789",
        written=("123456789", "GR 123 456 789", "GR123456789"),
        refused=("GR12345678", "GR1234567890"),
    ),
)


# ── Outside the EU ──────────────────────────────────────────────────────
_NON_EU_CASES: tuple[TaxIdCase, ...] = (
    # GB: 9 digits for an ordinary registration. (HMRC VAT registration
    # number.)
    TaxIdCase(
        country="GB",
        standard="GB VRN",
        canonical="123456789",
        written=("GB 123 4567 89", "GB123456789", "123456789"),
        refused=("GB12345678", "GB1234567890"),
    ),
    # GB: 12 digits for a VAT group or a branch trader.
    TaxIdCase(
        country="GB",
        standard="GB VRN",
        canonical="123456789012",
        written=("GB 123456789012", "123456789012"),
        refused=("GB12345678901",),
    ),
    # GB: HMRC documents variant formats for government departments and health
    # authorities without publishing their shape where it could be read here.
    # These two cases therefore assert only the shape the product's own pattern
    # declares, GD or HA plus 3 digits, rather than a confirmed written form.
    TaxIdCase(
        country="GB",
        standard="GB VRN",
        canonical="GD001",
        written=("GBGD001", "GB GD001", "GD001"),
        refused=("GBGD0011", "GBGD01"),
    ),
    TaxIdCase(
        country="GB",
        standard="GB VRN",
        canonical="HA501",
        written=("GBHA501", "GB HA501", "HA501"),
        refused=("GBHA5011",),
    ),
    # US: the EIN is 9 digits, printed with a hyphen after the first two.
    # (Internal Revenue Service.)
    TaxIdCase(
        country="US",
        standard="US EIN",
        canonical="123456789",
        written=("12-3456789", "12 3456789", "123456789"),
        refused=("12-345678", "12-34567890"),
    ),
    # CH: the UID, printed CHE-123.456.789, plus the VAT suffix in the
    # language of the region: MWST, TVA or IVA. The Federal Tax Administration
    # names those three and does not permit an English "VAT". The E belongs to
    # the number, so it has to survive the CH prefix strip.
    TaxIdCase(
        country="CH",
        standard="CH UID",
        canonical="E123456789MWST",
        written=(
            "CHE-123.456.789 MWST",
            "CHE 123 456 789 MWST",
            "CHE123456789MWST",
            "che-123.456.789 mwst",
        ),
        refused=("CHE-123.456.78 MWST", "CHE-123.456.789 VAT", "CHE-1234567890 MWST"),
    ),
    # CH: the bare UID, before the firm is VAT registered. A different value
    # from the one above, and deliberately so - the suffix is what says the
    # firm is in the VAT register.
    TaxIdCase(
        country="CH",
        standard="CH UID",
        canonical="E123456789",
        written=("CHE-123.456.789", "CHE 123 456 789", "CHE123456789"),
        refused=("CHE-123.456.78",),
    ),
    # NO: the 9-digit organisation number from the Brønnøysund Register
    # Centre, followed by MVA once the entity is in the VAT register.
    TaxIdCase(
        country="NO",
        standard="NO Org.nr",
        canonical="123456789MVA",
        written=("NO 123 456 789 MVA", "123 456 789 MVA", "123456789MVA"),
        refused=("12345678MVA", "1234567890MVA"),
    ),
    TaxIdCase(
        country="NO",
        standard="NO Org.nr",
        canonical="123456789",
        written=("NO 123 456 789", "123 456 789"),
        refused=("12345678",),
    ),
    # AU: the ABN is 11 digits, printed in a 2-3-3-3 grouping.
    # (Australian Business Register.)
    TaxIdCase(
        country="AU",
        standard="AU ABN",
        canonical="12345678901",
        written=("12 345 678 901", "12345678901"),
        refused=("1234567890", "123456789012"),
    ),
    # CA: the 9-digit business number plus the GST/HST program account, which
    # is the 2-letter code RT and a 4-digit reference. (Canada Revenue Agency.)
    TaxIdCase(
        country="CA",
        standard="CA BN9/15",
        canonical="123456789RT0001",
        written=("123456789 RT0001", "123456789RT0001", "123456789-RT0001"),
        refused=("12345678RT0001", "123456789RT001"),
    ),
    TaxIdCase(
        country="CA",
        standard="CA BN9/15",
        canonical="123456789",
        written=("123456789", "123 456 789"),
        refused=("12345678",),
    ),
    # BR: the CNPJ is 14 digits, printed 00.000.000/0000-00.
    # (Receita Federal do Brasil.)
    TaxIdCase(
        country="BR",
        standard="BR CNPJ",
        canonical="12345678000195",
        written=("12.345.678/0001-95", "12345678000195"),
        refused=("12.345.678/0001-9", "12.345.678/0001-955"),
    ),
    # IN: the GSTIN is 15 characters - 2-digit state code, 10-character PAN,
    # 1-digit entity number, a literal Z, 1 check character. (GST portal.)
    TaxIdCase(
        country="IN",
        standard="IN GSTIN",
        canonical="27AAAAA0000A1Z5",
        written=("27AAAAA0000A1Z5", "27 AAAAA 0000 A 1Z5", "27aaaaa0000a1z5"),
        # A 14th character that is not Z, and a value one character short.
        refused=("27AAAAA0000A1Y5", "27AAAAA0000A1Z"),
    ),
    # AE: the TRN is 15 digits and opens with 100. (Federal Tax Authority.)
    TaxIdCase(
        country="AE",
        standard="AE TRN",
        canonical="100123456700003",
        written=("100 1234 5670 0003", "100123456700003"),
        refused=("10012345670000", "1001234567000031"),
    ),
    # SA: the VAT registration number is 15 digits, opening and closing on 3.
    # (Zakat, Tax and Customs Authority.)
    TaxIdCase(
        country="SA",
        standard="SA TRN",
        canonical="300123456700003",
        written=("300 1234 5670 0003", "300123456700003"),
        refused=("30012345670000", "3001234567000031"),
    ),
    # TR: the VKN is 10 digits for a company. (Gelir İdaresi Başkanlığı.)
    TaxIdCase(
        country="TR",
        standard="TR VKN",
        canonical="1234567890",
        written=("TR 1234567890", "1234567890"),
        refused=("123456789", "TR123456789012"),
    ),
    # TR: a sole trader is filed under the 11-digit national identity number.
    TaxIdCase(
        country="TR",
        standard="TR VKN",
        canonical="12345678901",
        written=("TR 12345678901", "12345678901"),
        refused=("TR123456789012",),
    ),
    # RU: the INN is 10 digits for a legal entity. (Federal Tax Service.)
    TaxIdCase(
        country="RU",
        standard="RU INN",
        canonical="7712345678",
        written=("RU 7712345678", "7712345678"),
        refused=("771234567", "77123456789"),
    ),
    # RU: 12 digits for an individual, including a sole trader.
    TaxIdCase(
        country="RU",
        standard="RU INN",
        canonical="771234567890",
        written=("RU 771234567890", "771234567890"),
        refused=("7712345678901",),
    ),
    # ZA: 10 digits, always opening with 4. (South African Revenue Service.)
    TaxIdCase(
        country="ZA",
        standard="ZA VAT",
        canonical="4123456789",
        written=("4123 456 789", "4123456789"),
        refused=("412345678", "41234567890"),
    ),
)

_CASES: tuple[TaxIdCase, ...] = _EU_CASES + _NON_EU_CASES


def _written_params() -> list[object]:
    return [
        pytest.param(case, spelling, id=f"{case.country}-{case.canonical}-{n}")
        for case in _CASES
        for n, spelling in enumerate(case.written)
    ]


def _refused_params() -> list[object]:
    return [pytest.param(case, value, id=f"{case.country}-{value}") for case in _CASES for value in case.refused]


def test_every_country_the_product_tabulates_has_a_case_here():
    """The table is the whole mechanism, so say what this is decided against.

    Set equality rather than a count: a count survives a country being swapped
    out for another one, which is exactly the change that would leave a market
    untested while the number at the bottom of the file stayed reassuring.
    """
    covered = {case.country for case in _CASES}
    tabulated = set(_TAX_ID_RULES)
    assert covered == tabulated, (
        f"not covered: {sorted(tabulated - covered)}; covered but untabulated: {sorted(covered - tabulated)}"
    )


@pytest.mark.parametrize(("case", "spelling"), _written_params())
def test_the_form_a_country_writes_its_number_in_is_accepted(case: TaxIdCase, spelling: str):
    """Spacing, dots, hyphens and the country prefix, as typed off a letterhead."""
    result = validate_tax_id(case.country, spelling)
    assert result.format_valid, f"{case.country} refused its own written form {spelling!r}: {result.reason}"
    assert result.standard == case.standard


@pytest.mark.parametrize("case", [pytest.param(c, id=f"{c.country}-{c.canonical}") for c in _CASES])
def test_every_spelling_of_one_number_is_stored_as_the_same_value(case: TaxIdCase):
    """One number, however it was written, comes back as one canonical value.

    What this pins is the validation endpoint's answer, and only that.
    ``create_subcontractor`` still stores ``data.tax_id`` as it was typed, and
    the value asserted here is never written anywhere. What keeps two spellings
    of one number from becoming two rows is the separate identity key,
    ``canonical_tax_id``, which ``find_by_tax_id`` compares instead of the raw
    column; that half lives in
    ``test_one_tax_number_is_one_subcontractor_however_it_is_spelled.py``.
    """
    stored = {validate_tax_id(case.country, spelling).tax_id_normalised for spelling in case.written}
    assert stored == {case.canonical}


@pytest.mark.parametrize(("case", "value"), _refused_params())
def test_a_value_that_is_wrong_for_this_country_is_still_refused(case: TaxIdCase, value: str):
    """The half that lets this file fail.

    Accepting the written form is a widening, and a widening that went too far
    would satisfy every assertion above while validating nothing at all.
    """
    result = validate_tax_id(case.country, value)
    assert not result.format_valid, f"{case.country} accepted {value!r}, which is not one of its numbers"
    assert result.standard == case.standard
    assert result.reason == f"format_mismatch:{case.standard}"


class TestTheSwissSuffixIsNamedInTheLanguageOfTheRegion:
    """MWST, TVA and IVA are one number written three ways, not three numbers.

    A UID registered in Zurich prints MWST, the same shape in Geneva prints
    TVA and in Lugano IVA. The Federal Tax Administration names all three and
    permits no English "VAT". A rule that knows only the German spelling tells
    two thirds of the country that its VAT number is not a VAT number.
    """

    _SUFFIXES = ("MWST", "TVA", "IVA")

    @pytest.mark.parametrize("suffix", _SUFFIXES)
    def test_each_language_reaches_the_same_verdict(self, suffix: str):
        result = validate_tax_id("CH", f"CHE-123.456.789 {suffix}")
        assert result.format_valid
        assert result.standard == "CH UID"

    def test_the_suffix_is_kept_rather_than_folded_into_one_spelling(self):
        """The validator echoes the suffix it read; only the identity key folds it.

        The three suffixes are accepted and each comes back as it was written,
        so the form can show what was understood and the stored value keeps the
        register mark the letterhead carried. Whether the same firm entered
        from a German letter and from a French one is one row is decided by
        ``canonical_tax_id`` in the register, not here: that key drops the
        suffix, and Norway's MVA with it, and is pinned in
        ``test_one_tax_number_is_one_subcontractor_however_it_is_spelled.py``.
        """
        stored = {validate_tax_id("CH", f"CHE-123.456.789 {s}").tax_id_normalised for s in self._SUFFIXES}
        assert stored == {"E123456789MWST", "E123456789TVA", "E123456789IVA"}
        assert validate_tax_id("CH", "CHE-123.456.789").tax_id_normalised == "E123456789"

    def test_an_english_suffix_is_not_a_swiss_vat_number(self):
        """Widening to three languages is not widening to any word at all."""
        assert not validate_tax_id("CH", "CHE-123.456.789 VAT").format_valid


class TestAFrenchKeyThatIsItselfTwoLetters:
    """The country prefix is not always a country prefix.

    A French VAT number is a 2-character key then the 9-digit SIREN, and the
    key is alphanumeric. When the key happens to be the letters FR, the number
    typed without its prefix opens with the same two letters the prefix strip
    is looking for, and stripping them leaves a 9-character body that no
    French pattern can match. Roughly one French key in a thousand looks like
    this, which is few enough that nobody reports it and many enough that
    somebody hits it.
    """

    def test_the_number_typed_without_its_prefix_is_accepted(self):
        result = validate_tax_id("FR", "FR123456789")
        assert result.format_valid, f"a French key of FR was read as a prefix: {result.reason}"
        assert result.tax_id_normalised == "FR123456789"

    def test_the_same_number_typed_with_its_prefix_is_the_same_value(self):
        assert validate_tax_id("FR", "FRFR123456789").tax_id_normalised == "FR123456789"
        assert validate_tax_id("FR", "FR FR 123 456 789").tax_id_normalised == "FR123456789"

    def test_an_ordinary_numeric_key_still_reduces_to_its_body(self):
        """Offering the unstripped form must not stop the stripped one winning."""
        assert validate_tax_id("FR", "FR40123456789").tax_id_normalised == "40123456789"

    def test_a_key_using_the_excluded_letters_is_refused(self):
        """I and O are excluded from the key so they cannot be read as 1 and 0."""
        assert not validate_tax_id("FR", "FRIO123456789").format_valid


class TestGreecePrintsELAndIsFiledUnderGR:
    """Greece is the one member state whose VAT prefix is not its ISO code.

    Its numbers are printed EL123456789 while the country field elsewhere in
    this product carries ISO 3166 codes, and ``seed.py`` confirms that split:
    it stores an ISO country beside a separately-declared VAT prefix. The
    table holds both keys, but only the one that matches the country field is
    consulted, so a Greek number typed exactly as it is printed is refused
    whenever the country is recorded as GR.

    Pinned rather than fixed: which of the two keys the caller supplies is a
    product decision about the country field, not something a test may settle.
    """

    def test_the_printed_form_is_accepted_when_the_country_is_given_as_el(self):
        result = validate_tax_id("EL", "EL 123 456 789")
        assert result.format_valid
        assert result.tax_id_normalised == "123456789"

    def test_the_printed_form_is_refused_when_the_country_is_given_as_gr(self):
        result = validate_tax_id("GR", "EL 123 456 789")
        assert not result.format_valid
        assert result.reason == "format_mismatch:EU VAT (GR)"

    def test_the_bare_body_is_accepted_under_either_key(self):
        assert validate_tax_id("GR", "123456789").format_valid
        assert validate_tax_id("EL", "123456789").format_valid


def test_a_value_that_is_nothing_but_punctuation_says_so_rather_than_mismatching():
    """An empty field is a different message from a wrong number."""
    for blank in ("", "   ", "-- . /"):
        result = validate_tax_id("DE", blank)
        assert not result.format_valid
        assert result.reason == "empty_after_normalisation"


#: The member states of the European Union, ISO 3166-1 alpha-2, as of 2026.
_EU_MEMBER_STATES: frozenset[str] = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
        "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    }
)  # fmt: skip


def test_the_eu_block_is_the_whole_union_and_greece_answers_to_both_of_its_codes():
    """What the table's EU block holds, stated as the property and not a count.

    The comment above the table once said twenty-two member states beside a
    block of twenty-eight keys, and nothing could contradict it because nothing
    read it. The property is that every member state has a rule, and that
    Greece is keyed twice: VIES prints its numbers with EL while ISO 3166 calls
    the country GR, and a form fed from a country picker sends the ISO code.
    Set equality names the missing or the surplus state rather than a number.
    """
    eu_keys = {code for code, (standard, _pattern) in _TAX_ID_RULES.items() if standard.startswith("EU VAT")}
    assert {"EL", "GR"} <= eu_keys
    assert eu_keys - {"EL"} == _EU_MEMBER_STATES, (
        f"missing: {sorted(_EU_MEMBER_STATES - eu_keys)}; surplus: {sorted(eu_keys - {'EL'} - _EU_MEMBER_STATES)}"
    )
