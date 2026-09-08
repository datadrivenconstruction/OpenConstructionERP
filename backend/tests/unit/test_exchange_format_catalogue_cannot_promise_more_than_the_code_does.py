# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The exchange catalogue is a claim about this product, so it is tested as one.

Every row on the world formats screen tells a user whether we can read or
write their market's document. A row that says "native" where no reader
exists is not a cosmetic bug: they will send the file, watch it fail, and
have no reason to try the format that would have worked.

The catalogue is built so that it cannot say that, by computing both
verdicts from the importer and exporter registries instead of storing
them. These tests hold that construction in place. Most of them would
pass trivially against a hand-written table, which is the point: they are
here so that the day someone finds the computation inconvenient and
replaces it with a literal, the literal has to be right and has to stay
right.
"""

from __future__ import annotations

import json
from string import ascii_uppercase

import pytest

from app.modules.boq.exchange_formats import (
    EXCHANGE_FORMATS,
    ExchangeFormat,
    build_catalogue,
    default_format_for_country,
    describe_formats,
    export_support,
    format_by_id,
    formats_for_country,
    import_support,
)
from app.modules.boq.exporters import REGISTERED_EXPORTERS
from app.modules.boq.importers import REGISTERED_IMPORTERS

READER_IDS = frozenset(importer.format_id for importer in REGISTERED_IMPORTERS)
WRITER_IDS = frozenset(exporter.format_id for exporter in REGISTERED_EXPORTERS)


def test_no_row_claims_native_import_without_an_importer_that_reads_it() -> None:
    for fmt in EXCHANGE_FORMATS:
        if import_support(fmt) == "native":
            assert fmt.reader in READER_IDS, (
                f"{fmt.format_id} says it imports natively but names reader "
                f"{fmt.reader!r}, which is not in REGISTERED_IMPORTERS"
            )


def test_no_row_claims_native_export_without_a_writer_that_produces_it() -> None:
    for fmt in EXCHANGE_FORMATS:
        if export_support(fmt) == "native":
            assert fmt.writer in WRITER_IDS, (
                f"{fmt.format_id} says it exports natively but names writer "
                f"{fmt.writer!r}, which is not in REGISTERED_EXPORTERS"
            )


def test_a_reader_named_by_a_row_is_a_reader_that_exists() -> None:
    """The other direction: a row may not point at a reader we never had.

    Distinct from the test above, which only looks at rows currently
    reporting native. A row naming a misspelled importer would report
    "assisted" and pass that one while quietly never being able to
    improve, because the name it is waiting on will never arrive.
    """
    for fmt in EXCHANGE_FORMATS:
        if fmt.reader is not None:
            assert fmt.reader in READER_IDS, f"{fmt.format_id} names an importer that does not exist: {fmt.reader!r}"
        if fmt.writer is not None:
            assert fmt.writer in WRITER_IDS, f"{fmt.format_id} names an exporter that does not exist: {fmt.writer!r}"


def test_every_registered_exporter_names_a_route_the_router_actually_serves() -> None:
    """The weak link in the exporter registry is the route, which is a string.

    Nothing stops someone renaming an export route and leaving the
    registry pointing at the old one; the format would keep reporting
    native and the download would 404. So the strings are resolved
    against the router's real path table.
    """
    from app.modules.boq.router import router

    served = {getattr(route, "path", "") for route in router.routes}
    for exporter in REGISTERED_EXPORTERS:
        wanted = f"/{exporter.route}"
        assert any(path.rstrip("/").endswith(wanted) for path in served), (
            f"exporter {exporter.format_id} points at {exporter.route!r}, which no route in the BOQ router serves"
        )


def test_a_market_workbook_stays_guided_until_the_importer_knows_its_language() -> None:
    """A workbook row is only native if its column words are understood.

    Reading a Vietnamese workbook with an English header table does not
    fail loudly, it mismaps columns, which is worse. So the row is not
    allowed to say native on the strength of the importer existing.
    """
    from app.modules.boq.importers.excel import SUPPORTED_HEADER_LANGUAGES

    for fmt in EXCHANGE_FORMATS:
        if fmt.header_language is None:
            continue
        level = import_support(fmt)
        if fmt.header_language in SUPPORTED_HEADER_LANGUAGES:
            assert level == "native", f"{fmt.format_id} is in a known language but reports {level}"
        else:
            assert level != "native", (
                f"{fmt.format_id} claims native import, but the spreadsheet importer "
                f"does not know column headings in {fmt.header_language!r}"
            )


def test_taking_an_importer_away_downgrades_every_row_that_named_it() -> None:
    """The property the whole design exists for, exercised directly.

    Rather than deleting an importer, the registry view is narrowed and
    the same rows are asked again. If capability were stored rather than
    computed, the answers would not move.
    """
    without_gaeb = READER_IDS - {"gaeb_xml"}
    gaeb = format_by_id("gaeb_xml")
    assert gaeb is not None
    assert import_support(gaeb) == "native"
    # No reader, and a GAEB file is XML, which the guided path can attempt.
    assert import_support(gaeb, readers=without_gaeb) == "assisted"

    without_excel = READER_IDS - {"excel"}
    for fmt in EXCHANGE_FORMATS:
        if fmt.reader == "excel":
            assert import_support(fmt, readers=without_excel) != "native", (
                f"{fmt.format_id} still claims native import with the spreadsheet reader removed"
            )


def test_a_row_with_no_readable_shape_admits_it_rather_than_offering_guidance() -> None:
    """ "assisted" has to mean something, so it cannot be the answer to everything."""
    unreadable = ExchangeFormat(
        format_id="sealed_archive",
        name="Sealed archive",
        countries=("XX",),
        extensions=(".sealed",),
        summary="A container the guided import cannot open.",
    )
    assert import_support(unreadable) == "none"
    assert export_support(unreadable) == "none"


def test_format_ids_are_unique() -> None:
    ids = [fmt.format_id for fmt in EXCHANGE_FORMATS]
    duplicates = sorted({fid for fid in ids if ids.count(fid) > 1})
    assert not duplicates, f"duplicate format ids: {duplicates}"


def test_country_codes_are_iso_alpha_two_in_upper_case() -> None:
    for fmt in EXCHANGE_FORMATS:
        for code in fmt.countries:
            assert len(code) == 2 and code.isalpha() and code.isupper(), (
                f"{fmt.format_id} carries {code!r}, which is not an ISO 3166-1 alpha-2 code. "
                "The interface looks a flag up by this string and renders nothing when it misses."
            )
        assert len(set(fmt.countries)) == len(fmt.countries), f"{fmt.format_id} lists a country twice"


def test_extensions_are_lower_case_and_carry_their_dot() -> None:
    for fmt in EXCHANGE_FORMATS:
        assert fmt.extensions, f"{fmt.format_id} accepts no file at all"
        for ext in fmt.extensions:
            assert ext.startswith(".") and ext == ext.lower(), f"{fmt.format_id} carries a malformed extension {ext!r}"


def test_a_country_lands_on_its_own_document_never_on_the_generic_workbook() -> None:
    """The point of the country default: your market's paper, not ours."""
    generic = {"excel", "csv", "pdf"}
    covered = {code for fmt in EXCHANGE_FORMATS for code in fmt.countries}
    for code in sorted(covered):
        chosen = default_format_for_country(code)
        assert chosen is not None, f"{code} is listed in the catalogue but resolves to no default"
        assert chosen not in generic, (
            f"{code} defaults to {chosen!r}, which belongs to no market. "
            "A country the catalogue covers must land on one of its own rows."
        )
        picked = format_by_id(chosen)
        assert picked is not None and code in picked.countries


def test_a_country_default_is_a_row_we_can_actually_read_where_one_exists() -> None:
    for code in sorted({c for fmt in EXCHANGE_FORMATS for c in fmt.countries}):
        rows = formats_for_country(code)
        readable = [fmt for fmt in rows if import_support(fmt) == "native"]
        chosen = format_by_id(default_format_for_country(code) or "")
        assert chosen is not None
        if readable:
            assert import_support(chosen) == "native", (
                f"{code} defaults to {chosen.format_id!r}, which we cannot read, "
                f"while {readable[0].format_id!r} in the same market we can"
            )


def test_an_uncovered_country_gets_no_default_rather_than_a_borrowed_one() -> None:
    """Silence beats a plausible wrong answer.

    Returning, say, the German row for a country nobody has written a row
    for would put a GAEB export in front of a user whose market has never
    seen one, and they would have no way to tell that the choice was a
    guess. The caller falls back to the spreadsheet row, which is true for
    everybody, and says so.
    """
    assert default_format_for_country("ZZ") is None
    assert default_format_for_country("") is None
    assert formats_for_country("ZZ") == ()


def test_the_catalogue_covers_every_market_the_rule_resolver_knows() -> None:
    """Two country tables exist; neither may grow a market the other lacks.

    ``_build_rule_sets`` carries the country to rule-pack map. It is asked
    rather than read, and asked about every possible two-letter code, so
    the answer does not depend on knowing how it is written today. A
    market that resolves to a rule pack but has no row here is a market
    we have configured and cannot exchange a file with.
    """
    from app.core.classification_registry import normalise_region
    from app.modules.boq.router import _build_rule_sets

    baseline = _build_rule_sets([], "", "ZZ")
    known: set[str] = set()
    for first in ascii_uppercase:
        for second in ascii_uppercase:
            code = first + second
            if _build_rule_sets([], "", code) != baseline:
                # Probe by every code, record by the code the resolver
                # reduced it to. Aliases exist (a region name, a city
                # suffix), and counting an alias as a separate market
                # would demand a catalogue row for a spelling rather than
                # for a country.
                known.add((normalise_region(code) or code).upper())

    assert known, "the probe found no country rules at all, so it is measuring nothing"
    covered = {code for fmt in EXCHANGE_FORMATS for code in fmt.countries}
    missing = sorted(known - covered)
    assert not missing, f"these markets carry validation rules but have no exchange row: {missing}"


def test_a_declared_rule_pack_is_one_the_resolver_can_really_produce() -> None:
    """Catches the typo, which is the failure mode a rule pack name has.

    A misspelled pack name is invisible: the validation engine logs that
    it does not know the set and carries on, so nothing reddens and the
    import runs with fewer rules than the market needs.
    """
    from app.modules.boq.router import _build_rule_sets

    producible: set[str] = set()
    for first in ascii_uppercase:
        for second in ascii_uppercase:
            producible.update(_build_rule_sets([], "", first + second))
    for standard in ("din276", "nrm", "masterformat", "gaeb", "bc3", "onorm"):
        producible.update(_build_rule_sets([], standard, "ZZ"))

    for fmt in EXCHANGE_FORMATS:
        for pack in fmt.rule_packs:
            assert pack in producible, (
                f"{fmt.format_id} asks for rule pack {pack!r}, which nothing in the "
                f"rule resolver produces. Known packs: {sorted(producible)}"
            )


def test_the_described_catalogue_says_only_the_three_words_and_survives_json() -> None:
    described = describe_formats()
    assert len(described) == len(EXCHANGE_FORMATS)
    for row in described:
        assert row["import_support"] in {"native", "assisted", "none"}
        assert row["export_support"] in {"native", "assisted", "none"}
    json.dumps(described)


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("DE", "gaeb_xml"),
        ("de", "gaeb_xml"),
        ("  ch  ", "gaeb_xml"),
        ("ES", "bc3"),
        # Mexico deliberately does NOT land on BC3, though BC3 is listed for
        # it. See the Latin America test below for why.
        ("MX", "mx_catalogo_conceptos"),
    ],
)
def test_the_country_lookup_is_indifferent_to_case_and_stray_space(country: str, expected: str) -> None:
    assert default_format_for_country(country) == expected


def test_austria_is_offered_the_file_we_can_read_and_still_told_about_the_one_we_cannot() -> None:
    """The case the three support levels were invented for.

    Austria's own interchange is ÖNORM A 2063 and we do not read it. The
    honest response is to default them to GAEB, which we do read and which
    Austria genuinely uses, while leaving the ÖNORM row on the page saying
    plainly that it is not available. Dropping the row would leave an
    Austrian searching for their own format and finding nothing.
    """
    assert default_format_for_country("AT") == "gaeb_xml"
    oenorm = format_by_id("oenorm_a2063")
    assert oenorm is not None
    assert "AT" in oenorm.countries
    assert import_support(oenorm) == "assisted"  # XML, so the guided path can try
    assert export_support(oenorm) == "none"
    assert oenorm.format_id in {row["format_id"] for row in describe_formats()}


def test_the_catalogue_response_carries_the_languages_that_explain_a_guided_row() -> None:
    catalogue = build_catalogue("HU")
    assert catalogue.country == "HU"
    assert catalogue.default_format_id == "hu_koltsegvetes"
    assert catalogue.header_languages == sorted(catalogue.header_languages)
    assert "en" in catalogue.header_languages

    anonymous = build_catalogue()
    assert anonymous.country is None
    assert anonymous.default_format_id is None
    assert len(anonymous.formats) == len(EXCHANGE_FORMATS)


def test_a_market_is_claimed_as_its_own_by_at_most_one_row() -> None:
    """`primary_for` decides a default, so two claims would be a coin toss.

    Which one won would then depend on catalogue order, and that is exactly
    the accident the field was added to stop being load bearing.
    """
    claimed: dict[str, str] = {}
    for fmt in EXCHANGE_FORMATS:
        for code in fmt.primary_for:
            assert code in fmt.countries, f"{fmt.format_id} claims {code} as its own market but does not list it at all"
            assert code not in claimed, f"{code} is claimed by both {claimed[code]} and {fmt.format_id}"
            claimed[code] = fmt.format_id


def test_a_row_only_claims_a_market_whose_document_we_can_actually_read() -> None:
    for fmt in EXCHANGE_FORMATS:
        if fmt.primary_for:
            assert import_support(fmt) == "native", (
                f"{fmt.format_id} claims {list(fmt.primary_for)} as its own markets but we cannot read it, "
                "so the claim would push those markets onto a format that does not work for them"
            )


def test_a_claimed_market_lands_on_the_row_that_claimed_it() -> None:
    for fmt in EXCHANGE_FORMATS:
        for code in fmt.primary_for:
            assert default_format_for_country(code) == fmt.format_id


def test_latin_america_is_offered_its_own_paperwork_and_not_spains() -> None:
    """The case the field was added for, named so it cannot regress quietly.

    FIEBDC-3 files do reach Mexico and a Mexican user should be able to find
    the format on this page, so the row still lists the market. What changed
    is which document the page opens on: a Mexican unit-price contract is
    measured against a catálogo de conceptos, and opening on a Spanish
    database interchange would say we had misread their job.
    """
    bc3 = format_by_id("bc3")
    assert bc3 is not None
    assert "MX" in bc3.countries
    assert default_format_for_country("MX") == "mx_catalogo_conceptos"
    assert default_format_for_country("ES") == "bc3"
    for code in ("CL", "CO", "PE", "AR"):
        assert default_format_for_country(code) == "es_presupuesto"
