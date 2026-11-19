# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB phase rules and the bill-unchanged comparison, without a database."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

_PACK = (
    Path(__file__).resolve().parents[3]
    / "packs"
    / "germany-de"
    / "src"
    / "openconstructionerp_germany_de"
    / "rule_packs"
    / "gaeb_x83_x86.json"
)


def _pos(ordinal: str, unit: str = "m3", quantity: str = "10", text: str = "Excavate") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), ordinal=ordinal, unit=unit, quantity=quantity, description=text)


# ── Bill unchanged (DOMAIN: X86 refused if the bill changed) ─────────────────


def test_an_untouched_bill_has_no_differences() -> None:
    from app.modules.boq.exchange_source import compare_lines, snapshot_lines

    bill = [_pos("01.0010"), _pos("01.0020", "m2", "80.000", "Backfill  and\ncompact")]
    source = snapshot_lines(bill)
    assert compare_lines(source, bill) == []


def test_quantity_unit_text_and_ordinal_changes_are_each_reported() -> None:
    from app.modules.boq.exchange_source import compare_lines, snapshot_lines

    a, b, c, d = _pos("01.0010"), _pos("01.0020"), _pos("01.0030"), _pos("01.0040")
    source = snapshot_lines([a, b, c, d])
    a.quantity = "12"
    b.unit = "m2"
    c.description = "Excavate rock"
    d.ordinal = "01.0045"
    fields = sorted(diff["field"] for diff in compare_lines(source, [a, b, c, d]))
    assert fields == ["ordinal", "quantity", "text", "unit"]


def test_a_removed_and_an_added_line_are_reported() -> None:
    from app.modules.boq.exchange_source import compare_lines, snapshot_lines

    a, b = _pos("01.0010"), _pos("01.0020")
    source = snapshot_lines([a, b])
    added = _pos("01.0030")
    fields = sorted(diff["field"] for diff in compare_lines(source, [a, added]))
    assert fields == ["added", "removed"]


def test_a_package_scope_ignores_changes_outside_it() -> None:
    from app.modules.boq.exchange_source import compare_lines, snapshot_lines

    a, b = _pos("01.0010"), _pos("02.0010")
    source = snapshot_lines([a, b])
    b.quantity = "99"
    assert compare_lines(source, [a, b], {str(a.id)}) == []
    assert len(compare_lines(source, [a, b], {str(b.id)})) == 1


def test_the_fingerprint_ignores_order_and_ids() -> None:
    from app.modules.boq.exchange_source import bill_fingerprint, snapshot_lines

    a, b = _pos("01.0010"), _pos("01.0020", "m2")
    again = [_pos("01.0020", "m2"), _pos("01.0010")]
    assert bill_fingerprint(snapshot_lines([a, b])) == bill_fingerprint(snapshot_lines(again))


# ── Phase rules ──────────────────────────────────────────────────────────────


def _failed(results: list[dict]) -> set[str]:
    return {r["rule_id"] for r in results if not r["passed"]}


async def test_an_x84_bill_with_gaps_fails_the_line_rules() -> None:
    from app.core.validation.rules.gaeb_phases import run_gaeb_exchange_rules

    positions = [
        {
            "ordinal": "01.0010",
            "description": "Excavate",
            "unit": "m3",
            "quantity": "10",
            "unit_rate": "5",
            "total": "50",
        },
        {"ordinal": "01.0010", "description": "", "unit": "", "quantity": "2", "unit_rate": "", "total": "0"},
        {
            "ordinal": "01.0030",
            "description": "Backfill",
            "unit": "m3",
            "quantity": "4",
            "unit_rate": "3",
            "total": "13",
        },
    ]
    failed = _failed(await run_gaeb_exchange_rules({"positions": positions, "gaeb_phase": "x84", "currency": "EUR"}))
    assert {
        "gaeb.item_description_not_empty",
        "gaeb.unit_specified_per_item",
        "gaeb.unit_price_present_x84",
        "gaeb.total_price_calculated_correctly",
        "gaeb.lv_numbering_consistent",
    } <= failed
    assert "gaeb.currency_element_present" not in failed


async def test_messages_follow_the_locale() -> None:
    from app.core.validation.rules.gaeb_phases import run_gaeb_exchange_rules

    data = {"positions": [{"ordinal": "1", "description": "", "unit": "m", "quantity": "1"}], "gaeb_phase": "x83"}
    de = await run_gaeb_exchange_rules(data, locale="de")
    text = next(r["message"] for r in de if r["rule_id"] == "gaeb.item_description_not_empty")
    assert "Position 1" in text


async def test_a_file_outside_the_33_namespace_fails_the_schema_rule() -> None:
    from app.core.validation.rules.gaeb_phases import run_gaeb_exchange_rules

    bad = '<?xml version="1.0"?><GAEB xmlns="http://example.org/other"><Award><DP>84</DP></Award></GAEB>'
    failed = _failed(await run_gaeb_exchange_rules({"gaeb_document": {"phase": "x84", "content": bad}}))
    assert "gaeb.xml_schema_valid" in failed
    broken = await run_gaeb_exchange_rules({"gaeb_document": {"phase": "x84", "content": "<GAEB><Award>"}})
    assert "gaeb.xml_schema_valid" in _failed(broken)


def test_every_rule_the_german_pack_enables_is_registered() -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    pack = json.loads(_PACK.read_text(encoding="utf-8"))
    assert pack["enables_rule_ids"]
    assert not pack.get("planned_not_built_rule_ids")
    missing = [rid for rid in pack["enables_rule_ids"] if rule_registry.get_rule(rid) is None]
    assert missing == []


@pytest.mark.parametrize(
    ("kind", "name", "content", "code"),
    [
        ("offer_pdf", "offer.pdf", b"not a pdf at all", "not_a_pdf"),
        ("attachment", "tool.exe", b"MZ\x90\x00" + b"\x00" * 20, "file_type_not_allowed"),
        ("attachment", "run.pdf", b"MZ\x90\x00" + b"\x00" * 20, "file_type_not_allowed"),
        ("x84", "a.x84", b"<GAEB/>", "invalid_file_kind"),
        ("attachment", "empty.pdf", b"", "empty_file"),
    ],
)
def test_bidder_uploads_are_refused_by_kind_extension_and_signature(kind, name, content, code) -> None:
    from fastapi import HTTPException

    from app.modules.tendering.bidder_exchange import check_upload

    with pytest.raises(HTTPException) as caught:
        check_upload(kind, name, content)
    assert caught.value.detail == code


def test_a_real_pdf_offer_is_accepted() -> None:
    from app.modules.tendering.bidder_exchange import check_upload

    assert check_upload("offer_pdf", "Angebot.pdf", b"%PDF-1.7\n%...") == "application/pdf"
