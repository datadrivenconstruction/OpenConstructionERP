# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Five endpoints a stranger could call, and what each of them gave away.

A per-route pass over the live router tree found four routes with no gate of
any kind plus one install route gated on authentication alone. They are not
one defect: two disclosed an absolute server path, one spawned a process for a
caller who had not logged in, one wrote a service binary to the host, and one
was a capability URL by accident. Each is pinned here.

The two disclosure tests assert the server directory string is ABSENT from the
serialised body rather than asserting the shape of what remains. A projection
that kept the value under a different key would pass a key-absence test and
still leak, and a projection that dropped a field the UI needs would pass a
shape test and still break the page - so both properties are checked.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute


def _all_strings(obj: object) -> list[str]:
    """Every string anywhere in a response body, keys included.

    Not ``json.dumps`` + ``in``. A Windows ``Path`` renders with backslashes
    and ``json.dumps`` escapes each one, so a substring test against the
    original path silently matches nothing and the assertion passes while the
    leak is still there. That is not hypothetical - this test was written that
    way first, and the falsification run that put the leak back caught it.
    """
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for key, value in obj.items():
            out.append(str(key))
            out.extend(_all_strings(value))
        return out
    if isinstance(obj, (list, tuple)):
        return [s for item in obj for s in _all_strings(item)]
    return []


def _permissions_on(router: object, path: str, method: str) -> set[str | None]:
    """The permission keys FastAPI flattened onto one route's dependant."""
    route = next(
        r
        for r in router.routes  # type: ignore[attr-defined]
        if isinstance(r, APIRoute) and r.path == path and method in r.methods
    )
    return {getattr(dep.call, "permission", None) for dep in route.dependant.dependencies}


# ── 1. costs /vector/status/ - absolute path to an anonymous caller ──────────


class TestVectorStatusPathDisclosure:
    """``vector_status()`` was returned verbatim. On the LanceDB backend that
    dict carries ``path``: the absolute directory the embedded database lives
    in (``app/core/vector.py:416``). ``/api/system/status`` already projected
    the same call down to engine plus count; this door did not."""

    SECRET_DIR = "/srv/openestimator/var/lib/vectors"

    @pytest.fixture
    def _stub_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.vector as vector_mod

        monkeypatch.setattr(
            vector_mod,
            "vector_status",
            lambda: {
                "connected": True,
                "engine": "lancedb",
                "path": self.SECRET_DIR,
                "tables": 4,
                "cost_collection": {"vectors_count": 55719, "points_count": 55719, "status": "ready"},
                "collections": {},
                "can_restore_snapshots": False,
                "can_generate_locally": True,
                "backend": "lancedb",
            },
        )

    @pytest.mark.asyncio
    async def test_the_server_path_is_absent_from_the_body(self, _stub_status: None) -> None:
        from app.modules.costs.router import get_vector_status

        body = await get_vector_status()
        leaked = [s for s in _all_strings(body) if self.SECRET_DIR in s]
        assert not leaked, f"the vector directory reached an anonymous caller: {leaked}"

    @pytest.mark.asyncio
    async def test_the_fields_the_ui_reads_survive(self, _stub_status: None) -> None:
        """ImportDatabasePage, ModulesPage and BOQEditorPage read these. The
        projection is an allowlist, so dropping one of them is as much a
        regression as leaking the path."""
        from app.modules.costs.router import get_vector_status

        body = await get_vector_status()
        for key in (
            "connected",
            "engine",
            "cost_collection",
            "backend",
            "can_restore_snapshots",
            "can_generate_locally",
        ):
            assert key in body, f"projection dropped {key}, which the UI reads"
        assert body["cost_collection"]["vectors_count"] == 55719


# ── 2. costs /qdrant-search/ - parquet paths, and anonymous embedding ────────


class TestQdrantSmokeSearch:
    """The diag block returned ``parquet_root`` and ``parquet_file`` as
    absolute paths. Separately, every call ran a BGE-M3 embedding and a hybrid
    search at a caller-chosen limit of up to 500, for a caller who had not
    logged in."""

    # A marker rather than a realistic path: the separator style differs
    # between platforms, so the assertion has to key on something that
    # survives both renderings.
    MARKER = "OE_PARQUET_ROOT_MARKER"
    SECRET_ROOT = Path("/srv") / MARKER / "parquet"

    @pytest.fixture
    def _stub_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules.costs.parquet_lookup as parquet_mod
        import app.modules.costs.qdrant_adapter as adapter_mod

        hit = SimpleNamespace(rate_code="DE.01.001", country="DE", score=0.91, payload={"t": "x"})

        async def _search(**_kwargs: object) -> list[SimpleNamespace]:
            return [hit]

        async def _lookup_full_rows(**_kwargs: object) -> list[dict[str, object]]:
            return [{"rate_code": "DE.01.001", "unit": "m3"}]

        monkeypatch.setattr(adapter_mod, "search", _search)
        monkeypatch.setattr(adapter_mod, "lookup_full_rows", _lookup_full_rows)
        monkeypatch.setattr(adapter_mod, "country_to_collection", lambda _c: "cwicr_de")
        monkeypatch.setattr(parquet_mod, "parquet_root", lambda: self.SECRET_ROOT)
        monkeypatch.setattr(
            parquet_mod,
            "parquet_path_for_country",
            lambda _c: self.SECRET_ROOT / "DE_BERLIN.parquet",
        )

    @pytest.mark.asyncio
    async def test_diagnostics_do_not_carry_the_parquet_paths(self, _stub_pipeline: None) -> None:
        from app.modules.costs.router import qdrant_smoke_search

        body = await qdrant_smoke_search(
            q="Stahlbetonwand C30/37",
            country="DE",
            limit=10,
            is_abstract=False,
            department_code=None,
            unit_dim=None,
            diag=True,
        )
        leaked = [s for s in _all_strings(body) if self.MARKER in s]
        assert not leaked, f"an absolute server path leaked: {leaked}"

    @pytest.mark.asyncio
    async def test_diagnostics_still_name_the_file_that_answered(self, _stub_pipeline: None) -> None:
        """The diagnostic is for knowing WHICH file answered. The basename says
        that; the directory it sits in was never the useful part."""
        from app.modules.costs.router import qdrant_smoke_search

        body = await qdrant_smoke_search(
            q="x",
            country="DE",
            limit=10,
            is_abstract=False,
            department_code=None,
            unit_dim=None,
            diag=True,
        )
        assert body["diagnostics"]["parquet_file"] == "DE_BERLIN.parquet"
        assert body["diagnostics"]["collection"] == "cwicr_de"

    def test_the_route_is_no_longer_anonymous(self) -> None:
        from app.modules.costs.router import router as costs_router

        perms = _permissions_on(costs_router, "/qdrant-search/", "GET")
        assert "costs.read" in perms, f"anonymous callers can still run an embedding; saw {perms}"


# ── 3. takeoff converter verify - anonymous process spawn ───────────────────


def test_converter_verify_is_gated() -> None:
    """``POST /converters/{id}/verify/`` force-runs the converter binary's
    smoke test, deliberately bypassing the 5-minute cache, for anyone who sent
    the request. Every other route in that file was already gated, including
    the install it sits next to."""
    from app.modules.takeoff.router import router as takeoff_router

    perms = _permissions_on(takeoff_router, "/converters/{converter_id}/verify/", "POST")
    assert "takeoff.read" in perms, f"verify still spawns a process for a stranger; saw {perms}"


def test_the_converter_listing_stays_open() -> None:
    """The listing only stats files. It is reachable before login on purpose,
    and gating it was never the fix."""
    from app.modules.takeoff.router import router as takeoff_router

    named = {p for p in _permissions_on(takeoff_router, "/converters/", "GET") if p}
    assert not named, f"the converter listing picked up a gate: {named}"


# ── 4. match_elements qdrant install - authenticated, not authorised ────────


def test_qdrant_install_is_gated() -> None:
    """It downloads the Qdrant binary and starts it. Its own docstring says it
    mirrors the converter-install pattern, which asks for ``takeoff.create``;
    this asked only that somebody be logged in."""
    from app.modules.match_elements.router import router as match_router

    perms = _permissions_on(match_router, "/qdrant/install", "POST")
    assert "match_elements.qdrant.install" in perms, f"install still needs only a login; saw {perms}"


def test_qdrant_install_permission_is_registered_and_refuses_non_admins() -> None:
    """A key nobody registers makes the route silently admin-only and
    undelegatable. Non-admin roles are what discriminate - admin bypasses the
    registry entirely."""
    from app.core.permissions import Role, permission_registry
    from app.modules.match_elements.permissions import register_match_elements_permissions

    register_match_elements_permissions()
    key = "match_elements.qdrant.install"
    assert permission_registry.get_min_role(key) == Role.ADMIN
    assert permission_registry.role_has_permission(Role.MANAGER, key) is False
    assert permission_registry.role_has_permission(Role.ADMIN, key) is True


def test_match_elements_registers_its_permissions_on_startup() -> None:
    """The loader auto-imports router/models/hooks but never permissions.py.
    ``on_startup`` in the package __init__ is the only thing that runs the
    registration, so a permissions.py nobody calls is the same as no gate."""
    import app.modules.match_elements as match_module

    assert callable(getattr(match_module, "on_startup", None)), (
        "match_elements/permissions.py would never run: no on_startup hook"
    )


# ── 5. admin reindex status - a capability URL by accident ──────────────────


class TestReindexStatusGate:
    """The only route in ``admin/router.py`` with no gate at all, while its two
    siblings were triple-gated by env, shared secret and hostname the whole
    time. An opaque task_id is not a permission."""

    @staticmethod
    def _request(hostname: str = "localhost") -> object:
        return SimpleNamespace(url=SimpleNamespace(hostname=hostname))

    @pytest.mark.asyncio
    async def test_refused_when_the_env_gate_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.admin.router import cost_vector_reindex_status

        monkeypatch.delenv("QA_RESET_ALLOWED", raising=False)
        with pytest.raises(HTTPException) as excinfo:
            await cost_vector_reindex_status(
                task_id="anything",
                request=self._request(),  # type: ignore[arg-type]
                confirm_token="guessed",
            )
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail["code"] == "qa_reset_disabled"

    @pytest.mark.asyncio
    async def test_refused_on_a_wrong_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.admin.router import cost_vector_reindex_status

        monkeypatch.setenv("QA_RESET_ALLOWED", "1")
        monkeypatch.setenv("QA_RESET_TOKEN", "the-real-one")
        with pytest.raises(HTTPException) as excinfo:
            await cost_vector_reindex_status(
                task_id="anything",
                request=self._request(),  # type: ignore[arg-type]
                confirm_token="not-the-real-one",
            )
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail["code"] == "qa_reset_token_mismatch"

    @pytest.mark.asyncio
    async def test_refused_on_a_production_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.admin.router import cost_vector_reindex_status

        monkeypatch.setenv("QA_RESET_ALLOWED", "1")
        monkeypatch.setenv("QA_RESET_TOKEN", "the-real-one")
        with pytest.raises(HTTPException) as excinfo:
            await cost_vector_reindex_status(
                task_id="anything",
                request=self._request(hostname="app.example.com"),  # type: ignore[arg-type]
                confirm_token="the-real-one",
            )
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail["code"] == "qa_reset_production_hostname"

    @pytest.mark.asyncio
    async def test_gates_passed_still_reaches_the_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The happy path is unchanged: an operator with the token still gets
        the same 404 for an id this process has never seen."""
        from app.modules.admin.router import cost_vector_reindex_status

        monkeypatch.setenv("QA_RESET_ALLOWED", "1")
        monkeypatch.setenv("QA_RESET_TOKEN", "the-real-one")
        with pytest.raises(HTTPException) as excinfo:
            await cost_vector_reindex_status(
                task_id="no-such-task",
                request=self._request(),  # type: ignore[arg-type]
                confirm_token="the-real-one",
            )
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail["code"] == "task_not_found"

    def test_the_token_is_required_not_optional(self) -> None:
        """A default would make the gate opt-in, which is how the siblings'
        callers would have been tempted to skip it."""
        import inspect

        from app.modules.admin.router import cost_vector_reindex_status

        # FastAPI hands the ``...`` to pydantic, which stores it as
        # PydanticUndefined - so ask the FieldInfo, not the sentinel.
        param = inspect.signature(cost_vector_reindex_status).parameters["confirm_token"]
        assert param.default.is_required(), "confirm_token became optional"
