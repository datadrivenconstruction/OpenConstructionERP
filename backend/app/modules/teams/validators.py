# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Teams module-specific validation rules.

Access control is configuration, and configuration is exactly the kind of thing
that is silently wrong. A restriction typed against the wrong team, a team
emptied out after a handover, a second team promoted to default: none of these
throw an error at the point they are made, and none of them are visible from
the record they affect. They surface as "why can nobody open the tender pack"
three weeks later. These rules run over a project's whole access configuration
and say so up front.

The rules live in one rule set, ``teams``, and read a single collected snapshot
of the project (see :func:`collect_project_snapshot`), so the whole set is one
pass over four queries rather than one query per rule.

* ``teams.default_team_present``    - ERROR. A project resolves "add a member"
                                      through exactly one active default team.
                                      Zero makes the resolution lazy-create a
                                      team nobody chose; two make it arbitrary.
* ``teams.restriction_has_viewer``  - ERROR. A restricted record whose named
                                      teams have no members between them is
                                      readable by nobody but the project owner
                                      and system admins. This is the "we locked
                                      ourselves out" failure, and it is the
                                      single most common way a visibility model
                                      goes wrong in practice.
* ``teams.restriction_scope``       - ERROR. Every restriction on a project's
                                      record must name a team of that same
                                      project. A row pointing elsewhere is
                                      inert against this project's reads, so it
                                      looks like protection and is not.
* ``teams.empty_team``              - WARNING. An active team with no members
                                      grants nothing. Harmless on its own,
                                      which is why it is a warning, and the
                                      cause of the error above once it starts
                                      holding restrictions.
* ``teams.duplicate_team_name``     - WARNING. Two active teams sharing a name
                                      are indistinguishable in the picker, so a
                                      restriction can be pointed at the wrong
                                      one and read as correct afterwards.
* ``teams.restriction_enforced``    - WARNING. A restriction on a record kind
                                      no consumer subtracts yet is recorded but
                                      not enforced. Saying so is the honest
                                      alternative to letting the UI imply a
                                      lock that is not there.
* ``teams.roster_ticket_valid``     - WARNING. Somebody on the roster is
                                      working on a ticket that has run out.
* ``teams.roster_window``           - WARNING. An active roster line whose last
                                      day has passed, so the roster answers
                                      "who is on site" with somebody who left.
* ``teams.roster_site_lead``        - WARNING. A roster with nobody in a
                                      supervisory role cannot say who runs the
                                      job.
* ``teams.roster_covers_access``    - WARNING. Somebody can open the project
                                      but is on no roster line, so their name
                                      lands on records with no trade or firm
                                      behind it.
* ``teams.party_member_has_access`` - ERROR. A user bound to a project party
                                      who can no longer reach the project. The
                                      binding grants nothing, but it reads as a
                                      company member nobody removed.
* ``teams.party_record_scope``      - ERROR. A shared-register row naming a
                                      party of another project. It reads as a
                                      share and protects or grants nothing.
* ``teams.party_host_defined``      - WARNING. Members are bound to parties but
                                      the project owner is bound to none, so
                                      every bound member is external, including
                                      the owner's own colleagues.

Every rule reads the snapshot only. None of them queries, so none of them can
fail on a session that has already been rolled back, and the whole set is
usable from a read-only replica.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    ValidationStatus,
    rule_registry,
    validation_engine,
)
from app.modules.teams.entity_types import enforced_entity_type_keys, is_known_entity_type
from app.modules.teams.models import (
    EntityVisibility,
    PartyRecordAccess,
    ProjectParty,
    ProjectPartyMember,
    RosterMember,
    Team,
    TeamMembership,
)
from app.modules.teams.roster_vocab import supervisory_site_role_keys
from app.modules.teams.schemas import TeamsValidationFinding, TeamsValidationReport

logger = logging.getLogger(__name__)

#: The rule set every teams rule registers under.
TEAMS_RULE_SET = "teams"


# ── Snapshot ─────────────────────────────────────────────────────────────────


@dataclass
class TeamSnapshot:
    """One team, flattened for the rules."""

    id: str
    name: str
    is_default: bool
    is_active: bool
    member_count: int = 0
    restriction_count: int = 0


@dataclass
class RestrictionSnapshot:
    """One restricted record, flattened for the rules."""

    entity_type: str
    entity_id: str
    #: Teams named by rows on this record that belong to the project.
    in_project_team_ids: list[str] = field(default_factory=list)
    #: Teams named by rows on this record that belong to some other project.
    foreign_team_ids: list[str] = field(default_factory=list)
    #: Distinct users reachable through the in-project teams. Deliberately
    #: excludes the owner and system admins, who never lose access.
    viewer_count: int = 0


@dataclass
class RosterSnapshot:
    """One person on the project roster, flattened for the rules.

    Expiry and "has this person left" are resolved by the collector, against
    one ``today``, so the rules stay pure reads over the snapshot and cannot
    disagree with each other about what day it is.
    """

    id: str
    display_name: str
    is_active: bool
    site_role: str
    #: True when the person's stated last day on the project is already past.
    window_ended: bool = False
    #: The tickets on this line that have run out, by their ``kind``.
    expired_certifications: list[str] = field(default_factory=list)
    #: Set when the line names a platform user.
    user_id: str | None = None


@dataclass
class ProjectTeamsSnapshot:
    """Everything the teams rule set reads about one project."""

    project_id: str
    teams: list[TeamSnapshot] = field(default_factory=list)
    restrictions: list[RestrictionSnapshot] = field(default_factory=list)
    roster: list[RosterSnapshot] = field(default_factory=list)
    #: Users holding project access who appear nowhere on the roster.
    unrostered_user_ids: list[str] = field(default_factory=list)
    #: Number of parties on the project, and of members bound to one.
    party_count: int = 0
    bound_member_count: int = 0
    #: True when the project owner is bound to a party (the host party).
    owner_bound: bool = False
    #: Users bound to a party who no longer reach the project.
    bound_without_access_user_ids: list[str] = field(default_factory=list)
    #: Shared-register rows on this project naming a party of another project.
    foreign_party_record_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """The shape the rules receive as ``context.data``."""
        return {
            "scope": "project_teams",
            "project_id": self.project_id,
            "teams": [t.__dict__ for t in self.teams],
            "restrictions": [r.__dict__ for r in self.restrictions],
            "roster": [r.__dict__ for r in self.roster],
            "unrostered_user_ids": list(self.unrostered_user_ids),
            "parties": {
                "party_count": self.party_count,
                "bound_member_count": self.bound_member_count,
                "owner_bound": self.owner_bound,
                "bound_without_access_user_ids": list(self.bound_without_access_user_ids),
                "foreign_party_record_count": self.foreign_party_record_count,
            },
        }


def _roster_line(member: RosterMember, today: date) -> RosterSnapshot:
    """Flatten one roster row, resolving expiry against a single ``today``."""
    expired: list[str] = []
    raw = member.certifications if isinstance(member.certifications, list) else []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        valid_until = entry.get("valid_until")
        if not isinstance(valid_until, str) or not valid_until:
            continue
        try:
            expires = date.fromisoformat(valid_until[:10])
        except ValueError:
            # A hand-edited value that is not a date says nothing about
            # expiry, and guessing would either invent a breach or hide one.
            continue
        if expires < today:
            expired.append(str(entry.get("kind") or "").strip() or "certification")
    return RosterSnapshot(
        id=str(member.id),
        display_name=member.display_name,
        is_active=bool(member.is_active),
        site_role=member.site_role or "",
        window_ended=bool(member.ends_on and member.ends_on < today),
        expired_certifications=expired,
        user_id=str(member.user_id) if member.user_id else None,
    )


async def collect_project_snapshot(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> ProjectTeamsSnapshot:
    """Read one project's whole access configuration and roster in five queries.

    Deliberately unauthenticated: the caller has already established that the
    requester may see this project. Keeping the gate out of here means the
    collector is reusable from a background sweep that has no HTTP caller.
    """
    snapshot = ProjectTeamsSnapshot(project_id=str(project_id))

    teams = list((await session.execute(select(Team).where(Team.project_id == project_id))).scalars().all())
    project_team_ids = {team.id for team in teams}

    member_rows = (
        await session.execute(
            select(TeamMembership.team_id, TeamMembership.user_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.project_id == project_id)
        )
    ).all()
    members_by_team: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for team_id, user_id in member_rows:
        members_by_team[team_id].add(user_id)

    # Restriction rows are matched on the record identity, NOT scoped to the
    # project's teams, precisely so the scope rule can see a row that points
    # somewhere else. The scoped reads used on the access path do filter.
    project_restrictions = (
        await session.execute(
            select(EntityVisibility.entity_type, EntityVisibility.entity_id)
            .join(Team, Team.id == EntityVisibility.team_id)
            .where(Team.project_id == project_id)
            .distinct()
        )
    ).all()
    record_keys = {(kind, entity_id) for kind, entity_id in project_restrictions}

    all_rows: list[EntityVisibility] = []
    if record_keys:
        kinds = {kind for kind, _ in record_keys}
        ids = {entity_id for _, entity_id in record_keys}
        all_rows = list(
            (
                await session.execute(
                    select(EntityVisibility).where(
                        EntityVisibility.entity_type.in_(kinds),
                        EntityVisibility.entity_id.in_(ids),
                    )
                )
            )
            .scalars()
            .all()
        )

    rows_by_record: dict[tuple[str, str], list[EntityVisibility]] = defaultdict(list)
    for row in all_rows:
        key = (row.entity_type, row.entity_id)
        if key in record_keys:
            rows_by_record[key].append(row)

    restriction_counts: dict[uuid.UUID, int] = defaultdict(int)
    for rows in rows_by_record.values():
        for row in rows:
            if row.team_id in project_team_ids:
                restriction_counts[row.team_id] += 1

    for team in sorted(teams, key=lambda t: (t.sort_order, t.name)):
        snapshot.teams.append(
            TeamSnapshot(
                id=str(team.id),
                name=team.name,
                is_default=bool(team.is_default),
                is_active=bool(team.is_active),
                member_count=len(members_by_team.get(team.id, ())),
                restriction_count=restriction_counts.get(team.id, 0),
            )
        )

    for (kind, entity_id), rows in sorted(rows_by_record.items()):
        in_project = [r.team_id for r in rows if r.team_id in project_team_ids]
        foreign = [r.team_id for r in rows if r.team_id not in project_team_ids]
        viewers: set[uuid.UUID] = set()
        for team_id in in_project:
            viewers |= members_by_team.get(team_id, set())
        snapshot.restrictions.append(
            RestrictionSnapshot(
                entity_type=kind,
                entity_id=entity_id,
                in_project_team_ids=[str(t) for t in in_project],
                foreign_team_ids=[str(t) for t in foreign],
                viewer_count=len(viewers),
            )
        )

    today = datetime.now(UTC).date()
    roster_rows = list(
        (await session.execute(select(RosterMember).where(RosterMember.project_id == project_id))).scalars().all()
    )
    snapshot.roster = [_roster_line(member, today) for member in roster_rows]
    rostered_user_ids = {str(member.user_id) for member in roster_rows if member.user_id}
    project_member_ids = {str(user_id) for members in members_by_team.values() for user_id in members}
    snapshot.unrostered_user_ids = sorted(project_member_ids - rostered_user_ids)

    await _collect_parties(session, project_id, snapshot, project_member_ids)
    return snapshot


async def _collect_parties(
    session: AsyncSession,
    project_id: uuid.UUID,
    snapshot: ProjectTeamsSnapshot,
    project_member_ids: set[str],
) -> None:
    """Add the party configuration of one project to the snapshot."""
    from app.modules.projects.models import Project

    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    snapshot.party_count = len(
        (await session.execute(select(ProjectParty.id).where(ProjectParty.project_id == project_id))).all()
    )
    bound = [
        str(user_id)
        for (user_id,) in (
            await session.execute(select(ProjectPartyMember.user_id).where(ProjectPartyMember.project_id == project_id))
        ).all()
    ]
    snapshot.bound_member_count = len(bound)
    owner = str(owner_id) if owner_id is not None else None
    snapshot.owner_bound = owner is not None and owner in bound
    snapshot.bound_without_access_user_ids = sorted(u for u in bound if u != owner and u not in project_member_ids)
    snapshot.foreign_party_record_count = len(
        (
            await session.execute(
                select(PartyRecordAccess.id)
                .join(ProjectParty, ProjectParty.id == PartyRecordAccess.party_id)
                .where(PartyRecordAccess.project_id == project_id, ProjectParty.project_id != project_id)
            )
        ).all()
    )


# ── Context helpers ──────────────────────────────────────────────────────────


def _scope(context: ValidationContext) -> str:
    """The validation scope carried on the data."""
    data = context.data
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, str):
            return scope
    return ""


def _teams(context: ValidationContext) -> list[dict[str, Any]]:
    """The team snapshots on the context (or an empty list)."""
    data = context.data
    teams = data.get("teams") if isinstance(data, dict) else None
    return [t for t in teams if isinstance(t, dict)] if isinstance(teams, list) else []


def _restrictions(context: ValidationContext) -> list[dict[str, Any]]:
    """The restriction snapshots on the context (or an empty list)."""
    data = context.data
    rows = data.get("restrictions") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _roster(context: ValidationContext) -> list[dict[str, Any]]:
    """The roster snapshots on the context (or an empty list)."""
    data = context.data
    rows = data.get("roster") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _unrostered_user_ids(context: ValidationContext) -> list[str]:
    """Users with project access who are absent from the roster."""
    data = context.data
    rows = data.get("unrostered_user_ids") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, str)] if isinstance(rows, list) else []


def _parties(context: ValidationContext) -> dict[str, Any]:
    """The party configuration on the context (or an empty dict)."""
    data = context.data
    parties = data.get("parties") if isinstance(data, dict) else None
    return parties if isinstance(parties, dict) else {}


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


# ── Rules ────────────────────────────────────────────────────────────────────


class TeamsDefaultTeamPresent(ValidationRule):
    rule_id = "teams.default_team_present"
    name = "Project Has One Default Team"
    standard = "teams"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A project resolves 'add a member' through exactly one active default team."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        teams = _teams(context)
        if not teams:
            # A project with no teams at all has not been configured yet
            # rather than misconfigured; the first member add creates one.
            return []
        defaults = [t for t in teams if t.get("is_default") and t.get("is_active")]
        if len(defaults) == 1:
            return [_result(self, True, "OK", element_ref=str(defaults[0].get("id")))]
        if not defaults:
            return [
                _result(
                    self,
                    False,
                    "This project has no active default team, so adding a member has no team to put them on.",
                    suggestion="Mark one team as the default so project membership resolves to it.",
                    details={"default_count": 0, "team_count": len(teams)},
                )
            ]
        names = [str(t.get("name") or t.get("id")) for t in defaults]
        return [
            _result(
                self,
                False,
                (
                    f"{len(defaults)} teams are marked as the project default ({', '.join(names[:8])}), "
                    "so which one a new member lands on is arbitrary."
                ),
                suggestion="Leave exactly one team marked as the default.",
                details={"default_count": len(defaults), "team_names": names},
            )
        ]


class TeamsRestrictionHasViewer(ValidationRule):
    rule_id = "teams.restriction_has_viewer"
    name = "Restricted Record Still Has A Reader"
    standard = "teams"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A restricted record whose teams have no members is readable by nobody but the project owner."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        rows = _restrictions(context)
        if not rows:
            return []
        stranded = [r for r in rows if int(r.get("viewer_count") or 0) == 0]
        if not stranded:
            return [_result(self, True, "OK", details={"restricted_records": len(rows)})]
        return [
            _result(
                self,
                False,
                (
                    f"{r.get('entity_type')} {r.get('entity_id')} is restricted to teams that have no members, "
                    "so nobody but the project owner and system admins can open it."
                ),
                element_ref=f"{r.get('entity_type')}/{r.get('entity_id')}",
                suggestion="Add members to one of the named teams, or lift the restriction on this record.",
                details={
                    "entity_type": r.get("entity_type"),
                    "entity_id": r.get("entity_id"),
                    "team_ids": r.get("in_project_team_ids") or [],
                },
            )
            for r in stranded
        ]


class TeamsRestrictionScope(ValidationRule):
    rule_id = "teams.restriction_scope"
    name = "Restriction Names A Team Of This Project"
    standard = "teams"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A restriction naming a team outside the project is ignored on read, so it protects nothing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        rows = _restrictions(context)
        if not rows:
            return []
        mis_scoped = [r for r in rows if r.get("foreign_team_ids")]
        if not mis_scoped:
            return [_result(self, True, "OK", details={"restricted_records": len(rows)})]
        return [
            _result(
                self,
                False,
                (
                    f"{r.get('entity_type')} {r.get('entity_id')} carries "
                    f"{len(r.get('foreign_team_ids') or [])} restriction(s) naming a team outside this project; "
                    "those rows are ignored when this project's access is resolved."
                ),
                element_ref=f"{r.get('entity_type')}/{r.get('entity_id')}",
                suggestion="Remove the out-of-project rows and restrict the record to a team of this project.",
                details={
                    "entity_type": r.get("entity_type"),
                    "entity_id": r.get("entity_id"),
                    "foreign_team_ids": r.get("foreign_team_ids") or [],
                },
            )
            for r in mis_scoped
        ]


class TeamsEmptyTeam(ValidationRule):
    rule_id = "teams.empty_team"
    name = "Active Team Has Members"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An active team with no members grants nothing and only narrows what it is pointed at."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        teams = [t for t in _teams(context) if t.get("is_active")]
        if not teams:
            return []
        empty = [t for t in teams if int(t.get("member_count") or 0) == 0]
        if not empty:
            return [_result(self, True, "OK", details={"active_teams": len(teams)})]
        return [
            _result(
                self,
                False,
                (
                    f"Team '{t.get('name')}' has no members"
                    + (
                        f" but is named by {t.get('restriction_count')} restriction(s), which hides those records."
                        if int(t.get("restriction_count") or 0) > 0
                        else ", so it grants nobody anything."
                    )
                ),
                element_ref=str(t.get("id")),
                suggestion="Add the people this team represents, or deactivate the team.",
                details={
                    "team_id": t.get("id"),
                    "team_name": t.get("name"),
                    "restriction_count": t.get("restriction_count") or 0,
                },
            )
            for t in empty
        ]


class TeamsDuplicateTeamName(ValidationRule):
    rule_id = "teams.duplicate_team_name"
    name = "Active Team Names Are Distinct"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Two active teams sharing a name are indistinguishable in the picker that assigns restrictions."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        teams = [t for t in _teams(context) if t.get("is_active")]
        if not teams:
            return []
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for team in teams:
            by_name[str(team.get("name") or "").strip().casefold()].append(team)
        clashes = {name: rows for name, rows in by_name.items() if name and len(rows) > 1}
        if not clashes:
            return [_result(self, True, "OK", details={"active_teams": len(teams)})]
        return [
            _result(
                self,
                False,
                (
                    f"{len(rows)} active teams are called '{rows[0].get('name')}', so a restriction can be "
                    "pointed at the wrong one and still look right."
                ),
                element_ref=str(rows[0].get("id")),
                suggestion="Rename one of them so the picker shows which is which.",
                details={"name": rows[0].get("name"), "team_ids": [r.get("id") for r in rows]},
            )
            for rows in clashes.values()
        ]


class TeamsRestrictionEnforced(ValidationRule):
    rule_id = "teams.restriction_enforced"
    name = "Restriction Is Actually Enforced"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A restriction on a record kind no module subtracts yet is recorded but not enforced on read."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        rows = _restrictions(context)
        if not rows:
            return []
        enforced = enforced_entity_type_keys()
        # Group by kind: one finding per record kind, not per record, so a
        # project with 400 restricted drawings gets one line, not 400.
        unenforced: dict[str, int] = defaultdict(int)
        unknown: dict[str, int] = defaultdict(int)
        for row in rows:
            kind = str(row.get("entity_type") or "")
            if not is_known_entity_type(kind):
                unknown[kind] += 1
            elif kind not in enforced:
                unenforced[kind] += 1
        if not unenforced and not unknown:
            return [_result(self, True, "OK", details={"restricted_records": len(rows)})]
        results: list[RuleResult] = []
        for kind, count in sorted(unknown.items()):
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"{count} restriction(s) name the record kind '{kind}', which this platform no longer "
                        "publishes, so they are dead configuration and hide nothing."
                    ),
                    element_ref=kind,
                    suggestion="Remove these restrictions, or re-create them against a current record kind.",
                    details={"entity_type": kind, "count": count, "known": False},
                )
            )
        for kind, count in sorted(unenforced.items()):
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"{count} {kind} record(s) are marked restricted, but no module filters that record kind "
                        "on read yet, so the restriction is recorded rather than enforced."
                    ),
                    element_ref=kind,
                    suggestion="Treat these as an intention on record until the owning module adopts the filter.",
                    details={"entity_type": kind, "count": count, "known": True},
                )
            )
        return results


class TeamsRosterTicketValid(ValidationRule):
    rule_id = "teams.roster_ticket_valid"
    name = "Roster Tickets Are In Date"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Somebody on the roster is working on an expired ticket or competency."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        active = [r for r in _roster(context) if r.get("is_active")]
        if not active:
            return []
        lapsed = [r for r in active if r.get("expired_certifications")]
        if not lapsed:
            return [_result(self, True, "OK", details={"people": len(active)})]
        return [
            _result(
                self,
                False,
                (
                    f"{row.get('display_name')} is on the roster with an expired "
                    f"{', '.join(row.get('expired_certifications') or [])}"
                ),
                element_ref=str(row.get("id")),
                suggestion="Record the renewed ticket, or take the person off the roster until it is renewed.",
                details={
                    "roster_member_id": row.get("id"),
                    "display_name": row.get("display_name"),
                    "expired": row.get("expired_certifications") or [],
                },
            )
            for row in lapsed
        ]


class TeamsRosterWindow(ValidationRule):
    rule_id = "teams.roster_window"
    name = "Roster Dates Match Who Is Here"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An active roster line whose last day on the project has already passed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        active = [r for r in _roster(context) if r.get("is_active")]
        if not active:
            return []
        overdue = [r for r in active if r.get("window_ended")]
        if not overdue:
            return [_result(self, True, "OK", details={"people": len(active)})]
        return [
            _result(
                self,
                False,
                f"{row.get('display_name')} is still on the roster although their last day has passed",
                element_ref=str(row.get("id")),
                suggestion="Extend the end date if they are still here, otherwise mark the line as left.",
                details={
                    "roster_member_id": row.get("id"),
                    "display_name": row.get("display_name"),
                },
            )
            for row in overdue
        ]


class TeamsRosterSiteLead(ValidationRule):
    rule_id = "teams.roster_site_lead"
    name = "Roster Names Somebody In Charge"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A roster with nobody in a supervisory site role cannot say who runs the job."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        active = [r for r in _roster(context) if r.get("is_active")]
        if not active:
            # An empty roster has not been filled in yet rather than filled in
            # wrongly. The screen's own empty state is the right place to say so.
            return []
        supervisory = supervisory_site_role_keys()
        leads = [r for r in active if str(r.get("site_role") or "") in supervisory]
        if leads:
            return [_result(self, True, "OK", details={"lead_count": len(leads)})]
        return [
            _result(
                self,
                False,
                "Nobody on this roster holds a supervisory site role",
                suggestion="Give the project manager, site manager, superintendent or foreman their role.",
                details={"people": len(active)},
            )
        ]


class TeamsRosterCoversAccess(ValidationRule):
    rule_id = "teams.roster_covers_access"
    name = "Everybody With Access Is On The Roster"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Somebody holds access to this project but appears nowhere on its roster."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        if not _roster(context):
            # Nothing to reconcile against. Reporting every member as missing
            # from a roster nobody has started would be noise, not a finding.
            return []
        missing = _unrostered_user_ids(context)
        if not missing:
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                (
                    f"{len(missing)} person(s) can open this project but are not on the roster, "
                    f"so their name appears on records with no trade, firm or role behind it"
                ),
                suggestion="Add them to the roster, or take their project access away.",
                details={"user_ids": missing},
            )
        ]


class TeamsPartyMemberHasAccess(ValidationRule):
    rule_id = "teams.party_member_has_access"
    name = "Party Members Can Reach The Project"
    standard = "teams"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Every user bound to a project party is still a member of the project."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        parties = _parties(context)
        if not parties.get("bound_member_count"):
            return []
        stale = [u for u in parties.get("bound_without_access_user_ids", []) if isinstance(u, str)]
        if not stale:
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                f"{len(stale)} user(s) are bound to a party but are no longer members of the project.",
                suggestion="Unbind them from their party, or add them back to a project team.",
                details={"user_ids": stale[:50], "count": len(stale)},
            )
        ]


class TeamsPartyRecordScope(ValidationRule):
    rule_id = "teams.party_record_scope"
    name = "Shares Name Parties Of The Same Project"
    standard = "teams"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A shared-register row may only name a party of the record's own project."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        parties = _parties(context)
        if not parties.get("party_count"):
            return []
        count = int(parties.get("foreign_party_record_count") or 0)
        if count == 0:
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                f"{count} share(s) on this project's records name a party of another project.",
                suggestion="Remove those shares and share the records with a party of this project.",
                details={"count": count},
            )
        ]


class TeamsPartyHostDefined(ValidationRule):
    rule_id = "teams.party_host_defined"
    name = "Project Owner Belongs To A Party"
    standard = "teams"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "When members are bound to parties, the project owner is bound to the host party."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _scope(context) != "project_teams":
            return []
        parties = _parties(context)
        if not parties.get("bound_member_count"):
            return []
        if parties.get("owner_bound"):
            return [_result(self, True, "OK")]
        return [
            _result(
                self,
                False,
                "Members are bound to parties but the project owner is not, so every bound member is treated "
                "as external, including the owner's own colleagues.",
                suggestion="Bind the project owner to their company's party to make it the host party.",
            )
        ]


_TEAMS_RULES: tuple[ValidationRule, ...] = (
    TeamsDefaultTeamPresent(),
    TeamsRestrictionHasViewer(),
    TeamsRestrictionScope(),
    TeamsEmptyTeam(),
    TeamsDuplicateTeamName(),
    TeamsRestrictionEnforced(),
    TeamsRosterTicketValid(),
    TeamsRosterWindow(),
    TeamsRosterSiteLead(),
    TeamsRosterCoversAccess(),
    TeamsPartyMemberHasAccess(),
    TeamsPartyRecordScope(),
    TeamsPartyHostDefined(),
)


def register_teams_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import / hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    and explicitly from the test conftest because no test process runs
    startup hooks.
    """
    for rule in _TEAMS_RULES:
        rule_registry.register(rule, [TEAMS_RULE_SET])
    logger.debug("Registered %d teams validation rules", len(_TEAMS_RULES))


# ── Orchestration ────────────────────────────────────────────────────────────


def _to_finding(result: RuleResult) -> TeamsValidationFinding:
    """Render one failing rule result as a UI finding."""
    context: dict[str, Any] = dict(result.details or {})
    if result.element_ref:
        context["ref"] = result.element_ref
    if result.suggestion:
        context["suggestion"] = result.suggestion
    # Rule ids are already namespaced ("teams.empty_team"), so the raw id would
    # render "teams.validation.teams.empty_team". Drop the duplicated segment:
    # the translator sees "teams.validation.empty_team" and the rule_id field
    # still carries the unabridged id for anyone correlating with the registry.
    return TeamsValidationFinding(
        rule_id=result.rule_id,
        key=f"teams.validation.{result.rule_id.removeprefix('teams.')}",
        severity=result.severity.value,
        message=result.message,
        element_ref=result.element_ref,
        suggestion=result.suggestion,
        context=context,
    )


async def evaluate_project_teams(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> TeamsValidationReport:
    """Run the ``teams`` rule set over one project and return its findings.

    Access is the caller's responsibility - :meth:`TeamService.validate_project`
    gates it before calling here.

    A failure inside the engine degrades to a ``skipped`` report rather than a
    500: the validation banner is an aid, and losing it must not take the
    teams screen down with it. It never degrades to ``passed``, because
    "we could not check" and "we checked and it is fine" must not read alike.
    """
    try:
        snapshot = await collect_project_snapshot(session, project_id)
        report = await validation_engine.validate(
            data=snapshot.as_dict(),
            rule_sets=[TEAMS_RULE_SET],
            target_type="project_teams",
            target_id=str(project_id),
            project_id=str(project_id),
        )
    except Exception:  # noqa: BLE001 - validation augments, never breaks the screen
        logger.warning("teams validation failed for project %s", project_id, exc_info=True)
        return TeamsValidationReport(
            project_id=project_id,
            status=ValidationStatus.SKIPPED.value,
            score=None,
        )

    findings = [_to_finding(r) for r in report.results if not r.passed and not r.is_engine_error]
    score = report.score
    return TeamsValidationReport(
        project_id=project_id,
        status=report.status.value,
        # ``None`` when nothing was actually checked. Left as None rather than
        # coerced to 1.0, so "we did not check" never renders as a clean pass.
        score=None if score is None else float(score),
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        findings=findings,
    )
