"""BIM Hub service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — business logic for BIM data management.

Stateless service layer. Handles:
- BIM model CRUD
- Element bulk import (for CAD pipeline results)
- BOQ link management
- Quantity map rules application
- Model diff calculation (compare elements by stable_id + geometry_hash)
"""

import fnmatch
import logging
import shutil
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import event_bus
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.models import (
    BIMElement,
    BIMElementGroup,
    BIMModel,
    BIMModelDiff,
    BIMQuantityMap,
    BOQElementLink,
)
from app.modules.bim_hub.repository import (
    BIMElementRepository,
    BIMModelDiffRepository,
    BIMModelRepository,
    BIMQuantityMapRepository,
    BOQElementLinkRepository,
)
from app.modules.bim_hub.schemas import (
    BIMElementCreate,
    BIMElementGroupCreate,
    BIMElementGroupResponse,
    BIMElementGroupUpdate,
    BIMModelCreate,
    BIMModelUpdate,
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
    BOQElementLinkCreate,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.boq.models import BOQ, Position

logger = logging.getLogger(__name__)
_logger_events = logging.getLogger(__name__ + ".events")


async def _safe_publish(
    name: str,
    data: dict[str, Any],
    source_module: str = "oe_bim_hub",
) -> None:
    """Publish event safely — ignores MissingGreenlet errors with SQLite async."""
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_events.debug("Event publish skipped (SQLite async): %s", name)

# Sentinel key used by ``list_elements_with_links`` to signal that a
# BIM-model validation report exists. Routers can detect "report ran but
# element passed" vs "no report at all" by checking this key's presence.
_VALIDATION_REPORT_SENTINEL: uuid.UUID = uuid.UUID(int=0)


async def _strip_orphaned_bim_links(
    session: AsyncSession,
    deleted_element_ids: list[str],
    project_id: uuid.UUID | None,
) -> None:
    """Strip ``deleted_element_ids`` from every JSON-array link site.

    Three cross-module link types denormalise BIM element ids into JSON
    array columns instead of FK tables (Task.bim_element_ids,
    Activity.bim_element_ids, Requirement.metadata_["bim_element_ids"]).
    The FK-based link types (BOQElementLink, DocumentBIMLink) clean
    themselves up via ``ondelete='CASCADE'``; the JSON ones do not, so
    deleted element ids would otherwise leak forever and confuse the
    BIM viewer's "linked tasks/activities/requirements" panel as well
    as any reverse-query helper.

    Runs INLINE on the caller's session — must NOT open a new session.
    The previous implementation lived in an event subscriber that
    opened ``async_session_factory()``, but under SQLite write-lock
    contention (the upstream service is mid-transaction) the new
    session deadlocked.  Sharing the active session means the cleanup
    runs inside the same transaction so a failure rolls back atomically
    with the upstream delete, and there is no lock contention.

    The actual filter happens in Python because neither SQLite nor
    PostgreSQL share a portable JSON-array-contains/remove operator
    we can use for cross-dialect bulk updates.  ``project_id`` scopes
    the candidate set so the scan stays bounded.
    """
    if not deleted_element_ids:
        return

    targets: set[str] = {str(eid) for eid in deleted_element_ids if eid}
    if not targets:
        return

    # Defer imports so this helper can be loaded by the bim_hub module
    # without dragging tasks/schedule/requirements into the import graph
    # at module level (the loader auto-imports modules in dependency order
    # and bim_hub's manifest doesn't list these as hard dependencies).
    from app.modules.requirements.models import Requirement, RequirementSet
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.tasks.models import Task

    # ── Tasks ──────────────────────────────────────────────────────────
    try:
        task_stmt = select(Task)
        if project_id is not None:
            task_stmt = task_stmt.where(Task.project_id == project_id)
        task_rows = (await session.execute(task_stmt)).scalars().all()
        cleaned_tasks = 0
        for task in task_rows:
            ids = task.bim_element_ids or []
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                task.bim_element_ids = kept
                cleaned_tasks += 1
        if cleaned_tasks:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d task(s)",
                len(targets),
                cleaned_tasks,
            )
    except Exception:  # noqa: BLE001 — best-effort, never break upstream
        logger.warning(
            "Orphan cleanup failed for tasks (project=%s)",
            project_id,
            exc_info=True,
        )

    # ── Activities ─────────────────────────────────────────────────────
    try:
        act_stmt = select(Activity).where(Activity.bim_element_ids.isnot(None))
        if project_id is not None:
            act_stmt = act_stmt.join(
                Schedule, Activity.schedule_id == Schedule.id
            ).where(Schedule.project_id == project_id)
        act_rows = (await session.execute(act_stmt)).scalars().all()
        cleaned_activities = 0
        for activity in act_rows:
            ids = activity.bim_element_ids
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                activity.bim_element_ids = kept
                cleaned_activities += 1
        if cleaned_activities:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d activity(s)",
                len(targets),
                cleaned_activities,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Orphan cleanup failed for activities (project=%s)",
            project_id,
            exc_info=True,
        )

    # ── Requirements ───────────────────────────────────────────────────
    try:
        req_stmt = select(Requirement)
        if project_id is not None:
            req_stmt = req_stmt.join(
                RequirementSet, Requirement.requirement_set_id == RequirementSet.id
            ).where(RequirementSet.project_id == project_id)
        req_rows = (await session.execute(req_stmt)).scalars().all()
        cleaned_reqs = 0
        for req in req_rows:
            meta = dict(req.metadata_ or {})
            ids = meta.get("bim_element_ids")
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                meta["bim_element_ids"] = kept
                req.metadata_ = meta
                cleaned_reqs += 1
        if cleaned_reqs:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d requirement(s)",
                len(targets),
                cleaned_reqs,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Orphan cleanup failed for requirements (project=%s)",
            project_id,
            exc_info=True,
        )

    await session.flush()

# On-disk directory for BIM geometry files (original.{ext}, geometry.dae,
# dataframe.xlsx, …). Matches the layout used by ``bim_hub.router`` which
# writes to ``<repo>/data/bim/{project_id}/{model_id}/``.
#
# ``service.py`` → ``app/modules/bim_hub/service.py`` → parents[4] == repo root
_BIM_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "bim"


class BIMHubService:
    """Business logic for BIM Hub operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.model_repo = BIMModelRepository(session)
        self.element_repo = BIMElementRepository(session)
        self.link_repo = BOQElementLinkRepository(session)
        self.qmap_repo = BIMQuantityMapRepository(session)
        self.diff_repo = BIMModelDiffRepository(session)

    # ── BIM Model CRUD ───────────────────────────────────────────────────────

    async def create_model(
        self,
        data: BIMModelCreate,
        user_id: str | None = None,
    ) -> BIMModel:
        """Create a new BIM model record."""
        model = BIMModel(
            project_id=data.project_id,
            name=data.name,
            discipline=data.discipline,
            model_format=data.model_format,
            version=data.version,
            import_date=data.import_date,
            status=data.status,
            bounding_box=data.bounding_box,
            original_file_id=data.original_file_id,
            canonical_file_path=data.canonical_file_path,
            parent_model_id=data.parent_model_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        model = await self.model_repo.create(model)
        logger.info("BIM model created: %s (project=%s)", data.name, data.project_id)
        return model

    async def get_model(self, model_id: uuid.UUID) -> BIMModel:
        """Get a BIM model by ID. Raises 404 if not found."""
        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        return model

    async def list_models(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BIMModel], int]:
        """List BIM models for a project."""
        return await self.model_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def update_model(
        self,
        model_id: uuid.UUID,
        data: BIMModelUpdate,
    ) -> BIMModel:
        """Update a BIM model's fields."""
        await self.get_model(model_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return await self.get_model(model_id)

        await self.model_repo.update_fields(model_id, **fields)
        updated = await self.model_repo.get(model_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found after update",
            )
        logger.info("BIM model updated: %s (fields=%s)", model_id, list(fields.keys()))
        return updated

    async def delete_model(self, model_id: uuid.UUID) -> None:
        """Delete a BIM model, all its elements, and stored geometry blobs.

        CASCADE on the DB foreign key handles element deletion automatically.
        Orphaned BIM-link references in JSON columns (Task.bim_element_ids,
        Activity.bim_element_ids, Requirement.metadata_["bim_element_ids"])
        are cleaned lazily — callers that resolve these ids already tolerate
        missing elements, and a future background sweeper can purge stale
        references.  This keeps the delete O(1) w.r.t. element count so
        models with 7 000+ elements don't time out the HTTP request.

        Blob cleanup is best-effort — a failure to remove the blobs MUST
        NOT fail the delete operation (the DB row is already gone and the
        orphan sweeper can pick up any stragglers later).
        """
        model = await self.get_model(model_id)  # 404 check
        project_id = model.project_id

        # Publish a single model-level delete event instead of per-element
        # events.  Vector-store subscribers can bulk-purge by model_id.
        await _safe_publish(
            "bim_hub.model.deleted",
            {
                "model_id": str(model_id),
                "project_id": str(project_id) if project_id else None,
            },
        )

        # CASCADE handles element rows; no need to fetch element ids.
        await self.model_repo.delete(model_id)
        logger.info("BIM model deleted: %s  (elements removed via CASCADE)", model_id)

        # NOTE: _strip_orphaned_bim_links is intentionally skipped here.
        # For large models (7000+ elements) it loaded every Task, Activity,
        # and Requirement row in the project and filtered in Python, causing
        # 30+ second timeouts.  JSON-array link sites tolerate dangling ids
        # gracefully (the BIM viewer already ignores missing elements), and
        # a periodic orphan-sweep job can clean them up in the background.

        # Best-effort blob cleanup (after DB delete so we never strand
        # files belonging to a still-live DB row).  Routed through the
        # storage backend so S3 deployments work transparently.
        await bim_file_storage.delete_model_blobs(project_id, model_id)

    async def cleanup_orphan_bim_files(self) -> dict[str, Any]:
        """Scan ``data/bim/`` and remove directories with no matching DB row.

        Walks ``data/bim/{project_id}/{model_id}/`` and deletes any model
        directory whose ``model_id`` is not present in the ``oe_bim_models``
        table. Also removes empty ``project_id`` directories.

        Returns a summary with the count of removed model dirs and bytes
        reclaimed. Called from the admin-only
        ``POST /api/v1/bim_hub/cleanup-orphans/`` endpoint.
        """
        if not _BIM_DATA_DIR.is_dir():
            return {"scanned": 0, "removed_models": 0, "removed_projects": 0, "bytes_freed": 0}

        # Load all known model ids from the DB in a single query.
        from app.modules.bim_hub.models import BIMModel

        result = await self.session.execute(select(BIMModel.id))
        known_ids = {str(row[0]) for row in result.all()}

        scanned = 0
        removed_models = 0
        removed_projects = 0
        bytes_freed = 0
        removed_details: list[str] = []

        for project_dir in _BIM_DATA_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for model_dir in project_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                scanned += 1
                if model_dir.name in known_ids:
                    continue
                # Orphan — compute size then remove.
                try:
                    size = sum(
                        f.stat().st_size
                        for f in model_dir.rglob("*")
                        if f.is_file()
                    )
                except OSError:
                    size = 0
                try:
                    shutil.rmtree(model_dir, ignore_errors=True)
                    removed_models += 1
                    bytes_freed += size
                    removed_details.append(str(model_dir))
                    logger.info(
                        "Orphan BIM dir removed: %s (%d bytes)", model_dir, size
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to remove orphan %s: %s", model_dir, exc)
            # Drop now-empty project directories.
            try:
                if not any(project_dir.iterdir()):
                    project_dir.rmdir()
                    removed_projects += 1
            except OSError:
                pass

        return {
            "scanned": scanned,
            "removed_models": removed_models,
            "removed_projects": removed_projects,
            "bytes_freed": bytes_freed,
            "removed": removed_details,
        }

    async def cleanup_stale_processing(
        self,
        project_id: uuid.UUID,
        max_age_hours: int = 1,
    ) -> int:
        """Remove models stuck in 'processing' with 0 elements older than max_age_hours."""
        count = await self.model_repo.cleanup_stale_processing(
            project_id, max_age_hours=max_age_hours
        )
        if count:
            logger.info(
                "Cleaned up %d stale processing model(s) for project %s",
                count,
                project_id,
            )
        return count

    # ── BIM Elements ─────────────────────────────────────────────────────────

    async def list_elements(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int]:
        """List elements for a model with optional filters."""
        await self.get_model(model_id)  # 404 check
        return await self.element_repo.list_for_model(
            model_id,
            element_type=element_type,
            storey=storey,
            discipline=discipline,
            offset=offset,
            limit=limit,
        )

    async def list_elements_with_links(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        group_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[
        list[BIMElement],
        int,
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
    ]:
        """List elements AND their BOQ / Document / Task / Activity / Requirement briefs.

        Returns ``(elements, total, boq_links_by_element_id,
        doc_links_by_element_id, task_links_by_element_id,
        activity_briefs_by_element_id, requirement_briefs_by_element_id,
        validation_summaries_by_element_id)`` where each brief is a plain
        dict with the fields expected by the corresponding Pydantic brief
        schema.

        BOQ briefs match ``BOQElementLinkBrief`` (id, boq_position_id,
        boq_position_ordinal, boq_position_description, link_type, confidence).

        Document briefs match ``DocumentLinkBrief`` (id, document_id,
        document_name, document_category, link_type, confidence).

        Task briefs match ``bim_hub.schemas.TaskBrief`` (id, project_id,
        title, status, task_type, due_date). Tasks are denormalised — each
        ``Task`` row carries a JSON ``bim_element_ids`` array — so we load
        all project tasks once and filter in Python. This is cross-dialect
        safe and correct for the bounded sizes we expect (< a few thousand
        tasks per project).

        Activity briefs match ``bim_hub.schemas.ActivityBrief`` (id, name,
        start_date, end_date, status, percent_complete). Activities are
        loaded through ``oe_schedule_schedule`` for the model's project and
        filtered in Python on their ``bim_element_ids`` JSON array — same
        rationale as tasks.

        This avoids an N+1 by issuing:
            1. A single SELECT on BIMElement with ``selectinload(boq_links)``.
            2. A single SELECT on Position for all distinct linked position ids.
            3. A single SELECT joining ``oe_documents_bim_link`` → ``oe_documents_document``
               filtered by the element ids in the current page.
            4. A single SELECT on Task for all tasks in the project containing
               the model.
            5. A single SELECT on Activity joined to Schedule for all
               activities in the model's project.
        """
        # Local imports to avoid import-time cycles between bim_hub and
        # documents / tasks / schedule / requirements.
        from app.modules.documents.models import Document, DocumentBIMLink
        from app.modules.requirements.models import Requirement, RequirementSet
        from app.modules.schedule.models import Activity, Schedule
        from app.modules.tasks.models import Task

        model = await self.get_model(model_id)  # 404 check + need project_id

        # ── Step 1: load elements with BOQ links eagerly ────────────────
        base = select(BIMElement).where(BIMElement.model_id == model_id)
        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if storey is not None:
            base = base.where(BIMElement.storey == storey)
        if discipline is not None:
            base = base.where(BIMElement.discipline == discipline)

        # Lazy-load by group: restrict to member element ids when a group
        # filter is supplied.  This makes cross-module deep-links like
        # ``/bim?group={id}`` load only the relevant subset instead of the
        # entire model (7k+ elements).
        if group_id is not None:
            group = await self.get_element_group(group_id)
            member_ids_raw = group.element_ids or []
            member_uuids = [
                uuid.UUID(eid) if isinstance(eid, str) else eid
                for eid in member_ids_raw
            ]
            if member_uuids:
                base = base.where(BIMElement.id.in_(member_uuids))
            else:
                # Group has no members — return empty result set.
                base = base.where(False)  # type: ignore[arg-type]

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(selectinload(BIMElement.boq_links))
            .order_by(BIMElement.created_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        elements = list(result.scalars().all())
        element_ids = [elem.id for elem in elements]

        # ── Step 2: fetch ordinals/descriptions for every linked position
        pos_ids: set[uuid.UUID] = set()
        for elem in elements:
            for lnk in elem.boq_links or []:
                pos_ids.add(lnk.boq_position_id)

        pos_info: dict[uuid.UUID, tuple[str | None, str | None]] = {}
        if pos_ids:
            pos_stmt = select(
                Position.id, Position.ordinal, Position.description
            ).where(Position.id.in_(pos_ids))
            pos_result = await self.session.execute(pos_stmt)
            for pid, ordinal, desc in pos_result.all():
                pos_info[pid] = (ordinal, desc)

        # ── Step 3: build BOQ brief dicts per element ───────────────────
        boq_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for elem in elements:
            briefs: list[dict[str, Any]] = []
            for lnk in elem.boq_links or []:
                ordinal, desc = pos_info.get(lnk.boq_position_id, (None, None))
                briefs.append(
                    {
                        "id": lnk.id,
                        "boq_position_id": lnk.boq_position_id,
                        "boq_position_ordinal": ordinal,
                        "boq_position_description": desc,
                        "link_type": lnk.link_type,
                        "confidence": lnk.confidence,
                    }
                )
            boq_links_by_element_id[elem.id] = briefs

        # ── Step 4: fetch DocumentBIMLink rows joined with Document for this page
        doc_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {
            eid: [] for eid in element_ids
        }
        if element_ids:
            doc_link_stmt = (
                select(
                    DocumentBIMLink.id,
                    DocumentBIMLink.bim_element_id,
                    DocumentBIMLink.document_id,
                    DocumentBIMLink.link_type,
                    DocumentBIMLink.confidence,
                    Document.name,
                    Document.category,
                )
                .join(Document, Document.id == DocumentBIMLink.document_id)
                .where(DocumentBIMLink.bim_element_id.in_(element_ids))
                .order_by(DocumentBIMLink.created_at.desc())
            )
            doc_link_result = await self.session.execute(doc_link_stmt)
            for row in doc_link_result.all():
                link_id, elem_id, doc_id, link_type, confidence, doc_name, doc_cat = row
                doc_links_by_element_id.setdefault(elem_id, []).append(
                    {
                        "id": link_id,
                        "document_id": doc_id,
                        "document_name": doc_name,
                        "document_category": doc_cat,
                        "link_type": link_type,
                        "confidence": confidence,
                    }
                )

        # ── Step 5: fetch Task rows for this project and filter in Python ──
        # Tasks store bim_element_ids as a denormalised JSON array; pulling all
        # project tasks once and filtering in memory is cross-dialect safe and
        # fine for the bounded sizes we expect.
        task_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {
            eid: [] for eid in element_ids
        }
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            task_stmt = select(Task).where(Task.project_id == model.project_id)
            task_result = await self.session.execute(task_stmt)
            for task in task_result.scalars().all():
                raw_ids = task.bim_element_ids or []
                if not raw_ids:
                    continue
                task_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & task_ids_as_str
                if not matching:
                    continue
                brief = {
                    "id": task.id,
                    "project_id": task.project_id,
                    "title": task.title,
                    "status": task.status,
                    "task_type": task.task_type,
                    "due_date": task.due_date,
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        task_links_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 6: fetch Schedule Activities for this project and filter ──
        # Activities store ``bim_element_ids`` as a JSON list on each row.
        # We join through ``oe_schedule_schedule`` to scope by the model's
        # project, then filter in Python — same cross-dialect reasoning as
        # the task loop above.
        activity_briefs_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {
            eid: [] for eid in element_ids
        }
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            activity_stmt = (
                select(Activity)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == model.project_id)
                .where(Activity.bim_element_ids.isnot(None))
            )
            activity_result = await self.session.execute(activity_stmt)
            for act in activity_result.scalars().all():
                raw_ids = act.bim_element_ids
                if not isinstance(raw_ids, list) or not raw_ids:
                    continue
                act_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & act_ids_as_str
                if not matching:
                    continue
                try:
                    pct = float(act.progress_pct) if act.progress_pct else 0.0
                except (TypeError, ValueError):
                    pct = 0.0
                brief = {
                    "id": act.id,
                    "name": act.name,
                    "start_date": act.start_date,
                    "end_date": act.end_date,
                    "status": act.status,
                    "percent_complete": pct,
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        activity_briefs_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 6.5: fetch Requirement rows for this project ──────────
        # Requirements pin themselves to BIM elements via a JSON array
        # in ``Requirement.metadata_["bim_element_ids"]`` (no dedicated
        # column to keep migrations cheap).  We load every requirement
        # in the project once and filter in Python — same cross-dialect
        # reasoning as the task and activity loops above.
        requirement_briefs_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {
            eid: [] for eid in element_ids
        }
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            req_stmt = (
                select(Requirement)
                .join(
                    RequirementSet,
                    Requirement.requirement_set_id == RequirementSet.id,
                )
                .where(RequirementSet.project_id == model.project_id)
            )
            req_result = await self.session.execute(req_stmt)
            for req in req_result.scalars().all():
                raw_meta = req.metadata_ or {}
                raw_ids = raw_meta.get("bim_element_ids") or []
                if not isinstance(raw_ids, list) or not raw_ids:
                    continue
                req_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & req_ids_as_str
                if not matching:
                    continue
                brief = {
                    "id": req.id,
                    "requirement_set_id": req.requirement_set_id,
                    "entity": req.entity or "",
                    "attribute": req.attribute or "",
                    "constraint_type": req.constraint_type or "equals",
                    "constraint_value": req.constraint_value or "",
                    "unit": req.unit or "",
                    "category": req.category or "general",
                    "priority": req.priority or "must",
                    "status": req.status or "open",
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        requirement_briefs_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 7: load latest ValidationReport for this model ──────────
        # Look up the most recent ``target_type='bim_model'`` report and
        # zip its per-element results into a dict keyed by element_id.
        # Missing reports are fine — the router falls back to 'unchecked'.
        #
        # To distinguish "report exists, element passed" from "no report
        # exists at all", we stash a sentinel entry under
        # ``_VALIDATION_REPORT_SENTINEL`` (UUID(int=0)) whose list contains
        # a single marker dict. The router inspects this key before the
        # per-element loop.
        validation_summaries_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {
            eid: [] for eid in element_ids
        }
        if element_ids:
            from app.modules.validation.repository import ValidationReportRepository

            val_repo = ValidationReportRepository(self.session)
            latest_report = await val_repo.get_latest_for_target(
                target_type="bim_model",
                target_id=str(model_id),
            )
            if latest_report is not None:
                validation_summaries_by_element_id[_VALIDATION_REPORT_SENTINEL] = [
                    {"report_id": str(latest_report.id)}
                ]
                element_id_strs = {str(eid): eid for eid in element_ids}
                raw_results = latest_report.results or []
                for entry in raw_results:
                    if not isinstance(entry, dict):
                        continue
                    entry_eid = entry.get("element_id")
                    if not entry_eid:
                        continue
                    key_uuid = element_id_strs.get(str(entry_eid))
                    if key_uuid is None:
                        continue
                    severity = entry.get("severity") or "info"
                    if severity not in ("error", "warning", "info"):
                        severity = "info"
                    validation_summaries_by_element_id.setdefault(key_uuid, []).append(
                        {
                            "rule_id": entry.get("rule_id", ""),
                            "severity": severity,
                            "message": entry.get("message", ""),
                        }
                    )

        return (
            elements,
            total,
            boq_links_by_element_id,
            doc_links_by_element_id,
            task_links_by_element_id,
            activity_briefs_by_element_id,
            requirement_briefs_by_element_id,
            validation_summaries_by_element_id,
        )

    async def get_element(self, element_id: uuid.UUID) -> BIMElement:
        """Get a single element by ID. Raises 404 if not found."""
        element = await self.element_repo.get(element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        return element

    async def bulk_import_elements(
        self,
        model_id: uuid.UUID,
        elements_data: list[BIMElementCreate],
    ) -> list[BIMElement]:
        """Bulk import elements for a model (from CAD pipeline results).

        Replaces all existing elements for the model and updates
        element_count on the model record.
        """
        model = await self.get_model(model_id)

        # Capture existing element ids so we can emit element.deleted
        # events for the vector store before wiping them.
        existing_ids_stmt = select(BIMElement.id).where(BIMElement.model_id == model_id)
        existing_ids = [
            row_id for (row_id,) in (await self.session.execute(existing_ids_stmt)).all()
        ]

        # Delete existing elements
        deleted = await self.element_repo.delete_all_for_model(model_id)
        if deleted:
            logger.info("Deleted %d existing elements for model %s", deleted, model_id)

        # Strip orphaned references from JSON-array link sites (Tasks,
        # Activities, Requirements) BEFORE we fan out the vector-delete
        # events.  Runs inline on the active session so SQLite write-lock
        # contention can not bite us.
        await _strip_orphaned_bim_links(
            self.session,
            [str(eid) for eid in existing_ids],
            model.project_id,
        )

        for old_id in existing_ids:
            await _safe_publish(
                "bim_hub.element.deleted",
                {
                    "element_id": str(old_id),
                    "model_id": str(model_id),
                    "project_id": str(model.project_id) if model.project_id else None,
                },
            )

        # Create new elements
        elements = [
            BIMElement(
                model_id=model_id,
                stable_id=e.stable_id,
                element_type=e.element_type,
                name=e.name,
                storey=e.storey,
                discipline=e.discipline,
                properties=e.properties,
                quantities=e.quantities,
                geometry_hash=e.geometry_hash,
                bounding_box=e.bounding_box,
                mesh_ref=e.mesh_ref,
                lod_variants=e.lod_variants,
                metadata_=e.metadata,
            )
            for e in elements_data
        ]
        created = await self.element_repo.bulk_create(elements)

        for elem in created:
            await _safe_publish(
                "bim_hub.element.created",
                {
                    "element_id": str(elem.id),
                    "model_id": str(model_id),
                    "project_id": str(model.project_id) if model.project_id else None,
                },
            )

        # Compute unique storeys
        storeys = {e.storey for e in created if e.storey}

        # Eagerly capture the model name and the freshly-assigned
        # element PKs BEFORE ``update_fields`` — the repository helper
        # calls ``session.expire_all()`` which invalidates every mapped
        # instance in this session (including ``model`` and every row
        # we just created).  Attribute access after expire triggers a
        # lazy reload that needs a greenlet context, and under the
        # async HTTP test harness that lazy load raises
        # ``MissingGreenlet`` while building the response.
        model_name = model.name
        created_ids = [elem.id for elem in created]

        # Update model counts
        await self.model_repo.update_fields(
            model_id,
            element_count=len(created),
            storey_count=len(storeys),
            status="active",
        )

        # Re-fetch the newly-created elements in a single round trip so
        # callers receive non-expired ORM instances that Pydantic can
        # serialise without lazy loads.
        refresh_stmt = (
            select(BIMElement)
            .where(BIMElement.id.in_(created_ids))
            .options(selectinload(BIMElement.boq_links))
        )
        refreshed = list(
            (await self.session.execute(refresh_stmt)).scalars().all()
        )
        # Preserve the insertion order the caller requested — the IN
        # filter above returns in arbitrary order.
        order_index = {rid: idx for idx, rid in enumerate(created_ids)}
        refreshed.sort(key=lambda e: order_index.get(e.id, len(order_index)))

        logger.info(
            "Bulk imported %d elements for model %s (%d storeys)",
            len(refreshed),
            model_name,
            len(storeys),
        )
        return refreshed

    # ── BOQ Links ────────────────────────────────────────────────────────────

    async def list_links_for_position(
        self,
        boq_position_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all BIM element links for a BOQ position."""
        return await self.link_repo.list_by_boq_position(boq_position_id)

    async def create_link(
        self,
        data: BOQElementLinkCreate,
        user_id: str | None = None,
    ) -> BOQElementLink:
        """Create a link between a BOQ position and a BIM element.

        Also mirrors the BIM element id into ``Position.cad_element_ids``
        so legacy consumers that read that JSON array stay in sync with
        the canonical ``oe_bim_boq_link`` table.
        """
        # Verify element exists
        element = await self.element_repo.get(data.bim_element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )

        link = BOQElementLink(
            boq_position_id=data.boq_position_id,
            bim_element_id=data.bim_element_id,
            link_type=data.link_type,
            confidence=data.confidence,
            rule_id=data.rule_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        link = await self.link_repo.create(link)

        # Keep Position.cad_element_ids in sync (legacy JSON mirror).
        await self._append_cad_element_id(
            data.boq_position_id, data.bim_element_id
        )

        # Auto-populate BOQ position quantity from linked element quantities.
        await self._sync_boq_quantity_from_links(data.boq_position_id)

        logger.info(
            "BOQ-BIM link created: pos=%s elem=%s type=%s",
            data.boq_position_id,
            data.bim_element_id,
            data.link_type,
        )
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        """Delete a BOQ-BIM link and drop the mirrored id from the position."""
        link = await self.link_repo.get(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ-BIM link not found",
            )
        position_id = link.boq_position_id
        element_id = link.bim_element_id
        await self.link_repo.delete(link_id)

        # Remove the mirrored id from Position.cad_element_ids.
        await self._remove_cad_element_id(position_id, element_id)

        # Re-sync BOQ position quantity after link removal.
        await self._sync_boq_quantity_from_links(position_id)

        logger.info("BOQ-BIM link deleted: %s", link_id)

    # ── cad_element_ids sync helpers ─────────────────────────────────────

    async def _append_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Append ``element_id`` to ``Position.cad_element_ids`` if missing.

        Initialises the array when the column is NULL (legacy rows) and
        skips duplicates. No-op when the position no longer exists — the
        caller is responsible for verifying position existence beforehand.
        """
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str not in current:
            current.append(elem_str)
            pos.cad_element_ids = current
            # Re-assign to force SQLAlchemy to notice the mutation on JSON.
            await self.session.flush()

    async def _sync_boq_quantity_from_links(
        self,
        position_id: uuid.UUID,
    ) -> None:
        """Recompute ``Position.quantity`` from all linked BIM element quantities.

        Strategy: sum the quantity field from linked elements that best matches
        the position's unit.  Mapping:

        - m3  / m³  → volume_m3
        - m2  / m²  → area_m2
        - m   / lfm → length_m
        - kg         → weight_kg (if present)

        When no matching quantity key is found we fall back to the first
        non-zero numeric quantity value.  The position is only updated when
        the computed value is > 0 so manual overrides are not clobbered by
        elements with missing data.
        """
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return

        links = await self.link_repo.list_by_boq_position(position_id)
        if not links:
            return

        # Determine which quantity key to sum based on BOQ position unit.
        unit = (pos.unit or "").strip().lower()
        _UNIT_TO_QKEY: dict[str, list[str]] = {
            "m3": ["volume_m3", "Volume", "volume"],
            "m³": ["volume_m3", "Volume", "volume"],
            "m2": ["area_m2", "Area", "area"],
            "m²": ["area_m2", "Area", "area"],
            "m": ["length_m", "Length", "length"],
            "lfm": ["length_m", "Length", "length"],
            "kg": ["weight_kg", "Weight", "weight"],
            "t": ["weight_kg", "Weight", "weight"],
        }
        preferred_keys = _UNIT_TO_QKEY.get(unit, [])

        total = Decimal(0)
        for lnk in links:
            elem = await self.element_repo.get(lnk.bim_element_id)
            if elem is None:
                continue
            qtys = elem.quantities or {}

            value: Decimal | None = None
            # Try preferred keys first
            for key in preferred_keys:
                raw = qtys.get(key)
                if raw is not None:
                    try:
                        value = Decimal(str(raw))
                        break
                    except (InvalidOperation, TypeError, ValueError):
                        continue

            # Fallback: first non-zero numeric value
            if value is None:
                for v in qtys.values():
                    try:
                        candidate = Decimal(str(v))
                        if candidate > 0:
                            value = candidate
                            break
                    except (InvalidOperation, TypeError, ValueError):
                        continue

            if value is not None and value > 0:
                total += value

        if total > 0:
            # Round to 4 decimal places to avoid floating-point noise
            pos.quantity = str(total.quantize(Decimal("0.0001")))
            # Also recompute total = quantity * unit_rate
            try:
                rate = Decimal(pos.unit_rate or "0")
                pos.total = str((total * rate).quantize(Decimal("0.01")))
            except (InvalidOperation, TypeError, ValueError):
                pass
            await self.session.flush()
            logger.info(
                "BOQ position %s quantity auto-updated to %s from %d linked BIM elements",
                position_id,
                pos.quantity,
                len(links),
            )

    async def _remove_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Remove ``element_id`` from ``Position.cad_element_ids`` if present."""
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str in current:
            current.remove(elem_str)
            pos.cad_element_ids = current
            await self.session.flush()

    # ── Quantity Maps ────────────────────────────────────────────────────────

    async def list_quantity_maps(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMQuantityMap], int]:
        """List all quantity mapping rules."""
        return await self.qmap_repo.list_all(offset=offset, limit=limit)

    async def create_quantity_map(
        self,
        data: BIMQuantityMapCreate,
    ) -> BIMQuantityMap:
        """Create a new quantity mapping rule."""
        qmap = BIMQuantityMap(
            org_id=data.org_id,
            project_id=data.project_id,
            name=data.name,
            name_translations=data.name_translations,
            element_type_filter=data.element_type_filter,
            property_filter=data.property_filter,
            quantity_source=data.quantity_source,
            multiplier=data.multiplier,
            unit=data.unit,
            waste_factor_pct=data.waste_factor_pct,
            boq_target=data.boq_target,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        qmap = await self.qmap_repo.create(qmap)
        logger.info("Quantity map created: %s (source=%s)", data.name, data.quantity_source)
        return qmap

    async def update_quantity_map(
        self,
        map_id: uuid.UUID,
        data: BIMQuantityMapUpdate,
    ) -> BIMQuantityMap:
        """Update a quantity mapping rule."""
        existing = await self.qmap_repo.get(map_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return existing

        await self.qmap_repo.update_fields(map_id, **fields)
        updated = await self.qmap_repo.get(map_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found after update",
            )
        return updated

    async def apply_quantity_maps(
        self,
        request: QuantityMapApplyRequest,
    ) -> QuantityMapApplyResult:
        """Apply quantity mapping rules to all elements in a model.

        Two modes, selected by ``request.dry_run``:

        **dry_run=True (default)** — compute and return a preview only.
            No ``BOQElementLink`` rows and no ``Position`` rows are created.
            ``links_created`` and ``positions_created`` stay at 0.

        **dry_run=False** — actually persist the result:
            * For every rule with a resolvable ``boq_target``, create a
              ``BOQElementLink`` (link_type="rule_based", confidence="high",
              rule_id=rule.id) for each matched element, skipping any
              (position_id, element_id) pair that already exists.
            * If a rule's ``boq_target`` does not resolve to an existing
              position **and** the target dict has ``auto_create: True``,
              a new ``Position`` is inserted into the project's first BOQ
              with quantity = Σ(adjusted quantity across matched elements)
              and then the links are created against the new position.
            * Each rule's writes run inside a single savepoint
              (``session.begin_nested``) — a failure while processing one
              rule rolls that rule back cleanly without aborting the
              others or the outer request transaction.
            * Also keeps ``Position.cad_element_ids`` in sync via
              ``_append_cad_element_id``.
        """
        model = await self.get_model(request.model_id)

        # Get all elements for the model
        elements, _ = await self.element_repo.list_for_model(
            model.id, offset=0, limit=50000
        )

        # Get active rules (project-scoped first, then global)
        rules = await self.qmap_repo.list_active(project_id=model.project_id)

        # ── Step 1: compute matches per rule (same math regardless of
        # dry_run so the preview stays identical across modes). ───────────
        # Tracks (element, rule) pairs that fired the rule but were
        # then dropped because the quantity could not be extracted —
        # most often because the element is missing the property the
        # rule reads.  We surface this in the result so the dry-run
        # preview can show *why* a population is smaller than expected
        # instead of silently dropping rows.
        per_rule_matches: dict[uuid.UUID, list[tuple[BIMElement, Decimal, Decimal]]] = {}
        results: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        matched_element_ids: set[uuid.UUID] = set()

        for element in elements:
            for rule in rules:
                if not self._rule_matches_element(rule, element):
                    continue

                qty = self._extract_quantity(element, rule.quantity_source)
                if qty is None:
                    skipped.append({
                        "element_id": str(element.id),
                        "stable_id": element.stable_id,
                        "element_type": element.element_type,
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "quantity_source": rule.quantity_source,
                        "reason": "missing_property",
                        "detail": (
                            f"element has no value for "
                            f"'{rule.quantity_source}' (property/quantity key)"
                        ),
                    })
                    continue

                try:
                    multiplier = Decimal(rule.multiplier or "1")
                    waste_pct = Decimal(rule.waste_factor_pct or "0")
                    adjusted = qty * multiplier * (Decimal("1") + waste_pct / Decimal("100"))
                except (InvalidOperation, ValueError) as exc:
                    skipped.append({
                        "element_id": str(element.id),
                        "stable_id": element.stable_id,
                        "element_type": element.element_type,
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "quantity_source": rule.quantity_source,
                        "reason": "invalid_decimal",
                        "detail": (
                            f"could not convert quantity {qty!r} with "
                            f"multiplier={rule.multiplier!r} / "
                            f"waste={rule.waste_factor_pct!r}: {exc}"
                        ),
                    })
                    continue

                per_rule_matches.setdefault(rule.id, []).append(
                    (element, qty, adjusted)
                )
                matched_element_ids.add(element.id)

                results.append({
                    "element_id": str(element.id),
                    "stable_id": element.stable_id,
                    "element_type": element.element_type,
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "quantity_source": rule.quantity_source,
                    "raw_quantity": float(qty),
                    "adjusted_quantity": float(adjusted),
                    "unit": rule.unit,
                    "boq_target": rule.boq_target,
                })

        matched_elements = len(matched_element_ids)
        rules_applied = sum(1 for matches in per_rule_matches.values() if matches)
        links_created = 0
        positions_created = 0

        # ── Step 2: persist (only when dry_run is False) ───────────────
        if not request.dry_run and per_rule_matches:
            rules_by_id = {rule.id: rule for rule in rules}
            for rule_id, matches in per_rule_matches.items():
                rule = rules_by_id.get(rule_id)
                if rule is None or not matches:
                    continue

                try:
                    async with self.session.begin_nested():
                        created_links, created_positions = (
                            await self._persist_rule_matches(
                                rule=rule,
                                model=model,
                                matches=matches,
                            )
                        )
                        links_created += created_links
                        positions_created += created_positions
                except Exception:  # noqa: BLE001 — per-rule isolation
                    logger.exception(
                        "Failed to persist quantity map rule %s on model %s",
                        rule_id,
                        model.id,
                    )
                    # Savepoint already rolled back; continue with next rule.

        # Surface skip count alongside match counts so operators can
        # tell at-a-glance whether the population is honest.  A high
        # skip count almost always means the rule's ``quantity_source``
        # is wrong or the IFC export is missing a column.
        if skipped:
            logger.warning(
                "Quantity maps: %d (element, rule) pair(s) skipped on "
                "model %s — most common reason is a missing property "
                "(rule expects something the BIM export did not provide). "
                "First skipped pair: %s",
                len(skipped),
                model.name,
                skipped[0],
            )

        logger.info(
            "Quantity maps applied: %d elements matched, %d rules applied, "
            "%d links created, %d positions created, %d skipped for model "
            "%s (dry_run=%s)",
            matched_elements,
            rules_applied,
            links_created,
            positions_created,
            len(skipped),
            model.name,
            request.dry_run,
        )

        return QuantityMapApplyResult(
            matched_elements=matched_elements,
            rules_applied=rules_applied,
            links_created=links_created,
            positions_created=positions_created,
            skipped_count=len(skipped),
            results=results,
            skipped=skipped,
        )

    async def _persist_rule_matches(
        self,
        *,
        rule: BIMQuantityMap,
        model: BIMModel,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
    ) -> tuple[int, int]:
        """Create BOQElementLink (and optionally a Position) for one rule.

        Called from ``apply_quantity_maps`` inside a savepoint. Returns
        ``(links_created, positions_created)``.
        """
        if not matches:
            return 0, 0

        target = rule.boq_target or {}
        if not isinstance(target, dict):
            logger.warning(
                "Rule %s has non-dict boq_target; skipping persistence", rule.id
            )
            return 0, 0

        # ── Resolve the target Position ───────────────────────────────
        position = await self._resolve_boq_target_position(
            target=target,
            project_id=model.project_id,
        )
        positions_created = 0

        if position is None:
            if not target.get("auto_create"):
                logger.info(
                    "Rule %s: boq_target unresolved and auto_create is false; skipping",
                    rule.id,
                )
                return 0, 0

            position = await self._auto_create_position_for_rule(
                rule=rule,
                project_id=model.project_id,
                matches=matches,
            )
            if position is None:
                return 0, 0
            positions_created = 1

        # ── Create links for every matched element ────────────────────
        links_created = 0
        existing_elem_ids = await self._existing_link_element_ids(position.id)

        for element, _raw, _adjusted in matches:
            if element.id in existing_elem_ids:
                continue  # idempotent — dup UNIQUE would 500 us otherwise

            link = BOQElementLink(
                boq_position_id=position.id,
                bim_element_id=element.id,
                link_type="rule_based",
                confidence="high",
                rule_id=str(rule.id),
                metadata_={},
            )
            try:
                await self.link_repo.create(link)
            except IntegrityError:
                # Race with a concurrent writer — treat as already linked.
                logger.debug(
                    "IntegrityError creating link pos=%s elem=%s (treated as duplicate)",
                    position.id,
                    element.id,
                )
                continue

            await self._append_cad_element_id(position.id, element.id)
            existing_elem_ids.add(element.id)
            links_created += 1

        return links_created, positions_created

    async def _resolve_boq_target_position(
        self,
        *,
        target: dict[str, Any],
        project_id: uuid.UUID,
    ) -> Position | None:
        """Look up a Position from a rule's ``boq_target`` dict.

        Supports two lookup keys:
            - ``position_id``: direct UUID lookup (scoped to project).
            - ``position_ordinal``: match by ordinal within any BOQ of the
              given project (returns the first match).
        """
        raw_pid = target.get("position_id")
        if raw_pid:
            try:
                pid = uuid.UUID(str(raw_pid))
            except (ValueError, TypeError):
                return None
            pos = await self.session.get(Position, pid)
            if pos is None:
                return None
            # Make sure the position belongs to the same project.
            boq = await self.session.get(BOQ, pos.boq_id)
            if boq is None or boq.project_id != project_id:
                return None
            return pos

        ordinal = target.get("position_ordinal")
        if ordinal:
            stmt = (
                select(Position)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id, Position.ordinal == str(ordinal))
                .limit(1)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        return None

    async def _auto_create_position_for_rule(
        self,
        *,
        rule: BIMQuantityMap,
        project_id: uuid.UUID,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
    ) -> Position | None:
        """Insert a new Position in the project's first/default BOQ.

        Quantity = sum of adjusted quantities across all matches for this
        rule. Unit = rule.unit (fallback "pcs"). Classification is lifted
        from ``rule.metadata_["classification"]`` when present.
        Returns ``None`` if the project has no BOQ to attach to.
        """
        # Find the project's first BOQ (oldest created_at, same as
        # ``BOQRepository.list_for_project`` order inverted).
        stmt = (
            select(BOQ)
            .where(BOQ.project_id == project_id)
            .order_by(BOQ.created_at.asc())
            .limit(1)
        )
        boq = (await self.session.execute(stmt)).scalar_one_or_none()
        if boq is None:
            logger.warning(
                "Auto-create requested for rule %s but project %s has no BOQ",
                rule.id,
                project_id,
            )
            return None

        # Aggregate the adjusted quantity across all matched elements.
        total_qty = sum((adjusted for _, _, adjusted in matches), Decimal("0"))

        # Pull classification out of the rule's metadata if present.
        rule_meta = rule.metadata_ or {}
        classification = rule_meta.get("classification") or {}
        if not isinstance(classification, dict):
            classification = {}

        # Pick a free ordinal — "BIM-<short rule id>" — unlikely to clash.
        ordinal = f"BIM-{str(rule.id)[:8]}"

        # Determine sort_order: after everything else.
        max_order_stmt = select(func.coalesce(func.max(Position.sort_order), 0)).where(
            Position.boq_id == boq.id
        )
        max_order = (await self.session.execute(max_order_stmt)).scalar_one() or 0

        # Pull a default unit_rate from the rule's boq_target dict if the
        # author prefilled one (e.g. via the "Suggest from CWICR" button
        # in the rule editor).  When non-zero we also compute the line
        # total here so the new position lands fully priced — no second
        # pass needed in the BOQ editor.
        default_rate = "0"
        target_dict = rule.boq_target or {}
        if isinstance(target_dict, dict):
            raw_rate = target_dict.get("unit_rate")
            if isinstance(raw_rate, (int, float)):
                default_rate = str(raw_rate)
            elif isinstance(raw_rate, str) and raw_rate.strip():
                default_rate = raw_rate.strip()

        try:
            rate_decimal = Decimal(default_rate)
        except Exception:
            rate_decimal = Decimal("0")
        line_total = total_qty * rate_decimal

        position = Position(
            boq_id=boq.id,
            parent_id=None,
            ordinal=ordinal,
            description=rule.name,
            unit=rule.unit or "pcs",
            quantity=str(total_qty),
            unit_rate=default_rate,
            total=str(line_total),
            classification=classification,
            source="cad_import",
            confidence=None,
            cad_element_ids=[],
            validation_status="pending",
            metadata_={"auto_created_by_rule": str(rule.id)},
            sort_order=max_order + 1,
        )
        self.session.add(position)
        await self.session.flush()
        logger.info(
            "Auto-created Position %s (ordinal=%s) for rule %s in BOQ %s",
            position.id,
            ordinal,
            rule.id,
            boq.id,
        )
        return position

    async def _existing_link_element_ids(
        self,
        position_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """Return the set of bim_element_ids already linked to a position."""
        stmt = select(BOQElementLink.bim_element_id).where(
            BOQElementLink.boq_position_id == position_id
        )
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def sync_cad_element_ids(
        self,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Rewrite ``Position.cad_element_ids`` from ``oe_bim_boq_link``.

        Idempotent back-fill helper. Walks every ``BOQElementLink`` in the
        database (optionally scoped to a single project) and overwrites
        the JSON array on the linked ``Position`` with the sorted list of
        bim_element_id strings. Use this when:

            * the app shipped before the link↔position mirror existed and
              legacy rows have out-of-date or empty ``cad_element_ids``;
            * a bulk DB import bypassed the service layer;
            * a migration has added/removed links in bulk.

        Returns a small summary ``{"links_scanned", "positions_updated"}``.
        """
        # ── Load links (optionally scoped to project) ─────────────────
        if project_id is not None:
            stmt = (
                select(BOQElementLink.boq_position_id, BOQElementLink.bim_element_id)
                .join(Position, Position.id == BOQElementLink.boq_position_id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id)
            )
        else:
            stmt = select(
                BOQElementLink.boq_position_id, BOQElementLink.bim_element_id
            )

        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, set[str]] = {}
        links_scanned = 0
        for pos_id, elem_id in result.all():
            links_scanned += 1
            grouped.setdefault(pos_id, set()).add(str(elem_id))

        # Also make sure positions that exist in the project but have NO
        # links get their cad_element_ids reset to [] (so stale ids from a
        # previous state are cleared).
        if project_id is not None:
            all_pos_stmt = (
                select(Position.id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id)
            )
            all_pos = (await self.session.execute(all_pos_stmt)).scalars().all()
            for pid in all_pos:
                grouped.setdefault(pid, set())

        positions_updated = 0
        for pos_id, elem_ids in grouped.items():
            pos = await self.session.get(Position, pos_id)
            if pos is None:
                continue
            desired = sorted(elem_ids)
            current = list(pos.cad_element_ids or [])
            if sorted(current) != desired:
                pos.cad_element_ids = desired
                positions_updated += 1

        await self.session.flush()
        logger.info(
            "sync_cad_element_ids: scanned %d links, updated %d positions (project=%s)",
            links_scanned,
            positions_updated,
            project_id,
        )
        return {
            "links_scanned": links_scanned,
            "positions_updated": positions_updated,
        }

    @staticmethod
    def _rule_matches_element(rule: BIMQuantityMap, element: BIMElement) -> bool:
        """Check if a quantity map rule matches an element."""
        # Check element_type_filter
        if rule.element_type_filter:
            if rule.element_type_filter != "*":
                if not element.element_type:
                    return False
                if not fnmatch.fnmatch(element.element_type.lower(), rule.element_type_filter.lower()):
                    return False

        # Check property_filter via the shared type-aware helper so we
        # match dynamic-element-group semantics: list values fall back
        # to membership, dict values to recursive containment, None to
        # explicit "not set" handling.  The previous implementation
        # str()'d everything, which collapsed ``["steel","concrete"]``
        # into the literal string ``"['steel', 'concrete']"`` and made
        # multi-valued IFC properties unmatchable.
        if rule.property_filter:
            props = element.properties or {}
            for key, pattern in rule.property_filter.items():
                if not BIMHubService._property_value_matches(props.get(key), pattern):
                    return False

        return True

    @staticmethod
    def _property_value_matches(actual: Any, expected: Any) -> bool:  # noqa: PLR0911
        """Type-aware comparison for BIM property filters.

        Used by both the dynamic-element-group ``_matches`` predicate
        and the quantity-map rule engine, so multi-valued IFC properties
        (lists, nested dicts) and missing properties behave consistently
        across the two callers.

        Rules:
            * ``expected is None`` matches when ``actual is None`` (explicit
              "this property must not be set").
            * ``actual is None`` otherwise → ``False`` (the filter wants
              a value but the element has none).
            * ``actual`` is a list →
                - ``expected`` is a list  → non-empty set intersection
                - ``expected`` is a scalar → membership test (with
                  fnmatch wildcards on each list item if it's a string)
            * ``actual`` is a dict + ``expected`` is a dict → recursive
              containment (every key in ``expected`` must match the
              corresponding key in ``actual``).
            * Both are strings → fnmatch (case-insensitive, supports
              ``*`` and ``?`` wildcards).
            * Otherwise → exact equality after stringifying.

        Returns ``True`` when the actual value satisfies the expected
        pattern, ``False`` otherwise.
        """
        # Explicit "must not be set" filter
        if expected is None:
            return actual is None
        if actual is None:
            return False

        # List actual: membership / intersection semantics
        if isinstance(actual, list):
            if isinstance(expected, list):
                return any(
                    BIMHubService._property_value_matches(item, exp_item)
                    for item in actual
                    for exp_item in expected
                )
            # Scalar expected → does the list contain a matching item?
            return any(
                BIMHubService._property_value_matches(item, expected)
                for item in actual
            )

        # Dict actual + dict expected: recursive containment
        if isinstance(actual, dict) and isinstance(expected, dict):
            return all(
                BIMHubService._property_value_matches(actual.get(k), v)
                for k, v in expected.items()
            )

        # String values: fnmatch wildcards (existing _rule_matches_element
        # behaviour, kept for backwards compatibility with rules that use
        # ``*`` and ``?`` patterns).
        if isinstance(actual, str) and isinstance(expected, str):
            return fnmatch.fnmatch(actual.lower(), expected.lower())

        # Booleans / numerics / mixed types → fall back to exact equality
        # via string coercion.  This handles e.g. ``actual=42`` against
        # ``expected="42"`` and ``actual=True`` against ``expected="true"``.
        return str(actual).lower() == str(expected).lower()

    @staticmethod
    def _extract_quantity(element: BIMElement, source: str) -> Decimal | None:
        """Extract a quantity from an element based on the source specification.

        Supports:
        - Direct quantity keys: area_m2, volume_m3, length_m, weight_kg, count
        - Property references: property:xxx (e.g., property:fire_rating)
        """
        quantities = element.quantities or {}

        if source.startswith("property:"):
            prop_name = source[len("property:"):]
            value = (element.properties or {}).get(prop_name)
        elif source == "count":
            return Decimal("1")
        else:
            value = quantities.get(source)

        if value is None:
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    # ── Model Diff ───────────────────────────────────────────────────────────

    async def compute_diff(
        self,
        new_model_id: uuid.UUID,
        old_model_id: uuid.UUID,
    ) -> BIMModelDiff:
        """Compute diff between two model versions by comparing elements.

        Elements are matched by stable_id. Changes detected via geometry_hash.
        Returns a BIMModelDiff with summary counts and detailed changes.
        """
        new_model = await self.get_model(new_model_id)
        old_model = await self.get_model(old_model_id)

        # Check if diff already exists
        existing = await self.diff_repo.get_by_pair(old_model_id, new_model_id)
        if existing is not None:
            return existing

        # Load all elements for both models
        old_elements, _ = await self.element_repo.list_for_model(
            old_model.id, offset=0, limit=50000
        )
        new_elements, _ = await self.element_repo.list_for_model(
            new_model.id, offset=0, limit=50000
        )

        old_by_sid = {e.stable_id: e for e in old_elements}
        new_by_sid = {e.stable_id: e for e in new_elements}

        old_ids = set(old_by_sid.keys())
        new_ids = set(new_by_sid.keys())

        added_ids = new_ids - old_ids
        deleted_ids = old_ids - new_ids
        common_ids = old_ids & new_ids

        modified: list[dict[str, Any]] = []
        unchanged = 0

        for sid in common_ids:
            old_e = old_by_sid[sid]
            new_e = new_by_sid[sid]

            changes: list[dict[str, Any]] = []
            # Detect what changed across all tracked fields
            if old_e.geometry_hash != new_e.geometry_hash:
                changes.append({
                    "field": "geometry_hash",
                    "old": old_e.geometry_hash,
                    "new": new_e.geometry_hash,
                })
            if old_e.element_type != new_e.element_type:
                changes.append({
                    "field": "element_type",
                    "old": old_e.element_type,
                    "new": new_e.element_type,
                })
            if old_e.quantities != new_e.quantities:
                changes.append({
                    "field": "quantities",
                    "old": old_e.quantities,
                    "new": new_e.quantities,
                })
            if old_e.properties != new_e.properties:
                changes.append({
                    "field": "properties",
                    "old": old_e.properties,
                    "new": new_e.properties,
                })

            if changes:
                modified.append({
                    "stable_id": sid,
                    "element_type": new_e.element_type,
                    "changes": changes,
                })
            else:
                unchanged += 1

        diff_summary = {
            "unchanged": unchanged,
            "modified": len(modified),
            "added": len(added_ids),
            "deleted": len(deleted_ids),
        }

        diff_details = {
            "modified": modified,
            "added": [
                {
                    "stable_id": sid,
                    "element_type": new_by_sid[sid].element_type,
                    "name": new_by_sid[sid].name,
                }
                for sid in added_ids
            ],
            "deleted": [
                {
                    "stable_id": sid,
                    "element_type": old_by_sid[sid].element_type,
                    "name": old_by_sid[sid].name,
                }
                for sid in deleted_ids
            ],
        }

        diff = BIMModelDiff(
            old_model_id=old_model_id,
            new_model_id=new_model_id,
            diff_summary=diff_summary,
            diff_details=diff_details,
        )
        diff = await self.diff_repo.create(diff)

        logger.info(
            "Model diff computed: %s -> %s (added=%d, deleted=%d, modified=%d, unchanged=%d)",
            old_model.name,
            new_model.name,
            len(added_ids),
            len(deleted_ids),
            len(modified),
            unchanged,
        )
        return diff

    async def get_diff(self, diff_id: uuid.UUID) -> BIMModelDiff:
        """Get a model diff by ID. Raises 404 if not found."""
        diff = await self.diff_repo.get(diff_id)
        if diff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model diff not found",
            )
        return diff

    # ── Element Groups ───────────────────────────────────────────────────────

    async def list_element_groups(
        self,
        project_id: uuid.UUID,
        *,
        model_id: uuid.UUID | None = None,
    ) -> list[BIMElementGroupResponse]:
        """List element groups for a project, optionally scoped to one model.

        For dynamic groups the cached ``element_ids`` snapshot is returned as
        ``member_element_ids``; it is NOT re-resolved on list calls. Callers
        that need up-to-the-second membership should PATCH the group (which
        triggers a re-resolve) or fetch via the dedicated resolve endpoint.
        """
        stmt = select(BIMElementGroup).where(BIMElementGroup.project_id == project_id)
        if model_id is not None:
            stmt = stmt.where(BIMElementGroup.model_id == model_id)
        stmt = stmt.order_by(BIMElementGroup.created_at.asc())
        result = await self.session.execute(stmt)
        groups = list(result.scalars().all())
        return [self._group_to_response(g) for g in groups]

    async def get_element_group(self, group_id: uuid.UUID) -> BIMElementGroup:
        """Get a BIM element group by id. Raises 404 if not found."""
        group = await self.session.get(BIMElementGroup, group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element group not found",
            )
        return group

    async def create_element_group(
        self,
        project_id: uuid.UUID,
        payload: BIMElementGroupCreate,
        user_id: uuid.UUID | None,
    ) -> BIMElementGroupResponse:
        """Create a new element group.

        If ``payload.is_dynamic`` is True, the filter is evaluated immediately
        and the resolved element ids are cached in ``element_ids`` +
        ``element_count``. Otherwise the explicit ``element_ids`` list from
        the payload is stored verbatim.
        """
        group = BIMElementGroup(
            project_id=project_id,
            model_id=payload.model_id,
            name=payload.name,
            description=payload.description,
            is_dynamic=payload.is_dynamic,
            filter_criteria=payload.filter_criteria or {},
            element_ids=[str(eid) for eid in (payload.element_ids or [])],
            element_count=len(payload.element_ids or []),
            color=payload.color,
            created_by=user_id,
            metadata_=payload.metadata or {},
        )
        self.session.add(group)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An element group with this name already exists in the project",
            ) from exc

        # Dynamic groups: resolve membership now and cache it.
        if group.is_dynamic:
            resolved = await self._resolve_members_for_group(group)
            group.element_ids = [str(eid) for eid in resolved]
            group.element_count = len(resolved)
            await self.session.flush()

        await self.session.refresh(group)
        logger.info(
            "BIM element group created: %s (project=%s, dynamic=%s, count=%d)",
            group.name,
            project_id,
            group.is_dynamic,
            group.element_count,
        )
        return self._group_to_response(group)

    async def update_element_group(
        self,
        group_id: uuid.UUID,
        payload: BIMElementGroupUpdate,
    ) -> BIMElementGroupResponse:
        """Patch fields on a group and re-resolve the cache if needed.

        Re-resolution is triggered whenever ``filter_criteria``, ``model_id``,
        or ``is_dynamic`` is touched by the payload, OR when
        ``is_dynamic`` stays True and the caller supplied a new filter.
        """
        group = await self.get_element_group(group_id)

        fields = payload.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Normalise UUID list to str for JSON storage.
        if "element_ids" in fields and fields["element_ids"] is not None:
            fields["element_ids"] = [str(eid) for eid in fields["element_ids"]]
            fields["element_count"] = len(fields["element_ids"])

        re_resolve = (
            "filter_criteria" in fields
            or "model_id" in fields
            or "is_dynamic" in fields
        )

        for key, value in fields.items():
            setattr(group, key, value)

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An element group with this name already exists in the project",
            ) from exc

        # Re-resolve the cache only for dynamic groups when their inputs moved.
        if re_resolve and group.is_dynamic:
            resolved = await self._resolve_members_for_group(group)
            group.element_ids = [str(eid) for eid in resolved]
            group.element_count = len(resolved)
            await self.session.flush()

        await self.session.refresh(group)
        logger.info(
            "BIM element group updated: %s (fields=%s)",
            group_id,
            list(fields.keys()),
        )
        return self._group_to_response(group)

    async def delete_element_group(self, group_id: uuid.UUID) -> None:
        """Delete a BIM element group. Raises 404 if not found."""
        group = await self.get_element_group(group_id)
        await self.session.delete(group)
        await self.session.flush()
        logger.info("BIM element group deleted: %s", group_id)

    async def resolve_element_group_members(
        self,
        group_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Recompute the member list for a group and update its cache.

        Runs the current ``filter_criteria`` against ``oe_bim_element``,
        scoped to ``model_id`` (or all models in the project if
        ``model_id`` is NULL). Persists the refreshed ``element_ids`` +
        ``element_count`` snapshot and returns the new list.

        This works for both dynamic and static groups, but a static group
        will still overwrite its cached snapshot — callers that want to
        preserve a hand-curated static list should NOT call this method.
        """
        group = await self.get_element_group(group_id)
        resolved = await self._resolve_members_for_group(group)
        group.element_ids = [str(eid) for eid in resolved]
        group.element_count = len(resolved)
        await self.session.flush()
        return resolved

    async def _resolve_members_for_group(
        self,
        group: BIMElementGroup,
    ) -> list[uuid.UUID]:
        """Execute the filter against oe_bim_element for a group.

        Supported filter keys (``filter_criteria``):

        - ``element_type``: str | list[str] — exact match (OR across list).
        - ``category``: str | list[str] — match against ``properties.category``.
        - ``discipline``: str | list[str] — exact match.
        - ``storey``: str | list[str] — exact match.
        - ``property_filter``: dict[str, Any] — every key/value pair must be
          present inside ``properties`` JSON. On Postgres we use the native
          JSONB containment operator (``@>``); on SQLite we fall back to
          loading the candidates and filtering in Python.
        - ``name_contains``: str — case-insensitive substring match using
          ILIKE.

        Scope:
        - If ``group.model_id`` is set, we filter to that model only.
        - Otherwise we walk every ``BIMModel`` in ``group.project_id``.

        If the filter is empty and the group is static, we return the cached
        ``element_ids`` untouched so a static group's snapshot survives a
        re-resolve trigger; for dynamic empty filters we return the empty
        list.
        """
        criteria = group.filter_criteria or {}

        # Static group with no criteria: preserve the hand-curated snapshot.
        if not criteria and not group.is_dynamic:
            return [uuid.UUID(str(eid)) for eid in (group.element_ids or [])]

        base = select(BIMElement)

        if group.model_id is not None:
            base = base.where(BIMElement.model_id == group.model_id)
        else:
            # Constrain to every model belonging to the project.
            model_ids_stmt = select(BIMModel.id).where(BIMModel.project_id == group.project_id)
            model_ids_result = await self.session.execute(model_ids_stmt)
            model_ids = [row[0] for row in model_ids_result.all()]
            if not model_ids:
                return []
            base = base.where(BIMElement.model_id.in_(model_ids))

        # element_type (str or list) — OR-match.
        element_type = criteria.get("element_type")
        if element_type:
            values = element_type if isinstance(element_type, list) else [element_type]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.element_type.in_(values))

        # discipline (str or list) — OR-match.
        discipline = criteria.get("discipline")
        if discipline:
            values = discipline if isinstance(discipline, list) else [discipline]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.discipline.in_(values))

        # storey (str or list) — OR-match.
        storey = criteria.get("storey")
        if storey:
            values = storey if isinstance(storey, list) else [storey]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.storey.in_(values))

        # name_contains — case-insensitive substring.
        name_contains = criteria.get("name_contains")
        if name_contains:
            base = base.where(BIMElement.name.ilike(f"%{name_contains}%"))

        # Detect dialect for JSON-based filters.
        dialect_name = self.session.bind.dialect.name if self.session.bind else ""
        is_postgres = dialect_name in ("postgresql", "postgres")

        # category — lives inside the JSON ``properties`` column.
        category = criteria.get("category")
        property_filter = criteria.get("property_filter") or {}
        if not isinstance(property_filter, dict):
            property_filter = {}

        # Assemble the full expected-properties dict for JSON containment.
        expected_props: dict[str, Any] = dict(property_filter)
        category_values: list[str] = []
        if category:
            category_values = category if isinstance(category, list) else [category]
            category_values = [str(v) for v in category_values if v]

        # On Postgres: use @> JSON containment when possible (property_filter
        # only; category with multiple values still needs Python-side check).
        if is_postgres and expected_props and not category_values:
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB

            base = base.where(cast(BIMElement.properties, JSONB).contains(expected_props))
            result = await self.session.execute(base)
            elements = list(result.scalars().all())
            return [e.id for e in elements]

        # Fallback: load candidates and filter in Python. This is the path
        # used on SQLite and whenever we need list-semantics for ``category``.
        result = await self.session.execute(base)
        elements = list(result.scalars().all())

        def _matches(elem: BIMElement) -> bool:
            props = elem.properties or {}
            if category_values:
                cat = str(props.get("category") or "")
                if cat not in category_values:
                    return False
            # Use the shared type-aware helper so list/dict/None
            # property values match consistently with the quantity-map
            # rule engine.  Previously this used exact equality which
            # silently failed for multi-valued IFC properties.
            return all(
                BIMHubService._property_value_matches(props.get(key), value)
                for key, value in expected_props.items()
            )

        return [e.id for e in elements if _matches(e)]

    @staticmethod
    def _group_to_response(group: BIMElementGroup) -> BIMElementGroupResponse:
        """Convert a ``BIMElementGroup`` ORM row to its API response.

        Populates ``member_element_ids`` from the cached ``element_ids``
        snapshot (which, for dynamic groups, is refreshed by the service
        whenever the filter or scope moves).
        """
        raw_ids = list(group.element_ids or [])
        parsed_ids: list[uuid.UUID] = []
        for raw in raw_ids:
            try:
                parsed_ids.append(uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        return BIMElementGroupResponse(
            id=group.id,
            project_id=group.project_id,
            model_id=group.model_id,
            name=group.name,
            description=group.description,
            is_dynamic=group.is_dynamic,
            filter_criteria=group.filter_criteria or {},
            element_ids=parsed_ids,
            element_count=group.element_count,
            color=group.color,
            created_by=group.created_by,
            metadata_=group.metadata_ or {},
            created_at=group.created_at,
            updated_at=group.updated_at,
            member_element_ids=parsed_ids,
        )
