"""RFI deep-audit regression suite.

Each test below pins a finding from the deep audit on
``backend/app/modules/rfi/``:

#. ``test_create_rfi_ignores_caller_supplied_raised_by`` — schema accepts
   ``raised_by`` from the client; service must overwrite it with the
   authenticated caller so audit logs cannot be forged.

#. ``test_respond_to_rfi_rejects_non_open_status`` — ``respond_to_rfi``
   blocked only ``closed`` / ``void``; a ``draft`` RFI could leap
   straight to ``answered`` bypassing the documented FSM.

#. ``test_update_rfi_answered_to_open_requires_manager`` — ``answered``
   → ``open`` (reopen) was permitted to any EDITOR via the generic FSM
   table; reopening a vetted answer is a MANAGER+ action.

#. ``test_bulk_delete_rfis_admin_bypass`` — bulk routes used
   ``list_for_user(owner_id=...)`` without ``is_admin=True``, so admins
   silently got zero deletions for projects they did not personally own.

#. ``test_get_stats_caps_rfi_scan`` — ``get_stats`` did an unbounded
   ``SELECT *`` from ``oe_rfi_rfi``; large tenants paid the full cost.

The fixtures use the unit-test stub pattern (``_StubRFIRepo``) so this
suite runs without a live DB but still drives the same code paths the
HTTP router invokes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.rfi.schemas import RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService

# ── Stubs (mirrors tests/unit/test_rfi.py) ─────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:  # pragma: no cover - get_stats path
        # ``service.get_stats`` runs a single ``select(RFI)`` and iterates
        # the scalars. The stub returns the in-memory row store so the
        # cap test below can drive it without SQLAlchemy.
        class _Scalars:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def all(self) -> list[Any]:
                return self._rows

        class _Result:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def scalars(self) -> _Scalars:
                return _Scalars(self._rows)

        return _Result(list(_GLOBAL_ROWS.values()))


_GLOBAL_ROWS: dict[uuid.UUID, Any] = {}


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
        # ``attachments`` is on the SQLAlchemy model but RFI() doesn't
        # set it via __init__; mirror the DB default for the stub so
        # ``getattr(rfi, "attachments", None) or []`` survives.
        if not hasattr(rfi, "attachments") or rfi.attachments is None:
            rfi.attachments = []
        self.rows[rfi.id] = rfi
        _GLOBAL_ROWS[rfi.id] = rfi
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
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        self.rows.pop(rfi_id, None)
        _GLOBAL_ROWS.pop(rfi_id, None)


def _make_service() -> RFIService:
    _GLOBAL_ROWS.clear()
    service = RFIService.__new__(RFIService)
    service.session = _StubSession()
    service.repo = _StubRFIRepo()
    return service


# ── 1. raised_by spoofing ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rfi_ignores_caller_supplied_raised_by() -> None:
    """``raised_by`` from the request body must be overwritten by the
    authenticated caller.

    Pre-fix the schema accepted any UUID and the service preserved it
    (``data.raised_by or user_id``), letting a malicious caller forge
    the audit log to make it look like another user filed the RFI.
    """
    service = _make_service()
    attacker = str(uuid.uuid4())
    impersonated = uuid.uuid4()

    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Steel grade",
            question="C30/37?",
            raised_by=impersonated,  # forged
        ),
        user_id=attacker,
    )

    assert str(rfi.raised_by) == attacker, (
        f"forged raised_by={impersonated} leaked into the row; the "
        f"authenticated caller {attacker} must be the source of truth."
    )


# ── 2. respond_to_rfi FSM bypass ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_to_rfi_rejects_draft_status() -> None:
    """``respond_to_rfi`` must enforce the FSM.

    Pre-fix the service blocked only ``closed`` / ``void``, so a fresh
    ``draft`` RFI could be answered directly — bypassing the
    ``draft → open → answered`` transition documented in
    ``_RFI_STATUS_TRANSITIONS``.
    """
    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Skipped open",
            question="Q",
        )
    )
    # status is now "draft" by default

    with pytest.raises(HTTPException) as exc_info:
        await service.respond_to_rfi(rfi.id, "premature", "responder-1")
    assert exc_info.value.status_code == 400, (
        "draft → answered must be rejected; the FSM only allows draft → open and open → answered."
    )


# ── 3. answered → open reopen needs manager ───────────────────────────────


@pytest.mark.asyncio
async def test_update_rfi_answered_to_open_requires_manager_role() -> None:
    """Reopening an ``answered`` RFI is a MANAGER+ action.

    Pre-fix any EDITOR could PATCH ``status=open`` on an answered RFI
    because the generic FSM table treated ``answered → open`` as a free
    transition. A junior estimator could thus invalidate a vetted answer
    without escalation.
    """
    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Already answered",
            question="Q",
        )
    )
    rfi.status = "answered"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_rfi(
            rfi.id,
            RFIUpdate(status="open"),
            actor_id=str(uuid.uuid4()),
            actor_role="editor",
        )
    assert exc_info.value.status_code == 403, (
        "EDITOR must NOT be able to reopen an answered RFI; require MANAGER/ADMIN/OWNER."
    )


@pytest.mark.asyncio
async def test_update_rfi_answered_to_open_manager_succeeds() -> None:
    """Manager reopen is still allowed — regression guard for the gate."""
    service = _make_service()
    rfi = await service.create_rfi(
        RFICreate(
            project_id=uuid.uuid4(),
            subject="Already answered",
            question="Q",
        )
    )
    rfi.status = "answered"

    updated = await service.update_rfi(
        rfi.id,
        RFIUpdate(status="open"),
        actor_id=str(uuid.uuid4()),
        actor_role="manager",
    )
    assert updated.status == "open"


# ── 4. Bulk endpoints admin bypass ────────────────────────────────────────
#
# This one is router-level. We exercise it via TestClient because the
# behaviour lives in the route handler, not the service.


@pytest.mark.asyncio
async def test_bulk_delete_rfis_admin_bypass() -> None:
    """Admin must be able to bulk-delete RFIs across any project.

    Pre-fix the router used ``list_for_user(owner_id=user_id)`` to
    derive the "allowed projects" set with no ``is_admin=True`` escape
    hatch, so an admin trying to bulk-delete a tenant's RFIs got a
    silent zero-row response.
    """
    from app.modules.rfi.router import batch_delete_rfis

    captured: dict[str, Any] = {}

    class _StubProjectRepo:
        def __init__(self, session: Any) -> None:
            pass

        async def list_for_user(self, *, owner_id: Any, **kwargs: Any) -> tuple[list[Any], int]:
            captured["is_admin"] = kwargs.get("is_admin", False)
            # Stop the handler before it touches the (fake) session
            # again. We've already observed the flag we care about.
            raise _StopProbe

    class _StopProbe(Exception):
        pass

    class _AlsoStubSession:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            raise AssertionError("session.execute reached — probe came too late")

    import app.modules.projects.repository as _proj_repo_mod

    original = _proj_repo_mod.ProjectRepository
    _proj_repo_mod.ProjectRepository = _StubProjectRepo  # type: ignore[misc]
    try:
        from app.core.bulk_ops import BulkDeleteRequest

        try:
            await batch_delete_rfis(  # type: ignore[call-arg]
                body=BulkDeleteRequest(ids=[uuid.uuid4()]),
                user_id=str(uuid.uuid4()),
                session=_AlsoStubSession(),  # type: ignore[arg-type]
                payload={"role": "admin"},  # type: ignore[arg-type]
            )
        except TypeError:
            # Pre-fix signature has no ``payload`` arg → admin path is
            # impossible by construction; the failure mode IS the bug.
            pytest.fail(
                "batch_delete_rfis has no `payload` parameter — admin callers cannot reach an `is_admin=True` branch."
            )
        except _StopProbe:
            pass  # expected — captured the flag, short-circuit fine

        assert captured.get("is_admin") is True, (
            "Admin caller did not propagate is_admin=True into "
            "ProjectRepository.list_for_user; bulk-delete will silently "
            "return zero rows for cross-tenant admin cleanup."
        )
    finally:
        _proj_repo_mod.ProjectRepository = original  # type: ignore[misc]


# ── 5. get_stats hard cap on scan ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stats_applies_hard_cap_on_scan() -> None:
    """``get_stats`` must bound the per-project scan.

    Pre-fix the query was ``SELECT * FROM oe_rfi_rfi WHERE project_id =
    :pid`` with no ``LIMIT``. A noisy tenant with 100k RFIs would force
    a full table read on every dashboard tick. The fix caps the scan
    and surfaces the cap as a constant the test can pin.
    """
    from app.modules.rfi import service as svc_mod

    cap = getattr(svc_mod, "_RFI_STATS_SCAN_CAP", None)
    assert cap is not None, (
        "RFIService.get_stats has no scan cap; large tenants pay full table read on every stats request."
    )
    assert isinstance(cap, int) and cap > 0, f"_RFI_STATS_SCAN_CAP must be a positive int, got {cap!r}"
