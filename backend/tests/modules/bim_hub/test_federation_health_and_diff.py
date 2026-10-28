# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for BIM Federation health + snapshot/diff (v7.x).

Two layers are exercised:

* Pure helpers (``_classify_federation_member``, ``_aggregate_federation_health``,
  ``diff_federation_snapshots``) - no DB, fast, deterministic.
* Service methods (``compute_federation_health``, ``capture_federation_snapshot``,
  ``diff_federation_snapshot``) - against a transaction-isolated PostgreSQL
  session from ``tests._pg``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel
from app.modules.bim_hub.schemas import (
    FederationCreate,
    FederationMemberHealth,
    FederationModelAdd,
    FederationSnapshot,
    FederationSnapshotMember,
)
from app.modules.bim_hub.service import (
    FEDERATION_STALENESS_THRESHOLD_DAYS,
    BIMHubService,
    _aggregate_federation_health,
    _classify_federation_member,
    diff_federation_snapshots,
)
from tests._pg import transactional_session

# ── Pure helper: member classification ─────────────────────────────────────


def _make_model(
    *,
    status: str = "ready",
    element_count: int = 100,
    updated_at: datetime | None = None,
) -> BIMModel:
    """Build a detached BIMModel row for pure-function tests (no DB)."""
    model = BIMModel(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="Block A",
        discipline="arch",
        version="1",
        status=status,
        element_count=element_count,
    )
    model.updated_at = updated_at or datetime.now(UTC)
    return model


def test_classify_missing_model() -> None:
    """A dangling link (model is None) classifies as ``missing``."""
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=uuid.uuid4(),
        discipline="struct",
        model=None,
        newest_update=datetime.now(UTC),
    )
    assert report.state == "missing"
    assert report.model_status is None
    assert "model_deleted" in report.warnings


def test_classify_failed_model() -> None:
    """A model with a failed status classifies as ``failed``."""
    model = _make_model(status="failed")
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=model.id,
        discipline="mep",
        model=model,
        newest_update=datetime.now(UTC),
    )
    assert report.state == "failed"
    assert "conversion_failed" in report.warnings


def test_classify_processing_model() -> None:
    """A non-ready, non-failed status classifies as ``processing``."""
    model = _make_model(status="processing")
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=model.id,
        discipline="arch",
        model=model,
        newest_update=datetime.now(UTC),
    )
    assert report.state == "processing"
    assert "still_processing" in report.warnings


def test_classify_empty_model() -> None:
    """A ready model with zero elements classifies as ``empty``."""
    model = _make_model(status="ready", element_count=0)
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=model.id,
        discipline="arch",
        model=model,
        newest_update=datetime.now(UTC),
    )
    assert report.state == "empty"
    assert "no_elements" in report.warnings


def test_classify_stale_model() -> None:
    """A ready model lagging the freshest member past the threshold is stale."""
    newest = datetime.now(UTC)
    old = newest - timedelta(days=FEDERATION_STALENESS_THRESHOLD_DAYS + 5)
    model = _make_model(status="ready", element_count=50, updated_at=old)
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=model.id,
        discipline="struct",
        model=model,
        newest_update=newest,
    )
    assert report.state == "stale"
    assert report.staleness_days == FEDERATION_STALENESS_THRESHOLD_DAYS + 5
    assert "stale_relative_to_set" in report.warnings


def test_classify_ready_model_within_threshold() -> None:
    """A fresh, non-empty, ready model classifies as ``ready`` with no warnings."""
    newest = datetime.now(UTC)
    recent = newest - timedelta(days=FEDERATION_STALENESS_THRESHOLD_DAYS - 1)
    model = _make_model(status="ready", element_count=200, updated_at=recent)
    report = _classify_federation_member(
        member_id=uuid.uuid4(),
        bim_model_id=model.id,
        discipline="arch",
        model=model,
        newest_update=newest,
    )
    assert report.state == "ready"
    assert report.warnings == []


# ── Pure helper: aggregation ───────────────────────────────────────────────


def _health(state: str, elements: int = 10) -> FederationMemberHealth:
    return FederationMemberHealth(
        member_id=uuid.uuid4(),
        bim_model_id=uuid.uuid4(),
        model_name="m",
        discipline="arch",
        state=state,  # type: ignore[arg-type]
        element_count=elements,
    )


def test_aggregate_empty_federation() -> None:
    """Zero members yields a well-formed ``no_members`` report, score 0."""
    fed_id = uuid.uuid4()
    report = _aggregate_federation_health(fed_id, [], None)
    assert report.overall_state == "no_members"
    assert report.score == 0.0
    assert report.member_count == 0


def test_aggregate_all_ready() -> None:
    """All-ready members score 1.0 and headline ``ready``."""
    report = _aggregate_federation_health(
        uuid.uuid4(),
        [_health("ready", 10), _health("ready", 20)],
        spread_days=0,
    )
    assert report.score == 1.0
    assert report.overall_state == "ready"
    assert report.total_elements == 30


def test_aggregate_worst_state_wins() -> None:
    """The headline state is the worst member (missing beats failed beats ready)."""
    members = [_health("ready"), _health("failed"), _health("missing")]
    report = _aggregate_federation_health(uuid.uuid4(), members, spread_days=3)
    assert report.overall_state == "missing"
    assert report.ready_count == 1
    assert report.failed_count == 1
    assert report.missing_count == 1
    # 1 ready of 3 members -> 0.33.
    assert report.score == 0.33
    assert report.spread_days == 3


# ── Pure helper: snapshot diff ─────────────────────────────────────────────


def _snap_member(
    mid: uuid.UUID,
    *,
    name: str,
    discipline: str = "arch",
    count: int = 100,
) -> FederationSnapshotMember:
    return FederationSnapshotMember(
        bim_model_id=mid,
        model_name=name,
        discipline=discipline,
        element_count=count,
    )


def test_diff_added_removed_changed_unchanged() -> None:
    """All four diff buckets are populated correctly."""
    keep = uuid.uuid4()
    grow = uuid.uuid4()
    gone = uuid.uuid4()
    fresh = uuid.uuid4()
    fed_id = uuid.uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)

    old = FederationSnapshot(
        federation_id=fed_id,
        name="Coord",
        captured_at=t0,
        member_count=3,
        total_elements=300,
        members=[
            _snap_member(keep, name="Keep", count=100),
            _snap_member(grow, name="Grow", count=50),
            _snap_member(gone, name="Gone", count=150),
        ],
    )
    new = FederationSnapshot(
        federation_id=fed_id,
        name="Coord",
        captured_at=t1,
        member_count=3,
        total_elements=320,
        members=[
            _snap_member(keep, name="Keep", count=100),
            _snap_member(grow, name="Grow", count=120),
            _snap_member(fresh, name="Fresh", count=100),
        ],
    )

    diff = diff_federation_snapshots(fed_id, old, new)

    assert {m.bim_model_id for m in diff.added} == {fresh}
    assert {m.bim_model_id for m in diff.removed} == {gone}
    assert {d.bim_model_id for d in diff.changed} == {grow}
    assert {m.bim_model_id for m in diff.unchanged} == {keep}
    # Grow went 50 -> 120 = +70.
    grow_delta = next(d for d in diff.changed if d.bim_model_id == grow)
    assert grow_delta.element_count_delta == 70
    assert grow_delta.old_element_count == 50
    assert grow_delta.new_element_count == 120
    # Net drift = 320 - 300.
    assert diff.total_element_drift == 20
    assert diff.old_captured_at == t0
    assert diff.new_captured_at == t1


def test_diff_identical_snapshots() -> None:
    """Diffing a snapshot against itself yields only ``unchanged``."""
    mid = uuid.uuid4()
    fed_id = uuid.uuid4()
    snap = FederationSnapshot(
        federation_id=fed_id,
        name="Coord",
        captured_at=datetime.now(UTC),
        member_count=1,
        total_elements=100,
        members=[_snap_member(mid, name="A", count=100)],
    )
    diff = diff_federation_snapshots(fed_id, snap, snap)
    assert diff.added == []
    assert diff.removed == []
    assert diff.changed == []
    assert len(diff.unchanged) == 1
    assert diff.total_element_drift == 0


# ── Service-layer integration (PostgreSQL) ─────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session with one project pre-seeded."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"h-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="H",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Health Project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        yield s


async def _seed_model(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str,
    status: str = "ready",
    element_count: int = 100,
) -> BIMModel:
    model = BIMModel(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        version="1",
        status=status,
        element_count=element_count,
    )
    session.add(model)
    await session.commit()
    return model


@pytest.mark.asyncio
async def test_compute_health_mixed_members(session: AsyncSession) -> None:
    """A federation with ready + processing + failed members reports each.

    Note on ``missing``: deleting the underlying ``BIMModel`` cascades the
    link row away (FK ``ondelete=CASCADE`` on ``bim_model_id``), so a
    dangling member is unreachable through ordinary model deletion. The
    ``missing`` state is a defensive classification (raw deletes / future
    soft-delete) and is exercised at the pure-helper layer instead.
    """
    project_id: uuid.UUID = session.info["project_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="Coord"))

    ready = await _seed_model(session, project_id, name="ARCH", status="ready", element_count=500)
    proc = await _seed_model(session, project_id, name="MEP", status="processing", element_count=0)
    failed = await _seed_model(session, project_id, name="STR", status="failed", element_count=0)

    for m, disc in ((ready, "arch"), (proc, "mep"), (failed, "struct")):
        await service.add_federation_member(
            fed.id,
            FederationModelAdd(bim_model_id=m.id, discipline=disc),
        )
    await session.commit()

    health = await service.compute_federation_health(fed.id)
    assert health.member_count == 3
    assert health.ready_count == 1
    assert health.processing_count == 1
    assert health.failed_count == 1
    # Worst state across {ready, processing, failed} is failed.
    assert health.overall_state == "failed"
    assert health.total_elements == 500  # only the ready member has elements
    assert health.score == 0.33


@pytest.mark.asyncio
async def test_snapshot_then_diff_after_adding_member(session: AsyncSession) -> None:
    """Capture a snapshot, add a member, then diff -> one ``added`` row."""
    project_id: uuid.UUID = session.info["project_id"]
    service = BIMHubService(session)
    fed = await service.create_federation(FederationCreate(project_id=project_id, name="Coord"))

    m1 = await _seed_model(session, project_id, name="ARCH", element_count=200)
    await service.add_federation_member(fed.id, FederationModelAdd(bim_model_id=m1.id, discipline="arch"))
    await session.commit()

    old_snapshot = await service.capture_federation_snapshot(fed.id)
    assert old_snapshot.member_count == 1
    assert old_snapshot.total_elements == 200

    m2 = await _seed_model(session, project_id, name="STRUCT", element_count=300)
    await service.add_federation_member(fed.id, FederationModelAdd(bim_model_id=m2.id, discipline="struct"))
    await session.commit()

    diff = await service.diff_federation_snapshot(fed.id, old_snapshot)
    assert {m.bim_model_id for m in diff.added} == {m2.id}
    assert diff.removed == []
    assert {m.bim_model_id for m in diff.unchanged} == {m1.id}
    assert diff.total_element_drift == 300
