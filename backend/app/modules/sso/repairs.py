# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot repair: move the environment OIDC configuration into a provider row.

Single sign-on is configured per tenant in Settings now. An install that set ``OIDC_ENABLED`` and
friends in its environment gets one provider row, slug ``oidc``, built from those values on its
next boot, so its users keep signing in through the same IdP and the same redirect URI
(``/auth/oidc/callback``). The row is delivered once: an admin who deletes or edits it keeps that
decision, and the environment values are ignored from then on.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.data_repairs import (
    DataRepair,
    NeverDelivered,
    delivered_keys,
    record_deliveries,
    register_data_repair,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

REPAIR_ID = "sso_env_oidc_provider"
ENV_SLUG = "oidc"


def _role_map(raw: str) -> dict[str, str]:
    try:
        mapping = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(mapping, dict):
        return {}
    return {str(k): str(v) for k, v in mapping.items() if v in ("admin", "manager", "editor", "viewer")}


async def migrate_env_oidc(session: AsyncSession) -> int:
    """Insert the provider row for the environment OIDC settings once; return rows inserted."""
    from app.config import get_settings
    from app.core.crypto import encrypt_secret
    from app.modules.sso.models import SsoProvider

    s = get_settings()
    # Kept verbatim: existing accounts carry this exact string as their oidc_issuer.
    issuer = s.oidc_issuer_url or ""
    if not s.oidc_enabled or not issuer or not s.oidc_client_id:
        return 0
    key = f"{issuer}|{s.oidc_client_id}"
    if key in await delivered_keys(session, REPAIR_ID):
        return 0
    existing = await session.execute(
        select(SsoProvider.id).where(
            (SsoProvider.slug == ENV_SLUG)
            | ((SsoProvider.oidc_issuer == issuer) & (SsoProvider.oidc_client_id == s.oidc_client_id))
        )
    )
    inserted = existing.first() is None
    if inserted:
        mapping = _role_map(s.oidc_group_role_map)
        session.add(
            SsoProvider(
                slug=ENV_SLUG,
                display_name="Single sign-on",
                protocol="oidc",
                enabled=True,
                email_domains=[],
                auto_create_users=s.oidc_auto_create_users,
                default_role=s.oidc_default_role,
                group_attribute=s.oidc_role_claims or "groups",
                group_role_map=mapping,
                allow_admin_mapping="admin" in mapping.values(),
                link_by_email=True,
                oidc_issuer=issuer,
                oidc_client_id=s.oidc_client_id,
                oidc_client_secret_enc=encrypt_secret(s.oidc_client_secret or None),
                oidc_scopes=s.oidc_scopes or "openid email profile",
            )
        )
        await session.flush()
        logger.info("SSO: environment OIDC settings moved into provider '%s'; OIDC_* are now ignored", ENV_SLUG)
    await record_deliveries(session, REPAIR_ID, [key])
    return int(inserted)


SSO_ENV_OIDC_PROVIDER = register_data_repair(
    DataRepair(
        repair_id=REPAIR_ID,
        revision="",
        summary="Move the environment OIDC configuration into an oe_sso provider row",
        run=migrate_env_oidc,
        nature="never_delivered",
        never_delivered=NeverDelivered(table="oe_sso_provider", identified_by=("slug",)),
    )
)
