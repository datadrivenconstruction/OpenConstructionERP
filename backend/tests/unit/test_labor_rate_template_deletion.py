# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for deleting a labour-rate template without destroying referenced data.

A template is referenced from two places once it leaves this module. Publishing
it writes a labour :class:`CostItem` whose code encodes the template id, and a
norm-expansion price build-up writes the template id into the metadata of the
:class:`Assembly` it creates. Both rows outlive the request, so a plain delete
would leave a cost line and a priced assembly pointing at a template that no
longer exists.

These tests drive :meth:`LaborRateService.delete_template` against the
transaction-isolated embedded PostgreSQL (the fixture style the publish tests
use) and prove the delete refuses while either reference stands, names what
holds it, deletes nothing on refusal, and still performs a plain delete when
nothing points at the template.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.assemblies.models import Assembly
from app.modules.costs.models import CostItem
from app.modules.labor_rates.models import CrewMember, LaborRateTemplate, OnCostComponent
from app.modules.labor_rates.schemas import CrewMemberIn, CrewSaveRequest
from app.modules.labor_rates.service import (
    LaborRateService,
    LaborRateTemplateInUseError,
    describe_template_references,
)
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _seed_template(s, *, name: str = "Plasterer") -> LaborRateTemplate:
    """A template that builds up to 30/h + 20% = 36/h."""
    template = LaborRateTemplate(name=name, base_wage=D("30"), currency="EUR")
    template.components.append(OnCostComponent(label="Statutory charges", kind="percentage", value=D("20")))
    s.add(template)
    await s.flush()
    return template


async def _count_templates(s, template_id: uuid.UUID) -> int:
    result = await s.execute(
        select(func.count()).select_from(LaborRateTemplate).where(LaborRateTemplate.id == template_id)
    )
    return int(result.scalar_one())


async def _count_published_items(s, template_id: uuid.UUID) -> int:
    result = await s.execute(
        select(func.count()).select_from(CostItem).where(CostItem.code.like(f"LABOR-RATE-{template_id.hex}-%"))
    )
    return int(result.scalar_one())


# ── Refusal: a published cost item holds the template ────────────────────────


async def test_delete_refuses_while_a_published_cost_item_holds_the_template(session) -> None:
    """Publishing a template makes it undeletable until the cost item goes."""
    template = await _seed_template(session)
    template_id = template.id
    service = LaborRateService(session)

    await service.publish_template_as_cost_item(template_id, region="DE")
    assert await _count_published_items(session, template_id) == 1

    with pytest.raises(LaborRateTemplateInUseError) as excinfo:
        await service.delete_template(template)

    assert excinfo.value.references == {"cost_item": 1}
    assert await _count_templates(session, template_id) == 1, "the refused delete removed the template anyway"
    assert await _count_published_items(session, template_id) == 1, "the refused delete removed the cost item"


# ── Refusal: a priced assembly holds the template ────────────────────────────


async def test_delete_refuses_while_a_priced_assembly_holds_the_template(session) -> None:
    """A norm-expansion assembly records the template id and must pin it."""
    template = await _seed_template(session)
    template_id = template.id
    session.add(
        Assembly(
            code=f"NORM-{uuid.uuid4().hex[:8]}",
            name="Priced build-up",
            unit="m2",
            currency="EUR",
            metadata_={"source": "production_norm", "labor_rate_template_id": str(template_id)},
        )
    )
    await session.flush()

    service = LaborRateService(session)
    with pytest.raises(LaborRateTemplateInUseError) as excinfo:
        await service.delete_template(template)

    assert excinfo.value.references == {"assembly": 1}
    assert await _count_templates(session, template_id) == 1, "the refused delete removed the template anyway"


# ── A released reference stops holding the template ──────────────────────────


async def test_a_soft_deleted_cost_item_releases_the_template(session) -> None:
    """Cost items soft-delete, so an inactive one must not pin forever.

    Counting inactive rows would leave the user with a template that can never
    be deleted: the costs module never hard-deletes the published item, so
    there would be no move that clears the refusal.
    """
    template = await _seed_template(session)
    template_id = template.id
    service = LaborRateService(session)
    item = await service.publish_template_as_cost_item(template_id, region="DE")

    item.is_active = False
    await session.flush()

    assert await service.count_template_references(template_id) == {}
    await service.delete_template(template)
    assert await _count_templates(session, template_id) == 0


# ── The refusal names holders by count and kind ──────────────────────────────


@pytest.mark.parametrize(
    ("references", "expected"),
    [
        ({"cost_item": 1}, "1 published cost item"),
        ({"cost_item": 3}, "3 published cost items"),
        ({"assembly": 1}, "1 priced assembly"),
        ({"assembly": 2}, "2 priced assemblies"),
        ({"cost_item": 3, "assembly": 1}, "3 published cost items and 1 priced assembly"),
    ],
)
def test_the_refusal_names_each_holder_by_count_and_kind(references: dict[str, int], expected: str) -> None:
    """The message says what holds the template, not just that something does."""
    assert describe_template_references(references) == expected


# ── Plain delete when nothing points at the template ─────────────────────────


async def test_an_unreferenced_template_is_plainly_deleted(session) -> None:
    """Nothing referencing it means a real delete, not a refusal or a soft flag."""
    template = await _seed_template(session, name="Unused")
    template_id = template.id

    await LaborRateService(session).delete_template(template)

    assert await _count_templates(session, template_id) == 0


# ── Crews: nothing references a crew, so the delete stays plain ──────────────


async def test_deleting_a_crew_stays_a_plain_delete(session) -> None:
    """No table records a crew id, so a crew delete needs no in-use guard."""
    service = LaborRateService(session)
    owner_id = uuid.uuid4()
    saved = await service.save_crew(
        CrewSaveRequest(
            currency="EUR",
            members=[CrewMemberIn(trade="Mason", count=2, all_in_rate=D("36"))],
        ),
        owner_id=owner_id,
    )

    removed = await service.delete_crew(saved.crew_id, owner_id=owner_id)

    assert removed == 1
    result = await session.execute(
        select(func.count()).select_from(CrewMember).where(CrewMember.crew_id == saved.crew_id)
    )
    assert int(result.scalar_one()) == 0
