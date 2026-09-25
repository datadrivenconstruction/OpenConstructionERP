# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Background job handlers for onboarding provisioning.

Wrap the two heavy first-run operations - regional cost base import and sample
project install - as JobRun handlers so the wizard can fire them and move on.
Both underlying operations are already idempotent (they early-return when the
data is already present). A first-run user must never see the wizard break
because an optional cost base could not be downloaded, but that is the client's
concern: the wizard does not wait on these jobs. The job itself reports the
truth, ``failed`` when nothing could be loaded, and counts of what landed and
what was left out otherwise. Progress is reported through ``update_progress`` so the client's
polling banner can show a real bar rather than a fake ramp.

Heavy imports (``costs.router``, ``demo_projects``) are done lazily inside the
handlers, not at module load, so registering these handlers at startup stays
cheap and free of import cycles.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.core.job_runner import register_handler, update_progress
from app.database import async_session_factory

if TYPE_CHECKING:
    from app.core.job_run import JobRun

logger = logging.getLogger(__name__)

# Job kinds. Also referenced by the router when it submits work and when it
# guards the status endpoint to onboarding jobs only.
KIND_LOAD_CWICR = "onboarding.load_cwicr"
KIND_INSTALL_DEMO = "onboarding.install_demo"

# The CWICR import reads a large parquet and bulk-inserts tens of thousands of
# rows; it is heavy on memory and on the single-writer database. Bound how many
# run at once so a user who picks several bases - or several users onboarding at
# the same time - cannot thrash a 3 GB server. Sample installs are lighter and run
# unbounded.
_CWICR_SEMAPHORE = asyncio.Semaphore(2)


class ProvisioningError(RuntimeError):
    """An onboarding item could not be provisioned.

    Raised rather than returned so the job runner records the job as
    ``failed`` with this message. These handlers used to return
    ``{"skipped": True}`` on a failed load, which the runner recorded as
    ``success``, and the wizard then told the user the country was ready.
    Keeping the wizard moving after a failure is the client's job; the job
    status has to say what happened.
    """


async def load_cwicr_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Import one regional cost base in the background and report what landed.

    Returns ``imported`` / ``total_items`` / ``failed`` so the status route can
    tell a complete load from a partial one. Raises :class:`ProvisioningError`
    when the base could not be loaded at all.
    """
    db_id = str(payload.get("db_id") or "").strip()
    if not db_id:
        raise ProvisioningError("No cost base was named.")

    await update_progress(job_run.id, percent=5, message=f"Preparing cost base {db_id}")

    # Lazy imports: pulling the costs router (and its pandas/parquet stack) at
    # module load would be wasteful and risk a cycle. HTTPException is what
    # load_cwicr_region raises on a missing file (404) or import failure (500).
    from fastapi import HTTPException

    from app.modules.costs.router import load_cwicr_region

    async with _CWICR_SEMAPHORE:
        await update_progress(job_run.id, percent=15, message=f"Importing cost base {db_id}")
        async with async_session_factory() as session:
            try:
                result = await load_cwicr_region(db_id, session)
                await session.commit()
            except HTTPException as exc:
                await _rollback_quietly(session)
                logger.warning("onboarding: cost base %s could not be loaded: %s", db_id, exc.detail)
                raise ProvisioningError(str(exc.detail)) from exc
            except Exception:
                await _rollback_quietly(session)
                raise

    # A parquet without the columns the import needs comes back as a 422
    # response object rather than a dict.
    if not isinstance(result, dict):
        raise ProvisioningError(f"Cost base {db_id} is not in a format that can be imported.")

    imported = int(result.get("imported") or 0)
    failed = int(result.get("failed") or 0)
    total = result.get("total_items")
    if total is None:
        total = await _count_region_items(db_id)
    await update_progress(job_run.id, percent=100, message=f"Cost base {db_id} loaded")
    return {
        "db_id": db_id,
        "imported": imported,
        "total_items": total,
        "failed": failed,
        "failed_codes": list(result.get("failed_codes") or []),
        "resource_prices_error": result.get("resource_prices_error"),
        "status": result.get("status") or "loaded",
    }


async def _rollback_quietly(session: Any) -> None:
    """Roll back a session whose connection may already be gone."""
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001 - the original error is the one to report
        logger.warning("onboarding: rollback after a failed load also failed", exc_info=True)


async def _count_region_items(db_id: str) -> int | None:
    """How many active items the region holds now, read on a fresh session."""
    from sqlalchemy import func, select

    from app.modules.costs.models import CostItem

    try:
        async with async_session_factory() as session:
            stmt = (
                select(func.count()).select_from(CostItem).where(CostItem.region == db_id, CostItem.is_active.is_(True))
            )
            return int((await session.execute(stmt)).scalar_one())
    except Exception:  # noqa: BLE001 - a missing count must not fail a load that succeeded
        logger.warning("onboarding: could not count the items of %s", db_id, exc_info=True)
        return None


async def install_demo_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Install one sample project in the background.

    Raises :class:`ProvisioningError` when the sample cannot be installed, so
    the job reads ``failed`` rather than ``success``.
    """
    demo_id = str(payload.get("demo_id") or "").strip()
    if not demo_id:
        raise ProvisioningError("No sample project was named.")

    await update_progress(job_run.id, percent=10, message="Installing sample project")

    from app.core.demo_projects import install_demo_project

    async with async_session_factory() as session:
        try:
            result = await install_demo_project(session, demo_id)
            await session.commit()
        except ValueError as exc:
            # Unknown demo id.
            await _rollback_quietly(session)
            logger.warning("onboarding: sample project %s could not be installed: %s", demo_id, exc)
            raise ProvisioningError(str(exc)) from exc
        except Exception:
            await _rollback_quietly(session)
            raise

    await update_progress(job_run.id, percent=100, message="Sample project ready")
    return {
        "demo_id": demo_id,
        "project_id": result.get("project_id"),
        "project_name": result.get("project_name"),
        "already_installed": bool(result.get("already_installed", False)),
    }


def register_onboarding_job_handlers() -> None:
    """Wire the onboarding handlers into the job runner."""
    register_handler(KIND_LOAD_CWICR, load_cwicr_handler)
    register_handler(KIND_INSTALL_DEMO, install_demo_handler)
