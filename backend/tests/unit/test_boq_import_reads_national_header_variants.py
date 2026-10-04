# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The header words each market's own bills are written in.

The header table knew one word per column for most languages: "prezzo" but
not "Prezzo unitario", "precio" but not "Precio unitario", "наименование" but
not "Наименование работ". Matching is exact on the normalised label, so an
Italian computo headed the way Italian computi are headed imported every rate
at zero, with one info line per row to say so. The classification column was
worse: Chinese, Japanese, Korean, Indonesian, Russian, Polish, Romanian and
Greek bills name their code column in their own word, and with no alias the
code was dropped as an unknown column, so the national code rules that read
it found nothing on any line.

Each test below is a header row as that market prints it.

Run::

    cd backend
    python -m pytest tests/unit/test_boq_import_reads_national_header_variants.py -v
"""

from __future__ import annotations

import asyncio
import io

import pytest
from openpyxl import Workbook

from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.excel import (
    _HEADERS_BY_LANGUAGE,
    DECIMAL_COMMA_LANGUAGES,
    DECIMAL_POINT_LANGUAGES,
    ExcelImporter,
    _label_key,
    _match_column,
    header_language,
)


@pytest.mark.parametrize(
    ("header", "canonical"),
    [
        # Spanish presupuesto, as the Spanish estimating programs print it.
        ("Código", "classification"),
        ("Resumen", "description"),
        ("Medición", "quantity"),
        ("Precio unitario", "unit_rate"),
        ("Importe total", "total"),
        # Mexican catálogo de conceptos.
        ("Clave", "classification"),
        ("Concepto", "description"),
        ("P.U.", "unit_rate"),
        # French DPGF / DQE.
        ("N°", "ordinal"),
        ("Qté", "quantity"),
        ("PU HT", "unit_rate"),
        ("P.U. HT", "unit_rate"),
        ("Prix unitaire", "unit_rate"),
        ("Prix unitaire HT", "unit_rate"),
        # Italian computo metrico estimativo.
        ("N. ord.", "ordinal"),
        ("Num. ord.", "ordinal"),
        ("Tariffa", "classification"),
        ("Codice", "classification"),
        ("Designazione dei lavori", "description"),
        ("U.M.", "unit"),
        ("Q.tà", "quantity"),
        ("Prezzo unitario", "unit_rate"),
        ("Prezzo unit.", "unit_rate"),
        # Polish kosztorys.
        ("Lp.", "ordinal"),
        ("Podstawa", "classification"),
        ("Nazwa", "description"),
        ("Opis robót", "description"),
        ("J.m.", "unit"),
        ("Jednostka miary", "unit"),
        ("Wartość", "total"),
        # Russian smeta.
        ("№ п/п", "ordinal"),
        ("Обоснование", "classification"),
        ("Шифр расценки", "classification"),
        ("Наименование работ", "description"),
        ("Наименование работ и затрат", "description"),
        ("Ед. изм.", "unit"),
        ("Единица измерения", "unit"),
        ("Кол.", "quantity"),
        ("Всего", "total"),
        # Ukrainian koshtorys.
        ("Шифр", "classification"),
        ("Обґрунтування", "classification"),
        # Turkish keşif özeti: the poz number is the unit price code, the
        # running number is the sıra number.
        ("Poz No", "classification"),
        ("Sıra No", "ordinal"),
        ("Yapılan İşin Cinsi", "description"),
        ("Birimi", "unit"),
        ("Miktarı", "quantity"),
        ("Tutarı", "total"),
        # Romanian deviz, Greek προμέτρηση.
        ("Simbol", "classification"),
        ("Cod articol", "classification"),
        ("Άρθρο", "classification"),
        ("Κωδικός άρθρου", "classification"),
        # The code column of the East and South East Asian bills.
        ("项目编码", "classification"),
        ("清单编码", "classification"),
        ("定额编号", "classification"),
        ("コード", "classification"),
        ("細目コード", "classification"),
        ("코드", "classification"),
        ("공종코드", "classification"),
        ("Kode", "classification"),
        ("Kode Analisa", "classification"),
        # Indian bill priced against the Delhi Schedule of Rates.
        ("DSR Code", "classification"),
        ("DSR No.", "classification"),
        ("Item Code", "classification"),
    ],
)
def test_a_market_header_reaches_its_column(header: str, canonical: str) -> None:
    assert _match_column(header) == canonical


def test_no_new_word_is_claimed_by_a_decimal_comma_and_a_decimal_point_language() -> None:
    # The header language decides how "1.250" and "1,250" are read. A word
    # both kinds of market write would let one header flip the other's money.
    comma = {
        _label_key(word)
        for language in DECIMAL_COMMA_LANGUAGES & set(_HEADERS_BY_LANGUAGE)
        for words in _HEADERS_BY_LANGUAGE[language].values()
        for word in words
    }
    point = {
        _label_key(word)
        for language in DECIMAL_POINT_LANGUAGES & set(_HEADERS_BY_LANGUAGE)
        for words in _HEADERS_BY_LANGUAGE[language].values()
        for word in words
    }
    shared = comma & point
    # The two shared before this table grew: "No" (English, and the numero
    # sign of the Bulgarian header folded to the same two letters) and
    # "Sum" (English, and Norwegian and Danish). Both sit beside other words
    # that settle the language.
    assert shared <= {"no", "sum"}, sorted(shared)


def _workbook(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _import(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content))


def test_an_italian_computo_imports_its_rates_and_price_list_codes() -> None:
    content = _workbook(
        [
            ["Num. ord.", "Tariffa", "Designazione dei lavori", "U.M.", "Quantità", "Prezzo unitario", "Importo"],
            ["1", "1C.01.010.0010", "Scavo di sbancamento", "m³", "125,50", "8,40", "1.054,20"],
            ["2", "1C.04.030.0020.b", "Calcestruzzo C25/30 per fondazioni", "m³", "42", "1.250,00", "52.500,00"],
        ]
    )
    result = _import(content)

    assert result.metadata["header_language"] == "it"
    lines = {p.ordinal: p for p in result.positions}
    assert (lines["1"].quantity, lines["1"].unit_rate) == (pytest.approx(125.5), pytest.approx(8.4))
    assert (lines["2"].quantity, lines["2"].unit_rate) == (pytest.approx(42.0), pytest.approx(1250.0))
    assert lines["1"].classification["code"] == "1C.01.010.0010"
    assert lines["2"].classification["code"] == "1C.04.030.0020.b"


def test_a_turkish_bill_keeps_its_poz_number_as_the_code_and_its_sira_as_the_ordinal() -> None:
    content = _workbook(
        [
            ["Sıra No", "Poz No", "Yapılan İşin Cinsi", "Birimi", "Miktarı", "Birim Fiyatı", "Tutarı"],
            ["1", "15.150.1005", "C30/37 hazır beton dökülmesi", "m³", "18", "4.200,00", "75.600,00"],
            ["2", "15.180.1003", "Plywood ile düz yüzeyli beton kalıbı", "m²", "76", "380,00", "28.880,00"],
        ]
    )
    result = _import(content)

    lines = {p.ordinal: p for p in result.positions}
    assert set(lines) == {"1", "2"}
    assert lines["1"].classification["code"] == "15.150.1005"
    assert lines["1"].unit_rate == pytest.approx(4200.0)
    assert lines["2"].unit_rate == pytest.approx(380.0)


def test_a_russian_smeta_keeps_its_rate_code_and_reads_its_numbers_with_a_decimal_comma() -> None:
    content = (
        "№ п/п;Обоснование;Наименование работ и затрат;Ед. изм.;Кол.;Цена;Всего\n"
        "1;ГЭСН06-01-001-01;Устройство бетонной подготовки;100 м3;0,45;125 430,50;56 443,73\n"
        "2;ГЭСН08-02-001-01;Кладка стен из кирпича;м3;1.250;4 812,00;6 015 000,00\n"
    ).encode("cp1251")
    result = _import(content)

    assert result.metadata["header_language"] == "ru"
    lines = {p.ordinal: p for p in result.positions}
    assert lines["1"].classification["code"] == "ГЭСН06-01-001-01"
    assert lines["1"].description == "Устройство бетонной подготовки"
    assert (lines["1"].quantity, lines["1"].unit_rate) == (pytest.approx(0.45), pytest.approx(125430.5))
    assert lines["2"].quantity == pytest.approx(1250.0)


def test_a_spanish_presupuesto_imports_from_its_own_header() -> None:
    content = (
        "Código;Ud;Resumen;Medición;Precio unitario;Importe\n"
        "E02AM010;m2;Desbroce y limpieza del terreno;1.250,00;0,85;1.062,50\n"
        "E04CM040;m3;Hormigón de limpieza HL-150/B/20;12,5;78,40;980,00\n"
    ).encode()
    result = _import(content)

    assert result.metadata["header_language"] == "es"
    lines = [p for p in result.positions if not p.is_section]
    assert [p.classification.get("code") for p in lines] == ["E02AM010", "E04CM040"]
    assert [(p.quantity, p.unit_rate) for p in lines] == [
        (pytest.approx(1250.0), pytest.approx(0.85)),
        (pytest.approx(12.5), pytest.approx(78.4)),
    ]


def test_a_mexican_catalogo_keeps_its_decimal_point_and_its_clave() -> None:
    # Headed in Spanish, written with a decimal point: "1,250.50" can only be
    # read one way, so the comma groups thousands across the whole file.
    content = (
        "Clave,Concepto,Unidad,Cantidad,P.U.,Importe\n"
        'CIM-001,Excavación a cielo abierto,m3,"1,250.50",185.40,"231,842.70"\n'
        'EST-014,Concreto f\'c=250 kg/cm2 en zapatas,m3,42,"3,150.00","132,300.00"\n'
    ).encode()
    result = _import(content)

    lines = [p for p in result.positions if not p.is_section]
    assert [p.classification.get("code") for p in lines] == ["CIM-001", "EST-014"]
    assert [(p.quantity, p.unit_rate) for p in lines] == [
        (pytest.approx(1250.5), pytest.approx(185.4)),
        (pytest.approx(42.0), pytest.approx(3150.0)),
    ]


def test_a_gb50500_bill_keeps_its_twelve_digit_item_code() -> None:
    content = _workbook(
        [
            ["序号", "项目编码", "项目名称", "计量单位", "工程量", "综合单价", "合价"],
            ["1", "010101001001", "平整场地", "m2", "1250", "5.20", "6500.00"],
        ]
    )
    result = _import(content)

    assert header_language(["序号", "项目编码", "项目名称", "计量单位", "工程量", "综合单价", "合价"]) == "zh"
    (line,) = result.positions
    assert line.classification["code"] == "010101001001"
