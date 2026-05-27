# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the smart-issue lifecycle (v41).

Pins the cross-run contract:

* dedup — N result rows on the same signature → 1 :class:`ClashIssue`
* first-sighting creates an issue with a CLASH-NNN id + status=new
* second sighting flips new → persisted
* missing for 1 run → resolved (and stamps ``resolved_run_id``)
* missing for ``_ARCHIVE_AFTER_MISSING`` consecutive runs → archived
* reopened — a resolved issue that resurfaces flips back to persisted
* state-machine guards — no invalid transitions

Per ``feedback_test_isolation.md`` each test gets a fresh temp SQLite.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
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
)
from app.modules.clash.service import (
    _ARCHIVE_AFTER_MISSING,
    ClashService,
    _compute_signature_hash,
)


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.clash.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test SQLite + a project owned by a test user.

    The fixture seeds:
        * one User (owner)
        * one Project (the smart-issue scope)
    and yields an open :class:`AsyncSession`. Tear-down disposes the
    engine so the temp file can be cleaned up.
    """
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-clash-issue-")) / "test.db"
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
            email=f"clash-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Clash Tester",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Clash Smart Issues",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = str(owner.id)
        yield s
    await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_run(project_id: uuid.UUID, name: str = "run") -> ClashRun:
    """Build a minimal completed :class:`ClashRun`."""
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
    centroid: tuple[float, float, float] = (1.0, 2.0, 3.0),
    clash_type: str = "hard",
) -> ClashResult:
    """Build a :class:`ClashResult` with a stamped signature."""
    sig, quality = _compute_signature_hash(
        a_guid=a_stable,
        b_guid=b_stable,
        centroid=centroid,
        clash_type=clash_type,
        grid_mm=run.spatial_grid_mm,
    )
    return ClashResult(
        id=uuid.uuid4(),
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id=a_stable,
        b_stable_id=b_stable,
        a_name="A",
        b_name="B",
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type=clash_type,
        penetration_m=0.05,
        distance_m=0.0,
        cx=centroid[0],
        cy=centroid[1],
        cz=centroid[2],
        status="new",
        severity="medium",
        signature=sig[:16],
        signature_hash=sig,
        signature_quality=quality,
        tolerance_at_signature_time_mm=run.tolerance_m * 1000.0,
    )


async def _persist_run_with_clashes(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str,
    clashes_spec: list[dict],
) -> tuple[ClashRun, list[ClashResult]]:
    """Persist one run + its clash rows; upsert each, then finalize.

    ``clashes_spec`` is a list of kwargs passed to :func:`_make_clash`.
    """
    run = _make_run(project_id, name=name)
    session.add(run)
    await session.flush()
    rows = [_make_clash(run, **spec) for spec in clashes_spec]
    for r in rows:
        session.add(r)
    await session.flush()
    svc = ClashService(session)
    for r in rows:
        await svc.upsert_clash_with_signature(run, r)
    await svc.finalize_run(run)
    return run, rows


# ── 1. Dedup ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ten_clashes_same_signature_become_one_issue(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    specs = [{"a_stable": "A", "b_stable": "B"} for _ in range(10)]
    _run, rows = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=specs,
    )
    svc = ClashService(session)
    issues, total = await svc.list_issues(project_id)
    assert total == 1
    assert len(issues) == 1
    issue, member_count = issues[0]
    assert member_count == 10
    # Every row points at the same issue.
    assert {r.issue_id for r in rows} == {issue.id}


@pytest.mark.asyncio
async def test_two_signatures_two_issues(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    specs = [
        {"a_stable": "A", "b_stable": "B"},
        {"a_stable": "C", "b_stable": "D"},
    ]
    _run, _rows = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=specs,
    )
    svc = ClashService(session)
    _issues, total = await svc.list_issues(project_id)
    assert total == 2


# ── 2. First-sighting issue creation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_new_clash_creates_issue_with_server_id(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    _run, _rows = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "X", "b_stable": "Y"}],
    )
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id)
    issue, _count = issues[0]
    assert issue.server_assigned_id.startswith("CLASH-")
    assert issue.server_assigned_id == "CLASH-001"
    assert issue.status == "new"
    assert issue.first_seen_run_id == issue.last_seen_run_id
    assert issue.resolved_run_id is None
    assert issue.missing_run_count == 0


@pytest.mark.asyncio
async def test_server_ids_monotonic_per_project(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "A", "b_stable": "B"}],
    )
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r2",
        clashes_spec=[
            {"a_stable": "A", "b_stable": "B"},  # same as r1
            {"a_stable": "C", "b_stable": "D"},  # new
        ],
    )
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id)
    ids = sorted(i.server_assigned_id for (i, _c) in issues)
    assert ids == ["CLASH-001", "CLASH-002"]


# ── 3. new → persisted ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_sighting_flips_new_to_persisted(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    specs = [{"a_stable": "A", "b_stable": "B"}]
    await _persist_run_with_clashes(session, project_id, name="r1", clashes_spec=specs)
    await _persist_run_with_clashes(session, project_id, name="r2", clashes_spec=specs)
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id)
    issue, _count = issues[0]
    assert issue.status == "persisted"
    assert issue.first_seen_run_id != issue.last_seen_run_id


# ── 4. resolved + missing-for-3 → archived ───────────────────────────────


@pytest.mark.asyncio
async def test_missing_for_one_run_flips_to_resolved(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    spec_ab = [{"a_stable": "A", "b_stable": "B"}]
    run1, _ = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=spec_ab,
    )
    # r2 has no AB clash — the issue is gone.
    run2, _ = await _persist_run_with_clashes(
        session,
        project_id,
        name="r2",
        clashes_spec=[{"a_stable": "C", "b_stable": "D"}],
    )
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id)
    ab_issue = next(i for i, _c in issues if i.first_seen_run_id == run1.id)
    assert ab_issue.status == "resolved"
    assert ab_issue.resolved_run_id == run2.id
    assert ab_issue.missing_run_count == 1


@pytest.mark.asyncio
async def test_missing_for_three_runs_flips_to_archived(
    session: AsyncSession,
) -> None:
    """``_ARCHIVE_AFTER_MISSING`` is 3 per the spec."""
    assert _ARCHIVE_AFTER_MISSING == 3
    project_id = session.info["project_id"]
    spec_ab = [{"a_stable": "A", "b_stable": "B"}]
    spec_other = [{"a_stable": "X", "b_stable": "Y"}]
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=spec_ab,
    )
    # 3 runs without AB → missing_run_count climbs 1, 2, 3 → archived.
    for i in range(_ARCHIVE_AFTER_MISSING):
        await _persist_run_with_clashes(
            session,
            project_id,
            name=f"r{i + 2}",
            clashes_spec=spec_other,
        )
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id, status_filter="archived")
    archived = [i for i, _c in issues]
    assert len(archived) == 1
    assert archived[0].status == "archived"
    assert archived[0].missing_run_count >= _ARCHIVE_AFTER_MISSING


@pytest.mark.asyncio
async def test_missing_count_resets_when_signature_returns(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    spec_ab = [{"a_stable": "A", "b_stable": "B"}]
    spec_other = [{"a_stable": "X", "b_stable": "Y"}]
    await _persist_run_with_clashes(session, project_id, name="r1", clashes_spec=spec_ab)
    await _persist_run_with_clashes(session, project_id, name="r2", clashes_spec=spec_other)
    await _persist_run_with_clashes(session, project_id, name="r3", clashes_spec=spec_ab)
    svc = ClashService(session)
    ab_sig, _q = _compute_signature_hash(
        a_guid="A",
        b_guid="B",
        centroid=(1.0, 2.0, 3.0),
        clash_type="hard",
        grid_mm=500,
    )
    ab_issue = await svc.repo.get_issue_by_signature(project_id, ab_sig)
    assert ab_issue is not None
    # The AB issue resurfaced in r3 → missing_run_count must be reset.
    assert ab_issue.missing_run_count == 0
    assert ab_issue.status == "persisted"
    assert ab_issue.resolved_run_id is None


# ── 5. Reopen ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolved_issue_resurfaces_as_persisted(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    spec_ab = [{"a_stable": "A", "b_stable": "B"}]
    spec_other = [{"a_stable": "X", "b_stable": "Y"}]
    # r1: seed AB. r2: AB gone → resolved. r3: AB back → persisted.
    await _persist_run_with_clashes(session, project_id, name="r1", clashes_spec=spec_ab)
    await _persist_run_with_clashes(session, project_id, name="r2", clashes_spec=spec_other)
    await _persist_run_with_clashes(session, project_id, name="r3", clashes_spec=spec_ab)
    svc = ClashService(session)
    (issues, _total) = await svc.list_issues(project_id)
    ab_sig, _q = _compute_signature_hash(
        a_guid="A",
        b_guid="B",
        centroid=(1.0, 2.0, 3.0),
        clash_type="hard",
        grid_mm=500,
    )
    ab_issue = next(i for i, _c in issues if i.signature_hash == ab_sig)
    assert ab_issue.status == "persisted"
    # resolved_run_id is cleared on reopen.
    assert ab_issue.resolved_run_id is None


@pytest.mark.asyncio
async def test_archived_issue_can_be_reopened(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    spec_ab = [{"a_stable": "A", "b_stable": "B"}]
    spec_other = [{"a_stable": "X", "b_stable": "Y"}]
    # r1 seeds, runs r2..r4 archive it.
    await _persist_run_with_clashes(session, project_id, name="r1", clashes_spec=spec_ab)
    for i in range(_ARCHIVE_AFTER_MISSING):
        await _persist_run_with_clashes(
            session,
            project_id,
            name=f"r{i + 2}",
            clashes_spec=spec_other,
        )
    # Confirm archived.
    svc = ClashService(session)
    ab_sig, _q = _compute_signature_hash(
        a_guid="A",
        b_guid="B",
        centroid=(1.0, 2.0, 3.0),
        clash_type="hard",
        grid_mm=500,
    )
    issue = await svc.repo.get_issue_by_signature(project_id, ab_sig)
    assert issue is not None
    assert issue.status == "archived"
    # Now resurface.
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r_resurface",
        clashes_spec=spec_ab,
    )
    issue = await svc.repo.get_issue_by_signature(project_id, ab_sig)
    assert issue is not None
    assert issue.status == "persisted"
    assert issue.missing_run_count == 0


# ── 6. State-machine integrity ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_filter_validates_against_state_set(
    session: AsyncSession,
) -> None:
    from fastapi import HTTPException

    svc = ClashService(session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.list_issues(uuid.uuid4(), status_filter="bogus")
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_status_filter_passes_through_valid_values(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    svc = ClashService(session)
    for valid in ("new", "persisted", "resolved", "ignored", "archived"):
        # Should not raise even on an empty result set.
        rows, total = await svc.list_issues(project_id, status_filter=valid)
        assert rows == []
        assert total == 0


# ── 7. Cross-project isolation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_signature_scoped_per_project(session: AsyncSession) -> None:
    """Two projects with the same signature → two distinct issues."""
    from app.modules.projects.models import Project

    project_a = session.info["project_id"]
    project_b = Project(
        id=uuid.uuid4(),
        name="Other Project",
        owner_id=uuid.UUID(session.info["owner_id"]),
        currency="EUR",
    )
    session.add(project_b)
    await session.flush()

    spec = [{"a_stable": "A", "b_stable": "B"}]
    await _persist_run_with_clashes(session, project_a, name="r-a", clashes_spec=spec)
    await _persist_run_with_clashes(session, project_b.id, name="r-b", clashes_spec=spec)

    svc = ClashService(session)
    a_issues, _ = await svc.list_issues(project_a)
    b_issues, _ = await svc.list_issues(project_b.id)
    assert len(a_issues) == 1
    assert len(b_issues) == 1
    # Same signature_hash, but two distinct UUIDs + per-project CLASH-001 each.
    a_i, _ = a_issues[0]
    b_i, _ = b_issues[0]
    assert a_i.id != b_i.id
    assert a_i.signature_hash == b_i.signature_hash
    assert a_i.server_assigned_id == "CLASH-001"
    assert b_i.server_assigned_id == "CLASH-001"


# ── 8. Upsert directly (unit-level) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_requires_signature_hash(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    run = _make_run(project_id, name="r1")
    session.add(run)
    await session.flush()
    bad = ClashResult(
        id=uuid.uuid4(),
        run_id=run.id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="A",
        b_stable_id="B",
        a_name="A",
        b_name="B",
        a_discipline="X",
        b_discipline="Y",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=0.0,
        cy=0.0,
        cz=0.0,
        status="new",
        severity="medium",
        signature="",
        signature_hash="",  # ← intentionally blank
        signature_quality="strong",
    )
    session.add(bad)
    await session.flush()
    svc = ClashService(session)
    with pytest.raises(ValueError):
        await svc.upsert_clash_with_signature(run, bad)


@pytest.mark.asyncio
async def test_upsert_links_clash_to_issue(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    run, rows = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "A", "b_stable": "B"}],
    )
    # The persisted row should have a non-null issue_id.
    fresh = await session.get(ClashResult, rows[0].id)
    assert fresh is not None
    assert fresh.issue_id is not None
    issue = await session.get(ClashIssue, fresh.issue_id)
    assert issue is not None
    assert issue.signature_hash == fresh.signature_hash


# ── 9. Run-diff projection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_diff_reports_new_persisted_resolved(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    # r1: seed AB
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "A", "b_stable": "B"}],
    )
    # r2: keep AB (persisted), add CD (new), drop nothing else.
    r2, _ = await _persist_run_with_clashes(
        session,
        project_id,
        name="r2",
        clashes_spec=[
            {"a_stable": "A", "b_stable": "B"},
            {"a_stable": "C", "b_stable": "D"},
        ],
    )
    svc = ClashService(session)
    diff = await svc.run_diff(project_id, r2.id)
    assert diff["new"] == 1  # CD
    assert diff["persisted"] == 1  # AB
    assert diff["resolved"] == 0
    assert diff["reopened"] == 0
    assert diff["ignored"] == 0


@pytest.mark.asyncio
async def test_run_diff_counts_resolved(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "A", "b_stable": "B"}],
    )
    r2, _ = await _persist_run_with_clashes(
        session,
        project_id,
        name="r2",
        clashes_spec=[{"a_stable": "C", "b_stable": "D"}],
    )
    svc = ClashService(session)
    diff = await svc.run_diff(project_id, r2.id)
    assert diff["resolved"] == 1
    assert diff["new"] == 1
    assert diff["persisted"] == 0


# ── 10. Idempotency on the finalize pass ─────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_run_is_idempotent(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    run, _ = await _persist_run_with_clashes(
        session,
        project_id,
        name="r1",
        clashes_spec=[{"a_stable": "A", "b_stable": "B"}],
    )
    svc = ClashService(session)
    # Snapshot state.
    (issues_before, _) = await svc.list_issues(project_id)
    statuses_before = {(i.id, i.status, i.missing_run_count) for i, _c in issues_before}
    # Re-run finalize — should be a no-op for current-run-present signatures.
    await svc.finalize_run(run)
    await svc.finalize_run(run)
    (issues_after, _) = await svc.list_issues(project_id)
    statuses_after = {(i.id, i.status, i.missing_run_count) for i, _c in issues_after}
    assert statuses_before == statuses_after
