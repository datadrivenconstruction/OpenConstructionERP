"""Routes of the on-demand browser editor (see web_release): status, install, remove, and the bundle files."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.dependencies import CurrentUserId, SessionDep

from . import web_release as wr
from .settings import get_design_settings

FILES_PREFIX = "/api/v1/design/web-editor/files"


def _refusal(exc: wr.ReleaseError, code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(code, {"code": exc.code, "message": exc.detail, **exc.params})


async def _role(session, user_id: str) -> str:
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(str(user_id)))
    return getattr(user, "role", "viewer") if user is not None else "viewer"


def manifest_url(installed: wr.Installed) -> str:
    return f"{FILES_PREFIX}/{installed.version}/manifest.json"


async def status_view(session, user_id: str) -> dict[str, Any]:
    """What this ERP has (engine, installed bundle), what the feed offers, and whether this person may fetch it."""
    s = get_design_settings()
    installed = wr.read_installed(wr.editor_root(s))
    try:
        key_ok = wr.public_key(s) is not None
        key_error = None
    except wr.ReleaseError as exc:
        key_ok, key_error = False, exc.code
    feed: dict[str, Any]
    try:
        f = await wr.read_feed(s)
        feed = {
            "state": "available",
            "version": f.version,
            "bytes": f.zip_bytes,
            "bridge": list(f.bridge),
            "published_at": f.published_at or None,
            "problem": wr.bridge_problem(f.bridge),
        }
    except wr.ReleaseError as exc:
        feed = {"state": exc.code.removeprefix("feed_") if exc.code.startswith("feed_") else "invalid"}
    role = await _role(session, user_id)
    update = (
        feed.get("state") == "available"
        and not feed.get("problem")
        and (installed is None or installed.version != feed.get("version"))
    )
    return {
        "host_bridge": list(wr.HOST_BRIDGE),
        "installed": None
        if installed is None
        else {
            "version": installed.version,
            "bridge": list(installed.bridge),
            "bytes": installed.bytes,
            "installed_at": installed.installed_at,
            "manifest_url": manifest_url(installed),
            "problem": wr.bridge_problem(installed.bridge),
        },
        "feed": feed,
        "signing": {"key": key_ok, "error": key_error},
        "install": wr.install_state.view(),
        "update_available": bool(update),
        "can_install": role != "viewer" and key_ok,
        "can_remove": role == "admin",
        "is_admin": role == "admin",
    }


def register(router: APIRouter) -> None:
    @router.get("/web-editor")
    async def web_editor_status(session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
        return await status_view(session, user_id)

    @router.post("/web-editor/install", status_code=status.HTTP_202_ACCEPTED)
    async def web_editor_install(session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
        if await _role(session, user_id) == "viewer":
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "no_permission", "message": "Read-only role"})
        try:
            await wr.start_install(str(user_id))
        except wr.ReleaseError as exc:
            raise _refusal(exc, status.HTTP_503_SERVICE_UNAVAILABLE if exc.code.endswith("_unreachable") else 409)
        return await status_view(session, user_id)

    @router.delete("/web-editor", status_code=status.HTTP_204_NO_CONTENT)
    async def web_editor_remove(session: SessionDep, user_id: CurrentUserId) -> Response:
        if await _role(session, user_id) != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "no_permission", "message": "Administrators only"})
        task = wr.install_state.task
        if task is not None and not task.done():
            raise HTTPException(status.HTTP_409_CONFLICT, {"code": "busy", "message": "An install is running"})
        wr.remove_installed()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # The bundle is public open-source code loaded by <script type=module>/import(), which sends no token.
    @router.get("/web-editor/files/{version}/{path:path}", include_in_schema=False)
    async def web_editor_file(
        version: str, path: str, accept_encoding: str | None = Header(default=None)
    ) -> FileResponse:
        installed = wr.read_installed()
        if installed is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "No editor installed"})
        try:
            file, ctype, encoding = wr.resolve_file(installed, version, path, accept_encoding)
        except wr.ReleaseError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": path}) from exc
        headers = {
            "Vary": "Accept-Encoding",
            "X-Content-Type-Options": "nosniff",
            # versioned URL: a new release gets new URLs
            "Cache-Control": "public, max-age=31536000, immutable" if path != "manifest.json" else "no-cache",
            "Cross-Origin-Resource-Policy": "same-origin",
        }
        if encoding:
            headers["Content-Encoding"] = encoding
        return FileResponse(file, media_type=ctype, headers=headers)
