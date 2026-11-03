# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM routes.

* ``scim_router`` is the RFC 7644 server, mounted by ``app.main`` at ``/scim/v2``. It
  authenticates with an API key that carries the ``scim`` scope and answers errors in
  the SCIM error schema.
* ``router`` is the admin API for Settings > Identity, mounted by the module loader at
  ``/api/v1/scim`` (JWT, admin role).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.dependencies import (
    ApiKeyPrincipal,
    CurrentUserId,
    RequireRole,
    SessionDep,
    SettingsDep,
    resolve_api_key_principal,
)
from app.modules.scim import schemas as sch
from app.modules.scim.repository import ScimRepository
from app.modules.scim.service import ScimError, ScimService
from app.modules.users.sso_enforce import enforced_domains

logger = logging.getLogger(__name__)

SCOPE = "scim"


class ScimResponse(JSONResponse):
    media_type = "application/scim+json"


def _error(status: int, detail: str, scim_type: str | None = None, headers: dict[str, str] | None = None) -> Response:
    return ScimResponse(ScimError(status, detail, scim_type).body(), status_code=status, headers=headers)


class ScimRoute(APIRoute):
    """Turns every failure on a SCIM route into the SCIM error schema."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except ScimError as exc:
                return _error(exc.status, exc.detail, exc.scim_type)
            except RequestValidationError:
                return _error(400, "Malformed request.", "invalidSyntax")
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
                keep = {k: v for k, v in (exc.headers or {}).items() if k.lower() == "www-authenticate"}
                return _error(exc.status_code, detail, None, keep or None)

        return handler


scim_router = APIRouter(route_class=ScimRoute, default_response_class=ScimResponse, tags=["SCIM"])


async def scim_principal(request: Request) -> ApiKeyPrincipal:
    """Bearer token (or X-API-Key) that is an active API key with the scim scope, owned by an admin.

    The token itself is never logged; only the key row is touched.
    """
    principal = await resolve_api_key_principal(request, allow_bearer=True)
    if SCOPE not in principal.scopes or principal.user.role != "admin":
        raise HTTPException(status_code=401, detail="Invalid SCIM token", headers={"WWW-Authenticate": "Bearer"})
    return principal


async def _service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    principal: ApiKeyPrincipal = Depends(scim_principal),
) -> ScimService:
    base = str(request.base_url).rstrip("/") + "/scim/v2"
    return ScimService(session, settings, principal.user.id, base)


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise ScimError(400, "Body is not valid JSON.", "invalidSyntax") from None
    if not isinstance(body, dict):
        raise ScimError(400, "Body must be a JSON object.", "invalidSyntax")
    return body


def _page(start_index: int, count: int) -> tuple[int, int]:
    return max(start_index, 1), min(max(count, 0), sch.MAX_RESULTS)


Svc = Depends(_service)


@scim_router.get("/ServiceProviderConfig")
async def service_provider_config(svc: ScimService = Svc) -> dict[str, Any]:
    return sch.service_provider_config(svc.base)


@scim_router.get("/ResourceTypes")
async def list_resource_types(svc: ScimService = Svc) -> dict[str, Any]:
    items = sch.resource_types(svc.base)
    return svc.list_response(items, len(items), 1)


@scim_router.get("/Schemas")
async def list_schemas(svc: ScimService = Svc) -> dict[str, Any]:
    items = sch.schemas(svc.base)
    return svc.list_response(items, len(items), 1)


# ── Users ──────────────────────────────────────────────────────────────


@scim_router.get("/Users")
async def list_users(
    svc: ScimService = Svc,
    filter: str | None = Query(default=None),  # noqa: A002 - the SCIM parameter name
    startIndex: int = Query(default=1),  # noqa: N803
    count: int = Query(default=sch.MAX_RESULTS),
) -> dict[str, Any]:
    start, size = _page(startIndex, count)
    return await svc.list_users(filter, start, size)


@scim_router.post("/Users", status_code=201)
async def create_user(request: Request, svc: ScimService = Svc) -> Response:
    resource, created = await svc.create_user(await _json(request))
    return ScimResponse(
        resource, status_code=201 if created else 200, headers={"Location": resource["meta"]["location"]}
    )


@scim_router.get("/Users/{user_id}")
async def get_user(user_id: str, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.get_user(user_id)


@scim_router.put("/Users/{user_id}")
async def replace_user(user_id: str, request: Request, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.replace_user(user_id, await _json(request))


@scim_router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.patch_user(user_id, await _json(request))


@scim_router.delete("/Users/{user_id}", status_code=204)
async def delete_user(user_id: str, svc: ScimService = Svc) -> Response:
    await svc.delete_user(user_id)
    return Response(status_code=204)


# ── Groups ─────────────────────────────────────────────────────────────


@scim_router.get("/Groups")
async def list_groups(
    svc: ScimService = Svc,
    filter: str | None = Query(default=None),  # noqa: A002
    startIndex: int = Query(default=1),  # noqa: N803
    count: int = Query(default=sch.MAX_RESULTS),
) -> dict[str, Any]:
    start, size = _page(startIndex, count)
    return await svc.list_groups(filter, start, size)


@scim_router.post("/Groups", status_code=201)
async def create_group(request: Request, svc: ScimService = Svc) -> Response:
    resource, created = await svc.create_group(await _json(request))
    return ScimResponse(
        resource, status_code=201 if created else 200, headers={"Location": resource["meta"]["location"]}
    )


@scim_router.get("/Groups/{group_id}")
async def get_group(group_id: str, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.get_group(group_id)


@scim_router.put("/Groups/{group_id}")
async def replace_group(group_id: str, request: Request, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.replace_group(group_id, await _json(request))


@scim_router.patch("/Groups/{group_id}")
async def patch_group(group_id: str, request: Request, svc: ScimService = Svc) -> dict[str, Any]:
    return await svc.patch_group(group_id, await _json(request))


@scim_router.delete("/Groups/{group_id}", status_code=204)
async def delete_group(group_id: str, svc: ScimService = Svc) -> Response:
    await svc.delete_group(group_id)
    return Response(status_code=204)


# ── Admin API (Settings > Identity) ────────────────────────────────────

router = APIRouter(tags=["SCIM admin"], dependencies=[Depends(RequireRole("admin"))])


def _source(user: Any) -> str:
    return user.provisioned_by or ("oidc" if user.oidc_sub else "local")


@router.get("/status/", response_model=sch.ScimStatus)
async def scim_status(session: SessionDep, settings: SettingsDep) -> sch.ScimStatus:
    """Everything the Identity panel shows, in one call."""
    repo = ScimRepository(session)
    users = await repo.list_known_users()
    groups, _ = await repo.list_groups()
    counts = await repo.member_counts()
    provisioned, last_change = await repo.provisioned_summary()
    return sch.ScimStatus(
        base_path="/scim/v2",
        users_provisioned=provisioned,
        last_change_at=last_change,
        allow_admin_groups=bool(settings.scim_allow_admin_groups),
        sso_enforced_domains=sorted(enforced_domains(settings)),
        users=[
            sch.ProvisionedUser(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                source=_source(u),
                external_id=u.external_id,
                last_sync_at=u.updated_at,
            )
            for u in users
        ],
        groups=[
            sch.GroupOut(
                id=g.id,
                display_name=g.display_name,
                external_id=g.external_id,
                role=g.role,
                member_count=counts.get(g.id, 0),
            )
            for g in groups
        ],
    )


@router.patch("/groups/{group_id}/", response_model=sch.GroupOut)
async def set_group_role(
    group_id: uuid.UUID,
    body: sch.GroupRoleUpdate,
    session: SessionDep,
    settings: SettingsDep,
    actor: CurrentUserId,
) -> sch.GroupOut:
    """Map a group to a role (admin only). The IdP can never do this."""
    svc = ScimService(session, settings, uuid.UUID(actor), "")
    try:
        group = await svc.set_group_role(group_id, body.role)
    except ScimError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    counts = await svc.repo.member_counts()
    return sch.GroupOut(
        id=group.id,
        display_name=group.display_name,
        external_id=group.external_id,
        role=group.role,
        member_count=counts.get(group.id, 0),
    )
