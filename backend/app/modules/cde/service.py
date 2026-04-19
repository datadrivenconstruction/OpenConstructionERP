"""CDE service — business logic for ISO 19650 Common Data Environment.

Stateless service layer. Handles:
- Document container CRUD
- CDE state transitions (wip -> shared -> published -> archived) via CDEStateMachine
- Revision management with auto-numbering, content-addressable storage,
  and a cross-link into the Documents hub when a file is supplied
- Persistent audit log of every state transition
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cde_states import CDEState, CDEStateMachine
from app.core.events import event_bus
from app.modules.cde.models import DocumentContainer, DocumentRevision, StateTransition
from app.modules.cde.repository import ContainerRepository, RevisionRepository
from app.modules.cde.schemas import (
    CDEStatsResponse,
    ContainerCreate,
    ContainerTransmittalLink,
    ContainerUpdate,
    RevisionCreate,
    StateTransitionRequest,
)
from app.modules.cde.suitability import validate_suitability_for_state

logger = logging.getLogger(__name__)

_state_machine = CDEStateMachine()


class CDEService:
    """Business logic for CDE operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.container_repo = ContainerRepository(session)
        self.revision_repo = RevisionRepository(session)

    # ── Container CRUD ────────────────────────────────────────────────────

    async def create_container(
        self,
        data: ContainerCreate,
        user_id: str | None = None,
    ) -> DocumentContainer:
        """Create a new document container.

        If ``container_code`` equals the sentinel value ``"AUTO"``, a code is
        auto-generated from the ISO 19650 naming convention parts
        (originator_code, functional_breakdown, spatial_breakdown, form_code,
        discipline_code, sequence_number).

        Raises 409 if container_code already exists within the project.
        """
        # Auto-generate container_code from naming convention parts when requested
        if data.container_code.strip().upper() == "AUTO":
            data.container_code = self.generate_container_code(
                originator=data.originator_code,
                functional=data.functional_breakdown,
                spatial=data.spatial_breakdown,
                form=data.form_code,
                discipline=data.discipline_code,
                number=data.sequence_number,
            )
            if not data.container_code:
                from fastapi import HTTPException as _HTTPException

                raise _HTTPException(
                    status_code=400,
                    detail=(
                        "Cannot auto-generate container_code: provide at least one "
                        "naming convention field (originator_code, functional_breakdown, "
                        "spatial_breakdown, form_code, discipline_code, or sequence_number)"
                    ),
                )

        existing = await self.container_repo.get_by_code_and_project(
            data.project_id, data.container_code
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Container code '{data.container_code}' already exists "
                    f"in project {data.project_id}"
                ),
            )

        container = DocumentContainer(
            project_id=data.project_id,
            container_code=data.container_code,
            originator_code=data.originator_code,
            functional_breakdown=data.functional_breakdown,
            spatial_breakdown=data.spatial_breakdown,
            form_code=data.form_code,
            discipline_code=data.discipline_code,
            sequence_number=data.sequence_number,
            classification_system=data.classification_system,
            classification_code=data.classification_code,
            cde_state=data.cde_state,
            suitability_code=data.suitability_code,
            title=data.title,
            description=data.description,
            security_classification=data.security_classification,
            created_by=user_id,
            metadata_=data.metadata,
        )
        container = await self.container_repo.create(container)
        logger.info(
            "CDE container created: %s (%s) for project %s",
            data.container_code,
            data.cde_state,
            data.project_id,
        )
        return container

    async def get_container(self, container_id: uuid.UUID) -> DocumentContainer:
        """Get container by ID. Raises 404 if not found."""
        container = await self.container_repo.get_by_id(container_id)
        if container is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document container not found",
            )
        return container

    async def list_containers(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        cde_state: str | None = None,
        discipline_code: str | None = None,
    ) -> tuple[list[DocumentContainer], int]:
        """List containers for a project."""
        return await self.container_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            cde_state=cde_state,
            discipline_code=discipline_code,
        )

    async def update_container(
        self,
        container_id: uuid.UUID,
        data: ContainerUpdate,
    ) -> DocumentContainer:
        """Update container fields."""
        container = await self.get_container(container_id)

        if container.cde_state == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit an archived container",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return container

        # Re-validate suitability when either the state or the suitability
        # code changes on update — ContainerCreate has a model_validator,
        # but ContainerUpdate is a partial schema and can't express the
        # "state+code consistent" constraint on its own. Without this, an
        # editor could PATCH ``suitability_code="S1"`` onto a published
        # container and end up in an invalid ISO 19650 combo.
        next_code = fields.get("suitability_code", container.suitability_code)
        next_state = fields.get("cde_state", container.cde_state)
        ok, reason = validate_suitability_for_state(next_code, next_state)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reason,
            )

        await self.container_repo.update_fields(container_id, **fields)
        await self.session.refresh(container)

        logger.info(
            "CDE container updated: %s (fields=%s)",
            container_id,
            list(fields.keys()),
        )
        return container

    # ── CDE State Transitions ─────────────────────────────────────────────

    async def transition_state(
        self,
        container_id: uuid.UUID,
        data: StateTransitionRequest,
        user_role: str = "editor",
        user_id: str | None = None,
    ) -> DocumentContainer:
        """Transition a container's CDE state following ISO 19650 rules.

        Uses the CDEStateMachine from core/cde_states.py to validate both
        structural validity and role-based gate conditions.

        Gate B (SHARED → PUBLISHED) additionally requires an
        ``approver_signature`` in the request body — this is captured in
        ``container.metadata_.last_approval`` for the compliance trail.

        A ``StateTransition`` audit row is written inline (same session) so
        rollback leaves no orphan audit rows — the event bus is still used
        for cross-module notification.
        """
        container = await self.get_container(container_id)
        current_state = container.cde_state
        target_state = data.target_state

        if target_state == current_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Container is already in '{current_state}' state",
            )

        # Validate via CDEStateMachine (checks allowed transitions + role gates)
        allowed, reason = _state_machine.validate_transition(
            current_state, target_state, user_role=user_role,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reason,
            )

        gate_meta = _state_machine.get_gate_requirements(current_state, target_state)
        gate_code = gate_meta.get("gate")

        # Gate B — SHARED → PUBLISHED requires an explicit approver signature.
        updated_metadata: dict[str, Any] | None = None
        is_gate_b = (
            target_state == CDEState.PUBLISHED.value
            and current_state == CDEState.SHARED.value
        )
        if is_gate_b:
            if not data.approver_signature or not data.approver_signature.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Gate B (SHARED → PUBLISHED) requires approver_signature",
                )
            # Merge-in the approval block into metadata_ so it's persisted.
            md = dict(container.metadata_ or {})
            md["last_approval"] = {
                "by": user_id,
                "at": datetime.now(UTC).isoformat(),
                "signature": data.approver_signature,
                "comments": data.approval_comments,
            }
            updated_metadata = md

        # Apply state change (and optional metadata update) in one UPDATE.
        update_fields: dict[str, Any] = {"cde_state": target_state}
        if updated_metadata is not None:
            update_fields["metadata_"] = updated_metadata
        await self.container_repo.update_fields(container_id, **update_fields)

        # Audit row — inline in the same session so a rollback cleans it up.
        audit = StateTransition(
            container_id=container_id,
            from_state=current_state,
            to_state=target_state,
            gate_code=gate_code,
            user_id=user_id,
            user_role=user_role,
            reason=data.reason,
            signature=data.approver_signature if is_gate_b else None,
        )
        self.session.add(audit)
        await self.session.flush()
        await self.session.refresh(container)

        logger.info(
            "CDE state transition: %s -> %s for container %s (gate=%s, user=%s)",
            current_state,
            target_state,
            container_id,
            gate_code,
            user_id,
        )

        # Emit event for cross-module handlers (notifications, analytics).
        await event_bus.publish(
            "cde.container.promoted",
            data={
                "project_id": str(container.project_id),
                "container_id": str(container_id),
                "container_code": container.container_code,
                "from_state": current_state,
                "to_state": target_state,
                "reason": data.reason,
                "gate_code": gate_code,
                "user_id": user_id,
                "user_role": user_role,
            },
            source_module="cde",
        )

        return container

    async def get_container_history(
        self,
        container_id: uuid.UUID,
    ) -> list[StateTransition]:
        """Return the state-transition audit log for a container, newest first."""
        # Verify container exists — throws 404 otherwise.
        await self.get_container(container_id)
        stmt = (
            select(StateTransition)
            .where(StateTransition.container_id == container_id)
            .order_by(StateTransition.transitioned_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_container_transmittals(
        self,
        container_id: uuid.UUID,
    ) -> list[ContainerTransmittalLink]:
        """Return transmittals that include any revision of this container.

        Driven by ``TransmittalItem.revision_id`` → revision → container join.
        Used by the container view to show "this rev was sent in TR-00N …".

        Returns plain data (IDs, strings) rather than ORM objects so the
        caller can serialise safely without triggering additional lazy loads.
        """
        # Verify container exists.
        await self.get_container(container_id)

        # Run a single tuple-yielding query — we pull only the columns we
        # need, so no relationship lazy-loading is triggered when the
        # caller serialises the response.
        from app.modules.transmittals.models import Transmittal, TransmittalItem

        stmt = (
            select(
                Transmittal.id,
                Transmittal.transmittal_number,
                Transmittal.subject,
                Transmittal.status,
                Transmittal.issued_date,
                Transmittal.created_at,
                TransmittalItem.revision_id,
                DocumentRevision.revision_code,
            )
            .join(TransmittalItem, TransmittalItem.transmittal_id == Transmittal.id)
            .join(
                DocumentRevision,
                DocumentRevision.id == TransmittalItem.revision_id,
            )
            .where(DocumentRevision.container_id == container_id)
            .order_by(Transmittal.created_at.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        links: list[ContainerTransmittalLink] = []
        for tr_id, tr_num, subject, tr_status, issued, _created_at, rev_id, rev_code in rows:
            links.append(
                ContainerTransmittalLink(
                    transmittal_id=tr_id,
                    transmittal_number=tr_num,
                    subject=subject,
                    status=tr_status,
                    issued_date=issued,
                    revision_id=rev_id,
                    revision_code=rev_code,
                )
            )
        return links

    # ── Revision Management ───────────────────────────────────────────────

    async def create_revision(
        self,
        container_id: uuid.UUID,
        data: RevisionCreate,
        user_id: str | None = None,
    ) -> DocumentRevision:
        """Create a new revision for a container.

        When ``storage_key`` is provided, also materialise a ``Document`` row
        in the Documents hub so the file appears at ``/documents`` (per the
        platform cross-link rule — see meetings/router.py:991-1020 pattern).
        If no storage_key is supplied, the revision is metadata-only and no
        Document is created (no error).
        """
        container = await self.get_container(container_id)

        if container.cde_state == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add revisions to an archived container",
            )

        rev_number = await self.revision_repo.next_revision_number(container_id)

        # Generate revision code: P.01.01 for preliminary, C.01 for contractual
        if data.is_preliminary:
            revision_code = f"P.{rev_number:02d}.01"
        else:
            revision_code = f"C.{rev_number:02d}"

        # Content-addressable storage: compute SHA-256 if not supplied
        content_hash = data.content_hash
        if not content_hash:
            hash_input = f"{container_id}:{revision_code}:{data.file_name}:{data.file_size or ''}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        revision = DocumentRevision(
            container_id=container_id,
            revision_code=revision_code,
            revision_number=rev_number,
            is_preliminary=data.is_preliminary,
            content_hash=content_hash,
            file_name=data.file_name,
            file_size=data.file_size,
            mime_type=data.mime_type,
            storage_key=data.storage_key,
            status="draft",
            change_summary=data.change_summary,
            created_by=user_id,
            metadata_=data.metadata,
        )
        revision = await self.revision_repo.create(revision)

        # Cache the revision id up-front so later update_fields() calls
        # (which call ``session.expire_all()``) don't force a lazy reload
        # of the primary key outside the async context.
        revision_id = revision.id

        # Cross-link into the Documents hub when the revision carries a file.
        # Best-effort: failure here must not break the revision create — the
        # CDE row is the source of truth, the Documents row is an index.
        if data.storage_key:
            try:
                from app.modules.documents.models import Document

                try:
                    file_size_int = int(data.file_size) if data.file_size else 0
                except (TypeError, ValueError):
                    file_size_int = 0
                doc = Document(
                    project_id=container.project_id,
                    name=data.file_name,
                    description=(
                        f"CDE rev {revision_code} — {container.container_code}"
                    ),
                    category="cde",
                    file_size=file_size_int,
                    mime_type=data.mime_type or "",
                    file_path=data.storage_key,
                    version=rev_number,
                    uploaded_by=str(user_id) if user_id else "",
                    tags=["cde", container.container_code],
                )
                self.session.add(doc)
                await self.session.flush()
                # Read out doc.id before any expire_all() invalidates it.
                doc_id = doc.id
                await self.revision_repo.update_fields(
                    revision_id, document_id=str(doc_id)
                )
                logger.info(
                    "Cross-linked CDE revision %s -> document %s",
                    revision_id,
                    doc_id,
                )
            except Exception:
                logger.exception(
                    "Failed to cross-link CDE revision to Documents hub (revision=%s)",
                    revision_id,
                )

        # Update the container's current_revision_id
        await self.container_repo.update_fields(
            container_id,
            current_revision_id=str(revision_id),
        )

        # Re-fetch the revision with all fields freshly loaded so the caller
        # (the router) can serialise it without hitting a lazy-load IO path.
        revision = await self.revision_repo.get_by_id(revision_id)
        assert revision is not None, "Revision vanished between insert and re-read"

        logger.info(
            "CDE revision created: %s (rev %s) for container %s",
            revision_code,
            rev_number,
            container_id,
        )
        return revision

    async def get_revision(self, revision_id: uuid.UUID) -> DocumentRevision:
        """Get revision by ID. Raises 404 if not found."""
        revision = await self.revision_repo.get_by_id(revision_id)
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document revision not found",
            )
        return revision

    async def list_revisions(
        self,
        container_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRevision], int]:
        """List revisions for a container."""
        # Verify container exists
        await self.get_container(container_id)
        return await self.revision_repo.list_for_container(
            container_id,
            offset=offset,
            limit=limit,
        )

    # ── Stats ────────────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> CDEStatsResponse:
        """Return aggregate CDE statistics for a project."""
        raw = await self.container_repo.stats_for_project(project_id)
        return CDEStatsResponse(
            total=raw["total"],
            by_state=raw["by_state"],
            by_discipline=raw["by_discipline"],
            latest_revisions=raw["latest_revisions"],
        )

    # ── ISO 19650 naming convention ──────────────────────────────────────

    @staticmethod
    def generate_container_code(
        *,
        project: str | None = None,
        originator: str | None = None,
        functional: str | None = None,
        spatial: str | None = None,
        form: str | None = None,
        discipline: str | None = None,
        number: str | None = None,
    ) -> str:
        """Generate an ISO 19650 container code from naming convention parts.

        Pattern: ``{Project}-{Originator}-{Functional}-{Spatial}-{Form}-{Discipline}-{Number}``
        Empty parts are omitted.
        """
        parts = [
            p
            for p in (project, originator, functional, spatial, form, discipline, number)
            if p
        ]
        return "-".join(parts)
