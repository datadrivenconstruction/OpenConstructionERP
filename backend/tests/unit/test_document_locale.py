# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The resolution every document renderer shares.

This used to be three functions copied byte-for-byte into two PDF modules,
so a fix to either reached one document and not the other. The tests below
pin the rule once.

Unsupported languages are always spelled ``zz`` here, never a real language
code. A test that writes the unsupported case as ``fr`` stops describing the
mechanism the moment a catalogue gains French, and until then it reads like
a decision that French readers should get English.
"""

import pytest

from app.core.document_locale import (
    normalize_document_locale,
    resolve_document_locale,
    translate,
)

# A stand-in for a real PDF catalogue: far narrower than the interface.
CATALOGUE: tuple[str, ...] = ("en", "de")
DEFAULT = "en"
TABLES: dict[str, dict[str, str]] = {
    "en": {"total": "Total", "greeting": "Hello {name}"},
    "de": {"total": "Gesamt"},
}


class TestNormalizeDocumentLocale:
    def test_an_exact_code_is_kept(self) -> None:
        assert normalize_document_locale("de", CATALOGUE, DEFAULT) == "de"

    def test_a_region_is_stripped_and_case_is_folded(self) -> None:
        assert normalize_document_locale("DE-AT", CATALOGUE, DEFAULT) == "de"

    def test_a_code_the_catalogue_lacks_becomes_the_default(self) -> None:
        assert normalize_document_locale("zz", CATALOGUE, DEFAULT) == "en"

    def test_empty_and_none_become_the_default(self) -> None:
        assert normalize_document_locale(None, CATALOGUE, DEFAULT) == "en"
        assert normalize_document_locale("", CATALOGUE, DEFAULT) == "en"


class TestResolveDocumentLocale:
    def test_the_query_parameter_wins_over_the_header(self) -> None:
        assert resolve_document_locale("de", "en-US,en;q=0.9", CATALOGUE, DEFAULT) == "de"

    def test_an_unsupported_query_parameter_falls_through_to_the_header(self) -> None:
        assert resolve_document_locale("zz", "de-DE", CATALOGUE, DEFAULT) == "de"

    def test_the_first_supported_header_tag_wins_in_header_order(self) -> None:
        assert resolve_document_locale(None, "zz-ZZ,de;q=0.5", CATALOGUE, DEFAULT) == "de"

    def test_a_header_of_only_unsupported_tags_degrades_to_the_default(self) -> None:
        assert resolve_document_locale(None, "zz-ZZ,zz;q=0.9", CATALOGUE, DEFAULT) == "en"

    def test_absent_and_wildcard_inputs_degrade_to_the_default(self) -> None:
        assert resolve_document_locale(None, None, CATALOGUE, DEFAULT) == "en"
        assert resolve_document_locale(None, "", CATALOGUE, DEFAULT) == "en"
        assert resolve_document_locale(None, "*", CATALOGUE, DEFAULT) == "en"


class TestRegionalVariantsAreNotRepresentable:
    """The documented limit, asserted so it cannot be forgotten.

    Documents match on the primary subtag only. Adding a ``fr`` catalogue
    therefore serves European and Canadian French the same text, and no
    quantity of translation changes that - it needs a wider key in the
    catalogue and a resolver that stops truncating. Anyone promising a
    region-specific document has to change this function first.
    """

    @pytest.mark.parametrize(
        ("tag", "sibling"),
        [("fr-CA", "fr-FR"), ("pt-BR", "pt-PT"), ("es-MX", "es-CL")],
    )
    def test_two_regions_of_one_language_collapse_to_the_same_answer(self, tag: str, sibling: str) -> None:
        wide = (*CATALOGUE, tag.split("-")[0])
        assert resolve_document_locale(tag, None, wide, DEFAULT) == resolve_document_locale(
            sibling, None, wide, DEFAULT
        )


class TestTranslate:
    def test_a_present_key_reads_from_the_requested_language(self) -> None:
        assert translate(TABLES, "de", "total", DEFAULT) == "Gesamt"

    def test_a_key_missing_from_the_language_falls_back_to_the_default(self) -> None:
        assert translate(TABLES, "de", "greeting", DEFAULT, name="Anna") == "Hello Anna"

    def test_an_unknown_language_reads_the_default_table(self) -> None:
        assert translate(TABLES, "zz", "total", DEFAULT) == "Total"

    def test_a_key_missing_everywhere_returns_the_key_rather_than_raising(self) -> None:
        assert translate(TABLES, "de", "nonexistent", DEFAULT) == "nonexistent"

    def test_bad_interpolation_returns_the_template_rather_than_raising(self) -> None:
        """A document render must not crash on a malformed catalogue entry."""
        assert translate(TABLES, "en", "greeting", DEFAULT, wrong_kwarg="x") == "Hello {name}"
