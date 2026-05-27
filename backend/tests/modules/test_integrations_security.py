# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integrations module — Round-7 security audit regressions.

Covers the six guarantees the R7 sweep pinned down for outbound
credential-bearing connectors (chat / webhook / email):

1. **SSRF deny-list at write time** — ``IntegrationConfigCreate`` and
   ``WebhookCreate`` reject loopback / RFC1918 / link-local /
   cloud-metadata URLs before the row hits the DB. The deny-list
   covers literal IPv4 (``127.0.0.1``, ``10.x``, ``192.168.x``),
   IPv6 loopback (``::1``), the AWS metadata endpoint
   (``169.254.169.254``), and the magic ``metadata.google.internal``
   hostname. The dispatcher (``service._deliver``) still re-runs a
   DNS-resolving check as the second line of defence, but the schema
   gate is the cheap pre-flight that keeps malicious rows out entirely.

2. **Secret redaction in GET responses** — webhook URLs, bot tokens,
   API keys, OAuth access tokens, SMTP passwords and HMAC secrets
   never round-trip back to the API consumer. The
   ``IntegrationConfigResponse.config`` serializer replaces every
   key in ``_SECRET_CONFIG_KEYS`` with ``***REDACTED***``; the
   ``WebhookResponse.secret`` field is the same. Without redaction,
   a stored-XSS or screen-share leak would surface the credentials
   that drive every outbound connector for the tenant.

3. **HMAC signature determinism + constant-time compare** —
   ``_sign_payload`` produces a stable hex digest, different secrets
   diverge, and the platform's outbound HMAC header (``X-Webhook-
   Signature``) is a pure HMAC-SHA256(payload, secret). The webhook-
   leads sibling test pins the *incoming* HMAC comparison via
   ``hmac.compare_digest`` — this module emits the signature, so we
   only assert deterministic output here.

4. **Rate limit on test endpoints** — the
   ``/configs/{id}/test/`` and ``/webhooks/{id}/test/`` endpoints are
   gated through ``approval_limiter`` (20/min/user). Without the
   cap, a single compromised account could fan-out test deliveries
   against arbitrary third-party hosts and turn the platform into a
   DoS amplifier. The unit test imports the limiter and asserts the
   bucket exists with the expected window.

5. **RBAC: writes elevated to MANAGER** — credentials (webhook URLs,
   bot tokens) carry cross-tenant exfiltration risk, so a plain
   ``EDITOR`` (estimator / QS) must NOT be allowed to wire up new
   connectors. ``integrations.create`` / ``update`` / ``delete``
   require MANAGER+; ``integrations.read`` remains VIEWER-level so
   the list view still loads for everyone.

6. **IDOR on /configs/{id} + /webhooks/{id}** — ownership is checked
   via ``str(config.user_id) != str(user_id)``, returning 404 (not
   403) so a viewer cannot enumerate sibling-tenant integration UUIDs.

The tests use lightweight unit-level checks (Pydantic schema +
permission registry + helper functions) rather than spinning up the
full FastAPI app — much faster, no SQLite required, and the
integration suite under ``tests/integration`` covers wire-level smoke
where it matters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

# ── 1. SSRF deny-list at write time ──────────────────────────────────────


class TestSSRFRejectAtWriteTime:
    """``IntegrationConfigCreate`` and ``WebhookCreate`` block SSRF URLs."""

    def test_webhook_create_rejects_loopback_ipv4(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError) as exc:
            WebhookCreate(
                name="Loopback attack",
                url="http://127.0.0.1:8000/admin",
                events=["*"],
            )
        # The validator wraps ``UnsafeUrlError`` into the Pydantic error.
        msg = str(exc.value)
        assert "127.0.0.1" in msg or "non-routable" in msg, f"expected SSRF rejection message, got: {msg!r}"

    def test_webhook_create_rejects_localhost_hostname(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="Localhost attack",
                url="http://localhost/secrets",
                events=["*"],
            )

    def test_webhook_create_rejects_rfc1918_10_x(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="RFC1918 attack",
                url="http://10.0.0.1/internal",
                events=["*"],
            )

    def test_webhook_create_rejects_rfc1918_192_168(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="RFC1918 attack",
                url="http://192.168.1.1/internal",
                events=["*"],
            )

    def test_webhook_create_rejects_aws_metadata(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="AWS metadata attack",
                url="http://169.254.169.254/latest/meta-data/iam/security-credentials/",
                events=["*"],
            )

    def test_webhook_create_rejects_gcp_metadata_hostname(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="GCP metadata attack",
                url="http://metadata.google.internal/computeMetadata/v1/",
                events=["*"],
            )

    def test_webhook_create_rejects_ipv6_loopback(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="IPv6 loopback attack",
                url="http://[::1]/admin",
                events=["*"],
            )

    def test_webhook_create_rejects_file_scheme(self) -> None:
        from app.modules.integrations.schemas import WebhookCreate

        with pytest.raises(ValidationError):
            WebhookCreate(
                name="file://",
                url="file:///etc/passwd",
                events=["*"],
            )

    def test_webhook_create_accepts_public_https(self) -> None:
        """Happy-path regression guard — the SSRF check must not
        over-block legitimate external webhook URLs (hooks.slack.com,
        discord.com, hooks.com, …).
        """
        from app.modules.integrations.schemas import WebhookCreate

        data = WebhookCreate(
            name="Slack",
            url="https://hooks.slack.com/services/T0/B0/abc",
            events=["rfi.created"],
        )
        assert data.url == "https://hooks.slack.com/services/T0/B0/abc"

    def test_integration_config_rejects_loopback_webhook_url(self) -> None:
        """The connector ``config`` blob's ``webhook_url`` is validated
        for Teams / Slack / Discord / generic-webhook integrations
        before the row ever hits the DB. Otherwise an attacker could
        bypass the ``WebhookEndpoint`` write gate by stashing the same
        URL inside ``IntegrationConfig.config``.
        """
        from app.modules.integrations.schemas import IntegrationConfigCreate

        with pytest.raises(ValidationError) as exc:
            IntegrationConfigCreate(
                integration_type="slack",
                name="bypass attempt",
                config={"webhook_url": "http://127.0.0.1:8000/exfil"},
            )
        assert "unsafe" in str(exc.value) or "127.0.0.1" in str(exc.value)

    def test_integration_config_update_rejects_metadata_webhook(self) -> None:
        """``IntegrationConfigUpdate`` also validates ``webhook_url``
        on PATCH — without this, an attacker could create a benign
        Slack config and then re-point it at the metadata endpoint.
        """
        from app.modules.integrations.schemas import IntegrationConfigUpdate

        with pytest.raises(ValidationError):
            IntegrationConfigUpdate(
                config={"webhook_url": "http://169.254.169.254/foo"},
            )


# ── 2. Secret redaction in GET responses ─────────────────────────────────


class TestSecretRedaction:
    """``IntegrationConfigResponse`` and ``WebhookResponse`` redact secrets."""

    def test_config_response_redacts_webhook_url(self) -> None:
        from app.modules.integrations.schemas import IntegrationConfigResponse

        now = datetime.now(UTC)
        resp = IntegrationConfigResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            integration_type="slack",
            name="My Slack",
            config={
                "webhook_url": "https://hooks.slack.com/services/T0/B0/SECRET_BEARER_TOKEN",
                "channel": "#alerts",
            },
            created_at=now,
            updated_at=now,
        )
        payload = resp.model_dump(mode="json")
        assert payload["config"]["webhook_url"] == "***REDACTED***", (
            f"webhook_url must be redacted in the GET response, got {payload['config']['webhook_url']!r}"
        )
        # Non-secret fields like ``channel`` survive intact so the UI
        # can still render the connector destination label.
        assert payload["config"]["channel"] == "#alerts"
        # Belt-and-braces: the raw token must not appear ANYWHERE in
        # the serialized payload.
        assert "SECRET_BEARER_TOKEN" not in str(payload)

    def test_config_response_redacts_telegram_bot_token(self) -> None:
        from app.modules.integrations.schemas import IntegrationConfigResponse

        now = datetime.now(UTC)
        resp = IntegrationConfigResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            integration_type="telegram",
            name="My Telegram bot",
            config={
                "bot_token": "123456:LIVE_BOTFATHER_SECRET_AAAA",
                "chat_id": "-100123",
            },
            created_at=now,
            updated_at=now,
        )
        payload = resp.model_dump(mode="json")
        assert payload["config"]["bot_token"] == "***REDACTED***"
        # chat_id is NOT secret — needed to display destination.
        assert payload["config"]["chat_id"] == "-100123"
        assert "LIVE_BOTFATHER_SECRET" not in str(payload)

    def test_config_response_redacts_api_key_and_access_token(self) -> None:
        from app.modules.integrations.schemas import IntegrationConfigResponse

        now = datetime.now(UTC)
        resp = IntegrationConfigResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            integration_type="webhook",
            name="Custom HTTP",
            config={
                "api_key": "sk-PROD-LIVE-aaaaaaaaaaaaaaaa",
                "access_token": "OAuth-LIVE-bbbbbbbbbbbbbbbb",
                "smtp_password": "P@ssw0rd!2026",
                "endpoint": "https://api.example.com",
            },
            created_at=now,
            updated_at=now,
        )
        payload = resp.model_dump(mode="json")
        assert payload["config"]["api_key"] == "***REDACTED***"
        assert payload["config"]["access_token"] == "***REDACTED***"
        assert payload["config"]["smtp_password"] == "***REDACTED***"
        # Non-secret endpoint survives.
        assert payload["config"]["endpoint"] == "https://api.example.com"
        for needle in ("sk-PROD-LIVE", "OAuth-LIVE", "P@ssw0rd"):
            assert needle not in str(payload), f"plaintext secret {needle!r} leaked in response payload"

    def test_webhook_response_redacts_secret(self) -> None:
        from app.modules.integrations.schemas import WebhookResponse

        now = datetime.now(UTC)
        resp = WebhookResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="My Hook",
            url="https://example.com",
            secret="ULTRA_SECRET_HMAC_KEY",
            events=["*"],
            created_at=now,
            updated_at=now,
        )
        payload = resp.model_dump(mode="json")
        assert payload["secret"] == "***REDACTED***"
        assert "ULTRA_SECRET_HMAC_KEY" not in str(payload)

    def test_webhook_response_null_secret_stays_null(self) -> None:
        """If the user never set an HMAC secret, the redactor must
        leave the field ``None`` rather than emit ``***REDACTED***`` —
        otherwise the UI would falsely render a "signing enabled" badge.
        """
        from app.modules.integrations.schemas import WebhookResponse

        now = datetime.now(UTC)
        resp = WebhookResponse(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Unsigned",
            url="https://example.com",
            secret=None,
            events=["*"],
            created_at=now,
            updated_at=now,
        )
        payload = resp.model_dump(mode="json")
        assert payload["secret"] is None


# ── 3. HMAC signature determinism ────────────────────────────────────────


class TestHMACSignature:
    """``_sign_payload`` produces a stable hex digest."""

    def test_sign_deterministic(self) -> None:
        from app.modules.integrations.service import _sign_payload

        payload = b'{"event":"test","ts":1700000000}'
        sig1 = _sign_payload(payload, "secret-key")
        sig2 = _sign_payload(payload, "secret-key")
        assert sig1 == sig2, "HMAC must be deterministic for the same secret"
        assert len(sig1) == 64, "hex digest of SHA-256 is 64 chars"

    def test_sign_different_secrets_diverge(self) -> None:
        from app.modules.integrations.service import _sign_payload

        payload = b'{"event":"test"}'
        sig_a = _sign_payload(payload, "secret-a")
        sig_b = _sign_payload(payload, "secret-b")
        assert sig_a != sig_b, "HMAC must change with different secrets"

    def test_sign_different_payloads_diverge(self) -> None:
        from app.modules.integrations.service import _sign_payload

        sig_a = _sign_payload(b'{"event":"a"}', "key")
        sig_b = _sign_payload(b'{"event":"b"}', "key")
        assert sig_a != sig_b, "HMAC must change when payload changes"


# ── 4. Rate limit on test endpoints ──────────────────────────────────────


class TestRateLimiterWired:
    """``approval_limiter`` is the bucket used by the test endpoints."""

    def test_approval_limiter_caps_writes(self) -> None:
        from app.core.rate_limiter import RateLimiter, approval_limiter

        assert isinstance(approval_limiter, RateLimiter)
        # Default cap is 20/min — tight enough to refuse a flood, wide
        # enough that a developer iterating in the UI doesn't trip it.
        assert approval_limiter.max_requests == 20
        assert approval_limiter.window_seconds == 60

    def test_approval_limiter_blocks_after_n_calls(self) -> None:
        """End-to-end: the same key MUST be denied after exhausting
        the bucket — guards against a future refactor that swaps the
        sliding-window for a no-op stub.
        """
        from app.core.rate_limiter import RateLimiter

        limiter = RateLimiter(max_requests=3, window_seconds=60)
        key = f"unit-test-{uuid.uuid4().hex[:6]}"
        assert limiter.is_allowed(key)[0] is True
        assert limiter.is_allowed(key)[0] is True
        assert limiter.is_allowed(key)[0] is True
        # 4th request in the window must be refused.
        allowed, remaining = limiter.is_allowed(key)
        assert allowed is False
        assert remaining == 0

    def test_test_endpoint_imports_approval_limiter(self) -> None:
        """The router module references ``approval_limiter`` — this
        catches a future cleanup that accidentally drops the import.
        """
        import app.modules.integrations.router as router_mod

        assert hasattr(router_mod, "approval_limiter"), "router must import approval_limiter for the /test endpoints"


# ── 5. RBAC: writes elevated to MANAGER ──────────────────────────────────


class TestRBACManager:
    """Credential-writing routes must be MANAGER+; reads stay VIEWER."""

    def _ensure_registered(self) -> None:
        from app.modules.integrations.permissions import register_integrations_permissions

        register_integrations_permissions()

    def test_editor_cannot_create_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "integrations.create",
        ), (
            "EDITOR must NOT carry integrations.create — credentials "
            "(webhook URLs, bot tokens) are cross-tenant risk vectors "
            "that require manager-or-higher RBAC."
        )

    def test_editor_cannot_update_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "integrations.update",
        )

    def test_editor_cannot_delete_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert not permission_registry.role_has_permission(
            Role.EDITOR,
            "integrations.delete",
        )

    def test_manager_can_create_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        for perm in (
            "integrations.create",
            "integrations.update",
            "integrations.delete",
        ):
            assert permission_registry.role_has_permission(
                Role.MANAGER,
                perm,
            ), f"MANAGER must carry {perm}"

    def test_viewer_can_read_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        assert permission_registry.role_has_permission(
            Role.VIEWER,
            "integrations.read",
        )

    def test_viewer_cannot_write_integration(self) -> None:
        self._ensure_registered()
        from app.core.permissions import Role, permission_registry

        for perm in (
            "integrations.create",
            "integrations.update",
            "integrations.delete",
        ):
            assert not permission_registry.role_has_permission(
                Role.VIEWER,
                perm,
            )


# ── 6. IDOR safety regression ────────────────────────────────────────────


class TestIDORShape:
    """Router-level IDOR checks return 404 (not 403) for foreign rows."""

    def test_router_returns_404_for_foreign_config(self) -> None:
        """Static guard: the router still uses the 404-not-403 pattern.

        We grep the source rather than spin up the full HTTP stack — a
        future drift that switches to 403 (and turns the endpoint into
        a UUID-existence oracle) shows up as a red test.
        """
        from pathlib import Path

        import app.modules.integrations.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        # The handler raises 404 on the user-id mismatch — assert the
        # pattern survives.
        assert "Config not found" in source, "404 leak-safe response must remain"
        # Belt-and-braces — there must be NO ``status_code=403`` in this
        # router. Any 403 in an IDOR handler is by definition a leak.
        assert "status_code=403" not in source, (
            "router uses 403 somewhere — IDOR handlers must 404 to avoid leaking UUID existence"
        )

    def test_webhook_router_returns_404_for_foreign_webhook(self) -> None:
        from pathlib import Path

        import app.modules.integrations.router as router_mod

        source = Path(router_mod.__file__).read_text(encoding="utf-8")
        assert source.count("Webhook not found") >= 4, (
            "every webhook handler that loads by id must 404 on a "
            "cross-tenant mismatch — fewer than 4 occurrences means "
            "an endpoint dropped the guard"
        )


# ── 7. Test endpoint hardening surface ───────────────────────────────────


def test_router_test_endpoint_uses_resolve_validator() -> None:
    """The ``/configs/{id}/test/`` handler must call
    ``resolve_and_validate_external_url`` before httpx — without it,
    a row inserted before the SSRF check landed (or one that rebinds
    to a private IP at DNS-resolve time) could still exfiltrate to
    the metadata endpoint.
    """
    from pathlib import Path

    import app.modules.integrations.router as router_mod

    source = Path(router_mod.__file__).read_text(encoding="utf-8")
    assert "resolve_and_validate_external_url" in source, (
        "router must invoke resolve_and_validate_external_url inside "
        "the /test handler — the schema-level check alone misses "
        "DNS-rebinding"
    )
