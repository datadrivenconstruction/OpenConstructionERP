"""Integration tests for the validation API.

Specifically guards the IDS importer + SARIF exporter HTTP surface added in
task tracker #224:

    POST /api/v1/validation/import-ids        — multipart upload IDS file
    GET  /api/v1/validation/reports/{id}/sarif — export report as SARIF JSON

Test isolation
~~~~~~~~~~~~~~
Per ``feedback_test_isolation.md`` we MUST point ``DATABASE_URL`` at a
fresh temp SQLite file BEFORE ``app.database`` is first imported, otherwise
the tests would hammer ``backend/openestimate.db``. We therefore set the
env var at the top of the module, before any ``from app...`` line runs.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-validation-api-"))
_TMP_DB = _TMP_DIR / "validation_api.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ids"


# ── App + auth fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        # Backfill any tables that aren't pre-imported by main.py startup.
        from app.database import Base, engine
        from app.modules.validation import models as _val_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    """Register a unique admin user and return Authorization headers."""
    from ._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email = f"valapi-{unique}@test.io"
    password = f"ValApiTest{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Validation API Tester",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    await promote_to_admin(email)

    token = ""
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {}
        token = body.get("access_token", "")
        if token:
            break
        if "Too many login" in body.get("detail", ""):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"could not log in: {resp.status_code} {resp.text[:200]}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    """Create a throwaway project owned by the test user."""
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "IDS+SARIF API test", "description": "smoke"},
        headers=auth,
    )
    if resp.status_code in (200, 201):
        return resp.json()["id"]
    pytest.skip(f"could not create project: {resp.status_code} {resp.text[:200]}")


# ── 1. POST /import-ids — multipart upload happy path ─────────────────────


@pytest.mark.asyncio
async def test_import_ids_endpoint_creates_rules(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Uploading the multi-spec fixture creates 3 rules in the registry."""
    fixture = FIXTURES / "ids_10_multi_specification.xml"
    files = {
        "file": (
            fixture.name,
            fixture.read_bytes(),
            "application/xml",
        )
    }
    resp = await client.post(
        "/api/v1/validation/import-ids",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 200, f"unexpected: {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["rules_created"] == 3
    assert len(body["rule_ids"]) == 3
    assert all(rid.startswith("ids.") for rid in body["rule_ids"])
    assert body["rule_set"] == "ids_custom"


@pytest.mark.asyncio
async def test_import_ids_rejects_garbage(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Malformed payload → 422 with a helpful detail."""
    files = {"file": ("not_ids.xml", b"<<<not xml>>>", "application/xml")}
    resp = await client.post(
        "/api/v1/validation/import-ids",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    assert "IDS" in detail or "XML" in detail


# ── 2. GET /reports/{id}/sarif — export happy path ────────────────────────


@pytest.mark.asyncio
async def test_get_report_sarif(
    client: AsyncClient, auth: dict[str, str], project_id: str
) -> None:
    """Persist a synthetic ValidationReport then export it as SARIF JSON."""
    from app.database import async_session_factory
    from app.modules.validation.models import ValidationReport

    report_id = uuid.uuid4()
    async with async_session_factory() as session:
        row = ValidationReport(
            id=report_id,
            project_id=uuid.UUID(project_id),
            target_type="boq",
            target_id=str(uuid.uuid4()),
            rule_set="din276+boq_quality",
            status="errors",
            score="0.5",
            total_rules=2,
            passed_count=0,
            warning_count=0,
            error_count=2,
            results=[
                {
                    "rule_id": "din276.kg_required",
                    "rule_name": "DIN 276 KG required",
                    "severity": "error",
                    "passed": False,
                    "message": "Missing KG on pos-1 — Außenwände",
                    "element_ref": "pos-1",
                    "details": {},
                    "suggestion": "Assign a KG between 100 and 700",
                },
                {
                    "rule_id": "boq_quality.zero_rate",
                    "rule_name": "Zero rate",
                    "severity": "warning",
                    "passed": False,
                    "message": "Unit rate is zero",
                    "element_ref": "pos-2",
                    "details": {},
                    "suggestion": None,
                },
            ],
            metadata_={},
        )
        session.add(row)
        await session.commit()

    resp = await client.get(
        f"/api/v1/validation/reports/{report_id}/sarif",
        headers=auth,
    )
    assert resp.status_code == 200, f"unexpected: {resp.status_code} {resp.text[:300]}"
    assert resp.headers["content-type"].startswith("application/sarif+json")

    sarif = resp.json()
    assert sarif["version"] == "2.1.0"
    assert "runs" in sarif and len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert len(run["results"]) == 2
    levels = {r["level"] for r in run["results"]}
    assert "error" in levels
    assert "warning" in levels
    assert run["tool"]["driver"]["name"] == "OpenConstructionERP"
    encoded_msg = " ".join(r["message"]["text"] for r in run["results"])
    assert "Außenwände" in encoded_msg


@pytest.mark.asyncio
async def test_get_report_sarif_404(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """Unknown report id → 404."""
    resp = await client.get(
        f"/api/v1/validation/reports/{uuid.uuid4()}/sarif",
        headers=auth,
    )
    assert resp.status_code == 404
