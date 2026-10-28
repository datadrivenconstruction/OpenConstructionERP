"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cluster → coordination action (cross-module link) tests.

Covers the deliberate, human-confirmed bridge that turns one clash cluster
into a single tracked work item (punch item or task), with a reverse link
stamped onto every member clash. Two layers, same isolation discipline as
``test_clash_profiles.py``:

* **Pure** (no DB) - :func:`_max_severity` and
  :func:`_build_cluster_action_proposal` driven through tiny ``ClashResult``
  stand-ins (no engine / geometry needed).
* **DB-backed** - :class:`ClashService` ``propose_cluster_action`` +
  ``create_action_from_cluster`` over the PostgreSQL engine provisioned by
  ``conftest.py``: punch-item creation, link-back, status advance,
  idempotency, task target, and the unknown-cluster 404.
"""

from __future__ import annotations

import uuid

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.modules.clash.models import ClashCluster, ClashResult, ClashRun  # noqa: E402
from app.modules.clash.service import (  # noqa: E402
    ClashService,
    _build_cluster_action_proposal,
    _max_severity,
)

# ── Pure: _max_severity ────────────────────────────────────────────────────


class _Row:
    """Tiny ClashResult stand-in for the proposal helpers."""

    def __init__(
        self,
        *,
        a_disc: str = "Mechanical",
        b_disc: str = "Structural",
        a_name: str = "Duct-1",
        b_name: str = "Beam-1",
        severity: str = "medium",
        status: str = "new",
        clash_type: str = "hard",
        a_storey: int | None = None,
        b_storey: int | None = None,
        assigned_to: str | None = None,
        a_element_id: str = "",
        b_element_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.a_discipline = a_disc
        self.b_discipline = b_disc
        self.a_name = a_name
        self.b_name = b_name
        self.severity = severity
        self.status = status
        self.clash_type = clash_type
        self.a_storey = a_storey
        self.b_storey = b_storey
        self.assigned_to = assigned_to
        self.a_element_id = a_element_id or str(uuid.uuid4())
        self.b_element_id = b_element_id or str(uuid.uuid4())
        self.meta = meta or {}
        self.id = uuid.uuid4()


def test_max_severity_picks_worst_and_handles_empty():
    assert _max_severity([]) is None
    rows = [_Row(severity="low"), _Row(severity="high"), _Row(severity="medium")]
    assert _max_severity(rows) == "high"
    # Critical beats everything.
    assert _max_severity([*rows, _Row(severity="critical")]) == "critical"
    # Unknown severity degrades to medium (never raises).
    assert _max_severity([_Row(severity="bogus")]) == "medium"


# ── Pure: _build_cluster_action_proposal ───────────────────────────────────


def test_proposal_maps_severity_to_priority_and_titles():
    rows = [
        _Row(a_disc="Mechanical", b_disc="Structural", severity="high", a_storey=3, b_storey=3),
        _Row(a_disc="Mechanical", b_disc="Structural", severity="medium", a_storey=3, b_storey=3),
    ]
    p = _build_cluster_action_proposal(7, rows, "Mechanical × Structural - Level 3", "punchlist")
    assert p["cluster_id"] == 7
    assert p["priority"] == "high"  # worst severity in group
    assert p["max_severity"] == "high"
    assert p["member_count"] == 2
    assert "Mechanical × Structural" in p["title"]
    assert p["storey"] == 3
    assert sorted(p["dominant_disciplines"]) == ["Mechanical", "Structural"]
    # Body lists the representative pairs.
    assert "Duct-1 vs Beam-1" in p["description"]
    # Confidence is bounded and meaningfully high for a clean cluster.
    assert 0.0 <= p["confidence"] <= 1.0
    assert p["confidence"] >= 0.6


def test_proposal_carries_existing_assignee_and_low_confidence_when_mixed():
    rows = [
        _Row(a_disc="Unassigned", b_disc="Unassigned", severity="low", assigned_to="user-42"),
    ]
    p = _build_cluster_action_proposal(1, rows, "", "punchlist")
    assert p["suggested_assignee"] == "user-42"
    assert p["priority"] == "low"
    # No dominant pair, no storey, low severity, tiny → low confidence.
    assert p["confidence"] < 0.6


def test_proposal_truncates_body_for_large_clusters():
    rows = [_Row(a_name=f"A{i}", b_name=f"B{i}") for i in range(12)]
    p = _build_cluster_action_proposal(2, rows, "Mechanical × Structural", "punchlist")
    assert p["member_count"] == 12
    assert "and 7 more" in p["description"]  # 12 - 5 shown = 7


def test_proposal_unknown_target_defaults_to_punchlist():
    p = _build_cluster_action_proposal(1, [_Row()], "lbl", "nonsense")
    assert p["target"] == "punchlist"


# ── DB-backed: propose + create ────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Function-scoped, transaction-isolated AsyncSession (see ``tests/_pg.py``)."""
    from tests._pg import transactional_session

    async with transactional_session() as session:
        yield session


async def _seed_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal user + project + BIM model → ``(project_id, model_id)``."""
    from app.modules.bim_hub.models import BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-act-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash Action Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash Action Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    model = BIMModel(project_id=project.id, name="Action Model", status="ready")
    session.add(model)
    await session.flush()
    return project.id, model.id


async def _seed_cluster(
    session,
    project_id: uuid.UUID,
    model_id: uuid.UUID,
    *,
    cluster_id: int = 1,
    n: int = 3,
    severity: str = "high",
    status: str = "new",
    assigned_to: str | None = None,
) -> uuid.UUID:
    """Insert a completed run with ``n`` clustered results → run id."""
    run = ClashRun(
        project_id=project_id,
        name="Action Run",
        model_ids=[str(model_id)],
        status="completed",
        created_by=str(uuid.uuid4()),
        total_clashes=n,
        element_count=n * 2,
        summary={},
    )
    session.add(run)
    await session.flush()
    for i in range(n):
        session.add(
            ClashResult(
                run_id=run.id,
                a_element_id=uuid.uuid4(),
                b_element_id=uuid.uuid4(),
                a_stable_id=f"A{i}",
                b_stable_id=f"B{i}",
                a_name=f"Duct-{i}",
                b_name=f"Beam-{i}",
                a_discipline="Mechanical",
                b_discipline="Structural",
                a_model_id=model_id,
                b_model_id=model_id,
                clash_type="hard",
                severity=severity,
                status=status,
                assigned_to=assigned_to,
                cluster_id=cluster_id,
            )
        )
    session.add(ClashCluster(run_id=run.id, cluster_id=cluster_id, label="Mechanical × Structural", size=n))
    await session.flush()
    return run.id


@pytest.mark.asyncio
async def test_propose_cluster_action_returns_draft(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id, n=4, severity="critical")
    svc = ClashService(db_session)
    proposal = await svc.propose_cluster_action(project_id, run_id, 1, target="punchlist")
    assert proposal["member_count"] == 4
    assert proposal["priority"] == "critical"
    assert proposal["already_linked"] is False
    assert "Mechanical × Structural" in proposal["title"]


@pytest.mark.asyncio
async def test_propose_unknown_cluster_404(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id)
    svc = ClashService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.propose_cluster_action(project_id, run_id, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_punch_item_links_back_and_advances(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id, n=3, severity="high", status="new")
    svc = ClashService(db_session)
    actor = str(uuid.uuid4())
    result = await svc.create_action_from_cluster(project_id, run_id, 1, target="punchlist", actor=actor)
    assert result["created"] is True
    assert result["action_target"] == "punchlist"
    assert result["results_linked"] == 3
    assert result["results_advanced"] == 3  # all were "new"

    # The punch item exists, in the right project, with the cluster metadata.
    from app.modules.punchlist.models import PunchItem

    punch = await db_session.get(PunchItem, uuid.UUID(result["action_id"]))
    assert punch is not None
    assert punch.project_id == project_id
    assert punch.metadata_["source"] == "clash_cluster"
    assert punch.metadata_["clash_cluster_id"] == 1
    assert punch.clash_result_id  # representative member stamped

    # Every member now carries the reverse link + reviewed status + history.
    members = await svc._cluster_members(run_id, 1)
    assert all(m.status == "reviewed" for m in members)
    for m in members:
        link = m.meta["linked_action"]
        assert link["target"] == "punchlist"
        assert link["action_id"] == result["action_id"]
        assert any(h["field"] == "linked_action" for h in m.history)


@pytest.mark.asyncio
async def test_create_action_is_idempotent(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id, n=2)
    svc = ClashService(db_session)
    first = await svc.create_action_from_cluster(project_id, run_id, 1, target="punchlist")
    second = await svc.create_action_from_cluster(project_id, run_id, 1, target="punchlist")
    assert first["created"] is True
    assert second["created"] is False
    # Same item, no second punch row, no extra status advances.
    assert second["action_id"] == first["action_id"]
    assert second["results_advanced"] == 0

    # Proposal now reports the existing link so the UI can disable confirm.
    proposal = await svc.propose_cluster_action(project_id, run_id, 1)
    assert proposal["already_linked"] is True
    assert proposal["existing_action_id"] == first["action_id"]


@pytest.mark.asyncio
async def test_create_task_target_maps_priority_and_links_elements(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id, n=2, severity="critical")
    svc = ClashService(db_session)
    result = await svc.create_action_from_cluster(
        project_id, run_id, 1, target="task", title="Resolve MEP/Struct group"
    )
    assert result["created"] is True
    assert result["action_target"] == "task"

    from app.modules.tasks.models import Task

    task = await db_session.get(Task, uuid.UUID(result["action_id"]))
    assert task is not None
    assert task.project_id == project_id
    assert task.task_type == "coordination"
    assert task.title == "Resolve MEP/Struct group"
    # critical clash → urgent task priority.
    assert task.priority == "urgent"
    # Member element ids carried into the task BIM link.
    assert len(task.bim_element_ids) == 4  # 2 results × (a + b)
    assert task.metadata_["clash_run_id"] == str(run_id)


@pytest.mark.asyncio
async def test_create_action_can_skip_status_advance(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id, n=2, status="new")
    svc = ClashService(db_session)
    result = await svc.create_action_from_cluster(project_id, run_id, 1, target="punchlist", advance_status=False)
    assert result["results_linked"] == 2
    assert result["results_advanced"] == 0
    members = await svc._cluster_members(run_id, 1)
    assert all(m.status == "new" for m in members)  # untouched
    # Link still stamped even when status is not advanced.
    assert all("linked_action" in m.meta for m in members)


@pytest.mark.asyncio
async def test_create_action_unknown_target_422(db_session):
    project_id, model_id = await _seed_project(db_session)
    run_id = await _seed_cluster(db_session, project_id, model_id)
    svc = ClashService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_action_from_cluster(project_id, run_id, 1, target="email")
    assert exc.value.status_code == 422
