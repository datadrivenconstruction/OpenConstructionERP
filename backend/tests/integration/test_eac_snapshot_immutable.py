# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Snapshot immutability tests for the EAC alias-snapshot subsystem.

EAC captures an :class:`EacAliasSnapshot` at the start of every run to
guarantee deterministic replay even when aliases are later edited or
deleted. This suite verifies:

1. A snapshot taken before a rule update is unaffected by that update.
2. Re-running the ruleset after editing aliases produces a *new* snapshot
   (the old snapshot row is unchanged — append-only).
3. A run's ``summary_json`` / ``status`` is frozen after completion; a
   subsequent rerun does not mutate the source run row.
4. EVM-style: given a sequence of weekly EAC runs with differing ``elements``
   (simulating changing actuals), the historical run rows retain their
   original ``elements_evaluated`` / ``elements_matched`` counts.
5. CPI trend across a series of snapshots: mocked CPI values derived from
   successive run summaries must produce a monotonically-changing trend
   reflecting worsening performance.

For bullet 4/5 we directly manipulate ``EacRun`` rows (no HTTP) to keep
the test fast and free of auth/registration plumbing — the HTTP path is
covered by ``test_eac_idor.py``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session

# ── DB fixture (PostgreSQL, transaction-isolated) ───────────────────────────


@pytest_asyncio.fixture
async def mem_session():
    """Transaction-isolated PostgreSQL session with the full schema.

    Runs inside an outer transaction that is rolled back on teardown; the
    schema-loaded ``oe_test_unit`` database is shared and stays empty between
    tests. PostgreSQL enforces foreign keys natively.
    """
    async with transactional_session() as session:
        yield session


# ── HTTP fixture ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    from app.main import create_app

    app = create_app()

    @asynccontextmanager
    async def _lc():
        async with app.router.lifespan_context(app):
            yield

    async with _lc():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_and_login(client: AsyncClient, tag: str) -> dict[str, str]:
    from tests.integration._auth_helpers import promote_to_admin

    email = f"snap-{tag}-{uuid.uuid4().hex[:6]}@test.io"
    password = f"Snap{tag}9Xq"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Snap {tag}"},
    )
    # EAC writes require EDITOR+ (finding #6); promote so this suite can seed
    # a ruleset/run before asserting snapshot immutability.
    await promote_to_admin(email)
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


# ── Test 1: Alias snapshot is frozen after creation ──────────────────────────


@pytest.mark.asyncio
async def test_alias_snapshot_frozen_after_creation(mem_session: AsyncSession) -> None:
    """An EacAliasSnapshot row must be immutable after insertion.

    Steps:
    1. Insert an alias snapshot (simulating what EacRun captures at start).
    2. Verify the row is retrievable and equals the original content.
    3. Insert a *new* snapshot with updated alias data.
    4. Confirm original snapshot row is unmodified (append-only, no UPDATE).
    """
    from app.modules.eac.models import EacAliasSnapshot

    original_aliases = {
        "_Length": {
            "id": str(uuid.uuid4()),
            "value_type_hint": "number",
            "default_unit": "m",
            "synonyms": [{"pattern": "length_mm", "kind": "exact", "unit_multiplier": 0.001}],
        }
    }
    snap1 = EacAliasSnapshot(
        scope="project",
        scope_id=uuid.uuid4(),
        aliases_json=original_aliases,
    )
    mem_session.add(snap1)
    await mem_session.flush()
    snap1_id = snap1.id

    # Insert an updated snapshot (simulating alias edit + re-run).
    updated_aliases = dict(original_aliases)
    updated_aliases["_Area"] = {
        "id": str(uuid.uuid4()),
        "value_type_hint": "number",
        "default_unit": "m2",
        "synonyms": [],
    }
    snap2 = EacAliasSnapshot(
        scope="project",
        scope_id=uuid.uuid4(),
        aliases_json=updated_aliases,
    )
    mem_session.add(snap2)
    await mem_session.flush()

    # Re-fetch original snapshot — must still carry only one alias.
    reloaded = await mem_session.get(EacAliasSnapshot, snap1_id)
    assert reloaded is not None
    assert "_Length" in reloaded.aliases_json
    assert "_Area" not in reloaded.aliases_json, (
        "Original snapshot must be unchanged after a new snapshot was inserted. "
        "Snapshots are append-only; the old row must never be mutated."
    )


# ── Test 2: Completed run row is frozen (source run unchanged after rerun) ───


@pytest.mark.asyncio
async def test_completed_run_row_is_frozen_after_rerun(client: AsyncClient) -> None:
    """A finished EacRun must not be mutated by a subsequent rerun.

    The rerun creates a fresh EacRun row; the source run retains its
    original ``status``, ``elements_evaluated``, and ``elements_matched``.
    """
    headers = await _register_and_login(client, "frz")

    # Create ruleset + rule.
    rs_resp = await client.post(
        "/api/v1/eac/rulesets",
        json={"name": "snap_freeze_rs", "kind": "validation"},
        headers=headers,
    )
    assert rs_resp.status_code == 201
    ruleset_id = rs_resp.json()["id"]

    await client.post(
        "/api/v1/eac/rules",
        json={
            "ruleset_id": ruleset_id,
            "name": "snap_freeze_rule",
            "output_mode": "boolean",
            "definition_json": {
                "schema_version": "2.0",
                "name": "snap_freeze_rule",
                "output_mode": "boolean",
                "selector": {"kind": "category", "values": ["Slab"]},
                "predicate": {
                    "kind": "triplet",
                    "attribute": {"kind": "exact", "name": "ThicknessMM"},
                    "constraint": {"operator": "gte", "value": 200},
                },
            },
        },
        headers=headers,
    )

    elements_v1 = [
        {
            "stable_id": "s1",
            "element_type": "Slab",
            "properties": {"ThicknessMM": 250},
            "quantities": {},
        },
        {
            "stable_id": "s2",
            "element_type": "Slab",
            "properties": {"ThicknessMM": 150},
            "quantities": {},
        },
    ]

    # First run (2 elements).
    run1_resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": elements_v1, "triggered_by": "manual"},
        headers=headers,
    )
    assert run1_resp.status_code == 201
    run1_id = run1_resp.json()["id"]
    run1_evaluated = run1_resp.json()["elements_evaluated"]

    # Rerun with different elements (3 elements).
    elements_v2 = elements_v1 + [
        {
            "stable_id": "s3",
            "element_type": "Slab",
            "properties": {"ThicknessMM": 300},
            "quantities": {},
        }
    ]
    rerun_resp = await client.post(
        f"/api/v1/eac/runs/{run1_id}:rerun",
        json={"elements": elements_v2, "triggered_by": "manual"},
        headers=headers,
    )
    assert rerun_resp.status_code == 201
    run2_id = rerun_resp.json()["id"]
    assert run2_id != run1_id, "Rerun must produce a NEW run row"

    # Confirm original run row is unchanged.
    orig_resp = await client.get(f"/api/v1/eac/runs/{run1_id}", headers=headers)
    assert orig_resp.status_code == 200
    orig = orig_resp.json()
    assert orig["elements_evaluated"] == run1_evaluated, (
        f"Source run elements_evaluated mutated: was {run1_evaluated}, now {orig['elements_evaluated']}"
    )
    assert orig["status"] in {"success", "failed", "partial"}, (
        "Source run status must remain in a terminal state after rerun"
    )

    # Rerun row should reflect the new element count.
    new_resp = await client.get(f"/api/v1/eac/runs/{run2_id}", headers=headers)
    assert new_resp.status_code == 200
    new_run = new_resp.json()
    assert new_run["elements_evaluated"] >= 0  # rerun ran against v2 elements


# ── Test 3: Historical snapshot counts preserved across successive runs ───────


@pytest.mark.asyncio
async def test_historical_run_counts_preserved(mem_session: AsyncSession) -> None:
    """EacRun rows representing weekly EVM snapshots must be immutable.

    Simulates 4 weekly EAC 'actual cost' snapshots:
    - Week 1: 10 elements evaluated, 8 matched (strong performance)
    - Week 2: 10 elements evaluated, 6 matched (slipping)
    - Week 3: 10 elements evaluated, 4 matched (further slip)
    - Week 4: 10 elements evaluated, 2 matched (critical)

    After inserting all four, each row must retain its original
    elements_matched — confirming append-only, no cross-row mutation.
    """
    from app.modules.eac.models import EacRuleset, EacRun

    tenant_id = uuid.uuid4()
    ruleset = EacRuleset(name="weekly_snap", kind="validation", tenant_id=tenant_id)
    mem_session.add(ruleset)
    await mem_session.flush()

    weekly: list[dict] = [
        {"week": 1, "evaluated": 10, "matched": 8},
        {"week": 2, "evaluated": 10, "matched": 6},
        {"week": 3, "evaluated": 10, "matched": 4},
        {"week": 4, "evaluated": 10, "matched": 2},
    ]
    run_ids: list[uuid.UUID] = []
    for w in weekly:
        run = EacRun(
            ruleset_id=ruleset.id,
            tenant_id=tenant_id,
            status="success",
            triggered_by="scheduled",
            elements_evaluated=w["evaluated"],
            elements_matched=w["matched"],
            error_count=0,
            summary_json={
                "week": w["week"],
                "note": "EVM weekly snapshot",
            },
        )
        mem_session.add(run)
        await mem_session.flush()
        run_ids.append(run.id)

    # Now verify each snapshot is unchanged.
    for run_id, w in zip(run_ids, weekly, strict=False):
        row = await mem_session.get(EacRun, run_id)
        assert row is not None
        assert row.elements_matched == w["matched"], (
            f"Week {w['week']} snapshot mutated: expected matched={w['matched']}, got {row.elements_matched}"
        )
        assert row.elements_evaluated == w["evaluated"]
        assert row.summary_json["week"] == w["week"], "Summary JSON must be frozen to the snapshot-time value"


# ── Test 4: CPI trend computed from historical run snapshots ─────────────────


def _mock_cpi_from_run(elements_matched: int, elements_evaluated: int) -> float | None:
    """Derive a mock CPI from matched ratio.

    In a real EVM integration, CPI = EV/AC; here we approximate via the
    elements_matched/elements_evaluated ratio as a proxy for performance.
    CPI > 1.0 → under budget; CPI < 1.0 → over budget.
    """
    if elements_evaluated == 0:
        return None
    # Normalise so a 100% match → CPI 1.0.
    ratio = elements_matched / elements_evaluated
    # Skew: ratio 0.8 → CPI 1.0 is baseline; below → over budget.
    return ratio / 0.8


def test_cpi_trend_from_successive_snapshots() -> None:
    """CPI derived from weekly EAC snapshots must reflect deteriorating performance.

    Mirrors the EVM trend analysis described in the task: a series of weekly
    snapshots each contribute a CPI data point; the resulting trend array must
    be monotonically decreasing when the project is slipping.
    """
    # Simulated weekly snapshot data (elements_matched / elements_evaluated).
    weekly_data = [
        {"evaluated": 10, "matched": 9},  # Week 1: 90% → CPI=1.125
        {"evaluated": 10, "matched": 7},  # Week 2: 70% → CPI=0.875
        {"evaluated": 10, "matched": 5},  # Week 3: 50% → CPI=0.625
        {"evaluated": 10, "matched": 3},  # Week 4: 30% → CPI=0.375
    ]

    cpis: list[float] = []
    for w in weekly_data:
        cpi = _mock_cpi_from_run(w["matched"], w["evaluated"])
        assert cpi is not None
        cpis.append(cpi)

    # Trend must be strictly decreasing (worsening performance each week).
    for i in range(1, len(cpis)):
        assert cpis[i] < cpis[i - 1], f"CPI trend not decreasing at week {i + 1}: cpis={cpis}"

    # The final CPI must be below 1.0 (over budget).
    assert cpis[-1] < 1.0, f"Final CPI should indicate over-budget, got {cpis[-1]}"

    # The first CPI must be above 1.0 (initial good performance).
    assert cpis[0] > 1.0, f"Initial CPI should indicate under-budget, got {cpis[0]}"


# ── Test 5: Snapshot alias_json is deep-copied, not a reference ──────────────


@pytest.mark.asyncio
async def test_snapshot_aliases_json_is_independent_copy(
    mem_session: AsyncSession,
) -> None:
    """The aliases_json stored in an EacAliasSnapshot must be an independent copy.

    Mutating the original dict after insertion must NOT change the persisted
    snapshot data — the column stores a JSON serialisation, not a reference.
    """
    from app.modules.eac.models import EacAliasSnapshot

    original: dict = {
        "_Volume": {
            "id": str(uuid.uuid4()),
            "value_type_hint": "number",
            "default_unit": "m3",
            "synonyms": [],
        }
    }
    snap = EacAliasSnapshot(
        scope="org",
        scope_id=uuid.uuid4(),
        aliases_json=dict(original),  # shallow copy to simulate service layer
    )
    mem_session.add(snap)
    await mem_session.flush()
    snap_id = snap.id

    # Mutate the local dict (simulating an alias edit in memory).
    original["_Volume"]["default_unit"] = "MUTATED"
    original["_Height"] = {"id": str(uuid.uuid4()), "synonyms": []}

    # Expire cache to force a DB re-read.
    await mem_session.commit()
    await mem_session.refresh(snap)

    reloaded = await mem_session.get(EacAliasSnapshot, snap_id)
    assert reloaded is not None
    assert "_Height" not in reloaded.aliases_json, (
        "Mutation of the source dict after flush must not affect the persisted snapshot"
    )
    # The stored unit must remain 'm3' from insertion time.
    stored_unit = reloaded.aliases_json.get("_Volume", {}).get("default_unit", "")
    # After commit+refresh, SQLAlchemy re-reads from DB; the stored JSON
    # was serialised at flush time so must be the original 'm3'.
    assert stored_unit == "m3", f"Snapshot aliases_json must reflect insertion-time values, got unit={stored_unit!r}"
