"""PATCH /users/{id} must not strand the workspace without an active admin."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.users.service import UserService


class _Repo:
    def __init__(self, user, others):
        self.user = user
        self.others = others
        self.updated = []

    async def get_by_id(self, _id):
        return self.user

    async def count_active_admins(self, *, exclude_id=None):
        return self.others

    async def update_fields(self, _id, **fields):
        self.updated.append(fields)


def _svc(user, others):
    svc = UserService.__new__(UserService)
    svc.user_repo = _Repo(user, others)
    svc.session = None
    return svc


def _admin(**kw):
    base = {"id": uuid.uuid4(), "role": "admin", "is_active": True, "deleted_at": None, "email": "a@x.io"}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{"role": "viewer"}, {"is_active": False}])
async def test_last_admin_cannot_be_demoted_or_deactivated(fields):
    svc = _svc(_admin(), others=0)
    with pytest.raises(HTTPException) as e:
        await svc.update_profile(uuid.uuid4(), **fields)
    assert e.value.status_code == 409
    assert svc.user_repo.updated == []


@pytest.mark.asyncio
async def test_admin_can_be_demoted_when_another_admin_exists():
    svc = _svc(_admin(), others=1)
    await svc.update_profile(uuid.uuid4(), is_active=False)
    assert svc.user_repo.updated == [{"is_active": False}]


@pytest.mark.asyncio
async def test_erased_account_cannot_be_patched():
    svc = _svc(_admin(role="viewer", deleted_at="2026-01-01"), others=5)
    with pytest.raises(HTTPException) as e:
        await svc.update_profile(uuid.uuid4(), is_active=True)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_promote_self_or_touch_admins():
    from app.modules.users.router import update_user
    from app.modules.users.schemas import UserAdminUpdate

    svc = _svc(SimpleNamespace(id=uuid.uuid4(), role="manager"), others=3)

    async def _get_user(_id):
        return svc.user_repo.user

    svc.get_user = _get_user
    with pytest.raises(HTTPException) as e:
        await update_user(uuid.uuid4(), UserAdminUpdate(role="admin"), "v", {"role": "manager"}, svc)
    assert e.value.status_code == 403
    assert svc.user_repo.updated == []


def test_guard_admin_scope_blocks_non_admin_module_access_edit():
    from app.modules.users.router import _guard_admin_scope

    with pytest.raises(HTTPException) as exc:
        _guard_admin_scope({"role": "manager"}, "admin")
    assert exc.value.status_code == 403
    _guard_admin_scope({"role": "admin"}, "admin")
