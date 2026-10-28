# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for ``POST /api/v1/match_elements/sessions/from-image``.

The image source (MAPPING_PROCESS.md §3.1 / §4.1.4) lets an estimator
upload one site photo / drawing snapshot; the file is bound to the
session's ``metadata_["image"]`` and a vision-LLM enumerates the visible
elements. These tests pin the *upload* contract end-to-end — the LLM
extraction itself is exercised by the unit-level adapter tests and is
intentionally not invoked here (no AI provider is configured in the test
environment, so the adapter degrades to zero elements).

Coverage:
    1. test_from_image__success_binds_image_metadata — happy path, PNG
       upload returns source="image" and the image dict is persisted.
    2. test_from_image__jpeg_success                  — JPEG magic bytes.
    3. test_from_image__file_too_large_returns_413    — > 10 MB rejected.
    4. test_from_image__invalid_mime_returns_400      — non-image rejected.
    5. test_from_image__empty_file_returns_400        — 0-byte rejected.
    6. test_from_image__idor_other_project_404        — cross-tenant guard.

Run:
    cd backend
    python -m pytest tests/integration/test_match_elements_from_image.py -v
"""

from __future__ import annotations

import struct
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces the suite touches so Base.metadata
# sees a coherent table set when create_all runs (mirrors the sibling
# match-elements API baseline).
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.match_elements.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# ── Minimal valid image payloads (magic bytes are all the gate checks) ─────

# 1x1 transparent PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f6f0000000049454e44ae42"
    "6082"
)
# Smallest possible JPEG-ish blob — the SOI marker is enough for the
# magic-byte gate (the adapter never decodes it in these tests).
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login(
    client: AsyncClient,
    *,
    tenant: str,
    role: str = "admin",
) -> tuple[str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@me-image.io"
    password = f"ImgEl{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]
    await _activate_user(email)

    if role != "viewer":
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(
                update(User).where(User.email == email.lower()).values(role=role, is_active=True),
            )
            await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def _seed_project(*, owner_id: str, currency: str = "EUR") -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=project_id,
                name=f"ImageMatch-{uuid.uuid4().hex[:6]}",
                description="from-image upload test",
                owner_id=uuid.UUID(owner_id),
                currency=currency,
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        await s.commit()
    return project_id


@pytest_asyncio.fixture(scope="module")
async def owner(http_client):
    uid, headers = await _register_login(http_client, tenant="owner")
    return {"user_id": uid, "headers": headers}


# ═════════════════════════════════════════════════════════════════════════
#  1. Happy path — PNG upload binds the image dict
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_from_image__success_binds_image_metadata(http_client, owner):
    project_id = await _seed_project(owner_id=owner["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id), "name": "Site photo"},
        files={"image": ("site.png", _PNG_BYTES, "image/png")},
        headers=owner["headers"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == str(project_id)
    assert body["source"] == "image"
    assert body["name"] == "Site photo"

    # The image dict must be persisted on metadata_ with a path the
    # adapter can read back. (SessionRead omits metadata_, so verify at
    # the ORM layer.)
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.match_elements.models import MatchSession

    async with async_session_factory() as s:
        row = (
            await s.execute(
                select(MatchSession).where(MatchSession.id == uuid.UUID(body["id"])),
            )
        ).scalar_one()
        image = (row.metadata_ or {}).get("image")
        assert isinstance(image, dict), row.metadata_
        assert image.get("mime") == "image/png"
        assert image.get("path", "").endswith(".png")
        assert image.get("image_id")
        assert image.get("filename") == "site.png"


# ═════════════════════════════════════════════════════════════════════════
#  2. JPEG magic bytes accepted
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_from_image__jpeg_success(http_client, owner):
    project_id = await _seed_project(owner_id=owner["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id)},
        files={"image": ("photo.jpg", _JPEG_BYTES, "image/jpeg")},
        headers=owner["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source"] == "image"


# ═════════════════════════════════════════════════════════════════════════
#  3. Oversized upload → 413
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_from_image__file_too_large_returns_413(http_client, owner):
    project_id = await _seed_project(owner_id=owner["user_id"])

    # Valid PNG header, then padding to land exactly one byte over the cap the
    # router actually enforces. Read the limit from the router instead of
    # writing a number here: this test spelled its own "10 MB cap" and the
    # endpoint has shipped 50 MB since the day it was written, so it uploaded a
    # legal file and got the 201 it deserved.
    from app.modules.match_elements.router import _MAX_IMAGE_BYTES

    oversized = _PNG_BYTES + b"\x00" * (_MAX_IMAGE_BYTES + 1 - len(_PNG_BYTES))
    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id)},
        files={"image": ("huge.png", oversized, "image/png")},
        headers=owner["headers"],
    )
    assert resp.status_code == 413, resp.text


# ═════════════════════════════════════════════════════════════════════════
#  4. Non-image bytes → 400 (magic-byte gate)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_from_image__invalid_mime_returns_400(http_client, owner):
    project_id = await _seed_project(owner_id=owner["user_id"])

    # A PDF-magic blob mislabelled as PNG — the byte gate must reject it
    # regardless of the declared content-type / extension.
    not_an_image = b"%PDF-1.7\n" + struct.pack("<I", 0xDEADBEEF) * 8
    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id)},
        files={"image": ("trojan.png", not_an_image, "image/png")},
        headers=owner["headers"],
    )
    assert resp.status_code == 400, resp.text


# ═════════════════════════════════════════════════════════════════════════
#  5. Empty file → 400
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_from_image__empty_file_returns_400(http_client, owner):
    project_id = await _seed_project(owner_id=owner["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id)},
        files={"image": ("empty.png", b"", "image/png")},
        headers=owner["headers"],
    )
    assert resp.status_code == 400, resp.text


# ═════════════════════════════════════════════════════════════════════════
#  6. IDOR — outsider cannot upload into a project they don't own
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_from_image__idor_other_project_404(http_client, owner):
    # Owner's project.
    project_id = await _seed_project(owner_id=owner["user_id"])

    # A plain viewer from another tenant — no admin bypass.
    _, outsider_headers = await _register_login(
        http_client,
        tenant=f"outsider-{uuid.uuid4().hex[:6]}",
        role="viewer",
    )

    resp = await http_client.post(
        "/api/v1/match_elements/sessions/from-image",
        data={"project_id": str(project_id)},
        files={"image": ("site.png", _PNG_BYTES, "image/png")},
        headers=outsider_headers,
    )
    # verify_project_access returns 404 on deny (no existence leak).
    assert resp.status_code == 404, resp.text
