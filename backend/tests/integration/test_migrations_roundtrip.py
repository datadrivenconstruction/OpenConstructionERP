"""Alembic up/down round-trip tests (Wave 3-D / Task #237).

Goal: catch the "missing or broken downgrade()" CI bug class — a
recent migration whose ``downgrade()`` is empty or doesn't reverse what
``upgrade()`` did. The cheapest way to surface that is to run
``upgrade -> downgrade -> upgrade`` cycles on a fresh PostgreSQL DB.

Schema-creation reality (see ``app/main.py`` ~L1395):
  * The init revision ``129188e46db8`` is intentionally a no-op — its
    docstring says "Tables are created by SQLAlchemy at app startup".
  * The app boots by running ``Base.metadata.create_all()`` first,
    *then* ``alembic upgrade head`` (Alembic only carries column-level
    or new-table deltas after the metadata create).
  * Therefore plain ``alembic upgrade head`` on an empty DB doesn't
    work — e.g. ``v270_position_version_column`` does
    ``inspector.get_columns("oe_boq_position")`` which raises
    ``NoSuchTableError`` because that table comes from create_all,
    not from a migration. This is **expected** project behaviour, not
    a bug to fix here.

Test strategy (mirrors production, isolated per revision):
  1. ``Base.metadata.create_all()`` to lay down the schema at head.
  2. ``alembic stamp head`` to mark all migrations as applied.
  3. For each recent revision ``R``:
     a. ``stamp R`` - move the version marker to exactly R without
        touching the schema (already at head from create_all).
     b. ``downgrade R^`` - run *only* R's own ``downgrade()`` (one step).
     c. ``upgrade R`` - run *only* R's own ``upgrade()`` (one step back).
     d. Assert: post-cycle schema matches pre-cycle schema.

  The earlier design downgraded the whole chain head->R^ then re-upgraded
  to head, which dragged in every legacy migration body between head and
  R^. On PostgreSQL a single broken legacy downgrade aborts the
  transaction and masks the revision actually under test. Isolating to
  R's own one-step cycle attributes any failure to R and nothing else.

Isolation: every test gets its own throwaway PostgreSQL database
(created from scratch, dropped on teardown). ``DATABASE_SYNC_URL``
is monkeypatched so that Alembic's ``env.py`` targets the throwaway
DB, not the dev/production database.

PostgreSQL-only revisions that require extensions or dialect features
unavailable in the unit cluster can be added to ``PG_DOWNGRADE_BROKEN_REVS``
with a one-line reason each; they will be xfailed rather than skipped so
any unexpected recovery is surfaced.

Runtime: ~5-15 s per parametrized rev on a warm interpreter. Tier
``integration``.
"""

from __future__ import annotations

import ast
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

# Project paths — anchored to this file so the tests work regardless
# of pytest's rootdir / CWD.
THIS_FILE = Path(__file__).resolve()
BACKEND_DIR = THIS_FILE.parent.parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Older revisions we keep exercising by name. These are not the newest any
# more; they are here because each one once broke and the coverage is worth
# keeping regardless of how far behind head it falls.
LEGACY_REVISIONS: list[str] = [
    "v3151_cost_spine",
    "v290_dashboards_presets",
    "v280_4d_schedule_eac",
    "v270_position_version_column",
    "eb1cef6f5fce",  # v262 merge node
    "v261_eac_alias_catalog_seed",
    "v260a_eac_aliases_tables",
    "v260_jobs_runner",
    "v260_eac_v2_core",
    "v250_dashboards_snapshot",
]

# How many revisions back from head to always round-trip.
NEWEST_REVISION_WINDOW = 14


def _revision_graph() -> dict[str, tuple[str, ...]]:
    """Map every revision id to its parents, read from the files as text.

    Deliberately not ``ScriptDirectory.walk_revisions``. That imports each
    migration module, and ``v3121_geo_raster_overlay`` imports ``app.database``
    at module level, which refuses to load without a PostgreSQL ``DATABASE_URL``.
    Using it here would make merely collecting this file depend on a running
    database. Parsing the headers keeps collection free of that.
    """
    graph: dict[str, tuple[str, ...]] = {}
    for path in sorted((BACKEND_DIR / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            else:
                continue
            if target not in ("revision", "down_revision") or value is None:
                continue
            try:
                found[target] = ast.literal_eval(value)
            except ValueError:  # computed, not a literal - nothing to read
                continue
        rev = found.get("revision")
        if not isinstance(rev, str):
            continue
        down = found.get("down_revision")
        if isinstance(down, str):
            graph[rev] = (down,)
        elif isinstance(down, (tuple, list)):
            graph[rev] = tuple(str(d) for d in down)
        else:
            graph[rev] = ()
    return graph


_SCHEMA_OP_PREFIXES = ("add_", "alter_", "create_", "drop_", "rename_")


def _changes_schema(source: str, func_name: str) -> bool:
    """True if ``func_name`` in ``source`` calls an Alembic op that alters schema.

    ``op.get_bind`` and ``op.get_context`` are how a data migration reaches the
    connection, so their presence is not evidence of a schema change.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or node.name != func_name:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute):
                if inner.attr == "batch_alter_table" or inner.attr.startswith(_SCHEMA_OP_PREFIXES):
                    return True
    return False


def _newest_revisions(count: int) -> list[str]:
    """Return the newest ``count`` revision ids, walking down from the heads.

    Derived rather than typed. This list used to be written by hand and it
    stopped being updated: its newest entry was ``v3272`` while eight later
    migrations sat on disk, so the suite was green having never executed a
    single downgrade shipped in that release. A gate whose coverage is a
    literal only covers what somebody remembered to add to the literal, and
    the thing most likely to be forgotten is the migration written today,
    which is also the one most likely to be wrong.

    Walking the graph instead means a new revision is under test the moment
    it lands. A revision that genuinely cannot round-trip belongs in
    ``PG_DOWNGRADE_BROKEN_REVS`` with its reason, not outside the window.
    """
    graph = _revision_graph()
    parents = {parent for parents in graph.values() for parent in parents}
    frontier = sorted(rev for rev in graph if rev not in parents)

    newest: list[str] = []
    seen: set[str] = set()
    while frontier and len(newest) < count:
        rev = frontier.pop(0)
        if rev in seen or rev not in graph:
            continue
        seen.add(rev)
        newest.append(rev)
        frontier.extend(graph[rev])
    return newest


# Newest-first, so the most recent failures surface first.
_NEWEST = _newest_revisions(NEWEST_REVISION_WINDOW)
RECENT_REVISIONS: list[str] = _NEWEST + [rev for rev in LEGACY_REVISIONS if rev not in set(_NEWEST)]

# Revisions whose ``upgrade()`` and ``downgrade()`` are intentionally
# both ``pass`` (typically alembic-generated merge nodes). They round-
# trip vacuously; we still want to confirm they don't error, but we
# don't assert anything about schema deltas.
NOOP_BOTH_REVS: set[str] = {
    "eb1cef6f5fce",  # v262 merge — generator created empty bodies
}

# Revisions that are known to fail the downgrade/re-upgrade cycle on
# PostgreSQL due to genuine dialect-level issues that are separate bugs
# to fix. Add entries here rather than deleting the tests. Format:
#   "revision_id": "one-line reason"
PG_DOWNGRADE_BROKEN_REVS: dict[str, str] = {
    # Example: "v999_example": "downgrade drops a PG-only ENUM that upgrade doesn't recreate"
    "v260_eac_v2_core": (
        "isolation artefact, not a broken downgrade. The cycle above stamps R and runs R's own "
        "downgrade against a schema that is still at head, so this one tries to drop oe_eac_rule "
        "while oe_eac_block_graph - created much later, by v3259 - still holds "
        "fk_oe_eac_block_graph_rule_id_oe_eac_rule against it. A real head-to-v250 downgrade runs "
        "v3259's downgrade first and frees the parent, so this body is correct in the chain it "
        "actually runs in. Any revision whose downgrade drops a table a LATER migration references "
        "will fail here the same way; that is the class, and telling it apart from a genuine "
        "missing drop means asking which revision owns the dependent object, not reading the error."
    ),
}

# Columns the migration chain creates that ``Base.metadata.create_all`` does not,
# with the revision that owns each one and why it is dead. A cycle long enough to
# re-apply the owning revision brings the column back, and it is absent from the
# head schema because the model retired it - which is a divergence between the
# chain and the models, not the upgrade/downgrade inconsistency the assertion
# below is looking for. Repairing it means dropping a column from every
# alembic-managed deployment, and that is a data decision, so the divergence is
# recorded here where it can be read rather than converted into an xfail that
# would stop the whole cycle reporting anything.
#
# ``test_the_chain_only_column_exemptions_are_still_earned`` makes an entry that
# outlives its divergence a failure, so this list cannot quietly become a licence.
CHAIN_ONLY_COLUMNS: dict[str, tuple[str, str]] = {
    "oe_boq_boq.tax_rate": (
        "v3134_boq_tax_rate.py",
        "Tax is a BOQMarkup row of category 'tax' now, so the model dropped the column. "
        "BOQTotals in app.modules.boq.schemas still carries tax_rate for wire compatibility "
        "and says outright that the service never populates it.",
    ),
}

# ``oe_projects_project.unit_system`` sat in the dict above until 18.1.1, when
# the project model declared it again - nullable, no default, the measurement
# system a person states in the project settings - and
# ``v48_project_jurisdiction_unit_system`` relaxed the shape v3135 gave it.


# ``v41_contract_original_value`` used to sit in the dict above and no longer
# does. It is worth saying what it taught, because the entry named three
# different failures over its life and each one was a different class.
#
# It is a merge node: ``down_revision`` is the tuple
# ``(v41_coordination_thresholds, v3324_buyer_selection_currency)``, and the
# cycle asks for a one-step downgrade to ``parent[0]``. Alembic must also
# un-apply everything reachable only through the other parent, so the one step
# walks 222 revisions - measured as ``ancestors(parent[1])`` minus
# ``ancestors(parent[0])`` over all 359 files, not read off the error. Recognise
# that class by comparing the two parents' ancestor sets before reading the
# error, because the error always names a stranger.
#
# The three failures, in the order they surfaced, each hidden by the one before:
#
# 1. ``cannot drop index uq_oe_service_contract_number because constraint ...
#    requires it`` in v3101. Repaired;
#    ``test_no_downgrade_drops_an_index_a_constraint_owns`` is the live guard.
# 2. ``DatatypeMismatch`` on the way back up, in
#    v3104_propdev_broker_escrow_pricematrix_hierarchy and fifteen siblings,
#    which declared identity columns as native PostgreSQL uuid while the parents
#    they reference render as ``character varying(36)``. Repaired - and then ten
#    more were repaired that this walk never reaches. Re-running the walk finds
#    one revision per run; measuring every merge span found the rest at once,
#    and five of those ten hang the same foreign key onto a varchar parent. The
#    live guard is ``test_no_revision_inside_a_merge_span_declares_a_native_uuid``
#    below, and the allowlist in ``tests/pg/test_migration_uuid_convention.py``
#    shrank from 50 to 24.
# 3. Two swallowed errors that poisoned the transaction rather than the
#    statement that met them: v3234's ``CREATE EXTENSION pg_trgm`` on a cluster
#    that does not ship pg_trgm, and v3273's side connection blocking on a lock
#    its own migration held. Both repaired in their own bodies.
# 4. Two columns the chain still created that the models no longer carried,
#    ``oe_boq_boq.tax_rate`` and ``oe_projects_project.unit_system`` (the
#    second is back in the models since 18.1.1). Not an
#    upgrade/downgrade fault: both bodies are correct and idempotent, and both
#    revisions are simply older than the model decision that retired the column.
#    Only a walk this long reaches that far back. They are recorded in
#    ``CHAIN_ONLY_COLUMNS`` with the reason each column is dead, because
#    dropping a column from a deployed database is a data decision rather than
#    a test fix.
#
# The shape to carry away is that an expected failure hides the next one. Each
# repair moved the error to a revision that had been failing all along and had
# never been reported, because the walk had never reached it.


# ─────────────────────────────────────────────────────────────────────
#  PostgreSQL helpers (mirrors _pg.py internal pattern)
# ─────────────────────────────────────────────────────────────────────


def _maintenance_db(admin_url: str) -> str:
    """The cluster database used to issue CREATE/DROP DATABASE.

    Derived from ``admin_url`` - the *original* configured URL captured
    before the per-test monkeypatch - never from the live env var. By the
    time teardown runs, ``DATABASE_SYNC_URL`` points at the throwaway DB,
    and you cannot DROP the database your own connection is bound to.
    """
    return make_url(admin_url).database or "postgres"


def _sync_url_for(admin_url: str, database: str) -> str:
    """psycopg2 SQLAlchemy URL for ``database`` on ``admin_url``'s cluster."""
    base = make_url(admin_url)
    return base.set(drivername="postgresql+psycopg2", database=database).render_as_string(hide_password=False)


def _connect_admin(admin_url: str):
    """Autocommit psycopg2 connection to the maintenance database.

    Connects to the cluster's maintenance DB (the one named in the
    original ``admin_url``), not the throwaway, so CREATE/DROP DATABASE
    run from a connection that is not itself the target. ``admin_url``
    carries the SQLAlchemy ``postgresql+psycopg2`` driver form; raw
    ``psycopg2.connect`` only accepts a libpq ``postgresql://`` URI, so
    the driver suffix is stripped here.
    """
    base = make_url(admin_url)
    maint = base.set(drivername="postgresql", database=_maintenance_db(admin_url)).render_as_string(hide_password=False)
    conn = psycopg2.connect(maint)
    conn.autocommit = True
    return conn


def _terminate_backends(cur, db_name: str) -> None:
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
        (db_name,),
    )


def _create_throwaway_db(admin_url: str, db_name: str) -> None:
    """Create a fresh, empty PostgreSQL database for one test."""
    conn = _connect_admin(admin_url)
    try:
        conn.cursor().execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


def _drop_throwaway_db(admin_url: str, db_name: str) -> None:
    """Drop the throwaway database, terminating any leftover connections first."""
    conn = _connect_admin(admin_url)
    try:
        cur = conn.cursor()
        _terminate_backends(cur, db_name)
        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        cur.close()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────
#  Alembic config builder
# ─────────────────────────────────────────────────────────────────────


def _make_alembic_config(sync_url: str) -> Config:
    """Build an Alembic Config pointing at ``sync_url``.

    Override both the ini ``sqlalchemy.url`` entry (for completeness)
    and set the env var so ``alembic/env.py`` (which reads
    ``settings.database_sync_url`` directly) targets the throwaway DB.
    The ``DATABASE_SYNC_URL`` env var monkeypatch is applied by the
    ``pg_throwaway`` fixture before this function is called.
    """
    cfg = Config(str(ALEMBIC_INI))
    # ``script_location`` is normally relative to the .ini file; make it
    # explicit so a temp CWD doesn't break resolution.
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # Alembic keeps this in a ConfigParser with interpolation enabled, where a
    # bare ``%`` opens a substitution. A unix-socket URL carries its socket
    # directory percent-encoded in the query string
    # (``?host=%2Ftmp%2Foe-tests-pg-...``), so the raw value raises
    # ``ValueError: invalid interpolation syntax``. Doubling the sign is the
    # escape ConfigParser defines and the value reads back unchanged. This is
    # the embedded-cluster path: how the suite runs on macOS, on Linux with no
    # DATABASE_URL set, and on any developer machine that boots its own
    # cluster. The lanes that point at a TCP service container never see a
    # percent sign here, which is why this was macOS-only in CI - it took all
    # 28 tests in this module down on the 2026-09-22 nightly.
    cfg.set_main_option("sqlalchemy.url", sync_url.replace("%", "%%"))
    return cfg


# ─────────────────────────────────────────────────────────────────────
#  Model import helper
# ─────────────────────────────────────────────────────────────────────


def _import_all_models() -> None:
    """Mirror what ``alembic/env.py`` imports - populates Base.metadata.

    Done lazily (function-local imports) so this expensive step only
    runs when an actual round-trip test executes, not at collection.

    Uses the same pkgutil catch-all as ``alembic/env.py`` rather than a
    hand-maintained list. A static list silently drifts: it was missing
    ``property_dev`` (and others), so ``Base.metadata.create_all`` never
    materialised ``oe_property_dev_custom_template`` and any downgrade
    body that reflected that table (e.g. v3137) raised ``NoSuchTableError``
    on PostgreSQL. Sweeping every module guarantees create_all reproduces
    the exact production schema shape.
    """
    import importlib
    import pkgutil

    from app import modules as _modules_pkg

    # Core-level tables that live outside app.modules.* and so are not
    # reached by the module sweep below.
    from app.core import audit  # noqa: F401
    from app.core import audit_log as _audit_log  # noqa: F401  # oe_activity_log
    from app.core import job_run as _job_run  # noqa: F401  # oe_job_run
    from app.core.translation import cache as _tcache  # noqa: F401  # oe_translation_cache

    _modules_dir = os.path.dirname(_modules_pkg.__file__)
    for _entry in pkgutil.iter_modules([_modules_dir]):
        if not _entry.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{_entry.name}.models")
        except Exception:  # noqa: BLE001 - mirror env.py: a bad module never aborts the sweep
            pass


# ─────────────────────────────────────────────────────────────────────
#  Schema bootstrap
# ─────────────────────────────────────────────────────────────────────


def _create_all_then_stamp(sync_url: str, cfg: Config) -> None:
    """Mirror app boot: create_all on a sync PostgreSQL engine, then stamp head.

    This is the only realistic starting point for downgrade tests —
    ``upgrade head`` from base does not work on this project (see
    module docstring).
    """
    _import_all_models()  # populate Base.metadata

    from app.database import Base

    eng = create_engine(sync_url)
    try:
        Base.metadata.create_all(eng)
    finally:
        eng.dispose()

    command.stamp(cfg, "head")


# ─────────────────────────────────────────────────────────────────────
#  Schema snapshot
# ─────────────────────────────────────────────────────────────────────


def _schema_snapshot(sync_url: str) -> dict[str, list[str]]:
    """Return ``{table: sorted(column_names)}`` for the database at ``sync_url``.

    Skips ``alembic_version`` (its row content changes between
    upgrade/downgrade by design) and PostgreSQL system tables.
    """
    eng = create_engine(sync_url)
    try:
        insp = inspect(eng)
        out: dict[str, list[str]] = {}
        for table in sorted(insp.get_table_names()):
            if table == "alembic_version":
                continue
            cols = sorted(c["name"] for c in insp.get_columns(table))
            out[table] = cols
        return out
    finally:
        eng.dispose()


# ─────────────────────────────────────────────────────────────────────
#  Per-test fixture: throwaway PostgreSQL database
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def pg_throwaway(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Per-test throwaway PostgreSQL database + env vars routed at it.

    Creates a fresh, empty database on the session cluster, monkeypatches
    ``DATABASE_SYNC_URL`` (and ``DATABASE_URL``) to point at it, and
    clears the Settings cache so ``alembic/env.py`` picks up the override.
    Drops the database on teardown.

    Yields the sync psycopg2 URL string for the throwaway database.
    """
    # Capture the original (pre-monkeypatch) sync URL. All CREATE/DROP
    # DATABASE admin work uses this, never the patched env var: by the time
    # teardown runs, DATABASE_SYNC_URL points at the throwaway DB, and a
    # connection bound to that DB cannot drop it.
    admin_url = os.environ["DATABASE_SYNC_URL"]

    db_name = f"oe_mig_rt_{uuid.uuid4().hex[:16]}"
    _create_throwaway_db(admin_url, db_name)

    sync_url = _sync_url_for(admin_url, db_name)
    # Build the async URL from the sync one (replace driver).
    async_url = make_url(sync_url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)

    monkeypatch.setenv("DATABASE_SYNC_URL", sync_url)
    monkeypatch.setenv("DATABASE_URL", async_url)

    # Bust the cached Settings so env.py reads the override.
    from app.config import get_settings

    get_settings.cache_clear()

    try:
        yield sync_url
    finally:
        get_settings.cache_clear()
        _drop_throwaway_db(admin_url, db_name)


# ─────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────


def test_create_all_plus_stamp_head_succeeds(pg_throwaway: str) -> None:
    """Sanity: production-style boot (create_all + stamp head) works on PostgreSQL.

    If this fails, every other round-trip test in the file fails too,
    so we run it first to fail fast with a clear signal.
    """
    sync_url = pg_throwaway
    cfg = _make_alembic_config(sync_url)
    _create_all_then_stamp(sync_url, cfg)

    snap = _schema_snapshot(sync_url)
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
def test_revision_downgrade_reupgrade_does_not_error(pg_throwaway: str, revision: str) -> None:
    """For each recent revision R: isolate-test R's own down + up step on PostgreSQL.

    Starts from a production-style boot (create_all + stamp head), then:
      1. ``stamp R`` - move the version marker to exactly R without
         touching the schema (already at head from create_all).
      2. ``downgrade R^`` - run *only* R's ``downgrade()`` body (one step).
      3. ``upgrade R`` - run *only* R's ``upgrade()`` body (one step back).

    This is the canonical "missing/broken downgrade" detector, isolated
    so a failure is attributable to R alone and unrelated legacy bodies
    never run (they would abort the PG transaction and mask R).

    The schema matches before and after because create_all already laid
    down R's objects; R.downgrade() removes them and R.upgrade() re-adds
    them.
    """
    if revision in PG_DOWNGRADE_BROKEN_REVS:
        pytest.xfail(f"{revision} known broken on PG: {PG_DOWNGRADE_BROKEN_REVS[revision]}")

    if revision in NOOP_BOTH_REVS:
        # Empty upgrade()/downgrade() bodies (generator-emitted merge
        # nodes). There is no schema delta to cycle and a merge node
        # cannot be downgraded one step to a single parent cleanly. An
        # empty body cannot be "broken", so there is nothing to exercise.
        pytest.xfail(
            f"{revision} is a generator-emitted merge node with empty "
            f"upgrade()/downgrade() bodies - round-trip is vacuous"
        )

    sync_url = pg_throwaway
    cfg = _make_alembic_config(sync_url)
    _create_all_then_stamp(sync_url, cfg)
    snap_before = _schema_snapshot(sync_url)

    # Resolve the parent revision (the one-step downgrade target).
    script = ScriptDirectory.from_config(cfg)
    parent = script.get_revision(revision).down_revision
    parent_rev = parent[0] if isinstance(parent, tuple) else parent
    assert parent_rev, f"{revision} has no parent - can't downgrade past it"

    # Move the version marker to exactly R. The schema is already at head
    # from create_all, so this just rewrites alembic_version - no
    # migration body runs. The subsequent downgrade is then a single step
    # (R -> R^) that executes only R's own downgrade().
    command.stamp(cfg, revision)

    try:
        command.downgrade(cfg, parent_rev)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"downgrade of {revision} (target={parent_rev}) raised - "
            f"likely a missing/broken downgrade() body. Root cause: {exc!r}"
        )

    try:
        command.upgrade(cfg, revision)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"re-upgrade of {revision} raised - likely upgrade() is "
            f"non-idempotent or PG-incompatible. Root cause: {exc!r}"
        )

    snap_after = _schema_snapshot(sync_url)

    # Table set must be unchanged: a downgrade that drops a table whose
    # upgrade fails to recreate it (or a downgrade/upgrade that leaks a
    # spurious table) shows up here.
    assert set(snap_after) == set(snap_before), (
        f"Schema after round-tripping {revision} changed the table set. "
        f"Tables added by cycle: {set(snap_after) - set(snap_before)}; "
        f"tables removed by cycle: {set(snap_before) - set(snap_after)}"
    )

    # Column-level invariant for *isolated* single-step cycling: re-running
    # only R's own upgrade() recreates R's tables at their R-era shape, which
    # is a subset of the head shape whenever a *later* migration added columns
    # to one of those tables (e.g. v260_jobs_runner adds idempotency_key /
    # spool_path to the oe_eac_run table that v260_eac_v2_core created). That
    # subset divergence is expected, not a bug. What is NOT allowed is the
    # cycle introducing a column the head schema doesn't have - that signals a
    # genuine upgrade/downgrade inconsistency.
    #
    # ``CHAIN_ONLY_COLUMNS`` is subtracted here: those columns are absent from
    # the head schema because the model retired them and not because a body is
    # inconsistent, and each entry names the revision that owns it.
    introduced: dict[str, list[str]] = {}
    for table, columns in snap_after.items():
        extra = sorted(
            column for column in set(columns) - set(snap_before[table]) if f"{table}.{column}" not in CHAIN_ONLY_COLUMNS
        )
        if extra:
            introduced[table] = extra
    assert not introduced, (
        f"Round-tripping {revision} introduced columns absent from the head "
        f"schema (upgrade/downgrade inconsistency): {introduced}"
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
    skipped_data_only: list[str] = []
    for revision in RECENT_REVISIONS:
        if revision in NOOP_BOTH_REVS:
            continue
        # Locate the migration file by matching the revision assignment at the
        # start of a line — substring matches in ``down_revision`` tuples on
        # merge nodes would give false positives (e.g. eb1cef6f5fce mentions
        # both v260_jobs_runner and v261_eac_alias_catalog_seed in its
        # down_revision), and ``down_revision = "<id>"`` literally contains
        # ``revision = "<id>"``, so the anchor is what keeps the two apart.
        #
        # Both spellings of the assignment live in the tree: the annotated
        # ``revision: str = ...`` alembic's template emits now, and the bare
        # ``revision = ...`` that 51 older files still carry. Matching only the
        # annotated one made this guard fail the moment the newest-revision
        # window slid over one of those older files, which says nothing about
        # the downgrade bodies it is here to check.
        marker = re.compile(rf'^revision(?::\s*str)?\s*=\s*"{re.escape(revision)}"', re.MULTILINE)
        candidates = [p for p in versions_dir.glob("*.py") if marker.search(p.read_text(encoding="utf-8"))]
        assert candidates, f"Couldn't locate migration file for {revision}"
        src = candidates[0].read_text(encoding="utf-8")

        # A migration that never touched the schema has nothing to reverse, and
        # demanding a schema call in its downgrade() would be asking it to undo
        # work it did not do. v3269, v3271 and v3273 are backfills: their only
        # use of ``op`` is ``op.get_bind()`` to run data statements, and each
        # documents its downgrade as a deliberate no-op. Deciding this from the
        # upgrade body rather than from a list of exempt revision ids means a
        # future backfill is judged correctly without anyone registering it,
        # and a migration that does add a column is still held to the rule.
        if not _changes_schema(src, "upgrade"):
            skipped_data_only.append(revision)
            continue

        _, _, after = src.partition("def downgrade()")
        if not after:
            bad.append(f"{revision}: no downgrade() function at all")
            continue
        body = after.split("\ndef ", 1)[0]
        # Strip docstrings / comments / blanks; check what remains.
        stripped_lines = [
            line
            for line in body.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
        ]
        meaningful = "\n".join(stripped_lines)
        if "op." not in meaningful and "batch_alter_table" not in meaningful:
            bad.append(f"{revision}: downgrade() has no schema-mutating call")

    # Say what was not checked. An exemption nobody can see is the same shape
    # of blind spot as the short revision list this guard used to run against.
    print(f"data-only migrations exempt from the downgrade rule: {', '.join(skipped_data_only) or 'none'}")
    assert not bad, "Migrations with non-functional downgrade():\n  " + "\n  ".join(bad)


# ─────────────────────────────────────────────────────────────────────
#  Static guard: no downgrade may drop an index a constraint owns
#
#  PostgreSQL refuses ``DROP INDEX x`` when x is the index backing a
#  constraint: "cannot drop index x because constraint x on table t requires
#  it". A migration hits that whenever it creates uniqueness as a plain unique
#  INDEX - the portable spelling, because SQLite has no
#  ``ALTER TABLE ADD CONSTRAINT`` - while the model declares the same name as a
#  ``UniqueConstraint``, so ``Base.metadata.create_all`` builds a real
#  constraint and the index of that name belongs to it.
#
#  The guard below is what replaced an xfail entry. An xfail is a live signal
#  only while it is failing; once the body is repaired the entry has to go, and
#  removing it leaves nothing watching the shape. This asserts the condition
#  PostgreSQL actually enforces, so it also catches the regression from the
#  other side: a model that later turns a plain ``Index(unique=True)`` into a
#  ``UniqueConstraint`` puts an existing, untouched migration into the
#  colliding set and turns this red without anyone editing a migration.
# ─────────────────────────────────────────────────────────────────────

_INDEX_DROP_CALLS = ("drop_index",)
_CONSTRAINT_DROP_CALLS = ("drop_constraint",)
_RAW_DROP_INDEX = re.compile(r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?([\w{}.\"]+)", re.IGNORECASE)
_RAW_DROP_CONSTRAINT = re.compile(r"DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?([\w{}.\"]+)", re.IGNORECASE)


def _as_value(node: ast.expr) -> object | None:
    """Static value of ``node``, unwrapping a one-argument call around a literal.

    Index names are written three ways in this tree and the guard has to see
    all three, because the one it would miss is the one that broke:

    * a bare literal - ``op.drop_index("uq_x", table_name="t")``;
    * a row of a module-level table the downgrade loops over - v3101 builds
      three names from ``_UNIQUES``, and a probe that demands a literal finds
      none of them;
    * a literal passed through a local validator - v41_smart_views_share has
      ``_INDEX = _safe_ident("ix_smart_view_share_token")``, which is not a
      literal to ``ast.literal_eval`` at all.

    The unwrap is deliberately an over-approximation. A helper that rewrote its
    argument would make this guard check a name no table carries, which finds
    nothing; dropping the name instead would make the guard blind, which is the
    failure mode it exists to prevent.
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        pass
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        try:
            return ast.literal_eval(node.args[0])
        except (ValueError, TypeError, SyntaxError):
            return None
    return None


def _module_values(tree: ast.Module) -> dict[str, object]:
    """Module-level names bound to a static value."""
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target.id], node.value
        else:
            continue
        if value is None:
            continue
        resolved = _as_value(value)
        if resolved is None:
            continue
        for target in targets:
            values[target] = resolved
    return values


def _hashable(value: object) -> object:
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value


class _NameResolver:
    """Resolves an argument expression to the strings it can hold at runtime.

    Carries module-level constants plus whatever a ``for`` loop binds. Loops
    are unrolled one row at a time rather than each variable being bound to its
    whole column, so a row's values stay together.
    """

    def __init__(self, module_values: dict[str, object], binds: dict[str, object] | None = None) -> None:
        self._module = module_values
        self._binds = dict(binds or {})

    def _rows(self, iterable: ast.expr) -> list | None:
        source: object | None = None
        if isinstance(iterable, ast.Name):
            source = self._binds.get(iterable.id, self._module.get(iterable.id))
        else:
            source = _as_value(iterable)
        return list(source) if isinstance(source, (list, tuple, set)) else None

    def unrolled(self, target: ast.expr, iterable: ast.expr) -> list[_NameResolver]:
        rows = self._rows(iterable)
        if rows is None:
            return [_NameResolver(self._module, self._binds)]
        scopes: list[_NameResolver] = []
        for row in rows:
            binds = dict(self._binds)
            if isinstance(target, ast.Name):
                binds[target.id] = _hashable(row)
            elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(row, (tuple, list)):
                for position, element in enumerate(target.elts):
                    if isinstance(element, ast.Name) and position < len(row):
                        binds[element.id] = _hashable(row[position])
            scopes.append(_NameResolver(self._module, binds))
        return scopes or [_NameResolver(self._module, self._binds)]

    def strings(self, node: ast.expr | None) -> set[str]:
        """The string values ``node`` can take, as far as they are knowable."""
        if node is None:
            return set()
        if isinstance(node, ast.Name):
            value = self._binds.get(node.id, self._module.get(node.id))
            return {value} if isinstance(value, str) else set()
        value = _as_value(node)
        return {value} if isinstance(value, str) else set()

    def sql(self, node: ast.expr | None) -> str | None:
        """SQL text of ``node``, with f-string slots resolved where possible."""
        if node is None:
            return None
        # ``op.execute(sa.text(f"..."))`` is the same statement as
        # ``op.execute(f"...")``; unwrap the one-argument call first so the
        # f-string branch below sees the JoinedStr either way.
        if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
            return self.sql(node.args[0])
        if isinstance(node, ast.JoinedStr):
            out = ""
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out += part.value
                elif isinstance(part, ast.FormattedValue):
                    replacements = self.strings(part.value)
                    out += next(iter(replacements)) if len(replacements) == 1 else " ? "
            return out
        for candidate in (self.strings(node), {_as_value(node)}):
            for value in candidate:
                if isinstance(value, str):
                    return value
        return None


def _drops_in_downgrade(path: Path) -> tuple[set[str], set[str]]:
    """``(index names dropped, constraint names dropped)`` in one revision's downgrade."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    resolver = _NameResolver(_module_values(tree))
    indexes: set[str] = set()
    constraints: set[str] = set()

    def visit(statements: list[ast.stmt], scope: _NameResolver) -> None:
        for statement in statements:
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                for inner in scope.unrolled(statement.target, statement.iter):
                    visit(statement.body, inner)
                    visit(statement.orelse, inner)
                continue
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.stmt):
                    continue
                for node in ast.walk(child):
                    if isinstance(node, ast.Call):
                        record(node, scope)
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(statement, field, []) or [], scope)
            for handler in getattr(statement, "handlers", []) or []:
                visit(handler.body, scope)

    def record(call: ast.Call, scope: _NameResolver) -> None:
        if not isinstance(call.func, ast.Attribute):
            return
        attribute = call.func.attr
        keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        if attribute in _INDEX_DROP_CALLS:
            indexes.update(scope.strings(call.args[0] if call.args else keywords.get("index_name")))
        elif attribute in _CONSTRAINT_DROP_CALLS:
            constraints.update(scope.strings(call.args[0] if call.args else keywords.get("constraint_name")))
        elif attribute == "execute":
            statement = scope.sql(call.args[0] if call.args else None)
            if not statement:
                return
            flat = " ".join(statement.split())
            indexes.update(match.group(1).strip('"') for match in _RAW_DROP_INDEX.finditer(flat))
            constraints.update(match.group(1).strip('"') for match in _RAW_DROP_CONSTRAINT.finditer(flat))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            visit(node.body, resolver)
    return indexes, constraints


def _constraint_backed_index_names() -> dict[str, str]:
    """``{name: "table:ConstraintType"}`` for every constraint create_all names.

    A ``UniqueConstraint`` or ``PrimaryKeyConstraint`` is rendered by
    ``create_all`` as ``ALTER TABLE ... ADD CONSTRAINT``, and PostgreSQL builds
    the backing index under the constraint's own name. Those are exactly the
    names a ``DROP INDEX`` cannot have. A plain ``Index(unique=True)`` of the
    same name would be droppable, which is why the model, not the migration,
    decides whether a given name is a problem.
    """
    _import_all_models()

    from app.database import Base

    owned: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            kind = type(constraint).__name__
            if constraint.name and kind in ("UniqueConstraint", "PrimaryKeyConstraint"):
                owned[str(constraint.name)] = f"{table.name}:{kind}"
    return owned


def test_no_downgrade_drops_an_index_a_constraint_owns() -> None:
    """No revision may drop an index that ``create_all`` builds as a constraint.

    This is the positive form of what an xfail on ``v41_contract_original_value``
    used to report. That entry named the symptom - a merge node whose one-step
    downgrade walks 222 revisions and dies somewhere inside them - and reported
    it only as an expected failure, which is a signal that stops existing the
    moment the body is repaired.

    Measured over every revision on disk, not a window: a revision that has
    fallen out of the round-trip parametrisation still ships, and v3101 was
    exactly that, reachable only through a merge node's second parent.
    """
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    revision_files = sorted(versions_dir.glob("*.py"))
    owned = _constraint_backed_index_names()

    offenders: dict[str, list[str]] = {}
    droppers = 0
    for path in revision_files:
        dropped_indexes, dropped_constraints = _drops_in_downgrade(path)
        if dropped_indexes:
            droppers += 1
        colliding = sorted((dropped_indexes & set(owned)) - dropped_constraints)
        if colliding:
            offenders[path.name] = colliding

    # Population beside the verdict. A green gate whose denominator excludes
    # the place a defect lives is not evidence of anything, and these three
    # numbers are what say how much of the tree this actually looked at.
    print(
        f"revisions scanned: {len(revision_files)}; "
        f"downgrades that drop an index by name: {droppers}; "
        f"constraint-backed index names in Base.metadata: {len(owned)}"
    )

    assert not offenders, (
        "These downgrades drop an index PostgreSQL will not let them drop, because "
        "Base.metadata declares that name as a constraint and the index belongs to it. "
        "Drop the constraint first when the inspector reports one, as v3099 and v3101 do:\n  "
        + "\n  ".join(f"{name}: {', '.join(f'{n} ({owned[n]})' for n in names)}" for name, names in offenders.items())
    )


# ─────────────────────────────────────────────────────────────────────
#  Static gate: native uuid inside a merge node's one-step span
# ─────────────────────────────────────────────────────────────────────

# ``uuid`` is the standard library module and ``uuid.UUID`` the Python value a
# data migration builds an id with. Neither says anything about a column type.
_UUID_TYPE_LEAVES = {"UUID", "Uuid"}
_STDLIB_UUID_ROOT = "uuid"

# ``existing_type=postgresql.UUID()`` names what a column is being converted
# away from. That is the repair direction, not a declaration.
_UUID_EXEMPT_KEYWORD = "existing_type"


def _dotted_name(node: ast.AST) -> str | None:
    """Render an attribute chain as ``a.b.c``, or None when it is not one."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _native_uuid_sites(tree: ast.Module) -> list[str]:
    """Every native-UUID type reference in one revision, as ``line N: source``."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sqlalchemy"):
            imported.update(alias.asname or alias.name for alias in node.names if alias.name in _UUID_TYPE_LEAVES)

    exempt: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == _UUID_EXEMPT_KEYWORD:
                exempt.update(id(child) for child in ast.walk(keyword.value))

    sites: list[str] = []
    seen: set[int] = set()
    for node in ast.walk(tree):
        if id(node) in exempt or id(node) in seen:
            continue
        if isinstance(node, ast.Name):
            hit = node.id in imported
        else:
            chain = _dotted_name(node)
            parts = chain.split(".") if chain else []
            hit = bool(parts) and parts[-1] in _UUID_TYPE_LEAVES and parts[0] != _STDLIB_UUID_ROOT
        if not hit:
            continue
        # An attribute chain contains its own prefixes; report the outermost.
        seen.update(id(child) for child in ast.walk(node))
        sites.append(f"line {node.lineno}: {ast.unparse(node)[:90]}")
    return sites


def _revision_id_of(tree: ast.Module) -> str | None:
    """The ``revision = "..."`` header value, read without importing the module."""
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        else:
            continue
        if target != "revision" or value is None:
            continue
        try:
            found = ast.literal_eval(value)
        except ValueError:
            return None
        if isinstance(found, str):
            return found
    return None


def _ancestors_of(graph: dict[str, tuple[str, ...]], start: str) -> set[str]:
    """Every revision reachable downwards from ``start``, ``start`` included."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        rev = stack.pop()
        if rev in seen or rev not in graph:
            continue
        seen.add(rev)
        stack.extend(graph[rev])
    return seen


def _merge_span_revisions(graph: dict[str, tuple[str, ...]]) -> tuple[set[str], int]:
    """Revisions a merge node's one-step downgrade re-applies, over every parent.

    Downgrading a merge node one step is not one step. Alembic has to un-apply
    everything reachable only through the parents it is not going to, then
    re-apply all of it on the way back up, which is why the cycle above walks
    222 revisions for a node whose ``down_revision`` is a two-tuple.

    Every parent is taken, not just ``parent[0]``. The cycle above happens to
    ask for ``parent[0]``, but that is an implementation detail of one test
    rather than a property of the graph: over ``parent[0]`` alone the population
    is 266 revisions and over every parent it is 285, and the nineteen that
    separate those two numbers held five of the offenders this guard was written
    for. The merge nodes themselves stay in as well, because a merge node's own
    ``upgrade()`` re-runs too, which is how the 292 this test prints is reached.
    """
    span: set[str] = set()
    merges = 0
    for rev, parents in graph.items():
        if len(parents) < 2:
            continue
        merges += 1
        reachable = _ancestors_of(graph, rev)
        for parent in parents:
            # ``rev`` stays in: a merge node's own upgrade() re-runs too.
            span |= reachable - _ancestors_of(graph, parent)
    return span, merges


def test_no_revision_inside_a_merge_span_declares_a_native_uuid() -> None:
    """No revision a merge node re-applies may declare a native PostgreSQL uuid column.

    ``GUID`` in ``app.database`` is a ``TypeDecorator`` over ``String(36)`` with
    no ``load_dialect_impl``, so ``create_all`` renders every identity column as
    ``character varying(36)`` on PostgreSQL too, and a revision declaring
    ``postgresql.UUID`` describes a shape our schema never has. Stamped, that
    divergence is dormant and nothing executes it. Walked, it is fatal: a uuid
    child pointing at a varchar parent is refused with ``DatatypeMismatch``, the
    walk dies inside that revision's own ``upgrade()`` at the CREATE TABLE, and
    no follow-up revision can repair it because nothing after it ever runs.

    The rule is the coarse one - any reference to a native UUID type inside a
    span, whether or not this test can prove the type reaches a column that
    carries a foreign key. Three of the offenders hid their foreign key behind
    an interpolated target string, and a detector that insists on a literal
    calls those clean. A span holding no native uuid at all cannot produce a
    mismatch in either direction, and that is provable without resolving a
    single name.

    The population is the graph, not the round-trip window. Sixteen offenders
    were inside the one span the cycle above exercises; ten were not, had never
    been executed by anything, and were found by measuring rather than by
    running. ``tests/pg/test_migration_uuid_convention.py`` keeps the frozen
    remainder - the revisions no merge span reaches - from growing.
    """
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    revision_files = sorted(versions_dir.glob("*.py"))
    span, merges = _merge_span_revisions(_revision_graph())

    declaring: dict[str, list[str]] = {}
    offenders: dict[str, list[str]] = {}
    for path in revision_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sites = _native_uuid_sites(tree)
        if not sites:
            continue
        declaring[path.name] = sites
        revision = _revision_id_of(tree)
        # A header this test cannot read is not evidence of safety: it is a
        # revision that cannot be placed in the graph, so it counts as inside.
        if revision is None or revision in span:
            offenders[path.name] = sites

    # Population beside the verdict. A gate is worth its denominator, and this
    # one is green because the offenders were repaired rather than because the
    # scan was narrow: every revision on disk is read, not the fourteen in the
    # round-trip window.
    print(
        f"revisions scanned: {len(revision_files)}; merge nodes: {merges}; "
        f"revisions a merge span re-applies: {len(span)}; "
        f"revisions declaring a native uuid: {len(declaring)}; "
        f"of those, inside a merge span: {len(offenders)}"
    )

    detail = "\n".join(f"  {name}\n    " + "\n    ".join(sites) for name, sites in sorted(offenders.items()))
    assert not offenders, (
        "These revisions declare a native PostgreSQL uuid column and sit inside a merge "
        "node's one-step downgrade span, so a downgrade re-applies them against a schema "
        f"create_all built as character varying(36):\n{detail}\n\n"
        "Use sa.String(36), or the GUID type from app.database, to match what create_all "
        "builds. Adding the file to UUID_COLUMN_ALLOWLIST is not the fix: that list is for "
        "revisions no walk reaches, and this one is reached."
    )


def test_the_chain_only_column_exemptions_are_still_earned() -> None:
    """Every ``CHAIN_ONLY_COLUMNS`` entry must still describe a live divergence.

    An exemption that outlives the divergence it records is a permission that
    protects nothing, and the next genuine inconsistency on that column would be
    waved through. Two things have to hold, and each fails in its own direction:
    the models must still not declare the column, and exactly one revision - the
    one the entry names - may mention it.

    The second check is text rather than AST on purpose. A revision repairing
    the divergence has to name the column whatever shape it uses to drop it:
    ``op.drop_column``, a batch operation, or raw SQL. Matching the word means
    no repair can land without this test noticing, which is more than a
    resolver-based version could promise.
    """
    _import_all_models()

    from app.database import Base

    declared = {f"{table.name}.{column.name}" for table in Base.metadata.tables.values() for column in table.columns}
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    revision_files = sorted(versions_dir.glob("*.py"))
    sources = {path.name: path.read_text(encoding="utf-8") for path in revision_files}

    back_in_the_models = sorted(column for column in CHAIN_ONLY_COLUMNS if column in declared)
    drifted: dict[str, tuple[str, list[str]]] = {}
    for qualified, (owner, _reason) in CHAIN_ONLY_COLUMNS.items():
        word = re.compile(rf"\b{re.escape(qualified.split('.')[-1])}\b")
        naming = sorted(name for name, text_of in sources.items() if word.search(text_of))
        if naming != [owner]:
            drifted[qualified] = (owner, naming)

    print(
        f"revisions scanned: {len(revision_files)}; columns in Base.metadata: {len(declared)}; "
        f"chain-only exemptions: {len(CHAIN_ONLY_COLUMNS)}; back in the models: "
        f"{len(back_in_the_models)}; naming a revision other than their owner: {len(drifted)}"
    )

    assert not back_in_the_models, (
        "These columns are exempted in CHAIN_ONLY_COLUMNS but Base.metadata declares them "
        f"again, so create_all builds them and the exemption is dead: {back_in_the_models}"
    )
    assert not drifted, (
        "These CHAIN_ONLY_COLUMNS entries no longer describe the tree. Each should be named "
        "by exactly one revision, the one that adds it; a second revision means the chain "
        "was repaired and the entry has to go:\n  "
        + "\n  ".join(f"{column}: owner {owner}, named by {naming}" for column, (owner, naming) in drifted.items())
    )


def test_dev_db_is_not_being_targeted(pg_throwaway: str) -> None:
    """Tripwire: throwaway-DB fixture must override the dev-DB env var.

    If anyone copy-pastes this file or the fixture goes wrong, we want
    a screaming failure rather than silent corruption of the dev DB.
    """
    assert "openestimate.db" not in os.environ.get("DATABASE_SYNC_URL", ""), (
        "Test fixture failed to override DATABASE_SYNC_URL — would have written to the dev DB. Aborting."
    )
    # The active DATABASE_SYNC_URL must point at a throwaway PG database.
    active_url = os.environ.get("DATABASE_SYNC_URL", "")
    assert "postgresql" in active_url, f"Expected DATABASE_SYNC_URL to be a PostgreSQL URL, got: {active_url!r}"
    assert "oe_mig_rt_" in active_url, (
        f"Expected DATABASE_SYNC_URL to contain the throwaway DB name prefix 'oe_mig_rt_', got: {active_url!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  Data migrations
#
#  A data migration cannot be checked the way the schema ones above are.
#  create_all builds the catalogue table empty and the seed catalogue in
#  the source tree already carries the post-rename names, so running
#  v3271 against a fresh test database updates zero rows and passes
#  without executing a single branch. The rows it exists to repair only
#  occur on a database seeded before the rename, so the test has to write
#  that state itself.
# ─────────────────────────────────────────────────────────────────────

_SYSTEM_TABLE = "oe_formwork_system"

_INSERT_SYSTEM = text(
    f"""
    INSERT INTO {_SYSTEM_TABLE}
        (id, created_at, updated_at, name, system_type, supplier, material,
         reuses_max, unit_rate, erect_strike_rate, strip_time_days, currency)
    VALUES
        (:id, now(), now(), :name, 'wall', :supplier, 'steel',
         100, 65.00, 16.00, 1, '')
    """  # noqa: S608 - table name is a module constant, not user input
)


def _run_revision_upgrade(sync_url: str, revision: str) -> None:
    """Execute one revision's ``upgrade()`` body against ``sync_url``.

    Not ``command.upgrade``: the database is stamped at head, so alembic
    would consider this revision already applied and do nothing. Binding
    the body to a connection runs the code under test directly.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    cfg = _make_alembic_config(sync_url)
    module = ScriptDirectory.from_config(cfg).get_revision(revision).module

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            context = MigrationContext.configure(conn)
            with Operations.context(context):
                module.upgrade()
    finally:
        engine.dispose()


def _systems_by_id(sync_url: str) -> dict[str, tuple[str, str | None]]:
    """Return ``{id: (name, supplier)}`` for every catalogue row."""
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT id, name, supplier FROM {_SYSTEM_TABLE}")  # noqa: S608
            ).all()
    finally:
        engine.dispose()
    return {str(row[0]): (row[1], row[2]) for row in rows}


def test_v3271_renames_only_the_rows_it_should(pg_throwaway: str) -> None:
    """v3271 renames trademarked catalogue rows without touching tenant edits.

    Five rows covering every branch the revision has:

    * a plain trademarked row, which must be renamed and lose its supplier;
    * the one pair carrying a non-ASCII character, which must move too - if
      the literal in the migration ever stops byte-matching the column, this
      is the row that catches it;
    * a trademarked row whose supplier the tenant repointed at their own hire
      yard, where the name must move and that supplier value must survive;
    * a trademarked row whose replacement name is already present, which the
      duplicate guard must leave alone;
    * a row the tenant renamed themselves, which must not be touched at all
      even though its supplier still reads as a brand.
    """
    cfg = _make_alembic_config(pg_throwaway)
    _create_all_then_stamp(pg_throwaway, cfg)

    plain = str(uuid.uuid4())
    non_ascii = str(uuid.uuid4())
    tenant_supplier = str(uuid.uuid4())
    would_duplicate = str(uuid.uuid4())
    already_present = str(uuid.uuid4())
    tenant_renamed = str(uuid.uuid4())

    seeded = [
        {"id": plain, "name": "Doka Framax Xlife", "supplier": "Doka"},
        {"id": non_ascii, "name": "Hünnebeck MANTO", "supplier": "Hünnebeck"},
        {"id": tenant_supplier, "name": "PERI MAXIMO", "supplier": "Central hire yard"},
        {"id": would_duplicate, "name": "Doka Dokadek 30", "supplier": "Doka"},
        {"id": already_present, "name": "Aluminium slab deck panel", "supplier": None},
        {"id": tenant_renamed, "name": "Site-built wall shutter", "supplier": "Doka"},
    ]
    engine = create_engine(pg_throwaway)
    try:
        with engine.begin() as conn:
            for row in seeded:
                conn.execute(_INSERT_SYSTEM, row)
    finally:
        engine.dispose()

    _run_revision_upgrade(pg_throwaway, "v3271_formwork_debrand")
    after = _systems_by_id(pg_throwaway)

    assert after[plain] == ("Steel framed wall panel", None)
    assert after[non_ascii] == ("Crane-set steel wall panel", None), (
        "the non-ASCII pair did not move - the literal no longer matches the column"
    )
    assert after[tenant_supplier] == (
        "Steel wall panel, single-side tie",
        "Central hire yard",
    ), "a supplier the tenant set themselves was cleared"
    assert after[would_duplicate] == ("Doka Dokadek 30", "Doka"), (
        "renamed onto a name already present for this tenant, creating a duplicate"
    )
    assert after[already_present] == ("Aluminium slab deck panel", None)
    assert after[tenant_renamed] == ("Site-built wall shutter", "Doka"), "a row the tenant renamed was rewritten"

    # Idempotent: a second run must be a no-op, including for the row the
    # duplicate guard declined to touch.
    _run_revision_upgrade(pg_throwaway, "v3271_formwork_debrand")
    assert _systems_by_id(pg_throwaway) == after


def test_v3271_lands_an_upgraded_install_on_the_shipped_catalogue(pg_throwaway: str) -> None:
    """An upgraded install ends up with the names a fresh install has.

    This test cannot check the *old* names and does not try to. It seeds from
    ``_RENAMES``, so a mistyped old-name literal would be inserted mistyped,
    found renamed, and passed - measured, that exact mutation went green here
    while ``test_v3271_renames_only_the_rows_it_should`` caught it, because
    that one spells the trademarked names out independently of the migration.
    Drift in the old names is its job, not this one's.

    What this test owns is the other half: the migration and the shipped
    catalogue must agree on where the rows land. ``default_seed_systems()`` is
    the denominator, so re-wording a catalogue row without updating the
    revision fails here rather than leaving upgraded and fresh installs with
    two different names for the same system.
    """
    cfg = _make_alembic_config(pg_throwaway)
    _create_all_then_stamp(pg_throwaway, cfg)

    module = ScriptDirectory.from_config(cfg).get_revision("v3271_formwork_debrand").module
    renames = module._RENAMES  # noqa: SLF001 - the mapping is the thing under test

    from app.modules.formwork.schemas import default_seed_systems

    catalogue = {row["name"] for row in default_seed_systems()}
    written = {new_name for _old, _supplier, new_name in renames}
    assert written <= catalogue, (
        f"revision renames rows to names a fresh install does not have: {sorted(written - catalogue)}"
    )
    assert len(renames) == 8, f"expected eight renamed rows, mapping carries {len(renames)}"

    engine = create_engine(pg_throwaway)
    try:
        with engine.begin() as conn:
            for old_name, old_supplier, _new_name in renames:
                conn.execute(
                    _INSERT_SYSTEM,
                    {"id": str(uuid.uuid4()), "name": old_name, "supplier": old_supplier},
                )
    finally:
        engine.dispose()

    _run_revision_upgrade(pg_throwaway, "v3271_formwork_debrand")

    after = _systems_by_id(pg_throwaway)
    surviving = {name for name, _supplier in after.values()}
    assert surviving <= catalogue, f"rows left carrying a name no fresh install has: {sorted(surviving - catalogue)}"

    suppliers = {supplier for _name, supplier in after.values()}
    assert suppliers == {None}, f"brand suppliers still in the catalogue: {suppliers - {None}}"


# ─────────────────────────────────────────────────────────────────────
#  v3272 - the assignment -> schedule activity link
# ─────────────────────────────────────────────────────────────────────

_ASSIGNMENT_TABLE = "oe_resources_assignment"
_ACTIVITY_FK = "fk_oe_resources_assignment_activity_id_oe_schedule_activity"


def _activity_fk(sync_url: str) -> dict[str, object] | None:
    """Reflect the assignment -> activity foreign key back, or None."""
    engine = create_engine(sync_url)
    try:
        for fk in inspect(engine).get_foreign_keys(_ASSIGNMENT_TABLE):
            if fk.get("name") == _ACTIVITY_FK:
                return fk
        return None
    finally:
        engine.dispose()


def test_v3272_creates_the_activity_foreign_key(pg_throwaway: str) -> None:
    """The FK is the migration's whole payload, and only this asserts it.

    ``create_all`` already lays down ``activity_id`` and its index, because
    the column is on the model. What it cannot lay down is the constraint:
    the ORM deliberately carries no ``ForeignKey`` for it, so the resources
    module still imports on an install where the schedule module is absent.
    That leaves the migration as the only thing that ever creates it.

    A migration that ran without raising is not a migration that created a
    constraint. ``upgrade()`` returns early when the target table is missing
    and swallows a refused ``create_foreign_key``, and both of those silent
    paths look exactly like success from outside. Reflecting the constraint
    back is what tells them apart.
    """
    cfg = _make_alembic_config(pg_throwaway)
    _create_all_then_stamp(pg_throwaway, cfg)

    # Negative control. Without it this test cannot tell the migration's work
    # from what the model had already produced.
    assert _activity_fk(pg_throwaway) is None, "create_all already made the FK - this test would prove nothing"

    _run_revision_upgrade(pg_throwaway, "v3272_assignment_activity_link")

    fk = _activity_fk(pg_throwaway)
    assert fk is not None, f"{_ACTIVITY_FK} absent after the revision ran"
    assert fk["referred_table"] == "oe_schedule_activity"
    assert fk["constrained_columns"] == ["activity_id"]
    assert fk["referred_columns"] == ["id"]

    # Deleting a Gantt bar must not take the booking history with it.
    options = fk.get("options") or {}
    assert isinstance(options, dict)
    assert options.get("ondelete") == "SET NULL", f"expected SET NULL, reflected {options!r}"


def test_v3272_upgrade_is_idempotent(pg_throwaway: str) -> None:
    """Running it twice must not raise, and must leave one constraint.

    Every guard in the body is an ``if not present`` check, so a second run
    is the cheapest test of all of them at once.
    """
    cfg = _make_alembic_config(pg_throwaway)
    _create_all_then_stamp(pg_throwaway, cfg)

    _run_revision_upgrade(pg_throwaway, "v3272_assignment_activity_link")
    _run_revision_upgrade(pg_throwaway, "v3272_assignment_activity_link")

    engine = create_engine(pg_throwaway)
    try:
        fks = inspect(engine).get_foreign_keys(_ASSIGNMENT_TABLE)
    finally:
        engine.dispose()

    assert [fk["name"] for fk in fks].count(_ACTIVITY_FK) == 1


def test_v3272_rebuilds_a_column_the_constraint_still_fits(pg_throwaway: str) -> None:
    """After a downgrade, the re-upgrade must rebuild the column at its own type.

    The parametrized round-trip above compares column *names*, so a column
    that comes back at the wrong type reads as unchanged. This revision was
    first written declaring ``activity_id`` as native ``uuid``, copying the
    idiom of the neighbouring v3014 columns; PostgreSQL then refused the
    constraint against ``oe_schedule_activity.id``, which ``GUID`` makes
    ``varchar(36)`` on every dialect. What proves the type is right is the
    constraint standing after the cycle, not the column existing.
    """
    cfg = _make_alembic_config(pg_throwaway)
    _create_all_then_stamp(pg_throwaway, cfg)

    command.stamp(cfg, "v3272_assignment_activity_link")
    command.downgrade(cfg, "v3271_formwork_debrand")
    command.upgrade(cfg, "v3272_assignment_activity_link")

    engine = create_engine(pg_throwaway)
    try:
        insp = inspect(engine)
        column = next(c for c in insp.get_columns(_ASSIGNMENT_TABLE) if c["name"] == "activity_id")
    finally:
        engine.dispose()

    assert "CHAR" in str(column["type"]).upper(), f"activity_id came back as {column['type']!r}"
    fk = _activity_fk(pg_throwaway)
    assert fk is not None, "the constraint did not survive a downgrade and re-upgrade"
    assert (fk.get("options") or {}).get("ondelete") == "SET NULL"
