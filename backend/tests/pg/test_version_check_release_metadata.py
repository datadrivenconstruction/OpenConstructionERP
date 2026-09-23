# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The version the banner names and the notes it shows must be one release.

``GET /api/system/version-check`` reads two sources. The number comes from
PyPI, which is the source of truth precisely because a hotfix can publish a
wheel without a GitHub release object being created; the notes, the link and
the date come from the newest GitHub release. In exactly the case that
motivates the preference, those two are a release apart, and the endpoint used
to publish them together: "15.1.0 is available", under it the notes for
15.0.0, and a link to the 15.0.0 release page.

For a desktop build that is not a cosmetic mismatch. The frozen bundle carries
no pip, so the only remedy it can offer is "download the installer from the
release page", and the page it was linking to is one that does not carry the
build the reader was just told to install.

These tests need no database and no authentication - the route touches
neither - but they live in the PG lane because that is the lane the real gate
runs. ``tests/unit`` is reached only by the files ci-postgres.yml names one by
one, and a test nobody runs is not a gate.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_id
from app.main import create_app

PYPI = "pypi.org"
GITHUB = "api.github.com"


class _Response:
    """The two attributes the route reads off an httpx response."""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Stands in for ``httpx.AsyncClient`` inside the route only.

    Routing is by substring of the URL because the route builds both URLs
    itself, and a test that hard-codes them would pass while the endpoint asked
    something else entirely.
    """

    routes: dict[str, _Response] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **_kwargs: object) -> _Response:
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        raise AssertionError(f"the route asked for an unexpected URL: {url}")


def _github_release(tag: str) -> _Response:
    return _Response(
        200,
        {
            "tag_name": tag,
            "html_url": f"https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/{tag}",
            "body": f"## {tag.lstrip('v')}\n\nWhat this particular release changed.",
            "published_at": "2026-08-01T09:00:00Z",
        },
    )


def _pypi_version(version: str) -> _Response:
    return _Response(200, {"info": {"version": version}})


@pytest_asyncio.fixture
async def ask():
    """Ask the endpoint once, with the two upstreams answering as told.

    The app is built per test so the four-hour cache on ``app.state`` starts
    empty, and the lifespan is deliberately not run: this route reads no
    database, and starting one would tie a metadata test to a cluster.

    The route answers signed-in callers only, and who is asking is not what
    this file tests, so the caller is stood in for rather than signed in.

    The client is constructed before ``httpx.AsyncClient`` is replaced, so the
    transport this test speaks over stays real while the route gets the fake.
    """

    async def _ask(monkeypatch: pytest.MonkeyPatch, routes: dict[str, _Response]) -> dict[str, Any]:
        app = create_app()
        app.dependency_overrides[get_current_user_id] = lambda: "version-check-reader"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            _FakeClient.routes = routes
            monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
            response = await client.get("/api/system/version-check")
        assert response.status_code == 200, response.text
        return response.json()

    return _ask


async def test_notes_are_dropped_when_they_describe_an_older_release(ask, monkeypatch: pytest.MonkeyPatch) -> None:
    """PyPI is ahead of GitHub, which is the hotfix case, so the notes go."""
    data = await ask(
        monkeypatch,
        {PYPI: _pypi_version("15.1.0"), GITHUB: _github_release("v15.0.0")},
    )

    assert data["latest_version"] == "15.1.0"
    assert data["release_notes"] == ""
    assert data["published_at"] == ""
    # Whatever we link to, it must not be the page for the other version.
    assert "15.0.0" not in data["release_url"]


async def test_notes_are_kept_when_the_release_names_the_same_version(ask, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary release, where both sources agree, keeps everything."""
    data = await ask(
        monkeypatch,
        {PYPI: _pypi_version("15.1.0"), GITHUB: _github_release("v15.1.0")},
    )

    assert data["latest_version"] == "15.1.0"
    assert "What this particular release changed." in data["release_notes"]
    assert data["published_at"] == "2026-08-01T09:00:00Z"
    assert data["release_url"].endswith("/releases/tag/v15.1.0")


async def test_a_tag_written_shorter_than_the_wheel_still_matches(ask, monkeypatch: pytest.MonkeyPatch) -> None:
    """``15.1`` and ``15.1.0`` are one release written by two tools.

    Without the padding this is a false mismatch, and a false mismatch throws
    away notes that were correct.
    """
    data = await ask(
        monkeypatch,
        {PYPI: _pypi_version("15.1.0"), GITHUB: _github_release("v15.1")},
    )

    assert "What this particular release changed." in data["release_notes"]


async def test_github_alone_still_answers_with_its_own_notes(ask, monkeypatch: pytest.MonkeyPatch) -> None:
    """PyPI unreachable. The number then comes from the release we are quoting,
    so the two agree by construction and nothing should be dropped."""
    data = await ask(
        monkeypatch,
        {PYPI: _Response(503, {}), GITHUB: _github_release("v15.1.0")},
    )

    assert data["latest_version"] == "15.1.0"
    assert "What this particular release changed." in data["release_notes"]


async def test_pypi_alone_names_a_version_and_promises_nothing_else(ask, monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub unreachable, so there is no release object to quote at all."""
    data = await ask(
        monkeypatch,
        {PYPI: _pypi_version("15.1.0"), GITHUB: _Response(403, {})},
    )

    assert data["latest_version"] == "15.1.0"
    assert data["release_notes"] == ""
    assert data["release_url"].endswith("/releases")
