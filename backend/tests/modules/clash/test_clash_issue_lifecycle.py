# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the smart-issue lifecycle state machine (v41).

Pins the ``ClashIssue.status`` transitions driven by
:meth:`ClashService.upsert_clash_with_signature` +
:meth:`ClashService.finalize_run`:

* a brand-new signature seen in its first run is ``new`` - and STAYS
  ``new`` even when more than one result row in that same run carries
  the same ``signature_hash`` (weak GUID-less / same-bucket collisions);
  the duplicate-within-run sighting must NOT prematurely advance the
  issue to ``persisted`` (= "seen in more than one run").
* the same signature seen again in a *later* run flips ``new`` ->
  ``persisted``.
* a signature absent from a later run flips ``persisted`` -> ``resolved``.

Regression guard for the data-integrity fix: the within-run duplicate
must be idempotent on the issue lifecycle.

Runs on a transaction-isolated PostgreSQL session (rolled back on
teardown) via ``tests._pg.transactional_session`` - same idiom as
``test_clash_suppressions.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash.service import ClashService, _compute_signature_hash
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"life-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Lifecycle",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Lifecycle Project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        yield s


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_run(project_id: uuid.UUID, name: str) -> ClashRun:
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
) -> ClashResult:
    sig, quality = _compute_signature_hash(
        a_guid=a_stable,
        b_guid=b_stable,
        centroid=centroid,
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


# ── 1. First run stays ``new`` even with a duplicate-signature row ─────────


@pytest.mark.asyncio
async def test_single_member_first_run_is_new(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    row = _make_clash(run)
    session.add(row)
    await session.flush()
    svc = ClashService(session)
    await svc.upsert_clash_with_signature(run, row)
    await svc.finalize_run(run)
    issue = await svc.repo.get_issue_by_signature(project_id, row.signature_hash)
    assert issue is not None
    assert issue.status == "new"


@pytest.mark.asyncio
async def test_duplicate_signature_in_first_run_stays_new(session: AsyncSession) -> None:
    """Two result rows with the SAME signature in one run keep the issue ``new``.

    This is the regression: previously the second row flipped the
    brand-new issue ``new`` -> ``persisted`` even though it had only been
    seen in a single run.
    """
    project_id = session.info["project_id"]
    run = _make_run(project_id, "r1")
    session.add(run)
    await session.flush()
    # Two distinct result rows that collide on the same signature_hash
    # (identical stable ids + same spatial bucket + same clash_type).
    row_1 = _make_clash(run, a_stable="A", b_stable="B", centroid=(1.0, 2.0, 3.0))
    row_2 = _make_clash(run, a_stable="A", b_stable="B", centroid=(1.1, 2.1, 3.1))
    assert row_1.signature_hash == row_2.signature_hash
    session.add_all([row_1, row_2])
    await session.flush()
    svc = ClashService(session)
    await svc.upsert_clash_with_signature(run, row_1)
    await svc.upsert_clash_with_signature(run, row_2)
    await svc.finalize_run(run)
    issue = await svc.repo.get_issue_by_signature(project_id, row_1.signature_hash)
    assert issue is not None
    assert issue.status == "new"
    # Both rows linked to the one shared issue.
    assert row_1.issue_id == issue.id
    assert row_2.issue_id == issue.id


# ── 2. Second run advances ``new`` -> ``persisted`` ────────────────────────


@pytest.mark.asyncio
async def test_second_run_advances_to_persisted(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    svc = ClashService(session)

    run_1 = _make_run(project_id, "r1")
    session.add(run_1)
    await session.flush()
    row_1 = _make_clash(run_1)
    session.add(row_1)
    await session.flush()
    await svc.upsert_clash_with_signature(run_1, row_1)
    await svc.finalize_run(run_1)
    sig = row_1.signature_hash

    run_2 = _make_run(project_id, "r2")
    session.add(run_2)
    await session.flush()
    row_2 = _make_clash(run_2)
    session.add(row_2)
    await session.flush()
    await svc.upsert_clash_with_signature(run_2, row_2)
    await svc.finalize_run(run_2)

    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "persisted"


@pytest.mark.asyncio
async def test_duplicate_in_second_run_still_persisted(session: AsyncSession) -> None:
    """A within-run duplicate in the SECOND run is idempotent on lifecycle."""
    project_id = session.info["project_id"]
    svc = ClashService(session)

    run_1 = _make_run(project_id, "r1")
    session.add(run_1)
    await session.flush()
    row_1 = _make_clash(run_1)
    session.add(row_1)
    await session.flush()
    await svc.upsert_clash_with_signature(run_1, row_1)
    await svc.finalize_run(run_1)
    sig = row_1.signature_hash

    run_2 = _make_run(project_id, "r2")
    session.add(run_2)
    await session.flush()
    row_2a = _make_clash(run_2, centroid=(1.0, 2.0, 3.0))
    row_2b = _make_clash(run_2, centroid=(1.2, 2.2, 3.2))
    assert row_2a.signature_hash == row_2b.signature_hash == sig
    session.add_all([row_2a, row_2b])
    await session.flush()
    await svc.upsert_clash_with_signature(run_2, row_2a)
    await svc.upsert_clash_with_signature(run_2, row_2b)
    await svc.finalize_run(run_2)

    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "persisted"


# ── 3. Resolved when absent from a later run ───────────────────────────────


@pytest.mark.asyncio
async def test_resolved_when_absent_from_later_run(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    svc = ClashService(session)

    run_1 = _make_run(project_id, "r1")
    session.add(run_1)
    await session.flush()
    row_1 = _make_clash(run_1)
    session.add(row_1)
    await session.flush()
    await svc.upsert_clash_with_signature(run_1, row_1)
    await svc.finalize_run(run_1)
    sig = row_1.signature_hash

    # Second run sees a DIFFERENT signature, so the first one is now absent.
    run_2 = _make_run(project_id, "r2")
    session.add(run_2)
    await session.flush()
    row_2 = _make_clash(run_2, a_stable="C", b_stable="D")
    assert row_2.signature_hash != sig
    session.add(row_2)
    await session.flush()
    await svc.upsert_clash_with_signature(run_2, row_2)
    await svc.finalize_run(run_2)

    issue = await svc.repo.get_issue_by_signature(project_id, sig)
    assert issue is not None
    assert issue.status == "resolved"
    assert str(issue.resolved_run_id) == str(run_2.id)
