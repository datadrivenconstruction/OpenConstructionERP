"""Temporary works rules: each rule fires, a valid record passes, errors block the write with a code."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext
from app.modules.projects.models import Project
from app.modules.temporary_works.schemas import (
    TemporaryWorksItemCreate,
    TemporaryWorksItemUpdate,
    TemporaryWorksPermitCreate,
)
from app.modules.temporary_works.service import TemporaryWorksService
from app.modules.temporary_works.validators import (
    TEMPORARY_WORKS_RULES,
    CoordinatorAssignedRule,
    DatesInOrderRule,
    IndependentCheckRule,
    PermitToLoadPrerequisitesRule,
    PermitValidityWindowRule,
    register_temporary_works_validation_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


def _item(**kw: object) -> dict:
    base = {
        "id": "i1",
        "status": "approved_to_load",
        "design_check_category": "2",
        "designer_name": "A. Designer",
        "checker_name": "B. Checker",
        "twc_name": "C. Coordinator",
        "twc_user_id": None,
        "required_load_date": "2026-05-01",
        "required_strike_date": "2026-06-01",
        "design_due_date": "2026-04-01",
    }
    base.update(kw)
    return {"item": base}


def _permit(**kw: object) -> dict:
    base = {
        "id": "p1",
        "permit_type": "permit_to_load",
        "status": "issued",
        "issued_at": "2026-04-28",
        "valid_from": "2026-05-01",
        "valid_to": "2026-06-01",
        "closed_at": None,
        "prereq_design_check_accepted": True,
        "prereq_inspection_passed": True,
    }
    base.update(kw)
    return {"permit": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


FIRING = [
    (IndependentCheckRule, _item(checker_name=None)),
    (IndependentCheckRule, _item(checker_name="a. designer")),
    (CoordinatorAssignedRule, _item(twc_name=" ")),
    (DatesInOrderRule, _item(required_strike_date="2026-04-15")),
    (DatesInOrderRule, _item(design_due_date="2026-05-20")),
    (PermitValidityWindowRule, _permit(valid_to="2026-04-01")),
    (PermitValidityWindowRule, _permit(closed_at="2026-04-01")),
    (PermitToLoadPrerequisitesRule, _permit(prereq_design_check_accepted=False)),
    (PermitToLoadPrerequisitesRule, _permit(prereq_inspection_passed=False)),
]


@pytest.mark.parametrize(("rule_class", "data"), FIRING)
async def test_each_rule_fires(rule_class, data) -> None:
    failed = [r for r in await _run(rule_class(), data) if not r.passed]
    assert failed
    assert "temporary_works." not in failed[0].message
    assert failed[0].suggestion


@pytest.mark.parametrize("rule_class", TEMPORARY_WORKS_RULES)
async def test_a_valid_record_passes_every_rule(rule_class) -> None:
    for data in (_item(), _permit()):
        assert all(r.passed for r in await _run(rule_class(), data))


@pytest.mark.parametrize("rule_class", TEMPORARY_WORKS_RULES)
async def test_an_early_stage_record_is_not_flagged(rule_class) -> None:
    early_item = _item(status="identified", checker_name=None, twc_name=None, required_load_date=None)
    early_permit = _permit(status="draft", prereq_design_check_accepted=False, prereq_inspection_passed=False)
    for data in (early_item, early_permit):
        assert all(r.passed for r in await _run(rule_class(), data))


async def test_a_category_one_design_needs_no_independent_checker() -> None:
    assert all(
        r.passed for r in await _run(IndependentCheckRule(), _item(design_check_category="1", checker_name=None))
    )


async def test_the_late_design_is_a_warning_not_an_error() -> None:
    failed = [r for r in await _run(DatesInOrderRule(), _item(design_due_date="2026-05-20")) if not r.passed]
    assert [str(r.severity) for r in failed] == ["warning"]


async def test_messages_follow_the_locale() -> None:
    ru = await _run(CoordinatorAssignedRule(), _item(twc_name=None), locale="ru")
    assert "координатор" in ru[0].message


@pytest_asyncio.fixture
async def session():
    register_temporary_works_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"tw-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(s) -> uuid.UUID:
    p = Project(id=uuid.uuid4(), name="Tower", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    s.add(p)
    await s.flush()
    return p.id


def _create(**kw: object) -> TemporaryWorksItemCreate:
    base = {"reference": f"TW-{uuid.uuid4().hex[:6]}", "title": "Slab propping", "tw_type": "propping"}
    base.update(kw)
    return TemporaryWorksItemCreate(**base)


async def test_a_checked_category_3_design_without_a_checker_is_refused_with_its_code(session) -> None:
    pid = await _project(session)
    with pytest.raises(HTTPException) as exc:
        await TemporaryWorksService(session).create_item(
            pid, _create(status="design_checked", design_check_category="3", designer_name="A"), None
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "temporary_works.independent_check"


async def test_an_update_is_checked_against_the_stored_item(session) -> None:
    pid = await _project(session)
    svc = TemporaryWorksService(session)
    item = await svc.create_item(pid, _create(design_check_category="2", designer_name="A", checker_name="B"), None)
    with pytest.raises(HTTPException) as exc:
        await svc.update_item(pid, item.id, TemporaryWorksItemUpdate(status="approved_to_load"))
    assert exc.value.detail["code"] == "temporary_works.coordinator_assigned"
    ok = await svc.update_item(pid, item.id, TemporaryWorksItemUpdate(status="approved_to_load", twc_name="C"))
    assert ok.status == "approved_to_load"


async def test_a_permit_to_load_without_prerequisites_is_refused_but_a_draft_is_saved(session) -> None:
    pid = await _project(session)
    svc = TemporaryWorksService(session)
    item = await svc.create_item(pid, _create(), None)
    with pytest.raises(HTTPException) as exc:
        await svc.create_permit(
            pid,
            item.id,
            TemporaryWorksPermitCreate(permit_number="PL-1", permit_type="permit_to_load", status="issued"),
            None,
        )
    assert exc.value.detail["code"] == "temporary_works.permit_to_load_prerequisites"
    draft = await svc.create_permit(
        pid, item.id, TemporaryWorksPermitCreate(permit_number="PL-2", permit_type="permit_to_load"), None
    )
    assert draft.status == "draft"


async def test_a_late_design_is_saved_with_a_warning(session) -> None:
    pid = await _project(session)
    svc = TemporaryWorksService(session)
    await svc.create_item(pid, _create(required_load_date="2026-05-01", design_due_date="2026-05-20"), None)
    assert [f["code"] for f in svc.findings] == ["temporary_works.dates_in_order"]
