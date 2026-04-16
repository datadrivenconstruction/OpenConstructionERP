"""Project service — business logic for project management.

Stateless service layer. Handles:
- Project CRUD with ownership enforcement
- Project code auto-generation (PRJ-{YEAR}-{SEQ:04d})
- Soft-delete via status='archived'
- Event publishing on create/update/delete
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")
_logger_audit = __import__("logging").getLogger(__name__ + ".audit")


async def _safe_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Best-effort audit log — never blocks the caller on failure."""
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details,
        )
    except Exception:
        _logger_audit.debug("Audit log write skipped for %s %s", action, entity_type)


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        await event_bus.publish(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectService:
    """Business logic for project operations."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = ProjectRepository(session)

    # ── Project code generation ───────────────────────────────────────────

    async def _generate_project_code(self) -> str:
        """Generate the next project code in the format PRJ-{YEAR}-{SEQ:04d}.

        Scans existing codes matching the current year's prefix and increments
        the sequence number.  Falls back to 0001 if no codes exist yet.
        """
        year = datetime.now(UTC).year
        prefix = f"PRJ-{year}-"
        max_seq = await self.repo.max_project_code_seq(prefix)
        next_seq = (max_seq or 0) + 1
        return f"{prefix}{next_seq:04d}"

    # ── Create ────────────────────────────────────────────────────────────

    async def create_project(
        self,
        data: ProjectCreate,
        owner_id: uuid.UUID,
    ) -> Project:
        """Create a new project owned by the given user."""
        # Auto-generate project_code if not explicitly provided
        project_code = data.project_code
        if not project_code:
            project_code = await self._generate_project_code()

        project = Project(
            name=data.name,
            description=data.description,
            region=data.region,
            classification_standard=data.classification_standard,
            currency=data.currency,
            locale=data.locale,
            validation_rule_sets=data.validation_rule_sets,
            owner_id=owner_id,
            # Phase 12 expansion fields
            project_code=project_code,
            project_type=data.project_type,
            phase=data.phase,
            client_id=data.client_id,
            parent_project_id=data.parent_project_id,
            address=data.address,
            contract_value=data.contract_value,
            planned_start_date=data.planned_start_date,
            planned_end_date=data.planned_end_date,
            actual_start_date=data.actual_start_date,
            actual_end_date=data.actual_end_date,
            budget_estimate=data.budget_estimate,
            contingency_pct=data.contingency_pct,
            custom_fields=data.custom_fields,
            work_calendar_id=data.work_calendar_id,
        )
        project = await self.repo.create(project)

        await _safe_publish(
            "projects.project.created",
            {
                "project_id": str(project.id),
                "owner_id": str(owner_id),
                "name": project.name,
            },
            source_module="oe_projects",
        )

        # Auto-create a default team for the new project
        try:
            from app.modules.teams.models import Team, TeamMembership

            default_team = Team(
                project_id=project.id,
                name="Default Team",
                is_default=True,
            )
            self.session.add(default_team)
            await self.session.flush()
            self.session.add(
                TeamMembership(team_id=default_team.id, user_id=owner_id, role="lead")
            )
            await self.session.flush()
            logger.info("Default team created for project %s", project.id)
        except Exception:
            logger.debug("Auto-create default team skipped (teams module may not be loaded)")

        await _safe_audit(
            self.session,
            action="create",
            entity_type="project",
            entity_id=str(project.id),
            user_id=str(owner_id),
            details={"name": project.name, "project_code": project_code},
        )

        logger.info("Project created: %s (owner=%s, code=%s)", project.name, owner_id, project_code)
        return project

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_project(self, project_id: uuid.UUID, *, include_archived: bool = False) -> Project:
        """Get project by ID. Raises 404 if not found OR archived.

        Pass `include_archived=True` to also accept archived projects (used by
        admins, restore flows, and the soft-delete itself).
        """
        project = await self.repo.get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        if not include_archived and project.status == "archived":
            # Soft-deleted projects appear as gone to normal callers.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return project

    async def list_projects(
        self,
        owner_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        is_admin: bool = False,
    ) -> tuple[list[Project], int]:
        """List projects for a user with pagination. Admins see all.

        Archived projects are excluded by default; pass status_filter='archived'
        explicitly to see soft-deleted ones.
        """
        return await self.repo.list_for_user(
            owner_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            exclude_archived=(status_filter is None),
            is_admin=is_admin,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_project(
        self,
        project_id: uuid.UUID,
        data: ProjectUpdate,
    ) -> Project:
        """Update project fields. Raises 404 if not found."""
        project = await self.get_project(project_id)

        fields = data.model_dump(exclude_unset=True)

        # Map schema field 'metadata' to model column 'metadata_'
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return project

        await self.repo.update_fields(project_id, **fields)

        # Refresh the project object
        await self.session.refresh(project)

        await _safe_publish(
            "projects.project.updated",
            {
                "project_id": str(project_id),
                "updated_fields": list(fields.keys()),
            },
            source_module="oe_projects",
        )

        await _safe_audit(
            self.session,
            action="update",
            entity_type="project",
            entity_id=str(project_id),
            details={"updated_fields": list(fields.keys()), "name": project.name},
        )

        logger.info("Project updated: %s (fields=%s)", project_id, list(fields.keys()))
        return project

    # ── Delete (soft) ─────────────────────────────────────────────────────

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Soft-delete a project by setting status to 'archived'.

        Also hard-deletes child records (tasks, RFIs, etc.) that reference
        the project so they don't remain accessible after the project is
        archived.  The DB FK constraints use ``ondelete=CASCADE`` for real
        deletes, but since the project row itself is kept (soft-delete) those
        cascades never trigger — we do it explicitly here.

        Raises 404 if not found. Idempotent — re-archiving an archived
        project is a no-op (returns 204) so the user gets a clean delete UX.
        """
        from sqlalchemy import delete as sa_delete

        project = await self.get_project(project_id, include_archived=True)
        if project.status == "archived":
            return  # Already archived — silently succeed
        # Snapshot fields before update_fields() — that calls session.expire_all(),
        # after which any attribute access on `project` would trigger lazy IO and
        # crash with greenlet_spawn / MissingGreenlet under the async session.
        owner_id = str(project.owner_id)
        project_name = project.name

        # Cascade-delete child records that belong to this project.
        # These models all have project_id FK with ondelete=CASCADE, but
        # since we only soft-delete the project row the DB cascade never
        # fires.  Delete them explicitly so they don't remain accessible.
        child_models: list[type] = []
        try:
            from app.modules.tasks.models import Task
            child_models.append(Task)
        except ImportError:
            pass
        try:
            from app.modules.rfi.models import RFI
            child_models.append(RFI)
        except ImportError:
            pass
        try:
            from app.modules.meetings.models import Meeting
            child_models.append(Meeting)
        except ImportError:
            pass
        try:
            from app.modules.punchlist.models import PunchItem
            child_models.append(PunchItem)
        except ImportError:
            pass
        try:
            from app.modules.inspections.models import Inspection
            child_models.append(Inspection)
        except ImportError:
            pass
        try:
            from app.modules.ncr.models import NCR
            child_models.append(NCR)
        except ImportError:
            pass
        try:
            from app.modules.fieldreports.models import FieldReport
            child_models.append(FieldReport)
        except ImportError:
            pass
        try:
            from app.modules.risk.models import Risk
            child_models.append(Risk)
        except ImportError:
            pass

        for model in child_models:
            try:
                stmt = sa_delete(model).where(model.project_id == project_id)  # type: ignore[attr-defined]
                await self.session.execute(stmt)
            except Exception as exc:
                logger.debug(
                    "Cascade delete for %s skipped: %s",
                    model.__tablename__,  # type: ignore[attr-defined]
                    exc,
                )

        await self.repo.update_fields(project_id, status="archived")

        await _safe_publish(
            "projects.project.deleted",
            {
                "project_id": str(project_id),
                "owner_id": owner_id,
            },
            source_module="oe_projects",
        )

        await _safe_audit(
            self.session,
            action="delete",
            entity_type="project",
            entity_id=str(project_id),
            details={"name": project_name},
        )

        logger.info("Project archived: %s", project_id)

    # ── Restore (un-archive) ─────────────────────────────────────────────

    async def restore_project(self, project_id: uuid.UUID) -> Project:
        """Restore a previously archived project back to active status.

        Raises 404 if project not found (including never-archived ones that
        don't exist). Raises 400 if project is already active.
        """
        project = await self.get_project(project_id, include_archived=True)
        if project.status != "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project is not archived — nothing to restore",
            )
        owner_id = str(project.owner_id)

        await self.repo.update_fields(project_id, status="active")

        await _safe_publish(
            "projects.project.restored",
            {
                "project_id": str(project_id),
                "owner_id": owner_id,
            },
            source_module="oe_projects",
        )

        logger.info("Project restored: %s", project_id)

        # Re-fetch to return fresh data
        return await self.get_project(project_id)
