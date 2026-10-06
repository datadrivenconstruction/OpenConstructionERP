"""Regional price-list readers: every published format, read from trimmed real files.

The fixtures under ``tests/fixtures/pricelists/`` are excerpts of the files the
regions publish, cut to a handful of rows and otherwise unchanged; each names
its source and the licence as found in its first lines (``README.md`` there
lists them). SIX has no regional file available to us and is read from a
synthetic file built to the published schema.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.costs.pricelists import containers
from app.modules.costs.pricelists.base import (
    BrokenNumber,
    PriceListSource,
    normalise_unit,
    parse_amount,
    region_from_code,
)
from app.modules.costs.pricelists.containers import ContainerRefused, open_members
from app.modules.costs.pricelists.service import (
    build_preview,
    cost_item_payload,
    plan_upload,
    skip_reason,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _plan(data: bytes, name: str):
    return plan_upload(io.BytesIO(data), name)


def _rows(data: bytes, name: str):
    plan = _plan(data, name)
    return plan, list(plan.rows())


def _zip(members: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _component_total(components: list[dict]) -> Decimal:
    return sum((Decimal(str(c["cost"])) for c in components), Decimal(0))


# ── Numbers, units, codes ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("€ 1 826,34", Decimal("1826.34")),
        ("€\xa0263,12", Decimal("263.12")),
        ("1.826,34", Decimal("1826.34")),
        ("1,826.34", Decimal("1826.34")),
        ("217,67", Decimal("217.67")),
        ("13.63017", Decimal("13.63017")),
        ("8.6300000000000008", Decimal("8.63")),
        ("16.239999999999998", Decimal("16.24")),
        ("70,76 %", Decimal("70.76")),
        (1125, Decimal(1125)),
        (20.5, Decimal("20.5")),
        ("", None),
        (None, None),
        ("-", None),
    ],
)
def test_parse_amount_reads_every_spelling_the_lists_use(raw, expected) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["15.403.443", "6.777.515", "1,2,3", "12,34.5", "abc", "1.234,5,6"])
def test_parse_amount_refuses_a_number_whose_separator_is_lost(raw) -> None:
    with pytest.raises(BrokenNumber):
        parse_amount(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("m²", "m2"),
        ("mq", "m2"),
        ("m³", "m3"),
        ("mc", "m3"),
        ("cad", "pcs"),
        ("1 cad", "pcs"),
        ("100 kg", "100 kg"),
        ("ora", "hr"),
        ("a corpo", "lsum"),
        ("", "pcs"),
        ("1 m² * cm", "m2 x cm"),
        ("m² × cm", "m2 x cm"),
        ("€/m²", "m2"),
        ("ml <b>", "ml b"),
    ],
)
def test_units_are_normalised_and_a_multiplier_is_kept(raw, expected) -> None:
    assert normalise_unit(raw) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("TOS25_01.A03.001.001", ("TOS", "2025")),
        ("VEN26-01.02.01.00", ("VEN", "2026")),
        ("LOM261.OC.EEA.Pa01", ("LOM", "2026")),
        ("CAM24_A00.010.100.A", ("CAM", "2024")),
        ("PUG2026/01.E01.001.001", ("PUG", "2026")),
        ("08.P25.F79.040", None),
        ("XYZ25_01", None),
    ],
)
def test_region_and_year_read_off_the_code_prefix(code, expected) -> None:
    assert region_from_code(code) == expected


_ALL_LISTS = [
    ("toscana_firenze_2025.xml", "Firenze-2025.xml"),
    ("veneto_2026.xml", "prezzario2026.xml"),
    ("lombardia_2026.xml", "lom.xml"),
    ("lombardia_2026_legacy.xml", "legacy.xml"),
    ("campania_2024.csv", "prezzario_llpp2024_articoli.csv"),
    ("puglia_2026.csv", "2026_prezzario_regione_puglia.csv"),
    ("piemonte_2023.csv", "prezzi.csv"),
    ("umbria_2025.json", "Elenco_regionale_prezzi_2025.json"),
    ("lazio_2023_parte_a.csv", "PARTE A OPERE EDILI 2023.csv"),
    ("lazio_2023_parte_e.csv", "PARTE E IMPIANTI TECNOLOGICI 2023.csv"),
]


@pytest.mark.parametrize(("fixture", "name"), _ALL_LISTS)
def test_every_unit_a_list_yields_is_one_a_bill_line_accepts(fixture: str, name: str) -> None:
    # A Lombardia voce priced per square metre and centimetre of thickness
    # ("1 m² * cm") came out as "m2*cm", which the BOQ refuses, so the voce
    # could be imported and never added to a bill.
    from app.modules.boq.units import normalise_unit as bill_unit

    _plan_, rows = _rows(_bytes(fixture), name)
    refused = sorted({r.unit for r in rows if bill_unit(r.unit) is None})
    assert refused == []


# ── Toscana XML ──────────────────────────────────────────────────────────────


def test_toscana_header_gives_region_edition_area_and_the_licence_it_states() -> None:
    plan, rows = _rows(_bytes("toscana_firenze_2025.xml"), "Firenze-2025.xml")
    src = plan.source
    assert plan.format.format_id == "toscana_xml"
    assert (src.region_code, src.edition, src.area) == ("TOS", "2025", "Provincia di Firenze")
    assert (src.licence, src.licence_stated_in) == ("CC BY 3.0", "file")
    assert src.publisher == "Regione Toscana"
    assert src.suggested_catalog_name() == "Toscana 2025 - Firenze"
    assert "Regione Toscana" in src.attribution() and "CC BY 3.0" in src.attribution()
    assert len(rows) == 9


def test_toscana_analysis_becomes_components_that_add_up_to_the_price() -> None:
    _plan_, rows = _rows(_bytes("toscana_firenze_2025.xml"), "Firenze-2025.xml")
    first = next(r for r in rows if r.code == "TOS25_01.A03.001.001")
    assert first.rate == Decimal("13.63017")
    assert first.unit == "m3" and first.source_unit == "m³"
    assert first.components, "the voce carries an Analisi"
    assert _component_total(first.components) == first.rate
    types = {c["type"] for c in first.components}
    assert "labor" in types and "equipment" in types
    assert first.components[-1]["name"] == "Spese generali e utile d'impresa"
    assert first.labour_share_pct is not None and first.labour_amount is not None
    assert first.overhead_pct is not None and first.profit_pct is not None
    assert first.chapters[0] == ("01", "NUOVE COSTRUZIONI EDILI")


def test_toscana_safety_chapter_and_cam_flag_are_carried() -> None:
    _plan_, rows = _rows(_bytes("toscana_firenze_2025.xml"), "Firenze-2025.xml")
    assert sum(1 for r in rows if r.safety) == 2
    assert all(r.code.startswith("TOS25_17.") for r in rows if r.safety)
    assert sum(1 for r in rows if r.extra.get("cam")) == 1


# ── Veneto XML ───────────────────────────────────────────────────────────────


def test_veneto_reads_paragraphs_with_chapters_and_labour_share() -> None:
    plan, rows = _rows(_bytes("veneto_2026.xml"), "prezzario2026.xml")
    assert plan.format.format_id == "veneto_xml"
    assert (plan.source.region_code, plan.source.edition) == ("VEN", "2026")
    assert plan.source.detected_from == "code_prefix"
    assert plan.source.licence is None, "the file states none and no catalogue record was read"
    first = rows[0]
    assert first.code == "VEN26-01.02.01.00"
    assert first.rate == Decimal("3.47") and first.unit == "m2"
    assert first.labour_share_pct == Decimal("35.44")
    assert [c for c, _t in first.chapters] == ["VEN26-01", "VEN26-01.02", "VEN26-01.02.01"]
    assert first.description.startswith("Scavo di pulizia generale")


# ── Lombardia XML, both layouts ──────────────────────────────────────────────


def test_lombardia_resources_add_up_to_the_price_and_zero_rows_are_skipped() -> None:
    plan, rows = _rows(_bytes("lombardia_2026.xml"), "lom.xml")
    assert plan.format.format_id == "lombardia_xml"
    assert (plan.source.region_code, plan.source.edition) == ("LOM", "2026")
    assert [skip_reason(r) for r in rows].count("zero_rate") == 1
    with_resources = [r for r in rows if r.components]
    assert len(with_resources) == 3
    for row in with_resources:
        assert _component_total(row.components) == row.rate
    assert with_resources[0].source_unit == "1 cad" and with_resources[0].unit == "pcs"


def test_lombardia_legacy_layout_ratio_becomes_a_percentage() -> None:
    plan, rows = _rows(_bytes("lombardia_2026_legacy.xml"), "legacy.xml")
    assert plan.format.format_id == "lombardia_legacy_xml"
    first = rows[0]
    assert first.code == "LOM261.1C.00.010.0010"
    assert first.rate == Decimal("1.44")
    assert first.labour_share_pct == Decimal("45.61")
    assert first.chapters[0] == ("LOM261.1C", "OPERE COMPIUTE")


def test_lombardia_zip_reads_the_current_layout_and_lists_the_other_as_skipped() -> None:
    data = _zip(
        {
            "Prezzario_2026_LOM261_XML/A) Parte 1.xml": _bytes("lombardia_2026.xml"),
            "Prezzario_2026_LOM261_XML/F) Parte 4 - Precedente struttura.xml": _bytes("lombardia_2026_legacy.xml"),
            "Prezzario_2026_LOM261_XML/": b"",
        }
    )
    plan = _plan(data, "Prezzario_2026_LOM261_XML.zip")
    assert plan.format.format_id == "lombardia_xml"
    assert [m.name for m in plan.members] == ["A) Parte 1.xml"]
    assert plan.skipped == [
        {
            "name": "F) Parte 4 - Precedente struttura.xml",
            "reason": "same_list_other_format",
            "format": "lombardia_legacy_xml",
        }
    ]


# ── Tables: Campania, Puglia, Piemonte, Umbria, Lazio ────────────────────────


def test_campania_lost_separator_is_flagged_never_guessed() -> None:
    plan, rows = _rows(_bytes("campania_2024.csv"), "prezzario_llpp2024_articoli.csv")
    assert (plan.source.region_code, plan.source.edition) == ("CAM", "2024")
    assert plan.source.detected_from == "code_prefix"
    first = rows[0]
    assert first.code == "CAM24_A00.010.100.A"
    assert first.rate == Decimal("217.67")
    # "Manodopera %" read "15.403.443": the labour amount is left empty and flagged.
    assert first.labour_amount is None
    assert "broken_number:labour_amount" in first.flags
    assert first.labour_share_pct == Decimal("70.76")
    assert first.safety_amount == Decimal("0.28752")
    preview = build_preview(_plan(_bytes("campania_2024.csv"), "x.csv"))
    assert preview["counts"]["broken_rows"] == 8
    assert "broken_numbers" in preview["warnings"]
    assert preview["broken_examples"][0] == {"code": "CAM24_A00.010.100.A", "fields": ["labour_amount"]}
    # A broken labour cell does not stop the voce: its price is sound.
    assert preview["counts"]["importable"] == 8


def test_campania_does_not_repeat_the_voce_text_in_the_description() -> None:
    _plan_, rows = _rows(_bytes("campania_2024.csv"), "x.csv")
    assert not rows[0].description.startswith("Misura  ponderale  del  contenuto  d'acqua  su  murature - Misura")


def test_puglia_float_noise_and_resource_totals() -> None:
    plan, rows = _rows(_bytes("puglia_2026.csv"), "2026_prezzario_regione_puglia.csv")
    assert (plan.source.region_code, plan.source.edition) == ("PUG", "2026")
    first = rows[0]
    assert first.code == "PUG2026/01.E01.001.001"
    assert first.rate == Decimal("8.63")
    assert first.labour_share_pct == Decimal("59.26")
    assert _component_total(first.components) == first.rate
    assert {c["type"] for c in first.components} == {"labor", "equipment", "other"}
    assert first.chapters[:2] == [("01", "EDILIZIA"), ("01.E01", first.chapters[1][1])]
    # The file states no licence; the publisher's catalogue record does, and says so.
    assert plan.source.licence is None
    plan.source.resolve_licence()
    assert (plan.source.licence, plan.source.licence_stated_in) == ("CC BY 4.0", "catalogue")


def test_piemonte_region_is_a_layout_guess_the_preview_asks_to_confirm() -> None:
    plan = _plan(_bytes("piemonte_2023.csv"), "prezzi.csv")
    preview = build_preview(plan)
    assert preview["source"]["region_code"] == "PIE"
    assert preview["source"]["region_detected_from"] == "layout"
    assert "region_inferred" in preview["warnings"]
    assert preview["source"]["edition"] == "2023"
    row = next(iter(_plan(_bytes("piemonte_2023.csv"), "prezzi.csv").rows()))
    assert row.code == "08.P25.F79.040" and row.rate == Decimal("136.34")
    assert row.short_description == "guarnizione elemento conico terminale"
    assert row.description.startswith("Pozzetto di ispezione")


def test_umbria_json_in_cp1252_with_dot_zero_headings() -> None:
    plan, rows = _rows(_bytes("umbria_2025.json"), "Elenco_regionale_prezzi_2025.json")
    assert plan.format.format_id == "tabular_json"
    assert plan.source.edition == "2025"
    by_code = {r.code: r for r in rows}
    assert by_code["1.1.10"].rate == Decimal(1125)
    assert by_code["1.1.10"].labour_amount == Decimal(418)
    child = by_code["1.1.20.1"]
    assert child.description.startswith("INSTALLAZIONE DI ATTREZZATURA PER SONDAGGIO")
    assert child.description.endswith("Per distanza fino a m 300.")
    assert child.chapters[0][0] == "1"
    assert all(r.rate for r in rows), "headings carry no price and are not rows"


def _umbria_workbook() -> bytes:
    from openpyxl import Workbook

    records = json.loads(_bytes("umbria_2025.json").decode("cp1252"))
    ((title, rows),) = records.items()
    wb = Workbook()
    ws = wb.active
    ws.title = "Capitolo 1"
    header = list(rows[0].keys())
    ws.append(header)
    for rec in rows:
        ws.append([rec[h] for h in header])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_umbria_zip_with_xlsx_and_json_reads_the_workbook_once() -> None:
    data = _zip(
        {
            "2025/Elenco regionale dei prezzi 2025 - Capitoli da 1 a 13.xlsx": _umbria_workbook(),
            "2025/Elenco_regionale_prezzi_2025 - Capitoli da 1 a 21.json": _bytes("umbria_2025.json"),
            "2025/Prezzario 2025 Scheda metadatazione.docx": b"PK not really",
        }
    )
    plan = _plan(data, "2025.zip")
    assert plan.format.format_id == "tabular_xlsx"
    reasons = {s["name"]: s["reason"] for s in plan.skipped}
    assert reasons["Elenco_regionale_prezzi_2025 - Capitoli da 1 a 21.json"] == "same_list_other_format"
    assert reasons["Prezzario 2025 Scheda metadatazione.docx"] == "not_a_price_list_file"
    rows = list(plan.rows())
    assert {r.code for r in rows} >= {"1.1.10", "1.1.20.1"}
    assert next(r for r in rows if r.code == "1.1.10").rate == Decimal(1125)


def test_lazio_headerless_parts_in_two_encodings() -> None:
    data = _zip(
        {
            "PARTE A OPERE EDILI 2023.csv": _bytes("lazio_2023_parte_a.csv"),
            "PARTE E IMPIANTI TECNOLOGICI 2023.csv": _bytes("lazio_2023_parte_e.csv"),
        }
    )
    plan = _plan(data, "Tariffa_2023_formato_open_DATA.zip")
    rows = list(plan.rows())
    by_code = {r.code: r for r in rows}
    # Part A is Windows-1252: the apostrophe is U+2019 and the euro sign parses.
    first = by_code["A1.01.1"]
    assert first.rate == Decimal("1826.34")
    assert "dell’attrezzatura" in first.description
    assert by_code["A1.01.2.a"].rate == Decimal("263.12")
    assert by_code["A1.01.2.a"].chapters[0] == ("A", "Parte A")
    # Part E is UTF-8 with no part column and codes without dots.
    pipe = by_code["E01001a"]
    assert pipe.rate == Decimal("10.72")
    assert pipe.description.startswith("serie leggera:")
    assert ("E01", "IMPIANTI IDRO-SANITARI E GAS DOMESTICO") in pipe.chapters
    preview = build_preview(_plan(data, "Tariffa_2023_formato_open_DATA.zip"))
    assert "region_not_detected" in preview["warnings"]
    assert "licence_not_stated" in preview["warnings"]


# ── SIX (synthetic, built to the published schema) ───────────────────────────

_SIX = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Synthetic SIX file built to six.xsd 2.0 for tests; not a published list. -->
<Documento xmlns="six.xsd" xmlns:s="six.xsd">
  <intestazione s:autore="Regione Esempio"/>
  <prezzario s:prezzarioId="P1">
    <unitaDiMisura s:unitaDiMisuraId="1" s:simbolo="m²"/>
    <unitaDiMisura s:unitaDiMisuraId="2" s:simbolo="cad"/>
    <listaQuotazione s:listaQuotazioneId="Q24" s:lqtId="Prezzi 2024"/>
    <listaQuotazione s:listaQuotazioneId="Q25" s:lqtId="Prezzi 2025"/>
    <przDescrizione s:lingua="it" s:breve="Prezzario regionale 2025"/>
    <prodotto s:prodottoId="1" s:prdId="SAR25_A.01">
      <prdDescrizione s:lingua="it" s:breve="SCAVI" s:estesa="Scavi e movimenti di terra"/>
    </prodotto>
    <prodotto s:prodottoId="2" s:prdId="SAR25_A.01.001" s:unitaDiMisuraId="1" s:onereSicurezza="0,12">
      <incidenzaManodopera>35,5</incidenzaManodopera>
      <prdDescrizione s:lingua="it" s:breve="Scavo di sbancamento" s:estesa="Scavo di sbancamento con mezzi meccanici"/>
      <prdQuotazione s:listaQuotazioneId="Q24" s:valore="11.90"/>
      <prdQuotazione s:listaQuotazioneId="Q25" s:valore="12.50"/>
    </prodotto>
    <prodotto s:prodottoId="3" s:prdId="SAR25_A.01.002" s:unitaDiMisuraId="2">
      <prdDescrizione s:lingua="it" s:breve="Pozzetto" s:estesa="Pozzetto prefabbricato"/>
      <prdQuotazione s:listaQuotazioneId="Q25" s:valore="15.403.443"/>
    </prodotto>
  </prezzario>
</Documento>
"""


def test_six_takes_the_latest_quotation_and_carries_headings() -> None:
    plan, rows = _rows(_SIX.encode(), "elenco.xml")
    assert plan.format.format_id == "six_xml"
    assert plan.source.profile == "quotation:Q25"
    assert (plan.source.region_code, plan.source.edition) == ("SAR", "2025")
    first = rows[0]
    assert first.code == "SAR25_A.01.001"
    assert first.rate == Decimal("12.50")
    assert first.unit == "m2"
    assert first.labour_share_pct == Decimal("35.5")
    assert first.safety_amount == Decimal("0.12")
    assert first.chapters == [("SAR25_A.01", "Scavi e movimenti di terra")]
    assert first.description.startswith("Scavi e movimenti di terra - ")
    broken = rows[1]
    assert broken.rate is None and "broken_number:rate" in broken.flags
    assert skip_reason(broken) == "broken_rate"


# ── Mapping to cost items ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fixture", "name"),
    [
        ("toscana_firenze_2025.xml", "x.xml"),
        ("lombardia_2026.xml", "x.xml"),
        ("puglia_2026.csv", "x.csv"),
        ("campania_2024.csv", "x.csv"),
        ("veneto_2026.xml", "x.xml"),
    ],
)
def test_payload_never_sets_the_keys_the_boq_flow_turns_into_resources(fixture, name) -> None:
    from app.modules.costs.schemas import CostItemCreate

    plan, rows = _rows(_bytes(fixture), name)
    for row in rows:
        if skip_reason(row):
            continue
        payload = cost_item_payload(row, plan.source)
        for key in ("labor_cost", "material_cost", "equipment_cost", "labor_hours"):
            assert key not in payload["metadata"]
        assert payload["classification"] == {"voci": row.code}
        assert payload["currency"] == "EUR" and payload["source"] == "prezzario_regionale"
        block = payload["metadata"]["prezzario"]
        assert block["region_code"] == plan.source.region_code
        assert block["attribution"]
        if payload["components"]:
            assert _component_total(payload["components"]) == payload["rate"]
        CostItemCreate(**payload, region="Test")


def test_payload_carries_licence_attribution_and_shares_as_strings() -> None:
    plan, rows = _rows(_bytes("toscana_firenze_2025.xml"), "x.xml")
    payload = cost_item_payload(rows[0] if rows[0].components else next(r for r in rows if r.components), plan.source)
    block = payload["metadata"]["prezzario"]
    assert block["licence"] == "CC BY 3.0" and block["licence_stated_in"] == "file"
    assert block["edition"] == "2025" and block["area"] == "Provincia di Firenze"
    assert isinstance(block["labour_share_pct"], str)
    assert payload["descriptions"] == {"it": payload["description"]}


def test_safety_is_marked_from_the_chapter_title_too() -> None:
    plan, rows = _rows(_bytes("toscana_firenze_2025.xml"), "x.xml")
    safety = [cost_item_payload(r, plan.source) for r in rows if r.code.startswith("TOS25_17.")]
    assert safety and all(p["metadata"]["prezzario"]["safety"] for p in safety)


def test_preview_reports_counts_chapters_samples_and_the_suggested_name() -> None:
    preview = build_preview(_plan(_bytes("toscana_firenze_2025.xml"), "Firenze-2025.xml"))
    assert preview["counts"]["rows"] == 9 and preview["counts"]["importable"] == 9
    assert preview["counts"]["with_analysis"] == 6
    assert preview["counts"]["safety_rows"] == 2
    assert preview["source"]["suggested_catalog_name"] == "Toscana 2025 - Firenze"
    assert preview["source"]["licence"] == "CC BY 3.0"
    assert len(preview["sample_rows"]) == 8
    assert preview["chapter_count"] >= 3
    assert preview["warnings"] == []


def test_duplicate_codes_are_counted_once() -> None:
    text = _bytes("puglia_2026.csv").decode("utf-8")
    lines = text.splitlines()
    doubled = "\r\n".join([*lines, lines[2]]) + "\r\n"
    preview = build_preview(_plan(doubled.encode("utf-8"), "x.csv"))
    assert preview["counts"]["duplicates"] == 1
    assert preview["duplicate_examples"] == ["PUG2026/01.E01.001.001"]
    assert "duplicate_codes" in preview["warnings"]


def test_nothing_recognisable_is_refused_with_the_skipped_members() -> None:
    with pytest.raises(ContainerRefused) as info:
        _plan(_zip({"decreto.pdf": b"%PDF-1.4"}), "x.zip")
    assert info.value.code == "no_price_list_found"
    assert info.value.params["skipped"] == [{"name": "decreto.pdf", "reason": "not_a_price_list_file"}]


def test_an_xml_of_another_kind_is_not_taken_for_a_price_list() -> None:
    with pytest.raises(ContainerRefused) as info:
        _plan(b'<?xml version="1.0"?><rss><channel/></rss>', "feed.xml")
    assert info.value.code == "no_price_list_found"


def test_analysis_tables_beside_the_list_are_skipped() -> None:
    data = _zip(
        {
            "prezzario_llpp2024_articoli.csv": _bytes("campania_2024.csv"),
            "prezzario_llpp2024_analisi.csv": _bytes("campania_2024.csv"),
        }
    )
    plan = _plan(data, "campania.zip")
    assert [m.name for m in plan.members] == ["prezzario_llpp2024_articoli.csv"]
    assert plan.skipped == [{"name": "prezzario_llpp2024_analisi.csv", "reason": "analysis_table"}]


# ── XML safety and the ZIP guard ─────────────────────────────────────────────


def test_a_dtd_with_entities_is_refused_not_expanded() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE p [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
        b'<prezzario cod="2026"><settore cod="VEN26-01" desc="&b;"><capitolo cod="VEN26-01.02" desc="x">'
        b"</capitolo></settore></prezzario>"
    )
    plan = _plan(bomb, "x.xml")
    with pytest.raises(Exception, match="(?i)dtd|forbidden"):
        list(plan.rows())


def test_zip_member_compressed_beyond_any_price_list_is_refused() -> None:
    data = _zip({"lista.xml": b"<a>" + b"0" * (4 * 1024 * 1024) + b"</a>"})
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(data), "bomb.zip")
    assert info.value.code == "zip_ratio_suspicious"


def test_a_real_list_compressing_32_to_1_passes_the_ratio_guard() -> None:
    assert containers.MAX_MEMBER_RATIO > 32 * 4


def test_zip_with_too_many_members_is_refused() -> None:
    data = _zip({f"p{i}.csv": b"a;b\n" for i in range(containers.MAX_ZIP_MEMBERS + 1)}, zipfile.ZIP_STORED)
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(data), "many.zip")
    assert info.value.code == "zip_too_many_members"


def test_zip_inflating_past_the_budget_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(containers, "MAX_INFLATED_BYTES", 1000)
    data = _zip({"a.csv": b"x;" * 400, "b.csv": b"y;" * 400}, zipfile.ZIP_STORED)
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(data), "big.zip")
    assert info.value.code == "zip_too_large_inflated"


def _sheet_bomb() -> bytes:
    """A workbook-shaped archive whose one sheet inflates far past any real list."""
    return _zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "xl/worksheets/sheet1.xml": b"<worksheet>" + b"0" * (4 * 1024 * 1024) + b"</worksheet>",
        }
    )


def test_workbook_upload_is_held_to_the_zip_guard() -> None:
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(_sheet_bomb()), "prezzario.xlsx")
    assert info.value.code == "zip_ratio_suspicious"


def test_workbook_inside_a_zip_is_held_to_the_zip_guard() -> None:
    # Stored, so the outer archive sees one member at ratio 1 and passes it.
    data = _zip({"prezzario.xlsx": _sheet_bomb()}, zipfile.ZIP_STORED)
    with pytest.raises(ContainerRefused) as info:
        list(_plan(data, "prezzario.zip").rows())
    assert info.value.code == "zip_ratio_suspicious"


def test_encrypted_zip_is_refused() -> None:
    data = bytearray(_zip({"a.csv": b"a;b\n1;2\n"}, zipfile.ZIP_STORED))
    central = data.find(b"PK\x01\x02")
    flags = struct.unpack_from("<H", data, central + 8)[0]
    struct.pack_into("<H", data, central + 8, flags | 0x1)
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(bytes(data)), "locked.zip")
    assert info.value.code == "zip_encrypted"


def test_member_inflating_past_its_declared_size_is_stopped() -> None:
    reader = containers._CappedReader(io.BytesIO(b"x" * 5000), 1024, "lying.xml")
    with pytest.raises(ContainerRefused) as info:
        io.BufferedReader(reader).read()
    assert info.value.code == "zip_member_too_large"


def test_empty_and_oversized_uploads_are_refused(monkeypatch) -> None:
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(b""), "x.csv")
    assert info.value.code == "empty_file"
    monkeypatch.setattr(containers, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ContainerRefused) as info:
        open_members(io.BytesIO(b"x" * 11), "x.csv")
    assert info.value.code == "file_too_large"


def test_suggested_name_is_capped_at_the_region_tag_length() -> None:
    src = PriceListSource(format_id="x", region_code="TRE", edition="2025", area="Citta metropolitana di Qualcosa")
    assert len(src.suggested_catalog_name()) <= 50


# ── XPWE, registered beside the regional readers ────────────────────────────


@pytest.mark.parametrize("name", ["elenco.xpwe", "elenco.xml"])
def test_an_xpwe_price_list_is_read_without_any_wiring_of_its_own(name: str) -> None:
    from tests.fixtures import xpwe_builder

    plan = _plan(xpwe_builder.small_computo(), name)
    assert plan.format.format_id == "xpwe"
    rows = list(plan.rows())
    block = cost_item_payload(rows[0], plan.source)["metadata"]["prezzario"]
    # The material and equipment shares are kept beside labour, as strings.
    assert block["material_share_pct"] == "10"
    assert block["equipment_share_pct"] == "54.56"


def test_an_xpwe_too_large_to_read_whole_is_refused(monkeypatch) -> None:
    from app.modules.costs.pricelists import service
    from tests.fixtures import xpwe_builder

    monkeypatch.setattr(service, "_MAX_XPWE_BYTES", 100)
    plan = _plan(xpwe_builder.small_computo(), "elenco.xpwe")
    with pytest.raises(ContainerRefused) as info:
        list(plan.rows())
    assert info.value.code == "file_too_large"
