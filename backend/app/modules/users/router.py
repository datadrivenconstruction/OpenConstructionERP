"""Users & authentication API routes.

Endpoints:
    POST /auth/register         — Register new user
    POST /auth/login            — Login, get JWT tokens
    POST /auth/refresh          — Refresh access token
    POST /auth/forgot-password  — Request password reset token
    POST /auth/reset-password   — Reset password with token
    GET  /me                    — Current user profile
    PATCH /me                   — Update own profile
    POST /me/change-password    — Change own password
    GET  /me/api-keys           — List own API keys
    POST /me/api-keys           — Create API key
    DELETE /me/api-keys/{id}    — Revoke API key
    GET  /me/preferences         — Get regional preferences
    PATCH /me/preferences         — Update regional preferences
    GET  /me/module-preferences — Get saved module preferences
    PATCH /me/module-preferences — Save module preferences
    GET  /                      — List users (admin/manager)
    GET  /{id}                  — Get user by ID (admin/manager)
    PATCH /{id}                 — Update user (admin only)
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
    """Request/response body for module preferences."""

    modules: dict[str, bool]


class CustomUnitsPayload(BaseModel):
    """Request/response body for the user's per-tenant custom-unit catalogue.

    The unit dropdown in BOQ position / resource rows merges these with the
    locale-baseline units. Persisted in user metadata so the catalogue is
    available across browsers and sessions, not just the device localStorage.
    """

    units: list[str]


router = APIRouter()


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
# ``app.main._seed_demo_account``; both must stay in sync — the test
# ``backend/tests/integration/test_demo_login_endpoint.py`` asserts this.
_DEMO_EMAIL_WHITELIST: frozenset[str] = frozenset(
    {
        "demo@openestimator.io",
        "estimator@openestimator.io",
        "manager@openestimator.io",
    }
)


@router.post("/auth/demo-login/", response_model=TokenResponse)
@router.post(
    "/auth/demo-login", response_model=TokenResponse, include_in_schema=False
)
async def demo_login(
    data: DemoLoginRequest,
    request: Request,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Issue tokens for a seeded demo account without a password check.

    Why this exists: the seeder in ``app.main._seed_demo_account`` generates a
    fresh ``secrets.token_urlsafe(16)`` for every new install (BUG-D01 — no
    hardcoded credential is shipped) and persists it to a 0600 credentials
    file. The frontend's "Demo login" button cannot read that file, so on a
    fresh install the documented ``DemoPass1234!`` stopped working and users
    saw "Demo login failed. Please try again." This endpoint accepts the
    demo email *only*, looks the row up, and issues the same JWT pair as the
    regular login — without ever asking for the random password.

    Hard guards:
        * Disabled when ``SEED_DEMO`` env var is ``false`` / ``0`` / ``no``
          (production deployments).
        * Email must be in the whitelist of seeded demo accounts.
        * Account must exist and be active. Missing rows return 404 with a
          message that points the operator at the seed log.
        * Rate-limited per source IP (``demo_{ip}`` bucket) — the same
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
        # Same generic 401 as a wrong password — avoid leaking whether the
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
    ``/{user_id}`` route — FastAPI matches in source order.
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

    # Also persist module preferences so sidebar picks them up
    module_prefs: dict[str, bool] = {}
    from app.core.onboarding_presets import _ALL_MODULES

    for mod_key in _ALL_MODULES:
        module_prefs[mod_key] = mod_key in data.enabled_modules
    metadata["module_preferences"] = module_prefs

    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)

    return OnboardingResponse(
        completed=data.completed,
        company_type=data.company_type,
        enabled_modules=data.enabled_modules,
        interface_mode=data.interface_mode,
    )


@router.get("/onboarding-presets/")
async def get_onboarding_presets() -> list[dict[str, Any]]:
    """Return all available company-type presets for the onboarding wizard.

    Public endpoint (no auth required) — the presets are non-sensitive.
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
    limit: int = Query(default=50, ge=1, le=100),
    is_active: bool | None = None,
) -> list[UserResponse]:
    """List all users (admin/manager only).

    Demo-mode privacy: when ``OE_DEMO_MODE=true`` is set in the environment
    (only on the public hosted demo), personal data is stripped from the
    response — first/last names are blanked and the email's local part is
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
    await service.update_profile(user_id, metadata=metadata)
    return data
