# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The people of a project, as the actions name them: an assignee, an RFI's addressee, a risk owner.

A person is given by name and is resolved to a project member (the owner or
anyone on one of the project's teams) only when exactly one matches.
Otherwise the field stays empty and a note says so, because naming the wrong
person sends that person a notification. On the card the field is a list of
the project's members, so the person picks one rather than retyping a name;
the pick arrives as the member's id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.modules.erp_chat.actions.base import FieldErrors, coerce_uuid, make_field, make_note, parse_text
from app.modules.erp_chat.schemas import ActionField, ActionFieldOption, ActionNote

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

Member = tuple[uuid.UUID, str, str]

# Up to this many members a person is picked from a list; above it, typed.
MAX_MEMBER_OPTIONS = 200


async def project_members(session: AsyncSession, project_id: uuid.UUID) -> list[Member]:
    """``(id, full_name, email)`` of the project owner and every active team member."""
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    ids: set[uuid.UUID] = set()
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is not None:
        ids.add(owner_id)
    member_stmt = (
        select(TeamMembership.user_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id == project_id)
    )
    ids.update(uid for uid in (await session.execute(member_stmt)).scalars().all() if uid is not None)
    if not ids:
        return []
    stmt = (
        select(User.id, User.full_name, User.email)
        .where(User.id.in_(ids), User.is_active.is_(True))
        .order_by(User.full_name)
    )
    return [(uid, str(name or ""), str(email or "")) for uid, name, email in (await session.execute(stmt)).all()]


def display_name(full_name: str, email: str) -> str:
    """How a person is named on a card: full name, else the e-mail."""
    return full_name.strip() or email.strip()


def member_options(members: list[Member]) -> list[ActionFieldOption]:
    """The members as choices of a person field; two people with one name are told apart by e-mail."""
    names = [display_name(full, email) for _, full, email in members]
    counts: dict[str, int] = {}
    for name in names:
        counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    options = []
    for (uid, _, email), name in zip(members, names, strict=True):
        label = f"{name} ({email})" if counts[name.casefold()] > 1 and email and email != name else name
        options.append(ActionFieldOption(value=str(uid), label=label))
    return options


def match_members(needle: str, members: list[Member]) -> list[Member]:
    """Members matching a typed name, exact matches first.

    Exact: the full name or the whole e-mail, ignoring case. Only when nothing
    matches exactly: the e-mail's local part, or every typed word being the
    start of some word of the full name ("anna" and "anna s" both find "Anna
    Schmidt"). The local part is deliberately not an exact match: "anna" must
    stay ambiguous between Anna Schmidt (anna@...) and Anna Berg, because
    picking one of them silently would notify the wrong person.
    """
    typed = needle.strip().lower()
    if not typed:
        return []
    exact = [m for m in members if typed in {m[1].strip().lower(), m[2].strip().lower()}]
    if exact:
        return exact
    words = typed.split()
    partial = []
    for member in members:
        name_words = member[1].lower().split()
        by_name = bool(name_words) and all(any(nw.startswith(w) for nw in name_words) for w in words)
        by_mail = bool(member[2]) and member[2].split("@", 1)[0].lower() == typed
        if by_name or by_mail:
            partial.append(member)
    return partial


@dataclass
class MemberPick:
    """The person a field resolved to: an id and a name when exactly one member matched."""

    member_id: uuid.UUID | None = None
    name: str | None = None
    typed: str | None = None
    notes: list[ActionNote] = field(default_factory=list)

    @property
    def shown(self) -> str | None:
        """What the payload keeps as the person's name: the member's, else what was typed."""
        return self.name or self.typed


def merge_member_patch(payload: dict[str, Any], patch: dict[str, Any], *, key: str, id_key: str) -> dict[str, Any]:
    """A new name in ``key`` is resolved again; a picked member id in ``id_key`` is taken as given."""
    merged = {**payload, **patch}
    if key in patch and id_key not in patch:
        merged.pop(id_key, None)
    return merged


def resolve_member(
    args: dict[str, Any],
    members: list[Member],
    errors: FieldErrors,
    *,
    key: str,
    id_key: str,
    unmatched_note: str = "member_unmatched",
    ambiguous_note: str = "member_ambiguous",
) -> MemberPick:
    """Resolve the person named in ``args[key]`` (or picked by id in ``args[id_key]``) to a project member.

    ``id_key`` present - a stored payload or a member picked on the card - is
    taken as the id, but only a member's id. A value of ``key`` that is an id
    is a pick from the card's list. A typed name resolves only when exactly one
    member matches; otherwise the field stays empty and a warning note under it
    says why. An id that is not a member's is a field error, never a silent drop.
    """
    typed = parse_text(args, key, errors, max_length=255)
    pick = MemberPick(typed=typed)
    if id_key in args:
        raw = args.get(id_key)
        pick.member_id = coerce_uuid(raw)
        if raw not in (None, "") and pick.member_id is None:
            errors.add(key, "invalid_id")
    elif typed and coerce_uuid(typed) is not None:
        pick.member_id = coerce_uuid(typed)
    elif typed:
        matches = match_members(typed, members)
        if len(matches) == 1:
            pick.member_id = matches[0][0]
    if pick.member_id is not None:
        member = next((m for m in members if m[0] == pick.member_id), None)
        if member is None:
            errors.add(key, "invalid_id")
            pick.member_id = None
        else:
            pick.name = display_name(member[1], member[2])
    if typed and pick.member_id is None and key not in errors.errors:
        ambiguous = len(match_members(typed, members)) > 1
        pick.notes.append(
            make_note(
                ambiguous_note if ambiguous else unmatched_note,
                params={"name": typed},
                field_key=key,
                tone="warning",
            )
        )
    return pick


def member_field(key: str, members: list[Member], pick: MemberPick) -> ActionField:
    """A pick list of the project's members, so the person chooses rather than retypes a name.

    A project with more members than a list can usefully show keeps a text
    field, where a typed name is matched the same way the model's is.
    """
    if len(members) <= MAX_MEMBER_OPTIONS:
        return make_field(
            key,
            "enum",
            str(pick.member_id) if pick.member_id else None,
            editable=True,
            options=member_options(members),
        )
    return make_field(key, "text", pick.name, editable=True)
