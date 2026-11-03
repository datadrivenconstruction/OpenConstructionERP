"""SCIM 2.0 provisioning against a real PostgreSQL database.

Each test asks one question an IT admin cares about: does the IdP see a valid
SCIM server, do people appear once, does a role follow the group an admin mapped,
and does a leaver lose every way in.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.audit import AuditEntry
from app.modules.scim.models import ScimGroup
from app.modules.scim.service import ScimError, ScimService
from app.modules.users.models import APIKey, User, UserSession
from tests.modules.oe_scim.conftest import PASSWORD

ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
USER = "urn:ietf:params:scim:schemas:core:2.0:User"

pytestmark = pytest.mark.asyncio


def _user_body(email: str = "anna@corp.example", **kw):
    body = {"schemas": [USER], "userName": email, "externalId": f"ext-{email}", "active": True}
    body.update(kw)
    return body


async def _post_user(env, **kw):
    return await env.client.post("/scim/v2/Users", json=_user_body(**kw), headers=env.headers)


async def _patch(env, kind, rid, ops):
    return await env.client.patch(
        f"/scim/v2/{kind}/{rid}", json={"schemas": [PATCH], "Operations": ops}, headers=env.headers
    )


async def _group(env, name="Estimators", members=()):
    r = await env.client.post(
        "/scim/v2/Groups",
        json={"displayName": name, "externalId": f"g-{name}", "members": [{"value": str(m)} for m in members]},
        headers=env.headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _set_role(env, group_id, role):
    async with env.factory() as s:
        await ScimService(s, env.settings, env.admin_id, "").set_group_role(uuid.UUID(group_id), role)
        await s.commit()


# ── Discovery, envelopes, errors ────────────────────────────────────────


async def test_service_provider_config_shape(env):
    r = await env.client.get("/scim/v2/ServiceProviderConfig", headers=env.headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/scim+json")
    body = r.json()
    assert body["patch"]["supported"] is True
    for off in ("bulk", "sort", "etag", "changePassword"):
        assert body[off]["supported"] is False
    assert body["filter"] == {"supported": True, "maxResults": 100}


async def test_resource_types_and_schemas_are_list_responses(env):
    for path, expected in (("ResourceTypes", {"User", "Group"}), ("Schemas", None)):
        body = (await env.client.get(f"/scim/v2/{path}", headers=env.headers)).json()
        assert body["schemas"] == [LIST]
        assert body["totalResults"] == 2
        if expected:
            assert {r["name"] for r in body["Resources"]} == expected


async def test_list_response_has_paging_fields(env):
    for i in range(3):
        assert (await _post_user(env, email=f"p{i}@corp.example")).status_code == 201
    body = (await env.client.get("/scim/v2/Users?startIndex=2&count=2", headers=env.headers)).json()
    assert body["schemas"] == [LIST]
    assert body["totalResults"] == 4  # three people plus the token owner
    assert body["startIndex"] == 2
    assert body["itemsPerPage"] == len(body["Resources"]) == 2


async def test_errors_use_the_scim_error_schema(env):
    r = await env.client.get(f"/scim/v2/Users/{uuid.uuid4()}", headers=env.headers)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/scim+json")
    assert r.json()["schemas"] == [ERROR]
    assert r.json()["status"] == "404"
    bad = await env.client.post("/scim/v2/Users", content=b"{nope", headers=env.headers)
    assert bad.status_code == 400
    assert bad.json()["scimType"] == "invalidSyntax"


async def test_missing_or_wrong_scope_is_401_with_scim_error(env):
    other = await env.add_key(env.admin_id, ["projects.read"])
    unscoped = await env.add_key(env.admin_id, [])
    member = await env.add_user("viewer@corp.example", "viewer")
    viewer_key = await env.add_key(member, ["scim"])
    cases = [{}, {"Authorization": "Bearer nope"}]
    cases += [{"Authorization": f"Bearer {t}"} for t in (other, unscoped, viewer_key)]
    for headers in cases:
        r = await env.client.get("/scim/v2/Users", headers=headers)
        assert r.status_code == 401, headers
        assert r.json()["schemas"] == [ERROR]
        assert r.json()["status"] == "401"


async def test_x_api_key_header_is_accepted_too(env):
    r = await env.client.get("/scim/v2/Users", headers={"X-API-Key": env.token})
    assert r.status_code == 200


async def test_filters(env):
    await _post_user(env, email="a@corp.example")
    await _post_user(env, email="b@corp.example")
    one = (await env.client.get('/scim/v2/Users?filter=userName eq "B@corp.example"', headers=env.headers)).json()
    assert one["totalResults"] == 1 and one["Resources"][0]["userName"] == "b@corp.example"
    ext = (await env.client.get('/scim/v2/Users?filter=externalId eq "ext-a@corp.example"', headers=env.headers)).json()
    assert ext["totalResults"] == 1
    for bad in ('displayName eq "x"', 'userName co "x"', 'userName eq "x" and active eq "true"'):
        r = await env.client.get("/scim/v2/Users", params={"filter": bad}, headers=env.headers)
        assert r.status_code == 400
        assert r.json()["scimType"] == "invalidFilter"
    g = await env.client.get("/scim/v2/Groups", params={"filter": 'userName eq "x"'}, headers=env.headers)
    assert g.status_code == 400


# ── Create, adopt, idempotency ──────────────────────────────────────────


async def test_post_maps_attributes_and_is_idempotent_by_external_id(env):
    body = _user_body(
        "Anna.Site@Corp.Example",
        name={"givenName": "Anna", "familyName": "Site"},
        locale="de-DE",
        emails=[{"value": "anna.site@corp.example", "primary": True}],
    )
    first = await env.client.post("/scim/v2/Users", json=body, headers=env.headers)
    assert first.status_code == 201
    res = first.json()
    assert res["userName"] == "anna.site@corp.example"
    assert res["name"]["formatted"] == "Anna Site"
    assert res["locale"] == "de"
    assert res["meta"]["resourceType"] == "User" and res["meta"]["location"].endswith(f"/scim/v2/Users/{res['id']}")
    again = await env.client.post("/scim/v2/Users", json=body, headers=env.headers)
    assert again.status_code == 200 and again.json()["id"] == res["id"]
    row = await env.get(User, uuid.UUID(res["id"]))
    assert row.role == "viewer" and row.provisioned_by == "scim" and row.is_active
    assert row.hashed_password and "Passw0rd" not in row.hashed_password
    async with env.factory() as s:
        n = len((await s.execute(select(User).where(User.external_id == body["externalId"]))).scalars().all())
    assert n == 1


async def test_unsupported_locale_falls_back_to_en_and_default_role_is_never_admin(env):
    env.settings.oidc_default_role = "admin"
    res = (await _post_user(env, email="l@corp.example", locale="xx-YY")).json()
    row = await env.get(User, uuid.UUID(res["id"]))
    assert row.locale == "en" and row.role == "viewer"


async def test_post_adopts_an_existing_local_account(env):
    uid = await env.add_user("old@corp.example", "editor", provisioned_by="local")
    r = await _post_user(env, email="old@corp.example")
    assert r.status_code == 200 and r.json()["id"] == str(uid)
    row = await env.get(User, uid)
    assert row.external_id == "ext-old@corp.example"
    assert row.provisioned_by == "local"
    assert row.role == "editor"


async def test_same_email_with_a_different_external_id_is_409(env):
    await _post_user(env, email="dup@corp.example")
    r = await _post_user(env, email="dup@corp.example", externalId="someone-else")
    assert r.status_code == 409 and r.json()["scimType"] == "uniqueness"


async def test_invalid_user_name_is_rejected(env):
    r = await _post_user(env, email="not-an-email")
    assert r.status_code == 400 and r.json()["scimType"] == "invalidValue"


async def test_put_replaces_attributes_and_checks_email_uniqueness(env):
    a = (await _post_user(env, email="a@corp.example")).json()["id"]
    await _post_user(env, email="b@corp.example")
    ok = await env.client.put(
        f"/scim/v2/Users/{a}",
        json=_user_body("a@corp.example", name={"formatted": "Anna A"}, externalId="ext-a@corp.example"),
        headers=env.headers,
    )
    assert ok.status_code == 200 and ok.json()["name"]["formatted"] == "Anna A"
    clash = await env.client.put(f"/scim/v2/Users/{a}", json=_user_body("b@corp.example"), headers=env.headers)
    assert clash.status_code == 409


# ── PatchOp ─────────────────────────────────────────────────────────────


async def test_patch_replace_active_accepts_bool_and_entra_strings(env):
    uid = (await _post_user(env, email="c@corp.example")).json()["id"]
    off = await _patch(env, "Users", uid, [{"op": "Replace", "path": "active", "value": "False"}])
    assert off.status_code == 200 and off.json()["active"] is False
    on = await _patch(env, "Users", uid, [{"op": "replace", "path": "active", "value": True}])
    assert on.json()["active"] is True


async def test_patch_without_path_takes_a_value_object(env):
    uid = (await _post_user(env, email="d@corp.example", name={"formatted": "Dan Old"})).json()["id"]
    r = await _patch(
        env,
        "Users",
        uid,
        [{"op": "Replace", "value": {"name.givenName": "Daniel", "externalId": "new-ext", "active": False}}],
    )
    body = r.json()
    assert body["name"]["formatted"] == "Daniel Old"
    assert body["externalId"] == "new-ext" and body["active"] is False
    nested = await _patch(env, "Users", uid, [{"op": "replace", "value": {"name": {"familyName": "New"}}}])
    assert nested.json()["name"]["formatted"] == "Daniel New"


async def test_patch_email_add_replace_remove_and_unknown_path(env):
    uid = (await _post_user(env, email="e@corp.example")).json()["id"]
    moved = await _patch(
        env, "Users", uid, [{"op": "replace", "path": 'emails[type eq "work"].value', "value": "e2@corp.example"}]
    )
    assert moved.json()["userName"] == "e2@corp.example"
    primary = await _patch(env, "Users", uid, [{"op": "remove", "path": "emails"}])
    assert primary.status_code == 400 and primary.json()["scimType"] == "mutability"
    other = await _patch(env, "Users", uid, [{"op": "remove", "path": 'emails[value eq "x@y.example"]'}])
    assert other.status_code == 400 and other.json()["scimType"] == "noTarget"
    bad = await _patch(env, "Users", uid, [{"op": "replace", "path": "favouriteColour", "value": "red"}])
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidPath"
    empty = await _patch(env, "Users", uid, [])
    assert empty.status_code == 400 and empty.json()["scimType"] == "invalidSyntax"


async def test_group_membership_through_group_and_user_patch(env):
    uid = (await _post_user(env, email="m@corp.example")).json()["id"]
    gid = await _group(env, "Site team")
    added = await _patch(env, "Groups", gid, [{"op": "add", "path": "members", "value": [{"value": uid}]}])
    assert [m["value"] for m in added.json()["members"]] == [uid]
    assert (await env.client.get(f"/scim/v2/Users/{uid}", headers=env.headers)).json()["groups"][0]["value"] == gid
    gone = await _patch(env, "Groups", gid, [{"op": "remove", "path": f'members[value eq "{uid}"]'}])
    assert gone.json()["members"] == []
    again = await _patch(env, "Groups", gid, [{"op": "remove", "path": f'members[value eq "{uid}"]'}])
    assert again.status_code == 400 and again.json()["scimType"] == "noTarget"
    via_user = await _patch(env, "Users", uid, [{"op": "add", "path": "groups", "value": [{"value": gid}]}])
    assert via_user.json()["groups"][0]["display"] == "Site team"
    renamed = await _patch(env, "Groups", gid, [{"op": "replace", "path": "displayName", "value": "Site crew"}])
    assert renamed.json()["displayName"] == "Site crew"


async def test_duplicate_group_name_is_409_and_group_post_is_idempotent(env):
    gid = await _group(env, "Dup")
    same = await env.client.post(
        "/scim/v2/Groups", json={"displayName": "Dup", "externalId": "g-Dup"}, headers=env.headers
    )
    assert same.status_code == 200 and same.json()["id"] == gid
    clash = await env.client.post(
        "/scim/v2/Groups", json={"displayName": "dup", "externalId": "other"}, headers=env.headers
    )
    assert clash.status_code == 409 and clash.json()["scimType"] == "uniqueness"


# ── Roles from groups ───────────────────────────────────────────────────


async def test_role_follows_the_mapped_group_and_falls_back(env):
    uid = (await _post_user(env, email="r@corp.example")).json()["id"]
    editors = await _group(env, "Editors", [uuid.UUID(uid)])
    managers = await _group(env, "Managers", [uuid.UUID(uid)])
    await _set_role(env, editors, "editor")
    assert (await env.get(User, uuid.UUID(uid))).role == "editor"
    await _set_role(env, managers, "manager")
    assert (await env.get(User, uuid.UUID(uid))).role == "manager"
    await _patch(env, "Groups", managers, [{"op": "remove", "path": f'members[value eq "{uid}"]'}])
    assert (await env.get(User, uuid.UUID(uid))).role == "editor"
    await _patch(env, "Groups", editors, [{"op": "remove", "path": "members", "value": [{"value": uid}]}])
    assert (await env.get(User, uuid.UUID(uid))).role == "viewer"


async def test_cosmetic_group_does_not_touch_the_role(env):
    uid = await env.add_user("keep@corp.example", "manager")
    await _group(env, "Cosmetic", [uid])
    assert (await env.get(User, uid)).role == "manager"


async def test_idp_cannot_send_a_role(env):
    body = _user_body("sneaky@corp.example", role="admin", roles=[{"value": "admin"}])
    res = (await env.client.post("/scim/v2/Users", json=body, headers=env.headers)).json()
    assert (await env.get(User, uuid.UUID(res["id"]))).role == "viewer"
    g = await env.client.post("/scim/v2/Groups", json={"displayName": "Boss", "role": "admin"}, headers=env.headers)
    async with env.factory() as s:
        group = (await s.execute(select(ScimGroup).where(ScimGroup.id == uuid.UUID(g.json()["id"])))).scalar_one()
    assert group.role is None


async def test_admin_group_needs_the_explicit_setting(env):
    uid = (await _post_user(env, email="boss@corp.example")).json()["id"]
    gid = await _group(env, "Admins", [uuid.UUID(uid)])
    with pytest.raises(ScimError) as exc:
        await _set_role(env, gid, "admin")
    assert exc.value.status == 400 and "scim_allow_admin_groups" in exc.value.detail
    env.settings.scim_allow_admin_groups = True
    await _set_role(env, gid, "admin")
    assert (await env.get(User, uuid.UUID(uid))).role == "admin"
    env.settings.scim_allow_admin_groups = False
    # With the switch off again the admin mapping is ignored on the next recompute.
    await _patch(env, "Groups", gid, [{"op": "remove", "path": f'members[value eq "{uid}"]'}])
    assert (await env.get(User, uuid.UUID(uid))).role == "viewer"


async def test_unknown_role_is_refused(env):
    gid = await _group(env, "Odd")
    with pytest.raises(ScimError):
        await _set_role(env, gid, "superuser")


# ── Leavers ─────────────────────────────────────────────────────────────


async def _leaver(env, email="leaver@corp.example"):
    uid = uuid.UUID((await _post_user(env, email=email)).json()["id"])
    key = await env.add_key(uid, ["projects.read"])
    async with env.factory() as s:
        s.add(UserSession(sid=uuid.uuid4().hex, user_id=uid, expires_at=datetime(2099, 1, 1, tzinfo=UTC)))
        await s.commit()
    return uid, key


async def test_delete_is_a_soft_deactivation_that_ends_every_way_in(env):
    uid, _ = await _leaver(env)
    r = await env.client.delete(f"/scim/v2/Users/{uid}", headers=env.headers)
    assert r.status_code == 204 and r.content == b""
    row = await env.get(User, uid)
    assert row.is_active is False and row.deleted_at is None
    async with env.factory() as s:
        sessions = (await s.execute(select(UserSession).where(UserSession.user_id == uid))).scalars().all()
        keys = (await s.execute(select(APIKey).where(APIKey.user_id == uid))).scalars().all()
        audit = (await s.execute(select(AuditEntry).where(AuditEntry.action == "scim.user.deactivate"))).scalars().all()
    assert sessions and all(x.revoked_at is not None for x in sessions)
    assert keys and all(not k.is_active for k in keys)
    assert [(a.entity_id, a.user_id) for a in audit] == [(str(uid), env.admin_id)]
    # Idempotent, and the account is still readable as inactive.
    assert (await env.client.delete(f"/scim/v2/Users/{uid}", headers=env.headers)).status_code == 204
    assert (await env.client.get(f"/scim/v2/Users/{uid}", headers=env.headers)).json()["active"] is False


async def test_active_false_does_the_same_and_reactivation_keeps_keys_off(env):
    uid, _ = await _leaver(env, "back@corp.example")
    await _patch(env, "Users", str(uid), [{"op": "replace", "path": "active", "value": False}])
    async with env.factory() as s:
        assert all(
            x.revoked_at for x in (await s.execute(select(UserSession).where(UserSession.user_id == uid))).scalars()
        )
    await _patch(env, "Users", str(uid), [{"op": "replace", "path": "active", "value": True}])
    assert (await env.get(User, uid)).is_active is True
    async with env.factory() as s:
        keys = (await s.execute(select(APIKey).where(APIKey.user_id == uid))).scalars().all()
    assert keys and all(not k.is_active for k in keys)


async def test_last_admin_cannot_be_deactivated_or_demoted(env):
    r = await env.client.delete(f"/scim/v2/Users/{env.admin_id}", headers=env.headers)
    assert r.status_code == 400 and "last active admin" in r.json()["detail"]
    assert (await env.get(User, env.admin_id)).is_active is True
    gid = await _group(env, "Everyone", [env.admin_id])
    with pytest.raises(ScimError):
        await _set_role(env, gid, "viewer")
    assert (await env.get(User, env.admin_id)).role == "admin"
    second = await env.add_user("second@corp.example", "admin")
    ok = await env.client.delete(f"/scim/v2/Users/{second}", headers=env.headers)
    assert ok.status_code == 204


async def test_scim_token_dies_with_its_owner(env):
    second = await env.add_user("second@corp.example", "admin")
    await env.client.delete(f"/scim/v2/Users/{env.admin_id}", headers=env.headers)
    assert (await env.client.get("/scim/v2/Users", headers=env.headers)).status_code == 401
    assert (await env.get(User, second)).is_active


async def test_group_delete_returns_members_to_the_default_role(env):
    uid = (await _post_user(env, email="g@corp.example")).json()["id"]
    gid = await _group(env, "Temp", [uuid.UUID(uid)])
    await _set_role(env, gid, "manager")
    assert (await env.client.delete(f"/scim/v2/Groups/{gid}", headers=env.headers)).status_code == 204
    assert (await env.get(User, uuid.UUID(uid))).role == "viewer"
    assert (await env.client.get(f"/scim/v2/Groups/{gid}", headers=env.headers)).status_code == 404


# ── Enforced SSO domains ────────────────────────────────────────────────


async def _login(env, email, password=PASSWORD):
    return await env.client.post("/api/v1/users/auth/login/", json={"email": email, "password": password})


async def test_sso_enforced_domain_blocks_password_login_but_not_break_glass(env):
    env.settings.sso_enforced_domains = "corp.example, @Other.example"
    await env.add_user("staff@corp.example", "editor")
    await env.add_user("glass@corp.example", "admin", metadata_={"break_glass": True})
    await env.add_user("fake@corp.example", "editor", metadata_={"break_glass": True})
    await env.add_user("free@elsewhere.example", "editor")

    blocked = await _login(env, "staff@corp.example")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "auth.sso_required"
    assert (await _login(env, "fake@corp.example")).status_code == 403  # flag without admin role
    assert (await _login(env, "ghost@other.example")).status_code == 403
    assert (await _login(env, "glass@corp.example")).status_code == 200
    assert (await _login(env, "free@elsewhere.example")).status_code == 200

    forgot = await env.client.post("/api/v1/users/auth/forgot-password/", json={"email": "staff@corp.example"})
    assert forgot.status_code == 403 and forgot.json()["detail"]["code"] == "auth.sso_required"
    reg = await env.client.post(
        "/api/v1/users/auth/register/",
        json={"email": "new@corp.example", "password": "Abcdef12", "full_name": "New Person"},
    )
    assert reg.status_code == 403 and reg.json()["detail"]["code"] == "auth.sso_required"


async def test_sso_warning_only_when_oidc_is_off(env, caplog):
    from app.modules.users.sso_enforce import warn_if_misconfigured

    env.settings.sso_enforced_domains = "corp.example"
    env.settings.oidc_enabled = False
    with caplog.at_level("WARNING"):
        warn_if_misconfigured(env.settings)
    assert "SSO_ENFORCED_DOMAINS" in caplog.text
    caplog.clear()
    env.settings.oidc_enabled = True
    warn_if_misconfigured(env.settings)
    assert caplog.text == ""
