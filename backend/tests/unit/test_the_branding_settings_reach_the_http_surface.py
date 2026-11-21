"""The workspace settings, exercised through the HTTP surface that serves them.

``tests/integration/test_app_branding.py`` states the same contract against a real
application, a real database and two real accounts. That tree is gated on push and
pull request by exactly one job, which selects by the ``tenant_isolation`` marker
plus a frozen keyword chain it is documented not to extend - so a test there is
gated only if it earns the marker, which ``backend/pyproject.toml`` defines as
identity being the variable under test.

Two of these assertions earn it and eight do not. A refused URL scheme, a merge that
keeps an omitted field, a cleared destination and a page stored exactly as typed
are about values, with an admin merely the actor, and the marker's definition
names that neighbour as one that stays out. Marking the whole set anyway would
spend the marker's meaning to buy a green tick, and marking only the two denials
would gate a refusal without the allow side that proves the gate is not simply
denying everyone - which the same definition insists on.

So the contract is gated here instead, where all of it can be. The branding record
is a JSON file in the data directory and the only gate on the write is a role, so
a bare application holding just this router, a dependency override standing in for
a signed-in caller, and a temporary data directory exercise every rule below with
no database, no registration, no login and no rate limit in the way. That is the
trade ``tests/unit/test_admin_permissions_matrix.py`` makes for the admin
permission endpoints, for the same stated reason: the smallest setup that still
asserts the gate, the shape and the refusal.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import app_branding
from app.core.branding_router import router as branding_router
from app.dependencies import get_current_user_payload

API = "/api/v1/branding/"
MAILBOX = {"kind": "email", "value": "support@builder.example"}
SUPPORT_PAGE = {"kind": "url", "value": "https://support.builder.example/new-ticket"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A client over an app holding only the branding router, writing to tmp_path.

    ``resolve_data_dir`` is patched in the module that calls it, so the record
    under test is a file in this test's own temporary directory. Nothing here can
    read or disturb a data directory another test is using, and the branding
    cache - keyed by path - cannot carry a value from one test into the next.

    No lifespan is entered, on purpose: starting the real application boots the
    database and the background schedulers, and none of it is needed to serve a
    JSON file behind a role check.
    """
    monkeypatch.setattr(app_branding, "resolve_data_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(branding_router, prefix="/api/v1")
    return TestClient(app)


def sign_in_as(client: TestClient, role: str) -> None:
    """Make every later request arrive as a caller holding ``role``.

    The override replaces the dependency that validates the bearer token and
    rehydrates the caller from the database, which is the seam ``RequireRole``
    itself reads: it resolves the role out of this payload, so a gate that refuses
    a viewer here is refusing one for the reason it refuses one in production.
    """
    uid = str(uuid.uuid4())

    async def _payload() -> dict[str, Any]:
        return {"sub": uid, "role": role, "permissions": []}

    client.app.dependency_overrides[get_current_user_payload] = _payload


def sign_out(client: TestClient) -> None:
    """Arrive with no caller at all, which is how the login page asks."""
    client.app.dependency_overrides.pop(get_current_user_payload, None)


def test_the_get_is_public_and_reports_the_defaults(client: TestClient) -> None:
    """Read with no token, because the footers render before anybody signs in.

    ``support_destination`` null is the state in which the header leaves the
    bug-report channel out of the menu entirely. ``update_check_enabled`` false is
    the state in which the product asks nothing on the internet, and it is served
    without a token for the same reason the Legal-link flag is: About states the
    posture to every user, and a disclosure only an administrator could read would
    not be a disclosure.
    """
    resp = client.get(API)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["support_destination"] is None
    assert body["legal_link_visible"] is True
    assert body["update_check_enabled"] is False


def test_an_admin_sets_a_mailbox_and_an_anonymous_reader_sees_it(client: TestClient) -> None:
    sign_in_as(client, "admin")
    put = client.put(API, json={"support_destination": MAILBOX})
    assert put.status_code == 200, put.text
    assert put.json()["support_destination"] == MAILBOX

    # The allow side of the gate, and the half that matters for a setting served
    # from a public endpoint: what an admin wrote is what a signed-out reader gets.
    sign_out(client)
    anon = client.get(API)
    assert anon.status_code == 200, anon.text
    assert anon.json()["support_destination"] == MAILBOX


def test_a_viewer_is_refused_on_all_three_settings_and_changes_none(client: TestClient) -> None:
    sign_in_as(client, "viewer")
    destination = client.put(API, json={"support_destination": SUPPORT_PAGE})
    assert destination.status_code == 403, destination.text
    flag = client.put(API, json={"legal_link_visible": False})
    assert flag.status_code == 403, flag.text
    # The one that starts a connection nobody asked for is the one a viewer must
    # least be able to turn on for everybody else.
    check = client.put(API, json={"update_check_enabled": True})
    assert check.status_code == 403, check.text

    sign_out(client)
    body = client.get(API).json()
    assert body["support_destination"] is None
    assert body["legal_link_visible"] is True
    assert body["update_check_enabled"] is False


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "https://user:password@support.example",
    ],
)
def test_a_destination_that_executes_or_leaks_is_dropped_rather_than_served(client: TestClient, value: str) -> None:
    """Sanitised at the edge, and the request still succeeds.

    The endpoint does not 4xx on a bad scheme; it drops the value and answers with
    what it kept, which is how the record's other fields behave when one of them
    is unusable. The value is admin-set, but it is served from a public endpoint
    and opened in a user's browser, so a scheme that executes instead of
    navigating - or credentials embedded in an authority - must never be stored
    even once.
    """
    sign_in_as(client, "admin")
    put = client.put(API, json={"support_destination": {"kind": "url", "value": value}})
    assert put.status_code == 200, put.text
    assert put.json()["support_destination"] is None, value

    sign_out(client)
    assert client.get(API).json()["support_destination"] is None, value


def test_a_page_destination_is_stored_exactly_as_the_admin_typed_it(client: TestClient) -> None:
    sign_in_as(client, "admin")
    put = client.put(API, json={"support_destination": SUPPORT_PAGE})
    assert put.status_code == 200, put.text
    # Not lower-cased, not normalised, not given a trailing slash or a query
    # string: the header opens this URL as it stands and copies the report
    # separately, so a server that quietly rewrote it would send users somewhere
    # the operator did not write.
    assert put.json()["support_destination"] == SUPPORT_PAGE


def test_an_admin_can_hide_the_legal_link_and_show_it_again(client: TestClient) -> None:
    sign_in_as(client, "admin")
    off = client.put(API, json={"legal_link_visible": False})
    assert off.status_code == 200, off.text
    assert off.json()["legal_link_visible"] is False
    sign_out(client)
    assert client.get(API).json()["legal_link_visible"] is False

    sign_in_as(client, "admin")
    on = client.put(API, json={"legal_link_visible": True})
    assert on.json()["legal_link_visible"] is True


def test_setting_one_field_leaves_the_other_alone(client: TestClient) -> None:
    """The router merges by ``model_fields_set``, so an omitted field persists.

    Without this, saving a support mailbox would silently turn the Legal link back
    on, and saving the company name would clear the mailbox. Both are the same bug
    and both are invisible in a UI that only ever sends one thing at a time.
    """
    sign_in_as(client, "admin")
    both = client.put(API, json={"legal_link_visible": False, "support_destination": MAILBOX})
    assert both.status_code == 200, both.text
    name = client.put(API, json={"company_name": "Meridian"})
    assert name.status_code == 200, name.text

    sign_out(client)
    body = client.get(API).json()
    assert body["company_name"] == "Meridian"
    assert body["legal_link_visible"] is False
    assert body["support_destination"] == MAILBOX


def test_clearing_the_destination_hides_the_channel_again(client: TestClient) -> None:
    sign_in_as(client, "admin")
    client.put(API, json={"support_destination": SUPPORT_PAGE})
    cleared = client.put(API, json={"support_destination": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["support_destination"] is None

    sign_out(client)
    assert client.get(API).json()["support_destination"] is None


def test_an_administrator_can_turn_the_version_check_on_and_off_again(client: TestClient) -> None:
    """The allow side, and the half that makes the refusal above mean something.

    Read back with no token, because that is how About reads the posture it states
    to every user: what an administrator wrote has to be what a signed-out reader
    gets, or the disclosure describes the record and not the installation.
    """
    sign_in_as(client, "admin")
    on = client.put(API, json={"update_check_enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["update_check_enabled"] is True
    sign_out(client)
    assert client.get(API).json()["update_check_enabled"] is True

    sign_in_as(client, "admin")
    off = client.put(API, json={"update_check_enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["update_check_enabled"] is False
    sign_out(client)
    assert client.get(API).json()["update_check_enabled"] is False


def test_saving_the_brand_leaves_the_version_check_as_it_was(client: TestClient) -> None:
    """The merge is by ``model_fields_set``, so an omitted field persists.

    Without it, uploading a logo or naming a support mailbox would silently turn
    the outbound check on for the whole workspace - the exact failure the merge
    exists to prevent, in the direction that sends a request nobody started.
    """
    sign_in_as(client, "admin")
    client.put(API, json={"update_check_enabled": True})
    brand = client.put(API, json={"company_name": "Meridian", "support_destination": MAILBOX})
    assert brand.status_code == 200, brand.text

    sign_out(client)
    body = client.get(API).json()
    assert body["company_name"] == "Meridian"
    assert body["support_destination"] == MAILBOX
    assert body["update_check_enabled"] is True

    sign_in_as(client, "admin")
    client.put(API, json={"update_check_enabled": False})
    legal = client.put(API, json={"legal_link_visible": False})
    assert legal.status_code == 200, legal.text
    sign_out(client)
    assert client.get(API).json()["update_check_enabled"] is False
