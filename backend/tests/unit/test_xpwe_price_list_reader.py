# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An XPWE export read as a price list: one cost-database row per ``EPItem``.

The rows come from the same streaming reader the bill import uses, so these
tests pin what the price-list side adds: the chapter path as (code, title)
pairs, shares in percent, the analysis lines as components, the safety flag,
and the region and edition read off a regional code prefix.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.xpwe import XpweDocument, stream_price_list
from app.modules.costs.pricelists import xpwe
from app.modules.costs.pricelists.base import BALANCE_NAME, PriceListSource
from tests.fixtures import xpwe_builder as fx


def _rows(content: bytes) -> tuple[list, PriceListSource]:
    source = PriceListSource(format_id=xpwe.FORMAT_ID)
    return list(xpwe.read(io.BytesIO(content), source)), source


def test_every_price_item_becomes_one_row_with_its_chapter_path() -> None:
    rows, source = _rows(fx.small_computo())
    by_code = {row.code: row for row in rows}
    assert list(by_code) == ["EX26_01.A03.001.001", "EX26_01.B02.004.002", "EX26_17.S01.001.001"]
    assert by_code["EX26_01.A03.001.001"].chapters == [("E", "OPERE EDILI"), ("E.01", "Demolizioni")]
    assert by_code["EX26_01.B02.004.002"].chapters == [
        ("E", "OPERE EDILI"),
        ("E.02", "Murature"),
        ("E.02.a", "Murature portanti"),
    ]
    assert by_code["EX26_17.S01.001.001"].chapters == [("S", "SICUREZZA")]
    assert source.title


def test_rates_units_and_shares_keep_their_decimals() -> None:
    rows, _source = _rows(fx.small_computo())
    by_code = {row.code: row for row in rows}
    demolition = by_code["EX26_01.A03.001.001"]
    assert demolition.rate == Decimal("13.63")
    assert (demolition.unit, demolition.source_unit) == ("m2", "mq")
    assert demolition.labour_share_pct == Decimal("35.44")
    assert demolition.safety_share_pct == Decimal("2.5")
    assert demolition.extra == {"material_share_pct": "10", "equipment_share_pct": "54.56"}
    masonry = by_code["EX26_01.B02.004.002"]
    assert masonry.rate == Decimal("48.20")
    assert masonry.labour_share_pct == Decimal("40.5")
    assert masonry.description.startswith("Muratura portante in blocchi")
    assert masonry.short_description == "Muratura in blocchi"


def test_analysis_lines_become_components_with_their_cost() -> None:
    rows, _source = _rows(fx.small_computo())
    components = rows[0].components
    # The analysis, then the general expenses and profit that bring it to the price.
    assert [c["name"] for c in components] == ["Operaio comune", "Escavatore con operatore", BALANCE_NAME]
    assert sum(c["cost"] for c in components) == pytest.approx(float(rows[0].rate))
    assert components[0]["unit"] == "hr"
    assert components[0]["quantity"] == pytest.approx(0.15)
    assert components[0]["unit_rate"] == pytest.approx(32.17)
    assert components[0]["cost"] == pytest.approx(0.15 * 32.17)


def test_a_safety_item_is_flagged() -> None:
    rows, _source = _rows(fx.small_computo())
    assert [row.safety for row in rows] == [False, False, True]


def test_an_unreadable_rate_is_flagged_not_guessed() -> None:
    content = fx.replaced("<Prezzo1>13.63</Prezzo1>", "<Prezzo1>a corpo</Prezzo1>")
    rows, _source = _rows(content)
    assert rows[0].rate is None
    assert rows[0].flags == ["broken_number:rate"]


def test_a_regional_code_prefix_names_region_and_edition() -> None:
    content = fx.small_computo().replace(b"EX26_", b"TOS26_")
    _rows_read, source = _rows(content)
    assert (source.region_code, source.edition, source.detected_from) == ("TOS", "2026", "code_prefix")


def test_a_generated_price_list_export_reads_every_item() -> None:
    rows, _source = _rows(fx.price_list(25, analysis_lines=3))
    assert len(rows) == 25
    for row in rows:
        if "analysis_exceeds_price" in row.flags:
            assert row.components == [] and len(row.extra["analysis"]) == 3
        else:
            assert len(row.components) == 4 and row.components[-1]["name"] == BALANCE_NAME
    assert all(row.rate is not None and row.rate > 0 for row in rows)


def test_sniff_reads_the_root_element_not_the_file_name() -> None:
    assert xpwe.sniff(fx.small_computo()[:4096], "anything.xml")
    assert not xpwe.sniff(b'<?xml version="1.0"?><PREZZARIO/>', "list.xpwe")


def test_a_document_with_a_dtd_is_refused() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aa">]><PweDocumento>&a;</PweDocumento>'
    with pytest.raises(ImporterParseError):
        _rows(bomb)


def test_every_row_becomes_a_cost_item_the_schema_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rows go through the price-list service exactly as a registered format's would."""
    from app.modules.costs.pricelists import service
    from app.modules.costs.schemas import CostItemCreate

    fmt = service._Format(xpwe.FORMAT_ID, 0, xpwe.sniff, service._xml(xpwe.read), (".xpwe", ".xml"))
    others = tuple(f for f in service._FORMATS if f.format_id != xpwe.FORMAT_ID)
    monkeypatch.setattr(service, "_FORMATS", (fmt, *others))

    plan = service.plan_upload(io.BytesIO(fx.small_computo()), "elenco.xml")
    assert plan.format.format_id == xpwe.FORMAT_ID
    rows = list(plan.rows())
    assert [service.skip_reason(row) for row in rows] == [None, None, None]
    items = [CostItemCreate(**service.cost_item_payload(row, plan.source), region="Elenco prezzi") for row in rows]
    by_code = {item.code: item for item in items}
    demolition = by_code["EX26_01.A03.001.001"]
    assert demolition.rate == Decimal("13.63")
    assert demolition.classification == {"voci": "EX26_01.A03.001.001"}
    assert len(demolition.components) == 3
    assert sum(c["cost"] for c in demolition.components) == pytest.approx(13.63)
    block = demolition.metadata["prezzario"]
    assert block["chapters"] == [{"code": "E", "title": "OPERE EDILI"}, {"code": "E.01", "title": "Demolizioni"}]
    assert block["labour_share_pct"] == "35.44"
    assert by_code["EX26_17.S01.001.001"].metadata["prezzario"]["safety"] is True


def test_an_analysis_line_naming_a_later_item_still_carries_its_code() -> None:
    content = fx.replaced(
        "<IDEP>0</IDEP><Descrizione>Operaio comune</Descrizione>",
        "<IDEP>3</IDEP><Descrizione>Operaio comune</Descrizione>",
    )
    rows, _source = _rows(content)
    assert sorted(row.code for row in rows) == ["EX26_01.A03.001.001", "EX26_01.B02.004.002", "EX26_17.S01.001.001"]
    demolition = next(row for row in rows if row.code == "EX26_01.A03.001.001")
    assert demolition.components[0]["code"] == "EX26_17.S01.001.001"


def test_items_read_before_the_chapter_tree_still_get_their_chapters() -> None:
    text = fx.small_computo().decode("utf-8")
    head, rest = text.split("<PweDatiGenerali>", 1)
    general, rest = rest.split("</PweDatiGenerali>", 1)
    measured, tail = rest.split("</PweMisurazioni>", 1)
    reordered = head + measured + "</PweMisurazioni><PweDatiGenerali>" + general + "</PweDatiGenerali>" + tail
    assert reordered.index("<EPItem") < reordered.index("<PweDGCapitoliCategorie")
    rows, source = _rows(reordered.encode("utf-8"))
    by_code = {row.code: row for row in rows}
    assert by_code["EX26_01.A03.001.001"].chapters == [("E", "OPERE EDILI"), ("E.01", "Demolizioni")]
    assert source.title


def test_the_list_is_streamed_not_collected() -> None:
    doc = XpweDocument()
    items = stream_price_list(fx.price_list(5), doc)
    first = next(items)
    assert first.code
    assert doc.price_items == {}
    assert len([first, *items]) == 5
