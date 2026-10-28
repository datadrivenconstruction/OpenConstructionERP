"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site-inventory deletion guards: the ledger refuses to be cascaded away.

Before these verbs existed the module had no delete route at all, so a stock item
or a storage location entered by mistake stayed on the register for good. Adding
the verb naively would have been worse than leaving it out: ``StockItem.movements``
carries ``cascade="all, delete-orphan"`` and the database foreign key carries
``ON DELETE CASCADE``, so deleting an item takes its whole movement history with
it and reports 204. A location's movement columns are ``SET NULL``, so deleting a
location blanks it off every movement that happened there, equally quietly.

So the verbs ship with the refusal built in:

* An empty location and an item that never moved delete cleanly.
* A location any movement names, or any item defaults to, refuses with 409
  naming the holders by count and kind.
* An item with a movement history refuses with 409 naming the movement count.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

BASE = "/api/v1/site-inventory"


# -- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.projects import models as _project_models  # noqa: F401
        from app.modules.site_inventory import models as _si_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, *, role: str) -> None:
    """Force ``role`` and ``is_active=True`` on a user via a direct DB write."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    """One editor with a project to hold the stock register."""
    email = f"si-{uuid.uuid4().hex[:8]}@si-test.io"
    password = f"SiDel{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Stock Guard"},
    )
    assert reg.status_code in (200, 201), reg.text
    uid = reg.json()["id"]
    await _set_role(email, role="editor")

    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=project_id,
                name="Stock-Guard-Project",
                owner_id=uuid.UUID(uid),
                status="active",
                currency="EUR",
            )
        )
        await s.commit()

    return {"headers": headers, "project_id": str(project_id)}


# -- Helpers ----------------------------------------------------------------


def _project_base(world: dict) -> str:
    return f"{BASE}/projects/{world['project_id']}"


async def _new_location(client: AsyncClient, world: dict, **extra: object) -> str:
    body: dict = {"name": f"Yard {uuid.uuid4().hex[:4]}"}
    body.update(extra)
    resp = await client.post(f"{_project_base(world)}/locations", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_item(client: AsyncClient, world: dict, **extra: object) -> str:
    body: dict = {"name": f"Rebar B500B {uuid.uuid4().hex[:4]}", "unit": "t"}
    body.update(extra)
    resp = await client.post(f"{_project_base(world)}/items", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _record_movement(client: AsyncClient, world: dict, **body: object) -> dict:
    resp = await client.post(f"{_project_base(world)}/movements", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


# -- An empty register entry still deletes ----------------------------------


@pytest.mark.asyncio
async def test_empty_location_deletes_cleanly(http_client, world):
    """A location wrongly typed in, before anything was stored there, goes."""
    h = world["headers"]
    location_id = await _new_location(http_client, world)

    resp = await http_client.delete(f"{_project_base(world)}/locations/{location_id}", headers=h)
    assert resp.status_code == 204, f"an empty location must delete: {resp.status_code} {resp.text}"

    listing = await http_client.get(f"{_project_base(world)}/locations", headers=h)
    assert listing.status_code == 200, listing.text
    assert location_id not in [row["id"] for row in listing.json()], "the location survived its delete"


@pytest.mark.asyncio
async def test_item_that_never_moved_deletes_cleanly(http_client, world):
    """A stock item entered by mistake, with no movements, goes."""
    h = world["headers"]
    item_id = await _new_item(http_client, world)

    resp = await http_client.delete(f"{_project_base(world)}/items/{item_id}", headers=h)
    assert resp.status_code == 204, f"an unmoved item must delete: {resp.status_code} {resp.text}"

    listing = await http_client.get(f"{_project_base(world)}/items", headers=h)
    assert listing.status_code == 200, listing.text
    assert item_id not in [row["id"] for row in listing.json()], "the item survived its delete"


# -- Held by the ledger -----------------------------------------------------


@pytest.mark.asyncio
async def test_item_with_movements_refuses_deletion(http_client, world):
    """The refusal is what stops the cascade wiping the movement history."""
    h = world["headers"]
    item_id = await _new_item(http_client, world)
    location_id = await _new_location(http_client, world)
    await _record_movement(
        http_client,
        world,
        item_id=item_id,
        movement_type="INBOUND",
        quantity="12.0000",
        unit_cost="740.00",
        currency="EUR",
        location_id=location_id,
    )

    resp = await http_client.delete(f"{_project_base(world)}/items/{item_id}", headers=h)
    assert resp.status_code == 409, f"an item with a movement history must refuse deletion, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert "1 recorded movement" in detail, detail
    assert "1 recorded movements" not in detail, "singular and plural are chosen per count"

    # The ledger is intact: the item and its movement both survived.
    listing = await http_client.get(f"{_project_base(world)}/items", headers=h)
    assert item_id in [row["id"] for row in listing.json()]
    movements = await http_client.get(f"{_project_base(world)}/movements", headers=h)
    assert any(m["item_id"] == item_id for m in movements.json()), "the movement history was destroyed"


@pytest.mark.asyncio
async def test_location_holding_stock_refuses_deletion(http_client, world):
    """Non-zero stock on hand is named as its own holder kind."""
    h = world["headers"]
    location_id = await _new_location(http_client, world)
    item_id = await _new_item(http_client, world)
    await _record_movement(
        http_client,
        world,
        item_id=item_id,
        movement_type="INBOUND",
        quantity="8.0000",
        unit_cost="700.00",
        currency="EUR",
        location_id=location_id,
    )

    resp = await http_client.delete(f"{_project_base(world)}/locations/{location_id}", headers=h)
    assert resp.status_code == 409, f"a location holding stock must refuse deletion, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert "1 stock item with stock still on hand there" in detail, detail
    assert "1 recorded movement" in detail, detail


@pytest.mark.asyncio
async def test_location_that_nets_to_zero_still_refuses(http_client, world):
    """Zero on hand is not an empty location.

    Ten in and ten out leaves nothing standing there, but the movements still
    name the location and their ``location_id`` is ``SET NULL``, so deleting it
    would blank the history of where that material went without saying so.
    """
    h = world["headers"]
    location_id = await _new_location(http_client, world)
    item_id = await _new_item(http_client, world)
    for movement_type in ("INBOUND", "CONSUMPTION"):
        await _record_movement(
            http_client,
            world,
            item_id=item_id,
            movement_type=movement_type,
            quantity="10.0000",
            unit_cost="700.00",
            currency="EUR",
            location_id=location_id,
        )

    on_hand = await http_client.get(f"{_project_base(world)}/stock-on-hand", headers=h)
    assert on_hand.status_code == 200, on_hand.text

    resp = await http_client.delete(f"{_project_base(world)}/locations/{location_id}", headers=h)
    assert resp.status_code == 409, f"a location with a movement history must refuse deletion, {resp.status_code}"
    detail = resp.json()["detail"]
    assert "2 recorded movements" in detail, detail
    # Nothing is standing there, so on-hand must not be named as a holder.
    assert "stock still on hand" not in detail, detail


@pytest.mark.asyncio
async def test_location_an_item_defaults_to_refuses_deletion(http_client, world):
    """An item pointing at the location as its default holds it too."""
    h = world["headers"]
    location_id = await _new_location(http_client, world)
    await _new_item(http_client, world, default_location_id=location_id)

    resp = await http_client.delete(f"{_project_base(world)}/locations/{location_id}", headers=h)
    assert resp.status_code == 409, f"a defaulted-to location must refuse deletion, got {resp.status_code}"
    assert "1 stock item that defaults to it" in resp.json()["detail"], resp.text


@pytest.mark.asyncio
async def test_transfer_destination_leg_also_holds_the_location(http_client, world):
    """A location is held by ``to_location_id`` as well as ``location_id``.

    Counting only the source leg would let a transfer destination be deleted
    while movements still point at it.
    """
    h = world["headers"]
    source_id = await _new_location(http_client, world)
    destination_id = await _new_location(http_client, world)
    item_id = await _new_item(http_client, world)
    await _record_movement(
        http_client,
        world,
        item_id=item_id,
        movement_type="INBOUND",
        quantity="5.0000",
        unit_cost="700.00",
        currency="EUR",
        location_id=source_id,
    )
    await _record_movement(
        http_client,
        world,
        item_id=item_id,
        movement_type="TRANSFER",
        quantity="5.0000",
        unit_cost="700.00",
        currency="EUR",
        location_id=source_id,
        to_location_id=destination_id,
    )

    resp = await http_client.delete(f"{_project_base(world)}/locations/{destination_id}", headers=h)
    assert resp.status_code == 409, f"a transfer destination must refuse deletion, got {resp.status_code}"
    assert "1 recorded movement" in resp.json()["detail"], resp.text


# -- Scoping ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_an_unknown_item_is_404_not_204(http_client, world):
    """A missing id must not report success."""
    resp = await http_client.delete(
        f"{_project_base(world)}/items/{uuid.uuid4()}",
        headers=world["headers"],
    )
    assert resp.status_code == 404, f"an unknown item must 404, got {resp.status_code}"


@pytest.mark.asyncio
async def test_deleting_an_unknown_location_is_404_not_204(http_client, world):
    """A missing id must not report success."""
    resp = await http_client.delete(
        f"{_project_base(world)}/locations/{uuid.uuid4()}",
        headers=world["headers"],
    )
    assert resp.status_code == 404, f"an unknown location must 404, got {resp.status_code}"
