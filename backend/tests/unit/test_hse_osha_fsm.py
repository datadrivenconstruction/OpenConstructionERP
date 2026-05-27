# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE — OSHA 300 CSV export + slim CorrectiveAction FSM tests.

Covers
~~~~~~
* OSHA 300 CSV: only ``osha_recordable=True`` rows in the requested year
  appear; the header is the canonical 10-column row.
* FSM happy path: pending → in_progress → verified → closed, with
  ``verified_by_user_id`` + ``verified_at`` stamped on the
  ``in_progress → verified`` hop.
* FSM bad transition: pending → verified directly raises HTTP 409 with a
  message that names the rejected hop.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-hse-osha-"))
_TMP_DB = _TMP_DIR / "hse-osha.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402

PROJECT_ID = uuid.uuid4()


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """An ``AsyncSession`` over a freshly ``create_all``'d temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()

    # Eagerly import every module package so all model tables are in
    # ``Base.metadata`` before ``create_all`` runs (avoids dangling FKs).
    import importlib
    import pkgutil

    import app.modules as _modules_pkg

    for _m in pkgutil.iter_modules(_modules_pkg.__path__):
        if not _m.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{_m.name}.models")
        except ModuleNotFoundError:
            continue

    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


# ── OSHA 300 CSV ──────────────────────────────────────────────────────────


async def _make_user(db_session) -> uuid.UUID:
    """Insert a stub user row so projects/FK references resolve."""
    from app.modules.users.models import User

    user = User(
        email=f"hse-osha-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="HSE OSHA Tester",
    )
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _make_project(db_session) -> uuid.UUID:
    """Insert a stub project row so FKs from ``oe_safety_incident`` resolve."""
    from app.modules.projects.models import Project

    owner_id = await _make_user(db_session)
    proj = Project(
        name=f"HSE OSHA test {uuid.uuid4().hex[:8]}",
        description="Synthetic project for OSHA 300 / CA FSM tests",
        owner_id=owner_id,
    )
    db_session.add(proj)
    await db_session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_osha_300_csv_filters_recordable_and_year(db_session) -> None:
    """Only recordable rows in the requested year render; header is exact."""
    from app.modules.hse_advanced.service import HSEAdvancedService
    from app.modules.safety.models import SafetyIncident

    project_id = await _make_project(db_session)

    recordable = SafetyIncident(
        project_id=project_id,
        incident_number="INC-001",
        title="Hand laceration",
        incident_date="2026-04-15",
        location="Site A",
        incident_type="injury",
        severity="moderate",
        description="Worker cut hand on rebar",
        treatment_type="medical",
        days_lost=3,
        osha_recordable=True,
        osha_case_number="OSHA-2026-001",
        days_away=3,
        days_restricted=0,
        injured_person_details={"name": "Jane Doe", "role": "Welder"},
    )
    not_recordable = SafetyIncident(
        project_id=project_id,
        incident_number="INC-002",
        title="Near miss",
        incident_date="2026-04-20",
        location="Site B",
        incident_type="near_miss",
        severity="minor",
        description="Dropped wrench, nobody hurt",
        osha_recordable=False,
    )
    # Recordable but wrong year — also filtered out.
    wrong_year = SafetyIncident(
        project_id=project_id,
        incident_number="INC-003",
        title="2025 fall",
        incident_date="2025-11-10",
        location="Site C",
        incident_type="injury",
        severity="moderate",
        description="Slip, sprained ankle",
        treatment_type="medical",
        osha_recordable=True,
        osha_case_number="OSHA-2025-002",
        days_away=2,
    )
    db_session.add_all([recordable, not_recordable, wrong_year])
    await db_session.flush()

    svc = HSEAdvancedService(db_session)
    body = await svc.generate_osha_300_csv(project_id, 2026)

    reader = csv.reader(io.StringIO(body))
    rows = list(reader)

    # First line is the canonical header.
    assert rows[0] == [
        "case_no",
        "employee_name",
        "job_title",
        "date_of_injury",
        "location",
        "description_of_injury",
        "days_away",
        "days_restricted",
        "death_yes_no",
        "other_recordable_yes_no",
    ]
    # Exactly one data row — the recordable 2026 incident.
    assert len(rows) == 2
    data = rows[1]
    assert data[0] == "OSHA-2026-001"
    assert data[1] == "Jane Doe"
    assert data[2] == "Welder"
    assert data[3] == "2026-04-15"
    assert data[4] == "Site A"
    assert data[5] == "Worker cut hand on rebar"
    assert data[6] == "3"
    assert data[7] == "0"
    assert data[8] == "N"  # not a fatality
    assert data[9] == "N"  # days_away > 0 → not "other recordable"


# ── Slim CorrectiveAction FSM ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_corrective_action_fsm_happy_path(db_session) -> None:
    """pending → in_progress → verified → closed, with verifier stamped."""
    from app.modules.hse_advanced.service import HSEAdvancedService

    svc = HSEAdvancedService(db_session)
    incident_id = uuid.uuid4()
    verifier_id = await _make_user(db_session)

    ca = await svc.create_corrective_action(
        incident_id=incident_id,
        description="Replace damaged extension cord and retrain crew",
    )
    assert ca.status == "pending"
    assert ca.verified_at is None
    assert ca.verified_by_user_id is None

    ca = await svc.transition_corrective_action(
        ca.id,
        "in_progress",
        user_id=None,
    )
    assert ca.status == "in_progress"
    assert ca.verified_at is None

    ca = await svc.transition_corrective_action(
        ca.id,
        "verified",
        user_id=verifier_id,
        verification_notes="Inspected on 2026-05-19, defect resolved",
    )
    assert ca.status == "verified"
    assert ca.verified_at is not None
    assert ca.verified_by_user_id == verifier_id
    # ``verification_notes`` carries our entry (timestamp-prefixed).
    assert ca.verification_notes is not None
    assert "Inspected on 2026-05-19" in ca.verification_notes

    ca = await svc.transition_corrective_action(
        ca.id,
        "closed",
        user_id=verifier_id,
    )
    assert ca.status == "closed"
    # verified_at must survive subsequent transitions for the audit trail.
    assert ca.verified_at is not None


@pytest.mark.asyncio
async def test_corrective_action_fsm_rejects_skip_transition(db_session) -> None:
    """pending → verified (skipping in_progress) raises HTTP 409."""
    from app.modules.hse_advanced.service import HSEAdvancedService

    svc = HSEAdvancedService(db_session)
    ca = await svc.create_corrective_action(
        incident_id=uuid.uuid4(),
        description="Replace ladder feet",
    )
    assert ca.status == "pending"

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_corrective_action(
            ca.id,
            "verified",
            user_id=None,
        )
    assert exc_info.value.status_code == 409
    detail = str(exc_info.value.detail)
    # Error message must name both the from-state and the rejected hop so
    # the UI can render a clear actionable error.
    assert "pending" in detail
    assert "verified" in detail


@pytest.mark.asyncio
async def test_corrective_action_fsm_rejects_backwards(db_session) -> None:
    """A closed CA cannot reopen — terminal state has no allowed exits."""
    from app.modules.hse_advanced.service import HSEAdvancedService

    svc = HSEAdvancedService(db_session)
    ca = await svc.create_corrective_action(
        incident_id=uuid.uuid4(),
        description="Audit fall-protection anchor points",
    )
    verifier_id = await _make_user(db_session)
    await svc.transition_corrective_action(ca.id, "in_progress", user_id=None)
    await svc.transition_corrective_action(
        ca.id,
        "verified",
        user_id=verifier_id,
    )
    await svc.transition_corrective_action(ca.id, "closed", user_id=None)

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_corrective_action(
            ca.id,
            "in_progress",
            user_id=None,
        )
    assert exc_info.value.status_code == 409


def test_allowed_transitions_table() -> None:
    """Pure helper exposes the exact FSM the service enforces."""
    from app.modules.hse_advanced.service import (
        allowed_corrective_action_transitions,
    )

    assert allowed_corrective_action_transitions("pending") == ["in_progress"]
    assert allowed_corrective_action_transitions("in_progress") == ["verified"]
    assert allowed_corrective_action_transitions("verified") == ["closed"]
    assert allowed_corrective_action_transitions("closed") == []
    # Unknown state → empty list (defensive).
    assert allowed_corrective_action_transitions("nonsense") == []
