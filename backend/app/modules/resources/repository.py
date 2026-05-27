"""‌⁠‍Resources data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resources.models import (
    Assignment,
    AvailabilityWindow,
    Certification,
    Resource,
    ResourceLink,
    ResourceRequest,
    ResourceSkill,
    Skill,
)

# ── ResourceRepository ────────────────────────────────────────────────────


class ResourceRepository:
    """‌⁠‍Data access for :class:`Resource`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, resource_id: uuid.UUID) -> Resource | None:
        return await self.session.get(Resource, resource_id)

    async def get_by_code(self, code: str) -> Resource | None:
        stmt = select(Resource).where(Resource.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        resource_type: str | None = None,
        status: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[Resource], int]:
        base = select(Resource)
        if resource_type is not None:
            base = base.where(Resource.resource_type == resource_type)
        if status is not None:
            base = base.where(Resource.status == status)
        if project_id is not None:
            base = base.where(
                or_(
                    Resource.home_project_id == project_id,
                    Resource.home_project_id.is_(None),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Resource.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, resource: Resource) -> Resource:
        self.session.add(resource)
        await self.session.flush()
        return resource

    async def update_fields(self, resource_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(Resource).where(Resource.id == resource_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, resource_id: uuid.UUID) -> None:
        resource = await self.get_by_id(resource_id)
        if resource is not None:
            await self.session.delete(resource)
            await self.session.flush()


# ── SkillRepository ───────────────────────────────────────────────────────


class SkillRepository:
    """‌⁠‍Data access for :class:`Skill`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        return await self.session.get(Skill, skill_id)

    async def get_by_code(self, code: str) -> Skill | None:
        stmt = select(Skill).where(Skill.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 200,
        category: str | None = None,
    ) -> tuple[list[Skill], int]:
        base = select(Skill)
        if category is not None:
            base = base.where(Skill.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Skill.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, skill: Skill) -> Skill:
        self.session.add(skill)
        await self.session.flush()
        return skill

    async def update_fields(self, skill_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(Skill).where(Skill.id == skill_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, skill_id: uuid.UUID) -> None:
        skill = await self.get_by_id(skill_id)
        if skill is not None:
            await self.session.delete(skill)
            await self.session.flush()


# ── ResourceSkillRepository ──────────────────────────────────────────────


class ResourceSkillRepository:
    """Data access for :class:`ResourceSkill`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, link_id: uuid.UUID) -> ResourceSkill | None:
        return await self.session.get(ResourceSkill, link_id)

    async def list_for_resource(self, resource_id: uuid.UUID) -> list[ResourceSkill]:
        stmt = select(ResourceSkill).where(ResourceSkill.resource_id == resource_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_pair(
        self,
        resource_id: uuid.UUID,
        skill_id: uuid.UUID,
    ) -> ResourceSkill | None:
        stmt = select(ResourceSkill).where(
            and_(
                ResourceSkill.resource_id == resource_id,
                ResourceSkill.skill_id == skill_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, link: ResourceSkill) -> ResourceSkill:
        self.session.add(link)
        await self.session.flush()
        return link

    async def delete_pair(
        self,
        resource_id: uuid.UUID,
        skill_id: uuid.UUID,
    ) -> None:
        link = await self.find_pair(resource_id, skill_id)
        if link is not None:
            await self.session.delete(link)
            await self.session.flush()


# ── CertificationRepository ──────────────────────────────────────────────


class CertificationRepository:
    """Data access for :class:`Certification`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, cert_id: uuid.UUID) -> Certification | None:
        return await self.session.get(Certification, cert_id)

    async def list_for_resource(self, resource_id: uuid.UUID) -> list[Certification]:
        stmt = select(Certification).where(Certification.resource_id == resource_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expiring(
        self,
        *,
        today_iso: str,
        cutoff_iso: str,
    ) -> list[Certification]:
        """Return certifications whose valid_until is between today and cutoff (inclusive).

        Args:
            today_iso: Today's date as ISO YYYY-MM-DD.
            cutoff_iso: Cutoff date as ISO YYYY-MM-DD.
        """
        stmt = (
            select(Certification)
            .where(
                Certification.status == "valid",
                Certification.valid_until.isnot(None),
                Certification.valid_until >= today_iso,
                Certification.valid_until <= cutoff_iso,
            )
            .order_by(Certification.valid_until)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, cert: Certification) -> Certification:
        self.session.add(cert)
        await self.session.flush()
        return cert

    async def update_fields(self, cert_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(Certification).where(Certification.id == cert_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, cert_id: uuid.UUID) -> None:
        cert = await self.get_by_id(cert_id)
        if cert is not None:
            await self.session.delete(cert)
            await self.session.flush()


# ── AvailabilityWindowRepository ─────────────────────────────────────────


class AvailabilityWindowRepository:
    """Data access for :class:`AvailabilityWindow`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, window_id: uuid.UUID) -> AvailabilityWindow | None:
        return await self.session.get(AvailabilityWindow, window_id)

    async def list_for_resource(
        self,
        resource_id: uuid.UUID,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AvailabilityWindow]:
        stmt = select(AvailabilityWindow).where(AvailabilityWindow.resource_id == resource_id)
        if start_at is not None:
            stmt = stmt.where(AvailabilityWindow.end_at >= start_at)
        if end_at is not None:
            stmt = stmt.where(AvailabilityWindow.start_at <= end_at)
        stmt = stmt.order_by(AvailabilityWindow.start_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, window: AvailabilityWindow) -> AvailabilityWindow:
        self.session.add(window)
        await self.session.flush()
        return window

    async def update_fields(self, window_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(AvailabilityWindow).where(AvailabilityWindow.id == window_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, window_id: uuid.UUID) -> None:
        window = await self.get_by_id(window_id)
        if window is not None:
            await self.session.delete(window)
            await self.session.flush()


# ── AssignmentRepository ─────────────────────────────────────────────────


class AssignmentRepository:
    """Data access for :class:`Assignment`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, assignment_id: uuid.UUID) -> Assignment | None:
        return await self.session.get(Assignment, assignment_id)

    async def list_for_resource(
        self,
        resource_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
        status: str | None = None,
    ) -> tuple[list[Assignment], int]:
        base = select(Assignment).where(Assignment.resource_id == resource_id)
        if status is not None:
            base = base.where(Assignment.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Assignment.start_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 500,
        status: str | None = None,
    ) -> tuple[list[Assignment], int]:
        base = select(Assignment).where(Assignment.project_id == project_id)
        if status is not None:
            base = base.where(Assignment.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Assignment.start_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def assignments_for_resource_in_window(
        self,
        resource_id: uuid.UUID,
        start: datetime,
        end: datetime,
        *,
        exclude_id: uuid.UUID | None = None,
        active_only: bool = True,
    ) -> list[Assignment]:
        """Return assignments for resource that overlap [start, end).

        Active by default means not cancelled / not completed.
        """
        stmt = select(Assignment).where(
            Assignment.resource_id == resource_id,
            # Overlap: (a.start < end) AND (a.end > start)
            Assignment.start_at < end,
            Assignment.end_at > start,
        )
        if active_only:
            stmt = stmt.where(Assignment.status.notin_(("cancelled", "completed")))
        if exclude_id is not None:
            stmt = stmt.where(Assignment.id != exclude_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_in_window(
        self,
        start: datetime,
        end: datetime,
        *,
        project_id: uuid.UUID | None = None,
        resource_ids: list[uuid.UUID] | None = None,
    ) -> list[Assignment]:
        """Return assignments overlapping [start, end), optionally filtered."""
        stmt = select(Assignment).where(
            Assignment.start_at < end,
            Assignment.end_at > start,
        )
        if project_id is not None:
            stmt = stmt.where(Assignment.project_id == project_id)
        if resource_ids:
            stmt = stmt.where(Assignment.resource_id.in_(resource_ids))
        stmt = stmt.order_by(Assignment.start_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, assignment: Assignment) -> Assignment:
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def update_fields(self, assignment_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(Assignment).where(Assignment.id == assignment_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, assignment_id: uuid.UUID) -> None:
        assignment = await self.get_by_id(assignment_id)
        if assignment is not None:
            await self.session.delete(assignment)
            await self.session.flush()

    async def find_available_resources(
        self,
        *,
        skill_ids: list[uuid.UUID],
        start: datetime,
        end: datetime,
        exclude_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        """Find active resources that hold ALL given skills and have no
        conflicting active assignment in [start, end).
        """
        excl: set[uuid.UUID] = set(exclude_ids or [])

        # Resources with conflicting assignments
        conflict_stmt = select(Assignment.resource_id).where(
            Assignment.start_at < end,
            Assignment.end_at > start,
            Assignment.status.notin_(("cancelled", "completed")),
        )
        conflict_result = await self.session.execute(conflict_stmt)
        busy_ids = {row[0] for row in conflict_result.all()}

        # Base resource query: active only, not excluded, not busy
        res_stmt = select(Resource).where(Resource.status == "active")
        if busy_ids or excl:
            excluded_all = busy_ids | excl
            res_stmt = res_stmt.where(Resource.id.notin_(excluded_all))
        res_stmt = res_stmt.limit(limit * 5)  # widen, we'll skill-filter in Python
        res_result = await self.session.execute(res_stmt)
        candidates = list(res_result.scalars().all())

        if not skill_ids:
            return candidates[:limit]

        # Filter by skill possession (all skill_ids required)
        rs_stmt = select(ResourceSkill).where(
            ResourceSkill.resource_id.in_([c.id for c in candidates]),
            ResourceSkill.skill_id.in_(skill_ids),
        )
        rs_result = await self.session.execute(rs_stmt)
        owned: dict[uuid.UUID, set[uuid.UUID]] = {}
        for link in rs_result.scalars().all():
            owned.setdefault(link.resource_id, set()).add(link.skill_id)

        required = set(skill_ids)
        kept = [c for c in candidates if required.issubset(owned.get(c.id, set()))]
        return kept[:limit]


# ── ResourceRequestRepository ────────────────────────────────────────────


class ResourceRequestRepository:
    """Data access for :class:`ResourceRequest`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, req_id: uuid.UUID) -> ResourceRequest | None:
        return await self.session.get(ResourceRequest, req_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> tuple[list[ResourceRequest], int]:
        base = select(ResourceRequest).where(ResourceRequest.project_id == project_id)
        if status is not None:
            base = base.where(ResourceRequest.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ResourceRequest.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, req: ResourceRequest) -> ResourceRequest:
        self.session.add(req)
        await self.session.flush()
        return req

    async def update_fields(self, req_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(ResourceRequest).where(ResourceRequest.id == req_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, req_id: uuid.UUID) -> None:
        req = await self.get_by_id(req_id)
        if req is not None:
            await self.session.delete(req)
            await self.session.flush()


# ── ResourceLinkRepository ──────────────────────────────────────────────


class ResourceLinkRepository:
    """Data access for :class:`ResourceLink`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, link_id: uuid.UUID) -> ResourceLink | None:
        return await self.session.get(ResourceLink, link_id)

    async def list_for_resource(self, resource_id: uuid.UUID) -> list[ResourceLink]:
        stmt = select(ResourceLink).where(
            or_(
                ResourceLink.primary_resource_id == resource_id,
                ResourceLink.secondary_resource_id == resource_id,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, link: ResourceLink) -> ResourceLink:
        self.session.add(link)
        await self.session.flush()
        return link

    async def update_fields(self, link_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(ResourceLink).where(ResourceLink.id == link_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, link_id: uuid.UUID) -> None:
        link = await self.get_by_id(link_id)
        if link is not None:
            await self.session.delete(link)
            await self.session.flush()
