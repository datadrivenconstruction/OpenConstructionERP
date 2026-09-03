# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The India pack: does what the manifest promises reach an Indian estimate?

India was the only member of the jurisdiction cohort with no pack test of its
own. China, the UK, Russia and Hungary each have one, and each of those found
something the wiring could not: a rule reading a field nothing writes passes
every test built from its own fixtures.

What this file measures, in order of how much it is worth:

* The two engines that price a country agree to the rupee. The bill path
  (``markup_templates.resolve_region_lines``) and the methodology catalogue
  (``methodology.templates``) have been found to disagree for other countries,
  and a customer comparing two totals is how that gets discovered otherwise.
* GST at 18 and the BOCW labour cess at 1 both survive into both of them. The
  cess is the line most easily lost, because it is not a consumption tax and
  the reconciliation between the two engines is written around the tax line.
* Each India demo carries exactly one markup filed ``tax``. The BOQ editor
  answers "what is the tax rate on this bill" with ``getVatRateFromMarkups``,
  which takes the first active percentage markup filed ``tax`` and stops, so a
  second one silently decides the answer. The exports do not work that way and
  should not be cited here: ``_tax_split`` sums every active tax row, having
  been corrected for Brazil, which stacks two. Both India demos filed the 1
  percent cess as ``tax``
  ahead of the 18 percent GST, and India was the only region in the shipped
  catalogue that did. The regional table has always filed the cess ``other``,
  and the Argentine block cites the Indian line by name as the precedent for
  doing so, so the demos were the half that disagreed.
* The shipped Delhi demo clears the rule sets the pack switches on.

The count of declared-but-unbuilt rule ids is deliberately not asserted here.
It is 119 and it is pinned in ``test_uk_pack.py`` alongside every other pack's,
where the two directions that matter (a clean pack going dirty, a fixed pack
leaving a stale line) are already stated as one property.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.demo_packs import PACK_TEMPLATES
from app.core.validation.engine import validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.markup_templates import (
    NON_SINGLE_TAX_REGIONS,
    REGION_BY_COUNTRY,
    region_key_for_country,
    region_lines_for_country,
    resolve_region_lines,
)
from app.modules.methodology.templates import TEMPLATES_BY_SLUG

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "packs" / "india-cpwd" / "src" / "openconstructionerp_india_cpwd"

#: One crore of direct cost. Round, and large enough that a percentage point
#: is visible in the numbers a failure prints.
DIRECT_COST = Decimal("10000000")

#: The demo templates the shipped catalogue keys to India.
INDIA_DEMO_IDS = ("govt-building-delhi", "it-park-bangalore")

#: The two India stacks exactly as they shipped before the cess was refiled.
#: The fix changed one field of one line in each. Pinning the rest is what
#: keeps that claim checkable: a percentage or an ``apply_to`` altered later
#: under the same heading would move money, and it should land here rather
#: than in a customer's bill.
MARKUPS_BEFORE_REFILING: dict[str, tuple[tuple[str, float, str, str], ...]] = {
    "govt-building-delhi": (
        ("Contractor Overheads & Profit (CP&OH)", 15.0, "overhead", "direct_cost"),
        ("Contingencies", 3.0, "contingency", "direct_cost"),
        ("Building & Other Construction Workers Cess (1%)", 1.0, "tax", "direct_cost"),
        ("Goods & Services Tax (GST 18%)", 18.0, "tax", "cumulative"),
    ),
    "it-park-bangalore": (
        ("Contractor Overheads & Profit (CP&OH)", 14.0, "overhead", "direct_cost"),
        ("Design & Estimation Contingency", 4.0, "contingency", "direct_cost"),
        ("Building & Other Construction Workers Cess (1%)", 1.0, "tax", "direct_cost"),
        ("Goods & Services Tax (GST 18%)", 18.0, "tax", "cumulative"),
    ),
}

#: What each demo came to with its markups applied, measured before the fix.
NET_TOTAL_BEFORE_REFILING = {
    "govt-building-delhi": Decimal("476579722.78"),
    "it-park-bangalore": Decimal("6257543832.05"),
}


@pytest.fixture(scope="module")
def manifest() -> Any:
    """The pack's real on-disk manifest, loaded the way the loader loads it."""
    spec = importlib.util.spec_from_file_location("_india_manifest", PACK / "manifest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def _india_demos() -> list[Any]:
    """The shipped demo templates whose region is India."""
    return [t for t in PACK_TEMPLATES if t.region == "IN"]


def _demo_payload(demo_id: str) -> dict[str, Any]:
    """The shipped demo template, in the shape the payload builder produces.

    Assembled from the template rather than from a fixture on purpose: the
    question is whether the estimate an Indian user is actually handed passes
    the checks the pack actually switches on.
    """
    template = next(t for t in PACK_TEMPLATES if t.demo_id == demo_id)
    positions: list[dict[str, Any]] = []
    for ordinal, title, classification, items in template.sections:
        positions.append(
            {
                "id": f"s-{ordinal}",
                "ordinal": ordinal,
                "description": title,
                "classification": classification,
                "type": "section",
            }
        )
        for item_ordinal, description, unit, quantity, rate, item_classification in items:
            positions.append(
                {
                    "id": f"p-{item_ordinal}",
                    "ordinal": item_ordinal,
                    "description": description,
                    "unit": unit,
                    "quantity": quantity,
                    "unit_rate": str(rate),
                    "classification": item_classification,
                    "parent_id": f"s-{ordinal}",
                }
            )
    markups = [
        {"name": name, "category": category, "percentage": str(percentage), "apply_to": apply_to, "is_active": True}
        for name, percentage, category, apply_to in template.markups
    ]
    return {
        "positions": positions,
        "boq": {"name": template.boq_name, "metadata": template.boq_metadata, "currency": template.currency},
        "markups": markups,
    }


def _total_from_lines(lines: list[dict[str, Any]], direct: Decimal) -> Decimal:
    """Price a regional markup stack, the way the bill seeder applies it."""
    running = direct
    for line in lines:
        base = direct if str(line["apply_to"]) == "direct_cost" else running
        running += base * Decimal(str(line["percentage"])) / Decimal(100)
    return running


def _total_from_steps(steps: list[dict[str, Any]], direct: Decimal) -> Decimal:
    """Price a methodology cascade, the way a cascade names its own base."""
    amounts: dict[str, Decimal] = {"direct": direct}
    for step in steps:
        base = sum((amounts[key] for key in step["base"]), Decimal(0))
        amounts[step["key"]] = base * Decimal(str(step["rate"])) / Decimal(100)
    return sum(amounts.values(), Decimal(0))


# ── The two engines ──────────────────────────────────────────────────────


def test_india_is_a_country_the_regional_table_states_a_method_for() -> None:
    """Without this the rest is vacuous: an unstated country gets the neutral
    international stack and is told so, which is a different pack."""
    assert REGION_BY_COUNTRY.get("IN") == "IN"
    assert region_key_for_country("IN") == "IN"
    assert region_lines_for_country("IN") is not None


def test_the_bill_path_and_the_methodology_catalogue_price_india_the_same() -> None:
    """The claim ``_derived_steps`` makes, tested in money rather than in shape.

    Two engines price a country. If they disagree, nothing goes red: the
    customer finds it by comparing an estimate against a bill.
    """
    template = TEMPLATES_BY_SLUG["india"]
    assert template["derived_from_region"] == "IN", (
        "the India methodology template stopped being derived from the regional table, "
        "so it is now stating a second opinion on the same country"
    )
    bill_lines = resolve_region_lines("IN", vat_rate=template["vat_rate"])
    bill_total = _total_from_lines(bill_lines, DIRECT_COST)
    methodology_total = _total_from_steps(template["cascade_steps"], DIRECT_COST)
    assert bill_total == methodology_total, (
        f"an Indian project priced through the bill comes to {bill_total} and through the "
        f"methodology catalogue to {methodology_total} on the same {DIRECT_COST} of direct cost"
    )


def test_gst_and_the_labour_cess_both_reach_both_engines() -> None:
    """The two statutory lines an Indian bill has to carry.

    GST is the works-contract rate. The cess is 1 percent under the Building
    and Other Construction Workers Welfare Cess Act 1996, and it is the line
    most easily lost: it is not a consumption tax, so the machinery that
    reconciles the two engines is written around the tax line rather than
    around it.
    """
    template = TEMPLATES_BY_SLUG["india"]
    bill_lines = resolve_region_lines("IN", vat_rate=template["vat_rate"])

    bill_tax = [line for line in bill_lines if line["category"] == "tax"]
    assert [line["percentage"] for line in bill_tax] == ["18"], "India's bill stack lost its 18 percent GST line"
    bill_cess = [line for line in bill_lines if "cess" in str(line["name"]).lower()]
    assert len(bill_cess) == 1, "India's bill stack lost the BOCW labour cess"
    assert Decimal(str(bill_cess[0]["percentage"])) == Decimal("1.0")
    assert bill_cess[0]["category"] == "other", (
        "the cess is filed 'other' so the region keeps exactly one tax line and a project-level "
        "rate override lands on GST alone; the Argentine block cites this line as its precedent"
    )

    steps = template["cascade_steps"]
    step_tax = [step for step in steps if step["category"] == "tax"]
    assert [step["rate"] for step in step_tax] == ["18"], "India's methodology cascade lost its GST step"
    step_cess = [step for step in steps if "cess" in str(step["label"]).lower()]
    assert len(step_cess) == 1, "India's methodology cascade lost the BOCW labour cess"
    assert Decimal(str(step_cess[0]["rate"])) == Decimal("1.0")


def test_a_project_rate_override_moves_gst_and_leaves_the_cess_alone() -> None:
    """A reduced GST rate is a real Indian case: 12 percent on a government
    works contract, 5 on some affordable housing. The cess is fixed by a
    different statute and must not follow the number the user typed.

    India is not in ``NON_SINGLE_TAX_REGIONS``, so the override does run here;
    that it lands on one line only is what the ``other`` filing buys.
    """
    assert "IN" not in NON_SINGLE_TAX_REGIONS
    lines = resolve_region_lines("IN", vat_rate="12")
    overridden = [line["name"] for line in lines if line["vat_override"]]
    assert overridden == ["GST"], f"a project GST override touched {overridden}"
    cess = next(line for line in lines if "cess" in str(line["name"]).lower())
    assert Decimal(str(cess["percentage"])) == Decimal("1.0")


# ── The shipped demos ────────────────────────────────────────────────────


def test_the_shipped_india_demos_are_the_ones_this_file_knows_about() -> None:
    """A demo added for India without being read here would be untested by the
    assertion below, which is the one that has already caught something."""
    assert sorted(t.demo_id for t in _india_demos()) == sorted(INDIA_DEMO_IDS)


def test_no_shipped_demo_anywhere_carries_two_tax_markups() -> None:
    """The property India turned out to be the first instance of.

    Every reader that answers "what is the tax rate on this bill" answers it
    the same way: walk the markups, take the first active one filed ``tax``,
    stop. ``pdf_export`` does exactly that at three places, and each of them
    then applies that rate to a net total which already contains every markup.
    A second line filed ``tax`` therefore does not add a levy, it renames one
    and charges it twice. India was the only region in the catalogue carrying
    two; the guard is written over all of them because the next one will not
    be India, and nothing else in the tree states this.
    """
    offenders = {
        template.demo_id: [
            (name, percentage) for name, percentage, category, _ in template.markups if category == "tax"
        ]
        for template in PACK_TEMPLATES
        if len([markup for markup in template.markups if markup[2] == "tax"]) > 1
    }
    assert not offenders, (
        f"{len(offenders)} of {len(PACK_TEMPLATES)} shipped demos carry more than one markup filed "
        f"'tax', and a bill export names the first of them as the rate: {offenders}"
    )


@pytest.mark.parametrize("demo_id", INDIA_DEMO_IDS)
def test_an_india_demo_carries_exactly_one_tax_markup(demo_id: str) -> None:
    """The finding this file was written for.

    ``pdf_export`` answers "what is the tax rate on this bill" by taking the
    first active markup whose category is ``tax`` and breaking out of the loop.
    Both India demos filed the 1 percent BOCW cess as ``tax`` ahead of the
    18 percent GST, so the exported bill named 1 percent as the tax rate and
    added it on top of a net total that already contained the real GST. India
    was the only region in the shipped catalogue with two tax lines.
    """
    template = next(t for t in PACK_TEMPLATES if t.demo_id == demo_id)
    tax_lines = [(name, percentage) for name, percentage, category, _ in template.markups if category == "tax"]
    assert len(tax_lines) == 1, (
        f"{demo_id} carries {len(tax_lines)} markups filed 'tax' ({tax_lines}); the PDF export reads "
        f"the first of them as the bill's tax rate, so it would report {tax_lines[0][1]} percent"
    )
    assert Decimal(str(tax_lines[0][1])) == Decimal("18.0"), (
        f"{demo_id} does not carry GST at 18 percent as its tax line"
    )


@pytest.mark.parametrize("demo_id", INDIA_DEMO_IDS)
def test_an_india_demo_still_carries_the_labour_cess(demo_id: str) -> None:
    """Refiling the cess must not delete it. It is a statutory levy on the cost
    of construction and it belongs on the bill whatever category it sits in."""
    template = next(t for t in PACK_TEMPLATES if t.demo_id == demo_id)
    cess = [m for m in template.markups if "cess" in m[0].lower()]
    assert len(cess) == 1, f"{demo_id} lost the BOCW labour cess"
    assert Decimal(str(cess[0][1])) == Decimal("1.0")
    assert cess[0][2] == "other", "the cess is filed 'other', matching India's own regional stack"


@pytest.mark.parametrize("demo_id", INDIA_DEMO_IDS)
def test_refiling_the_cess_was_a_relabelling_and_nothing_else(demo_id: str) -> None:
    """What the fix claims about itself, checked against the stack it replaced.

    Comparing the new stack against a relabelled copy of itself would prove
    nothing. Money is a function of ``percentage`` and ``apply_to``, a pricing
    routine cannot see ``category`` at all, and both sides of such a comparison
    would come out equal whatever had been done to the file. The claim only
    means something against the lines as they actually shipped, so those are
    written out above and this reads them.
    """
    template = next(t for t in PACK_TEMPLATES if t.demo_id == demo_id)
    before = MARKUPS_BEFORE_REFILING[demo_id]
    after = tuple(tuple(markup) for markup in template.markups)

    assert [(name, pct, apply_to) for name, pct, _category, apply_to in after] == [
        (name, pct, apply_to) for name, pct, _category, apply_to in before
    ], (
        f"{demo_id} changed more than the filing of a markup: a name, a percentage or an "
        f"apply_to moved, and those three are what the money is made of"
    )
    differing = [i for i, (was, now) in enumerate(zip(before, after, strict=True)) if was != now]
    assert len(differing) == 1, f"{demo_id} refiled {len(differing)} markups; the fix touched one"
    assert (before[differing[0]][2], after[differing[0]][2]) == ("tax", "other")

    direct = Decimal("0")
    for _ordinal, _title, _classification, items in template.sections:
        for _item_ordinal, _description, _unit, quantity, rate, _item_classification in items:
            direct += Decimal(str(quantity)) * Decimal(str(rate))
    lines = [
        {"name": name, "category": category, "percentage": str(percentage), "apply_to": apply_to}
        for name, percentage, category, apply_to in after
    ]
    assert _total_from_lines(lines, direct) == NET_TOTAL_BEFORE_REFILING[demo_id], (
        f"{demo_id} no longer prices to the {NET_TOTAL_BEFORE_REFILING[demo_id]} it priced to "
        f"before the cess was refiled"
    )


# ── What the manifest promises the engine ────────────────────────────────


def test_the_rule_sets_the_pack_switches_on_resolve_to_real_rules(manifest: Any) -> None:
    """A rule set name can be declared without a rule ever being registered
    against it, and such a set does not run rather than failing loudly."""
    register_builtin_rules()
    registered = validation_engine.registry.list_rule_sets()
    declared = list(manifest.validation_rule_sets)
    assert declared, "the India pack declares no engine rule set at all"
    missing = [name for name in declared if not registered.get(name)]
    assert not missing, f"the India pack switches on rule sets the engine does not implement: {missing}"


def test_the_cpwd_rules_are_the_two_the_pack_documents_name(manifest: Any) -> None:
    """The pack's documents tell the reader, in their review status, exactly
    which checks run. That sentence has to stay true."""
    register_builtin_rules()
    rule_ids = sorted(
        rule.rule_id for rule in validation_engine.registry.get_rules_for_sets(list(manifest.validation_rule_sets))
    )
    assert rule_ids == ["cpwd.code_required", "cpwd.measurement_units"]


def test_the_manifest_names_a_methodology_the_catalogue_builds(manifest: Any) -> None:
    """``default_methodology`` is activated on the pack's demo at install, and
    an unknown slug is skipped with a warning rather than an error."""
    assert manifest.default_methodology in TEMPLATES_BY_SLUG
    assert TEMPLATES_BY_SLUG[manifest.default_methodology]["country_code"] == "IN"
    assert TEMPLATES_BY_SLUG[manifest.default_methodology]["currency"] == manifest.default_currency


@pytest.mark.asyncio
async def test_the_shipped_delhi_demo_passes_the_checks_the_pack_switches_on(manifest: Any) -> None:
    """The assertion the wiring tests cannot make: the estimate an Indian user
    is handed on first boot, run through the rules the pack turns on."""
    register_builtin_rules()
    report = await validation_engine.validate(
        data=_demo_payload("govt-building-delhi"),
        rule_sets=list(manifest.validation_rule_sets),
        target_type="boq",
        target_id="govt-building-delhi",
        metadata={"locale": "en"},
    )
    assert report.results, "the India rule sets produced no findings at all on the India demo"
    failed = sorted({result.rule_id for result in report.results if not result.passed})
    assert not failed, f"the shipped India demo cannot clear its own pack's checks: {failed}"


@pytest.mark.asyncio
async def test_both_cpwd_rules_actually_fired_on_the_demo(manifest: Any) -> None:
    """A green report is worth nothing if half of it never ran."""
    register_builtin_rules()
    report = await validation_engine.validate(
        data=_demo_payload("govt-building-delhi"),
        rule_sets=list(manifest.validation_rule_sets),
        target_type="boq",
        target_id="govt-building-delhi",
        metadata={"locale": "en"},
    )
    fired = {result.rule_id for result in report.results}
    assert fired == {"cpwd.code_required", "cpwd.measurement_units"}
