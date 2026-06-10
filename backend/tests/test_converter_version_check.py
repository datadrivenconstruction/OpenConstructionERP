"""Regression tests for the system converter version-check payload."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_converter_version_check_exposes_converters_key() -> None:
    """The system endpoint must always expose `converters` for the UI.

    The Settings converters panel calls `data.converters.map(...)`.
    A previous backend response exposed only `results` on the non-Windows
    path, which crashed the page with `Cannot read properties of undefined
    (reading 'map')`.
    """
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/system/converters/version-check")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "converters" in body
    assert "results" in body
    assert isinstance(body["converters"], list)
    assert isinstance(body["results"], list)
    assert body["converters"] == body["results"]
    assert body["network_ok"] is True
