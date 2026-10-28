# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A deployment without a frontend must not look like a crashed server.

Two states, and until this fix they were answered by one bug and one silence.

A server that never found a bundle already answered 404, because
``mount_frontend`` returns before registering the SPA fallback. The 404 was the
bare ``{"detail":"Not Found"}`` FastAPI produces for a route that does not
exist, which reads as a mistyped URL. The truth is that the wheel shipped
without a UI, or the volume holding the build never mounted, and the server
knows that at startup.

A server that mounted a bundle and then lost it answered 500. ``FileResponse``
raises ``RuntimeError`` on a path that is not there, and the ASGI stack turns
that into ``Internal Server Error`` in plain text. An operator reading that goes
looking for an application crash, when the application is healthy and a
directory is gone. Measured before the fix, with the whole dist removed under a
running client: ``/boq`` 500, ``/favicon.svg`` 500, ``/logo.svg`` 500.

``/assets/*`` belongs on that list too, and the way it hides is worth pinning.
``StaticFiles`` stats its directory once and raises ``RuntimeError`` if it is
gone, and that check runs on the FIRST REQUEST, not at construction. So a server
that had served one asset before the dist vanished answered 404, and a server
whose dist went missing before its first asset request answered 500. Same
deployment, opposite diagnosis, decided by traffic order - and a first probe
that happened to warm the mount reported the honest number.

``raise_server_exceptions=False`` throughout, deliberately. Under the default
the pre-fix code raises ``RuntimeError`` out of the client instead of returning
500, so a test written the usual way passes against the broken code for the
wrong reason and proves nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cli_static

# Paths a browser asks a running server for. Parametrised rather than asserted
# one at a time because the defect was a property of every handler that closed
# over a path checked at mount time, not of any single route.
UI_PATHS = ["/", "/boq", "/projects/123", "/favicon.svg", "/logo.svg"]


def _build_dist(root: Path) -> Path:
    """Write a minimal but complete frontend dist.

    Args:
        root: Directory to create the dist under.

    Returns:
        Path to the dist directory.
    """
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (dist / "assets" / "index-REAL1234.js").write_text("export const ok = 1;\n", encoding="utf-8")
    return dist


class TestAServerThatNeverFoundABundle:
    """``mount_frontend`` could not resolve a dist at startup."""

    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        def _missing() -> Path:
            raise FileNotFoundError("Frontend dist not found. Looked for index.html in ...")

        monkeypatch.setattr(cli_static, "get_frontend_dir", _missing)

        app = FastAPI()
        cli_static.mount_frontend(app)
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path", UI_PATHS)
    def test_every_ui_path_is_a_404(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 404

    def test_the_404_says_the_server_has_no_bundle(self, client: TestClient) -> None:
        """The point of the change. A bare denial sends the reader after the URL."""
        detail = client.get("/boq").json()["detail"]

        assert detail != "Not Found", "the 404 still only denies the path"
        assert "API only" in detail
        assert "npm run build" in detail

    def test_the_api_keeps_its_own_404(self, client: TestClient) -> None:
        """Asserted so the new handler cannot have widened into the API surface.

        An API client parsing ``detail`` must not start receiving a message
        about a frontend it never asked for.
        """
        r = client.get("/api/definitely-not-a-route")

        assert r.status_code == 404
        assert r.json()["detail"] == "Not Found"

    def test_the_startup_log_names_the_state_once(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Startup can know this one, so it should say it without being asked.

        The condition is permanent for the life of the process; a line at boot
        is worth more than the four hundredth 404.
        """

        def _missing() -> Path:
            raise FileNotFoundError("Frontend dist not found. Looked for index.html in /a and /b.")

        monkeypatch.setattr(cli_static, "get_frontend_dir", _missing)

        with caplog.at_level("WARNING", logger="app.cli_static"):
            cli_static.mount_frontend(FastAPI())

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "serving API only" in warnings[0]
        # Both candidate directories, because "missing" means an empty wheel in
        # one and an unbuilt checkout in the other.
        assert "/a" in warnings[0]
        assert "/b" in warnings[0]


class TestABundleThatDisappearedUnderARunningServer:
    """The 500. Mounted at startup, gone by the time a request arrives."""

    @pytest.fixture
    def dist(self, tmp_path: Path) -> Path:
        return _build_dist(tmp_path)

    @pytest.fixture
    def client(self, dist: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setattr(cli_static, "get_frontend_dir", lambda: dist)

        app = FastAPI()
        cli_static.mount_frontend(app)
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path", UI_PATHS)
    def test_the_control_every_path_is_served_while_the_dist_is_there(self, client: TestClient, path: str) -> None:
        """Without this a blanket 404 would satisfy every assertion below."""
        assert client.get(path).status_code == 200

    @pytest.mark.parametrize("path", UI_PATHS)
    def test_every_ui_path_is_a_404_and_not_a_500(self, client: TestClient, dist: Path, path: str) -> None:
        """The regression. ``/boq``, ``/favicon.svg`` and ``/logo.svg`` were 500s."""
        shutil.rmtree(dist)

        r = client.get(path)

        assert r.status_code == 404, (
            f"{path} answered {r.status_code}; a build directory that went "
            f"missing must not read as a crashed application"
        )

    def test_the_404_says_the_bundle_went_missing(self, client: TestClient, dist: Path) -> None:
        """Distinct from the never-mounted message: the way out is different."""
        shutil.rmtree(dist)

        detail = client.get("/boq").json()["detail"]

        assert detail != "Not Found"
        assert "no longer on disk" in detail
        assert "npm run build" not in detail, "this deployment had a build; rebuilding is not the advice"

    def test_the_loss_is_logged_once_and_not_once_per_request(
        self, client: TestClient, dist: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Startup cannot know this one, so the request path has to say it.

        Once, though. The state holds until someone restores the directory, and
        a line per page load buries the one that mattered.
        """
        shutil.rmtree(dist)

        with caplog.at_level("ERROR", logger="app.cli_static"):
            for _ in range(5):
                client.get("/boq")
            client.get("/favicon.svg")

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1, f"expected one line, got {len(errors)}"
        assert str(dist) in errors[0], "the log is where the server-side path belongs"

    def test_the_body_does_not_leak_a_server_path(self, client: TestClient, dist: Path) -> None:
        """The log gets the path; an anonymous HTTP caller does not."""
        shutil.rmtree(dist)

        assert str(dist) not in client.get("/boq").text

    def test_an_asset_is_a_404_even_as_the_very_first_request(self, client: TestClient, dist: Path) -> None:
        """The one the first repro missed, because it asked in the wrong order.

        ``StaticFiles`` defers its directory check to the first request, so a
        mount that has already served something answers 404 while a cold one
        answers 500. No request precedes this one on purpose: warming the mount
        first is what makes the defect invisible.
        """
        shutil.rmtree(dist)

        assert client.get("/assets/index-REAL1234.js").status_code == 404

    def test_an_asset_is_still_a_404_on_a_mount_that_had_already_served(self, client: TestClient, dist: Path) -> None:
        """The other order, which was already correct and must stay correct."""
        assert client.get("/assets/index-REAL1234.js").status_code == 200

        shutil.rmtree(dist)

        assert client.get("/assets/index-REAL1234.js").status_code == 404

    def test_the_api_still_gets_its_own_404(self, client: TestClient, dist: Path) -> None:
        shutil.rmtree(dist)

        r = client.get("/api/definitely-not-a-route")

        assert r.status_code == 404
        assert r.json()["detail"] == "Not Found"


class TestResolutionAgreesWithWhatTheServerNeeds:
    """``get_frontend_dir`` gated on ``exists``; ``FileResponse`` needs a file."""

    def test_a_directory_named_index_html_is_not_a_frontend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise resolution succeeds and the first request 500s.

        Contrived on purpose: the cheap fix is a one-word change, and the
        alternative is a mount that passes every startup check and serves
        nothing.
        """
        pkg = tmp_path / "app"
        (pkg / "_frontend_dist" / "index.html").mkdir(parents=True)
        monkeypatch.setattr(cli_static, "__file__", str(pkg / "cli_static.py"))

        with pytest.raises(FileNotFoundError):
            cli_static.get_frontend_dir()

    def test_the_error_names_both_places_it_looked(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """An operator who cannot see which directory was expected debugs the wrong one."""
        monkeypatch.setattr(cli_static, "__file__", str(tmp_path / "app" / "cli_static.py"))

        with pytest.raises(FileNotFoundError) as excinfo:
            cli_static.get_frontend_dir()

        message = str(excinfo.value)
        assert "_frontend_dist" in message
        assert str(Path("frontend") / "dist") in message
