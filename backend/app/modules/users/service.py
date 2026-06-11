"""‌⁠‍User service - business logic for authentication and user management.

Stateless service layer. Handles:
- User registration & login (JWT)
- Password hashing & verification
- Token generation (access + refresh)
- API key management
- Role & permission resolution
"""

import asyncio  # noqa: F401 - reload trigger
import hashlib
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.email import get_email_service
from app.core.events import event_bus

_logger_ev = __import__("logging").getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "") -> None:
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


from app.modules.users.models import APIKey, User
from app.modules.users.repository import (
    LOCAL_DESKTOP_OWNER_EMAIL,
    APIKeyRepository,
    UserRepository,
)
from app.modules.users.schemas import (
    AdminUserCreate,
    APIKeyCreate,
    APIKeyCreatedResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    FirstRunResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenResponse,
    UserCreate,
    UserPreferencesUpdate,
)

logger = logging.getLogger(__name__)


# ── Password utilities ─────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """‌⁠‍Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """‌⁠‍Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _is_usable_password_hash(hashed: str | None) -> bool:
    """True when ``hashed`` looks like a real bcrypt hash we can verify against.

    SSO / passwordless rows may carry an empty or sentinel value rather than a
    bcrypt digest. ``erase_account`` uses this to decide whether to require the
    current password or the typed confirmation phrase.
    """
    return bool(hashed) and (hashed.startswith("$2a$") or hashed.startswith("$2b$") or hashed.startswith("$2y$"))


# ── Token utilities ────────────────────────────────────────────────────────


def create_access_token(
    user: User,
    settings: Settings,
    extra_claims: dict | None = None,
) -> str:
    """Create a JWT access token for a user.

    The token deliberately carries only identity claims (``sub``, ``email``,
    ``role``) - NOT the resolved permission list. Permissions are re-hydrated
    from the DB role on every request in ``get_current_user_payload`` (and the
    frontend reads them from ``GET /users/me``), so embedding them here was
    pure dead weight: for an admin it added ~12 KB, pushing the ``Authorization``
    header past the 16 KB limit of Node/Vite dev proxies and yielding HTTP 431
    ("Request Header Fields Too Large") on every authenticated call. See the
    re-hydration note in ``app/dependencies.py``.
    """
    now = datetime.now(UTC)
    payload = {
        "iss": "openconstructionerp",  # RFC 7519 issuer claim
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
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
        "iss": "openconstructionerp",
        "sub": str(user.id),
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_reset_token(user: User, settings: Settings) -> str:
    """Create a JWT password-reset token (15 min expiry)."""
    now = datetime.now(UTC)
    payload = {
        "iss": "openconstructionerp",
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "type": "reset",
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


# Whitelist of seeded demo accounts. Must mirror the same set in
# ``backend/app/modules/users/router.py:_DEMO_EMAIL_WHITELIST`` and
# ``backend/app/main.py:_seed_demo_account``. The integration test
# ``test_demo_login_endpoint.py`` asserts router and seeder stay in sync;
# this duplicate exists so ``login()`` can route demo logins without
# importing from router (which would create a circular import).
_DEMO_EMAIL_WHITELIST: frozenset[str] = frozenset(
    {
        "demo@openconstructionerp.com",
        "estimator@openconstructionerp.com",
        "manager@openconstructionerp.com",
    }
)


class UserService:
    """Business logic for user operations."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.user_repo = UserRepository(session)
        self.api_key_repo = APIKeyRepository(session)

    # ── Registration ───────────────────────────────────────────────────

    async def register(
        self,
        data: UserCreate,
        *,
        client_ip: str = "",
        user_agent: str = "",
        referrer: str = "",
    ) -> User:
        """Register a new user.

        Raises HTTPException 409 if email already taken.
        First user automatically gets admin role.
        """
        # Resolve registration policy. Re-read settings each call so a
        # test (or runtime config reload) can switch modes without restart.
        from app.config import get_settings as _get_settings

        _s = _get_settings()
        mode = getattr(_s, "registration_mode", "open") or "open"

        # "First real user becomes admin" bootstrap. Check for any existing
        # admin rather than any user - a prior `make seed` run may have
        # inserted demo/viewer rows that would otherwise block the first
        # real registrant from receiving admin rights.
        admin_exists = await self.user_repo.has_admin()

        # ``closed`` mode rejects every self-registration. The bootstrap
        # path is still allowed: an admin must be reachable on a fresh
        # install or the operator has no way in. Once one admin exists,
        # closed truly closes the door.
        if mode == "closed" and admin_exists:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Self-registration is disabled. Contact an administrator.",
            )

        if await self.user_repo.email_exists(data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        # First user becomes admin (bootstrap path); subsequent self-registered
        # users default to `viewer` - a near-zero-privilege role. Historically
        # this defaulted to `editor`, which granted 119 permissions including
        # `costs.create`, `boq.delete`, `schedule.delete` to anyone who could
        # hit the public registration endpoint (BUG-327/386). Admins must
        # explicitly promote via PATCH /{user_id}.
        #
        # If the tenant wants open self-onboarding to continue creating
        # editors (e.g. internal-only deployment behind a VPN), they can
        # override this via the ``OE_DEFAULT_REGISTRATION_ROLE`` env var.
        default_role = getattr(_s, "default_registration_role", "viewer") or "viewer"
        if default_role not in {"viewer", "editor", "manager"}:
            # Admin is intentionally excluded - nobody should self-register
            # as admin no matter what config says.
            default_role = "viewer"

        if not admin_exists:
            # Bootstrap path - always active so the operator can actually
            # log in to a fresh install in admin-approve mode.
            role = "admin"
            is_active = True
        else:
            role = default_role
            # In gated modes the new account is dormant until an admin
            # flips it active. ``open`` keeps prior behaviour. ``login``
            # already returns the same 401 for inactive accounts as for
            # bad credentials, so no enumeration leak is added.
            is_active = mode == "open"

        # Build registration metadata from form fields + auto-collected data
        reg_meta: dict[str, object] = {}
        if data.company:
            reg_meta["company"] = data.company
        if data.job_title:
            reg_meta["job_title"] = data.job_title
        if data.how_found_us:
            reg_meta["how_found_us"] = data.how_found_us
        if client_ip:
            reg_meta["registration_ip"] = client_ip
        if user_agent:
            reg_meta["registration_user_agent"] = user_agent
        if referrer:
            reg_meta["registration_referrer"] = referrer

        metadata = {"registration": reg_meta} if reg_meta else {}

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=role,
            locale=data.locale,
            is_active=is_active,
            # The mapped attribute is metadata_ (column "metadata"); passing
            # metadata= here is silently swallowed by the declarative
            # constructor and the registration metadata never persisted.
            metadata_=metadata,
        )
        user = await self.user_repo.create(user)

        await _safe_publish(
            "users.user.created",
            {
                "user_id": str(user.id),
                "email": user.email,
                "role": role,
                "is_active": is_active,
                "registration_mode": mode,
            },
            source_module="oe_users",
        )

        logger.info(
            "User registered: %s (role=%s, active=%s, mode=%s)",
            user.email,
            role,
            is_active,
            mode,
        )
        return user

    # ── Admin: create user (BUG-USERS-CREATE) ──────────────────────────

    async def admin_create(self, data: AdminUserCreate) -> User:
        """Admin-only: create a user with an arbitrary role / active state.

        Bypasses the public-registration policy (default-to-viewer, dormant
        in gated modes, first-real-user-becomes-admin). The router gates
        this behind ``RequirePermission("users.create")`` (admin only) and
        the ``AdminUserCreate`` schema rejects bogus roles / weak passwords
        before they reach this method.

        Raises:
            HTTPException 409 if the email is already registered.
        """
        if await self.user_repo.email_exists(data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            locale=data.locale,
            is_active=data.is_active,
            # metadata_ is the mapped attribute; metadata= would be dropped.
            metadata_={"registration": {"created_by": "admin"}},
        )
        user = await self.user_repo.create(user)

        await _safe_publish(
            "users.user.created",
            {
                "user_id": str(user.id),
                "email": user.email,
                "role": data.role,
                "is_active": data.is_active,
                "registration_mode": "admin_create",
            },
            source_module="oe_users",
        )

        logger.info(
            "Admin created user: %s (role=%s, active=%s)",
            user.email,
            data.role,
            data.is_active,
        )
        return user

    # ── Authentication ─────────────────────────────────────────────────

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate user and return JWT tokens.

        Raises HTTPException 401 on invalid credentials.

        Demo-account UX shortcut: if the email matches one of the seeded
        demo accounts and ``SEED_DEMO`` is enabled (default on community /
        self-host installs, disabled in production), we route through
        ``demo_login`` - which issues tokens without verifying the
        password. Why: BUG-D01 randomised demo passwords per install for
        security, but users who typed the documented ``DemoPass1234!``
        into the manual form got 401 "Invalid email or password" because
        the stored hash was now a ``secrets.token_urlsafe(16)`` instead.
        Keeping demo emails password-free in the manual path makes the
        documented credentials JustWork without reintroducing a
        hardcoded password into ``main.py`` (the source-grep test in
        ``test_demo_credentials.py`` stays green). Production installs
        set ``SEED_DEMO=false`` so this shortcut is dead code there.
        """
        email_norm = (data.email or "").strip().lower()
        # The password-free demo shortcut is a development/demo convenience
        # only. Refuse it outright in production even if SEED_DEMO was left
        # at its default, so a self-host install can never expose a
        # no-password login to a seeded manager/estimator account by simply
        # forgetting to set the env flag.
        from app.config import get_settings as _get_settings

        _demo_allowed = not _get_settings().is_production and os.environ.get("SEED_DEMO", "true").lower() not in (
            "false",
            "0",
            "no",
        )
        if email_norm in _DEMO_EMAIL_WHITELIST and _demo_allowed:
            return await self.demo_login(email_norm)

        user = await self.user_repo.get_by_email(data.email)

        if user is None:
            # Dummy bcrypt check to prevent timing side-channel (user enumeration)
            # Without this, non-existent user returns ~0.2s, existing user ~0.5s (bcrypt)
            verify_password(data.password, "$2b$12$LJ3m4ys3Lz0Y0u9DuMmDCeDhR5x.V5fHn/G8s8GD3EO2M4QRWQ.IO")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not verify_password(data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not user.is_active:
            # Return same generic error as invalid credentials to avoid
            # revealing whether an account exists or its activation status
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Eagerly read fields before update_fields (which calls expire_all)
        user_id = user.id
        user_email = user.email
        user_role = user.role
        user_full_name = user.full_name
        prior_last_login = user.last_login_at

        # Throttle last_login_at writes - if the previous login was <60s ago
        # we skip the UPDATE. Avoids a race against the UserActivity INSERT
        # that the session-middleware fires on the same request (BUG-161),
        # and prevents burst-login from hammering the users table.
        #
        # SQLite strips the tzinfo on DateTime(timezone=True) columns so we
        # coerce both sides to naive UTC before subtracting - otherwise
        # Python raises ``can't subtract offset-naive and offset-aware``.
        now = datetime.now(UTC)
        skip_write = False
        if prior_last_login is not None:
            prior = prior_last_login
            if prior.tzinfo is None:
                prior = prior.replace(tzinfo=UTC)
            skip_write = (now - prior).total_seconds() < 60.0

        if not skip_write:
            # Bump last_login_at inside this request's own session so it commits
            # with the rest of the login, before the response. A detached task
            # here opened a SECOND database connection that wrote concurrently
            # with the user's next request; on SQLite (still the test and VPS
            # database) the second writer hit "database is locked", and on
            # PostgreSQL it was a stray connection that could outlive the
            # request. In-session it is one indexed primary-key UPDATE, so login
            # latency is unaffected on either backend.
            await self.session.execute(update(User).where(User.id == user_id).values(last_login_at=now))

        access_token = create_access_token(user, self.settings)
        refresh_token = create_refresh_token(user, self.settings)

        # Audit trail - security-critical event: successful login.
        try:
            from app.core.audit_log import log_activity as _log_activity

            await _log_activity(
                self.session,
                actor_id=str(user_id),
                entity_type="user",
                entity_id=str(user_id),
                action="login",
                module="users",
                after_state={"email": user_email, "role": user_role},
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit log skipped for login (non-fatal)")

        await _safe_publish(
            "users.user.logged_in",
            {"user_id": str(user.id)},
            source_module="oe_users",
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.jwt_expire_minutes * 60,
        )

    async def demo_login(self, email: str) -> TokenResponse:
        """Issue tokens for a seeded demo account without a password check.

        Caller (router) is responsible for whitelisting the email to one of
        the seeded demo accounts and gating on ``SEED_DEMO``. This method
        only verifies the row exists and is active, then mints the same
        JWT pair as :meth:`login`. Bumps ``last_login_at`` with the same
        60-second throttle so heavy demo traffic doesn't hammer Postgres.
        """
        user = await self.user_repo.get_by_email(email)
        if user is None or not user.is_active:
            # The seeder must have failed (rare) or the row was manually
            # deleted. Surface a 404 so the operator knows to check the
            # startup log - distinct from a 401 so it's clear this isn't
            # a credential problem.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Demo account {email!r} is not present on this server. "
                    f"Check the startup log for the seeder output, or set "
                    f"SEED_DEMO=true and restart."
                ),
            )

        user_id = user.id
        prior_last_login = user.last_login_at
        now = datetime.now(UTC)
        skip_write = False
        if prior_last_login is not None:
            prior = prior_last_login
            if prior.tzinfo is None:
                prior = prior.replace(tzinfo=UTC)
            skip_write = (now - prior).total_seconds() < 60.0
        # Bump last_login_at in this request's own session (same 60s throttle
        # as login()). The previous detached-task write opened a second
        # connection that raced the caller's next request and locked SQLite;
        # in-session it commits with the login and never contends.
        if not skip_write:
            await self.session.execute(update(User).where(User.id == user_id).values(last_login_at=now))

        access_token = create_access_token(user, self.settings)
        refresh_token = create_refresh_token(user, self.settings)

        await _safe_publish(
            "users.user.logged_in",
            {"user_id": str(user.id), "demo": True},
            source_module="oe_users",
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.jwt_expire_minutes * 60,
        )

    # ── Desktop first-run / bootstrap ──────────────────────────────────

    async def first_run_status(self, *, is_desktop: bool) -> FirstRunResponse:
        """Compute the desktop first-run status (never raises).

        Surfaced by ``GET /auth/first-run`` to let the desktop shell decide
        whether to silently auto-provision and log in the local workspace
        owner. ``fresh_install`` excludes the seeded demo accounts and the
        local owner itself, so a desktop install that has only created its own
        owner is still "fresh" from the standpoint of real registered users.

        Args:
            is_desktop: Result of :func:`app.config.desktop_mode` - threaded in
                by the router so the value is resolved once per request.

        Returns:
            A populated :class:`FirstRunResponse`. The owner's
            ``onboarding_completed`` flag is read from user metadata and is
            ``None`` when no local owner exists yet.
        """
        owner = await self.user_repo.get_local_desktop_owner()
        has_local_account = owner is not None and bool((owner.metadata_ or {}).get("local_desktop"))

        onboarding_completed: bool | None = None
        if owner is not None:
            onboarding: dict[str, object] = (owner.metadata_ or {}).get("onboarding") or {}
            onboarding_completed = bool(onboarding.get("completed", False))

        has_real_user = await self.user_repo.has_real_active_user()

        return FirstRunResponse(
            desktop_mode=is_desktop,
            fresh_install=not has_real_user,
            has_local_account=has_local_account,
            onboarding_completed=onboarding_completed,
        )

    async def desktop_bootstrap(self) -> TokenResponse:
        """Provision (first call) or re-authenticate the local desktop owner.

        Mints the SAME token pair as :meth:`login`. All policy guards
        (desktop-mode, loopback host, fresh-or-owner) are enforced by the
        router BEFORE this method runs - it assumes it is safe to either
        create or reuse the ``owner@openestimate.local`` admin.

        First call:
            Creates an active admin named "Workspace Owner" with a random
            unguessable password (the account is never password-authenticated)
            and a ``local_desktop=true`` metadata flag, then issues tokens.

        Subsequent calls:
            Finds the same row by e-mail, verifies its ``local_desktop`` flag
            (a manually created row at that address without the flag is
            rejected with 403), and issues fresh tokens.

        Raises:
            HTTPException 403 if a row exists at the owner e-mail but is not a
                genuine local-desktop owner (missing flag / inactive).
        """
        owner = await self.user_repo.get_local_desktop_owner()

        if owner is None:
            # First run - auto-provision the local workspace owner. The
            # password is a throwaway random value: this account is only ever
            # entered through the loopback-guarded bootstrap path, never via
            # the password form, so the hash exists purely to satisfy the
            # NOT NULL column.
            owner = User(
                email=LOCAL_DESKTOP_OWNER_EMAIL,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                full_name="Workspace Owner",
                role="admin",
                is_active=True,
                metadata_={"local_desktop": True},
            )
            owner = await self.user_repo.create(owner)
            logger.info("Desktop bootstrap: created local workspace owner %s", owner.email)
            await _safe_publish(
                "users.user.created",
                {
                    "user_id": str(owner.id),
                    "email": owner.email,
                    "role": "admin",
                    "is_active": True,
                    "registration_mode": "desktop_bootstrap",
                },
                source_module="oe_users",
            )
        elif not (owner.metadata_ or {}).get("local_desktop") or not owner.is_active:
            # A row sits at the owner e-mail but it is not a genuine, active
            # local-desktop owner (e.g. someone manually registered that
            # address). Refuse to hand out admin tokens for it.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The local owner account is not available for desktop bootstrap.",
            )

        access_token = create_access_token(owner, self.settings)
        refresh_token = create_refresh_token(owner, self.settings)

        await _safe_publish(
            "users.user.logged_in",
            {"user_id": str(owner.id), "desktop_bootstrap": True},
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

    # ── Password reset ──────────────────────────────────────────────────

    async def forgot_password(self, data: ForgotPasswordRequest) -> ForgotPasswordResponse:
        """Generate a password-reset token if the email exists.

        Always returns a generic success message to prevent email enumeration.
        The token is NEVER included in the HTTP response - it must be
        delivered only via a secure side-channel (email).
        """
        user = await self.user_repo.get_by_email(data.email)

        # Generic message regardless of whether the email exists
        message = "If this email exists, a password reset link has been sent."

        if user is None or not user.is_active:
            logger.info("Password reset requested for unknown/inactive email: %s", data.email)
            return ForgotPasswordResponse(message=message)

        token = create_reset_token(user, self.settings)

        await _safe_publish(
            "users.password_reset.requested",
            {"user_id": str(user.id), "email": user.email},
            source_module="oe_users",
        )

        logger.info("Password reset token generated for user %s", user.email)

        reset_url = f"{self.settings.resolved_frontend_url}/auth/reset?token={token}"
        recipient_name = user.full_name or user.email.split("@", 1)[0]
        email_service = get_email_service()
        result = await email_service.send_password_reset(
            to=user.email,
            reset_url=reset_url,
            recipient_name=recipient_name,
            token_lifetime_minutes=self.settings.jwt_expire_minutes,
        )
        # Never raise - the response must stay enumeration-proof even
        # when SMTP is down. The service already logs failure reasons.
        if not result.ok and self.settings.app_debug:
            # Dev-only fallback so developers without SMTP can still
            # complete the reset flow from logs.
            logger.debug("Reset URL for %s (dev-only log): %s", user.email, reset_url)

        return ForgotPasswordResponse(message=message)

    async def reset_password(self, data: ResetPasswordRequest) -> ResetPasswordResponse:
        """Reset user password using a valid reset token.

        Raises HTTPException 400 on invalid/expired token.

        Single-use enforcement: after the first successful reset the
        ``password_changed_at`` column is bumped to ``now()``.  On any
        subsequent attempt with the same token, ``iat`` (issued-at) will
        be ≤ ``password_changed_at`` - we reject it as already-used,
        preventing token reuse within the 15-minute expiry window.  No DB
        blocklist is needed; the existing ``password_changed_at`` column
        already serves as the invalidation timestamp.
        """
        from jose import JWTError

        try:
            payload = jwt.decode(
                data.token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            ) from exc

        if payload.get("type") != "reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type",
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset token",
            )

        user = await self.user_repo.get_by_id(uuid.UUID(user_id))
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User not found or inactive",
            )

        # Single-use guard: reject the token if password was already changed
        # after this token was issued (iat).  Mirrors the same logic used in
        # get_current_user_payload for access tokens.
        iat = payload.get("iat")
        if iat is not None and user.password_changed_at is not None:
            pwd_changed = user.password_changed_at
            if pwd_changed.tzinfo is None:
                pwd_changed = pwd_changed.replace(tzinfo=UTC)
            if int(float(iat)) <= int(pwd_changed.timestamp()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reset token has already been used. Please request a new one.",
                )

        # Eagerly read email before update_fields (which calls expire_all)
        user_email = user.email
        user_uuid = user.id

        await self.user_repo.update_fields(
            user.id,
            hashed_password=hash_password(data.new_password),
            password_changed_at=datetime.now(UTC),
        )

        # Audit trail - security-critical event: password change via reset token.
        try:
            from app.core.audit_log import log_activity as _log_activity

            await _log_activity(
                self.session,
                actor_id=str(user_uuid),
                entity_type="user",
                entity_id=str(user_uuid),
                action="password_reset_completed",
                module="users",
                after_state={"email": user_email},
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit log skipped for password_reset_completed (non-fatal)")

        await _safe_publish(
            "users.password_reset.completed",
            {"user_id": str(user_uuid), "email": user_email},
            source_module="oe_users",
        )

        logger.info("Password reset completed for user %s", user_email)
        return ResetPasswordResponse(message="Password updated successfully")

    # ── User management ────────────────────────────────────────────────

    async def get_user(self, user_id: uuid.UUID) -> User:
        """Get user by ID. Raises 404 if not found."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def update_profile(self, user_id: uuid.UUID, **fields: object) -> User:
        """Update user profile fields.

        If ``role`` is being changed, a dedicated audit log entry is written so
        privilege escalation / demotion is always traceable (RBAC audit gap fix).
        """
        # Capture old role before overwriting so the audit row has before/after.
        old_role: str | None = None
        new_role: str | None = None
        if "role" in fields:
            prior = await self.user_repo.get_by_id(user_id)
            if prior is not None:
                old_role = prior.role
            new_role = str(fields["role"])

        await self.user_repo.update_fields(user_id, **fields)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if old_role is not None and new_role is not None and old_role != new_role:
            try:
                from app.core.audit_log import log_activity as _log_activity

                await _log_activity(
                    self.session,
                    actor_id=None,  # context dep fills this from ContextVar
                    entity_type="user",
                    entity_id=str(user_id),
                    action="role_changed",
                    from_status=old_role,
                    to_status=new_role,
                    module="users",
                    before_state={"role": old_role},
                    after_state={"role": new_role, "email": user.email},
                )
            except Exception:  # noqa: BLE001
                logger.debug("audit log skipped for role_changed (non-fatal)")

        return user

    async def update_preferences(
        self,
        user_id: uuid.UUID,
        data: UserPreferencesUpdate,
    ) -> User:
        """Update regional preference fields for a user."""
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.user_repo.update_fields(user_id, **fields)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def change_password(
        self,
        user_id: uuid.UUID,
        data: ChangePasswordRequest,
    ) -> TokenResponse:
        """Change user password and return fresh JWT tokens.

        Verifies current password first, then bumps `password_changed_at` so
        any JWT issued before this moment will be rejected by
        `get_current_user`.  Returns a new token pair so the caller stays
        authenticated without a forced re-login.
        """
        user = await self.get_user(user_id)

        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        # Eagerly read email before update_fields (which calls expire_all)
        # to avoid MissingGreenlet on expired attributes in async context.
        user_email = user.email

        await self.user_repo.update_fields(
            user_id,
            hashed_password=hash_password(data.new_password),
            password_changed_at=datetime.now(UTC),
        )
        logger.info("Password changed for user %s", user_email)

        # Re-fetch user to pick up the updated password_changed_at timestamp
        user = await self.user_repo.get_by_id(user_id)

        access_token = create_access_token(user, self.settings)
        refresh_token = create_refresh_token(user, self.settings)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.jwt_expire_minutes * 60,
        )

    async def list_users(
        self,
        offset: int = 0,
        limit: int = 50,
        is_active: bool | None = None,
    ) -> tuple[list[User], int]:
        """List users with pagination."""
        return await self.user_repo.list_all(offset=offset, limit=limit, is_active=is_active)

    # ── Self-service erasure (GDPR Art. 17) ────────────────────────────

    async def erase_account(
        self,
        user_id: uuid.UUID,
        data: DeleteAccountRequest,
    ) -> None:
        """Erase (anonymise in place) the caller's own account. GDPR Art. 17.

        The signup UI promises users can delete their account at any time, so
        this is the self-service path behind that promise. It never touches
        another user - the caller's id comes from the authenticated token, and
        the request body carries no id.

        Erasure model: ANONYMIZE in place rather than hard delete. The user row
        is referenced by other tables (projects via owner_id, activity / audit
        rows via actor_id) and the projects FK is ON DELETE CASCADE, so a hard
        delete would silently drag the user's projects (and their BOQs, costs,
        documents) into the grave with it. Instead we null every PII field,
        replace the email with a non-reversible placeholder, invalidate the
        password hash, flip ``is_active`` False and stamp ``deleted_at``. The
        row survives so foreign keys stay intact, but it holds no personal data
        and can no longer authenticate.

        Confirmation guard:
          - A password account must re-supply ``current_password``; we verify
            it against the stored hash and raise 400 on a mismatch.
          - A passwordless / SSO account (no usable hash) must instead type the
            literal ``DELETE`` into ``confirm``; anything else raises 400.

        Tenant safety: refuses to erase the last remaining active admin so the
        workspace is never orphaned without an administrator - returns 409 with
        guidance to promote another admin first.

        Raises:
            HTTPException 404 if the user does not exist (or is already erased).
            HTTPException 400 if the confirmation guard is not satisfied.
            HTTPException 409 if the caller is the last active admin.
        """
        user = await self.get_user(user_id)

        if user.deleted_at is not None:
            # Already erased - nothing left to do, and we must not leak a second
            # audit row or re-randomise the placeholder. Treat as gone.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # ── Confirmation guard ──────────────────────────────────────────
        has_password = bool(user.hashed_password) and _is_usable_password_hash(user.hashed_password)
        if has_password:
            supplied = data.current_password or ""
            if not supplied or not verify_password(supplied, user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect",
                )
        else:
            # Passwordless / SSO account: require the typed confirmation phrase.
            if (data.confirm or "").strip() != "DELETE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=("This account has no password. Type DELETE in the confirm field to erase it."),
                )

        # ── Tenant safety: never orphan the workspace ───────────────────
        if user.role == "admin":
            other_admins = await self.user_repo.count_active_admins(exclude_id=user_id)
            if other_admins == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "You are the last active administrator. Promote another "
                        "user to admin before erasing your own account so the "
                        "workspace is not left without an administrator."
                    ),
                )

        # Eagerly read the fields we still need before update_fields expires
        # the instance (avoids MissingGreenlet on async re-access).
        user_uuid = user.id

        # ── Anonymise in place ──────────────────────────────────────────
        placeholder_email = f"deleted+{uuid.uuid4().hex}@deleted.invalid"
        now = datetime.now(UTC)
        await self.user_repo.update_fields(
            user_id,
            email=placeholder_email,
            full_name="",
            # A bcrypt hash of a fresh random secret nobody holds: the column is
            # NOT NULL, and ``_is_usable_password_hash`` still reads it as a hash
            # so a re-erasure won't fall through to the SSO branch. The user can
            # never authenticate with it because the plaintext is discarded.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            # Bump password_changed_at so any access/refresh token issued before
            # now is rejected by get_current_user_payload - the user is logged
            # out everywhere immediately.
            password_changed_at=now,
            is_active=False,
            deleted_at=now,
            # Drop all profile PII held in the JSON column (company, job title,
            # registration ip / user-agent / referrer, avatar, phone, etc.).
            metadata_={"erased": True},
            locale="en",
        )

        # Revoke every API key the user owns so no programmatic session survives.
        await self.api_key_repo.deactivate_all_for_user(user_uuid)

        # ── Audit trail (no PII in the record) ──────────────────────────
        try:
            from app.core.audit_log import log_activity as _log_activity

            await _log_activity(
                self.session,
                actor_id=str(user_uuid),
                entity_type="user",
                entity_id=str(user_uuid),
                action="account_erasure",
                module="users",
                # Deliberately store NO personal data here - just the fact and
                # the timestamp. The whole point of erasure is that the record
                # must not re-store what we just removed.
                after_state={"erased": True},
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit log skipped for account_erasure (non-fatal)")

        await _safe_publish(
            "users.user.erased",
            {"user_id": str(user_uuid)},
            source_module="oe_users",
        )

        logger.info("Account erased (self-service GDPR Art. 17): user=%s", user_uuid)

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
