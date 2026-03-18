"""User service — business logic for authentication and user management.

Stateless service layer. Handles:
- User registration & login (JWT)
- Password hashing & verification
- Token generation (access + refresh)
- API key management
- Role & permission resolution
"""

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.events import event_bus
from app.core.permissions import permission_registry
from app.modules.users.models import APIKey, User
from app.modules.users.repository import APIKeyRepository, UserRepository
from app.modules.users.schemas import (
    APIKeyCreate,
    APIKeyCreatedResponse,
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserCreate,
)

logger = logging.getLogger(__name__)


# ── Password utilities ─────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Token utilities ────────────────────────────────────────────────────────


def create_access_token(
    user: User,
    settings: Settings,
    extra_claims: dict | None = None,
) -> str:
    """Create a JWT access token for a user."""
    permissions = permission_registry.get_role_permissions(user.role)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "permissions": permissions,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user: User, settings: Settings) -> str:
    """Create a JWT refresh token for a user."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ── API Key utilities ──────────────────────────────────────────────────────


def generate_api_key() -> tuple[str, str, str]:
    """Generate an API key.

    Returns:
        (full_key, key_hash, key_prefix)
    """
    raw = secrets.token_urlsafe(32)
    full_key = f"oe_{raw}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:12]
    return full_key, key_hash, key_prefix


# ── Service class ──────────────────────────────────────────────────────────


class UserService:
    """Business logic for user operations."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.user_repo = UserRepository(session)
        self.api_key_repo = APIKeyRepository(session)

    # ── Registration ───────────────────────────────────────────────────

    async def register(self, data: UserCreate) -> User:
        """Register a new user.

        Raises HTTPException 409 if email already taken.
        First user automatically gets admin role.
        """
        if await self.user_repo.email_exists(data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        # First user becomes admin
        user_count = await self.user_repo.count()
        role = "admin" if user_count == 0 else data.role

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=role,
            locale=data.locale,
        )
        user = await self.user_repo.create(user)

        await event_bus.publish(
            "users.user.created",
            {"user_id": str(user.id), "email": user.email, "role": role},
            source_module="oe_users",
        )

        logger.info("User registered: %s (role=%s)", user.email, role)
        return user

    # ── Authentication ─────────────────────────────────────────────────

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate user and return JWT tokens.

        Raises HTTPException 401 on invalid credentials.
        """
        user = await self.user_repo.get_by_email(data.email)

        if user is None or not verify_password(data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )

        # Update last login
        await self.user_repo.update_fields(
            user.id,
            last_login_at=datetime.now(UTC),
        )

        access_token = create_access_token(user, self.settings)
        refresh_token = create_refresh_token(user, self.settings)

        await event_bus.publish(
            "users.user.logged_in",
            {"user_id": str(user.id)},
            source_module="oe_users",
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.jwt_expire_minutes * 60,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """Issue new token pair from a valid refresh token.

        Raises HTTPException 401 if refresh token is invalid.
        """
        from jose import JWTError

        try:
            payload = jwt.decode(
                refresh_token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            ) from exc

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        new_access = create_access_token(user, self.settings)
        new_refresh = create_refresh_token(user, self.settings)

        return TokenResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=self.settings.jwt_expire_minutes * 60,
        )

    # ── User management ────────────────────────────────────────────────

    async def get_user(self, user_id: uuid.UUID) -> User:
        """Get user by ID. Raises 404 if not found."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def update_profile(self, user_id: uuid.UUID, **fields: object) -> User:
        """Update user profile fields."""
        await self.user_repo.update_fields(user_id, **fields)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def change_password(
        self,
        user_id: uuid.UUID,
        data: ChangePasswordRequest,
    ) -> None:
        """Change user password. Verifies current password first."""
        user = await self.get_user(user_id)

        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        await self.user_repo.update_fields(
            user_id,
            hashed_password=hash_password(data.new_password),
        )
        logger.info("Password changed for user %s", user.email)

    async def list_users(
        self,
        offset: int = 0,
        limit: int = 50,
        is_active: bool | None = None,
    ) -> tuple[list[User], int]:
        """List users with pagination."""
        return await self.user_repo.list_all(offset=offset, limit=limit, is_active=is_active)

    # ── API Keys ───────────────────────────────────────────────────────

    async def create_api_key(
        self,
        user_id: uuid.UUID,
        data: APIKeyCreate,
    ) -> APIKeyCreatedResponse:
        """Create a new API key for a user."""
        full_key, key_hash, key_prefix = generate_api_key()

        expires_at = None
        if data.expires_in_days:
            expires_at = datetime.now(UTC) + timedelta(days=data.expires_in_days)

        api_key = APIKey(
            user_id=user_id,
            name=data.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            description=data.description,
            permissions=data.permissions,
            expires_at=expires_at,
        )
        api_key = await self.api_key_repo.create(api_key)

        logger.info("API key created: %s... for user %s", key_prefix, user_id)

        return APIKeyCreatedResponse(
            id=api_key.id,
            name=api_key.name,
            key_prefix=key_prefix,
            key=full_key,
            description=api_key.description,
            is_active=api_key.is_active,
            permissions=api_key.permissions,
            expires_at=api_key.expires_at,
            last_used_at=api_key.last_used_at,
            created_at=api_key.created_at,
        )

    async def list_api_keys(self, user_id: uuid.UUID) -> list[APIKey]:
        """List all API keys for a user."""
        return await self.api_key_repo.list_for_user(user_id)

    async def revoke_api_key(self, user_id: uuid.UUID, key_id: uuid.UUID) -> None:
        """Revoke (deactivate) an API key."""
        key = await self.api_key_repo.get_by_id(key_id)
        if key is None or key.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        await self.api_key_repo.deactivate(key_id)
        logger.info("API key revoked: %s", key.key_prefix)
