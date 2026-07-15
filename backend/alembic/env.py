"""Alembic migration environment​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Auto-discovers all module models via Base.metadata.

Fresh-blank-DB handling
-----------------------
The canonical install path boots the FastAPI app first, which calls
``Base.metadata.create_all()`` to materialise every table at the
latest schema. Alembic is then used only to track future column
additions. Ops who instead run ``alembic upgrade head`` against a
fresh blank DB without booting the app first used to hit a cascade
of crashes — the very first batch_alter_table on a table whose new
FK targets ``oe_users_user`` failed with ``no such table:`` because
no migration ever creates ``oe_users_user`` (it lives only in the
ORM ``Base.metadata``). Later migrations also crash with ``add_column``
on tables that no migration ever created (oe_assemblies_component,
oe_costs_item, oe_dwg_takeoff_drawing_version, ...). This is the
same class of bug closed for the seed loader in v4.4.1 (#154).

The fix here is to detect a fresh blank DB on alembic entry (no
``alembic_version`` table and no other tables) and short-circuit:
create every table at the latest schema via ``Base.metadata.create_all``
and stamp the alembic version directly at the head. That mirrors
exactly what the app boot path does, and keeps ``alembic upgrade head``
on a non-empty already-stamped DB on the normal migration code path
so future column-add migrations still execute correctly.
"""

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
from app.modules.schedule_intelligence import models as _sched_intel  # noqa: F401, E402
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
# spa_schedule_parties``, is 51 characters, and 23 revisions exceed 32. SQLite
# silently ignores declared VARCHAR length, so this was invisible there, but
# PostgreSQL enforces it strictly: a plain ``alembic upgrade head`` (or any
# incremental up/downgrade that records one of those revisions) fails with
# ``value too long for type character varying(32)`` the moment alembic writes
# the revision into its own version table. The production boot path never hits
# this because it does create_all + stamp head, jumping straight to the short
# head id - but the canonical incremental migration path on PostgreSQL was
# broken. ``version_table_impl`` is a documented override hook, so we widen the
# column to VARCHAR(255). Existing databases keep whatever table their stamp
# already created (head id is short); the wider column only applies when the
# version table is created fresh.
# --------------------------------------------------------------------------
from alembic.ddl.impl import DefaultImpl as _AlembicDefaultImpl  # noqa: E402


def _wide_version_table_impl(  # noqa: ANN202
    self,  # noqa: ANN001
    *,
    version_table: str,
    version_table_schema,  # noqa: ANN001
    version_table_pk: bool,
    **kw,  # noqa: ANN003, ARG001
):
    vt = sa.Table(
        version_table,
        sa.MetaData(),
        sa.Column("version_num", sa.String(255), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        vt.append_constraint(sa.PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
    return vt


_AlembicDefaultImpl.version_table_impl = _wide_version_table_impl


config = context.config
settings = get_settings()


# Render UUID columns properly for autogenerate
def render_item(type_, obj, autogen_context):
    """Custom render for UUID type."""
    if type_ == "type" and hasattr(obj, "__class__") and obj.__class__.__name__ == "GUID":
        return "sa.String(36)"
    return False


if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
