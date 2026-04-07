"""Alembic migration environment.

Auto-discovers all module models via Base.metadata.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.database import Base
from app.modules.ai import models as _ai  # noqa: F401
from app.modules.assemblies import models as _asm  # noqa: F401
from app.modules.bim_hub import models as _bim_hub  # noqa: F401
from app.modules.boq import models as _boq  # noqa: F401
from app.modules.catalog import models as _catalog  # noqa: F401
from app.modules.collaboration import models as _collaboration  # noqa: F401
from app.modules.cde import models as _cde  # noqa: F401
from app.modules.contacts import models as _contacts  # noqa: F401
from app.modules.correspondence import models as _correspondence  # noqa: F401
from app.modules.changeorders import models as _changeorders  # noqa: F401
from app.modules.costmodel import models as _cm  # noqa: F401
from app.modules.costs import models as _costs  # noqa: F401
from app.modules.documents import models as _documents  # noqa: F401
from app.modules.fieldreports import models as _fieldreports  # noqa: F401
from app.modules.finance import models as _finance  # noqa: F401
from app.modules.i18n_foundation import models as _i18n  # noqa: F401
from app.modules.inspections import models as _inspections  # noqa: F401
from app.modules.markups import models as _markups  # noqa: F401
from app.modules.meetings import models as _meetings  # noqa: F401
from app.modules.ncr import models as _ncr  # noqa: F401
from app.modules.procurement import models as _procurement  # noqa: F401
from app.modules.projects import models as _projects  # noqa: F401
from app.modules.punchlist import models as _punchlist  # noqa: F401
from app.modules.reporting import models as _reporting  # noqa: F401
from app.modules.requirements import models as _requirements  # noqa: F401
from app.modules.rfi import models as _rfi  # noqa: F401
from app.modules.risk import models as _risk  # noqa: F401
from app.modules.safety import models as _safety  # noqa: F401
from app.modules.schedule import models as _sched  # noqa: F401
from app.modules.submittals import models as _submittals  # noqa: F401
from app.modules.takeoff import models as _takeoff  # noqa: F401
from app.modules.tasks import models as _tasks  # noqa: F401
from app.modules.teams import models as _teams  # noqa: F401
from app.modules.tendering import models as _tender  # noqa: F401
from app.modules.transmittals import models as _transmittals  # noqa: F401

from app.modules.notifications import models as _notifications  # noqa: F401

# Import all module models so they're registered with Base.metadata.
# This is done automatically by the module loader at runtime,
# but we need it here for autogenerate to work.
from app.modules.users import models as _users  # noqa: F401

# Core models (not in modules/)
from app.core import audit as _audit_core  # noqa: F401

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

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
