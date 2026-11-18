"""Provincial fee programmes of the China pack, against the worked example.

One 1,000 m2 RC frame office, identical resources everywhere: labour 600,000,
materials 1,150,000, plant 100,000, provisional sum 100,000, general tax 9%.
Only the fee rules differ, and every total below is the figure of the domain
note's table. Rates marked USER there are passed as the user's rates here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.china_pack import fees, service
from app.modules.china_pack.validators import evaluate

D = Decimal
COMPONENTS = {"components": {"labour": "600000", "material": "1150000", "plant": "100000", "provisional_sum": "100000"}}


def _profile(sub: str, city: str | None, tender: str, edition: str | None = None) -> dict:
    return {
        "site_subdivision": sub,
        "site_city": city,
        "tender_date": tender,
        "tax_method": "general",
        "standard_edition": edition,
    }


def _block(sub: str, city: str | None, tender: str, settings: dict | None = None) -> dict:
    fee = fees.fee_block(_profile(sub, city, tender), settings or {}, COMPONENTS)
    assert fee is not None
    return fee


def _amounts(fee: dict) -> dict[str, Decimal]:
    return {row["code"]: D(row["amount"]) for row in fee["result"]["lines"]}


async def _rule_ids(fee: dict, profile: dict | None = None) -> list[str]:
    record = service.build_record(profile=profile or {}, fee=fee)
    return [r.rule_id for r in await evaluate(record)]


@pytest.mark.parametrize(
    ("sub", "city", "tender", "settings", "schedule", "pre_tax", "vat", "total"),
    [
        ("CN-GD", "Shenzhen", "2026-03-01", {}, "shenzhen_2025", "2370786.34", "213370.77", "2584157.11"),
        (
            "CN-GD",
            "Guangzhou",
            "2026-03-01",
            {"rates": {"mgmt": "25.71"}},
            "guangdong_2018_adj2025",
            "2441540.00",
            "219738.60",
            "2661278.60",
        ),
        (
            "CN-ZJ",
            "Hangzhou",
            "2026-03-01",
            {"options": {"zone": "urban"}},
            "zhejiang_2018_rules2026",
            "2386450.00",
            "214780.50",
            "2601230.50",
        ),
        (
            "CN-JS",
            "Suzhou",
            "2026-03-01",
            {"options": {"project_class": "III"}},
            "jiangsu_2014_vat",
            "2366699.53",
            "213002.96",
            "2579702.49",
        ),
        (
            "CN-BJ",
            None,
            "2025-10-01",
            {"rates": {"mgmt": "15", "profit": "7"}, "options": {"safety_grade": "dabiao", "ring": "inside"}},
            "beijing_2021_377",
            "2569902.20",
            "231291.20",
            "2801193.40",
        ),
        (
            "CN-SC",
            "Chengdu",
            "2025-06-01",
            {"rates": {"zonghe": "25", "guifei": "8"}},
            "sichuan_2020_15",
            "2306856.80",
            "207617.11",
            "2514473.91",
        ),
    ],
)
def test_worked_example_per_jurisdiction(sub, city, tender, settings, schedule, pre_tax, vat, total) -> None:
    fee = _block(sub, city, tender, settings)
    result = fee["result"]
    assert result["schedule_key"] == schedule
    assert fee["in_force"] is True
    assert D(result["pre_tax"]) == D(pre_tax)
    assert D(result["vat"]) == D(vat)
    assert D(result["total"]) == D(total)


def test_line_amounts_of_the_sourced_rows() -> None:
    assert _amounts(_block("CN-GD", "Shenzhen", "2026-03-01")) == {
        "mgmt": D("143080.00"),
        "profit": D("104154.00"),
        "safety": D("74803.40"),
        "training": D("8748.94"),
    }
    gz = _amounts(_block("CN-GD", "Guangzhou", "2026-03-01", {"rates": {"mgmt": "25.71"}}))
    assert gz["mgmt"] == D("179970.00")
    assert gz["profit"] == D("140000.00")
    assert gz["civilised"] + gz["environment"] + gz["temporary"] + gz["safety"] == D("171570.00")
    js = _amounts(_block("CN-JS", None, "2026-03-01"))
    assert js["safety"] == D("65596.00")
    assert js["social_insurance"] + js["housing_fund"] == D("85103.53")
    sc = _amounts(_block("CN-SC", None, "2025-06-01", {"rates": {"zonghe": "25", "guifei": "8"}}))
    assert sc["safety"] == D("133856.80")


def test_a_site_outside_every_listed_jurisdiction_gets_no_programme() -> None:
    assert fees.jurisdiction_for("CN-SH", "Shanghai") is None
    assert fees.fee_block(_profile("CN-SH", "Shanghai", "2026-03-01"), {}, COMPONENTS) is None
    assert fees.jurisdiction_for("DE-BY", None) is None


def test_shenzhen_overrides_the_rest_of_guangdong() -> None:
    assert fees.jurisdiction_for("CN-GD", "Shenzhen") == "CN-GD-SZ"
    assert fees.jurisdiction_for("CN-GD", "深圳") == "CN-GD-SZ"
    assert fees.jurisdiction_for("CN-GD", "Foshan") == "CN-GD"


def test_the_tender_date_picks_the_shenzhen_edition() -> None:
    assert _block("CN-GD", "Shenzhen", "2025-12-31")["result"]["schedule_key"] == "shenzhen_2023"
    assert _block("CN-GD", "Shenzhen", "2026-01-01")["result"]["schedule_key"] == "shenzhen_2025"


def test_unsourced_lines_are_empty_until_the_user_enters_them() -> None:
    fee = _block("CN-JS", None, "2026-07-01")
    assert fee["result"]["schedule_key"] == "jiangsu_2026"
    assert {row["status"] for row in fee["result"]["lines"]} == {"missing"}
    assert all(row["rate"] is None for row in fee["result"]["lines"])


async def test_jiangsu_legacy_is_rejected_after_the_switch() -> None:
    fee = _block("CN-JS", None, "2026-06-01", {"schedule_key": "jiangsu_2014_vat"})
    assert fee["in_force"] is False
    assert fee["successor"] == "jiangsu_2026"
    ids = await _rule_ids(fee)
    assert "cn.fee.schedule_not_in_force" in ids
    assert "cn.fee.guifei_after_abolition" in ids


async def test_sourced_rows_raise_no_fee_findings() -> None:
    for sub, city, tender, settings in [
        ("CN-GD", "Shenzhen", "2026-03-01", {}),
        ("CN-ZJ", None, "2026-03-01", {}),
        ("CN-JS", None, "2026-03-01", {}),
    ]:
        assert await _rule_ids(_block(sub, city, tender, settings)) == []


async def test_user_rates_are_reported_as_unchecked() -> None:
    fee = _block("CN-BJ", None, "2025-10-01", {"rates": {"mgmt": "15", "profit": "7"}})
    ids = await _rule_ids(fee)
    assert ids.count("cn.fee.unsourced_rate") == 2


async def test_safety_fee_below_the_floor_is_a_blocking_error() -> None:
    fee = _block("CN-GD", "Shenzhen", "2026-03-01", {"rates": {"safety": "1.5"}})
    ids = await _rule_ids(fee)
    assert "cn.fee.noncompetitive_below_floor" in ids
    beijing = _block("CN-BJ", None, "2025-10-01", {"options": {"safety_grade": "lvse"}, "rates": {"safety": "23.53"}})
    assert "cn.fee.noncompetitive_below_floor" in await _rule_ids(beijing)


async def test_rate_outside_the_band_is_a_warning() -> None:
    ids = await _rule_ids(_block("CN-GD", "Shenzhen", "2026-03-01", {"rates": {"mgmt": "30"}}))
    assert ids == ["cn.fee.rate_outside_band"]


async def test_labour_factor_and_social_insurance() -> None:
    plain = _block("CN-GD", "Shenzhen", "2026-03-01", {"labour_includes_social_insurance": True})
    assert plain["result"]["labour_factor_applied"] is False
    assert D(plain["result"]["labour"]) == D(600000)
    forced = _block(
        "CN-GD", "Shenzhen", "2026-03-01", {"labour_includes_social_insurance": True, "apply_labour_factor": True}
    )
    assert "cn.labour.double_social_insurance" in await _rule_ids(forced)


async def test_sichuan_safety_base_may_not_take_lump_sum_measures() -> None:
    settings = {
        "rates": {"zonghe": "25", "guifei": "8"},
        "bases": {"safety": {"fenbu": "1", "group:guifei": "1", "provisional_sum": "1", "lump_sum_measures": "1"}},
    }
    ids = await _rule_ids(_block("CN-SC", None, "2025-06-01", settings))
    assert "cn.sc.safety_base_includes_lumpsum" in ids
    assert "cn.sc.safety_base_includes_lumpsum" not in await _rule_ids(
        _block("CN-SC", None, "2025-06-01", {"rates": {"zonghe": "25", "guifei": "8"}})
    )


async def test_mixed_tax_methods_in_one_bill() -> None:
    record = service.build_record(profile={}, lines=[{"ref": "a", "rate_pct": "9"}, {"ref": "b", "rate_pct": "3"}])
    assert "cn.tax.method_mixed" in [r.rule_id for r in await evaluate(record)]


async def test_national_edition_date_where_no_local_switch_is_known() -> None:
    profile = _profile("CN-ZJ", "Hangzhou", "2025-10-01", edition=service.EDITION_2013)
    ids = [r.rule_id for r in await evaluate(service.build_record(profile=profile))]
    assert "cn.standard.edition_mismatch" in ids
    early = _profile("CN-ZJ", "Hangzhou", "2025-08-01", edition=service.EDITION_2013)
    assert "cn.standard.edition_mismatch" not in [
        r.rule_id for r in await evaluate(service.build_record(profile=early))
    ]


async def test_material_price_without_source() -> None:
    record = service.build_record(profile={}, prices={"material_positions": 2, "unsourced_material": ["p1"]})
    assert "cn.price.source_missing" in [r.rule_id for r in await evaluate(record)]


def _pos(total: str, *, resources=None, kind=None, parent=None, quantity="1", **meta) -> SimpleNamespace:
    m = dict(meta)
    if resources is not None:
        m["resources"] = resources
    if kind:
        m["cn_item_kind"] = kind
    return SimpleNamespace(id=uuid.uuid4(), parent_id=parent, total=total, quantity=quantity, metadata_=m)


def test_components_from_stored_positions() -> None:
    positions = [
        _pos(
            "500",
            quantity="10",
            resources=[
                {"type": "labor", "total": "20"},
                {"type": "material", "total": "25", "code": "CWICR-1"},
                {"type": "machinery", "quantity": "1", "unit_rate": "5"},
            ],
        ),
        _pos("80", resources=[{"type": "material", "total": "80"}]),
        _pos("100000", kind="provisional_sum"),
        _pos("3000", kind="specialist_pc_sum"),
        _pos("700", cn_measure_basis="lump_sum"),
        _pos("9"),
    ]
    split = fees.components_from_positions(positions)
    comp = {k: D(v) for k, v in split["components"].items()}
    assert comp == {
        "labour": D(200),
        "material": D(330),
        "plant": D(50),
        "provisional_sum": D(100000),
        "tax_inclusive": D(3000),
        "lump_sum_measures": D(700),
        "other": D(9),
    }
    assert split["material_positions"] == 2
    assert split["unsourced_material"] == [str(positions[1].id)]


def test_edition_move_preview_lists_what_moves_by_hand() -> None:
    record = service.build_record(
        profile={"standard_edition": service.EDITION_2013, "site_subdivision": "CN-ZJ"},
        lines=[
            {"ref": "a", "code": "010101001001", "head": "fenbu"},
            {"ref": "b", "code": "", "head": "guifei"},
        ],
        markup_names=["规费", "管理费"],
    )
    preview = fees.edition_move_preview(record)
    assert preview["needed"] is True
    assert preview["to"] == service.EDITION_2024
    assert preview["guifei_lines"] == ["b"]
    assert preview["guifei_markups"] == ["规费"]
