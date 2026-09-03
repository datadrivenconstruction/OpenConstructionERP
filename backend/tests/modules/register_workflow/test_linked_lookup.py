# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The reverse lookup the base modules decorate their rows from.

``GET /register-workflow/linked?project_id=&entity_type=`` answers
"which register item stands behind this native row" for a whole page in
one call. What this file proves:

1. An RFI raised through the register is returned for ``entity_type=rfi``
   with the native RFI id it mirrors, and NOT for ``entity_type=rfq``.
2. ``entity_ids`` narrows to the rows on screen; an id that is not on the
   project answers nothing rather than everything.
3. An entity type the registers cannot mirror is refused up front.

Mounted as a bare app with the auth dependencies overridden, so no JWT is
minted and no module loader runs. Neutral data only.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project
from app.modules.register_workflow.router import router as rw_router
from app.modules.users.models import User
from tests._pg import isolated_engine

USER_ID = "00000000-0000-0000-0000-0000000000b2"
BASE = "/api/v1/register-workflow"


@pytest_asyncio.fixture
async def ctx():
    """A live app + a project the overridden user may access."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(USER_ID),
                email=f"ll-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Linked Lookup Test",
                role="admin",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name=f"Acme Electrical fit-out {uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
            )
            s.add(project)
            await s.commit()
            project_id = str(project.id)

        app = FastAPI()
        app.include_router(rw_router, prefix=BASE)
        app.dependency_overrides[get_current_user_id] = lambda: USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": USER_ID,
            "role": "admin",
            "permissions": ["*"],
        }

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id


async def _raise_rfi(client, project_id: str, title: str) -> dict:
    r = await client.post(
        f"{BASE}/items",
        json={
            "project_id": project_id,
            "kind": "rfi",
            "title": title,
            "fields": {"Question": "Which revision of the switchboard schedule applies?"},
            "recipient_contact_ids": [],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _linked(client, project_id: str, entity_type: str, **params) -> list[dict]:
    r = await client.get(
        f"{BASE}/linked",
        params={"project_id": project_id, "entity_type": entity_type, **params},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


@pytest.mark.asyncio
async def test_rfi_item_is_found_by_its_native_id_and_only_under_rfi(ctx) -> None:
    client, pid = ctx
    item = await _raise_rfi(client, pid, "Switchboard schedule revision")
    # The raise mirrored itself into the native RFI register.
    assert item["linked_entity_type"] == "rfi"
    assert item["linked_entity_id"]
    assert item["reference"].startswith("REG-RFI-25406-")

    rows = await _linked(client, pid, "rfi")
    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == item["id"]
    assert row["linked_entity_id"] == item["linked_entity_id"]
    assert row["reference"] == item["reference"]
    assert row["kind"] == "rfi"
    assert row["status"] == "open"
    assert row["title"] == "Switchboard schedule revision"
    assert row["is_overdue"] is False
    assert row["ball_in_court"] in ("us", "them")
    assert set(row) == {
        "item_id",
        "reference",
        "kind",
        "status",
        "title",
        "due_date",
        "is_overdue",
        "linked_entity_id",
        "ball_in_court",
    }

    # The same item is NOT an RFQ: the lookup is keyed by the register the
    # native row lives in, never by "anything on the project".
    assert await _linked(client, pid, "rfq") == []


@pytest.mark.asyncio
async def test_entity_ids_narrows_to_the_rows_on_screen(ctx) -> None:
    client, pid = ctx
    first = await _raise_rfi(client, pid, "First question")
    second = await _raise_rfi(client, pid, "Second question")
    assert first["linked_entity_id"] != second["linked_entity_id"]

    both = await _linked(client, pid, "rfi")
    assert {r["item_id"] for r in both} == {first["id"], second["id"]}

    only_first = await _linked(client, pid, "rfi", entity_ids=first["linked_entity_id"])
    assert [r["item_id"] for r in only_first] == [first["id"]]

    # A comma list with padding and an unknown id still answers just the
    # rows it can name - never the whole project.
    mixed = await _linked(
        client,
        pid,
        "rfi",
        entity_ids=f" {second['linked_entity_id']} , {uuid.uuid4()} ,",
    )
    assert [r["item_id"] for r in mixed] == [second["id"]]

    # An id that belongs to nothing answers nothing.
    assert await _linked(client, pid, "rfi", entity_ids=str(uuid.uuid4())) == []
    # "Nothing on screen" is an empty answer, not "everything".
    assert await _linked(client, pid, "rfi", entity_ids="") == []


@pytest.mark.asyncio
async def test_unknown_entity_type_is_refused(ctx) -> None:
    client, pid = ctx
    r = await client.get(f"{BASE}/linked", params={"project_id": pid, "entity_type": "toolbox"})
    assert r.status_code == 422
