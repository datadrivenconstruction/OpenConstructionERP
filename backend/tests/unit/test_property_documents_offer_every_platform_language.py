# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The property-development documents are offered in every platform language.

The picker used to list the 27 languages somebody chose when the module was
written, so a reader in Hebrew, Ukrainian or Greek could not pick their own.
The offered set is now the platform's language list, less the language the PDF
layer cannot draw. The wording stays in ``data/document_locales/<code>.json``
(a tenant can replace a file from the settings page, which is why these are not
folded into ``backend/locales``); a language without a file prints English key by
key, and keeps a left-to-right layout so English prose is never set right to left.

Pure: no database, no event bus.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.document_forms_i18n import REGISTER_UNRENDERABLE
from app.core.i18n import SUPPORTED_LOCALES as PLATFORM_LOCALES
from app.modules.property_dev import document_templates as dt

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src" / "shared" / "lib" / "documentExport.ts"


def test_every_platform_language_the_pdf_layer_can_draw_is_offered() -> None:
    expected = {code for code in PLATFORM_LOCALES if code not in REGISTER_UNRENDERABLE}
    assert set(dt.SUPPORTED_LOCALES) == expected | {"mn"}
    assert len(dt.SUPPORTED_LOCALES) == len(set(dt.SUPPORTED_LOCALES))


def test_the_web_client_offers_exactly_these_languages() -> None:
    source = _FRONTEND.read_text(encoding="utf-8")
    assert re.search(
        r"PROPERTY_DOCUMENT_LOCALES: readonly string\[\] = \[\.\.\.REGISTER_DOCUMENT_LOCALES, 'mn'\];", source
    )
    match = re.search(r"REGISTER_DOCUMENT_LOCALES: readonly string\[\] =\s*\[(.*?)\];", source, re.S)
    assert match
    register = re.findall(r"'([a-z]{2,3})'", match.group(1))
    assert {*register, "mn"} == set(dt.SUPPORTED_LOCALES)


def test_every_offered_language_has_a_name_and_a_status_row() -> None:
    rows = {row["code"]: row for row in dt.list_locale_status()}
    assert set(rows) == set(dt.SUPPORTED_LOCALES)
    for code, row in rows.items():
        assert code in dt.LOCALE_DISPLAY_NAMES, code
        assert row["native_name"].strip() and row["english_name"].strip(), code
    assert rows["he"]["rtl"] is True
    assert rows["en"]["source"] == "bundled"


@pytest.mark.parametrize("code", [c for c in dt.SUPPORTED_LOCALES if not (dt._LOCALE_DIR / f"{c}.json").exists()])
def test_a_language_without_a_file_prints_english_left_to_right(code: str) -> None:
    assert dt._t(code, "reservation_receipt.title") == dt._t("en", "reservation_receipt.title")
    assert dt._styles(code)["body"].alignment == dt._styles("en")["body"].alignment


def test_a_translated_right_to_left_language_is_set_right_to_left() -> None:
    for code in sorted(dt.RTL_LOCALES):
        assert (dt._LOCALE_DIR / f"{code}.json").exists(), code
        assert dt._styles(code)["body"].wordWrap == "RTL", code
    assert dt._styles("en")["body"].wordWrap is None


def test_the_web_client_offers_messages_and_workbooks_in_every_backend_language() -> None:
    from app.modules.schedule.tabular_headers import LANGUAGES

    source = _FRONTEND.read_text(encoding="utf-8")
    assert "MESSAGE_DOCUMENT_LOCALES: readonly string[] = [...REGISTER_DOCUMENT_LOCALES, 'bn'];" in source
    match = re.search(r"REGISTER_DOCUMENT_LOCALES: readonly string\[\] =\s*\[(.*?)\];", source, re.S)
    assert match
    offered = {*re.findall(r"'([a-z]{2,3})'", match.group(1)), "bn"}
    assert offered == set(PLATFORM_LOCALES) == set(LANGUAGES)
