# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the compute-estimate math pipeline (pure parts).

``MethodologyService.compute_estimate`` is a thin orchestration over three
PURE steps: build the cascade spec from a methodology config, resolve the leaf
bases from per-resource-type totals, and run the cascade engine. The service
itself needs a DB (project lookup, optional BOQ aggregation) so it is verified
in CI; this module exercises the exact pure pipeline it runs, on fixtures with
hand-computed expected values, so the arithmetic is locked down on local Python
3.11 too.

The helper :func:`_compute` mirrors the service's resolve-then-run logic
including the "no base mapping -> single direct base" fallback.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.methodology import templates as t
from app.modules.methodology.bases import resolve_bases
from app.modules.methodology.cascade import compute_cascade


def _compute(slug: str, resource_totals: dict[str, Decimal]):
    """Resolve + run a built-in template exactly as compute_estimate does."""
    tpl = t.get_template(slug)
    base_mapping = tpl["base_mapping"]
    if base_mapping:
        bases = resolve_bases(base_mapping, resource_totals)
    else:
        total = sum(resource_totals.values(), Decimal(0))
        bases = {"direct": total}
    spec = t.build_cascade_spec(
        slug=tpl["slug"],
        currency=tpl["currency"],
        decimals=tpl["decimals"],
        composites=tpl["composites"],
        cascade_steps=tpl["cascade_steps"],
    )
    return compute_cascade(spec, bases)


def _amounts(result) -> dict[str, Decimal]:
    return {s.key: s.amount for s in result.steps}


# ── International flat methodology ────────────────────────────────────────


def test_international_flat_overhead_then_profit() -> None:
    """labor 100 + material 100, overhead 12 %, profit 8 %, VAT 0 %.

    direct = 200; overhead = 24; profit = 8 % of 224 = 17.92; VAT = 0.
    grand = 241.92.
    """
    r = _compute(
        "international",
        {
            "labor": Decimal("100"),
            "material": Decimal("100"),
            "equipment": Decimal("0"),
            "subcontractor": Decimal("0"),
        },
    )
    assert r.direct_total == Decimal("200.00")
    amts = _amounts(r)
    assert amts["overhead"] == Decimal("24.00")
    assert amts["profit"] == Decimal("17.92")
    assert amts["vat"] == Decimal("0.00")
    assert r.grand_total == Decimal("241.92")


def test_germany_vat_applies_on_top_of_the_whole_zuschlag() -> None:
    """DE: the DACH Zuschlagskalkulation on labor 1000 + material 0.

    The claim under test has not changed: the tax step prices everything before
    it, not the direct cost alone. The stack it prices has. Germany used to be
    three flat steps of 13 / 6 / 19 for a grand total of 1425.38, which was the
    methodology catalogue disagreeing with the stack a German bill was actually
    seeded with. It now derives from that stack, so the numbers here are the
    VOB/B ones: BGK 10 %, AGK 8 %, Wagnis 2 % and Gewinn 3 % all on direct cost,
    then MwSt 19 % on the sum of all of them.

    direct = 1000; BGK = 100; AGK = 80; Wagnis = 20; Gewinn = 30;
    subtotal = 1230; MwSt = 19 % of 1230 = 233.70. grand = 1463.70.
    """
    r = _compute("germany", {"labor": Decimal("1000")})
    amts = _amounts(r)
    assert amts["s1_overhead"] == Decimal("100.00")
    assert amts["s2_overhead"] == Decimal("80.00")
    assert amts["s3_contingency"] == Decimal("20.00")
    assert amts["s4_profit"] == Decimal("30.00")
    assert amts["s5_tax"] == Decimal("233.70")
    assert r.grand_total == Decimal("1463.70")


# ── Uzbekistan cascading methodology ─────────────────────────────────────


def test_uzbekistan_smr_equipment_split_and_feed_forward() -> None:
    """UZ reference split with non-zero step rates.

    bases: labor 100, machinery 50, materials 150, equipment 200.
    SMR = 300; direct = 500.
    Rates set: temp/winter 10 %, contractor 5 %, contingency 2 %
    (insurance 0.32 %, VAT 12 % are the template defaults).

      temp_winter   = 10 % of SMR(300)                         = 30.00
      contractor    = 5 % of (300 + 30 = 330)                  = 16.50
      insurance     = 0.32 % of (300 + 200 + 30 + 16.50=546.50)= 1.75
      contingency   = 2 % of (546.50 + 1.75 = 548.25)          = 10.97
      vat           = 12 % of (548.25 + 10.97 = 559.22)        = 67.11
    grand = 500 + 30 + 16.50 + 1.75 + 10.97 + 67.11 = 626.33.
    """
    import copy

    tpl = copy.deepcopy(t.get_template("uzbekistan"))
    for s in tpl["cascade_steps"]:
        if s["key"] == "other_temp_winter":
            s["rate"] = "10"
        elif s["key"] == "contractor_other":
            s["rate"] = "5"
        elif s["key"] == "contingency":
            s["rate"] = "2"

    spec = t.build_cascade_spec(
        slug=tpl["slug"],
        currency=tpl["currency"],
        decimals=tpl["decimals"],
        composites=tpl["composites"],
        cascade_steps=tpl["cascade_steps"],
    )
    bases = resolve_bases(
        tpl["base_mapping"],
        {
            "labor": Decimal("100"),
            "machinery": Decimal("50"),
            "material": Decimal("150"),
            "equipment": Decimal("200"),
        },
    )
    r = compute_cascade(spec, bases)

    assert r.composites["SMR"] == Decimal("300.00")
    assert r.direct_total == Decimal("500.00")
    amts = _amounts(r)
    assert amts["other_temp_winter"] == Decimal("30.00")
    assert amts["contractor_other"] == Decimal("16.50")
    assert amts["insurance"] == Decimal("1.75")
    assert amts["contingency"] == Decimal("10.97")
    assert amts["vat"] == Decimal("67.11")
    assert r.grand_total == Decimal("626.33")


def test_uzbekistan_defaults_only_insurance_and_vat_fire() -> None:
    """With template default rates, only insurance (0.32 %) and VAT (12 %) are

    non-zero. labor 0, machinery 0, materials 1000, equipment 0:
      SMR = 1000; direct = 1000.
      temp_winter = 0; contractor = 0.
      insurance = 0.32 % of 1000 = 3.20.
      contingency = 0.
      vat = 12 % of (1000 + 3.20 = 1003.20) = 120.384 -> 120.38.
    grand = 1000 + 3.20 + 120.38 = 1123.58.
    """
    r = _compute("uzbekistan", {"material": Decimal("1000")})
    amts = _amounts(r)
    assert amts["other_temp_winter"] == Decimal("0.00")
    assert amts["insurance"] == Decimal("3.20")
    assert amts["contingency"] == Decimal("0.00")
    assert amts["vat"] == Decimal("120.38")
    assert r.grand_total == Decimal("1123.58")


def test_equipment_skips_smr_steps_but_carries_insurance_vat() -> None:
    """Pure equipment (no SMR): temp/winter and contractor bases are zero, but

    insurance and VAT still apply to the equipment amount. equipment 1000:
      SMR = 0; direct = 1000.
      temp_winter = 10 % of 0 = 0; contractor = 5 % of 0 = 0.
      insurance = 0.32 % of (0 + 1000 + 0 + 0) = 3.20.
      vat = 12 % of (1000 + 3.20) = 120.38.  (contingency default 0)
    grand = 1123.58.
    """
    import copy

    tpl = copy.deepcopy(t.get_template("uzbekistan"))
    for s in tpl["cascade_steps"]:
        if s["key"] == "other_temp_winter":
            s["rate"] = "10"
        elif s["key"] == "contractor_other":
            s["rate"] = "5"
    spec = t.build_cascade_spec(
        slug=tpl["slug"],
        currency=tpl["currency"],
        decimals=tpl["decimals"],
        composites=tpl["composites"],
        cascade_steps=tpl["cascade_steps"],
    )
    bases = resolve_bases(tpl["base_mapping"], {"equipment": Decimal("1000")})
    r = compute_cascade(spec, bases)
    amts = _amounts(r)
    assert amts["other_temp_winter"] == Decimal("0.00")
    assert amts["contractor_other"] == Decimal("0.00")
    assert amts["insurance"] == Decimal("3.20")
    assert amts["vat"] == Decimal("120.38")


# ── Edge cases ────────────────────────────────────────────────────────────


def test_empty_resource_totals_yield_zero_estimate() -> None:
    """No resources -> all-zero direct and grand totals (never a crash)."""
    r = _compute("international", {})
    assert r.direct_total == Decimal("0.00")
    assert r.grand_total == Decimal("0.00")
    assert all(s.amount == Decimal("0.00") for s in r.steps)


def test_unmapped_resource_types_are_ignored() -> None:
    """A resource type absent from base_mapping contributes nothing.

    The international mapping has no 'overheadphantom' token, so it is dropped;
    only labor feeds the cascade.
    """
    r = _compute(
        "international",
        {"labor": Decimal("100"), "overheadphantom": Decimal("999")},
    )
    assert r.direct_total == Decimal("100.00")


def test_no_base_mapping_falls_back_to_single_direct_base() -> None:
    """A methodology with an empty base_mapping sums all resources into 'direct'.

    Mirrors the service fallback. A flat overhead/profit cascade over that
    single base must still compute. We build an ad-hoc spec with one composite-
    free 'direct' base.
    """
    from app.modules.methodology.cascade import CascadeSpec, MarkupStep

    spec = CascadeSpec(
        slug="custom",
        currency="USD",
        decimals=2,
        composites={},
        steps=(
            MarkupStep(
                key="overhead",
                label="Overhead",
                category="overhead",
                kind="percentage",
                rate=Decimal("10"),
                base=("direct",),
            ),
        ),
    )
    total = sum({"labor": Decimal("100"), "material": Decimal("100")}.values(), Decimal(0))
    bases = {"direct": total}
    r = compute_cascade(spec, bases)
    assert r.direct_total == Decimal("200.00")
    assert _amounts(r)["overhead"] == Decimal("20.00")
    assert r.grand_total == Decimal("220.00")


def test_currency_is_never_blended_currency_passthrough() -> None:
    """The spec carries the methodology currency verbatim; the engine never

    converts. (A defensive check that build + compute preserve currency.)
    """
    r = _compute("united_arab_emirates", {"labor": Decimal("100")})
    # Result object does not carry currency, but the spec used does; assert the
    # template currency is the AED we expect so a future edit cannot silently
    # blend it with another template's currency.
    assert t.get_template("united_arab_emirates")["currency"] == "AED"
    assert r.direct_total == Decimal("100.00")
