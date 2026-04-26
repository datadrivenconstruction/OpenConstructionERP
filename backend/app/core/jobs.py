# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Celery application factory — RFC 34 §4 W0.1.

The Celery app is the thin transport layer that hands JobRun ids to
worker processes. It is intentionally framework-agnostic: business
handlers are registered via :mod:`app.core.job_runner`, never via raw
``@celery_app.task`` decorators. This keeps the worker entry point a
single, well-tested generic dispatcher (``oe.dispatch_job``) and lets
modules add new background work without touching this file.

Configuration is locked to JSON serialization (so payloads remain
inspectable in Redis), UTC timestamps (so log correlation is sane
across regions), and a 10-minute hard timeout (so a misbehaving task
cannot pin a worker forever).

Environment overrides:
    OE_CELERY_BROKER_URL   — default ``redis://localhost:6379/1``
    OE_CELERY_RESULT_BACKEND — default ``redis://localhost:6379/1``
"""

from __future__ import annotations

import os

from celery import Celery

# Stable application token — emitted in worker logs so two workers
# pointed at different builds during a rolling deploy can be told
# apart at a glance.
_OE_JOBS_APP_NAME: str = "oe_jobs"

# Default broker / result-backend point at Redis DB 1 to keep the
# job runner's queues separate from any cache traffic the rest of
# the platform might use on Redis DB 0 (cf. ``settings.redis_url``).
_DEFAULT_REDIS_URL: str = "redis://localhost:6379/1"


def make_celery_app(broker_url: str, result_backend: str) -> Celery:
    """Build a fully-configured Celery app for the OpenEstimate job runner.

    Args:
        broker_url: Where Celery enqueues tasks. Redis is the supported
            broker; AMQP would work too but we have no operational test
            coverage for it.
        result_backend: Where Celery writes per-task results. We mostly
            ignore Celery's own results (the JobRun row is the source of
            truth) but the backend must still be configured so
            ``apply_async()`` does not crash in eager-mode tests.

    Returns:
        A Celery app with RFC 34 §4 W0.1 settings applied.
    """
    app = Celery(
        _OE_JOBS_APP_NAME,
        broker=broker_url,
        backend=result_backend,
    )
    app.conf.update(
        # Lock serialization to JSON so payloads and results remain
        # inspectable in Redis without needing a Python deserializer.
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        # All timestamps in UTC — matches DB convention and avoids
        # cross-region log-correlation pain.
        timezone="UTC",
        enable_utc=True,
        # Tasks emit a "started" state so the JobRun row can flip from
        # pending → started even when the handler runs for several seconds.
        task_track_started=True,
        # Hard timeout: 10 min — any single task taking longer indicates
        # a runaway loop, not legitimate work. Long pipelines should split
        # into multiple tasks.
        task_time_limit=600,
        # Prefetch=1 makes per-task duration fairer across workers; one
        # heavy task does not get to monopolise a worker's prefetch buffer.
        worker_prefetch_multiplier=1,
    )
    return app


def _broker_url_from_env() -> str:
    """Resolve the broker URL from env, falling back to the default."""
    return os.environ.get("OE_CELERY_BROKER_URL", _DEFAULT_REDIS_URL)


def _result_backend_from_env() -> str:
    """Resolve the result backend from env, falling back to the default."""
    return os.environ.get("OE_CELERY_RESULT_BACKEND", _DEFAULT_REDIS_URL)


# Singleton — initialised lazily on first ``get_celery_app()`` call so
# that test suites can override the env vars before the Celery app is
# constructed (e.g., to point at a testcontainers Redis).
_celery_app: Celery | None = None


def get_celery_app() -> Celery:
    """Return the process-wide Celery app, instantiating on first use.

    Importing :mod:`app.core.jobs_tasks` at the same time registers the
    generic ``oe.dispatch_job`` task on the returned app — callers
    almost always want both, so we trigger the import here to keep
    bootstrap order easy to reason about.

    The tasks-module import is done after the singleton is assigned so
    that ``jobs_tasks`` can safely ``from app.core.jobs import celery_app``
    without tripping a circular-import error.
    """
    global _celery_app
    if _celery_app is None:
        _celery_app = make_celery_app(
            broker_url=_broker_url_from_env(),
            result_backend=_result_backend_from_env(),
        )
        # Mirror onto the module-level alias FIRST so the import below
        # can read ``celery_app`` without a partially-initialised-module
        # ImportError. Without this, the `from app.core.jobs import
        # celery_app` line inside jobs_tasks.py runs while jobs.py is
        # still on the line that triggered the import.
        global celery_app
        celery_app = _celery_app
        # Importing the tasks module attaches @task decorators to the
        # singleton above. Done here, not at module top, so that the
        # app exists before tasks try to register against it.
        from app.core import jobs_tasks  # noqa: F401  (registration side effect)

    return _celery_app


# Module-level alias so workers launched via ``celery -A app.core.jobs``
# can find the app. Celery's CLI looks up an attribute named ``app`` or
# ``celery_app`` on the module path it is given. Initialised to None
# here and populated by ``get_celery_app()`` on first call.
celery_app: Celery | None = None
# Trigger the singleton initialisation at import time so plain
# `import app.core.jobs` is enough for both the worker CLI and
# downstream callers that want to read `celery_app` directly.
get_celery_app()
