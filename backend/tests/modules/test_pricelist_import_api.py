"""Import a regional price list through the API: preview, confirm, persist.

Boots the app against the conftest database, uploads trimmed real lists from
``tests/fixtures/pricelists/`` and reads the stored cost items back.
"""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pricelists"
PREVIEW = "/api/v1/costs/import/pricelist/preview/"
IMPORT = "/api/v1/costs/import/pricelist/file/"


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


@pytest_asyncio.fixture(scope="module")
async def headers(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"prezzario-{uuid.uuid4().hex[:6]}@pricelist.io"
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


def _file(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _lombardia_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Prezzario_2026_LOM261_XML/A) Parte 1.xml", _file("lombardia_2026.xml"))
        zf.writestr("Prezzario_2026_LOM261_XML/F) Precedente struttura.xml", _file("lombardia_2026_legacy.xml"))
    return buf.getvalue()


async def _stored(catalog: str):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        return list((await s.execute(select(CostItem).where(CostItem.region == catalog))).scalars())


@pytest.mark.asyncio
async def test_preview_reports_the_list_without_writing(http_client, headers) -> None:
    resp = await http_client.post(
        PREVIEW,
        files={"file": ("Firenze-2025.xml", _file("toscana_firenze_2025.xml"), "application/xml")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["format"] == "toscana_xml"
    assert body["source"]["suggested_catalog_name"] == "Toscana 2025 - Firenze"
    assert body["source"]["licence"] == "CC BY 3.0"
    assert body["counts"]["importable"] == 9
    assert await _stored("Toscana 2025 - Firenze") == []


@pytest.mark.asyncio
async def test_import_creates_the_catalogue_and_stores_the_voci(http_client, headers) -> None:
    name = f"Lombardia 2026 {uuid.uuid4().hex[:6]}"
    resp = await http_client.post(
        IMPORT,
        files={"file": ("Prezzario_2026_LOM261_XML.zip", _lombardia_zip(), "application/zip")},
        data={"catalog_name": name},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 5
    assert body["skipped"] == {"zero_rate": 1}
    assert body["catalog_currency"] == "EUR"

    items = {i.code: i for i in await _stored(name)}
    assert len(items) == 5
    item = items["LOM261.OC.EEA.Pa01.C0625.Sb010.0000.-"]
    assert Decimal(str(item.rate)) == Decimal("310.62")
    assert item.currency == "EUR" and item.unit == "pcs" and item.source == "prezzario_regionale"
    assert item.classification == {"voci": item.code}
    meta = item.metadata_["prezzario"]
    assert meta["region_code"] == "LOM" and meta["edition"] == "2026"
    assert meta["labour_share_pct"] == "5.13"
    total = sum(Decimal(str(c["cost"])) for c in item.components)
    assert total == Decimal("310.62")


@pytest.mark.asyncio
async def test_a_taken_name_is_refused_with_a_code(http_client, headers) -> None:
    name = f"Veneto 2026 {uuid.uuid4().hex[:6]}"
    files = {"file": ("prezzario.xml", _file("veneto_2026.xml"), "application/xml")}
    first = await http_client.post(IMPORT, files=files, data={"catalog_name": name}, headers=headers)
    assert first.status_code == 200, first.text
    files = {"file": ("prezzario.xml", _file("veneto_2026.xml"), "application/xml")}
    again = await http_client.post(IMPORT, files=files, data={"catalog_name": name}, headers=headers)
    assert again.status_code == 409
    detail = again.json()["detail"]
    # Neutral: the name may be another user's, and the refusal must not say so.
    assert detail["code"] == "catalog_name_unavailable"
    assert name not in detail["message"] and "name" not in detail
    assert detail["suggestion"] == f"{name} (2)"


@pytest.mark.asyncio
async def test_a_damaged_zip_member_is_refused_on_import_not_failed(http_client, headers) -> None:
    from tests.unit.test_pricelist_text_encodings import _damaged_zip

    name = f"Puglia 2026 {uuid.uuid4().hex[:6]}"
    resp = await http_client.post(
        IMPORT,
        files={"file": ("puglia.zip", _damaged_zip(), "application/zip")},
        data={"catalog_name": name},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "zip_member_corrupt"
    assert await _stored(name) == []


@pytest.mark.asyncio
async def test_a_utf16_csv_is_previewed_like_its_utf8_original(http_client, headers) -> None:
    text = _file("puglia_2026.csv").decode("utf-8")
    plain = await http_client.post(
        PREVIEW, files={"file": ("prezzi.csv", text.encode("utf-8"), "text/csv")}, headers=headers
    )
    wide = await http_client.post(
        PREVIEW, files={"file": ("prezzi.csv", text.encode("utf-16"), "text/csv")}, headers=headers
    )
    assert plain.status_code == wide.status_code == 200, wide.text
    assert wide.json()["counts"] == plain.json()["counts"]
    assert wide.json()["counts"]["importable"] > 0


@pytest.mark.asyncio
async def test_nothing_importable_leaves_no_catalogue_behind(http_client, headers) -> None:
    name = f"Vuoto {uuid.uuid4().hex[:6]}"
    only_zero = _file("lombardia_2026.xml")
    # Keep the header and the one voce priced at 0.00, the first record.
    head, _, rest = only_zero.partition(b"</voci>")
    empty = head + b"</voci>\n  </voci>\n</report>\n"
    resp = await http_client.post(
        IMPORT, files={"file": ("lom.xml", empty, "application/xml")}, data={"catalog_name": name}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "nothing_to_import"
    # The catalogue created for the run went with it, so the name is free again.
    retry = await http_client.post(
        IMPORT,
        files={"file": ("lom.xml", _file("lombardia_2026.xml"), "application/xml")},
        data={"catalog_name": name},
        headers=headers,
    )
    assert retry.status_code == 200, retry.text


@pytest.mark.asyncio
async def test_a_zip_bomb_is_refused_before_anything_is_written(http_client, headers) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lista.xml", b"<a>" + b"0" * (4 * 1024 * 1024) + b"</a>")
    resp = await http_client.post(
        PREVIEW, files={"file": ("bomb.zip", buf.getvalue(), "application/zip")}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "zip_ratio_suspicious"


@pytest.mark.asyncio
async def test_region_override_is_validated_and_applied(http_client, headers) -> None:
    files = {"file": ("prezzi.csv", _file("piemonte_2023.csv"), "text/csv")}
    bad = await http_client.post(PREVIEW, files=files, data={"region_code": "XX"}, headers=headers)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_region"
    files = {"file": ("prezzi.csv", _file("piemonte_2023.csv"), "text/csv")}
    ok = await http_client.post(PREVIEW, files=files, data={"region_code": "PIE"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["source"]["region_detected_from"] == "user"
    assert "region_inferred" not in ok.json()["warnings"]


@pytest.mark.asyncio
async def test_the_import_needs_a_signed_in_user(http_client) -> None:
    resp = await http_client.post(PREVIEW, files={"file": ("x.xml", _file("veneto_2026.xml"), "application/xml")})
    assert resp.status_code in (401, 403)
