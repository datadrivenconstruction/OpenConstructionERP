"""Catalogue-name conflicts are neutral, localized and atomic on PostgreSQL."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.i18n import get_locale, load_translations, set_locale, t
from app.dependencies import get_current_user_payload
from app.middleware.accept_language import AcceptLanguageMiddleware
from app.modules.costs.models import CostCatalog
from app.modules.costs.router import _get_catalog_service, router
from app.modules.costs.schemas import CostCatalogCreate, CostCatalogUpdate
from app.modules.costs.service import CostCatalogService
from tests._pg import isolated_engine, transactional_session


@pytest.fixture(autouse=True)
def translations():
    original = get_locale()
    load_translations()
    yield
    set_locale(original)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as value:
        yield value


@pytest.mark.parametrize("locale", ["en", "de", "ru", "pt-BR", "ar"])
async def test_duplicate_is_a_localized_neutral_409_without_echo(session: AsyncSession, locale: str):
    service = CostCatalogService(session)
    secret = "Private <customer> PRICEBOOK"
    await service.create_catalog(CostCatalogCreate(name=secret, currency="EUR"), created_by=uuid.uuid4())
    set_locale(locale)
    with pytest.raises(HTTPException) as error:
        await service.create_catalog(CostCatalogCreate(name=f"  {secret.lower()}  ", currency="USD"))
    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "catalog_name_unavailable",
        "message": t("costs.catalog_name_unavailable"),
    }
    assert error.value.detail["message"] != "costs.catalog_name_unavailable"
    assert "private" not in str(error.value.detail).lower()
    assert "already exists" not in str(error.value.detail).lower()
    assert await session.scalar(select(func.count()).select_from(CostCatalog)) == 1


async def test_http_create_keeps_status_owner_permission_and_private_scope(session: AsyncSession):
    owner, stranger = uuid.uuid4(), uuid.uuid4()
    identity = {"sub": str(owner), "role": "editor", "permissions": ["costs.create", "costs.list", "costs.update"]}
    app = FastAPI()
    app.add_middleware(AcceptLanguageMiddleware)
    app.include_router(router, prefix="/api/v1/costs")
    app.dependency_overrides[get_current_user_payload] = lambda: identity
    app.dependency_overrides[_get_catalog_service] = lambda: CostCatalogService(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://catalog.test") as client:
        created = await client.post("/api/v1/costs/catalogs/", json={"name": "Owner rates", "currency": "eur"})
        assert created.status_code == 201
        assert created.json()["created_by"] == str(owner)
        assert created.json()["currency"] == "EUR"
        catalog_id = created.json()["id"]

        identity["sub"] = str(stranger)
        visible = await client.get("/api/v1/costs/catalogs/")
        assert visible.status_code == 200 and visible.json() == []
        denied = await client.patch(f"/api/v1/costs/catalogs/{catalog_id}", json={"name": "Stolen"})
        assert denied.status_code == 404
        duplicate = await client.post(
            "/api/v1/costs/catalogs/",
            json={"name": "owner RATES", "currency": "USD"},
            headers={"Accept-Language": "de"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "catalog_name_unavailable"
        assert duplicate.json()["detail"]["message"] == t("costs.catalog_name_unavailable", locale="de")
        assert "Owner rates" not in duplicate.text and "owner RATES" not in duplicate.text

        identity.update(role="viewer", permissions=[])
        refused = await client.post("/api/v1/costs/catalogs/", json={"name": "Viewer rates", "currency": "EUR"})
        assert refused.status_code == 403
        assert await session.scalar(select(func.count()).select_from(CostCatalog)) == 1


async def test_rename_uses_the_same_refusal_and_keeps_the_original(session: AsyncSession):
    service = CostCatalogService(session)
    first = await service.create_catalog(CostCatalogCreate(name="First", currency="EUR"))
    first_id = first.id
    await service.create_catalog(CostCatalogCreate(name="Second", currency="EUR"))
    with pytest.raises(HTTPException) as error:
        await service.update_catalog(first_id, CostCatalogUpdate(name=" SECOND "))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "catalog_name_unavailable"
    assert (await service.get_catalog(first_id)).name == "First"
    renamed = await service.update_catalog(first_id, CostCatalogUpdate(name="FIRST"))
    assert renamed.name == "FIRST"


async def test_concurrent_create_serializes_the_name_check():
    """Pause A after its name check; B must wait, not insert into A's gap."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        checked = asyncio.Event()
        release = asyncio.Event()

        class PausedCreator(CostCatalogService):
            async def _assert_name_available(self, name, *, exclude_id=None):
                await super()._assert_name_available(name, exclude_id=exclude_id)
                checked.set()
                await release.wait()

        async with factory() as first, factory() as second, factory() as observer:
            task_a = asyncio.create_task(
                PausedCreator(first).create_catalog(CostCatalogCreate(name="Concurrent", currency="EUR"))
            )
            await asyncio.wait_for(checked.wait(), timeout=10)
            task_b = asyncio.create_task(
                CostCatalogService(second).create_catalog(CostCatalogCreate(name=" concurrent ", currency="USD"))
            )
            try:
                # Before the fix B finishes in the intentional check/insert gap.
                # Observe an actual database lock wait, not merely a slow task.
                async def observe_wait():
                    while not task_b.done():
                        waiting = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                                "AND NOT granted AND database = "
                                "(SELECT oid FROM pg_database WHERE datname = current_database())"
                            )
                        )
                        if waiting:
                            return waiting
                        await asyncio.sleep(0.01)
                    return 0

                assert await asyncio.wait_for(observe_wait(), timeout=10) == 1
                assert not task_b.done()
            finally:
                release.set()
                outcomes = await asyncio.gather(task_a, task_b, return_exceptions=True)
            assert isinstance(outcomes[0], CostCatalog)
            assert isinstance(outcomes[1], HTTPException)
            assert outcomes[1].status_code == 409
            assert outcomes[1].detail["code"] == "catalog_name_unavailable"
            await second.rollback()
            assert await second.scalar(select(func.count()).select_from(CostCatalog)) == 1
