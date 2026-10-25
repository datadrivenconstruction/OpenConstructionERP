# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every register and record form can be printed in every language the platform runs in.

The submittal, change order, claims evidence, correspondence, transmittal,
variation, RFI log and daily diary documents used to carry English and Turkish
tables in Python (the diary German as well), so the export menu offered two
languages and every other reader got English. Their strings now live in
``backend/locales/<code>.json`` under ``document_forms.<form>`` and the
catalogue is built from those files, like the purchase order and invoice.

What is pinned here:

* every language in ``SUPPORTED_LOCALES`` except Bengali (no bundled face draws
  its script) is in every form's catalogue, and each of them holds a value of
  its own for every key the English file has: no key is satisfied by the English
  fallback, which is how a language silently half-works;
* a translation keeps the placeholders of the English text;
* a translation is not the English text under another code;
* filename stems stay plain ASCII, so a download name is the same on every
  operating system;
* a language outside the catalogue, or a value that is no language at all,
  renders in English and is never refused;
* the languages the web client offers are the ones the server can render.
"""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from app.core.document_forms_i18n import (
    REGISTER_UNRENDERABLE,
    document_form_catalogue,
    document_form_locales,
    load_document_forms,
    register_form_catalogue,
)
from app.core.i18n import SUPPORTED_LOCALES
from app.core.register_export import FORM_FURNITURE, FURNITURE

#: Printed forms built from the locale files in this change.
REGISTER_FORMS: tuple[str, ...] = (
    "submittals",
    "changeorders",
    "claims_evidence",
    "correspondence",
    "transmittals",
    "variations",
    "rfi_register",
    "daily_diary",
)

#: Bengali has no face in the PDF font ladder (see ``app.core.pdf_fonts``) and
#: Urdu cannot be drawn correctly one face per string: both are answered in English.
UNRENDERABLE = REGISTER_UNRENDERABLE

DOCUMENT_LOCALES: tuple[str, ...] = tuple(code for code in SUPPORTED_LOCALES if code not in UNRENDERABLE)

#: Keys whose value is a number format or a short identifier, not prose.
NOT_PROSE = {"decimal_mark", "percent", "filename_prefix", "running_title"}

_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src" / "shared" / "lib" / "documentExport.ts"


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


def _tables(form: str, code: str) -> dict[str, dict[str, str]]:
    """The strings and every label table of one form in one language, exactly as the file holds them."""
    block = load_document_forms(code).get(form) or {}
    tables = {"strings": dict(block.get("strings") or {})}
    for name, table in (block.get("labels") or {}).items():
        tables[f"labels.{name}"] = dict(table)
    return tables


def _english(form: str) -> dict[str, dict[str, str]]:
    return _tables(form, "en")


def test_the_unrenderable_set_is_the_only_gap() -> None:
    assert set(SUPPORTED_LOCALES) - set(DOCUMENT_LOCALES) == set(UNRENDERABLE)
    assert len(DOCUMENT_LOCALES) == len(SUPPORTED_LOCALES) - len(UNRENDERABLE)


@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_every_renderable_language_is_in_the_catalogue(form: str) -> None:
    catalogue = register_form_catalogue(form)
    assert set(catalogue.supported) == set(DOCUMENT_LOCALES)
    assert catalogue.supported[0] == "en"
    assert "ur" in catalogue.supported  # set in runs of faces; see pdf_font_runs
    assert "bn" in UNRENDERABLE  # no bundled face carries Bengali; see REGISTER_UNRENDERABLE
    for code, reason in UNRENDERABLE.items():
        assert code not in catalogue.supported, reason
        assert catalogue.normalize(code) == "en"


@pytest.mark.parametrize("code", DOCUMENT_LOCALES)
@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_a_language_holds_its_own_value_for_every_english_key(form: str, code: str) -> None:
    """The file is complete, so nothing in the document reaches the English fallback."""
    english = _english(form)
    own = _tables(form, code)
    for table, expected in english.items():
        assert table in own, f"{code}.{form}.{table} is missing"
        missing = sorted(set(expected) - set(own[table]))
        assert not missing, f"{code}.{form}.{table} lacks {missing}"
        for key, value in own[table].items():
            assert isinstance(value, str) and value.strip(), f"{code}.{form}.{table}.{key} is empty"
        extra = sorted(set(own[table]) - set(expected))
        assert not extra, f"{code}.{form}.{table} has keys English does not: {extra}"


@pytest.mark.parametrize("code", DOCUMENT_LOCALES)
@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_a_translation_keeps_the_placeholders_of_the_english_text(form: str, code: str) -> None:
    english = _english(form)
    own = _tables(form, code)
    for table, expected in english.items():
        for key, text in expected.items():
            assert _placeholders(own[table][key]) == _placeholders(text), f"{code}.{form}.{table}.{key}"


@pytest.mark.parametrize("code", [c for c in DOCUMENT_LOCALES if c != "en"])
@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_a_translation_is_not_the_english_text_under_another_code(form: str, code: str) -> None:
    english = _english(form)
    own = _tables(form, code)
    total = same = 0
    for table, expected in english.items():
        for key, text in expected.items():
            if key in NOT_PROSE or (table == "labels.status" and form == "rfi_register"):
                continue
            total += 1
            same += own[table][key] == text
    # Codes, abbreviations, "No." and shared loan words legitimately match.
    assert same <= max(3, total // 4), f"{code}.{form}: {same} of {total} values are the English text"


@pytest.mark.parametrize("code", [c for c in DOCUMENT_LOCALES if c != "en"])  # English keeps its historic names
def test_filename_stems_are_plain_ascii_slugs(code: str) -> None:
    for form in REGISTER_FORMS:
        for key, value in _tables(form, code)["strings"].items():
            if key.endswith("filename") or key == "filename_prefix":
                assert _SLUG.match(value), f"{code}.{form}.{key} = {value!r}"


@pytest.mark.parametrize("code", DOCUMENT_LOCALES)
def test_page_furniture_exists_for_the_language(code: str) -> None:
    """Footer, signature captions and "Total" come from the shared tables or the locale file."""
    if code in FURNITURE or code in FORM_FURNITURE:
        return
    own = load_document_forms(code).get("furniture") or {}
    english = load_document_forms("en")["furniture"]
    assert set(english) <= set(own), f"{code}: furniture lacks {sorted(set(english) - set(own))}"
    for key, value in own.items():
        assert _placeholders(value) == _placeholders(english[key]), f"{code}.furniture.{key}"


@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_the_catalogue_prints_each_language_not_english(form: str) -> None:
    """Resolved through the catalogue, as the renderers do: no key falls back for any language."""
    catalogue = register_form_catalogue(form)
    english = catalogue.strings["en"]
    key = next(k for k in english if k.startswith(("register_title", "variation_register_title", "doc_title")))
    seen: dict[str, str] = {}
    for code in DOCUMENT_LOCALES:
        assert catalogue.normalize(code) == code
        seen[code] = catalogue.tr(code, key)
    assert all(seen.values())
    assert len(set(seen.values())) > len(DOCUMENT_LOCALES) * 0.8, "titles collapse onto too few wordings"


@pytest.mark.parametrize("form", REGISTER_FORMS)
@pytest.mark.parametrize("value", ["zz", "xx-YY", "bn", "BN-bd", "", None, "not a language", "klingon"])
def test_a_language_the_documents_lack_renders_in_english(form: str, value: str | None) -> None:
    catalogue = register_form_catalogue(form)
    assert catalogue.normalize(value) == "en"
    assert catalogue.resolve(value, None) == "en"
    assert catalogue.resolve(value, "zz-ZZ") == "en"
    english_key = next(iter(_english(form)["strings"]))
    assert catalogue.tr(value, english_key) == catalogue.tr("en", english_key)


@pytest.mark.parametrize("form", REGISTER_FORMS)
def test_a_regional_tag_reads_its_base_language(form: str) -> None:
    catalogue = register_form_catalogue(form)
    assert catalogue.normalize("pt-BR") == "pt"
    assert catalogue.normalize("ZH-hans-CN") == "zh"
    assert catalogue.resolve(None, "ar-EG,ar;q=0.9,en;q=0.5") == "ar"
    assert catalogue.resolve("zz", "ko-KR,en;q=0.5") == "ko"


def test_turkish_keeps_the_wording_it_had() -> None:
    """The Turkish moved from Python tables into tr.json unchanged."""
    from app.modules.changeorders.pdf_translations import tr as change_tr
    from app.modules.submittals.pdf_translations import doc_title, register_title

    assert doc_title("tr", "product_data") == "Malzeme Onay Formu"
    assert register_title("tr").endswith("Kayıt Listesi")
    assert change_tr("tr", "item_cost_delta") == "Maliyet farkı"
    assert change_tr("tr", "register_filename") == "degisiklik-emirleri-kayit-listesi"


def test_the_submittal_discipline_words_are_translated_for_every_language() -> None:
    from app.modules.submittals.tracking import DISCIPLINES

    catalogue = register_form_catalogue("submittals")
    for code in DOCUMENT_LOCALES:
        for item in DISCIPLINES:
            assert catalogue.label("discipline", item.code, code), (code, item.code)
    assert catalogue.label("discipline", "hvac", "tr") == "İklimlendirme"
    assert catalogue.label("discipline", "custom_trade", "de") == "custom_trade"


def test_the_server_lists_the_languages_of_every_form() -> None:
    listed = document_form_locales()
    for form in REGISTER_FORMS:
        assert listed[form] == register_form_catalogue(form).supported
    assert set(listed["procurement"]) <= set(SUPPORTED_LOCALES)
    from app.core.i18n_router import router

    assert any(getattr(route, "path", "") == "/i18n/document-locales" for route in router.routes)


def _ts_list(name: str) -> tuple[str, ...]:
    source = _FRONTEND.read_text(encoding="utf-8")
    match = re.search(rf"export const {name}: readonly string\[\] =\s*\[(.*?)\];", source, re.S)
    assert match, f"{name} is not a literal list in documentExport.ts"
    return tuple(re.findall(r"'([a-z]{2,3})'", match.group(1)))


def test_the_web_client_offers_exactly_the_languages_the_server_renders() -> None:
    """``documentExport.ts`` lists the languages per family; this keeps the lists equal to the catalogues."""
    register = _ts_list("REGISTER_DOCUMENT_LOCALES")
    assert len(register) == len(set(register))
    for form in (f for f in REGISTER_FORMS if f != "daily_diary"):
        assert set(register) == set(register_form_catalogue(form).supported), form
    source = _FRONTEND.read_text(encoding="utf-8")
    # The diary prints in the same languages as the registers; the client reuses the list.
    assert "DIARY_DOCUMENT_LOCALES: readonly string[] = REGISTER_DOCUMENT_LOCALES" in source
    assert set(register) == set(register_form_catalogue("daily_diary").supported)
    purchasing = _ts_list("PURCHASING_DOCUMENT_LOCALES")
    assert set(purchasing) == set(document_form_catalogue("procurement").supported)
    assert set(purchasing) == set(document_form_catalogue("finance").supported)


def _walk(value: object, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, str) and not path.endswith("_format"):
        yield path, value


@pytest.mark.parametrize("code", DOCUMENT_LOCALES)
def test_the_face_the_printer_picks_can_draw_every_string(code: str) -> None:
    """Every character of every string has a face that draws it, run by run where one face is not enough."""
    from app.core.pdf_fonts import font_can_draw_all, pdf_font_runs, register_pdf_fonts

    assert register_pdf_fonts() is True
    blocks = load_document_forms(code)
    bad = []
    for path, text in _walk({k: v for k, v in blocks.items() if k in (*REGISTER_FORMS, "furniture")}):
        for bold in (False, True):
            for face, chunk in pdf_font_runs(text, bold=bold):
                if not font_can_draw_all(face, chunk.replace(chr(10), "")):
                    bad.append((path, face, chunk))
    assert not bad, bad[:5]
