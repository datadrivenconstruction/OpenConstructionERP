"""Integration tests for paginated cost search + category tree.

Covers (end-to-end through the FastAPI router):
    - Cursor flow: page 1 → next_cursor → page 2 → next_cursor=None at end.
    - ``total`` is populated on the first page only.
    - ``has_more`` flips correctly at the boundary.
    - ``classification_path`` prefix filter at multiple depths.
    - Region filter changes the result set.
    - Garbage cursor → 400 Bad Request.
    - Category tree endpoint returns the nested 4-level structure with
      the ``__unspecified__`` sentinel for missing intermediate levels.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-search-api-"))
_TMP_DB = _TMP_DIR / "search_api.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and seed the catalog."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, async_session_factory, engine
        from app.modules.costs import models as _costs_models  # noqa: F401
        from app.modules.costs.models import CostItem

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed ~20 rows across two regions with a 4-level classification
        # tree. Codes are A001…A015 (DE_BERLIN) and B001…B005 (GB_LONDON).
        async with async_session_factory() as s:
            rows: list[CostItem] = []

            def _row(
                code: str,
                *,
                col: str | None,
                dept: str | None,
                sec: str | None,
                sub: str | None,
                region: str,
            ) -> CostItem:
                cls: dict[str, str] = {}
                if col is not None:
                    cls["collection"] = col
                if dept is not None:
                    cls["department"] = dept
                if sec is not None:
                    cls["section"] = sec
                if sub is not None:
                    cls["subsection"] = sub
                return CostItem(
                    id=uuid.uuid4(),
                    code=code,
                    description=f"desc {code}",
                    unit="m2",
                    rate="123.45",
                    currency="EUR",
                    source="cwicr",
                    classification=cls,
                    components=[],
                    tags=[],
                    region=region,
                    is_active=True,
                    metadata_={},
                )

            # DE_BERLIN — 15 rows.
            de_seeds = [
                ("A001", "Buildings", "Concrete", "Walls", "Reinforced"),
                ("A002", "Buildings", "Concrete", "Walls", "Plain"),
                ("A003", "Buildings", "Concrete", "Floors", "Slab"),
                ("A004", "Buildings", "Masonry", "Walls", "Brick"),
                ("A005", "Buildings", "Masonry", "Walls", "Block"),
                ("A006", "Roads", "Asphalt", "Surface", "Hot"),
                ("A007", "Roads", "Asphalt", "Surface", "Cold"),
                ("A008", "Roads", "Asphalt", "Subbase", "Crushed"),
                ("A009", "Roads", "Concrete", "Surface", "CRCP"),
                ("A010", "Buildings", "Concrete", "Walls", "Reinforced"),
                ("A011", "Buildings", "Concrete", "Walls", "Reinforced"),
                ("A012", "Buildings", "Concrete", "Walls", "Reinforced"),
                ("A013", "Buildings", "Concrete", "Walls", "Reinforced"),
                # NULL intermediate level — must coalesce in tree.
                ("A014", "Buildings", None, "Walls", "Reinforced"),
                ("A015", "Buildings", "Concrete", None, "Plain"),
            ]
            for code, col, dept, sec, sub in de_seeds:
                rows.append(_row(code, col=col, dept=dept, sec=sec, sub=sub, region="DE_BERLIN"))

            # GB_LONDON — 5 rows.
            gb_seeds = [
                ("B001", "Buildings", "Concrete", "Walls", "Reinforced"),
                ("B002", "Buildings", "Concrete", "Floors", "Slab"),
                ("B003", "Roads", "Asphalt", "Surface", "Hot"),
                ("B004", "Roads", "Asphalt", "Surface", "Cold"),
                ("B005", "Buildings", "Masonry", "Walls", "Brick"),
            ]
            for code, col, dept, sec, sub in gb_seeds:
                rows.append(_row(code, col=col, dept=dept, sec=sec, sub=sub, region="GB_LONDON"))

            s.add_all(rows)
            await s.commit()

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client):
    """Register + promote-to-admin + log in a test user, return auth headers.

    The ``GET /api/v1/costs/`` endpoint requires authentication (asserted
    by ``tests/integration/test_api_smoke.py::test_cost_search_requires_auth``)
    even though reads are public-by-design — the auth check is a JWT
    presence check, not a per-row permission. We mint a single token
    and reuse it across the module.
    """
    import uuid

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"costs-search-{unique}@test.io"
    password = f"CostsTest{unique}9!"

    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Costs Search"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    async with async_session_factory() as s:
        await s.execute(
            sa_update(User)
            .where(User.email == email.lower())
            .values(role="admin", is_active=True)
        )
        await s.commit()

    login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Cursor flow ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_page_returns_total_and_next_cursor(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/", params={"limit": 5}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["limit"] == 5
    assert body["total"] == 20  # 15 DE + 5 GB
    assert body["has_more"] is True
    assert body["next_cursor"] is not None
    assert isinstance(body["next_cursor"], str)
    assert len(body["items"]) == 5


@pytest.mark.asyncio
async def test_cursor_pagination_walks_all_rows(http_client, auth_headers):
    """Walk page-by-page and confirm every row appears exactly once."""
    seen_codes: list[str] = []
    cursor: str | None = None

    while True:
        params: dict[str, object] = {"limit": 7}
        if cursor:
            params["cursor"] = cursor

        resp = await http_client.get(
            "/api/v1/costs/", params=params, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        if cursor is None:
            assert body["total"] == 20
        else:
            assert body["total"] is None, "subsequent pages must omit total"

        for item in body["items"]:
            assert item["code"] not in seen_codes
            seen_codes.append(item["code"])

        if not body["has_more"]:
            assert body["next_cursor"] is None
            break

        assert body["next_cursor"] is not None
        cursor = body["next_cursor"]

    assert len(seen_codes) == 20
    # Order must be ascending by code.
    assert seen_codes == sorted(seen_codes)


@pytest.mark.asyncio
async def test_garbage_cursor_returns_400(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/",
        params={"cursor": "not-a-real-cursor!!!"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "cursor" in body.get("detail", "").lower()


# ── classification_path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classification_path_prefix_filter(http_client, auth_headers):
    """Filter by full path returns the expected branch."""
    resp = await http_client.get(
        "/api/v1/costs/",
        params={
            "classification_path": "Buildings/Concrete/Walls/Reinforced",
            "limit": 100,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # DE_BERLIN: A001, A010-A013, A014 (dept=None excluded by depth-2 filter)
    # → A001, A010, A011, A012, A013 = 5
    # GB_LONDON: B001 = 1
    # Total = 6
    assert body["total"] == 6
    codes = {it["code"] for it in body["items"]}
    assert codes == {"A001", "A010", "A011", "A012", "A013", "B001"}


@pytest.mark.asyncio
async def test_classification_path_with_region(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/",
        params={
            "classification_path": "Buildings",
            "region": "GB_LONDON",
            "limit": 100,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # GB_LONDON Buildings: B001, B002, B005 = 3
    assert body["total"] == 3
    codes = {it["code"] for it in body["items"]}
    assert codes == {"B001", "B002", "B005"}


@pytest.mark.asyncio
async def test_region_filter_changes_results(http_client, auth_headers):
    de = (
        await http_client.get(
            "/api/v1/costs/",
            params={"region": "DE_BERLIN", "limit": 100},
            headers=auth_headers,
        )
    ).json()
    gb = (
        await http_client.get(
            "/api/v1/costs/",
            params={"region": "GB_LONDON", "limit": 100},
            headers=auth_headers,
        )
    ).json()
    assert de["total"] == 15
    assert gb["total"] == 5
    assert {it["code"] for it in de["items"]}.isdisjoint(
        {it["code"] for it in gb["items"]}
    )


# ── Category tree ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_category_tree_returns_nested_structure(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/category-tree/",
        params={"region": "DE_BERLIN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    tree = resp.json()

    names = {n["name"] for n in tree}
    assert "Buildings" in names
    assert "Roads" in names

    buildings = next(n for n in tree if n["name"] == "Buildings")
    # DE_BERLIN Buildings: A001-A005, A010-A015 = 11 rows.
    assert buildings["count"] == 11
    assert isinstance(buildings["children"], list)
    assert all("name" in c and "count" in c and "children" in c for c in buildings["children"])


@pytest.mark.asyncio
async def test_category_tree_has_unspecified_sentinel(http_client, auth_headers):
    """A row with department=NULL must surface the ``__unspecified__`` node."""
    resp = await http_client.get(
        "/api/v1/costs/category-tree/",
        params={"region": "DE_BERLIN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    tree = resp.json()
    buildings = next(n for n in tree if n["name"] == "Buildings")
    dept_names = {n["name"] for n in buildings["children"]}
    assert "__unspecified__" in dept_names


@pytest.mark.asyncio
async def test_category_tree_count_rollup(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/category-tree/",
        params={"region": "DE_BERLIN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    tree = resp.json()

    def _walk(n: dict) -> None:
        if n["children"]:
            assert n["count"] == sum(c["count"] for c in n["children"])
            for c in n["children"]:
                _walk(c)

    for root in tree:
        _walk(root)


@pytest.mark.asyncio
async def test_category_tree_no_region_aggregates_all(http_client, auth_headers):
    resp = await http_client.get(
        "/api/v1/costs/category-tree/", headers=auth_headers
    )
    assert resp.status_code == 200
    tree = resp.json()
    total_rows = sum(n["count"] for n in tree)
    # All 20 seeded rows.
    assert total_rows == 20
