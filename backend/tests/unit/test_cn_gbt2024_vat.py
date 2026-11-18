# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GB/T 50500-2024, the VAT Law, 预缴 and 数电票: the worked examples first.

E1 is a new 2024 bill (Shanghai employer, Anhui site, contract 2026-03-10,
甲供 steel and concrete, general method). E2 is its 预缴 in months 4 and 5.
E3 is an old project on the simplified method, cross-city. Every figure below
is the figure in the scoping note, to the cent.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.core.item_codes import code_patterns, default_edition_key, editions
from app.core.line_tax import (
    TaxLine,
    check_item_codes,
    compute_tax_base,
    default_edition,
    lock_ends_on,
    method_change_locked,
)
from app.modules.china_pack import fapiao, service
from app.modules.china_pack.config import CN_TAX
from app.modules.china_pack.validators import RULE_IDS, evaluate
from app.modules.tax_withholding.place_of_supply import PrepaymentPeriod, prepayment_schedule

# ── E1: the 2024 bill ────────────────────────────────────────────────────────


def _e1_lines(*, pc_sum_inclusive: bool = True) -> list[dict]:
    return [
        {"ref": "fenbu", "head": "fenbu", "amount": "6600000", "code": "010101001001", "sub_project": "A"},
        {
            "ref": "jiagong",
            "head": "fenbu",
            "amount": "1200000",
            "employer_supplied": True,
            "code": "010501001001",
            "sub_project": "A",
        },
        {"ref": "cuoshi", "head": "cuoshi", "amount": "900000"},
        {"ref": "zanlie", "head": "qita", "kind": "provisional_sum", "amount": "300000"},
        {"ref": "jirigong", "head": "qita", "kind": "daywork", "amount": "20000"},
        {"ref": "zongbao", "head": "qita", "kind": "main_contractor_service", "amount": "8000"},
        {
            "ref": "pcsum",
            "head": "qita",
            "kind": "specialist_pc_sum",
            "amount": "436000",
            "tax_inclusive": pc_sum_inclusive,
        },
    ]


def _e1_profile(**changes) -> dict:
    profile = {
        "tax_method": "general",
        "standard_edition": "gb50500@2024",
        "employer_supplied": True,
        "contract_date": "2026-03-10",
        "site_subdivision": "CN-AH",
        "site_city": "Hefei",
        "home_subdivision": "CN-SH",
        "home_city": "Shanghai",
    }
    profile.update(changes)
    return profile


def test_e1_tender_total_is_10_276_520() -> None:
    summary = service.tender_summary(_e1_lines(), service.SummaryInput(edition="gb50500@2024", on=date(2026, 3, 10)))
    assert summary["vat_base"] == "9028000"
    assert summary["vat"] == "812520.00"
    assert summary["tax_inclusive_total"] == "436000"
    assert Decimal(summary["tender_total"]) == Decimal("10276520")
    heads = {h["key"]: Decimal(h["amount"]) for h in summary["heads"]}
    assert [h["key"] for h in summary["heads"]] == ["fenbu", "cuoshi", "qita", "zengzhishui"]
    assert heads == {
        "fenbu": Decimal("7800000"),
        "cuoshi": Decimal("900000"),
        "qita": Decimal("764000"),
        "zengzhishui": Decimal("812520.00"),
    }


def test_e1_pc_sum_stays_out_of_the_vat_base_even_unflagged() -> None:
    summary = service.tender_summary(_e1_lines(pc_sum_inclusive=False), service.SummaryInput(on=date(2026, 3, 10)))
    assert summary["vat"] == "812520.00"


def test_e1_employer_supplied_is_priced_and_deducted_not_invoiced() -> None:
    summary = service.tender_summary(_e1_lines(), service.SummaryInput(on=date(2026, 3, 10)))
    assert summary["employer_supplied_net"] == "1200000"
    assert summary["employer_supplied_tax"] == "108000.00"
    assert Decimal(summary["invoiceable_total"]) == Decimal("10276520") - Decimal("1308000")


def test_the_2013_edition_keeps_five_heads() -> None:
    keys = [h["key"] for h in service.structure("gb50500@2013")]
    assert keys == ["fenbu", "cuoshi", "qita", "guifei", "shuijin"]


def test_neutral_tax_base_matches_e1() -> None:
    lines = [TaxLine("a", Decimal("9028000"), Decimal(9)), TaxLine("pc", Decimal("436000"), Decimal(9), True)]
    base = compute_tax_base(lines)
    assert (base.taxable_base, base.tax, base.total) == (Decimal("9028000"), Decimal("812520.00"), Decimal("10276520"))


async def _ids(**record_parts) -> set[str]:
    record = service.build_record(**record_parts)
    return {r.rule_id for r in await evaluate(record)}


async def test_e1_as_drawn_raises_nothing() -> None:
    assert await _ids(profile=_e1_profile(), lines=_e1_lines()) == set()


async def test_e1_with_3_percent_fires_simplified_jiagong() -> None:
    ids = await _ids(profile=_e1_profile(tax_method="simplified", simplified_basis="employer_supplied"), lines=[])
    assert "cn.simplified_jiagong" in ids


async def test_jiagong_elected_before_2026_is_grandfathered() -> None:
    profile = _e1_profile(tax_method="simplified", contract_date="2025-06-01")
    assert "cn.simplified_jiagong" not in await _ids(profile=profile)
    late = _e1_profile(tax_method="simplified", grandfathered=True)
    assert "cn.simplified_jiagong" not in await _ids(profile=late)


async def test_e1_vat_on_the_pc_sum_fires_vat_base_pc_sum() -> None:
    ids = await _ids(profile=_e1_profile(), lines=_e1_lines(pc_sum_inclusive=False))
    assert "cn.vat_base_pc_sum" in ids


async def test_guifei_head_on_a_2024_bill_is_flagged() -> None:
    lines = [*_e1_lines(), {"ref": "gf", "head": "guifei", "amount": "50000"}]
    assert "cn.guifei_head_2024" in await _ids(profile=_e1_profile(), lines=lines)
    old = _e1_profile(standard_edition="gb50500@2013")
    assert "cn.guifei_head_2024" not in await _ids(profile=old, lines=lines)


async def test_a_line_rate_that_is_not_its_category_rate_warns() -> None:
    lines = [
        {"ref": "w", "amount": "100", "tax_category": "works", "rate_pct": "9"},
        {"ref": "g", "amount": "100", "tax_category": "goods_installed", "rate_pct": "9"},
    ]
    results = await evaluate(service.build_record(profile=_e1_profile(), lines=lines))
    wrong = [r for r in results if r.rule_id == "cn.vat_rate_line"]
    assert [r.element_ref for r in wrong] == ["g"]
    assert wrong[0].details["expected"] == "13"


# ── E2: 预缴 on E1 ────────────────────────────────────────────────────────────


def test_e2_month_4_prepays_28_000_and_month_5_carries_245_000() -> None:
    m4, m5 = prepayment_schedule(
        [
            PrepaymentPeriod("2026-07", Decimal("2180000"), Decimal("654000")),
            PrepaymentPeriod("2026-08", Decimal("300000"), Decimal("545000")),
        ],
        tax_rate_pct=Decimal(9),
        prepay_rate_pct=Decimal(2),
    )
    assert (m4.base_net, m4.prepaid, m4.carried_out) == (Decimal("1400000.00"), Decimal("28000.00"), Decimal(0))
    assert (m5.prepaid, m5.carried_out) == (Decimal("0"), Decimal("245000"))


async def test_e2_a_wrong_recorded_prepayment_fires_prepay_calc() -> None:
    prepayment = {
        "periods": [
            {
                "period": "2026-07",
                "receipts": "2180000",
                "subcontract_paid": "654000",
                "recorded_prepaid": "43600",
                "subcontract_invoices": [{"amount": "654000", "site_location": "Hefei Feidong"}],
            }
        ],
        "site_location": "Hefei",
    }
    results = await evaluate(service.build_record(profile=_e1_profile(), prepayment=prepayment))
    calc = [r for r in results if r.rule_id == "cn.prepay_calc"]
    assert len(calc) == 1 and calc[0].details["exp"] == "28000.00"
    assert "cn.prepay_subcontract_invoice" not in {r.rule_id for r in results}
    prepayment["periods"][0]["recorded_prepaid"] = "28000"
    assert "cn.prepay_calc" not in await _ids(profile=_e1_profile(), prepayment=prepayment)


async def test_e2_subcontract_without_site_invoices_warns() -> None:
    prepayment = {
        "periods": [{"period": "m4", "receipts": "2180000", "subcontract_paid": "654000"}],
        "site_location": "Hefei",
    }
    results = await evaluate(service.build_record(profile=_e1_profile(), prepayment=prepayment))
    found = [r for r in results if r.rule_id == "cn.prepay_subcontract_invoice"]
    assert found and found[0].details["amt"] == "654000"


# ── E3: old project, simplified, cross-city ──────────────────────────────────


def _e3_profile() -> dict:
    return {
        "tax_method": "simplified",
        "simplified_basis": "old_project",
        "permit_start_date": "2016-03-01",
        "election_date": "2019-05-01",
        "standard_edition": "gb50500@2013",
    }


def test_e3_prepays_24_000() -> None:
    (period,) = prepayment_schedule(
        [PrepaymentPeriod("p1", Decimal("1030000"), Decimal("206000"))],
        tax_rate_pct=Decimal(3),
        prepay_rate_pct=Decimal(3),
    )
    assert (period.base_net, period.prepaid) == (Decimal("800000.00"), Decimal("24000.00"))


async def test_e3_invoice_dated_2028_fires_sunset() -> None:
    invoices = [
        {"ref": "ok", "date": "2027-12-20", "rates": ["3"], "site_location": "Suzhou", "project_name": "X"},
        {"ref": "late", "date": "2028-01-15", "rates": ["3"], "site_location": "Suzhou", "project_name": "X"},
    ]
    results = await evaluate(service.build_record(profile=_e3_profile(), invoices=invoices))
    sunset = [r for r in results if r.rule_id == "cn.simplified_sunset"]
    assert [r.element_ref for r in sunset] == ["late"]


@pytest.mark.parametrize(
    ("code", "subdivision", "ok"),
    [
        ("010101001001", None, True),
        ("010101001", None, True),
        ("01B001", None, True),
        ("沪010101001", "CN-SH", True),
        ("沪010101001", None, False),
        ("01010100100", None, False),
    ],
)
def test_e3_code_examples(code: str, subdivision: str | None, ok: bool) -> None:
    patterns = code_patterns("gb50500", "gb50500@2024", subdivision)
    findings = check_item_codes([("r", code, "A")], patterns)
    assert (not findings) is ok


async def test_e3_duplicate_code_in_one_sub_project_fires_code_unique() -> None:
    lines = [
        {"ref": "a", "code": "010501001001", "sub_project": "S1", "amount": "1"},
        {"ref": "b", "code": "010501001001", "sub_project": "S1", "amount": "1"},
        {"ref": "c", "code": "010501001001", "sub_project": "S2", "amount": "1"},
        {"ref": "d", "code": "01010100100", "sub_project": "S2", "amount": "1"},
    ]
    results = await evaluate(service.build_record(profile=_e3_profile(), lines=lines))
    by_rule = {(r.rule_id, r.element_ref) for r in results}
    assert ("cn.code_unique", "b") in by_rule
    assert ("cn.code_unique", "c") not in by_rule
    assert ("cn.code_format", "d") in by_rule


# ── Lock, edition, invoices, contract ────────────────────────────────────────


def test_the_36_month_lock() -> None:
    assert lock_ends_on(date(2026, 1, 31), 36) == date(2029, 1, 31)
    assert method_change_locked(date(2026, 1, 31), 36, date(2029, 1, 30))
    assert not method_change_locked(date(2026, 1, 31), 36, date(2029, 1, 31))


async def test_leaving_simplified_inside_the_lock_fires_simplified_lock() -> None:
    profile = {
        "tax_method": "general",
        "method_history": [{"method": "simplified", "election_date": "2025-02-01", "changed_on": "2026-05-01"}],
    }
    assert "cn.simplified_lock" in await _ids(profile=profile)


def test_edition_follows_the_creation_day() -> None:
    rows = editions("gb50500")
    assert default_edition(rows, date(2025, 8, 31)) == "gb50500@2013"
    assert default_edition(rows, date(2025, 9, 1)) == "gb50500@2024"
    assert default_edition_key("gb50500") == CN_TAX["default_edition_key"] == "gb50500@2024"


async def test_a_2013_bill_tendered_in_shenzhen_after_the_switch_warns() -> None:
    profile = {"standard_edition": "gb50500@2013", "tender_date": "2026-02-01", "site_city": "Shenzhen"}
    assert "cn.edition_mismatch" in await _ids(profile=profile)
    profile["tender_date"] = "2025-12-01"
    assert "cn.edition_mismatch" not in await _ids(profile=profile)
    # No switch date is shipped for Shanghai, so nothing is claimed there.
    assert "cn.edition_mismatch" not in await _ids(profile={**profile, "site_city": "Shanghai"})


async def test_fapiao_number_and_site() -> None:
    invoices = [
        {
            "ref": "good",
            "number": "26312000000000000001",
            "date": "2026-04-01",
            "site_location": "Hefei",
            "project_name": "E1",
        },
        {
            "ref": "year",
            "number": "25312000000000000001",
            "date": "2026-04-01",
            "site_location": "Hefei",
            "project_name": "E1",
        },
        {"ref": "short", "number": "2631200000", "date": "2026-04-01", "site_location": "", "project_name": "E1"},
    ]
    results = await evaluate(service.build_record(profile=_e1_profile(), invoices=invoices))
    pairs = {(r.rule_id, r.element_ref) for r in results}
    assert ("cn.fapiao_number", "year") in pairs and ("cn.fapiao_number", "short") in pairs
    assert ("cn.fapiao_number", "good") not in pairs
    assert ("cn.fapiao_site", "short") in pairs and ("cn.fapiao_site", "good") not in pairs


async def test_open_ended_risk_clause_warns() -> None:
    assert "cn.unlimited_risk" in await _ids(profile={}, contract={"risk_clause": "unlimited"})
    assert "cn.unlimited_risk" not in await _ids(profile={}, contract={"risk_clause": "bands"})


def test_all_rules_are_registered_once() -> None:
    # 14 national rules plus 10 for the provincial fee programmes.
    assert len(RULE_IDS) == 24
    assert len(set(RULE_IDS)) == 24


# ── 数电票 data ──────────────────────────────────────────────────────────────


def _fapiao() -> dict:
    return fapiao.build_fapiao_data(
        invoice={"invoice_number": "INV-7", "invoice_date": "2026-04-01", "currency_code": "CNY"},
        lines=[
            {
                "description": "土方工程",
                "quantity": "1",
                "unit": "项",
                "unit_rate": "1000",
                "amount": "1000",
                "vat_rate": "9",
            }
        ],
        seller={"name": "上海某建设有限公司", "vat_id": "91310000000000000X"},
        buyer={"name": "某置业有限公司", "vat_id": "91340100000000000Y"},
        einvoice={
            "project_name": "合肥某项目",
            "site_address": {"subdivision": "安徽省", "city": "合肥市", "line1": "肥东县"},
        },
    )


def test_fapiao_data_carries_the_construction_tag_and_totals() -> None:
    data = _fapiao()
    assert data["special_business"]["tag"] == "建筑服务"
    assert data["special_business"]["site_location"] == "安徽省 合肥市 肥东县"
    assert (data["total_amount"], data["total_tax"], data["total_with_tax"]) == ("1000.00", "90.00", "1090.00")
    assert json.loads(fapiao.to_json(data))["items"][0]["tax_rate_pct"] == "9"
    root = ET.fromstring(fapiao.to_xml(data))
    assert root.findtext("special_business/project_name") == "合肥某项目"


def test_fapiao_data_refuses_a_construction_invoice_without_a_site() -> None:
    with pytest.raises(fapiao.FapiaoDataError):
        fapiao.build_fapiao_data(invoice={}, lines=[], seller=None, buyer=None, einvoice={"project_name": "x"})
