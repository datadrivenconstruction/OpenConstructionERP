# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The session list says which session you are reading it from.

Revocation is only usable if the person can tell the sessions apart. Without
this flag the list is five rows of timestamps, and the one action people
actually want - end everything except the device in my hand - requires knowing
which row is the device in your hand. Getting that wrong is not a cosmetic
error: it signs you out of the session you are working in and leaves the one
you were worried about alive.

Kept in its own file rather than beside the revocation tests because it
measures a different claim. Those ask whether a session can be ended; this asks
whether the list is legible enough to choose the right one. The flag is also
the only field in the response computed from the REQUEST rather than read from
the row, so it is the only one that can be right for one caller and wrong for
another - and a test that logs in once cannot see that at all.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PASSWORD = "CurrentSessionPassw0rd!"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """One app, one lifespan, driven synchronously.

    Module-scoped and sync for the same reason as the revocation test beside
    it: ``TestClient`` runs the app on its own portal thread, so building a
    second app inside an async test would cross event loops and re-run module
    discovery in the same process.
    """
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _register(client: TestClient) -> str:
    """Register a fresh account and return its e-mail.

    ``.example.com`` and not ``.test``: the reserved TLD is refused by our own
    e-mail validation, so registration answers 422 and every later assertion
    dies on the control instead of on what it meant to measure.
    """
    email = f"current-{uuid.uuid4().hex[:8]}@sessions.example.com"
    resp = client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Current Session Tester"},
    )
    assert resp.status_code in (200, 201), f"registration failed: {resp.text}"
    return email


def _login(client: TestClient, email: str) -> str:
    """Open one more session for an account and return its access token."""
    resp = client.post("/api/v1/users/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed for {email}: {resp.text}"
    return resp.json()["access_token"]


def _sessions(client: TestClient, access_token: str) -> list[dict]:
    """The rows out of the page envelope the route answers with.

    The total is checked against the rows here for the reason the envelope was
    introduced: "end every session except this one" is only safe if the caller
    was handed every session, and a page that was cut short would otherwise
    read as a shorter list rather than as an incomplete answer.
    """
    resp = client.get("/api/v1/users/me/sessions", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200, f"listing sessions failed: {resp.text}"
    body = resp.json()
    assert body["total"] == len(body["items"]), (
        f"the page reports {body['total']} sessions and carries {len(body['items'])}; "
        "the assertions below count rows and cannot tell a short list from a cut page"
    )
    return body["items"]


def test_each_caller_sees_its_own_session_marked_and_only_that_one(client: TestClient) -> None:
    """Three sessions, three listings, each naming a different current row.

    Reading the list from more than one session is what gives the test its
    teeth. With a single login the flag is right by accident under several
    wrong implementations - marking the newest row, marking the first row,
    marking every row - because with one session those all coincide. The
    second and third sessions separate them: the answer has to move with the
    token doing the asking while the rows stay the same.

    The count assertion and the identity assertion catch different mistakes. A
    flag hardwired to ``True`` passes identity and fails the count; a flag
    hardwired to ``False``, which is what a defaulted field would produce,
    fails both, and is the failure the required field in the schema exists to
    prevent.
    """
    email = _register(client)
    first = _login(client, email)
    second = _login(client, email)
    third = _login(client, email)

    listed = _sessions(client, first)
    assert len(listed) == 3, f"expected the three sessions this account just opened, got {len(listed)}"

    # Control: the flag is not simply absent or uniform. If every row carried
    # the same value the per-caller assertions below could still pass one at a
    # time while the field said nothing at all.
    assert {row["current"] for row in listed} == {True, False}, (
        "every session carries the same value for 'current', so the field distinguishes nothing"
    )

    seen: list[str] = []
    for label, token in (("first", first), ("second", second), ("third", third)):
        rows = _sessions(client, token)
        marked = [row["sid"] for row in rows if row["current"]]
        assert len(marked) == 1, (
            f"the {label} session's listing marked {len(marked)} sessions as current; "
            "exactly the one doing the asking must be marked, or 'end all the others' "
            "ends the wrong ones"
        )
        seen.append(marked[0])

    assert len(set(seen)) == 3, (
        f"three different sessions listed the same set of rows and reported {sorted(set(seen))} "
        "as current; the flag is being read from the row instead of from the caller"
    )

    # And the rows themselves are the same three regardless of who asks, so
    # what moved above is the flag and not the contents of the list.
    assert set(seen) == {row["sid"] for row in listed}, (
        "the sessions reported as current are not the sessions on the list"
    )
