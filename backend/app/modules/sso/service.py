# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO business logic: provider admin, SAML and OIDC sign-in, JIT provisioning."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.audit import audit_log
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.validation.engine import Severity, validation_engine
from app.modules.sso import saml
from app.modules.sso import schemas as sch
from app.modules.sso.models import SsoProvider
from app.modules.sso.repository import SsoRepository
from app.modules.sso.validators import RULE_SET, normalise_certificate, register_sso_rules
from app.modules.users import oidc
from app.modules.users.models import User
from app.modules.users.schemas import TokenResponse
from app.modules.users.service import UserService, hash_password

logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(minutes=10)
HANDOFF_TTL = timedelta(seconds=60)
_ROLE_ORDER = ("admin", "manager", "editor", "viewer")


def sso_error(status_code: int, code: str, message: str) -> HTTPException:
    """HTTPException carrying a frontend i18n key under ``sso.errors``."""
    return HTTPException(
        status_code=status_code, detail={"code": code, "message_key": f"sso.errors.{code}", "message": message}
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SsoService:
    """Per-request service; *base* is the public origin of this installation."""

    def __init__(self, session: AsyncSession, settings: Settings, base: str = "") -> None:
        self.session = session
        self.settings = settings
        self.base = base.rstrip("/")
        self.repo = SsoRepository(session)
        register_sso_rules()

    # ── URLs ────────────────────────────────────────────────────────────

    def acs_url(self, p: SsoProvider) -> str:
        return f"{self.base}/api/v1/sso/saml/{p.slug}/acs/"

    def metadata_url(self, p: SsoProvider) -> str:
        return f"{self.base}/api/v1/sso/saml/{p.slug}/metadata/"

    def sp_entity_id(self, p: SsoProvider) -> str:
        return p.saml_sp_entity_id or self.metadata_url(p)

    def to_out(self, p: SsoProvider) -> sch.ProviderOut:
        out = sch.ProviderOut.model_validate(p)
        out.has_client_secret = bool(p.oidc_client_secret_enc)
        if p.protocol == "saml":
            out.sp_entity_id = self.sp_entity_id(p)
            out.acs_url = self.acs_url(p)
            out.metadata_url = self.metadata_url(p)
        return out

    # ── Admin ───────────────────────────────────────────────────────────

    async def _validate(self, snapshot: dict[str, Any]) -> None:
        snapshot["saml_available"] = saml.saml_available()
        report = await validation_engine.validate(data=snapshot, rule_sets=[RULE_SET], target_type="sso_provider")
        errors = [r for r in report.results if not r.passed and r.severity == Severity.ERROR]
        for r in report.results:
            if not r.passed and r.severity != Severity.ERROR:
                logger.warning("sso validation warning %s: %s", r.rule_id, r.message)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "validation_failed",
                    "message_key": "sso.errors.validation_failed",
                    "message": "; ".join(r.message for r in errors),
                    "findings": [{"rule_id": r.rule_id, "message": r.message} for r in errors],
                },
            )

    @staticmethod
    def _snapshot(p: SsoProvider) -> dict[str, Any]:
        cols = [c.key for c in SsoProvider.__table__.columns]
        return {k: getattr(p, k) for k in cols}

    async def create(self, data: sch.ProviderCreate, actor_id: uuid.UUID | None) -> SsoProvider:
        if await self.repo.by_slug(data.slug):
            raise sso_error(409, "slug_taken", f"A provider with slug '{data.slug}' already exists.")
        fields = data.model_dump(exclude={"oidc_client_secret"})
        fields["email_domains"] = [d.strip().lower().lstrip("@") for d in fields["email_domains"] if d.strip()]
        p = SsoProvider(**fields, oidc_client_secret_enc=encrypt_secret(data.oidc_client_secret))
        await self._validate(self._snapshot(p))
        if p.saml_idp_cert:
            p.saml_idp_cert = normalise_certificate(p.saml_idp_cert)
        self.session.add(p)
        await self.session.flush()
        await self._audit("sso.provider.create", p, actor_id)
        return p

    async def update(self, p: SsoProvider, data: sch.ProviderUpdate, actor_id: uuid.UUID | None) -> SsoProvider:
        changes = data.model_dump(exclude_unset=True)
        secret = changes.pop("oidc_client_secret", None)
        if "email_domains" in changes and changes["email_domains"] is not None:
            changes["email_domains"] = [d.strip().lower().lstrip("@") for d in changes["email_domains"] if d.strip()]
        snapshot = {**self._snapshot(p), **{k: v for k, v in changes.items() if v is not None or k == "tenant_id"}}
        await self._validate(snapshot)
        for k, v in changes.items():
            if v is not None or k == "tenant_id":
                setattr(p, k, v)
        if "oidc_client_secret" in data.model_fields_set:
            p.oidc_client_secret_enc = encrypt_secret(secret) if secret else None
        if p.saml_idp_cert:
            p.saml_idp_cert = normalise_certificate(p.saml_idp_cert)
        await self.session.flush()
        await self._audit("sso.provider.update", p, actor_id, fields=sorted(changes))
        return p

    async def delete(self, p: SsoProvider, actor_id: uuid.UUID | None) -> None:
        await self._audit("sso.provider.delete", p, actor_id)
        await self.session.delete(p)
        await self.session.flush()

    async def _audit(self, action: str, p: SsoProvider, actor_id: uuid.UUID | None, **details: Any) -> None:
        await audit_log(
            self.session,
            action=action,
            entity_type="sso_provider",
            entity_id=str(p.id),
            user_id=str(actor_id) if actor_id else None,
            details={"slug": p.slug, "protocol": p.protocol, **details},
        )

    async def get_enabled(self, slug: str, protocol: str) -> SsoProvider:
        p = await self.repo.by_slug(slug)
        if p is None or not p.enabled or p.protocol != protocol:
            raise sso_error(404, "provider_not_found", "No enabled provider with this slug.")
        if protocol == "saml" and not saml.saml_available():
            raise sso_error(501, "saml_unavailable", "SAML support is not installed on this server.")
        return p

    # ── SAML ────────────────────────────────────────────────────────────

    async def saml_login_url(self, p: SsoProvider, relay_state: str = "") -> str:
        request_id = saml.new_request_id()
        await self.repo.purge_expired()
        await self.repo.put_one_time("saml_req", request_id, p.slug, datetime.now(UTC) + REQUEST_TTL)
        return saml.build_authn_request(
            request_id=request_id,
            sp_entity_id=self.sp_entity_id(p),
            acs_url=self.acs_url(p),
            idp_sso_url=p.saml_idp_sso_url or "",
            relay_state=relay_state[:80],
        )

    async def saml_acs(self, p: SsoProvider, saml_response: str) -> str:
        """Validate the response, provision the user and return a single-use hand-off code."""
        try:
            a = saml.validate_response(
                saml_response,
                idp_entity_id=p.saml_idp_entity_id or "",
                idp_cert_pem=p.saml_idp_cert or "",
                sp_entity_id=self.sp_entity_id(p),
                acs_url=self.acs_url(p),
                clock_skew_seconds=p.clock_skew_seconds,
            )
        except saml.SamlError as exc:
            logger.info("SAML response refused for %s: %s", p.slug, exc.code)
            raise sso_error(401, exc.code, exc.message) from exc
        if await self.repo.take_one_time("saml_req", a.in_response_to, p.slug) is None:
            raise sso_error(401, "unsolicited", "The sign-in request is unknown, expired or already used.")
        if not a.assertion_id or await self.repo.exists_one_time("saml_assert", a.assertion_id):
            raise sso_error(401, "replayed", "This assertion was already used.")
        keep_until = a.not_on_or_after + timedelta(seconds=p.clock_skew_seconds)
        await self.repo.put_one_time("saml_assert", a.assertion_id, p.slug, keep_until)

        email = next(iter(a.attributes.get(p.saml_email_attribute) or []), "")
        if not email and "@" in a.name_id:
            email = a.name_id
        name = next(iter(a.attributes.get(p.saml_name_attribute) or []), "")
        groups = list(a.attributes.get(p.group_attribute) or [])
        user = await self.provision(p, subject=a.name_id, email=email, full_name=name, groups=groups)
        return await self._handoff(p, user)

    async def _handoff(self, p: SsoProvider, user: User) -> str:
        code = secrets.token_urlsafe(32)
        await self.repo.put_one_time(
            "handoff", _hash(code), p.slug, datetime.now(UTC) + HANDOFF_TTL, {"user_id": str(user.id)}
        )
        return f"{p.slug}.{code}"

    async def redeem_handoff(self, token: str) -> TokenResponse:
        slug, _, code = token.partition(".")
        row = await self.repo.take_one_time("handoff", _hash(code), slug) if code else None
        if row is None:
            raise sso_error(401, "handoff_invalid", "The sign-in link expired or was already used.")
        user = await self.session.get(User, uuid.UUID(row.data["user_id"]))
        if user is None or not user.is_active or user.deleted_at is not None:
            raise sso_error(403, "account_disabled", "This account is deactivated.")
        return await UserService(self.session, self.settings)._issue_token_pair(user)

    # ── OIDC ────────────────────────────────────────────────────────────

    async def oidc_start(self, p: SsoProvider) -> sch.OidcStart:
        disc = await oidc.get_discovery(p.oidc_issuer or "")
        return sch.OidcStart(
            authorization_endpoint=disc["authorization_endpoint"],
            client_id=p.oidc_client_id or "",
            scopes=p.oidc_scopes,
        )

    async def oidc_callback(self, p: SsoProvider, body: sch.OidcCallback) -> TokenResponse:
        if await self.repo.exists_one_time("oidc_nonce", _hash(body.nonce)):
            raise sso_error(401, "replayed", "This sign-in was already completed.")
        disc = await oidc.get_discovery(p.oidc_issuer or "")
        form = {
            "grant_type": "authorization_code",
            "code": body.code,
            "redirect_uri": body.redirect_uri,
            "client_id": p.oidc_client_id or "",
        }
        secret = decrypt_secret(p.oidc_client_secret_enc)
        if secret:
            form["client_secret"] = secret
        if body.code_verifier:
            form["code_verifier"] = body.code_verifier
        userinfo: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(disc["token_endpoint"], data=form)
                if resp.status_code != 200:
                    raise sso_error(401, "token_exchange_failed", "OIDC token exchange failed.")
                tokens = resp.json()
                if not tokens.get("id_token"):
                    raise sso_error(401, "invalid_id_token", "OIDC provider returned no ID token.")
                claims = await oidc.verify_id_token(
                    tokens["id_token"], discovery=disc, client_id=p.oidc_client_id or "", nonce=body.nonce
                )
                if disc.get("userinfo_endpoint") and tokens.get("access_token"):
                    ui = await client.get(
                        disc["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"}
                    )
                    if ui.status_code == 200 and ui.json().get("sub") == claims.get("sub"):
                        userinfo = ui.json()
        except httpx.HTTPError as exc:
            raise sso_error(502, "provider_unreachable", "Could not reach the identity provider.") from exc
        exp = datetime.fromtimestamp(int(claims.get("exp", 0)), UTC) + timedelta(seconds=p.clock_skew_seconds)
        await self.repo.put_one_time("oidc_nonce", _hash(body.nonce), p.slug, max(exp, datetime.now(UTC)))
        email = (
            claims.get("email")
            or userinfo.get("email")
            or (claims.get("preferred_username") if "@" in str(claims.get("preferred_username", "")) else "")
        )
        name = claims.get("name") or userinfo.get("name") or ""
        groups = oidc.extract_groups(p.group_attribute, claims, userinfo)
        user = await self.provision(p, subject=str(claims.get("sub", "")), email=email, full_name=name, groups=groups)
        return await UserService(self.session, self.settings)._issue_token_pair(user)

    # ── JIT provisioning ────────────────────────────────────────────────

    def mapped_role(self, p: SsoProvider, groups: list[str]) -> str | None:
        mapping = p.group_role_map or {}
        roles = {mapping.get(g) for g in groups}
        if not p.allow_admin_mapping:
            roles.discard("admin")
        for role in _ROLE_ORDER:
            if role in roles:
                return role
        return None

    async def provision(self, p: SsoProvider, *, subject: str, email: str, full_name: str, groups: list[str]) -> User:
        """Find or create the account for this IdP identity.

        Match order: the IdP identity already linked, then a SCIM account whose externalId is the
        subject, then the email. SCIM stays authoritative for the role of accounts it provisioned.
        """
        email = (email or "").strip().lower()
        if not subject or "@" not in email:
            raise sso_error(400, "missing_claims", "The identity provider sent no subject or email.")
        domain = email.rpartition("@")[2]
        if p.email_domains and domain not in p.email_domains:
            raise sso_error(403, "domain_not_allowed", "This email domain is not served by this provider.")
        link = f"{p.slug}:{subject}"
        if len(link) > 255:
            link = f"{p.slug}:sha256:{_hash(subject)}"
        issuer = p.oidc_issuer if p.protocol == "oidc" else p.saml_idp_entity_id

        user = (await self.session.execute(select(User).where(User.oidc_sub == link))).scalar_one_or_none()
        how = "returning"
        if user is None:
            stmt = select(User).where(User.external_id == subject, User.provisioned_by == "scim")
            user = (await self.session.execute(stmt)).scalar_one_or_none()
            how = "scim_link"
        if user is None:
            user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            how = "email_link"
            # Taking over an existing account by email needs the admin to have vouched for the domain.
            if user is not None and domain not in (p.email_domains or []):
                raise sso_error(403, "link_needs_domain", "An account with this email exists; list its domain first.")
        role = self.mapped_role(p, groups)
        if user is None:
            if not p.auto_create_users:
                raise sso_error(403, "account_not_found", "No account exists and automatic creation is off.")
            user = User(
                email=email,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                full_name=full_name or email.partition("@")[0],
                role=role or p.default_role,
                is_active=True,
                provisioned_by=p.protocol,
            )
            self.session.add(user)
            how = "created"
        if not user.is_active or user.deleted_at is not None:
            raise sso_error(403, "account_disabled", "This account is deactivated.")
        if user.oidc_sub and user.oidc_sub != link and how != "returning":
            logger.info("SSO relinks user %s from another identity to %s", user.id, p.slug)
        user.oidc_sub = link
        user.oidc_issuer = issuer
        meta = dict(user.metadata_ or {})
        if p.tenant_id and not meta.get("tenant_id"):
            meta["tenant_id"] = p.tenant_id
            user.metadata_ = meta
        old_role = user.role
        if role and user.provisioned_by != "scim" and how != "created":
            user.role = role
        user.last_login_at = datetime.now(UTC)
        await self.session.flush()
        await audit_log(
            self.session,
            action=f"sso.login.{how}",
            entity_type="user",
            entity_id=str(user.id),
            user_id=str(user.id),
            details={
                "provider": p.slug,
                "protocol": p.protocol,
                "role": user.role,
                **({"old_role": old_role} if old_role != user.role else {}),
                "groups": json.dumps(groups[:20]),
            },
        )
        return user
