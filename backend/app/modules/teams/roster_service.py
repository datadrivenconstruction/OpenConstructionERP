# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project roster service - who is on this job, and in what capacity.

Authorisation
~~~~~~~~~~~~~
Reads and writes both need project access, which is one gate lower than the
rest of this module. That is deliberate and it rests on a single property: a
roster line grants nothing. It cannot let anyone reach a project, a team or a
record. Maintaining the roster is daily site work - people arrive, tickets
expire, a subcontractor swaps a foreman - and putting it behind project
ownership would guarantee it goes stale, which is the failure mode that makes
the whole feature worthless.

The one thing that does change access, ``grant_project_access`` on an add, is
not handled here. It is delegated to :meth:`TeamService.add_member`, which
keeps the owner-or-admin gate and the elevated-role check in the single place
that has always owned them.

Where the people come from
~~~~~~~~~~~~~~~~~~~~~~~~~~
:meth:`RosterService.list_candidates` searches platform users and address-book
contacts together, so a team is assembled from what the platform already knows
rather than retyped. Contacts are reached through a late import guarded by
``ImportError``: a module has to keep working when an optional module is not
installed, so a deployment without the contacts module simply offers users.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.demo_privacy import anonymize_email, demo_mode_enabled, should_redact
from app.core.events import event_bus
from app.modules.teams.models import RosterMember, Team, TeamMembership
from app.modules.teams.repository import RosterRepository, TeamRepository
from app.modules.teams.roster_schemas import (
    CertificationState,
    RosterCandidate,
    RosterMemberCreate,
    RosterMemberResponse,
    RosterMemberUpdate,
    RosterSummary,
    RosterTradeCount,
)
from app.modules.teams.roster_vocab import (
    ROSTER_TRADES,
    SITE_ROLES,
    site_role_label,
    trade_label,
)
from app.modules.teams.schemas import AddMemberRequest
from app.modules.teams.service import TeamService
from app.modules.users.models import User

logger = logging.getLogger(__name__)

#: Supervisory roles first, then the rest of the catalogue order, then people
#: with no role stated. A roster is read top-down looking for who is in charge.
_ROLE_RANK: dict[str, int] = {role.key: index for index, role in enumerate(SITE_ROLES)}
_UNRANKED = len(SITE_ROLES) + 1


def _today() -> date:
    """Today in UTC.

    One helper so every expiry answer on a roster read is taken against the
    same day, rather than each field asking the clock again mid-request.
    """
    return datetime.now(UTC).date()


def _person_name(first: str | None, last: str | None, company: str | None) -> str:
    """A contact's name for the roster, falling back to the firm.

    A contact row can describe a person or a company. When it describes a
    company the roster line is that company's representative slot, and the firm
    name is the only name there is.
    """
    person = " ".join(part for part in (first or "", last or "") if part).strip()
    return person or (company or "").strip()


class RosterService:
    """Business logic for the project roster."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RosterRepository(session)
        self.team_repo = TeamRepository(session)
        self.teams = TeamService(session)

    # ── Gates ────────────────────────────────────────────────────────────

    async def _assert_project_access(
        self,
        project_id: uuid.UUID,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Gate on project access. ``None`` is a system call and skips the gate."""
        if actor_id is None:
            return
        # Late-import for the same reason the teams service does it: keeping
        # the FastAPI dependency graph out of module-load order.
        from app.dependencies import verify_project_access

        await verify_project_access(project_id, str(actor_id), self.session)

    # ── Reads ────────────────────────────────────────────────────────────

    async def list_roster(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
        include_inactive: bool = True,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[RosterMemberResponse], int]:
        """One page of the project roster, resolved for display and ordered for reading.

        Returns the page and the number of lines matching ``include_inactive``,
        which is the only filter this read has. ``limit=None`` means the whole
        matched set, which is what an in-process caller wanting the roster
        rather than a page asks for; the route always passes a number.

        The page is cut in Python rather than in SQL, and that is not laziness.
        Reading order is :meth:`_reading_order` - supervisory roles first, then
        trade, then name - and it is computed from resolved rows, not from
        columns: the team name and the contact name are fetched separately and
        the role rank is a Python dict. Pushing OFFSET/LIMIT into the query
        would page in the database's order and then sort only within the page,
        so page two would hold names that belong on page one.

        Slicing after the sort means every matched row is already in hand, so
        ``total`` is ``len()`` of them and costs no COUNT query.
        """
        await self._assert_project_access(project_id, actor_id)
        rows = await self.repo.list_for_project(project_id, include_inactive=include_inactive)
        access_user_ids = await self._project_access_user_ids(project_id)
        contact_names = await self._contact_names({m.contact_id for m, _, _ in rows if m.contact_id})
        today = _today()
        responses = [
            self._to_response(member, team, user, access_user_ids, contact_names, today) for member, team, user in rows
        ]
        responses.sort(key=self._reading_order)
        total = len(responses)
        if limit is None:
            return responses[offset:], total
        return responses[offset : offset + limit], total

    async def summary(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> RosterSummary:
        """What the roster adds up to.

        ``unrostered_member_count`` is the number that closes the loop with the
        rest of the platform: people who hold project access but appear nowhere
        on the roster. They are the ones whose name shows up on a snag with no
        trade and no firm behind it.
        """
        await self._assert_project_access(project_id, actor_id)
        rows = await self.repo.list_for_project(project_id, include_inactive=True)
        access_user_ids = await self._project_access_user_ids(project_id)
        today = _today()

        trades: dict[str, int] = {}
        roles: dict[str, int] = {}
        companies: set[str] = set()
        rostered_users: set[uuid.UUID] = set()
        active = 0
        without_access = 0
        expired = 0
        off_window = 0

        for member, _team, _user in rows:
            if member.user_id:
                rostered_users.add(member.user_id)
            if not member.is_active:
                continue
            active += 1
            if member.company_name:
                companies.add(member.company_name.casefold())
            if member.trade:
                trades[member.trade] = trades.get(member.trade, 0) + 1
            if member.site_role:
                roles[member.site_role] = roles.get(member.site_role, 0) + 1
            if member.user_id is None or member.user_id not in access_user_ids:
                without_access += 1
            expired += sum(1 for cert in self._certification_states(member.certifications, today) if cert.expired)
            if self._off_window(member, today):
                off_window += 1

        return RosterSummary(
            project_id=project_id,
            headcount=len(rows),
            active_headcount=active,
            company_count=len(companies),
            without_access_count=without_access,
            unrostered_member_count=len(access_user_ids - rostered_users),
            expired_certification_count=expired,
            off_window_count=off_window,
            by_trade=[
                RosterTradeCount(key=t.key, label=t.label, count=trades[t.key])
                for t in ROSTER_TRADES
                if t.key in trades
            ],
            by_site_role=[
                RosterTradeCount(key=r.key, label=r.label, count=roles[r.key]) for r in SITE_ROLES if r.key in roles
            ],
        )

    async def list_candidates(
        self,
        project_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
        query: str = "",
        limit: int = 50,
    ) -> tuple[list[RosterCandidate], int]:
        """People the platform already knows, offered for this project's roster.

        Users and contacts in one list, each marked with whether they are
        already on the roster, so the drawer that assembles a team never asks
        anybody to retype a name the database is holding.

        Returns the page and how many people matched ``query``. The total is
        counted, not measured: both searches apply ``limit`` in the database,
        so the rows in hand are already cut short and reporting their length
        would state a wrong number confidently. Somebody who is both a user and
        a contact counts twice, because they appear in ``items`` twice too -
        deduplicating one side alone would make the total disagree with what
        the caller can see.

        There is no offset, and the envelope's ``offset`` is always 0. Serving
        a second page would mean re-sorting the union of two sources that are
        ordered independently in SQL - users by name and email, contacts by
        company and surname - by a key neither of them carries
        (``on_roster``, then the display name). The true page two of that union
        is not contained in the two per-source windows, so it would drop names
        and repeat others. A picker that shows the first page and states the
        real size is honest; one that pages wrongly is not. Narrowing ``query``
        is how a caller reaches the rest today.
        """
        await self._assert_project_access(project_id, actor_id)
        rostered_users, rostered_contacts = await self.repo.linked_ids(project_id)
        access_user_ids = await self._project_access_user_ids(project_id)
        needle = query.strip().lower()

        # On the public hosted demo the user side of the picker is not a
        # directory of everyone who signed up: it offers only the caller and
        # people already on this project, for the rows and the count alike (a
        # count over all users would still answer "does alice@acme.com have
        # an account"), and shows everyone but the caller redacted.
        within: set[uuid.UUID] | None = None
        if demo_mode_enabled():
            within = {uuid.UUID(str(u)) for u in (*access_user_ids, *rostered_users)}
            if actor_id is not None:
                within.add(uuid.UUID(str(actor_id)))

        candidates: list[RosterCandidate] = []
        for user in await self._search_users(needle, limit, within=within):
            if should_redact(user.id, actor_id):
                shown_email = anonymize_email(user.email)
                shown_name = shown_email
            else:
                shown_email = user.email
                shown_name = (user.full_name or "").strip() or user.email
            candidates.append(
                RosterCandidate(
                    id=user.id,
                    source="user",
                    name=shown_name,
                    email=shown_email,
                    on_roster=user.id in rostered_users,
                    has_project_access=user.id in access_user_ids,
                )
            )
        candidates.extend(await self._search_contacts(needle, limit, rostered_contacts))
        total = await self._count_users(needle, within=within) + await self._count_contacts(needle)
        # Somebody already on the roster stays in the list, ticked, rather than
        # disappearing: a name that is absent from a search reads as "we do not
        # have them" and sends the user off to create a duplicate.
        candidates.sort(key=lambda c: (c.on_roster, c.name.casefold()))
        return candidates[:limit], total

    # ── Writes ───────────────────────────────────────────────────────────

    async def add_members(
        self,
        project_id: uuid.UUID,
        payloads: list[RosterMemberCreate],
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> list[RosterMemberResponse]:
        """Put several people on the roster in one transaction.

        A person the roster already holds is skipped rather than rejected. The
        add drawer is a multi-select over a list that says who is already
        there, so a repeat is a race or a double click, and failing the other
        nine names because of it would be the wrong answer.
        """
        await self._assert_project_access(project_id, actor_id)
        rostered_users, rostered_contacts = await self.repo.linked_ids(project_id)
        teams = {team.id: team for team in await self.team_repo.list_for_project(project_id, include_inactive=True)}

        prepared: list[RosterMember] = []
        grants: list[tuple[uuid.UUID, str]] = []
        for payload in payloads:
            if payload.user_id and payload.user_id in rostered_users:
                continue
            if payload.contact_id and payload.contact_id in rostered_contacts:
                continue
            if payload.team_id is not None and payload.team_id not in teams:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team not found",
                )
            prepared.append(await self._build_member(project_id, payload))
            if payload.grant_project_access and payload.user_id:
                grants.append((payload.user_id, payload.access_role))
            if payload.user_id:
                rostered_users.add(payload.user_id)
            if payload.contact_id:
                rostered_contacts.add(payload.contact_id)

        # Access first, roster second. The access grant is the only part of
        # this call that can be refused for who the caller is, and doing it
        # before any roster row is written makes the refusal arrive with
        # nothing written rather than with a batch to reason about.
        for user_id, role in grants:
            await self._grant_project_access(project_id, user_id, role, actor_id)
        created = await self.repo.add_all(prepared)

        for member in created:
            await self._record_audit(
                actor_id=actor_id,
                member=member,
                action="roster_member_added",
                metadata={"project_id": str(project_id), "site_role": member.site_role, "trade": member.trade},
            )
        if created:
            await self._publish_event(
                "teams.roster.added",
                {
                    "project_id": str(project_id),
                    "member_ids": [str(m.id) for m in created],
                    "actor_id": str(actor_id) if actor_id else None,
                },
            )
        return await self._respond(project_id, created)

    async def update_member(
        self,
        project_id: uuid.UUID,
        member_id: uuid.UUID,
        payload: RosterMemberUpdate,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> RosterMemberResponse:
        """Change one roster line."""
        await self._assert_project_access(project_id, actor_id)
        member = await self._get_or_404(project_id, member_id)
        fields = payload.assigned_fields()
        if "team_id" in fields and fields["team_id"] is not None:
            # A team of some other project would group this person under a name
            # nobody on this project can see, so it answers 404 the same way a
            # team that does not exist does.
            found = await self.team_repo.list_in_project(project_id, [fields["team_id"]])  # type: ignore[list-item]
            if not found:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        if fields:
            await self.repo.update_fields(member, fields)
            await self._record_audit(
                actor_id=actor_id,
                member=member,
                action="roster_member_updated",
                metadata={"project_id": str(project_id), "fields": sorted(fields)},
            )
        responses = await self._respond(project_id, [member])
        return responses[0]

    async def remove_member(
        self,
        project_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID | None = None,
    ) -> None:
        """Take one person off the roster.

        This removes the roster line only. Any project access the person holds
        is a team membership and survives, because withdrawing access is a
        different decision made on a different screen by a different gate.
        """
        await self._assert_project_access(project_id, actor_id)
        member = await self._get_or_404(project_id, member_id)
        await self._record_audit(
            actor_id=actor_id,
            member=member,
            action="roster_member_removed",
            metadata={"project_id": str(project_id), "display_name": member.display_name},
        )
        await self.repo.delete(member)

    # ── Internals ────────────────────────────────────────────────────────

    async def _get_or_404(self, project_id: uuid.UUID, member_id: uuid.UUID) -> RosterMember:
        """One roster line of this project, or 404.

        A line belonging to another project answers exactly the same way as one
        that does not exist, so an id cannot be probed across projects.
        """
        member = await self.repo.get_in_project(project_id, member_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Roster entry not found")
        return member

    async def _build_member(self, project_id: uuid.UUID, payload: RosterMemberCreate) -> RosterMember:
        """Turn one create payload into a row, filling the blanks from the link.

        Name, firm, email and phone are taken from the linked user or contact
        whenever the request left them empty. What the request DID send always
        wins: a site phone that differs from the head-office number is the
        normal case, not a mistake to be overwritten.
        """
        display_name = payload.display_name
        company_name = payload.company_name
        email = payload.email
        phone = payload.phone

        if payload.user_id is not None:
            user = await self._load_user(payload.user_id)
            display_name = display_name or (user.full_name or "").strip() or user.email
            email = email or user.email
        elif payload.contact_id is not None:
            contact = await self._load_contact(payload.contact_id)
            if contact is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
            display_name = display_name or _person_name(
                contact.get("first_name"), contact.get("last_name"), contact.get("company_name")
            )
            company_name = company_name or (contact.get("company_name") or "")
            email = email or (contact.get("primary_email") or "")
            phone = phone or (contact.get("primary_phone") or "")

        if not display_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="[teams.validation.roster.no_name] Pick somebody the platform knows, or type a name",
            )

        return RosterMember(
            project_id=project_id,
            team_id=payload.team_id,
            user_id=payload.user_id,
            contact_id=payload.contact_id,
            display_name=display_name[:255],
            company_name=company_name[:255],
            trade=payload.trade,
            site_role=payload.site_role,
            email=email[:255],
            phone=phone[:50],
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            allocation_percent=payload.allocation_percent,
            certifications=[c.model_dump(mode="json") for c in payload.certifications],
            resource_id=payload.resource_id,
            notes=payload.notes,
        )

    async def _grant_project_access(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        actor_id: str | uuid.UUID | None,
    ) -> None:
        """Give a rostered user access to the project, through the gated path.

        Delegated to :meth:`TeamService.add_member` on the project's default
        team, so the owner-or-admin gate, the elevated-role check and the audit
        trail that has always guarded project access still apply. A caller who
        may edit the roster but not hand out access is refused the whole call
        with a 403 and nothing is written - the alternative, writing the roster
        line and dropping the access request, would tell them they got what
        they asked for.
        """
        team = await self._default_team(project_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This project has no default team to grant access through",
            )
        await self.teams.add_member(team.id, AddMemberRequest(user_id=user_id, role=role), actor_id=actor_id)

    async def _default_team(self, project_id: uuid.UUID) -> Team | None:
        """The project's default team, or any team, or None."""
        teams = await self.team_repo.list_for_project(project_id, include_inactive=False)
        if not teams:
            return None
        for team in teams:
            if team.is_default:
                return team
        return teams[0]

    async def _load_user(self, user_id: uuid.UUID) -> User:
        """The user row behind a roster link, or 404."""
        user = (await self.session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def _load_contact(self, contact_id: uuid.UUID) -> dict[str, Any] | None:
        """One contact as a plain dict, or ``None`` when contacts are unavailable.

        Returns a dict rather than the ORM object so the rest of this service
        never holds a type from an optional module.
        """
        rows = await self._load_contacts([contact_id])
        return rows.get(contact_id)

    async def _load_contacts(self, contact_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """Several contacts at once, keyed by id. Empty when contacts are absent."""
        if not contact_ids:
            return {}
        try:
            from app.modules.contacts.models import Contact
        except ImportError:  # pragma: no cover - deployment without the contacts module
            logger.debug("contacts module unavailable; roster contact links stay unresolved")
            return {}
        stmt = select(Contact).where(Contact.id.in_(contact_ids))
        return {
            contact.id: {
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "company_name": contact.company_name,
                "primary_email": contact.primary_email,
                "primary_phone": contact.primary_phone,
                "contact_type": contact.contact_type,
            }
            for contact in (await self.session.execute(stmt)).scalars().all()
        }

    async def _contact_names(self, contact_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Display names for linked contacts, for lines that were never given one."""
        rows = await self._load_contacts(contact_ids)
        return {
            contact_id: _person_name(row.get("first_name"), row.get("last_name"), row.get("company_name"))
            for contact_id, row in rows.items()
        }

    # The two candidate searches are each written as a filter builder plus the
    # two things done to it, a page read and a count. Splitting them that way
    # is what makes the total trustworthy: one WHERE clause serves both, so a
    # filter added later cannot land on the page query alone and leave the
    # total describing a wider set than the rows it is attached to.

    def _users_stmt(self, needle: str, within: set[uuid.UUID] | None = None) -> Select[Any]:
        """Active users matching ``needle`` in their name or email, unpaged.

        ``within`` narrows the search to those ids (demo mode), so the page
        and the count stay one WHERE clause.
        """
        stmt = select(User).where(User.is_active.is_(True))
        if within is not None:
            stmt = stmt.where(User.id.in_(within)) if within else stmt.where(false())
        if needle:
            pattern = f"%{needle}%"
            stmt = stmt.where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
        return stmt

    async def _search_users(self, needle: str, limit: int, *, within: set[uuid.UUID] | None = None) -> list[User]:
        """One page of the active users matching ``needle``."""
        stmt = self._users_stmt(needle, within).order_by(User.full_name, User.email).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _count_users(self, needle: str, *, within: set[uuid.UUID] | None = None) -> int:
        """How many users match ``needle``, whatever the page size."""
        stmt = select(func.count()).select_from(self._users_stmt(needle, within).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    @staticmethod
    def _contact_model() -> Any | None:
        """The Contact model, or None where the contacts module is not installed.

        The candidate list then offers platform users only, which is still a
        working screen, and the total counts users only for the same reason -
        so it keeps describing exactly the set ``items`` was drawn from.
        """
        try:
            from app.modules.contacts.models import Contact
        except ImportError:  # pragma: no cover - deployment without the contacts module
            return None
        return Contact

    def _contacts_stmt(self, needle: str, contact_model: Any) -> Select[Any]:
        """Active address-book contacts matching ``needle``, unpaged."""
        stmt = select(contact_model).where(contact_model.is_active.is_(True))
        if needle:
            pattern = f"%{needle}%"
            stmt = stmt.where(
                or_(
                    contact_model.first_name.ilike(pattern),
                    contact_model.last_name.ilike(pattern),
                    contact_model.company_name.ilike(pattern),
                    contact_model.primary_email.ilike(pattern),
                )
            )
        return stmt

    async def _count_contacts(self, needle: str) -> int:
        """How many contacts match ``needle``; zero without the contacts module."""
        contact_model = self._contact_model()
        if contact_model is None:
            return 0
        stmt = select(func.count()).select_from(self._contacts_stmt(needle, contact_model).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    async def _search_contacts(
        self,
        needle: str,
        limit: int,
        rostered_contacts: set[uuid.UUID],
    ) -> list[RosterCandidate]:
        """One page of the address-book contacts matching ``needle``.

        Silent when the contacts module is not installed - the candidate list
        then offers platform users only, which is still a working screen.
        """
        contact_model = self._contact_model()
        if contact_model is None:
            return []
        stmt = (
            self._contacts_stmt(needle, contact_model)
            .order_by(contact_model.company_name, contact_model.last_name)
            .limit(limit)
        )
        return [
            RosterCandidate(
                id=contact.id,
                source="contact",
                name=_person_name(contact.first_name, contact.last_name, contact.company_name)
                or (contact.primary_email or ""),
                email=contact.primary_email or "",
                phone=contact.primary_phone or "",
                company_name=contact.company_name or "",
                on_roster=contact.id in rostered_contacts,
            )
            for contact in (await self.session.execute(stmt)).scalars().all()
        ]

    async def _project_access_user_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Everyone holding a team membership on this project.

        This is what "can sign in and see this project" means, read from the
        authorization table itself rather than inferred from the roster.
        """
        stmt = (
            select(TeamMembership.user_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == project_id)
            .distinct()
        )
        return {row for (row,) in (await self.session.execute(stmt)).all()}

    async def _respond(self, project_id: uuid.UUID, members: list[RosterMember]) -> list[RosterMemberResponse]:
        """Resolve a handful of just-written rows into responses."""
        if not members:
            return []
        teams = {team.id: team for team in await self.team_repo.list_for_project(project_id, include_inactive=True)}
        access_user_ids = await self._project_access_user_ids(project_id)
        contact_names = await self._contact_names({m.contact_id for m in members if m.contact_id})
        users = {
            user.id: user
            for user in (
                await self.session.execute(select(User).where(User.id.in_([m.user_id for m in members if m.user_id])))
            )
            .scalars()
            .all()
        }
        today = _today()
        return [
            self._to_response(
                member,
                teams.get(member.team_id) if member.team_id else None,
                users.get(member.user_id) if member.user_id else None,
                access_user_ids,
                contact_names,
                today,
            )
            for member in members
        ]

    def _certification_states(self, raw: Any, today: date) -> list[CertificationState]:
        """Read the stored ticket list back, with expiry resolved against ``today``.

        A malformed entry is dropped rather than raising: the JSON column has
        been writable by the schema layer only, but a hand-edited row must not
        take the whole roster screen down with it.
        """
        if not isinstance(raw, list):
            return []
        states: list[CertificationState] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                state = CertificationState.model_validate(entry)
            except ValueError:
                logger.debug("dropping malformed roster certification entry")
                continue
            if state.valid_until is not None:
                state.days_remaining = (state.valid_until - today).days
                state.expired = state.valid_until < today
            states.append(state)
        return states

    def _off_window(self, member: RosterMember, today: date) -> bool:
        """True when today falls outside the person's stated dates on the project."""
        if member.starts_on and today < member.starts_on:
            return True
        return bool(member.ends_on and today > member.ends_on)

    def _to_response(
        self,
        member: RosterMember,
        team: Team | None,
        user: User | None,
        access_user_ids: set[uuid.UUID],
        contact_names: dict[uuid.UUID, str],
        today: date,
    ) -> RosterMemberResponse:
        """One row, resolved: names filled, labels attached, expiry answered."""
        if member.user_id is not None:
            source = "user"
        elif member.contact_id is not None:
            source = "contact"
        else:
            source = "manual"

        name = member.display_name
        if not name and user is not None:
            name = (user.full_name or "").strip() or user.email
        if not name and member.contact_id is not None:
            name = contact_names.get(member.contact_id, "")

        certifications = self._certification_states(member.certifications, today)
        return RosterMemberResponse(
            id=member.id,
            project_id=member.project_id,
            team_id=member.team_id,
            team_name=team.name if team is not None else "",
            user_id=member.user_id,
            contact_id=member.contact_id,
            resource_id=member.resource_id,
            source=source,
            display_name=name,
            company_name=member.company_name,
            trade=member.trade,
            trade_label=trade_label(member.trade) if member.trade else "",
            site_role=member.site_role,
            site_role_label=site_role_label(member.site_role) if member.site_role else "",
            email=member.email or (user.email if user is not None else ""),
            phone=member.phone,
            starts_on=member.starts_on,
            ends_on=member.ends_on,
            allocation_percent=member.allocation_percent,
            certifications=certifications,
            notes=member.notes,
            is_active=member.is_active,
            has_project_access=member.user_id is not None and member.user_id in access_user_ids,
            user_is_inactive=user is not None and not user.is_active,
            off_window=self._off_window(member, today),
            expired_certification_count=sum(1 for c in certifications if c.expired),
        )

    def _reading_order(self, row: RosterMemberResponse) -> tuple[Any, ...]:
        """Sort key: teams together, people in charge first, then by name."""
        return (
            not row.is_active,
            row.team_name.casefold() if row.team_name else "￿",
            _ROLE_RANK.get(row.site_role, _UNRANKED),
            row.display_name.casefold(),
        )

    async def _record_audit(
        self,
        *,
        actor_id: str | uuid.UUID | None,
        member: RosterMember,
        action: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Write one audit row; never let a logging failure abort the write."""
        try:
            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="team_roster_member",
                entity_id=str(member.id),
                action=action,
                metadata=metadata,
            )
        except Exception:  # pragma: no cover - best-effort audit
            logger.exception("audit write failed for roster member=%s action=%s", member.id, action)

    async def _publish_event(self, name: str, payload: dict[str, object]) -> None:
        """Publish a roster event; delivery failures never break the write."""
        try:
            publish_detached = getattr(event_bus, "publish_detached", None)
            if publish_detached is not None:
                publish_detached(name, payload, source_module="oe_teams")
            else:
                await event_bus.publish(name, payload, source_module="oe_teams")
        except Exception:  # pragma: no cover - best-effort fanout
            logger.exception("event publish failed: %s", name)
