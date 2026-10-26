# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout package build job handler.

Registered with the job runner under kind ``closeout.build``. Assembles the
ZIP via :meth:`CloseoutService._build_zip_blob`, persists it to storage and
stamps the result back on the package row.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.job_runner import register_handler, update_progress
from app.core.storage import get_storage_backend
from app.database import async_session_factory
from app.modules.closeout.models import CloseoutDossier
from app.modules.closeout.service import JOB_KIND, CloseoutService

if TYPE_CHECKING:
    from app.core.job_run import JobRun

logger = logging.getLogger(__name__)


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _package_key(project_id: uuid.UUID, package_id: uuid.UUID) -> str:
    return f"closeout/{project_id}/{package_id}.zip"


async def closeout_build_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the closeout ZIP for a package and persist it to storage."""
    package_id = _coerce_uuid(payload.get("package_id"))
    if package_id is None:
        return {"error": "missing package_id"}

    await update_progress(job_run.id, percent=20, message="Collecting evidence")

    async with async_session_factory() as session:
        service = CloseoutService(session)
        package = await service.repo.get_package(package_id)
        if package is None:
            return {"error": "package not found"}

        await update_progress(job_run.id, percent=50, message="Rendering COBie / reports")
        zip_bytes, summary = await service._build_zip_blob(package)

        await update_progress(job_run.id, percent=90, message="Writing package to storage")
        key = _package_key(package.project_id, package.id)
        await get_storage_backend().put(key, zip_bytes)

        # Stamp the build result on the package.
        package.package_key = key
        package.last_built_at = datetime.now(UTC).isoformat()
        package.last_built_job_id = job_run.id
        session.add(package)
        # Now that package_key is set, has_built is True, so generated required
        # slots count as delivered. Recompute the denormalised counters/status
        # so a fully delivered, built package can reach ready/100% and the
        # persisted status no longer contradicts the API ready flag.
        await service.recompute_completeness(package)
        await session.commit()

    result = {
        "package_key": key,
        "size_bytes": summary.get("size_bytes", len(zip_bytes)),
        "completeness_pct": summary.get("completeness_pct"),
        "ready": summary.get("ready"),
        "document_count": summary.get("document_count"),
        "generated_count": summary.get("generated_count"),
    }
    await update_progress(job_run.id, percent=100, message="Closeout package ready")
    logger.info("closeout: built package %s -> %s (%s bytes)", package_id, key, result["size_bytes"])
    return result


async def closeout_dossier_handler(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble a handover dossier, then run the deliveries it was requested with."""
    from app.modules.closeout.dossier_service import DossierService

    dossier_id = _coerce_uuid(payload.get("dossier_id"))
    if dossier_id is None:
        return {"error": "missing dossier_id"}
    await update_progress(job_run.id, percent=10, message="Collecting evidence")
    async with async_session_factory() as session:
        service = DossierService(session)
        dossier = await service.session.get(CloseoutDossier, dossier_id)
        if dossier is None:
            return {"error": "dossier not found"}
        try:
            await service.build(dossier)
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - recorded on the row, the UI shows it
            logger.exception("closeout: dossier %s build failed", dossier_id)
            await session.rollback()
            dossier = await service.session.get(CloseoutDossier, dossier_id)
            if dossier is not None:
                dossier.status = "failed"
                dossier.error = f"{exc.__class__.__name__}: {exc}"[:2000]
                await session.commit()
            return {"error": "build failed"}

        await update_progress(job_run.id, percent=80, message="Delivering")
        sent = 0
        for entry in list(dossier.delivery_request or []):
            if not isinstance(entry, dict):
                continue
            delivery = await service.deliver(dossier, entry, delivered_by=dossier.requested_by)
            sent += 1 if delivery.status == "sent" else 0
            await session.commit()
        result = {
            "dossier_id": str(dossier_id),
            "status": dossier.status,
            "size_bytes": dossier.size_bytes,
            "deliveries_sent": sent,
        }
    await update_progress(job_run.id, percent=100, message="Dossier ready")
    return result


def register_closeout_job_handler() -> None:
    """Wire the build handlers into the job runner."""
    from app.modules.closeout.dossier_service import JOB_KIND as DOSSIER_JOB_KIND

    register_handler(JOB_KIND, closeout_build_handler)
    register_handler(DOSSIER_JOB_KIND, closeout_dossier_handler)
