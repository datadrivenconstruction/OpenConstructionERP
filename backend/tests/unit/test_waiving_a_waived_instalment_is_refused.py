# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Waiving an instalment that is already waived is a conflict, not a rewrite.

``_ensure_transition`` returns early when the target equals the current status,
so a second waive used to fall through, overwrite ``waiver_reason`` and
``waived_at`` in the instalment's metadata with the new call's values and
publish ``property_dev.instalment.waived`` a second time for one waiver. The
same shortcut is closed with an explicit 409 on ``cancel_reservation``,
``expire_reservation`` and ``cancel_spa``; ``waive_instalment`` now does the
same. The paired case shows a pending instalment still waives.

Repositories and the event bus are stubbed, no database is touched.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.property_dev.schemas import InstalmentWaiveRequest
from app.modules.property_dev.service import PropertyDevService


class _StubInstalmentRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, oid: uuid.UUID) -> Any:
        return self.rows.get(oid)

    async def update_fields(self, oid: uuid.UUID, **fields: Any) -> None:
        for k, v in fields.items():
            setattr(self.rows[oid], k, v)

    async def list_for_schedule(self, schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.schedule_id == schedule_id]


class _StubScheduleRepo:
    def __init__(self) -> None:
        self.updates: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def update_fields(self, oid: uuid.UUID, **fields: Any) -> None:
        self.updates.append((oid, fields))


def _make_service(status: str, metadata: dict[str, Any] | None = None) -> tuple[PropertyDevService, Any]:
    svc = PropertyDevService.__new__(PropertyDevService)
    svc.instalments = _StubInstalmentRepo()
    svc.payment_schedules = _StubScheduleRepo()
    ins = SimpleNamespace(
        id=uuid.uuid4(),
        schedule_id=uuid.uuid4(),
        status=status,
        metadata_=dict(metadata or {}),
    )
    svc.instalments.rows[ins.id] = ins
    return svc, ins


@pytest.mark.asyncio
async def test_waiving_a_waived_instalment_is_refused() -> None:
    first = {"waiver_reason": "Goodwill after the leak", "waived_at": "2026-09-01T10:00:00+00:00"}
    svc, ins = _make_service("waived", first)
    publish = MagicMock()

    with (
        patch("app.modules.property_dev.service.event_bus.publish_detached", publish),
        pytest.raises(HTTPException) as exc,
    ):
        await svc.waive_instalment(ins.id, InstalmentWaiveRequest(reason="Second thoughts"))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Instalment in status 'waived' cannot be waived"
    assert ins.status == "waived"
    assert ins.metadata_ == first
    assert svc.payment_schedules.updates == []
    publish.assert_not_called()


@pytest.mark.asyncio
async def test_waiving_a_pending_instalment_still_goes_through() -> None:
    svc, ins = _make_service("pending")
    publish = MagicMock()

    with patch("app.modules.property_dev.service.event_bus.publish_detached", publish):
        waived = await svc.waive_instalment(ins.id, InstalmentWaiveRequest(reason="Goodwill"))

    assert waived.status == "waived"
    assert waived.metadata_["waiver_reason"] == "Goodwill"
    assert "waived_at" in waived.metadata_
    # The only instalment of its schedule is now settled, so the schedule completes first.
    assert [c.args[0] for c in publish.call_args_list] == [
        "property_dev.payment_schedule.completed",
        "property_dev.instalment.waived",
    ]
