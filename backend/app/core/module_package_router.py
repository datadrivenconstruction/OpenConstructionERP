# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module package API: upload, review, install and remove third-party module ZIPs.

Upload, install and removal are admin actions (``system.modules.install`` /
``.uninstall``) checked here on the server. See :mod:`app.core.module_package`
for the trust model.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from app.core import module_package as pkg
from app.core.audit import audit_log
from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep, SettingsDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/module-packages", tags=["Module Packages"])

UI_TOKEN_MINUTES = 10

_HTTP = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "in_use": status.HTTP_409_CONFLICT,
    "changed": status.HTTP_409_CONFLICT,
}


def _refused(exc: pkg.PackageRefused) -> HTTPException:
    return HTTPException(
        status_code=_HTTP.get(exc.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
        detail=str(exc),
    )


async def _audit(session: Any, request: Request, user: dict[str, Any], action: str, details: dict[str, Any]) -> None:
    try:
        await audit_log(
            session,
            action=action,
            entity_type="module_package",
            entity_id=None,
            user_id=user.get("sub"),
            ip_address=request.client.host if request.client else None,
            details=details,
        )
        await session.commit()
    except Exception:
        logger.exception("module_package: audit write failed for %s", action)


class InstallBody(BaseModel):
    confirm_trusted: bool = False
    enable: bool = True


@router.post("/preview", dependencies=[Depends(RequirePermission("system.modules.install"))])
async def preview_package(
    request: Request, session: SessionDep, user: CurrentUserPayload, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Validate an uploaded module ZIP without running it and keep it for review."""
    data = await file.read(pkg.MAX_UPLOAD_BYTES + 1)
    try:
        preview = pkg.stage(data)
    except pkg.PackageRefused as exc:
        await _audit(session, request, user, "module_package.preview", {"outcome": exc.code, "file": file.filename})
        raise _refused(exc) from exc
    await _audit(
        session,
        request,
        user,
        "module_package.preview",
        {
            "outcome": "installable" if preview.installable else "rejected",
            "archive_sha256": preview.archive_sha256,
            "module": preview.module_name,
            "version": preview.version,
        },
    )
    return preview.to_dict()


@router.post("/{token}/install", dependencies=[Depends(RequirePermission("system.modules.install"))])
async def install_package(
    token: str, body: InstallBody, request: Request, session: SessionDep, user: CurrentUserPayload
) -> dict[str, Any]:
    """Install a reviewed package. The admin must confirm that the code is trusted."""
    if not body.confirm_trusted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Confirm that you trust this code before installing.",
        )
    try:
        result = await pkg.install(token, request.app, enable=body.enable, actor=user.get("sub"))
    except pkg.PackageRefused as exc:
        await _audit(session, request, user, "module_package.install", {"outcome": exc.code, "message": str(exc)})
        raise _refused(exc) from exc
    await _audit(session, request, user, "module_package.install", {"outcome": result["status"], **result})
    return result


@router.delete("/{token}", dependencies=[Depends(RequirePermission("system.modules.install"))])
async def discard_package(token: str) -> dict[str, str]:
    """Drop an upload that will not be installed."""
    try:
        pkg.discard(token)
    except pkg.PackageRefused as exc:
        raise _refused(exc) from exc
    return {"status": "discarded"}


@router.get("/installed", dependencies=[Depends(RequirePermission("system.modules.install"))])
async def list_installed() -> list[dict[str, Any]]:
    """Modules installed from a ZIP, with their install record."""
    from app.core.module_loader import module_loader

    return [
        {**m, "loaded": m.get("name") in module_loader._modules, "enabled": module_loader.is_enabled(m.get("name"))}
        for m in pkg.installed_packages()
    ]


@router.delete("/installed/{module_name}", dependencies=[Depends(RequirePermission("system.modules.uninstall"))])
async def uninstall_package(
    module_name: str, request: Request, session: SessionDep, user: CurrentUserPayload
) -> dict[str, Any]:
    """Remove a ZIP-installed module. Its database tables and records are kept."""
    try:
        result = await pkg.uninstall(module_name, request.app)
    except pkg.PackageRefused as exc:
        raise _refused(exc) from exc
    await _audit(session, request, user, "module_package.uninstall", {"outcome": "removed", "module": module_name})
    return result


@router.get("/ui-entries")
async def list_ui_entries(_user: CurrentUserPayload) -> list[dict[str, Any]]:
    """Sidebar pages declared by enabled ZIP-installed modules."""
    return pkg.ui_entries()


@router.post("/ui-token/{module_name}")
async def issue_ui_token(
    module_name: str, user: CurrentUserPayload, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """A short-lived token that only opens this module's own API, for its embedded page."""
    if module_name not in {e["module"] for e in pkg.ui_entries()}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No page for this module.")
    from app.middleware.module_ui_scope import SCOPE_CLAIM
    from app.modules.users.models import User
    from app.modules.users.service import create_access_token

    account = await session.get(User, UUID(str(user["sub"])))
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    expires = datetime.now(UTC) + timedelta(minutes=UI_TOKEN_MINUTES)
    token = create_access_token(
        account, settings, extra_claims={SCOPE_CLAIM: module_name, "exp": expires}, sid=user.get("sid")
    )
    return {"token": token, "expires_at": expires.isoformat()}
