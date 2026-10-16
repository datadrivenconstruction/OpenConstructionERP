# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project parties: CRUD, member binding, and record shares.

Authorisation follows the rest of the teams module:

* reads need project access (404 on denial),
* party CRUD and member binding need the project owner or a system admin,
  because binding a user changes what they can read,
* sharing a record needs read access to it plus the share right: internal
  members may share any record, an external party only the records it
  originated (it cannot pass on what it received),
* setting the originator is owner or system admin only.

Every write lands an audit row. Revoking a share writes it in the same
transaction and lets an audit failure abort the revoke, so a revocation that
is not on the trail does not happen.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.modules.teams.models import PartyRecordAccess, ProjectParty, ProjectPartyMember
from app.modules.teams.party_access import (
    ACCESS_ORIGINATOR,
    ACCESS_SHARED,
    PERMISSION_CONTRIBUTE,
    get_party_register,
    resolve_party_scope,
    verify_record_access,
)
from app.modules.teams.party_schemas import (
    PartyMemberResponse,
    PartyScopeResponse,
    ProjectPartyCreate,
    ProjectPartyResponse,
    ProjectPartyUpdate,
    RecordPartiesResponse,
    RecordPartyRow,
)

logger = logging.getLogger(__name__)


def _not_found(detail: str = "Not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class PartyService:
    """Business logic for project parties and record shares."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Gates ────────────────────────────────────────────────────────────

    async def _assert_project_access(self, project_id: uuid.UUID, actor_id: str | uuid.UUID | None) -> None:
        if actor_id is None:
            return
        from app.dependencies import verify_project_access

        await verify_project_access(project_id, str(actor_id), self.session)

    async def _is_owner_or_admin(self, project_id: uuid.UUID, actor_id: str | uuid.UUID | None) -> bool:
        if actor_id is None:
            return True
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        try:
            uid = uuid.UUID(str(actor_id))
        except (ValueError, TypeError):
            return False
        role = (await self.session.execute(select(User.role).where(User.id == uid))).scalar_one_or_none()
        if role == "admin":
            return True
        owner_id = (
            await self.session.execute(select(Project.owner_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        return owner_id is not None and str(owner_id) == str(uid)

    async def _assert_project_admin(self, project_id: uuid.UUID, actor_id: str | uuid.UUID | None) -> None:
        await self._assert_project_access(project_id, actor_id)
        if not await self._is_owner_or_admin(project_id, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the project owner or a system admin may change parties on this project",
            )

    async def _get_party(self, project_id: uuid.UUID, party_id: uuid.UUID) -> ProjectParty:
        party = await self.session.get(ProjectParty, party_id)
        if party is None or party.project_id != project_id:
            raise _not_found("Party not found")
        return party

    async def _audit(
        self,
        *,
        actor_id: str | uuid.UUID | None,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        metadata: dict[str, Any],
        strict: bool = False,
    ) -> None:
        try:
            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type=entity_type,
                entity_id=str(entity_id),
                action=action,
                metadata=metadata,
                module="oe_teams",
            )
        except Exception:
            if strict:
                raise
            logger.exception("audit write failed for %s %s action=%s", entity_type, entity_id, action)

    # ── Parties ──────────────────────────────────────────────────────────

    async def _host_party_id(self, project_id: uuid.UUID) -> uuid.UUID | None:
        from app.modules.projects.models import Project

        owner_id = (
            await self.session.execute(select(Project.owner_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        if owner_id is None:
            return None
        return (
            await self.session.execute(
                select(ProjectPartyMember.party_id).where(
                    ProjectPartyMember.project_id == project_id,
                    ProjectPartyMember.user_id == owner_id,
                )
            )
        ).scalar_one_or_none()

    async def _to_response(self, party: ProjectParty, *, host_id: uuid.UUID | None, count: int) -> ProjectPartyResponse:
        resp = ProjectPartyResponse.model_validate(party)
        resp.is_host = host_id is not None and party.id == host_id
        resp.member_count = count
        return resp

    async def list_parties(
        self, project_id: uuid.UUID, *, actor_id: str | uuid.UUID | None
    ) -> list[ProjectPartyResponse]:
        """Every party on the project, host first, then by name."""
        await self._assert_project_access(project_id, actor_id)
        parties = (
            (await self.session.execute(select(ProjectParty).where(ProjectParty.project_id == project_id)))
            .scalars()
            .all()
        )
        counts = dict(
            (
                await self.session.execute(
                    select(ProjectPartyMember.party_id, func.count(ProjectPartyMember.id))
                    .where(ProjectPartyMember.project_id == project_id)
                    .group_by(ProjectPartyMember.party_id)
                )
            ).all()
        )
        host_id = await self._host_party_id(project_id)
        out = [await self._to_response(p, host_id=host_id, count=int(counts.get(p.id, 0))) for p in parties]
        out.sort(key=lambda r: (not r.is_host, r.name.lower()))
        return out

    async def _assert_unique_name(self, project_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None) -> None:
        stmt = select(ProjectParty.id).where(
            ProjectParty.project_id == project_id,
            func.lower(ProjectParty.name) == name.lower(),
        )
        if exclude is not None:
            stmt = stmt.where(ProjectParty.id != exclude)
        if (await self.session.execute(stmt.limit(1))).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A party with this name already exists on the project",
            )

    async def create_party(
        self, project_id: uuid.UUID, data: ProjectPartyCreate, *, actor_id: str | uuid.UUID | None
    ) -> ProjectPartyResponse:
        await self._assert_project_admin(project_id, actor_id)
        await self._assert_unique_name(project_id, data.name)
        party = ProjectParty(project_id=project_id, **data.model_dump())
        self.session.add(party)
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="project_party",
            entity_id=party.id,
            action="party_created",
            metadata={"project_id": str(project_id), "name": party.name, "role": party.role},
        )
        return await self._to_response(party, host_id=await self._host_party_id(project_id), count=0)

    async def update_party(
        self,
        project_id: uuid.UUID,
        party_id: uuid.UUID,
        data: ProjectPartyUpdate,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> ProjectPartyResponse:
        await self._assert_project_admin(project_id, actor_id)
        party = await self._get_party(project_id, party_id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is not None:
            await self._assert_unique_name(project_id, changes["name"], exclude=party.id)
        for key, value in changes.items():
            if value is None and key in ("name", "role", "notes", "is_active"):
                continue
            setattr(party, key, value)
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="project_party",
            entity_id=party.id,
            action="party_updated",
            metadata={"project_id": str(project_id), "changes": sorted(changes)},
        )
        count = (
            await self.session.execute(
                select(func.count(ProjectPartyMember.id)).where(ProjectPartyMember.party_id == party.id)
            )
        ).scalar_one()
        return await self._to_response(party, host_id=await self._host_party_id(project_id), count=int(count))

    async def delete_party(
        self, project_id: uuid.UUID, party_id: uuid.UUID, *, actor_id: str | uuid.UUID | None
    ) -> None:
        """Delete a party, its bindings and its record rows.

        Its members become internal again. That widens what they can see, which
        is why the delete is owner or admin only and audited with the counts.
        """
        await self._assert_project_admin(project_id, actor_id)
        party = await self._get_party(project_id, party_id)
        members = (
            await self.session.execute(
                select(func.count(ProjectPartyMember.id)).where(ProjectPartyMember.party_id == party.id)
            )
        ).scalar_one()
        records = (
            await self.session.execute(
                select(func.count(PartyRecordAccess.id)).where(PartyRecordAccess.party_id == party.id)
            )
        ).scalar_one()
        # Children first and explicitly, so the outcome does not depend on the
        # engine enforcing the ON DELETE CASCADE.
        await self.session.execute(delete(PartyRecordAccess).where(PartyRecordAccess.party_id == party.id))
        await self.session.execute(delete(ProjectPartyMember).where(ProjectPartyMember.party_id == party.id))
        await self.session.delete(party)
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="project_party",
            entity_id=party_id,
            action="party_deleted",
            metadata={
                "project_id": str(project_id),
                "name": party.name,
                "members_unbound": int(members),
                "record_rows_removed": int(records),
            },
            strict=True,
        )

    # ── Members ──────────────────────────────────────────────────────────

    async def list_members(
        self, project_id: uuid.UUID, *, actor_id: str | uuid.UUID | None
    ) -> list[PartyMemberResponse]:
        from app.modules.users.models import User

        await self._assert_project_access(project_id, actor_id)
        rows = (
            await self.session.execute(
                select(
                    ProjectPartyMember.user_id,
                    ProjectPartyMember.party_id,
                    ProjectParty.name,
                    User.full_name,
                    User.email,
                )
                .join(ProjectParty, ProjectParty.id == ProjectPartyMember.party_id)
                .join(User, User.id == ProjectPartyMember.user_id)
                .where(ProjectPartyMember.project_id == project_id)
                .order_by(ProjectParty.name, User.full_name)
            )
        ).all()
        return [
            PartyMemberResponse(user_id=r[0], party_id=r[1], party_name=r[2], full_name=r[3] or "", email=r[4] or "")
            for r in rows
        ]

    async def _user_reaches_project(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        from app.modules.projects.models import Project
        from app.modules.teams.access import is_project_member

        owner_id = (
            await self.session.execute(select(Project.owner_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        if owner_id is not None and str(owner_id) == str(user_id):
            return True
        return await is_project_member(self.session, project_id, user_id)

    async def bind_member(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        party_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> PartyMemberResponse:
        """Bind a project member to a party. A member has at most one party per project."""
        from app.modules.users.models import User

        await self._assert_project_admin(project_id, actor_id)
        party = await self._get_party(project_id, party_id)
        if not party.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This party is inactive")
        if not await self._user_reaches_project(project_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only a member of the project can be bound to one of its parties",
            )
        existing = (
            await self.session.execute(
                select(ProjectPartyMember).where(
                    ProjectPartyMember.project_id == project_id,
                    ProjectPartyMember.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.party_id != party.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This member already belongs to another party on the project; unbind them first",
            )
        if existing is None:
            self.session.add(ProjectPartyMember(project_id=project_id, party_id=party.id, user_id=user_id))
            await self.session.flush()
            await self._audit(
                actor_id=actor_id,
                entity_type="project_party",
                entity_id=party.id,
                action="party_member_bound",
                metadata={"project_id": str(project_id), "user_id": str(user_id)},
            )
        user = await self.session.get(User, user_id)
        return PartyMemberResponse(
            user_id=user_id,
            party_id=party.id,
            party_name=party.name,
            full_name=getattr(user, "full_name", "") or "",
            email=getattr(user, "email", "") or "",
        )

    async def unbind_member(
        self, project_id: uuid.UUID, user_id: uuid.UUID, *, actor_id: str | uuid.UUID | None
    ) -> None:
        await self._assert_project_admin(project_id, actor_id)
        existing = (
            await self.session.execute(
                select(ProjectPartyMember).where(
                    ProjectPartyMember.project_id == project_id,
                    ProjectPartyMember.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise _not_found("Member is not bound to a party")
        party_id = existing.party_id
        await self.session.delete(existing)
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="project_party",
            entity_id=party_id,
            action="party_member_unbound",
            metadata={"project_id": str(project_id), "user_id": str(user_id)},
            strict=True,
        )

    async def my_scope(self, project_id: uuid.UUID, *, actor_id: str | uuid.UUID | None) -> PartyScopeResponse:
        await self._assert_project_access(project_id, actor_id)
        scope = await resolve_party_scope(self.session, project_id, actor_id)
        name = None
        if scope.party_id is not None:
            party = await self.session.get(ProjectParty, scope.party_id)
            name = party.name if party is not None else None
        has_parties = (
            await self.session.execute(select(ProjectParty.id).where(ProjectParty.project_id == project_id).limit(1))
        ).scalar_one_or_none() is not None
        return PartyScopeResponse(
            project_id=project_id,
            restricted=scope.restricted,
            party_id=scope.party_id,
            party_name=name,
            is_host=scope.is_host,
            has_parties=has_parties,
            can_manage=await self._is_owner_or_admin(project_id, actor_id),
        )

    # ── Record shares ────────────────────────────────────────────────────

    async def _load_record(self, project_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> None:
        register = get_party_register(entity_type)
        if register is None:
            raise _not_found()
        model = register.model()
        record_project = (
            await self.session.execute(select(model.project_id).where(model.id == entity_id))
        ).scalar_one_or_none()
        if record_project is None or record_project != project_id:
            raise _not_found()

    async def _gate_record(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        await self._load_record(project_id, entity_type, entity_id)
        if actor_id is not None:
            await verify_record_access(
                self.session,
                entity_type=entity_type,
                project_id=project_id,
                entity_id=entity_id,
                user_id=actor_id,
            )

    async def _rows(self, entity_type: str, entity_id: uuid.UUID) -> list[tuple[PartyRecordAccess, ProjectParty]]:
        return list(
            (
                await self.session.execute(
                    select(PartyRecordAccess, ProjectParty)
                    .join(ProjectParty, ProjectParty.id == PartyRecordAccess.party_id)
                    .where(PartyRecordAccess.entity_type == entity_type, PartyRecordAccess.entity_id == entity_id)
                    .order_by(ProjectParty.name)
                )
            ).all()
        )

    async def _can_share(
        self, project_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, actor_id: str | uuid.UUID | None
    ) -> bool:
        scope = await resolve_party_scope(self.session, project_id, actor_id)
        if scope.internal:
            return True
        if scope.party_id is None:
            return False
        origin = (
            await self.session.execute(
                select(PartyRecordAccess.party_id).where(
                    PartyRecordAccess.entity_type == entity_type,
                    PartyRecordAccess.entity_id == entity_id,
                    PartyRecordAccess.access == ACCESS_ORIGINATOR,
                )
            )
        ).scalar_one_or_none()
        return origin == scope.party_id

    async def record_parties(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> RecordPartiesResponse:
        """Originator and shares of a record, as seen by someone who may read it."""
        await self._gate_record(project_id, entity_type, entity_id, actor_id)
        originator: RecordPartyRow | None = None
        shares: list[RecordPartyRow] = []
        for row, party in await self._rows(entity_type, entity_id):
            item = RecordPartyRow(
                party_id=party.id,
                party_name=party.name,
                party_role=party.role,
                access=row.access,
                permission=row.permission,
                shared_by=row.shared_by,
                shared_at=row.created_at,
            )
            if row.access == ACCESS_ORIGINATOR:
                originator = item
            else:
                shares.append(item)
        return RecordPartiesResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            originator=originator,
            shares=shares,
            can_share=await self._can_share(project_id, entity_type, entity_id, actor_id),
            can_set_originator=await self._is_owner_or_admin(project_id, actor_id),
        )

    async def share_record(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        party_id: uuid.UUID,
        permission: str,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> RecordPartiesResponse:
        """Share a record with a party of the same project, or change the share's permission."""
        await self._gate_record(project_id, entity_type, entity_id, actor_id)
        if not await self._can_share(project_id, entity_type, entity_id, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the originating company or an internal member can share this record",
            )
        # A party of another project answers 404 like a party that does not exist.
        party = await self._get_party(project_id, party_id)
        if not party.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This party is inactive")
        existing = (
            await self.session.execute(
                select(PartyRecordAccess).where(
                    PartyRecordAccess.entity_type == entity_type,
                    PartyRecordAccess.entity_id == entity_id,
                    PartyRecordAccess.party_id == party.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.access == ACCESS_ORIGINATOR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This party originated the record and already has full access",
            )
        if existing is None:
            self.session.add(
                PartyRecordAccess(
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    party_id=party.id,
                    access=ACCESS_SHARED,
                    permission=permission,
                    shared_by=uuid.UUID(str(actor_id)) if actor_id is not None else None,
                )
            )
            action = "party_share_granted"
        else:
            existing.permission = permission
            action = "party_share_changed"
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="party_record",
            entity_id=entity_id,
            action=action,
            metadata={
                "project_id": str(project_id),
                "record_type": entity_type,
                "party_id": str(party.id),
                "party_name": party.name,
                "permission": permission,
            },
            strict=True,
        )
        return await self.record_parties(project_id, entity_type, entity_id, actor_id=actor_id)

    async def revoke_share(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        party_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Withdraw a share. Audited in the same transaction; an audit failure aborts it."""
        await self._gate_record(project_id, entity_type, entity_id, actor_id)
        if not await self._can_share(project_id, entity_type, entity_id, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the originating company or an internal member can change who sees this record",
            )
        row = (
            await self.session.execute(
                select(PartyRecordAccess).where(
                    PartyRecordAccess.project_id == project_id,
                    PartyRecordAccess.entity_type == entity_type,
                    PartyRecordAccess.entity_id == entity_id,
                    PartyRecordAccess.party_id == party_id,
                    PartyRecordAccess.access == ACCESS_SHARED,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise _not_found("Share not found")
        permission = row.permission
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="party_record",
            entity_id=entity_id,
            action="party_share_revoked",
            metadata={
                "project_id": str(project_id),
                "record_type": entity_type,
                "party_id": str(party_id),
                "permission": permission,
            },
            strict=True,
        )

    async def set_originator(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        party_id: uuid.UUID | None,
        *,
        actor_id: str | uuid.UUID | None,
    ) -> RecordPartiesResponse:
        """Owner or admin: name (or clear) the party that originated a record.

        For records created before parties existed, or entered by an internal
        member on a company's behalf.
        """
        await self._assert_project_admin(project_id, actor_id)
        await self._load_record(project_id, entity_type, entity_id)
        if party_id is not None:
            await self._get_party(project_id, party_id)
        rows = (
            (
                await self.session.execute(
                    select(PartyRecordAccess).where(
                        PartyRecordAccess.entity_type == entity_type,
                        PartyRecordAccess.entity_id == entity_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        previous = None
        for row in rows:
            if row.access == ACCESS_ORIGINATOR:
                previous = row.party_id
                await self.session.delete(row)
            elif party_id is not None and row.party_id == party_id:
                # The new originator's share is superseded by the originator row.
                await self.session.delete(row)
        await self.session.flush()
        if party_id is not None:
            self.session.add(
                PartyRecordAccess(
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    party_id=party_id,
                    access=ACCESS_ORIGINATOR,
                    permission=PERMISSION_CONTRIBUTE,
                    shared_by=uuid.UUID(str(actor_id)) if actor_id is not None else None,
                )
            )
            await self.session.flush()
        await self._audit(
            actor_id=actor_id,
            entity_type="party_record",
            entity_id=entity_id,
            action="party_originator_set",
            metadata={
                "project_id": str(project_id),
                "record_type": entity_type,
                "previous_party_id": str(previous) if previous else None,
                "party_id": str(party_id) if party_id else None,
            },
            strict=True,
        )
        return await self.record_parties(project_id, entity_type, entity_id, actor_id=actor_id)
