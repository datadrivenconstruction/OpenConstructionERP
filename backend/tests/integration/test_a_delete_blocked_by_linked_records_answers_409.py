"""A delete the database refuses on a foreign key answers 409 fk_conflict, not 500.

The route below deletes a parent row that a child row still references, on the
real database, through the real app and its global exception handler.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

_PARENT = "zz_test_fk_parent"
_CHILD = "zz_test_fk_child"


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.database import async_session_factory, engine
    from app.main import create_app

    app = create_app()

    @app.delete("/api/v1/_test/fk-parent/{parent_id}", status_code=204)
    async def _delete_parent(parent_id: str) -> None:
        async with async_session_factory() as session:
            await session.execute(text(f"DELETE FROM {_PARENT} WHERE id = :id"), {"id": parent_id})
            await session.commit()

    async with app.router.lifespan_context(app):
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {_CHILD}"))
            await conn.execute(text(f"DROP TABLE IF EXISTS {_PARENT}"))
            await conn.execute(text(f"CREATE TABLE {_PARENT} (id VARCHAR(36) PRIMARY KEY)"))
            await conn.execute(
                text(
                    f"CREATE TABLE {_CHILD} (id VARCHAR(36) PRIMARY KEY, parent_id VARCHAR(36) REFERENCES {_PARENT}(id))"
                )
            )
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {_CHILD}"))
            await conn.execute(text(f"DROP TABLE IF EXISTS {_PARENT}"))


@pytest.mark.asyncio
async def test_deleting_a_referenced_row_answers_409_naming_the_linked_records(client: AsyncClient) -> None:
    from app.database import engine

    parent = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(f"INSERT INTO {_PARENT} (id) VALUES (:id)"), {"id": parent})
        await conn.execute(
            text(f"INSERT INTO {_CHILD} (id, parent_id) VALUES (:id, :p)"), {"id": str(uuid.uuid4()), "p": parent}
        )

    response = await client.delete(f"/api/v1/_test/fk-parent/{parent}")

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "fk_conflict"
    assert body["blocked_by"] == "zz test fk child"
