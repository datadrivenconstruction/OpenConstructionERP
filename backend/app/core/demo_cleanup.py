# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Find, and on request remove, demo rows the boot seeding wrote into real projects.

Up to 18.2 the boot enrichment handed every project in the database to a set
of demo seeders, so a real project that had not reached a module yet received
that module's demo records on the next restart or upgrade. The gate that stops
it now lives in ``app.core.demo_enrichment``; this module is for installs that
ran the old code.

Only projects WITHOUT the ``demo_id`` marker are searched, and inside them a
row is taken only when it is provably the seed's, in one of two ways:

* It carries the seeder's own mark, one no person or API write produces:
  ``metadata_["seed"]`` on a diary, ``{"seed": true, "demo": true}`` on a bid
  package, photo, accommodation or element group, ``created_by="demo-seed"`` on
  a clash run, ``metadata_["source"]="service_demo_seed"`` on a recurring
  service schedule.
* Its content is exactly what the seeder writes. The seeders of quality plans,
  rosters, HSE registers, variations, service contracts, field timesheets and
  the diary's weather, drone and reality-capture rows left no mark, so each of
  them exposes a recogniser that compares several fields of a row at once with
  the constants the seeder itself writes from. The fingerprint lives next to
  the seed and reads the same constants, so the two cannot drift apart, and a
  single matching title is never enough.

A row that is the seed's but that somebody has worked on since is kept and
reported instead of removed: one changed well after the seed run that wrote it
(:data:`EDITED_AFTER`), and a quality plan a person has recorded an inspection
against.

Company-wide rows the seed wrote (the PPE register, the service SLA tiers,
checklists and customers, the contacts of a removed demo) belong to no project.
They are removed only when no demo project is left installed, because while
one is they are part of that demo, and a tier or customer still used by a
person's contract stays.

The default is a dry run that lists what it would remove, project by project.
Nothing is written unless ``apply=True``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_marker import demo_id_of, live_demo_projects

logger = logging.getLogger(__name__)

# How long after the seed run a row may still have been written by it. Seeders
# move their own rows on (a timesheet is approved, an inspection passed) within
# the same run, seconds after writing them; a person's edit comes later.
EDITED_AFTER = timedelta(minutes=10)

# The fields a listed row is named by, in order of preference.
_CODE_FIELDS = ("code", "contract_number", "permit_number", "reference", "sheet_number", "asset_tag", "serial")
_TITLE_FIELDS = (
    "title",
    "name",
    "display_name",
    "task_description",
    "item_description",
    "control_point_name",
    "recipient_name",
    "company_name",
    "description",
    "notes",
    "diary_date",
    "captured_at",
    "flown_at",
)


def _meta(row: Any) -> dict:
    value = getattr(row, "metadata_", None)
    return value if isinstance(value, dict) else {}


def _seed_and_demo(row: Any) -> bool:
    meta = _meta(row)
    return meta.get("seed") is True and meta.get("demo") is True


def _diary_seed(row: Any) -> bool:
    # ``True`` from the generic seeder, the seeder's name from the German one.
    seed = _meta(row).get("seed")
    return seed is True or seed == "daily_diary_showcase_de"


@dataclass
class _Rule:
    """One seeded model and the mark that proves a row of it came from the seed."""

    name: str
    model: Callable[[], Any]
    is_seeded: Callable[[Any], bool]
    # Rows that point at a removed parent without a cascading foreign key.
    orphans: Callable[[], list[tuple[Any, str]]] = field(default=lambda: [])


def _marker_rules() -> list[_Rule]:
    def diary():
        from app.modules.daily_diary.models import DailyDiary

        return DailyDiary

    def diary_orphans():
        # Photo and video rows keep their project and set ``diary_id`` NULL when
        # the diary goes, so they would stay behind in the real project.
        from app.modules.daily_diary.models import DiaryPhoto, DiaryVideo

        return [(DiaryPhoto, "diary_id"), (DiaryVideo, "diary_id")]

    def bid_package():
        from app.modules.bid_management.models import BidPackage

        return BidPackage

    def photo():
        from app.modules.documents.models import ProjectPhoto

        return ProjectPhoto

    def accommodation():
        from app.modules.accommodation.models import Accommodation

        return Accommodation

    def element_group():
        from app.modules.bim_hub.models import BIMElementGroup

        return BIMElementGroup

    def clash_run():
        from app.modules.clash.models import ClashRun

        return ClashRun

    def recurring():
        from app.modules.service.models import ServiceRecurringSchedule

        return ServiceRecurringSchedule

    return [
        _Rule("daily_diary", diary, _diary_seed, diary_orphans),
        _Rule("bid_management", bid_package, _seed_and_demo),
        _Rule("photos", photo, _seed_and_demo),
        _Rule("accommodation", accommodation, _seed_and_demo),
        _Rule("bim_element_groups", element_group, _seed_and_demo),
        _Rule("clash", clash_run, lambda r: getattr(r, "created_by", None) == "demo-seed"),
        _Rule(
            "service_recurring",
            recurring,
            lambda r: _meta(r).get("source") == "service_demo_seed",
        ),
    ]


def _fingerprinters() -> list[Callable[[AsyncSession, list[uuid.UUID]], Awaitable[list[tuple[type, list, str]]]]]:
    """Each unmarked seeder's own recogniser, in the order their rows can be deleted.

    Field time goes before variations because its lines point at variation
    orders; everything else is independent of the others.
    """
    from app.modules.field_time.seed import seeded_row_ids as field_time
    from app.modules.hse_advanced.seed import seeded_row_ids as hse
    from app.modules.qms.seed import seeded_row_ids as qms
    from app.modules.service.seed import seeded_row_ids as service
    from app.modules.teams.seed import seeded_row_ids as teams
    from app.modules.variations.seed import seeded_row_ids as variations

    return [field_time, variations, qms, hse, service, teams]


@dataclass
class LeftoverRow:
    """One row the seed wrote, named the way a person finds it on screen."""

    group: str
    module: str
    table: str
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_name: str
    title: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "module": self.module,
            "table": self.table,
            "id": str(self.id),
            "project_id": str(self.project_id) if self.project_id else None,
            "project_name": self.project_name,
            "title": self.title,
        }


@dataclass
class KeptRow(LeftoverRow):
    """A row that is the seed's but is left in place, and why."""

    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {**super().as_dict(), "reason": self.reason}


@dataclass
class CleanupReport:
    """What a pass found in real projects, what it removed, and what it kept."""

    real_projects: int = 0
    applied: bool = False
    # group name -> ids of the rows proven to be the seed's (removed when ``applied``)
    rows: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    found: list[LeftoverRow] = field(default_factory=list)
    kept: list[KeptRow] = field(default_factory=list)
    # Why the company-wide rows (PPE, service tiers and customers) were left alone, when they were.
    ppe_kept_reason: str = ""

    @property
    def marked(self) -> dict[str, int]:
        return {name: len(ids) for name, ids in self.rows.items()}

    @property
    def total(self) -> int:
        return sum(len(ids) for ids in self.rows.values())

    def by_project(self) -> dict[str, list[LeftoverRow]]:
        """Listed rows grouped by project name, company-wide ones under an empty name."""
        out: dict[str, list[LeftoverRow]] = {}
        for row in sorted(self.found, key=lambda r: (r.project_name, r.module, r.table, r.title)):
            out.setdefault(row.project_name, []).append(row)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "real_projects": self.real_projects,
            "applied": self.applied,
            "total": self.total,
            "groups": self.marked,
            "rows": [r.as_dict() for r in self.found],
            "kept": [r.as_dict() for r in self.kept],
            "company_rows_kept_reason": self.ppe_kept_reason,
        }


@dataclass
class _Group:
    label: str
    model: Any
    ids: list[uuid.UUID]
    orphans: list[tuple[Any, str]] = field(default_factory=list)


async def _real_projects(session: AsyncSession) -> dict[uuid.UUID, str]:
    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.name, Project.metadata_))).all()
    return {pid: str(name or "") for pid, name, meta in rows if not demo_id_of(meta)}


def _module_of(model: Any) -> str:
    parts = model.__module__.split(".")
    return parts[2] if len(parts) > 2 and parts[1] == "modules" else parts[-1]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return " ".join(str(value).split())


def _title_of(row: Any) -> str:
    code = next((t for f in _CODE_FIELDS if (t := _text(getattr(row, f, None)))), "")
    title = next((t for f in _TITLE_FIELDS if (t := _text(getattr(row, f, None)))), "")
    name = f"{code} - {title}" if code and title and code != title else (code or title or str(row.id))
    return name if len(name) <= 120 else name[:117] + "..."


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _edited_ids(rows: list[Any]) -> set[uuid.UUID]:
    """Rows of one group changed well after the seed run that wrote them.

    The run's time is the earliest change in the group, per project: every row
    of a group is written in one run, and a person edits one or two of them
    later. A group of one has nothing to compare with, and falls back to the
    row's own creation time.
    """
    by_project: dict[Any, list[Any]] = {}
    for row in rows:
        by_project.setdefault(getattr(row, "project_id", None), []).append(row)
    edited: set[uuid.UUID] = set()
    for group in by_project.values():
        stamps = [u for r in group if (u := _aware(getattr(r, "updated_at", None)))]
        run_end = min(stamps) if len(stamps) > 1 else None
        for row in group:
            updated = _aware(getattr(row, "updated_at", None))
            created = _aware(getattr(row, "created_at", None))
            if updated is None or created is None or updated - created <= EDITED_AFTER:
                continue
            if run_end is None or updated - run_end > EDITED_AFTER:
                edited.add(row.id)
    return edited


async def _qms_plans_in_use(session: AsyncSession, plan_ids: list, seeded_inspections: list) -> set[uuid.UUID]:
    """Seeded quality plans a person has recorded an inspection against."""
    from app.modules.qms.models import ITPItem, QMSInspection

    if not plan_ids:
        return set()
    stmt = (
        select(ITPItem.itp_plan_id)
        .join(QMSInspection, QMSInspection.itp_item_id == ITPItem.id)
        .where(ITPItem.itp_plan_id.in_(plan_ids))
    )
    if seeded_inspections:
        stmt = stmt.where(QMSInspection.id.not_in(list(seeded_inspections)))
    return {r[0] for r in (await session.execute(stmt)).all()}


async def _project_groups(session: AsyncSession, real: list[uuid.UUID]) -> list[_Group]:
    from app.modules.daily_diary.seed import seeded_child_ids

    groups: list[_Group] = []
    diary_ids: list[uuid.UUID] = []
    for rule in _marker_rules():
        model = rule.model()
        rows = (await session.execute(select(model).where(model.project_id.in_(real)))).scalars().all()
        ids = [row.id for row in rows if rule.is_seeded(row)]
        if rule.name == "daily_diary":
            diary_ids = ids
        groups.append(_Group(rule.name, model, ids, rule.orphans()))
    for model, ids, label in await seeded_child_ids(session, real, diary_ids):
        groups.append(_Group(label, model, ids))
    for fingerprint in _fingerprinters():
        for model, ids, label in await fingerprint(session, real):
            groups.append(_Group(label, model, ids))
    return groups


async def _company_groups(session: AsyncSession, removed: dict[str, list[uuid.UUID]]) -> tuple[list[_Group], list]:
    """Company-wide seed rows, and the ones a person's work still uses (with the reason)."""
    from app.modules.contacts.models import Contact
    from app.modules.hse_advanced.models import PPEIssue
    from app.modules.hse_advanced.seed import seeded_ppe_ids
    from app.modules.service.models import ServiceContract
    from app.modules.service.seed import seeded_global_ids

    groups = [_Group("hse_ppe_issues", PPEIssue, await seeded_ppe_ids(session))]

    # A contract that stays keeps its tier and its customer.
    gone = set(removed.get("service_contracts", []))
    staying = [
        r
        for r in (
            await session.execute(
                select(ServiceContract.id, ServiceContract.sla_definition_id, ServiceContract.customer_id)
            )
        ).all()
        if r.id not in gone
    ]
    in_use = {r.sla_definition_id for r in staying} | {r.customer_id for r in staying}
    held: list[tuple[Any, uuid.UUID, str]] = []
    for model, ids, label in await seeded_global_ids(session):
        free = [i for i in ids if i not in in_use]
        held += [(model, i, "a service contract that stays uses it") for i in ids if i in in_use]
        groups.append(_Group(label, model, free))

    # Contacts an installer wrote for a demo that is no longer installed.
    live = {did for _pid, did in await live_demo_projects(session)}
    tagged = [
        r.id
        for r in (await session.execute(select(Contact.id, Contact.metadata_))).all()
        if (did := demo_id_of(r.metadata_)) and did not in live
    ]
    groups.append(_Group("demo_contacts", Contact, tagged))
    return groups, held


async def _describe(
    session: AsyncSession, group: _Group, names: dict[uuid.UUID, str]
) -> tuple[list[LeftoverRow], set[uuid.UUID]]:
    """Name each row of ``group`` and find the ones edited since the seed wrote them."""
    if not group.ids:
        return [], set()
    rows = (await session.execute(select(group.model).where(group.model.id.in_(group.ids)))).scalars().all()
    listed = [
        LeftoverRow(
            group=group.label,
            module=_module_of(group.model),
            table=group.model.__tablename__,
            id=row.id,
            project_id=getattr(row, "project_id", None),
            project_name=names.get(getattr(row, "project_id", None), ""),
            title=_title_of(row),
        )
        for row in rows
    ]
    return listed, _edited_ids(list(rows))


async def clean_leaked_demo_rows(
    session: AsyncSession,
    *,
    apply: bool = False,
    only_ids: Iterable[uuid.UUID | str] | None = None,
) -> CleanupReport:
    """Report, and with ``apply`` delete, the seed's rows in real projects.

    Flushes but does not commit; the caller commits, so a dry run followed by a
    rollback leaves the database exactly as it was. Groups are deleted in the
    order they are listed, children before the rows they point at.

    Args:
        session: Session to read and write through.
        apply: Delete what was found. ``False`` (the default) only lists it.
        only_ids: Delete no row outside these, the ones a person saw in a
            preview. A row that no longer matches the seed is not deleted
            even when it is named here. ``None`` means every row found.
    """
    report = CleanupReport(applied=apply)
    names = await _real_projects(session)
    real = list(names)
    report.real_projects = len(real)
    allowed = {uuid.UUID(str(i)) for i in only_ids} if only_ids is not None else None

    groups = await _project_groups(session, real) if real else []
    held: list[tuple[Any, uuid.UUID, str]] = []
    listed: dict[uuid.UUID, LeftoverRow] = {}

    async def settle(batch: list[_Group]) -> None:
        # Name every row, and keep the ones somebody changed since the seed.
        for group in batch:
            rows, edited = await _describe(session, group, names)
            for row in rows:
                listed[row.id] = row
                if row.id in edited:
                    report.kept.append(KeptRow(**vars(row), reason="changed after the seed wrote it"))
            group.ids = [r.id for r in rows if r.id not in edited]

    await settle(groups)

    # A plan a person inspected against stays, with its control points.
    for group in groups:
        if group.label == "qms_itp_plans":
            seeded_inspections = next((g.ids for g in groups if g.label == "qms_inspections"), [])
            used = await _qms_plans_in_use(session, group.ids, seeded_inspections)
            held += [(group.model, i, "a person recorded an inspection against it") for i in group.ids if i in used]
            group.ids = [i for i in group.ids if i not in used]

    if await live_demo_projects(session):
        report.ppe_kept_reason = "demo projects are still installed; the company-wide seed rows belong to them"
    else:
        company, company_held = await _company_groups(session, {g.label: g.ids for g in groups})
        await settle(company)
        groups += company
        held += company_held

    for model, row_id, reason in held:
        rows, _ = await _describe(session, _Group("", model, [row_id]), names)
        report.kept += [KeptRow(**vars(r), reason=reason) for r in rows]

    for group in groups:
        if allowed is not None:
            group.ids = [i for i in group.ids if i in allowed]
        report.rows[group.label] = list(group.ids)
        report.found += [replace(listed[i], group=group.label) for i in group.ids]

    if apply:
        for group in groups:
            if not group.ids:
                continue
            try:
                async with session.begin_nested():
                    for child, column in group.orphans:
                        await session.execute(delete(child).where(getattr(child, column).in_(group.ids)))
                    await session.execute(delete(group.model).where(group.model.id.in_(group.ids)))
            except IntegrityError:
                # Something outside the seed still points at these rows.
                logger.warning(
                    "demo cleanup: kept %d %s row(s) still referenced elsewhere", len(group.ids), group.label
                )
                for row in [r for r in report.found if r.group == group.label]:
                    report.kept.append(KeptRow(**vars(row), reason="other records still point at it"))
                report.found = [r for r in report.found if r.group != group.label]
                report.rows[group.label] = []
                continue
            logger.info("demo cleanup: removed %d seeded %s row(s) from real projects", len(group.ids), group.label)
        await session.flush()
        session.expire_all()
    return report
