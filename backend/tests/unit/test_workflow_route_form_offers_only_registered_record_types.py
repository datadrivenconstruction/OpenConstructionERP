# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The route form lists record types from the approval registry itself.

The form used to take the record type as free text, so a typo only surfaced
as a server error. It now reads the list from the registry that submit
checks against, which keeps the two from drifting apart.
"""

from __future__ import annotations

import pytest

from app.modules.enterprise_workflows import router as ew_router
from app.modules.enterprise_workflows.entities import APPROVABLE_ENTITIES


@pytest.mark.asyncio
async def test_entity_types_are_exactly_the_registry() -> None:
    types = await ew_router.list_entity_types(_perm=None)
    assert types == sorted(APPROVABLE_ENTITIES)
    assert "purchase_order" in types


def test_entity_types_route_is_not_shadowed_by_workflow_id() -> None:
    paths = [getattr(r, "path", "") for r in ew_router.router.routes]
    assert paths.index("/entity-types/") < paths.index("/{workflow_id}")
