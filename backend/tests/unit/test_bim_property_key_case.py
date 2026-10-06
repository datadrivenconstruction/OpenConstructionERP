# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A property filter names a Revit parameter the way Revit spells it.

The DDC import lowercases every header (``parse_cad_excel``), so a canonical
element carries ``{"phase created": "Progetto"}``. An estimator writing a
quantity rule or a dynamic group types the parameter as it appears in Revit,
``Phase Created``. The rule engine used to look the key up with
``props.get(key)``, so that rule matched nothing and said nothing. Key lookup
is now case-insensitive and trimmed, the way Smart Views already resolve
``properties.<key>``; rules saved with the lowercase key keep matching.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.bim_hub.service import BIMHubService
from tests._pg import transactional_session

ELEMENT = SimpleNamespace(
    element_type="Walls",
    properties={"category": "Walls", "phase created": "Stato di fatto", "type name": "Muro 30"},
)


def _rule(property_filter: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(element_type_filter="Wall*", property_filter=property_filter)


@pytest.mark.parametrize(
    "key",
    ["Phase Created", "PHASE CREATED", " phase created ", "phase created"],
)
def test_rule_key_matches_whatever_the_case_and_padding(key: str) -> None:
    assert BIMHubService._rule_matches_element(_rule({key: "stato di fatto"}), ELEMENT) is True


def test_rule_key_case_does_not_loosen_the_value() -> None:
    assert BIMHubService._rule_matches_element(_rule({"Phase Created": "Progetto"}), ELEMENT) is False


def test_rule_on_a_missing_key_still_fails() -> None:
    assert BIMHubService._rule_matches_element(_rule({"Phase Demolished": "*"}), ELEMENT) is False


def test_exact_key_wins_over_a_case_variant() -> None:
    element = SimpleNamespace(
        element_type="Walls",
        properties={"Mark": "A", "mark": "B"},
    )
    assert BIMHubService._rule_matches_element(_rule({"mark": "B"}), element) is True
    assert BIMHubService._rule_matches_element(_rule({"Mark": "A"}), element) is True


# ── Against the database: apply and dynamic groups ───────────────────────


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _restoration_model(s):
    """A restoration project: existing walls and new walls told apart by phase."""
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="O")
    s.add(owner)
    await s.flush()
    project = Project(id=uuid.uuid4(), name="Restauro", description="", owner_id=owner.id, currency="EUR")
    s.add(project)
    await s.flush()
    boq = BOQ(project_id=project.id, name="Computo", description="", status="draft", is_locked=False)
    s.add(boq)
    model = BIMModel(project_id=project.id, name="restauro.rvt", status="ready")
    s.add(model)
    await s.flush()
    for phase, area in (("Stato di fatto", 30.0), ("Progetto", 12.5), ("Progetto", 7.5), ("Demolizioni", 4.0)):
        s.add(
            BIMElement(
                model_id=model.id,
                stable_id=uuid.uuid4().hex,
                element_type="Walls",
                properties={"category": "Walls", "phase created": phase},
                quantities={"area": area},
            )
        )
    await s.flush()
    return project, boq, model


@pytest.mark.asyncio
async def test_apply_matches_a_rule_written_with_the_revit_parameter_name(session) -> None:
    from app.modules.bim_hub.models import BIMQuantityMap
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest
    from app.modules.boq.models import Position

    project, boq, model = await _restoration_model(session)
    session.add(
        BIMQuantityMap(
            project_id=project.id,
            name="Muri di progetto",
            element_type_filter="Wall*",
            property_filter={"Phase Created": "Progetto"},
            quantity_source="area",
            multiplier="1",
            waste_factor_pct="0",
            unit="m2",
            boq_target={"auto_create": True, "unit_rate": "10"},
            is_active=True,
        )
    )
    await session.flush()

    service = BIMHubService(session)
    checked = await service.apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id))
    result = await service.apply_quantity_maps(
        QuantityMapApplyRequest(
            model_id=model.id,
            dry_run=False,
            preview_fingerprint=checked.preview_fingerprint,
        )
    )

    assert result.matched_elements == 2
    assert result.positions_created == 1
    rows = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
    assert len(rows) == 1
    assert Decimal(rows[0].quantity) == Decimal("20")


@pytest.mark.asyncio
async def test_dynamic_group_resolves_a_revit_cased_key(session) -> None:
    project, _boq, model = await _restoration_model(session)
    group = SimpleNamespace(
        project_id=project.id,
        model_id=model.id,
        filter_criteria={"property_filter": {"Phase Created": "stato di fatto"}},
        is_dynamic=True,
        element_ids=[],
    )

    members = await BIMHubService(session)._resolve_members_for_group(group)

    assert len(members) == 1
