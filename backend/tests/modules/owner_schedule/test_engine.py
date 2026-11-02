# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule engine: profile schema, detection, parsing, addendum diff, rounding and write back."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from app.modules.owner_schedule import engine
from app.modules.owner_schedule.profile import ScheduleProfile, pack_profiles, platform_profiles, profile_json_schema

from .conftest import FIXTURES, agency_workbook, generic_csv, generic_workbook


def _generic(key: str = "generic_xlsx") -> ScheduleProfile:
    return next(p for p in platform_profiles() if p.key == key)


class TestProfileSchema:
    def test_platform_profiles_validate(self):
        keys = {p.key for p in platform_profiles()}
        assert {"generic_xlsx", "generic_csv", "gaeb_xml"} <= keys

    def test_schema_is_exported(self):
        schema = profile_json_schema()
        assert "columns" in schema["properties"]
        assert "rounding" in schema["properties"]

    def test_missing_required_role_is_rejected(self):
        with pytest.raises(ValidationError, match="item_no"):
            ScheduleProfile(
                key="x",
                name="x",
                file_type="xlsx",
                first_data_row=2,
                columns={"description": "B", "quantity": "C", "unit_price": "D"},
            )

    def test_bad_column_letter_and_regex(self):
        with pytest.raises(ValidationError):
            ScheduleProfile(key="x", name="x", file_type="xlsx", first_data_row=2, columns={"item_no": "1"})
        with pytest.raises(ValidationError, match="regular expression"):
            ScheduleProfile(
                key="x",
                name="x",
                file_type="xlsx",
                first_data_row=2,
                numbering_pattern="(",
                columns={"item_no": "A", "description": "B", "quantity": "C", "unit_price": "D"},
            )

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            ScheduleProfile.model_validate(
                {"key": "x", "name": "x", "file_type": "xml", "handled_by": "gaeb", "colour": 1}
            )

    def test_pack_hook_reads_profiles_from_manifest_metadata(self, monkeypatch):
        from types import SimpleNamespace

        import app.core.partner_pack.discovery as disc

        pack = SimpleNamespace(slug="example-pack", metadata={"owner_schedule_profiles": ["p.json", "missing.json"]})
        monkeypatch.setattr(disc, "discover_packs", lambda: [pack])
        raw = (FIXTURES / "pack_profile.json").read_bytes()
        monkeypatch.setattr(disc, "read_pack_file", lambda slug, rel: raw if rel == "p.json" else None)
        profiles = pack_profiles()
        assert [p.key for p in profiles] == ["example-pack.agency_unit_price"]
        assert profiles[0].source == "pack"


class TestDetect:
    def test_pack_profile_wins_on_its_own_file(self, agency_profile):
        cands = engine.detect(agency_workbook(), "bid.xlsx", [*platform_profiles(), agency_profile])
        assert cands[0]["profile_key"] == agency_profile.key
        assert cands[0]["confidence"] >= 0.8
        assert "numbering" in cands[0]["reasons"]

    def test_generic_profile_finds_headers(self, agency_profile):
        cands = engine.detect(generic_workbook(), "s.xlsx", [*platform_profiles(), agency_profile])
        assert cands[0]["profile_key"] == "generic_xlsx"
        assert cands[0]["item_count"] == 3
        # The pack profile needs a sheet the file does not have.
        assert agency_profile.key not in {c["profile_key"] for c in cands}

    def test_csv_and_xml(self):
        assert engine.detect(generic_csv(), "s.csv", platform_profiles())[0]["profile_key"] == "generic_csv"
        xml = b'<?xml version="1.0"?><GAEB/>'
        assert engine.detect(xml, "lv.x83", platform_profiles())[0]["profile_key"] == "gaeb_xml"


class TestParse:
    def test_sections_items_lump_sum_alternate(self, agency_profile):
        res = engine.parse(agency_workbook(), "bid.xlsx", agency_profile)
        by_no = {ln.item_no: ln for ln in res.lines}
        assert by_no["0201-001"].is_lump_sum
        assert by_no["0201-001"].quantity == 1
        assert by_no["0401-005"].quantity == Decimal("333.333")
        assert by_no["ALT-1"].is_alternate
        assert res.total_row == 10
        assert not [i for i in res.issues if i["severity"] == "error"]

    def test_generic_sections(self):
        res = engine.parse(generic_workbook(), "s.xlsx", _generic())
        assert [ln.item_no for ln in res.lines if ln.is_section] == ["1", "2"]
        assert res.header_row == 3

    def test_duplicate_and_unreadable_are_errors(self, agency_profile):
        data = agency_workbook([("0203-010", "A", "CY", 1), ("0203-010", "B", "CY", "lots")])
        codes = {i["code"] for i in engine.parse(data, "b.xlsx", agency_profile).issues}
        assert {"duplicate_item", "quantity_unreadable"} <= codes

    def test_csv_decimal_comma(self):
        prof = _generic("generic_csv").model_copy(update={"csv_delimiter": ";"})
        res = engine.parse(generic_csv(), "s.csv", prof)
        assert res.lines[1].quantity == Decimal("40.5")


class TestDiff:
    def test_added_removed_quantity_changed(self, agency_profile):
        base = engine.parse(agency_workbook(), "b.xlsx", agency_profile).lines
        current = [{**ln.as_dict(), "removed": False} for ln in base]
        revised = agency_workbook(
            [
                ("0201-001", "Clearing and grubbing", "LS", None),
                ("0203-010", "Unclassified excavation", "CY", 1300),
                ("0501-001", "Curb and gutter", "LF", 80),
                ("ALT-1", "Alternate: colored concrete", "SY", 120),
            ]
        )
        changes = engine.diff_items(current, engine.parse(revised, "b2.xlsx", agency_profile).lines)
        kinds = {c["item_no"]: c["kind"] for c in changes}
        assert kinds == {"0203-010": "quantity_changed", "0501-001": "added", "0401-005": "removed"}


class TestRounding:
    def test_total_equals_sum_of_rounded_lines(self, agency_profile):
        lines = engine.parse(agency_workbook(), "b.xlsx", agency_profile).lines
        prices = {
            "0201-001": Decimal("15000"),
            "0203-010": Decimal("12.345"),
            "0401-005": Decimal("87.125"),
            "ALT-1": Decimal("9.999"),
        }
        priced, base, alts = engine.price_lines(lines, prices, agency_profile)
        by = {p.item_no: p for p in priced}
        assert by["0203-010"].unit_price == Decimal("12.35")  # half up
        assert by["0203-010"].amount == Decimal("15246.08")  # 12.35 * 1234.5 = 15246.075
        assert by["0401-005"].amount == Decimal("29043.30")  # 87.13 * 333.333 = 29043.30429
        assert base == sum(p.amount for p in priced if not p.is_alternate)
        assert base == Decimal("59289.38")
        assert alts == by["ALT-1"].amount

    def test_unpriced_line_has_no_amount(self, agency_profile):
        lines = engine.parse(agency_workbook(), "b.xlsx", agency_profile).lines
        priced, base, _ = engine.price_lines(lines, {}, agency_profile)
        assert all(p.amount is None for p in priced)
        assert base == 0


class TestWriteBack:
    def test_untouched_cells_formulas_and_protection_survive(self, agency_profile):
        src = agency_workbook()
        lines = engine.parse(src, "b.xlsx", agency_profile).lines
        prices = {"0201-001": Decimal("15000"), "0203-010": Decimal("12.35"), "0401-005": Decimal("87.13")}
        priced, base, _ = engine.price_lines(lines, prices, agency_profile)
        out, log = engine.write_back(src, "b.xlsx", agency_profile, priced, base)
        a = load_workbook(io.BytesIO(src))["Bid Schedule"]
        b = load_workbook(io.BytesIO(out))["Bid Schedule"]
        written = {c["cell"] for c in log if c.get("value") is not None}
        assert "E6" not in written  # lump sum, amount only
        assert {"F6", "E7", "F7", "E8", "F8"} <= written
        for row in a.iter_rows():
            for cell in row:
                if cell.coordinate not in written:
                    assert b[cell.coordinate].value == cell.value, cell.coordinate
        assert b["F10"].value.startswith("=SUM")  # owner's formula kept
        assert b.protection.sheet
        assert b["A1"].font.bold
        assert Decimal(str(b["F7"].value)) == Decimal("15246.08")

    def test_csv_round_trip_changes_only_fill_cells(self):
        prof = _generic("generic_csv").model_copy(update={"csv_delimiter": ";"})
        src = generic_csv()
        lines = engine.parse(src, "s.csv", prof).lines
        priced, base, _ = engine.price_lines(lines, {"1.1": Decimal("10"), "1.2": Decimal("3.333")}, prof)
        out, _ = engine.write_back(src, "s.csv", prof, priced, base)
        rows = out.decode().splitlines()
        assert rows[0] == src.decode().splitlines()[0]
        assert rows[1] == "1.1;Excavation;m3;100;10.00;1000.00"
        assert rows[2] == "1.2;Backfill;m3;40,5;3.33;134.87"
        assert rows[3] == "Total;;;;;1134.87"
