# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: a methodology asked about a project prices that project's VAT.

VAT is a property of the transaction, not of the method. "How Germany
estimates" is a catalogue fact and the template's 19 belongs there. But
:meth:`MethodologyService.compute_estimate` takes a ``project_id`` and, through
:meth:`build_export_data`, a ``boq_id``, and at that moment it is not answering
about Germany any more. It is answering about one project's bill, and the bill
engine has honoured that project's ``default_vat_rate`` since issue #89.

The two therefore disagreed. On a million of direct cost with a project on 25
percent, the bill said 1,537,500 and the methodology said 1,463,700, and 15 of
the 20 mapped countries diverged the same way, up to 315,632 on the Gulf pair.
The agreement the parity suite reports was real but narrow: it holds on the
branch where both sides read the same VAT number, which is every project that
never set one.

The divergent figure was not confined to a screen. ``build_export_data`` prices
a real ``boq_id`` through a stored methodology and streams it as Excel or PDF,
so it left the building as a document.

What must NOT move: the catalogue answer. ``build_cascade_spec_from_template``
still prices a slug at the template rate, and a project that set no rate of its
own is not touched by a cent. The override wins only where there is a project
and a rate to win with.

Gated by ``OE_TEST_DB=pg`` (see conftest); it needs stored Project and
Methodology rows, so it cannot live in the unit lane.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.boq.markup_templates import region_lines_for_country
from app.modules.boq.models import BOQMarkup
from app.modules.boq.service import _calculate_markup_amounts
from app.modules.methodology.schemas import ComputeEstimateRequest
from app.modules.methodology.service import MethodologyService
from app.modules.projects.models import Project
from app.modules.users.models import User

#: Resource totals keyed the way ``base_mapping`` expects them, summing to a
#: round million so the pair stays legible: 1,537,500 against 1,463,700.
RESOURCE_TOTALS: dict[str, Decimal] = {
    "labor": Decimal("400000"),
    "material": Decimal("400000"),
    "equipment": Decimal("150000"),
    "subcontractor": Decimal("50000"),
}
DIRECT_COST = sum(RESOURCE_TOTALS.values(), Decimal("0"))

#: Germany: one tax step, so one rate is a complete swap. 19 in the catalogue.
TEMPLATE_SLUG = "germany"
COUNTRY = "DE"
PROJECT_VAT = "25"


def _bill_total(vat_rate: str | None) -> Decimal:
    """Price the same country through the bill engine, as a seeded bill would.

    This is the authoritative side. ``region_lines_for_country`` is what
    ``apply_default_markups`` seeds from, and it already applies the project
    override, so passing the rate here reproduces the bill exactly.
    """
    lines = region_lines_for_country(COUNTRY, vat_rate=vat_rate)
    assert lines is not None
    markups = [
        BOQMarkup(
            name=str(line["name"]),
            markup_type=str(line.get("markup_type", "percentage")),
            category=str(line["category"]),
            percentage=str(line["percentage"]),
            fixed_amount=str(line.get("fixed_amount", "0")),
            apply_to=str(line.get("apply_to", "direct_cost")),
            sort_order=int(line["sort_order"]),  # type: ignore[arg-type]
            is_active=True,
        )
        for line in lines
    ]
    return DIRECT_COST + sum((amount for _, amount in _calculate_markup_amounts(DIRECT_COST, markups)), Decimal("0"))


def _tolerance(steps: int, decimals: int = 2) -> Decimal:
    """The most the two rounding conventions can make the totals differ by.

    Same derivation as the parity suite: the cascade quantizes every step and
    feeds the rounded amount forward, the bill engine quantizes once at the
    rollup, and a later cumulative step grows the difference by at most
    ``1 + rate`` per step.
    """
    quantum = Decimal(1).scaleb(-decimals)
    return steps * (quantum / 2) * Decimal("1.3") ** steps


async def _project(session, *, vat: str | None) -> Project:
    """A stored project, with or without a VAT rate of its own."""
    owner = User(email=f"vat-{vat or 'none'}@example.test", hashed_password="x", full_name="VAT")
    session.add(owner)
    await session.flush()

    project = Project(name=f"VAT {vat or 'default'}", owner_id=owner.id, currency="EUR", default_vat_rate=vat)
    session.add(project)
    await session.flush()
    return project


async def _compute_total(session, project: Project, slug: str) -> Decimal:
    """Grand total for a project under a stored methodology."""
    result = await MethodologyService(session).compute_estimate(
        ComputeEstimateRequest(
            project_id=project.id,
            methodology_slug=slug,
            resource_totals=dict(RESOURCE_TOTALS),
        )
    )
    return Decimal(str(result["grand_total"]))


@pytest.mark.asyncio
async def test_a_stored_methodology_prices_the_projects_own_vat(pg_session) -> None:
    """The finish line: one bill, two engines, one number, on the other branch.

    Deliberately run through the project's INSTALLED clone rather than the
    template slug, because a clone is what the export endpoint resolves and
    because a clone is the thing a user can later edit.
    """
    project = await _project(pg_session, vat=PROJECT_VAT)
    service = MethodologyService(pg_session)
    installed = await service.install_template(project_id=project.id, template_slug=TEMPLATE_SLUG)

    cascade_total = await _compute_total(pg_session, project, installed.slug)
    bill_total = _bill_total(PROJECT_VAT)

    assert abs(cascade_total - bill_total) <= _tolerance(5), (
        f"the methodology says {cascade_total} and the bill says {bill_total} on {DIRECT_COST} of direct cost "
        f"for a project on {PROJECT_VAT} percent VAT. The bill engine is authoritative here: VAT belongs to the "
        f"transaction, not to the method, so the cascade has to take the project's rate once a project is named. "
        f"Do not widen this tolerance to close the gap; it is sized for rounding and this difference is a rate."
    )


@pytest.mark.asyncio
async def test_a_project_without_a_rate_of_its_own_is_not_touched(pg_session) -> None:
    """The other half of the ruling: the catalogue answer must not move.

    A project that never set a VAT rate has to price exactly as it did before
    the override existed, to the cent. Without this, "take the project's rate"
    could quietly become "take zero when there is no project rate", which would
    move every estimate that relies on the template.
    """
    project = await _project(pg_session, vat=None)
    service = MethodologyService(pg_session)
    installed = await service.install_template(project_id=project.id, template_slug=TEMPLATE_SLUG)

    cascade_total = await _compute_total(pg_session, project, installed.slug)
    bill_total = _bill_total(None)

    assert abs(cascade_total - bill_total) <= _tolerance(5), (
        f"a project with no VAT rate of its own priced at {cascade_total} against the catalogue's {bill_total}. "
        f"The template rate is the default and must survive the override."
    )


@pytest.mark.asyncio
async def test_the_override_moves_the_total_by_the_rate_and_not_by_rounding(pg_session) -> None:
    """The two branches must actually differ, or the test above proves nothing.

    If a project rate and the template rate happened to produce the same total,
    both assertions would pass while the override did nothing at all. Germany
    at 19 against a project at 25 has to be a visible amount of money.
    """
    with_override = _bill_total(PROJECT_VAT)
    catalogue = _bill_total(None)

    assert with_override - catalogue > _tolerance(5) * 1000, (
        "the two VAT branches price the same, so these tests cannot tell an applied override from an ignored one"
    )
