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
  rosters, HSE registers, variations, service contracts and field timesheets
  left no mark, so each of them exposes ``seeded_row_ids``, which compares
  several fields of a row at once with the constants the seeder itself writes
  from. The fingerprint lives next to the seed and reads the same constants,
  so the two cannot drift apart, and a single matching title is never enough.

The PPE register belongs to the company rather than to a project. Its seeded
rows are removed only when no demo project is left installed, because while
one is, they are part of that demo.

The default is a dry run that lists what it would remove. Nothing is written
unless ``apply=True``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_marker import demo_id_of, live_demo_projects

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
class CleanupReport:
    """What a pass found in real projects, and what it removed."""

    real_projects: int = 0
    applied: bool = False
    # group name -> ids of the rows proven to be the seed's (removed when ``applied``)
    rows: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    # Why the company-wide PPE register was left alone, when it was.
    ppe_kept_reason: str = ""

    @property
    def marked(self) -> dict[str, int]:
        return {name: len(ids) for name, ids in self.rows.items()}

    @property
    def total(self) -> int:
        return sum(len(ids) for ids in self.rows.values())


async def _real_project_ids(session: AsyncSession) -> list[uuid.UUID]:
    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.metadata_))).all()
    return [pid for pid, meta in rows if not demo_id_of(meta)]


async def clean_leaked_demo_rows(session: AsyncSession, *, apply: bool = False) -> CleanupReport:
    """Report, and with ``apply`` delete, the seed's rows in real projects.

    Flushes but does not commit; the caller commits, so a dry run followed by a
    rollback leaves the database exactly as it was. Groups are deleted in the
    order they are listed, children before the rows they point at.

    Args:
        session: Session to read and write through.
        apply: Delete what was found. ``False`` (the default) only lists it.
    """
    report = CleanupReport(applied=apply)
    real = await _real_project_ids(session)
    report.real_projects = len(real)

    async def take(label: str, model: Any, ids: list, orphans: list[tuple[Any, str]] = ()) -> None:
        report.rows[label] = list(ids)
        if not apply or not ids:
            return
        for child, column in orphans:
            await session.execute(delete(child).where(getattr(child, column).in_(ids)))
        await session.execute(delete(model).where(model.id.in_(ids)))
        await session.flush()
        logger.info("demo cleanup: removed %d seeded %s row(s) from real projects", len(ids), label)

    if real:
        for rule in _marker_rules():
            model = rule.model()
            rows = (await session.execute(select(model).where(model.project_id.in_(real)))).scalars().all()
            await take(rule.name, model, [row.id for row in rows if rule.is_seeded(row)], rule.orphans())

        for fingerprint in _fingerprinters():
            for model, ids, label in await fingerprint(session, real):
                await take(label, model, ids)

    from app.modules.hse_advanced.models import PPEIssue
    from app.modules.hse_advanced.seed import seeded_ppe_ids

    if await live_demo_projects(session):
        report.ppe_kept_reason = "demo projects are still installed; the seeded PPE issues belong to them"
    else:
        await take("hse_ppe_issues", PPEIssue, await seeded_ppe_ids(session))

    if apply:
        session.expire_all()
    return report
