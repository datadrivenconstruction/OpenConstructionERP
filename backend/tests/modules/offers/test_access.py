"""Text and position routes refuse a caller from another project with 404 and write nothing."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.offers import router as offers_router
from app.modules.offers.models import OfferTextBlock
from app.modules.offers.schemas import PositionRoleIn, TextBlockIn

OWN = uuid.uuid4()
FOREIGN = uuid.uuid4()
USER = str(uuid.uuid4())


class FakeSession:
    def __init__(self, rows: dict[tuple[type, uuid.UUID], Any]) -> None:
        self.rows = rows
        self.deleted: list[Any] = []
        self.flushed = 0

    async def get(self, model: type, key: uuid.UUID) -> Any:
        return self.rows.get((model, key))

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.fixture(autouse=True)
def _only_own_project(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify(project_id: uuid.UUID, user_id: str, session: Any) -> None:
        if project_id != OWN:
            raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(offers_router, "verify_project_access", verify)


def _block(project_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), project_id=project_id, scope="project" if project_id else "company")


def _body(project_id: uuid.UUID | None = None) -> TextBlockIn:
    return TextBlockIn(kind="intro", body="Hello", scope="project" if project_id else "company", project_id=project_id)


async def test_foreign_project_text_cannot_be_edited_or_deleted() -> None:
    block = _block(FOREIGN)
    session = FakeSession({(OfferTextBlock, block.id): block})
    with pytest.raises(HTTPException) as exc:
        await offers_router.update_text(block.id, _body(FOREIGN), session, USER)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await offers_router.delete_text(block.id, session, USER)
    assert exc.value.status_code == 404
    assert session.deleted == []
    assert session.flushed == 0


async def test_own_text_cannot_be_moved_into_a_foreign_project() -> None:
    block = _block(OWN)
    session = FakeSession({(OfferTextBlock, block.id): block})
    with pytest.raises(HTTPException) as exc:
        await offers_router.update_text(block.id, _body(FOREIGN), session, USER)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await offers_router.create_text(_body(FOREIGN), session, USER)
    assert exc.value.status_code == 404


async def test_own_and_company_texts_can_be_deleted() -> None:
    own, company = _block(OWN), _block(None)
    session = FakeSession({(OfferTextBlock, own.id): own, (OfferTextBlock, company.id): company})
    await offers_router.delete_text(own.id, session, USER)
    await offers_router.delete_text(company.id, session, USER)
    assert session.deleted == [own, company]


async def test_missing_text_is_404() -> None:
    with pytest.raises(HTTPException) as exc:
        await offers_router.delete_text(uuid.uuid4(), FakeSession({}), USER)
    assert exc.value.status_code == 404


async def test_foreign_position_role_is_refused() -> None:
    boq = SimpleNamespace(id=uuid.uuid4(), project_id=FOREIGN)
    pos = SimpleNamespace(id=uuid.uuid4(), boq_id=boq.id, metadata_={})
    session = FakeSession({(BOQ, boq.id): boq, (Position, pos.id): pos})
    with pytest.raises(HTTPException) as exc:
        await offers_router.set_position_role(pos.id, PositionRoleIn(role="optional"), session, USER)
    assert exc.value.status_code == 404
    assert pos.metadata_ == {}


async def test_own_position_role_is_set() -> None:
    boq = SimpleNamespace(id=uuid.uuid4(), project_id=OWN)
    pos = SimpleNamespace(id=uuid.uuid4(), boq_id=boq.id, metadata_={})
    session = FakeSession({(BOQ, boq.id): boq, (Position, pos.id): pos})
    out = await offers_router.set_position_role(pos.id, PositionRoleIn(role="optional"), session, USER)
    assert out["role"] == "optional"
    assert pos.metadata_["offer_role"] == "optional"
