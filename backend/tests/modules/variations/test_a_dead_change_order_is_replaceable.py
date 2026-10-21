"""A variation order whose change order died can take a replacement; voiding needs a reason."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.variations.router import _VoidBody
from app.modules.variations.schemas import VariationOrderCreate
from tests.modules.variations.test_variations_idor import _make_service


class _FakeCORepo:
    def __init__(self, rows: dict[uuid.UUID, Any]) -> None:
        self.rows = rows
        self.updates: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def get_by_id(self, row_id: uuid.UUID) -> Any:
        return self.rows.get(row_id)

    async def update_fields(self, row_id: uuid.UUID, **fields: Any) -> None:
        self.updates.append((row_id, fields))


def _fake_co_service(rows: dict[uuid.UUID, Any], created: list[Any]) -> type:
    class _FakeCOService:
        last: Any = None

        def __init__(self, session: Any) -> None:
            self.repo = _FakeCORepo(rows)
            _FakeCOService.last = self

        async def create_order(self, payload: Any) -> Any:
            co = SimpleNamespace(id=uuid.uuid4(), status="draft", metadata_=dict(payload.metadata))
            rows[co.id] = co
            created.append(co)
            return co

    return _FakeCOService


async def _vo(svc: Any) -> Any:
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        return await svc.create_order(
            VariationOrderCreate(project_id=uuid.uuid4(), title="vo", currency="EUR"),
            user_id="u1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("dead", ["rejected", "cancelled", "withdrawn"])
async def test_a_dead_linked_change_order_can_be_replaced(dead: str) -> None:
    svc = _make_service()
    vo = await _vo(svc)
    old = SimpleNamespace(id=uuid.uuid4(), status=dead, metadata_={})
    rows: dict[uuid.UUID, Any] = {old.id: old}
    created: list[Any] = []
    vo.reference_change_order_id = old.id
    fake = _fake_co_service(rows, created)
    with (
        patch("app.modules.changeorders.service.ChangeOrderService", fake),
        patch("app.modules.variations.service.event_bus.publish_detached"),
    ):
        out = await svc.create_linked_change_order(vo.id, user_id="u1")
    assert len(created) == 1
    assert out.reference_change_order_id == created[0].id != old.id
    assert out.metadata_["previous_change_order_ids"] == [str(old.id)]
    assert created[0].metadata_["supersedes_change_order_id"] == str(old.id)
    ((old_id, fields),) = fake.last.repo.updates
    assert old_id == old.id
    assert fields["metadata_"]["superseded_by_change_order_id"] == str(created[0].id)


@pytest.mark.asyncio
@pytest.mark.parametrize("live", ["draft", "submitted", "approved", "executed"])
async def test_a_live_linked_change_order_still_blocks(live: str) -> None:
    svc = _make_service()
    vo = await _vo(svc)
    old = SimpleNamespace(id=uuid.uuid4(), status=live, metadata_={})
    vo.reference_change_order_id = old.id
    created: list[Any] = []
    with (
        patch("app.modules.changeorders.service.ChangeOrderService", _fake_co_service({old.id: old}, created)),
        pytest.raises(HTTPException) as exc,
    ):
        await svc.create_linked_change_order(vo.id, user_id="u1")
    assert exc.value.status_code == 409
    assert not created


@pytest.mark.asyncio
async def test_a_voided_vo_never_takes_a_change_order() -> None:
    svc = _make_service()
    vo = await _vo(svc)
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        await svc.transition_variation_order(vo.id, "voided", user_id="u1", reason="duplicate of VO-9")
    with pytest.raises(HTTPException) as exc:
        await svc.create_linked_change_order(vo.id, user_id="u1")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [None, "", "  ", "ab"])
async def test_voiding_without_a_reason_is_refused(reason: str | None) -> None:
    svc = _make_service()
    vo = await _vo(svc)
    with pytest.raises(HTTPException) as exc:
        await svc.transition_variation_order(vo.id, "voided", user_id="u1", reason=reason)
    assert exc.value.status_code == 422
    assert vo.status == "issued"


@pytest.mark.asyncio
async def test_the_void_reason_is_stored_with_who_and_when() -> None:
    svc = _make_service()
    vo = await _vo(svc)
    with patch("app.modules.variations.service.event_bus.publish_detached"):
        out = await svc.transition_variation_order(vo.id, "voided", user_id="u1", reason="  Scope withdrawn  ")
    assert out.status == "voided"
    assert out.metadata_["void_reason"] == "Scope withdrawn"
    assert out.metadata_["voided_by"] == "u1"
    assert out.metadata_["voided_at"]


def test_the_void_route_body_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        _VoidBody()  # type: ignore[call-arg]
    assert _VoidBody(reason="Duplicate").reason == "Duplicate"
