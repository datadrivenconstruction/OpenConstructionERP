"""Re-export the core JobRun ORM model for module-loader registration.

The actual table lives in :mod:`app.core.job_run` so the runner code
doesn't have to import a module-package to access its own row type.
This thin re-export lets the loader's autodiscovery (``import
{module}.models``) still find the model and register it with
``Base.metadata`` for Alembic.
"""

from app.core.job_run import JobRun  # noqa: F401

__all__ = ["JobRun"]
