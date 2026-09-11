# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Users & authentication API routes.

Endpoints:
    POST /auth/register         - Register new user
    POST /auth/login            - Login, get JWT tokens
    POST /auth/refresh          - Refresh access token
    POST /auth/forgot-password  - Request password reset token
    POST /auth/reset-password   - Reset password with token
    GET  /me                    - Current user profile
    PATCH /me                   - Update own profile
    DELETE /me                  - Erase own account (GDPR Art. 17)
    POST /me/change-password    - Change own password
    GET  /me/sessions           - List own login sessions
    DELETE /me/sessions/{sid}   - Sign out one of them
    GET  /me/api-keys           - List own API keys
    POST /me/api-keys           - Create API key
    DELETE /me/api-keys/{id}    - Revoke API key
    GET  /me/preferences         - Get regional preferences
    PATCH /me/preferences         - Update regional preferences
    GET  /me/module-preferences - Get saved module preferences
    PATCH /me/module-preferences - Save module preferences
    GET  /me/sidebar-preferences - Get sidebar visibility preferences
    PUT  /me/sidebar-preferences - Save sidebar visibility preferences
    GET  /me/dashboard-layout    - Get dashboard widget layout
    PUT  /me/dashboard-layout    - Save dashboard widget layout
    GET  /me/tour-state          - Get per-tour dismiss / completion state
    PUT  /me/tour-state          - Save per-tour dismiss / completion state
    GET  /me/info-blocks         - Get module info-card collapse state
    PUT  /me/info-blocks         - Save module info-card collapse state
    GET  /                      - List users (admin/manager)
    GET  /{id}                  - Get user by ID (admin/manager)
    PATCH /{id}                 - Update user (admin only)
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS
from app.core.rate_limiter import client_identifier, login_limiter
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    RequireRole,
    SessionDep,
    SettingsDep,
)
from app.modules.users.schemas import (
    AdminUserCreate,
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    DeleteAccountResponse,
    FirstRunResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    OnboardingRequest,
    OnboardingResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SessionListResponse,
    SessionResponse,
    TokenResponse,
    UserAdminUpdate,
    UserCreate,
    UserMeResponse,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    UserResponse,
    UserUpdate,
)
from app.modules.users.service import UserService


class ModulePreferencesPayload(BaseModel):
    """Request/response body for module preferences."""

    modules: dict[str, bool]


class CustomUnitsPayload(BaseModel):
    """Request/response body for the user's per-tenant custom-unit catalogue.

    The unit dropdown in BOQ position / resource rows merges these with the
    locale-baseline units. Persisted in user metadata so the catalogue is
    available across browsers and sessions, not just the device localStorage.
    """

    units: list[str]


class SidebarPreferencesPayload(BaseModel):
    """Request/response body for the user's sidebar visibility preferences.

    ``hidden_modules`` is the list of NavItem ``to`` routes the user has
    chosen to hide from the sidebar via the menu editor. Persisted per-user
    in the ``metadata_`` JSON column so the choice follows the user across
    browsers and devices, not just a single localStorage bucket.
    """

    hidden_modules: list[str]


class InfoBlocksPayload(BaseModel):
    """Request/response body for the user's module info-card collapse state.

    Every module page carries a ``DismissibleInfo`` card ("what this page is
    for and how it connects"). A user can collapse it into a small button next
    to "How it works" so it stops taking room, and re-open it when needed.
    ``blocks`` maps each card's stable ``storageKey`` to whether the user has
    collapsed it (``true``) or explicitly kept it open (``false``). Missing
    keys fall back to the default (expanded). Persisted per-user in the
    ``metadata_`` JSON column so the preference follows the user across
    browsers and devices, exactly like sidebar and dashboard preferences.
    """

    blocks: dict[str, bool]


class DashboardLayoutPayload(BaseModel):
    """Request/response body for the user's dashboard widget layout.

    Mirrors the localStorage bucket ``oe.dashboard-layout`` so the
    customisation follows the user across browsers and devices, not just
    a single localStorage bucket.

    * ``order`` - widget ids in the user's preferred top-to-bottom order.
      Unknown ids are dropped client-side at render time via
      ``reconcileOrder`` so a removed widget never corrupts a saved layout.
    * ``hidden`` - widget ids the user has hidden via the customise panel.
    """

    order: list[str]
    hidden: list[str]


class TourStateEntry(BaseModel):
    """Per-tour persistence record - when a user dismissed / completed a tour.

    Both timestamps are ISO-8601 strings (``datetime.now(UTC).isoformat()``).
    Either may be ``None`` - Skip writes only ``dismissed_at``; Finish writes
    both. ProductTour reads the bucket on mount and skips auto-open when
    either timestamp is set.
    """

    dismissed_at: str | None = None
    completed_at: str | None = None


class TourStatePayload(BaseModel):
    """Request/response body for the user's per-tour completion state.

    ``tours`` maps a TourId (``global``, ``boq``, ``bim``, ``geo``,
    ``propdev``, ``dashboard``, ``accommodation``) to a small persistence
    record. Mirrors localStorage keys ``oe.tour_completed`` and
    ``oe.tour_completed.<tourId>`` so the dismissed/completed state follows
    the user across browsers and devices.
    """

    tours: dict[str, TourStateEntry]


router = APIRouter(tags=["users"])


def _get_service(session: SessionDep, settings: SettingsDep) -> UserService:
    return UserService(session, settings)


# ── Auth ───────────────────────────────────────────────────────────────────


@router.post("/auth/register/", response_model=UserResponse, status_code=201)
@router.post("/auth/register", response_model=UserResponse, status_code=201, include_in_schema=False)
async def register(
    data: UserCreate,
    request: Request,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Register a new user account. Rate-limited per IP."""
    client_ip = client_identifier(request)
    allowed, _remaining = login_limiter.is_allowed(f"reg_{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )
    user = await service.register(
        data,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent", ""),
        referrer=request.headers.get("referer", ""),
    )
    return UserResponse.model_validate(user)


# NOTE on the dual-route registration: every auth endpoint below is mounted
# at BOTH the trailing-slash and the bare path. Issue #42 retest showed that
# some Docker quickstart proxy setups (and bare curl users) hit
# `POST /api/v1/users/auth/login` (no slash) and got a 404 because FastAPI's
# default 307 redirect doesn't preserve POST bodies. Registering both forms
# is more robust than relying on slash redirects to behave correctly through
# every reverse proxy in the wild.


class DemoLoginRequest(BaseModel):
    """Request body for the password-free demo login.

    Only the e-mail field is honoured; the value MUST match one of the seeded
    demo accounts (whitelist enforced server-side).
    """

    email: str


# Whitelist of seeded demo accounts, taken from the one module that names
# them. It still has to match the spec list in ``app.main._seed_demo_account``,
# and ``backend/tests/integration/test_demo_login_endpoint.py`` asserts that.
_DEMO_EMAIL_WHITELIST: frozenset[str] = DEMO_ACCOUNT_EMAILS


@router.post("/auth/demo-login/", response_model=TokenResponse)
@router.post("/auth/demo-login", response_model=TokenResponse, include_in_schema=False)
async def demo_login(
    data: DemoLoginRequest,
    request: Request,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Issue tokens for a seeded demo account without a password check.

    Why this exists: the seeder in ``app.main._seed_demo_account`` generates a
    fresh ``secrets.token_urlsafe(16)`` for every new install (BUG-D01 - no
    hardcoded credential is shipped) and persists it to a 0600 credentials
    file. The frontend's "Demo login" button cannot read that file, so on a
    fresh install the documented ``DemoPass1234!`` stopped working and users
    saw "Demo login failed. Please try again." This endpoint accepts the
    demo email *only*, looks the row up, and issues the same JWT pair as the
    regular login - without ever asking for the random password.

    Hard guards:
        * Disabled whenever demo seeding is off - either ``SEED_DEMO`` is
          ``false`` / ``0`` / ``no`` or the persisted first-run choice opted
          out (``seed_demo_enabled()``). Production deployments that never
          seeded demo data therefore cannot demo-login.
        * Email must be in the whitelist of seeded demo accounts.
        * Account must exist and be active. Missing rows return 404 with a
          message that points the operator at the seed log.
        * Rate-limited per source IP (``demo_{ip}`` bucket) - the same
          login_limiter so repeated taps don't bypass throttling.
    """
    from app.core.demo_login import demo_login_enabled
    from app.core.demo_seed import seed_demo_enabled

    # Admin switch (Settings screen) takes precedence and gets its own clear
    # 403 so the user understands it was turned off deliberately, distinct from
    # a server that simply never seeded demo data (404 below). The service-layer
    # sink re-checks this, so this early guard is a clean message, not the only
    # line of defence.
    if not demo_login_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo login is currently switched off by the administrator.",
        )

    if not seed_demo_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo login is disabled on this server.",
        )

    email = (data.email or "").strip().lower()
    if email not in _DEMO_EMAIL_WHITELIST:
        # Same generic 401 as a wrong password - avoid leaking whether the
        # email is in the whitelist via an attacker-distinguishable response.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    client_ip = client_identifier(request)
    allowed, _remaining = login_limiter.is_allowed(f"demo_{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )

    return await service.demo_login(email)


# ── Admin: public demo-login switch ─────────────────────────────────────────


class DemoLoginSettingResponse(BaseModel):
    """Admin view of the public demo-login switch.

    * ``enabled`` - the admin's explicit on/off choice, persisted server-side
      (a small JSON file in the data dir, so no database migration).
    * ``seeded`` - whether demo accounts exist on this server at all
      (``seed_demo_enabled()``). When ``False`` the demo login stays
      unavailable even with ``enabled`` on, so the UI can explain why.
    * ``effective`` - what the sign-in screen actually honours:
      ``enabled AND seeded``.
    """

    enabled: bool
    seeded: bool
    effective: bool


class DemoLoginSettingUpdate(BaseModel):
    """Admin payload to switch the public demo login on or off."""

    enabled: bool


def _demo_login_setting_state() -> DemoLoginSettingResponse:
    """Assemble the current demo-login switch state for the admin API."""
    from app.core.demo_login import demo_login_enabled
    from app.core.demo_seed import seed_demo_enabled

    enabled = demo_login_enabled()
    seeded = seed_demo_enabled()
    return DemoLoginSettingResponse(enabled=enabled, seeded=seeded, effective=enabled and seeded)


@router.get(
    "/auth/demo-login/settings/",
    response_model=DemoLoginSettingResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.get(
    "/auth/demo-login/settings",
    response_model=DemoLoginSettingResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def get_demo_login_setting() -> DemoLoginSettingResponse:
    """Admin only: read whether the public demo login is currently enabled."""
    return _demo_login_setting_state()


@router.put(
    "/auth/demo-login/settings/",
    response_model=DemoLoginSettingResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/auth/demo-login/settings",
    response_model=DemoLoginSettingResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_demo_login_setting(body: DemoLoginSettingUpdate) -> DemoLoginSettingResponse:
    """Admin only: switch the public demo login on or off.

    Persisted immediately (no restart). The sign-in screen re-reads the state
    on its next load, and the demo-login code path refuses new demo sign-ins as
    soon as this is turned off.
    """
    from app.core.demo_login import set_demo_login_enabled

    set_demo_login_enabled(body.enabled)
    return _demo_login_setting_state()


@router.post("/auth/login/", response_model=TokenResponse)
@router.post("/auth/login", response_model=TokenResponse, include_in_schema=False)
async def login(
    data: LoginRequest,
    request: Request,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Authenticate and receive JWT tokens.

    Rate-limited per source IP to slow down credential stuffing attacks.
    """
    client_ip = client_identifier(request)
    allowed, _remaining = login_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )
    return await service.login(data)


@router.post("/auth/refresh/", response_model=TokenResponse)
@router.post("/auth/refresh", response_model=TokenResponse, include_in_schema=False)
async def refresh(
    data: RefreshRequest,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Refresh access token using a refresh token."""
    return await service.refresh_tokens(data.refresh_token)


# ── Desktop first-run / bootstrap ───────────────────────────────────────────

# These two endpoints are mounted at ``/api/v1/auth/`` (NOT
# ``/api/v1/users/auth/``) so they sit on a short, stable, app-level auth path
# the desktop shell can call without knowing the users-module mount point. The
# module loader only auto-mounts the module ``router`` (at ``/api/v1/users``),
# so these live on a dedicated ``desktop_auth_router`` that ``app.main``
# explicitly includes at the ``/api/v1/auth`` prefix.
desktop_auth_router = APIRouter(tags=["auth"])


def _is_loopback_request(request: Request) -> bool:
    """Return True when the request originates from the local loopback.

    The check itself lives in ``app.core.loopback`` because the desktop
    shutdown endpoint guards itself with the same question, and a security
    guard kept in two copies is one that can be right in one of them.
    """
    from app.core.loopback import is_loopback_request

    return is_loopback_request(request)


@desktop_auth_router.get("/first-run/", response_model=FirstRunResponse)
@desktop_auth_router.get("/first-run", response_model=FirstRunResponse, include_in_schema=False)
async def first_run(
    service: UserService = Depends(_get_service),
) -> FirstRunResponse:
    """Report desktop first-run status. Public, no auth, never errors.

    The desktop shell calls this on the ``/login`` route to decide whether to
    silently auto-provision and log in the local workspace owner. Any failure
    degrades gracefully to ``desktop_mode=False`` / ``fresh_install=False`` so
    the client simply shows the normal login form.
    """
    from app.config import desktop_mode

    is_desktop = desktop_mode()
    try:
        return await service.first_run_status(is_desktop=is_desktop)
    except Exception:  # noqa: BLE001 - this endpoint must never error
        try:
            from app.core.demo_login import demo_login_enabled
            from app.core.demo_seed import seed_demo_enabled

            demo_enabled = seed_demo_enabled() and demo_login_enabled()
        except Exception:  # noqa: BLE001 - degrade to the safe default
            demo_enabled = True
        return FirstRunResponse(
            desktop_mode=is_desktop,
            fresh_install=False,
            has_local_account=False,
            onboarding_completed=None,
            demo_enabled=demo_enabled,
        )


@desktop_auth_router.post("/desktop-bootstrap/", response_model=TokenResponse)
@desktop_auth_router.post("/desktop-bootstrap", response_model=TokenResponse, include_in_schema=False)
async def desktop_bootstrap(
    request: Request,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Auto-provision / re-authenticate the local desktop workspace owner.

    Guards (all return 403 with a clear detail string when violated):
      * the backend must be running in desktop mode (sidecar / frozen),
      * the request must originate from the loopback interface,
      * the workspace must be a fresh install OR already have the local owner
        (never lets a caller into a workspace that has real registered users
        but no local owner).

    On success returns the exact same token shape as ``POST /auth/login``.
    """
    from app.config import desktop_mode

    if not desktop_mode():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Desktop bootstrap is only available in the desktop app.",
        )

    if not _is_loopback_request(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Desktop bootstrap is only available from the local machine.",
        )

    status_ = await service.first_run_status(is_desktop=True)
    if not (status_.fresh_install or status_.has_local_account):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Desktop bootstrap is not allowed: this workspace already has registered users.",
        )

    return await service.desktop_bootstrap()


@router.post("/auth/forgot-password/", response_model=ForgotPasswordResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    service: UserService = Depends(_get_service),
) -> ForgotPasswordResponse:
    """Request a password reset token. Rate-limited per IP.

    Always returns a success message to prevent email enumeration.
    The token is never included in the HTTP response.
    """
    client_ip = client_identifier(request)
    allowed, _remaining = login_limiter.is_allowed(f"pwd_{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )
    return await service.forgot_password(data)


@router.post("/auth/reset-password/", response_model=ResetPasswordResponse)
async def reset_password(
    data: ResetPasswordRequest,
    service: UserService = Depends(_get_service),
) -> ResetPasswordResponse:
    """Reset password using a valid reset token."""
    return await service.reset_password(data)


# ── Current user ───────────────────────────────────────────────────────────


@router.get("/me/", response_model=UserMeResponse)
@router.get("/me", response_model=UserMeResponse, include_in_schema=False)
async def get_me(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserMeResponse:
    """Get current user profile with permissions.

    BUG-API01: the bare-path ``/me`` (no trailing slash) is registered alongside
    ``/me/`` so requests against ``GET /api/v1/users/me`` resolve to "current
    user" instead of falling through to ``/{user_id}`` and 422-failing UUID
    parsing on the literal ``"me"``. Both must be declared *before* the
    ``/{user_id}`` route - FastAPI matches in source order.
    """
    from app.core.permissions import permission_registry

    user = await service.get_user(uuid.UUID(user_id))
    permissions = permission_registry.get_role_permissions(user.role)
    return UserMeResponse(
        **UserResponse.model_validate(user).model_dump(),
        permissions=permissions,
    )


@router.patch("/me/", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Update current user profile."""
    fields = data.model_dump(exclude_unset=True)

    # Map schema field 'metadata' to model column 'metadata_'. The
    # self-service profile update must NOT be able to clobber the whole
    # metadata blob: it holds admin-managed and security-relevant keys
    # (per-module access, desktop-owner flag, registration audit). Merge the
    # user-supplied keys onto the existing blob and strip the protected ones
    # so a user PATCHing /me cannot wipe admin-set module_access or grant
    # themselves local_desktop.
    if "metadata" in fields:
        incoming = fields.pop("metadata") or {}
        _protected = {
            "module_access",
            "module_preferences",
            "local_desktop",
            "registration",
            "custom_role_name",
        }
        existing_user = await service.get_user(uuid.UUID(user_id))
        merged = dict(getattr(existing_user, "metadata_", None) or {})
        for key, value in incoming.items():
            if key in _protected:
                continue
            merged[key] = value
        fields["metadata_"] = merged

    user = await service.update_profile(uuid.UUID(user_id), **fields)
    return UserResponse.model_validate(user)


@router.post("/me/change-password/", response_model=TokenResponse)
async def change_password(
    data: ChangePasswordRequest,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Change current user's password and return fresh JWT tokens.

    After a successful password change the old tokens are invalidated
    (via ``password_changed_at``).  The response contains a new token
    pair so the client can stay authenticated without a forced re-login.
    """
    return await service.change_password(uuid.UUID(user_id), data)


@router.get("/me/sessions/", response_model=SessionListResponse)
@router.get("/me/sessions", response_model=SessionListResponse, include_in_schema=False)
async def list_my_sessions(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: UserService = Depends(_get_service),
) -> SessionListResponse:
    """List the caller's own login sessions, newest first.

    Self-service only: the owner comes from the caller's own token and the
    route takes no user id, so this can never list somebody else's sessions.
    Needs no permission beyond being authenticated, for the same reason
    changing your own password needs none.

    Sessions that have already expired are omitted; revoked ones are kept, so
    ending a session shows up as ended rather than as a row that vanished.

    ``current`` is computed here rather than in the service, because it is a
    property of the request and not of the row: the same session is current to
    the device holding it and not current to every other device listing it.
    """
    caller_sid = payload.get("sid")
    sessions = await service.list_sessions(uuid.UUID(user_id))
    items = [
        SessionResponse(
            sid=s.sid,
            created_at=s.created_at,
            expires_at=s.expires_at,
            last_used_at=s.last_used_at,
            revoked_at=s.revoked_at,
            # ``caller_sid`` is None for a token minted before sessions
            # existed. ``None == s.sid`` is False for every row, which is the
            # honest answer: such a token belongs to no row on file.
            current=s.sid == caller_sid,
        )
        for s in sessions
    ]
    return SessionListResponse(items=items, total=len(items), offset=0, limit=len(items))


@router.delete("/me/sessions/{sid}/", status_code=status.HTTP_204_NO_CONTENT)
@router.delete("/me/sessions/{sid}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def revoke_my_session(
    sid: str,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> None:
    """Sign out one of the caller's own sessions, leaving the others alone.

    This is the point of the whole mechanism: before it, the only way to end a
    session was to change the password, which ends every session the person
    has, on every device. Now the laptop left in a hotel can be signed out
    from the phone.

    The owner is taken from the caller's token and never from the path, and
    the service scopes its write by both, so quoting somebody else's session
    id gets a 404 rather than ending their session. A session id that does not
    exist and one that belongs to another user answer identically on purpose,
    so this route cannot be used to find out which session ids are real.

    Revoking the session the caller is currently using is allowed and simply
    signs them out, which is what "sign out everywhere else, including here"
    has to mean.
    """
    await service.revoke_session(uuid.UUID(user_id), sid)


@router.delete("/me/", response_model=DeleteAccountResponse)
@router.delete("/me", response_model=DeleteAccountResponse, include_in_schema=False)
async def delete_me(
    data: DeleteAccountRequest,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> DeleteAccountResponse:
    """Erase the current user's own account (GDPR Art. 17, right to erasure).

    Self-service only: it always targets the authenticated caller (``user_id``
    comes from the token, the body has no id), so a caller can never erase
    another user through this route.

    The request body must confirm intent so an account is never erased by
    accident or by a replayed token alone: a password account re-supplies its
    ``current_password``; a passwordless / SSO account types ``DELETE`` into
    ``confirm``. A bad confirmation returns 400.

    Erasure anonymises the row in place rather than hard-deleting it, so the
    user's projects and audit/activity history keep resolving while every
    personal field is nulled, the password hash is invalidated, all API keys
    are revoked and the account can no longer log in. The last active admin of
    a workspace cannot erase itself (409) so the workspace is never orphaned.

    Declared before the ``/{user_id}`` admin routes so ``DELETE /users/me``
    resolves here and not as a UUID-path 422 on the literal ``"me"``.
    """
    await service.erase_account(uuid.UUID(user_id), data)
    return DeleteAccountResponse()


# ── Regional Preferences ──────────────────────────────────────────────────


@router.get("/me/preferences/", response_model=UserPreferencesResponse)
async def get_my_preferences(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserPreferencesResponse:
    """Get current user's regional preferences."""
    user = await service.get_user(uuid.UUID(user_id))
    return UserPreferencesResponse.model_validate(user)


@router.patch("/me/preferences/", response_model=UserPreferencesResponse)
async def update_my_preferences(
    data: UserPreferencesUpdate,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserPreferencesResponse:
    """Update current user's regional preferences."""
    user = await service.update_preferences(uuid.UUID(user_id), data)
    return UserPreferencesResponse.model_validate(user)


# ── API Keys ───────────────────────────────────────────────────────────────


@router.get("/me/api-keys/", response_model=list[APIKeyResponse])
async def list_my_api_keys(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> list[APIKeyResponse]:
    """List current user's API keys."""
    keys = await service.list_api_keys(uuid.UUID(user_id))
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.post("/me/api-keys/", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    data: APIKeyCreate,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> APIKeyCreatedResponse:
    """Create a new API key. The full key is shown only in this response."""
    return await service.create_api_key(uuid.UUID(user_id), data)


@router.delete("/me/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> None:
    """Revoke (deactivate) an API key."""
    await service.revoke_api_key(uuid.UUID(user_id), key_id)


# ── Module Preferences ────────────────────────────────────────────────────


@router.get("/me/module-preferences/", response_model=ModulePreferencesPayload)
async def get_module_preferences(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> ModulePreferencesPayload:
    """Get saved module visibility preferences for the current user."""
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    prefs: dict[str, bool] = metadata.get("module_preferences", {})
    return ModulePreferencesPayload(modules=prefs)


@router.patch("/me/module-preferences/", response_model=ModulePreferencesPayload)
async def save_module_preferences(
    data: ModulePreferencesPayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> ModulePreferencesPayload:
    """Save module visibility preferences for the current user.

    Stores the mapping in the user's metadata JSON under key ``module_preferences``.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["module_preferences"] = data.modules
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return ModulePreferencesPayload(modules=data.modules)


# ── Sidebar Preferences ───────────────────────────────────────────────────


@router.get("/me/sidebar-preferences/", response_model=SidebarPreferencesPayload)
async def get_sidebar_preferences(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> SidebarPreferencesPayload:
    """Get the current user's sidebar visibility preferences.

    Returns an empty list when the user has never customised the sidebar.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    raw = metadata.get("sidebar_hidden_modules", [])
    hidden = [str(r) for r in raw if isinstance(r, str) and r.strip()]
    return SidebarPreferencesPayload(hidden_modules=hidden)


@router.put("/me/sidebar-preferences/", response_model=SidebarPreferencesPayload)
async def save_sidebar_preferences(
    data: SidebarPreferencesPayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> SidebarPreferencesPayload:
    """Upsert sidebar visibility preferences for the current user.

    Stores the hidden-route list in the user's ``metadata_`` JSON column under
    key ``sidebar_hidden_modules``. Sanitises the payload: trims whitespace,
    drops empties / duplicates, caps each route at 128 chars and the list at
    500 entries so a runaway client can't bloat the JSON column.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in data.hidden_modules:
        if not isinstance(raw, str):
            continue
        route = raw.strip()[:128]
        if route and route not in seen:
            seen.add(route)
            cleaned.append(route)
        if len(cleaned) >= 500:
            break

    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["sidebar_hidden_modules"] = cleaned
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return SidebarPreferencesPayload(hidden_modules=cleaned)


# ── Dashboard Layout ──────────────────────────────────────────────────────


def _sanitise_widget_ids(raw_list: object) -> list[str]:
    """Trim, drop empties / non-strings / duplicates, cap each id at 64 chars.

    The widget registry today has ~22 ids; we cap the list at 200 entries
    to leave room for future widgets while making sure a runaway client
    can't bloat the JSON column.
    """
    if not isinstance(raw_list, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in raw_list:
        if not isinstance(raw, str):
            continue
        wid = raw.strip()[:64]
        if wid and wid not in seen:
            seen.add(wid)
            cleaned.append(wid)
        if len(cleaned) >= 200:
            break
    return cleaned


@router.get("/me/dashboard-layout/", response_model=DashboardLayoutPayload)
async def get_dashboard_layout(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> DashboardLayoutPayload:
    """Get the current user's dashboard widget layout.

    Returns ``{order: [], hidden: []}`` (defaults) when the user has never
    customised the dashboard - the client's ``reconcileOrder`` helper then
    falls back to the canonical registry order.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    layout: dict[str, Any] = metadata.get("dashboard_layout") or {}
    return DashboardLayoutPayload(
        order=_sanitise_widget_ids(layout.get("order", [])),
        hidden=_sanitise_widget_ids(layout.get("hidden", [])),
    )


@router.put("/me/dashboard-layout/", response_model=DashboardLayoutPayload)
async def save_dashboard_layout(
    data: DashboardLayoutPayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> DashboardLayoutPayload:
    """Upsert the current user's dashboard widget layout.

    Stores ``{order, hidden}`` in the user's ``metadata_`` JSON column under
    key ``dashboard_layout``. Sanitises both lists: trims, drops empties /
    duplicates / non-strings, caps each id at 64 chars and the list at 200
    entries so a runaway client can't bloat the JSON column.

    Pydantic enforces ``list[str]`` at the schema boundary - non-list bodies
    or non-string array items 422 before reaching this handler.
    """
    cleaned_order = _sanitise_widget_ids(data.order)
    cleaned_hidden = _sanitise_widget_ids(data.hidden)

    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["dashboard_layout"] = {
        "order": cleaned_order,
        "hidden": cleaned_hidden,
    }
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return DashboardLayoutPayload(order=cleaned_order, hidden=cleaned_hidden)


# ── Tour State ────────────────────────────────────────────────────────────


# Mirror of ``TourId`` from frontend/src/shared/ui/ProductTour.tsx. Tours
# outside this whitelist are silently dropped on PUT so a typo / a
# malicious client can't pollute the JSON column with arbitrary keys.
_KNOWN_TOUR_IDS: frozenset[str] = frozenset(
    {
        "global",
        "boq",
        "accommodation",
        "bim",
        "geo",
        "propdev",
        "dashboard",
    },
)


def _sanitise_tour_state(raw: object) -> dict[str, dict[str, str | None]]:
    """Clean the inbound tour-state map.

    Drops unknown tour ids; trims/caps ISO-8601 strings at 40 chars; coerces
    bad shapes to ``None``. Returns a plain dict so it can be JSON-serialised
    directly into ``metadata_``.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str | None]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        tour_id = key.strip()[:64]
        if tour_id not in _KNOWN_TOUR_IDS:
            continue
        if not isinstance(value, dict):
            continue
        dismissed = value.get("dismissed_at")
        completed = value.get("completed_at")
        out[tour_id] = {
            "dismissed_at": (str(dismissed)[:40] if isinstance(dismissed, str) and dismissed.strip() else None),
            "completed_at": (str(completed)[:40] if isinstance(completed, str) and completed.strip() else None),
        }
    return out


@router.get("/me/tour-state/", response_model=TourStatePayload)
async def get_tour_state(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> TourStatePayload:
    """Get the current user's per-tour dismiss / completion state.

    Returns ``{"tours": {}}`` (defaults) when the user has never run a tour -
    ProductTour then falls back to the localStorage flag for first-login auto-
    open. Tours outside the canonical id set are filtered out on read so an
    obsolete tour id never leaks back to the client.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    stored = _sanitise_tour_state(metadata.get("tour_state"))
    return TourStatePayload(
        tours={tid: TourStateEntry(**entry) for tid, entry in stored.items()},
    )


@router.put("/me/tour-state/", response_model=TourStatePayload)
async def save_tour_state(
    data: TourStatePayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> TourStatePayload:
    """Upsert tour-state for the current user.

    Stores ``{tour_id: {dismissed_at, completed_at}}`` in the user's
    ``metadata_`` JSON column under key ``tour_state``. Sanitises the
    payload: drops unknown tour ids, caps each timestamp at 40 chars so a
    runaway client can't bloat the JSON column.

    IDOR posture: writes the row keyed by ``CurrentUserId`` only - the body
    has no ``user_id`` field, so a caller can never write to another user's
    tour state via this endpoint.
    """
    raw_tours = {
        tid: {
            "dismissed_at": entry.dismissed_at,
            "completed_at": entry.completed_at,
        }
        for tid, entry in data.tours.items()
    }
    cleaned = _sanitise_tour_state(raw_tours)

    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["tour_state"] = cleaned
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return TourStatePayload(
        tours={tid: TourStateEntry(**entry) for tid, entry in cleaned.items()},
    )


# ── Custom Units ──────────────────────────────────────────────────────────


@router.get("/me/custom-units/", response_model=CustomUnitsPayload)
async def get_custom_units(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> CustomUnitsPayload:
    """Get the user's saved custom unit catalogue."""
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    raw = metadata.get("custom_units", [])
    units = [str(u) for u in raw if isinstance(u, str) and u.strip()]
    return CustomUnitsPayload(units=units)


@router.patch("/me/custom-units/", response_model=CustomUnitsPayload)
async def save_custom_units(
    data: CustomUnitsPayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> CustomUnitsPayload:
    """Replace the user's saved custom-unit catalogue.

    Sanitises the payload: trims whitespace, drops empties / duplicates,
    caps each unit at 32 chars and the list at 200 entries so a runaway
    client can't bloat the JSON column.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in data.units:
        if not isinstance(raw, str):
            continue
        u = raw.strip()[:32]
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)
        if len(cleaned) >= 200:
            break

    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["custom_units"] = cleaned
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return CustomUnitsPayload(units=cleaned)


# ── Module Info Blocks ────────────────────────────────────────────────────


def _sanitise_info_blocks(raw: object) -> dict[str, bool]:
    """Clean the inbound info-block map into ``{storageKey: collapsed}``.

    Drops non-string keys, trims and caps each key at 128 chars, coerces
    values to bool, and caps the map at 500 entries so a runaway client can't
    bloat the JSON column. Mirrors the sanitisation the sidebar and dashboard
    preference endpoints already apply.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        storage_key = key.strip()[:128]
        if not storage_key:
            continue
        cleaned[storage_key] = bool(value)
        if len(cleaned) >= 500:
            break
    return cleaned


@router.get("/me/info-blocks/", response_model=InfoBlocksPayload)
async def get_info_blocks(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> InfoBlocksPayload:
    """Get the user's module info-card collapse state.

    Returns ``{"blocks": {}}`` when the user has never collapsed a card - the
    client then treats every card as expanded (the default) and falls back to
    any legacy per-browser localStorage flag for a one-time migration.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    return InfoBlocksPayload(blocks=_sanitise_info_blocks(metadata.get("info_blocks")))


@router.put("/me/info-blocks/", response_model=InfoBlocksPayload)
async def save_info_blocks(
    data: InfoBlocksPayload,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> InfoBlocksPayload:
    """Upsert the user's module info-card collapse state.

    Stores ``{storageKey: collapsed}`` in the user's ``metadata_`` JSON column
    under key ``info_blocks``. Sanitises the payload (trims keys, caps lengths,
    coerces values to bool) so a runaway client can't bloat the column.

    IDOR posture: writes the row keyed by ``CurrentUserId`` only - the body has
    no ``user_id`` field, so a caller can never write another user's state.
    """
    cleaned = _sanitise_info_blocks(data.blocks)
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    metadata["info_blocks"] = cleaned
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    return InfoBlocksPayload(blocks=cleaned)


# ── Onboarding ────────────────────────────────────────────────────────────────


@router.get("/me/onboarding/", response_model=OnboardingResponse)
async def get_onboarding(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> OnboardingResponse:
    """Get onboarding state for the current user."""
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    onboarding: dict[str, Any] = metadata.get("onboarding", {})
    return OnboardingResponse(
        completed=onboarding.get("completed", False),
        company_type=onboarding.get("company_type"),
        company_size=onboarding.get("company_size"),
        enabled_modules=onboarding.get("enabled_modules", []),
        interface_mode=onboarding.get("interface_mode"),
    )


@router.post("/me/onboarding/", response_model=OnboardingResponse)
async def save_onboarding(
    data: OnboardingRequest,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> OnboardingResponse:
    """Save onboarding wizard choices.

    Stores the company type, enabled modules, and interface mode in the
    user's metadata JSON under the ``onboarding`` key.  Also syncs the
    chosen modules into ``module_preferences`` so the sidebar reflects
    the selection immediately.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})

    # "Full Enterprise" means the whole platform. Pin it to the backend's own
    # authoritative functional-module list rather than trusting whatever set the
    # client computed: if the client catalogue is even slightly behind the
    # server's module registry, the missing keys would be sent as "not chosen"
    # and ``modules_for`` would write an explicit False for them, silently
    # hiding live sidebar routes (BIM, Finance, CRM and the rest). Making the
    # server authoritative here closes that drift for good.
    from app.core.onboarding_presets import get_preset, get_size_preset, modules_for

    effective_modules = data.enabled_modules
    if data.company_type == "full_enterprise":
        full_enterprise = get_preset("full_enterprise")
        if full_enterprise is not None:
            effective_modules = list(full_enterprise.enabled_modules)
    elif data.company_type == "size_large":
        # "Large Enterprise" is the size-dimension twin of Full Enterprise: it
        # means the whole platform, so pin it to the server's authoritative
        # functional-module list for the same anti-drift reason as above.
        size_large = get_size_preset("size_large")
        if size_large is not None:
            effective_modules = list(size_large.enabled_modules)

    metadata["onboarding"] = {
        "company_type": data.company_type,
        "company_size": data.company_size,
        "enabled_modules": effective_modules,
        "interface_mode": data.interface_mode,
        "completed": data.completed,
    }

    # Also persist module preferences so the sidebar reflects the selection.
    # ``modules_for`` writes an explicit True/False for every known module and
    # forces core modules on, so a profile can never hide Projects/Settings/etc.
    metadata["module_preferences"] = modules_for(effective_modules)

    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)

    return OnboardingResponse(
        completed=data.completed,
        company_type=data.company_type,
        company_size=data.company_size,
        enabled_modules=effective_modules,
        interface_mode=data.interface_mode,
    )


@router.post("/me/onboarding/complete/", response_model=OnboardingResponse)
async def complete_onboarding(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> OnboardingResponse:
    """Flag onboarding as completed without rewriting the user's choices.

    Lightweight companion to ``save_onboarding``. The wizard calls this from
    every exit path that has no module selection to persist (skip, the
    "explore all modules" link, the apply-a-pack flow), so the per-user
    ``completed`` flag is set reliably on the server and the dashboard
    first-run redirect can trust it. Existing ``company_type`` /
    ``enabled_modules`` / ``interface_mode`` and the user's
    ``module_preferences`` are left untouched.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    onboarding: dict[str, Any] = dict(metadata.get("onboarding") or {})
    onboarding["completed"] = True
    metadata["onboarding"] = onboarding
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)

    return OnboardingResponse(
        completed=True,
        company_type=onboarding.get("company_type"),
        company_size=onboarding.get("company_size"),
        enabled_modules=onboarding.get("enabled_modules", []),
        interface_mode=onboarding.get("interface_mode"),
    )


@router.delete("/me/onboarding/complete/", response_model=OnboardingResponse)
async def reset_onboarding(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> OnboardingResponse:
    """Reset onboarding to incomplete so the wizard can be re-run.

    Called from the Settings "restart onboarding" action and from the
    update-welcome dialog's "re-run setup" button.  Clears the per-user
    ``completed`` flag on the server while leaving all other onboarding
    choices (company_type, enabled_modules, etc.) intact.
    """
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = dict(user.metadata_ or {})
    onboarding: dict[str, Any] = dict(metadata.get("onboarding") or {})
    onboarding["completed"] = False
    metadata["onboarding"] = onboarding
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)

    return OnboardingResponse(
        completed=False,
        company_type=onboarding.get("company_type"),
        company_size=onboarding.get("company_size"),
        enabled_modules=onboarding.get("enabled_modules", []),
        interface_mode=onboarding.get("interface_mode"),
    )


@router.get("/onboarding-presets/")
async def get_onboarding_presets() -> list[dict[str, Any]]:
    """Return all available company-type presets for the onboarding wizard.

    Public endpoint (no auth required) - the presets are non-sensitive.
    """
    from app.core.onboarding_presets import get_all_presets

    return get_all_presets()


@router.get("/onboarding-presets/sizes/")
async def get_onboarding_size_presets() -> list[dict[str, Any]]:
    """Return all company-size presets for the onboarding wizard.

    Public endpoint (no auth required) - the presets are non-sensitive. A
    parallel dimension to ``/onboarding-presets/`` (company role): the size the
    user picks maps to the same ``module_preferences`` machinery, so the two
    endpoints share one response shape.
    """
    from app.core.onboarding_presets import get_all_size_presets

    return get_all_size_presets()


# ── Admin: User management ─────────────────────────────────────────────────


@router.post(
    "/",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("users.create"))],
)
@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("users.create"))],
    include_in_schema=False,
)
async def admin_create_user(
    data: AdminUserCreate,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Admin-only: create a user with an arbitrary role and active state.

    BUG-USERS-CREATE: distinct from ``/auth/register`` (open self-signup) so
    the admin can mint accounts in any role bypassing the
    "first-real-user-becomes-admin / subsequent users default to viewer"
    bootstrap policy. The ``AdminUserCreate`` schema enforces:
      - ``EmailStr`` email format,
      - password length >= 12 + the standard strong-password policy,
      - ``role`` constrained to a fixed Literal whitelist,
      - ``is_active`` defaulting to True (admin can opt for dormant).

    Anything else (e.g. ``role="god"``) is rejected by Pydantic with 422
    *before* it can reach the service layer.
    """
    user = await service.admin_create(data)
    return UserResponse.model_validate(user)


@router.get(
    "/",
    response_model=list[UserResponse],
    dependencies=[Depends(RequirePermission("users.list"))],
)
async def list_users(
    service: UserService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    # Directory/assignee pickers load the full active-user list in one call,
    # so the cap is generous (a hard 100 silently dropped assignees and made
    # ``?limit=200`` requests fail with 422). Rows are tiny; 500 covers any
    # realistic org without paging. Use ``offset`` for the rare larger directory.
    limit: int = Query(default=50, ge=1, le=500),
    is_active: bool | None = None,
) -> list[UserResponse]:
    """List all users (admin/manager only).

    Demo-mode privacy: when ``OE_DEMO_MODE=true`` is set in the environment
    (only on the public hosted demo), personal data is stripped from the
    response - first/last names are blanked and the email's local part is
    replaced with a hash. Only the email domain remains visible. This way
    the public demo can show registration counts without leaking PII from
    real users who signed up to try the product.
    """
    import os as _os

    users, _ = await service.list_users(offset=offset, limit=limit, is_active=is_active)
    responses = [UserResponse.model_validate(u) for u in users]

    if _os.environ.get("OE_DEMO_MODE", "").lower() in ("1", "true", "yes"):
        import hashlib as _hl

        def _scrub(r: UserResponse) -> UserResponse:
            data = r.model_dump()
            email = (data.get("email") or "").strip()
            if "@" in email:
                local, domain = email.split("@", 1)
                short = _hl.sha1(local.encode("utf-8")).hexdigest()[:6]
                data["email"] = f"user-{short}@{domain}"
            data["full_name"] = ""
            return UserResponse.model_validate(data)

        responses = [_scrub(r) for r in responses]
    return responses


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(RequirePermission("users.read"))],
)
async def get_user(
    user_id: uuid.UUID,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Get user by ID (admin/manager only)."""
    user = await service.get_user(user_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(RequirePermission("users.update"))],
)
async def update_user(
    user_id: uuid.UUID,
    data: UserAdminUpdate,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Update user (admin only)."""
    fields = data.model_dump(exclude_unset=True)
    user = await service.update_profile(user_id, **fields)
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}/",
    status_code=204,
    dependencies=[Depends(RequirePermission("users.delete"))],
)
@router.delete(
    "/{user_id}",
    status_code=204,
    include_in_schema=False,
    dependencies=[Depends(RequirePermission("users.delete"))],
)
async def admin_delete_user(
    user_id: uuid.UUID,
    actor_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> None:
    """Admin-only: delete (erase) another user's account.

    Until now an administrator could only deactivate an account (``PATCH`` with
    ``is_active=false``); the row and its email stayed on the books. This erases
    the account the same way the self-service path does: the row is anonymised
    in place so the user's projects and history keep resolving, but every
    personal field is stripped, the password is invalidated, all API keys are
    revoked and the account can no longer log in (issue #272).

    Self-targeting is refused with 400 so an admin deletes their own account
    through ``DELETE /users/me`` (which keeps its password confirmation), and the
    last active admin of a workspace cannot be erased (409) so it is never left
    without an administrator. Declared after the ``/me`` routes so that literal
    path still resolves to self-deletion.
    """
    await service.admin_erase_account(uuid.UUID(actor_id), user_id)


class ModuleAccessLevel(BaseModel):
    """Per-module access level for a user."""

    visible: bool = True
    access: str = "edit"  # none | view | edit | full


class UserModuleAccessPayload(BaseModel):
    """Module access configuration for a user."""

    modules: dict[str, ModuleAccessLevel] = {}
    custom_role_name: str | None = None


@router.get(
    "/{user_id}/module-access/",
    response_model=UserModuleAccessPayload,
    dependencies=[Depends(RequirePermission("users.read"))],
)
async def get_user_module_access(
    user_id: uuid.UUID,
    service: UserService = Depends(_get_service),
) -> UserModuleAccessPayload:
    """Get per-module access settings for a user (admin/manager)."""
    user = await service.get_user(user_id)
    metadata = user.metadata_ if hasattr(user, "metadata_") else (user.metadata or {})
    access_data = metadata.get("module_access", {})
    custom_role = metadata.get("custom_role_name")
    modules = {}
    for mod_id, cfg in access_data.items():
        if isinstance(cfg, dict):
            modules[mod_id] = ModuleAccessLevel(**cfg)
        else:
            modules[mod_id] = ModuleAccessLevel(visible=bool(cfg))
    return UserModuleAccessPayload(modules=modules, custom_role_name=custom_role)


@router.patch(
    "/{user_id}/module-access/",
    response_model=UserModuleAccessPayload,
    dependencies=[Depends(RequirePermission("users.update"))],
)
async def set_user_module_access(
    user_id: uuid.UUID,
    data: UserModuleAccessPayload,
    service: UserService = Depends(_get_service),
) -> UserModuleAccessPayload:
    """Set per-module access settings for a user (admin only).

    Also syncs module_preferences for sidebar visibility.
    """
    user = await service.get_user(user_id)
    metadata = dict(user.metadata_ if hasattr(user, "metadata_") else (user.metadata or {}))
    # Store full access config
    access_data = {}
    module_prefs = {}
    for mod_id, cfg in data.modules.items():
        access_data[mod_id] = cfg.model_dump()
        module_prefs[mod_id] = cfg.visible
    metadata["module_access"] = access_data
    metadata["module_preferences"] = module_prefs
    if data.custom_role_name is not None:
        metadata["custom_role_name"] = data.custom_role_name
    await service.update_profile(user_id, metadata_=metadata)
    return data
