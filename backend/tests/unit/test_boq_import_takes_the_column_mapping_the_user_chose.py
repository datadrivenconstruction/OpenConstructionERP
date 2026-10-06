# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The column mapping a user picks in the import preview is the one the import uses.

The preview has always shown a dropdown per column, and the import never sent
it: whatever the user chose, the bill was read with the importer's own guess,
so the one control that could rescue a file with unfamiliar headings did
nothing. The dialog now sends the columns the user changed, and the importer
lays them over its own reading. These tests hold the importer and the route to
that, and to refusing a mapping it cannot apply rather than guessing:

* a header the importer does not know at all imports once the user names its
  columns, and the preview offers the row the user wrote as headings rather
  than the title above it;
* a column the user leaves out is left out, and the columns the user did not
  touch keep the importer's reading (the material half of a split rate
  dropped leaves the fee half as the rate);
* a mapping that would leave two columns feeding one field, or names a column
  the header does not have, is refused with the reason;
* a sheet headed differently from the one the mapping was chosen on, and a
  workbook read through a national profile, say the mapping was not used.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile

from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers._base import ImportedBOQ
from app.modules.boq.importers.excel import ExcelImporter, parse_column_mapping
from tests.fixtures import hu_boq
from tests.unit.test_hungary_workbook_import import _building_workbook, _rows_like_the_template


def _parse(content: bytes, mapping: dict[int, str] | None = None) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content, column_mapping=mapping))


def _lines(result: ImportedBOQ) -> list[Any]:
    return [p for p in result.positions if not p.is_section and p.unit not in ("", "section")]


def _coded(result: ImportedBOQ, code: str) -> list[dict[str, Any]]:
    return [issue for issue in [*result.errors, *result.warnings] if issue.get("code") == code]


# ── Reading the form field ───────────────────────────────────────────────


@pytest.mark.parametrize("raw", [None, "", "  ", "{}"])
def test_no_mapping_means_the_importers_own_reading(raw: str | None) -> None:
    assert parse_column_mapping(raw) is None


def test_a_mapping_is_read_as_column_index_to_field() -> None:
    assert parse_column_mapping('{"0": "ordinal", "3": "quantity", "5": ""}') == {
        0: "ordinal",
        3: "quantity",
        5: "",
    }


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("not json", "not valid JSON"),
        ('["quantity"]', "must be an object"),
        ('{"C": "quantity"}', "is not a column index"),
        ('{"-1": "quantity"}', "is not a column index"),
        ('{"3": "price"}', "use one of"),
        ('{"3": 4}', "use one of"),
        ('{"3": "quantity", "4": "quantity"}', "more than one column to quantity"),
    ],
)
def test_a_mapping_that_cannot_be_read_says_why(raw: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_column_mapping(raw)


# ── An unknown header, named by the user ─────────────────────────────────


def test_the_preview_offers_the_row_the_user_wrote_as_headings() -> None:
    """Not the title block above it: those are the columns the user can map."""
    preview = _parse(hu_boq.unrecognised_header_xlsx())
    assert preview.metadata["original_columns"] == ["Sor", "Kód", "Munka", "Darab", "ME", "Ár"]
    assert preview.metadata["header_row"] == len(hu_boq.TITLE_ROWS) + 1
    assert preview.metadata["column_mapping"] == {"4": "unit"}
    assert _coded(preview, "header_not_recognised")
    assert not _lines(preview)


def test_a_header_nobody_knows_imports_once_the_user_names_the_columns() -> None:
    mapping = {0: "ordinal", 1: "classification", 2: "description", 3: "quantity", 5: "unit_rate"}
    result = _parse(hu_boq.unrecognised_header_xlsx(), mapping)

    assert not _coded(result, "header_not_recognised")
    lines = _lines(result)
    assert len(lines) == 1
    line = lines[0]
    assert (line.ordinal, line.description, line.unit) == ("1", "Földkiemelés", "m3")
    assert line.quantity == pytest.approx(125.5)
    assert line.unit_rate == pytest.approx(1850.0)
    assert result.metadata["column_mapping_applied"] is True


# ── Changing a column the importer did read ──────────────────────────────


def test_a_column_left_out_is_left_out_and_the_rest_keep_their_reading() -> None:
    """Dropping the material rate leaves the fee as the rate, not nothing."""
    result = _parse(hu_boq.flat_xlsx(), {5: ""})
    by_ordinal = {p.ordinal: p for p in _lines(result)}
    for ssz, unit, quantity, _material, fee in hu_boq.EXPECTED_LINES:
        line = by_ordinal[ssz]
        assert line.unit == unit
        assert line.quantity == pytest.approx(quantity)
        assert line.unit_rate == pytest.approx(fee), f"line {ssz}: the rate should be the fee alone"
    assert "5" not in result.metadata["column_mapping"]


def test_without_a_mapping_the_same_file_reads_as_before() -> None:
    result = _parse(hu_boq.flat_xlsx())
    by_ordinal = {p.ordinal: p for p in _lines(result)}
    for ssz, _unit, _quantity, material, fee in hu_boq.EXPECTED_LINES:
        assert by_ordinal[ssz].unit_rate == pytest.approx(material + fee)
    assert result.metadata["column_mapping_applied"] is False


def test_a_mapping_that_leaves_two_columns_on_one_field_is_refused() -> None:
    """Column 2 (the item code) named as the quantity while "Menny." still is one."""
    with pytest.raises(ImporterParseError, match="all feeding quantity"):
        _parse(hu_boq.flat_xlsx(), {1: "quantity"})


def test_a_mapping_for_a_column_the_header_does_not_have_is_refused() -> None:
    with pytest.raises(ImporterParseError, match="names column 41"):
        _parse(hu_boq.flat_xlsx(), {40: "unit"})


def test_a_csv_takes_the_mapping_too() -> None:
    result = _parse(hu_boq.utf8_csv(), {5: ""})
    fees = {ssz: fee for ssz, _unit, _quantity, _material, fee in hu_boq.EXPECTED_LINES}
    for line in _lines(result):
        assert line.unit_rate == pytest.approx(fees[line.ordinal])


# ── Where the mapping does not apply ─────────────────────────────────────


def test_a_sheet_headed_differently_is_read_as_before_and_named() -> None:
    content = hu_boq._xlsx(
        [
            ("Építészet", [hu_boq.HEADER, *hu_boq.ROWS]),
            ("Villamos", [hu_boq.SINGLE_RATE_HEADER, ["1", "", "Kábel", "10", "fm", "900", "9 000"]]),
        ]
    )
    result = _parse(content, {5: ""})
    notes = _coded(result, "column_mapping_not_applied")
    assert [(n["reason"], n.get("sheet")) for n in notes] == [("different_header", "Villamos")]
    cable = next(p for p in _lines(result) if p.description == "Kábel")
    assert cable.unit_rate == pytest.approx(900.0), "the second sheet keeps its own rate column"


def test_a_workbook_read_through_its_national_profile_says_the_mapping_was_not_used() -> None:
    result = _parse(_building_workbook(_rows_like_the_template()), {0: "description"})
    assert [n["reason"] for n in _coded(result, "column_mapping_not_applied")] == ["profile"]
    assert result.positions


# ── The route ────────────────────────────────────────────────────────────


class _Service:
    session = None

    async def _ensure_boq_writable(self, _boq_id: uuid.UUID) -> None:
        return None


def _call_auto(
    monkeypatch: pytest.MonkeyPatch, content: bytes, name: str, column_mapping: str | None
) -> tuple[dict[str, Any], list[ImportedBOQ]]:
    from app.modules.boq import router

    persisted: list[ImportedBOQ] = []

    async def verify(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def persist(_boq_id: uuid.UUID, imported: ImportedBOQ, **_kwargs: Any) -> dict[str, Any]:
        persisted.append(imported)
        return {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "unchanged": 0,
            "would_delete": 0,
            "round_trip": False,
            "problems": [],
            "apply_errors": [],
        }

    monkeypatch.setattr(router, "_verify_boq_owner", verify)
    monkeypatch.setattr(router, "_persist_imported_boq", persist)
    upload = UploadFile(file=io.BytesIO(content), filename=name)
    body = asyncio.run(
        router.import_boq_auto(
            boq_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            payload=SimpleNamespace(),
            file=upload,
            service=_Service(),  # type: ignore[arg-type]
            session=None,
            delete_missing=False,
            column_mapping=column_mapping,
            # Called directly, a Query default is a truthy marker, not False.
            background=False,
            force=False,
        )
    )
    return body, persisted


def test_the_route_hands_the_mapping_to_the_spreadsheet_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {"0": "ordinal", "1": "classification", "2": "description", "3": "quantity", "5": "unit_rate"}
    body, persisted = _call_auto(
        monkeypatch, hu_boq.unrecognised_header_xlsx(), "koltsegvetes.xlsx", json.dumps(mapping)
    )
    assert body["metadata"]["column_mapping_applied"] is True
    assert [p.description for p in persisted[0].positions if not p.is_section] == ["Földkiemelés"]


def test_the_route_refuses_a_mapping_it_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as refused:
        _call_auto(monkeypatch, hu_boq.flat_xlsx(), "koltsegvetes.xlsx", '{"3": "price"}')
    assert refused.value.status_code == 422
    assert "use one of" in str(refused.value.detail)


def test_the_route_reads_a_file_without_a_mapping_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    body, persisted = _call_auto(monkeypatch, hu_boq.flat_xlsx(), "koltsegvetes.xlsx", None)
    assert body["metadata"]["column_mapping_applied"] is False
    assert len(_lines(persisted[0])) == len(hu_boq.EXPECTED_LINES)


def test_the_preview_shows_the_bill_the_mapping_gives() -> None:
    """The dialog previews again with the mapping, so an unknown header can reach the import button."""
    from app.modules.boq import router

    def preview(column_mapping: str | None) -> dict[str, Any]:
        upload = UploadFile(file=io.BytesIO(hu_boq.unrecognised_header_xlsx()), filename="koltsegvetes.xlsx")
        return asyncio.run(router.import_preview(file=upload, column_mapping=column_mapping))

    assert preview(None)["total_positions"] == 0
    mapping = {"0": "ordinal", "2": "description", "3": "quantity", "4": "unit", "5": "unit_rate"}
    mapped = preview(json.dumps(mapping))
    assert mapped["total_positions"] == 1
    assert mapped["positions"][0]["total"] == pytest.approx(125.5 * 1850)
