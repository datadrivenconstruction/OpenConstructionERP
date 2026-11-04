# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The ``postcalc`` rule set runs at the report write point: errors block, warnings travel."""

from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.postcalc.service import PostCalcService, compute_project_postcalc
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _project(session) -> uuid.UUID:
    user = User(email=f"pc-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="Pc", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"Pc {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


def _line(ref: str, hours: str = "1") -> dict:
    return {
        "ref": ref,
        "position_id": str(uuid.uuid4()),
        "description": "Wall",
        "unit": "m2",
        "currency": "EUR",
        "planned_quantity": Decimal("10"),
        "planned_cost": Decimal("1000"),
        "resources": [{"type": "labor", "unit": "h", "quantity": hours, "unit_rate": "40", "total": "40"}],
        "actual_quantity": Decimal("5"),
        "actual_labour_hours": Decimal("4"),
        "actual_plant_hours": Decimal("0"),
        "actual_labour_cost": Decimal("160"),
        "actual_plant_cost": None,
        "actual_material_cost": None,
    }


def _stub(monkeypatch, report) -> None:
    async def fake(self, project_id, **kw):
        return report

    monkeypatch.setattr(PostCalcService, "generate", fake)


async def test_valid_report_passes_without_findings(session, monkeypatch) -> None:
    pid = await _project(session)
    report = compute_project_postcalc([_line("01.001"), _line("01.002")], currency="EUR")
    _stub(monkeypatch, report)
    got, warnings = await PostCalcService(session).generate_checked(pid)
    assert got is report
    assert warnings == []


async def test_real_empty_project_passes(session) -> None:
    pid = await _project(session)
    report, warnings = await PostCalcService(session).generate_checked(pid)
    assert report.line_count == 0
    assert warnings == []


async def test_blocking_rule_rejects_with_its_code(session, monkeypatch) -> None:
    pid = await _project(session)
    report = compute_project_postcalc([_line("01.001")], currency="EUR")
    _stub(monkeypatch, dataclasses.replace(report, line_count=report.line_count + 5))
    with pytest.raises(HTTPException) as exc:
        await PostCalcService(session).generate_checked(pid)
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["error"] == "postcalc_validation_failed"
    assert "postcalc.rollup_matches_lines" in {r["rule_id"] for r in detail["results"]}


async def test_blank_line_reference_warns_not_blocks(session, monkeypatch) -> None:
    pid = await _project(session)
    _stub(monkeypatch, compute_project_postcalc([_line("")], currency="EUR"))
    _, warnings = await PostCalcService(session).generate_checked(pid)
    assert "postcalc.references_present" in {w["rule_id"] for w in warnings}


async def test_project_without_currency_warns_not_blocks(session, monkeypatch) -> None:
    pid = await _project(session)
    line = {**_line("01.001"), "currency": ""}
    _stub(monkeypatch, compute_project_postcalc([line], currency=""))
    _, warnings = await PostCalcService(session).generate_checked(pid)
    assert "postcalc.currency_consistent" in {w["rule_id"] for w in warnings}


async def test_implausible_factor_is_a_warning_not_a_block(session, monkeypatch) -> None:
    pid = await _project(session)
    report = compute_project_postcalc([_line("01.001")], currency="EUR")
    line = dataclasses.replace(report.lines[0], productivity_factor=Decimal("25"))
    _stub(monkeypatch, dataclasses.replace(report, lines=[line]))
    got, warnings = await PostCalcService(session).generate_checked(pid)
    assert got.lines[0].productivity_factor == Decimal("25")
    assert [w["rule_id"] for w in warnings] == ["postcalc.values_in_range"]
    assert warnings[0]["severity"] == "warning"
