"""/api/v1/design — contract ddc-erp-link/1 (contract/README.md §8)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import re
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.rate_limiter import RateLimiter, client_ip
from app.dependencies import CurrentUserId, SessionDep

from . import integration, links
from .ai_profile import build_profile
from .auth import (
    LINK_VERSIONS,
    TOKEN_PREFIX,
    PrincipalDep,
    as_aware,
    digest,
    link_version,
    new_secret,
    now_utc,
    require_project,
)
from .brief import current_brief
from .brief import router as brief_router
from .estimate import recompute_on_accept
from .intake import Limits, PackageRejected, verify_package
from .models import DesignLinkCode, DesignLinkToken, DesignRevision
from .procurement import recompute_on_accept as procurement_on_accept
from .revisions import UPLOADING, VISIBLE
from .schedule import recompute_on_accept as schedule_on_accept
from .schemas import (
    AcceptRequest,
    ExchangeRequest,
    ExchangeResponse,
    LinkCodeRequest,
    LinkFile,
    LockView,
    RejectRequest,
    RevisionListResponse,
    RevisionView,
)
from .settings import get_design_settings


class LinkRoute(APIRoute):
    """Every response of the module carries ``X-DDC-Link: 1`` (contract §8), errors included."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request: Request) -> Response:
            try:
                response = await handler(request)
            except StarletteHTTPException as exc:
                exc.headers = {**(exc.headers or {}), "X-DDC-Link": "1"}
                raise
            except RequestValidationError as exc:
                on_error = request.app.exception_handlers.get(RequestValidationError)
                if on_error is None:
                    raise
                response = await on_error(request, exc)
            response.headers["X-DDC-Link"] = "1"
            return response

        return route


log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(link_version)], route_class=LinkRoute)
exchange_limiter = RateLimiter(max_requests=30, window_seconds=60)
_ERP_URL = re.compile(
    r"(?:https://[A-Za-z0-9.-]+(:[0-9]{1,5})?|http://(localhost|127(\.[0-9]{1,3}){3}|\[::1\])(:[0-9]{1,5})?)"
    r"(/[^?#@\s]*)?"
)
router.include_router(brief_router)

from .brief_api import router as brief_extract_router  # noqa: E402

router.include_router(brief_extract_router)

CODE_TTL = timedelta(minutes=5)
TOKEN_TTL = timedelta(days=30)
LOCK_TTL_S = 600
LOCK_ENTITY = "project"


def public_erp_url() -> str:
    """Where the editor must call: the configured public URL, never the request's Host header."""
    from app.config import get_settings

    url = (get_design_settings().public_url.strip() or get_settings().resolved_frontend_url).rstrip("/")
    if not _ERP_URL.fullmatch(url):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The public URL of this ERP must be https (http only for localhost); set OE_DESIGN_PUBLIC_URL",
        )
    return url


@router.get("/")
async def module_info(response: Response) -> dict:
    response.headers["X-DDC-Link"] = "1"
    return {"module": "oe_design", "status": "active", "link_versions": list(LINK_VERSIONS)}


# ── Link ────────────────────────────────────────────────────────────────────


@router.post("/link/code", response_model=LinkFile, response_model_by_alias=True, response_model_exclude_none=True)
async def create_link_code(
    body: LinkCodeRequest, request: Request, session: SessionDep, user_id: CurrentUserId
) -> LinkFile:
    from app.dependencies import verify_project_access
    from app.modules.projects.models import Project

    await verify_project_access(body.project_id, user_id, session)
    erp_url = public_erp_url()
    if body.revision_id is not None:
        rev = await session.get(DesignRevision, body.revision_id)
        if rev is None or rev.project_id != body.project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    project = await session.get(Project, body.project_id)
    code = new_secret()
    expires = now_utc() + CODE_TTL
    session.add(
        DesignLinkCode(
            code_hash=digest(code),
            project_id=body.project_id,
            user_id=uuid.UUID(user_id),
            action=body.action,
            revision_id=body.revision_id,
            expires_at=expires,
        )
    )
    await session.commit()
    return LinkFile(
        erp_url=erp_url,
        project_id=body.project_id,
        project_name=project.name if project else "",
        code=code,
        expires_at=expires,
        action=body.action,
        revision_id=body.revision_id,
    )


@router.post("/link/exchange", response_model=ExchangeResponse)
async def exchange_link_code(body: ExchangeRequest, session: SessionDep, request: Request) -> ExchangeResponse:
    ok, _ = exchange_limiter.is_allowed(
        f"ddc_exchange:{client_ip(request) or 'unknown'}", get_design_settings().exchange_rate_per_minute
    )
    if not ok:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts", headers={"Retry-After": "60"})
    now = now_utc()
    # Single use: the UPDATE claims the code atomically; a second caller matches no row.
    claimed = await session.execute(
        update(DesignLinkCode)
        .where(DesignLinkCode.code_hash == digest(body.code), DesignLinkCode.used_at.is_(None))
        .values(used_at=now)
        .returning(DesignLinkCode.id)
    )
    code_id = claimed.scalar_one_or_none()
    row = await session.get(DesignLinkCode, code_id) if code_id else None
    if row is None or as_aware(row.expires_at) <= now:
        await session.commit()
        raise HTTPException(status.HTTP_410_GONE, "Link code used or expired")
    token = new_secret(TOKEN_PREFIX)
    expires = now + TOKEN_TTL
    session.add(
        DesignLinkToken(
            token_hash=digest(token),
            project_id=row.project_id,
            user_id=row.user_id,
            client_name=body.client.name,
            client_version=body.client.version,
            client_os=body.client.os,
            expires_at=expires,
        )
    )
    await session.commit()
    return ExchangeResponse(token=token, expires_at=expires, project_id=row.project_id)


# ── Context ─────────────────────────────────────────────────────────────────


async def _can_accept(session, user_id: uuid.UUID, project) -> bool:
    from app.modules.users.models import User

    user = await session.get(User, user_id)
    if getattr(user, "role", "") == "viewer":
        return False
    if project.owner_id == user_id:
        return True
    return getattr(user, "role", "") in ("admin", "manager")


async def _can_publish(session, user_id: uuid.UUID) -> bool:
    """Read-only ERP roles may look at the model but not take the lock or publish."""
    from app.modules.users.models import User

    user = await session.get(User, user_id)
    return user is not None and getattr(user, "role", "viewer") != "viewer"


async def _can_edit_design(session, user_id: uuid.UUID, project) -> bool:
    """Members who may publish edit the design and create revisions, unless the project keeps that to managers."""
    from .drafts_api import edit_right

    if not await _can_publish(session, user_id):
        return False
    return await edit_right(session, project.id) == "members" or await _can_accept(session, user_id, project)


async def _require_publisher(session, user_id: uuid.UUID) -> None:
    if not await _can_publish(session, user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role may not publish to this project")


async def _lock_view(session, project_id: uuid.UUID, user_id: uuid.UUID) -> LockView | None:
    from app.modules.collaboration_locks.service import CollabLockService

    lock = await CollabLockService(session).get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)
    if lock is None:
        return None
    return LockView(held_by=lock.user_name, mine=lock.user_id == user_id, expires_at=lock.expires_at)


@router.get("/projects/{project_id}/context")
async def project_context(
    project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, request: Request, response: Response
) -> dict:
    from app.modules.projects.models import Project

    await require_project(principal, project_id, session)
    project = await session.get(Project, project_id)
    latest = (
        await session.execute(
            select(DesignRevision)
            .where(DesignRevision.project_id == project_id, DesignRevision.status.in_(VISIBLE))
            .order_by(DesignRevision.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    lock = await _lock_view(session, project_id, principal.user_id)
    brief = await current_brief(session, project_id)
    ai = await build_profile(session, principal.user_id, request.client.host if request.client else None)
    # The block can carry the user's own key: no cache may keep it.
    response.headers["Cache-Control"] = "no-store"
    await session.commit()
    return {
        "schema": "ddc-context/1",
        "link_versions": list(LINK_VERSIONS),
        "project": {
            "id": str(project.id),
            "name": project.name,
            "country": (project.country_code or None),
            "currency": (project.currency or None),
            "locale": project.locale or "en",
        },
        "permissions": {
            "can_publish": await _can_publish(session, principal.user_id),
            "can_accept": await _can_accept(session, principal.user_id, project),
            "can_generate": True,
        },
        "lock": None if lock is None else lock.model_dump(mode="json"),
        "latest_revision": None
        if latest is None
        else {"revision_id": str(latest.id), "number": latest.number, "status": latest.status},
        "brief": brief,
        "ai": ai,
    }


@router.get("/projects/{project_id}/access")
async def project_access(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    """What the signed-in user may do here and who holds the editing lock; the acceptance screen reads it."""
    from app.modules.projects.models import Project

    await require_project(principal, project_id, session)
    project = await session.get(Project, project_id)
    lock = await _lock_view(session, project_id, principal.user_id)
    return {
        "can_accept": (not principal.via_link) and await _can_accept(session, principal.user_id, project),
        "currency": project.currency or None,
        "lock": None if lock is None else lock.model_dump(mode="json"),
    }


# ── Lock (ERP collaboration locks, one per project) ─────────────────────────


async def _acquire(project_id: uuid.UUID, principal, session, *, renew: bool = False) -> LockView:
    from app.modules.collaboration_locks.service import CollabLockService, LockConflictError

    await require_project(principal, project_id, session)
    await _require_publisher(session, principal.user_id)
    if not renew:
        from .jobs import active_job

        # The server worker holds the model for its run; the same person's editor must not slip in beside it.
        if await active_job(session, project_id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"message": "Project is being edited", "held_by": "generation job"}
            )
    if renew:
        # A heartbeat extends a lock the caller still holds; a lost one must show as lost, not be re-taken.
        held = await _lock_view(session, project_id, principal.user_id)
        if held is None or not held.mine or as_aware(held.expires_at) <= now_utc():
            raise HTTPException(status.HTTP_409_CONFLICT, "lock lost")
    try:
        lock = await CollabLockService(session).acquire(
            entity_type=LOCK_ENTITY, entity_id=project_id, user_id=principal.user_id, ttl_seconds=LOCK_TTL_S
        )
    except LockConflictError as exc:
        await session.rollback()
        c = exc.conflict
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "Project is being edited",
                "held_by": c.current_holder_name,
                "expires_at": c.expires_at.isoformat(),
            },
        ) from exc
    await session.commit()
    return LockView(held_by=lock.user_name, mine=True, expires_at=lock.expires_at)


@router.post("/projects/{project_id}/lock", response_model=LockView)
async def take_lock(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> LockView:
    return await _acquire(project_id, principal, session)


@router.post("/projects/{project_id}/lock/heartbeat", response_model=LockView)
async def renew_lock(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> LockView:
    return await _acquire(project_id, principal, session, renew=True)


@router.delete("/projects/{project_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
async def release_lock(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    from app.modules.collaboration_locks.service import CollabLockService
    from app.modules.projects.models import Project

    await require_project(principal, project_id, session)
    svc = CollabLockService(session)
    lock = await svc.get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)
    if lock is not None:
        holder = lock.user_id
        if holder != principal.user_id:
            project = await session.get(Project, project_id)
            if not await _can_accept(session, principal.user_id, project):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the holder or a manager may release")
        await svc.release(lock_id=lock.id, user_id=holder)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def holds_lock(session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    view = await _lock_view(session, project_id, user_id)
    return view is not None and view.mine


# ── Revisions (contract §8, §9) ─────────────────────────────────────────────


async def _ingest(
    session, background: BackgroundTasks, project_id: uuid.UUID, principal, pkg, upload, work_dir: Path
) -> DesignRevision:
    from sqlalchemy import delete

    from app.modules.projects.models import Project

    from . import revisions as rv

    manifest = pkg.manifest
    revision_id = uuid.UUID(manifest.revision_id)
    await rv.sweep_stale_uploads(session, project_id, get_design_settings().revision_stale_upload_seconds)
    if await session.get(DesignRevision, revision_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This revision was already uploaded")
    latest = await rv.design_tip(session, project_id)
    parent_id = uuid.UUID(manifest.parent_revision_id) if manifest.parent_revision_id else None
    if (latest.id if latest else None) != parent_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "parent_revision_id must be the newest revision that is neither rejected nor archived "
                "nor an imported model",
                "latest_published": str(latest.id) if latest else None,
            },
        )
    project = await session.get(Project, project_id)
    project_name = project.name
    number = await rv.next_number(session, project_id)
    prefix = rv.storage_prefix(project_id, revision_id)
    # Claim first: the primary key and (project, number) decide between parallel uploads,
    # so only the winner ever writes to (or cleans) this prefix.
    session.add(
        DesignRevision(
            id=revision_id,
            project_id=project_id,
            number=number,
            parent_id=parent_id,
            status=UPLOADING,
            source_kind=manifest.source.kind,
            depth_level=manifest.depth_level,
            message=manifest.message or "",
            manifest=pkg.manifest_json,
            storage_prefix=prefix,
            package_sha256=upload.sha256_hex,
            package_bytes=upload.size,
            author_user_id=principal.user_id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This revision or revision number is being uploaded") from exc

    created: list[uuid.UUID] = []
    sheets = {
        f.path: pkg.files[f.path].read_bytes() for f in manifest.files if f.role == "sheet" and f.path in pkg.files
    }
    try:
        glb_copy = await rv.store_files(pkg, prefix, work_dir)
        model_id = await rv.register_bim_model(
            session,
            pkg=pkg,
            project_id=project_id,
            model_name=f"{project_name} R{number}",
            number=number,
            parent=latest,
            user_id=principal.user_id,
            glb_path=glb_copy,
            on_created=created.append,
        )
        done = await session.execute(
            update(DesignRevision)
            .where(DesignRevision.id == revision_id, DesignRevision.status == UPLOADING)
            .values(status="shared", bim_model_id=model_id)
        )
        if done.rowcount != 1:
            raise RuntimeError(f"upload claim on revision {revision_id} was lost")
        await session.commit()
    except BaseException:
        await session.rollback()
        await rv.discard_files(prefix)
        for mid in created:
            await rv.discard_model_files(project_id, mid)
        try:
            await session.execute(
                delete(DesignRevision).where(DesignRevision.id == revision_id, DesignRevision.status == UPLOADING)
            )
            await session.commit()
        except Exception:  # noqa: BLE001 - the stale sweep removes it later
            await session.rollback()
        raise
    background.add_task(rv.ensure_model_artifacts, str(project_id), str(model_id))
    shared = await session.get(DesignRevision, revision_id, populate_existing=True)
    try:
        from . import integration

        await integration.on_shared(session, shared, sheets)
        await session.commit()
    except Exception:  # noqa: BLE001 - the revision is in; drawings, task and notice are extras
        await session.rollback()
        log.warning("design: revision %s shared without its ERP side effects", revision_id, exc_info=True)
    return await session.get(DesignRevision, revision_id, populate_existing=True)


@router.post("/projects/{project_id}/revisions", response_model=RevisionView, status_code=status.HTTP_201_CREATED)
async def upload_revision(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    background: BackgroundTasks,
    package: UploadFile = File(...),
) -> RevisionView:
    from app.core.partner_pack._safe_extract import has_zip_magic
    from app.core.upload_streaming import stream_upload_to_temp

    await require_project(principal, project_id, session)
    await _require_publisher(session, principal.user_id)
    from app.modules.projects.models import Project

    from .drafts_api import edit_right

    if await edit_right(session, project_id) == "managers" and not await _can_accept(
        session, principal.user_id, await session.get(Project, project_id)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "On this project only managers create revisions")
    if not await holds_lock(session, project_id, principal.user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Take the project lock before publishing a revision")
    settings = get_design_settings()
    limits = Limits(
        max_unpacked=settings.revision_max_unpacked_bytes,
        max_json=settings.revision_max_json_bytes,
        max_glb_json=settings.revision_max_glb_json_bytes,
        max_rows=settings.revision_max_rows,
    )
    async with contextlib.AsyncExitStack() as stack:
        try:
            upload = await stack.enter_async_context(
                stream_upload_to_temp(package, max_bytes=settings.revision_max_bytes, suffix=".ddcrev")
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
        if not has_zip_magic(upload.head):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "package is not a zip archive")
        work_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="oe-ddcrev-")))
        try:
            pkg = await asyncio.to_thread(
                verify_package, upload.path, work_dir / "pkg", project_id=str(project_id), limits=limits
            )
        except PackageRejected as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        rev = await _ingest(session, background, project_id, principal, pkg, upload, work_dir)
    return RevisionView.of(rev)


@router.get("/projects/{project_id}/revisions", response_model=RevisionListResponse)
async def list_revisions(
    project_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> RevisionListResponse:
    await require_project(principal, project_id, session)
    where = (DesignRevision.project_id == project_id, DesignRevision.status.in_(VISIBLE))
    total = (await session.execute(select(func.count()).select_from(DesignRevision).where(*where))).scalar_one()
    rows = (
        (
            await session.execute(
                select(DesignRevision).where(*where).order_by(DesignRevision.number.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return RevisionListResponse(items=[RevisionView.of(r) for r in rows], total=total, offset=offset, limit=limit)


async def _revision(session, principal, revision_id: uuid.UUID) -> DesignRevision:
    rev = await session.get(DesignRevision, revision_id)
    if rev is None or rev.status not in VISIBLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    await require_project(principal, rev.project_id, session)
    return rev


@router.get("/revisions/{revision_id}", response_model=RevisionView)
async def get_revision(revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> RevisionView:
    return RevisionView.of(await _revision(session, principal, revision_id))


@router.get("/revisions/{revision_id}/files/{path:path}")
async def get_revision_file(
    revision_id: uuid.UUID, path: str, principal: PrincipalDep, session: SessionDep
) -> StreamingResponse:
    from app.core.storage import get_storage_backend

    from .revisions import file_key

    rev = await _revision(session, principal, revision_id)
    listed = {f["path"] for f in (rev.manifest or {}).get("files", [])}
    if path not in listed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not in this revision")
    backend = get_storage_backend()
    key = file_key(rev.storage_prefix, path)
    size = await backend.size(key)
    media = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return StreamingResponse(
        backend.open_stream(key),
        media_type=media,
        headers={"Content-Length": str(size), "Content-Disposition": f'attachment; filename="{Path(path).name}"'},
    )


async def _decide(session, principal, revision_id: uuid.UUID) -> DesignRevision:
    from app.modules.projects.models import Project

    rev = await _revision(session, principal, revision_id)
    # The editor publishes; acceptance is a manager's act inside the ERP, never through a link token.
    if principal.via_link:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Revisions are accepted or rejected in the ERP")
    project = await session.get(Project, rev.project_id)
    if not await _can_accept(session, principal.user_id, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may decide on revisions")
    if rev.status != "shared":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Revision is {rev.status}, not awaiting a decision")
    return rev


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


@router.post("/revisions/{revision_id}/accept", response_model=RevisionView)
async def accept_revision(
    revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, body: AcceptRequest | None = None
) -> RevisionView:
    rev = await _decide(session, principal, revision_id)
    try:
        await decide_accept(
            session,
            rev,
            principal.user_id,
            body.comment if body else None,
            change_order=body.change_order if body else None,
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Another revision was accepted at the same time") from exc
    return RevisionView.of(await session.get(DesignRevision, revision_id, populate_existing=True))


async def decide_accept(
    session, rev: DesignRevision, user_id: uuid.UUID, comment: str | None, *, change_order: bool | None = None
) -> None:
    """Publish a shared revision, recompute the estimate, the schedule and the take-off; per project setting draft a change order.

    Flushes; the caller commits or rolls back on 409.
    """
    from app.modules.bim_hub.models import BIMModel

    from . import change_orders as co
    from .imported import is_import_record
    from .revisions import mark_model

    revision_id, project_id, parent_id, model_id = rev.id, rev.project_id, rev.parent_id, rev.bim_model_id
    co_mode = await co.mode(session, project_id)
    make_order = co.wanted(co_mode, change_order)
    if make_order:
        await co.require_create(session, user_id)
    # The cost delta is taken before the positions move.
    snap = await co.snapshot(session, rev) if co_mode != "off" else None
    # Row lock on the published revision: a parallel accept waits here, then sees it archived.
    latest = (
        await session.execute(
            select(DesignRevision)
            .where(DesignRevision.project_id == project_id, DesignRevision.status == "published")
            .with_for_update()
        )
    ).scalar_one_or_none()
    # A design without a parent may replace a published import: designs never build on imports (contract §8).
    replaces_import = parent_id is None and latest is not None and is_import_record(latest.manifest)
    if (latest.id if latest else None) != parent_id and not replaces_import:
        raise _conflict("Another revision was accepted after this one was based")
    if latest is not None:
        archived = await session.execute(
            update(DesignRevision)
            .where(DesignRevision.id == latest.id, DesignRevision.status == "published")
            .values(status="archived")
        )
        if archived.rowcount != 1:
            raise _conflict("Another revision was accepted after this one was based")
    published = await session.execute(
        update(DesignRevision)
        .where(DesignRevision.id == revision_id, DesignRevision.status == "shared")
        .values(status="published", decided_by=user_id, decided_at=now_utc(), decision_comment=comment)
    )
    if published.rowcount != 1:
        raise _conflict("Revision was decided in the meantime")
    if latest is not None and latest.bim_model_id is not None and model_id is not None:
        # Chain the BIM model only now, so the BOQ follows accepted revisions only.
        await session.execute(
            update(BIMModel).where(BIMModel.id == model_id).values(parent_model_id=latest.bim_model_id)
        )
        await mark_model(session, latest.bim_model_id, "archived")
    await mark_model(session, model_id, "published")
    # Positions follow the accepted model in the same transaction: both change or neither.
    if model_id is not None:
        await recompute_on_accept(session, project_id, revision_id, model_id, user_id)
        await schedule_on_accept(session, project_id, revision_id, model_id, user_id)
        await procurement_on_accept(session, project_id, revision_id, model_id, user_id)
        await integration._best_effort(session, "element links", lambda: links.sync(session, project_id))
    if snap is not None:
        row = await co.store(session, rev, snap, user_id)
        if make_order:
            await co.create(session, rev, row, user_id)
    await integration.on_decided(session, rev, "accepted", user_id)
    await session.flush()


async def decide_reject(session, rev: DesignRevision, user_id: uuid.UUID, comment: str) -> None:
    """Reject a shared revision. Flushes; the caller commits or rolls back on 409."""
    from .revisions import mark_model

    rejected = await session.execute(
        update(DesignRevision)
        .where(DesignRevision.id == rev.id, DesignRevision.status == "shared")
        .values(status="rejected", decided_by=user_id, decided_at=now_utc(), decision_comment=comment)
    )
    if rejected.rowcount != 1:
        raise _conflict("Revision was decided in the meantime")
    await mark_model(session, rev.bim_model_id, "rejected")
    await integration.on_decided(session, rev, "rejected", user_id)
    await session.flush()


@router.post("/revisions/{revision_id}/reject", response_model=RevisionView)
async def reject_revision(
    revision_id: uuid.UUID, body: RejectRequest, principal: PrincipalDep, session: SessionDep
) -> RevisionView:
    rev = await _decide(session, principal, revision_id)
    try:
        await decide_reject(session, rev, principal.user_id, body.comment)
    except HTTPException:
        await session.rollback()
        raise
    await session.commit()
    return RevisionView.of(await session.get(DesignRevision, revision_id, populate_existing=True))


# ── Change orders from accepted revisions (R9) ──────────────────────────────


class ChangeOrderSettings(BaseModel):
    mode: Literal["off", "ask", "always"]


@router.get("/projects/{project_id}/change-orders/settings")
async def change_order_settings(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    from app.modules.projects.models import Project

    from . import change_orders as co

    await require_project(principal, project_id, session)
    project = await session.get(Project, project_id)
    manager = (not principal.via_link) and await _can_accept(session, principal.user_id, project)
    return {
        "mode": await co.mode(session, project_id),
        "can_change": manager,
        "can_create": manager and await co.can_create(session, principal.user_id),
    }


@router.put("/projects/{project_id}/change-orders/settings")
async def put_change_order_settings(
    project_id: uuid.UUID, body: ChangeOrderSettings, principal: PrincipalDep, session: SessionDep
) -> dict:
    from app.modules.projects.models import Project

    from . import change_orders as co

    await require_project(principal, project_id, session)
    project = await session.get(Project, project_id)
    if principal.via_link or not await _can_accept(session, principal.user_id, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may change this setting")
    await co.set_mode(session, project_id, body.mode, principal.user_id)
    await session.commit()
    return {"mode": body.mode}


async def _accepted(session, principal, revision_id: uuid.UUID) -> DesignRevision:
    rev = await session.get(DesignRevision, revision_id)
    if rev is None or rev.status == UPLOADING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    await require_project(principal, rev.project_id, session)
    return rev


@router.get("/revisions/{revision_id}/change-order")
async def revision_change_order(revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    from . import change_orders as co

    return await co.view(session, await _accepted(session, principal, revision_id))


@router.post("/revisions/{revision_id}/change-order")
async def create_revision_change_order(revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    """Draft the change order of an accepted revision later (declined at accept, or deleted); never a second one."""
    from app.modules.projects.models import Project

    from . import change_orders as co

    rev = await _accepted(session, principal, revision_id)
    project = await session.get(Project, rev.project_id)
    if principal.via_link or not await _can_accept(session, principal.user_id, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may create it")
    try:
        await co.create_later(session, rev, principal.user_id)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    return await co.view(session, rev)


from . import estimate_api  # noqa: E402 - needs `router` and `_can_accept` above

estimate_api.register(router, _can_accept)

from . import schedule_api  # noqa: E402

schedule_api.register(router, _can_accept)

from . import procurement_api  # noqa: E402

procurement_api.register(router, _can_accept)

from . import generate_api  # noqa: E402

generate_api.register(router, _can_edit_design)

from . import imported_api  # noqa: E402

imported_api.register(router, _require_publisher)

from .mcp import router as mcp_router  # noqa: E402

router.include_router(mcp_router)

from . import model_api  # noqa: E402

model_api.register(router, _can_edit_design)

from . import links_api  # noqa: E402

links_api.register(router, _can_accept)

from . import start_api  # noqa: E402

start_api.register(router)

from . import drafts_api  # noqa: E402

drafts_api.register(router, _can_accept, _can_publish, _acquire, holds_lock, _ingest)

from . import web_release_api  # noqa: E402

web_release_api.register(router)

from . import validation_api  # noqa: E402

validation_api.register(router)
