# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO routes, mounted by the module loader at ``/api/v1/sso``.

Public: provider list for the login page, SAML metadata / login / ACS, OIDC start / callback
and the hand-off exchange. Admin (JWT, admin role): provider CRUD under ``/providers/``.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.dependencies import CurrentUserId, RequireRole, SessionDep, SettingsDep
from app.modules.sso import schemas as sch
from app.modules.sso.saml import (
    REQUEST_COOKIE,
    REQUEST_COOKIE_TTL,
    build_sp_metadata,
    cookie_path,
    saml_available,
    sign_request_id,
    verify_request_id,
)
from app.modules.sso.service import SsoService, sso_error
from app.modules.users.schemas import TokenResponse

router = APIRouter(tags=["sso"])
_admin = [Depends(RequireRole("admin"))]


def _service(session: SessionDep, settings: SettingsDep) -> SsoService:
    # The public origin comes from configuration, never from the request's Host header.
    return SsoService(session, settings, settings.resolved_frontend_url)


# ── Public ─────────────────────────────────────────────────────────────


@router.get("/capabilities/", response_model=sch.Capabilities)
async def capabilities() -> sch.Capabilities:
    """Whether the optional SAML extra is installed (the UI hides SAML when not)."""
    return sch.Capabilities(saml_available=saml_available())


@router.get("/providers/", response_model=sch.PublicProviders)
async def public_providers(email: str = "", svc: SsoService = Depends(_service)) -> sch.PublicProviders:
    """Enabled providers for the login page; with *email*, only those routed to its domain."""
    has_saml = saml_available()
    domain = email.rpartition("@")[2].strip().lower() if "@" in email else ""
    out: list[sch.PublicProvider] = []
    for p in await svc.repo.list_providers(enabled_only=True):
        if p.protocol == "saml" and not has_saml:
            continue
        if domain and p.email_domains and domain not in p.email_domains:
            continue
        login = f"/api/v1/sso/saml/{p.slug}/login/" if p.protocol == "saml" else None
        out.append(sch.PublicProvider(slug=p.slug, display_name=p.display_name, protocol=p.protocol, login_url=login))
    return sch.PublicProviders(saml_available=has_saml, providers=out)


@router.get("/saml/{slug}/metadata/")
async def saml_metadata(slug: str, svc: SsoService = Depends(_service)) -> Response:
    p = await svc.get_enabled(slug, "saml")
    xml = build_sp_metadata(sp_entity_id=svc.sp_entity_id(p), acs_url=svc.acs_url(p))
    return Response(content=xml, media_type="application/samlmetadata+xml")


@router.get("/saml/{slug}/login/")
async def saml_login(slug: str, svc: SsoService = Depends(_service)) -> RedirectResponse:
    """SP-initiated login: redirect the browser to the IdP with a fresh AuthnRequest."""
    p = await svc.get_enabled(slug, "saml")
    url, request_id = await svc.saml_login_url(p, relay_state=slug)
    response = RedirectResponse(url, status_code=302)
    # SameSite=None: the IdP returns the browser with a cross-site POST to the ACS.
    response.set_cookie(
        REQUEST_COOKIE,
        sign_request_id(svc.settings, p.slug, request_id),
        max_age=int(REQUEST_COOKIE_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="none",
        path=cookie_path(svc.acs_url(p)),
    )
    return response


@router.post("/saml/{slug}/acs/")
async def saml_acs(
    slug: str,
    request: Request,
    svc: SsoService = Depends(_service),
    saml_response: str = Form(alias="SAMLResponse", max_length=400_000),
) -> RedirectResponse:
    """Assertion Consumer Service (HTTP-POST). Redirects to the app with a 60-second hand-off code."""
    complete = f"{svc.base}/auth/sso/complete"
    try:
        p = await svc.get_enabled(slug, "saml")
        request_id = verify_request_id(svc.settings, slug, request.cookies.get(REQUEST_COOKIE))
        code = await svc.saml_acs(p, saml_response, request_id)
    except HTTPException as exc:
        err = exc.detail.get("code", "failed") if isinstance(exc.detail, dict) else "failed"
        await svc.session.rollback()
        return RedirectResponse(f"{complete}?error={quote(err)}", status_code=303)
    response = RedirectResponse(f"{complete}#code={quote(code)}", status_code=303)
    response.delete_cookie(REQUEST_COOKIE, path=cookie_path(svc.acs_url(p)))
    return response


@router.post("/handoff/", response_model=TokenResponse)
async def handoff(body: sch.HandoffIn, svc: SsoService = Depends(_service)) -> TokenResponse:
    """Exchange the single-use hand-off code from the ACS redirect for tokens."""
    return await svc.redeem_handoff(body.code)


@router.get("/oidc/{slug}/start/", response_model=sch.OidcStart)
async def oidc_start(slug: str, svc: SsoService = Depends(_service)) -> sch.OidcStart:
    return await svc.oidc_start(await svc.get_enabled(slug, "oidc"))


@router.post("/oidc/{slug}/callback/", response_model=TokenResponse)
async def oidc_callback(slug: str, body: sch.OidcCallback, svc: SsoService = Depends(_service)) -> TokenResponse:
    return await svc.oidc_callback(await svc.get_enabled(slug, "oidc"), body)


# ── Admin ──────────────────────────────────────────────────────────────


@router.get("/providers/admin/", response_model=list[sch.ProviderOut], dependencies=_admin)
async def list_providers(svc: SsoService = Depends(_service)) -> list[sch.ProviderOut]:
    return [svc.to_out(p) for p in await svc.repo.list_providers()]


@router.post("/providers/admin/", response_model=sch.ProviderOut, status_code=201, dependencies=_admin)
async def create_provider(
    body: sch.ProviderCreate, user_id: CurrentUserId, svc: SsoService = Depends(_service)
) -> sch.ProviderOut:
    p = await svc.create(body, uuid.UUID(user_id))
    return svc.to_out(p)


async def _get(svc: SsoService, provider_id: uuid.UUID):  # noqa: ANN202
    p = await svc.repo.get(provider_id)
    if p is None:
        raise sso_error(404, "provider_not_found", "Provider not found.")
    return p


@router.patch("/providers/admin/{provider_id}", response_model=sch.ProviderOut, dependencies=_admin)
async def update_provider(
    provider_id: uuid.UUID, body: sch.ProviderUpdate, user_id: CurrentUserId, svc: SsoService = Depends(_service)
) -> sch.ProviderOut:
    p = await svc.update(await _get(svc, provider_id), body, uuid.UUID(user_id))
    return svc.to_out(p)


@router.delete("/providers/admin/{provider_id}", status_code=204, dependencies=_admin)
async def delete_provider(
    provider_id: uuid.UUID, user_id: CurrentUserId, svc: SsoService = Depends(_service)
) -> Response:
    await svc.delete(await _get(svc, provider_id), uuid.UUID(user_id))
    return Response(status_code=204)
