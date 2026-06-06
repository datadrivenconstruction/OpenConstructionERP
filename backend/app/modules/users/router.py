"""‌⁠‍Users & authentication API routes.

Endpoints:
    POST /auth/register         - Register new user
    POST /auth/login            - Login, get JWT tokens
    POST /auth/refresh          - Refresh access token
    POST /auth/forgot-password  - Request password reset token
    POST /auth/reset-password   - Reset password with token
    GET  /me                    - Current user profile
    PATCH /me                   - Update own profile
    POST /me/change-password    - Change own password
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
    GET  /                      - List users (admin/manager)
    GET  /{id}                  - Get user by ID (admin/manager)
    PATCH /{id}                 - Update user (admin only)
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.core.rate_limiter import client_identifier, login_limiter
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    SettingsDep,
)
from app.modules.users.schemas import (
    AdminUserCreate,
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    ChangePasswordRequest,
    FirstRunResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    OnboardingRequest,
    OnboardingResponse,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
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
    """‌⁠‍Request/response body for module preferences."""

    modules: dict[str, bool]


class CustomUnitsPayload(BaseModel):
    """‌⁠‍Request/response body for the user's per-tenant custom-unit catalogue.

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


# Whitelist of seeded demo accounts. Mirrors the spec list in
# ``app.main._seed_demo_account``; both must stay in sync - the test
# ``backend/tests/integration/test_demo_login_endpoint.py`` asserts this.
_DEMO_EMAIL_WHITELIST: frozenset[str] = frozenset(
    {
        "demo@openconstructionerp.com",
        "estimator@openconstructionerp.com",
        "manager@openconstructionerp.com",
    }
)


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
        * Disabled when ``SEED_DEMO`` env var is ``false`` / ``0`` / ``no``
          (production deployments).
        * Email must be in the whitelist of seeded demo accounts.
        * Account must exist and be active. Missing rows return 404 with a
          message that points the operator at the seed log.
        * Rate-limited per source IP (``demo_{ip}`` bucket) - the same
          login_limiter so repeated taps don't bypass throttling.
    """
    import os

    if os.environ.get("SEED_DEMO", "true").lower() in ("false", "0", "no"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo login is disabled on this server (SEED_DEMO=false).",
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


# Loopback hosts the desktop sidecar may legitimately be reached on. The Tauri
# shell talks to the bundled backend over 127.0.0.1, so anything else is a
# remote caller that must never reach the auto-login path.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def _running_under_pytest() -> bool:
    """True when the process is a pytest run (``request.client`` may be None).

    The ASGI test transport leaves ``request.client`` unset, so the loopback
    guard would otherwise reject every test call. We only relax the
    ``client is None`` case under this marker - a real server with a missing
    client (which would be unusual) is still rejected.
    """
    import os

    return "PYTEST_CURRENT_TEST" in os.environ


def _is_loopback_request(request: Request) -> bool:
    """Return True when the request originates from the local loopback.

    ``request.client`` is ``None`` under the ASGI test transport; that case is
    treated as loopback only when running under pytest, and rejected otherwise.
    """
    client = request.client
    if client is None:
        return _running_under_pytest()
    return client.host in _LOOPBACK_HOSTS


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
        return FirstRunResponse(
            desktop_mode=is_desktop,
            fresh_install=False,
            has_local_account=False,
            onboarding_completed=None,
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

    metadata["onboarding"] = {
        "company_type": data.company_type,
        "enabled_modules": data.enabled_modules,
        "interface_mode": data.interface_mode,
        "completed": data.completed,
    }

    # Also persist module preferences so the sidebar reflects the selection.
    # ``modules_for`` writes an explicit True/False for every known module and
    # forces core modules on, so a profile can never hide Projects/Settings/etc.
    from app.core.onboarding_presets import modules_for

    metadata["module_preferences"] = modules_for(data.enabled_modules)

    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)

    return OnboardingResponse(
        completed=data.completed,
        company_type=data.company_type,
        enabled_modules=data.enabled_modules,
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
