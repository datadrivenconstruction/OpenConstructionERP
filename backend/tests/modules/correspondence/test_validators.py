"""Correspondence rules: each rule fires, a valid record passes, errors block the write with a code."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext
from app.modules.correspondence.schemas import CorrespondenceCreate, CorrespondenceUpdate
from app.modules.correspondence.service import CorrespondenceService
from app.modules.correspondence.validators import (
    CORRESPONDENCE_RULES,
    NoticeCitesClauseRule,
    ReceivedNotBeforeSentRule,
    ResponseDeadlineAfterNoticeRule,
    register_correspondence_validation_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


def _rec(**kw: object) -> dict:
    base = {
        "id": "c1",
        "direction": "incoming",
        "correspondence_type": "letter",
        "date_sent": "2026-03-01",
        "date_received": "2026-03-03",
        "response_required_by": "2026-03-17",
        "contract_clause_ref": None,
    }
    base.update(kw)
    return {"correspondence": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


FIRING = [
    (ReceivedNotBeforeSentRule, _rec(date_received="2026-02-27")),
    (ResponseDeadlineAfterNoticeRule, _rec(response_required_by="2026-03-02")),
    (NoticeCitesClauseRule, _rec(correspondence_type="notice")),
]


@pytest.mark.parametrize(("rule_class", "data"), FIRING)
async def test_each_rule_fires(rule_class, data) -> None:
    failed = [r for r in await _run(rule_class(), data) if not r.passed]
    assert failed
    assert "correspondence." not in failed[0].message
    assert failed[0].suggestion


@pytest.mark.parametrize("rule_class", CORRESPONDENCE_RULES)
async def test_a_valid_record_passes_every_rule(rule_class) -> None:
    data = _rec(correspondence_type="notice", contract_clause_ref="20.2.1")
    assert all(r.passed for r in await _run(rule_class(), data))


@pytest.mark.parametrize("rule_class", CORRESPONDENCE_RULES)
async def test_a_partial_record_does_not_trip_a_rule(rule_class) -> None:
    partial = _rec(date_sent=None, date_received=None, response_required_by=None)
    assert all(r.passed for r in await _run(rule_class(), partial))


async def test_an_outgoing_deadline_counts_from_the_day_sent() -> None:
    data = _rec(direction="outgoing", date_sent="2026-03-10", date_received=None, response_required_by="2026-03-09")
    assert any(not r.passed for r in await _run(ResponseDeadlineAfterNoticeRule(), data))


async def test_messages_follow_the_locale() -> None:
    de = await _run(NoticeCitesClauseRule(), _rec(correspondence_type="notice"), locale="de")
    assert "Vertragsklausel" in de[0].message


@pytest_asyncio.fixture
async def session():
    register_correspondence_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"co-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(s) -> uuid.UUID:
    p = Project(id=uuid.uuid4(), name="Tower", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    s.add(p)
    await s.flush()
    return p.id


def _create(pid: uuid.UUID, **kw: object) -> CorrespondenceCreate:
    base = {
        "project_id": pid,
        "direction": "incoming",
        "subject": "Instruction",
        "correspondence_type": "letter",
        "date_sent": "2026-03-01",
        "date_received": "2026-03-03",
    }
    base.update(kw)
    return CorrespondenceCreate(**base)


async def test_a_letter_received_before_it_was_sent_is_refused_with_its_code(session) -> None:
    pid = await _project(session)
    with pytest.raises(HTTPException) as exc:
        await CorrespondenceService(session).create_correspondence(_create(pid, date_received="2026-02-20"))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "correspondence.received_not_before_sent"


async def test_an_update_is_checked_against_the_stored_dates(session) -> None:
    pid = await _project(session)
    svc = CorrespondenceService(session)
    rec = await svc.create_correspondence(_create(pid))
    with pytest.raises(HTTPException) as exc:
        await svc.update_correspondence(rec.id, CorrespondenceUpdate(response_required_by="2026-03-01"))
    assert exc.value.detail["code"] == "correspondence.response_deadline_after_notice"
    ok = await svc.update_correspondence(rec.id, CorrespondenceUpdate(response_required_by="2026-03-20"))
    assert ok.response_required_by == "2026-03-20"


async def test_a_notice_without_a_clause_is_saved_with_a_warning(session) -> None:
    pid = await _project(session)
    svc = CorrespondenceService(session)
    rec = await svc.create_correspondence(_create(pid, correspondence_type="notice"))
    assert rec.id
    assert [f["code"] for f in svc.findings] == ["correspondence.notice_cites_clause"]
