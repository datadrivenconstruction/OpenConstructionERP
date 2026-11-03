# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM 2.0 discovery documents (RFC 7643/7644) and the admin API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SPC_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"

MAX_RESULTS = 100


def service_provider_config(base: str) -> dict[str, Any]:
    return {
        "schemas": [SPC_SCHEMA],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_RESULTS},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer token",
                "description": "API key with the scim scope, sent as Authorization: Bearer or X-API-Key.",
                "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
                "primary": True,
            }
        ],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base}/ServiceProviderConfig"},
    }


def resource_types(base: str) -> list[dict[str, Any]]:
    return [
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": name,
            "name": name,
            "endpoint": f"/{name}s",
            "description": name,
            "schema": urn,
            "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/{name}"},
        }
        for name, urn in (("User", USER_SCHEMA), ("Group", GROUP_SCHEMA))
    ]


def _attr(name: str, typ: str = "string", **kw: Any) -> dict[str, Any]:
    base = {
        "name": name,
        "type": typ,
        "multiValued": False,
        "required": False,
        "caseExact": False,
        "mutability": "readWrite",
        "returned": "default",
        "uniqueness": "none",
    }
    base.update(kw)
    return base


def schemas(base: str) -> list[dict[str, Any]]:
    user = {
        "schemas": [SCHEMA_SCHEMA],
        "id": USER_SCHEMA,
        "name": "User",
        "description": "User account",
        "attributes": [
            _attr("userName", required=True, uniqueness="server"),
            _attr("externalId", caseExact=True, uniqueness="server"),
            _attr(
                "name",
                "complex",
                subAttributes=[_attr("formatted"), _attr("givenName"), _attr("familyName")],
            ),
            _attr("displayName"),
            _attr("locale"),
            _attr(
                "emails",
                "complex",
                multiValued=True,
                subAttributes=[_attr("value"), _attr("type"), _attr("primary", "boolean")],
            ),
            _attr("active", "boolean"),
            _attr(
                "groups",
                "complex",
                multiValued=True,
                mutability="readOnly",
                subAttributes=[_attr("value", mutability="readOnly"), _attr("display", mutability="readOnly")],
            ),
        ],
        "meta": {"resourceType": "Schema", "location": f"{base}/Schemas/{USER_SCHEMA}"},
    }
    group = {
        "schemas": [SCHEMA_SCHEMA],
        "id": GROUP_SCHEMA,
        "name": "Group",
        "description": "Group of users",
        "attributes": [
            _attr("displayName", required=True, uniqueness="server"),
            _attr("externalId", caseExact=True),
            _attr(
                "members",
                "complex",
                multiValued=True,
                subAttributes=[_attr("value", mutability="immutable"), _attr("display", mutability="readOnly")],
            ),
        ],
        "meta": {"resourceType": "Schema", "location": f"{base}/Schemas/{GROUP_SCHEMA}"},
    }
    return [user, group]


# ── Admin API (Settings > Identity) ────────────────────────────────────


class ProvisionedUser(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    source: str = Field(description="scim, oidc or local")
    external_id: str | None = None
    last_sync_at: datetime | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    external_id: str | None = None
    role: str | None = None
    member_count: int = 0


class GroupRoleUpdate(BaseModel):
    role: str | None = Field(default=None, max_length=50)


class ScimStatus(BaseModel):
    base_path: str
    users_provisioned: int
    last_change_at: datetime | None
    allow_admin_groups: bool
    sso_enforced_domains: list[str]
    users: list[ProvisionedUser]
    groups: list[GroupOut]
