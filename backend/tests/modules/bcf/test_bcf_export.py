# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for the BCF 3.0 clash-export endpoint.

Per ``feedback_test_isolation.md`` every test points
``DATABASE_URL`` at a fresh temp SQLite *before* importing any ``app``
module. The fixture seeds the schema, creates a project, then writes
``ClashRun`` + ``ClashResult`` rows directly so the test is independent
of the clash engine.

The endpoint under test:

    GET /api/v1/bcf/export/clashes?project_id=...&status=open

The test suite exercises:

* successful export with N clash rows
* the returned archive is a valid BCF 3.0 zip
* the response carries Content-Disposition with the right filename
* the export honours the status filter (the "open" virtual value)
* unauthenticated access is rejected
* a clash with no centroid still exports cleanly (no viewpoint)
* deterministic Topic GUID = clash signature (round-trip property)
* IDOR — a non-owner cannot export another project's clashes
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-bcf-export-"))
_TMP_DB = _TMP_DIR / "bcf_export.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App / auth / project fixtures ─────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        # Force-register the clash + bcf model tables so they exist.
        from app.modules.bcf import models as _bcf_models  # noqa: F401
        from app.modules.clash import models as _clash_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient, tag: str = "owner") -> tuple[dict[str, str], str]:
    """Register an admin user; return (auth_header, email)."""
    from tests.integration._auth_helpers import promote_to_admin

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-export-{tag}-{suffix}@test.io"
    password = f"BcfExportTest{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"BCF Export Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, email


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    headers, _email = await _register_admin(client, "owner")
    return headers


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "BCF export probe", "description": "BCF clash export"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def seeded_clashes(project_id: str) -> list[str]:
    """Seed 5 ClashResult rows on a fresh ClashRun. Returns signatures."""

    from app.database import async_session_factory
    from app.modules.clash.models import ClashResult, ClashRun

    async with async_session_factory() as session:
        run = ClashRun(
            project_id=uuid.UUID(project_id),
            name="Test run",
            model_ids=[],
            clash_type="both",
            mode="cross_discipline",
            status="completed",
            created_by="tester",
            total_clashes=5,
        )
        session.add(run)
        await session.flush()

        signatures: list[str] = []
        specs = [
            ("new", "critical", 1.0, 2.0, 3.0, "Wall-1", "Pipe-1"),
            ("new", "high", 4.0, 5.0, 6.0, "Wall-2", "Pipe-2"),
            ("resolved", "medium", 0.0, 0.0, 0.0, "Wall-3", "Pipe-3"),
            ("active", "low", 7.0, 8.0, 9.0, "Wall-4", "Pipe-4"),
            ("ignored", "medium", 10.0, 11.0, 12.0, "Wall-5", "Pipe-5"),
        ]
        for i, (status_v, sev, cx, cy, cz, a_name, b_name) in enumerate(specs):
            sig = f"deadbeefcafe{i:04x}"
            signatures.append(sig)
            session.add(
                ClashResult(
                    run_id=run.id,
                    a_element_id=uuid.uuid4(),
                    b_element_id=uuid.uuid4(),
                    a_stable_id=f"A{i}",
                    b_stable_id=f"B{i}",
                    a_name=a_name,
                    b_name=b_name,
                    a_discipline="Architecture",
                    b_discipline="MEP",
                    a_model_id=uuid.uuid4(),
                    b_model_id=uuid.uuid4(),
                    clash_type="hard",
                    penetration_m=0.05,
                    distance_m=0.0,
                    cx=cx,
                    cy=cy,
                    cz=cz,
                    status=status_v,
                    severity=sev,
                    signature=sig,
                )
            )
        await session.commit()
        return signatures


# ── Test helpers ─────────────────────────────────────────────────────────


def _verify_bcfzip(blob: bytes) -> dict:
    """Parse the archive enough to assert the BCF 3.0 invariants. Returns counts."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert "bcf.version" in names
        assert "extensions.xml" in names
        # Version document
        version_root = ET.fromstring(zf.read("bcf.version"))
        assert version_root.get("VersionId") == "3.0"
        # Markup count = topic folder count
        markup = [n for n in names if n.endswith("markup.bcf")]
        bcfv = [n for n in names if n.endswith(".bcfv")]
        # Walk each markup so we know it round-trips through ET.
        topics: list[str] = []
        for m in markup:
            data = zf.read(m)
            root = ET.fromstring(data)
            topic = root.find("Topic")
            assert topic is not None
            assert topic.get("Guid")
            assert topic.get("TopicType") == "Clash"
            assert topic.findtext("Title")
            topics.append(topic.get("Guid"))
        return {"markup_count": len(markup), "bcfv_count": len(bcfv), "topic_guids": topics}


# ── 1. Happy-path export ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_clashes_returns_valid_bcfzip(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    seeded_clashes: list[str],
) -> None:
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd
    assert "clashes-" in cd
    assert ".bcfzip" in cd

    info = _verify_bcfzip(resp.content)
    assert info["markup_count"] == 5  # all 5 clashes


@pytest.mark.asyncio
async def test_export_clashes_filters_by_status_open(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    seeded_clashes: list[str],
) -> None:
    """status=open expands to {new|active|persisted|reviewed}."""
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id, "status": "open"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    info = _verify_bcfzip(resp.content)
    # specs has 2 new + 1 active + 1 resolved + 1 ignored. Open = 3.
    assert info["markup_count"] == 3


@pytest.mark.asyncio
async def test_export_clashes_filters_by_severity(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    seeded_clashes: list[str],
) -> None:
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id, "severity": "critical"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    info = _verify_bcfzip(resp.content)
    assert info["markup_count"] == 1


@pytest.mark.asyncio
async def test_export_topic_guid_equals_clash_signature(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    seeded_clashes: list[str],
) -> None:
    """Round-trip property: Topic GUID equals the clash's stable signature."""
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
        headers=auth,
    )
    info = _verify_bcfzip(resp.content)
    topic_guids = {g.strip("{}").lower() for g in info["topic_guids"]}
    expected = {s.lower() for s in seeded_clashes}
    assert expected.issubset(topic_guids)


@pytest.mark.asyncio
async def test_export_zero_centroid_omits_viewpoint(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    seeded_clashes: list[str],
) -> None:
    """A clash with cx=cy=cz=0 should produce a topic but no viewpoint."""
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
        headers=auth,
    )
    info = _verify_bcfzip(resp.content)
    # 5 topics; one of them (the "resolved" spec above) has centroid 0/0/0
    # → 4 viewpoints expected.
    assert info["bcfv_count"] == 4


# ── 2. Auth / IDOR ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_clashes_requires_auth(client: AsyncClient, project_id: str) -> None:
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_export_clashes_idor_blocked(client: AsyncClient, project_id: str) -> None:
    """A second admin user should not be able to export the first owner's clashes."""
    other_auth, _ = await _register_admin(client, "other")
    # other_auth is an admin → it should still pass (admins can read across
    # projects per the existing access check). We probe the opposite
    # direction: register a viewer-only account and confirm it fails.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User
    from tests.integration._auth_helpers import promote_to_admin  # noqa: F401

    suffix = uuid.uuid4().hex[:8]
    email = f"bcf-export-viewer-{suffix}@test.io"
    password = f"BcfExportVwr{suffix}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Viewer",
            "role": "viewer",
        },
    )
    assert reg.status_code in (200, 201)
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
        headers=headers,
    )
    # 403 (owns-check) or 404 (not visible). Either is "blocked".
    assert resp.status_code in (403, 404)


# ── 3. Feature-unavailable degradation ─────────────────────────────────


@pytest.mark.asyncio
async def test_export_clashes_feature_unavailable_returns_503(
    client: AsyncClient, auth: dict[str, str], project_id: str, monkeypatch
) -> None:
    """If the clash table is unreachable, return 503 — NOT 500."""
    from app.modules.bcf import service as bcf_service

    async def boom(*args, **kwargs):
        raise bcf_service.BCFExportFeatureUnavailable("Clash storage table missing")

    monkeypatch.setattr(
        bcf_service.BCFExportService,
        "export_clashes_to_bcf",
        boom,
    )
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": project_id},
        headers=auth,
    )
    assert resp.status_code == 503, resp.text
    assert "Clash storage table missing" in resp.text


@pytest.mark.asyncio
async def test_export_clashes_handles_project_not_found(client: AsyncClient, auth: dict[str, str]) -> None:
    """A missing project id should 404 — not 500."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(
        "/api/v1/bcf/export/clashes",
        params={"project_id": fake_id},
        headers=auth,
    )
    assert resp.status_code == 404, resp.text
