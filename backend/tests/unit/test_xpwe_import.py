# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An XPWE (Italian estimating XML) bill imports with its hierarchy, its libretto and its money intact.

The fixture is described in :mod:`tests.fixtures.xpwe_builder`. Each item of it
has a row only one rule gets right, so a test failing names the rule.
"""

from __future__ import annotations

import asyncio
import tracemalloc
from collections.abc import Callable
from decimal import Decimal

import pytest

from app.modules.boq.importers import REGISTERED_IMPORTERS, ImportedBOQ, ImporterParseError
from app.modules.boq.importers.xpwe import (
    XpweDocument,
    XpweImporter,
    XpweNativeFileError,
    build_imported_boq,
    plain_decimal,
    read_xpwe,
    stream_price_list,
)
from tests.fixtures import xpwe_builder as fx


def _parse(content: bytes):
    return asyncio.run(XpweImporter.parse(content, locale="en"))


def _claimed_by(content: bytes, name: str) -> str | None:
    for importer in REGISTERED_IMPORTERS:
        if importer.detect(content[:4096], name):
            return importer.format_id
    return None


def _by_ordinal(result):
    return {p.ordinal: p for p in result.positions}


# ── Detection ────────────────────────────────────────────────────────────────


def test_the_dispatcher_hands_an_xpwe_file_to_the_xpwe_importer() -> None:
    assert _claimed_by(fx.small_computo(), "computo.xpwe") == "xpwe"
    assert _claimed_by(fx.small_computo(), "COMPUTO.XPWE") == "xpwe"


def test_an_xml_named_export_is_recognised_by_its_root_element_not_by_a_vendor_mark() -> None:
    assert b"PweDocumento" in fx.small_computo()[:200]
    assert _claimed_by(fx.small_computo(), "computo.xml") == "xpwe"


def test_other_xml_is_left_to_the_importers_that_own_it() -> None:
    gaeb = b'<?xml version="1.0"?><GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407"><GAEBInfo/></GAEB>'
    assert _claimed_by(gaeb, "lv.xml") == "gaeb_xml"
    assert _claimed_by(b"<?xml version='1.0'?><not-xpwe/>", "other.xml") is None


def test_the_native_project_file_and_the_legacy_name_are_claimed_so_they_can_be_refused() -> None:
    native = b"AAMVHFSS\x00\x01\x02\x03" + bytes(range(256))
    assert _claimed_by(native, "progetto.dcf") == "xpwe"
    assert _claimed_by(native, "progetto.pwe") == "xpwe"


def test_the_xpwe_importer_runs_before_the_spreadsheet_catch_all() -> None:
    ids = [imp.format_id for imp in REGISTERED_IMPORTERS]
    assert ids.index("xpwe") < ids.index("excel")


@pytest.mark.parametrize("name", ["progetto.dcf", "progetto.pwe", "computo.xpwe"])
def test_a_file_that_is_not_xml_is_refused_with_what_to_do(name: str) -> None:
    native = b"AAMVHFSS\x00\x01\x02\x03" + bytes(range(256))
    assert XpweImporter.detect(native, name)
    with pytest.raises(ImporterParseError) as caught:
        _parse(native)
    assert "XPWE" in str(caught.value)
    with pytest.raises(XpweNativeFileError):
        read_xpwe(native)


def test_a_legacy_name_carrying_the_same_xml_is_read() -> None:
    result = _parse(fx.small_computo())
    assert result.positions
    assert XpweImporter.detect(fx.small_computo(), "computo.pwe")


def test_xml_with_another_root_is_refused_by_name() -> None:
    with pytest.raises(ImporterParseError, match="not an XPWE document"):
        _parse(b"<?xml version='1.0'?><Prezzario><voce/></Prezzario>")


# ── Hierarchy ────────────────────────────────────────────────────────────────


def test_sections_come_from_the_bill_tree_with_dotted_ordinals_before_their_children() -> None:
    result = _parse(fx.small_computo())
    layout = [(p.ordinal, p.is_section, p.description[:20]) for p in result.positions]
    assert layout == [
        ("1", True, "Piano terra"),
        ("1.1", True, "Demolizioni"),
        ("1.1.1", False, "Demolizione totale d"),
        ("1.2", True, "Murature"),
        ("1.2.1", False, "Muratura portante in"),
        ("2", True, "Piano primo"),
        ("2.1", True, "Murature"),
        ("2.1.1", False, "Muratura portante in"),
        ("2.2", True, "Ala nord"),
        ("2.2.1", False, "Recinzione provvisor"),
        ("3", False, "Demolizione totale d"),
    ]
    assert result.metadata["xpwe_grouping"] == "categories"
    assert result.metadata["xpwe_sections"] == 6
    assert result.metadata["xpwe_items"] == 5


def test_every_item_names_its_section_and_keeps_its_place_in_the_file() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["1.1.1"].metadata["import_section"] == "1.1"
    assert rows["2.2.1"].metadata["import_section"] == "2.2"
    assert rows["3"].metadata["import_section"] == ""
    assert [rows[o].metadata["xpwe_order"] for o in ("1.1.1", "1.2.1", "2.2.1", "2.1.1", "3")] == [1, 2, 3, 4, 5]


def test_the_two_halves_of_the_file_come_in_either_order() -> None:
    first = _parse(fx.small_computo())
    second = _parse(fx.price_list_first())
    shape = [(p.ordinal, p.description, p.quantity, p.unit_rate) for p in first.positions]
    assert shape == [(p.ordinal, p.description, p.quantity, p.unit_rate) for p in second.positions]


def test_a_bill_without_categories_is_laid_out_by_the_price_list_chapters() -> None:
    content = fx.small_computo()
    for tag in ("IDSpCat", "IDCat", "IDSbCat"):
        for value in ("1", "2"):
            content = content.replace(f"<{tag}>{value}</{tag}>".encode(), f"<{tag}>0</{tag}>".encode())
    result = _parse(content)
    assert result.metadata["xpwe_grouping"] == "chapters"
    sections = [p.description for p in result.positions if p.is_section]
    assert sections[:2] == ["OPERE EDILI", "Demolizioni"]


# ── Quantities and the libretto ──────────────────────────────────────────────


def test_quantities_are_computed_from_the_measurement_rows() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["1.1.1"].quantity == pytest.approx(49.11)
    assert rows["1.2.1"].quantity == pytest.approx(12.0)
    assert rows["2.2.1"].quantity == pytest.approx(1.0)
    assert rows["3"].quantity == pytest.approx(10.0)


def test_a_printed_partial_subtotal_is_not_added_to_the_item() -> None:
    """Item 4's subtotal row repeats 24 in ``Quantita``; summing that field would give 48."""
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["2.1.1"].quantity == pytest.approx(24.0)
    subtotal = rows["2.1.1"].metadata["measurement"]["lines"][1]
    assert subtotal["xpwe_subtotal"] is True
    assert subtotal["formula"] == "0"


def test_a_see_item_row_is_flattened_to_the_quantity_it_repeats_and_said_so() -> None:
    result = _parse(fx.small_computo())
    rows = _by_ordinal(result)
    line = rows["2.1.1"].metadata["measurement"]["lines"][0]
    assert line["xpwe_see_item"] == "2"
    assert line["formula"] == "12 * 2"
    flattened = [w for w in result.warnings if w["code"] == "xpwe_see_item_flattened"]
    assert len(flattened) == 1
    assert flattened[0]["ordinal"] == "2.1.1"
    assert flattened[0]["ref"] == "1.2.1"


def test_the_libretto_is_stored_the_way_the_measurement_sheet_reads_it() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    measurement = rows["1.1.1"].metadata["measurement"]
    assert measurement["source"] == "xpwe"
    assert measurement["unit"] == "m2"
    plain, expression, deduction, note = measurement["lines"]
    assert (plain["factor"], plain["variables"], plain["formula"], plain["sign"]) == (
        "2",
        {"L": "5", "H": "3"},
        "L * H",
        "+",
    )
    assert expression["formula"] == "(2*(3+4)) * 1.5"
    assert (deduction["variables"], deduction["sign"]) == ({"L": "0.90", "H": "2.10"}, "-")
    assert (note["description"], note["formula"]) == ("Lato cortile", "0")


@pytest.mark.parametrize("ordinal", ["1.1.1", "1.2.1", "2.1.1", "3"])
def test_the_stored_libretto_totals_to_the_imported_quantity(ordinal: str) -> None:
    """What the measurement drawer recomputes on open must equal the position quantity."""
    from app.modules.measurement import build_sheet

    position = _by_ordinal(_parse(fx.small_computo()))[ordinal]
    lines = position.metadata["measurement"]["lines"]
    sheet = build_sheet(item_ref=ordinal, description="", unit=position.unit, lines=lines, strict=True)
    assert sheet.total_quantity == Decimal(str(position.quantity))


def test_a_difference_from_the_declared_quantity_is_reported_and_the_measured_one_kept() -> None:
    content = fx.replaced("<Quantita>12.00</Quantita><DataMis>", "<Quantita>13.00</Quantita><DataMis>")
    result = _parse(content)
    assert _by_ordinal(result)["1.2.1"].quantity == pytest.approx(12.0)
    mismatch = [w for w in result.warnings if w["code"] == "xpwe_quantity_mismatch"]
    assert len(mismatch) == 1
    assert (mismatch[0]["ordinal"], mismatch[0]["computed"], mismatch[0]["declared"]) == ("1.2.1", 12.0, 13.0)


def test_the_unmodified_fixture_reports_no_mismatch() -> None:
    result = _parse(fx.small_computo())
    assert not [w for w in result.warnings if w["code"] == "xpwe_quantity_mismatch"]


_VC2_ROW = (
    '<RGItem ID="5"><IDVV>-2</IDVV><Descrizione>Muro di spina</Descrizione><PartiUguali>3</PartiUguali>'
    "<Lunghezza>4.00</Lunghezza><Larghezza></Larghezza><HPeso></HPeso><Quantita>12.00</Quantita>"
    "<Flags>0</Flags></RGItem>"
)


def _item_two(rows: list[tuple[str, str, str]], declared: str, *, decimals: str | None = "10.2|0") -> bytes:
    """The small bill with item 2's rows and declared quantity replaced.

    Each row is (PartiUguali, Lunghezza, HPeso); ``decimals`` replaces the
    Quantita rounding the file declares, ``None`` removes it.
    """
    xml = "".join(
        f'<RGItem ID="{50 + n}"><IDVV>-2</IDVV><Descrizione>Riga {n}</Descrizione><PartiUguali>{parts}</PartiUguali>'
        f"<Lunghezza>{length}</Lunghezza><Larghezza></Larghezza><HPeso>{height}</HPeso><Quantita></Quantita>"
        "<Flags>0</Flags></RGItem>"
        for n, (parts, length, height) in enumerate(rows)
    )
    content = fx.replaced(_VC2_ROW, xml)
    content = fx.replaced(
        "<Quantita>12.00</Quantita><DataMis>", f"<Quantita>{declared}</Quantita><DataMis>", source=content
    )
    replacement = f"<Quantita>{decimals}</Quantita>" if decimals is not None else "<Quantita></Quantita>"
    return fx.replaced("<Quantita>10.2|0</Quantita>", replacement, source=content)


def _reconciles(position) -> bool:
    """What the measurement GET answers for the stored sheet of ``position``."""
    from app.modules.measurement import build_sheet, reconcile

    stored = position.metadata["measurement"]
    sheet = build_sheet(
        item_ref=position.ordinal,
        description="",
        unit=position.unit,
        lines=stored["lines"],
        strict=False,
        row_decimals=stored.get("row_decimals"),
    )
    return reconcile(sheet, position.quantity)["matches"]


def _mismatches(result) -> list[dict]:
    """Item 2's own mismatch notes (item 4 repeats item 2's quantity and may differ on its own)."""
    return [w for w in result.warnings if w["code"] == "xpwe_quantity_mismatch" and w["ordinal"] == "1.2.1"]


def test_rows_are_rounded_one_by_one_as_the_file_declares_so_ten_ties_add_up() -> None:
    result = _parse(_item_two([("", "1.005", "")] * 10, "10.10"))
    position = _by_ordinal(result)["1.2.1"]
    assert Decimal(str(position.quantity)) == Decimal("10.10")
    assert _mismatches(result) == []
    assert _reconciles(position)


def test_a_product_row_is_rounded_after_multiplying() -> None:
    result = _parse(_item_two([("", "2.011", "0.5")] * 2, "2.02"))
    position = _by_ordinal(result)["1.2.1"]
    assert Decimal(str(position.quantity)) == Decimal("2.02")
    assert _mismatches(result) == []
    assert _reconciles(position)


def test_a_rounded_formula_row_keeps_its_formula_and_the_sheet_rounds_it() -> None:
    result = _parse(_item_two([("", "10/3", "")], "3.33"))
    position = _by_ordinal(result)["1.2.1"]
    assert Decimal(str(position.quantity)) == Decimal("3.33")
    assert _reconciles(position), "a clean import must reconcile with its own sheet"
    stored = position.metadata["measurement"]
    assert stored["row_decimals"] == 2
    [line] = stored["lines"]
    assert line["formula"] == "(10/3)"
    assert "xpwe_unrounded" not in line


def test_a_rounded_product_row_keeps_its_dimensions_editable() -> None:
    result = _parse(_item_two([("", "2.011", "0.5")] * 2, "2.02"))
    stored = _by_ordinal(result)["1.2.1"].metadata["measurement"]
    assert [(line["variables"], line["formula"]) for line in stored["lines"]] == [
        ({"L": "2.011", "H": "0.5"}, "L * H")
    ] * 2
    assert stored["row_decimals"] == 2


def test_a_row_rounding_to_itself_keeps_its_dimensions_editable() -> None:
    result = _parse(_item_two([("3", "4.00", "")], "12.00"))
    line = _by_ordinal(result)["1.2.1"].metadata["measurement"]["lines"][0]
    assert (line["factor"], line["variables"], line["formula"]) == ("3", {"L": "4"}, "L")
    assert "xpwe_unrounded" not in line


def test_a_file_declaring_no_rounding_leaves_the_sheet_unrounded() -> None:
    result = _parse(_item_two([("", "10/3", "")], "3.33", decimals=None))
    assert "row_decimals" not in _by_ordinal(result)["1.2.1"].metadata["measurement"]


def test_a_difference_of_one_quantum_is_reported_with_the_value_kept() -> None:
    result = _parse(_item_two([("3", "4.00", "")], "12.01"))
    position = _by_ordinal(result)["1.2.1"]
    assert Decimal(str(position.quantity)) == Decimal("12.00")
    [warning] = _mismatches(result)
    assert (warning["computed"], warning["declared"], warning["kept"]) == (12.0, 12.01, "measured")


def test_drift_over_many_rows_is_not_hidden_by_the_row_count() -> None:
    # Twenty rows of 1.00 against a declared 20.10: the old tolerance (one
    # quantum per row, 0.20) let the 0.10 difference through unreported.
    result = _parse(_item_two([("", "1.00", "")] * 20, "20.10"))
    assert len(_mismatches(result)) == 1


def test_without_declared_decimals_a_rounded_declaration_is_not_taken_on_trust() -> None:
    result = _parse(_item_two([("", "10/3", "")], "3.33", decimals=None))
    [warning] = _mismatches(result)
    assert warning["kept"] == "measured"
    assert _reconciles(_by_ordinal(result)["1.2.1"])


def test_an_unreadable_factor_counts_as_zero_with_a_warning_naming_it() -> None:
    content = fx.replaced("<Lunghezza>4.00</Lunghezza>", "<Lunghezza>4.00+sqrt(2)</Lunghezza>")
    result = _parse(content)
    assert _by_ordinal(result)["1.2.1"].quantity == pytest.approx(0.0)
    unreadable = [w for w in result.warnings if w["code"] == "xpwe_expression_unreadable"]
    assert [w["text"] for w in unreadable] == ["4.00+sqrt(2)"]


def test_a_power_is_not_evaluated() -> None:
    """``**`` would let a file ask for a number with a hundred million digits."""
    content = fx.replaced("<Lunghezza>4.00</Lunghezza>", "<Lunghezza>10**99999999</Lunghezza>")
    result = _parse(content)
    assert [w["code"] for w in result.warnings if w["code"] == "xpwe_expression_unreadable"] == [
        "xpwe_expression_unreadable"
    ]


# ── One bad row or item does not cost the whole file ────────────────────────


def _by_vc_id(result) -> dict[str, object]:
    return {p.metadata["xpwe_vc_id"]: p for p in result.positions if not p.is_section}


def _codes(result) -> list[str]:
    return [w["code"] for w in result.warnings] + [e.get("code", "") for e in result.errors]


def test_a_see_item_chain_hundreds_deep_is_followed_to_its_end() -> None:
    """A chain of 400 "see item" rows used to exhaust the call stack and lose the whole file."""
    result = _parse(fx.chained_bill(400))
    items = _by_vc_id(result)
    assert len(items) == 400
    assert Decimal(str(items["1"].quantity)) == Decimal(6 + 399)
    assert Decimal(str(items["400"].quantity)) == Decimal(6)
    assert "xpwe_see_item_unresolved" not in _codes(result)


def test_a_see_item_cycle_still_counts_as_unresolved() -> None:
    content = fx.chained_bill(3).replace(b"<IDVV>-2</IDVV><Descrizione>Parete", b"<IDVV>1</IDVV><Descrizione>Parete")
    result = _parse(content)
    assert len(_by_vc_id(result)) == 3
    assert "xpwe_see_item_unresolved" in _codes(result)


@pytest.mark.parametrize(
    "factor",
    [
        pytest.param("10**999999", id="power"),
        pytest.param("10 * * 3", id="spaced-power"),
        pytest.param("1/0", id="division-by-zero"),
    ],
)
def test_a_factor_that_cannot_be_evaluated_costs_only_its_row(factor: str) -> None:
    content = fx.replaced("<Lunghezza>4.00</Lunghezza>", f"<Lunghezza>{factor}</Lunghezza>")
    result = _parse(content)
    rows = _by_ordinal(result)
    assert rows["1.2.1"].quantity == pytest.approx(0.0)
    assert rows["1.1.1"].quantity == pytest.approx(49.11)
    assert "xpwe_expression_unreadable" in _codes(result)


@pytest.mark.parametrize(
    ("parts", "length"),
    [
        pytest.param("999999999999", "999999999999", id="product"),
        pytest.param("", "99999999999999999999999999999999", id="one-long-number"),
    ],
)
def test_a_measurement_beyond_any_real_quantity_is_refused_for_its_row(parts: str, length: str) -> None:
    content = fx.replaced(
        "<PartiUguali>3</PartiUguali><Lunghezza>4.00</Lunghezza>",
        f"<PartiUguali>{parts}</PartiUguali><Lunghezza>{length}</Lunghezza>",
    )
    result = _parse(content)
    rows = _by_ordinal(result)
    assert rows["1.2.1"].quantity == pytest.approx(0.0)
    assert rows["1.1.1"].quantity == pytest.approx(49.11)
    [note] = [w for w in result.warnings if w["code"] == "xpwe_measurement_out_of_range"]
    assert note["ordinal"] == "1.2.1"


def test_a_declared_quantity_beyond_any_real_one_refuses_only_its_item() -> None:
    content = fx.replaced("<Quantita>1.00</Quantita><DataMis>", "<Quantita>1" + "0" * 40 + "</Quantita><DataMis>")
    result = _parse(content)
    errors = [e for e in result.errors if e["code"] == "xpwe_quantity_out_of_range"]
    assert len(errors) == 1
    assert errors[0]["ordinal"] not in _by_ordinal(result)
    assert _by_ordinal(result)["1.1.1"].quantity == pytest.approx(49.11)


def test_an_arithmetic_failure_while_shaping_an_item_refuses_only_that_item(monkeypatch) -> None:
    from decimal import InvalidOperation

    from app.modules.boq.importers import xpwe

    real = xpwe._mismatch_tolerance

    def failing(quantum, declared):
        if declared == Decimal("12.00"):
            raise InvalidOperation
        return real(quantum, declared)

    monkeypatch.setattr(xpwe, "_mismatch_tolerance", failing)
    result = _parse(fx.small_computo())
    [error] = [e for e in result.errors if e["code"] == "xpwe_item_failed"]
    assert error["ordinal"] == "1.2.1"
    assert "1.2.1" not in _by_ordinal(result)
    assert _by_ordinal(result)["1.1.1"].quantity == pytest.approx(49.11)


def test_an_item_that_fails_mid_chain_leaves_the_rest_of_the_chain_measurable(monkeypatch) -> None:
    """Item 2 of a three-item chain fails; item 3, reached through it, is still measured on its own."""
    from decimal import InvalidOperation

    from app.modules.boq.importers import xpwe

    real = xpwe._Measurer._measure

    def failing(self, item):
        if item.id == "2":
            raise InvalidOperation
        return real(self, item)

    monkeypatch.setattr(xpwe._Measurer, "_measure", failing)
    result = _parse(fx.chained_bill(3))
    failed = sorted(e["ordinal"] for e in result.errors if e["code"] == "xpwe_item_failed")
    assert len(failed) == 2, result.errors  # items 1 and 2; item 1 needs item 2
    third = next(p for p in result.positions if p.metadata.get("xpwe_vc_id") == "3")
    assert Decimal(str(third.quantity)) == Decimal(6)


def _duplicated_ids() -> bytes:
    """Three items where the second reuses the first one's ID and the third repeats "item 1".

    Item 1 measures 2 x 3 + 3 x 1.5 = 10.5, the duplicate 4 x 3 + 4.5 = 16.5,
    so the third item's "see item 1" row tells which one it followed.
    """
    content = fx.measured_bill(3, categories=1)
    content = content.replace(b'<VCItem ID="2">', b'<VCItem ID="1">')
    content = content.replace(
        b"<Descrizione>Parete 2</Descrizione><PartiUguali>2</PartiUguali>",
        b"<Descrizione>Parete 2</Descrizione><PartiUguali>4</PartiUguali>",
    )
    return content.replace(
        b'<RGItem ID="6"><IDVV>-2</IDVV><Descrizione>Parete 3</Descrizione><PartiUguali>2</PartiUguali>'
        b"<Lunghezza>3</Lunghezza>",
        b'<RGItem ID="6"><IDVV>1</IDVV><Descrizione>Parete 3</Descrizione><PartiUguali></PartiUguali>'
        b"<Lunghezza></Lunghezza>",
    )


def test_two_items_sharing_an_id_are_both_imported_and_the_clash_is_noted() -> None:
    result = _parse(_duplicated_ids())
    items = [p for p in result.positions if not p.is_section]
    assert sorted(Decimal(str(p.quantity)) for p in items) == [Decimal("10.5"), Decimal("15"), Decimal("16.5")]
    [note] = [w for w in result.warnings if w["code"] == "xpwe_duplicate_item_id"]
    assert note["ref"] == "1"
    assert note["ordinal"] in {p.ordinal for p in items}


def test_a_see_item_row_naming_a_shared_id_follows_the_first_item() -> None:
    result = _parse(_duplicated_ids())
    third = next(p for p in result.positions if p.metadata.get("xpwe_order") == 3)
    # 10.5 from item 1 (the duplicate would give 16.5) plus the 4.5 slab row.
    assert Decimal(str(third.quantity)) == Decimal("15")


# ── Money, units, safety and shares ─────────────────────────────────────────


def test_prices_read_with_a_decimal_comma_or_point_and_keep_their_exact_text() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["1.2.1"].unit_rate == pytest.approx(48.2)
    assert rows["1.2.1"].metadata["xpwe_unit_rate"] == "48.20"
    assert rows["1.1.1"].metadata["xpwe_unit_rate"] == "13.63"
    assert Decimal(str(rows["1.1.1"].unit_rate)) == Decimal("13.63")


def test_italian_units_are_folded_onto_the_canonical_ones_and_the_original_is_kept() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert (rows["1.1.1"].unit, rows["1.1.1"].metadata["xpwe_unit_raw"]) == ("m2", "mq")
    assert (rows["1.2.1"].unit, rows["1.2.1"].metadata["xpwe_unit_raw"]) == ("m2", "m²")
    assert (rows["2.2.1"].unit, rows["2.2.1"].metadata["xpwe_unit_raw"]) == ("pcs", "cad")


def test_a_safety_item_is_classified_as_a_safety_cost() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["2.2.1"].classification == {
        "code": "EX26_17.S01.001.001",
        "voci": "EX26_17.S01.001.001",
        "cost_type": "sicurezza",
    }
    assert rows["2.2.1"].metadata["safety_item"] is True
    assert "cost_type" not in rows["1.1.1"].classification


def test_labour_safety_material_and_equipment_shares_travel_as_fractions() -> None:
    rows = _by_ordinal(_parse(fx.small_computo()))
    assert rows["1.1.1"].metadata["cost_shares"] == {
        "labour": "0.3544",
        "safety": "0.025",
        "material": "0.1",
        "equipment": "0.5456",
    }
    assert rows["1.2.1"].metadata["cost_shares"]["labour"] == "0.405"


def test_project_header_and_currency_are_carried() -> None:
    result = _parse(fx.small_computo())
    assert result.currency == "EUR"
    assert result.source_format == "xpwe"
    assert result.metadata["xpwe_title"] == "Ristrutturazione della scuola elementare"
    assert result.metadata["xpwe_municipality"] == "Comune di Esempio"
    assert result.metadata["measurement_rows"] == 8


def test_an_item_naming_a_missing_price_item_is_an_error_and_the_rest_imports() -> None:
    content = fx.replaced('<VCItem ID="5"><IDEP>1</IDEP>', '<VCItem ID="5"><IDEP>99</IDEP>')
    result = _parse(content)
    assert [e["code"] for e in result.errors] == ["xpwe_price_item_missing"]
    assert result.errors[0]["ordinal"] == "3"
    assert len([p for p in result.positions if not p.is_section]) == 4


# ── Deductions ───────────────────────────────────────────────────────────────


def _items(result) -> dict[str, object]:
    return {p.metadata["xpwe_vc_id"]: p for p in result.positions if not p.is_section}


def test_a_negatively_measured_item_is_a_deduction_line_its_amount_moved_to_the_bills_deductions() -> None:
    result = _parse(fx.deductions_bill())
    item = _items(result)["5"]
    assert result.errors == []
    assert item.quantity == 10.0
    assert item.unit_rate == 0.0, "the line adds nothing; its amount is taken off by the deductions line"
    assert item.metadata["deduction"] is True
    assert Decimal(item.metadata["deduction_amount"]) == Decimal("-136.30")
    assert Decimal(item.metadata["deduction_quantity"]) == Decimal("-10")
    assert Decimal(item.metadata["deduction_unit_rate"]) == Decimal("13.63")


def test_a_deduction_lines_sheet_still_adds_up_to_its_quantity_with_the_rows_typed_sign_kept() -> None:
    item = _items(_parse(fx.deductions_bill()))["5"]
    lines = item.metadata["measurement"]["lines"]
    assert [(line["sign"], line["xpwe_sign"]) for line in lines] == [("+", "-")]
    assert lines[0]["variables"] == {"L": "10"}
    assert _reconciles(item)


def test_a_credit_priced_item_is_a_deduction_line_too() -> None:
    item = _items(_parse(fx.deductions_bill()))["6"]
    assert (item.quantity, item.unit_rate) == (2.0, 0.0)
    assert item.metadata["deduction"] is True
    assert Decimal(item.metadata["deduction_amount"]) == Decimal("-100")
    assert Decimal(item.metadata["deduction_unit_rate"]) == Decimal("-50")
    assert item.metadata["xpwe_unit_rate"] == "-50.00"


def test_the_bill_plus_its_deductions_is_the_files_own_total() -> None:
    result = _parse(fx.deductions_bill())
    work = sum(
        (Decimal(str(p.quantity)) * Decimal(str(p.unit_rate)) for p in result.positions if not p.is_section),
        Decimal(0),
    )
    deductions = result.metadata["deductions"]
    assert deductions["count"] == 2
    assert Decimal(deductions["amount"]) == Decimal("-236.30")
    assert work + Decimal(deductions["amount"]) == Decimal("2418.2693")


def test_the_report_says_how_many_lines_were_moved_into_the_deductions_and_by_how_much() -> None:
    notes = [w for w in _parse(fx.deductions_bill()).warnings if w["code"] == "xpwe_deductions_moved"]
    assert len(notes) == 1
    assert notes[0]["count"] == 2
    assert Decimal(str(notes[0]["amount"])) == Decimal("-236.30")


def test_two_minuses_that_cancel_add_money_and_are_not_a_deduction() -> None:
    result = _parse(fx.deductions_bill(credit_quantity="-2.00"))
    item = _items(result)["6"]
    assert (item.quantity, item.unit_rate) == (2.0, 50.0)
    assert "deduction" not in item.metadata
    assert [w["ordinal"] for w in result.warnings if w["code"] == "xpwe_signs_cancel"] == [item.ordinal]
    assert result.metadata["deductions"]["count"] == 1


def test_a_bill_without_deductions_says_nothing_about_them() -> None:
    result = _parse(fx.small_computo())
    assert "deductions" not in result.metadata
    assert not [w for w in result.warnings if w["code"] == "xpwe_deductions_moved"]


def test_a_long_description_is_cut_to_what_a_position_holds_and_kept_whole_in_metadata() -> None:
    long_text = "Muratura " * 700
    content = fx.replaced(
        "<DesEstesa>Muratura portante in blocchi di laterizio porizzato, spessore 30 cm, con malta cementizia.</DesEstesa>",
        f"<DesEstesa>{long_text}</DesEstesa>",
    )
    position = _by_ordinal(_parse(content))["1.2.1"]
    assert len(position.description) <= 5000
    assert position.metadata["description_full"] == long_text.strip()


# ── Encoding and hostile input ───────────────────────────────────────────────


def test_a_windows_code_page_file_with_no_declaration_reads_its_accents() -> None:
    result = _parse(fx.cp1252_bill())
    lines = _by_ordinal(result)["1.1.1"].metadata["measurement"]["lines"]
    assert lines[0]["description"] == "Pareti della città vecchia"
    assert result.metadata["xpwe_encoding"] == "cp1252"
    assert [w["code"] for w in result.warnings if w["code"] == "xpwe_encoding_fallback"] == ["xpwe_encoding_fallback"]


def test_an_external_entity_is_refused() -> None:
    hostile = (
        b'<?xml version="1.0"?><!DOCTYPE PweDocumento [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<PweDocumento><PweDatiGenerali><PweDGProgetto><PweDGDatiGenerali><Oggetto>&x;</Oggetto>"
        b"</PweDGDatiGenerali></PweDGProgetto></PweDatiGenerali></PweDocumento>"
    )
    with pytest.raises(ImporterParseError, match="DTD or entities"):
        _parse(hostile)


def test_an_entity_expansion_bomb_is_refused() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE PweDocumento [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        b"<PweDocumento><CopyRight>&c;</CopyRight></PweDocumento>"
    )
    with pytest.raises(ImporterParseError, match="DTD or entities"):
        _parse(bomb)


def test_malformed_xml_is_a_parse_error_not_a_crash() -> None:
    with pytest.raises(ImporterParseError, match="not well-formed"):
        _parse(b"<PweDocumento><PweMisurazioni></PweDocumento>")


def test_plain_decimal_reads_both_separators_and_refuses_text() -> None:
    assert plain_decimal("1,5") == Decimal("1.5")
    assert plain_decimal("1.234,56") == Decimal("1234.56")
    assert plain_decimal("1,234.56") == Decimal("1234.56")
    assert plain_decimal("") is None
    with pytest.raises(ValueError):
        plain_decimal("12 euro")


# ── Price list only ──────────────────────────────────────────────────────────


def test_a_price_list_export_is_read_with_its_chapters_and_analysis() -> None:
    doc = read_xpwe(fx.small_computo(), price_list_only=True)
    assert doc.work_items == []
    masonry = doc.price_items["2"]
    assert [(g.code, g.title) for g in doc.chapter_path(masonry)] == [
        ("E", "OPERE EDILI"),
        ("E.02", "Murature"),
        ("E.02.a", "Murature portanti"),
    ]
    demolition = doc.price_items["1"]
    assert [(line["name"], line["quantity"], line["unit_rate"]) for line in demolition.analysis] == [
        ("Operaio comune", Decimal("0.15"), Decimal("32.17")),
        ("Escavatore con operatore", Decimal("0.02"), Decimal("25.97")),
    ]


def test_a_price_list_without_a_bill_says_where_it_belongs() -> None:
    result = build_imported_boq(read_xpwe(fx.price_list(5)))
    assert [p for p in result.positions] == []
    assert [w["code"] for w in result.warnings] == ["xpwe_no_bill_items"]


# ── Memory on a large file ───────────────────────────────────────────────────


def _peak_bytes(fn: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.slow
def test_a_sixty_megabyte_export_parses_in_bounded_memory() -> None:
    """Peak allocation stays proportional to the text the reader keeps, not to a tree.

    Measured on 2026-10-06: a full ``ElementTree.fromstring`` of a 20 MiB file
    of this shape peaked at 111 MiB (5.5x). The streaming reader keeps one
    record attached at a time. A bill keeps every price item's text (it can
    name any of them, in any order): about 1.0x the file. A price list is
    yielded item by item and keeps nothing but the chapter tree: 2.2 MiB on the
    20 MiB file, about 0.1x. The bounds leave headroom over those figures.
    """
    content = fx.large_bill(60 * 1024 * 1024)
    size = len(content)
    assert size > 55 * 1024 * 1024
    result: list[ImportedBOQ] = []
    bill_peak = _peak_bytes(lambda: result.append(build_imported_boq(read_xpwe(content))))
    assert len([p for p in result[0].positions if not p.is_section]) == 300
    assert bill_peak < 1.5 * size, f"bill: peak {bill_peak / 2**20:.0f} MiB for a {size / 2**20:.0f} MiB file"
    list_peak = _peak_bytes(lambda: sum(1 for _item in stream_price_list(content, XpweDocument())))
    assert list_peak < 0.25 * size, f"price list: peak {list_peak / 2**20:.0f} MiB for a {size / 2**20:.0f} MiB file"


def test_parsing_does_not_hold_the_event_loop() -> None:
    """The single worker keeps answering other requests while a large bill is read."""
    content = fx.large_bill(8 * 1024 * 1024)

    async def run() -> tuple[float, float]:
        loop = asyncio.get_running_loop()
        gaps: list[float] = []
        done = asyncio.Event()

        async def ticker() -> None:
            last = loop.time()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = loop.time()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        started = loop.time()
        await XpweImporter.parse(content, locale="en")
        elapsed = loop.time() - started
        done.set()
        await tick
        return elapsed, max(gaps, default=elapsed)

    elapsed, worst_gap = asyncio.run(run())
    assert worst_gap < max(0.25, elapsed / 4), f"loop held for {worst_gap:.2f}s of a {elapsed:.2f}s parse"
