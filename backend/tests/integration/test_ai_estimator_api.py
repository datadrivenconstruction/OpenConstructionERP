# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration baseline for the ``/api/v1/ai-estimator/`` API surface.

Drives the full AI Estimate Builder run lifecycle end-to-end through the
ASGI app with no AI key and no Qdrant (the deterministic graceful-degradation
path), and pins the load-bearing contracts:

    create run -> analyze (deterministic) -> confirm source -> groups
    -> match (rank() stubbed to a seeded CWICR rate) -> confirm groups
    -> confirm grouping/matching/assembly -> preview (validation attached)
    -> apply -> Positions exist with source='ai_precise_estimate', the real
    confidence, resource sub-rows, and validation_status='pending'.

RBAC: a viewer (project member, so it passes verify_project_access) can read
runs but cannot create a run or apply an estimate (the run/apply verbs require
EDITOR).

Test isolation
~~~~~~~~~~~~~~
Runs against the PostgreSQL cluster provisioned by ``tests/conftest.py``. The
``rank()`` grounded retrieval entrypoint is stubbed so the suite is hermetic
and fast (no embedder, no vector DB).

Run:
    cd backend
    python -m pytest tests/integration/test_ai_estimator_api.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import every model namespace the suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the match_elements baseline).
import app.modules.ai_estimator.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.teams.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables.

    The lifespan runs the module loader's ``on_startup`` hooks, which register
    the ai_estimator permissions + validation rules + the precise-match agent.
    """
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


async def _register_login_promote(
    client: AsyncClient,
    *,
    tenant: str,
    role: str = "admin",
) -> tuple[str, str, dict[str, str]]:
    """Register, activate, optionally promote, log in. Returns (uid, email, headers)."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@ai-estimator.io"
    password = f"AiEst{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    if role != "viewer":
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
            await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def admin(http_client):
    uid, email, headers = await _register_login_promote(http_client, tenant="admin")
    return {"user_id": uid, "email": email, "headers": headers}


async def _seed_project(*, owner_id: str, currency: str = "EUR", region: str = "DACH") -> uuid.UUID:
    """Insert a Project owned by ``owner_id`` directly through the ORM."""
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=pid,
                name=f"AiEst-{uuid.uuid4().hex[:6]}",
                description="AI estimator integration test",
                owner_id=uuid.UUID(owner_id),
                currency=currency,
                region=region,
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        await s.commit()
    return pid


async def _seed_cost_item(
    *,
    description: str,
    unit: str = "m3",
    rate: str = "185.00",
    currency: str = "EUR",
    components: list[dict] | None = None,
) -> uuid.UUID:
    """Insert a CWICR-style CostItem (the grounded rate source)."""
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    cid = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            CostItem(
                id=cid,
                code=f"AIEST-{uuid.uuid4().hex[:8].upper()}",
                description=description,
                unit=unit,
                rate=rate,
                currency=currency,
                source="cwicr",
                classification={"din276": "330"},
                components=components or [],
                tags=[],
                region=None,
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()
    return cid


async def _add_project_member(project_id: uuid.UUID, user_id: str) -> None:
    """Make ``user_id`` a project member (a Team + TeamMembership row) so the
    viewer passes ``verify_project_access`` and the RBAC test isolates the
    permission gate, not the project gate."""
    from app.database import async_session_factory
    from app.modules.teams.models import Team, TeamMembership

    async with async_session_factory() as s:
        team = Team(id=uuid.uuid4(), project_id=project_id, name="Default", metadata_={})
        s.add(team)
        await s.flush()
        s.add(TeamMembership(id=uuid.uuid4(), team_id=team.id, user_id=uuid.UUID(user_id), role="member"))
        await s.commit()


def _stub_rank(monkeypatch, cost_id: uuid.UUID, *, unit_rate: float, currency: str, score: float) -> None:
    """Stub the grounded retrieval entrypoint to a single seeded candidate."""
    from app.core.match_service.envelope import MatchCandidate, MatchRequest, MatchResponse

    async def _rank(req, *, db, ai_settings=None):
        return MatchResponse(
            request=req
            if isinstance(req, MatchRequest)
            else MatchRequest(envelope=req.envelope, project_id=req.project_id),
            candidates=[
                MatchCandidate(
                    id=str(cost_id),
                    code="AIEST-RATE",
                    description="Reinforced concrete wall C30/37",
                    unit="m3",
                    unit_rate=unit_rate,
                    currency=currency,
                    score=score,
                    confidence_band="high" if score >= 0.78 else "medium",
                )
            ],
        )

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _rank)


def _stub_rank_candidates(monkeypatch, candidates: list[dict]) -> None:
    """Stub the grounded ranker to a fixed list of candidate dicts.

    Each dict carries id / code / description / unit / unit_rate / currency /
    score; the multi-pass mapping then reconciles + sanity-checks them. The list
    is returned for every group (the integration cases match a single group).
    """
    from app.core.match_service.envelope import MatchCandidate, MatchRequest, MatchResponse

    async def _rank(req, *, db, ai_settings=None):
        return MatchResponse(
            request=req
            if isinstance(req, MatchRequest)
            else MatchRequest(envelope=req.envelope, project_id=req.project_id),
            candidates=[
                MatchCandidate(
                    id=str(c["id"]),
                    code=c.get("code", "C"),
                    description=c.get("description", ""),
                    unit=c.get("unit", "m2"),
                    unit_rate=c["unit_rate"],
                    currency=c.get("currency", "EUR"),
                    score=c["score"],
                    confidence_band="high" if c["score"] >= 0.78 else "medium",
                )
                for c in candidates
            ],
        )

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _rank)


# ═════════════════════════════════════════════════════════════════════════
#  1. Create run -> analyze (deterministic, no AI key)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_run_starts_analysis_deterministically(http_client, admin):
    project_id = await _seed_project(owner_id=admin["user_id"])
    resp = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Concrete wall C30/37", "qty": 10.0, "unit": "m3", "category": "walls"}],
            "currency": "EUR",
        },
        headers=admin["headers"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == str(project_id)
    # Stage 1 ran on create; status is analyzing, source detected.
    assert body["status"] == "analyzing"
    assert body["current_stage"] == "source"
    assert body["detected_source"]["type"] == "excel"


@pytest.mark.asyncio
async def test_create_run_invalid_source_rejected(http_client, admin):
    project_id = await _seed_project(owner_id=admin["user_id"])
    resp = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "not-a-source"},
        headers=admin["headers"],
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_readiness_reports_degraded_without_ai_key(http_client, admin):
    """No AI key -> readiness is honest about degradation and guides re-entry."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "brick wall"},
        headers=admin["headers"],
    )
    run_id = create.json()["id"]
    resp = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/readiness", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_connected"] is False
    # Plain-prose guidance present (re-enter key / settings).
    assert body["message"] and "settings" in body["message"].lower()

    prog = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/progress", headers=admin["headers"])
    assert prog.status_code == 200, prog.text
    assert prog.json()["degraded_reason"] == "no_ai_key"


# ═════════════════════════════════════════════════════════════════════════
#  2. Full lifecycle: groups -> match -> confirm -> preview -> apply
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_run_lifecycle_to_applied_boq(http_client, admin, monkeypatch):
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    cost_id = await _seed_cost_item(
        description="Reinforced concrete wall C30/37",
        unit="m3",
        rate="185.00",
        currency="EUR",
        components=[
            {
                "description": "Concrete C30/37",
                "code": "C1",
                "unit": "m3",
                "factor": 1.0,
                "unit_rate": "120.00",
                "type": "material",
            },
            {"description": "Labour", "code": "L1", "unit": "h", "factor": 0.8, "unit_rate": "55.00", "type": "labor"},
        ],
    )
    _stub_rank(monkeypatch, cost_id, unit_rate=185.0, currency="EUR", score=0.83)

    h = admin["headers"]

    # Create + analyze.
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [
                {"description": "Concrete wall A", "qty": 6.0, "unit": "m3", "category": "walls"},
                {"description": "Concrete wall B", "qty": 4.0, "unit": "m3", "category": "walls"},
            ],
            "currency": "EUR",
        },
        headers=h,
    )
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]

    # Confirm source -> grouping runs.
    conf = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/confirm",
        json={"stage": "source", "edits": {"currency": "EUR"}},
        headers=h,
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["status"] == "grouping"

    # Groups: the two walls merged into one group, 10 m3 total.
    groups = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups", headers=h)
    assert groups.status_code == 200, groups.text
    gbody = groups.json()
    assert gbody["total"] == 1
    assert "confidence_high_threshold" in gbody
    grp = gbody["groups"][0]
    assert grp["chosen_unit"] == "m3"
    assert grp["primary_quantity"] == pytest.approx(10.0)
    assert grp["status"] == "unmatched"
    group_id = grp["id"]

    # Match -> grounded candidate attached, real score.
    match = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/match",
        json={"use_agent": False, "top_k": 5},
        headers=h,
    )
    assert match.status_code == 200, match.text
    mg = match.json()["groups"][0]
    assert mg["chosen_code"] == "AIEST-RATE"
    assert float(mg["unit_rate"]) == 185.0
    assert mg["currency"] == "EUR"
    assert mg["confidence"] == pytest.approx(0.83, abs=1e-4)
    assert mg["confidence_band"] == "high"
    assert mg["status"] == "suggested"

    # Group detail carries the resource breakdown + grounded candidates.
    detail = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups/{group_id}", headers=h)
    assert detail.status_code == 200, detail.text
    dbody = detail.json()
    assert len(dbody["resources"]) == 2
    assert len(dbody["candidates"]) == 1
    assert dbody["candidates"][0]["candidate_id"] == str(cost_id)

    # Human confirms the group (AI suggests, human confirms).
    cg = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/groups/{group_id}/confirm",
        json={},
        headers=h,
    )
    assert cg.status_code == 200, cg.text
    assert cg.json()["status"] == "confirmed"

    # Walk the remaining checkpoints to the assembly gate.
    for stage in ("grouping", "matching", "assembly"):
        r = await http_client.post(
            f"/api/v1/ai-estimator/runs/{run_id}/confirm",
            json={"stage": stage},
            headers=h,
        )
        assert r.status_code == 200, r.text

    # Preview: validation attached, applicable, total = 10 x 185 = 1850 EUR.
    preview = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/preview", headers=h)
    assert preview.status_code == 200, preview.text
    pbody = preview.json()
    assert pbody["can_apply"] is True
    assert pbody["validation"] is not None
    assert pbody["validation"]["status"] in ("passed", "warnings")
    assert float(pbody["grand_total"]) == pytest.approx(1850.0)
    assert pbody["currency"] == "EUR"
    assert len(pbody["positions"]) == 1
    prow = pbody["positions"][0]
    assert prow["confirmed"] is False  # preview, not yet written
    assert len(prow["resources"]) == 2

    # Apply -> writes the BOQ.
    apply = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/apply",
        json={"boq_name": "AI Estimate"},
        headers=h,
    )
    assert apply.status_code == 200, apply.text
    abody = apply.json()
    assert abody["positions_created"] == 1
    assert float(abody["grand_total"]) == pytest.approx(1850.0)
    boq_id = abody["boq_id"]

    # The run is terminal-applied and points at the BOQ.
    run = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}", headers=h)
    assert run.json()["status"] == "applied"
    assert run.json()["boq_id"] == boq_id

    # Positions exist with the right provenance + resource sub-rows.
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        rows = (await s.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id)))).scalars().all()
    assert len(rows) == 1
    pos = rows[0]
    assert pos.source == "ai_precise_estimate"
    assert pos.validation_status == "pending"
    assert pos.confidence == "0.8300"  # real float, not a fabricated placeholder
    assert pos.cad_element_ids  # element ids carried over
    assert pos.metadata_["ai_estimator_run_id"] == run_id
    assert pos.metadata_["cost_item_id"] == str(cost_id)
    assert len(pos.metadata_["resources"]) == 2
    # Resource scaled by factor x parent qty (1.0 x 10).
    assert pos.metadata_["resources"][0]["quantity"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_match_no_candidate_marks_needs_human(http_client, admin, monkeypatch):
    """rank() returning no candidate -> the group is needs_human with a null
    rate, never silently dropped and never an invented number."""
    from app.core.match_service.envelope import MatchRequest, MatchResponse

    async def _empty_rank(req, *, db, ai_settings=None):
        return MatchResponse(
            request=req
            if isinstance(req, MatchRequest)
            else MatchRequest(envelope=req.envelope, project_id=req.project_id),
            candidates=[],
        )

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _empty_rank)

    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    h = admin["headers"]
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Unobtanium widget", "qty": 3.0, "unit": "pcs"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)
    assert match.status_code == 200, match.text
    g = match.json()["groups"][0]
    assert g["status"] == "needs_human"
    assert g["unit_rate"] is None
    assert g["confidence"] is None
    assert g["confidence_band"] == "none"


# ═════════════════════════════════════════════════════════════════════════
#  2b. Multi-pass mapping pipeline (semantic -> unit/scale -> rate sanity)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_match_records_three_named_passes_in_trace(http_client, admin, monkeypatch):
    """A matched group carries a mapping_trace with exactly the three named
    passes (semantic / unit_scale / rate_sanity) and a final_method, and the
    run timeline records a per-pass semantic observation. Deterministic, no key."""
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    # Two plausible same-dimension m2 candidates so all passes have real work.
    c1 = await _seed_cost_item(description="Floor tiling porcelain", unit="m2", rate="45.00", currency="EUR")
    c2 = await _seed_cost_item(description="Floor tiling ceramic", unit="m2", rate="52.00", currency="EUR")
    _stub_rank_candidates(
        monkeypatch,
        [
            {
                "id": c1,
                "code": "TILE-1",
                "description": "Floor tiling porcelain",
                "unit": "m2",
                "unit_rate": 45.0,
                "score": 0.84,
            },
            {
                "id": c2,
                "code": "TILE-2",
                "description": "Floor tiling ceramic",
                "unit": "m2",
                "unit_rate": 52.0,
                "score": 0.80,
            },
        ],
    )
    h = admin["headers"]

    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Floor tiling", "qty": 20.0, "unit": "m2", "category": "finishes"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)
    assert match.status_code == 200, match.text
    group_id = match.json()["groups"][0]["id"]

    # The group detail exposes the three-pass mapping trace (WP4 serialisation).
    detail = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups/{group_id}", headers=h)
    assert detail.status_code == 200, detail.text
    trace = detail.json()["mapping_trace"]
    assert trace is not None, "mapping_trace must be present on a matched group"
    names = [p["pass"] for p in trace["passes"]]
    assert names == ["semantic", "unit_scale", "rate_sanity"]
    # Each pass entry carries the structured kept/dropped/notes shape.
    for p in trace["passes"]:
        assert {"pass", "kept", "dropped", "notes", "benchmark"} <= set(p)
    # The rate-sanity pass carries a benchmark band block.
    rs = trace["passes"][2]
    assert rs["benchmark"]["trade"] == "finishes"
    assert rs["benchmark"]["unit"] == "m2"
    # No key + no agent -> deterministic vector method.
    assert trace["final_method"] == "vector"

    # The run timeline rendered the multi-pass for free (semantic observation).
    steps = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/steps", headers=h)
    assert steps.status_code == 200, steps.text
    contents = [s.get("content") or {} for s in steps.json()]
    assert any(isinstance(c, dict) and c.get("pass") == "semantic" for c in contents), (
        "the run timeline must record a semantic-pass observation"
    )


@pytest.mark.asyncio
async def test_rate_sanity_flags_outlier_without_dropping_real_top(http_client, admin, monkeypatch):
    """An injected ~130x outlier candidate is flagged (rate_outlier) and capped at
    LOW band, while the dimensionally- and price-plausible candidate is the chosen
    top-1. The real outlier rate is kept for human override, never dropped."""
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    good1 = await _seed_cost_item(description="Wall plaster A", unit="m2", rate="20.00", currency="EUR")
    good2 = await _seed_cost_item(description="Wall plaster B", unit="m2", rate="24.00", currency="EUR")
    outlier = await _seed_cost_item(description="Wall plaster mispriced", unit="m2", rate="3000.00", currency="EUR")
    _stub_rank_candidates(
        monkeypatch,
        [
            # The outlier has the HIGHEST raw score; rate sanity must still demote it
            # out of top-1 (it is the only outlier), choosing a plausible candidate.
            {"id": outlier, "code": "PLASTER-OUT", "unit": "m2", "unit_rate": 3000.0, "score": 0.90},
            {"id": good1, "code": "PLASTER-1", "unit": "m2", "unit_rate": 20.0, "score": 0.85},
            {"id": good2, "code": "PLASTER-2", "unit": "m2", "unit_rate": 24.0, "score": 0.80},
        ],
    )
    h = admin["headers"]

    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Wall plaster", "qty": 30.0, "unit": "m2", "category": "finishes"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)
    assert match.status_code == 200, match.text
    mg = match.json()["groups"][0]
    group_id = mg["id"]

    # The chosen top-1 is a plausible candidate, NOT the 3000 outlier.
    assert mg["chosen_code"] in ("PLASTER-1", "PLASTER-2")
    assert float(mg["unit_rate"]) in (20.0, 24.0)

    detail = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups/{group_id}", headers=h)
    cands = {c["code"]: c for c in detail.json()["candidates"]}
    # The outlier survived (never dropped) but is flagged + capped at LOW band.
    assert "PLASTER-OUT" in cands, "the real outlier rate must be kept for human override"
    assert cands["PLASTER-OUT"]["rate_outlier"] is True
    assert cands["PLASTER-OUT"]["confidence_band"] == "low"
    # The plausible candidates are not flagged.
    assert cands["PLASTER-1"]["rate_outlier"] is False
    # The rate-sanity pass reported exactly one outlier in the trace.
    rs = detail.json()["mapping_trace"]["passes"][2]
    assert rs["benchmark"]["outliers"] == 1


@pytest.mark.asyncio
async def test_unit_scale_demotes_dimension_mismatch_in_match(http_client, admin, monkeypatch):
    """A volume (m3) candidate for an area (m2) group is demoted out of top-1 by
    the unit/scale pass; the dimensionally-correct m2 candidate is chosen, and
    the m3 candidate is kept in the override list (never dropped)."""
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    m3 = await _seed_cost_item(description="Concrete by volume", unit="m3", rate="120.00", currency="EUR")
    m2 = await _seed_cost_item(description="Screed by area", unit="m2", rate="35.00", currency="EUR")
    _stub_rank_candidates(
        monkeypatch,
        [
            # The m3 candidate has the higher raw score but the wrong dimension.
            {"id": m3, "code": "VOL", "unit": "m3", "unit_rate": 120.0, "score": 0.90},
            {"id": m2, "code": "AREA", "unit": "m2", "unit_rate": 35.0, "score": 0.70},
        ],
    )
    h = admin["headers"]

    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Floor screed", "qty": 40.0, "unit": "m2", "category": "finishes"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)
    mg = match.json()["groups"][0]
    # The m2 (dimensionally-correct) candidate is top-1 despite the lower raw score.
    assert mg["chosen_code"] == "AREA"
    assert float(mg["unit_rate"]) == 35.0

    detail = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups/{mg['id']}", headers=h)
    codes = {c["code"] for c in detail.json()["candidates"]}
    assert codes == {"VOL", "AREA"}  # the m3 candidate survived, just demoted
    unit_scale = detail.json()["mapping_trace"]["passes"][1]
    assert unit_scale["pass"] == "unit_scale"
    assert unit_scale["dropped"] == 1


@pytest.mark.asyncio
async def test_apply_blocked_before_assembly_checkpoint(http_client, admin, monkeypatch):
    """Apply must 409 before the assembly review checkpoint is accepted - never
    auto-applies (AI suggests, human confirms)."""
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    cost_id = await _seed_cost_item(description="Wall", unit="m3", rate="100.00", currency="EUR")
    _stub_rank(monkeypatch, cost_id, unit_rate=100.0, currency="EUR", score=0.81)
    h = admin["headers"]

    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Wall", "qty": 5.0, "unit": "m3"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)

    # No assembly checkpoint accepted yet -> apply rejected.
    apply = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/apply", json={}, headers=h)
    assert apply.status_code == 409, apply.text


@pytest.mark.asyncio
async def test_add_sources_after_analysis_is_rejected(http_client, admin):
    """Sources can only be coalesced before analysis advances - 409 once the
    source checkpoint is accepted (FSM guard)."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    h = admin["headers"]
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "wall"},
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    resp = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/sources",
        json={"source": "text", "text_input": "more"},
        headers=h,
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_cancel_then_cancel_applied_guard(http_client, admin, monkeypatch):
    """A run cancels cleanly; an applied run cannot be cancelled (409)."""
    h = admin["headers"]
    # A fresh run cancels.
    project_id = await _seed_project(owner_id=admin["user_id"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "wall"},
        headers=h,
    )
    run_id = create.json()["id"]
    cancel = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/cancel", json={}, headers=h)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    # Drive a second run to applied, then assert cancel is refused.
    project2 = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    cost_id = await _seed_cost_item(description="Wall", unit="m3", rate="100.00", currency="EUR")
    _stub_rank(monkeypatch, cost_id, unit_rate=100.0, currency="EUR", score=0.81)
    create2 = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project2),
            "source": "excel",
            "rows": [{"description": "Wall", "qty": 5.0, "unit": "m3"}],
            "currency": "EUR",
        },
        headers=h,
    )
    rid2 = create2.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/match", json={"use_agent": False}, headers=h)
    gid = match.json()["groups"][0]["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/groups/{gid}/confirm", json={}, headers=h)
    for stage in ("grouping", "matching", "assembly"):
        await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/confirm", json={"stage": stage}, headers=h)
    apply = await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/apply", json={}, headers=h)
    assert apply.status_code == 200, apply.text

    cancel2 = await http_client.post(f"/api/v1/ai-estimator/runs/{rid2}/cancel", json={}, headers=h)
    assert cancel2.status_code == 409, cancel2.text


@pytest.mark.asyncio
async def test_fx_rollup_keeps_per_currency_subtotals(http_client, admin):
    """Mixed-currency confirmed groups roll up into the base currency via the
    project FX map, and the per-currency subtotals are never blended."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.ai_estimator.models import AiEstimatorGroup
    from app.modules.projects.models import Project

    h = admin["headers"]
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    # Add a USD fx rate (1 USD = 0.90 EUR) to the project.
    async with async_session_factory() as s:
        await s.execute(
            update(Project).where(Project.id == project_id).values(fx_rates=[{"code": "USD", "rate": "0.90"}])
        )
        await s.commit()

    eur_cost = await _seed_cost_item(description="EUR wall", unit="m3", rate="100.00", currency="EUR")
    usd_cost = await _seed_cost_item(description="USD slab", unit="m2", rate="200.00", currency="USD")

    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [
                {"description": "EUR wall", "qty": 10.0, "unit": "m3", "category": "walls"},
                {"description": "USD slab", "qty": 5.0, "unit": "m2", "category": "slabs"},
            ],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    groups = (await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups", headers=h)).json()["groups"]
    by_unit = {g["chosen_unit"]: g for g in groups}

    # Ground + confirm each group directly in two currencies (deterministic).
    async with async_session_factory() as s:
        await s.execute(
            update(AiEstimatorGroup)
            .where(AiEstimatorGroup.id == uuid.UUID(by_unit["m3"]["id"]))
            .values(
                status="confirmed",
                candidate_id=str(eur_cost),
                chosen_code="EUR-1",
                unit_rate="100.00",
                currency="EUR",
                confidence=0.9,
                confidence_band="high",
            )
        )
        await s.execute(
            update(AiEstimatorGroup)
            .where(AiEstimatorGroup.id == uuid.UUID(by_unit["m2"]["id"]))
            .values(
                status="confirmed",
                candidate_id=str(usd_cost),
                chosen_code="USD-1",
                unit_rate="200.00",
                currency="USD",
                confidence=0.9,
                confidence_band="high",
            )
        )
        await s.commit()

    for stage in ("grouping", "matching", "assembly"):
        await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": stage}, headers=h)

    preview = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/preview", headers=h)
    assert preview.status_code == 200, preview.text
    pbody = preview.json()
    # EUR line: 10 x 100 = 1000 EUR. USD line: 5 x 200 = 1000 USD -> 900 EUR.
    # Grand total in base = 1900 EUR.
    assert float(pbody["grand_total"]) == pytest.approx(1900.0)
    assert pbody["currency"] == "EUR"
    # Subtotals kept per-currency, NEVER blended.
    subtotals = {k: float(v) for k, v in pbody["currency_subtotals"].items()}
    assert subtotals == {"EUR": pytest.approx(1000.0), "USD": pytest.approx(1000.0)}


# ═════════════════════════════════════════════════════════════════════════
#  3. RBAC + IDOR
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_viewer_can_read_but_cannot_create_or_apply(http_client, admin, monkeypatch):
    """A viewer who is a project member can read runs but cannot create a run
    (run verb = EDITOR) nor apply (apply verb = EDITOR)."""
    project_id = await _seed_project(owner_id=admin["user_id"], currency="EUR")
    cost_id = await _seed_cost_item(description="Wall", unit="m3", rate="100.00", currency="EUR")
    _stub_rank(monkeypatch, cost_id, unit_rate=100.0, currency="EUR", score=0.81)
    h = admin["headers"]

    # Admin drives a run to the assembly gate.
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "excel",
            "rows": [{"description": "Wall", "qty": 5.0, "unit": "m3"}],
            "currency": "EUR",
        },
        headers=h,
    )
    run_id = create.json()["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": "source"}, headers=h)
    match = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/match", json={"use_agent": False}, headers=h)
    gid = match.json()["groups"][0]["id"]
    await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/groups/{gid}/confirm", json={}, headers=h)
    for stage in ("grouping", "matching", "assembly"):
        await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/confirm", json={"stage": stage}, headers=h)

    # Viewer, made a project member so verify_project_access passes.
    viewer_uid, _, viewer_h = await _register_login_promote(
        http_client, tenant=f"viewer-{uuid.uuid4().hex[:6]}", role="viewer"
    )
    await _add_project_member(project_id, viewer_uid)

    # Viewer can READ the run + groups + preview.
    rd = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}", headers=viewer_h)
    assert rd.status_code == 200, rd.text
    grd = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups", headers=viewer_h)
    assert grd.status_code == 200, grd.text

    # Viewer CANNOT create a run (run verb = EDITOR) -> 403.
    bad_create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "x"},
        headers=viewer_h,
    )
    assert bad_create.status_code == 403, bad_create.text

    # Viewer CANNOT apply (apply verb = EDITOR) -> 403, nothing written.
    bad_apply = await http_client.post(f"/api/v1/ai-estimator/runs/{run_id}/apply", json={}, headers=viewer_h)
    assert bad_apply.status_code == 403, bad_apply.text


@pytest.mark.asyncio
async def test_idor_outsider_cannot_read_run(http_client, admin):
    """A non-member, non-admin user cannot read another tenant's run (404, not
    403, so the run id's existence is not leaked)."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "wall"},
        headers=admin["headers"],
    )
    run_id = create.json()["id"]

    _, _, outsider_h = await _register_login_promote(
        http_client, tenant=f"outsider-{uuid.uuid4().hex[:6]}", role="viewer"
    )
    resp = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}", headers=outsider_h)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_catalogues_and_qdrant_health_reuse(http_client, admin):
    """The reuse endpoints (catalogues registry + Qdrant health) respond."""
    cat = await http_client.get("/api/v1/ai-estimator/catalogues", headers=admin["headers"])
    assert cat.status_code == 200, cat.text
    assert isinstance(cat.json(), list)

    health = await http_client.get("/api/v1/ai-estimator/qdrant/health", headers=admin["headers"])
    assert health.status_code == 200, health.text
    assert "reachable" in health.json()


# ═════════════════════════════════════════════════════════════════════════
#  4. Meta contract + construction_stage validation + boq_id in list
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_meta_endpoint_returns_the_agreed_contract(http_client, admin):
    """GET /meta returns the exact agreed shape, sourced from the module's
    single definitions (thresholds ~0.78/0.62, the 12-stage enum, cap 25)."""
    from app.modules.ai_estimator import schemas
    from app.modules.ai_estimator.service import (
        CONFIDENCE_HIGH_THRESHOLD,
        CONFIDENCE_MEDIUM_THRESHOLD,
    )

    resp = await http_client.get("/api/v1/ai-estimator/meta", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"score_thresholds", "construction_stages", "match_group_cap"}
    assert body["score_thresholds"] == {
        "high": CONFIDENCE_HIGH_THRESHOLD,
        "low": CONFIDENCE_MEDIUM_THRESHOLD,
    }
    assert body["construction_stages"] == list(schemas.CONSTRUCTION_STAGES)
    assert body["match_group_cap"] == schemas.DEFAULT_MATCH_GROUP_CAP


@pytest.mark.asyncio
async def test_meta_requires_authentication(http_client):
    """The meta endpoint enforces ai_estimator.read (no anonymous access)."""
    resp = await http_client.get("/api/v1/ai-estimator/meta")
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_create_run_rejects_unknown_construction_stage(http_client, admin):
    """A bad construction_stage on create -> 422; a valid enum value -> 201."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    bad = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "text",
            "text_input": "Brick wall, 24cm",
            "construction_stage": "nonsense",
        },
        headers=admin["headers"],
    )
    assert bad.status_code == 422, bad.text

    good = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "text",
            "text_input": "Brick wall, 24cm",
            "construction_stage": "07_Envelope",
        },
        headers=admin["headers"],
    )
    assert good.status_code == 201, good.text
    assert good.json()["construction_stage"] == "07_Envelope"


@pytest.mark.asyncio
async def test_confirm_source_rejects_unknown_construction_stage_edit(http_client, admin):
    """The source-confirm edits validate construction_stage against the closed
    taxonomy: a typo is a clean 422, a valid value advances the run."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    h = admin["headers"]
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "Brick wall, 24cm"},
        headers=h,
    )
    run_id = create.json()["id"]
    bad = await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/confirm",
        json={"stage": "source", "edits": {"construction_stage": "nope"}},
        headers=h,
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_runs_list_rows_carry_boq_id(http_client, admin):
    """Each row in the runs list serializer carries boq_id (null before apply),
    matching the detail endpoint."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={"project_id": str(project_id), "source": "text", "text_input": "Brick wall, 24cm"},
        headers=admin["headers"],
    )
    assert create.status_code == 201, create.text
    run_id = create.json()["id"]

    listing = await http_client.get(f"/api/v1/ai-estimator/runs?project_id={project_id}", headers=admin["headers"])
    assert listing.status_code == 200, listing.text
    rows = listing.json()["runs"]
    row = next(r for r in rows if r["id"] == run_id)
    assert "boq_id" in row
    assert row["boq_id"] is None  # not applied yet


@pytest.mark.asyncio
async def test_failed_source_extraction_sets_failed_and_publishes_event(http_client, admin, monkeypatch):
    """A run referencing a missing artifact fails honestly (status=failed,
    failure_reason set) and publishes ai_estimator.run.failed."""
    from app.modules.ai_estimator import events as estimator_events

    captured: list[dict] = []

    def _capture(event_name, data, **_kwargs):
        if event_name == estimator_events.EVENT_RUN_FAILED:
            captured.append(data)

    monkeypatch.setattr(estimator_events.event_bus, "publish_detached", _capture)

    project_id = await _seed_project(owner_id=admin["user_id"])
    # source=bim with a model id that does not exist in this project -> the
    # source extractor finds nothing -> the run fails with a reason.
    resp = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "bim",
            "bim_model_ids": [str(uuid.uuid4())],
        },
        headers=admin["headers"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    assert body["failure_reason"]
    # The run.failed event fired with the structured reason.
    assert captured, "ai_estimator.run.failed was not published"
    assert captured[0]["failure_reason"] == body["failure_reason"]
    assert captured[0]["project_id"] == str(project_id)


@pytest.mark.asyncio
async def test_text_run_keeps_dimension_spec_comma_as_one_element(http_client, admin):
    """A text run over 'Brick wall, 24cm\\n30 m3 concrete foundation' yields
    exactly two estimable elements; the first description keeps the comma spec."""
    project_id = await _seed_project(owner_id=admin["user_id"])
    create = await http_client.post(
        "/api/v1/ai-estimator/runs",
        json={
            "project_id": str(project_id),
            "source": "text",
            "text_input": "Brick wall, 24cm\n30 m3 concrete foundation",
            "currency": "EUR",
        },
        headers=admin["headers"],
    )
    assert create.status_code == 201, create.text
    body = create.json()
    run_id = body["id"]
    # Honest element count surfaced in the detected-source summary.
    assert body["detected_source"]["by_source"].get("text") == 2

    # Confirm source -> grouping; the per-clause group hint keeps them distinct.
    await http_client.post(
        f"/api/v1/ai-estimator/runs/{run_id}/confirm",
        json={"stage": "source", "edits": {"currency": "EUR"}},
        headers=admin["headers"],
    )
    groups = await http_client.get(f"/api/v1/ai-estimator/runs/{run_id}/groups", headers=admin["headers"])
    gbody = groups.json()
    assert gbody["total"] == 2
    descs = [g["description"] for g in gbody["groups"]]
    assert any("Brick wall, 24cm" in (d or "") for d in descs)
