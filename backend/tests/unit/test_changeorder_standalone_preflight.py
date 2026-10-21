"""Standalone change order preflight: a check that lists active variations, never a block."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.changeorders import router as co_router
from app.modules.changeorders.schemas import ChangeOrderCreate
from app.modules.changeorders.service import ChangeOrderService


class _Session:
    def __init__(self, vos: list[Any]) -> None:
        self.vos = vos

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.vos))


class _Repo:
    def __init__(self, rows: dict[uuid.UUID, Any]) -> None:
        self.rows = rows

    async def get_by_id(self, row_id: uuid.UUID) -> Any:
        return self.rows.get(row_id)


def _vo(code: str, status: str = "issued", co_id: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(), code=code, title=f"t {code}", status=status, reference_change_order_id=co_id
    )


@pytest.mark.asyncio
async def test_preflight_reports_link_ability_per_variation() -> None:
    live = SimpleNamespace(id=uuid.uuid4(), status="submitted")
    dead = SimpleNamespace(id=uuid.uuid4(), status="rejected")
    vos = [_vo("VO-1"), _vo("VO-2", co_id=live.id), _vo("VO-3", co_id=dead.id), _vo("VO-4", "completed")]
    svc = ChangeOrderService.__new__(ChangeOrderService)
    svc.session = _Session(vos)  # type: ignore[assignment]
    svc.repo = _Repo({live.id: live, dead.id: dead})  # type: ignore[assignment]
    rows = await svc.standalone_preflight(uuid.uuid4())
    assert [r["can_link"] for r in rows] == [True, False, True, True]
    assert rows[1]["linked_change_order_status"] == "submitted"
    assert rows[2]["linked_change_order_status"] == "rejected"


@pytest.mark.asyncio
async def test_acknowledgement_is_stamped_by_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Svc:
        async def create_order(self, data: ChangeOrderCreate) -> Any:
            seen["metadata"] = data.metadata
            return SimpleNamespace()

    async def _ok(*a: Any, **k: Any) -> None:
        return None

    async def _resp(session: Any, order: Any) -> str:
        return "ok"

    monkeypatch.setattr(co_router, "verify_project_access", _ok)
    monkeypatch.setattr(co_router, "_order_response", _resp)
    data = ChangeOrderCreate(project_id=uuid.uuid4(), title="x", metadata={"standalone_overlap_acknowledged": True})
    await co_router.create_change_order(data, "user-1", None, None, _Svc())  # type: ignore[arg-type]
    ack = seen["metadata"]["standalone_overlap_acknowledged"]
    assert ack["by"] == "user-1"
    assert ack["at"]


@pytest.mark.asyncio
async def test_an_acknowledged_order_gets_no_overlap_warning() -> None:
    svc = ChangeOrderService.__new__(ChangeOrderService)
    order = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        metadata_={"standalone_overlap_acknowledged": {"by": "u", "at": "now"}},
    )
    await svc._warn_standalone_overlap(order)  # type: ignore[arg-type]
    assert "standalone_overlap_warning" not in order.metadata_
