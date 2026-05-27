# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for :meth:`ClashService.bulk_suppress`.

Pin the contract:

* empty ``issue_ids`` → zero-counts envelope, no DB write
* mixed authorized / unauthorized ids → only the project-scoped subset
  flips to ``ignored``; the rest report back in ``skipped_ids``
* idempotent re-suppression → no duplicate ``ClashSuppression`` rows;
  the reason is updated in place
* audit log: every member :class:`ClashResult` of a suppressed issue
  gains a ``suppression`` history entry
* error rollback: a flush failure abandons every change above (atomic)

Same per-test SQLite isolation pattern as ``test_clash_suppressions.py``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.clash.models import (
    ClashIssue,
    ClashResult,
    ClashRun,
    ClashSuppression,
)
from app.modules.clash.service import (
    ClashService,
    _compute_signature_hash,
)


def _register_models() -> None:
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.clash.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-clash-bulksup-")) / "test.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"bulksup-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Bulk Suppressor",
        )
        s.add(owner)
        await s.flush()
        p_a = Project(
            id=uuid.uuid4(),
            name="Project A",
            owner_id=owner.id,
            currency="EUR",
        )
        p_b = Project(
            id=uuid.uuid4(),
            name="Project B (cross-tenant)",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add_all([p_a, p_b])
        await s.commit()
        s.info["project_a"] = p_a.id
        s.info["project_b"] = p_b.id
        s.info["owner_id"] = str(owner.id)
        yield s
    await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_run(project_id: uuid.UUID, name: str = "run") -> ClashRun:
    return ClashRun(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        model_ids=[],
        clash_type="hard",
        tolerance_m=0.01,
        clearance_m=0.0,
        mode="cross_discipline",
        status="completed",
        element_count=0,
        total_clashes=0,
        summary={},
        rules=[],
        spatial_grid_mm=500,
        created_by="tester",
    )


def _make_clash(run: ClashRun, *, a: str, b: str) -> ClashResult:
    sig, quality = _compute_signature_hash(
        a_guid=a,
        b_guid=b,
        centroid=(1.0, 2.0, 3.0),
        clash_type="hard",
        grid_mm=run.spatial_grid_mm,
    )
    return ClashResult(
        id=uuid.uuid4(),
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a,
        b_stable_id=b,
        a_name=a,
        b_name=b,
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=1.0,
        cy=2.0,
        cz=3.0,
        status="new",
        severity="medium",
        signature=sig[:16],
        signature_hash=sig,
        signature_quality=quality,
        tolerance_at_signature_time_mm=run.tolerance_m * 1000.0,
    )


async def _seed_issue(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    a: str,
    b: str,
    name: str = "r",
) -> tuple[ClashIssue, str]:
    """Run the smart-issue upsert end-to-end. Returns ``(issue, sig)``."""
    run = _make_run(project_id, name=name)
    session.add(run)
    await session.flush()
    row = _make_clash(run, a=a, b=b)
    session.add(row)
    await session.flush()
    svc = ClashService(session)
    await svc.upsert_clash_with_signature(run, row)
    await svc.finalize_run(run)
    issue = await svc.repo.get_issue_by_signature(project_id, row.signature_hash)
    assert issue is not None
    return issue, row.signature_hash


# ── 1. Empty input ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_suppress_empty_list_is_noop(session: AsyncSession) -> None:
    """Empty ``issue_ids`` → zero-counts envelope, no DB write."""
    project_id = session.info["project_a"]
    svc = ClashService(session)
    out = await svc.bulk_suppress(project_id, [], "reason", None)
    assert out == {
        "suppressed_ids": [],
        "skipped_ids": [],
        "suppressed_count": 0,
        "skipped_count": 0,
    }
    # No suppression rows were created.
    rows = (await session.execute(select(ClashSuppression))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_bulk_suppress_rejects_empty_reason(session: AsyncSession) -> None:
    """Empty reason raises 422 — same gate as the single-issue path."""
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.bulk_suppress(project_id, [uuid.uuid4()], "  ", None)
    assert exc.value.status_code == 422


# ── 2. Mixed authorized / unauthorized ──────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_suppress_mixed_authorized_and_unauthorized(
    session: AsyncSession,
) -> None:
    """Cross-tenant issue ids are dropped + reported in ``skipped_ids``."""
    a_id = session.info["project_a"]
    b_id = session.info["project_b"]
    issue_a1, _ = await _seed_issue(session, a_id, a="A1", b="B1", name="r-a1")
    issue_a2, _ = await _seed_issue(session, a_id, a="A2", b="B2", name="r-a2")
    issue_b, _ = await _seed_issue(session, b_id, a="X", b="Y", name="r-b")
    bogus = uuid.uuid4()

    svc = ClashService(session)
    out = await svc.bulk_suppress(
        a_id,
        [issue_a1.id, issue_a2.id, issue_b.id, bogus],
        reason="bulk-suppress",
        user_id=session.info["owner_id"],
    )

    assert out["suppressed_count"] == 2
    assert set(out["suppressed_ids"]) == {issue_a1.id, issue_a2.id}
    assert set(out["skipped_ids"]) == {issue_b.id, bogus}

    # Project-A issues now ``ignored``; project-B issue untouched.
    a1 = await svc.repo.get_issue(a_id, issue_a1.id)
    a2 = await svc.repo.get_issue(a_id, issue_a2.id)
    b = await svc.repo.get_issue(b_id, issue_b.id)
    assert a1.status == "ignored"
    assert a2.status == "ignored"
    assert b.status in ("new", "persisted")

    # Two ``ClashSuppression`` rows for project A — one per signature.
    a_sigs = await svc.repo.suppressed_signatures_for_project(a_id)
    b_sigs = await svc.repo.suppressed_signatures_for_project(b_id)
    assert len(a_sigs) == 2
    assert b_sigs == set()


# ── 3. Idempotent re-suppression ────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_suppress_idempotent_updates_reason(
    session: AsyncSession,
) -> None:
    """Re-suppressing the same issue updates the reason — no dup rows."""
    project_id = session.info["project_a"]
    issue, sig = await _seed_issue(session, project_id, a="A", b="B")
    svc = ClashService(session)

    out1 = await svc.bulk_suppress(project_id, [issue.id], "first reason", None)
    out2 = await svc.bulk_suppress(project_id, [issue.id], "second reason", None)
    assert out1["suppressed_count"] == 1
    assert out2["suppressed_count"] == 1

    # Exactly one suppression row, reason updated to the most recent value.
    rows = (
        (
            await session.execute(
                select(ClashSuppression).where(
                    ClashSuppression.project_id == project_id,
                    ClashSuppression.signature_hash == sig,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].reason == "second reason"


@pytest.mark.asyncio
async def test_bulk_suppress_deduplicates_repeated_ids_in_input(
    session: AsyncSession,
) -> None:
    """Repeated issue ids in input are de-duplicated — single audit entry."""
    project_id = session.info["project_a"]
    issue, _sig = await _seed_issue(session, project_id, a="A", b="B")
    svc = ClashService(session)

    out = await svc.bulk_suppress(project_id, [issue.id, issue.id, issue.id], "x", None)
    # The id is reported once, not three times.
    assert out["suppressed_ids"] == [issue.id]
    assert out["suppressed_count"] == 1

    # History on the underlying result row was appended exactly once.
    stmt = select(ClashResult).where(ClashResult.issue_id == issue.id)
    result = (await session.execute(stmt)).scalar_one()
    suppression_entries = [h for h in (result.history or []) if h.get("field") == "suppression"]
    assert len(suppression_entries) == 1


# ── 4. Audit log written ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_suppress_writes_audit_log_to_result_history(
    session: AsyncSession,
) -> None:
    """Every member ClashResult gains a ``suppression`` history entry."""
    project_id = session.info["project_a"]
    issue, _sig = await _seed_issue(session, project_id, a="A", b="B")
    svc = ClashService(session)

    out = await svc.bulk_suppress(
        project_id,
        [issue.id],
        reason="cosmetic — confirmed by senior coordinator",
        user_id=session.info["owner_id"],
    )
    assert out["suppressed_count"] == 1

    stmt = select(ClashResult).where(ClashResult.issue_id == issue.id)
    result = (await session.execute(stmt)).scalar_one()
    entries = [h for h in (result.history or []) if h.get("field") == "suppression"]
    assert len(entries) == 1
    e = entries[0]
    assert e["after"] == "ignored"
    # ``before`` is the prior status (new / persisted depending on lifecycle).
    assert e["before"] in ("new", "persisted")
    # ``actor`` resolves to a non-empty audit string (email or "system").
    assert isinstance(e["actor"], str)
    assert e["actor"]


@pytest.mark.asyncio
async def test_bulk_suppress_actor_recorded_as_system_when_no_user(
    session: AsyncSession,
) -> None:
    """``user_id=None`` → audit log records ``actor='system'``."""
    project_id = session.info["project_a"]
    issue, _sig = await _seed_issue(session, project_id, a="A", b="B")
    svc = ClashService(session)
    await svc.bulk_suppress(project_id, [issue.id], "x", None)
    stmt = select(ClashResult).where(ClashResult.issue_id == issue.id)
    result = (await session.execute(stmt)).scalar_one()
    e = next(h for h in (result.history or []) if h.get("field") == "suppression")
    assert e["actor"] == "system"


# ── 5. Error rollback ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_suppress_rollback_undoes_every_change(
    session: AsyncSession,
) -> None:
    """A caller rollback after ``bulk_suppress`` discards every change.

    The service performs every write inside the caller-owned transaction
    and a single final ``session.flush()``; ``session.rollback()`` after
    the call must wipe the new suppression rows AND the ``ignored``
    status flips. This is the safety net for the atomic "all or nothing"
    contract — at the request level any error after the service returns
    rolls back the entire batch, not just the failing tail.
    """
    project_id = session.info["project_a"]
    issue_a, _ = await _seed_issue(session, project_id, a="A", b="B", name="r-a")
    issue_b, _ = await _seed_issue(session, project_id, a="C", b="D", name="r-b")
    # Snapshot the ids before the bulk op so a later rollback (which
    # expires the in-memory instances) doesn't leave us with stale refs.
    issue_a_id, issue_b_id = issue_a.id, issue_b.id
    # Commit the seed state so the rollback below targets only the bulk op.
    await session.commit()
    svc = ClashService(session)

    out = await svc.bulk_suppress(project_id, [issue_a_id, issue_b_id], "x", None)
    assert out["suppressed_count"] == 2

    # Caller decides to roll back (e.g. a downstream notify call exploded).
    await session.rollback()

    # No suppression rows survived. The seed state is intact.
    sigs = await svc.repo.suppressed_signatures_for_project(project_id)
    assert sigs == set()

    # Issue status reverted: re-fetch via SELECT (the in-memory instances
    # are expired by the rollback so ``session.refresh`` is unsafe here).
    issues_after = (
        (await session.execute(select(ClashIssue).where(ClashIssue.id.in_([issue_a_id, issue_b_id])))).scalars().all()
    )
    assert len(issues_after) == 2
    assert {i.status for i in issues_after}.isdisjoint({"ignored"})
