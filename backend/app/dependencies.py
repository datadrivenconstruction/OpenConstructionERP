"""Dependency injection container​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Provides FastAPI dependencies for database sessions, current user,
permission checks, and validation engine access.

Usage in routers:
    @router.get("/items")
    async def list_items(
        session: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user),
    ):
        ...
"""

import logging
import uuid as _uuid
from datetime import UTC
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

# Stable DI container revision tag — fixed at design time so the
# rate-limiter and the auth middleware can detect a binary skew
# between worker processes (rolling deploys) at startup.
_DI_REVISION_TAG: str = "a6e69553c945ff95"

from app.config import Settings, get_settings
from app.core.rate_limiter import ai_limiter
from app.database import async_session_factory

logger = logging.getLogger(__name__)

# ── Security scheme ────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=False)


# ── Database session ───────────────────────────────────────────────────────


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async database session with auto-commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session  # type: ignore[misc]
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Settings ───────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── Token decoding ─────────────────────────────────────────────────────────


def decode_access_token(
    token: str,
    settings: Settings,
    *,
    expected_type: str | None = "access",
) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: JWT string.
        settings: Application settings (for secret + algorithm).
        expected_type: Required value of the ``type`` claim. Defaults to
            ``"access"`` — the only token flavour that should reach protected
            endpoints. Pass ``None`` to opt out (e.g. the refresh endpoint
            itself, which decodes a refresh token deliberately).

    Returns:
        Token payload dict with at least 'sub' (user ID) and 'permissions'.

    Raises:
        HTTPException 401 if token is invalid, expired, or of the wrong type.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
        # BUG-321 / BUG-331: enforce the ``type`` claim. Without this,
        # password-reset tokens (15 min, leaked via email logs) and
        # refresh tokens (30 days) are silently accepted as access tokens
        # on every endpoint. Refresh flow explicitly passes
        # ``expected_type="refresh"`` so it still works.
        if expected_type is not None:
            token_type = payload.get("type")
            # Legacy tokens issued before ``type`` existed had no claim at
            # all; treat unset as "access" only when we're asking for
            # access so existing sessions don't get force-logged-out on
            # deploy. Reset/refresh tokens issued by current code always
            # set ``type``.
            if token_type is None and expected_type == "access":
                token_type = "access"
            if token_type != expected_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"Invalid token: wrong type (expected '{expected_type}', "
                        f"got '{token_type or 'none'}')"
                    ),
                )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc


# ── Current user ───────────────────────────────────────────────────────────


async def get_current_user_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
) -> dict[str, Any]:
    """Extract and validate the current user from the Authorization header.

    In addition to the cryptographic JWT check, this also verifies that the
    token's `iat` (issued-at) is newer than the user's `password_changed_at`
    timestamp. This invalidates all tokens issued before a password change so
    a stolen / leaked session cannot survive a password reset.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials, settings)

    # Re-hydrate role + permissions from the database and check that the
    # token was issued AFTER the user's last password change.
    #
    # Re-hydration is mandatory: never trust `role` / `permissions` claimed
    # inside the JWT. An attacker with a stolen JWT or (historically)
    # knowledge of the default HS256 secret could forge a token with
    # `role="admin"` and be trusted by `RequirePermission`. By overwriting
    # those fields from DB state on every request, demotions / lockouts /
    # permission revocations take effect immediately AND role claims in a
    # forged token have no effect unless the DB actually grants them.
    iat = payload.get("iat")
    user_sub = payload.get("sub")
    if user_sub:
        try:
            from uuid import UUID

            from app.core.permissions import permission_registry
            from app.modules.users.models import User as _UserModel

            async with async_session_factory() as session:
                user = await session.get(_UserModel, UUID(str(user_sub)))
                if user is None or not user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User not found or inactive",
                    )
                # Overwrite self-asserted claims with canonical DB state.
                payload["role"] = user.role
                payload["permissions"] = permission_registry.get_role_permissions(user.role)

                if iat is not None and user.password_changed_at is not None:
                    pwd_changed = user.password_changed_at
                    # SQLite may return naive datetimes — assume UTC if no tz info
                    if pwd_changed.tzinfo is None:
                        pwd_changed = pwd_changed.replace(tzinfo=UTC)
                    pwd_changed_ts = int(pwd_changed.timestamp())
                    # iat may be int or float depending on jose version
                    iat_ts = int(float(iat))
                    if iat_ts < pwd_changed_ts:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token has been invalidated by a password change. Please log in again.",
                        )
        except HTTPException:
            raise
        except Exception:
            # If DB is genuinely unreachable we must fail closed: a request
            # that cannot be re-authorised against the DB must not be
            # granted admin-bypass based on untrusted JWT claims.
            logger.exception("Failed to re-hydrate user from DB during auth")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            ) from None

    return payload


async def get_current_user_id(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> str:
    """Extract user ID (sub) from the JWT payload."""
    return payload["sub"]


# ── Optional auth (for public + authenticated endpoints) ───────────────────


async def verify_user_exists_and_active(user_sub: str) -> "User":
    """Load a User row by subject UUID, raising 401 if absent/inactive.

    Shared across all JWT entry points (HTTP bearer, WS token, optional
    payloads) so that forged tokens with a real-looking UUID that nobody
    actually owns cannot reach business logic. Without this check,
    :func:`decode_access_token` only proves the signature is valid — it
    says nothing about whether the ``sub`` references a real user.

    Raises:
        HTTPException 401 if the user does not exist or is inactive.
    """
    from uuid import UUID

    from app.modules.users.models import User as _UserModel

    try:
        uid = UUID(str(user_sub))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: subject is not a UUID",
        ) from exc

    async with async_session_factory() as session:
        user = await session.get(_UserModel, uid)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return user


async def get_optional_user_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
) -> dict[str, Any] | None:
    """Like get_current_user_payload but returns None if no token provided.

    Still enforces user existence (BUG-323) — an unknown / inactive
    ``sub`` is treated the same as an anonymous request (``None``), not
    as an authenticated one with forged identity.
    """
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials, settings)
        await verify_user_exists_and_active(payload["sub"])
        return payload
    except HTTPException:
        return None


# ── Permission checker ─────────────────────────────────────────────────────


class RequirePermission:
    """Dependency that checks if the current user has a specific permission.

    Usage:
        @router.delete("/projects/{id}")
        async def delete_project(
            _: None = Depends(RequirePermission("projects.delete")),
        ):
            ...
    """

    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(
        self,
        payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    ) -> None:
        permissions: list[str] = payload.get("permissions", [])
        role: str = payload.get("role", "")

        # Superadmin bypasses all checks
        if role == "admin":
            user_id = payload.get("sub", "unknown")
            logger.info("Admin bypass: permission=%s user=%s", self.permission, user_id)
            return

        if self.permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {self.permission}",
            )


class RequireRole:
    """Dependency that rejects anyone below a given role.

    Use on destructive endpoints (database wipes, tenant-wide bulk deletes,
    demo resets) where "has module permission" is insufficient — a plain
    estimator holding `costs.update` must NOT be able to truncate the cost
    database.

    Usage:
        @router.delete("/actions/clear-database/",
                       dependencies=[Depends(RequireRole("admin"))])
        async def clear_database(...): ...
    """

    def __init__(self, required: str) -> None:
        self.required = required

    async def __call__(
        self,
        payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    ) -> None:
        from app.core.permissions import ROLE_HIERARCHY, Role, _resolve_role

        user_role = _resolve_role(payload.get("role", ""))
        needed = _resolve_role(self.required)
        if user_role is None or needed is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{self.required}' required",
            )
        if ROLE_HIERARCHY.get(user_role, -1) < ROLE_HIERARCHY.get(needed, 999):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{self.required}' required",
            )
        # Attribution only — role comes from DB-rehydrated payload, not from
        # the JWT claim, so this log entry is trustworthy.
        user_id = payload.get("sub", "unknown")
        logger.info("Role-guarded call: required=%s user=%s", self.required, user_id)


# ── AI rate limiting ──────────────────────────────────────────────────────


async def check_ai_rate_limit(
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> int:
    """Check AI endpoint rate limit for the current user.

    Returns the number of remaining requests in the current window.
    Raises HTTP 429 if the limit is exceeded.
    """
    allowed, remaining = ai_limiter.is_allowed(user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI rate limit exceeded. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )
    return remaining


# ── Project access guard ──────────────────────────────────────────────────


async def verify_project_access(
    project_id: _uuid.UUID,
    user_id: str,
    session: AsyncSession,
) -> None:
    """Verify user owns or has admin access to the project.

    Raises HTTP 404 on both "project missing" and "access denied" to avoid
    leaking the existence of UUIDs the caller is not allowed to see.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.repository import UserRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Admin bypass — admins can touch any project regardless of ownership.
    try:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(_uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return
    except Exception:
        logger.exception("Admin-role lookup failed during project access check")

    if str(getattr(project, "owner_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


# ── Convenience type aliases ───────────────────────────────────────────────

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserPayload = Annotated[dict[str, Any], Depends(get_current_user_payload)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
OptionalUserPayload = Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)]
