"""Unit tests for RFC 33 — CDE module deep audit.

Covers the five must-fix items:
1. Suitability code validation — right codes for right state, 422 otherwise.
2. Revision → Document cross-link on create (with and without storage_key).
3. Gate B (SHARED → PUBLISHED) requires ``approver_signature`` → 400 otherwise.
4. ``metadata_.last_approval`` is populated on valid Gate B promotion.
5. Every valid transition writes a ``StateTransition`` audit row.

Repositories and the Documents module are stubbed so the suite doesn't need a
live database. The ``CDEService`` is the unit under test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.cde.schemas import (
    ContainerCreate,
    RevisionCreate,
    StateTransitionRequest,
)
from app.modules.cde.service import CDEService
from app.modules.cde.suitability import (
    SUITABILITY_CODES,
    codes_for_state,
    validate_suitability_for_state,
)

# ── Stubs ─────────────────────────────────────────────────────────────────


class _StubSession:
    """Minimal async session stub with add/flush/refresh/execute."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = datetime.now(UTC)
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = datetime.now(UTC)
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        pass

    async def execute(self, stmt: Any) -> SimpleNamespace:  # noqa: ARG002
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: []),
            scalar_one_or_none=lambda: None,
            all=lambda: [],
        )


class _StubContainerRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, container_id: uuid.UUID) -> Any:
        return self.rows.get(container_id)

    async def get_by_code_and_project(
        self, project_id: uuid.UUID, code: str,  # noqa: ARG002
    ) -> Any:
        return None

    async def create(self, container: Any) -> Any:
        if getattr(container, "id", None) is None:
            container.id = uuid.uuid4()
        container.created_at = datetime.now(UTC)
        container.updated_at = datetime.now(UTC)
        self.rows[container.id] = container
        return container

    async def update_fields(
        self, container_id: uuid.UUID, **fields: object
    ) -> None:
        row = self.rows.get(container_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)


class _StubRevisionRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def next_revision_number(self, container_id: uuid.UUID) -> int:  # noqa: ARG002
        self._counter += 1
        return self._counter

    async def create(self, revision: Any) -> Any:
        if getattr(revision, "id", None) is None:
            revision.id = uuid.uuid4()
        revision.created_at = datetime.now(UTC)
        revision.updated_at = datetime.now(UTC)
        self.rows[revision.id] = revision
        return revision

    async def get_by_id(self, revision_id: uuid.UUID) -> Any:
        return self.rows.get(revision_id)

    async def update_fields(self, revision_id: uuid.UUID, **fields: object) -> None:
        row = self.rows.get(revision_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)


def _make_service() -> tuple[CDEService, _StubSession, _StubContainerRepo, _StubRevisionRepo]:
    service = CDEService.__new__(CDEService)
    session = _StubSession()
    c_repo = _StubContainerRepo()
    r_repo = _StubRevisionRepo()
    service.session = session  # type: ignore[attr-defined]
    service.container_repo = c_repo  # type: ignore[attr-defined]
    service.revision_repo = r_repo  # type: ignore[attr-defined]
    return service, session, c_repo, r_repo


def _seed_container(c_repo: _StubContainerRepo, *, state: str = "wip") -> Any:
    container = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        container_code="PRJ-ARC-DWG-001",
        cde_state=state,
        current_revision_id=None,
        metadata_={},
    )
    c_repo.rows[container.id] = container
    return container


# ── Suitability validation (schema-level) ─────────────────────────────────


class TestSuitabilityValidation:
    def test_codes_for_state_shared(self) -> None:
        codes = [c for c, _ in codes_for_state("shared")]
        assert "S1" in codes
        assert "S2" in codes
        assert "A1" not in codes

    def test_codes_for_state_wip_only_s0(self) -> None:
        codes = [c for c, _ in codes_for_state("wip")]
        assert codes == ["S0"]

    def test_validate_blank_code_accepted(self) -> None:
        ok, _ = validate_suitability_for_state(None, "wip")
        assert ok
        ok2, _ = validate_suitability_for_state("", "shared")
        assert ok2

    def test_validate_unknown_state_rejected(self) -> None:
        ok, reason = validate_suitability_for_state("S1", "bogus")
        assert not ok
        assert "Unknown CDE state" in reason

    def test_wip_with_s1_fails_at_pydantic(self) -> None:
        """Mirrors RFC §4: state=WIP + code=S1 → 422 at Pydantic layer."""
        with pytest.raises(ValidationError):
            ContainerCreate(
                project_id=uuid4(),
                container_code="C1",
                title="T",
                cde_state="wip",
                suitability_code="S1",
            )

    def test_shared_with_s1_passes(self) -> None:
        """state=SHARED + code=S1 → OK."""
        c = ContainerCreate(
            project_id=uuid4(),
            container_code="C2",
            title="T",
            cde_state="shared",
            suitability_code="S1",
        )
        assert c.suitability_code == "S1"

    def test_published_with_a3_passes(self) -> None:
        c = ContainerCreate(
            project_id=uuid4(),
            container_code="C3",
            title="T",
            cde_state="published",
            suitability_code="A3",
        )
        assert c.suitability_code == "A3"

    def test_published_with_s1_fails(self) -> None:
        with pytest.raises(ValidationError):
            ContainerCreate(
                project_id=uuid4(),
                container_code="C4",
                title="T",
                cde_state="published",
                suitability_code="S1",
            )

    def test_suitability_table_has_expected_shape(self) -> None:
        # Ensure all four state buckets exist and are non-empty.
        for state in ("wip", "shared", "published", "archived"):
            assert state in SUITABILITY_CODES
            assert SUITABILITY_CODES[state]


# ── Revision cross-link ───────────────────────────────────────────────────


class TestRevisionDocumentCrossLink:
    @pytest.mark.asyncio
    async def test_without_storage_key_no_document_created(self) -> None:
        service, session, c_repo, r_repo = _make_service()
        container = _seed_container(c_repo)

        rev = await service.create_revision(
            container.id,
            RevisionCreate(file_name="drawing.pdf"),
            user_id="user-1",
        )

        # Nothing added to the documents hub because storage_key is None.
        doc_added = [
            obj
            for obj in session.added
            if obj.__class__.__name__ == "Document"
        ]
        assert doc_added == []
        # Revision is still persisted and has no document_id.
        assert rev.id in r_repo.rows
        assert getattr(rev, "document_id", None) in (None, "")

    @pytest.mark.asyncio
    async def test_with_storage_key_creates_document(self) -> None:
        service, session, c_repo, r_repo = _make_service()
        container = _seed_container(c_repo)

        rev = await service.create_revision(
            container.id,
            RevisionCreate(
                file_name="drawing.pdf",
                storage_key="uploads/drawing.pdf",
                file_size="1024",
                mime_type="application/pdf",
            ),
            user_id="user-1",
        )

        doc_added = [
            obj
            for obj in session.added
            if obj.__class__.__name__ == "Document"
        ]
        assert len(doc_added) == 1
        doc = doc_added[0]
        assert doc.category == "cde"
        assert doc.file_path == "uploads/drawing.pdf"
        assert "cde" in (doc.tags or [])
        assert container.container_code in (doc.tags or [])
        # The revision's document_id was wired up via update_fields.
        persisted = r_repo.rows[rev.id]
        assert str(persisted.document_id) == str(doc.id)


# ── Gate B approval ───────────────────────────────────────────────────────


class TestGateBApproval:
    @pytest.mark.asyncio
    async def test_without_signature_raises_400(self) -> None:
        service, _session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="shared")

        with pytest.raises(HTTPException) as exc_info:
            await service.transition_state(
                container.id,
                StateTransitionRequest(target_state="published"),
                user_role="lead_ap",
                user_id="user-1",
            )

        assert exc_info.value.status_code == 400
        assert "approver_signature" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_with_signature_succeeds_and_writes_metadata(self) -> None:
        service, session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="shared")

        await service.transition_state(
            container.id,
            StateTransitionRequest(
                target_state="published",
                approver_signature="J. Reviewer",
                approval_comments="Looks good — proceeding.",
                reason="All drawings approved",
            ),
            user_role="lead_ap",
            user_id="user-1",
        )

        # State was changed on the container.
        assert container.cde_state == "published"
        # last_approval metadata was set.
        approval = container.metadata_.get("last_approval")
        assert approval is not None
        assert approval["by"] == "user-1"
        assert approval["signature"] == "J. Reviewer"
        assert approval["comments"] == "Looks good — proceeding."
        assert "at" in approval

    @pytest.mark.asyncio
    async def test_wip_to_shared_does_not_need_signature(self) -> None:
        service, _session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="wip")

        await service.transition_state(
            container.id,
            StateTransitionRequest(target_state="shared"),
            user_role="task_team_manager",
            user_id="user-1",
        )

        assert container.cde_state == "shared"
        # No approval block expected on Gate A.
        assert "last_approval" not in container.metadata_


# ── StateTransition audit row ─────────────────────────────────────────────


class TestStateTransitionAuditLog:
    @pytest.mark.asyncio
    async def test_row_written_on_valid_transition(self) -> None:
        service, session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="wip")

        await service.transition_state(
            container.id,
            StateTransitionRequest(target_state="shared", reason="go"),
            user_role="task_team_manager",
            user_id="user-7",
        )

        audit = [
            obj
            for obj in session.added
            if obj.__class__.__name__ == "StateTransition"
        ]
        assert len(audit) == 1
        row = audit[0]
        assert row.from_state == "wip"
        assert row.to_state == "shared"
        assert row.gate_code == "A"
        assert row.user_id == "user-7"
        assert row.user_role == "task_team_manager"
        assert row.reason == "go"
        # Gate A doesn't require a signature.
        assert row.signature is None

    @pytest.mark.asyncio
    async def test_row_captures_signature_on_gate_b(self) -> None:
        service, session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="shared")

        await service.transition_state(
            container.id,
            StateTransitionRequest(
                target_state="published",
                approver_signature="S. Signed",
            ),
            user_role="lead_ap",
            user_id="user-9",
        )

        audit = [
            obj
            for obj in session.added
            if obj.__class__.__name__ == "StateTransition"
        ]
        assert len(audit) == 1
        assert audit[0].gate_code == "B"
        assert audit[0].signature == "S. Signed"

    @pytest.mark.asyncio
    async def test_no_row_on_rejected_transition(self) -> None:
        service, session, c_repo, _r_repo = _make_service()
        container = _seed_container(c_repo, state="wip")

        # Direct wip -> published is not allowed (must go through shared).
        with pytest.raises(HTTPException):
            await service.transition_state(
                container.id,
                StateTransitionRequest(target_state="published"),
                user_role="admin",
                user_id="user-1",
            )

        audit = [
            obj
            for obj in session.added
            if obj.__class__.__name__ == "StateTransition"
        ]
        assert audit == []
