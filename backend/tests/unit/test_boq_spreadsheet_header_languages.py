# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The spreadsheet header table, and what a market may claim from it.

The BOQ Excel importer maps a header row onto canonical columns through a
table that used to be seven languages flattened into one set of strings. It
is now tagged by language and the flat map is derived from it, which buys two
things a flat set could not give:

* ``SUPPORTED_HEADER_LANGUAGES`` is computed, so a national profile deciding
  whether to advertise native spreadsheet import reads what the table holds
  rather than a hand-kept second list that drifts from it.
* a language is either complete or it is not. A market whose entry names a
  description column but no rate column imports every line at zero, which
  looks like a successful import and is not one, so the four columns a bill
  row cannot be read without are enforced here rather than discovered by a
  user.

The restructure had to preserve behaviour exactly, so the first tests pin the
membership the flat table had before the split and allow only the two
additions that are named below. The rest guard the properties that a table
this wide breaks silently: one string reaching two different columns, or a
header colliding with the round-trip identity column, either of which sends a
quantity into the money column with nothing going red.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_spreadsheet_header_languages.py -v
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ, ImporterParseError
from app.modules.boq.importers.excel import (
    _COLUMN_ALIASES,
    _HEADERS_BY_LANGUAGE,
    _MANDATORY_COLUMNS,
    SUPPORTED_HEADER_LANGUAGES,
    ExcelImporter,
    _build_column_aliases,
    _languages_missing_mandatory_columns,
    _match_column,
)
from app.modules.boq.roundtrip import ID_COLUMN_ALIASES

# ── The pin ─────────────────────────────────────────────────────────────────

# Exactly what ``_COLUMN_ALIASES`` held before the table was split by
# language, copied out of the committed file rather than retyped. Every one
# of these strings has to keep reaching the same canonical column, otherwise
# a spreadsheet that imported yesterday stops importing today.
_HEADERS_BEFORE_THE_SPLIT: dict[str, frozenset[str]] = {
    "ordinal": frozenset(
        {
            "item",
            "item no",
            "no",
            "no.",
            "nr",
            "nr.",
            "ord",
            "ordinal",
            "pos",
            "pos.",
            "position",
            "ref",
        }
    ),
    "description": frozenset(
        {
            "beschreibung",
            "desc",
            "descripcion",
            "descripción",
            "description",
            "descrizione",
            "designacion",
            "designación",
            "designation",
            "désignation",
            "leistung",
            "opis",
            "text",
            "наименование",
        }
    ),
    "unit": frozenset(
        {
            "einheit",
            "jed",
            "me",
            "u",
            "ud",
            "uds",
            "unidad",
            "unit",
            "unità",
            "unité",
            "ед",
            "ед.",
        }
    ),
    "quantity": frozenset(
        {
            "cant",
            "cant.",
            "cantidad",
            "ilosc",
            "ilość",
            "menge",
            "qty",
            "quantita",
            "quantity",
            "quantità",
            "quantité",
            "кол-во",
            "количество",
        }
    ),
    "unit_rate": frozenset(
        {
            "einheitspreis",
            "ep",
            "precio",
            "preis",
            "prezzo",
            "prix",
            "rate",
            "unit rate",
            "unitrate",
            "цена",
        }
    ),
    "total": frozenset(
        {
            "amount",
            "gesamt",
            "gesamtpreis",
            "importe",
            "subtotal",
            "total",
            "стоимость",
        }
    ),
    "classification": frozenset(
        {
            "category",
            "classification",
            "code",
            "csi",
            "din 276",
            "din276",
            "division",
            "element",
            "kg",
            "masterformat",
            "nrm",
            "trade",
        }
    ),
}

# The languages the flat table was made of.
_LANGUAGES_BEFORE_THE_SPLIT = frozenset({"en", "de", "es", "fr", "it", "pl", "ru"})

# The only strings the original seven were allowed to gain in the move.
# Polish named a description, a unit and a quantity column but no rate one,
# so a Polish bill imported with every rate at zero; the completeness rule
# below is what forced the gap shut.
_DELIBERATE_ADDITIONS_TO_THE_ORIGINAL_SEVEN: dict[str, frozenset[str]] = {
    "unit_rate": frozenset({"cena jednostkowa", "cena jedn.", "cena"}),
}


# ── Behaviour preservation ──────────────────────────────────────────────────


def test_every_header_read_before_the_split_still_reaches_the_same_column() -> None:
    for canonical, headers in _HEADERS_BEFORE_THE_SPLIT.items():
        missing = headers - _COLUMN_ALIASES[canonical]
        assert not missing, f"{canonical} lost {sorted(missing)} in the move"


def test_every_header_read_before_the_split_still_matches_through_the_matcher() -> None:
    # The table being right is not the same as the matcher answering right:
    # ``_match_column`` walks the map in order, so this reads the answer the
    # importer actually gets.
    for canonical, headers in _HEADERS_BEFORE_THE_SPLIT.items():
        for header in headers:
            assert _match_column(header) == canonical
            assert _match_column(f"  {header.upper()}  ") == canonical


def test_the_original_seven_languages_gained_only_the_polish_rate_headers() -> None:
    # A subset check alone would not notice a string quietly added to, say,
    # German. Rebuild the union of just the seven the table started with and
    # account for every difference.
    original = _build_column_aliases(
        {
            language: headers
            for language, headers in _HEADERS_BY_LANGUAGE.items()
            if language in _LANGUAGES_BEFORE_THE_SPLIT
        }
    )
    for canonical, headers in _HEADERS_BEFORE_THE_SPLIT.items():
        allowed = _DELIBERATE_ADDITIONS_TO_THE_ORIGINAL_SEVEN.get(canonical, frozenset())
        assert original[canonical] - headers == allowed
        assert headers - original[canonical] == frozenset()


def test_the_identity_column_is_still_the_first_column_the_matcher_tries() -> None:
    # An exported "Position ID" header has to reach ``position_id``, never
    # ``ordinal`` (GitHub #360).
    assert next(iter(_COLUMN_ALIASES)) == "position_id"
    assert _COLUMN_ALIASES["position_id"] is ID_COLUMN_ALIASES
    assert _match_column("Position ID") == "position_id"


# ── Collisions ──────────────────────────────────────────────────────────────


def _owner_of_every_header() -> dict[str, list[str]]:
    """Map every declared header string to the canonical columns claiming it."""
    owners: dict[str, list[str]] = {}
    for canonical, headers in _COLUMN_ALIASES.items():
        for header in headers:
            owners.setdefault(header, []).append(canonical)
    return owners


def test_no_header_string_maps_to_two_different_canonical_columns() -> None:
    # Ambiguity here is invisible: whichever column the dict happens to reach
    # first wins, so a quantity lands in the money column and the bill still
    # imports. Fix a collision by dropping the ambiguous token, never by
    # reordering the table.
    ambiguous = {header: sorted(owners) for header, owners in _owner_of_every_header().items() if len(owners) > 1}
    assert ambiguous == {}


def test_no_language_header_collides_with_the_round_trip_identity_column() -> None:
    for language, headers in _HEADERS_BY_LANGUAGE.items():
        for canonical, words in headers.items():
            clash = set(words) & set(ID_COLUMN_ALIASES)
            assert not clash, f"{language}.{canonical} collides with the id column on {sorted(clash)}"


def test_indonesian_does_not_accept_the_word_that_heads_both_of_its_money_columns() -> None:
    # Indonesian bills head the quantity column and the money column with
    # "jumlah" alike, so accepting it makes one read as the other. The
    # spellings that say which is meant are kept instead.
    indonesian = _HEADERS_BY_LANGUAGE["id"]
    assert "jumlah" not in indonesian["quantity"]
    assert "jumlah" not in indonesian["total"]
    assert "volume" in indonesian["quantity"]
    assert "jumlah harga" in indonesian["total"]
    assert _match_column("Jumlah") is None


def test_every_declared_header_resolves_to_the_column_it_was_declared_under() -> None:
    for language, headers in _HEADERS_BY_LANGUAGE.items():
        for canonical, words in headers.items():
            for word in words:
                assert _match_column(word) == canonical, f"{language}.{canonical}: {word!r}"


def test_every_declared_header_is_stored_lowercased_and_stripped() -> None:
    # The matcher lowercases and strips the sheet's header before the lookup,
    # so a table entry that is not already in that form can never be hit.
    for language, headers in _HEADERS_BY_LANGUAGE.items():
        for canonical, words in headers.items():
            for word in words:
                assert word == word.strip().lower(), f"{language}.{canonical}: {word!r}"
                assert word, f"{language}.{canonical} holds an empty header"


# ── Completeness ────────────────────────────────────────────────────────────


def test_every_language_names_the_four_columns_a_bill_row_needs() -> None:
    assert _languages_missing_mandatory_columns(_HEADERS_BY_LANGUAGE) == {}


def test_the_four_columns_a_bill_row_needs_are_still_those_four() -> None:
    # Pinned rather than read off the constant elsewhere: dropping one of
    # these would weaken the completeness rule without failing it, and a
    # language admitted with no rate column imports every line at zero.
    assert _MANDATORY_COLUMNS == ("description", "unit", "quantity", "unit_rate")


def test_a_language_added_with_a_hole_is_reported_rather_than_silently_supported() -> None:
    # The mechanism, not today's data: a table with a hole has to be named as
    # incomplete, otherwise the rule above passes for as long as nobody adds
    # a bad language and stops meaning anything the day somebody does.
    holed = {
        "xx": {"description": ("beskrywing",), "unit": ("eenheid",), "quantity": ("hoeveelheid",)},
        "yy": {"description": ("descripcio",), "unit": (), "quantity": ("quantitat",), "unit_rate": ("preu",)},
        "zz": {"description": ("a",), "unit": ("b",), "quantity": ("c",), "unit_rate": ("d",)},
    }
    assert _languages_missing_mandatory_columns(holed) == {"xx": ("unit_rate",), "yy": ("unit",)}


def test_supported_header_languages_is_the_tables_own_key_set() -> None:
    assert frozenset(_HEADERS_BY_LANGUAGE) == SUPPORTED_HEADER_LANGUAGES
    assert sorted(SUPPORTED_HEADER_LANGUAGES) == [
        "ar",
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "fi",
        "fr",
        "he",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sv",
        "tr",
        "uk",
        "vi",
        "zh",
    ]


def test_the_flat_alias_map_is_derived_from_the_table_rather_than_kept_beside_it() -> None:
    # ``SUPPORTED_HEADER_LANGUAGES`` is only honest if the matcher reads the
    # same table the constant is counted from. A second list maintained by
    # hand would agree with both of these on the day it was written and drift
    # afterwards, so the map is asserted to BE the table's union, and a table
    # with one more language is asserted to produce a different map.
    assert _build_column_aliases(_HEADERS_BY_LANGUAGE) == _COLUMN_ALIASES

    grown = dict(_HEADERS_BY_LANGUAGE)
    grown["xx"] = {
        "description": ("beskrywing",),
        "unit": ("eenheid",),
        "quantity": ("hoeveelheid",),
        "unit_rate": ("prys",),
    }
    rebuilt = _build_column_aliases(grown)
    assert rebuilt["description"] - _COLUMN_ALIASES["description"] == {"beskrywing"}
    assert rebuilt["unit_rate"] - _COLUMN_ALIASES["unit_rate"] == {"prys"}


# ── Reading a real workbook in each market's own words ──────────────────────


def _workbook(header_row: list[str], data_rows: list[list[Any]]) -> bytes:
    """A one-sheet .xlsx with the given header row and data rows."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(header_row)
    for row in data_rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _parse(content: bytes) -> ImportedBOQ:
    """Run the importer's async entry point from a synchronous test."""
    return asyncio.run(ExcelImporter.parse(content))


# One header row per market, written the way that market writes it, plus the
# two lines underneath. Polish and Russian carry no ordinal header of their
# own, so those sheets start at the description and the importer numbers the
# rows itself, which is the shape a bill exported without a position column
# actually has.
_MARKET_SHEETS: dict[str, tuple[dict[str, str], list[tuple[str, str, float, float]]]] = {
    "pt": (
        {
            "ordinal": "Nº",
            "description": "Descrição",
            "unit": "Unidade",
            "quantity": "Quantidade",
            "unit_rate": "Preço Unitário",
            "total": "Valor Total",
        },
        [
            ("Concreto usinado fck 30 MPa", "m3", 12.5, 340.0),
            ("Forma de madeira para pilares", "m2", 48.0, 96.5),
        ],
    ),
    "nl": (
        {
            "ordinal": "Postnr.",
            "description": "Omschrijving",
            "unit": "Eenheid",
            "quantity": "Hoeveelheid",
            "unit_rate": "Eenheidsprijs",
            "total": "Totaal",
        },
        [
            ("Betonwand C30/37 dikte 240 mm", "m3", 31.0, 288.0),
            ("Bekisting wanden tweezijdig", "m2", 122.0, 54.0),
        ],
    ),
    "tr": (
        {
            "ordinal": "Sıra No",
            "description": "Tanım",
            "unit": "Birim",
            "quantity": "Miktar",
            "unit_rate": "Birim Fiyat",
            "total": "Tutar",
        },
        [
            ("C30/37 betonarme perde duvar", "m3", 18.0, 4200.0),
            ("Kalıp işleri, düz yüzey", "m2", 76.0, 380.0),
        ],
    ),
    "ja": (
        {
            "ordinal": "番号",
            "description": "名称",
            "unit": "単位",
            "quantity": "数量",
            "unit_rate": "単価",
            "total": "金額",
        },
        [
            ("鉄筋コンクリート壁 C30/37", "m3", 24.0, 62000.0),
            ("型枠工事 普通合板", "m2", 96.0, 4800.0),
        ],
    ),
    "zh": (
        {
            "ordinal": "序号",
            "description": "项目名称",
            "unit": "计量单位",
            "quantity": "工程量",
            "unit_rate": "综合单价",
            "total": "合价",
        },
        [
            ("现浇混凝土墙 C30/37", "m3", 40.0, 620.0),
            ("模板工程 胶合板", "m2", 160.0, 48.0),
        ],
    ),
    "ar": (
        {
            "ordinal": "الرقم",
            "description": "الوصف",
            "unit": "الوحدة",
            "quantity": "الكمية",
            "unit_rate": "سعر الوحدة",
            "total": "الإجمالي",
        },
        [
            ("جدار خرساني مسلح", "m3", 22.0, 1150.0),
            ("أعمال القوالب الخشبية", "m2", 88.0, 130.0),
        ],
    ),
    "pl": (
        {
            "description": "Opis",
            "unit": "Jed",
            "quantity": "Ilość",
            "unit_rate": "Cena jednostkowa",
        },
        [
            ("Ściana żelbetowa C30/37", "m3", 27.0, 980.0),
            ("Deskowanie ścian dwustronne", "m2", 108.0, 62.0),
        ],
    ),
    "ru": (
        {
            "description": "Наименование",
            "unit": "Ед.",
            "quantity": "Количество",
            "unit_rate": "Цена",
        },
        [
            ("Стена железобетонная C30/37", "m3", 35.0, 14500.0),
            ("Опалубка стен двусторонняя", "m2", 140.0, 850.0),
        ],
    ),
}


@pytest.mark.parametrize("language", sorted(_MARKET_SHEETS))
def test_a_bill_headed_in_its_own_language_imports_with_its_own_numbers(language: str) -> None:
    headers, lines = _MARKET_SHEETS[language]
    columns = list(headers)
    content = _workbook(
        [headers[column] for column in columns],
        [
            [
                {
                    "ordinal": str(index),
                    "description": description,
                    "unit": unit,
                    "quantity": quantity,
                    "unit_rate": rate,
                    "total": round(quantity * rate, 2),
                }[column]
                for column in columns
            ]
            for index, (description, unit, quantity, rate) in enumerate(lines, start=1)
        ],
    )

    imported = _parse(content)

    assert imported.errors == []
    assert len(imported.positions) == len(lines)
    for position, (description, unit, quantity, rate) in zip(imported.positions, lines, strict=True):
        assert position.description == description
        assert position.unit == unit
        assert position.quantity == pytest.approx(quantity)
        assert position.unit_rate == pytest.approx(rate)
    assert [position.ordinal for position in imported.positions] == ["1", "2"]


@pytest.mark.parametrize("language", sorted(_MARKET_SHEETS))
def test_a_market_whose_sheet_imports_is_listed_as_a_supported_header_language(language: str) -> None:
    assert language in SUPPORTED_HEADER_LANGUAGES


# ── A market the table does not know ────────────────────────────────────────

# Swahili, which the table does not carry. Deliberately a language nobody
# has added, so the test keeps meaning what it says.
_UNKNOWN_MARKET_HEADERS = ["Na.", "Maelezo ya kazi", "Kipimo", "Kiasi", "Bei ya kipimo", "Jumla ya bei"]


def test_a_header_in_an_unknown_language_is_unmatched_rather_than_an_error() -> None:
    for header in _UNKNOWN_MARKET_HEADERS:
        assert _match_column(header) is None


def test_an_unknown_column_beside_known_ones_is_ignored_and_the_rest_imports() -> None:
    content = _workbook(
        ["Description", "Unit", "Quantity", "Unit Rate", "Maelezo ya kazi"],
        [["Reinforced concrete wall", "m3", 9.0, 410.0, "kazi ya ziada"]],
    )

    imported = _parse(content)

    assert imported.errors == []
    assert len(imported.positions) == 1
    assert imported.positions[0].quantity == pytest.approx(9.0)
    assert imported.positions[0].unit_rate == pytest.approx(410.0)
    assert "Maelezo ya kazi" in imported.metadata["original_columns"]
    # The unknown column is the fifth, so index "4" must be absent from the
    # mapping: recorded as seen, mapped to nothing.
    assert sorted(imported.metadata["column_mapping"]) == ["0", "1", "2", "3"]


def test_a_sheet_headed_entirely_in_an_unknown_language_degrades_to_a_named_refusal() -> None:
    # Nothing maps, so no row carries a canonical key and the parser has
    # nothing to return. It has to say so as ``ImporterParseError``, which the
    # dispatcher turns into a 400 naming the reason and, when it is the
    # dispatcher's own detection that found no importer at all, into the smart
    # import path. An untyped exception would be logged as a failure of ours
    # instead of reported as a file we cannot read.
    content = _workbook(
        _UNKNOWN_MARKET_HEADERS,
        [["1", "Ukuta wa zege", "m3", 9.0, 410.0, 3690.0]],
    )

    with pytest.raises(ImporterParseError) as excinfo:
        _parse(content)

    assert "No data rows found" in str(excinfo.value)
