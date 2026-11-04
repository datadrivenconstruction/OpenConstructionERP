"""Transmittal rules: each rule fires, a valid record passes, errors block the write with a code."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext
from app.modules.projects.models import Project
from app.modules.transmittals.schemas import ItemCreate, RecipientCreate, TransmittalCreate, TransmittalUpdate
from app.modules.transmittals.service import TransmittalService
from app.modules.transmittals.validators import (
    TRANSMITTALS_RULES,
    ActionNeedsDeadlineRule,
    ItemIdentifiesDocumentRule,
    RecipientIdentifiedRule,
    UniqueItemNumbersRule,
    register_transmittals_validation_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


def _data(*, issuing: bool = True, due: str | None = "2026-12-01", recipients=None, items=None) -> dict:
    return {
        "transmittal": {"id": "t1", "issuing": issuing, "response_due_date": due},
        "recipients": recipients
        if recipients is not None
        else [{"recipient_email": "a@b.io", "action_required": "review"}],
        "items": items if items is not None else [{"item_number": 1, "description": "GA plan"}],
    }


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


FIRING = [
    (
        UniqueItemNumbersRule,
        _data(items=[{"item_number": 2, "description": "x"}, {"item_number": 2, "description": "y"}]),
    ),
    (ItemIdentifiesDocumentRule, _data(items=[{"item_number": 1}])),
    (RecipientIdentifiedRule, _data(recipients=[{"action_required": "review"}])),
    (ActionNeedsDeadlineRule, _data(due=None)),
]


@pytest.mark.parametrize(("rule_class", "data"), FIRING)
async def test_each_rule_fires(rule_class, data) -> None:
    results = await _run(rule_class(), data)
    failed = [r for r in results if not r.passed]
    assert failed
    assert "transmittals." not in failed[0].message  # translated, not a raw key
    assert failed[0].suggestion


@pytest.mark.parametrize("rule_class", TRANSMITTALS_RULES)
async def test_a_complete_record_passes_every_rule(rule_class) -> None:
    assert all(r.passed for r in await _run(rule_class(), _data()))


@pytest.mark.parametrize("rule_class", TRANSMITTALS_RULES)
async def test_a_draft_with_partial_lines_passes_the_issue_rules(rule_class) -> None:
    draft = _data(issuing=False, due=None, recipients=[{"action_required": "review"}], items=[{"item_number": 1}])
    assert all(r.passed for r in await _run(rule_class(), draft))


async def test_messages_follow_the_locale() -> None:
    de = await _run(ItemIdentifiesDocumentRule(), _data(items=[{"item_number": 4}]), locale="de")
    assert "Position 4" in de[0].message


@pytest_asyncio.fixture
async def session():
    register_transmittals_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"tr-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(s) -> uuid.UUID:
    p = Project(id=uuid.uuid4(), name="Tower", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    s.add(p)
    await s.flush()
    return p.id


async def test_duplicate_line_numbers_block_create_with_code(session) -> None:
    pid = await _project(session)
    data = TransmittalCreate(
        project_id=pid,
        subject="Issue",
        purpose_code="for_review",
        items=[ItemCreate(item_number=1, description="a"), ItemCreate(item_number=1, description="b")],
    )
    with pytest.raises(HTTPException) as exc:
        await TransmittalService(session).create_transmittal(data)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "transmittals.unique_item_numbers"


async def test_a_blank_line_blocks_issue_but_not_the_draft(session) -> None:
    pid = await _project(session)
    svc = TransmittalService(session)
    created = await svc.create_transmittal(
        TransmittalCreate(
            project_id=pid,
            subject="Issue",
            purpose_code="for_review",
            recipients=[RecipientCreate(recipient_email="a@b.io")],
            items=[ItemCreate(item_number=1)],
        )
    )
    tid = created.id
    with pytest.raises(HTTPException) as exc:
        await svc.issue_transmittal(tid)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "transmittals.item_identifies_document"

    await svc.update_transmittal(tid, TransmittalUpdate(items=[ItemCreate(item_number=1, description="GA plan")]))
    session.expire_all()
    issued = await svc.issue_transmittal(tid)
    assert issued.is_locked


async def test_an_action_without_a_date_is_reported_not_blocking(session) -> None:
    pid = await _project(session)
    svc = TransmittalService(session)
    created = await svc.create_transmittal(
        TransmittalCreate(
            project_id=pid,
            subject="Issue",
            purpose_code="for_review",
            recipients=[RecipientCreate(recipient_email="a@b.io", action_required="approve")],
            items=[ItemCreate(item_number=1, description="GA plan")],
        )
    )
    issued = await svc.issue_transmittal(created.id)
    assert issued.is_locked
    assert [f["code"] for f in svc.findings] == ["transmittals.action_needs_deadline"]
