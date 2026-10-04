"""Integration tests for the validation API.

Specifically guards the IDS importer + SARIF exporter HTTP surface added in
task tracker #224:

    POST /api/v1/validation/import-ids        — multipart upload IDS file
    GET  /api/v1/validation/reports/{id}/sarif — export report as SARIF JSON

Test isolation
~~~~~~~~~~~~~~
The engine is bound to the conftest-provisioned PostgreSQL cluster before
any test module imports, so these tests run against that PostgreSQL.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ids"


# ── App + auth fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the conftest PostgreSQL."""
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


def _assert_rule_ids_are_project_scoped(rule_ids: list[str], project_id: str) -> None:
    """Assert every imported rule id carries both halves of its identity.

    ``validation.router.import_ids`` prefixes each rule id with the project id so
    one tenant's imported specs are never resolvable by another, and the IDS
    importer slugs its own rules under ``ids.``. Checking only the ``ids.`` half
    would pass for a rule that had lost its namespace, which is the cross-tenant
    leak the prefix exists to prevent; checking only the namespace would pass for
    any rule the endpoint happened to return.
    """
    for rid in rule_ids:
        namespace, sep, local = rid.partition(":")
        assert sep, f"rule id carries no project namespace at all: {rid!r}"
        assert namespace == project_id, f"rule id escaped its project: {rid!r} is not scoped to {project_id}"
        assert local.startswith("ids."), f"rule id is not an imported IDS rule: {rid!r}"


# ── 1. POST /import-ids — multipart upload happy path ─────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_import_ids_endpoint_creates_rules(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
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
        params={"project_id": project_id},
        headers=auth,
    )
    assert resp.status_code == 200, f"unexpected: {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["rules_created"] == 3
    assert len(body["rule_ids"]) == 3
    _assert_rule_ids_are_project_scoped(body["rule_ids"], project_id)
    # Rule set is namespaced with the project id so imported rules cannot
    # leak across tenants/projects.
    assert body["rule_set"] == f"ids_custom:{project_id}"
    assert body["project_id"] == project_id


@pytest.mark.tenant_isolation
def test_rule_id_check_rejects_a_dropped_namespace() -> None:
    """Negative control for :func:`_assert_rule_ids_are_project_scoped`.

    This exercises the checker, not the endpoint. Without it the happy-path
    assertion could stop catching anything and still pass, which is how a test
    quietly turns into decoration.
    """
    project_id = str(uuid.uuid4())
    other_project = str(uuid.uuid4())

    # The namespace dropped entirely: exactly what ``parse_ids`` emits before the
    # router scopes it, and the cross-tenant leak this guards against.
    with pytest.raises(AssertionError):
        _assert_rule_ids_are_project_scoped(["ids.ids_10_walls"], project_id)

    # Namespaced, but to somebody else's project.
    with pytest.raises(AssertionError):
        _assert_rule_ids_are_project_scoped([f"{other_project}:ids.ids_10_walls"], project_id)

    # Correctly namespaced, but not an imported IDS rule.
    with pytest.raises(AssertionError):
        _assert_rule_ids_are_project_scoped([f"{project_id}:din276.cost_group"], project_id)

    # The shape the router actually produces has to pass.
    _assert_rule_ids_are_project_scoped([f"{project_id}:ids.ids_10_walls"], project_id)


@pytest.mark.asyncio
async def test_import_ids_rejects_garbage(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
    """Malformed payload returns 422 with a helpful detail."""
    files = {"file": ("not_ids.xml", b"<<<not xml>>>", "application/xml")}
    resp = await client.post(
        "/api/v1/validation/import-ids",
        files=files,
        params={"project_id": project_id},
        headers=auth,
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    assert "IDS" in detail or "XML" in detail


# ── 2. GET /reports/{id}/sarif — export happy path ────────────────────────


@pytest.mark.asyncio
async def test_get_report_sarif(client: AsyncClient, auth: dict[str, str], project_id: str) -> None:
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
async def test_get_report_sarif_404(client: AsyncClient, auth: dict[str, str]) -> None:
    """Unknown report id → 404."""
    resp = await client.get(
        f"/api/v1/validation/reports/{uuid.uuid4()}/sarif",
        headers=auth,
    )
    assert resp.status_code == 404


# ── 3. GET /portfolio-status/ - cross-project status over HTTP ───────────


@pytest.mark.asyncio
async def test_portfolio_status_endpoint(client: AsyncClient, auth: dict[str, str]) -> None:
    """The route is mounted, gated, and reads stored reports per estimate.

    The service is covered in depth by tests/unit/test_validation_portfolio_status.py;
    this pins the HTTP surface: auth is required, the latest report of a
    real estimate decides its state, and a report whose target is not an
    estimate of the project does not turn the project red.
    """
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ
    from app.modules.validation.models import ValidationReport

    unauth = await client.get("/api/v1/validation/portfolio-status/")
    assert unauth.status_code in (401, 403)

    created = await client.post(
        "/api/v1/projects/",
        json={"name": f"Portfolio status {uuid.uuid4().hex[:6]}", "description": "smoke"},
        headers=auth,
    )
    assert created.status_code in (200, 201), created.text[:200]
    pid = uuid.UUID(created.json()["id"])

    boq_id = uuid.uuid4()
    report_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(BOQ(id=boq_id, project_id=pid, name="Shell and core", status="draft"))
        await session.flush()
        session.add(
            ValidationReport(
                id=report_id,
                project_id=pid,
                target_type="boq",
                target_id=str(boq_id),
                rule_set="boq_quality",
                status="passed",
                score="1.0",
                total_rules=7,
                passed_count=7,
                results=[],
                metadata_={"rule_sets": ["boq_quality"]},
            )
        )
        # A report on something that is not an estimate of this project.
        session.add(
            ValidationReport(
                id=uuid.uuid4(),
                project_id=pid,
                target_type="boq",
                target_id=str(uuid.uuid4()),
                rule_set="boq_quality",
                status="errors",
                total_rules=1,
                error_count=1,
                results=[],
                metadata_={},
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/validation/portfolio-status/", headers=auth)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    row = next(p for p in body["projects"] if p["project_id"] == str(pid))
    assert row["state"] == "passed"
    assert row["error_count"] == 0
    assert row["estimate_count"] == 1
    (estimate,) = row["estimates"]
    assert estimate["boq_id"] == str(boq_id)
    assert estimate["report_id"] == str(report_id)
    assert estimate["rule_sets"] == ["boq_quality"]
    assert body["project_count"] == len(body["projects"])


@pytest.mark.asyncio
async def test_the_editor_validate_button_lands_on_the_portfolio_status(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """A check from the BOQ editor is stored and read back across requests.

    The Validate button used to return its summary and store nothing, so the
    cross-project status called a just-checked estimate "never validated".
    """
    created = await client.post(
        "/api/v1/projects/",
        json={"name": f"Editor run {uuid.uuid4().hex[:6]}", "description": "smoke"},
        headers=auth,
    )
    assert created.status_code in (200, 201), created.text[:200]
    pid = created.json()["id"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": pid, "name": "Editor bill"}, headers=auth)
    assert boq.status_code in (200, 201), boq.text[:200]
    boq_id = boq.json()["id"]
    pos = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Strip foundation, no rate yet",
            "unit": "m3",
            "quantity": 12.0,
            "unit_rate": 0.0,
        },
        headers=auth,
    )
    assert pos.status_code in (200, 201), pos.text[:200]

    run = await client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", json={}, headers=auth)
    assert run.status_code == 200, run.text[:300]
    summary = run.json()
    report_id = summary.get("report_id")
    assert report_id, "the editor run was not stored"

    stored = await client.get(f"/api/v1/validation/reports/{report_id}", headers=auth)
    assert stored.status_code == 200, stored.text[:300]
    assert stored.json()["status"] == summary["status"]

    status_resp = await client.get("/api/v1/validation/portfolio-status/", headers=auth)
    assert status_resp.status_code == 200, status_resp.text[:300]
    row = next(p for p in status_resp.json()["projects"] if p["project_id"] == pid)
    (estimate,) = row["estimates"]
    assert estimate["boq_id"] == boq_id
    assert estimate["report_id"] == report_id
    assert estimate["report_status"] == summary["status"]
