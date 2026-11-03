# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM 2.0 business logic: user and group provisioning from the company IdP.

Roles come only from groups an admin mapped in the UI; the IdP cannot send a role.
Removal is always a soft deactivation: sessions and API keys end in the same
transaction, the row and its history stay.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.audit import audit_log
from app.core.i18n import SUPPORTED_LOCALES
from app.core.validation.engine import Severity, validation_engine
from app.modules.scim import schemas as sch
from app.modules.scim.models import ScimGroup
from app.modules.scim.repository import ScimRepository
from app.modules.scim.validators import RULE_SET, SCIM_ERROR_MAP, register_scim_rules
from app.modules.users.models import User
from app.modules.users.oidc import VALID_ROLES, most_privileged
from app.modules.users.repository import APIKeyRepository
from app.modules.users.service import hash_password

logger = logging.getLogger(__name__)

_FILTER = re.compile(r'^\s*([A-Za-z][\w.]*)\s+eq\s+"((?:[^"\\]|\\.)*)"\s*$', re.IGNORECASE)
_PATH = re.compile(r"^([^\[\].]+(?:\.[^\[\].]+)?)(?:\[(.*)\])?(?:\.(\w+))?$")
_VALUE_EQ = re.compile(r'value\s+eq\s+"([^"]*)"', re.IGNORECASE)
_USER_URN = sch.USER_SCHEMA + ":"
_GROUP_URN = sch.GROUP_SCHEMA + ":"

GroupOps = list[tuple[str, list[uuid.UUID] | None]]


class ScimError(Exception):
    """A SCIM protocol error (RFC 7644 section 3.12)."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schemas": [sch.ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


# ── Parsing helpers ────────────────────────────────────────────────────


def parse_filter(expr: str | None, allowed: dict[str, str]) -> tuple[str, str] | None:
    """Parse ``attr eq "value"``; anything else is an invalidFilter error."""
    if not expr or not expr.strip():
        return None
    m = _FILTER.match(expr)
    if not m or m.group(1).lower() not in allowed:
        raise ScimError(
            400, f'Unsupported filter. Only {", ".join(sorted(allowed))} eq "value" is supported.', "invalidFilter"
        )
    return allowed[m.group(1).lower()], re.sub(r"\\(.)", r"\1", m.group(2))


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ScimError(400, "active must be a boolean.", "invalidValue")


def _str(value: Any, what: str) -> str:
    if isinstance(value, str):
        return value.strip()
    raise ScimError(400, f"{what} must be a string.", "invalidValue")


def _locale(value: Any) -> str:
    base = str(value or "").replace("_", "-").split("-")[0].lower()
    return base if base in SUPPORTED_LOCALES else "en"


def _uuid(value: Any, what: str = "id") -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ScimError(400, f"{what} '{str(value)[:60]}' is not a valid identifier.", "invalidValue") from None


def _ref(item: Any, what: str) -> uuid.UUID:
    return _uuid(item.get("value") if isinstance(item, dict) else item, what)


def _primary_email(emails: Any) -> str | None:
    if isinstance(emails, str):
        return emails.strip()
    if isinstance(emails, dict):
        emails = [emails]
    if not isinstance(emails, list):
        raise ScimError(400, "emails must be a list.", "invalidValue")
    items = [e for e in emails if isinstance(e, dict) and e.get("value")]
    if not items:
        return None
    chosen = next((e for e in items if _truthy(e.get("primary"))), items[0])
    return _str(chosen["value"], "emails.value")


def _norm_path(path: str) -> tuple[str, str | None]:
    """Return (lowercase attribute key such as ``name.givenname``, filter text or None)."""
    p = path.strip()
    for urn in (_USER_URN, _GROUP_URN):
        if p.startswith(urn):
            p = p[len(urn) :]
    m = _PATH.match(p)
    if not m:
        raise ScimError(400, f"Invalid path '{path[:80]}'.", "invalidPath")
    key = m.group(1).lower() + (f".{m.group(3).lower()}" if m.group(3) else "")
    return key, m.group(2)


def split_name(full_name: str) -> tuple[str, str]:
    first, _, rest = (full_name or "").strip().partition(" ")
    return first, rest.strip()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_user_body(body: dict[str, Any]) -> dict[str, Any]:
    """Map a SCIM User document to our attribute names; absent keys stay absent."""
    attrs: dict[str, Any] = {}
    email = _primary_email(body["emails"]) if "emails" in body else None
    if "userName" in body:
        attrs["email"] = _str(body["userName"], "userName")
        if "@" not in attrs["email"] and email:
            attrs["email"] = email
    elif email:
        attrs["email"] = email
    name = body.get("name")
    if isinstance(name, dict):
        if name.get("formatted"):
            attrs["full_name"] = _str(name["formatted"], "name.formatted")
        elif name.get("givenName") or name.get("familyName"):
            attrs["full_name"] = f"{name.get('givenName') or ''} {name.get('familyName') or ''}".strip()
    if "full_name" not in attrs and body.get("displayName"):
        attrs["full_name"] = _str(body["displayName"], "displayName")
    if "active" in body:
        attrs["active"] = _bool(body["active"])
    if "externalId" in body:
        attrs["external_id"] = _str(body["externalId"], "externalId") or None
    loc = body.get("locale") or body.get("preferredLanguage")
    if loc:
        attrs["locale"] = _str(loc, "locale")
    return attrs


def _operations(body: dict[str, Any]) -> list[tuple[str, str | None, Any]]:
    ops = body.get("Operations")
    if not isinstance(ops, list) or not ops:
        raise ScimError(400, "Operations must be a non-empty list.", "invalidSyntax")
    out = []
    for op in ops:
        name = str(op.get("op", "")).lower() if isinstance(op, dict) else ""
        if name not in ("add", "replace", "remove"):
            raise ScimError(400, "op must be add, replace or remove.", "invalidSyntax")
        out.append((name, op.get("path") or None, op.get("value")))
    return out


def _flatten(op: str, path: str | None, value: Any) -> list[tuple[str, Any]]:
    """Path-less operations carry an object of attribute/value pairs; give every pair its own path."""
    if path:
        return [(path, value)]
    if op == "remove" or not isinstance(value, dict):
        raise ScimError(400, "A path-less operation needs a value object.", "noTarget")
    return list(value.items())


class ScimService:
    """Provisioning operations; every method runs inside the request transaction."""

    def __init__(self, session: AsyncSession, settings: Settings, actor_id: uuid.UUID | None, base: str) -> None:
        self.session = session
        self.settings = settings
        self.actor_id = actor_id
        self.base = base.rstrip("/")
        self.repo = ScimRepository(session)
        register_scim_rules()

    # ── Validation and audit ───────────────────────────────────────────

    async def _validate(self, **snapshot: Any) -> None:
        """Run the scim rule set; the first error becomes a SCIM error, warnings are logged."""
        snapshot.setdefault("allow_admin_groups", bool(self.settings.scim_allow_admin_groups))
        report = await validation_engine.validate(data=snapshot, rule_sets=[RULE_SET], target_type="scim")
        for r in report.results:
            if r.passed:
                continue
            if r.severity == Severity.ERROR:
                status, typ = SCIM_ERROR_MAP.get(r.rule_id, (400, "invalidValue"))
                raise ScimError(status, r.message, typ)
            logger.warning("scim validation warning %s: %s", r.rule_id, r.message)

    async def _audit(self, action: str, entity_type: str, entity_id: uuid.UUID, **details: Any) -> None:
        await audit_log(
            self.session,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            user_id=str(self.actor_id) if self.actor_id else None,
            details={"source": "scim", **details},
        )

    async def _admin_facts(self, user: User | None) -> dict[str, Any]:
        is_admin = bool(user and user.role == "admin" and user.is_active)
        return {
            "target_is_active_admin": is_admin,
            "active_admins": await self.repo.count_active_admins() if is_admin else 0,
            "user_id": str(user.id) if user else None,
        }

    # ── Rendering ──────────────────────────────────────────────────────

    def _loc(self, kind: str, rid: uuid.UUID) -> str:
        return f"{self.base}/{kind}/{rid}"

    def user_resource(self, user: User, groups: list[ScimGroup]) -> dict[str, Any]:
        given, family = split_name(user.full_name)
        out: dict[str, Any] = {
            "schemas": [sch.USER_SCHEMA],
            "id": str(user.id),
            "userName": user.email,
            "name": {"formatted": user.full_name, "givenName": given, "familyName": family},
            "displayName": user.full_name,
            "emails": [{"value": user.email, "type": "work", "primary": True}],
            "active": bool(user.is_active),
            "locale": user.locale,
            "groups": [
                {"value": str(g.id), "display": g.display_name, "$ref": self._loc("Groups", g.id)} for g in groups
            ],
            "meta": {
                "resourceType": "User",
                "created": _iso(user.created_at),
                "lastModified": _iso(user.updated_at),
                "location": self._loc("Users", user.id),
            },
        }
        if user.external_id:
            out["externalId"] = user.external_id
        return out

    def group_resource(self, group: ScimGroup, members: list[User]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schemas": [sch.GROUP_SCHEMA],
            "id": str(group.id),
            "displayName": group.display_name,
            "members": [{"value": str(u.id), "display": u.email, "$ref": self._loc("Users", u.id)} for u in members],
            "meta": {
                "resourceType": "Group",
                "created": _iso(group.created_at),
                "lastModified": _iso(group.updated_at),
                "location": self._loc("Groups", group.id),
            },
        }
        if group.external_id:
            out["externalId"] = group.external_id
        return out

    @staticmethod
    def list_response(resources: list[dict[str, Any]], total: int, start: int) -> dict[str, Any]:
        return {
            "schemas": [sch.LIST_SCHEMA],
            "totalResults": total,
            "startIndex": start,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }

    # ── Roles ──────────────────────────────────────────────────────────

    def _default_role(self) -> str:
        role = self.settings.oidc_default_role
        return role if role in VALID_ROLES and role != "admin" else "viewer"

    async def _sync_role(self, user: User) -> None:
        """Most privileged mapped group wins; no mapped group left falls back to the default role."""
        groups = await self.repo.groups_of_user(user.id)
        roles = [
            g.role
            for g in groups
            if g.role in VALID_ROLES and (g.role != "admin" or self.settings.scim_allow_admin_groups)
        ]
        target = most_privileged(roles) or self._default_role()
        if target == user.role:
            return
        if user.role == "admin":
            await self._validate(loses_admin=True, **await self._admin_facts(user))
        await self._audit("scim.user.role", "user", user.id, old=user.role, new=target)
        user.role = target
        await self.session.flush()

    # ── Users ──────────────────────────────────────────────────────────

    async def _load_user(self, user_id: str) -> User:
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            raise ScimError(404, "User not found.") from None
        user = await self.repo.get_user(uid)
        if user is None:
            raise ScimError(404, "User not found.")
        return user

    async def _render_user(self, user: User) -> dict[str, Any]:
        return self.user_resource(user, await self.repo.groups_of_user(user.id))

    async def list_users(self, flt: str | None, start: int, count: int) -> dict[str, Any]:
        parsed = parse_filter(flt, {"username": "email", "externalid": "external_id"})
        kw = {parsed[0]: parsed[1]} if parsed else {}
        users, total = await self.repo.list_users(offset=max(start, 1) - 1, limit=count, **kw)
        by_user = await self.repo.groups_by_user([u.id for u in users])
        return self.list_response([self.user_resource(u, by_user[u.id]) for u in users], total, max(start, 1))

    async def get_user(self, user_id: str) -> dict[str, Any]:
        return await self._render_user(await self._load_user(user_id))

    async def create_user(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Idempotent create by externalId, then by email. Returns (resource, created)."""
        attrs = parse_user_body(body)
        email = (attrs.get("email") or "").strip().lower()
        if not email:
            raise ScimError(400, "userName is required.", "invalidValue")
        attrs["email"] = email
        ext = attrs.get("external_id")

        existing = await self.repo.user_by_external_id(ext) if ext else None
        adopting = False
        if existing is None:
            existing = await self.repo.user_by_email(email)
            adopting = existing is not None
            if existing is not None and existing.external_id and ext and existing.external_id != ext:
                raise ScimError(409, f"{email} already belongs to a different identity.", "uniqueness")
        if existing is not None:
            await self._apply_attrs(existing, attrs, adopting=adopting)
            return await self._render_user(existing), False

        await self._validate(email=email, email_owner_id=None, user_id=None)
        user = User(
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=attrs.get("full_name", ""),
            role=self._default_role(),
            locale=_locale(attrs.get("locale")),
            is_active=attrs.get("active", True),
            external_id=ext,
            provisioned_by="scim",
        )
        self.session.add(user)
        await self.session.flush()
        await self._audit("scim.user.create", "user", user.id, email=email)
        return self.user_resource(user, []), True

    async def _apply_attrs(self, user: User, attrs: dict[str, Any], *, adopting: bool = False) -> None:
        email = attrs.get("email")
        if email is not None:
            email = email.strip().lower()
            owner = await self.repo.user_by_email(email)
            await self._validate(email=email, email_owner_id=str(owner.id) if owner else None, user_id=str(user.id))
            user.email = email
        if "external_id" in attrs:
            ext = attrs["external_id"]
            if ext:
                other = await self.repo.user_by_external_id(ext)
                if other is not None and other.id != user.id:
                    raise ScimError(409, f"externalId '{ext[:80]}' already belongs to another user.", "uniqueness")
            await self._validate(
                external_id=ext,
                previous_external_id=user.external_id,
                previous_provisioned_by=user.provisioned_by,
                adopting=adopting,
                user_id=str(user.id),
            )
            user.external_id = ext
        if adopting and user.provisioned_by is None:
            user.provisioned_by = "scim"
        if "full_name" in attrs:
            user.full_name = attrs["full_name"]
        if "active" in attrs and attrs["active"] != user.is_active:
            if attrs["active"]:
                await self._reactivate(user)
            else:
                await self._deactivate(user)
        await self.session.flush()

    async def _deactivate(self, user: User) -> None:
        """Soft deactivation: sessions revoked and API keys off in this transaction, audit written."""
        was_active = user.is_active
        if was_active:
            await self._validate(loses_admin=True, **await self._admin_facts(user))
        user.is_active = False
        await self.repo.revoke_sessions(user.id)
        await APIKeyRepository(self.session).deactivate_all_for_user(user.id)
        await self.session.flush()
        if was_active:
            await self._audit("scim.user.deactivate", "user", user.id, email=user.email)

    async def _reactivate(self, user: User) -> None:
        """Access returns; API keys stay off and must be issued again."""
        user.is_active = True
        await self.session.flush()
        await self._audit("scim.user.reactivate", "user", user.id, email=user.email)

    async def replace_user(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        user = await self._load_user(user_id)
        await self._apply_attrs(user, parse_user_body(body))
        return await self._render_user(user)

    async def delete_user(self, user_id: str) -> None:
        await self._deactivate(await self._load_user(user_id))

    async def patch_user(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        user = await self._load_user(user_id)
        attrs: dict[str, Any] = {}
        group_ops: GroupOps = []
        for op, path, value in _operations(body):
            for p, v in _flatten(op, path, value):
                self._patch_user_attr(user, op, p, v, attrs, group_ops)
        given, family = attrs.pop("given", None), attrs.pop("family", None)
        if given is not None or family is not None:
            cur_given, cur_family = split_name(user.full_name)
            new_given = cur_given if given is None else given
            new_family = cur_family if family is None else family
            attrs.setdefault("full_name", f"{new_given} {new_family}".strip())
        await self._apply_attrs(user, attrs)
        await self._patch_memberships(user, group_ops)
        return await self._render_user(user)

    def _patch_user_attr(
        self, user: User, op: str, path: str, value: Any, attrs: dict[str, Any], group_ops: GroupOps
    ) -> None:
        key, filt = _norm_path(path)
        if key in ("id", "meta", "meta.created", "meta.lastmodified"):
            raise ScimError(400, f"{path} is read-only.", "mutability")
        if op == "remove":
            self._patch_user_remove(user, key, filt, value, attrs, group_ops, path)
        elif key == "active":
            attrs["active"] = _bool(value)
        elif key == "username":
            attrs["email"] = _str(value, "userName")
        elif key == "externalid":
            attrs["external_id"] = _str(value, "externalId") or None
        elif key in ("displayname", "name.formatted"):
            attrs["full_name"] = _str(value, key)
        elif key == "name.givenname":
            attrs["given"] = _str(value, key)
        elif key == "name.familyname":
            attrs["family"] = _str(value, key)
        elif key == "name":
            if not isinstance(value, dict):
                raise ScimError(400, "name must be an object.", "invalidValue")
            for sub, target in (("formatted", "full_name"), ("givenName", "given"), ("familyName", "family")):
                if sub in value:
                    attrs[target] = _str(value[sub], f"name.{sub}")
        elif key in ("locale", "preferredlanguage"):
            attrs["locale"] = _str(value, key)
        elif key in ("emails", "emails.value"):
            email = _primary_email(value)
            if email:
                attrs["email"] = email
        elif key == "groups":
            if not isinstance(value, list):
                raise ScimError(400, "groups must be a list.", "invalidValue")
            group_ops.append(("replace" if op == "replace" else "add", [_ref(m, "group") for m in value]))
        else:
            raise ScimError(400, f"Unknown path '{path[:80]}'.", "invalidPath")

    @staticmethod
    def _patch_user_remove(
        user: User, key: str, filt: str | None, value: Any, attrs: dict[str, Any], group_ops: GroupOps, path: str
    ) -> None:
        if key == "externalid":
            attrs["external_id"] = None
        elif key in ("displayname", "name.formatted"):
            attrs["full_name"] = ""
        elif key in ("name.givenname", "name.familyname"):
            attrs["given" if key.endswith("givenname") else "family"] = ""
        elif key in ("emails", "emails.value"):
            # The single email is the login (userName); a secondary address is not stored.
            target = None
            if filt:
                m = _VALUE_EQ.search(filt)
                target = m.group(1).lower() if m else None
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                target = str(value[0].get("value", "")).lower()
            if target is not None and target != user.email.lower():
                raise ScimError(400, "No such email on this user.", "noTarget")
            raise ScimError(400, "The email is the userName and cannot be removed.", "mutability")
        elif key == "groups":
            ids: list[uuid.UUID] | None = None
            if filt:
                m = _VALUE_EQ.search(filt)
                if not m:
                    raise ScimError(400, "Unsupported groups filter.", "invalidFilter")
                ids = [_uuid(m.group(1), "group")]
            elif isinstance(value, list):
                ids = [_ref(x, "group") for x in value]
            group_ops.append(("remove", ids))
        elif key in ("username", "active", "locale", "preferredlanguage", "name"):
            raise ScimError(400, f"{path} cannot be removed.", "mutability")
        else:
            raise ScimError(400, f"Unknown path '{path[:80]}'.", "invalidPath")

    async def _patch_memberships(self, user: User, group_ops: GroupOps) -> None:
        touched_mapped = False
        for op, ids in group_ops:
            current = {g.id: g for g in await self.repo.groups_of_user(user.id)}
            if op == "remove":
                for gid in list(current) if ids is None else ids:
                    if gid not in current:
                        raise ScimError(400, "The user is not a member of that group.", "noTarget")
                    touched_mapped |= current[gid].role is not None
                    await self.repo.remove_members(gid, [user.id])
                continue
            wanted: dict[uuid.UUID, ScimGroup] = {}
            for gid in ids or []:
                group = await self.repo.get_group(gid)
                if group is None:
                    raise ScimError(400, f"Group {gid} not found.", "invalidValue")
                wanted[gid] = group
            if op == "replace":
                for gid in set(current) - set(wanted):
                    touched_mapped |= current[gid].role is not None
                    await self.repo.remove_members(gid, [user.id])
            for gid, group in wanted.items():
                if gid not in current:
                    touched_mapped |= group.role is not None
                    await self.repo.add_members(gid, [user.id])
        if touched_mapped:
            await self._sync_role(user)

    # ── Groups ─────────────────────────────────────────────────────────

    async def _load_group(self, group_id: str) -> ScimGroup:
        try:
            gid = uuid.UUID(group_id)
        except ValueError:
            raise ScimError(404, "Group not found.") from None
        group = await self.repo.get_group(gid)
        if group is None:
            raise ScimError(404, "Group not found.")
        return group

    async def _render_group(self, group: ScimGroup) -> dict[str, Any]:
        return self.group_resource(group, await self.repo.members(group.id))

    async def list_groups(self, flt: str | None, start: int, count: int) -> dict[str, Any]:
        parsed = parse_filter(flt, {"displayname": "name"})
        groups, total = await self.repo.list_groups(
            name=parsed[1] if parsed else None, offset=max(start, 1) - 1, limit=count
        )
        return self.list_response([await self._render_group(g) for g in groups], total, max(start, 1))

    async def get_group(self, group_id: str) -> dict[str, Any]:
        return await self._render_group(await self._load_group(group_id))

    async def _member_users(self, raw: Any) -> list[uuid.UUID]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ScimError(400, "members must be a list.", "invalidValue")
        ids = []
        for m in raw:
            uid = _ref(m, "member")
            if await self.repo.get_user(uid) is None:
                raise ScimError(400, f"Member {uid} not found.", "invalidValue")
            ids.append(uid)
        return ids

    async def _check_group_name(self, name: str, group: ScimGroup | None) -> None:
        if not name:
            raise ScimError(400, "displayName is required.", "invalidValue")
        other = await self.repo.group_by_name(name)
        if other is not None and (group is None or other.id != group.id):
            raise ScimError(409, f"A group named '{name[:80]}' already exists.", "uniqueness")

    async def create_group(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Idempotent create by externalId. Returns (resource, created). The role is never taken from the IdP."""
        name = _str(body.get("displayName", ""), "displayName")
        ext = _str(body["externalId"], "externalId") or None if body.get("externalId") else None
        members = await self._member_users(body.get("members"))
        existing = await self.repo.group_by_external_id(ext) if ext else None
        if existing is not None:
            await self._set_members(existing, members)
            return await self._render_group(existing), False
        await self._check_group_name(name, None)
        group = ScimGroup(display_name=name, external_id=ext)
        self.session.add(group)
        await self.session.flush()
        await self.repo.add_members(group.id, members)
        return await self._render_group(group), True

    async def _set_members(self, group: ScimGroup, wanted: list[uuid.UUID]) -> None:
        have = set(await self.repo.member_ids(group.id))
        await self._change_members(group, add=[u for u in wanted if u not in have], remove=list(have - set(wanted)))

    async def _change_members(self, group: ScimGroup, *, add: list[uuid.UUID], remove: list[uuid.UUID]) -> None:
        await self.repo.remove_members(group.id, remove)
        await self.repo.add_members(group.id, add)
        if group.role:
            for uid in dict.fromkeys([*add, *remove]):
                user = await self.repo.get_user(uid)
                if user is not None:
                    await self._sync_role(user)

    async def replace_group(self, group_id: str, body: dict[str, Any]) -> dict[str, Any]:
        group = await self._load_group(group_id)
        name = _str(body.get("displayName", ""), "displayName")
        await self._check_group_name(name, group)
        group.display_name = name
        if "externalId" in body:
            group.external_id = _str(body["externalId"], "externalId") or None
        await self.session.flush()
        await self._set_members(group, await self._member_users(body.get("members")))
        return await self._render_group(group)

    async def patch_group(self, group_id: str, body: dict[str, Any]) -> dict[str, Any]:
        group = await self._load_group(group_id)
        for op, path, value in _operations(body):
            for p, v in _flatten(op, path, value):
                await self._patch_group_attr(group, op, p, v)
        await self.session.flush()
        return await self._render_group(group)

    async def _patch_group_attr(self, group: ScimGroup, op: str, path: str, value: Any) -> None:
        key, filt = _norm_path(path)
        if key == "displayname" and op != "remove":
            name = _str(value, "displayName")
            await self._check_group_name(name, group)
            group.display_name = name
        elif key == "externalid":
            group.external_id = None if op == "remove" else (_str(value, "externalId") or None)
        elif key == "members":
            have = set(await self.repo.member_ids(group.id))
            if op != "remove":
                ids = await self._member_users(value)
                if op == "replace":
                    await self._set_members(group, ids)
                else:
                    await self._change_members(group, add=[i for i in ids if i not in have], remove=[])
                return
            if filt:
                m = _VALUE_EQ.search(filt)
                if not m:
                    raise ScimError(400, "Unsupported members filter.", "invalidFilter")
                ids = [_uuid(m.group(1), "member")]
            elif isinstance(value, list):
                ids = [_ref(x, "member") for x in value]
            else:
                ids = list(have)
            if any(i not in have for i in ids):
                raise ScimError(400, "The user is not a member of that group.", "noTarget")
            await self._change_members(group, add=[], remove=ids)
        else:
            raise ScimError(400, f"Unknown path '{path[:80]}'.", "invalidPath")

    async def delete_group(self, group_id: str) -> None:
        group = await self._load_group(group_id)
        members = await self.repo.member_ids(group.id)
        mapped = group.role is not None
        await self.repo.delete_group(group)
        if mapped:
            for uid in members:
                user = await self.repo.get_user(uid)
                if user is not None:
                    await self._sync_role(user)

    # ── Admin (UI) ─────────────────────────────────────────────────────

    async def set_group_role(self, group_id: uuid.UUID, role: str | None) -> ScimGroup:
        """An admin maps a group to a role (or clears it); members follow at once."""
        group = await self.repo.get_group(group_id)
        if group is None:
            raise ScimError(404, "Group not found.")
        if role is not None and role not in VALID_ROLES:
            raise ScimError(400, f"role must be one of {', '.join(VALID_ROLES)}.", "invalidValue")
        await self._validate(group_role=role, group=group.display_name)
        group.role = role
        await self.session.flush()
        await self._audit("scim.group.role", "scim_group", group.id, role=role, name=group.display_name)
        for user in await self.repo.members(group.id):
            await self._sync_role(user)
        return group
