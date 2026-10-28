"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap D module tests: ``CostModelService.set_overrun_alert_threshold``.

Exercised directly against a real PostgreSQL session wrapped in a per-test
transaction that is rolled back on teardown (canonical ``transactional_session``).

Covers TEST MATRIX cases 5-7 at the service layer:
    5  set threshold success     (valid % -> stored, 200 at the router)
    6  set threshold validation  (out-of-range / non-finite -> 400)
    7  set threshold not found    (missing line -> 404)

Case 8 (missing permission -> 403) is enforced by the router dependency
``RequirePermission("costmodel.write")`` on the endpoint and is not re-tested at
the service layer (the service has no auth concern).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine
from app.modules.costmodel.service import CostModelService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed_project(session: AsyncSession, *, owner: bool = True) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner_id = None
    if owner:
        user = User(
            id=uuid.uuid4(),
            email=f"gapd-{uuid.uuid4().hex[:10]}@overrun.io",
            hashed_password="x",
            full_name="Gap D Owner",
            role="admin",
        )
        session.add(user)
        await session.flush()
        owner_id = user.id

    project = Project(
        id=uuid.uuid4(),
        name="Gap D project",
        owner_id=owner_id,
        currency="EUR",
        fx_rates=[],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_budget_line(session: AsyncSession, project_id: uuid.UUID) -> BudgetLine:
    line = BudgetLine(
        project_id=project_id,
        category="material",
        description="RC wall",
        planned_amount="1000",
        committed_amount="0",
        actual_amount="0",
        forecast_amount="1000",
        currency="EUR",
    )
    session.add(line)
    await session.flush()
    return line


# ── Case 5: success ─────────────────────────────────────────────────────────────


async def test_set_threshold_success(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    updated = await svc.set_overrun_alert_threshold(line.id, 20)
    assert updated.overrun_alert_threshold_pct == "20"


async def test_set_threshold_fractional_normalised(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    updated = await svc.set_overrun_alert_threshold(line.id, 12.5)
    assert updated.overrun_alert_threshold_pct == "12.5"


async def test_set_threshold_zero_disables(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    await svc.set_overrun_alert_threshold(line.id, 30)
    updated = await svc.set_overrun_alert_threshold(line.id, 0)
    assert updated.overrun_alert_threshold_pct == "0"


# ── Case 6: validation (out of range / non-finite) ──────────────────────────────


@pytest.mark.parametrize("bad", [-1, 101, 500, float("inf"), float("nan")])
async def test_set_threshold_validation(session: AsyncSession, bad: float) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.set_overrun_alert_threshold(line.id, bad)
    assert exc.value.status_code == 400


# ── Case 7: not found ───────────────────────────────────────────────────────────


async def test_set_threshold_not_found(session: AsyncSession) -> None:
    svc = CostModelService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.set_overrun_alert_threshold(uuid.uuid4(), 10)
    assert exc.value.status_code == 404


# ── Extra: arming a threshold re-publishes budget_line.updated ──────────────────


async def test_set_threshold_publishes_updated(session: AsyncSession, monkeypatch) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    captured: list[tuple[str, dict]] = []

    async def _fake_publish(name: str, data: dict, source_module: str = "") -> None:
        captured.append((name, data))

    monkeypatch.setattr("app.modules.costmodel.service._safe_publish", _fake_publish)

    await svc.set_overrun_alert_threshold(line.id, 10)

    assert any(name == "costmodel.budget_line.updated" for name, _ in captured)
    _, data = next((n, d) for n, d in captured if n == "costmodel.budget_line.updated")
    assert data["line_id"] == str(line.id)
    assert data["fields"] == ["overrun_alert_threshold_pct"]


# ── Extra: stored value really persists as a string in the column ───────────────


async def test_set_threshold_persists_decimal_string(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    line = await _seed_budget_line(session, project_id)
    svc = CostModelService(session)

    await svc.set_overrun_alert_threshold(line.id, 25)
    reloaded = await svc.budget_repo.get_by_id(line.id)
    assert reloaded is not None
    assert reloaded.overrun_alert_threshold_pct == "25"
    # And it round-trips back to the expected Decimal.
    assert Decimal(reloaded.overrun_alert_threshold_pct) == Decimal("25")
