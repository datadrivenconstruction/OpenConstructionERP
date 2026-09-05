# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""No unauthenticated response names the server's own filesystem.

Three routes answer without credentials on purpose and used to describe the
machine while doing it: the converter listing, the converter version check and
the install-progress poll. Each carried an absolute path to a converter binary,
which on a default install lives under the operator's home directory and so
publishes both the directory layout and the operating system account name of
whoever runs the process, to anybody who can reach the port.

The routes stay open. What they are for survives without the path: a caller
asking whether a converter is installed is answered by ``installed``, and one
asking whether a newer build exists is answered by two SHAs. An authenticated
caller still gets the path, because the Settings panel and the BIM banner both
print it and an operator repairing a broken install needs the folder name.

What is asserted here is the **absence of the host path**, computed by walking
every string in the body and asking whether it names a place on this machine,
rather than the presence of whatever field the fix happens to introduce. A test
written around the new shape would stay green against a regression that put the
path back somewhere else in the body, which is the shape of at least three of
the channels found in this sweep - the version check spelt it ``installed_path``,
the listing spelt it ``path``, and the smoke test buried it in prose inside
``health_message``.

One case here is not about the body at all. Producing that ``health_message``
means launching the converter exe and waiting on it, which is the act the
per-converter verify route asks a permission for, so the listing declines it
for a caller who has not signed in rather than running it and emptying the
output afterwards. That one is asserted by counting launches, because a body
that has been redacted and a body that was never produced look alike.
"""

from __future__ import annotations

import getpass
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import create_app

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


#: A stand-in for the operator's home directory. Distinctive enough that a
#: match cannot be a coincidence, and used instead of the real one so the test
#: reads the same on a developer laptop and on a CI runner.
_FAKE_HOME = "Zq-operator-home"

#: Where the fake converter pretends to live. Absolute on both platforms the
#: product ships on, because that is the property under test.
_FAKE_CONVERTER = Path(f"C:/Users/{_FAKE_HOME}/.openestimator/converters/rvt_windows/RvtExporter.exe")

#: Shapes that name a place on a host rather than a place in the API. A Windows
#: drive-letter root, the two usual homes of a home directory on Unix, and the
#: account this process actually runs as. The last one is what catches a
#: regression that leaks the real path rather than the fixture's.
#:
#: The drive-letter pattern refuses a preceding letter on purpose. Without that
#: it matches the ``s:/`` in every ``https://`` and reports the GitHub download
#: link this endpoint is supposed to return, which is the sort of false read
#: that gets a whole assertion deleted rather than corrected.
_HOST_PATH_SHAPES = [
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(r"/home/[^/\s]"),
    re.compile(r"/Users/[^/\s]"),
    re.compile(r"[\\/]\.openestimator[\\/]"),
    re.compile(re.escape(_FAKE_HOME)),
]

_ACCOUNT = getpass.getuser()
if len(_ACCOUNT) >= 4:
    # Short logins ("ci", "u", "app") match half the English language; skip
    # them rather than assert something that would fail on unrelated prose.
    _HOST_PATH_SHAPES.append(re.compile(rf"\b{re.escape(_ACCOUNT)}\b"))

# One of the shapes is conditional and the rest are not, so say out loud how
# many always run. Otherwise this file passes identically on a machine where
# the account shape was skipped, and a reader has no way to tell which of the
# two things they are looking at.
assert len(_HOST_PATH_SHAPES) >= 5, "the unconditional shapes are what carries this file"


def host_path_strings(payload: Any, trail: str = "$") -> list[str]:
    """Every string anywhere in ``payload`` that names a place on this host.

    Walks the decoded body rather than reading named fields, so a path that
    comes back under a different key, nested one level deeper, or spliced into
    a sentence is found the same way the original one was. Returns
    ``["<json path> -> <the offending value>"]`` so a failure says where.
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(host_path_strings(value, f"{trail}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(host_path_strings(value, f"{trail}[{index}]"))
    elif isinstance(payload, str) and any(shape.search(payload) for shape in _HOST_PATH_SHAPES):
        found.append(f"{trail} -> {payload}")
    return found


@pytest_asyncio.fixture(scope="module")
async def app_client():
    """One application, one lifespan, so the modules are mounted."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
            yield app, client


@pytest_asyncio.fixture(scope="module")
async def auth_headers(app_client):
    """A signed-in caller, to prove the fix is a redaction and not a deletion."""
    from sqlalchemy import update as sa_update

    from app.modules.users.models import User

    _app, client = app_client
    unique = uuid.uuid4().hex[:8]
    email = f"paths-{unique}@disclosure-probe.io"
    password = f"PathProbe{unique}9!"

    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Path Disclosure Probe"},
    )
    assert registered.status_code == 201, registered.text

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    signed_in = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert signed_in.status_code == 200, signed_in.text
    return {"Authorization": f"Bearer {signed_in.json()['access_token']}"}


@pytest.fixture
def an_installed_converter(monkeypatch):
    """Make every converter lookup answer with the fake absolute path.

    Patched at ``app.modules.boq.cad_import``, which is where all three routes
    import it from at call time, so one patch covers them all and none of them
    depends on what is really installed on the machine running the suite.
    """
    from app.modules.boq import cad_import

    monkeypatch.setattr(cad_import, "find_converter", lambda _ext: _FAKE_CONVERTER)
    return _FAKE_CONVERTER


@pytest.fixture
def a_smoke_test_that_names_the_folder(monkeypatch):
    """A health result whose prose quotes the install directory.

    This is the real shape: every failing branch of ``smoke_test_converter``
    writes ``exe_path.parent`` into ``message`` so the operator knows which
    folder to rebuild. Useful text, and not for an anonymous reader.

    Returns the list of converters it was actually asked about, because whether
    the smoke test runs at all is itself under test: running it launches the exe.
    """
    from app.modules.boq import cad_import

    ran: list[str] = []

    def _health(extension: str, force: bool = False) -> dict[str, Any]:
        ran.append(extension)
        return {
            "status": "failed",
            "message": (
                f"{_FAKE_CONVERTER.parent} holds {_FAKE_CONVERTER.name} but not Qt6Core.dll, "
                f"so that folder has only part of a converter in it."
            ),
            "suggested_actions": ["reinstall_converter"],
            "checked_at": 0.0,
        }

    monkeypatch.setattr(cad_import, "smoke_test_converter", _health)
    return ran


@pytest.fixture
def a_finished_install(monkeypatch):
    """An install record of the kind that lingers for three minutes after one.

    Written through the module's own setter so the record has the shape the
    installer really leaves behind, including the success message that quotes
    the path back.
    """
    import time as _time

    from app.modules.takeoff import router as takeoff_router

    converter_id = "rvt"
    takeoff_router._clear_install_progress(converter_id)
    takeoff_router._set_install_progress(
        converter_id,
        stage="done",
        installed=True,
        finished_at=_time.time(),
        current=175,
        total=175,
        path=str(_FAKE_CONVERTER),
        message=f"RVT Parser installed successfully at {_FAKE_CONVERTER}",
        error="",
    )
    yield converter_id
    takeoff_router._clear_install_progress(converter_id)


@pytest.fixture
def a_warm_version_check_cache(app_client, monkeypatch):
    """Seed the six-hour cache with one canonical answer.

    The cache is why redaction has to happen on a copy, and seeding it is the
    only way to exercise that without a network call. The real handler only
    caches when it reached GitHub, which the suite forbids.

    ``sys.platform`` is pinned to Windows for the same reason the fake path is
    a Windows one: the handler short-circuits off-Windows with an empty,
    path-free answer, so without this the test would be measuring nothing on a
    Linux runner while passing there for the wrong reason.
    """
    import sys as _sys
    import time as _time

    monkeypatch.setattr(_sys, "platform", "win32")

    app, _client = app_client
    previous = getattr(app.state, "_converter_version_cache", None)
    row = {
        "id": "rvt",
        "name": "RVT Parser",
        "exe": "RvtExporter.exe",
        "installed": True,
        "installed_path": str(_FAKE_CONVERTER),
        "installed_size": 4096,
        "installed_sha": "a" * 40,
        "latest_size": 4096,
        "latest_sha": "b" * 40,
        "is_outdated": True,
        "download_url": "https://raw.githubusercontent.com/x/y/z/RvtExporter.exe",
        "html_url": "https://github.com/x/y/blob/z/RvtExporter.exe",
    }
    rows = [row]
    app.state._converter_version_cache = {
        "data": {
            "converters": rows,
            "results": rows,
            "any_outdated": True,
            "network_ok": True,
            "checked_at": "2026-09-05T00:00:00+00:00",
            "ttl_seconds": 6 * 3600,
        },
        "checked_at_ts": _time.time(),
    }
    yield
    app.state._converter_version_cache = previous


# ── The converter listing ────────────────────────────────────────────────


async def test_the_converter_listing_tells_an_anonymous_caller_nothing_about_the_disk(
    app_client,
    an_installed_converter,
):
    _app, client = app_client
    response = await client.get("/api/v1/takeoff/converters/")
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body) == []
    # And the status check still answers the question it exists for.
    assert body["installed_count"] == len(body["converters"])
    assert all(row["installed"] for row in body["converters"])


async def test_the_converter_listing_still_tells_the_operator_where_the_binary_is(
    app_client,
    auth_headers,
    an_installed_converter,
):
    """The fix is a redaction, not a deletion: the Settings panel still renders this."""
    _app, client = app_client
    response = await client.get("/api/v1/takeoff/converters/", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body), "a signed-in operator must still be given the install path"
    assert all(row["path"] == str(_FAKE_CONVERTER) for row in body["converters"])


async def test_a_failing_smoke_test_does_not_name_its_folder_to_an_anonymous_caller(
    app_client,
    an_installed_converter,
    a_smoke_test_that_names_the_folder,
):
    """The second channel on the same route, and the one a field-name test misses."""
    _app, client = app_client
    response = await client.get("/api/v1/takeoff/converters/", params={"verify": "true"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body) == []
    # And the status check still answers the question it exists for.
    assert all(row["installed"] for row in body["converters"])


async def test_a_failing_smoke_test_still_names_its_folder_to_the_operator(
    app_client,
    auth_headers,
    an_installed_converter,
    a_smoke_test_that_names_the_folder,
):
    _app, client = app_client
    response = await client.get(
        "/api/v1/takeoff/converters/",
        params={"verify": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body), "the operator has to be told which folder to rebuild"


async def test_an_anonymous_caller_cannot_make_the_server_launch_the_converter_binaries(
    app_client,
    auth_headers,
    an_installed_converter,
    a_smoke_test_that_names_the_folder,
):
    """``verify=true`` is the same act the per-converter route asks a permission for.

    Both halves belong in one test. An anonymous ``verify=true`` must launch
    nothing, and the only way to know that assertion means anything is to watch
    the same fixture record launches for a caller who is allowed them.
    """
    _app, client = app_client
    ran = a_smoke_test_that_names_the_folder

    anonymous = await client.get("/api/v1/takeoff/converters/", params={"verify": "true"})
    assert anonymous.status_code == 200, anonymous.text
    assert ran == [], "an anonymous verify=true launched the converter exe"

    operator = await client.get(
        "/api/v1/takeoff/converters/",
        params={"verify": "true"},
        headers=auth_headers,
    )
    assert operator.status_code == 200, operator.text
    assert ran, "the smoke test has to run for someone, or the assertion above proves nothing"


# ── The version check ────────────────────────────────────────────────────


async def test_the_version_check_tells_an_anonymous_caller_nothing_about_the_disk(
    app_client,
    a_warm_version_check_cache,
):
    _app, client = app_client
    response = await client.get("/api/system/converters/version-check")
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body) == []
    # The comparison the endpoint exists to answer is untouched.
    assert body["any_outdated"] is True
    assert body["converters"][0]["is_outdated"] is True
    assert body["converters"][0]["installed_sha"] == "a" * 40


async def test_an_anonymous_version_check_does_not_empty_the_cache_for_the_operator(
    app_client,
    auth_headers,
    a_warm_version_check_cache,
):
    """Redaction on a copy, asserted in both orders.

    A fix that popped the field out of the cached dict passes when the operator
    reads first and fails only on the second ordering; a fix that cached
    whichever form warmed it passes the other way round. Neither survives both.
    """
    _app, client = app_client

    anonymous_first = await client.get("/api/system/converters/version-check")
    operator_second = await client.get("/api/system/converters/version-check", headers=auth_headers)
    assert host_path_strings(anonymous_first.json()) == []
    assert host_path_strings(operator_second.json()), "an anonymous read emptied the operator's answer"

    operator_first = await client.get("/api/system/converters/version-check", headers=auth_headers)
    anonymous_second = await client.get("/api/system/converters/version-check")
    assert host_path_strings(operator_first.json())
    assert host_path_strings(anonymous_second.json()) == [], "a warmed cache leaked the path to an anonymous read"


# ── The install-progress poll ────────────────────────────────────────────


async def test_install_progress_tells_an_anonymous_caller_nothing_about_the_disk(
    app_client,
    a_finished_install,
):
    _app, client = app_client
    response = await client.get(f"/api/v1/takeoff/converters/{a_finished_install}/install-progress/")
    assert response.status_code == 200, response.text
    body = response.json()

    assert host_path_strings(body) == []
    # What the progress bar reads is all still there.
    assert body["active"] is True
    assert body["stage"] == "done"
    assert body["current"] == 175


async def test_install_progress_still_reports_the_outcome_to_the_operator(
    app_client,
    auth_headers,
    a_finished_install,
):
    _app, client = app_client
    response = await client.get(
        f"/api/v1/takeoff/converters/{a_finished_install}/install-progress/",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    assert host_path_strings(response.json()), "the operator's install toast quotes the path back"
