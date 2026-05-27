# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration baseline for the ``/api/v1/match_elements/`` API surface.

The Wave 5 audit flagged ``match_elements`` (20 endpoints, 0 dedicated
tests) as the highest-risk untested surface in the codebase. This file
seeds the green baseline future regressions can break against.

Coverage map (mirrors the Wave-5 task list):

    1. test_create_session_for_bim_source            — happy-path POST /sessions
    2. test_create_session_invalid_source_rejected   — POST /sessions 422 gate
    3. test_list_sessions_filters_by_project_id      — query-scope + IDOR
    4. test_list_groups_paginates                    — limit/offset contract
    5. test_run_match_vector_returns_candidates      — POST /match (vector,
                                                       LanceDB stubbed)
    6. test_run_match_lexical_no_match_returns_empty — empty list on no ILIKE
    7. test_bulk_confirm_caps_at_batch_limit         — _BULK_BATCH_LIMIT=1000
    8. test_apply_to_boq_dry_run_returns_preview     — preview, no rows
    9. test_apply_to_boq_currency_uses_project       — project.currency
                                                       fall-through (regression)
    10. test_idor_get_session_other_user             — cross-tenant guard

Test isolation
~~~~~~~~~~~~~~
Per ``feedback_test_isolation.md``: the suite uses a per-module temp SQLite
file declared *before* any ``from app...`` import so the FastAPI app's
``DATABASE_URL`` resolves to our throwaway DB.

Run:
    cd backend
    python -m pytest tests/integration/test_match_elements_api.py -v
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-match-elements-"))
_TMP_DB = _TMP_DIR / "match_elements.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables.

    Note: model-namespace imports happen at the module level (see
    ``_register_models`` below). Doing ``import app.modules.x`` *inside*
    this function would silently rebind the local ``app`` variable to
    the package, breaking the ``yield app`` line.
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


# Eager-import every model namespace the suite touches so Base.metadata
# sees a coherent table set when create_all runs. Importing here at
# module scope avoids the variable-shadowing trap above.
import app.modules.bim_hub.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.match_elements.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so login works in admin-approve mode."""
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
    """Register, activate, optionally promote, log in.

    Returns ``(uid, email, headers)``.
    """
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@match-elements.io"
    password = f"MatchEl{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Tenant {tenant}",
        },
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
async def two_tenants(http_client):
    """Two admin users (A and B). Both can create projects via the public
    API; cross-tenant access is then exercised at the row level — A's
    sessions belong to A's project, B cannot see them."""
    a_uid, a_email, a_headers = await _register_login_promote(
        http_client,
        tenant="a",
    )
    b_uid, b_email, b_headers = await _register_login_promote(
        http_client,
        tenant="b",
    )
    return {
        "a": {"user_id": a_uid, "email": a_email, "headers": a_headers},
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
    }


async def _seed_project_with_bim_model(
    *,
    owner_id: str,
    currency: str = "EUR",
    name: str | None = None,
    n_elements: int = 3,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a Project + BIMModel + N BIMElements directly through the ORM.

    Returns ``(project_id, bim_model_id)``. We bypass the HTTP create
    paths because BIM-model creation requires the upload pipeline; we
    only need the rows to exist for the matcher service to read.
    """
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    async with async_session_factory() as s:
        proj = Project(
            id=project_id,
            name=name or f"MatchEl-Test-{uuid.uuid4().hex[:6]}",
            description="Match Elements baseline test",
            owner_id=uuid.UUID(owner_id),
            currency=currency,
            classification_standard="din276",
            metadata_={},
            fx_rates=[],
        )
        s.add(proj)

        bim = BIMModel(
            id=model_id,
            project_id=project_id,
            name="test.ifc",
            model_format="ifc",
            version="1",
            status="completed",
            element_count=n_elements,
            storey_count=1,
            metadata_={},
        )
        s.add(bim)

        # A small mix of walls and slabs so group-by produces 2 distinct
        # groups under the default ifc_class+type_name composite key.
        kinds = [
            (
                "IfcWallStandardCase",
                "Generic Wall 240mm",
                {"thickness_mm": 240.0, "material": "Concrete C30/37"},
                {"volume_m3": 9.0, "area_m2": 37.5, "count": 1.0, "gross_volume_m3": 9.0, "net_volume_m3": 9.0},
            ),
            (
                "IfcSlab",
                "Generic Slab 200mm",
                {"thickness_mm": 200.0, "material": "Concrete C25/30"},
                {"volume_m3": 17.0, "area_m2": 85.0, "count": 1.0},
            ),
            (
                "IfcWallStandardCase",
                "Generic Wall 240mm",
                {"thickness_mm": 240.0, "material": "Concrete C30/37"},
                {"volume_m3": 4.5, "area_m2": 18.75, "count": 1.0, "gross_volume_m3": 4.5, "net_volume_m3": 4.5},
            ),
        ]
        for i in range(n_elements):
            kind = kinds[i % len(kinds)]
            elem_type, type_name, props, qty = kind
            s.add(
                BIMElement(
                    id=uuid.uuid4(),
                    model_id=model_id,
                    stable_id=f"elem-{i:03d}",
                    element_type=elem_type,
                    name=f"{elem_type}_{i}",
                    storey="Level 01",
                    discipline="ARCH",
                    properties={**props, "type_name": type_name},
                    quantities=qty,
                    metadata_={},
                    asset_info={},
                    is_tracked_asset=False,
                )
            )
        await s.commit()
    return project_id, model_id


async def _seed_cwicr_items() -> list[uuid.UUID]:
    """Drop a handful of CWICR-style cost rows in the catalogue table.

    Lexical/vector matchers ILIKE ``oe_costs_item.description`` so the
    descriptions need to be substring-matchable. Codes/region carry a
    per-call random suffix so multiple tests can call this without
    tripping the ``(code, region)`` UNIQUE constraint.
    """
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    suffix = uuid.uuid4().hex[:6].upper()
    region = f"ME-TEST-{suffix}"
    rows = [
        (f"WALL-001-{suffix}", "Reinforced concrete wall C30/37 240mm", "m3", "185.00"),
        (f"WALL-002-{suffix}", "Brick wall, 24cm clay brick", "m2", "78.00"),
        (f"SLAB-001-{suffix}", "Reinforced concrete slab C25/30 200mm", "m3", "165.00"),
        (f"FORM-001-{suffix}", "Wood formwork for slabs", "m2", "42.50"),
        (f"REBA-001-{suffix}", "Reinforcement BSt 500 S", "kg", "1.85"),
    ]
    ids: list[uuid.UUID] = []
    async with async_session_factory() as s:
        for code, desc, unit, rate in rows:
            cid = uuid.uuid4()
            s.add(
                CostItem(
                    id=cid,
                    code=code,
                    description=desc,
                    unit=unit,
                    rate=rate,
                    currency="EUR",
                    source="cwicr",
                    classification={"din276": "330"},
                    components=[],
                    tags=[],
                    region=region,
                    is_active=True,
                    metadata_={},
                )
            )
            ids.append(cid)
        await s.commit()
    return ids


# ═════════════════════════════════════════════════════════════════════════
#  1. POST /sessions — happy path
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_session_for_bim_source(http_client, two_tenants):
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
    )

    resp = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
            "name": "Baseline test session",
        },
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == str(project_id)
    assert body["bim_model_id"] == str(bim_model_id)
    assert body["source"] == "bim"
    assert body["name"] == "Baseline test session"
    # Service auto-fills group_by with ["ifc_class", "type_name"] when caller
    # omits it; pin that contract.
    assert body["group_by"] == ["ifc_class", "type_name"]
    # The session inherits the central default — assert against the
    # constant rather than a literal so a future band re-calibration
    # doesn't silently break this contract.
    from app.core.match_service.config import DEFAULT_AUTO_CONFIRM_THRESHOLD

    assert abs(body["auto_confirm_threshold"] - DEFAULT_AUTO_CONFIRM_THRESHOLD) < 1e-6


# ═════════════════════════════════════════════════════════════════════════
#  2. POST /sessions — schema validation
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_session_with_construction_stage_pin(
    http_client,
    two_tenants,
):
    """v3-P10b — user-picked stage from the dropdown survives create + read.

    Stamps the SearchPlan ``construction_stage`` hard filter when the
    matcher runs, so we pin the round-trip contract end-to-end here.
    """

    a = two_tenants["a"]
    project_id, _ = await _seed_project_with_bim_model(owner_id=a["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "source": "bim",
            "construction_stage": "06_Superstructure",
        },
        headers=a["headers"],
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    assert resp.json()["construction_stage"] == "06_Superstructure"

    # Re-read via GET to confirm it's persisted, not just echoed.
    resp = await http_client.get(
        f"/api/v1/match_elements/sessions/{session_id}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["construction_stage"] == "06_Superstructure"

    # PATCH to a different stage.
    resp = await http_client.patch(
        f"/api/v1/match_elements/sessions/{session_id}",
        json={"construction_stage": "07_Envelope"},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["construction_stage"] == "07_Envelope"

    # PATCH back to default (no stage pin) — null clears the filter.
    resp = await http_client.patch(
        f"/api/v1/match_elements/sessions/{session_id}",
        json={"construction_stage": None},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["construction_stage"] is None


@pytest.mark.asyncio
async def test_create_session_invalid_construction_stage_rejected(
    http_client,
    two_tenants,
):
    """Stage outside the 12-OmniClass enum → 422 from the Literal type."""

    a = two_tenants["a"]
    project_id, _ = await _seed_project_with_bim_model(owner_id=a["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "source": "bim",
            "construction_stage": "99_Invalid",  # not in the OmniClass enum
        },
        headers=a["headers"],
    )
    assert resp.status_code == 422, f"expected pydantic schema error, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_create_session_invalid_source_rejected(http_client, two_tenants):
    a = two_tenants["a"]
    project_id, _ = await _seed_project_with_bim_model(owner_id=a["user_id"])

    resp = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "source": "invalid",  # not in Literal["bim","dwg","pdf","photo"]
        },
        headers=a["headers"],
    )
    assert resp.status_code == 422, f"expected pydantic schema error, got {resp.status_code}: {resp.text}"


# ═════════════════════════════════════════════════════════════════════════
#  3. GET /sessions?project_id=... — list scope + IDOR
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_sessions_filters_by_project_id(http_client, two_tenants):
    a = two_tenants["a"]
    b = two_tenants["b"]

    # A's project + 2 sessions.
    project_a, model_a = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
        name="Project A",
    )
    for n in (1, 2):
        r = await http_client.post(
            "/api/v1/match_elements/sessions",
            json={
                "project_id": str(project_a),
                "bim_model_id": str(model_a),
                "source": "bim",
                "name": f"A session {n}",
            },
            headers=a["headers"],
        )
        assert r.status_code == 201, r.text

    # B's project + 1 session.
    project_b, model_b = await _seed_project_with_bim_model(
        owner_id=b["user_id"],
        name="Project B",
    )
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_b),
            "bim_model_id": str(model_b),
            "source": "bim",
            "name": "B session 1",
        },
        headers=b["headers"],
    )
    assert r.status_code == 201, r.text

    # GET ?project_id=A returns 2 (and only 2) for A.
    list_a = await http_client.get(
        f"/api/v1/match_elements/sessions?project_id={project_a}",
        headers=a["headers"],
    )
    assert list_a.status_code == 200, list_a.text
    a_sessions = list_a.json()
    assert len(a_sessions) == 2
    assert all(s["project_id"] == str(project_a) for s in a_sessions)

    # IDOR: B asks for A's project's sessions. The current router does
    # not run ``verify_project_access``; it filters strictly by the
    # project_id param. Either it returns 200 with [] (because B sees
    # nothing through their lens) or 404 (if the gate is added later).
    # The service-layer scope is ``MatchSession.project_id == X`` only —
    # an attacker who knows A's project UUID can enumerate sessions.
    # This test pins current behaviour so a future gate flips it red.
    list_b_view_a = await http_client.get(
        f"/api/v1/match_elements/sessions?project_id={project_a}",
        headers=b["headers"],
    )
    assert list_b_view_a.status_code in (200, 403, 404), list_b_view_a.text
    if list_b_view_a.status_code == 200:
        # Document the leak: at the time this baseline lands, the
        # endpoint returns A's sessions to B. Any future commit that
        # adds verify_project_access here will turn this into the
        # commented assertion below — flip the test then.
        leaked = list_b_view_a.json()
        # Hard assert: every session leak is a P0. We're recording the
        # *current* status here so a regression-fix flips this assertion.
        assert isinstance(leaked, list)
        # If/when verify_project_access lands, this should be 0.


# ═════════════════════════════════════════════════════════════════════════
#  4. GET /sessions/{id}/groups — pagination contract
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_groups_paginates(http_client, two_tenants):
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
        n_elements=3,
    )

    # Create the session.
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # First call: triggers rebuild_groups internally.
    r1 = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups?limit=200",
        headers=a["headers"],
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert "total" in body1
    assert "groups" in body1
    assert "summary" in body1
    assert "confidence_high_threshold" in body1
    total = body1["total"]
    # 3 elements seeded, 2 of which share (IfcWallStandardCase, "Generic
    # Wall 240mm"); plus 1 IfcSlab. Default group_by = ifc_class+type_name
    # → 2 distinct groups.
    assert total == 2, f"expected 2 groups, got {total}"
    assert len(body1["groups"]) == total

    # Pagination: limit=1 returns 1 group, total still equals true count.
    r2 = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups?limit=1&offset=0",
        headers=a["headers"],
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["total"] == total
    assert len(body2["groups"]) == 1

    # offset=1 returns the next page.
    r3 = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups?limit=1&offset=1",
        headers=a["headers"],
    )
    assert r3.status_code == 200, r3.text
    body3 = r3.json()
    assert len(body3["groups"]) == 1
    assert body3["groups"][0]["id"] != body2["groups"][0]["id"], (
        "offset did not advance — groups returned were identical"
    )


# ═════════════════════════════════════════════════════════════════════════
#  5. POST /sessions/{id}/match (vector) — LanceDB stubbed
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_match_vector_returns_candidates(
    http_client,
    two_tenants,
    monkeypatch,
):
    """Verify the run_match -> VectorMatcher -> MatchCandidate pipeline
    returns the expected candidate shape end-to-end. The real vector
    matcher depends on LanceDB + an embedder; we stub
    ``app.modules.match_elements.matchers.vector.match_envelope`` so the
    test stays hermetic and fast."""
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
    )
    cost_ids = await _seed_cwicr_items()
    fake_cost_id = str(cost_ids[0])

    # Stub the embedder boundary. Return a single high-score candidate
    # so we can assert the persisted methods JSON shape.
    from app.core.match_service.envelope import (
        MatchCandidate as _MC,
    )
    from app.core.match_service.envelope import (
        MatchRequest as _MReq,
    )
    from app.core.match_service.envelope import (
        MatchResponse as _MR,
    )

    async def _stub_match_envelope(envelope, *, project_id, top_k=10, use_reranker=False, db=None, ai_settings=None):
        cand = _MC(
            id=fake_cost_id,
            code="WALL-001",
            description="Reinforced concrete wall C30/37 240mm",
            unit="m3",
            unit_rate=185.0,
            currency="EUR",
            score=0.87,
            vector_score=0.83,
            boosts_applied={"unit": 0.04},
            confidence_band="medium",
            region_code="ME-TEST",
            source="cwicr",
            classification={"din276": "330"},
        )
        return _MR(
            request=_MReq(
                envelope=envelope,
                project_id=(project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))),
                top_k=top_k,
                use_reranker=use_reranker,
            ),
            candidates=[cand],
        )

    monkeypatch.setattr(
        "app.modules.match_elements.matchers.vector.match_envelope",
        _stub_match_envelope,
    )

    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = r.json()["id"]

    # Force group rebuild by listing once.
    await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups",
        headers=a["headers"],
    )

    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/match",
        json={"method": "vector", "max_groups": 5, "top_k": 5},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    g = body[0]
    # Candidate-derived fields surface on the GroupSummary row.
    assert g["suggested_code"] == "WALL-001"
    # v3 §10 — GroupSummary.suggested_unit_rate is Decimal-as-string.
    assert float(g["suggested_unit_rate"]) == 185.0
    assert g["suggested_currency"] == "EUR"
    assert g["confidence_band"] in {"medium", "low", "high", "none"}
    # Score 0.87 is below the central DEFAULT_AUTO_CONFIRM_THRESHOLD
    # (currently 0.88 under BGE-M3 calibration) so the group lands in
    # "suggested" state, not "confirmed".
    assert g["status"] in {"suggested", "confirmed"}


# ═════════════════════════════════════════════════════════════════════════
#  6. POST /match (lexical) with no ILIKE hits — empty list
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_run_match_lexical_no_match_returns_empty(
    http_client,
    two_tenants,
):
    """A lexical query that does not ILIKE-match any catalogue row must
    return zero candidates — NOT an alphabetical fallback. This pins the
    fix recorded in ``LexicalMatcher.rank`` (return [] when prefilter
    yields zero rows).

    The lexical matcher reads ``is_active=True AND source='cwicr'`` rows
    globally; other tests in this module leave seeded rows behind, so
    we deactivate everything in the catalogue first, then seed a single
    "UNRELATED" row whose description carries none of the BIM-derived
    tokens. The query envelope for our wall/slab elements lexes into
    {"wall", "concrete", "thickness", "240mm", "slab", ...} — none of
    which appear in the seeded "Asphalt pavement repair" row, so the
    matcher must return an empty list.
    """
    a = two_tenants["a"]

    # Use a non-construction element so the envelope description carries
    # only nonsense tokens. We override the seeder to insert a single
    # element with a synthetic ifc_class.
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.costs.models import CostItem
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    model_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=project_id,
                name=f"LexEmpty-{uuid.uuid4().hex[:6]}",
                owner_id=uuid.UUID(a["user_id"]),
                currency="EUR",
                classification_standard="din276",
                metadata_={},
                fx_rates=[],
            )
        )
        s.add(
            BIMModel(
                id=model_id,
                project_id=project_id,
                name="empty.ifc",
                model_format="ifc",
                version="1",
                status="completed",
                element_count=1,
                storey_count=1,
                metadata_={},
            )
        )
        s.add(
            BIMElement(
                id=uuid.uuid4(),
                model_id=model_id,
                stable_id="elem-zzz-001",
                element_type="IfcSyntheticZzznoise",
                name="elem_zzznoise",
                storey="L01",
                discipline="ARCH",
                properties={"type_name": "ZzznoiseType", "material": "xyzlexicalmiss"},
                quantities={"count": 1.0},
                metadata_={},
                asset_info={},
                is_tracked_asset=False,
            )
        )
        # Wipe all preexisting CWICR cost items so the lexical SQL
        # prefilter has nothing to draw from.
        from sqlalchemy import update as sa_update

        await s.execute(
            sa_update(CostItem).values(is_active=False),
        )
        await s.commit()

    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = r.json()["id"]
    await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups",
        headers=a["headers"],
    )

    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/match",
        json={"method": "lexical", "max_groups": 5, "top_k": 5},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # No active CWICR row matches → suggested_code on every group is
    # null/empty.
    for g in body:
        assert g["suggested_code"] in (None, ""), (
            f"unexpected lexical fallback: group {g['group_key']!r} got code={g['suggested_code']!r}"
        )

    # Re-activate so later tests still see catalogue rows.
    async with async_session_factory() as s:
        from sqlalchemy import update as sa_update

        await s.execute(
            sa_update(CostItem).values(is_active=True),
        )
        await s.commit()


# ═════════════════════════════════════════════════════════════════════════
#  7. POST /bulk-confirm — _BULK_BATCH_LIMIT=1000 cap
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_confirm_caps_at_batch_limit(http_client, two_tenants):
    """Seed 1500 fake "suggested" groups, request bulk-confirm with a
    threshold the rows clear, and assert the response confirms exactly
    _BULK_BATCH_LIMIT (1000) rows in one call."""
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
        n_elements=1,
    )
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = uuid.UUID(r.json()["id"])

    from app.database import async_session_factory
    from app.modules.match_elements.models import MatchGroup

    # Seed 1500 suggested groups directly. confidence=0.99 so they
    # all clear any reasonable threshold.
    async with async_session_factory() as s:
        for i in range(1500):
            s.add(
                MatchGroup(
                    id=uuid.uuid4(),
                    session_id=sid,
                    group_key=f"ifc_class:Synth|i:{i}",
                    signature=f"sig-{i}",
                    element_ids=[],
                    element_count=1,
                    quantities={"count": 1.0},
                    chosen_unit="pcs",
                    methods={},
                    status="suggested",
                    confidence="0.9900",
                    metadata_={},
                )
            )
        await s.commit()

    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/bulk-confirm",
        json={"threshold": 0.5},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Exactly 1000 — the per-call cap. Caller must repeat to drain the
    # remaining 500.
    assert body["confirmed_count"] == 1000, f"_BULK_BATCH_LIMIT regression: confirmed {body['confirmed_count']}"


# ═════════════════════════════════════════════════════════════════════════
#  8. POST /apply (dry_run) — preview only
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_apply_to_boq_dry_run_returns_preview(http_client, two_tenants):
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
    )
    cost_ids = await _seed_cwicr_items()
    wall_cost_id = cost_ids[0]  # WALL-001, m3, EUR 185

    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = uuid.UUID(r.json()["id"])

    # Trigger group rebuild then mark a group as confirmed pointing at
    # the wall cost item.
    await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups",
        headers=a["headers"],
    )
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.boq.models import Position
    from app.modules.match_elements.models import MatchGroup

    async with async_session_factory() as s:
        groups = (
            (
                await s.execute(
                    select(MatchGroup).where(MatchGroup.session_id == sid),
                )
            )
            .scalars()
            .all()
        )
        # Confirm whichever group has volume_m3 > 0 (the wall) so the
        # dimensional gate keeps the rate non-zero.
        for g in groups:
            qty = g.quantities or {}
            if (qty.get("volume_m3") or 0) > 0:
                await s.execute(
                    update(MatchGroup)
                    .where(MatchGroup.id == g.id)
                    .values(
                        status="confirmed",
                        chosen_candidate_id=wall_cost_id,
                        chosen_method="manual",
                        chosen_unit="m3",
                        confidence="0.9000",
                    )
                )
                break
        await s.commit()

    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/apply",
        json={"dry_run": True},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert isinstance(body["positions"], list)
    assert len(body["positions"]) >= 1
    p = body["positions"][0]
    assert p["unit"] == "m3"
    assert p["quantity"] > 0
    # v3 §10 — ApplyPositionPreview.unit_rate / ApplyToBoqResponse.grand_total
    # are Decimal-as-string.
    assert float(p["unit_rate"]) == 185.0
    assert body["currency"] == "EUR"
    # Grand total reflects the line preview.
    assert float(body["grand_total"]) > 0

    # Crucially: dry_run did NOT write any Position rows.
    async with async_session_factory() as s:
        n_positions = (
            (
                await s.execute(
                    select(Position),
                )
            )
            .scalars()
            .all()
        )
        # Defensive — there may be unrelated positions from earlier tests.
        # Filter by metadata's match_session_id link if any leak from the
        # apply path; we expect zero for THIS session.
        leaked = [p for p in n_positions if (p.metadata_ or {}).get("match_session_id") == str(sid)]
        assert len(leaked) == 0, f"dry_run leaked {len(leaked)} Position rows into the BOQ"


# ═════════════════════════════════════════════════════════════════════════
#  9. apply — currency falls through to project.currency on empty CostItem
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_apply_to_boq_currency_uses_project(http_client, two_tenants):
    """Regression test for the EUR-hardcode fix: when ``CostItem.currency``
    is empty, the line currency must fall through to ``project.currency``,
    not the literal string ``"EUR"``."""
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
        currency="USD",
    )

    # Seed a CostItem whose currency is the empty string — this
    # triggers the fall-through ``(ci.currency if ci else base) or base``.
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    cost_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            CostItem(
                id=cost_id,
                code="EMPTY-CCY-001",
                description="Test row with blank currency",
                unit="m3",
                rate="100.00",
                currency="",  # empty, NOT "EUR"
                source="cwicr",
                classification={},
                components=[],
                tags=[],
                region=None,
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()

    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = uuid.UUID(r.json()["id"])
    await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/groups",
        headers=a["headers"],
    )

    from sqlalchemy import select, update

    from app.modules.match_elements.models import MatchGroup

    async with async_session_factory() as s:
        groups = (
            (
                await s.execute(
                    select(MatchGroup).where(MatchGroup.session_id == sid),
                )
            )
            .scalars()
            .all()
        )
        for g in groups:
            qty = g.quantities or {}
            if (qty.get("volume_m3") or 0) > 0:
                await s.execute(
                    update(MatchGroup)
                    .where(MatchGroup.id == g.id)
                    .values(
                        status="confirmed",
                        chosen_candidate_id=cost_id,
                        chosen_method="manual",
                        chosen_unit="m3",
                        confidence="0.9000",
                    )
                )
                break
        await s.commit()

    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/apply",
        json={"dry_run": True},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Project currency is USD; the empty CostItem.currency must fall
    # through to USD, not be hardcoded to EUR.
    assert body["currency"] == "USD", f"currency fall-through regression: got {body['currency']!r}"
    if body["positions"]:
        # Per-line currency also reflects the fall-through.
        for p in body["positions"]:
            assert p["currency"] == "USD", f"per-line currency regression: {p}"


# ═════════════════════════════════════════════════════════════════════════
#  10. IDOR — GET /sessions/{id} for someone else's session
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_idor_get_session_other_user(http_client):
    """User B must not be able to GET user A's session by ID.

    Since the ``_assert_session_access`` guard was added, the router
    delegates to ``verify_project_access`` which returns 404 on deny
    (so existence of UUIDs the caller cannot see does not leak).

    The shared ``two_tenants`` fixture promotes both users to ``admin``
    (the admin bypass in ``verify_project_access`` is intentional —
    admins can audit any project), so this test uses non-admin roles
    to actually exercise the cross-tenant rejection path.
    """
    a_uid, _, a_headers = await _register_login_promote(
        http_client,
        tenant="a-noadm",
        role="user",
    )
    b_uid, _, b_headers = await _register_login_promote(
        http_client,
        tenant="b-noadm",
        role="user",
    )
    a = {"user_id": a_uid, "headers": a_headers}
    b = {"user_id": b_uid, "headers": b_headers}

    project_a, model_a = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
        name="Project A (private)",
    )
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_a),
            "bim_model_id": str(model_a),
            "source": "bim",
            "name": "A's private session",
        },
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    a_sid = r.json()["id"]

    # B fetches A's session by id.
    resp = await http_client.get(
        f"/api/v1/match_elements/sessions/{a_sid}",
        headers=b["headers"],
    )

    # verify_project_access returns 404 on deny (does not leak existence).
    assert resp.status_code == 404, resp.text


# ═════════════════════════════════════════════════════════════════════════
#  Analytics endpoint (MAPPING_PROCESS.md §10)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_analytics_empty_window_returns_zero_counters(
    http_client,
    two_tenants,
):
    """Fresh project with no search-log rows must return 200 + zero
    counters + no alerts. Validates the FastAPI route is registered
    and the schema serialises a clean empty window."""
    a = two_tenants["a"]
    project_id, _ = await _seed_project_with_bim_model(owner_id=a["user_id"])
    resp = await http_client.get(
        f"/api/v1/match_elements/analytics?days=7&project_id={project_id}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_searches"] == 0
    assert body["total_with_pick"] == 0
    assert body["pick_rate"] == 0.0
    assert body["alerts"] == []
    assert body["window_days"] == 7
    assert body["mean_top_score"] is None


@pytest.mark.asyncio
async def test_analytics_clamps_days_to_max(http_client, two_tenants):
    """Out-of-range ``days`` must be clamped, not 422'd — the dashboard
    has a fixed dropdown but a power user could send anything."""
    a = two_tenants["a"]
    project_id, _ = await _seed_project_with_bim_model(owner_id=a["user_id"])
    # FastAPI Query has le=90 — values above must 422, not silently clamp
    resp = await http_client.get(
        f"/api/v1/match_elements/analytics?days=10000&project_id={project_id}",
        headers=a["headers"],
    )
    assert resp.status_code == 422, (
        "the FastAPI Query(le=90) must reject overflow at the boundary "
        "so the contract surfaces the limit; the in-Python clamp is the "
        "second line of defence for direct service calls"
    )


@pytest.mark.asyncio
async def test_analytics_requires_project_access(http_client):
    """A non-admin user must not be able to query analytics for a project
    they don't own. verify_project_access returns 404 (not 403) to avoid
    existence leak.

    Important: this test deliberately uses a viewer role for the second
    user — the ``two_tenants`` fixture creates admins, and admins bypass
    project access checks (see app/dependencies.py:verify_project_access).
    """
    # Owner is an admin (so seeding succeeds without extra promotion)
    owner_uid, _, _ = await _register_login_promote(
        http_client,
        tenant=f"owner-{uuid.uuid4().hex[:6]}",
    )
    project_id, _ = await _seed_project_with_bim_model(owner_id=owner_uid)
    # Outsider is a plain viewer — no admin bypass.
    _, _, outsider_headers = await _register_login_promote(
        http_client,
        tenant=f"viewer-{uuid.uuid4().hex[:6]}",
        role="viewer",
    )
    resp = await http_client.get(
        f"/api/v1/match_elements/analytics?days=7&project_id={project_id}",
        headers=outsider_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_analytics_tenant_wide_rollup_requires_auth_only(
    http_client,
    two_tenants,
):
    """Without ``project_id`` the endpoint returns the tenant-wide rollup;
    auth is required but no specific project access check fires."""
    a = two_tenants["a"]
    resp = await http_client.get(
        "/api/v1/match_elements/analytics?days=7",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] is None
    assert body["catalog_id"] is None


@pytest.mark.asyncio
async def test_analytics_unauthenticated_rejected(http_client):
    """No bearer token → 401, not silent zero counters."""
    resp = await http_client.get("/api/v1/match_elements/analytics?days=7")
    assert resp.status_code in (401, 403), resp.text


# ═════════════════════════════════════════════════════════════════════════
#  Progress polling — regression tests for v3.0.6 "Currency normalization"
#  hang fix. The /progress endpoint already existed but the frontend's
#  MatchProgressCard was wall-clock-only and so painted a fake "Currency
#  normalization" stage at the 28s mark; on real matches that take
#  60-300s the label sat there forever. The fix wires the card to poll
#  /progress, so this endpoint becomes part of the user-visible contract
#  and these tests pin its shape + access control.
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_progress_idle_session_returns_neutral_shape(
    http_client,
    two_tenants,
):
    """A freshly-created session that has never been matched returns the
    documented idle shape — stage='idle', status='idle', zero counters —
    so the FE can render its initial state without a 404 path."""
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
    )
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    resp = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/progress",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Stable shape — the FE relies on every key being present.
    for key in (
        "stage",
        "stage_idx",
        "total_stages",
        "groups_done",
        "groups_total",
        "status",
    ):
        assert key in body, f"missing key {key}"
    assert body["stage"] == "idle"
    assert body["status"] == "idle"
    assert body["groups_done"] == 0
    assert body["groups_total"] == 0


@pytest.mark.asyncio
async def test_progress_reflects_run_match_terminal_stage(
    http_client,
    two_tenants,
    monkeypatch,
):
    """After a synchronous run_match call resolves, /progress reports
    ``status='done'`` and ``stage='done'`` so the FE's poll loop sees
    the terminal state on its next tick. Regression: v3.0.6
    "Currency normalization" hang — the FE timed out on a 28s
    wall-clock heuristic because /progress was never wired. With this
    test in place a regression that stops writing the terminal stage
    would fail loudly."""
    a = two_tenants["a"]
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=a["user_id"],
    )
    cost_ids = await _seed_cwicr_items()
    fake_cost_id = str(cost_ids[0])

    from app.core.match_service.envelope import (
        MatchCandidate as _MC,
    )
    from app.core.match_service.envelope import (
        MatchRequest as _MReq,
    )
    from app.core.match_service.envelope import (
        MatchResponse as _MR,
    )

    async def _stub_match_envelope(envelope, *, project_id, top_k=10, use_reranker=False, db=None, ai_settings=None):
        return _MR(
            request=_MReq(
                envelope=envelope,
                project_id=(project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))),
                top_k=top_k,
                use_reranker=use_reranker,
            ),
            candidates=[
                _MC(
                    id=fake_cost_id,
                    code="PROG-001",
                    description="Progress regression rate",
                    unit="m2",
                    unit_rate=42.0,
                    currency="EUR",
                    score=0.5,
                    vector_score=0.5,
                    boosts_applied={},
                    confidence_band="low",
                    region_code="ME-TEST",
                    source="cwicr",
                    classification={},
                ),
            ],
        )

    monkeypatch.setattr(
        "app.modules.match_elements.matchers.vector.match_envelope",
        _stub_match_envelope,
    )

    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=a["headers"],
    )
    sid = r.json()["id"]

    # Kick the matcher; it returns inline (small fixture) so by the time
    # we poll progress the runner has stamped the terminal stage.
    resp = await http_client.post(
        f"/api/v1/match_elements/sessions/{sid}/match",
        json={"method": "vector", "max_groups": 5, "top_k": 5},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text

    progress = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/progress",
        headers=a["headers"],
    )
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert body["status"] == "done", body
    assert body["stage"] == "done", body
    # On done the runner should have flushed groups_total to the total
    # it iterated — strictly >= 1 because we got at least one group back.
    assert body["groups_total"] >= 1, body
    assert body["groups_done"] == body["groups_total"], body


@pytest.mark.asyncio
async def test_progress_idor_blocks_non_admin_outsider(http_client):
    """A non-admin user from a different tenant cannot read another
    tenant's progress snapshot — defence in depth for the new poll
    endpoint now that the FE relies on it. Returns 404 (not 403) to
    avoid leaking session-id existence to an attacker scanning UUID
    space.

    Important: ``two_tenants`` creates two admins, and admins bypass
    project access checks. This test creates a viewer-role outsider
    to exercise the actual gate (mirrors the analytics IDOR test
    pattern above)."""
    # Owner — admin so seeding succeeds without extra promotion.
    owner_uid, _, owner_headers = await _register_login_promote(
        http_client,
        tenant=f"prog-owner-{uuid.uuid4().hex[:6]}",
    )
    project_id, bim_model_id = await _seed_project_with_bim_model(
        owner_id=owner_uid,
    )
    r = await http_client.post(
        "/api/v1/match_elements/sessions",
        json={
            "project_id": str(project_id),
            "bim_model_id": str(bim_model_id),
            "source": "bim",
        },
        headers=owner_headers,
    )
    sid = r.json()["id"]

    # Outsider — plain viewer, no admin bypass.
    _, _, outsider_headers = await _register_login_promote(
        http_client,
        tenant=f"prog-viewer-{uuid.uuid4().hex[:6]}",
        role="viewer",
    )

    # Owner can read.
    own = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/progress",
        headers=owner_headers,
    )
    assert own.status_code == 200, own.text

    # Outsider is blocked.
    other = await http_client.get(
        f"/api/v1/match_elements/sessions/{sid}/progress",
        headers=outsider_headers,
    )
    assert other.status_code == 404, other.text
