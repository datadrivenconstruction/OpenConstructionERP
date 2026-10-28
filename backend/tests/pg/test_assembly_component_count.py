# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A card must not say "0 components" about a recipe that has three.

The list query loads assemblies without their components on purpose, to keep a
page of fifty from dragging every component row across and to stay clear of a
lazy load in an async session. The response builder then read the length of that
collection, and an unloaded collection is indistinguishable from an empty one,
so every card in the list printed 0 while its own hover panel, which calls the
detail endpoint, listed the real three.

This is the loading policy's own example: noload does not raise, it returns an
empty collection, which is a silent wrong answer rather than an error. The count
now comes from a grouped COUNT. Both halves are asserted here, the count being
right and the collection still being empty, because a future change that fixes
the number by eagerly loading the components would pass the first assertion
while undoing the reason the query is shaped this way.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.assemblies.repository import AssemblyRepository
from app.modules.assemblies.router import _assembly_to_response
from app.modules.assemblies.schemas import AssemblyCreate, ComponentCreate
from app.modules.assemblies.service import AssemblyService

_COMPONENTS = [
    ComponentCreate(
        description="Concrete C30/37 ready-mix", unit="m3", factor=1.0, quantity=1.0, unit_cost=Decimal("95.00")
    ),
    ComponentCreate(description="Rebar B500B", unit="t", factor=0.12, quantity=1.0, unit_cost=Decimal("750.00")),
    ComponentCreate(description="Formwork, one-sided", unit="m2", factor=4.5, quantity=1.0, unit_cost=Decimal("18.00")),
]


async def test_the_list_reports_the_components_a_recipe_has(pg_session) -> None:
    owner_id = uuid.uuid4()
    service = AssemblyService(pg_session)
    code = f"RC-WALL-{uuid.uuid4().hex[:8].upper()}"
    assembly = await service.create_assembly(
        AssemblyCreate(code=code, name="RC Wall C30/37 d=25cm", unit="m3"),
        owner_id=str(owner_id),
    )
    for component in _COMPONENTS:
        await service.add_component(assembly.id, component)
    await pg_session.flush()

    listed, total = await service.search_assemblies(owner_id=owner_id)
    assert total == 1, "the assembly this test created is not the one being listed"
    row = listed[0]

    counts = await AssemblyRepository(pg_session).count_components([row.id])
    assert counts.get(str(row.id)) == len(_COMPONENTS)

    # The number the card actually renders, built the way the list endpoint
    # builds it. Without this the checks above would still pass if the response
    # builder went back to reading the length of the unloaded collection, which
    # is the defect itself and lives in the router rather than the repository.
    response = _assembly_to_response(row, component_count=counts.get(str(row.id), 0))
    assert response.component_count == len(_COMPONENTS)

    # The other half of the contract. If this ever comes back non-empty the
    # list has started loading components again, and the count above would be
    # right for a reason that costs a page of fifty every component row.
    assert len(row.components) == 0, "the list query is eagerly loading components again"


async def test_an_assembly_with_no_components_is_absent_rather_than_zero(pg_session) -> None:
    """The call site reads the map with a default, so a missing key is the zero."""
    owner_id = uuid.uuid4()
    service = AssemblyService(pg_session)
    code = f"EMPTY-{uuid.uuid4().hex[:8].upper()}"
    assembly = await service.create_assembly(
        AssemblyCreate(code=code, name="Empty recipe", unit="m3"),
        owner_id=str(owner_id),
    )
    await pg_session.flush()

    counts = await AssemblyRepository(pg_session).count_components([assembly.id])
    assert counts == {}
    assert counts.get(str(assembly.id), 0) == 0


async def test_counting_nothing_asks_the_database_nothing(pg_session) -> None:
    """An empty page must not become ``IN ()``, which is not valid SQL everywhere."""
    assert await AssemblyRepository(pg_session).count_components([]) == {}
