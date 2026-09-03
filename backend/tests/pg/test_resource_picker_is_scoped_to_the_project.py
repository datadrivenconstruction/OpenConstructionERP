# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A site picker must offer this project's roster, not the whole install.

The repository has carried the ``project_id`` filter from the start; the
service dropped it and the endpoint never asked for it, so every caller got
the tenant-wide register. On a German site the day-recording widget was
offering a project manager from a Canadian project.

Asserted against real SQL because the filter is an ``OR`` against ``NULL``:
the project's own crews plus the unhomed company pool, and "unhomed" is a
null comparison an in-memory stub would not reproduce.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _project(session, name: str) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "roster-owner@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Roster owner")
        session.add(owner)
        await session.flush()
    project = Project(name=name, owner_id=owner.id, country_code="DE", currency="EUR")
    session.add(project)
    await session.flush()
    return uuid.UUID(str(project.id))


async def _resource(session, code: str, home: uuid.UUID | None) -> None:
    from app.modules.resources.models import Resource

    session.add(
        Resource(
            id=uuid.uuid4(),
            code=code,
            name=f"Crew {code}",
            resource_type="person",
            home_project_id=home,
            default_cost_rate=Decimal("42.50"),
            currency="EUR",
            status="active",
            metadata_={},
        )
    )
    await session.flush()


async def test_the_roster_is_this_project_plus_the_unhomed_pool(pg_session) -> None:
    """Scoped: own crews and the company pool. Never another project's."""
    from app.modules.resources.service import ResourcesService

    tag = uuid.uuid4().hex[:8]
    here = await _project(pg_session, f"Baustelle Hier {tag}")
    elsewhere = await _project(pg_session, f"Baustelle Anderswo {tag}")
    await _resource(pg_session, f"{tag}-HERE-01", here)
    await _resource(pg_session, f"{tag}-THERE-01", elsewhere)
    await _resource(pg_session, f"{tag}-POOL-01", None)

    service = ResourcesService(pg_session)
    items, _ = await service.list_resources(limit=500, project_id=here)
    codes = {r.code for r in items if r.code.startswith(tag)}
    assert codes == {f"{tag}-HERE-01", f"{tag}-POOL-01"}, f"the picker offered the wrong roster: {sorted(codes)}"


async def test_the_unscoped_register_still_sees_everything(pg_session) -> None:
    """The resources page is tenant-wide and must not narrow by accident."""
    from app.modules.resources.service import ResourcesService

    tag = uuid.uuid4().hex[:8]
    here = await _project(pg_session, f"Baustelle Register {tag}")
    await _resource(pg_session, f"{tag}-HERE-01", here)
    await _resource(pg_session, f"{tag}-POOL-01", None)

    service = ResourcesService(pg_session)
    items, _ = await service.list_resources(limit=500)
    codes = {r.code for r in items if r.code.startswith(tag)}
    assert codes == {f"{tag}-HERE-01", f"{tag}-POOL-01"}


async def test_the_endpoint_declares_the_filter(pg_session) -> None:
    """The parameter has to reach the wire, not just the service.

    The defect was one unpassed argument between two layers that both
    already understood it, so the signature is what is gated here.
    """
    import inspect

    from app.modules.resources.router import list_resources

    params = inspect.signature(list_resources).parameters
    assert "project_id" in params, "the resources endpoint does not accept a project filter"


async def test_the_endpoint_answers_with_a_page_not_a_bare_array(pg_session) -> None:
    """A capped list that cannot say it was capped is the bug this pins.

    The route caps at 500 and every caller asks for the cap, so a tenant with
    more resources than that was shown a page and told nothing. The service
    has always returned the count and the route discarded it, which is why
    this asserts the declared response rather than a row: the number existed
    the whole time and simply never reached the wire.

    Asserted against the registered ``response_model`` rather than the return
    annotation. This module imports annotations from ``__future__``, so the
    annotation is the string "ResourceListResponse" and an identity check
    against it passes for any module that happens to spell a name the same
    way. ``response_model`` is also the thing FastAPI actually serialises
    through, so a route could declare the envelope in one and rows in the
    other and only this half would reach the reader.

    ``total`` is named explicitly because it is the field carrying the
    disclosure: a model with ``items`` and no ``total`` satisfies a shape
    check and still tells the reader nothing.
    """
    from app.modules.resources.router import list_resources, router
    from app.modules.resources.schemas import ResourceListResponse

    routes = [r for r in router.routes if getattr(r, "endpoint", None) is list_resources]
    assert len(routes) == 1, f"expected exactly one route for list_resources, found {len(routes)}"
    assert routes[0].response_model is ResourceListResponse, (
        f"the register answers with {routes[0].response_model!r}, not the page envelope"
    )
    fields = ResourceListResponse.model_fields
    assert set(fields) == {"items", "total", "offset", "limit"}, (
        f"the envelope has drifted from {{items, total, offset, limit}}: {sorted(fields)}"
    )
