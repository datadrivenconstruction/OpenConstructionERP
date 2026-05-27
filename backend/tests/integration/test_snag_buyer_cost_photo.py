# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Snag deep-integration tests — buyer_id, cost_impact, photos (task #156).

Locks in the new Snag fields:

* ``buyer_id`` round-trips through create + response.
* ``category`` validates against the regex allow-list (general/
  cosmetic/functional/structural/mechanical/electrical/plumbing/
  finishing/exterior/safety); junk values → 422.
* ``cost_impact`` is Decimal-validated: negatives → 422; positive decimals
  round-trip without binary-float drift; the API response keeps the
  Decimal precision.
* ``POST /snags/{id}/photos/`` accepts a real JPEG (magic-byte gated) and
  appends to ``snag.photos``; SVG and other formats are rejected 415.
* Photo upload is IDOR-gated (tenant B can't upload to tenant A's snag).
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-snag-deep-"))
_TMP_DB = _TMP_DIR / "snag_deep.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@snag-deep.io"
    password = f"SnagDeep{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, {"_password": password}


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    """Manager tenant with project + dev + plot + buyer + handover."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.property_dev.models import (
        Buyer,
        Development,
        Handover,
        Plot,
    )
    from app.modules.users.models import User

    email, meta = await _register(http_client, "snag-mgr")
    await _set_role(email, "manager")
    headers = await _login(http_client, email, meta["_password"])

    async with async_session_factory() as s:
        owner = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one()

        proj = Project(
            name=f"SnagDeep-{uuid.uuid4().hex[:6]}",
            description="snag deep integ",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV-SD-{uuid.uuid4().hex[:5]}",
            name="SnagDeep Heights",
            total_plots=1,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        plot = Plot(
            development_id=dev.id,
            plot_number="SD-01",
            area_m2=Decimal("100"),
            price_base=Decimal("400000"),
            currency="EUR",
            status="planned",
        )
        s.add(plot)
        await s.flush()

        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id,
            full_name="Snag Buyer",
            email=f"buyer-{uuid.uuid4().hex[:6]}@x.io",
            status="contracted",
            contract_value=Decimal("400000"),
            currency="EUR",
        )
        s.add(buyer)
        await s.flush()

        handover = Handover(
            plot_id=plot.id,
            scheduled_at="2026-01-01",
            snag_count_at_handover=0,
            final_check_passed=False,
        )
        s.add(handover)
        await s.flush()

        await s.commit()

        return {
            "headers": headers,
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "plot_id": str(plot.id),
            "buyer_id": str(buyer.id),
            "handover_id": str(handover.id),
        }


# ── New field round-trip ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_snag_with_buyer_and_cost_impact(http_client, seeded):
    res = await http_client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": seeded["handover_id"],
            "buyer_id": seeded["buyer_id"],
            "category": "structural",
            "description": "Hairline crack above bedroom-1 doorframe",
            "severity": "major",
            "cost_impact": "1234.56",
        },
        headers=seeded["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["buyer_id"] == seeded["buyer_id"]
    assert body["category"] == "structural"
    # Decimal serialises as string in pydantic JSON output (no binary
    # float drift).
    assert body["cost_impact"] == "1234.56"
    assert body["photos"] == []
    assert body["linked_punch_item_id"] is None


@pytest.mark.asyncio
async def test_create_snag_negative_cost_rejected(http_client, seeded):
    res = await http_client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": seeded["handover_id"],
            "description": "negative cost should fail",
            "cost_impact": "-50.00",
        },
        headers=seeded["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_create_snag_invalid_category_rejected(http_client, seeded):
    res = await http_client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": seeded["handover_id"],
            "description": "junk category",
            "category": "not-a-real-category",
        },
        headers=seeded["headers"],
    )
    assert res.status_code == 422, res.text


# ── Magic-byte photo upload ────────────────────────────────────────────────


# Minimal valid JPEG (FF D8 FF E0 + JFIF header + EOI). Enough for the
# signature gate to accept; not a real image but the magic-byte
# validator only inspects the leading bytes.
_VALID_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
_NOT_AN_IMAGE = b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"


async def _create_snag(http_client, seeded) -> str:
    res = await http_client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": seeded["handover_id"],
            "description": f"photo-test {uuid.uuid4().hex[:6]}",
        },
        headers=seeded["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_upload_snag_photo_jpeg_accepted(http_client, seeded):
    sid = await _create_snag(http_client, seeded)
    res = await http_client.post(
        f"/api/v1/property-dev/snags/{sid}/photos/",
        files={"file": ("crack.jpg", io.BytesIO(_VALID_JPEG), "image/jpeg")},
        headers=seeded["headers"],
    )
    assert res.status_code == 200, res.text
    photos = res.json()["photos"]
    assert isinstance(photos, list)
    assert len(photos) == 1
    assert photos[0].startswith("snag/photos/")


@pytest.mark.asyncio
async def test_upload_snag_photo_svg_rejected(http_client, seeded):
    sid = await _create_snag(http_client, seeded)
    res = await http_client.post(
        f"/api/v1/property-dev/snags/{sid}/photos/",
        files={"file": ("evil.svg", io.BytesIO(_NOT_AN_IMAGE), "image/svg+xml")},
        headers=seeded["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_upload_snag_photo_idor(http_client, seeded):
    """Tenant B cannot upload to tenant A's snag."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    sid = await _create_snag(http_client, seeded)

    email, meta = await _register(http_client, "snag-other")
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="manager", is_active=True))
        await s.commit()
    other_headers = await _login(http_client, email, meta["_password"])

    res = await http_client.post(
        f"/api/v1/property-dev/snags/{sid}/photos/",
        files={"file": ("crack.jpg", io.BytesIO(_VALID_JPEG), "image/jpeg")},
        headers=other_headers,
    )
    assert res.status_code == 404, res.text
