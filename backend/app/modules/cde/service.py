# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CDE service - business logic for ISO 19650 Common Data Environment.

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
from app.core.events import publish_after_commit
from app.core.json_merge import merge_metadata
from app.modules.cde import readiness as cde_readiness
from app.modules.cde.models import (
    CdeSettings,
    DocumentContainer,
    DocumentRevision,
    StateTransition,
)
from app.modules.cde.repository import ContainerRepository, RevisionRepository
from app.modules.cde.roles import CDE_REVIEW_PRESET_KEYS, CDE_REVIEW_PRESET_META
from app.modules.cde.schemas import (
    CDEApprovalPresetApplyResponse,
    CDEApprovalPresetEntry,
    CDEApprovalPresetsResponse,
    CDEApprovalPresetStep,
    CDEReadinessResponse,
    CdeSettingsResponse,
    CdeSettingsUpdate,
    CDEStatsResponse,
    ContainerCreate,
    ContainerTransmittalLink,
    ContainerUpdate,
    GoLiveGateStatus,
    ReadinessNextAction,
    ReadinessSignalStatus,
    RevisionCreate,
    StateTransitionRequest,
)
from app.modules.cde.suitability import validate_suitability_for_state

logger = logging.getLogger(__name__)

_state_machine = CDEStateMachine()

# Map the platform's canonical RBAC roles (admin / manager / editor / viewer,
# see app.core.permissions.Role) onto the ISO 19650 role names the
# CDEStateMachine gates are keyed by (viewer / editor / task_team_manager /
# lead_ap / admin). The JWT payload only ever carries an app role, so without
# this translation a project ``manager`` resolved to rank -1 and could never
# cross any gate - only ``admin`` could promote a container.
#
# Gate ranks: Gate A needs task_team_manager(2), Gate B needs lead_ap(3),
# Gate C needs admin(4). The ``cde.transition`` permission is MANAGER-level,
# so a manager must clear Gate A and Gate B (→ lead_ap) while archiving
# (Gate C) stays admin-only.
_APP_ROLE_TO_ISO: dict[str, str] = {
    "admin": "admin",
    "manager": "lead_ap",
    "editor": "editor",
    "viewer": "viewer",
}

# Industry-title aliases that behave like one of the canonical four roles
# (mirrors app.core.permissions.ROLE_ALIASES so a "quantity_surveyor" maps to
# editor, "owner" to admin, etc.). Kept local to avoid importing the alias
# table at module import time.
_ROLE_ALIASES: dict[str, str] = {
    "estimator": "editor",
    "quantity_surveyor": "editor",
    "qs": "editor",
    "user": "editor",
    "superuser": "admin",
    "owner": "admin",
    "readonly": "viewer",
    "guest": "viewer",
}


def _iso_role_for(app_role: str | None) -> str:
    """Translate an app/JWT role into the ISO 19650 role the gates use.

    Unknown roles fall through to ``viewer`` (least authority) so an
    unrecognised role can never accidentally pass a gate.
    """
    role = (app_role or "viewer").strip().lower()
    role = _ROLE_ALIASES.get(role, role)
    return _APP_ROLE_TO_ISO.get(role, role)


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

        existing = await self.container_repo.get_by_code_and_project(data.project_id, data.container_code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Container code '{data.container_code}' already exists in project {data.project_id}"),
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
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(container, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        if not fields:
            return container

        # Re-validate suitability when either the state or the suitability
        # code changes on update - ContainerCreate has a model_validator,
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
        ``approver_signature`` in the request body - this is captured in
        ``container.metadata_.last_approval`` for the compliance trail.

        A ``StateTransition`` audit row is written inline (same session) so
        rollback leaves no orphan audit rows - the event bus is still used
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

        # Validate via CDEStateMachine (checks allowed transitions + role gates).
        # The gates are keyed by ISO 19650 role names, but ``user_role`` is the
        # canonical app role from the JWT (admin / manager / editor / viewer) -
        # translate it first, otherwise everyone except admin gets a spurious
        # "Insufficient role" 400.
        iso_role = _iso_role_for(user_role)
        allowed, reason = _state_machine.validate_transition(
            current_state,
            target_state,
            user_role=iso_role,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reason,
            )

        gate_meta = _state_machine.get_gate_requirements(current_state, target_state)
        gate_code = gate_meta.get("gate")

        # Gate enforcement - Epic H lifted the bespoke Gate-B signature
        # check into ``app.core.audit_gates.gate_registry`` so additional
        # transition preconditions can be added declaratively elsewhere.
        # ``enforce`` raises ``HTTPException(400)`` with the same detail
        # message the inline check used to emit; the public contract is
        # byte-identical.
        from app.core.audit_gates import gate_registry as _gate_registry

        _gate_registry.enforce(gate_code, data)

        # Gate B - SHARED → PUBLISHED also captures the signature in the
        # container's metadata for the compliance trail.
        updated_metadata: dict[str, Any] | None = None
        is_gate_b = target_state == CDEState.PUBLISHED.value and current_state == CDEState.SHARED.value
        if is_gate_b:
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

        # Audit row - inline in the same session so a rollback cleans it up.
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
        #
        # The payload carries each value under two names. ``from_state`` /
        # ``to_state`` / ``user_id`` are what this module has always sent and
        # what the notifications and webhook consumers read. The core
        # ``cde.container.promoted`` handler in ``core/event_handlers.py``
        # reads ``old_state`` / ``new_state`` / ``promoted_by`` instead, so
        # with only the first set it audited every transition as "" -> "" and
        # never re-emitted ``cde.container.published``: nothing downstream of
        # a publish ever ran. Sending both keeps every reader correct without
        # touching the shared handler.
        #
        # Deferred to the commit rather than detached immediately. The
        # subscribers open their own sessions and the published consumer
        # checks the container really is ``published`` before it notifies
        # anyone; a task scheduled before this transaction commits would read
        # the old state on PostgreSQL and stand down.
        publish_after_commit(
            self.session,
            "cde.container.promoted",
            {
                "project_id": str(container.project_id),
                "container_id": str(container_id),
                "container_code": container.container_code,
                "from_state": current_state,
                "to_state": target_state,
                "old_state": current_state,
                "new_state": target_state,
                "reason": data.reason,
                "gate_code": gate_code,
                "user_id": user_id,
                "promoted_by": user_id,
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
        # Verify container exists - throws 404 otherwise.
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

        # Run a single tuple-yielding query - we pull only the columns we
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

        Two file-linking modes:

        - **Link mode** (``data.document_id`` set): reference an *existing*
          ``Document`` from the Documents hub. The revision reuses that
          document's real ``file_path`` (as its ``storage_key``), size and mime
          type so the file stays downloadable, and ``DocumentRevision.document_id``
          points at the existing row. **No duplicate Document is created.**
        - **Upload mode** (``data.storage_key`` set, no ``document_id``):
          materialise a new ``Document`` row in the Documents hub so a
          freshly-uploaded file appears at ``/documents`` (per the platform
          cross-link rule - see meetings/router.py:991-1020 pattern).

        If neither is supplied, the revision is metadata-only and no Document is
        created (no error).
        """
        container = await self.get_container(container_id)

        if container.cde_state == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add revisions to an archived container",
            )

        # ── Link mode: resolve an existing Document up-front ─────────────────
        # When linking, the revision must carry the source document's REAL
        # file_path so downloads resolve, not a synthesised key. We read the
        # source's path/size/mime here and feed them into the revision below.
        linked_doc_id: str | None = None
        storage_key = data.storage_key
        file_name = data.file_name
        file_size = data.file_size
        mime_type = data.mime_type
        if data.document_id is not None:
            from app.modules.documents.models import Document as _Document

            source_doc = await self.session.get(_Document, data.document_id)
            if source_doc is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document to link not found",
                )
            if source_doc.project_id != container.project_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Document belongs to a different project than the container",
                )
            linked_doc_id = str(source_doc.id)
            # Reuse the source document's real storage path + metadata so the
            # revision points at the actual file (no broken duplicate path).
            storage_key = source_doc.file_path or None
            if not file_size and source_doc.file_size:
                file_size = str(source_doc.file_size)
            if not mime_type and source_doc.mime_type:
                mime_type = source_doc.mime_type
            if not file_name:
                file_name = source_doc.name

        rev_number = await self.revision_repo.next_revision_number(container_id)

        # Generate revision code: P.01.01 for preliminary, C.01 for contractual
        if data.is_preliminary:
            revision_code = f"P.{rev_number:02d}.01"
        else:
            revision_code = f"C.{rev_number:02d}"

        # Content-addressable storage: compute SHA-256 if not supplied
        content_hash = data.content_hash
        if not content_hash:
            hash_input = f"{container_id}:{revision_code}:{file_name}:{file_size or ''}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        revision = DocumentRevision(
            container_id=container_id,
            revision_code=revision_code,
            revision_number=rev_number,
            is_preliminary=data.is_preliminary,
            content_hash=content_hash,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            storage_key=storage_key,
            status="draft",
            change_summary=data.change_summary,
            document_id=linked_doc_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        revision = await self.revision_repo.create(revision)

        # Cache the revision id up-front so the later update_fields() calls
        # work from a plain value instead of re-reading ``revision``.
        revision_id = revision.id

        # Link mode is complete - the revision already points at the existing
        # Document row, so we must NOT synthesise a second one. Update the
        # container's current_revision_id and return.
        if linked_doc_id is not None:
            await self.container_repo.update_fields(
                container_id,
                current_revision_id=str(revision_id),
            )
            revision = await self.revision_repo.get_by_id(revision_id)
            assert revision is not None, "Revision vanished between insert and re-read"
            logger.info(
                "CDE revision %s linked to existing document %s (container %s)",
                revision_code,
                linked_doc_id,
                container_id,
            )
            self._announce_revision_if_published(container, revision_id, revision_code, user_id)
            return revision

        # Upload mode: cross-link into the Documents hub when the revision
        # carries a freshly-uploaded file. Best-effort: failure here must not
        # break the revision create - the CDE row is the source of truth, the
        # Documents row is an index.
        if storage_key:
            try:
                from app.modules.documents.models import Document

                try:
                    file_size_int = int(file_size) if file_size else 0
                except (TypeError, ValueError):
                    file_size_int = 0
                doc = Document(
                    project_id=container.project_id,
                    name=file_name,
                    description=(f"CDE rev {revision_code} - {container.container_code}"),
                    category="cde",
                    file_size=file_size_int,
                    mime_type=mime_type or "",
                    file_path=storage_key,
                    version=rev_number,
                    uploaded_by=str(user_id) if user_id else "",
                    tags=["cde", container.container_code],
                )
                self.session.add(doc)
                await self.session.flush()
                # Read out doc.id once the flush has assigned it.
                doc_id = doc.id
                await self.revision_repo.update_fields(revision_id, document_id=str(doc_id))
                logger.info(
                    "Cross-linked CDE revision %s -> document %s",
                    revision_id,
                    doc_id,
                )

                # Epic C - also register a unified ``oe_file_version``
                # row so the chain is continuous across modules. Best
                # effort; failure does not roll back the revision.
                try:
                    from app.modules.file_versions.helpers import (
                        canonical_name_for,
                    )
                    from app.modules.file_versions.schemas import (
                        FileVersionCreate,
                    )
                    from app.modules.file_versions.service import (
                        FileVersionService,
                    )

                    fv_svc = FileVersionService(self.session)
                    try:
                        uploader = uuid.UUID(str(user_id)) if user_id else None
                    except (TypeError, ValueError):
                        uploader = None
                    fv_payload = FileVersionCreate(
                        project_id=container.project_id,
                        file_kind="document",
                        file_id=str(doc_id),
                        canonical_name=canonical_name_for("document", doc),
                        file_size=file_size_int,
                        notes=data.change_summary,
                    )
                    await fv_svc.register_new_version(fv_payload, uploaded_by_id=uploader)
                except Exception:
                    logger.warning(
                        "Failed to register FileVersion for CDE revision (doc=%s)",
                        doc_id,
                        exc_info=True,
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
        self._announce_revision_if_published(container, revision_id, revision_code, user_id)
        return revision

    def _announce_revision_if_published(
        self,
        container: DocumentContainer,
        revision_id: uuid.UUID,
        revision_code: str,
        user_id: str | None,
    ) -> None:
        """Say so when a revision lands on a container that is already published.

        The state machine has no way back from ``published``, so a container
        crosses Gate B exactly once and ``cde.container.published`` fires once
        per container. Every later revision added to it still becomes the
        container's current revision at once, which is the change that leaves
        measurements and links made against the previous one stale. Without
        this the owners of those records heard about C01 and never about C02.

        A name of its own rather than a second ``cde.container.published``:
        that one means "crossed the approval gate" to the webhook and audit
        readers, and a revision is not a gate. The CDE subscriber listens to
        both. Deferred to the commit for the same reason the promote event is:
        the subscriber reads the container's current revision in its own
        session and must see the one this request wrote.

        ``container.cde_state`` is the state read at the top of
        ``create_revision``; nothing in between changes it.
        """
        if container.cde_state != CDEState.PUBLISHED.value:
            return
        publish_after_commit(
            self.session,
            "cde.revision.published",
            {
                "project_id": str(container.project_id),
                "container_id": str(container.id),
                "container_code": container.container_code,
                "revision_id": str(revision_id),
                "revision_code": revision_code,
                "user_id": user_id,
                "promoted_by": user_id,
            },
            source_module="cde",
        )

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

    async def compute_readiness(self, project_id: uuid.UUID) -> CDEReadinessResponse:
        """Score how ready a project's CDE is to go live.

        Reads the project's real container / transition / revision state, maps it
        onto the readiness engine's observed signal keys, and returns the weighted
        score, level, full checklist and the leading unmet milestones. The scoring
        itself is the pure :mod:`app.modules.cde.readiness` engine - this method
        only translates database facts into the keys that engine recognises.
        """
        facts = await self.container_repo.readiness_facts_for_project(project_id)

        observed: set[str] = set()
        if facts["total"] > 0:
            observed.add("containers_created")
        if facts["has_naming"]:
            observed.add("structured_naming")
        if facts["has_suitability"]:
            observed.add("suitability_assigned")
        if facts["has_classification"]:
            observed.add("classification_used")
        states = facts["states"]
        if states & {"shared", "published", "archived"}:
            observed.add("shared_reached")
        if states & {"published", "archived"}:
            observed.add("published_reached")
        if "archived" in states:
            observed.add("lifecycle_archived")
        if facts["has_signed_transition"]:
            observed.add("gate_signed")
        if facts["has_multi_revision"]:
            observed.add("revision_controlled")

        result = cde_readiness.evaluate(frozenset(observed))
        return CDEReadinessResponse(
            score=result.score,
            level=result.level,
            total_containers=facts["total"],
            signals=[
                ReadinessSignalStatus(
                    key=s.signal.key,
                    label=s.signal.label,
                    weight=s.signal.weight,
                    hint=s.signal.hint,
                    done=s.done,
                )
                for s in result.signals
            ],
            next_actions=[ReadinessNextAction(key=s.key, label=s.label, hint=s.hint) for s in result.next_actions],
        )

    # ── CDE settings (per-project setup) ─────────────────────────────────

    async def get_or_create_settings(self, project_id: uuid.UUID) -> CdeSettings:
        """Return the project's CDE settings, creating a default row if absent.

        Lazy get-or-create (mirrors ``get_or_create_match_settings``) so projects
        that predate the setup wizard get a sensible default configuration on
        first read rather than a 404. The caller owns the commit.
        """
        stmt = select(CdeSettings).where(CdeSettings.project_id == project_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row
        row = CdeSettings(project_id=project_id)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update_settings(
        self,
        project_id: uuid.UUID,
        data: CdeSettingsUpdate,
    ) -> CdeSettings:
        """Apply a partial update to a project's CDE settings.

        Only fields explicitly supplied (``exclude_unset``) are written, so a
        wizard step can save just the part it owns without clobbering the rest.
        """
        row = await self.get_or_create_settings(project_id)
        fields = data.model_dump(exclude_unset=True)
        for key, value in fields.items():
            setattr(row, key, value)
        await self.session.flush()
        await self.session.refresh(row)
        logger.info(
            "CDE settings updated: project=%s fields=%s",
            project_id,
            list(fields.keys()),
        )
        return row

    # ── Approval presets (ISO 19650 review flows) ─────────────────────────

    async def list_approval_presets(self, project_id: uuid.UUID | None) -> CDEApprovalPresetsResponse:
        """List the tenant-wide CDE approval presets a project can adopt.

        Reads the live route + step definitions from ``approval_routes`` (the
        source of truth) and merges in the CDE-facing gate/description framing
        from :data:`app.modules.cde.roles.CDE_REVIEW_PRESET_META`. When
        ``project_id`` is given, also reports which preset (if any) is
        currently adopted so the UI can show an "Active" state.
        """
        from app.modules.approval_routes.service import ApprovalRouteService

        engine = ApprovalRouteService(self.session)
        routes = await engine.list_routes(project_id=None, target_kind="submittal", include_inactive=False)
        by_key = {r.system_key: r for r in routes if r.system_key in CDE_REVIEW_PRESET_META}

        presets: list[CDEApprovalPresetEntry] = []
        for key in CDE_REVIEW_PRESET_KEYS:
            route = by_key.get(key)
            if route is None:
                # Seed has not run yet (fresh DB) - skip rather than 500.
                continue
            meta = CDE_REVIEW_PRESET_META[key]
            steps = await engine.list_steps(route.id)
            presets.append(
                CDEApprovalPresetEntry(
                    system_key=key,
                    route_id=route.id,
                    name=route.name,
                    gate=meta["gate"],
                    description=meta["description"],
                    steps=[
                        CDEApprovalPresetStep(
                            ordinal=s.ordinal,
                            approver_role=s.approver_role,
                            mode=s.mode,
                            required_approver_count=s.required_approver_count,
                            sla_hours=s.sla_hours,
                        )
                        for s in sorted(steps, key=lambda s: s.ordinal)
                    ],
                )
            )

        active_key: str | None = None
        active_route_id: uuid.UUID | None = None
        if project_id is not None:
            settings = await self.get_or_create_settings(project_id)
            active_key = settings.review_preset_key
            active_route_id = settings.review_route_id

        return CDEApprovalPresetsResponse(
            presets=presets,
            active_system_key=active_key,
            active_route_id=active_route_id,
        )

    async def apply_approval_preset(
        self,
        project_id: uuid.UUID,
        system_key: str,
        *,
        actor_id: str | None,
    ) -> CDEApprovalPresetApplyResponse:
        """Adopt a CDE approval preset as this project's editable review route.

        Clones the tenant-wide preset (via ``approval_routes.clone_route``)
        into a project-scoped route with no ``system_key`` - so it can be
        tailored in the Approval routes editor right after adoption - and
        records both the preset label and the new route on the project's CDE
        settings. Adopting a second preset (or re-adopting the same one)
        simply clones a fresh route each time; the previous clone is left in
        place (it may already carry running instances) so nothing is lost.
        """
        from app.modules.approval_routes.service import ApprovalRouteService

        if system_key not in CDE_REVIEW_PRESET_META:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown CDE approval preset {system_key!r}",
            )

        engine = ApprovalRouteService(self.session)
        routes = await engine.list_routes(project_id=None, target_kind="submittal", include_inactive=True)
        source = next((r for r in routes if r.system_key == system_key), None)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval preset {system_key!r} is not seeded yet",
            )

        actor_uuid: uuid.UUID | None
        try:
            actor_uuid = uuid.UUID(str(actor_id)) if actor_id else None
        except (ValueError, TypeError):
            actor_uuid = None

        clone = await engine.clone_route(
            source.id,
            project_id=project_id,
            name=None,
            created_by=actor_uuid,
        )
        clone_steps = await engine.list_steps(clone.id)

        settings = await self.update_settings(
            project_id,
            CdeSettingsUpdate(review_preset_key=system_key),
        )
        settings.review_route_id = clone.id
        await self.session.flush()
        await self.session.refresh(settings)

        logger.info(
            "CDE approval preset applied: project=%s preset=%s route=%s",
            project_id,
            system_key,
            clone.id,
        )
        return CDEApprovalPresetApplyResponse(
            settings=CdeSettingsResponse.model_validate(settings),
            route_id=clone.id,
            route_name=clone.name,
            step_count=len(clone_steps),
        )

    async def evaluate_go_live_gate(self, project_id: uuid.UUID) -> GoLiveGateStatus:
        """Decide whether the CDE may be opened to the whole team.

        The go-live gate is the anti-"showroom" protection: a team cannot invite
        everyone onto a common data environment that has not actually been
        exercised. When the gate is enabled, the project's readiness ``level``
        must meet the configured ``min_readiness_level``; when it is disabled the
        gate always allows. Read-only - it computes readiness but changes nothing.
        """
        settings = await self.get_or_create_settings(project_id)
        readiness = await self.compute_readiness(project_id)
        required = settings.min_readiness_level

        if not settings.go_live_gate_enabled:
            allowed = True
            reason = "Go-live gate is disabled for this project."
        else:
            allowed = cde_readiness.meets_level(readiness.level, required)
            if allowed:
                reason = f"CDE readiness is '{readiness.level}', which meets the required '{required}'."
            else:
                reason = (
                    f"CDE readiness is '{readiness.level}', below the required '{required}'. "
                    "Exercise the CDE workflow further before inviting the whole team."
                )

        return GoLiveGateStatus(
            project_id=project_id,
            gate_enabled=settings.go_live_gate_enabled,
            allowed=allowed,
            level=readiness.level,
            min_readiness_level=required,
            score=readiness.score,
            reason=reason,
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
        parts = [p for p in (project, originator, functional, spatial, form, discipline, number) if p]
        return "-".join(parts)
