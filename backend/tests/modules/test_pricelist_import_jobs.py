"""A regional price list is read and imported as background jobs the import screen polls.

A list of tens of thousands of voci outlasts the 120 s the proxy waits, so the
screen stores the upload once, then follows a preview job and an import job.
Boots the app against the conftest database, uploads trimmed real lists from
``tests/fixtures/pricelists/`` and reads the stored cost items back.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"
BASE = "/api/v1/costs/import/pricelist"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.costs import models as _costs_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def _sign_in(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"prezzario-job-{uuid.uuid4().hex[:6]}@pricelist.io"
    password = f"Prezzario{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Prezzario"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def headers(http_client) -> dict[str, str]:
    return await _sign_in(http_client)


def _file(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def _stored(catalog: str):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        return list((await s.execute(select(CostItem).where(CostItem.region == catalog))).scalars())


async def _finished(http_client, headers, job_id: str) -> dict[str, Any]:
    """Poll the job the way the screen does until it stops running."""
    deadline = time.monotonic() + 120
    while True:
        resp = await http_client.get(f"{BASE}/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        view = resp.json()
        if view["status"] not in ("pending", "started"):
            return view
        assert time.monotonic() < deadline, view
        await asyncio.sleep(0.2)


async def _upload(http_client, headers, name: str, content: bytes, **data: str) -> tuple[str, dict[str, Any]]:
    resp = await http_client.post(f"{BASE}/uploads/", files={"file": (name, content)}, data=data, headers=headers)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    return body["upload_id"], await _finished(http_client, headers, body["job_id"])


async def _import(http_client, headers, upload_id: str, catalog: str, **data: Any) -> dict[str, Any]:
    resp = await http_client.post(
        f"{BASE}/uploads/{upload_id}/import/", data={"catalog_name": catalog, **data}, headers=headers
    )
    assert resp.status_code == 202, resp.text
    return await _finished(http_client, headers, resp.json()["job_id"])


@pytest.mark.asyncio
async def test_the_list_is_previewed_then_imported_through_jobs(http_client, headers) -> None:
    upload_id, preview = await _upload(http_client, headers, "Firenze-2025.xml", _file("toscana_firenze_2025.xml"))
    assert preview["status"] == "success", preview
    assert preview["kind"] == "preview" and preview["progress_percent"] == 100
    report = preview["result"]
    assert report["source"]["suggested_catalog_name"] == "Toscana 2025 - Firenze"
    assert report["counts"]["importable"] == 9
    assert preview["rows_read"] == report["counts"]["rows"]

    catalog = f"Toscana 2025 {uuid.uuid4().hex[:6]}"
    done = await _import(http_client, headers, upload_id, catalog, expected_rows=report["counts"]["rows"])
    assert done["status"] == "success", done
    assert done["kind"] == "import" and done["progress_percent"] == 100
    assert done["result"]["imported"] == 9 == done["imported"]
    assert done["result"]["durability"] == "atomic"
    items = await _stored(catalog)
    assert len(items) == 9
    assert {i.currency for i in items} == {"EUR"}
    assert {str(i.catalog_id) for i in items} == {done["result"]["catalog_id"]}
    assert all(i.metadata_["prezzario"]["region_code"] == "TOS" for i in items)

    # The upload went with the import: it cannot be imported a second time.
    again = await http_client.post(
        f"{BASE}/uploads/{upload_id}/import/", data={"catalog_name": catalog + " bis"}, headers=headers
    )
    assert again.status_code == 404 and again.json()["detail"]["code"] == "upload_not_found"


@pytest.mark.asyncio
async def test_a_refusal_ends_the_job_with_its_code_and_keeps_the_upload(http_client, headers) -> None:
    taken = f"Veneto 2026 {uuid.uuid4().hex[:6]}"
    first_id, _ = await _upload(http_client, headers, "prezzario.xml", _file("veneto_2026.xml"))
    assert (await _import(http_client, headers, first_id, taken))["status"] == "success"

    upload_id, _ = await _upload(http_client, headers, "prezzario.xml", _file("veneto_2026.xml"))
    refused = await _import(http_client, headers, upload_id, taken)
    assert refused["status"] == "failed"
    assert refused["error"]["code"] == "catalog_name_unavailable"
    assert refused["error"]["params"] == {"suggestion": f"{taken} (2)"}
    assert taken not in refused["error"]["message"]

    # Corrected, the same upload imports.
    other = taken + " b"
    done = await _import(http_client, headers, upload_id, other)
    assert done["status"] == "success", done
    assert len(await _stored(other)) == done["result"]["imported"] > 0


@pytest.mark.asyncio
async def test_nothing_importable_fails_the_job_and_leaves_no_catalogue(http_client, headers) -> None:
    head, _, _rest = _file("lombardia_2026.xml").partition(b"</voci>")
    empty = head + b"</voci>\n  </voci>\n</report>\n"
    upload_id, preview = await _upload(http_client, headers, "lom.xml", empty)
    assert preview["status"] == "success" and preview["result"]["counts"]["importable"] == 0
    name = f"Vuoto {uuid.uuid4().hex[:6]}"
    refused = await _import(http_client, headers, upload_id, name)
    assert refused["status"] == "failed" and refused["error"]["code"] == "nothing_to_import"
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostCatalog

    async with async_session_factory() as s:
        assert (await s.execute(select(CostCatalog).where(CostCatalog.name == name))).first() is None
    await http_client.delete(f"{BASE}/uploads/{upload_id}/", headers=headers)


@pytest.mark.asyncio
async def test_a_correction_previews_the_stored_upload_again(http_client, headers) -> None:
    upload_id, first = await _upload(http_client, headers, "prezzi.csv", _file("piemonte_2023.csv"))
    assert first["status"] == "success"
    resp = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={"region_code": "XX"}, headers=headers)
    bad = await _finished(http_client, headers, resp.json()["job_id"])
    assert bad["status"] == "failed" and bad["error"]["code"] == "invalid_region"
    resp = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={"region_code": "PIE"}, headers=headers)
    ok = await _finished(http_client, headers, resp.json()["job_id"])
    assert ok["status"] == "success"
    assert ok["result"]["source"]["region_detected_from"] == "user"
    assert "region_inferred" not in ok["result"]["warnings"]
    gone = await http_client.delete(f"{BASE}/uploads/{upload_id}/", headers=headers)
    assert gone.status_code == 204
    after = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={}, headers=headers)
    assert after.status_code == 404 and after.json()["detail"]["code"] == "upload_not_found"


@pytest.mark.asyncio
async def test_an_upload_and_its_jobs_belong_to_whoever_made_them(http_client, headers) -> None:
    upload_id, preview = await _upload(http_client, headers, "prezzi.json", _file("umbria_2025.json"))
    stranger = await _sign_in(http_client)
    seen = await http_client.get(f"{BASE}/jobs/{preview['job_id']}", headers=stranger)
    assert seen.status_code == 404
    taken = await http_client.post(
        f"{BASE}/uploads/{upload_id}/import/", data={"catalog_name": "Altrui"}, headers=stranger
    )
    assert taken.status_code == 404 and taken.json()["detail"]["code"] == "upload_not_found"
    await http_client.delete(f"{BASE}/uploads/{upload_id}/", headers=stranger)
    # A stranger's cancel removes nothing.
    still = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={}, headers=headers)
    assert still.status_code == 202
    await _finished(http_client, headers, still.json()["job_id"])
    await http_client.delete(f"{BASE}/uploads/{upload_id}/", headers=headers)


@pytest.mark.asyncio
async def test_an_upload_nobody_imported_is_swept_after_a_day(http_client, headers) -> None:
    from app.modules.costs import pricelist_jobs

    upload_id, _ = await _upload(http_client, headers, "prezzi.csv", _file("puglia_2026.csv"))
    await pricelist_jobs.sweep_stale_uploads()  # a fresh upload is kept
    still = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={}, headers=headers)
    assert still.status_code == 202
    await _finished(http_client, headers, still.json()["job_id"])
    assert await pricelist_jobs.sweep_stale_uploads(now=time.time() + 2 * 86400) >= 1
    gone = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={}, headers=headers)
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_a_slice_writes_only_the_codes_the_catalogue_does_not_hold(app_instance) -> None:
    """The batched insert looks the slice's codes up once and skips those already there."""
    from app.database import async_session_factory
    from app.modules.costs.pricelist_import import insert_batch
    from app.modules.costs.schemas import CostCatalogCreate
    from app.modules.costs.service import CostCatalogService

    name = f"Lotto {uuid.uuid4().hex[:6]}"
    payload = {"description": "Voce", "unit": "m2", "rate": "10.5", "currency": "EUR", "source": "prezzario_regionale"}
    async with async_session_factory() as session:
        catalog = await CostCatalogService(session).create_catalog(
            CostCatalogCreate(name=name, currency="EUR", description=None), created_by=None, source="import"
        )
        first = await insert_batch(
            session, [{**payload, "code": "A.1"}, {**payload, "code": "A.2"}], catalog_id=catalog.id, region=name
        )
        second = await insert_batch(
            session, [{**payload, "code": "A.2"}, {**payload, "code": "A.3"}], catalog_id=catalog.id, region=name
        )
        await session.commit()
    assert (first, second) == (2, 1)
    assert sorted(i.code for i in await _stored(name)) == ["A.1", "A.2", "A.3"]


@pytest.mark.asyncio
async def test_the_suggested_name_is_one_a_new_catalogue_can_take(http_client, headers) -> None:
    """A list's natural name may already be someone else's catalogue; the preview offers the next free one."""
    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.modules.costs.models import CostCatalog
    from app.modules.costs.schemas import CostCatalogCreate
    from app.modules.costs.service import CostCatalogService

    upload_id, first = await _upload(http_client, headers, "prezzi.json", _file("umbria_2025.json"))
    natural = first["result"]["source"]["suggested_catalog_name"]
    assert natural and not natural.endswith(")")
    # Another user's catalogues, one in other letter case: the lookup ignores case.
    async with async_session_factory() as s:
        service = CostCatalogService(s)
        await service.create_catalog(CostCatalogCreate(name=natural.upper(), currency="EUR"), created_by=None)
        await service.create_catalog(CostCatalogCreate(name=f"{natural} (2)", currency="EUR"), created_by=None)
    try:
        resp = await http_client.post(f"{BASE}/uploads/{upload_id}/preview/", data={}, headers=headers)
        again = await _finished(http_client, headers, resp.json()["job_id"])
        assert again["result"]["source"]["suggested_catalog_name"] == f"{natural} (3)"
        done = await _import(http_client, headers, upload_id, f"{natural} (3)")
        assert done["status"] == "success", done
    finally:
        async with async_session_factory() as s:
            await s.execute(delete(CostCatalog).where(CostCatalog.name.in_([natural.upper(), f"{natural} (2)"])))
            await s.commit()
