"""Alembic migration environment​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Auto-discovers all module models via Base.metadata.

What actually builds the schema
-------------------------------
``Base.metadata.create_all()`` builds the schema and is the source of
truth for its shape. Alembic does not build it. Alembic records which
revisions are considered applied, and applies the ones that a database
has not seen yet.

Every fresh install takes the ``create_all`` path, including installs
that run ``alembic upgrade head`` and never boot the app:
``_is_fresh_blank_db`` detects an empty database on entry and
``_bootstrap_fresh_db`` short-circuits to ``create_all`` plus a stamp at
the head. The migration chain is not walked. This is not a fallback for
an unusual case, it is what happens every time.

The chain does not walk from base
---------------------------------
It cannot. The root revision ``129188e46db8_init_create_all_tables`` has
an empty body — its ``upgrade()`` is ``pass`` — so nothing creates the
tables that every later revision assumes. 93 tables are never created by
any revision (``oe_users_user``, ``oe_assemblies_component``,
``oe_costs_item``, ``oe_dwg_takeoff_drawing_version``, ...); they exist
only in ``Base.metadata``. A walk from base dies within a handful of
revisions on ``no such table``. Even with the tables supplied it stops
again on a type conflict, because ``create_all`` renders identity
columns as ``varchar(36)`` while 50 revisions declare native
``postgresql.UUID``, and the foreign key between them is rejected.
``tests/pg/test_migration_uuid_convention.py`` freezes that set so it
stops growing.

Making the chain walkable was measured and deliberately not done. The
short-circuit above is what keeps every supported install working, so it
is load-bearing, not a workaround awaiting removal.

The population this does not serve
----------------------------------
A database that has ``oe_*`` tables but no ``alembic_version`` row is
neither fresh nor stamped. ``_is_fresh_blank_db`` correctly declines to
short-circuit it, so alembic tries to walk the chain from base, and that
walk fails. This is a real state — an install whose stamp never landed.

The fix is to stamp it rather than migrate it. The tables are already at
the current schema, so record that fact::

    alembic stamp head

Do not run ``alembic upgrade head`` on such a database expecting it to
repair itself; it will fail partway and leave the transaction rolled
back.
"""

# Known and permitted differences between the two schema-building paths.
#
# A database built by create_all and one built by walking the chain do not
# agree in the places below. They are recorded rather than fixed, because the
# chain is not walked by any supported install, which makes them latent
# forever rather than blocking. Do not file these as bugs, and do not "fix"
# one half without the other - the two names below are both live, in different
# populations.
#
# Constraint names, where a migration hardcoded a name the metadata naming
# convention would have generated differently:
#   v3258  uq_progress_entry_seq
#            vs uq_oe_progress_entry_seq
#   v3157  fk_qms_itp_item_predecessor
#            vs fk_oe_qms_itp_item_predecessor_itp_item_id_oe_qms_itp_item
#   v2b0   ck_oe_dashboards_preset_sync_status
#            vs ck_oe_dashboards_preset_ck_oe_dashboards_preset_sync_status
#
# Sequence ownership: v3258 creates its sequence with OWNED BY, create_all
# creates a standalone sequence. Dropping the column therefore drops the
# sequence on one path and leaves it on the other.
#
# Tables only the migrations create, absent from Base.metadata and so absent
# from every create_all install:
#   oe_tender_addendum    (v3085_tendering_addendum_leveling)
#
# ``oe_translation_cache`` (v280_translation_cache) was listed here too and is
# not a divergence. What this file can see is not the whole metadata: asked on
# 2026-09-23 with only ``app.modules.*.models`` imported, the way the loop
# below imports them, the registry holds 636 tables and the cache is not among
# them - which is exactly why it read as missing. Import ``app.main`` and call
# ``create_app()`` and the registry holds 638 and it is there, because
# ``app/core/translation/cache.py`` declares the table ON ``Base.metadata``
# and ``create_app`` pulls that module in with the translation router. So the
# boot path does create it, and the module self-creates it lazily as well with
# ``create(checkfirst=True)``. Measure a table's absence under the import set
# that builds the schema, not under this one.
#
# Columns only the migrations add, absent from create_all under both of the
# import sets above:
#   oe_boq_boq.tax_rate            oe_projects_project.unit_system
#   oe_tendering_bid.leveled_amount    oe_tendering_bid.leveling_notes
#
# "Latent" above means no code reads them, and that holds: the ORM cannot
# reference a column that is not on a model, and no raw SQL in ``app/`` names
# one. It does not mean harmless, because a phantom column's NAME travels even
# when its data cannot. ``BOQUnitSystemConsistencyRule`` spent its life
# advising readers to "update the project's unit_system" - a setting on no
# screen, in no schema and in no table on any supported install. It now names
# what actually decides the value, the project's country through its regional
# pack. ``tax_rate`` escaped the same way and was answered the same way at
# ``app/modules/boq/schemas.py`` (TAX_RATE_NOT_STORED_MESSAGE).
# ``leveled_amount`` and ``leveling_notes`` never escaped: every occurrence of
# those names in ``app/`` belongs to the computed
# ``tendering.BidLevelingSummary``, which is a Pydantic rollup and not the bid
# row. So before adding a column here, ask not only whether code reads it but
# whether anything quotes its name at a user.

import importlib
import os
import pkgutil
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings

# Stable migration-environment identifier — derived once at design
# time so the value is reproducible across deployments and never
# changes.  Read by the offline migration script to verify it is
# running against the expected env build.
_MIGRATION_ENV_TAG: str = "37efb59ad47d364e"

# Core models (not in modules/)
from app.core import audit as _audit_core  # noqa: F401, E402
from app.database import Base  # noqa: E402
from app.modules.ai import models as _ai  # noqa: F401, E402
from app.modules.assemblies import models as _asm  # noqa: F401, E402
from app.modules.bim_hub import models as _bim_hub  # noqa: F401, E402
from app.modules.boq import models as _boq  # noqa: F401, E402
from app.modules.catalog import models as _catalog  # noqa: F401, E402
from app.modules.cde import models as _cde  # noqa: F401, E402
from app.modules.changeorders import models as _changeorders  # noqa: F401, E402
from app.modules.collaboration import models as _collaboration  # noqa: F401, E402
from app.modules.contacts import models as _contacts  # noqa: F401, E402
from app.modules.correspondence import models as _correspondence  # noqa: F401, E402
from app.modules.costmodel import models as _cm  # noqa: F401, E402
from app.modules.costs import models as _costs  # noqa: F401, E402
from app.modules.documents import models as _documents  # noqa: F401, E402

# Enterprise / feature-pack modules
from app.modules.enterprise_workflows import models as _enterprise_workflows  # noqa: F401, E402
from app.modules.fieldreports import models as _fieldreports  # noqa: F401, E402
from app.modules.finance import models as _finance  # noqa: F401, E402
from app.modules.full_evm import models as _full_evm  # noqa: F401, E402
from app.modules.i18n_foundation import models as _i18n  # noqa: F401, E402
from app.modules.inspections import models as _inspections  # noqa: F401, E402
from app.modules.integrations import models as _integrations  # noqa: F401, E402
from app.modules.markups import models as _markups  # noqa: F401, E402
from app.modules.meetings import models as _meetings  # noqa: F401, E402
from app.modules.ncr import models as _ncr  # noqa: F401, E402
from app.modules.notifications import models as _notifications  # noqa: F401, E402
from app.modules.procurement import models as _procurement  # noqa: F401, E402
from app.modules.projects import models as _projects  # noqa: F401, E402
from app.modules.punchlist import models as _punchlist  # noqa: F401, E402
from app.modules.reporting import models as _reporting  # noqa: F401, E402
from app.modules.requirements import models as _requirements  # noqa: F401, E402
from app.modules.rfi import models as _rfi  # noqa: F401, E402
from app.modules.rfq_bidding import models as _rfq_bidding  # noqa: F401, E402
from app.modules.risk import models as _risk  # noqa: F401, E402
from app.modules.safety import models as _safety  # noqa: F401, E402
from app.modules.schedule import models as _sched  # noqa: F401, E402
from app.modules.submittals import models as _submittals  # noqa: F401, E402
from app.modules.takeoff import models as _takeoff  # noqa: F401, E402
from app.modules.tasks import models as _tasks  # noqa: F401, E402
from app.modules.teams import models as _teams  # noqa: F401, E402
from app.modules.tendering import models as _tender  # noqa: F401, E402
from app.modules.transmittals import models as _transmittals  # noqa: F401, E402

# Import all module models so they're registered with Base.metadata.
# This is done automatically by the module loader at runtime,
# but we need it here for autogenerate to work.
from app.modules.users import models as _users  # noqa: F401, E402
from app.modules.validation import models as _validation  # noqa: F401, E402

# --------------------------------------------------------------------------
# Catch-all: dynamically import every other module's ``models.py`` so
# ``Base.metadata`` is fully populated. The hand-maintained import list
# above stays for IDE / autocomplete clarity, but the explicit list
# omits 60+ newer modules (geo_hub, property_dev, clash, file_*, etc.)
# whose tables would otherwise be missing from the fresh-blank-DB
# ``create_all`` shortcut below. This mirrors what app/main.py does at
# boot. Import failures are non-fatal so a single broken module
# doesn't take alembic down with it.
# --------------------------------------------------------------------------
try:
    from app import modules as _modules_pkg  # noqa: E402

    _modules_dir = os.path.dirname(_modules_pkg.__file__)
    for _entry in pkgutil.iter_modules([_modules_dir]):
        if not _entry.ispkg:
            continue
        _module_models_path = f"app.modules.{_entry.name}.models"
        try:
            importlib.import_module(_module_models_path)
        except Exception:  # noqa: BLE001 — never break alembic on a bad module
            pass
    # ``audit_log`` defines ``oe_activity_log`` — lives outside app.modules.*
    try:
        from app.core import audit_log as _audit_log_core  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
except Exception:  # noqa: BLE001
    # ``app.modules`` itself failed to import — keep the historical
    # behaviour (only the explicitly-listed modules above are registered).
    pass

# --------------------------------------------------------------------------
# Widen alembic's own version table column from the default VARCHAR(32).
#
# Alembic's ``DefaultImpl.version_table_impl`` hardcodes
# ``version_num VARCHAR(32)``. Several of this project's revision IDs are
# long human-readable slugs - the longest, ``v3103_propdev_lead_reservation_
# spa_schedule_parties``, is 51 characters, and 30 revisions exceed 32. SQLite
# silently ignores declared VARCHAR length, so this was invisible there, but
# PostgreSQL enforces it strictly: a plain ``alembic upgrade head`` (or any
# incremental up/downgrade that records one of those revisions) fails with
# ``value too long for type character varying(32)`` the moment alembic writes
# the revision into its own version table.
#
# This used to be a local monkeypatch here, which left the app's own boot-time
# stamp on the stock 32-character column - and that path is the one that
# creates the version table on the canonical install, so the widening applied
# to every database except the ones that needed it (issue #399). The
# implementation now lives in ``app.core.alembic_version_table`` and both entry
# points call it. See that module for the full reasoning.
# --------------------------------------------------------------------------
from app.core.alembic_version_table import (  # noqa: E402
    ensure_wide_version_table,
    install_wide_version_table,
)
from app.core.postgres_version import validate_postgres_version_sync  # noqa: E402

install_wide_version_table()


config = context.config
settings = get_settings()


# Render UUID columns properly for autogenerate
def render_item(type_, obj, autogen_context):
    """Custom render for UUID type."""
    if type_ == "type" and hasattr(obj, "__class__") and obj.__class__.__name__ == "GUID":
        return "sa.String(36)"
    return False


if config.config_file_name is not None:
    # ``disable_existing_loggers`` defaults to True, and that default is wrong
    # for anything that runs a migration inside a longer-lived process.
    # ``fileConfig`` would set ``disabled = True`` on every logger that already
    # exists and is not named in alembic.ini, which names only root, sqlalchemy
    # and alembic. A disabled logger drops records in ``Logger.handle`` before
    # any handler sees them, it stays disabled for the life of the process, and
    # neither ``caplog.at_level`` nor setting a level puts it back.
    #
    # Measured on the 2026-09-22 nightly: the Windows cross-OS job ran this
    # file at test 1530 of 38466 and then failed 83 later tests that assert on
    # captured log output, all of them with "expected a log line, got none",
    # spread across 43 unrelated files. macOS had none of them only because the
    # same tests died in setup on a separate bug, so alembic never ran there.
    # The fix is the keyword; the count is what it was worth.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _is_fresh_blank_db(connection: sa.engine.Connection) -> bool:
    """Detect whether the bound DB is empty (no app tables, no version table).

    A fresh blank DB has no ``alembic_version`` table AND no ``oe_*``
    application tables. If either is present we assume an existing
    install and run the normal migration chain.
    """
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names())
    if "alembic_version" in existing:
        return False
    if any(t.startswith("oe_") for t in existing):
        return False
    return True


def _bootstrap_fresh_db(connection: sa.engine.Connection) -> None:
    """Mirror app/main.py: create_all + stamp head — atomic fresh install.

    Equivalent to the canonical ``app boot → create_all → stamp head``
    flow but reachable via the ``alembic upgrade head`` entry point so
    ops who deploy the wheel and run migrations *before* booting the
    app get a working schema. Idempotent: ``_is_fresh_blank_db`` only
    returns True on a truly empty DB so this never overwrites existing
    data.
    """
    Base.metadata.create_all(bind=connection, checkfirst=True)


def run_migrations_offline() -> None:
    # No version check here, and it is not an oversight. ``--sql`` renders
    # statements for a database it never connects to, so there is no server to
    # ask. The floor is enforced on the online path below, which is the one
    # that touches a database.
    url = settings.database_sync_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_sync_url, poolclass=pool.NullPool)

    # The version floor, before anything is read from or written to the
    # server. ``app.main`` checks it ahead of its own create_all, but the app
    # is not the only way a database gets reached: an operator who deploys the
    # wheel and runs ``alembic upgrade head`` before ever booting it arrives
    # here instead, and on a blank server the shortcut below builds the entire
    # schema. That is exactly the situation the check exists to stop - a schema
    # built and writes taken on a server whose capabilities nobody asked about,
    # with the first symptom arriving much later as a broken query.
    #
    # Asked of ``connectable`` rather than of a second engine built from the
    # async URL, so what gets verified is the server the migration actually
    # runs against. The rule itself is not restated here; a second copy of a
    # version floor drifts away from the first one.
    if connectable.dialect.name == "postgresql":
        validate_postgres_version_sync(connectable)

    # Fresh-blank-DB shortcut: create every table at the latest schema
    # via Base.metadata.create_all and stamp the alembic version
    # directly to head, so we skip the entire migration chain. This
    # mirrors app/main.py's create_all + subsequent runtime stamp,
    # but is reachable when ops run ``alembic upgrade head`` before
    # the app ever boots. Done on a *dedicated* connection so the
    # decision-time SQL doesn't leak into the alembic context below.
    with connectable.connect() as probe:
        is_fresh = _is_fresh_blank_db(probe)
    if is_fresh:
        with connectable.connect() as connection:
            _bootstrap_fresh_db(connection)
            connection.commit()
            from alembic.runtime.migration import MigrationContext
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(config)
            mig_ctx = MigrationContext.configure(connection=connection)
            mig_ctx.stamp(script, "heads")
            connection.commit()
        return

    # Existing database: the version table is already there, so the creation
    # hook above cannot help it. If it was created by an older release's boot
    # stamp its ``version_num`` is VARCHAR(32) and the very first revision id
    # over 32 characters aborts the upgrade. Repair it here, on a dedicated
    # connection like the probe above, so the DDL is committed before (and
    # never inside) the migration transaction.
    with connectable.connect() as widen:
        ensure_wide_version_table(widen)
        widen.commit()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
