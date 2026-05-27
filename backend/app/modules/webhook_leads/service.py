"""Webhook Leads service — security, payload mapping, lead creation.

Pure helpers (no I/O) for credential hashing, signature verification,
IP-allowlist matching, and JSON-path extraction are kept at module level
so they can be unit-tested in isolation. Anything that hits the DB lives
on :class:`WebhookLeadsService`.

Security model
~~~~~~~~~~~~~~
The public ingestion endpoint never trusts the platform JWT session.
Instead it authenticates the *caller* against the per-source credential:

* ``api_key`` — caller sends ``X-Api-Key: <key>``; compared in constant
  time against ``sha256(key)`` stored on the source.
* ``hmac``   — caller sends ``X-Webhook-Signature: <hexdigest>``; the
  digest is recomputed as ``HMAC-SHA256(secret, RAW_BODY_BYTES)`` and
  compared in constant time. Verification is over the **raw request
  body bytes**, never a reparsed JSON re-serialisation.
* ``jwt``    — caller sends ``Authorization: Bearer <jwt>``; the JWT is
  verified HS256 against the source secret.

In addition: an optional per-source IP allowlist and a per-source
sliding-window rate limit. Every attempt — accepted, rejected, or
errored — writes a :class:`WebhookLog` row.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from app.modules.webhook_leads.models import (
    PayloadMapping,
    WebhookLog,
    WebhookSource,
)
from app.modules.webhook_leads.repository import (
    PayloadMappingRepository,
    WebhookLogRepository,
    WebhookSourceRepository,
)
from app.modules.webhook_leads.schemas import (
    ALLOWED_TARGET_FIELDS,
    ALLOWED_TRANSFORMS,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.webhook_leads.schemas import (
        PayloadMappingCreate,
        PayloadMappingUpdate,
        WebhookSourceCreate,
        WebhookSourceUpdate,
    )

logger = logging.getLogger(__name__)

# Hard cap on the payload snapshot persisted into WebhookLog.payload. A
# malicious caller could POST megabytes; we keep an auditable head only.
MAX_LOGGED_PAYLOAD_BYTES: int = 16_384

# CRM Lead requires a non-empty contact_name; if no mapping fills it we
# fall back to this so a partially-mapped source still produces a lead
# rather than 500-ing inside the CRM layer.
_FALLBACK_CONTACT_NAME = "Unknown (webhook)"


# ── Pure security helpers ─────────────────────────────────────────────────


def hash_secret(secret: str) -> str:
    """Return the SHA-256 hex digest of a shared secret / API key."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_secret() -> str:
    """Generate a high-entropy URL-safe secret (shown to operator once)."""
    return secrets.token_urlsafe(32)


def verify_api_key(presented_key: str | None, stored_hash: str) -> bool:
    """Constant-time check that ``sha256(presented_key) == stored_hash``."""
    if not presented_key or not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(presented_key), stored_hash)


def verify_hmac_signature(raw_body: bytes, presented_sig: str | None, secret: str) -> bool:
    """Verify an HMAC-SHA256 signature over the RAW request body bytes.

    ``presented_sig`` may be a bare hex digest or prefixed (``sha256=``,
    as GitHub-style webhooks send). Comparison is constant time.
    """
    if not presented_sig or not secret:
        return False
    sig = presented_sig.strip()
    if "=" in sig:
        # Accept "sha256=<hex>" style prefixes.
        algo, _, sig = sig.partition("=")
        if algo.lower() not in ("sha256", "hmac-sha256"):
            return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.lower())


def verify_jwt(token: str | None, secret: str) -> bool:
    """Verify an HS256 JWT signed with the per-source secret."""
    if not token:
        return False
    try:
        from jose import JWTError, jwt

        jwt.decode(token, secret, algorithms=["HS256"])
        return True
    except (JWTError, Exception):  # noqa: BLE001
        return False


def ip_allowed(remote_ip: str, allowlist: list[str] | None) -> bool:
    """Return True when ``remote_ip`` is permitted.

    An empty / missing allowlist means "any IP". Otherwise the remote IP
    must match an entry exactly (CIDR is intentionally out of scope —
    operators list explicit egress IPs of their marketing/ad platform).
    """
    if not allowlist:
        return True
    return remote_ip in set(allowlist)


def truncate_payload(payload: Any) -> Any:
    """Cap the JSON snapshot persisted into the audit log.

    Serialises defensively; oversized or non-serialisable bodies are
    replaced with a small marker so a hostile payload can't bloat the DB
    or break the log write.
    """
    import json

    try:
        encoded = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"_truncated": True, "_reason": "unserialisable"}
    if len(encoded.encode("utf-8")) <= MAX_LOGGED_PAYLOAD_BYTES:
        return payload
    return {
        "_truncated": True,
        "_bytes": len(encoded.encode("utf-8")),
        "_head": encoded[:2000],
    }


def extract_path(payload: Any, dotted_path: str) -> Any:
    """Resolve a dotted JSON path against ``payload``.

    Numeric segments index into lists (``items.0.name``). Returns ``None``
    if any segment is missing rather than raising — a missing optional
    field must not abort the whole ingestion.
    """
    current: Any = payload
    for seg in dotted_path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(seg)
        elif isinstance(current, list):
            try:
                idx = int(seg)
            except (TypeError, ValueError):
                return None
            if -len(current) <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def apply_transform(value: Any, transform: str | None) -> Any:
    """Apply a named pure string transform. Unknown names are a no-op."""
    if value is None or not transform:
        return value
    t = transform.lower()
    if t not in ALLOWED_TRANSFORMS:
        return value
    s = str(value)
    if t == "lower":
        return s.lower()
    if t == "upper":
        return s.upper()
    if t == "strip":
        return s.strip()
    if t == "title":
        return s.title()
    return s  # "str"


def map_payload_to_lead(
    payload: Any,
    mappings: list[PayloadMapping],
    *,
    default_lead_source: str = "web",
) -> tuple[dict[str, Any], list[str]]:
    """Apply mapping rules → CRM Lead kwargs.

    Returns ``(lead_fields, missing_required)``. ``missing_required`` lists
    the ``target_field`` names whose mapping was marked required but whose
    resolved value was absent/empty — the caller turns a non-empty list
    into a 422.
    """
    lead_fields: dict[str, Any] = {}
    missing_required: list[str] = []

    for m in mappings:
        if m.target_field not in ALLOWED_TARGET_FIELDS:
            # Defensive: schema validation already blocks this on write,
            # but a hand-edited DB row must not inject arbitrary kwargs.
            continue
        raw = extract_path(payload, m.source_path)
        value = apply_transform(raw, m.transform)
        is_empty = value is None or (isinstance(value, str) and value.strip() == "")
        if is_empty:
            if m.required:
                missing_required.append(m.target_field)
            continue
        lead_fields[m.target_field] = value

    lead_fields.setdefault("source", default_lead_source)
    return lead_fields, missing_required


class WebhookAuthError(Exception):
    """Raised by :meth:`authenticate_source` — carries an HTTP status.

    Caught by the router so an audit log is always written before the
    response is returned.
    """

    def __init__(self, http_status: int, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.message = message


# ── Per-source sliding-window rate limiter ────────────────────────────────


class _SourceRateLimiter:
    """In-memory per-source sliding window.

    The platform's :class:`app.core.rate_limiter.RateLimiter` is a fixed
    per-process limit; webhook sources need an *independent, per-source
    configurable* limit (a marketing form vs. an ad platform have very
    different volumes), so we key a sliding window by source id with the
    source's own ``rate_limit_per_min``.
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = Lock()

    def check(self, source_key: str, limit_per_min: int) -> bool:
        now = time.time()
        with self._lock:
            window = [t for t in self._hits.get(source_key, []) if t > now - 60]
            if len(window) >= limit_per_min:
                self._hits[source_key] = window
                return False
            window.append(now)
            self._hits[source_key] = window
            return True

    def reset(self, source_key: str | None = None) -> None:
        with self._lock:
            if source_key is None:
                self._hits.clear()
            else:
                self._hits.pop(source_key, None)


# Module-level singleton (process-wide, like the platform limiters).
source_rate_limiter = _SourceRateLimiter()


# ── Service class ─────────────────────────────────────────────────────────


class WebhookLeadsService:
    """Business logic for the Webhook Leads module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.source_repo = WebhookSourceRepository(session)
        self.mapping_repo = PayloadMappingRepository(session)
        self.log_repo = WebhookLogRepository(session)

    # ── Source CRUD ──────────────────────────────────────────────────────

    async def create_source(self, data: WebhookSourceCreate, user_id: str | None = None) -> tuple[WebhookSource, str]:
        """Create a source, returning the model + the one-time plaintext secret."""
        existing = await self.source_repo.get_by_slug(data.slug)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Webhook source slug '{data.slug}' already exists",
            )
        secret = generate_secret()
        source = WebhookSource(
            project_id=data.project_id,
            name=data.name,
            slug=data.slug,
            auth_method=data.auth_method,
            secret_hash=hash_secret(secret),
            ip_allowlist=list(data.ip_allowlist or []),
            is_active=data.is_active,
            rate_limit_per_min=data.rate_limit_per_min,
            default_lead_source=data.default_lead_source,
            created_by=_to_uuid_or_none(user_id),
        )
        await self.source_repo.create(source)
        logger.info("Webhook source created: %s (%s)", source.slug, source.id)
        return source, secret

    async def get_source(self, source_id: uuid.UUID) -> WebhookSource:
        source = await self.source_repo.get_by_id(source_id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Webhook source not found",
            )
        return source

    async def update_source(self, source_id: uuid.UUID, data: WebhookSourceUpdate) -> WebhookSource:
        source = await self.get_source(source_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.source_repo.update_fields(source_id, **fields)
            await self.session.refresh(source)
        return source

    async def rotate_secret(self, source_id: uuid.UUID) -> tuple[WebhookSource, str]:
        source = await self.get_source(source_id)
        secret = generate_secret()
        await self.source_repo.update_fields(source_id, secret_hash=hash_secret(secret))
        await self.session.refresh(source)
        logger.info("Webhook source secret rotated: %s", source_id)
        return source, secret

    async def delete_source(self, source_id: uuid.UUID) -> None:
        await self.get_source(source_id)
        await self.source_repo.delete(source_id)

    # ── Mapping CRUD ─────────────────────────────────────────────────────

    async def create_mapping(self, source_id: uuid.UUID, data: PayloadMappingCreate) -> PayloadMapping:
        await self.get_source(source_id)  # 404 if missing
        if data.target_field not in ALLOWED_TARGET_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"target_field '{data.target_field}' is not a mappable CRM lead field"),
            )
        if data.transform is not None and data.transform not in ALLOWED_TRANSFORMS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"transform '{data.transform}' is not supported",
            )
        mapping = PayloadMapping(
            source_id=source_id,
            target_field=data.target_field,
            source_path=data.source_path,
            transform=data.transform,
            required=data.required,
        )
        await self.mapping_repo.create(mapping)
        return mapping

    async def list_mappings(self, source_id: uuid.UUID) -> list[PayloadMapping]:
        await self.get_source(source_id)
        return await self.mapping_repo.list_for_source(source_id)

    async def update_mapping(self, mapping_id: uuid.UUID, data: PayloadMappingUpdate) -> PayloadMapping:
        mapping = await self.mapping_repo.get_by_id(mapping_id)
        if mapping is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mapping not found",
            )
        fields = data.model_dump(exclude_unset=True)
        if "target_field" in fields and fields["target_field"] not in ALLOWED_TARGET_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_field is not a mappable CRM lead field",
            )
        if fields.get("transform") is not None and fields["transform"] not in ALLOWED_TRANSFORMS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="transform is not supported",
            )
        if fields:
            await self.mapping_repo.update_fields(mapping_id, **fields)
            await self.session.refresh(mapping)
        return mapping

    async def delete_mapping(self, mapping_id: uuid.UUID) -> None:
        mapping = await self.mapping_repo.get_by_id(mapping_id)
        if mapping is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mapping not found",
            )
        await self.mapping_repo.delete(mapping_id)

    # ── Audit logging ────────────────────────────────────────────────────

    async def _write_log(
        self,
        *,
        source: WebhookSource | None,
        source_slug: str,
        remote_ip: str,
        status_label: str,
        http_status: int,
        payload: Any,
        error_message: str = "",
        created_lead_id: uuid.UUID | None = None,
    ) -> WebhookLog:
        log = WebhookLog(
            source_id=source.id if source is not None else None,
            source_slug=source_slug,
            received_at=datetime.now(UTC).isoformat(),
            remote_ip=remote_ip or "",
            status=status_label,
            http_status=http_status,
            payload=truncate_payload(payload),
            error_message=error_message,
            created_lead_id=created_lead_id,
        )
        await self.log_repo.create(log)
        return log

    # ── Authentication ───────────────────────────────────────────────────

    def authenticate_source(
        self,
        source: WebhookSource,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        remote_ip: str,
        presented_secret_for_test: str | None = None,
    ) -> None:
        """Authenticate one ingestion attempt. Raises :class:`WebhookAuthError`.

        ``headers`` keys are expected lower-cased. ``presented_secret_for_test``
        lets callers (and tests) recover the verifying secret without DB
        round-trips — production passes the live source's plaintext secret
        is *not* available (only the hash), so HMAC/JWT verification uses
        the stored hash semantics described below.
        """
        if not source.is_active:
            raise WebhookAuthError(status.HTTP_403_FORBIDDEN, "Webhook source is disabled")

        if not ip_allowed(remote_ip, source.ip_allowlist):
            raise WebhookAuthError(
                status.HTTP_403_FORBIDDEN,
                f"Client IP {remote_ip} is not in the source allowlist",
            )

        method = source.auth_method
        if method == "api_key":
            presented = headers.get("x-api-key") or headers.get("x-webhook-key")
            if not verify_api_key(presented, source.secret_hash):
                raise WebhookAuthError(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
        elif method == "hmac":
            presented_sig = headers.get("x-webhook-signature") or headers.get("x-hub-signature-256")
            secret = presented_secret_for_test
            if secret is None:
                # HMAC/JWT need the plaintext secret, which we deliberately
                # do not store. The supported production model is: the
                # operator configures the source as ``api_key`` (hash-based,
                # zero plaintext at rest) OR supplies the verifying secret
                # via the per-source env override below.
                secret = _resolve_runtime_secret(source)
            if secret is None or not verify_hmac_signature(raw_body, presented_sig, secret):
                raise WebhookAuthError(
                    status.HTTP_401_UNAUTHORIZED,
                    "Invalid or missing HMAC signature",
                )
        elif method == "jwt":
            authz = headers.get("authorization", "")
            token = authz.split(" ", 1)[1] if authz.lower().startswith("bearer ") else None
            secret = presented_secret_for_test or _resolve_runtime_secret(source)
            if secret is None or not verify_jwt(token, secret):
                raise WebhookAuthError(status.HTTP_401_UNAUTHORIZED, "Invalid or missing JWT")
        else:  # pragma: no cover - schema-validated on write
            raise WebhookAuthError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Unknown auth method '{method}'",
            )

    def check_rate_limit(self, source: WebhookSource) -> None:
        """Raise :class:`WebhookAuthError` 429 when the source is over budget."""
        allowed = source_rate_limiter.check(str(source.id), source.rate_limit_per_min)
        if not allowed:
            raise WebhookAuthError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Per-source rate limit exceeded",
            )

    # ── Ingestion (orchestration) ────────────────────────────────────────

    async def ingest(
        self,
        *,
        source_slug: str,
        raw_body: bytes,
        parsed_payload: Any,
        headers: dict[str, str],
        remote_ip: str,
        presented_secret_for_test: str | None = None,
    ) -> tuple[WebhookLog, uuid.UUID]:
        """Full ingestion pipeline.

        Always writes a :class:`WebhookLog`. Raises :class:`HTTPException`
        with the audit log already persisted on every failure path. On
        success returns ``(log, created_lead_id)``.
        """
        source = await self.source_repo.get_by_slug(source_slug)

        # Unknown slug — still auditable.
        if source is None:
            log = await self._write_log(
                source=None,
                source_slug=source_slug,
                remote_ip=remote_ip,
                status_label="rejected",
                http_status=status.HTTP_404_NOT_FOUND,
                payload=parsed_payload,
                error_message="Unknown webhook source slug",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Unknown webhook source",
                headers={"X-Webhook-Log-Id": str(log.id)},
            )

        # Auth + rate limit.
        try:
            self.authenticate_source(
                source,
                raw_body=raw_body,
                headers=headers,
                remote_ip=remote_ip,
                presented_secret_for_test=presented_secret_for_test,
            )
            self.check_rate_limit(source)
        except WebhookAuthError as exc:
            await self._write_log(
                source=source,
                source_slug=source_slug,
                remote_ip=remote_ip,
                status_label="rejected",
                http_status=exc.http_status,
                payload=parsed_payload,
                error_message=exc.message,
            )
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc

        # Payload mapping.
        mappings = await self.mapping_repo.list_for_source(source.id)
        lead_fields, missing = map_payload_to_lead(
            parsed_payload,
            mappings,
            default_lead_source=source.default_lead_source,
        )
        if missing:
            msg = f"Missing required mapped field(s): {', '.join(sorted(missing))}"
            await self._write_log(
                source=source,
                source_slug=source_slug,
                remote_ip=remote_ip,
                status_label="rejected",
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                payload=parsed_payload,
                error_message=msg,
            )
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)

        # Create the CRM lead via the CRM service (no table duplication).
        try:
            lead_id = await self._create_crm_lead(lead_fields)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._write_log(
                source=source,
                source_slug=source_slug,
                remote_ip=remote_ip,
                status_label="error",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                payload=parsed_payload,
                error_message=f"CRM lead creation failed: {exc}",
            )
            logger.exception("Webhook lead creation failed for %s", source_slug)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Lead creation failed",
            ) from exc

        log = await self._write_log(
            source=source,
            source_slug=source_slug,
            remote_ip=remote_ip,
            status_label="accepted",
            http_status=status.HTTP_201_CREATED,
            payload=parsed_payload,
            created_lead_id=lead_id,
        )
        logger.info("Webhook lead created via source %s → lead %s", source_slug, lead_id)
        return log, lead_id

    async def _create_crm_lead(self, lead_fields: dict[str, Any]) -> uuid.UUID:
        """Delegate to the CRM module's lead-create path.

        Imported lazily so this module's tests can run without the CRM
        package being eagerly imported, and so the dependency is honoured
        at call time (matching the manifest ``depends=["oe_crm"]``).
        """
        from app.modules.crm.schemas import LeadCreate
        from app.modules.crm.service import CrmService

        lead_fields.setdefault("contact_name", _FALLBACK_CONTACT_NAME)
        # LeadCreate validates source against the CRM enum; an unmapped /
        # odd source falls back to "web".
        try:
            payload = LeadCreate(**lead_fields)
        except Exception:  # noqa: BLE001 - normalise then retry once
            safe = dict(lead_fields)
            safe["source"] = "web"
            payload = LeadCreate(**safe)

        crm = CrmService(self.session)
        lead = await crm.create_lead(payload)
        return lead.id


def _to_uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _resolve_runtime_secret(source: WebhookSource) -> str | None:
    """Resolve the plaintext secret for HMAC/JWT verification.

    Plaintext secrets are deliberately NOT stored at rest (only a SHA-256
    hash). For HMAC/JWT sources the verifying secret is supplied out of
    band via an environment variable named
    ``WEBHOOK_LEADS_SECRET__<SLUG>`` (slug upper-cased, ``-`` → ``_``).
    Returns ``None`` when not configured (verification then fails closed).
    """
    import os
    import re

    key = "WEBHOOK_LEADS_SECRET__" + re.sub(r"[^A-Z0-9]", "_", source.slug.upper())
    return os.environ.get(key)
