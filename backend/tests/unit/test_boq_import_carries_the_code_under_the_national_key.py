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
