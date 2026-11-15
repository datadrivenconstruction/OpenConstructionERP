"""SSO: provider admin with validation, SAML SP security checks, JIT provisioning and SCIM linking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from tests.modules.oe_sso.conftest import BASE, CERT, IDP, OTHER_CERT, OTHER_KEY, build_response

from app.modules.sso import saml
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

ACS = f"{BASE}/api/v1/sso/saml/corp/acs/"
SP = f"{BASE}/api/v1/sso/saml/corp/metadata/"


def _saml_body(**over):
    body = {
        "slug": "corp",
        "display_name": "Corp SAML",
        "protocol": "saml",
        "email_domains": ["corp.example"],
        "group_role_map": {"estimators": "editor", "leads": "manager"},
        "saml_idp_entity_id": IDP,
        "saml_idp_sso_url": "https://idp.corp.example/sso",
        "saml_idp_cert": CERT,
    }
    body.update(over)
    return body


async def _create(env, **over):
    r = await env.client.post("/api/v1/sso/providers/admin/", json=_saml_body(**over), headers=env.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _start(env) -> str:
    r = await env.client.get("/api/v1/sso/saml/corp/login/")
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "idp.corp.example"
    import base64
    import zlib

    req = zlib.decompress(base64.b64decode(parse_qs(loc.query)["SAMLRequest"][0]), -15).decode()
    return req.split('ID="')[1].split('"')[0]


async def _acs(env, response_b64: str):
    r = await env.client.post("/api/v1/sso/saml/corp/acs/", data={"SAMLResponse": response_b64})
    assert r.status_code == 303
    return r.headers["location"]


async def _login(env, **kw):
    rid = await _start(env)
    loc = await _acs(env, build_response(in_response_to=rid, acs_url=ACS, audience=SP, **kw))
    return rid, loc


async def _redeem(env, loc: str):
    code = loc.split("#code=")[1]
    return await env.client.post("/api/v1/sso/handoff/", json={"code": code})


# ── Admin + validation ────────────────────────────────────────────────


async def test_admin_crud_and_secret_never_returned(env, saml_required):
    oidc = {
        "slug": "entra",
        "display_name": "Entra",
        "protocol": "oidc",
        "oidc_issuer": "https://login.example/tenant/v2.0",
        "oidc_client_id": "abc",
        "oidc_client_secret": "s3cret",
    }
    r = await env.client.post("/api/v1/sso/providers/admin/", json=oidc, headers=env.headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_client_secret"] is True
    assert "s3cret" not in r.text
    p = await _create(env)
    assert p["acs_url"] == ACS and p["sp_entity_id"] == SP
    r = await env.client.patch(
        f"/api/v1/sso/providers/admin/{p['id']}", json={"display_name": "Corp"}, headers=env.headers
    )
    assert r.json()["display_name"] == "Corp"
    pub = (await env.client.get("/api/v1/sso/providers/?email=ann@corp.example")).json()
    assert {x["slug"] for x in pub["providers"]} == {"entra", "corp"}
    pub = (await env.client.get("/api/v1/sso/providers/?email=bob@other.example")).json()
    assert [x["slug"] for x in pub["providers"]] == ["entra"]
    r = await env.client.delete(f"/api/v1/sso/providers/admin/{p['id']}", headers=env.headers)
    assert r.status_code == 204


async def test_admin_list_is_an_envelope(env):
    await env.client.post("/api/v1/sso/providers/admin/", json=_saml_body(), headers=env.headers)
    r = await env.client.get("/api/v1/sso/providers/admin/", headers=env.headers)
    body = r.json()
    assert r.status_code == 200
    assert body["total"] == len(body["items"]) >= 1
    assert {"offset", "limit"} <= body.keys()


async def test_admin_requires_admin_role(env):
    assert (await env.client.get("/api/v1/sso/providers/admin/")).status_code in (401, 403)


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"slug": "Bad Slug"}, "sso.slug_format"),
        ({"saml_idp_sso_url": "http://idp.corp.example/sso"}, "sso.protocol_fields"),
        ({"saml_idp_cert": "not a cert"}, "sso.idp_certificate"),
        ({"clock_skew_seconds": 3600}, "sso.clock_skew"),
        ({"group_role_map": {"it": "admin"}}, "sso.role_mapping"),
        ({"group_role_map": {"it": "owner"}}, "sso.role_mapping"),
        ({"email_domains": ["not a domain"]}, "sso.email_domains"),
    ],
)
async def test_validation_rules_reject_bad_config(env, saml_required, over, rule):
    r = await env.client.post("/api/v1/sso/providers/admin/", json=_saml_body(**over), headers=env.headers)
    assert r.status_code == 422, r.text
    assert rule in {f["rule_id"] for f in r.json()["detail"]["findings"]}


async def test_expired_idp_certificate_rejected(env, saml_required):
    from tests.modules.oe_sso.conftest import make_keypair

    _, old = make_keypair(days=-1)
    r = await env.client.post("/api/v1/sso/providers/admin/", json=_saml_body(saml_idp_cert=old), headers=env.headers)
    assert r.status_code == 422
    assert "sso.idp_certificate" in r.text


async def test_saml_hidden_without_library(env, monkeypatch):
    monkeypatch.setattr(saml, "saml_available", lambda: False)
    monkeypatch.setattr("app.modules.sso.router.saml_available", lambda: False)
    monkeypatch.setattr("app.modules.sso.service.saml.saml_available", lambda: False)
    r = await env.client.post("/api/v1/sso/providers/admin/", json=_saml_body(), headers=env.headers)
    assert r.status_code == 422
    assert "sso.saml_available" in r.text
    assert (await env.client.get("/api/v1/sso/capabilities/")).json() == {"saml_available": False}


# ── SAML flow ─────────────────────────────────────────────────────────


async def test_metadata(env, saml_required):
    await _create(env)
    r = await env.client.get("/api/v1/sso/saml/corp/metadata/")
    assert r.status_code == 200
    assert f'entityID="{SP}"' in r.text and f'Location="{ACS}"' in r.text


async def test_signed_assertion_provisions_user_with_mapped_role(env, saml_required):
    await _create(env)
    _, loc = await _login(env, groups=("leads", "estimators"))
    assert "#code=" in loc, loc
    r = await _redeem(env, loc)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    async with env.factory() as s:
        from sqlalchemy import select

        u = (await s.execute(select(User).where(User.email == "ann@corp.example"))).scalar_one()
    assert u.role == "manager" and u.provisioned_by == "saml"
    assert (u.oidc_issuer, u.oidc_sub) == (IDP, "u-1001")
    # hand-off code is single use
    assert (await _redeem(env, loc)).status_code == 401


async def test_signed_response_accepted(env, saml_required):
    await _create(env)
    _, loc = await _login(env, sign="response")
    assert "#code=" in loc, loc


@pytest.mark.parametrize(
    ("kw", "error"),
    [
        ({"sign": "none"}, "unsigned"),
        ({"key": OTHER_KEY, "cert": OTHER_CERT}, "bad_signature"),
        ({"not_after": datetime.now(UTC) - timedelta(minutes=10)}, "expired"),
        ({"issuer": "https://evil.example"}, "wrong_issuer"),
    ],
)
async def test_bad_assertions_refused(env, saml_required, kw, error):
    await _create(env)
    _, loc = await _login(env, **kw)
    assert f"error={error}" in loc


async def test_wrong_audience_and_recipient_refused(env, saml_required):
    await _create(env)
    rid = await _start(env)
    loc = await _acs(env, build_response(in_response_to=rid, acs_url=ACS, audience="https://other-sp"))
    assert "error=wrong_audience" in loc
    rid = await _start(env)
    loc = await _acs(env, build_response(in_response_to=rid, acs_url="https://other/acs", audience=SP))
    assert "error=wrong_recipient" in loc


async def test_clock_skew_tolerates_slightly_expired(env, saml_required):
    await _create(env, clock_skew_seconds=300)
    _, loc = await _login(env, not_after=datetime.now(UTC) - timedelta(seconds=60))
    assert "#code=" in loc


async def test_replay_and_unsolicited_refused(env, saml_required):
    await _create(env)
    rid = await _start(env)
    resp = build_response(in_response_to=rid, acs_url=ACS, audience=SP)
    assert "#code=" in await _acs(env, resp)
    assert "error=unsolicited" in await _acs(env, resp)  # request id consumed
    rid2 = await _start(env)
    again = build_response(in_response_to=rid2, acs_url=ACS, audience=SP, assertion_id="_fixed")
    assert "#code=" in await _acs(env, again)
    rid3 = await _start(env)
    replay = build_response(in_response_to=rid3, acs_url=ACS, audience=SP, assertion_id="_fixed")
    assert "error=replayed" in await _acs(env, replay)
    forged = build_response(in_response_to="_never_sent", acs_url=ACS, audience=SP)
    assert "error=unsolicited" in await _acs(env, forged)


async def test_signature_wrapping_reads_only_signed_assertion(env, saml_required):
    """An unsigned evil assertion placed before the signed one must not be read."""
    import base64

    from lxml import etree

    await _create(env)
    rid = await _start(env)
    good = etree.fromstring(base64.b64decode(build_response(in_response_to=rid, acs_url=ACS, audience=SP)))
    evil = etree.fromstring(
        base64.b64decode(build_response(in_response_to=rid, acs_url=ACS, audience=SP, sign="none", name_id="admin"))
    )
    ns = {"saml": saml.NS["saml"]}
    good.insert(2, evil.find("saml:Assertion", ns))
    loc = await _acs(env, base64.b64encode(etree.tostring(good)).decode())
    # the signed element is the second assertion; the response holds two, so it is refused or reads the good one
    if "#code=" in loc:
        async with env.factory() as s:
            from sqlalchemy import select

            u = (await s.execute(select(User).where(User.oidc_sub == "admin"))).scalar_one_or_none()
        assert u is None


# ── JIT linking ───────────────────────────────────────────────────────


async def test_links_scim_user_and_keeps_scim_role(env, saml_required):
    uid = await env.add_user("ann@corp.example", role="editor", external_id="u-1001", provisioned_by="scim")
    await _create(env)
    _, loc = await _login(env, groups=("leads",))
    assert (await _redeem(env, loc)).status_code == 200
    u = await env.get(User, uid)
    assert u.oidc_sub == "u-1001" and u.role == "editor"


async def test_untrusted_email_does_not_link_an_existing_account(env, saml_required):
    uid = await env.add_user("ann@corp.example")
    await _create(env)
    _, loc = await _login(env)
    assert "error=account_link_refused" in loc
    assert (await env.get(User, uid)).oidc_sub is None


async def test_trusted_email_links_an_unbound_account(env, saml_required):
    uid = await env.add_user("ann@corp.example")
    await _create(env, link_by_email=True)
    _, loc = await _login(env)
    assert (await _redeem(env, loc)).status_code == 200
    u = await env.get(User, uid)
    assert (u.oidc_issuer, u.oidc_sub) == (IDP, "u-1001")


async def test_trusted_email_never_relinks_an_account_bound_elsewhere(env, saml_required):
    uid = await env.add_user("ann@corp.example", oidc_issuer="https://other-idp", oidc_sub="u-1001")
    await _create(env, link_by_email=True)
    _, loc = await _login(env)
    assert "error=account_link_refused" in loc
    assert (await env.get(User, uid)).oidc_issuer == "https://other-idp"


async def test_same_subject_from_another_issuer_is_a_different_person(env, saml_required):
    await env.add_user("first@corp.example", oidc_issuer="https://other-idp", oidc_sub="u-1001")
    await _create(env)
    _, loc = await _login(env)
    assert (await _redeem(env, loc)).status_code == 200
    async with env.factory() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(User).where(User.oidc_sub == "u-1001"))).scalars().all()
    assert sorted(u.email for u in rows) == ["ann@corp.example", "first@corp.example"]


async def test_legacy_null_issuer_row_matches_only_as_sole_provider(env, saml_required):
    uid = await env.add_user("legacy@corp.example", oidc_sub="u-1001")
    await _create(env)
    await _create(env, slug="corp2", display_name="Second", enabled=True)
    _, loc = await _login(env, email="ann@corp.example")
    assert "#code=" in loc  # two providers: the legacy row is not claimed, a new account is made
    assert (await env.get(User, uid)).oidc_issuer is None


async def test_legacy_null_issuer_row_is_backfilled(env, saml_required):
    uid = await env.add_user("legacy@corp.example", oidc_sub="u-1001")
    await _create(env)
    _, loc = await _login(env, email="legacy@corp.example")
    assert (await _redeem(env, loc)).status_code == 200
    assert (await env.get(User, uid)).oidc_issuer == IDP


# ── SAML request binding ──────────────────────────────────────────────


async def test_login_sets_signed_request_cookie(env, saml_required):
    await _create(env)
    r = await env.client.get("/api/v1/sso/saml/corp/login/")
    cookie = r.headers["set-cookie"]
    assert saml.REQUEST_COOKIE in cookie and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=none" in cookie.lower() and "Path=/api/v1/sso/saml/corp/acs/" in cookie


async def test_acs_without_request_cookie_is_refused(env, saml_required):
    await _create(env)
    rid = await _start(env)
    env.client.cookies.clear()
    loc = await _acs(env, build_response(in_response_to=rid, acs_url=ACS, audience=SP))
    assert "error=unsolicited" in loc


async def test_request_cookie_round_trip_and_forgery(env):
    token = saml.sign_request_id(env.settings, "corp", "_rid1")
    assert saml.verify_request_id(env.settings, "corp", token) == "_rid1"
    assert saml.verify_request_id(env.settings, "other", token) is None
    assert saml.verify_request_id(env.settings, "corp", token[:-2] + "xx") is None
    assert saml.verify_request_id(env.settings, "corp", None) is None


async def test_idp_initiated_only_when_enabled(env, saml_required):
    p = await _create(env)
    env.client.cookies.clear()
    loc = await _acs(env, build_response(in_response_to="", acs_url=ACS, audience=SP))
    assert "error=unsolicited" in loc
    r = await env.client.patch(
        f"/api/v1/sso/providers/admin/{p['id']}", json={"saml_allow_idp_initiated": True}, headers=env.headers
    )
    assert r.status_code == 200, r.text
    resp = build_response(in_response_to="", acs_url=ACS, audience=SP)
    assert "#code=" in await _acs(env, resp)
    assert "error=replayed" in await _acs(env, resp)


async def test_host_header_does_not_change_urls(env, saml_required):
    await _create(env)
    r = await env.client.get("/api/v1/sso/saml/corp/metadata/", headers={"Host": "evil.example"})
    assert "evil.example" not in r.text and f'Location="{ACS}"' in r.text


async def test_domain_not_served_and_deactivated_refused(env, saml_required):
    await _create(env, link_by_email=True)
    _, loc = await _login(env, email="eve@other.example")
    assert "error=domain_not_allowed" in loc
    await env.add_user("bob@corp.example", is_active=False)
    _, loc = await _login(env, email="bob@corp.example", name_id="u-2")
    assert "error=account_disabled" in loc


async def test_auto_create_off(env, saml_required):
    await _create(env, auto_create_users=False)
    _, loc = await _login(env)
    assert "error=account_not_found" in loc


async def test_admin_group_needs_switch(env, saml_required):
    p = await _create(env)
    r = await env.client.patch(
        f"/api/v1/sso/providers/admin/{p['id']}", json={"group_role_map": {"it": "admin"}}, headers=env.headers
    )
    assert r.status_code == 422
    r = await env.client.patch(
        f"/api/v1/sso/providers/admin/{p['id']}",
        json={"group_role_map": {"it": "admin"}, "allow_admin_mapping": True},
        headers=env.headers,
    )
    assert r.status_code == 200, r.text
    _, loc = await _login(env, groups=("it",))
    assert (await _redeem(env, loc)).status_code == 200


# ── Environment OIDC moves into a provider row ────────────────────────


async def test_env_oidc_becomes_one_provider_row_once(env):
    from sqlalchemy import select

    from app.core.crypto import decrypt_secret
    from app.modules.sso.models import SsoProvider
    from app.modules.sso.repairs import migrate_env_oidc

    env.settings.oidc_enabled = True
    env.settings.oidc_issuer_url = "https://login.corp.example/realms/main"
    env.settings.oidc_client_id = "oe"
    env.settings.oidc_client_secret = "s3cret"
    env.settings.oidc_group_role_map = '{"leads": "manager", "bad": "root"}'
    async with env.factory() as s:
        assert await migrate_env_oidc(s) == 1
        await s.commit()
    async with env.factory() as s:
        p = (await s.execute(select(SsoProvider))).scalar_one()
        assert (p.slug, p.protocol, p.oidc_client_id) == ("oidc", "oidc", "oe")
        assert p.oidc_client_secret_enc != "s3cret" and decrypt_secret(p.oidc_client_secret_enc) == "s3cret"
        assert p.group_role_map == {"leads": "manager"} and p.link_by_email
        await s.delete(p)
        await s.commit()
    async with env.factory() as s:
        assert await migrate_env_oidc(s) == 0  # deleted by an admin: never delivered again
        assert (await s.execute(select(SsoProvider))).first() is None


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://idp.example/realms/x", True),
        ("http://localhost:8080/realms/x", True),
        ("http://127.0.0.1/realms/x", True),
        ("http://[::1]:8080/realms/x", True),
        ("http://idp.example/realms/x", False),
        ("http://localhost.evil.example/x", False),
        ("http://localhost@evil.example/x", False),
        ("ftp://localhost/x", False),
        ("https://", False),
        (None, False),
    ],
)
def test_http_issuer_allowed_only_for_loopback(url, ok):
    from app.modules.sso.validators import _https

    assert _https(url) is ok
