"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Verify the Asset Operations router exposes the expected routes.

This is a lightweight mount check that does NOT spin up the full app
lifespan (that path imports the unrelated ``oe_closeout`` module, whose
transitive import of ``app.core.job_runner`` uses the PEP 695 ``type``
statement and only parses on Python 3.12+, the project's target runtime).
The end-to-end HTTP behaviour is covered by
``tests/integration/test_assets_api.py`` on a 3.12 interpreter.
"""

from __future__ import annotations


def test_router_exposes_expected_routes():
    from app.modules.assets.router import router

    paths = {(tuple(sorted(r.methods)), r.path) for r in router.routes if hasattr(r, "methods")}
    flat = {p for _, p in paths}
    assert "/portfolio" in flat
    assert "/" in flat
    assert "/discover" in flat
    assert "/warranty-alerts" in flat
    assert "/{element_id}/service-log" in flat


def test_router_methods():
    from app.modules.assets.router import router

    by_path: dict[str, set[str]] = {}
    for r in router.routes:
        if hasattr(r, "methods"):
            by_path.setdefault(r.path, set()).update(r.methods)
    assert "GET" in by_path["/portfolio"]
    assert "GET" in by_path["/discover"]
    assert "POST" in by_path["/warranty-alerts"]
    assert "POST" in by_path["/{element_id}/service-log"]
