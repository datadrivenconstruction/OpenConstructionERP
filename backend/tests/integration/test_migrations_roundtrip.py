"""Alembic up/down round-trip tests (Wave 3-D / Task #237).

Goal: catch the "missing or broken downgrade()" CI bug class — i.e. a
recent migration whose ``downgrade()`` is empty or doesn't reverse what
``upgrade()`` did. The cheapest way to surface that is to run
``upgrade -> downgrade -> upgrade`` cycles on a fresh SQLite DB.

Schema-creation reality (see ``app/main.py`` ~L1395):
  • The init revision ``129188e46db8`` is intentionally a no-op — its
    docstring says "Tables are created by SQLAlchemy at app startup".
  • The app boots by running ``Base.metadata.create_all()`` first,
    *then* ``alembic upgrade head`` (Alembic only carries column-level
    or new-table deltas after the metadata create).
  • Therefore plain ``alembic upgrade head`` on an empty DB doesn't
    work — e.g. ``v270_position_version_column`` does
    ``inspector.get_columns("oe_boq_position")`` which raises
    ``NoSuchTableError`` because that table comes from create_all,
    not from a migration. This is **expected** project behaviour, not
    a bug to fix here.

Test strategy (mirrors production):
  1. ``Base.metadata.create_all()`` to lay down the schema.
  2. ``alembic stamp head`` to mark all migrations as applied.
  3. For each recent revision ``R``:
     a. ``downgrade R^`` — peel just R off the stamped head.
     b. ``upgrade head`` — re-apply R (and any siblings).
     c. Assert: post-cycle schema matches pre-cycle schema.

Isolation: every test gets its own ``tempfile.mkdtemp()`` SQLite file
(``feedback_test_isolation.md`` — never touch ``backend/openestimate.db``).

PostgreSQL-only revisions (none today; placeholder for future) are
skipped via ``PG_ONLY_REVS``.

Runtime: ~5–15 s per parametrized rev on a warm interpreter. Tier
``integration``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

# Project paths — anchored to this file so the tests work regardless
# of pytest's rootdir / CWD.
THIS_FILE = Path(__file__).resolve()
BACKEND_DIR = THIS_FILE.parent.parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Recent revisions we want to exercise (the v250+ wave).
# Listed newest-first so the most recent failures surface first.
RECENT_REVISIONS: list[str] = [
    "v280_4d_schedule_eac",
    "v270_position_version_column",
    "eb1cef6f5fce",  # v262 merge node
    "v261_eac_alias_catalog_seed",
    "v260a_eac_aliases_tables",
    "v260_jobs_runner",
    "v260_eac_v2_core",
    "v250_dashboards_snapshot",
]

# Revisions needing PostgreSQL features (postgis / pgvector / JSONB
# operators / CREATE EXTENSION). None today; populate as needed.
PG_ONLY_REVS: set[str] = set()

# Revisions whose ``upgrade()`` and ``downgrade()`` are intentionally
# both ``pass`` (typically alembic-generated merge nodes). They round-
# trip vacuously; we still want to confirm they don't error, but we
# don't assert anything about schema deltas.
NOOP_BOTH_REVS: set[str] = {
    "eb1cef6f5fce",  # v262 merge — generator created empty bodies
}


def _make_alembic_config(tmp_db: Path) -> Config:
    """Build an Alembic Config pointing at ``tmp_db``.

    Override ``sqlalchemy.url`` on the config object *and* the env
    vars so ``env.py`` (which builds its own engine from
    ``settings.database_sync_url``) targets the temp DB too.
    """
    cfg = Config(str(ALEMBIC_INI))
    # ``script_location`` is normally relative to the .ini file. Make
    # it explicit so a tmp CWD doesn't break it.
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_db.as_posix()}")
    return cfg


def _import_all_models() -> None:
    """Mirror what ``alembic/env.py`` imports — populates Base.metadata.

    Done lazily (function-local imports) so this expensive step only
    runs when an actual round-trip test executes, not at collection.
    """
    # noqa: F401 imports — registering models with Base.metadata is the
    # only purpose. Order doesn't matter.
    from app.core import audit  # noqa: F401
    from app.core import job_run as _job_run  # noqa: F401  # oe_job_run table lives in core/
    from app.modules.ai import models as _ai  # noqa: F401
    from app.modules.assemblies import models as _asm  # noqa: F401
    from app.modules.bim_hub import models as _bim_hub  # noqa: F401
    from app.modules.boq import models as _boq  # noqa: F401
    from app.modules.catalog import models as _catalog  # noqa: F401
    from app.modules.cde import models as _cde  # noqa: F401
    from app.modules.changeorders import models as _co  # noqa: F401
    from app.modules.collaboration import models as _collab  # noqa: F401
    from app.modules.contacts import models as _contacts  # noqa: F401
    from app.modules.correspondence import models as _corresp  # noqa: F401
    from app.modules.costmodel import models as _cm  # noqa: F401
    from app.modules.costs import models as _costs  # noqa: F401
    from app.modules.dashboards import models as _dash  # noqa: F401
    from app.modules.documents import models as _docs  # noqa: F401
    # EAC models — not imported by env.py; their tables are alembic-only
    # in production. We import them here so ``Base.metadata.create_all``
    # mirrors the post-migration shape.
    from app.modules.eac import models as _eac  # noqa: F401
    from app.modules.enterprise_workflows import models as _ew  # noqa: F401
    from app.modules.fieldreports import models as _fr  # noqa: F401
    from app.modules.finance import models as _fin  # noqa: F401
    from app.modules.full_evm import models as _fe  # noqa: F401
    from app.modules.i18n_foundation import models as _i18n  # noqa: F401
    from app.modules.inspections import models as _ins  # noqa: F401
    from app.modules.integrations import models as _int  # noqa: F401
    from app.modules.markups import models as _mk  # noqa: F401
    from app.modules.meetings import models as _meet  # noqa: F401
    from app.modules.ncr import models as _ncr  # noqa: F401
    from app.modules.notifications import models as _notif  # noqa: F401
    from app.modules.procurement import models as _proc  # noqa: F401
    from app.modules.projects import models as _proj  # noqa: F401
    from app.modules.punchlist import models as _pl  # noqa: F401
    from app.modules.reporting import models as _rep  # noqa: F401
    from app.modules.requirements import models as _req  # noqa: F401
    from app.modules.rfi import models as _rfi  # noqa: F401
    from app.modules.rfq_bidding import models as _rfq  # noqa: F401
    from app.modules.risk import models as _risk  # noqa: F401
    from app.modules.safety import models as _safe  # noqa: F401
    from app.modules.schedule import models as _sched  # noqa: F401
    from app.modules.submittals import models as _sub  # noqa: F401
    from app.modules.takeoff import models as _to  # noqa: F401
    from app.modules.tasks import models as _tasks  # noqa: F401
    from app.modules.teams import models as _teams  # noqa: F401
    from app.modules.tendering import models as _ten  # noqa: F401
    from app.modules.transmittals import models as _trans  # noqa: F401
    from app.modules.users import models as _users  # noqa: F401
    from app.modules.validation import models as _val  # noqa: F401


def _create_all_then_stamp(tmp_db: Path, cfg: Config) -> None:
    """Mirror app boot: create_all -> stamp head.

    This is the only realistic starting point for downgrade tests —
    ``upgrade head`` from base does not work on this project (see
    module docstring).
    """
    _import_all_models()  # populate Base.metadata

    from app.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _create() -> None:
        eng = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_db.as_posix()}", future=True
        )
        try:
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await eng.dispose()

    asyncio.run(_create())
    command.stamp(cfg, "head")


@pytest.fixture
def temp_db_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Per-test temp SQLite DB + env vars routed at it.

    Yields the ``Path`` of the (not-yet-created) temp DB file. Cleanup
    removes the whole tempdir.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="oe_mig_rt_"))
    tmp_db = tmpdir / "rt.db"

    url = f"sqlite:///{tmp_db.as_posix()}"
    aurl = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", aurl)
    monkeypatch.setenv("DATABASE_SYNC_URL", url)

    # Bust the cached Settings so env.py reads the override.
    from app.config import get_settings

    get_settings.cache_clear()

    yield tmp_db

    get_settings.cache_clear()
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        pass


def _schema_snapshot(db_path: Path) -> dict[str, list[str]]:
    """Return ``{table: sorted(column_names)}`` for ``db_path``.

    Skips ``alembic_version`` (its row content changes between
    upgrade/downgrade by design) and SQLite-internal ``sqlite_*``
    tables.
    """
    if not db_path.exists():
        return {}
    eng = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        insp = inspect(eng)
        out: dict[str, list[str]] = {}
        for table in sorted(insp.get_table_names()):
            if table == "alembic_version" or table.startswith("sqlite_"):
                continue
            cols = sorted(c["name"] for c in insp.get_columns(table))
            out[table] = cols
        return out
    finally:
        eng.dispose()


# ─────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────


def test_create_all_plus_stamp_head_succeeds(temp_db_env: Path) -> None:
    """Sanity: production-style boot (create_all + stamp head) works.

    If this fails, every other round-trip test in the file fails too,
    so we run it first to fail fast with a clear signal.
    """
    cfg = _make_alembic_config(temp_db_env)
    _create_all_then_stamp(temp_db_env, cfg)

    snap = _schema_snapshot(temp_db_env)
    assert snap, "create_all + stamp produced no tables"
    # Spot-check core tables created by metadata + alembic-tracked tables.
    assert "oe_projects_project" in snap
    assert "oe_boq_position" in snap
    assert "version" in snap["oe_boq_position"], (
        "v270 column not on Position model — Base.metadata.create_all should add it"
    )
    # EAC v2 tables come from create_all too (the model is in metadata).
    assert "oe_eac_ruleset" in snap, "EAC ruleset table missing from metadata"
    assert "oe_eac_parameter_aliases" in snap
    assert "oe_job_run" in snap
    assert "oe_dashboards_snapshot" in snap


@pytest.mark.parametrize("revision", RECENT_REVISIONS)
def test_revision_downgrade_reupgrade_does_not_error(
    temp_db_env: Path, revision: str
) -> None:
    """For each recent revision: ``downgrade R^`` -> ``upgrade head`` cleanly.

    Starts from a production-style boot (create_all + stamp head),
    then exercises just the down + up of revision ``R``. This is the
    canonical "missing downgrade" detector — a broken ``downgrade()``
    raises here.

    Migrations whose upgrade() is also a no-op (merge nodes) are
    marked xfail since there's no schema delta to verify.
    """
    if revision in PG_ONLY_REVS:
        pytest.skip(f"{revision} requires PostgreSQL features")

    cfg = _make_alembic_config(temp_db_env)
    _create_all_then_stamp(temp_db_env, cfg)
    snap_before = _schema_snapshot(temp_db_env)

    # Resolve the parent revision (for downgrade target). On merge nodes
    # ``down_revision`` is a tuple — pick the first element; alembic's
    # ``downgrade`` walks the whole graph regardless.
    script = ScriptDirectory.from_config(cfg)
    parent = script.get_revision(revision).down_revision
    if isinstance(parent, tuple):
        parent_rev = parent[0]
    else:
        parent_rev = parent
    assert parent_rev, f"{revision} has no parent — can't downgrade past it"

    if revision in NOOP_BOTH_REVS:
        # Still run the cycle — if it errors, that's worth knowing —
        # but don't assert delta semantics.
        command.downgrade(cfg, parent_rev)
        command.upgrade(cfg, "head")
        pytest.xfail(
            f"{revision} is a generator-emitted merge node with empty "
            f"upgrade()/downgrade() bodies — round-trip is vacuous"
        )

    try:
        command.downgrade(cfg, parent_rev)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"downgrade past {revision} (target={parent_rev}) raised — "
            f"likely a missing/broken downgrade() body. Root cause: {exc!r}"
        )

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"re-upgrade after downgrading {revision} raised — likely "
            f"upgrade() is non-idempotent. Root cause: {exc!r}"
        )

    snap_after = _schema_snapshot(temp_db_env)
    assert snap_after == snap_before, (
        f"Schema after round-tripping {revision} differs from before. "
        f"Tables added by cycle: {set(snap_after) - set(snap_before)}; "
        f"tables removed by cycle: {set(snap_before) - set(snap_after)}"
    )


def test_recent_migrations_have_real_downgrade_bodies() -> None:
    """Static guard: each recent migration's downgrade() is non-trivial.

    "Non-trivial" = the source contains some schema-mutating call
    (``op.drop_*``, ``op.execute(...)``, ``batch_alter_table``) — not
    just ``pass`` / a docstring. Merge revisions in ``NOOP_BOTH_REVS``
    are exempt.

    This is the cheap "lint" companion to the round-trip test above:
    it surfaces the same issue even when nobody runs the slower
    integration test.
    """
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    bad: list[str] = []
    for revision in RECENT_REVISIONS:
        if revision in NOOP_BOTH_REVS:
            continue
        # Locate the migration file by matching the canonical
        # ``revision: str = "<id>"`` line — substring matches in
        # ``down_revision`` tuples on merge nodes would give false
        # positives (e.g. eb1cef6f5fce mentions both v260_jobs_runner
        # and v261_eac_alias_catalog_seed in its down_revision).
        marker = f'revision: str = "{revision}"'
        candidates = [
            p for p in versions_dir.glob("*.py")
            if marker in p.read_text(encoding="utf-8")
        ]
        assert candidates, f"Couldn't locate migration file for {revision}"
        src = candidates[0].read_text(encoding="utf-8")
        _, _, after = src.partition("def downgrade()")
        if not after:
            bad.append(f"{revision}: no downgrade() function at all")
            continue
        body = after.split("\ndef ", 1)[0]
        # Strip docstrings / comments / blanks; check what remains.
        stripped_lines = [
            line for line in body.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
        ]
        meaningful = "\n".join(stripped_lines)
        if "op." not in meaningful and "batch_alter_table" not in meaningful:
            bad.append(f"{revision}: downgrade() has no schema-mutating call")

    assert not bad, "Migrations with non-functional downgrade():\n  " + "\n  ".join(bad)


def test_dev_db_is_not_being_targeted(temp_db_env: Path) -> None:
    """Tripwire: temp-DB fixture must override the dev-DB env var.

    If anyone copy-pastes this file or the fixture goes wrong, we want
    a screaming failure rather than silent corruption of the dev DB.
    """
    assert "openestimate.db" not in os.environ.get("DATABASE_SYNC_URL", ""), (
        "Test fixture failed to override DATABASE_SYNC_URL — "
        "would have written to the dev DB. Aborting."
    )
    assert temp_db_env.parent.exists()
    assert "Temp" in str(temp_db_env) or "tmp" in str(temp_db_env).lower(), (
        f"Temp DB path doesn't look like a temp path: {temp_db_env}"
    )
