"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PostgreSQL dialect-correctness tests (embedded PG, no Docker).

These guard the SQLite -> PostgreSQL divergences that the default in-memory
SQLite suite cannot see. They would have caught the ``ARRAY(JSON)`` -> ``jsonb[]``
DDL breaker that previously failed CREATE TABLE on PG while SQLite accepted it.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_full_schema_builds_on_postgres(pg_session) -> None:
    """The entire ORM schema builds on real PG, with JSONB columns and GIN indexes.

    A green run proves: no ``jsonb[]``/dialect DDL breakers, the JSON->JSONB
    ``@compiles`` hook fired, and the ``after_create`` GIN-index events ran.
    """
    tables = (
        await pg_session.execute(
            text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        )
    ).scalar_one()
    jsonb_cols = (
        await pg_session.execute(
            text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND data_type='jsonb'")
        )
    ).scalar_one()
    gin_idx = (
        await pg_session.execute(
            text("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexdef ILIKE '%using gin%'")
        )
    ).scalar_one()

    # The app has 400+ tables; exact counts drift as modules are added, so we
    # assert generous floors rather than brittle equality.
    assert tables >= 400, f"expected 400+ tables on PG, got {tables}"
    assert jsonb_cols >= 100, f"expected JSON columns to compile to JSONB, got {jsonb_cols}"
    assert gin_idx >= 1, f"expected at least one GIN index on PG, got {gin_idx}"


async def test_jsonb_roundtrip_and_containment(pg_session) -> None:
    """A dict survives a JSONB write/read, and the ``@>`` containment operator works.

    ``@>`` is the PostgreSQL containment operator that the GIN-indexed JSONB
    queries rely on; it does not exist on SQLite.
    """
    await pg_session.execute(text("CREATE TEMP TABLE _t_jsonb (id uuid PRIMARY KEY, data jsonb) ON COMMIT DROP"))
    payload = {"din276": "330", "tags": ["a", "b"], "nested": {"x": 1}}
    row_id = uuid.uuid4()
    await pg_session.execute(
        text("INSERT INTO _t_jsonb (id, data) VALUES (CAST(:id AS uuid), CAST(:data AS jsonb))"),
        {"id": str(row_id), "data": json.dumps(payload)},
    )

    got = (
        await pg_session.execute(text("SELECT data FROM _t_jsonb WHERE id = CAST(:id AS uuid)"), {"id": str(row_id)})
    ).scalar_one()
    # asyncpg may hand back jsonb as a str or already-parsed dict depending on codecs.
    got_dict = json.loads(got) if isinstance(got, str) else got
    assert got_dict == payload

    contained = (
        await pg_session.execute(
            text("SELECT count(*) FROM _t_jsonb WHERE data @> CAST(:q AS jsonb)"),
            {"q": json.dumps({"din276": "330"})},
        )
    ).scalar_one()
    assert contained == 1

    not_contained = (
        await pg_session.execute(
            text("SELECT count(*) FROM _t_jsonb WHERE data @> CAST(:q AS jsonb)"),
            {"q": json.dumps({"din276": "999"})},
        )
    ).scalar_one()
    assert not_contained == 0


async def test_ilike_is_case_insensitive_unlike_like(pg_session) -> None:
    """ILIKE matches case-insensitively where PostgreSQL LIKE does not.

    The Phase-2 search fixes rewrite ``.like`` -> ``.ilike`` precisely because
    PostgreSQL ``LIKE`` is case-sensitive (SQLite ``LIKE`` is not), so a
    SQLite-passing search silently returns nothing on PG. This pins both halves.
    """
    await pg_session.execute(text("CREATE TEMP TABLE _t_search (id uuid PRIMARY KEY, name text) ON COMMIT DROP"))
    await pg_session.execute(
        text("INSERT INTO _t_search (id, name) VALUES (CAST(:id AS uuid), :name)"),
        {"id": str(uuid.uuid4()), "name": "Stahlbeton C30/37"},
    )

    ilike_hits = (
        await pg_session.execute(text("SELECT count(*) FROM _t_search WHERE name ILIKE :q"), {"q": "stahlbeton%"})
    ).scalar_one()
    like_hits = (
        await pg_session.execute(text("SELECT count(*) FROM _t_search WHERE name LIKE :q"), {"q": "stahlbeton%"})
    ).scalar_one()

    assert ilike_hits == 1, "ILIKE must match case-insensitively on PostgreSQL"
    assert like_hits == 0, "PostgreSQL LIKE is case-sensitive — this is why .ilike matters"


async def test_uuid_primary_key_roundtrip(pg_session) -> None:
    """A native ``uuid`` column round-trips a Python ``uuid.UUID`` via asyncpg."""
    await pg_session.execute(text("CREATE TEMP TABLE _t_uuid (id uuid PRIMARY KEY) ON COMMIT DROP"))
    rid = uuid.uuid4()
    await pg_session.execute(text("INSERT INTO _t_uuid (id) VALUES (CAST(:id AS uuid))"), {"id": str(rid)})
    got = (await pg_session.execute(text("SELECT id FROM _t_uuid"))).scalar_one()
    assert uuid.UUID(str(got)) == rid


async def test_gin_indexes_use_jsonb_path_ops(pg_session) -> None:
    """Every JSONB GIN index declares the ``jsonb_path_ops`` opclass.

    ``jsonb_path_ops`` is smaller and faster than the default ``jsonb_ops`` for
    the ``@>`` containment queries the app runs on these columns. The only GIN
    indexes in the schema are the ones ``pg_optimizations`` builds on the
    path-queried JSON columns, so all of them must carry the opclass.
    """
    rows = (
        await pg_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND indexdef ILIKE '%USING gin%'"
            )
        )
    ).all()
    assert rows, "expected at least one GIN index on PostgreSQL"
    missing = [name for name, ddl in rows if "jsonb_path_ops" not in ddl]
    assert not missing, f"GIN indexes missing the jsonb_path_ops opclass: {missing}"
