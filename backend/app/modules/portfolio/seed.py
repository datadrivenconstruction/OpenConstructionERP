# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portfolio demo seed - one programme structure over the demo projects.

Unlike every other module in the estate, this one is not a register inside a
project: it is a structure *over* the projects, so it is seeded once across the
whole install rather than once per project. There is one portfolio at the root,
a programme per sector beneath it, a region subprogramme wherever a sector runs
three or more jobs, and each demo project filed under exactly one leaf - which
is what ``oe_portfolio_membership`` allows, one node per project.

The classification is read from the projects themselves - the demo id says what
kind of job it is and the country code says where it runs - rather than from a
list of project ids, so an install carrying a partner pack's own country project
is filed correctly without this file knowing the pack exists.

On top of the tree it seeds a handful of cross-schedule links: the dependencies
that only exist because two projects share something, a crane coming off one job
onto the next, one commissioning team covering both in turn. They are directed
strictly from an earlier project to a later one, so the schedule-of-schedules
CPM can never find a cycle, and at least one link sits wholly inside a single
programme, so running the CPM on a programme node - not only on the root - has
real edges to apply.

What a reader sees on the portfolio screen afterwards:

* a navigable tree instead of an empty state - a portfolio, its programmes, the
  region subprogrammes under the busiest of them, and the projects filed under
  each, all three node types represented;
* a portfolio CPM that returns real numbers on any node with schedules under it:
  schedule and activity counts, the portfolio finish work-day, and a critical
  path that crosses project boundaries where a cross-link puts it there;
* a cross-links panel with links to look at, each one carrying the reason it
  exists rather than being an unexplained arrow between two projects.

Self-gating: the tree is a single global structure, so the seeder does nothing
at all once any portfolio node exists - which covers both the second boot and an
install where somebody has already built their own hierarchy. Only projects
carrying the demo marker are filed, so a customer's live project is never swept
into a portfolio it did not ask to be in.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.portfolio.models import (
    PortfolioCrossLink,
    PortfolioMembership,
    PortfolioNode,
)

logger = logging.getLogger(__name__)

_SEED = 6503

# Node types (mirrors PORTFOLIO_NODE_TYPES in the module's own models).
_PORTFOLIO = "portfolio"
_PROGRAMME = "programme"
_SUBPROGRAMME = "subprogramme"

# The root the whole structure hangs from.
_ROOT_NAME = "Group capital programme"
_ROOT_CODE = "PF-01"

# A sector programme is only split into region subprogrammes once it runs this
# many projects. Below it, a second level of nodes is filing for its own sake.
_SPLIT_AT = 3

# The sector programmes, as ``(code, display name, sector key)``. The order here
# is the order they are laid out on screen, since each one's ``sort_order`` is
# taken from its position in this tuple.
_SECTORS: tuple[tuple[str, str, str], ...] = (
    ("RES", "Residential programme", "residential"),
    ("IND", "Industrial and logistics programme", "industrial"),
    ("SOC", "Social infrastructure programme", "social"),
    ("COM", "Commercial and retail programme", "commercial"),
    ("GEN", "General works programme", "general"),
)

# Demo-id leading word -> sector key. The demo id is authored with the project,
# so it says what the job is far more reliably than its display name does.
_SECTOR_BY_DEMO_HEAD: dict[str, str] = {
    "residential": "residential",
    "condo": "residential",
    "housing": "residential",
    "modular": "residential",
    "warehouse": "industrial",
    "solar": "industrial",
    "renewables": "industrial",
    "rc": "industrial",
    "industrial": "industrial",
    "plant": "industrial",
    "school": "social",
    "medical": "social",
    "hospital": "social",
    "govt": "social",
    "office": "commercial",
    "retail": "commercial",
    "commercial": "commercial",
    "mixed": "commercial",
}

# Fallback for a project with no demo id worth reading: a keyword in its name.
# Checked in order, first hit wins.
_SECTOR_BY_NAME_KEYWORD: tuple[tuple[str, str], ...] = (
    ("residential", "residential"),
    ("condo", "residential"),
    ("apartment", "residential"),
    ("housing", "residential"),
    ("warehouse", "industrial"),
    ("logistics", "industrial"),
    ("plant", "industrial"),
    ("solar", "industrial"),
    ("factory", "industrial"),
    ("school", "social"),
    ("medical", "social"),
    ("hospital", "social"),
    ("clinic", "social"),
    ("university", "social"),
    ("government", "social"),
    ("office", "commercial"),
    ("retail", "commercial"),
    ("market", "commercial"),
    ("tower", "commercial"),
    ("mixed", "commercial"),
)

# Delivery region a country belongs to, for the subprogramme split.
_REGION_BY_COUNTRY: dict[str, tuple[str, str]] = {
    **dict.fromkeys(
        ("DE", "FR", "GB", "IE", "NL", "BE", "ES", "IT", "PT", "PL", "CZ", "AT", "CH", "SE", "NO", "DK", "FI", "ZA"),
        ("EMEA", "Europe, Middle East and Africa"),
    ),
    # Turkey is not a Gulf state; it sits with the rest of the region.
    "TR": ("EMEA", "Europe, Middle East and Africa"),
    **dict.fromkeys(("AE", "SA", "QA", "KW", "OM", "BH"), ("GULF", "Gulf states")),
    **dict.fromkeys(("US", "CA", "BR", "MX", "AR", "CL", "CO"), ("AMER", "Americas")),
    **dict.fromkeys(("CN", "IN", "JP", "KR", "SG", "AU", "NZ", "MY", "TH", "VN", "ID", "PH"), ("APAC", "Asia Pacific")),
}
_DEFAULT_REGION = ("INTL", "International")

# Why a cross-project dependency exists. A link between two schedules is only
# worth drawing when something real is shared, so each one says what.
_LINK_REASONS: tuple[str, ...] = (
    "Tower crane released here and re-erected on the following project.",
    "The same piling rig and crew move between the two sites.",
    "Shared precast supply slot; the second project takes the casting line after the first.",
    "One commissioning team covers both projects in sequence.",
    "The standard facade detail is signed off once and reused on the following project.",
    "Shared temporary power connection transferred once the first project energises.",
)

# Days between the two ends of a cross-project link: demobilise, move, set up.
_LINK_LAG_RANGE = (5, 20)


class _Filed(NamedTuple):
    """One project and where it lands in the tree."""

    project_id: uuid.UUID
    sector: str
    region_code: str
    region_name: str


def _sector_for(demo_id: str, name: str) -> str:
    """Which sector programme a project belongs under."""
    head = str(demo_id or "").split("-", 1)[0].lower()
    sector = _SECTOR_BY_DEMO_HEAD.get(head)
    if sector is not None:
        return sector
    lowered = str(name or "").lower()
    for keyword, value in _SECTOR_BY_NAME_KEYWORD:
        if keyword in lowered:
            return value
    return "general"


def _region_for(country_code: str | None) -> tuple[str, str]:
    """Delivery region ``(code, name)`` for a project's country.

    ``None`` is expected rather than tolerated: ``Project.country_code`` is
    nullable from revision ``v3319``, and a project that names no country files
    under the default region, which is what the body already did for ''.
    """
    return _REGION_BY_COUNTRY.get(str(country_code or "").upper(), _DEFAULT_REGION)


async def _demo_projects(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> tuple[list[_Filed], uuid.UUID | None]:
    """Classify the demo projects among ``project_ids`` and find their owner.

    A customer's live project is never filed into a portfolio somebody else
    invented, so the marker the demo installer writes onto its own projects is
    what admits a project here. The filter runs in Python because a JSON
    ``contains`` compiles to a string LIKE on this stack rather than to real
    containment.
    """
    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.name, Project.country_code, Project.owner_id, Project.metadata_)
            .where(Project.id.in_(list(project_ids)))
            .order_by(Project.name),
        )
    ).all()
    filed: list[_Filed] = []
    owner_id: uuid.UUID | None = None
    for project_id, name, country_code, project_owner, metadata in rows:
        meta = metadata if isinstance(metadata, dict) else {}
        # ``demo_id`` and not ``is_demo``. The ten template projects stamp both,
        # but the flagship reference project is installed from its own baked
        # fixture and carries only ``demo_id``, so a gate on ``is_demo`` would
        # leave the project users land on out of the portfolio entirely.
        if not str(meta.get("demo_id") or "").strip():
            continue
        if owner_id is None and project_owner is not None:
            owner_id = project_owner
        region_code, region_name = _region_for(country_code)
        filed.append(
            _Filed(
                project_id=project_id,
                sector=_sector_for(str(meta.get("demo_id") or ""), str(name or "")),
                region_code=region_code,
                region_name=region_name,
            ),
        )
    return filed, owner_id


def _add_node(
    session: AsyncSession,
    *,
    node_type: str,
    name: str,
    code: str,
    parent_id: uuid.UUID | None,
    owner_id: uuid.UUID | None,
    sort_order: int,
) -> PortfolioNode:
    """Add one node to the session (the base supplies its id on flush).

    ``sort_order`` is always set: the tree builder sorts on it before falling
    back to the name, so leaving it at zero would hand the layout to the
    alphabet rather than to the order the programmes are meant to read in.
    """
    node = PortfolioNode(
        parent_id=parent_id,
        node_type=node_type,
        name=name,
        code=code,
        owner_id=owner_id,
        sort_order=sort_order,
        metadata_={"seed": True, "demo": True},
    )
    session.add(node)
    return node


async def _build_tree(
    session: AsyncSession,
    filed: Sequence[_Filed],
    owner_id: uuid.UUID | None,
) -> tuple[dict[str, uuid.UUID], dict[str, int]]:
    """Create the nodes and memberships, one level at a time.

    Each level is flushed before the next is built, so a child can reference its
    parent's id without this seeder minting primary keys of its own.

    Returns ``(programme_by_sector, counts)``: which programme node covers each
    sector, so a caller can tell whether two projects share one, and the insert
    counts.
    """
    counts = {"nodes": 0, "memberships": 0}
    root = _add_node(
        session,
        node_type=_PORTFOLIO,
        name=_ROOT_NAME,
        code=_ROOT_CODE,
        parent_id=None,
        owner_id=owner_id,
        sort_order=0,
    )
    counts["nodes"] += 1
    await session.flush()

    by_sector: dict[str, list[_Filed]] = {}
    for item in filed:
        by_sector.setdefault(item.sector, []).append(item)

    programmes: dict[str, tuple[str, PortfolioNode]] = {}
    order = 0
    for code, name, key in _SECTORS:
        if not by_sector.get(key):
            # A sector nobody is building in gets no node at all: an empty
            # programme is a label with nothing under it.
            continue
        order += 1
        programmes[key] = (
            code,
            _add_node(
                session,
                node_type=_PROGRAMME,
                name=name,
                code=f"PG-{code}",
                parent_id=root.id,
                owner_id=owner_id,
                sort_order=order,
            ),
        )
        counts["nodes"] += 1
    await session.flush()

    node_by_project: dict[uuid.UUID, uuid.UUID] = {}
    programme_by_sector: dict[str, uuid.UUID] = {key: node.id for key, (_code, node) in programmes.items()}
    # Subprogrammes are collected first and read back only after the flush that
    # mints their ids. Reading ``sub.id`` before that yields None, and a
    # membership pointing at None is silently dropped - which files every
    # project in a split sector nowhere at all.
    pending: list[tuple[PortfolioNode, list[_Filed]]] = []
    for key, (code, programme) in programmes.items():
        members = by_sector[key]
        if len(members) < _SPLIT_AT:
            for item in members:
                node_by_project[item.project_id] = programme.id
            continue

        # A sector running three or more jobs is worth splitting by delivery
        # region, which is how a programme of that size is actually run.
        by_region: dict[str, list[_Filed]] = {}
        for item in members:
            by_region.setdefault(item.region_code, []).append(item)
        for sub_order, region_code in enumerate(sorted(by_region), start=1):
            group = by_region[region_code]
            sub = _add_node(
                session,
                node_type=_SUBPROGRAMME,
                name=f"{group[0].region_name} delivery",
                code=f"SP-{code}-{region_code}",
                parent_id=programme.id,
                owner_id=owner_id,
                sort_order=sub_order,
            )
            counts["nodes"] += 1
            pending.append((sub, group))
    await session.flush()
    for sub, group in pending:
        for item in group:
            node_by_project[item.project_id] = sub.id

    for item in filed:
        node_id = node_by_project.get(item.project_id)
        if node_id is None:
            continue
        session.add(
            PortfolioMembership(
                node_id=node_id,
                project_id=item.project_id,
                metadata_={"seed": True, "demo": True},
            ),
        )
        counts["memberships"] += 1
    await session.flush()
    return programme_by_sector, counts


async def _schedule_activities(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, tuple[uuid.UUID, list[uuid.UUID]]]:
    """One schedule per project plus its leaf activities, in start-date order.

    A project can carry several schedules (a baseline beside the live one); the
    busiest is the one a portfolio link should hang off, so that is the one
    returned. Summary rows are excluded by dropping anything another activity
    calls its parent, and zero-duration milestones with them: a cross-project
    dependency lands on a piece of work, not on a heading or a flag.
    """
    from app.modules.schedule.models import Activity, Schedule

    out: dict[uuid.UUID, tuple[uuid.UUID, list[uuid.UUID]]] = {}
    schedules = (
        await session.execute(select(Schedule.id, Schedule.project_id).where(Schedule.project_id.in_(project_ids)))
    ).all()
    if not schedules:
        return out

    schedule_ids = [sid for sid, _pid in schedules]
    sizes = dict(
        (
            await session.execute(
                select(Activity.schedule_id, func.count())
                .where(Activity.schedule_id.in_(schedule_ids))
                .group_by(Activity.schedule_id),
            )
        ).all(),
    )
    best: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}
    for schedule_id, project_id in schedules:
        size = int(sizes.get(schedule_id, 0))
        current = best.get(project_id)
        if current is None or size > current[1]:
            best[project_id] = (schedule_id, size)

    chosen = [sid for sid, size in best.values() if size]
    if not chosen:
        return out
    rows = (
        await session.execute(
            select(Activity.id, Activity.schedule_id, Activity.parent_id, Activity.duration_days)
            .where(Activity.schedule_id.in_(chosen))
            .order_by(Activity.start_date, Activity.wbs_code),
        )
    ).all()
    parents = {parent_id for _aid, _sid, parent_id, _dur in rows if parent_id is not None}
    by_schedule: dict[uuid.UUID, list[uuid.UUID]] = {}
    for activity_id, schedule_id, _parent_id, duration_days in rows:
        if activity_id in parents or int(duration_days or 0) <= 0:
            continue
        by_schedule.setdefault(schedule_id, []).append(activity_id)
    for project_id, (schedule_id, _size) in best.items():
        activities = by_schedule.get(schedule_id)
        if activities:
            out[project_id] = (schedule_id, activities)
    return out


def _link_pairs(
    filed: Sequence[_Filed],
    programme_by_sector: dict[str, uuid.UUID],
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Project pairs to link, earlier project first so the graph stays acyclic.

    Every pair is ordered by the project's position in ``filed``, so the
    project-level dependency graph is a strict DAG and the schedule-of-schedules
    CPM can never raise a cycle on seeded data.

    Pairs inside one sector come first and are what makes running the CPM on a
    programme node - rather than only on the root - show applied links instead
    of an empty critical path.
    """
    position = {item.project_id: index for index, item in enumerate(filed)}
    pairs: list[tuple[uuid.UUID, uuid.UUID]] = []

    by_sector: dict[str, list[_Filed]] = {}
    for item in filed:
        by_sector.setdefault(item.sector, []).append(item)
    for sector in sorted(by_sector):
        if sector not in programme_by_sector:
            continue
        members = by_sector[sector]
        for index in range(len(members) - 1):
            pairs.append((members[index].project_id, members[index + 1].project_id))

    # A couple of links across programmes as well, so the root node's CPM covers
    # edges the individual programmes do not.
    for index in range(0, max(0, len(filed) - 2), 3):
        pairs.append((filed[index].project_id, filed[index + 2].project_id))

    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    ordered: list[tuple[uuid.UUID, uuid.UUID]] = []
    for left, right in pairs:
        if left == right:
            continue
        pair = (left, right) if position[left] < position[right] else (right, left)
        if pair in seen:
            continue
        seen.add(pair)
        ordered.append(pair)
    return ordered


async def _seed_cross_links(
    session: AsyncSession,
    filed: Sequence[_Filed],
    programme_by_sector: dict[str, uuid.UUID],
) -> int:
    """Link activities across projects that really do depend on each other."""
    schedules = await _schedule_activities(session, [item.project_id for item in filed])
    if len(schedules) < 2:
        logger.debug("Fewer than two demo projects carry a schedule; no portfolio cross-links seeded")
        return 0

    rng = random.Random(_SEED)
    created = 0
    for index, (left, right) in enumerate(_link_pairs(filed, programme_by_sector)):
        pred = schedules.get(left)
        succ = schedules.get(right)
        if pred is None or succ is None:
            continue
        pred_schedule, pred_activities = pred
        succ_schedule, succ_activities = succ
        # Late work on the giving project, early work on the receiving one. Each
        # activity is taken from the list belonging to the schedule it is filed
        # under, which is the consistency the API enforces on this pair when a
        # user creates one by hand.
        pred_activity = pred_activities[int(len(pred_activities) * 0.7)]
        succ_activity = succ_activities[min(int(len(succ_activities) * 0.2), len(succ_activities) - 1)]
        session.add(
            PortfolioCrossLink(
                predecessor_schedule_id=pred_schedule,
                predecessor_activity_id=pred_activity,
                successor_schedule_id=succ_schedule,
                successor_activity_id=succ_activity,
                dep_type="FS",
                lag_days=rng.randint(*_LINK_LAG_RANGE),
                metadata_={
                    "seed": True,
                    "demo": True,
                    "reason": _LINK_REASONS[index % len(_LINK_REASONS)],
                },
            ),
        )
        created += 1
    await session.flush()
    return created


async def seed_portfolio_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Build the one portfolio structure spanning the demo projects.

    This runs once over every project rather than once per project, because the
    thing it creates is a hierarchy above the projects rather than rows inside
    one. Afterwards the portfolio screen shows a navigable tree - a portfolio,
    its sector programmes, a region subprogramme under any sector running three
    or more jobs, and every demo project filed under exactly one leaf - and the
    portfolio CPM on any of those nodes returns real schedule counts, a finish
    work-day and a critical path, with a handful of cross-project links applied
    where two projects genuinely share something.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Every project in the install. Only those carrying the demo
            marker are filed. The whole call is a no-op once any portfolio node
            exists, so a re-run never doubles the tree and a hierarchy somebody
            built themselves is never touched.

    Returns:
        Dict with per-entity insert counts.
    """
    totals = {"nodes": 0, "memberships": 0, "cross_links": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    existing = (await session.execute(select(PortfolioNode.id).limit(1))).scalars().first()
    if existing is not None:
        return totals

    filed, owner_id = await _demo_projects(session, ids)
    if not filed:
        return totals

    already_filed = set(
        (await session.execute(select(PortfolioMembership.project_id))).scalars().all(),
    )
    filed = [item for item in filed if item.project_id not in already_filed]
    if not filed:
        return totals

    try:
        # A SAVEPOINT around the tree, so a structure that cannot be built costs
        # nothing else. Catching the exception is not enough on PostgreSQL: a
        # failed statement aborts the whole transaction, and everything after it
        # would then fail on a poisoned session rather than on its own merits.
        async with session.begin_nested():
            programme_by_sector, counts = await _build_tree(session, filed, owner_id)
    except Exception:
        logger.warning("Portfolio demo seed skipped (non-fatal)", exc_info=True)
        return totals
    totals["nodes"] += counts["nodes"]
    totals["memberships"] += counts["memberships"]

    try:
        # The cross-links reach into the schedule module, so they get a savepoint
        # of their own: an install whose schedules are not where this expects
        # them still keeps its portfolio tree.
        async with session.begin_nested():
            totals["cross_links"] += await _seed_cross_links(session, filed, programme_by_sector)
    except Exception:
        logger.warning("Portfolio cross-link demo seed skipped (non-fatal)", exc_info=True)
    return totals
