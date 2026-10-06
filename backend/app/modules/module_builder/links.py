# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a link field may point at, and who may see what it points at.

A ``link`` field in a built module is a foreign key into a table another module
owns: a contract, a contact, a schedule activity, a document or a person. This
module is the one place that knows, for each of those, which table it is,
which column a person reads as its name, which project it belongs to, and how
its own module decides who may see a row.

That last part is the point. A link picker that listed every contract in the
database, or a list that printed the name of a document in a folder the reader
was never granted, would be a new way round access rules the owning module
already enforces. So every reading path here - the picker, the labels in a
list, the export, and the check on create and update - goes through one
function, :func:`visible`, which answers what the target's own list endpoint
would show this caller and nothing more.

The functions generated modules call (:func:`link_problems` and
:func:`labels_for`) are a contract with modules already installed on servers:
their code imports them by name. Their signatures only ever gain optional
arguments.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Most a picker returns at once. It is a search box, not a register.
MAX_LOOKUP = 50
# Most ids one labels call resolves; a list page is 500 rows at most.
MAX_LABELS = 500


@dataclass(frozen=True)
class LinkTargetDef:
    """One record type a link may point at."""

    target: str
    #: The manifest name of the module that owns the table.
    module: str
    #: Where its ORM model lives, and the class.
    models: str
    model: str
    #: The physical table the foreign key references.
    table: str
    #: What the caller needs to read it, as that module's own list route asks.
    permission: str
    #: Whether a row belongs to a project, directly or through its parent.
    project_scoped: bool
    #: The field name a suggested link gets when nothing better is known.
    field_name: str


LINK_TARGETS: dict[str, LinkTargetDef] = {
    "contract": LinkTargetDef(
        target="contract",
        module="oe_contracts",
        models="app.modules.contracts.models",
        model="Contract",
        table="oe_contracts_contract",
        permission="contracts.read",
        project_scoped=True,
        field_name="contract",
    ),
    "contact": LinkTargetDef(
        target="contact",
        module="oe_contacts",
        models="app.modules.contacts.models",
        model="Contact",
        table="oe_contacts_contact",
        permission="contacts.read",
        project_scoped=False,
        field_name="contact",
    ),
    "schedule_activity": LinkTargetDef(
        target="schedule_activity",
        module="oe_schedule",
        models="app.modules.schedule.models",
        model="Activity",
        table="oe_schedule_activity",
        permission="schedule.read",
        project_scoped=True,
        field_name="activity",
    ),
    "document": LinkTargetDef(
        target="document",
        module="oe_documents",
        models="app.modules.documents.models",
        model="Document",
        table="oe_documents_document",
        permission="documents.read",
        project_scoped=True,
        field_name="document",
    ),
    "user": LinkTargetDef(
        target="user",
        module="oe_users",
        models="app.modules.users.models",
        model="User",
        table="oe_users_user",
        # Not users.list: picking the person responsible for a record is not
        # browsing the user directory. Who may be picked is decided by shared
        # projects instead, see _people.
        permission="projects.read",
        project_scoped=False,
        field_name="responsible",
    ),
}


@dataclass(frozen=True)
class LinkedRecord:
    """A target row as a reader sees it."""

    id: uuid.UUID
    label: str
    sublabel: str | None
    project_id: uuid.UUID | None


@dataclass(frozen=True)
class Caller:
    user_id: uuid.UUID | None
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def available(target: str) -> bool:
    """Whether the module owning ``target`` is loaded in this process."""
    definition = LINK_TARGETS.get(target)
    if definition is None:
        return False
    from app.core.module_loader import module_loader

    return definition.module in module_loader.loaded_modules


async def caller_for(session: AsyncSession, user_id: object) -> Caller:
    """The caller's id and role, read from the database rather than a token."""
    from app.modules.users.repository import UserRepository

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return Caller(user_id=None, role="")
    user = await UserRepository(session).get_by_id(uid)
    if user is None or not getattr(user, "is_active", True):
        return Caller(user_id=None, role="")
    return Caller(user_id=uid, role=str(getattr(user, "role", "") or ""))


def may_read(caller: Caller, target: str) -> bool:
    """The target module's read permission, decided as ``RequirePermission`` decides it."""
    if caller.user_id is None:
        return False
    if caller.is_admin:
        return True
    from app.core.permissions import permission_registry

    return bool(permission_registry.role_has_permission(caller.role, LINK_TARGETS[target].permission))


def _model(target: str) -> Any:
    import importlib

    definition = LINK_TARGETS[target]
    return getattr(importlib.import_module(definition.models), definition.model)


async def visible(
    session: AsyncSession,
    caller: Caller,
    target: str,
    *,
    ids: Iterable[uuid.UUID] | None = None,
    project_id: uuid.UUID | None = None,
    query: str = "",
    limit: int = MAX_LOOKUP,
) -> list[LinkedRecord]:
    """The rows of ``target`` this caller may see, optionally narrowed.

    ``ids`` narrows to those rows, ``project_id`` to one project (the caller's
    access to it is the router's to check first) and ``query`` to a search.
    Rows the caller may not see are left out, never reported, so the answer
    for a row in someone else's project and for one that does not exist is
    the same: absent.
    """
    if target not in LINK_TARGETS or not may_read(caller, target):
        return []
    id_list = list(dict.fromkeys(ids)) if ids is not None else None
    if id_list is not None and not id_list:
        return []

    builder = _BUILDERS[target]
    stmt, label_of = builder(caller)

    model = _model(target)
    if id_list is not None:
        stmt = stmt.where(model.id.in_(id_list[:MAX_LABELS]))

    definition = LINK_TARGETS[target]
    if target == "user":
        stmt = await _people(session, caller, stmt, project_id)
    if definition.project_scoped:
        project_column = _project_column(target)
        if project_id is not None:
            stmt = stmt.where(project_column == project_id)
        elif not caller.is_admin:
            from app.dependencies import accessible_project_ids

            reachable = await accessible_project_ids(session, str(caller.user_id))
            if reachable is not None:
                stmt = stmt.where(project_column.in_(list(reachable)))

    text = (query or "").strip()
    if text:
        pattern = f"%{_escape_like(text)}%"
        stmt = stmt.where(or_(*(c.ilike(pattern, escape="\\") for c in _SEARCH_COLUMNS[target]())))

    if id_list is None:
        stmt = stmt.limit(max(1, min(limit, MAX_LOOKUP)) * (4 if target == "document" else 1))

    rows = (await session.execute(stmt)).all()
    records = [label_of(row) for row in rows]
    if target == "document" and not caller.is_admin:
        records = await _readable_documents(session, caller, rows, records)
    if id_list is None:
        records = records[: max(1, min(limit, MAX_LOOKUP))]
    return records


async def _people(session: AsyncSession, caller: Caller, stmt: Any, project_id: uuid.UUID | None) -> Any:
    """Narrow a user query to the people a caller may link.

    The rule, as decided for v1:

    - with ``project_id`` (the record's project, whose access the router has
      already checked), that project's owner and its team members;
    - without it, everyone who shares at least one project the caller can
      reach - owner or team member on either side;
    - an administrator is not narrowed, except by ``project_id`` when given.

    So an editor on project A never sees, picks or reads the name of someone
    who is only on project B.
    """
    from app.modules.users.models import User

    if project_id is not None:
        return stmt.where(User.id.in_(_people_of([project_id])))
    if caller.is_admin:
        return stmt
    from app.dependencies import accessible_project_ids

    reachable = await accessible_project_ids(session, str(caller.user_id))
    if reachable is None:
        return stmt
    return stmt.where(User.id.in_(_people_of(list(reachable))))


def _people_of(project_ids: list[uuid.UUID]) -> Any:
    """The ids of the owners and team members of these projects, as a subquery."""
    from sqlalchemy import union

    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    owners = select(Project.owner_id.label("user_id")).where(Project.id.in_(project_ids))
    members = (
        select(TeamMembership.user_id.label("user_id"))
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.project_id.in_(project_ids))
    )
    people = union(owners, members).subquery()
    return select(people.c.user_id)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _project_column(target: str) -> Any:
    if target == "schedule_activity":
        from app.modules.schedule.models import Schedule

        return Schedule.project_id
    return _model(target).project_id


def _contract_query(caller: Caller) -> tuple[Any, Any]:
    from app.modules.contracts.models import Contract

    stmt = select(Contract.id, Contract.title, Contract.code, Contract.project_id).order_by(Contract.code)

    def label(row: Any) -> LinkedRecord:
        title = (row.title or "").strip()
        code = (row.code or "").strip()
        return LinkedRecord(
            id=row.id, label=title or code or str(row.id), sublabel=code if title else None, project_id=row.project_id
        )

    return stmt, label


def _contact_query(caller: Caller) -> tuple[Any, Any]:
    from app.modules.contacts.models import Contact

    stmt = (
        select(
            Contact.id,
            Contact.company_name,
            Contact.first_name,
            Contact.last_name,
            Contact.primary_email,
        )
        .where(Contact.is_active.is_(True))
        .order_by(Contact.company_name, Contact.last_name)
    )
    if not caller.is_admin:
        # The contacts module's own tenant rule (contacts/router.py, list and
        # export): a contact is the caller's when its tenant is the caller, or,
        # for rows from before tenants, when the caller created it.
        mine = str(caller.user_id)
        stmt = stmt.where(or_(Contact.tenant_id == mine, and_(Contact.tenant_id.is_(None), Contact.created_by == mine)))

    def label(row: Any) -> LinkedRecord:
        person = " ".join(p for p in ((row.first_name or "").strip(), (row.last_name or "").strip()) if p)
        company = (row.company_name or "").strip()
        main = company or person or (row.primary_email or "") or str(row.id)
        detail = person if company and person else (row.primary_email or None)
        return LinkedRecord(id=row.id, label=main, sublabel=detail, project_id=None)

    return stmt, label


def _activity_query(caller: Caller) -> tuple[Any, Any]:
    from app.modules.schedule.models import Activity, Schedule

    stmt = (
        select(Activity.id, Activity.name, Activity.wbs_code, Schedule.project_id)
        .join(Schedule, Schedule.id == Activity.schedule_id)
        .order_by(Activity.wbs_code, Activity.name)
    )

    def label(row: Any) -> LinkedRecord:
        return LinkedRecord(
            id=row.id,
            label=(row.name or "").strip() or str(row.id),
            sublabel=(row.wbs_code or "").strip() or None,
            project_id=row.project_id,
        )

    return stmt, label


def _document_query(caller: Caller) -> tuple[Any, Any]:
    from app.modules.documents.models import Document

    stmt = select(Document.id, Document.name, Document.category, Document.project_id).order_by(Document.name)

    def label(row: Any) -> LinkedRecord:
        return LinkedRecord(
            id=row.id,
            label=(row.name or "").strip() or str(row.id),
            sublabel=(row.category or "").strip() or None,
            project_id=row.project_id,
        )

    return stmt, label


def _user_query(caller: Caller) -> tuple[Any, Any]:
    from app.modules.users.models import User

    stmt = (
        select(User.id, User.full_name, User.email)
        .where(User.is_active.is_(True), User.deleted_at.is_(None))
        .order_by(User.full_name, User.email)
    )

    def label(row: Any) -> LinkedRecord:
        name = (row.full_name or "").strip()
        return LinkedRecord(id=row.id, label=name or row.email, sublabel=row.email if name else None, project_id=None)

    return stmt, label


def _search_contract() -> list[Any]:
    from app.modules.contracts.models import Contract

    return [Contract.title, Contract.code]


def _search_contact() -> list[Any]:
    from app.modules.contacts.models import Contact

    return [Contact.company_name, Contact.first_name, Contact.last_name, Contact.primary_email]


def _search_activity() -> list[Any]:
    from app.modules.schedule.models import Activity

    return [Activity.name, Activity.wbs_code]


def _search_document() -> list[Any]:
    from app.modules.documents.models import Document

    return [Document.name]


def _search_user() -> list[Any]:
    from app.modules.users.models import User

    return [User.full_name, User.email]


_BUILDERS = {
    "contract": _contract_query,
    "contact": _contact_query,
    "schedule_activity": _activity_query,
    "document": _document_query,
    "user": _user_query,
}

_SEARCH_COLUMNS = {
    "contract": _search_contract,
    "contact": _search_contact,
    "schedule_activity": _search_activity,
    "document": _search_document,
    "user": _search_user,
}


async def _readable_documents(
    session: AsyncSession, caller: Caller, rows: list[Any], records: list[LinkedRecord]
) -> list[LinkedRecord]:
    """Drop documents in folders the caller is not granted.

    The documents module's own list route applies this rule (documents/router.py,
    ``list_documents``): a project owner sees everything; a member sees a
    document unless its folder carries grants and none of them covers the
    member. Decided per project, with the same helpers that route uses.
    """
    from app.modules.documents.folder_permissions_service import (
        effective_permissions_for,
        is_project_owner,
        kind_and_path_for_document,
        restricted_scopes_for_project,
    )

    decided: dict[uuid.UUID, tuple[bool, dict, set]] = {}
    kept: list[LinkedRecord] = []
    for row, record in zip(rows, records, strict=True):
        project = row.project_id
        if project not in decided:
            owner = await is_project_owner(session, project, caller.user_id)
            grants = (
                {} if owner else await effective_permissions_for(session, project_id=project, user_id=caller.user_id)
            )
            restricted = set() if owner else await restricted_scopes_for_project(session, project)
            decided[project] = (owner, grants, restricted)
        owner, grants, restricted = decided[project]
        if owner:
            kept.append(record)
            continue
        kind, path = kind_and_path_for_document(row.category)
        unrestricted = (kind, path) not in restricted and (kind, None) not in restricted
        granted = (kind, path) in grants or (kind, None) in grants
        if unrestricted or granted:
            kept.append(record)
    return kept


# ── What generated modules call ─────────────────────────────────────────────


LINK_OUTSIDE_PROJECT = "link_outside_project"
LINK_NOT_FOUND = "link_not_found"


async def link_problems(
    session: AsyncSession,
    user_id: object,
    record_project_id: uuid.UUID | None,
    links: Mapping[str, tuple[str, uuid.UUID | None]],
) -> list[tuple[str, str, str]]:
    """Why the links a record is about to carry cannot be written, if they cannot.

    ``links`` maps a field name to ``(target, value)``. Returns one
    ``(field, code, message)`` per refused link: ``link_not_found`` when the
    target is missing or not the caller's to see, which are deliberately the
    same answer, and ``link_outside_project`` when a project-scoped record
    points at a project-scoped target in another project.
    """
    caller = await caller_for(session, user_id)
    problems: list[tuple[str, str, str]] = []
    for field, (target, value) in links.items():
        if value is None:
            continue
        found = await visible(session, caller, target, ids=[value])
        if not found:
            problems.append((field, LINK_NOT_FOUND, "The linked record does not exist or is not yours to see."))
            continue
        definition = LINK_TARGETS[target]
        if record_project_id is not None and definition.project_scoped and found[0].project_id != record_project_id:
            problems.append((field, LINK_OUTSIDE_PROJECT, "The linked record belongs to a different project."))
        elif (
            record_project_id is not None
            and target == "user"
            and not await visible(session, caller, target, ids=[value], project_id=record_project_id)
        ):
            # A person is "in" a project as its owner or a team member.
            problems.append((field, LINK_OUTSIDE_PROJECT, "This person is not on the record's project."))
    return problems


async def labels_for(
    session: AsyncSession,
    user_id: object,
    target: str,
    ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Readable names for the ids the caller may see; the others are left out.

    Asked :data:`MAX_LABELS` ids at a time, because :func:`visible` names at
    most that many per call and an export holds up to 10,000 rows.
    """
    caller = await caller_for(session, user_id)
    wanted = list(dict.fromkeys(ids))
    named: dict[uuid.UUID, str] = {}
    for start in range(0, len(wanted), MAX_LABELS):
        chunk = wanted[start : start + MAX_LABELS]
        named.update((r.id, r.label) for r in await visible(session, caller, target, ids=chunk))
    return named
