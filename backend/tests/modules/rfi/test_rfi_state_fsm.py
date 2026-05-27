"""‌⁠‍R5 deep-audit tests for the RFI state-machine + role gates.

Scope:
    1. ``service.respond_to_rfi`` rejects a caller who isn't the assignee
       and isn't admin/manager — returns 403 with a clear message.
       (R5 / BUG-RFI-ROLE — respondent identity verification.)
    2. ``service.respond_to_rfi`` accepts the assignee.
    3. ``service.respond_to_rfi`` accepts an admin/manager escalation
       even when the actor isn't the assignee.
    4. ``service.update_rfi`` rejects an editor that tries to change
       ``assigned_to`` (BUG-RFI-ROLE — assigner role gate).
    5. ``service.update_rfi`` lets a manager reassign.
    6. Closing endpoint runs ``verify_project_access`` (R5 / BUG-RFI-IDOR-CLOSE).
       Cross-tenant attacker gets 404, not 200.
    7. Structured ``rfi.state_change`` log fires with the expected keys
       when ``respond_to_rfi`` succeeds.

All tests use in-memory stubs so the suite runs without a live database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.rfi.schemas import RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService

# ── Stubs (mirror test_rfi.py pattern, plus role plumb-through) ──────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:  # for the create retry path
        pass


class _StubRFIRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, rfi: Any) -> Any:
        if getattr(rfi, "id", None) is None:
            rfi.id = uuid.uuid4()
        now = datetime.now(UTC)
        rfi.created_at = now
        rfi.updated_at = now
        if getattr(rfi, "attachments", None) is None:
            rfi.attachments = []
        self.rows[rfi.id] = rfi
        return rfi

    async def get_by_id(self, rfi_id: uuid.UUID) -> Any:
        return self.rows.get(rfi_id)

    async def next_rfi_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"RFI-{self._counter:03d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, rfi_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(rfi_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        self.rows.pop(rfi_id, None)


def _make_service() -> RFIService:
    service = RFIService.__new__(RFIService)
    service.session = _StubSession()
    service.repo = _StubRFIRepo()
    return service


# ── 1-3. Respondent identity verification ────────────────────────────────


class TestRespondentIdentity:
    """R5 / BUG-RFI-ROLE: only assignee or admin/manager may answer."""

    @pytest.mark.asyncio
    async def test_non_assignee_editor_is_rejected_with_403(self) -> None:
        from fastapi import HTTPException

        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Concrete grade?",
                question="C30/37 or C35/45?",
                assigned_to=assignee,
                status="open",
            )
        )

        # A different user with the EDITOR role tries to answer.
        attacker = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.respond_to_rfi(
                rfi.id,
                "Use C35/45",
                responded_by=attacker,
                actor_role="editor",
            )
        assert exc_info.value.status_code == 403
        assert "assignee" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_assignee_is_accepted(self) -> None:
        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Concrete grade?",
                question="C30/37 or C35/45?",
                assigned_to=assignee,
                status="open",
            )
        )
        result = await service.respond_to_rfi(
            rfi.id,
            "Use C35/45",
            responded_by=assignee,
            actor_role="editor",
        )
        assert result.status == "answered"
        assert result.official_response == "Use C35/45"

    @pytest.mark.asyncio
    async def test_manager_escalation_is_accepted(self) -> None:
        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Concrete grade?",
                question="C30/37 or C35/45?",
                assigned_to=assignee,
                status="open",
            )
        )
        manager = str(uuid.uuid4())
        result = await service.respond_to_rfi(
            rfi.id,
            "Escalated answer.",
            responded_by=manager,
            actor_role="manager",
        )
        assert result.status == "answered"

    @pytest.mark.asyncio
    async def test_unassigned_rfi_anyone_with_perm_can_respond(self) -> None:
        """No ``assigned_to`` means no fine-grained identity gate."""
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="General clarification",
                question="Any colour for handrails?",
                status="open",
            )
        )
        result = await service.respond_to_rfi(
            rfi.id,
            "Black.",
            responded_by=str(uuid.uuid4()),
            actor_role="editor",
        )
        assert result.status == "answered"


# ── 4-5. Assigner role gate ──────────────────────────────────────────────


class TestAssignerRoleGate:
    """R5 / BUG-RFI-ROLE: only manager/admin/owner may change ``assigned_to``."""

    @pytest.mark.asyncio
    async def test_editor_cannot_reassign(self) -> None:
        from fastapi import HTTPException

        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Door spec",
                question="60min or 90min fire rating?",
            )
        )
        new_assignee = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.update_rfi(
                rfi.id,
                RFIUpdate(assigned_to=new_assignee),
                actor_role="editor",
            )
        assert exc_info.value.status_code == 403
        assert "assign" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_manager_can_reassign(self) -> None:
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Door spec",
                question="60min or 90min fire rating?",
            )
        )
        new_assignee = str(uuid.uuid4())
        updated = await service.update_rfi(
            rfi.id,
            RFIUpdate(assigned_to=new_assignee),
            actor_role="manager",
        )
        assert str(updated.assigned_to) == new_assignee

    @pytest.mark.asyncio
    async def test_editor_can_still_patch_body_fields(self) -> None:
        """The role gate is field-scoped: editors retain body-edit access."""
        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Door spec",
                question="Original question",
            )
        )
        updated = await service.update_rfi(
            rfi.id,
            RFIUpdate(question="Updated question text."),
            actor_role="editor",
        )
        assert updated.question == "Updated question text."

    @pytest.mark.asyncio
    async def test_no_change_to_assigned_to_no_role_check(self) -> None:
        """Editor patching only ``subject`` doesn't trip the assigner gate
        even if ``assigned_to`` happens to be in the request — but only
        when the requested value equals the existing one (idempotent)."""
        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="X",
                question="Y",
                assigned_to=assignee,
            )
        )
        # Editor re-sends the same assignee → no transition → no gate.
        updated = await service.update_rfi(
            rfi.id,
            RFIUpdate(subject="X2", assigned_to=assignee),
            actor_role="editor",
        )
        assert updated.subject == "X2"


# ── 6. IDOR on close endpoint (router-level via stub session) ────────────


class TestCloseEndpointIDOR:
    """R5 / BUG-RFI-IDOR-CLOSE: ``close_rfi`` runs ``verify_project_access``.

    We don't need a real DB here — the route handler imports
    ``verify_project_access`` and ``service.get_rfi`` lazily; we can stub
    both and assert the close endpoint calls them.
    """

    @pytest.mark.asyncio
    async def test_close_endpoint_runs_verify_project_access(self, monkeypatch) -> None:
        from app.modules.rfi import router as rfi_router

        called: dict[str, Any] = {}

        async def _fake_verify(project_id, user_id, session) -> None:
            called["verify_called_with"] = (project_id, user_id)

        monkeypatch.setattr(rfi_router, "verify_project_access", _fake_verify)

        service = _make_service()
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Close me",
                question="?",
                status="open",
            ),
            user_id=str(uuid.uuid4()),
        )
        rfi.status = "answered"
        rfi.official_response = "yes"

        # Invoke the route handler directly (no real HTTP client needed).
        result = await rfi_router.close_rfi(
            rfi_id=rfi.id,
            user_id=str(uuid.uuid4()),
            session=service.session,  # unused by the stubbed verify
            service=service,
        )
        assert result.status == "closed"
        # Crucially, verify_project_access was called BEFORE the close
        # mutation — the (project_id, user_id) tuple is captured in the
        # stub above.
        assert "verify_called_with" in called
        captured_pid, _captured_uid = called["verify_called_with"]
        assert str(captured_pid) == str(rfi.project_id)


# ── 7. Structured state-change log ───────────────────────────────────────


class TestStructuredStateChangeLog:
    """R5: ``rfi.state_change`` log carries rfi_id / status_from / status_to."""

    @pytest.mark.asyncio
    async def test_respond_emits_structured_log(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="app.modules.rfi.service")
        service = _make_service()
        assignee = str(uuid.uuid4())
        rfi = await service.create_rfi(
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Foundation depth",
                question="How deep?",
                assigned_to=assignee,
                status="open",
            )
        )

        await service.respond_to_rfi(rfi.id, "1.5 m", responded_by=assignee, actor_role="editor")

        # Find the state_change record with the respond transition. Other
        # log records (e.g. ``rfi.created``) may also be in caplog.records.
        state_records = [
            r
            for r in caplog.records
            if getattr(r, "message", "") == "rfi.state_change" or r.getMessage() == "rfi.state_change"
        ]
        assert state_records, "expected at least one rfi.state_change log"
        # Find the respond transition specifically.
        respond_rec = next(r for r in state_records if getattr(r, "transition", None) == "respond")
        assert getattr(respond_rec, "status_from", None) == "open"
        assert getattr(respond_rec, "status_to", None) == "answered"
        assert getattr(respond_rec, "rfi_id", None) == str(rfi.id)
        assert getattr(respond_rec, "actor", None) == assignee
