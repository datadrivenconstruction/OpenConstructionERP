# OpenConstructionERP - DataDrivenConstruction (DDC)
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Reusable per-module demo enrichment.

The rich per-module demo seeders (photos, takeoff, BIM grouping, clash,
carbon, QMS, advanced scheduling, cost model, MoC, supplier catalogs,
variations, accommodation, markups, catalog, plus CRM / service / bid /
HSE / portal / tendering) used to run only inline at first boot in
``app/main.py``. The in-app partner-pack apply paths installed the demo
project's BOQ / budget / schedule / tender / BIM model / PDFs but never ran
these enrichment seeders, so a pack applied from the Modules page after boot
opened with empty photos / takeoff / clash / carbon / qms / variations /
costmodel / moc / markups / catalog.

This module extracts that seeder list into one reusable, fail-soft coroutine
so both boot AND the pack-apply paths run the exact same enrichment. Each
seeder runs in its own DB session inside its own ``try/except`` so a single
seeder (or a single project) failing never aborts the rest, never aborts the
pack apply and never aborts boot.

No new DB tables: this only orchestrates seeders that already exist.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

# The flagship reference project. Kept first in the enrichment order so the
# seeders that cap at a few projects (advanced scheduling, QMS, supplier
# catalog) always cover the project users land on.
_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")


async def enrich_projects(project_ids: list[uuid.UUID]) -> None:
    """Run every per-module demo seeder across the given projects.

    Mirrors the first-boot enrichment block that used to live inline in
    ``app/main.py`` (the unconditional ``OE_TEST_FAST_STARTUP``-gated block).
    Each seeder runs in its own session and its own ``try/except`` so one
    failing seeder (or one failing project) can never abort the rest. Safe to
    call repeatedly: every seeder is either internally idempotent or gated on a
    marker table so a re-run never duplicates rows.

    Args:
        project_ids: The projects to enrich. Typically every project at boot,
            or the single project a partner-pack apply just installed.
    """
    if not project_ids:
        return

    try:
        from sqlalchemy import func as _func
        from sqlalchemy import select as _msel

        from app.database import async_session_factory
        from app.modules.accommodation.seed import seed_accommodation
        from app.modules.bid_management.seed import seed_bid_management_demo
        from app.modules.bim_hub.seed import seed_bim_hub
        from app.modules.carbon.models import CarbonInventory
        from app.modules.carbon.seed import seed_carbon_demo
        from app.modules.catalog.seed import seed_catalog
        from app.modules.clash.seed import seed_clash
        from app.modules.costmodel.seed import seed_costmodel
        from app.modules.crm.seed import seed_crm_demo
        from app.modules.documents.photos_seed import seed_photos
        from app.modules.hse_advanced.seed import seed_hse_advanced_demo
        from app.modules.markups.seed import seed_markups
        from app.modules.moc.seed import seed_moc
        from app.modules.portal.seed import seed_portal_demo
        from app.modules.qms.models import ITPPlan
        from app.modules.qms.seed import seed_qms
        from app.modules.schedule_advanced.models import MasterSchedule
        from app.modules.schedule_advanced.seed import seed_schedule_advanced_demo
        from app.modules.service.seed import seed_service_demo
        from app.modules.supplier_catalogs.seed import seed_supplier_catalogs
        from app.modules.takeoff.seed import seed_takeoff_demo
        from app.modules.tendering.seed import seed_tendering
        from app.modules.variations.models import Notice
        from app.modules.variations.seed import seed_variations_demo

        # Keep the flagship reference project first so seeders that cap at a
        # few projects (advanced scheduling, QMS, supplier catalog) always
        # cover the project users land on.
        _all_pids = list(project_ids)
        _all_pids.sort(key=lambda _p: 0 if _p == _FLAGSHIP_ID else 1)
        _first_pid = _all_pids[0] if _all_pids else None

        # (name, marker model gating a restart-safe skip, coroutine builder).
        # A None marker means the seeder self-guards against duplicates.
        _module_seeders = [
            ("crm", None, lambda s: seed_crm_demo(s)),
            ("service", None, lambda s: seed_service_demo(s)),
            ("bid_management", None, lambda s: seed_bid_management_demo(s, _all_pids)),
            ("hse_advanced", None, lambda s: seed_hse_advanced_demo(s, _all_pids)),
            ("portal", None, lambda s: seed_portal_demo(s, _all_pids)),
            ("supplier_catalogs", None, lambda s: seed_supplier_catalogs(s, _first_pid)),
            ("carbon", CarbonInventory, lambda s: seed_carbon_demo(s, _all_pids)),
            (
                "schedule_advanced",
                MasterSchedule,
                lambda s: seed_schedule_advanced_demo(s, _all_pids),
            ),
            ("variations", Notice, lambda s: seed_variations_demo(s, _all_pids)),
            # ── Modules that shipped without any startup seeder at all ──
            # Each new seeder below is internally idempotent (it returns an
            # empty dict once its own marker rows already exist), so they are
            # wired with a None marker and re-checked cheaply on every restart.
            # A None marker is required here rather than a global row-count gate
            # because several of these (takeoff, tendering, markups)
            # legitimately share their table with rows seeded elsewhere or by
            # users, so a table-wide count would skip the projects that are
            # still empty.
            ("costmodel", None, lambda s: seed_costmodel(s, _all_pids)),
            ("moc", None, lambda s: seed_moc(s, _all_pids)),
            ("tendering", None, lambda s: seed_tendering(s, _all_pids)),
            ("takeoff", None, lambda s: seed_takeoff_demo(s, _all_pids)),
            ("accommodation", None, lambda s: seed_accommodation(s, _all_pids)),
            ("markups", None, lambda s: seed_markups(s, _all_pids)),
            ("catalog", None, lambda s: seed_catalog(s, _all_pids)),
            # Site photos drop real JPEGs into the gallery so the Photos module
            # and the dashboard "latest photos" widget are never empty on a
            # fresh install. Self-guards per project on an existing seeded photo.
            ("photos", None, lambda s: seed_photos(s, _all_pids)),
            # bim_hub groups the BIM models that already exist for a project, so
            # it runs near the end (after every other seeder). clash runs right
            # after it so its clash results reference the freshly grouped
            # models; clash also feeds the coordination_hub dashboard's clash
            # rollup.
            ("bim_hub", None, lambda s: seed_bim_hub(s, _all_pids)),
            ("clash", None, lambda s: seed_clash(s, _all_pids)),
        ]
        for _name, _marker, _build in _module_seeders:
            try:
                if _marker is not None:
                    async with async_session_factory() as _chk:
                        _n = (await _chk.execute(_msel(_func.count()).select_from(_marker))).scalar_one()
                    if _n:
                        continue
                async with async_session_factory() as _ms:
                    _counts = await _build(_ms)
                    await _ms.commit()
                    if isinstance(_counts, dict) and any(_counts.values()):
                        logger.info("%s demo seed: %s", _name, _counts)
            except Exception:
                logger.warning("%s demo seed skipped (non-fatal)", _name, exc_info=True)

        # QMS seeds one project at a time and is not internally idempotent; loop
        # the projects, skipping any that already carry an ITP plan so a re-run
        # never duplicates.
        for _pid in _all_pids:
            try:
                async with async_session_factory() as _qs:
                    _has = (
                        await _qs.execute(_msel(ITPPlan.id).where(ITPPlan.project_id == _pid).limit(1))
                    ).scalar_one_or_none()
                    if _has is None:
                        await seed_qms(_qs, project_id=_pid)
                        await _qs.commit()
            except Exception:
                logger.warning("qms demo seed skipped for %s (non-fatal)", _pid, exc_info=True)
    except Exception:
        logger.warning("Feature-module demo seeds skipped (non-fatal)", exc_info=True)


async def enrich_all() -> None:
    """Enrich every project that currently exists in the database.

    Convenience wrapper used at boot: discovers all project ids and runs
    :func:`enrich_projects` over them. Fail-soft; a discovery error logs and
    returns without raising.
    """
    try:
        from sqlalchemy import select as _msel

        from app.database import async_session_factory
        from app.modules.projects.models import Project as _Proj

        async with async_session_factory() as _pid_s:
            _all_pids = list((await _pid_s.execute(_msel(_Proj.id))).scalars().all())
    except Exception:
        logger.warning("Feature-module demo seeds skipped (project discovery failed)", exc_info=True)
        return

    await enrich_projects(_all_pids)
