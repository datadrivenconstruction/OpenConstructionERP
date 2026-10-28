# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The outgoing-document catalogue is one more group of ``backend/locales/<code>.json``.

It used to be a second mechanism, a folder of JSON files beside
``app/core/document_catalogue.py``. It now lives in the locale files, under
``document_catalogue.<section>``, so a language is added, translated and shipped
in one place. What is held here:

* the old folder is gone and the loader reads the locale files;
* every locale file carries every section with the key shape English has, so the
  locale coverage gate measures it like any other string;
* English is a copy of the module's own table, and a module's own table still
  wins over the file for any language it carries;
* what each module reads for a language is what that language's file says.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from app.core import document_catalogue
from app.core.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from app.modules.bim_requirements.exporters import excel_exporter
from app.modules.cost_plan import export as cost_export
from app.modules.module_builder import suggest
from app.modules.notifications import email_render, localized
from app.modules.notifications.templates import all_template_keys, english_template
from app.modules.portal import login_email
from app.modules.schedule import tabular_headers as headers
from app.modules.tendering import addendum_email, invitation_email, xlsx_translations

SECTIONS = (
    "portal_login",
    "tender_invite",
    "notification_email",
    "tender_xlsx",
    "cost_plan",
    "bim_requirements_excel",
    "notification_templates",
    "schedule_headers",
    "module_suggest",
    "tender_addendum",
)

TABLES = {
    "portal_login": login_email._TABLES,
    "tender_invite": invitation_email._TABLES,
    "notification_email": email_render._TABLES,
    "tender_xlsx": xlsx_translations._STRINGS,
    "cost_plan": cost_export._LABELS,
    "bim_requirements_excel": excel_exporter._STRINGS,
    "tender_addendum": addendum_email._TABLES,
}

_BACKEND = Path(__file__).resolve().parents[2]


def _group(code: str) -> dict[str, Any]:
    data = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    return data["document_catalogue"]


def _shape(value: Any) -> Any:
    """The dict keys of a payload, recursively; lists and strings are leaves."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return None


def test_the_separate_catalogue_folder_is_gone() -> None:
    assert not (Path(document_catalogue.__file__).parent / "document_catalogues").exists()
    assert not hasattr(document_catalogue, "CATALOGUE_DIR")
    assert document_catalogue.GROUP == "document_catalogue"


def test_the_wheel_ships_the_locale_folder_the_catalogue_is_read_from() -> None:
    config = tomllib.loads((_BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include.get("locales") == "locales"
    assert "document_catalogues" not in (_BACKEND / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("code", SUPPORTED_LOCALES)
def test_every_locale_file_carries_every_section_in_the_english_shape(code: str) -> None:
    english = _group("en")
    own = _group(code)
    assert tuple(own) == SECTIONS
    for name in SECTIONS:
        if name == "notification_templates":
            assert set(own[name]) == set(english[name]), code
        else:
            assert _shape(own[name]) == _shape(english[name]), (code, name)


@pytest.mark.parametrize("name", list(TABLES))
@pytest.mark.parametrize("code", SUPPORTED_LOCALES)
def test_a_modules_table_holds_what_the_locale_file_says(name: str, code: str) -> None:
    """The in-file languages and the file agree, and a language only the file has is read from it."""
    assert TABLES[name][code] == _group(code)[name]


def test_english_notification_templates_are_the_modules_own() -> None:
    english = _group("en")["notification_templates"]
    assert set(english) == set(all_template_keys())
    assert all(english[key] == english_template(key) for key in english)


@pytest.mark.parametrize("code", [code for code in SUPPORTED_LOCALES if code != "en"])
def test_the_notification_catalogue_is_the_locale_file(code: str) -> None:
    assert localized._CATALOGUES[code] == _group(code)["notification_templates"]


@pytest.mark.parametrize("code", headers._BASE_LANGUAGES)
def test_the_schedule_files_copy_the_in_file_header_tables(code: str) -> None:
    own = _group(code)["schedule_headers"]
    assert own["headers"] == {field: list(headers.HEADER_SYNONYMS[field][code]) for field in headers.FIELDS}
    assert own["example_names"] == list(headers.TEMPLATE_EXAMPLE_NAMES[code])
    yes, no = headers.TEMPLATE_YES_NO[code]
    assert (own["yes_words"][0], own["no_words"][0]) == (yes, no)
    assert all(headers.flag_value(word) is True for word in own["yes_words"])
    assert all(headers.flag_value(word) is False for word in own["no_words"])


@pytest.mark.parametrize("code", [c for c in SUPPORTED_LOCALES if c not in headers._BASE_LANGUAGES])
def test_the_schedule_catalogue_languages_come_from_the_locale_file(code: str) -> None:
    assert headers._CATALOGUE[code] == _group(code)["schedule_headers"]
    assert headers.HEADER_SYNONYMS["id"][code] == tuple(_group(code)["schedule_headers"]["headers"]["id"])


@pytest.mark.parametrize("code", suggest._BASE_LANGUAGES)
def test_the_suggest_files_copy_the_in_file_tables(code: str) -> None:
    own = _group(code)["module_suggest"]
    assert own["link_labels"] == {target: labels[code] for target, labels in suggest.LINK_LABELS.items()}
    assert own["keywords"] == {concept: list(words[code]) for concept, words in suggest.KEYWORDS.items()}
    assert own["state_labels"] == list(suggest.STATE_LABELS[code])


@pytest.mark.parametrize("code", [c for c in SUPPORTED_LOCALES if c not in suggest._BASE_LANGUAGES])
def test_the_suggest_catalogue_languages_come_from_the_locale_file(code: str) -> None:
    assert suggest._CATALOGUE[code] == _group(code)["module_suggest"]
    assert suggest.STATE_LABELS[code] == tuple(_group(code)["module_suggest"]["state_labels"])


def test_section_leaves_english_out_and_the_modules_table_wins() -> None:
    portal = document_catalogue.section("portal_login")
    assert "en" not in portal and set(portal) == set(SUPPORTED_LOCALES) - {"en"}
    table: dict[str, Any] = {"de": {"own": "table"}}
    document_catalogue.merge_missing(table, "portal_login")
    assert table["de"] == {"own": "table"}
    assert table["ja"] == portal["ja"]
    assert document_catalogue.english_section("portal_login") == _group("en")["portal_login"]
    assert document_catalogue.section("no_such_section") == {}


def test_the_catalogue_group_is_not_loaded_from_a_language_the_platform_lacks() -> None:
    assert set(document_catalogue._load()) == set(SUPPORTED_LOCALES)
