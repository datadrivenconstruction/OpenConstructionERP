"""Dependency injection container.

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
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

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


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Returns:
        Token payload dict with at least 'sub' (user ID) and 'permissions'.

    Raises:
        HTTPException 401 if token is invalid or expired.
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

    Returns the decoded JWT payload as a dict.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials, settings)


async def get_current_user_id(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> str:
    """Extract user ID (sub) from the JWT payload."""
    return payload["sub"]


# ── Optional auth (for public + authenticated endpoints) ───────────────────


async def get_optional_user_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
) -> dict[str, Any] | None:
    """Like get_current_user_payload but returns None if no token provided."""
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials, settings)
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
            logger.info(
                "Admin bypass: permission=%s user=%s", self.permission, user_id
            )
            return

        if self.permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {self.permission}",
            )


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


# ── Convenience type aliases ───────────────────────────────────────────────

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserPayload = Annotated[dict[str, Any], Depends(get_current_user_payload)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
OptionalUserPayload = Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)]
