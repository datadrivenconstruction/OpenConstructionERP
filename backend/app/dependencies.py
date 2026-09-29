# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
from collections import OrderedDict
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from app.modules.users.models import User

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

# Stable DI container revision tag - fixed at design time so the
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
            ``"access"`` - the only token flavour that should reach protected
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
                    detail=(f"Invalid token: wrong type (expected '{expected_type}', got '{token_type or 'none'}')"),
                )
        return payload
    except JWTError as exc:
        # Do NOT echo the raw jose exception text to the client - it leaks
        # crypto-library internals (algorithm names, signature/segment counts,
        # expiry deltas) that aid token-forgery probing. Log the full detail
        # server-side, tagged with the request-id by the RequestIDLogFilter,
        # and hand the caller only a generic message + the same correlation id.
        from app.middleware.request_id import get_request_id

        request_id = get_request_id()
        logger.warning("JWT decode rejected (request_id=%s): %s", request_id or "-", exc)
        detail = "Invalid or expired token"
        if request_id:
            detail = f"{detail} (request_id: {request_id})"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        ) from exc


# ── Current user ───────────────────────────────────────────────────────────


def reject_token_issued_before_password_change(
    issued_at: float | int | None,
    password_changed_at: datetime | None,
) -> None:
    """Refuse a credential minted before the user's last password change.

    ``password_changed_at`` is the only session kill switch this product has.
    The rule for reading it lives here once, because it used to live inline in
    :func:`get_current_user_payload` and nowhere else: every other place a
    token is accepted - the three websockets, the optional-auth resolver and
    the refresh endpoint - went on honouring tokens the HTTP surface had
    already refused. A rule written twice drifts; a rule written once and
    called from each door cannot.

    Both operands are whole seconds by construction, and that sets the limit
    of the mechanism rather than revealing an oversight in it. ``iat`` is
    seconds since the epoch by RFC 7519, so the watermark is truncated to
    match, and a credential minted inside the same second as the change
    compares equal to it and survives. Comparing the truncated ``iat`` against
    a fractional timestamp does not close that: it breaks the ordinary case,
    because the fresh token pair that change-password itself hands back
    carries an ``iat`` inside that very second and would be refused, logging
    the user out of the session they just created. The per-session ``sid``
    revocation being built on top of this asks whether a session is still
    alive rather than when its token was minted, so second resolution does not
    reach it at all.

    Args:
        issued_at: the credential's ``iat`` claim. ``None`` (a token minted
            before we set the claim) skips the comparison, because a token
            that never said when it was issued cannot be placed either side
            of the watermark.
        password_changed_at: the user's watermark, ``None`` until they first
            change a password.

    Raises:
        HTTPException 401 if the credential predates the watermark.
    """
    if issued_at is None or password_changed_at is None:
        return
    # SQLite hands back naive datetimes; assume UTC when the tzinfo is absent.
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=UTC)
    # ``iat`` arrives as int or float depending on the jose version.
    if int(float(issued_at)) < int(password_changed_at.timestamp()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated by a password change. Please log in again.",
        )


# Sessions already reported by :func:`reject_revoked_session` as missing, most
# recently seen last. The warning it writes exists to be counted, and what
# carries the signal is the number of DISTINCT sessions, not the number of
# lines: a restore from a backup shows up as a burst of new ones that stops
# arriving, a pruning predicate reaching unexpired rows shows up as new ones
# that keep arriving. Repeating a line for a session already reported adds
# nothing to either reading and costs a line on every request that token makes,
# for as long as it lives. That is the case this exists to prevent: the pruning
# scenario never decays, so the unbounded version writes forever, and a log
# filling the disk is a way this diagnostic could take down the host it is
# diagnosing.
#
# The cap bounds the registry itself, which a restore would otherwise grow by
# one entry per live token. Falling out of it lets a session be reported once
# more later, so the cap degrades to a rate limit rather than to silence. Hits
# move to the end, so the sessions asking most often are the ones kept quiet.
_SESSIONS_REPORTED_MISSING: OrderedDict[str, None] = OrderedDict()
_SESSIONS_REPORTED_MISSING_CAP = 4096


def _first_sighting_of_missing_session(sid: str) -> bool:
    """True the first time ``sid`` is seen missing, false while it is remembered."""
    if sid in _SESSIONS_REPORTED_MISSING:
        _SESSIONS_REPORTED_MISSING.move_to_end(sid)
        return False
    _SESSIONS_REPORTED_MISSING[sid] = None
    while len(_SESSIONS_REPORTED_MISSING) > _SESSIONS_REPORTED_MISSING_CAP:
        _SESSIONS_REPORTED_MISSING.popitem(last=False)
    return True


async def reject_revoked_session(
    session: AsyncSession,
    sid: str | None,
    user_id: _uuid.UUID,
) -> None:
    """Refuse a credential whose session has been revoked.

    The fine-grained counterpart to
    :func:`reject_token_issued_before_password_change`. The watermark can only
    say "everything older than this moment", which ends every session the
    person has; this asks whether one named session is still alive, so ending
    the laptop left in a hotel does not sign them out of their phone.

    Takes the caller's already-open session rather than opening one. Every
    door that calls this has just loaded the user row through a session it
    holds, and opening a second one here would double connection churn on the
    hot authentication path.

    Two cases deliberately pass rather than raise, and both are load-bearing.

    A token with no ``sid`` is honoured. Every credential issued before the
    session table existed carries none, and refusing them would sign out every
    live user the moment this deploys. Such a token is not revocable
    individually; it lives until it expires, at most the refresh horizon, and
    the lever over it in the meantime is ``password_changed_at`` through the
    watermark check above. Its first refresh opens a session and it becomes
    revocable from then on.

    A ``sid`` with no row is also honoured, which is a fail-open check and is
    worth justifying rather than assuming. The question is not "open or
    closed" in the abstract but whether a live token can exist without its
    row. There are three ways for the row to be missing. A failed insert at
    login cannot produce one, because
    :meth:`UserService._open_session` flushes before any token is minted and a
    failure there refuses the login. Pruning cannot reach one, because it is
    only ever allowed to delete rows already past ``expires_at`` and that
    column is kept at or beyond the horizon of the refresh token naming it.
    That leaves restoring the database from a backup taken before the session
    began, and failing closed there would sign out every user on the platform
    at the moment of a restore, which is when they can least afford it. So the
    remaining case is one where fail-open is the choice we would make on
    purpose, not a hole nobody noticed. If that stops being true - a fourth
    way for a row to go missing - this is the comment to come back to, and the
    fix is to close the new hole, not to flip this.

    Args:
        session: an open database session belonging to the caller.
        sid: the credential's ``sid`` claim, or ``None``.
        user_id: the owner the credential claims, already verified against the
            database. The lookup is scoped by it so that a ``sid`` belonging
            to somebody else cannot be used to probe another account.

    Raises:
        HTTPException 401 if the named session has been revoked.
    """
    if not sid:
        return
    from app.modules.users.models import UserSession

    # ``sid`` is selected alongside ``revoked_at`` so that the two passing cases
    # stay distinguishable. Reading ``revoked_at`` alone cannot tell them apart:
    # it is NULL both for a live session and for a row that is not there, so the
    # deliberate fail-open documented above would be indistinguishable in the
    # code from the ordinary success it is meant to be an exception to, and
    # would leave no trace to count.
    row = (
        await session.execute(
            select(UserSession.sid, UserSession.revoked_at).where(
                UserSession.sid == sid,
                UserSession.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        # The fail-open path. It is logged because its three causes are only
        # separable by how often it fires: a restore from backup produces a
        # burst across every live token that decays as sessions refresh, a
        # pruning predicate that reaches unexpired rows produces a flat rate
        # that never decays, and isolated events mean the login-time flush
        # stopped refusing a failed insert. The comment above argues the case
        # is acceptable; this line is what says whether it is happening.
        if _first_sighting_of_missing_session(sid):
            logger.warning(
                "Session %s claimed by user %s is not on file; honouring the token as unrevocable",
                sid,
                user_id,
            )
        return
    if row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session has been signed out. Please log in again.",
        )


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

                reject_token_issued_before_password_change(iat, user.password_changed_at)
                await reject_revoked_session(session, payload.get("sid"), user.id)
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


async def verify_user_exists_and_active(
    user_sub: str,
    *,
    issued_at: float | int | None,
    session_id: str | None,
) -> "User":
    """Load a User row by subject UUID, raising 401 if absent/inactive/stale.

    Shared across all JWT entry points (HTTP bearer, WS token, optional
    payloads) so that forged tokens with a real-looking UUID that nobody
    actually owns cannot reach business logic. Without this check,
    :func:`decode_access_token` only proves the signature is valid - it
    says nothing about whether the ``sub`` references a real user.

    ``issued_at`` is keyword-only and has NO default on purpose. It is the
    token's ``iat``, and passing it is what enforces the password-change
    watermark at this door. A default would let a new entry point skip the
    check by saying nothing, which is exactly how the sockets came to outlive
    a password change: the watermark went into one caller's inline copy and
    never into this shared helper. Without a default, a caller that has not
    decided fails to start rather than failing to protect somebody.

    ``session_id`` is the token's ``sid`` and is keyword-only with no default
    for the same reason. Note what that buys and what it does not: it makes
    forgetting the argument a build failure, and it does nothing at all unless
    the body below calls the rule. Both were briefly true of ``issued_at`` at
    once - required at every call site, read by none - and every caller looked
    correct throughout, which is the same way the sockets came to outlive a
    password change. The enforcement is not this signature, it is the two
    lines at the end of this function.

    Raises:
        HTTPException 401 if the user does not exist, is inactive, the
        credential predates the user's last password change, or the session
        the credential names has been revoked.
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
        reject_token_issued_before_password_change(issued_at, user.password_changed_at)
        await reject_revoked_session(session, session_id, user.id)
        return user


async def _optional_bearer_token(conn: HTTPConnection) -> str | None:
    """Pull a Bearer token from an HTTP request OR a WebSocket handshake.

    ``HTTPConnection`` is the shared base of ``Request`` and ``WebSocket``,
    so ``conn.headers`` resolves on websocket routes too. The ``HTTPBearer``
    security class cannot: its ``__call__`` takes a ``Request`` and raises on
    a websocket scope, which is what made the global RLS dependency reject the
    two websocket handshakes with a 500. Mirrors ``HTTPBearer(auto_error=
    False)``: a missing or non-Bearer header resolves to ``None``.
    """
    auth = conn.headers.get("Authorization")
    if not auth:
        return None
    scheme, _, param = auth.partition(" ")
    if scheme.lower() != "bearer" or not param:
        return None
    return param


async def get_optional_user_payload(
    token: Annotated[str | None, Depends(_optional_bearer_token)],
    settings: SettingsDep,
) -> dict[str, Any] | None:
    """Like get_current_user_payload but returns None if no token provided.

    Still enforces user existence (BUG-323) - an unknown / inactive
    ``sub`` is treated the same as an anonymous request (``None``), not
    as an authenticated one with forged identity.

    The token is read via ``HTTPConnection`` (not ``HTTPBearer``) so this
    resolver, and everything built on it - the tenant id and the global RLS
    request context - resolves on websocket routes as well as HTTP ones.
    """
    if token is None:
        return None
    try:
        payload = decode_access_token(token, settings)
        await verify_user_exists_and_active(
            payload["sub"],
            issued_at=payload.get("iat"),
            session_id=payload.get("sid"),
        )
        return payload
    except HTTPException:
        return None


# ── API-key auth (additive, JWT stays primary) ─────────────────────────────


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """The caller behind a valid ``X-API-Key``: the key's owner and its scopes.

    ``scopes`` is a copy of the key row's ``permissions`` list, taken before the
    session closes so nothing here lazy-loads later. It is NOT the owner's
    permission list - see :func:`key_scopes_allow` for what it does.
    """

    user: "User"
    scopes: list[str]


def key_scopes_allow(
    scopes: Sequence[str] | None,
    permission: str,
    *,
    require_declared: bool = False,
) -> bool:
    """Decide the narrowing half of an API key's authority.

    A key's ``permissions`` list has the OPPOSITE polarity of a JWT's. A JWT
    list WIDENS: a permission present in the token is granted. A key's list
    NARROWS: it can only ever take authority away from the owner, never add
    any. The effective authority of a request authenticated by an API key is
    therefore the INTERSECTION of what the owner's live role grants and what
    the key declares, and this function computes the key half of it. The owner
    half stays where it always was, in the role->permission registry.

    An empty or missing list declares no narrowing and returns True, so every
    key issued before scopes were enforced keeps exactly the authority it has
    today.

    Routes that must never open to a general-purpose key pass
    ``require_declared=True``, which drops that escape: an undeclared scope is
    refused even on a key that narrows nothing else.
    """
    declared = list(scopes or ())
    if not declared:
        return not require_declared
    return permission in declared


async def resolve_api_key_principal(
    request: Request,
) -> ApiKeyPrincipal:
    """Resolve an ``X-API-Key`` header to its owner and the key's own scopes.

    Additive entry point that runs entirely separate from the JWT path.
    The header value is hashed with the same SHA-256 scheme used at key
    creation (see :func:`app.modules.users.service.generate_api_key`) and
    looked up via :meth:`APIKeyRepository.get_by_hash`, which already
    rejects inactive or expired keys. The key's ``last_used_at`` is touched
    on each successful resolution.

    Returns both halves of the caller because authorization needs both: the
    owner supplies the role the registry is asked about, and the key supplies
    the scope list that narrows it.

    Raises:
        HTTPException 401 if the header is missing, unknown, expired, or its
        owning user does not exist / is inactive.
    """
    import hashlib

    from app.modules.users.models import User as _UserModel
    from app.modules.users.repository import APIKeyRepository

    header = request.headers.get("x-api-key")
    if not header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = hashlib.sha256(header.encode()).hexdigest()
    async with async_session_factory() as session:
        api_key = await APIKeyRepository(session).get_by_hash(key_hash)
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        scopes = list(api_key.permissions or [])
        await APIKeyRepository(session).update_last_used(api_key.id)
        user = await session.get(_UserModel, api_key.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return ApiKeyPrincipal(user=user, scopes=scopes)


async def get_user_from_api_key(
    request: Request,
) -> "User":
    """Resolve an ``X-API-Key`` header to its owning user.

    Thin wrapper over :func:`resolve_api_key_principal` for callers that only
    need the identity. Anything making an authorization decision must use the
    principal instead, because the key's scopes narrow what its owner may do
    and this return value drops them.
    """
    principal = await resolve_api_key_principal(request)
    return principal.user


ApiKeyUser = Annotated["User", Depends(get_user_from_api_key)]


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

        # Superadmin bypasses all checks.
        #
        # BUG-RBAC05: this used to log at INFO ("Admin bypass: ..."), which
        # generated hundreds of identical lines per minute on a busy admin
        # session AND tripped Splunk/Datadog alert rules that pattern-match
        # the literal string "Admin bypass" as a security flag. Demoted to
        # DEBUG - admin permissions are by design, not noteworthy.
        if role == "admin":
            user_id = payload.get("sub", "unknown")
            logger.debug(
                "Permission granted via admin role: permission=%s user=%s",
                self.permission,
                user_id,
            )
            return

        if self.permission not in permissions:
            # Issue #101: a JWT issued before a permission was lowered
            # to a more permissive role still carries its old permission
            # list, so the user appears blocked until they log out + log
            # in. Fall through to the live registry to honour the current
            # role→permission mapping for stale tokens. Admin already
            # short-circuited above; this only widens for non-admins.
            from app.core.permissions import permission_registry as _reg

            if _reg.role_has_permission(role, self.permission):
                logger.debug(
                    "Permission granted via live-registry fallback (stale JWT): permission=%s role=%s",
                    self.permission,
                    role,
                )
                return
            # BUG-RBAC05: log denials at DEBUG, not WARN. Viewer accounts
            # navigating normal pages routinely hit gated routes that the
            # UI knows are off-limits; flooding WARN with these false-
            # positive "Missing permission" lines drowns out genuinely
            # suspicious patterns. Still emitted so curious operators can
            # opt in via LOG_LEVEL=DEBUG.
            user_id = payload.get("sub", "unknown")
            logger.debug(
                "Permission denied: permission=%s user=%s role=%s",
                self.permission,
                user_id,
                role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {self.permission}",
            )


class RequirePermissionOrApiKey:
    """Permission gate that accepts either a JWT bearer or an ``X-API-Key``.

    For an interactive caller that presents a bearer token it behaves exactly
    like :class:`RequirePermission`: the ``admin`` role bypasses, and a stale JWT
    issued before a role->permission change still passes through the live
    registry (issue #101). For a headless caller that presents no usable bearer
    token it authenticates with the ``X-API-Key`` mechanism
    (:func:`resolve_api_key_principal`) and applies the identical role->permission
    check to the key's owning user, then narrows the result by the key's own
    declared permission list (see :meth:`_authorize`). Either way the same
    permission is required, so opening a route to machine callers never lowers
    its authorization bar, and a key can be issued that reaches less than its
    owner does.

    Unlike :class:`RequirePermission` (which returns ``None`` and is used in a
    route's ``dependencies=[...]``), this resolves and RETURNS the caller's user
    id, so a handler can attribute the rows it creates to whoever called, JWT
    user or API-key owner alike. Wire it as a normal parameter dependency::

        async def capture(
            ...,
            user_id: Annotated[str, Depends(RequirePermissionOrApiKey("inbound.write"))],
        ): ...

    This is the first route-level use of the ``X-API-Key`` mechanism, which was
    defined in this module but previously wired into no permission-gated route.
    """

    def __init__(self, permission: str) -> None:
        self.permission = permission

    async def __call__(
        self,
        request: Request,
        payload: Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)],
    ) -> str:
        # Interactive caller: a valid bearer token was presented. Attribute the
        # work to the JWT subject, exactly as RequirePermission would gate it.
        if payload is not None:
            self._authorize(payload.get("role", "") or "", payload.get("permissions", []))
            return str(payload["sub"])
        # Headless caller: no usable bearer token, so require a valid X-API-Key.
        # Its own 401 (missing / unknown / expired key, or inactive owner)
        # propagates unchanged; a valid key resolves to its owner and scopes.
        principal = await resolve_api_key_principal(request)
        self._authorize(getattr(principal.user, "role", "") or "", None, principal.scopes)
        return str(principal.user.id)

    def _authorize(
        self,
        role: str,
        permissions: list[str] | None,
        key_scopes: Sequence[str] | None = None,
    ) -> None:
        """Apply the shared role->permission check; raise 403 when it fails.

        ``permissions`` is the JWT's baked-in permission list for a bearer
        caller, or ``None`` for an API-key caller (whose token carries no such
        list), in which case the owner-side decision rests entirely on the live
        registry.

        ``key_scopes`` is the API key's own ``permissions`` list, or ``None``
        when no key is involved. It pulls in the opposite direction to the two
        arguments above: those can grant, this can only take away. The
        authority of an API-key request is the INTERSECTION of the owner's live
        permissions and the key's declared list, so a key can be held below its
        owner but never raised above them.

        The narrowing runs FIRST, ahead of the admin bypass, and that ordering
        is the whole point: narrowing an admin's key is exactly the case the
        declared list exists for, and a check placed after the bypass would
        never execute for the owner who most needs it.
        """
        if not key_scopes_allow(key_scopes, self.permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key does not carry permission: {self.permission}",
            )
        if role == "admin":
            return
        if permissions is not None and self.permission in permissions:
            return
        from app.core.permissions import permission_registry as _reg

        if _reg.role_has_permission(role, self.permission):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {self.permission}",
        )


class RequireRole:
    """Dependency that rejects anyone below a given role.

    Use on destructive endpoints (database wipes, tenant-wide bulk deletes,
    demo resets) where "has module permission" is insufficient - a plain
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
        from app.core.permissions import ROLE_HIERARCHY, _resolve_role

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
        # Attribution only - role comes from DB-rehydrated payload, not from
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
    """Verify user owns or has admin / team-member access to the project.

    Raises HTTP 404 on both "project missing" and "access denied" to avoid
    leaking the existence of UUIDs the caller is not allowed to see (IDOR
    defence - same policy as all downstream modules that call this helper).
    Team membership (added via add_project_member) grants the same read/write
    access as ownership within the caller's RBAC role.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.teams.access import is_project_member
    from app.modules.users.repository import UserRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Admin bypass - admins can touch any project regardless of ownership.
    try:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(_uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return
    except Exception:
        logger.exception("Admin-role lookup failed during project access check")

    # Owner has full access.
    if str(getattr(project, "owner_id", "")) == str(user_id):
        return

    # Team-member check - any TeamMembership row for this project grants access.
    try:
        if await is_project_member(session, project_id, _uuid.UUID(str(user_id))):
            return
    except (ValueError, TypeError):
        pass  # malformed user_id - fall through to 404
    except Exception:
        logger.exception("Team-membership lookup failed during project access check")

    # 404 (not 403) - keeps "resource missing" and "access denied"
    # indistinguishable, preventing UUID-existence oracle attacks.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project not found",
    )


async def accessible_project_ids(
    session: AsyncSession,
    user_id: str | None,
    *,
    live_only: bool = False,
) -> set[_uuid.UUID] | None:
    """Set of project IDs the caller may access, or ``None`` for admins.

    The set-level companion to :func:`verify_project_access`, using the exact
    same access rule: a non-admin may reach a project they OWN or are a
    team-member of; an admin may reach all. ``None`` is a sentinel meaning "do
    not filter" (admin / unrestricted) so a caller can branch:

        ids = await accessible_project_ids(session, user_id)
        if ids is not None:                  # non-admin -> scope the query
            stmt = stmt.where(Model.project_id.in_(ids))

    Use this to scope a list/aggregate endpoint whose ``project_id`` filter is
    OPTIONAL: when the caller omits it, return only their own projects instead
    of every project in the deployment. An empty set (non-admin with no
    projects, or a malformed user id) makes the query return nothing, which is
    the safe default - never fall back to "all rows".

    ``live_only=True`` is for listings, not for access checks. Deleting a
    project archives it and keeps the row, so the access rule alone still
    reaches it; a list built from that set shows a project that opens as
    "Project not found". With the flag archived projects are left out, and an
    admin gets the set of every live project instead of ``None``, because
    "do not filter" would let the archived ones back in.
    """
    from sqlalchemy import select

    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery
    from app.modules.users.repository import UserRepository

    if user_id is None:
        return set()

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return set()

    # Admin bypass - no filter, mirroring verify_project_access.
    try:
        user = await UserRepository(session).get_by_id(uid)
        if user is not None and getattr(user, "role", "") == "admin":
            if not live_only:
                return None
            live = (await session.execute(select(Project.id).where(Project.status != "archived"))).scalars().all()
            return {r if isinstance(r, _uuid.UUID) else _uuid.UUID(str(r)) for r in live}
    except Exception:
        logger.exception("Admin-role lookup failed during accessible-projects scan")

    stmt = select(Project.id).where((Project.owner_id == uid) | (Project.id.in_(member_project_ids_subquery(uid))))
    if live_only:
        stmt = stmt.where(Project.status != "archived")
    rows = (await session.execute(stmt)).scalars().all()
    return {r if isinstance(r, _uuid.UUID) else _uuid.UUID(str(r)) for r in rows}


async def allowed_project_ids_for_similar(
    session: AsyncSession,
    user_id: str | None,
    source_project_id: str | None,
    cross_project: bool,
) -> set[str] | None:
    """Compute the project-scope set for a ``/{id}/similar/`` search.

    Shared by every per-module ``similar`` endpoint so cross-project
    semantic search can never leak row text from a project the caller
    cannot access (the set-level analogue of the per-endpoint
    :func:`verify_project_access` gate already applied to the source row).

    Returns a value to pass straight to ``find_similar(..., allowed_project_ids=)``:

    * ``None`` -> no restriction.  Returned for admins (``accessible_project_ids``
      yields ``None``) and for same-project searches, where the result set
      is already constrained to the caller-authorised ``source_project_id``.
    * a ``set[str]`` -> the caller's accessible project UUIDs (as strings),
      always including ``source_project_id`` so the already-authorised source
      project's own rows survive the filter.  An empty set returns nothing,
      the safe default for a caller with no accessible projects.
    """
    if not cross_project:
        # Same-project search is already scoped to source_project_id, which
        # the router authorised via verify_project_access - no extra filter.
        return None
    ids = await accessible_project_ids(session, user_id)
    if ids is None:
        return None  # admin / unrestricted
    allowed = {str(p) for p in ids}
    if source_project_id:
        allowed.add(str(source_project_id))
    return allowed


# ── Locale resolution (per-request, for HTTPException i18n) ────────────────


def get_lang(request: Request) -> str:
    """Resolve the request's preferred locale as a 2-letter ISO 639-1 code.

    Priority:
        1. ``?locale=XX`` query parameter (explicit override)
        2. First language tag of the ``Accept-Language`` header
        3. ``"en"`` fallback

    The full RFC 7231 parser lives in
    :mod:`app.middleware.accept_language` and already runs on every
    request; this helper exists so router handlers can ask for the same
    resolved code without going through the context variable when they
    want to render an HTTPException detail via
    :func:`app.core.validation.messages.translate`.

    Args:
        request: Incoming FastAPI/Starlette request.

    Returns:
        A 2-letter locale code, e.g. ``"de"`` / ``"ru"`` / ``"en"``.
    """
    # 1. Explicit query override
    qs_locale = request.query_params.get("locale")
    if qs_locale:
        code = qs_locale.strip().lower()[:2]
        if code:
            return code

    # 2. Accept-Language header (first tag, region stripped)
    header = request.headers.get("accept-language", "")
    if header:
        first = header.split(",", 1)[0].strip()
        # Strip ;q=... suffix, then language-region → language
        first = first.split(";", 1)[0].strip()
        code = first.split("-", 1)[0].lower()[:2]
        if code and code.isalpha():
            return code

    # 3. Default
    return "en"


LangDep = Annotated[str, Depends(get_lang)]


# ── Convenience type aliases ───────────────────────────────────────────────

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserPayload = Annotated[dict[str, Any], Depends(get_current_user_payload)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
OptionalUserPayload = Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)]


# ── Tenant scope (multi-tenant isolation, Phase 1 scaffolding) ──────────────
#
# The "tenant" today is simply the owning user's id (the JWT ``sub``);
# there is no separate Tenant entity and no ``tenant_id`` claim in the JWT
# yet. The pure resolver lives in :mod:`app.core.tenant_scope` (import-safe,
# no DB); the request-time dependency is assembled here because this module
# owns ``get_optional_user_payload`` and the session plumbing. Importing
# tenant_scope from here (and never the reverse) keeps the edge acyclic.


async def get_current_tenant_id(
    payload: OptionalUserPayload = None,
) -> str | None:
    """The caller's tenant id, or ``None`` when it cannot be determined.

    Built on :func:`get_optional_user_payload`, so an anonymous or
    unrecognised caller yields ``None`` rather than a 401 - this dependency
    is safe to add to any endpoint without changing its auth contract. For
    an endpoint that must be authenticated, keep using :data:`CurrentUserId`
    for the 401 and use this only to obtain the scoping key.

    Resolution (see :func:`app.core.tenant_scope.resolve_tenant_id`):
    explicit ``tenant_id`` claim if present (forward-compatible), else the
    user id ``sub`` (the tenant == the user in single-tenant installs,
    matching ``Contact.tenant_id`` / ``Snapshot.tenant_id``), else ``None``.
    """
    from app.core.tenant_scope import resolve_tenant_id

    return resolve_tenant_id(payload)


# Annotated alias mirroring ``CurrentUserId`` so routers can write
# ``tenant_id: CurrentTenantId``. None == "tenant unknown" (anonymous).
CurrentTenantId = Annotated[str | None, Depends(get_current_tenant_id)]


async def tenant_scoped_owner_filter(
    session: SessionDep,
    tenant_id: CurrentTenantId = None,
) -> str | None:
    """Reference usage: the ready-to-apply ``owner_id`` filter for the caller.

    Composes :data:`CurrentTenantId` + the session with
    :func:`app.core.tenant_scope.tenant_scope_owner` so a company-wide
    list/aggregate endpoint can scope to the caller's tenant in one line:

        @router.get("/widgets")
        async def list_widgets(
            session: SessionDep,
            owner_id: Annotated[str | None, Depends(tenant_scoped_owner_filter)],
            service: WidgetService = Depends(_get_service),
        ):
            return await service.list(owner_id=owner_id)

    Returns the tenant id for a normal user, or ``None`` for an admin
    (= "do not filter", the same unrestricted sentinel
    :func:`accessible_project_ids` uses). This is **not** wired into any
    existing endpoint yet - it is the Phase 1 reference that Phase 2 rolls
    out module-by-module. Importing or exposing it changes no behaviour.
    """
    from app.core.tenant_scope import tenant_scope_owner

    return await tenant_scope_owner(session, tenant_id)


# ── Epic H - universal audit context dependency ────────────────────────────


async def audit_context_dep(
    payload: Annotated[
        dict[str, Any] | None,
        Depends(get_optional_user_payload),
    ] = None,
) -> None:
    """Enrich the per-request :class:`AuditContext` with resolved identity.

    The :class:`app.middleware.actor_context.ActorContextMiddleware`
    already populated the ContextVar with IP / UA / request-id at the top
    of the request. By the time a router handler resolves dependencies,
    the JWT has been decoded and we can layer the actor/tenant IDs onto
    the same ContextVar so :func:`app.core.audit_log.log_activity` calls
    deeper in the call stack pick them up automatically.

    Mounting this dependency on every router (or via a global router
    dependency) is optional - service-layer callers that pass
    ``actor_id=`` / ``tenant_id=`` explicitly continue to work unchanged.
    Using the dep just spares them the boilerplate.
    """
    from app.core.audit_log import (
        AuditContext,
        get_audit_context,
        set_audit_context,
    )

    if payload is None:
        return  # anonymous request - middleware capture is enough

    current = get_audit_context() or AuditContext()
    actor_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if actor_id is None and tenant_id is None:
        return

    import dataclasses as _dc

    set_audit_context(
        _dc.replace(
            current,
            actor_id=str(actor_id) if actor_id else current.actor_id,
            tenant_id=str(tenant_id) if tenant_id else current.tenant_id,
        ),
    )


AuditContextDep = Annotated[None, Depends(audit_context_dep)]


# ── Row-level-security request context ──────────────────────────────────────


async def rls_request_context(
    tenant_id: CurrentTenantId = None,
) -> AsyncGenerator[None, None]:
    """Bind the caller's tenant to the RLS context for the whole request.

    Generator dependency: it sets the tenant ContextVar that the ``after_begin``
    GUC listener in :mod:`app.core.rls` reads when a transaction starts, then
    clears it when the request ends so the binding never leaks to the next
    request served on the same worker task. Mounted as a global dependency in
    :mod:`app.main`, so every request session is tenant-scoped once
    ``OE_RLS_ENFORCE`` is enabled. An anonymous caller resolves to ``None`` (no
    tenant); a fail-closed policy then denies tenant-scoped rows. Inert while the
    flag is off - the listener ignores the bound value.
    """
    from app.core import rls

    token = rls.set_request_tenant(tenant_id)
    try:
        yield
    finally:
        rls.reset_request_tenant(token)
