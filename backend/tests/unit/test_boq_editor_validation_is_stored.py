# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Validate button in the BOQ editor leaves a stored report behind.

``POST /boq/boqs/{id}/validate/`` used to return the engine summary and store
nothing. Every reader of validation (the validation page, the dashboard, the
cross-project status) reads stored reports, so an estimate an estimator had
just checked read "never validated" everywhere else.

What has to hold:

* a caller who may create validation reports gets a stored report, in the
  same shape a validation page run writes, and the cross-project status picks
  it up;
* a viewer can still run the check, but nothing is written;
* no NCR escalation is published from the editor path (one NCR per click
  would bury the register).

Run:  pytest tests/unit/test_boq_editor_validation_is_stored.py
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.validation.engine import RuleCategory, RuleResult, Severity
from app.core.validation.engine import ValidationReport as EngineReport
from app.modules.boq.router import _store_editor_validation
from app.modules.validation.portfolio import STATE_ERRORS, build_portfolio_status
from tests._pg import transactional_session

EDITOR = {"role": "editor", "permissions": ["boq.read", "validation.create"]}
VIEWER = {"role": "viewer", "permissions": ["boq.read"]}


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _seed(session):
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"edval-{uuid.uuid4().hex[:10]}@test.io",
        hashed_password="x",
        full_name="Editor Validation",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Editor run", owner_id=user.id, status="active", currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main bill", status="draft")
    session.add(boq)
    await session.flush()
    return user, project, boq


def _engine_report(boq_id: uuid.UUID) -> EngineReport:
    def _result(rule_id: str, *, passed: bool, severity: Severity) -> RuleResult:
        return RuleResult(
            rule_id=rule_id,
            rule_name=rule_id,
            severity=severity,
            category=RuleCategory.QUALITY,
            passed=passed,
            message="ok" if passed else "missing quantity",
        )

    return EngineReport(
        target_type="boq",
        target_id=str(boq_id),
        rule_sets_applied=["boq_quality", "gaeb"],
        unsupported_rule_sets=["gaeb"],
        results=[
            _result("boq_quality.quantity_missing", passed=False, severity=Severity.ERROR),
            _result("boq_quality.unit_present", passed=True, severity=Severity.ERROR),
            _result("boq_quality.rate_anomaly", passed=False, severity=Severity.WARNING),
        ],
    )


async def _report_count(session, boq_id: uuid.UUID) -> int:
    from app.modules.validation.models import ValidationReport

    stmt = select(func.count()).select_from(ValidationReport).where(ValidationReport.target_id == str(boq_id))
    return int((await session.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_an_editor_run_is_stored_and_shows_on_the_cross_project_status(session) -> None:
    from app.modules.validation.models import ValidationReport

    user, project, boq = await _seed(session)
    report_id = await _store_editor_validation(
        session, project.id, boq.id, _engine_report(boq.id), ["boq_quality", "gaeb"], str(user.id), EDITOR
    )

    assert report_id is not None
    stored = await session.get(ValidationReport, uuid.UUID(report_id))
    assert stored is not None
    assert stored.target_type == "boq"
    assert stored.target_id == str(boq.id)
    assert stored.project_id == project.id
    assert stored.status == "errors"
    assert (stored.error_count, stored.warning_count, stored.passed_count, stored.total_rules) == (1, 1, 1, 3)
    assert stored.created_by == user.id
    assert stored.metadata_["source"] == "boq_editor"
    assert stored.metadata_["supported_rule_sets"] == ["boq_quality"]
    assert stored.metadata_["unsupported_rule_sets"] == ["gaeb"]
    assert len(stored.results) == 3

    (row,) = (await build_portfolio_status(session, str(user.id))).projects
    (est,) = row.estimates
    assert est.report_id == stored.id
    assert est.state == STATE_ERRORS
    # GAEB was asked for but had no rule to run, so it is not shown as run.
    assert est.rule_sets == ["boq_quality"]


@pytest.mark.asyncio
async def test_a_viewer_run_stores_nothing(session) -> None:
    user, project, boq = await _seed(session)
    report_id = await _store_editor_validation(
        session, project.id, boq.id, _engine_report(boq.id), ["boq_quality"], str(user.id), VIEWER
    )

    assert report_id is None
    assert await _report_count(session, boq.id) == 0


@pytest.mark.asyncio
async def test_each_editor_run_is_its_own_report(session) -> None:
    user, project, boq = await _seed(session)
    first = await _store_editor_validation(
        session, project.id, boq.id, _engine_report(boq.id), ["boq_quality"], str(user.id), EDITOR
    )
    second = await _store_editor_validation(
        session, project.id, boq.id, _engine_report(boq.id), ["boq_quality"], str(user.id), EDITOR
    )

    assert first and second and first != second
    assert await _report_count(session, boq.id) == 2


@pytest.mark.asyncio
async def test_an_editor_run_with_errors_raises_no_ncr_escalation(session, monkeypatch) -> None:
    import app.core.events as events

    published: list[str] = []
    real_detached = events.event_bus.publish_detached

    def _after_commit(_session, name, *_a, **_k) -> None:
        published.append(name)

    def _detached(name, *a, **k):
        published.append(name)
        return real_detached(name, *a, **k)

    monkeypatch.setattr(events, "publish_after_commit", _after_commit)
    monkeypatch.setattr(events.event_bus, "publish_detached", _detached)

    user, project, boq = await _seed(session)
    report_id = await _store_editor_validation(
        session, project.id, boq.id, _engine_report(boq.id), ["boq_quality"], str(user.id), EDITOR
    )

    assert report_id is not None
    assert "validation.report.created" in published
    assert "validation.results.errors_found" not in published
