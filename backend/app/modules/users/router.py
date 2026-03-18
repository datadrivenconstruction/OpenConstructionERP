"""Users & authentication API routes.

Endpoints:
    POST /auth/register     — Register new user
    POST /auth/login        — Login, get JWT tokens
    POST /auth/refresh      — Refresh access token
    GET  /me                — Current user profile
    PATCH /me               — Update own profile
    POST /me/change-password — Change own password
    GET  /me/api-keys       — List own API keys
    POST /me/api-keys       — Create API key
    DELETE /me/api-keys/{id} — Revoke API key
    GET  /                  — List users (admin/manager)
    GET  /{id}              — Get user by ID (admin/manager)
    PATCH /{id}             — Update user (admin only)
"""

import uuid

from fastapi import APIRouter, Depends, Query

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
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserAdminUpdate,
    UserCreate,
    UserMeResponse,
    UserResponse,
    UserUpdate,
)
from app.modules.users.service import UserService

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
async def login(data: LoginRequest, service: UserService = Depends(_get_service)) -> TokenResponse:
    """Authenticate and receive JWT tokens."""
    return await service.login(data)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest,
    service: UserService = Depends(_get_service),
) -> TokenResponse:
    """Refresh access token using a refresh token."""
    return await service.refresh_tokens(data.refresh_token)


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
