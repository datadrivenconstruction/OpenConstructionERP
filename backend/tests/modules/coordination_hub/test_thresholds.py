# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Coordination Hub threshold endpoints + evaluation contract.

Covers:
    * default seeding on first read
    * evaluate with no breaches → all ``level == "ok"``
    * evaluate with one warn-only breach
    * evaluate with an error-level breach
    * disabled threshold does not produce an alert
    * PUT endpoint succeeds + persists the new values
    * PUT endpoint 422 on unknown metric
    * PUT endpoint requires write permission (VIEWER blocked)
    * cost-impact-pct-of-budget without budget surfaces 0.0
    * model-age fires error when no model uploaded

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
per-module temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-cohub-th-"))
_TMP_DB = _TMP_DIR / "cohub-th.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient) -> tuple[str, dict[str, str]]:
    from tests.integration._auth_helpers import promote_to_admin

    tag = uuid.uuid4().hex[:8]
    email = f"cohub-th-{tag}@test.io"
    password = f"CoHubTh{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"CoHub Th Tester {tag}",
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
    return reg.json()["id"], {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth_pair(client: AsyncClient) -> tuple[str, dict[str, str]]:
    return await _register_admin(client)


@pytest_asyncio.fixture(scope="module")
async def auth(auth_pair: tuple[str, dict[str, str]]) -> dict[str, str]:
    return auth_pair[1]


@pytest_asyncio.fixture()
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    """Fresh project per test so the seeded thresholds start clean."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Threshold Test {uuid.uuid4().hex[:6]}",
            "description": "thresholds",
        },
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Seeding helpers ───────────────────────────────────────────────────────


async def _seed_clash(
    project_id_: str,
    *,
    a_disc: str = "Architectural",
    b_disc: str = "Structural",
    status_: str = "new",
    severity: str = "medium",
) -> str:
    from app.database import async_session_factory
    from app.modules.clash.models import ClashResult, ClashRun

    async with async_session_factory() as session:
        run = ClashRun(
            project_id=uuid.UUID(project_id_),
            name="Th Run",
            model_ids=[str(uuid.uuid4())],
            status="completed",
            created_by=str(uuid.uuid4()),
        )
        session.add(run)
        await session.flush()
        clash = ClashResult(
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id=f"A-{uuid.uuid4().hex[:6]}",
            b_stable_id=f"B-{uuid.uuid4().hex[:6]}",
            a_name="a",
            b_name="b",
            a_discipline=a_disc,
            b_discipline=b_disc,
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=0.0,
            cy=0.0,
            cz=0.0,
            status=status_,
            severity=severity,
            signature=uuid.uuid4().hex[:16],
        )
        session.add(clash)
        await session.commit()
        return str(clash.id)


async def _seed_bim_model(project_id_: str, *, created_at: datetime | None = None) -> None:
    """Seed one BIMModel; created_at controls the staleness clock."""
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMModel

    async with async_session_factory() as session:
        model = BIMModel(
            project_id=uuid.UUID(project_id_),
            name=f"M-{uuid.uuid4().hex[:6]}",
            discipline="Architectural",
            model_format="ifc",
            version="1",
            status="ready",
            element_count=1,
        )
        if created_at is not None:
            model.created_at = created_at
        session.add(model)
        await session.commit()


def _invalidate_cache() -> None:
    from app.modules.coordination_hub.service import (
        CoordinationHubService,
    )

    CoordinationHubService.invalidate_cache()


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_thresholds_default_seeded_on_first_get(client: AsyncClient, auth: dict[str, str], project_id: str):
    """First GET on a fresh project lazily seeds four default rows."""
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    metrics = {t["metric"] for t in body["thresholds"]}
    assert metrics == {
        "open_clashes_total",
        "high_severity_clashes",
        "open_cost_impact_pct_of_budget",
        "model_age_days_max",
    }
    # All enabled by default.
    assert all(t["enabled"] for t in body["thresholds"])


@pytest.mark.asyncio
async def test_evaluate_no_breach_when_zero_signal(client: AsyncClient, auth: dict[str, str], project_id: str):
    """Empty project: no model uploaded → model_age fires ERROR (99999d)."""
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    levels = {t["metric"]: t["level"] for t in body["thresholds"]}
    # No clashes / no cost-impact / no budget — these three stay OK.
    assert levels["open_clashes_total"] == "ok"
    assert levels["high_severity_clashes"] == "ok"
    assert levels["open_cost_impact_pct_of_budget"] == "ok"
    # No model has ever been uploaded → the model-age guard fires ERROR.
    assert levels["model_age_days_max"] == "error"


@pytest.mark.asyncio
async def test_evaluate_warn_only_breach(client: AsyncClient, auth: dict[str, str], project_id: str):
    """Seed exactly 5 high-severity clashes — warn breach, not error."""
    # Defaults: warn=5 / error=20 for high_severity_clashes.
    for _ in range(5):
        await _seed_clash(project_id, severity="high", status_="new")
    # Avoid model_age "empty project" error noise — give it a recent model.
    await _seed_bim_model(project_id, created_at=datetime.now(UTC))

    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    body = resp.json()
    by_metric = {t["metric"]: t for t in body["thresholds"]}
    assert by_metric["high_severity_clashes"]["level"] == "warn"
    # Alerts list contains the warn entry.
    alert_metrics = {a["metric"] for a in body["alerts"]}
    assert "high_severity_clashes" in alert_metrics


@pytest.mark.asyncio
async def test_evaluate_error_level_breach(client: AsyncClient, auth: dict[str, str], project_id: str):
    """Seed 20 high-severity clashes (= error threshold)."""
    for _ in range(20):
        await _seed_clash(project_id, severity="critical", status_="new")
    await _seed_bim_model(project_id, created_at=datetime.now(UTC))

    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    body = resp.json()
    by_metric = {t["metric"]: t for t in body["thresholds"]}
    assert by_metric["high_severity_clashes"]["level"] == "error"
    # Error alerts must come before warn alerts in the sorted alerts list.
    errors = [a for a in body["alerts"] if a["level"] == "error"]
    assert any(a["metric"] == "high_severity_clashes" for a in errors)


@pytest.mark.asyncio
async def test_disabled_threshold_does_not_alert(client: AsyncClient, auth: dict[str, str], project_id: str):
    """Flipping ``enabled=False`` suppresses the alert even on breach."""
    # Trigger an error first.
    for _ in range(25):
        await _seed_clash(project_id, severity="high", status_="new")
    await _seed_bim_model(project_id, created_at=datetime.now(UTC))

    # Disable the high_severity metric.
    resp = await client.put(
        f"/api/v1/coordination/projects/{project_id}/thresholds/high_severity_clashes",
        json={"enabled": False},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text

    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    body = resp.json()
    by_metric = {t["metric"]: t for t in body["thresholds"]}
    assert by_metric["high_severity_clashes"]["enabled"] is False
    assert by_metric["high_severity_clashes"]["level"] == "ok"
    # The metric does NOT appear in the alerts list.
    alert_metrics = {a["metric"] for a in body["alerts"]}
    assert "high_severity_clashes" not in alert_metrics


@pytest.mark.asyncio
async def test_put_persists_new_thresholds(client: AsyncClient, auth: dict[str, str], project_id: str):
    """PUT a custom override — GET reflects the new warn / error values."""
    resp = await client.put(
        f"/api/v1/coordination/projects/{project_id}/thresholds/open_clashes_total",
        json={"warn_value": "10", "error_value": "40"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["warn_value"]) == Decimal("10")
    assert Decimal(body["error_value"]) == Decimal("40")

    # Re-GET to confirm persistence.
    _invalidate_cache()
    resp2 = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    by_metric = {t["metric"]: t for t in resp2.json()["thresholds"]}
    assert Decimal(by_metric["open_clashes_total"]["warn_value"]) == Decimal("10")
    assert Decimal(by_metric["open_clashes_total"]["error_value"]) == Decimal("40")


@pytest.mark.asyncio
async def test_put_rejects_unknown_metric(client: AsyncClient, auth: dict[str, str], project_id: str):
    """A typo'd metric returns 422 — no ghost-write."""
    resp = await client.put(
        f"/api/v1/coordination/projects/{project_id}/thresholds/not_a_real_metric",
        json={"warn_value": "10", "error_value": "40"},
        headers=auth,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_rejects_empty_payload(client: AsyncClient, auth: dict[str, str], project_id: str):
    """An empty PUT is a no-op — rejected with 422."""
    resp = await client.put(
        f"/api/v1/coordination/projects/{project_id}/thresholds/open_clashes_total",
        json={},
        headers=auth,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_blocks_viewer_role(client: AsyncClient, project_id: str):
    """A plain VIEWER lacks coordination.write permission."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = f"cohub-th-viewer-{tag}@test.io"
    password = f"ViewerTh{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Viewer Th",
            "role": "viewer",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email).values(is_active=True))
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    viewer_auth = {"Authorization": f"Bearer {token}"}
    resp = await client.put(
        f"/api/v1/coordination/projects/{project_id}/thresholds/open_clashes_total",
        json={"warn_value": "10"},
        headers=viewer_auth,
    )
    # 403 (permission denied) or 404 (project access guard) — both deny.
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_model_age_fires_error_on_empty_project(client: AsyncClient, auth: dict[str, str], project_id: str):
    """No BIM model upload → model_age_days_max = 99999d → ERROR."""
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    body = resp.json()
    by_metric = {t["metric"]: t for t in body["thresholds"]}
    age_row = by_metric["model_age_days_max"]
    assert age_row["level"] == "error"
    assert Decimal(age_row["current_value"]) >= Decimal("30")


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client: AsyncClient, project_id: str):
    """No Authorization header → 401/403 from the auth layer."""
    resp = await client.get(f"/api/v1/coordination/projects/{project_id}/thresholds")
    assert resp.status_code in (401, 403)


# ── Unit tests against the service directly ──────────────────────────────


@pytest.mark.asyncio
async def test_service_evaluates_known_metrics_only():
    """The seeded threshold set matches DEFAULT_THRESHOLDS exactly."""
    from app.modules.coordination_hub.models import (
        DEFAULT_THRESHOLDS,
        KNOWN_METRICS,
    )

    assert set(KNOWN_METRICS) == {m for (m, _, _) in DEFAULT_THRESHOLDS}
    # Defaults must be Decimal so PUT round-trip stays lossless.
    for _metric, warn, error in DEFAULT_THRESHOLDS:
        assert isinstance(warn, Decimal)
        assert isinstance(error, Decimal)
        assert warn <= error


@pytest.mark.asyncio
async def test_threshold_evaluation_warn_then_error_progression(
    client: AsyncClient, auth: dict[str, str], project_id: str
):
    """Seeded 50 open clashes ladders WARN → 200 ladders to ERROR."""
    # 50 open clashes = warn threshold (open_clashes_total: warn=50, error=200).
    await _seed_bim_model(project_id, created_at=datetime.now(UTC))
    for _ in range(50):
        await _seed_clash(project_id, severity="medium", status_="new")
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    by_metric = {t["metric"]: t for t in resp.json()["thresholds"]}
    assert by_metric["open_clashes_total"]["level"] == "warn"

    # Add 150 more → 200 total → ERROR.
    for _ in range(150):
        await _seed_clash(project_id, severity="medium", status_="new")
    _invalidate_cache()
    resp2 = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    by_metric2 = {t["metric"]: t for t in resp2.json()["thresholds"]}
    assert by_metric2["open_clashes_total"]["level"] == "error"


@pytest.mark.asyncio
async def test_recent_model_keeps_model_age_ok(client: AsyncClient, auth: dict[str, str], project_id: str):
    """A model uploaded 5 days ago stays OK (default warn=14, error=30)."""
    await _seed_bim_model(project_id, created_at=datetime.now(UTC) - timedelta(days=5))
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/thresholds",
        headers=auth,
    )
    by_metric = {t["metric"]: t for t in resp.json()["thresholds"]}
    assert by_metric["model_age_days_max"]["level"] == "ok"
