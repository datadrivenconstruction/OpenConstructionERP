"""Integration tests for the Wave A4 clash endpoints.

Covers:
    * GET  /runs/{rid}/clusters         — cluster chip payload
    * GET  /runs/{rid}/rule-suggestions — FP-derived rule proposals
    * POST /runs/{rid}/apply-rule-suggestion — rule append + re-evaluate
    * PATCH /runs/{rid}/rules            — size-cap of the persisted list
    * GET  /runs/{rid}/kpi               — dashboard projection shape

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported. The engine is
monkey-patched at the geometry-loader seam (same pattern as
``test_clash_triage_delta.py``) so we get real engine output without
needing a GLB asset.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-a4-"))
_TMP_DB = _TMP_DIR / "clash_a4.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App / auth / project fixtures ─────────────────────────────────────────


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


async def _register_admin(client: AsyncClient) -> dict[str, str]:
    """Register a fresh admin user, return the auth header."""
    from ._auth_helpers import promote_to_admin

    tag = uuid.uuid4().hex[:8]
    email = f"clash-a4-{tag}@test.io"
    password = f"ClashA4Test{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Clash A4 Tester {tag}",
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
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    return await _register_admin(client)


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Clash A4 project", "description": "wave A4 endpoint suite"},
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Engine seeding helpers ────────────────────────────────────────────────


async def _seed_run(
    project_id_: str,
    element_specs: list[
        tuple[
            str,  # stable id suffix
            tuple[float, float, float],  # box origin
            tuple[float, float, float],  # box size
            str,  # discipline
        ]
    ],
    *,
    monkeypatch,
) -> tuple[str, str, list[tuple[str, str]]]:
    """Build N elements then run cross-discipline detection on them.

    Each spec is ``(suffix, origin, size, discipline)`` — the caller
    drops boxes wherever they want and the engine pairs them up
    (cross-discipline mode), producing one clash per cross pair that
    interpenetrates beyond the 0.01 m tolerance. Returns
    ``(model_id, run_id, [(result_id, signature), …])``.
    """
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.clash.schemas import ClashRunCreate
    from app.modules.clash.service import ClashService
    from tests.unit.test_clash_narrow_phase import _box_geom

    async with async_session_factory() as session:
        model = BIMModel(
            project_id=uuid.UUID(project_id_),
            name="A4 Test Model",
            status="ready",
        )
        session.add(model)
        await session.flush()
        model_id = str(model.id)

        elements: list[tuple] = []
        geoms_by_eid: dict[str, object] = {}
        tag = uuid.uuid4().hex[:6]
        for suffix, origin, size, disc in element_specs:
            g = _box_geom(f"{suffix}-{tag}", origin, size, disc)
            el = BIMElement(
                model_id=model.id,
                stable_id=g.stable_id,
                name=g.name,
                element_type="Generic",
                discipline=g.discipline,
                bounding_box={
                    "min_x": g.aabb[0],
                    "min_y": g.aabb[1],
                    "min_z": g.aabb[2],
                    "max_x": g.aabb[3],
                    "max_y": g.aabb[4],
                    "max_z": g.aabb[5],
                },
            )
            session.add(el)
            elements.append((el, g))
        await session.flush()
        for el, g in elements:
            geoms_by_eid[str(el.id)] = g

        async def _fake_load(self, model_ids):  # noqa: ANN001, ARG001
            return dict(geoms_by_eid)

        monkeypatch.setattr(ClashService, "_load_geometry", _fake_load)

        svc = ClashService(session)
        run = await svc.create_run(
            uuid.UUID(project_id_),
            ClashRunCreate(
                model_ids=[model.id],
                tolerance_m=0.01,
                mode="cross_discipline",
                carry_forward=False,
            ),
            str(uuid.uuid4()),
        )
        await session.commit()
        rows, _ = await svc.repo.list_results(run.id, limit=500)
        results = [(str(r.id), r.signature) for r in rows]
        return model_id, str(run.id), results


def _packed_cluster_specs(base_x: float = 0.0) -> list[tuple]:
    """Two cross-discipline clash pairs whose centroids land in one cluster.

    Two Struc + Mech pairs sit at the same Y plane but only 0.2 m apart
    on Y — their clash centroids end up well within DBSCAN's
    ``eps_m=0.6 m`` neighbourhood, so the cluster pass groups them
    into a single cluster of size 2 (= ``min_samples``). Pair geometry
    is the classic "two cubes overlapping 0.3 m on X" the unit tests
    use, which the engine reliably classifies as a hard clash.
    """
    return [
        # Pair A — Y=0.
        ("S0", (base_x, 0.0, 0.0), (1.0, 1.0, 1.0), "Structural"),
        ("M0", (base_x + 0.7, 0.0, 0.0), (1.0, 1.0, 1.0), "Mechanical"),
        # Pair B — Y=0.2 (well below DBSCAN eps_m=0.6).
        ("S1", (base_x, 0.2, 0.0), (1.0, 1.0, 1.0), "Structural"),
        ("M1", (base_x + 0.7, 0.2, 0.0), (1.0, 1.0, 1.0), "Mechanical"),
    ]


def _separated_pair_specs(n_pairs: int, base_x: float, da: str = "Structural", db: str = "Mechanical") -> list[tuple]:
    """N well-separated (A, B) cross-discipline pairs.

    Pairs are 10 m apart on Y and ``i * 100 m`` apart on X so each pair
    yields exactly one cross-discipline clash with no cross-pair
    contamination. Used by the rule-suggestion / KPI / PATCH tests
    where cluster shape is irrelevant.
    """
    out: list[tuple] = []
    for i in range(n_pairs):
        ox = base_x + i * 100.0
        oy = i * 10.0
        out.append((f"A{i}", (ox, oy, 0.0), (1.0, 1.0, 1.0), da))
        out.append((f"B{i}", (ox + 0.7, oy, 0.0), (1.0, 1.0, 1.0), db))
    return out


# ── 1. Clusters endpoint ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clusters_endpoint_returns_persisted_clusters(client: AsyncClient, auth, project_id, monkeypatch):
    """Engine produces clusters; endpoint surfaces them with shape + size."""
    _model_id, run_id, results = await _seed_run(
        project_id,
        _packed_cluster_specs(base_x=0.0),
        monkeypatch=monkeypatch,
    )
    # Two pairs packed tight on Y → four cross-discipline clashes (Sx ×
    # My for x,y in {0,1}), all centroids within 0.6 m of one another →
    # DBSCAN groups them into one cluster of size 4.
    assert len(results) == 4

    resp = await client.get(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/clusters",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    clusters = resp.json()
    assert isinstance(clusters, list)
    assert len(clusters) == 1
    c = clusters[0]
    assert isinstance(c["cluster_id"], int)
    assert c["cluster_id"] >= 1
    assert c["size"] == 4
    assert isinstance(c["label"], str)
    assert c["label"]
    assert set(c["dominant_disciplines"]) == {"Structural", "Mechanical"}


# ── 2. Rule suggestions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_suggestions_surfaced_from_fp_history(client: AsyncClient, auth, project_id, monkeypatch):
    """Three FPs on the same pair → one rule suggestion."""
    _model_id, run_id, results = await _seed_run(
        project_id,
        _separated_pair_specs(n_pairs=4, base_x=1000.0),
        monkeypatch=monkeypatch,
    )
    assert len(results) == 4
    # Mark 3 of the 4 clashes as ignored — that's the FP signal.
    for rid, _sig in results[:3]:
        patch = await client.patch(
            f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{rid}",
            json={"status": "ignored"},
            headers=auth,
        )
        assert patch.status_code == 200, patch.text

    resp = await client.get(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/rule-suggestions",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    sug = resp.json()
    assert isinstance(sug, list)
    assert len(sug) == 1
    item = sug[0]
    assert item["fp_count"] == 3
    assert item["rule"] is not None
    pair = {item["rule"]["discipline_a"], item["rule"]["discipline_b"]}
    assert pair == {"Structural", "Mechanical"}
    assert item["rule"]["tolerance_m"] > 0.0
    assert isinstance(item["reason"], str)
    assert item["reason"]


# ── 3. Apply rule suggestion ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_rule_suggestion_modifies_run_and_reevaluates(client: AsyncClient, auth, project_id, monkeypatch):
    """Apply suggestion → run.rules grows + sub-tolerance clashes flip to ignored."""
    _model_id, run_id, results = await _seed_run(
        project_id,
        _separated_pair_specs(n_pairs=3, base_x=2000.0),
        monkeypatch=monkeypatch,
    )
    # Sanity: every clash is currently a hard Structural × Mechanical with
    # measured penetration ≈ 0.30 m (>> the run-wide tolerance of 0.01 m).
    assert len(results) == 3

    # Apply a generous rule (tolerance=0.5 m) — all 3 hard clashes (each
    # ~0.30 m deep) should now sit ≤ tolerance → flipped to ignored.
    apply = await client.post(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/apply-rule-suggestion",
        json={
            "discipline_a": "Structural",
            "discipline_b": "Mechanical",
            "tolerance_m": 0.5,
        },
        headers=auth,
    )
    assert apply.status_code == 200, apply.text
    body = apply.json()
    assert body["rule_added"] is True
    assert body["results_affected"] == 3

    # Inspect the persisted rule list.
    rules = await client.get(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/rules",
        headers=auth,
    )
    assert rules.status_code == 200, rules.text
    rules_body = rules.json()
    assert len(rules_body) == 1
    assert {rules_body[0]["discipline_a"], rules_body[0]["discipline_b"]} == {
        "Structural",
        "Mechanical",
    }
    assert rules_body[0]["tolerance_m"] == 0.5
    assert rules_body[0]["enabled"] is True

    # A second apply for the same pair → no duplicate rule, but the
    # re-evaluation pass is now a no-op (all three already ignored).
    apply2 = await client.post(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/apply-rule-suggestion",
        json={
            "discipline_a": "Structural",
            "discipline_b": "Mechanical",
            "tolerance_m": 0.5,
        },
        headers=auth,
    )
    assert apply2.status_code == 200, apply2.text
    body2 = apply2.json()
    assert body2["rule_added"] is False
    assert body2["results_affected"] == 0


# ── 4. PATCH rules — size cap ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_rules_enforces_size_cap(client: AsyncClient, auth, project_id, monkeypatch):
    """Pydantic ``max_length=500`` rejects oversized payloads with 422."""
    _model_id, run_id, _results = await _seed_run(
        project_id,
        _separated_pair_specs(n_pairs=2, base_x=3000.0),
        monkeypatch=monkeypatch,
    )
    too_many = [
        {
            "id": f"rule-{i}",
            "discipline_a": "Structural",
            "discipline_b": "Mechanical",
            "tolerance_m": 0.05,
            "severity_override": None,
            "enabled": True,
        }
        for i in range(501)
    ]
    resp = await client.patch(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/rules",
        json={"rules": too_many},
        headers=auth,
    )
    assert resp.status_code == 422, resp.text

    # Exactly-at-cap (500) is accepted — and round-trips intact.
    at_cap = too_many[:500]
    ok = await client.patch(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/rules",
        json={"rules": at_cap},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()) == 500

    # An empty list also round-trips (clearing the rule set is supported).
    cleared = await client.patch(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/rules",
        json={"rules": []},
        headers=auth,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == []


# ── 5. KPI endpoint shape ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kpi_endpoint_returns_aggregated_dashboard_payload(client: AsyncClient, auth, project_id, monkeypatch):
    """KPI endpoint shape: totals, histograms, top pairs, MTTR slot."""
    _model_id, run_id, results = await _seed_run(
        project_id,
        _separated_pair_specs(n_pairs=3, base_x=4000.0),
        monkeypatch=monkeypatch,
    )
    assert len(results) == 3

    # Resolve one clash so MTTR has a sample.
    patch = await client.patch(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/results/{results[0][0]}",
        json={"status": "resolved"},
        headers=auth,
    )
    assert patch.status_code == 200, patch.text

    resp = await client.get(
        f"/api/v1/clash/projects/{project_id}/runs/{run_id}/kpi",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Shape — every documented field present.
    assert body["total"] == 3
    assert isinstance(body["by_status"], dict)
    assert isinstance(body["by_severity"], dict)
    assert isinstance(body["by_type"], dict)
    assert isinstance(body["by_discipline_pair"], list)
    assert isinstance(body["top_clashing_pairs"], list)

    # Status histogram reflects the resolve we just did.
    assert body["by_status"].get("resolved", 0) == 1
    # Two of the three rows are still 'new'.
    assert body["by_status"].get("new", 0) == 2

    # The single pair (Structural × Mechanical) tops the chart.
    assert body["top_clashing_pairs"], "top_clashing_pairs should be non-empty"
    top = body["top_clashing_pairs"][0]
    assert {top["a"], top["b"]} == {"Structural", "Mechanical"}
    assert top["count"] == 3
    assert 0.0 <= top["open_share"] <= 1.0

    # MTTR is a non-negative float (we just resolved a row).
    assert body["mttr_hours"] is not None
    assert body["mttr_hours"] >= 0.0
