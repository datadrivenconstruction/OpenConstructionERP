# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A request for a file that is not there must be told so.

The SPA fallback answers any unmatched path with ``index.html``, which is
correct for client-side routes and wrong for assets. A browser holding a stale
``index.html`` asks for a hashed bundle that a redeploy has deleted, gets HTML
back with status 200 and a ``text/html`` content type, and fails inside the
module loader. What the operator then sees is a syntax error in a script, which
is several steps from "that file is gone" and is where the debugging starts.
The 200 also invites the browser and every proxy between to keep the answer.

This is the same failure the ``/health`` and ``/openapi.json`` aliases already
exist to prevent, written up there as making a sick service look healthy to a
probe. The reasoning was never carried across to assets.

The discriminator is what the request is asking for rather than what it looks
like it might be. A file request is one whose suffix is a type this server
serves, or anything at all under the ``/assets`` mount, where the bundler puts
nothing else. Client-side routes have no suffix, and a route whose last segment
happens to contain a dot keeps its ``index.html`` unless that suffix is one we
would have served.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cli_static


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A frontend dist with one real bundle, one root file, and an index."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "assets" / "index-REAL1234.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")

    monkeypatch.setattr(cli_static, "get_frontend_dir", lambda: dist)

    app = FastAPI()
    cli_static.mount_frontend(app)
    return TestClient(app)


def test_a_bundle_that_exists_is_served(client: TestClient) -> None:
    """The control. Without it a blanket 404 would pass every case below."""
    r = client.get("/assets/index-REAL1234.js")

    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "export const ok" in r.text


def test_a_missing_bundle_is_a_404_and_not_the_index(client: TestClient) -> None:
    """The regression. This answered 200 with index.html."""
    r = client.get("/assets/index-DELETED9.js")

    assert r.status_code == 404, (
        f"a deleted bundle answered {r.status_code} with "
        f"{r.headers.get('content-type')!r}; a browser asks for this after a "
        f"redeploy and must be told the file is gone"
    )
    assert "<!doctype html>" not in r.text.lower()


def test_a_missing_root_script_is_a_404(client: TestClient) -> None:
    """Root-level scripts are the service worker's home, and it checks the type."""
    r = client.get("/sw.js")

    assert r.status_code == 404
    assert "<!doctype html>" not in r.text.lower()


@pytest.mark.parametrize("path", ["/favicon.ico", "/manifest.json", "/absent.css", "/nope.wasm"])
def test_every_served_type_answers_404_when_absent(client: TestClient, path: str) -> None:
    """Parametrised over types rather than asserting one, because the bug was a
    property of the fallback and not of any single extension."""
    r = client.get(path)

    assert r.status_code == 404, f"{path} answered {r.status_code}"


def test_a_root_file_that_exists_is_still_served(client: TestClient) -> None:
    """The other control. The fix must not turn present files into 404s."""
    r = client.get("/robots.txt")

    assert r.status_code == 200
    assert "User-agent" in r.text


@pytest.mark.parametrize("path", ["/projects/123", "/boq", "/", "/settings/ai"])
def test_client_side_routes_still_get_the_index(client: TestClient, path: str) -> None:
    """The point of the fallback, unchanged. These have no file to be missing."""
    r = client.get(path)

    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


def test_a_route_with_a_dot_in_it_is_not_mistaken_for_a_file(client: TestClient) -> None:
    """``.project`` is not a type this server serves, so the route survives.

    Worth pinning: the obvious implementation of "does this look like a file"
    is "does it contain a dot", and that would have turned a legitimate
    client-side route into a 404 while every test above still passed.
    """
    r = client.get("/projects/tower.a1")

    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


def test_an_api_path_still_gets_its_json_404(client: TestClient) -> None:
    """Unchanged, and asserted so the fix cannot have widened into the API."""
    r = client.get("/api/definitely-not-a-route")

    assert r.status_code == 404
    assert r.json()["detail"] == "Not Found"
