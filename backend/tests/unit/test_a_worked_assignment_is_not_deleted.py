# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An assignment that has been worked is not deleted.

Deleting a resource is refused while it has worked assignments (in progress or
completed), because the allocation history of work already done would go with
it. Deleting one of those assignments on its own took the same history away
with no check at all. It now holds the same line and points at cancelling;
planned assignments (proposed, confirmed) and cancelled ones still delete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.unit.test_resources import PROJECT_ID, _make_resource, _make_service


def _assignment(svc, resource, status: str) -> SimpleNamespace:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        resource_id=resource.id,
        project_id=PROJECT_ID,
        start_at=start,
        end_at=start + timedelta(days=5),
        allocation_percent=100,
        status=status,
    )
    svc.assignment_repo.rows[row.id] = row
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["in_progress", "completed"])
async def test_a_worked_assignment_is_not_deleted(status: str) -> None:
    svc = _make_service()
    resource = _make_resource(svc)
    row = _assignment(svc, resource, status)

    with pytest.raises(HTTPException) as exc:
        await svc.delete_assignment(row.id)
    assert exc.value.status_code == 409
    assert row.id in svc.assignment_repo.rows


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["proposed", "confirmed", "cancelled"])
async def test_an_unworked_assignment_is_still_deleted(status: str) -> None:
    svc = _make_service()
    resource = _make_resource(svc)
    row = _assignment(svc, resource, status)

    await svc.delete_assignment(row.id)
    assert row.id not in svc.assignment_repo.rows
