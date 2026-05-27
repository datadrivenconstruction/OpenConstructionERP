# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for clash signature suppressions (v41).

Pin the contract:

* suppress(sig, reason) → matching issue flips to ``ignored``
* per-project scope — suppressing on A does not suppress on B
* unsuppress restores the issue to ``persisted``
* suppressed signatures don't auto-resurface as ``new``/``persisted``
  while a suppression is active
* suppress is idempotent (repeat call updates the reason)
* unsuppress on an unknown signature is a no-op (returns False)
* missing reason / blank signature → HTTPException 422

Same per-test SQLite isolation pattern as ``test_smart_issues.py``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.clash.models import (
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
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-clash-suppr-")) / "test.db"
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
            email=f"sup-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Suppressor",
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
            name="Project B",
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


def _make_clash(
    run: ClashRun,
    *,
    a_stable: str = "A",
    b_stable: str = "B",
) -> ClashResult:
    sig, quality = _compute_signature_hash(
        a_guid=a_stable,
        b_guid=b_stable,
        centroid=(1.0, 2.0, 3.0),
        clash_type="hard",
        grid_mm=run.spatial_grid_mm,
    )
    return ClashResult(
        id=uuid.uuid4(),
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_stable,
        b_stable_id=b_stable,
        a_name=a_stable,
        b_name=b_stable,
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


async def _seed_clash(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    a: str = "A",
    b: str = "B",
    name: str = "r1",
) -> tuple[ClashRun, ClashResult, str]:
    """Persist one run + one clash; upsert it; return (run, row, signature)."""
    run = _make_run(project_id, name=name)
    session.add(run)
    await session.flush()
    row = _make_clash(run, a_stable=a, b_stable=b)
    session.add(row)
    await session.flush()
    svc = ClashService(session)
    await svc.upsert_clash_with_signature(run, row)
    await svc.finalize_run(run)
    return run, row, row.signature_hash


# ── 1. Suppress flips status ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suppress_flips_issue_to_ignored(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    await svc.suppress(project_id, sig, reason="known cosmetic", user_id=None)
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "ignored"


@pytest.mark.asyncio
async def test_suppress_creates_suppression_row(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "reason", session.info["owner_id"])
    row = await svc.repo.get_suppression(project_id, sig)
    assert row is not None
    assert row.reason == "reason"
    assert str(row.suppressed_by_user_id) == session.info["owner_id"]


@pytest.mark.asyncio
async def test_suppress_idempotent_updates_reason(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "first reason", None)
    await svc.suppress(project_id, sig, "updated reason", None)
    row = await svc.repo.get_suppression(project_id, sig)
    assert row is not None
    assert row.reason == "updated reason"
    # Still only one suppression row.
    sigs = await svc.repo.suppressed_signatures_for_project(project_id)
    assert sigs == {sig}


@pytest.mark.asyncio
async def test_suppress_rejects_empty_signature(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.suppress(project_id, "", "reason", None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_suppress_rejects_blank_signature(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.suppress(project_id, "   ", "reason", None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_suppress_rejects_empty_reason(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.suppress(project_id, "abc", "", None)
    assert exc.value.status_code == 422


# ── 2. Per-project scoping ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suppression_scoped_per_project(session: AsyncSession) -> None:
    """Suppressing on A leaves B's issue with the same signature untouched."""
    a_id = session.info["project_a"]
    b_id = session.info["project_b"]
    _, _, sig_a = await _seed_clash(session, a_id, name="A-r1")
    _, _, sig_b = await _seed_clash(session, b_id, name="B-r1")
    # Same input → same hash, but two distinct ClashIssue rows.
    assert sig_a == sig_b
    svc = ClashService(session)
    await svc.suppress(a_id, sig_a, "shut up A", None)

    issue_a = await svc.repo.get_issue_by_signature(a_id, sig_a)
    issue_b = await svc.repo.get_issue_by_signature(b_id, sig_b)
    assert issue_a is not None and issue_b is not None
    assert issue_a.status == "ignored"
    assert issue_b.status == "new"  # untouched


@pytest.mark.asyncio
async def test_suppressed_set_is_project_scoped(session: AsyncSession) -> None:
    a_id = session.info["project_a"]
    b_id = session.info["project_b"]
    _, _, sig_a = await _seed_clash(session, a_id, name="A-r1")
    _, _, _ = await _seed_clash(session, b_id, name="B-r1")
    svc = ClashService(session)
    await svc.suppress(a_id, sig_a, "x", None)
    a_set = await svc.repo.suppressed_signatures_for_project(a_id)
    b_set = await svc.repo.suppressed_signatures_for_project(b_id)
    assert a_set == {sig_a}
    assert b_set == set()


# ── 3. Unsuppress ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsuppress_removes_row_and_restores_issue(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "tmp", None)
    removed = await svc.unsuppress(project_id, sig, None)
    assert removed is True
    # Suppression row gone.
    row = await svc.repo.get_suppression(project_id, sig)
    assert row is None
    # Issue flipped back to ``persisted``.
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "persisted"


@pytest.mark.asyncio
async def test_unsuppress_unknown_signature_is_no_op(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    removed = await svc.unsuppress(project_id, "0" * 40, None)
    assert removed is False


@pytest.mark.asyncio
async def test_unsuppress_rejects_empty_signature(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.unsuppress(project_id, "", None)
    assert exc.value.status_code == 422


# ── 4. Suppression survives re-runs ──────────────────────────────────────


@pytest.mark.asyncio
async def test_suppressed_signature_stays_ignored_on_re_run(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_a"]
    _r1, _row1, sig = await _seed_clash(session, project_id, name="r1")
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "ignore", None)
    # Run 2: same signature shows up again.
    await _seed_clash(session, project_id, name="r2")
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "ignored"


@pytest.mark.asyncio
async def test_suppression_does_not_create_new_issue_after_unsuppress_then_run(
    session: AsyncSession,
) -> None:
    """Unsuppress + new run → issue back to ``persisted``, no duplicate."""
    project_id = session.info["project_a"]
    _r1, _row1, sig = await _seed_clash(session, project_id, name="r1")
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "ignore", None)
    await svc.unsuppress(project_id, sig, None)
    await _seed_clash(session, project_id, name="r2")
    # Still exactly one issue with this signature.
    rows, total = await svc.list_issues(project_id)
    matching = [i for i, _c in rows if i.signature_hash == sig]
    assert len(matching) == 1
    assert total >= 1
    assert matching[0].status == "persisted"


# ── 5. Repository helpers ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_suppression_returns_none_when_missing(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    row = await svc.repo.get_suppression(project_id, "deadbeef" * 5)
    assert row is None


@pytest.mark.asyncio
async def test_suppressed_signatures_set_grows_and_shrinks(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_a"]
    # Seed two distinct signatures.
    _r1, _row1, sig_ab = await _seed_clash(session, project_id, a="A", b="B", name="r1")
    _r2, _row2, sig_cd = await _seed_clash(session, project_id, a="C", b="D", name="r2")
    assert sig_ab != sig_cd
    svc = ClashService(session)
    await svc.suppress(project_id, sig_ab, "x", None)
    sigs = await svc.repo.suppressed_signatures_for_project(project_id)
    assert sigs == {sig_ab}
    await svc.suppress(project_id, sig_cd, "y", None)
    sigs = await svc.repo.suppressed_signatures_for_project(project_id)
    assert sigs == {sig_ab, sig_cd}
    await svc.unsuppress(project_id, sig_ab, None)
    sigs = await svc.repo.suppressed_signatures_for_project(project_id)
    assert sigs == {sig_cd}


# ── 6. Suppression by issue id (router convenience wrapper) ──────────────


@pytest.mark.asyncio
async def test_suppress_by_issue_resolves_signature(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    out = await svc.suppress_by_issue(project_id, issue.id, "reason", None)
    assert out.id == issue.id
    refreshed = await svc.repo.get_issue_by_signature(project_id, sig)
    assert refreshed.status == "ignored"


@pytest.mark.asyncio
async def test_unsuppress_by_issue_resolves_signature(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    await svc.suppress_by_issue(project_id, issue.id, "tmp", None)
    out = await svc.unsuppress_by_issue(project_id, issue.id, None)
    assert out.id == issue.id
    refreshed = await svc.repo.get_issue_by_signature(project_id, sig)
    assert refreshed.status == "persisted"


@pytest.mark.asyncio
async def test_suppress_by_unknown_issue_id_raises_404(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.suppress_by_issue(project_id, uuid.uuid4(), "x", None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unsuppress_by_unknown_issue_id_raises_404(session: AsyncSession) -> None:
    project_id = session.info["project_a"]
    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.unsuppress_by_issue(project_id, uuid.uuid4(), None)
    assert exc.value.status_code == 404


# ── 7. Suppression is the only state that ignores the lifecycle ──────────


@pytest.mark.asyncio
async def test_unsuppress_does_not_revive_archived_issue(
    session: AsyncSession,
) -> None:
    """unsuppress only flips ``ignored`` rows — leaves other states alone."""
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    # Manually set issue to archived (simulate the lifecycle).
    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    issue.status = "archived"
    await session.flush()
    # No suppression exists yet — unsuppress should be a no-op.
    removed = await svc.unsuppress(project_id, sig, None)
    assert removed is False
    refreshed = await svc.repo.get_issue_by_signature(project_id, sig)
    assert refreshed.status == "archived"


# ── 8. Suppression model integrity ───────────────────────────────────────


@pytest.mark.asyncio
async def test_suppression_unique_per_project_signature(
    session: AsyncSession,
) -> None:
    """Two suppressions with the same (project, signature) violate UQ."""
    project_id = session.info["project_a"]
    _run, _row, sig = await _seed_clash(session, project_id)
    svc = ClashService(session)
    await svc.suppress(project_id, sig, "x", None)
    # The second suppress() call must NOT create a duplicate row (idempotent).
    await svc.suppress(project_id, sig, "y", None)
    # ORM-level: exactly one suppression row for this (project, sig).
    from sqlalchemy import select

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
