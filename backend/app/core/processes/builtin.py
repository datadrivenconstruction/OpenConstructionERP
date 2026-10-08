# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedulers, sweepers and cache warm-ups as registry processes.

Everything here used to be a bare ``asyncio.create_task`` in the startup
handler: no handle was kept, nothing cancelled it on shutdown, and nobody could
see whether it ran. Each is now a process the admin can stop and restart.

None of them sits on the boot path. A periodic loop sleeps first and does its
first pass well after the server answers, and the cost-cache warm-up waits for
the first visit to the cost database (the frontend's module-entry ensure)
instead of running at every boot.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.core.processes.base import LoopProcess, ManagedProcess, OneShotProcess
from app.core.processes.registry import ProcessRegistry, ProcessSpec
from app.core.processes.semantic import fast_startup

logger = logging.getLogger(__name__)

DAY_S = 24 * 3600
HOUR_S = 3600

#: Short pause before a loop's first pass when its old loop had none, so the
#: pass lands after the server reports ready rather than inside the boot.
SETTLE_S = 60


def _off_in_tests() -> bool | None:
    return False if fast_startup() else None


# -- ticks ported from the startup handler -------------------------------


async def kpi_tick() -> None:
    """Recalculate KPIs for every active project."""
    from app.database import async_session_factory
    from app.modules.reporting.service import ReportingService

    async with async_session_factory() as session:
        result = await ReportingService(session).auto_recalculate_kpis()
        await session.commit()
    logger.info("KPI scheduler: %d projects processed, %d failed", result["processed"], result["failed"])


async def reports_tick() -> None:
    """Render every due report template and advance its next run."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.database import async_session_factory
    from app.modules.reporting.schemas import GenerateReportRequest
    from app.modules.reporting.service import ReportingService

    async with async_session_factory() as session:
        svc = ReportingService(session)
        due = await svc.list_due_templates(datetime.now(UTC))
        for template in due:
            if template.project_id_scope is None:
                # Portfolio reports need cross-project context we don't have
                # yet - pause so the worker doesn't busy-loop.
                template.is_scheduled = False
                template.next_run_at = None
                await svc.template_repo.update(template)
                continue
            try:
                gen = GenerateReportRequest(
                    project_id=template.project_id_scope,
                    template_id=template.id,
                    report_type=template.report_type,
                    title=f"{template.name} (scheduled {datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
                    format="pdf",
                    metadata={"triggered_by": "scheduler", "run_id": str(uuid4())},
                )
                report = await svc.generate_report(gen)
                await svc.mark_template_ran(template)
                if template.recipients:
                    try:
                        await svc.dispatch_report_email(report, list(template.recipients))
                    except Exception:
                        logger.exception("Scheduled report %s email dispatch failed", template.id)
            except Exception:
                logger.exception("Scheduled report %s failed", template.id)
        await session.commit()


async def risk_tick() -> None:
    """Escalate risks over their threshold or past their review date."""
    from app.database import async_session_factory
    from app.modules.risk.escalation import RiskEscalationService

    async with async_session_factory() as session:
        await RiskEscalationService(session).sweep()
        await session.commit()


async def phonelog_tick() -> None:
    """Delete call recordings past their retention window."""
    from app.database import async_session_factory
    from app.modules.phonelog.retention import prune_expired_recordings

    async with async_session_factory() as session:
        await prune_expired_recordings(session)
        await session.commit()


async def sla_tick() -> None:
    from app.modules.approval_routes.sla_monitor import _run_once

    await _run_once()


async def deadline_tick() -> None:
    from app.modules.deadlines.sweeper import _run_once

    await _run_once()


async def ai_agents_tick() -> None:
    from app.modules.ai_agents.scheduler import fire_due_runs

    await fire_due_runs()


async def file_trash_tick() -> None:
    from app.modules.file_trash.jobs import run_purge_once

    purged = await run_purge_once()
    if purged:
        logger.info("file_trash scheduler: purged %d expired trash row(s)", purged)


async def demo_retention_tick() -> None:
    from app.core.demo_retention import run_sweep_once

    await run_sweep_once()


async def prewarm_cost_caches() -> None:
    """Fill the cost database caches behind the "Add from Database" modal.

    /costs/regions/ and /costs/category-tree/ aggregate the whole catalog
    (DISTINCT region, GROUP BY JSON paths), slow on a cold 100k+ row database.
    Paying it once in the background makes every later open a cache hit.
    """
    import time

    from sqlalchemy import distinct, func, select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem
    from app.modules.costs.router import _category_tree_cache, _region_cache
    from app.modules.costs.schemas import CategoryTreeNode
    from app.modules.costs.service import CostItemService

    async with async_session_factory() as session:
        active = (CostItem.is_active.is_(True), CostItem.region.isnot(None), CostItem.region != "")
        r = await session.execute(select(distinct(CostItem.region)).where(*active))
        regions = sorted(row[0] for row in r.all())
        _region_cache["regions"] = regions

        s = await session.execute(
            select(CostItem.region, func.count(CostItem.id).label("cnt"))
            .where(*active)
            .group_by(CostItem.region)
            .order_by(func.count(CostItem.id).desc())
        )
        _region_cache["stats"] = [{"region": row[0], "count": row[1]} for row in s.all()]

        coll_expr = CostItem.classification["collection"].as_string()
        c = await session.execute(
            select(distinct(coll_expr))
            .where(CostItem.is_active.is_(True))
            .where(coll_expr.isnot(None))
            .where(coll_expr != "")
            .order_by(coll_expr)
        )
        _region_cache["categories_all"] = [row[0] for row in c.all() if row[0]]
        _region_cache["ts"] = time.monotonic()

        svc = CostItemService(session)
        for reg in regions:
            try:
                raw = await svc.category_tree(region=reg, depth=4)
                nodes = [CategoryTreeNode.model_validate(n) for n in raw]
                _category_tree_cache[f"tree::{reg}::d=4::p="] = {"nodes": nodes, "ts": time.monotonic()}
            except Exception:
                logger.debug("Pre-warm tree failed for region=%s", reg, exc_info=True)
    logger.info("Cost-DB caches pre-warmed for %d regions", len(regions))


# -- processes that wrap an existing start/stop pair ----------------------


class NotificationWorkerProcess(ManagedProcess):
    """The notification digests and cleanup, four loops under one switch."""

    async def start(self) -> None:
        from app.modules.notifications.notification_worker import start_scheduler

        start_scheduler()

    async def stop(self) -> None:
        from app.modules.notifications.notification_worker import stop_scheduler

        await stop_scheduler()


def _spec(
    process_id: str,
    factory: Callable[[], ManagedProcess],
    modules: list[str],
    *,
    category: str = "scheduler",
    start_mode: str = "boot",
    default_enabled: bool = True,
    legacy_enabled: bool = True,
    env_override: Callable[[], bool | None] = _off_in_tests,
    logger_names: list[str] | None = None,
) -> ProcessSpec:
    return ProcessSpec(
        id=process_id,
        factory=factory,
        modules=modules,
        category=category,  # type: ignore[arg-type]
        start_mode=start_mode,  # type: ignore[arg-type]
        default_enabled=default_enabled,
        legacy_enabled=legacy_enabled,
        estimated_ram_mb=1,
        env_override=env_override,
        logger_names=logger_names or [],
    )


def _loop(interval_s: float, tick: Callable[[], Awaitable[None]], initial_delay_s: float) -> Callable[[], LoopProcess]:
    return lambda: LoopProcess(interval_s=interval_s, tick=tick, initial_delay_s=initial_delay_s)


def register_builtin_processes(
    registry: ProcessRegistry,
    *,
    openapi_prime: Callable[[], Awaitable[None]] | None = None,
    openapi_env: Callable[[], bool | None] | None = None,
) -> None:
    """Declare every scheduler, sweeper and warm-up outside the semantic stack.

    Args:
        registry: The registry to declare them on.
        openapi_prime: Builds the OpenAPI document; None leaves it undeclared.
        openapi_env: Environment decision for the OpenAPI prime.
    """

    def demo_env() -> bool | None:
        if fast_startup():
            return False
        from app.core.demo_retention import demo_retention_enabled

        return demo_retention_enabled()

    specs = [
        # Intervals and first-pass delays are the old loops' own: each slept a
        # full interval before its first pass, except where noted.
        _spec("kpi_scheduler", _loop(DAY_S, kpi_tick, DAY_S), ["reporting"]),
        _spec("reports_scheduler", _loop(60, reports_tick, 60), ["reporting"]),
        # Started when someone opens the agents module (module entry ensure).
        _spec(
            "ai_agent_scheduler",
            _loop(60, ai_agents_tick, 60),
            ["ai_agents"],
            start_mode="lazy",
            default_enabled=False,
            logger_names=["app.modules.ai_agents.scheduler"],
        ),
        _spec(
            "approval_sla_monitor",
            _loop(1800, sla_tick, 1800),
            ["approval_routes"],
            logger_names=["app.modules.approval_routes.sla_monitor"],
        ),
        _spec(
            "deadline_sweeper",
            _loop(HOUR_S, deadline_tick, HOUR_S),
            ["deadlines"],
            logger_names=["app.modules.deadlines.sweeper"],
        ),
        _spec("risk_escalation", _loop(HOUR_S, risk_tick, HOUR_S), ["risk"]),
        # The old loop swept at boot; now it waits for the server to settle.
        _spec(
            "phonelog_retention",
            _loop(DAY_S, phonelog_tick, SETTLE_S),
            ["phonelog"],
            category="maintenance",
            logger_names=["app.modules.phonelog.retention"],
        ),
        _spec(
            "file_trash_purge",
            _loop(DAY_S, file_trash_tick, HOUR_S),
            ["file_trash"],
            category="maintenance",
            logger_names=["app.modules.file_trash.jobs"],
        ),
        _spec(
            "demo_retention",
            _loop(DAY_S, demo_retention_tick, HOUR_S),
            [],
            category="maintenance",
            env_override=demo_env,
            logger_names=["app.core.demo_retention"],
        ),
        _spec(
            "cost_cache_prewarm",
            lambda: OneShotProcess(run=prewarm_cost_caches),
            ["costs"],
            category="cache_warmup",
            start_mode="lazy",
            default_enabled=False,
        ),
    ]
    if openapi_prime is not None:
        specs.append(
            _spec(
                "openapi_prime",
                lambda: OneShotProcess(run=openapi_prime),
                [],
                category="cache_warmup",
                default_enabled=False,
                legacy_enabled=False,
                env_override=openapi_env or _off_in_tests,
            )
        )
    for spec in specs:
        registry.register(spec)


def register_notification_worker(registry: ProcessRegistry) -> None:
    """Declare the notification worker (called by its module)."""
    registry.register(
        _spec(
            "notification_worker",
            NotificationWorkerProcess,
            ["notifications"],
            category="sync",
            logger_names=["app.modules.notifications.notification_worker"],
        )
    )


def register_collab_lock_sweeper(registry: ProcessRegistry) -> None:
    """Declare the collaboration lock sweeper (called by its module)."""
    from app.modules.collaboration_locks.sweeper import SWEEP_INTERVAL_SECONDS, _sweep_once

    async def tick() -> None:
        await _sweep_once()

    registry.register(
        _spec(
            "collab_lock_sweeper",
            _loop(SWEEP_INTERVAL_SECONDS, tick, SWEEP_INTERVAL_SECONDS),
            ["collaboration_locks"],
            category="maintenance",
            logger_names=["app.modules.collaboration_locks.sweeper"],
        )
    )


__all__ = [
    "NotificationWorkerProcess",
    "register_builtin_processes",
    "register_collab_lock_sweeper",
    "register_notification_worker",
]
