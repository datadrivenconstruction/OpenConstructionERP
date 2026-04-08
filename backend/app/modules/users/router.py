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

from app.core.rate_limiter import login_limiter
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    SettingsDep,
)
from app.modules.users.schemas import (
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


router = APIRouter()


def _get_service(session: SessionDep, settings: SettingsDep) -> UserService:
    return UserService(session, settings)


# ── Auth ───────────────────────────────────────────────────────────────────


@router.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(data: UserCreate, service: UserService = Depends(_get_service)) -> UserResponse:
    """Register a new user account."""
    user = await service.register(data)
    return UserResponse.model_validate(user)


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Authenticate and receive JWT tokens.

    Rate-limited per source IP to slow down credential stuffing attacks.
    """
    client_ip = request.client.host if request.client else "unknown"
    allowed, _remaining = login_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )
    return await service.login(data)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Refresh access token using a refresh token."""
    return await service.refresh_tokens(data.refresh_token)


@router.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    service: UserService = Depends(_get_service),
) -> ForgotPasswordResponse:
    """Request a password reset token.

    Always returns a success message to prevent email enumeration.
    In dev mode, the reset token is included in the response for testing.
    """
    return await service.forgot_password(data)


@router.post("/auth/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    data: ResetPasswordRequest,
    service: UserService = Depends(_get_service),
) -> ResetPasswordResponse:
    """Reset password using a valid reset token."""
    return await service.reset_password(data)


# ── Current user ───────────────────────────────────────────────────────────


@router.get("/me", response_model=UserMeResponse)
async def get_me(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserMeResponse:
    """Get current user profile with permissions."""
    from app.core.permissions import permission_registry

    user = await service.get_user(uuid.UUID(user_id))
    permissions = permission_registry.get_role_permissions(user.role)
    return UserMeResponse(
        **UserResponse.model_validate(user).model_dump(),
        permissions=permissions,
    )


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserResponse:
    """Update current user profile."""
    fields = data.model_dump(exclude_unset=True)
    user = await service.update_profile(uuid.UUID(user_id), **fields)
    return UserResponse.model_validate(user)


@router.post("/me/change-password", status_code=204)
async def change_password(
    data: ChangePasswordRequest,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> None:
    """Change current user's password."""
    await service.change_password(uuid.UUID(user_id), data)


# ── Regional Preferences ──────────────────────────────────────────────────


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserPreferencesResponse:
    """Get current user's regional preferences."""
    user = await service.get_user(uuid.UUID(user_id))
    return UserPreferencesResponse.model_validate(user)


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_my_preferences(
    data: UserPreferencesUpdate,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> UserPreferencesResponse:
    """Update current user's regional preferences."""
    user = await service.update_preferences(uuid.UUID(user_id), data)
    return UserPreferencesResponse.model_validate(user)


# ── API Keys ───────────────────────────────────────────────────────────────


@router.get("/me/api-keys", response_model=list[APIKeyResponse])
async def list_my_api_keys(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> list[APIKeyResponse]:
    """List current user's API keys."""
    keys = await service.list_api_keys(uuid.UUID(user_id))
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.post("/me/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
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


@router.get("/me/module-preferences", response_model=ModulePreferencesPayload)
async def get_module_preferences(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> ModulePreferencesPayload:
    """Get saved module visibility preferences for the current user."""
    user = await service.get_user(uuid.UUID(user_id))
    metadata: dict[str, Any] = user.metadata_ or {}
    prefs: dict[str, bool] = metadata.get("module_preferences", {})
    return ModulePreferencesPayload(modules=prefs)


@router.patch("/me/module-preferences", response_model=ModulePreferencesPayload)
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


# ── Onboarding ────────────────────────────────────────────────────────────────


@router.get("/me/onboarding", response_model=OnboardingResponse)
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


@router.post("/me/onboarding", response_model=OnboardingResponse)
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


@router.get("/onboarding-presets")
async def get_onboarding_presets() -> list[dict[str, Any]]:
    """Return all available company-type presets for the onboarding wizard.

    Public endpoint (no auth required) — the presets are non-sensitive.
    """
    from app.core.onboarding_presets import get_all_presets

    return get_all_presets()


# ── Admin: User management ─────────────────────────────────────────────────


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
    """List all users (admin/manager only)."""
    users, _ = await service.list_users(offset=offset, limit=limit, is_active=is_active)
    return [UserResponse.model_validate(u) for u in users]


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
