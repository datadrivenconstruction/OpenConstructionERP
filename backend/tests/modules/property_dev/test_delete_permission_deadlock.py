# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A development owned by an EDITOR can be deleted by nobody.

Two independent walls guard DELETE /developments/{dev_id}, and no role
satisfies both at once when the owning project belongs to an editor:

  * ``RequirePermission("property_dev.delete")`` maps to MANAGER, so the
    editor who owns the project is refused with 403.
  * ``_verify_owner_via_development`` is strict, only ``project.owner_id``
    passes, so the manager and the admin who do hold the permission are
    refused with 404.

The row is therefore permanent. Its owner can still read it and cannot
remove it, and nobody with the verb can reach it.

Why the existing suite cannot see this. Every delete test in this package
is a DENIAL test: test_r8_member_denied_delete_plot asserts the status is
"in (403, 404)", which is satisfied just as well by a world where the
operation is impossible for everyone. Asserting that a request is refused
can never detect that every request is refused. This test asserts the
positive half, that exactly one role gets through, which is the half
nobody wrote.

The three roles are all asserted on purpose. A test that only checked the
owner would pass against a "fix" that simply let the global admin bypass
ownership, and that direction is barred: strict ownership here is
deliberate and closes the cross-tenant broker IDOR (deferred #66). The
manager and admin cells are the control that keeps the repair honest, so
this file fails both when nobody can delete and when the wrong party can.
"""

import uuid

import pytest
from httpx import AsyncClient

from .conftest import _register_user


async def _editor_owning_a_development(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Register an editor, then have them own a project and a development."""
    _uid, _email, headers = await _register_user(client, role="editor", tag="dlk")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Deadlock-{uuid.uuid4().hex[:6]}",
            "description": "owner is an editor",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), f"editor could not create a project: {proj.text}"

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": proj.json()["id"],
            "code": f"DLK-{uuid.uuid4().hex[:6]}",
            "name": "Deadlock development",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, f"editor could not create a development: {dev.text}"
    return headers, dev.json()["id"]


@pytest.mark.asyncio
async def test_an_editor_owned_development_can_be_deleted_by_its_owner(client: AsyncClient):
    """All three roles, in denial-first order so the owner's 204 is real."""
    owner_headers, dev_id = await _editor_owning_a_development(client)
    path = f"/api/v1/property-dev/developments/{dev_id}"

    # A manager who does not own the project holds the verb and must still
    # be refused by the ownership wall.
    _uid, _email, manager_headers = await _register_user(client, role="manager", tag="dlkm")
    res = await client.delete(path, headers=manager_headers)
    assert res.status_code == 404, f"non-owner manager must not delete, got {res.status_code}: {res.text}"

    # The global admin must not cross the tenant boundary either. If this
    # cell ever turns into 204 the ownership wall has been weakened, which
    # is the one repair that is not allowed here.
    _uid, _email, admin_headers = await _register_user(client, role="admin", tag="dlka")
    res = await client.delete(path, headers=admin_headers)
    assert res.status_code == 404, f"non-owner admin must not delete, got {res.status_code}: {res.text}"

    # The owner has to be able to remove their own development. This is the
    # cell that is red today: the editor owns the project and is refused by
    # the permission wall with 403.
    res = await client.delete(path, headers=owner_headers)
    assert res.status_code == 204, f"the owning editor must be able to delete, got {res.status_code}: {res.text}"

    # And it is really gone, not merely answered 204.
    gone = await client.get(path, headers=owner_headers)
    assert gone.status_code == 404, f"development survived its own deletion: {gone.status_code}"
