# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the Customer & Partner Portal service layer.

Mirrors the stubbed-repository pattern used in ``test_safety.py``: the
SQLAlchemy session and each repository class are replaced with in-memory
stand-ins, so these tests run without a real DB connection. Token
generation/hashing helpers and the permission constants are also covered.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.portal.schemas import PORTAL_ROLES
from app.modules.portal.service import (
    MAGIC_LINK_TTL,
    SESSION_TTL,
    PortalService,
    constant_time_equals,
    generate_token,
    hash_token,
    now_utc,
)

# ── In-memory stubs ───────────────────────────────────────────────────────


class _StubSession:
    """Drop-in for AsyncSession that no-ops everything tests need."""

    async def refresh(self, obj: Any) -> None:
        return None

    def expire_all(self) -> None:
        return None


class _BaseStubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def _store(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not getattr(obj, "created_at", None):
            obj.created_at = now
        obj.updated_at = now
        self.rows[obj.id] = obj
        return obj


class _StubUserRepo(_BaseStubRepo):
    async def get_by_id(self, user_id: uuid.UUID) -> Any:
        return self.rows.get(user_id)

    async def get_by_email(self, email: str) -> Any:
        norm = email.strip().lower()
        for row in self.rows.values():
            if row.email == norm:
                return row
        return None

    async def create(self, user: Any) -> Any:
        user.email = user.email.strip().lower()
        return await self._store(user)

    async def list_users(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        portal_role: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if portal_role:
            rows = [r for r in rows if r.portal_role == portal_role]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, user_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(user_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)


class _StubRuleRepo(_BaseStubRepo):
    async def get_by_id(self, rule_id: uuid.UUID) -> Any:
        return self.rows.get(rule_id)

    async def get_one(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> Any:
        for row in self.rows.values():
            if (
                row.portal_user_id == portal_user_id
                and row.resource_type == resource_type
                and row.resource_id == resource_id
            ):
                return row
        return None

    async def list_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        resource_type: str | None = None,
    ) -> list[Any]:
        rows = [r for r in self.rows.values() if r.portal_user_id == portal_user_id]
        if resource_type:
            rows = [r for r in rows if r.resource_type == resource_type]
        return rows

    async def list_rules(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if portal_user_id is not None:
            rows = [r for r in rows if r.portal_user_id == portal_user_id]
        if resource_type is not None:
            rows = [r for r in rows if r.resource_type == resource_type]
        return rows[offset : offset + limit], len(rows)

    async def create(self, rule: Any) -> Any:
        return await self._store(rule)

    async def update_fields(self, rule_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(rule_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)

    async def delete(self, rule_id: uuid.UUID) -> None:
        self.rows.pop(rule_id, None)

    async def delete_match(
        self,
        portal_user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> None:
        existing = await self.get_one(portal_user_id, resource_type, resource_id)
        if existing is not None:
            self.rows.pop(existing.id, None)


class _StubSessionRepo(_BaseStubRepo):
    async def get_by_token_hash(self, token_hash: str) -> Any:
        for row in self.rows.values():
            if row.session_token_hash == token_hash:
                return row
        return None

    async def create(self, sess: Any) -> Any:
        return await self._store(sess)

    async def update_fields(self, session_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(session_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)

    async def revoke_all_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        revoked_at: datetime,
    ) -> int:
        n = 0
        for row in self.rows.values():
            if row.portal_user_id == portal_user_id and row.revoked_at is None:
                row.revoked_at = revoked_at
                n += 1
        return n


class _StubMagicRepo(_BaseStubRepo):
    async def create(self, link: Any) -> Any:
        return await self._store(link)

    async def get_by_token_hash(self, token_hash: str) -> Any:
        for row in self.rows.values():
            if row.token_hash == token_hash:
                return row
        return None

    async def update_fields(self, link_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(link_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)


class _StubNotifRepo(_BaseStubRepo):
    async def create(self, notif: Any) -> Any:
        return await self._store(notif)

    async def get_by_id(self, notif_id: uuid.UUID) -> Any:
        return self.rows.get(notif_id)

    async def list_for_user(
        self,
        portal_user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.portal_user_id == portal_user_id]
        if unread_only:
            rows = [r for r in rows if r.read_at is None]
        return rows[offset : offset + limit], len(rows)

    async def unread_count(self, portal_user_id: uuid.UUID) -> int:
        return sum(1 for r in self.rows.values() if r.portal_user_id == portal_user_id and r.read_at is None)

    async def update_fields(self, notif_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(notif_id)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)


class _StubAuditRepo(_BaseStubRepo):
    async def create(self, entry: Any) -> Any:
        return await self._store(entry)

    async def list_entries(
        self,
        *,
        portal_user_id: uuid.UUID | None = None,
        document_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if portal_user_id is not None:
            rows = [r for r in rows if r.portal_user_id == portal_user_id]
        if document_type is not None:
            rows = [r for r in rows if r.document_type == document_type]
        return rows[offset : offset + limit], len(rows)


def _make_service() -> PortalService:
    svc = PortalService.__new__(PortalService)
    svc.session = _StubSession()
    svc.user_repo = _StubUserRepo()
    svc.rule_repo = _StubRuleRepo()
    svc.session_repo = _StubSessionRepo()
    svc.magic_repo = _StubMagicRepo()
    svc.notif_repo = _StubNotifRepo()
    svc.audit_repo = _StubAuditRepo()
    return svc


def _patch_bus() -> Any:
    return patch(
        "app.modules.portal.service.event_bus.publish_detached",
        new=lambda *a, **k: None,
    )


# ── Pure helpers ──────────────────────────────────────────────────────────


def test_generate_token_is_hex_and_unique() -> None:
    t1 = generate_token()
    t2 = generate_token()
    assert len(t1) == 64
    assert all(c in "0123456789abcdef" for c in t1)
    assert t1 != t2


def test_hash_token_is_deterministic_and_sha256() -> None:
    plain = "abc123"
    digest = hash_token(plain)
    assert len(digest) == 64
    assert hash_token(plain) == digest
    assert hash_token("abc1234") != digest


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc") is True
    assert constant_time_equals("abc", "abd") is False
    assert constant_time_equals("a", "ab") is False


def test_portal_roles_schema_constant() -> None:
    import re

    pattern = re.compile(PORTAL_ROLES)
    for role in (
        "client",
        "investor",
        "consultant",
        "subcontractor",
        "supplier",
        "building_user",
    ):
        assert pattern.match(role), f"role {role} should match"
    assert not pattern.match("admin")
    assert not pattern.match("")


# ── Invite ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_creates_user_and_magic_link() -> None:
    svc = _make_service()
    with _patch_bus():
        user, plain, expires_at = await svc.invite_portal_user(
            email="alice@example.com",
            role="client",
            language="en",
            granted_by="admin-1",
        )
    assert user.id is not None
    assert user.email == "alice@example.com"
    assert user.portal_role == "client"
    assert user.status == "invited"
    assert len(plain) == 64
    assert expires_at > now_utc()
    # Magic link is stored as hash only.
    stored = list(svc.magic_repo.rows.values())[0]
    assert stored.token_hash == hash_token(plain)
    assert stored.token_hash != plain


@pytest.mark.asyncio
async def test_invite_idempotent_on_existing_email() -> None:
    svc = _make_service()
    with _patch_bus():
        u1, t1, _ = await svc.invite_portal_user(
            email="bob@example.com",
            role="investor",
        )
        u2, t2, _ = await svc.invite_portal_user(
            email="bob@example.com",
            role="investor",
        )
    assert u1.id == u2.id
    assert t1 != t2  # fresh magic link issued
    assert len(svc.magic_repo.rows) == 2


@pytest.mark.asyncio
async def test_invite_lowercases_email() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="MIXED@Example.COM",
            role="client",
        )
    assert user.email == "mixed@example.com"


# ── Magic link consumption ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_magic_link_success() -> None:
    svc = _make_service()
    with _patch_bus():
        user, plain, _ = await svc.invite_portal_user(
            email="carl@example.com",
            role="consultant",
        )
        user2, sess, session_plain, sess_expires = await svc.consume_magic_link(
            plain,
        )
    assert user2.id == user.id
    assert sess.portal_user_id == user.id
    assert len(session_plain) == 64
    assert sess_expires > now_utc()
    # User flips invited → active.
    assert user2.status == "active"
    # Magic link is now consumed.
    link = list(svc.magic_repo.rows.values())[0]
    assert link.consumed_at is not None


@pytest.mark.asyncio
async def test_consume_magic_link_expired() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="dora@example.com",
            role="client",
        )
    # Force expiry on the only link.
    link = list(svc.magic_repo.rows.values())[0]
    link.expires_at = now_utc() - timedelta(minutes=1)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.consume_magic_link(plain)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_consume_magic_link_already_consumed() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="erin@example.com",
            role="supplier",
        )
        await svc.consume_magic_link(plain)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await svc.consume_magic_link(plain)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_consume_magic_link_wrong_purpose() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="finn@example.com",
            role="subcontractor",
        )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.consume_magic_link(plain, purpose="document_signature")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_consume_magic_link_unknown_token() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.consume_magic_link("0" * 64)
    assert exc.value.status_code == 401


# ── Sessions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_session_valid_and_touches_last_seen() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="gina@example.com",
            role="client",
        )
        _, sess, session_plain, _ = await svc.consume_magic_link(plain)

    user = await svc.verify_session(session_plain)
    assert user is not None
    assert user.id == sess.portal_user_id
    refreshed = svc.session_repo.rows[sess.id]
    assert refreshed.last_seen_at is not None


@pytest.mark.asyncio
async def test_verify_session_revoked_returns_none() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="hank@example.com",
            role="client",
        )
        _, sess, session_plain, _ = await svc.consume_magic_link(plain)

    ok = await svc.revoke_session(session_plain)
    assert ok is True
    assert await svc.verify_session(session_plain) is None


@pytest.mark.asyncio
async def test_verify_session_expired_returns_none() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="iris@example.com",
            role="client",
        )
        _, sess, session_plain, _ = await svc.consume_magic_link(plain)
    # Force expiry on the only session.
    sess_row = list(svc.session_repo.rows.values())[0]
    sess_row.expires_at = now_utc() - timedelta(seconds=1)
    assert await svc.verify_session(session_plain) is None


@pytest.mark.asyncio
async def test_verify_session_empty_token() -> None:
    svc = _make_service()
    assert await svc.verify_session("") is None


@pytest.mark.asyncio
async def test_revoke_all_for_user() -> None:
    svc = _make_service()
    with _patch_bus():
        _, plain, _ = await svc.invite_portal_user(
            email="jane@example.com",
            role="client",
        )
        _, sess1, p1, _ = await svc.consume_magic_link(plain)
        _, plain2, _ = await svc.invite_portal_user(
            email="jane@example.com",
            role="client",
        )
        _, sess2, p2, _ = await svc.consume_magic_link(plain2)

    n = await svc.revoke_all_for_user(sess1.portal_user_id)
    assert n == 2
    assert await svc.verify_session(p1) is None
    assert await svc.verify_session(p2) is None


# ── Access rules / RLS ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_access_creates_rule() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="kim@example.com",
            role="client",
        )
    resource_id = uuid.uuid4()
    rule = await svc.grant_access(
        user.id,
        "project",
        resource_id,
        "view",
        granted_by="admin",
    )
    assert rule.portal_user_id == user.id
    assert rule.resource_id == resource_id
    assert rule.permission == "view"


@pytest.mark.asyncio
async def test_grant_access_idempotent_updates_permission() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="leo@example.com",
            role="client",
        )
    rid = uuid.uuid4()
    r1 = await svc.grant_access(user.id, "project", rid, "view")
    r2 = await svc.grant_access(user.id, "project", rid, "comment")
    assert r1.id == r2.id  # same row updated
    assert r2.permission == "comment"
    assert len(svc.rule_repo.rows) == 1


@pytest.mark.asyncio
async def test_revoke_access_removes_rule() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="mia@example.com",
            role="client",
        )
    rid = uuid.uuid4()
    await svc.grant_access(user.id, "project", rid, "view")
    await svc.revoke_access(user.id, "project", rid)
    assert len(svc.rule_repo.rows) == 0


@pytest.mark.asyncio
async def test_enforce_rls_true_when_rule_present() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="nick@example.com",
            role="client",
        )
    rid = uuid.uuid4()
    await svc.grant_access(user.id, "project", rid, "comment")

    assert await svc.enforce_rls(user.id, "project", rid, "view") is True
    assert await svc.enforce_rls(user.id, "project", rid, "comment") is True
    # higher-than-granted should be denied
    assert await svc.enforce_rls(user.id, "project", rid, "sign") is False


@pytest.mark.asyncio
async def test_enforce_rls_false_without_rule() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="oli@example.com",
            role="client",
        )
    assert await svc.enforce_rls(user.id, "project", uuid.uuid4(), "view") is False


@pytest.mark.asyncio
async def test_enforce_rls_expired_rule_denied() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="pat@example.com",
            role="client",
        )
    rid = uuid.uuid4()
    await svc.grant_access(
        user.id,
        "project",
        rid,
        "view",
        expires_at=now_utc() - timedelta(seconds=1),
    )
    assert await svc.enforce_rls(user.id, "project", rid, "view") is False


@pytest.mark.asyncio
async def test_list_access_rules_admin_lists_all_and_filters() -> None:
    """``list_access_rules`` must return rules across all users (durable
    admin list), and honour the ``portal_user_id`` / ``resource_type``
    filters. Regression for the Access-Rules tab being empty after reload.
    """
    svc = _make_service()
    with _patch_bus():
        ua, _, _ = await svc.invite_portal_user(
            email="aa@example.com",
            role="client",
        )
        ub, _, _ = await svc.invite_portal_user(
            email="bb@example.com",
            role="subcontractor",
        )
    pa, pb = uuid.uuid4(), uuid.uuid4()
    doc = uuid.uuid4()
    await svc.grant_access(ua.id, "project", pa, "view")
    await svc.grant_access(ub.id, "project", pb, "comment")
    await svc.grant_access(ub.id, "document", doc, "sign")

    all_rules, total = await svc.list_access_rules()
    assert total == 3
    assert len(all_rules) == 3

    only_b, total_b = await svc.list_access_rules(portal_user_id=ub.id)
    assert total_b == 2
    assert {r.portal_user_id for r in only_b} == {ub.id}

    only_docs, total_docs = await svc.list_access_rules(
        resource_type="document",
    )
    assert total_docs == 1
    assert only_docs[0].resource_id == doc


@pytest.mark.asyncio
async def test_list_access_rules_pagination() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="page@example.com",
            role="client",
        )
    for _ in range(5):
        await svc.grant_access(user.id, "project", uuid.uuid4(), "view")
    page1, total = await svc.list_access_rules(offset=0, limit=2)
    page2, _ = await svc.list_access_rules(offset=2, limit=2)
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


@pytest.mark.asyncio
async def test_enforce_rls_is_per_user_no_cross_tenant_read() -> None:
    """Security boundary: a grant to subcontractor A must NEVER let
    subcontractor B read A's resource by id.
    """
    svc = _make_service()
    with _patch_bus():
        sub_a, _, _ = await svc.invite_portal_user(
            email="sub-a@example.com",
            role="subcontractor",
        )
        sub_b, _, _ = await svc.invite_portal_user(
            email="sub-b@example.com",
            role="subcontractor",
        )
    package = uuid.uuid4()
    await svc.grant_access(sub_a.id, "subcontract", package, "submit")

    assert (
        await svc.enforce_rls(
            sub_a.id,
            "subcontract",
            package,
            "submit",
        )
        is True
    )
    # B has no rule on A's package — must be denied at every permission level.
    assert (
        await svc.enforce_rls(
            sub_b.id,
            "subcontract",
            package,
            "view",
        )
        is False
    )
    assert (
        await svc.enforce_rls(
            sub_b.id,
            "subcontract",
            package,
            "submit",
        )
        is False
    )
    # And B sees none of A's accessible resources.
    assert package not in await svc.list_accessible_resources(
        sub_b.id,
        "subcontract",
    )


@pytest.mark.asyncio
async def test_list_accessible_resources_filters_expired() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="quinn@example.com",
            role="client",
        )
    live = uuid.uuid4()
    dead = uuid.uuid4()
    other_type = uuid.uuid4()
    await svc.grant_access(user.id, "project", live, "view")
    await svc.grant_access(
        user.id,
        "project",
        dead,
        "view",
        expires_at=now_utc() - timedelta(seconds=1),
    )
    await svc.grant_access(user.id, "contract", other_type, "view")

    ids = await svc.list_accessible_resources(user.id, "project")
    assert live in ids
    assert dead not in ids
    assert other_type not in ids


# ── Notifications ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_creates_notification() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="rita@example.com",
            role="client",
        )
        notif = await svc.notify(
            user.id,
            kind="document_ready",
            title="Your invoice is ready",
            body="Please review",
        )
    assert notif.portal_user_id == user.id
    assert notif.kind == "document_ready"
    assert notif.read_at is None


@pytest.mark.asyncio
async def test_notify_emits_event() -> None:
    svc = _make_service()
    # ``event_bus.publish_detached`` is a SYNCHRONOUS method (it returns an
    # ``asyncio.Task`` from ``asyncio.create_task`` and is intentionally
    # called WITHOUT ``await`` in production code). The test double must
    # honour that contract — mocking it with ``AsyncMock`` would create a
    # coroutine that production code never awaits, raising a spurious
    # "coroutine was never awaited" RuntimeWarning instead of testing
    # anything real.
    publisher = MagicMock()
    with patch(
        "app.modules.portal.service.event_bus.publish_detached",
        new=publisher,
    ):
        user_repo = svc.user_repo
        # Bypass full invite to avoid extra event noise.
        from app.modules.portal.models import PortalUser

        u = PortalUser(
            email="sam@example.com",
            full_name="",
            portal_role="client",
        )
        await user_repo.create(u)
        await svc.notify(u.id, kind="general", title="hi")

    event_names = [c.args[0] for c in publisher.call_args_list]
    assert "portal.notification.created" in event_names


@pytest.mark.asyncio
async def test_mark_notification_read_owner_only() -> None:
    svc = _make_service()
    with _patch_bus():
        user_a, _, _ = await svc.invite_portal_user(
            email="tia@example.com",
            role="client",
        )
        user_b, _, _ = await svc.invite_portal_user(
            email="ula@example.com",
            role="client",
        )
        notif = await svc.notify(user_a.id, kind="general", title="hello")

    updated = await svc.mark_notification_read(notif.id, user_a.id)
    assert updated.read_at is not None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.mark_notification_read(notif.id, user_b.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_notifications_returns_unread_count() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="vic@example.com",
            role="client",
        )
        await svc.notify(user.id, kind="general", title="n1")
        n2 = await svc.notify(user.id, kind="general", title="n2")
        await svc.notify(user.id, kind="general", title="n3")
        await svc.mark_notification_read(n2.id, user.id)

    items, total, unread = await svc.list_notifications(user.id)
    assert total == 3
    assert unread == 2
    assert len(items) == 3


# ── Document access log ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_document_access_appends() -> None:
    svc = _make_service()
    with _patch_bus():
        user, _, _ = await svc.invite_portal_user(
            email="will@example.com",
            role="client",
        )
    doc_id = uuid.uuid4()
    await svc.record_document_access(
        user.id,
        "document",
        doc_id,
        "view",
        ip_address="1.2.3.4",
    )
    await svc.record_document_access(
        user.id,
        "document",
        doc_id,
        "download",
        ip_address="1.2.3.4",
    )
    items, total = await svc.list_document_access(portal_user_id=user.id)
    assert total == 2
    actions = {e.action for e in items}
    assert actions == {"view", "download"}


# ── Permission registry ───────────────────────────────────────────────────


def test_permission_constants_registered() -> None:
    from app.core.permissions import permission_registry
    from app.modules.portal.permissions import register_portal_permissions

    register_portal_permissions()
    all_perms = permission_registry.list_all()
    for perm in (
        "portal.admin.users.read",
        "portal.admin.users.invite",
        "portal.admin.users.suspend",
        "portal.admin.access_rules.manage",
        "portal.admin.audit.read",
    ):
        assert perm in all_perms


# ── Misc / sanity ─────────────────────────────────────────────────────────


def test_session_ttl_longer_than_magic_link_ttl() -> None:
    """Session should outlive the magic link used to mint it."""
    assert SESSION_TTL > MAGIC_LINK_TTL


@pytest.mark.asyncio
async def test_request_magic_link_returns_none_for_unknown_email() -> None:
    svc = _make_service()
    with _patch_bus():
        result = await svc.request_magic_link("ghost@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_request_magic_link_returns_token_for_known_email() -> None:
    svc = _make_service()
    with _patch_bus():
        await svc.invite_portal_user(
            email="active@example.com",
            role="client",
        )
        # mark active so request_magic_link returns the link
        u = await svc.user_repo.get_by_email("active@example.com")
        u.status = "active"
        result = await svc.request_magic_link("active@example.com")
    assert result is not None
    _user, plain, _expires = result
    assert len(plain) == 64
