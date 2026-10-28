# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Focused tests for the RFI activity-journal endpoint (item #13).

``GET /{rfi_id}/activity/`` reuses the generic ``get_activity_for_entity``
helper over the shared ``oe_activity_log`` table to surface an RFI's
lifecycle history. These tests pin the two load-bearing pieces WITHOUT a
database, in the same monkeypatch / transient-ORM-object style as
``tests/integration/test_rfi_audit.py`` and
``tests/modules/file_approvals/test_notifications.py``:

#. ``test_get_rfi_activity_is_scoped_and_serialised`` - the route resolves
   the RFI, runs the project-scope (IDOR) guard against the RFI's OWN
   project, asks the helper for THIS RFI's journal (``entity_type="rfi"``,
   ``entity_id=<rfi_id>``), and serialises the rows through
   ``RFIActivityEntry`` (never the raw ORM row) inside a page envelope whose
   ``total`` is counted over the same two filters as the page.

#. ``test_rfi_activity_entry_maps_metadata_alias`` - the response schema maps
   the ``metadata_`` column to the wire field ``metadata`` (the subtle alias
   that a bare ``model_validate`` would otherwise drop).

The underlying DB query itself is already covered by
``tests/unit/test_audit_log.py``; here we only pin the wiring + contract.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.audit_log import ActivityLog
from app.modules.rfi import router as rfi_router
from app.modules.rfi.schemas import RFIActivityEntry, RFIActivityListResponse


def _activity_row(
    *,
    actor_id: uuid.UUID | None,
    from_status: str,
    to_status: str,
    metadata: dict[str, Any],
) -> ActivityLog:
    """Build a transient (un-flushed) ActivityLog the way the RFI service does.

    ``id`` / ``created_at`` are normally filled on flush; we set them here so
    the required schema fields are present without touching a database.
    """
    return ActivityLog(
        id=uuid.uuid4(),
        actor_id=actor_id,
        entity_type="rfi",
        entity_id=str(uuid.uuid4()),
        action="status_changed",
        from_status=from_status,
        to_status=to_status,
        reason="RFI answered via respond_to_rfi()",
        module="rfi",
        metadata_=metadata,
        created_at=datetime.now(UTC),
    )


class _StubService:
    """Stands in for RFIService.get_rfi - returns an RFI with a project scope."""

    def __init__(self, project_id: uuid.UUID) -> None:
        self._project_id = project_id
        self.asked_for: uuid.UUID | None = None

    async def get_rfi(self, rfi_id: uuid.UUID) -> Any:
        self.asked_for = rfi_id
        return SimpleNamespace(id=rfi_id, project_id=self._project_id)


@pytest.mark.asyncio
async def test_get_rfi_activity_is_scoped_and_serialised(monkeypatch) -> None:
    rfi_id = uuid.uuid4()
    project_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    caller = str(uuid.uuid4())
    captured: dict[str, Any] = {}

    async def _fake_verify(project: Any, user: Any, session: Any) -> None:
        captured["vpa_project"] = project
        captured["vpa_user"] = user

    async def _fake_activity(
        session: Any,
        *,
        entity_type: str,
        entity_id: Any,
        limit: int,
        offset: int,
    ) -> list[ActivityLog]:
        captured["entity_type"] = entity_type
        captured["entity_id"] = entity_id
        captured["limit"] = limit
        captured["offset"] = offset
        return [
            _activity_row(
                actor_id=actor_id,
                from_status="open",
                to_status="answered",
                metadata={"rfi_number": "RFI-001"},
            ),
            _activity_row(
                actor_id=None,  # system / background row - actor stays null
                from_status="answered",
                to_status="closed",
                metadata={"rfi_number": "RFI-001"},
            ),
        ]

    async def _fake_count(session: Any, *, entity_type: str, entity_id: Any) -> int:
        # The count has to be filtered exactly like the page above, or the
        # envelope describes a different set of rows than it carries.
        captured["count_entity_type"] = entity_type
        captured["count_entity_id"] = entity_id
        return 7

    monkeypatch.setattr(rfi_router, "verify_project_access", _fake_verify)
    monkeypatch.setattr(rfi_router, "get_activity_for_entity", _fake_activity)
    monkeypatch.setattr(rfi_router, "count_activity_for_entity", _fake_count)

    service = _StubService(project_id)
    result = await rfi_router.get_rfi_activity(
        rfi_id=rfi_id,
        user_id=caller,
        session=object(),  # unused by the stubs
        limit=50,
        offset=0,
        service=service,  # type: ignore[arg-type]
    )

    # IDOR guard runs against the RFI's OWN project, not a caller-supplied one.
    assert service.asked_for == rfi_id
    assert captured["vpa_project"] == project_id
    assert captured["vpa_user"] == caller

    # The helper is asked for exactly THIS RFI's journal.
    assert captured["entity_type"] == "rfi"
    assert str(captured["entity_id"]) == str(rfi_id)
    assert captured["limit"] == 50
    assert captured["offset"] == 0

    # The count is asked for the SAME journal as the page, not a wider one.
    assert captured["count_entity_type"] == "rfi"
    assert str(captured["count_entity_id"]) == str(rfi_id)

    # Rows come back typed (not raw ORM) with the fields the timeline needs,
    # inside an envelope stating how long the journal actually is. Two of
    # seven here: the endpoint returns the OLDEST entries first, so what the
    # reader is missing is the recent history rather than the ancient part.
    assert isinstance(result, RFIActivityListResponse)
    assert result.total == 7
    assert result.offset == 0
    assert result.limit == 50
    assert len(result.items) == 2
    assert all(isinstance(r, RFIActivityEntry) for r in result.items)
    first = result.items[0]
    assert first.from_status == "open"
    assert first.to_status == "answered"
    assert str(first.actor_id) == str(actor_id)
    assert first.metadata == {"rfi_number": "RFI-001"}
    # Null actor (background row) survives serialisation.
    assert result.items[1].actor_id is None


def test_rfi_activity_entry_maps_metadata_alias() -> None:
    """``metadata_`` column -> ``metadata`` wire field (the aliased bit)."""
    row = _activity_row(
        actor_id=uuid.uuid4(),
        from_status="open",
        to_status="answered",
        metadata={"ball_in_court": "user-123"},
    )

    entry = RFIActivityEntry.model_validate(row)

    assert entry.action == "status_changed"
    assert entry.module == "rfi"
    assert entry.reason == "RFI answered via respond_to_rfi()"
    # The column is named ``metadata_`` on the ORM row; the schema must expose
    # it as ``metadata`` (never leak the trailing underscore to the wire).
    assert entry.metadata == {"ball_in_court": "user-123"}
    dumped = entry.model_dump()
    assert "metadata" in dumped
    assert "metadata_" not in dumped
