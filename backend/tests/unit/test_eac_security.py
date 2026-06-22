# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Security + correctness hardening tests for the EAC v2 module.

Covers the v4.3 Round-3 Wave A audit findings:

1. ``rule_id`` FK column on ``oe_eac_run_result_item`` has a covering
   index (``ix_eac_run_result_rule_id``). Without it, queries that
   filter by ``rule_id`` alone fall through to a seq-scan on a hot
   100k-row table.
2. Formula sandbox refuses obvious dunder / eval-style escapes — the
   safe-eval layer is what stands between user-authored rules and
   arbitrary Python execution.
3. ``POST /rulesets/{id}:run`` is idempotent: re-posting the same
   ``Idempotency-Key`` for the same ``(tenant, ruleset)`` returns the
   prior run instead of starting a duplicate execution.
4. ``GET /runs/{id}/results`` blocks cross-tenant access (IDOR sweep) —
   a run from tenant B is 404 to tenant A, even with a guessed UUID.
5. Audit trail: every accepted ``POST .../rulesets:run`` writes one
   ``ActivityLog`` row tagged ``entity_type='eac_run'``.
6. Idempotency-key auto-derivation is stable across dict-key ordering
   so semantically identical inputs collapse to one run.

These are pure unit tests — the model-level checks use SQLAlchemy
metadata directly; the HTTP-level checks drive the real FastAPI app
through an in-process ``ASGITransport`` client, matching the pattern
used by ``tests/integration/eac/test_runs_endpoint.py``. They run
against the session PostgreSQL cluster provisioned by
``backend/tests/conftest.py``; the engine-level isolation test uses the
``transactional_session`` helper, which wraps each test in an outer
transaction that is rolled back on teardown.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest

# simpleeval (the sandboxed formula evaluator) is not declared in pyproject and
# is not a transitive of any base/dev dependency, so a [dev]-only install (the
# CI test job) does not have it. The eac safe_eval module imports it at module
# top, so guard the whole module so it skips cleanly instead of erroring during
# collection.
pytest.importorskip("simpleeval", reason="simpleeval is not in the [dev] install")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Register EAC + audit tables before any test runs.
import app.modules.eac.models  # noqa: F401
from app.core.audit_log import ActivityLog
from app.modules.eac.engine.idempotency import compute_idempotency_key
from app.modules.eac.engine.safe_eval import (
    FormulaUnsafeError,
    evaluate_formula,
    parse_formula,
)
from app.modules.eac.models import EacRun, EacRunResultItem
from tests._pg import transactional_session

# ── Test 1: FK index on rule_id (Round-3 Wave A finding) ────────────────


def test_eac_run_result_item_has_rule_id_index() -> None:
    """The ``rule_id`` FK column must have a dedicated covering index.

    The existing ``ix_eac_run_result_run_rule`` is leftmost-prefixed on
    ``run_id`` so queries that filter by ``rule_id`` alone cannot use
    it. ``ix_eac_run_result_rule_id`` is the standalone FK index added
    by v3099 (RFC v4.3 Round-3 Wave A).
    """
    indexes = {ix.name: ix for ix in EacRunResultItem.__table__.indexes}

    assert "ix_eac_run_result_rule_id" in indexes, (
        "Standalone rule_id FK index missing — v4.3 Round-3 Wave A "
        f"finding regressed. Indexes present: {sorted(indexes)}"
    )

    idx = indexes["ix_eac_run_result_rule_id"]
    columns = [c.name for c in idx.columns]
    assert columns == ["rule_id"], f"ix_eac_run_result_rule_id must cover exactly ['rule_id'], got {columns}"


# ── Test 2: Formula sandbox rejects dunder + eval escapes ───────────────


def test_safe_eval_rejects_dunder_and_eval_escapes() -> None:
    """Rule-authored formulas must NOT be able to escape the sandbox.

    A user-authored rule is a templated formula string; if the sandbox
    accepted ``__class__`` traversal or ``eval(...)`` calls, every
    multi-tenant install would have an arbitrary-code-execution
    surface. We re-verify the sandbox here (defence in depth on top of
    the engine's own ``test_safe_eval`` suite). The full ``parse +
    scan + eval`` pipeline lives in ``evaluate_formula`` — that's the
    function the executor actually calls, so that's what we attack.
    """
    # Dunder attribute access — classic Python sandbox escape.
    with pytest.raises(FormulaUnsafeError):
        evaluate_formula("(1).__class__", {})

    # Direct call to eval()/exec()/compile()/__import__()/open().
    for malicious in (
        "eval('1+1')",
        "exec('x=1')",
        "compile('x', 'f', 'exec')",
        "__import__('os')",
        "open('/etc/passwd')",
    ):
        with pytest.raises(FormulaUnsafeError):
            evaluate_formula(malicious, {})

    # Comprehensions are blocked (sandbox-escape vector + no business need).
    with pytest.raises(FormulaUnsafeError):
        evaluate_formula("[x for x in [1,2,3]]", {})

    # Lambdas are blocked.
    with pytest.raises(FormulaUnsafeError):
        evaluate_formula("lambda x: x", {})

    # Sanity — parse_formula on its own does not reject (it's a pure AST
    # parse), but the unsafe scan is invoked by evaluate_formula and the
    # validator. So the legitimate-formula round-trip must succeed.
    parsed = parse_formula("ROUND(Volume * 2400, 2)")
    assert parsed is not None
    result = evaluate_formula("ROUND(Volume * 2400, 2)", {"Volume": 6.0})
    assert result == 14400.0


# ── Test 3: Idempotency-key auto-derivation is dict-order stable ────────


def test_idempotency_key_stable_across_dict_ordering() -> None:
    """Two semantically-identical input lists must produce the same key.

    A naive ``json.dumps`` would hash dict-key insertion order, leading
    to spurious "new" runs whenever an upstream BIM exporter re-orders
    properties. Catching this at the unit level keeps the
    ``POST /rulesets/{id}:run`` idempotency contract honest.
    """
    from datetime import UTC, datetime

    ruleset_id = uuid.uuid4()
    ts = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)

    elements_a = [
        {
            "stable_id": "e1",
            "properties": {"Mark": "A1", "FireRating": "F90", "Thickness": 200},
        },
        {
            "stable_id": "e2",
            "properties": {"Mark": "A2", "FireRating": "F30"},
        },
    ]
    # Same elements, keys re-shuffled, list re-shuffled.
    elements_b = [
        {
            "properties": {"FireRating": "F30", "Mark": "A2"},
            "stable_id": "e2",
        },
        {
            "stable_id": "e1",
            "properties": {"Thickness": 200, "Mark": "A1", "FireRating": "F90"},
        },
    ]

    key_a = compute_idempotency_key(
        ruleset_id=ruleset_id,
        ruleset_updated_at=ts,
        elements=elements_a,
    )
    key_b = compute_idempotency_key(
        ruleset_id=ruleset_id,
        ruleset_updated_at=ts,
        elements=elements_b,
    )
    assert key_a == key_b, "Idempotency key must be stable across dict ordering"
    assert key_a.startswith("auto:"), "Auto-derived key must carry the auto: prefix"

    # And a different element-set must produce a different key.
    elements_c = elements_a + [{"stable_id": "e3", "properties": {"Mark": "A3"}}]
    key_c = compute_idempotency_key(
        ruleset_id=ruleset_id,
        ruleset_updated_at=ts,
        elements=elements_c,
    )
    assert key_c != key_a, "Adding an element must change the key"


# ── HTTP fixtures (mirror tests/integration/eac/test_runs_endpoint) ─────


@pytest_asyncio.fixture
async def client():
    """Real FastAPI app driven through ASGITransport.

    ``conftest.py`` has already pointed DATABASE_URL at the session
    PostgreSQL cluster, so the app boots against that fresh DB.
    """
    from app.main import create_app

    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_user(client, suffix: str) -> dict[str, str]:
    """Create a brand-new user account and return its Authorization header."""
    from tests.integration._auth_helpers import promote_to_admin

    email = f"eac-sec-{suffix}@test.io"
    password = f"EacSec{suffix}9X"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"EAC sec {suffix}"},
    )
    # EAC writes/runs require EDITOR+ (finding #6); promote so the security
    # suite can seed rulesets/rules and exercise the run + audit-log path.
    await promote_to_admin(email)
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


async def _seed_ruleset_with_rule(client, headers: dict[str, str]) -> tuple[str, str]:
    """Create a ruleset + one boolean rule, return (ruleset_id, rule_id)."""
    rs_resp = await client.post(
        "/api/v1/eac/rulesets",
        json={"name": "sec_test_rs", "kind": "validation"},
        headers=headers,
    )
    assert rs_resp.status_code == 201, rs_resp.text
    ruleset_id = rs_resp.json()["id"]

    rule_resp = await client.post(
        "/api/v1/eac/rules",
        json={
            "ruleset_id": ruleset_id,
            "name": "sec_rule",
            "output_mode": "boolean",
            "definition_json": {
                "schema_version": "2.0",
                "name": "sec_rule",
                "output_mode": "boolean",
                "selector": {"kind": "category", "values": ["Wall"]},
                "predicate": {
                    "kind": "triplet",
                    "attribute": {"kind": "exact", "name": "FireRating"},
                    "constraint": {"operator": "eq", "value": "F90"},
                },
            },
        },
        headers=headers,
    )
    assert rule_resp.status_code == 201, rule_resp.text
    return ruleset_id, rule_resp.json()["id"]


def _walls() -> list[dict]:
    return [
        {
            "stable_id": "wall_001",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "L1",
            "discipline": "ARC",
            "properties": {"FireRating": "F90"},
            "quantities": {"area_m2": 25.0, "volume_m3": 6.0},
        },
        {
            "stable_id": "wall_002",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "L1",
            "discipline": "ARC",
            "properties": {"FireRating": "F30"},
            "quantities": {"area_m2": 12.5, "volume_m3": 3.0},
        },
    ]


# ── Test 4: Idempotent run (header-driven dedup) ────────────────────────


@pytest.mark.asyncio
async def test_run_ruleset_dedups_on_idempotency_key_header(client) -> None:
    """Re-posting the same Idempotency-Key returns the prior run row.

    Without this, a webhook retry or a double-click submit creates a
    duplicate ``EacRun`` (and N duplicate ``EacRunResultItem`` rows)
    that the user then sees as garbage. The contract is:

    1. First POST: creates a run, returns its id.
    2. Second POST with the same key: returns the SAME id, never
       starts a second execution.
    """
    headers = await _register_user(client, "idem")
    ruleset_id, _rule_id = await _seed_ruleset_with_rule(client, headers)

    key = "client-supplied-test-key-001"
    first = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls(), "triggered_by": "manual"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls(), "triggered_by": "manual"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first_id, (
        "Same Idempotency-Key must return the prior run id, not start a "
        f"duplicate. Got: {first_id} vs {second.json()['id']}"
    )

    # And a third POST with a DIFFERENT key for the same payload must
    # start a fresh run (header overrides auto-derived dedup).
    third = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls(), "triggered_by": "manual"},
        headers={**headers, "Idempotency-Key": "client-supplied-test-key-002"},
    )
    assert third.status_code == 201
    assert third.json()["id"] != first_id


# ── Test 5: Cross-tenant IDOR on engine.status / cancel / diff ──────────


@pytest.mark.asyncio
async def test_cross_tenant_engine_access_is_blocked() -> None:
    """A run owned by tenant B must be invisible to tenant A at the
    engine API layer — ``status()`` returns ``None`` (router maps to
    404), ``cancel()`` returns ``False`` (router maps to 404), and
    ``diff()`` raises ``ExecutionError`` (router maps to 422).

    The router-level tenant check is a thin wrapper; the engine
    functions hold the actual contract. Driving the engine directly
    keeps this test free of the HTTP auth/registration plumbing — a
    pure tenant-isolation check on the seam that any future API
    surface (REST, GraphQL, Celery worker) must continue to honour.
    """
    from app.core.audit_log import ActivityLog  # noqa: F401 — register table
    from app.modules.eac.engine import api as engine_api
    from app.modules.eac.engine.executor import ExecutionError
    from app.modules.eac.models import EacRuleset, EacRun

    # The whole check runs against a single session inside a transaction that
    # is rolled back on teardown (PostgreSQL, full schema preloaded — no
    # create_all needed). FKs are enforced natively by PostgreSQL.
    async with transactional_session() as session:
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        # Tenant B owns a ruleset + run.
        ruleset_b = EacRuleset(
            name="b_set",
            kind="validation",
            tenant_id=tenant_b,
        )
        session.add(ruleset_b)
        await session.flush()

        run_b = EacRun(
            ruleset_id=ruleset_b.id,
            tenant_id=tenant_b,
            status="success",
            triggered_by="manual",
            elements_evaluated=10,
            elements_matched=4,
            error_count=0,
        )
        session.add(run_b)
        await session.flush()

        # Tenant A asks the engine for B's run status — None.
        snapshot_for_a = await engine_api.status(
            session,
            run_b.id,
            tenant_id=tenant_a,
        )
        assert snapshot_for_a is None, f"Cross-tenant status() must return None (router 404). Got: {snapshot_for_a!r}"

        # Cancel as tenant A must refuse.
        accepted = await engine_api.cancel(
            session,
            run_b.id,
            tenant_id=tenant_a,
        )
        assert accepted is False, f"Cross-tenant cancel() must return False (router 404). Got: {accepted!r}"

        # Diff between two B-owned runs must be refused under A.
        run_b2 = EacRun(
            ruleset_id=ruleset_b.id,
            tenant_id=tenant_b,
            status="success",
            triggered_by="manual",
            elements_evaluated=10,
            elements_matched=5,
            error_count=0,
        )
        session.add(run_b2)
        await session.flush()

        with pytest.raises(ExecutionError):
            await engine_api.diff(
                session,
                run_b.id,
                run_b2.id,
                tenant_id=tenant_a,
            )

        # And list_runs scoped to tenant A must NOT see B's runs.
        visible_to_a = await engine_api.list_runs(
            session,
            tenant_id=tenant_a,
        )
        assert all(r.id not in {run_b.id, run_b2.id} for r in visible_to_a), (
            "Cross-tenant list_runs leak: tenant A saw tenant B's runs"
        )

        # Sanity — tenant B sees its own run.
        own_snapshot = await engine_api.status(
            session,
            run_b.id,
            tenant_id=tenant_b,
        )
        assert own_snapshot is not None
        assert own_snapshot.run_id == run_b.id


# ── Test 6: Audit log written on every accepted run trigger ─────────────


@pytest.mark.asyncio
async def test_run_trigger_writes_audit_log_row(client) -> None:
    """Every ``POST .../rulesets/{id}:run`` that creates a fresh run
    must persist exactly one ``ActivityLog`` row keyed on
    ``entity_type='eac_run'``.

    Without this, "who ran what when" is undiscoverable. The audit
    table is what FIDIC / ISO 9001 dispute timelines reproduce off of.
    """
    headers = await _register_user(client, "audit")
    ruleset_id, _rule_id = await _seed_ruleset_with_rule(client, headers)

    resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls(), "triggered_by": "manual"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    # Inspect the activity log via a direct DB read — the app's audit
    # endpoint is not in scope for this hardening pass.
    from app.database import async_session_factory

    async with async_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type == "eac_run")
                    .where(ActivityLog.entity_id == run_id)
                )
            ).all()
        )

    assert len(rows) >= 1, f"Expected at least one ActivityLog row for eac_run {run_id}, got {len(rows)}"
    triggered = next((r for r in rows if r.action == "run_triggered"), None)
    assert triggered is not None, (
        f"Expected an action='run_triggered' ActivityLog row for the new run; saw actions {[r.action for r in rows]}"
    )
    assert triggered.actor_id is not None, "Audit log row must record the actor (user_id) — got NULL"
    assert "ruleset_id" in (triggered.metadata_ or {}), "Audit metadata must capture ruleset_id"


# ── Sanity: the new model column is wired to the DB ─────────────────────


def test_eac_run_carries_idempotency_key_column() -> None:
    """The ``idempotency_key`` column must exist on the ORM model.

    Belt-and-braces — without it the runner's dedup write silently
    drops the value and the next-call dedup query returns nothing.
    """
    columns = {c.name for c in EacRun.__table__.columns}
    assert "idempotency_key" in columns
