"""KNU norm codes, graded labour rates and public-funding caps for the Ukraine pack.

The figures are the worked examples of the domain spec, written down before
the code: a graded hourly rate from a monthly estimate wage (Додаток 15 to the
Настанова), a three-line repair estimate taken through the Ukrainian markup
cascade to the total with ПДВ, the same estimate as a contractor bid over the
cap of постанова КМУ №1512, and the combat-zone labour factor.

The core reads every value from ``packs/ukraine-ua``; nothing below is a
Ukrainian number living in the core.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import norm_bases
from app.core.norm_bases import (
    EstimatePricing,
    NormBase,
    NormLine,
    cost_components,
    graded_hourly_rate,
    quantize_money,
)
from app.core.validation.engine import validation_engine
from app.core.validation.messages import is_key_present
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.service import _calculate_markup_amounts

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_PKG = REPO_ROOT / "packs" / "ukraine-ua" / "src" / "openconstructionerp_ukraine_ua"


def _doc(rel: str) -> dict[str, Any]:
    return json.loads((PACK_PKG / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def knu() -> NormBase:
    return NormBase.from_document(_doc("norm_bases/knu.json"), pack_slug="ukraine-ua")


@pytest.fixture(scope="module")
def pricing() -> EstimatePricing:
    return EstimatePricing.from_document(_doc("estimate_pricing.json"), pack_slug="ukraine-ua")


D = Decimal


# ── Worked example 1: the hourly rate from the textbook ──────────────────


def test_example_1_hourly_rates_from_a_monthly_wage(pricing: EstimatePricing) -> None:
    grading = pricing.grading
    assert grading is not None
    wage, hours = D("18570.02"), D("171.75")
    base = graded_hourly_rate(wage, hours, D("3.8"), grading)
    assert (base.base_rate, base.grade_one_rate, base.rate) == (D("108.12"), D("82.66"), D("108.12"))
    assert graded_hourly_rate(wage, hours, D("5.2"), grading).rate == D("131.68")
    assert graded_hourly_rate(wage, hours, D("7.0"), grading).rate == D("171.52")


def test_the_coefficient_table_reproduces_every_value_the_source_quotes(pricing: EstimatePricing) -> None:
    grading = pricing.grading
    assert grading is not None
    assert grading.base_grade == D("3.8")
    quoted = {"1.0": "1.000", "3.5": "1.263", "3.8": "1.308", "5.2": "1.593", "7.0": "2.075"}
    for grade, k in quoted.items():
        assert grading.coefficient(D(grade)) == D(k), grade


# ── Worked example 2: repair of a communal flat, public funds, Kyiv ──────


def _flat_lines(pricing: EstimatePricing) -> list[NormLine]:
    grading = pricing.grading
    assert grading is not None
    wage, hours = D("30000"), D("174")
    v38 = graded_hourly_rate(wage, hours, D("3.8"), grading)
    v35 = graded_hourly_rate(wage, hours, D("3.5"), grading)
    assert (v38.rate, v38.grade_one_rate, v35.rate) == (D("172.41"), D("131.81"), D("166.48"))
    return [
        # A. plaster walls 40 m2
        NormLine("labor", D("44"), v35.rate),
        NormLine("material", D("400"), D("9.50")),
        NormLine("machine", D("0.8"), D("250")),
        # B. floor tiles 12 m2
        NormLine("labor", D("21.6"), v38.rate),
        NormLine("material", D("12.6"), D("520")),
        NormLine("material", D("60"), D("14")),
        # C. door replacement 1 pc
        NormLine("labor", D("3.2"), v38.rate),
        NormLine("material", D("1"), D("6800.00")),
    ]


def _ua_cascade(direct: Decimal, zvv: str = "10") -> list[Decimal]:
    markups = [
        SimpleNamespace(id=None, is_active=True, apply_to=a, markup_type="percentage", percentage=p)
        for a, p in (
            ("direct_cost", zvv),  # ЗВВ
            ("cumulative", "1.8"),  # risk, housing, on chapters 1-12
            ("direct_cost", "3"),  # administrative
            ("direct_cost", "15"),  # profit
            ("cumulative", "20"),  # ПДВ
        )
    ]
    return [quantize_money(amount) for _, amount in _calculate_markup_amounts(direct, markups)]


def test_example_2_direct_costs(pricing: EstimatePricing) -> None:
    totals = cost_components(_flat_lines(pricing))
    assert totals["labor"] == D("11600.89")
    assert totals["material"] == D("17992.00")
    assert totals["machine"] == D("200.00")
    assert totals["direct"] == D("29792.89")


def test_example_2_cascade_to_the_total_with_vat(pricing: EstimatePricing) -> None:
    direct = cost_components(_flat_lines(pricing))["direct"]
    zvv, risk, admin, profit, vat = _ua_cascade(direct)
    assert (zvv, risk, admin, profit) == (D("2979.29"), D("589.90"), D("893.79"), D("4468.93"))
    net = direct + zvv + risk + admin + profit
    assert net == D("38724.80")
    assert vat == D("7744.96")
    assert net + vat == D("46469.76")


def test_example_3_combat_zone_doubles_labour_only(pricing: EstimatePricing) -> None:
    factor = pricing.location_factor("active_hostilities")
    assert factor is not None and factor.factor == D("2.0")
    assert pricing.location_factor("possible_hostilities").factor == D("1.5")  # type: ignore[union-attr]
    totals = cost_components(_flat_lines(pricing), labour_factor=factor.factor)
    assert totals["labor"] == D("23201.78")
    assert totals["material"] == D("17992.00")
    assert totals["direct"] == D("41393.78")


# ── Norm codes ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "status", "suggested"),
    [
        ("КБ1-13-1", "ok", None),
        ("КБМ2-1-4", "ok", None),
        ("КР15-12-3", "ok", None),
        ("KP15-12-3", "ok", None),  # typed with Latin look-alike letters
        ("РН15-12-3", "legacy", "КР15-12-3"),
        ("Е1-13-1", "legacy", "КБ1-13-1"),
        ("ЕН11-2-1", "legacy", "КБ11-2-1"),
        ("15-02-036-1", "shape", None),
        ("КБ1-13", "shape", None),
    ],
)
def test_code_check(knu: NormBase, code: str, status: str, suggested: str | None) -> None:
    check = knu.check(code)
    assert (check.status, check.suggested) == (status, suggested)


def test_grade_scale(pricing: EstimatePricing) -> None:
    grading = pricing.grading
    assert grading is not None
    assert grading.in_range(D("3.8")) and grading.in_range(D("8.0"))
    assert not grading.in_range(D("3.85"))
    assert not grading.in_range(D("0.9"))
    assert not grading.in_range(D("8.1"))


# ── Validation rules on a bill ───────────────────────────────────────────


@pytest.fixture
def ua_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the Ukraine pack from the source checkout for country UA only."""
    from app.core.partner_pack.discovery import get_pack_by_slug

    pack = get_pack_by_slug("ukraine-ua")
    assert pack is not None, "the source-checkout pack is not discoverable"
    monkeypatch.setattr(norm_bases, "pack_for_country", lambda c: pack if c == "UA" else None)


def _position(code: str | None, resources: list[dict[str, Any]] | None = None, ordinal: str = "1") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "ordinal": ordinal,
        "description": "Штукатурення стін",
        "unit": "m2",
        "quantity": 40,
        "unit_rate": 300,
        "classification": {"knu": code} if code else {},
        "metadata": {"resources": resources or []},
    }


def _markups(zvv: str) -> list[dict[str, Any]]:
    return [
        {"id": "m1", "name": "Загальновиробничі витрати", "category": "overhead", "percentage": zvv},
        {"id": "m2", "name": "Кошти на покриття ризиків", "category": "contingency", "percentage": "1.8"},
        {"id": "m3", "name": "Адміністративні витрати", "category": "overhead", "percentage": "3"},
        {"id": "m4", "name": "Кошторисний прибуток", "category": "profit", "percentage": "15"},
    ]


def _run(data: dict[str, Any], rule_sets: list[str], country: str = "UA", settings: dict | None = None):
    register_builtin_rules()
    payload = {**data, "project_record": {"country_code": country, "estimate_pricing": settings}}
    return asyncio.run(
        validation_engine.validate(
            data=payload,
            rule_sets=rule_sets,
            target_type="boq",
            target_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            metadata={"locale": "en"},
        )
    )


def _failed(report: Any) -> list[tuple[str, str]]:
    return sorted((r.rule_id, r.severity) for r in report.results if not r.passed)


def test_example_3_contractor_bid_over_the_cap_is_an_error_and_private_is_not(ua_pack: None) -> None:
    data = {"positions": [], "markups": _markups("12")}
    public = _run(data, ["public_funding"], settings={"funding_class": "public", "estimate_role": "contractor"})
    assert _failed(public) == [("public_funding.markup_cap", "error")]
    msg = next(r.message for r in public.results if not r.passed)
    assert "12" in msg and "10" in msg and "1512" in msg
    private = _run(data, ["public_funding"], settings={"funding_class": "private", "estimate_role": "contractor"})
    assert _failed(private) == []


def test_investor_estimate_on_public_funds_sits_exactly_at_the_caps(ua_pack: None) -> None:
    settings = {"funding_class": "public", "estimate_role": "investor"}
    assert _failed(_run({"positions": [], "markups": _markups("10")}, ["public_funding"], settings=settings)) == []
    report = _run({"positions": [], "markups": _markups("9")}, ["public_funding"], settings=settings)
    assert _failed(report) == [("public_funding.investor_exact", "warning")]


def test_example_3_code_and_grade_findings(ua_pack: None) -> None:
    labour = {"type": "labor", "name": "Затрати праці", "unit": "люд.-год", "quantity": "1.1", "grade": "3.5"}
    positions = [
        _position("КР15-12-3", [labour], "1"),
        _position("РН15-12-3", [labour], "2"),
        _position("15-02-036-1", [labour], "3"),
        _position("КБ1-13-1", [{**labour, "grade": "3.85"}], "4"),
        _position("КБ1-13-2", [], "5"),
        _position(None, [], "6"),
    ]
    report = _run({"positions": positions}, ["norm_base"])
    failed = {(r.rule_id, r.details.get("code") or r.details.get("grade")) for r in report.results if not r.passed}
    assert ("norm_base.legacy_prefix", "РН15-12-3") in failed
    assert ("norm_base.code_shape", "15-02-036-1") in failed
    assert ("norm_base.grade_range", "3.85") in failed
    assert ("norm_base.resource_breakdown", "КБ1-13-2") in failed
    assert ("norm_base.code_present", None) in failed
    legacy = next(r for r in report.results if r.rule_id == "norm_base.legacy_prefix" and not r.passed)
    assert legacy.details["suggested"] == "КР15-12-3"
    assert "КР15-12-3" in legacy.message
    severities = {r.rule_id: r.severity for r in report.results}
    assert severities["norm_base.code_shape"] == "warning"
    assert severities["norm_base.grade_range"] == "error"


def test_public_funds_ask_for_three_offers_per_material(ua_pack: None) -> None:
    quotes = [{"supplier": f"S{i}", "price": "9.50"} for i in range(3)]
    positions = [
        _position("КР15-12-3", [{"type": "material", "code": "plaster", "quantity": "10", "unit_rate": "9.5"}], "1"),
        _position(
            "КР15-12-4",
            [{"type": "material", "code": "tile", "quantity": "1", "price_evidence": {"quotes": quotes}}],
            "2",
        ),
        _position(
            "КР15-12-5",
            [{"type": "material", "code": "door", "quantity": "1", "price_evidence": {"report_ref": "doc-17"}}],
            "3",
        ),
    ]
    report = _run({"positions": positions}, ["public_funding"], settings={"funding_class": "public"})
    assert [(r.details["material"], r.passed) for r in report.results] == [
        ("plaster", False),
        ("tile", True),
        ("door", True),
    ]
    private = _run({"positions": positions}, ["public_funding"], settings={"funding_class": "private"})
    assert private.results == []


def test_the_rules_say_nothing_where_no_pack_supplies_a_norm_base(ua_pack: None) -> None:
    data = {"positions": [_position("15-02-036-1")], "markups": _markups("30")}
    report = _run(data, ["norm_base", "public_funding"], country="DE", settings={"funding_class": "public"})
    assert report.results == []


@pytest.mark.parametrize(
    "key",
    [
        "norm_base.code_present.fail",
        "norm_base.code_shape.fail",
        "norm_base.legacy_prefix.fail",
        "norm_base.resource_breakdown.fail",
        "norm_base.grade_range.fail",
        "public_funding.markup_cap.fail",
        "public_funding.investor_exact.fail",
        "public_funding.material_price_evidence.fail",
    ],
)
@pytest.mark.parametrize("locale", ["en", "uk", "ru", "de", "ar", "zh"])
def test_messages_exist(key: str, locale: str) -> None:
    assert is_key_present(key, locale)


# ── The pack and the profile the client reads ────────────────────────────


def test_the_pack_declares_its_norm_data_and_ships_the_files() -> None:
    from app.core.partner_pack.discovery import get_pack_by_slug, read_pack_file

    pack = get_pack_by_slug("ukraine-ua")
    assert pack is not None
    assert pack.norm_bases == ["norm_bases/knu.json"]
    assert pack.estimate_pricing == "estimate_pricing.json"
    assert {"norm_base", "public_funding"} <= set(pack.validation_rule_sets)
    assert read_pack_file("ukraine-ua", "norm_bases/knu.json") is not None
    assert read_pack_file("ukraine-ua", "estimate_pricing.json") is not None


def test_profile_is_offered_only_where_a_pack_supplies_it(ua_pack: None) -> None:
    from app.modules.norm_pricing.service import build_profile, labour_rates

    assert build_profile("DE", {}, "en").available is False
    profile = build_profile("UA", {"funding_class": "public"}, "uk")
    assert profile.available and profile.base_grade == "3.8"
    assert [f.key for f in profile.funding_classes] == ["public", "private"]
    assert {c.cap_percent for c in profile.funding_classes[0].markup_caps} == {"10", "3", "15"}
    assert profile.funding_classes[0].label == "Бюджетні або державні кошти"
    rates = labour_rates(
        "UA",
        {"estimate_wage": "30000", "monthly_hours": "174", "labour_location": "active_hostilities"},
        ["3.5", "3.8", "7.5"],
    )
    assert [(r.grade, r.rate, r.rate_with_location) for r in rates.rates] == [
        ("3.5", "166.48", "332.96"),
        ("3.8", "172.41", "344.82"),
    ]
    assert rates.missing_grades == ["7.5"]
