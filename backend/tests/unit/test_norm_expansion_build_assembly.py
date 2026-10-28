# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service tests for building a priced assembly from a production norm.

These drive :func:`app.modules.norm_expansion.service.build_assembly_from_norm`
end to end against a real (transaction-isolated) PostgreSQL session, seeding a
production norm, a labour-rate template and matching cost items, then asserting
the persisted assembly carries the built-up unit rate, the correct priced /
unpriced components, and the project / template wiring.

They use the shared ``oe_test_unit`` database via ``tests._pg`` (rolled back on
teardown), the same fixture style the assemblies module tests use - no new test
harness is introduced.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.labor_rates.models import LaborRateTemplate, OnCostComponent
from app.modules.norm_expansion.models import NormMaterial, ProductionNorm
from app.modules.norm_expansion.service import NormNotFoundError, build_assembly_from_norm
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _seed_plastering_norm(s) -> ProductionNorm:
    """A norm: 0.45 labour-h, 0.02 machine-h, 12 kg gypsum + 6 l water per m2."""
    norm = ProductionNorm(
        work_key=f"plastering_{uuid.uuid4().hex[:6]}",
        name="Internal plastering",
        unit="m2",
        category="finishing",
        labor_hours_per_unit=D("0.45"),
        machine_hours_per_unit=D("0.02"),
        is_active=True,
    )
    norm.materials.append(NormMaterial(name="Gypsum plaster", unit="kg", qty_per_unit=D("12.0"), sort_order=0))
    norm.materials.append(NormMaterial(name="Water", unit="l", qty_per_unit=D("6.0"), sort_order=1))
    s.add(norm)
    await s.flush()
    return norm


async def _seed_labor_template(s) -> LaborRateTemplate:
    """A template that builds up to a 36.00/h all-in rate (30 base + 20%)."""
    template = LaborRateTemplate(name="Plasterer", base_wage=D("30"), currency="EUR")
    template.components.append(
        OnCostComponent(label="Statutory charges", kind="percentage", value=D("20"), sort_order=0)
    )
    s.add(template)
    await s.flush()
    return template


async def _seed_rate_template(s, *, name: str, base_wage: str, kind: str, value: str) -> LaborRateTemplate:
    """A template with one on-cost component, to drive its all-in rate anywhere.

    ``base_wage`` is positive (the create schema requires it), but a component's
    ``value`` carries no bound, so a percentage of -100 cancels the wage exactly
    and a larger negative one inverts it.
    """
    template = LaborRateTemplate(name=name, base_wage=D(base_wage), currency="EUR")
    template.components.append(OnCostComponent(label="Adjustment", kind=kind, value=D(value), sort_order=0))
    s.add(template)
    await s.flush()
    return template


async def _seed_cost_item(
    s,
    *,
    code: str,
    description: str,
    unit: str,
    rate: str,
    currency: str = "EUR",
    source: str = "custom",
    price_as_of=None,
):
    from app.modules.costs.models import CostItem

    item = CostItem(
        code=code,
        description=description,
        unit=unit,
        rate=rate,
        currency=currency,
        source=source,
        is_active=True,
        price_as_of=price_as_of,
    )
    s.add(item)
    await s.flush()
    return item


async def _seed_waste_factor(s, *, category: str, factor: str) -> None:
    """Insert one waste-factor library row (gross = net * factor)."""
    from app.modules.waste_factors.models import WasteFactor

    s.add(WasteFactor(category=category, label=category, factor=D(factor)))
    await s.flush()


@pytest.mark.asyncio
async def test_build_prices_labour_and_materials_and_persists(session):
    norm = await _seed_plastering_norm(session)
    template = await _seed_labor_template(session)
    gypsum = await _seed_cost_item(
        session, code=f"G-{uuid.uuid4().hex[:6]}", description="Gypsum plaster 25 kg bag", unit="kg", rate="0.50"
    )
    await _seed_cost_item(session, code=f"W-{uuid.uuid4().hex[:6]}", description="Water potable", unit="l", rate="0.01")

    assembly = await build_assembly_from_norm(
        session,
        norm.id,
        labor_rate_template_id=template.id,
    )

    assert assembly.is_template is False
    assert assembly.unit == "m2"
    assert assembly.currency == "EUR"
    assert assembly.code.startswith("NORM-")
    assert assembly.metadata_["source"] == "production_norm"
    assert assembly.metadata_["work_key"] == norm.work_key

    # labour 0.45*36 = 16.20; machine unpriced = 0; gypsum 12*0.50 = 6.00;
    # water 6*0.01 = 0.06 -> built-up unit rate 22.26.
    assert D(str(assembly.total_rate)) == D("22.26")

    by_type = {c.resource_type: c for c in assembly.components}
    assert len(assembly.components) == 4
    assert by_type["labor"].metadata_["priced"] is True
    assert D(str(by_type["labor"].unit_cost)) == D("36.0000")
    assert D(str(by_type["labor"].total)) == D("16.20")

    # No machine-rate template was given: the machine line is present but
    # unpriced and flagged, and contributes zero to the total.
    assert by_type["equipment"].metadata_["priced"] is False
    assert D(str(by_type["equipment"].unit_cost)) == D("0")
    assert "Machine / equipment" in assembly.metadata_["unpriced"]

    # Materials are linked back to the matched cost items.
    gypsum_comp = next(c for c in assembly.components if c.description == "Gypsum plaster")
    assert gypsum_comp.cost_item_id == gypsum.id
    assert gypsum_comp.metadata_["priced"] is True
    assert D(str(gypsum_comp.total)) == D("6.00")


@pytest.mark.asyncio
async def test_unmatched_material_is_unpriced_and_flagged(session):
    norm = await _seed_plastering_norm(session)
    template = await _seed_labor_template(session)
    # Only gypsum is in the catalogue; water has no matching cost item.
    await _seed_cost_item(
        session, code=f"G-{uuid.uuid4().hex[:6]}", description="Gypsum plaster 25 kg bag", unit="kg", rate="0.50"
    )

    assembly = await build_assembly_from_norm(session, norm.id, labor_rate_template_id=template.id)

    water = next(c for c in assembly.components if c.description == "Water")
    assert water.metadata_["priced"] is False
    assert D(str(water.unit_cost)) == D("0")
    assert water.cost_item_id is None
    assert "Water" in assembly.metadata_["unpriced"]
    # labour 16.20 + machine 0 + gypsum 6.00 + water 0 = 22.20.
    assert D(str(assembly.total_rate)) == D("22.20")


@pytest.mark.asyncio
async def test_missing_labour_template_leaves_labour_unpriced(session):
    norm = await _seed_plastering_norm(session)
    await _seed_cost_item(
        session, code=f"G-{uuid.uuid4().hex[:6]}", description="Gypsum plaster 25 kg bag", unit="kg", rate="0.50"
    )
    await _seed_cost_item(session, code=f"W-{uuid.uuid4().hex[:6]}", description="Water potable", unit="l", rate="0.01")

    assembly = await build_assembly_from_norm(session, norm.id, labor_rate_template_id=None)

    labour = next(c for c in assembly.components if c.resource_type == "labor")
    assert labour.metadata_["priced"] is False
    assert D(str(labour.unit_cost)) == D("0")
    assert "Labour" in assembly.metadata_["unpriced"]
    # Only the materials are priced: gypsum 6.00 + water 0.06 = 6.06.
    assert D(str(assembly.total_rate)) == D("6.06")


@pytest.mark.asyncio
async def test_project_scoping_sets_project_and_owner(session):
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    session.add(User(id=owner_id, email=f"o-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="O"))
    await session.flush()
    session.add(Project(id=project_id, name="Norm Build", owner_id=owner_id, currency="EUR"))
    await session.flush()

    norm = await _seed_plastering_norm(session)
    template = await _seed_labor_template(session)

    assembly = await build_assembly_from_norm(
        session,
        norm.id,
        labor_rate_template_id=template.id,
        project_id=project_id,
        owner_id=str(owner_id),
    )

    assert assembly.project_id == project_id
    assert assembly.owner_id == owner_id
    assert assembly.is_template is False


@pytest.mark.asyncio
async def test_material_waste_grosses_up_component_total(session):
    # A library factor keyed by the material NAME grosses that material up;
    # a material with no library entry stays net == gross and is flagged.
    norm = await _seed_plastering_norm(session)
    template = await _seed_labor_template(session)
    await _seed_cost_item(
        session, code=f"G-{uuid.uuid4().hex[:6]}", description="Gypsum plaster 25 kg bag", unit="kg", rate="0.50"
    )
    await _seed_cost_item(session, code=f"W-{uuid.uuid4().hex[:6]}", description="Water potable", unit="l", rate="0.01")
    # Only "Gypsum plaster" has a factor; "Water" does not.
    await _seed_waste_factor(session, category="Gypsum plaster", factor="1.10")

    assembly = await build_assembly_from_norm(session, norm.id, labor_rate_template_id=template.id)

    gypsum = next(c for c in assembly.components if c.description == "Gypsum plaster")
    assert gypsum.metadata_["waste_matched"] is True
    assert gypsum.metadata_["waste_pct"] == "10.0000"
    assert gypsum.metadata_["net_qty"] == "12.0000"
    assert gypsum.metadata_["gross_qty"] == "13.2000"  # 12 * 1.10
    # The gross-up reaches component.total (net 12 * 0.50 * 1.10 = 6.60), not
    # just the metadata.
    assert D(str(gypsum.total)) == D("6.60")
    # The displayed quantity stays the net (installed) coefficient.
    assert D(str(gypsum.quantity)) == D("12")

    water = next(c for c in assembly.components if c.description == "Water")
    assert water.metadata_["waste_matched"] is False
    assert water.metadata_["waste_pct"] == "0.0000"
    assert water.metadata_["net_qty"] == water.metadata_["gross_qty"] == "6.0000"
    assert D(str(water.total)) == D("0.06")  # 6 * 0.01, no gross-up

    # labour 16.20 + machine 0 + gypsum 6.60 + water 0.06 = 22.86.
    assert D(str(assembly.total_rate)) == D("22.86")
    assert assembly.metadata_["waste_applied"] is True
    assert assembly.metadata_["waste_unmatched"] == ["Water"]


@pytest.mark.asyncio
async def test_apply_waste_false_prices_net_quantities(session):
    # Opting out leaves every material at net == gross and flags nothing.
    norm = await _seed_plastering_norm(session)
    template = await _seed_labor_template(session)
    await _seed_cost_item(
        session, code=f"G-{uuid.uuid4().hex[:6]}", description="Gypsum plaster 25 kg bag", unit="kg", rate="0.50"
    )
    await _seed_cost_item(session, code=f"W-{uuid.uuid4().hex[:6]}", description="Water potable", unit="l", rate="0.01")
    await _seed_waste_factor(session, category="Gypsum plaster", factor="1.10")

    assembly = await build_assembly_from_norm(session, norm.id, labor_rate_template_id=template.id, apply_waste=False)

    gypsum = next(c for c in assembly.components if c.description == "Gypsum plaster")
    assert gypsum.metadata_["waste_matched"] is False
    assert gypsum.metadata_["waste_pct"] == "0.0000"
    assert gypsum.metadata_["net_qty"] == gypsum.metadata_["gross_qty"] == "12.0000"
    assert D(str(gypsum.total)) == D("6.00")  # net, no gross-up despite the library factor

    # labour 16.20 + gypsum 6.00 + water 0.06 = 22.26.
    assert D(str(assembly.total_rate)) == D("22.26")
    assert assembly.metadata_["waste_applied"] is False
    assert assembly.metadata_["waste_unmatched"] == []


@pytest.mark.asyncio
async def test_missing_norm_raises_not_found(session):
    with pytest.raises(NormNotFoundError):
        await build_assembly_from_norm(session, uuid.uuid4())


# ── Match provenance: exact normalized name before fuzzy (issue #443) ─────────
# A norm material carries a NAME, so the build has to find the cost item behind
# it. These pin the ORDERING - an exact normalized identity match is taken ahead
# of a lexical one - rather than a fuzzy score floor. Raising the floor would
# only move which wrong product appears, so the first test deliberately asserts
# that the fuzzy channel on its own still prefers the wrong row: what fixes the
# defect is the ordering, not a better guess.

# The material as an estimator typed it into the norm, accents and comma
# decimals included; the catalogue exported the same product without either.
_BOARD_MATERIAL = "Lámina yeso blanca 12 mm x 1,22 x 2,44 m"
_BOARD_CATALOGUE = "Lamina Yeso Blanca 12mm X 1.22 X 2.44 M"
# A DIFFERENT product - a moisture-resistant grade - listed in the same style as
# the norm material, so every token of the material name is a subset of this
# description and the lexical channel scores it a perfect 100 while the correctly
# priced row, formatted differently by another catalogue export, scores 85.
_BOARD_OTHER_PRODUCT = "Lámina yeso blanca 12 mm x 1,22 x 2,44 m resistente a la humedad"


async def _seed_single_material_norm(s, *, name: str, unit: str = "m2") -> ProductionNorm:
    """A norm with no hours and exactly one material, so one component is built."""
    norm = ProductionNorm(
        work_key=f"drywall_{uuid.uuid4().hex[:6]}",
        name="Drywall sheeting",
        unit="m2",
        category="finishing",
        labor_hours_per_unit=D("0"),
        machine_hours_per_unit=D("0"),
        is_active=True,
    )
    norm.materials = [NormMaterial(name=name, unit=unit, qty_per_unit=D("1"), sort_order=0)]
    s.add(norm)
    await s.flush()
    return norm


@pytest.mark.asyncio
async def test_exact_normalized_cost_item_wins_over_a_higher_fuzzy_score(session):
    norm = await _seed_single_material_norm(session, name=_BOARD_MATERIAL)
    wrong = await _seed_cost_item(
        session,
        code=f"AA-{uuid.uuid4().hex[:6]}",
        description=_BOARD_OTHER_PRODUCT,
        unit="m2",
        rate="6668.23",
    )
    right = await _seed_cost_item(
        session,
        code=f"ZZ-{uuid.uuid4().hex[:6]}",
        description=_BOARD_CATALOGUE,
        unit="m2",
        rate="2334.72",
    )

    # Measure the premise rather than assume it: on the lexical channel alone the
    # wrong product still scores higher, because every token of the material name
    # is a subset of its longer description. Without this the assertions below
    # could pass for a reason that has nothing to do with the fix.
    from app.modules.costs.matcher import match_cwicr_items

    fuzzy = await match_cwicr_items(session, _BOARD_MATERIAL, unit="m2", top_k=2, source=None)
    assert fuzzy[0].cost_item_id == str(wrong.id)
    assert fuzzy[0].score > fuzzy[1].score

    assembly = await build_assembly_from_norm(session, norm.id)

    component = next(c for c in assembly.components if c.resource_type == "material")
    assert component.cost_item_id == right.id
    assert D(str(component.unit_cost)) == D("2334.72")
    assert component.metadata_["price_source"] == "cost_item_exact"
    assert component.metadata_["match_confidence"] == "1"
    assert component.metadata_["matched_code"] == right.code
    assert component.metadata_["matched_description"] == _BOARD_CATALOGUE
    assert component.metadata_["matched_source"] == "custom"
    # An identity match is a fact, not a proposal, so nothing is queued for review.
    assert component.metadata_["needs_review"] is False
    assert assembly.metadata_["total_rate_complete"] is True
    assert assembly.metadata_["needs_review_count"] == 0

    from app.modules.norm_expansion.router import _build_assembly_response

    response = _build_assembly_response(assembly)
    priced = next(c for c in response.components if c.resource_type == "material")
    assert priced.price_source == "cost_item_exact"
    assert priced.match_confidence == D("1")
    assert priced.matched_code == right.code
    assert priced.needs_review is False
    assert response.total_rate_complete is True


@pytest.mark.asyncio
async def test_fuzzy_priced_material_is_reported_as_a_reviewable_proposal(session):
    # With no exact match in the catalogue the lexical tier still prices the
    # line - dropping it would be worse - but the response has to say the money
    # came from a heuristic and carry its score.
    norm = await _seed_single_material_norm(session, name=_BOARD_MATERIAL)
    approximate = await _seed_cost_item(
        session,
        code=f"AA-{uuid.uuid4().hex[:6]}",
        description=_BOARD_OTHER_PRODUCT,
        unit="m2",
        rate="6668.23",
    )

    assembly = await build_assembly_from_norm(session, norm.id)

    component = next(c for c in assembly.components if c.resource_type == "material")
    assert component.cost_item_id == approximate.id
    assert component.metadata_["price_source"] == "cost_item_fuzzy"
    assert component.metadata_["needs_review"] is True
    assert D("0") < D(component.metadata_["match_confidence"]) <= D("1")
    # A proposal still counts towards the rate, so the total is complete - but it
    # is listed for a human to confirm.
    assert assembly.metadata_["total_rate_complete"] is True
    assert assembly.metadata_["needs_review"] == [_BOARD_MATERIAL]

    from app.modules.norm_expansion.router import _build_assembly_response

    response = _build_assembly_response(assembly)
    assert response.needs_review == [_BOARD_MATERIAL]
    assert response.needs_review_count == 1


@pytest.mark.asyncio
async def test_exact_match_prefers_the_freshest_priced_row(session):
    # The same product twice: a price fixed months ago and one verified since.
    # An exact name match that hands back the stale number is still the wrong
    # number, so price_as_of breaks the tie. The stale row is deliberately given
    # the code that sorts FIRST, because ``code`` is the last resort in the
    # tie-break: the assertion below can only hold if freshness outranked it.
    from datetime import date

    norm = await _seed_single_material_norm(session, name=_BOARD_MATERIAL)
    await _seed_cost_item(
        session,
        code=f"AA-{uuid.uuid4().hex[:6]}",
        description=_BOARD_CATALOGUE,
        unit="m2",
        rate="10511.00",
        price_as_of=date(2025, 11, 4),
    )
    fresh = await _seed_cost_item(
        session,
        code=f"ZZ-{uuid.uuid4().hex[:6]}",
        description=_BOARD_CATALOGUE,
        unit="m2",
        rate="4806.00",
        price_as_of=date(2026, 6, 18),
    )

    assembly = await build_assembly_from_norm(session, norm.id)

    component = next(c for c in assembly.components if c.resource_type == "material")
    assert component.cost_item_id == fresh.id
    assert D(str(component.unit_cost)) == D("4806.00")
    assert component.metadata_["price_source"] == "cost_item_exact"
    assert component.metadata_["price_as_of"] == "2026-06-18"


@pytest.mark.asyncio
async def test_unmatched_material_is_explicitly_unpriced_never_priced_at_zero(session):
    # Nothing in the catalogue resembles this material. The component must read
    # as "no price found", not as "priced, at zero" - and the assembly total has
    # to admit it is missing a cost line.
    norm = await _seed_single_material_norm(session, name="Zyrconium vapour barrier tape 48 mm")

    assembly = await build_assembly_from_norm(session, norm.id)

    component = next(c for c in assembly.components if c.resource_type == "material")
    assert component.cost_item_id is None
    assert component.metadata_["priced"] is False
    assert component.metadata_["price_source"] == "unpriced"
    # No confidence, rather than a zero confidence: the line was never priced.
    assert component.metadata_["match_confidence"] is None
    assert component.metadata_["unpriced_reason"] == "no matching cost item"
    assert D(str(component.unit_cost)) == D("0")

    assert assembly.metadata_["total_rate_complete"] is False
    assert assembly.metadata_["unpriced_count"] == 1
    assert D(str(assembly.total_rate)) == D("0")

    from app.modules.norm_expansion.router import _build_assembly_response

    response = _build_assembly_response(assembly)
    unpriced = next(c for c in response.components if c.resource_type == "material")
    assert unpriced.priced is False
    assert unpriced.price_source == "unpriced"
    assert unpriced.match_confidence is None
    # The total is zero AND flagged incomplete, so a caller reading only the
    # number cannot mistake it for a finished rate.
    assert response.total_rate_complete is False
    assert response.unpriced_count == 1


@pytest.mark.asyncio
async def test_labour_is_priced_from_a_real_rate_or_flagged_never_silently_zero(session):
    # Three ways the labour line can end up, and none of them is a silent zero.
    template = await _seed_labor_template(session)

    # 1. An explicit rate on the request.
    explicit_norm = await _seed_plastering_norm(session)
    explicit = await build_assembly_from_norm(session, explicit_norm.id, labor_rate=D("42.50"))
    labour = next(c for c in explicit.components if c.resource_type == "labor")
    assert labour.metadata_["priced"] is True
    assert labour.metadata_["price_source"] == "explicit_rate"
    assert D(str(labour.unit_cost)) == D("42.50")
    assert D(str(labour.total)) == D("19.125")  # 0.45 h * 42.50
    assert explicit.metadata_["labor_rate_source"] == "explicit_rate"

    # 2. A labour-rate template, which is the labour-rates module supplying it.
    templated_norm = await _seed_plastering_norm(session)
    templated = await build_assembly_from_norm(session, templated_norm.id, labor_rate_template_id=template.id)
    labour = next(c for c in templated.components if c.resource_type == "labor")
    assert labour.metadata_["priced"] is True
    assert labour.metadata_["price_source"] == "labor_rate_template"
    assert labour.metadata_["matched_description"] == template.name
    assert D(str(labour.unit_cost)) == D("36.0000")
    assert templated.metadata_["labor_rate_source"] == "labor_rate_template"

    # 3. Neither. No rate is invented: the line is unpriced, says why, and the
    # assembly total is marked incomplete.
    bare_norm = await _seed_plastering_norm(session)
    bare = await build_assembly_from_norm(session, bare_norm.id)
    labour = next(c for c in bare.components if c.resource_type == "labor")
    assert labour.metadata_["priced"] is False
    assert labour.metadata_["price_source"] == "unpriced"
    assert labour.metadata_["match_confidence"] is None
    assert labour.metadata_["unpriced_reason"] == "no labour rate given and no rate template named"
    assert D(str(labour.unit_cost)) == D("0")
    assert bare.metadata_["total_rate_complete"] is False
    assert "Labour" in bare.metadata_["unpriced"]


def test_an_explicit_rate_of_zero_is_refused_by_the_request() -> None:
    # The fourth way the labour line could have ended up, closed at the door.
    # A zero that gets through is not a harmless number: it reaches the pricing
    # as a real rate, so the hours come back priced=True at nothing with
    # confidence 1 and the assembly still calls its total complete. "This costs
    # nothing" would then be indistinguishable from case 3 above, which is the
    # one thing this module promises never to blur. Omitting the field is how a
    # caller says the rate is unknown.
    from pydantic import ValidationError

    from app.modules.norm_expansion.schemas import BuildAssemblyRequest

    assert BuildAssemblyRequest(labor_rate=D("42.50")).labor_rate == D("42.50")
    with pytest.raises(ValidationError):
        BuildAssemblyRequest(labor_rate=D("0"))
    with pytest.raises(ValidationError):
        BuildAssemblyRequest(machine_rate=D("0"))


@pytest.mark.asyncio
async def test_a_template_that_computes_to_zero_leaves_labour_unpriced(session):
    # The same silent zero the request refuses at the door, arriving through the
    # template door instead. base_wage is positive on create, but an on-cost
    # component's value is unbounded, so a -100 pct component cancels the wage
    # and the template's all-in rate is exactly 0. Passed on as a rate it would
    # price the hours at nothing with confidence 1 while the assembly still
    # called its total complete - indistinguishable from a real 0-cost trade.
    from app.modules.labor_rates import rate_math

    norm = await _seed_plastering_norm(session)
    template = await _seed_rate_template(
        session, name="Cancelled trade", base_wage="30", kind="percentage", value="-100"
    )
    # Measure the premise rather than assume it.
    assert rate_math.all_in_rate(
        template.base_wage,
        [rate_math.OnCost(label=c.label, kind=c.kind, value=c.value) for c in template.components],
    ) == D("0.00")

    assembly = await build_assembly_from_norm(session, norm.id, labor_rate_template_id=template.id)

    labour = next(c for c in assembly.components if c.resource_type == "labor")
    assert labour.metadata_["priced"] is False
    assert labour.metadata_["price_source"] == "unpriced"
    assert labour.metadata_["match_confidence"] is None
    assert D(str(labour.unit_cost)) == D("0")
    assert D(str(labour.total)) == D("0")
    assert "Labour" in assembly.metadata_["unpriced"]
    assert assembly.metadata_["total_rate_complete"] is False
    assert assembly.metadata_["labor_rate_source"] == "unpriced"


@pytest.mark.asyncio
async def test_a_template_that_computes_below_zero_never_reaches_the_build(session):
    # Worse than the zero above, and differently so. A fixed on-cost of -50 on a
    # 30 base wage builds up to -20/h, and measured before the guard existed
    # that number did not quietly subtract from the unit rate - it never got
    # that far. ComponentCreate.unit_cost carries ge=0, so the build raised
    # ValidationError at service.py's add_component, out of service code rather
    # than request parsing, which the router does not catch: the endpoint
    # answered 500. So the template door hid a crash, not only a wrong figure.
    # The equipment door is the same resolver as the labour one, so it is
    # covered here.
    from app.modules.labor_rates import rate_math

    norm = await _seed_plastering_norm(session)
    template = await _seed_rate_template(session, name="Inverted plant", base_wage="30", kind="fixed", value="-50")
    assert rate_math.all_in_rate(
        template.base_wage,
        [rate_math.OnCost(label=c.label, kind=c.kind, value=c.value) for c in template.components],
    ) == D("-20.00")

    assembly = await build_assembly_from_norm(session, norm.id, machine_rate_template_id=template.id)

    machine = next(c for c in assembly.components if c.resource_type == "equipment")
    assert machine.metadata_["priced"] is False
    assert machine.metadata_["price_source"] == "unpriced"
    assert D(str(machine.unit_cost)) == D("0")
    assert D(str(machine.total)) == D("0")
    assert assembly.metadata_["machine_rate_source"] == "unpriced"
    assert assembly.metadata_["total_rate_complete"] is False
    # Belt and braces rather than the assertion that was red: nothing in the
    # build-up is negative, so an unpriced line reads as a gap and never as a
    # discount, whatever ComponentCreate's own bound would have done.
    assert all(D(str(c.total)) >= D("0") for c in assembly.components)
    assert D(str(assembly.total_rate)) >= D("0")


@pytest.mark.asyncio
async def test_an_accented_catalogue_row_is_still_an_exact_match(session):
    # The mirror of the fixtures above: here the CATALOGUE carries the accent
    # and the norm material does not. SQL ILIKE is case-insensitive but not
    # accent-insensitive, so '%lamina%' does not find 'Lamina' spelt with an
    # acute, and neither of the two selective candidate passes can see the row.
    # Only the last-resort window does, and the comparison key still decides.
    from app.modules.norm_expansion.material_match import (
        _prefilter_tokens,
        _rows_by_all_tokens,
        _rows_by_literal_description,
        find_exact_cost_item,
    )

    plain = "Lamina yeso blanca 12 mm x 1,22 x 2,44 m"
    accented = "Lámina yeso blanca 12 mm x 1,22 x 2,44 m"
    row = await _seed_cost_item(
        session, code=f"AC-{uuid.uuid4().hex[:6]}", description=accented, unit="m2", rate="2334.72"
    )

    # Measure the premise rather than assume it: both selective passes are blind
    # to this row, so a hit can only have come from the third pass.
    assert await _rows_by_literal_description(session, plain) == []
    assert await _rows_by_all_tokens(session, _prefilter_tokens(plain)) == []

    found = await find_exact_cost_item(session, plain, unit="m2")
    assert found is not None
    assert found.id == row.id

    # And end to end, it prices the line as an exact match needing no review.
    norm = await _seed_single_material_norm(session, name=plain)
    assembly = await build_assembly_from_norm(session, norm.id)
    component = next(c for c in assembly.components if c.resource_type == "material")
    assert component.cost_item_id == row.id
    assert component.metadata_["price_source"] == "cost_item_exact"
    assert component.metadata_["needs_review"] is False
