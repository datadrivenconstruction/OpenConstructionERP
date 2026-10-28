# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Ending one session must not end the others, and every session must be endable.

Before this, an issued token could not be revoked at all. Every token carried a
``jti`` that nothing ever read, so a credential had a name and no record behind
it: there was nowhere to write down that one session should stop being
honoured. Revoking a single session was not merely unimplemented, it was
inexpressible, and the only lever was rotating the signing secret, which ends
every session of every user at once. A ``sid`` claim and a row it points at are
what make the question answerable.

Two tests, because there are two ways to get this wrong and only one of them
looks like a bug.

The first is the obvious one: revocation has to actually refuse the revoked
credential, and has to leave every other credential alone. A check that refuses
too much passes a test that only asserts the refusal, so the other two tokens
in that test are not decoration - they are what separates "revocation works"
from "authentication is broken".

The second is the one that would ship silently. Revocation can only reach a
session that has a row, so an endpoint that hands out a token pair without
recording one produces a session nobody can ever end. Nothing about such a
token looks wrong: it authenticates perfectly, forever. The formula of the
first test cannot see this, because it exercises the login path alone and
would stay green with every other issuing endpoint leaking unrevocable
sessions. So the second test asserts over the population instead: no endpoint
mints a pair outside the one helper that opens a session.

That distinction was not hypothetical here. The first count of the issuing
sites in this service was three, taken from reading rather than measuring, and
it was wrong by two: ``demo_login`` and ``change_password`` also hand back
pairs. Both would have passed the first test and shipped sessions that could
never be signed out.

Every assertion carries a positive control, for the reason spelled out in
``test_password_change_kills_every_entry_point.py``: a revoked session and a
broken build both present as a refusal, so each credential is first shown to
WORK before it is shown to stop working.
"""

from __future__ import annotations

import ast
import logging
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PASSWORD = "SessionPassw0rd!"

# The two functions that turn a user into a JWT. Any call to either is a mint
# site, and a mint site outside the session-opening helper is an unrevocable
# session waiting to happen.
_MINTERS = {"create_access_token", "create_refresh_token"}

# The single helper allowed to call them. It opens (or rotates) the session row
# and mints the pair together, so the two cannot come apart.
_ISSUER = "_issue_token_pair"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """One app, one lifespan, driven synchronously.

    Module-scoped and sync for the same reason as the watermark test next to
    it: ``TestClient`` runs the app on its own portal thread, so building a
    second app inside an async test would cross event loops and re-run module
    discovery in the same process.
    """
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _register_and_login(client: TestClient) -> dict[str, str]:
    """Register a fresh user and return its e-mail and first token pair.

    ``conftest`` pins ``REGISTRATION_MODE=open``, so the account lands active
    and can log in without an admin promotion. The domain is ``example.com``
    and not ``.test``: ``.test`` is a reserved TLD our own e-mail validation
    refuses, so registration answers 422 and every later assertion dies on the
    control rather than on what it meant to measure.
    """
    email = f"sessions-{uuid.uuid4().hex[:8]}@revocation.example.com"
    client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Session Tester"},
    )
    return {"email": email, **_login(client, email)}


def _login(client: TestClient, email: str) -> dict[str, str]:
    """Log in again, opening a SECOND session for an account that already has one."""
    resp = client.post("/api/v1/users/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed for {email}: {resp.text}"
    body = resp.json()
    return {"access": body["access_token"], "refresh": body["refresh_token"]}


def _whoami(client: TestClient, access_token: str):
    """Any authenticated call. ``/users/me`` goes through the HTTP bearer door."""
    return client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})


def _sessions(client: TestClient, access_token: str) -> list[dict]:
    """The rows out of the page envelope the route answers with.

    The total is asserted against the rows rather than ignored, because the
    one thing this envelope exists to make sayable is "there are more of these
    than you were handed", and a helper that dropped it would hide exactly
    that.
    """
    resp = client.get("/api/v1/users/me/sessions", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200, f"listing sessions failed: {resp.text}"
    body = resp.json()
    assert body["total"] == len(body["items"]), (
        f"the page reports {body['total']} sessions and carries {len(body['items'])}; "
        "every assertion below counts rows and would read a truncated page as a shorter list"
    )
    return body["items"]


def test_revoking_one_session_leaves_the_others_alive(client: TestClient) -> None:
    """One session ends; the user's other session and another user's both survive.

    The two survivors are the substance of the test rather than padding around
    it. A revocation check that refused every token would satisfy an assertion
    that only says "the revoked token is now 401", and it would be a total
    outage. The second session of the SAME user is the sharper of the two,
    because a check keyed on the user instead of the session - which is what
    the password watermark does, and what this exists to improve on - passes
    the other-user assertion and fails only this one.
    """
    alice_first = _register_and_login(client)
    alice_second = _login(client, alice_first["email"])
    bob = _register_and_login(client)

    # Positive controls: all three doors are open BEFORE anything is revoked.
    # Without these, the assertions below pass against a build where
    # authentication is broken for everybody.
    assert _whoami(client, alice_first["access"]).status_code == 200, "alice's first session should start working"
    assert _whoami(client, alice_second["access"]).status_code == 200, "alice's second session should start working"
    assert _whoami(client, bob["access"]).status_code == 200, "bob's session should start working"

    listed = _sessions(client, alice_second["access"])
    assert len(listed) >= 2, f"alice logged in twice and should see at least two sessions, saw {len(listed)}"

    # Revoke the session the FIRST token belongs to, named from the listing
    # rather than by decoding a token here, so the route a person would really
    # use is the one under test.
    doomed = _pick_session_not_used_by(client, listed, alice_second["access"])
    resp = client.delete(
        f"/api/v1/users/me/sessions/{doomed}",
        headers={"Authorization": f"Bearer {alice_second['access']}"},
    )
    assert resp.status_code == 204, f"revoking alice's own session should succeed: {resp.text}"

    assert _whoami(client, alice_first["access"]).status_code == 401, "the revoked session must stop working"
    assert _whoami(client, alice_second["access"]).status_code == 200, (
        "alice's OTHER session must survive - revocation that ends every session of the user "
        "is the password watermark, not per-session revocation"
    )
    assert _whoami(client, bob["access"]).status_code == 200, "another user's session must be untouched"

    # The refresh token of the revoked session must not mint its way back in.
    # Without this the revocation lasts one hour: refresh would hand out a
    # fresh access token whose own claims look perfectly current.
    replay = client.post(
        "/api/v1/users/auth/refresh",
        json={"refresh_token": alice_first["refresh"]},
    )
    assert replay.status_code == 401, "a revoked session must not be able to refresh itself back to life"


def _pick_session_not_used_by(client: TestClient, listed: list[dict], access_token: str) -> str:
    """Return a sid from the listing that is NOT the one making the request.

    Revoking the caller's own session is allowed, so picking blindly would
    sometimes sign out the token used for the surviving-session assertion and
    turn this test into a coin flip. Identified by elimination: revoke one,
    keep the one the caller is holding.
    """
    survivor = _current_sid(client, access_token)
    for row in listed:
        if row["sid"] != survivor:
            return str(row["sid"])
    raise AssertionError(f"every listed session was the caller's own ({survivor}), so none can be revoked safely")


def _current_sid(client: TestClient, access_token: str) -> str:
    """The sid of the session the given token belongs to.

    Read from the token rather than guessed. Reading claims without verifying
    is deliberate: this is test-side inspection of a token the app just
    issued, not an authentication decision.
    """
    sid = _unverified(access_token).get("sid")
    assert sid, "an access token issued by login must carry a sid, otherwise its session can never be revoked"
    return str(sid)


def test_a_token_minted_before_sessions_existed_still_works(client: TestClient) -> None:
    """Nobody is signed out by the deploy that introduced sessions.

    Every credential issued before the ``sid`` claim existed carries none, and
    there is no record anywhere to backfill one from. Refusing them would have
    logged out every live user at the moment this shipped, so a token without
    a ``sid`` is honoured and simply cannot be revoked individually until its
    next refresh opens a session for it.

    That is a deliberate decision rather than an oversight, which is exactly
    why it needs a test: it is indistinguishable, in the code, from having
    forgotten to handle the case. Someone tightening ``reject_revoked_session``
    later would break every live session on the next deploy and no other test
    here would notice, because every token the rest of this file mints has a
    ``sid``.

    The token is minted through the real ``create_access_token`` with no
    ``sid`` argument, which is precisely how the code produced tokens before
    this change, rather than by editing claims of an existing one.
    """
    from types import SimpleNamespace

    from app.config import get_settings
    from app.modules.users.service import create_access_token

    account = _register_and_login(client)
    claims = _unverified(account["access"])

    # ``id`` is a real UUID, not the string form of one, because that is what
    # ``User.id`` holds. Handing over ``claims["sub"]`` also works today, but
    # only because the minter happens to call ``str()`` on it, so the test
    # would break confusingly the moment that line stopped being a no-op.
    legacy = create_access_token(
        SimpleNamespace(id=uuid.UUID(claims["sub"]), email=claims["email"], role=claims["role"]),
        get_settings(),
    )
    assert "sid" not in _unverified(legacy), "the point of this token is that it has no sid; it was built wrong"

    # Control first: the door is open for the ordinary token, so a refusal
    # below would mean the sid-less token specifically, not a broken build.
    assert _whoami(client, account["access"]).status_code == 200, "the ordinary session should work"
    assert _whoami(client, legacy).status_code == 200, (
        "a token issued before sessions existed must keep working; refusing it signs out "
        "every live user on the deploy that introduces revocation"
    )


def test_a_session_that_is_not_on_file_is_honoured_and_says_so(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The fail-open path passes the caller through and leaves a trace.

    A token can name a session that has no row: restoring the database from a
    backup taken before the session began produces exactly that. Refusing there
    would sign out the whole platform at the worst possible moment, so the
    token is honoured, and the reasoning sits beside the check.

    The trace is the half that is easy to leave out, and without it the branch
    is unfalsifiable. Reading ``revoked_at`` alone cannot even reach this test:
    that column is NULL both for a live session and for a row that is not
    there, so the two cases collapse into one and the deliberate exception
    becomes indistinguishable in the code from the ordinary success. Nothing
    would be wrong at runtime and nothing would be measurable either, which is
    how a restore, a pruning predicate that reaches unexpired rows, and a
    login-time flush that stopped refusing failed inserts would all look the
    same: silence.

    So this asserts both halves. The request must succeed, and the log must
    name the orphaned session, because the frequency of this line is the only
    thing that separates those three causes.
    """
    from types import SimpleNamespace

    account = _register_and_login(client)
    orphan_sid = "sid-that-no-row-was-ever-written-for"
    claims = _unverified(account["access"])

    from app.config import get_settings
    from app.modules.users.service import create_access_token

    orphaned = create_access_token(
        SimpleNamespace(id=uuid.UUID(claims["sub"]), email=claims["email"], role=claims["role"]),
        get_settings(),
        sid=orphan_sid,
    )
    assert _unverified(orphaned).get("sid") == orphan_sid, "the token was built without the sid under test"

    # Control: the ordinary session works, so a refusal below would be about
    # the orphaned sid and not about a broken build.
    assert _whoami(client, account["access"]).status_code == 200, "the ordinary session should work"

    with caplog.at_level(logging.WARNING):
        assert _whoami(client, orphaned).status_code == 200, (
            "a token naming a session with no row must be honoured; failing closed here signs out "
            "every user at the moment the database is restored from a backup"
        )

    assert any(orphan_sid in record.getMessage() for record in caplog.records), (
        "the fail-open path left no trace naming the session, so a restore, a pruning bug and a "
        "failed insert at login are indistinguishable from one another and from silence"
    )

    # The same session must not report itself again. What the log is read for is
    # the count of DISTINCT sessions, so a repeat adds nothing to it and costs a
    # line on every request that token makes. One of the three causes never
    # decays, which is what makes the unbounded version able to fill a disk.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert _whoami(client, orphaned).status_code == 200, (
            "the second request with the same orphaned session must still be honoured; "
            "quieting the log must not change who gets in"
        )
    assert not [record for record in caplog.records if orphan_sid in record.getMessage()], (
        "the same missing session was reported twice, so a token whose session never comes back "
        "writes a line on every request it ever makes"
    )


def _unverified(token: str) -> dict:
    """Claims of a token this test process just minted, read without verifying."""
    from jose import jwt

    return jwt.get_unverified_claims(token)


def test_every_token_pair_is_minted_inside_the_session_helper() -> None:
    """No endpoint hands out a pair without opening a session to go with it.

    The population check the revocation test above cannot perform. It exercises
    login, and would stay green if ``demo_login``, ``desktop_bootstrap``,
    ``change_password`` or a sixth endpoint added next year minted pairs
    directly - each one a session with no row, which authenticates forever and
    can never be signed out.

    Asserted over the source rather than over live endpoints on purpose. Some
    issuing endpoints need conditions a test process does not have (a seeded
    demo account, desktop mode), so a runtime sweep would quietly skip exactly
    the sites most likely to be forgotten. Parsed with ``ast`` rather than
    grepped because the minters are named in prose in several docstrings, and a
    textual match cannot tell an explanation from a call.
    """
    app_root = Path(__file__).resolve().parents[2] / "app"
    assert app_root.is_dir(), f"expected the application package at {app_root}"

    offenders: list[str] = []
    call_sites = 0

    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else None
                if name not in _MINTERS:
                    continue
                call_sites += 1
                if func.name != _ISSUER:
                    offenders.append(f"{path.relative_to(app_root.parent)}:{node.lineno} in {func.name}()")

    # Control. Every assertion below is satisfied by finding nothing at all, so
    # a renamed minter, a moved package or a broken walk would report perfect
    # compliance instead of failing. The count is the denominator that makes
    # the verdict mean something.
    assert call_sites > 0, (
        f"found no calls to {sorted(_MINTERS)} anywhere under {app_root}; the check inspected the wrong "
        "population or the functions were renamed, and its silence is not evidence of compliance"
    )

    assert not offenders, (
        "every access/refresh pair must be minted inside "
        f"{_ISSUER}(), which opens the session row that makes the pair revocable. "
        "A pair minted anywhere else is a session with no record, which authenticates "
        "normally and can never be signed out. Found "
        f"{len(offenders)} of {call_sites} call sites outside it: " + ", ".join(offenders)
    )
