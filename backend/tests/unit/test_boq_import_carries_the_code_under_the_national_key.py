# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An imported line's code reaches the key the project's national rules read.

The spreadsheet importer files a code column under ``code``, or under ``nrm``
or ``masterformat`` when the code has that shape. The national code rules
read their own key: ``cpwd`` for India, ``gesn`` for Russia, ``birimfiyat``
for Turkey and so on. An Indian bill whose every line carried its DSR item
number therefore failed ``cpwd.code_required`` on every line. The comment on
``_CLASSIFICATION_CODE_SETS`` said the import read that table to carry the
code across; nothing did.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_carries_the_code_under_the_national_key.py -v
"""

from __future__ import annotations

import pytest

from app.modules.boq.router import (
    _CLASSIFICATION_CODE_SETS,
    _IMPORT_CARRIED_CODE_SETS,
    _build_rule_sets,
    _carry_national_code,
    _national_code_key,
)


def _key_for(country: str, standard: str = "", rule_sets: list[str] | None = None) -> str | None:
    sets = _build_rule_sets(rule_sets or ["boq_quality"], standard, "", country)
    return _national_code_key(sets, standard)


@pytest.mark.parametrize(
    ("country", "standard", "key"),
    [
        ("IN", "", "cpwd"),
        ("IN", "cpwd", "cpwd"),
        ("RU", "", "gesn"),
        ("TR", "", "birimfiyat"),
        ("JP", "", "sekisan"),
        ("BR", "", "sinapi"),
        ("CN", "gb50500", "gb50500"),
        ("CN", "", "gb50500"),
        ("PL", "", "knr"),
        ("HU", "", "tetelrend"),
        ("ES", "", "bc3_code"),
    ],
)
def test_a_market_with_its_own_code_gets_its_key(country: str, standard: str, key: str) -> None:
    assert _key_for(country, standard) == key


@pytest.mark.parametrize(
    ("country", "standard"),
    [
        # DIN 276, NRM and MasterFormat are never filled from the code column:
        # the importer reads NRM and MasterFormat codes by their shape, and a
        # Romanian, Greek or Croatian bill's code column is the national code,
        # not a DIN 276 cost group.
        ("DE", "din276"),
        ("RO", ""),
        ("GR", ""),
        ("HR", ""),
        ("GB", "nrm"),
        ("US", "masterformat"),
        ("AE", ""),
        # Mexico's rule set reads no classification code.
        ("MX", ""),
        # No country, no standard.
        ("", ""),
    ],
)
def test_a_market_without_its_own_code_gets_no_key(country: str, standard: str) -> None:
    assert _key_for(country, standard) is None


def test_the_project_standard_breaks_a_tie_between_two_code_sets() -> None:
    both = ["boq_quality", "gesn", "cpwd"]

    assert _national_code_key(both, "") is None
    assert _national_code_key(both, "cpwd") == "cpwd"
    assert _national_code_key(both, "gesn") == "gesn"


def test_every_carried_code_set_names_a_key() -> None:
    assert set(_CLASSIFICATION_CODE_SETS) >= _IMPORT_CARRIED_CODE_SETS
    assert not {"din276", "nrm", "masterformat"} & _IMPORT_CARRIED_CODE_SETS


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        ({"code": "2.8.1.2"}, {"code": "2.8.1.2", "cpwd": "2.8.1.2"}),
        # A DSR item number looks like an NRM element to the importer.
        ({"nrm": "2.8.1"}, {"nrm": "2.8.1", "cpwd": "2.8.1"}),
        ({"masterformat": "03 30 00"}, {"masterformat": "03 30 00", "cpwd": "03 30 00"}),
        # A key the line already carries is never overwritten.
        ({"code": "X", "cpwd": "13.1.1"}, {"code": "X", "cpwd": "13.1.1"}),
        ({"code": "  "}, {"code": "  "}),
        ({}, {}),
    ],
)
def test_the_code_is_carried_under_the_key(classification: dict, expected: dict) -> None:
    before = dict(classification)

    assert _carry_national_code(classification, "cpwd", is_section=False) == expected
    assert classification == before


def test_a_blank_national_key_is_filled() -> None:
    assert _carry_national_code({"code": "2.8.1", "cpwd": ""}, "cpwd", is_section=False) == {
        "code": "2.8.1",
        "cpwd": "2.8.1",
    }


def test_sections_and_projects_without_a_key_are_left_alone() -> None:
    assert _carry_national_code({"code": "2"}, "cpwd", is_section=True) == {"code": "2"}
    assert _carry_national_code({"code": "2.8.1"}, None, is_section=False) == {"code": "2.8.1"}
    assert _carry_national_code(None, "cpwd", is_section=False) is None


# ── Only a code of the key's kind is carried ────────────────────────────────
#
# A code column holds whatever the estimator wrote there. A Russian smeta's
# "Обоснование" cites a GESN norm on one line, a regional price base item on
# the next and a supplier's price list on the third; a Brazilian orçamento
# mixes SINAPI, SICRO and own compositions in one "Código" column. Copying all
# of it under the national key filed a price list as a norm, and the format
# rule then warned on every line.


@pytest.mark.parametrize(
    ("key", "cell", "carried"),
    [
        # GESN: the printed prefix is dropped, the bare number is what the
        # rule and the platform's own Russian bill hold.
        ("gesn", "06-01-001-01", "06-01-001-01"),
        ("gesn", "ГЭСН06-01-001-01", "06-01-001-01"),
        ("gesn", "ГЭСН 06-01-001-01", "06-01-001-01"),
        ("gesn", "ФЕР06-01-001-01", "06-01-001-01"),
        ("gesn", "ТЕР-06-01-001-01", "06-01-001-01"),
        ("gesn", "гэсн06-01-001-01", "06-01-001-01"),
        # The montage collection reuses the construction numbers: stripping
        # its prefix would cite the wrong norm.
        ("gesn", "ГЭСНм08-03-594-01", None),
        ("gesn", "ФЕРм08-03-594-01", None),
        ("gesn", "ФССЦ-04.1.02.05-0006", None),
        ("gesn", "Прайс-лист", None),
        # Turkey: the current ministry book and the older Bayındırlık one.
        ("birimfiyat", "15.150.1005", "15.150.1005"),
        ("birimfiyat", "16.050/3", "16.050/3"),
        ("birimfiyat", "Y.16.050/01", "Y.16.050/01"),
        ("birimfiyat", "Özel Analiz-1", None),
        # Brazil, with no bank column.
        ("sinapi", "92873", "92873"),
        ("sinapi", "74209/001", "74209/001"),
        ("sinapi", "COMP-01", None),
        # China: a bill item code, not a quota number.
        ("gb50500", "010101001001", "010101001001"),
        ("gb50500", "010101001", "010101001"),
        ("gb50500", "A1-1", None),
        ("gb50500", "1-1", None),
        # Hungary: the building and the infrastructure item orders.
        ("tetelrend", "MA-01-11-01", "MA-01-11-01"),
        ("tetelrend", "211 1011", "211 1011"),
        ("tetelrend", "Egyedi tétel", None),
        # Poland: a catalogue table or the line's own calculation.
        ("knr", "KNR 2-02 0101-01", "KNR 2-02 0101-01"),
        ("knr", "kalkulacja własna", "kalkulacja własna"),
        ("knr", "Cennik dostawcy", None),
        # Spain: a FIEBDC-3 concept code.
        ("bc3_code", "E04CM040", "E04CM040"),
        ("bc3_code", "E04 CM040", None),
        # India and Japan have no format rule, so the code is taken as it is.
        ("cpwd", "SOR-12.3", "SOR-12.3"),
        ("sekisan", "土工-1", "土工-1"),
    ],
)
def test_only_a_code_of_the_keys_kind_is_carried(key: str, cell: str, carried: str | None) -> None:
    result = _carry_national_code({"code": cell}, key, is_section=False)

    assert result.get(key) == carried
    assert result["code"] == cell


@pytest.mark.parametrize(
    ("bank", "carried"),
    [
        ("SINAPI", True),
        ("sinapi", True),
        ("SINAPI-I", True),
        ("", True),
        # Another bank's code is that bank's, even when it looks like SINAPI's.
        ("ORSE", False),
        ("SICRO3", False),
        ("PRÓPRIO", False),
    ],
)
def test_a_sinapi_code_is_carried_only_from_a_sinapi_line(bank: str, carried: bool) -> None:
    classification = {"code": "92873", **({"banco": bank} if bank else {})}

    result = _carry_national_code(classification, "sinapi", is_section=False)

    assert ("sinapi" in result) is carried


@pytest.mark.parametrize(
    ("poz", "valid"),
    [
        ("15.150.1005", True),
        ("16.050", True),
        ("16.050/3", True),
        ("Y.16.050/01", True),
        ("15.150.100", False),
        ("NOT-A-POZ", False),
        ("1.150.1005", False),
    ],
)
def test_the_poz_rule_reads_the_current_ministry_book(poz: str, valid: bool) -> None:
    from app.core.validation.rules import BirimFiyatValidPoz

    assert bool(BirimFiyatValidPoz._PATTERN.match(poz)) is valid
