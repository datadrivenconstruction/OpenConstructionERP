"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the architecture_map module.

Two things are pinned here, and they are different in kind.

The first is the permission gate. The architecture map exposes
high-signal structural intelligence about the running ERP: module file
lists, ORM models, table names, column SQL types, the dependency graph.
That surface is gated to ``Role.ADMIN`` via ``architecture.read``, and
the tests below pin the gate so a future contributor does not silently
drop it back to "any logged-in user" the way it was before that audit.

The second is the response content, and it is new. Every endpoint except
``GET /`` used to read a manifest schema that the generator has never
produced: top-level ``connections`` / ``layers`` / ``categories``, and
modules keyed by ``id``. Because those reads all went through
``dict.get`` with a default, nothing raised. ``/modules/{module_id}``
returned 404 for all 195 modules that exist, ``/connections`` returned
``[]``, ``/search`` matched nothing for any query, and ``/stats``
reported zeros. The old version of this file could not see any of it,
because it asserted only that a list was a list and that a key was
present. ``assert isinstance(resp.json(), list)`` is satisfied by ``[]``,
and ``assert "total_connections" in body`` is satisfied by ``0``.

So the rule for this file is: every assertion that something is returned
is paired with one that pins what was returned. A test that says "not
empty" without saying "and these are the values" would have passed
against the broken router, which is the whole reason the defect survived
this long.

Two tests are deliberately built to fail if the schema regresses:
``test_module_is_found_by_module_id_not_id`` goes red the moment the
lookup key moves back to ``id``, and
``test_the_manifest_has_no_layer_anywhere`` goes red if a layer concept
is ever added to the generator without revisiting the endpoints that
were stripped of it.

The synthetic fixture keeps most of the file fast and free of the real
6 MB file. One class at the end runs against the shipped manifest so the
populations are real, and no test here needs a database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.permissions import (
    PermissionRegistry,
    Role,
    permission_registry,
)
from app.dependencies import get_current_user_payload
from app.modules.architecture_map import router as router_module
from app.modules.architecture_map.permissions import (
    register_architecture_map_permissions,
)
from app.modules.architecture_map.router import router

PREFIX = "/api/v1/architecture-map"

# A manifest in the shape the generator really emits, small enough to assert
# against exhaustively. Three modules, five dependency edges, two categories.
#
#   billing  -> projects, users
#   projects -> users
#   users    -> (nothing)
#
# Three edges. Degrees, counting both directions, are 2 apiece: billing is
# the source of two, projects is the source of one and the target of one,
# users is the target of two and the source of none.
FIXTURE_MANIFEST: dict[str, Any] = {
    "_meta": {
        "generator": "generate_architecture_manifest.py",
        "description": "Auto-generated architecture manifest for OpenConstructionERP",
        "version": "1.0.0",
    },
    "modules": [
        {
            "module_id": "billing",
            "module_label": "Billing",
            "module_category": "business",
            "files": ["__init__.py", "router.py"],
            "manifest": {"name": "oe_billing", "description": "Issues invoices and tracks payment."},
            "models": [],
            "routes": [],
            "schemas": [],
            "import_dependencies": ["projects", "users"],
        },
        {
            "module_id": "projects",
            "module_label": "Projects",
            "module_category": "core",
            "files": ["__init__.py"],
            "manifest": {"name": "oe_projects", "description": "The project register."},
            "models": [],
            "routes": [],
            "schemas": [],
            "import_dependencies": ["users"],
        },
        {
            "module_id": "users",
            "module_label": "Users",
            "module_category": "core",
            "files": ["__init__.py"],
            "manifest": {"name": "oe_users", "description": "Accounts and roles."},
            "models": [],
            "routes": [],
            "schemas": [],
            "import_dependencies": [],
        },
    ],
    "frontend_features": [{"name": "billing", "total_files": 4}],
    "dependency_graph": {
        "billing": ["projects", "users"],
        "projects": ["users"],
        "users": [],
    },
    "frontend_backend_mapping": {"billing": "billing"},
    "statistics": {"backend_modules": 3, "total_models": 0, "frontend_features": 1},
}


@pytest.fixture
def fresh_registry(monkeypatch):
    """Swap the global registry for a clean instance for this test only.

    The router resolves permissions via ``permission_registry`` at request
    time (through the live-registry fallback in ``RequirePermission``),
    so we have to patch the module attribute that ``dependencies.py``
    imports, not just create a local instance.
    """
    clean = PermissionRegistry()
    monkeypatch.setattr("app.core.permissions.permission_registry", clean)
    monkeypatch.setattr(
        "app.modules.architecture_map.permissions.permission_registry",
        clean,
    )
    return clean


@pytest.fixture
def app(fresh_registry) -> FastAPI:
    """Mount the architecture_map router in a minimal app."""
    register_architecture_map_permissions()
    # Sanity check. The registry actually got the gate we expect.
    assert fresh_registry.get_min_role("architecture.read") == Role.ADMIN

    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    return app


@pytest.fixture
def fixture_manifest(tmp_path: Path, monkeypatch):
    """Point the router at FIXTURE_MANIFEST instead of the shipped file.

    The router caches the parsed manifest in a module global, so the cache
    has to be dropped on the way in and on the way out. Without the second
    invalidation a later test reading the real file would be served this
    fixture instead.
    """
    path = tmp_path / "architecture_manifest.json"
    path.write_text(json.dumps(FIXTURE_MANIFEST), encoding="utf-8")
    monkeypatch.setattr(router_module, "_MANIFEST_PATH", path)
    router_module.invalidate_cache()
    yield path
    router_module.invalidate_cache()


@pytest.fixture
def real_manifest(monkeypatch):
    """Serve the manifest the repository actually ships.

    Skips rather than fails when the file is absent, so a sparse checkout
    does not turn into a red suite. The file is generated, so its contents
    move; these tests pin structure and population, never a byte count.
    """
    path = router_module._MANIFEST_PATH
    if not path.exists():
        pytest.skip(f"shipped manifest not present at {path}")
    router_module.invalidate_cache()
    yield path
    router_module.invalidate_cache()


def _set_role(app: FastAPI, role: str, permissions: list[str] | None = None) -> None:
    """Override the auth dependency to act as a user with ``role``."""

    async def _payload() -> dict[str, object]:
        return {
            "sub": "00000000-0000-0000-0000-000000000001",
            "role": role,
            "permissions": permissions or [],
        }

    app.dependency_overrides[get_current_user_payload] = _payload


def _admin(app: FastAPI) -> TestClient:
    """Return a client acting as an admin."""
    _set_role(app, role="admin")
    return TestClient(app)


# ── Negative path: non-admin is rejected ─────────────────────────────────


class TestNonAdminRejected:
    def test_viewer_gets_403_on_root(self, app):
        _set_role(app, role="viewer")
        resp = TestClient(app).get(f"{PREFIX}/")
        assert resp.status_code == 403
        assert "architecture.read" in resp.json()["detail"]

    def test_editor_gets_403_on_modules(self, app):
        _set_role(app, role="editor")
        assert TestClient(app).get(f"{PREFIX}/modules/").status_code == 403

    def test_manager_gets_403_on_stats(self, app):
        """Manager is one rung below admin, and must still be blocked."""
        _set_role(app, role="manager")
        assert TestClient(app).get(f"{PREFIX}/stats/").status_code == 403

    def test_viewer_gets_403_on_search(self, app):
        _set_role(app, role="viewer")
        assert TestClient(app).get(f"{PREFIX}/search/?q=projects").status_code == 403

    def test_viewer_gets_403_on_connections(self, app):
        _set_role(app, role="viewer")
        assert TestClient(app).get(f"{PREFIX}/connections/").status_code == 403


# ── GET /modules ─────────────────────────────────────────────────────────


class TestListModules:
    def test_returns_every_module_with_its_id(self, app, fixture_manifest):
        # Population, then content. "is a list" was the old assertion and it
        # passed against a router that could not read the file at all.
        body = _admin(app).get(f"{PREFIX}/modules/").json()
        assert len(body) == 3, f"expected 3 modules, got {len(body)}"
        assert [m["module_id"] for m in body] == ["billing", "projects", "users"]

    def test_connection_count_is_the_degree_in_both_directions(self, app, fixture_manifest):
        # This is the assertion the old test could not make: connection_count
        # was 0 for every module because it counted a key that did not exist.
        body = _admin(app).get(f"{PREFIX}/modules/").json()
        counts = {m["module_id"]: m["connection_count"] for m in body}
        assert counts == {"billing": 2, "projects": 2, "users": 2}

    def test_category_filter_keeps_the_matching_modules(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/modules/?category=core").json()
        assert [m["module_id"] for m in body] == ["projects", "users"]

    def test_category_filter_is_case_insensitive(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/modules/?category=CORE").json()
        assert [m["module_id"] for m in body] == ["projects", "users"]

    def test_category_filter_excludes_the_others(self, app, fixture_manifest):
        # Paired with the test above. A filter that returns everything would
        # satisfy "keeps the matching modules" but not this.
        body = _admin(app).get(f"{PREFIX}/modules/?category=business").json()
        assert [m["module_id"] for m in body] == ["billing"]

    def test_unknown_category_returns_empty(self, app, fixture_manifest):
        # A true negative. Empty here is the correct answer, which is exactly
        # why empty cannot be trusted as a pass anywhere else in this file.
        assert _admin(app).get(f"{PREFIX}/modules/?category=nonexistent").json() == []


# ── GET /modules/{module_id} ─────────────────────────────────────────────


class TestModuleDetail:
    def test_module_is_found_by_module_id_not_id(self, app, fixture_manifest):
        """The regression test for the original defect.

        The lookup used to match on ``m.get("id")``. No module carries
        ``id``, so this request returned 404 for every module in the
        manifest. If the key ever moves back, this goes red.
        """
        resp = _admin(app).get(f"{PREFIX}/modules/projects")
        assert resp.status_code == 200, f"lookup by module_id failed: {resp.status_code} {resp.text}"
        assert resp.json()["module_id"] == "projects"
        assert resp.json()["module_label"] == "Projects"

    def test_detail_carries_inbound_and_outbound_edges(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/modules/projects").json()
        assert body["connections_outbound"] == [{"source": "projects", "target": "users", "type": "import"}]
        assert body["connections_inbound"] == [{"source": "billing", "target": "projects", "type": "import"}]

    def test_a_leaf_module_has_no_outbound_edges(self, app, fixture_manifest):
        # The other direction of the pair above: a module that genuinely has
        # no outbound edges must report none, and still report its inbound.
        body = _admin(app).get(f"{PREFIX}/modules/users").json()
        assert body["connections_outbound"] == []
        assert [c["source"] for c in body["connections_inbound"]] == ["billing", "projects"]

    def test_unknown_module_is_404(self, app, fixture_manifest):
        resp = _admin(app).get(f"{PREFIX}/modules/does-not-exist")
        assert resp.status_code == 404
        assert "does-not-exist" in resp.json()["detail"]


# ── GET /connections ─────────────────────────────────────────────────────


class TestConnections:
    def test_all_edges_are_derived_from_the_dependency_graph(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/connections/").json()
        assert body == [
            {"source": "billing", "target": "projects", "type": "import"},
            {"source": "billing", "target": "users", "type": "import"},
            {"source": "projects", "target": "users", "type": "import"},
        ]

    def test_source_filter(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/connections/?source=billing").json()
        assert [c["target"] for c in body] == ["projects", "users"]

    def test_target_filter(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/connections/?target=users").json()
        assert [c["source"] for c in body] == ["billing", "projects"]

    def test_the_only_edge_type_matches_and_others_do_not(self, app, fixture_manifest):
        # Both directions in one place. Filtering on the type the manifest
        # records returns everything; filtering on a type it does not record
        # returns nothing, which is the truthful answer rather than a stub.
        assert len(_admin(app).get(f"{PREFIX}/connections/?type=import").json()) == 3
        assert _admin(app).get(f"{PREFIX}/connections/?type=api").json() == []


# ── GET /search ──────────────────────────────────────────────────────────


class TestSearch:
    def test_search_requires_a_query(self, app, fixture_manifest):
        assert _admin(app).get(f"{PREFIX}/search/").status_code == 422

    def test_matches_a_module_by_id(self, app, fixture_manifest):
        # Only the projects module itself matches. billing depends on
        # projects, but a dependency is not part of a module's searchable
        # text, and the edges it produces are reported under "connections"
        # below rather than folded into the module hits.
        body = _admin(app).get(f"{PREFIX}/search/?q=projects").json()
        assert [m["module_id"] for m in body["modules"]] == ["projects"]
        assert body["query"] == "projects"
        assert [(c["source"], c["target"]) for c in body["connections"]] == [
            ("billing", "projects"),
            ("projects", "users"),
        ]

    def test_matches_several_modules_by_category(self, app, fixture_manifest):
        # The paired direction of the test above: a query that should hit
        # more than one module does.
        body = _admin(app).get(f"{PREFIX}/search/?q=core").json()
        assert [m["module_id"] for m in body["modules"]] == ["projects", "users"]

    def test_matches_a_module_by_its_plugin_description(self, app, fixture_manifest):
        # "invoices" appears only in billing's manifest description. This
        # pins that the description is read from manifest.description, where
        # the generator puts it, and not from a top-level description key.
        body = _admin(app).get(f"{PREFIX}/search/?q=invoices").json()
        assert [m["module_id"] for m in body["modules"]] == ["billing"]

    def test_matches_a_category(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/search/?q=business").json()
        assert body["categories"] == [{"id": "business", "module_count": 1}]

    def test_a_query_that_matches_nothing_totals_zero(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/search/?q=zzzznotathing").json()
        assert body["total"] == 0
        assert body["modules"] == []
        assert body["connections"] == []
        assert body["categories"] == []

    def test_total_is_the_sum_of_the_groups(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/search/?q=users").json()
        assert body["total"] == len(body["modules"]) + len(body["connections"]) + len(body["categories"])
        assert body["total"] > 0, "expected 'users' to match something"

    def test_there_is_no_layers_group(self, app, fixture_manifest):
        # The manifest has no layers. The endpoint used to return
        # "layers": [] on every call, which reads as "no matches" rather
        # than "this question has no source", and that is how the defect
        # stayed invisible.
        assert "layers" not in _admin(app).get(f"{PREFIX}/search/?q=users").json()


# ── GET /stats ───────────────────────────────────────────────────────────


class TestStats:
    def test_totals_are_the_real_populations(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["total_modules"] == 3
        assert body["total_connections"] == 3
        assert body["total_categories"] == 2

    def test_modules_by_category(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["modules_by_category"] == {"business": 1, "core": 2}

    def test_connections_by_type(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["connections_by_type"] == {"import": 3}

    def test_most_connected_is_ordered_by_degree_then_id(self, app, fixture_manifest):
        # Every module in the fixture has degree 2, so this pins the
        # tie-break rather than the ordering by degree. That is the part
        # that would otherwise vary between processes.
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["most_connected"] == [
            {"module_id": "billing", "connection_count": 2},
            {"module_id": "projects", "connection_count": 2},
            {"module_id": "users", "connection_count": 2},
        ]

    def test_most_connected_puts_a_busier_module_first(self, app, tmp_path, monkeypatch):
        # The degree ordering itself, on a graph where the degrees differ.
        # Without this, the tie-break test above would be the only witness
        # and a sort by id alone would pass it.
        busy = json.loads(json.dumps(FIXTURE_MANIFEST))
        busy["dependency_graph"] = {"billing": ["users"], "projects": ["users"], "users": []}
        path = tmp_path / "busy.json"
        path.write_text(json.dumps(busy), encoding="utf-8")
        monkeypatch.setattr(router_module, "_MANIFEST_PATH", path)
        router_module.invalidate_cache()
        try:
            body = _admin(app).get(f"{PREFIX}/stats/").json()
            assert body["most_connected"] == [
                {"module_id": "users", "connection_count": 2},
                {"module_id": "billing", "connection_count": 1},
                {"module_id": "projects", "connection_count": 1},
            ]
        finally:
            router_module.invalidate_cache()

    def test_the_generators_own_statistics_are_passed_through(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["manifest_statistics"] == {
            "backend_modules": 3,
            "total_models": 0,
            "frontend_features": 1,
        }

    def test_the_layer_counters_are_gone(self, app, fixture_manifest):
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert "modules_by_layer" not in body
        assert "total_layers" not in body


# ── Behaviour when the manifest is missing or unreadable ─────────────────


class TestMissingManifest:
    def test_absent_file_yields_the_real_empty_shape(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(router_module, "_MANIFEST_PATH", tmp_path / "nope.json")
        router_module.invalidate_cache()
        try:
            body = _admin(app).get(f"{PREFIX}/").json()
            # The fallback must advertise the keys the generator emits, not
            # the phantom ones it used to carry.
            assert sorted(body) == [
                "_meta",
                "dependency_graph",
                "frontend_backend_mapping",
                "frontend_features",
                "modules",
                "statistics",
            ]
            assert body["modules"] == []
        finally:
            router_module.invalidate_cache()

    def test_endpoints_stay_up_with_no_manifest(self, app, tmp_path, monkeypatch):
        monkeypatch.setattr(router_module, "_MANIFEST_PATH", tmp_path / "nope.json")
        router_module.invalidate_cache()
        try:
            client = _admin(app)
            assert client.get(f"{PREFIX}/modules/").json() == []
            assert client.get(f"{PREFIX}/connections/").json() == []
            assert client.get(f"{PREFIX}/stats/").json()["total_modules"] == 0
            assert client.get(f"{PREFIX}/modules/anything").status_code == 404
        finally:
            router_module.invalidate_cache()


# ── Against the manifest the repository actually ships ───────────────────


class TestTheShippedManifest:
    """Real populations, so the fixture above cannot be the only witness.

    Nothing here pins a count, because the manifest is generated and its
    numbers move with the tree. Freshness is a separate gate's job, in
    ``scripts/check_architecture_manifest.py``. These pin that the
    endpoints can read the real file at all, which is precisely what was
    broken.
    """

    def test_modules_endpoint_returns_the_whole_population(self, app, real_manifest):
        client = _admin(app)
        served = client.get(f"{PREFIX}/modules/").json()
        on_disk = json.loads(real_manifest.read_text(encoding="utf-8"))["modules"]
        assert len(served) == len(on_disk) > 100, f"served {len(served)} of {len(on_disk)} modules"

    def test_every_served_module_resolves_by_its_own_id(self, app, real_manifest):
        # The 404-for-everything defect, measured against the real file.
        # Sampling the ends and the middle keeps this quick while still
        # crossing the whole list.
        client = _admin(app)
        served = client.get(f"{PREFIX}/modules/").json()
        sample = [served[0], served[len(served) // 2], served[-1]]
        for mod in sample:
            mid = mod["module_id"]
            resp = client.get(f"{PREFIX}/modules/{mid}")
            assert resp.status_code == 200, f"module {mid!r} exists in the list but 404s on detail"
            assert resp.json()["module_id"] == mid

    def test_the_real_graph_produces_edges(self, app, real_manifest):
        client = _admin(app)
        edges = client.get(f"{PREFIX}/connections/").json()
        graph = json.loads(real_manifest.read_text(encoding="utf-8"))["dependency_graph"]
        expected = sum(len(v) for v in graph.values())
        assert len(edges) == expected > 0, f"served {len(edges)} edges, graph holds {expected}"

    def test_search_finds_a_module_that_exists(self, app, real_manifest):
        client = _admin(app)
        first = client.get(f"{PREFIX}/modules/").json()[0]["module_id"]
        body = client.get(f"{PREFIX}/search/?q={first}").json()
        assert first in [m["module_id"] for m in body["modules"]]

    def test_stats_agree_with_the_manifests_own_statistics(self, app, real_manifest):
        # Two independent counts of the same thing: ours, walking the
        # modules list, and the generator's, recorded when it scanned the
        # tree. They are computed from the same file, so disagreement means
        # the endpoint is reading the wrong section.
        body = _admin(app).get(f"{PREFIX}/stats/").json()
        assert body["total_modules"] == body["manifest_statistics"]["backend_modules"]

    def test_the_manifest_has_no_layer_anywhere(self, app, real_manifest):
        """Guards the decision to delete the layer concept.

        The layer filter and counters were removed because nothing in the
        manifest supplies a layer. If the generator ever starts emitting
        one, this goes red and whoever added it is pointed at the
        endpoints that would need to come back.
        """
        data = json.loads(real_manifest.read_text(encoding="utf-8"))
        assert "layers" not in data
        carrying = [m["module_id"] for m in data["modules"] if "layer" in m]
        assert not carrying, f"{len(carrying)} module(s) now carry a layer, for example {carrying[:3]}"


# ── Surface pinning ──────────────────────────────────────────────────────


def test_router_exposes_only_documented_endpoints():
    """Pin the registered route set so a new route cannot sneak through
    without an explicit code review touching this test."""
    paths = sorted({route.path for route in router.routes})
    assert paths == sorted(
        [
            "/",
            "/modules/",
            "/modules/{module_id}",
            "/connections/",
            "/search/",
            "/stats/",
        ]
    ), f"unexpected router surface: {paths}"


def test_permissions_registered_at_admin_role():
    """The permission ``architecture.read`` must exist and require ADMIN.

    Done against the live registry rather than a clean one so a
    misconfigured production deploy, for example a startup hook that
    never ran, is caught. Calling the registration again also pins that
    it is idempotent.
    """
    register_architecture_map_permissions()
    assert permission_registry.get_min_role("architecture.read") == Role.ADMIN, (
        "architecture.read must require Role.ADMIN"
    )
