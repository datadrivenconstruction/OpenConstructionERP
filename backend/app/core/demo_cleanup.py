# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Find, and on request remove, demo rows the boot seeding wrote into real projects.

Up to 18.2 the boot enrichment handed every project in the database to a set
of demo seeders, so a real project that had not reached a module yet received
that module's demo records on the next restart or upgrade. The gate that stops
it now lives in ``app.core.demo_enrichment``; this module is for installs that
ran the old code.

A row is removed only when both of these hold:

* it sits in a project WITHOUT the ``demo_id`` marker (a real project), and
* it carries the seeder's own mark, the one no person or API write produces:
  ``metadata_["seed"]`` on a diary, ``{"seed": true, "demo": true}`` on a bid
  package, photo, accommodation or element group, ``created_by="demo-seed"`` on
  a clash run, ``metadata_["source"]="service_demo_seed"`` on a recurring
  service schedule.

Several seeders wrote rows that carry no mark at all: the quality plans with
their inspections, NCRs, punch items and audits, team rosters, field
timesheets, HSE registers, variation notices, service contracts and the
coordination federation. Those rows are indistinguishable from work a person
recorded, so they are only COUNTED here, as candidates to review by hand, and
never deleted. For the quality plan the count uses the seed's fixed content (a
plan named "Concrete pour - slab on grade" under "WBS.03.30", created by
nobody), which narrows it but still is not proof.

The default is a dry run. Nothing is written unless ``apply=True``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_marker import demo_id_of

logger = logging.getLogger(__name__)


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


def _rules() -> list[_Rule]:
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


def _candidates() -> list[tuple[str, Any, Callable[[Any], Any] | None]]:
    """Models the old seeding wrote without a mark: ``(name, model, extra where)``."""
    from app.modules.bim_hub.models import BIMFederation
    from app.modules.field_time.models import FieldTimesheet
    from app.modules.hse_advanced.models import JobSafetyAnalysis, PermitToWork
    from app.modules.qms.models import QMSNCR, ITPPlan, QMSAudit, QMSInspection, QMSPunchItem
    from app.modules.service.models import ServiceContract
    from app.modules.teams.models import RosterMember
    from app.modules.variations.models import Notice

    return [
        (
            "qms_itp_plan_seed_fingerprint",
            ITPPlan,
            lambda m: (m.name == "Concrete pour - slab on grade") & (m.wbs_ref == "WBS.03.30") & m.created_by.is_(None),
        ),
        ("qms_inspections", QMSInspection, None),
        ("qms_ncrs", QMSNCR, None),
        ("qms_punch_items", QMSPunchItem, None),
        ("qms_audits", QMSAudit, None),
        ("teams_roster", RosterMember, None),
        ("field_timesheets", FieldTimesheet, None),
        ("hse_job_safety_analyses", JobSafetyAnalysis, None),
        ("hse_permits_to_work", PermitToWork, None),
        ("variation_notices", Notice, None),
        ("service_contracts", ServiceContract, None),
        (
            "bim_coordination_federation",
            BIMFederation,
            lambda m: m.name == "Coordination Federation",
        ),
    ]


@dataclass
class CleanupReport:
    """What a pass found in real projects, and what it removed."""

    real_projects: int = 0
    applied: bool = False
    # rule name -> rows carrying the seed's mark (removed when ``applied``)
    marked: dict[str, int] = field(default_factory=dict)
    # model name -> rows with no mark, left alone, for a person to review
    unmarked_candidates: dict[str, int] = field(default_factory=dict)

    @property
    def total_marked(self) -> int:
        return sum(self.marked.values())


async def _real_project_ids(session: AsyncSession) -> list[uuid.UUID]:
    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.metadata_))).all()
    return [pid for pid, meta in rows if not demo_id_of(meta)]


async def clean_leaked_demo_rows(session: AsyncSession, *, apply: bool = False) -> CleanupReport:
    """Report, and with ``apply`` delete, seed-marked rows in real projects.

    Flushes but does not commit; the caller commits, so a dry run followed by a
    rollback leaves the database exactly as it was.

    Args:
        session: Session to read and write through.
        apply: Delete the marked rows. ``False`` (the default) only counts.
    """
    report = CleanupReport(applied=apply)
    real = await _real_project_ids(session)
    report.real_projects = len(real)
    if not real:
        return report

    for rule in _rules():
        model = rule.model()
        rows = (await session.execute(select(model).where(model.project_id.in_(real)))).scalars().all()
        ids = [row.id for row in rows if rule.is_seeded(row)]
        report.marked[rule.name] = len(ids)
        if not apply or not ids:
            continue
        for child, column in rule.orphans():
            await session.execute(delete(child).where(getattr(child, column).in_(ids)))
        await session.execute(delete(model).where(model.id.in_(ids)))
        await session.flush()
        logger.info("demo cleanup: removed %d seeded %s row(s) from real projects", len(ids), rule.name)

    for name, model, extra in _candidates():
        stmt = select(func.count()).select_from(model).where(model.project_id.in_(real))
        if extra is not None:
            stmt = stmt.where(extra(model))
        count = int((await session.execute(stmt)).scalar_one())
        if count:
            report.unmarked_candidates[name] = count

    if apply:
        session.expire_all()
    return report
