# OpenConstructionERP - DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · CAD2DATA Pipeline
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""OpenEstimate​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - FastAPI application factory.

Usage:
    uvicorn app.main:create_app --factory --reload --port 8000
    openestimate serve  (CLI mode - also serves frontend)
"""

# ── Runtime compatibility shims ─────────────────────────────────────────────
# MUST run BEFORE any import that can pull in numpy / torch / lancedb.
# On Windows + Anaconda Python, both Intel MKL (bundled with Anaconda numpy)
# and the torch wheels ship their own copy of ``libiomp5md.dll``. When the
# second copy is loaded, the OpenMP runtime aborts with:
#
#   OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll
#                   already initialized.
#
# On Linux/macOS this is a warning; on Windows it is a fatal native abort
# that kills the process silently - no Python traceback, the shell just
# returns to the prompt. ``KMP_DUPLICATE_LIB_OK=TRUE`` tells the OpenMP
# runtime to accept the duplicate library instead of terminating, which
# is safe for inference workloads where we do not rely on deterministic
# thread pool ownership.
import os as _os

_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("OMP_NUM_THREADS", "1")
_os.environ.setdefault("MKL_NUM_THREADS", "1")

import asyncio
import hashlib as _hashlib
import logging
import os
import secrets
import time
import uuid
import uuid as _instance_uuid
from typing import TYPE_CHECKING, Any

_APP_BUILD_TAG: str = "a037e172eb9c84f9"

# Unique instance fingerprint - proves this specific deployment origin
_INSTANCE_ID = str(_instance_uuid.uuid4())
# Build-pepper. Looks like opaque crypto material; the bytes XOR-decode to
# the project authorship marker so removing it changes the published health
# build hash (deterministic across rebuilds with the same INSTANCE_ID).
_BUILD_PEPPER = bytes(b ^ 0x55 for b in (b"\x11\x11\x16\x78\x16\x02\x1c\x16\x07\x78\x1a\x10\x78\x67\x65\x67\x63"))
_BUILD_HASH = _hashlib.sha256(_BUILD_PEPPER + f"DDC-CWICR-OE-{_INSTANCE_ID}".encode()).hexdigest()[:16]

from datetime import UTC
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    Settings,
    build_provenance_tag,
    desktop_mode,
    get_settings,
    jwt_secret_is_known_weak,
    jwt_secret_is_too_short,
)
from app.core.demo_read_only import (
    DemoReadOnlyError,
    demo_read_only_guard,
    read_only_refusal,
)
from app.core.deployment_posture import build_data_security_posture
from app.core.host_disclosure import without_host_fields
from app.core.module_loader import module_loader
from app.core.self_upgrade import (
    FROZEN_REFUSAL,
    claim_upgrade,
    current_upgrade,
    is_frozen_build,
    repair_hint,
    run_upgrade,
)
from app.dependencies import OptionalUserPayload, RequireRole, get_current_user_id, rls_request_context

if TYPE_CHECKING:
    from app.core.data_repairs import DataRepairReport

logger = logging.getLogger(__name__)

# (alembic.ini path, head revision) for this process, filled on first use by
# ``_expected_alembic_head``. The path is part of the key so a test pointed at a
# different tree is never answered from the previous one.
_ALEMBIC_HEAD_CACHE: tuple[str, str | None] | None = None


def alembic_head_state(expected: str | None, actual: str | None) -> bool | None:
    """Is the database at the migration head? ``None`` when that cannot be told.

    ``expected`` is the head the installed migration tree declares and ``actual``
    is the revision recorded in the database. Either can be absent, and absence
    is not disagreement:

    * ``expected`` is ``None`` where no migration tree shipped. The desktop
      bundle is the live case: it carries neither ``alembic.ini`` nor the
      script directory, on purpose (see
      ``tests/unit/test_desktop_spec_ships_wheel_data.py``).
    * ``actual`` is ``None`` on a database with no ``alembic_version`` row. That
      is every install built by ``create_all`` before the boot-time stamp
      existed, and every install where the stamp could not be written. The
      columns are physically present and the schema is current; nobody wrote
      down that it is.

    Comparing the two raw values with ``==`` answers ``False`` for both of those,
    which is the bug this replaces. A permanent ``False`` on a healthy install is
    worse than no signal at all, because it is a signal that says the opposite of
    the truth and consumers act on it. ``None`` says "I could not tell", which is
    what the caller has to be able to distinguish before it decides anything.
    """
    if expected is None or actual is None:
        return None
    return expected == actual


def publish_data_repair_verdict(app: FastAPI, report: "DataRepairReport | None") -> None:
    """Copy a data-repair pass's verdict onto ``app.state`` for ``/api/health``.

    Every field the health endpoint reads about the repair pass is written
    here, and only here, so that the endpoint cannot end up publishing one half
    of a report and silently dropping the other. That is not a hypothetical
    tidiness argument: it is the defect this function was extracted to close.
    ``run_data_repairs`` returns ``ledger_written`` separately from the repair
    outcomes on purpose - a repair can succeed against a database whose role
    may write rows but not create tables, leaving the data correct and the
    *record* of it missing - and the boot path published the outcomes and threw
    the ledger flag away. With the ledger table dropped, both repairs landed,
    ``ledger_written`` was ``False``, and health answered ``healthy`` with
    ``data_repairs_failed: false``. Nothing anywhere could then answer "did this
    repair run on this install", which is the only question a ledger exists for.

    ``discovery_failures`` is the same mistake one step earlier and is folded
    into ``data_repairs_failed`` here. A module whose ``repairs.py`` did not
    import registers nothing, so its repairs are absent from ``failed`` for the
    only reason ``failed`` can be read: that property lists repairs that RAN and
    raised. Reading it alone answered ``false`` for a module broken badly enough
    not to load, which is to say the more thoroughly broken module got the more
    reassuring answer. A repair that did not run and a repair that ran and found
    nothing wrong must not produce the same verdict, so a discovery failure
    degrades exactly as a raising repair does, and the module names go on
    ``data_repairs_failed_ids`` beside the repair ids.

    Args:
        app: The application whose ``state`` carries the verdict.
        report: What the pass returned, or ``None`` when the pass could not run
            at all. ``None`` is not the same as the ``None`` the fields are
            built with. A pass that raised before producing a report leaves
            rows unrepaired and unrecorded, so every field goes to its failed
            value; the initial ``None`` on ``app.state`` means the pass was
            never reached, which is where a deployment whose database is not
            PostgreSQL stays for its whole life.
    """
    if report is None:
        app.state.data_repairs_failed = True
        app.state.data_repairs_failed_ids = ("<pass did not run>",)
        app.state.data_repair_ledger_failed = True
        return

    # Marked so a support log can tell a repair that raised from a module that
    # never loaded. The two need different first moves - one is a database the
    # repair could not touch, the other is a build that shipped a broken file -
    # and an unmarked dotted path in a list of repair ids reads as neither.
    unimported = tuple(f"<{failure.module} did not import>" for failure in report.discovery_failures)
    app.state.data_repairs_failed = bool(report.failed) or bool(unimported)
    app.state.data_repairs_failed_ids = report.failed + unimported
    # Inverted on the way out so the published field keeps the polarity of the
    # two beside it: ``true`` is the bad news on every one of them, and a
    # monitor should not need a second, opposite predicate for this one field.
    app.state.data_repair_ledger_failed = not report.ledger_written


def _expected_alembic_head(ini_path: os.PathLike[str] | str) -> str | None:
    """The head revision the installed migration tree declares, parsed once.

    The tree cannot change under a running process: it is installed inside the
    package next to this file, and a new one only arrives with a new process.
    Repeating the parse is not cheap either, since
    ``ScriptDirectory.from_config`` opens and compiles every revision file and
    there are over three hundred of them.

    That mattered because of who calls it. Health is polled on a timer by the
    desktop shell, by container healthchecks and by whatever watches the
    deployment, so this ran on a loop rather than on a rare diagnostic path.

    The database revision it gets compared against is deliberately not cached.
    That one does change while the process runs, and caching it would turn "has
    the schema fallen behind" into "was it behind when this process started",
    which is a different and much less useful question.
    """
    global _ALEMBIC_HEAD_CACHE

    key = str(ini_path)
    cached = _ALEMBIC_HEAD_CACHE
    if cached is not None and cached[0] == key:
        return cached[1]

    from alembic.config import Config as _AlembicConfig
    from alembic.script import ScriptDirectory as _ScriptDir

    head = _ScriptDir.from_config(_AlembicConfig(key)).get_current_head()
    # Only reached when the parse succeeded. A failure is left uncached so the
    # next call tries again instead of reporting a permanent unknown.
    _ALEMBIC_HEAD_CACHE = (key, head)
    return head


def _database_target() -> str:
    """Describe where the database connection was aimed, without the password.

    A name-resolution failure reports only what the resolver was handed, so
    ``[Errno -2] Name or service not known`` arrives naming nothing the
    operator can check. The host *as parsed* is the useful thing to print: a
    password containing ``@`` moves the split point in the URL's userinfo, so
    ``oe:pa@ss@postgres`` parses its host as ``ss@postgres``, which resolves
    nowhere. That is visible on sight here and invisible everywhere else.

    Never renders the password. Returns an empty string if anything at all
    goes wrong, because this only ever runs on a failure path.
    """
    try:
        from sqlalchemy.engine import make_url

        url = make_url(get_settings().database_url)
        target = url.host or "(no host)"
        if url.port:
            target = f"{target}:{url.port}"
        if url.database:
            target = f"{target}/{url.database}"
        return target[:80]
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real error
        return ""


def _emit_server_fail(exc: BaseException) -> None:
    """Report a fatal startup failure as a machine-readable marker plus a log.

    The FastAPI startup event runs the work that can fatally fail (DB connect,
    schema build, module load, demo seed). When it raises, uvicorn swallows the
    cause into a bare "Application startup failed" line and exits, and the
    embedded-PostgreSQL shutdown that follows floods stdout - so the desktop
    launcher used to show that shutdown noise instead of the real reason.
    Emitting a ``STAGE:server:fail:<reason>`` marker here (flushed, before the
    process tears down) lets the launcher latch the true cause; the full
    traceback is logged for the log file. Best effort - never raises and never
    changes how the original error propagates.
    """
    try:
        import traceback

        reason = f"{type(exc).__name__}: {exc}".replace("\n", " ").replace("\r", " ").strip()
        if len(reason) > 180:
            reason = reason[:177] + "..."
        # Neutral label rather than a diagnosis: this runs for every fatal
        # startup failure, including ones the database had nothing to do with.
        target = _database_target()
        if target:
            reason = f"{reason} | db={target}"
        from app.core.embedded_pg import emit_stage

        emit_stage("server", "fail", reason)
        logger.error("startup failed: %s", reason)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.error("startup traceback:\n%s", tb)
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real error
        pass


def configure_logging(settings: Settings) -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if settings.app_debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Plain stdlib formatter carries the request-id context so logs emitted
    # by SQLAlchemy / FastAPI / business code outside structlog still get
    # tagged with the correlation ID. ``%(request_id)s`` is injected by
    # ``RequestIDLogFilter`` (defaults to "-" off-request).
    from app.middleware.request_id import RequestIDLogFilter

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
        force=True,
    )
    _rid_filter = RequestIDLogFilter()
    root_logger = logging.getLogger()
    # Attach to root so every handler inherits the filter; also attach
    # directly to existing handlers since logging.Filter does not propagate
    # through ``Logger.addFilter`` to already-attached handlers reliably.
    root_logger.addFilter(_rid_filter)
    for handler in root_logger.handlers:
        handler.addFilter(_rid_filter)


def _init_vector_db() -> None:
    """Initialize vector database on startup (non-blocking, never fatal).

    Vector search is an important feature of OpenConstructionERP -
    it powers semantic cost-item matching, BOQ auto-classification,
    and assembly suggestions. We support two backends:

    * **Qdrant** (recommended for production) - dedicated server, scales
      to millions of vectors, supports snapshots. Run it locally with:
      ``docker run -p 6333:6333 qdrant/qdrant``
    * **LanceDB** (embedded, default) - zero-config, stores vectors on
      the local filesystem. Good enough for single-node deployments.

    Neither is a hard dependency: if both are unavailable, the platform
    still runs and serves all modules - only semantic search is disabled.
    This function is deliberately wrapped in a broad try/except so that
    no vector-related failure can ever block the rest of startup.
    """
    try:
        from app.core.vector import vector_status

        status = vector_status()
        engine = status.get("engine", "lancedb")
        if status.get("connected"):
            vectors = status.get("cost_collection", {})
            count = vectors.get("vectors_count", 0) if vectors else 0
            logger.info("Vector DB ready: %s (%d vectors indexed)", engine, count)
            return

        # Not connected - log a clear, actionable hint so users know how
        # to enable semantic search if they need it.
        error = status.get("error", "unknown")
        if engine == "qdrant":
            logger.warning(
                "Qdrant not reachable (%s). Semantic search is disabled. "
                "Start a local Qdrant with: docker run -p 6333:6333 qdrant/qdrant",
                error,
            )
        else:
            # lancedb is in requirements-desktop.lock, so a bundle whose store
            # will not start is damaged rather than lean: the default repair
            # wording, not DESKTOP_NO_EXTRA.
            logger.warning(
                "LanceDB init failed (%s). Semantic search is disabled. %s",
                error,
                repair_hint("Install the embedded vector backend with: pip install openconstructionerp[vector]"),
            )
    except Exception as exc:  # noqa: BLE001 - intentional: never fatal
        # Includes ImportError (missing optional extras), native crashes
        # surfaced as OSError, etc. Semantic search is optional; the rest
        # of the application must continue to boot.
        logger.warning("Vector DB init skipped: %s", exc)


async def _auto_backfill_vector_collections() -> None:
    """Backfill the multi-collection vector store from existing rows.

    The event-driven indexing layer (added in v1.4.0) only fires for
    rows that are created or updated AFTER the upgrade.  On a fresh
    install with no data this is a no-op; on an existing v1.3.x install
    it would leave thousands of BOQ positions / documents / tasks /
    risks / BIM elements / validation reports / chat messages
    unsearchable until the user manually called every per-module
    `/vector/reindex/` endpoint.

    This helper closes that gap automatically.  For each registered
    collection it:

    1. Reads the live row count from Postgres
    2. Reads the indexed row count from the vector store
    3. If the vector store is short, runs ``reindex_collection`` for the
       missing rows (capped by ``vector_backfill_max_rows`` per pass)

    Designed to be **non-blocking** - it runs in a detached background
    task so startup completes immediately even if the model loader has
    to download a fresh embedding checkpoint.

    All failures are logged and swallowed.  Disable entirely with
    ``vector_auto_backfill=False`` in settings.
    """
    try:
        from sqlalchemy import select

        from app.config import get_settings
        from app.core.vector import vector_count_collection
        from app.core.vector_index import (
            COLLECTION_BIM_ELEMENTS,
            COLLECTION_BOQ,
            COLLECTION_CHAT,
            COLLECTION_COSTS,
            COLLECTION_DOCUMENTS,
            COLLECTION_REQUIREMENTS,
            COLLECTION_RISKS,
            COLLECTION_TASKS,
            COLLECTION_VALIDATION,
            reindex_collection,
        )
        from app.database import async_session_factory

        settings = get_settings()
        if not settings.vector_auto_backfill:
            logger.info("Vector auto-backfill disabled by settings; skipping")
            return

        cap = max(0, int(settings.vector_backfill_max_rows or 0))

        from sqlalchemy import func
        from sqlalchemy.orm import selectinload

        async def _maybe_backfill(
            label: str,
            collection: str,
            model,
            adapter,
            *,
            options: list | None = None,
        ) -> None:
            """Backfill ``collection`` from ``model`` rows in a memory-safe way.

            Steps:
                1. Read the indexed-row count from the vector store (cheap).
                2. Issue a ``SELECT COUNT(*)`` against the model - also cheap.
                3. Skip if the index already has at least as many rows.
                4. Otherwise pull rows with ``LIMIT cap`` applied at the SQL
                   level so we never materialise the full table in memory.

            The previous implementation called ``loader(session)`` which
            executed an unbounded ``SELECT *`` and then sliced ``rows[:cap]``
            in Python - fine on a 100-row dev DB, catastrophic on a 2M-row
            production deployment because it allocates the entire result set
            before applying the cap.  Now the cap is enforced before the
            scan reaches the network.
            """
            try:
                indexed = vector_count_collection(collection) or 0
            except Exception:
                indexed = 0

            try:
                async with async_session_factory() as session:
                    # Step 1: cheap COUNT(*) - never materialises rows.
                    live_total = (await session.execute(select(func.count()).select_from(model))).scalar_one() or 0

                    if not live_total:
                        return
                    if indexed >= live_total:
                        logger.debug(
                            "Backfill %s: %d/%d already indexed; skipping",
                            label,
                            indexed,
                            live_total,
                        )
                        return

                    # Step 2: decide how many rows to actually pull.
                    if cap > 0 and live_total > cap:
                        limit_to = cap
                        logger.info(
                            "Backfill %s: %d live rows exceeds cap (%d); indexing first %d",
                            label,
                            live_total,
                            cap,
                            cap,
                        )
                    else:
                        limit_to = live_total

                    # Step 3: pull only what we need, with relationship
                    # eager-loads if the adapter needs them.
                    stmt = select(model)
                    if options:
                        stmt = stmt.options(*options)
                    stmt = stmt.limit(limit_to)
                    rows = list((await session.execute(stmt)).scalars().all())
            except Exception as exc:
                logger.debug("Backfill %s loader failed: %s", label, exc)
                return

            if not rows:
                return

            try:
                result = await reindex_collection(adapter, rows)
                logger.info(
                    "Backfill %s: indexed=%d, skipped=%d (live=%d, was=%d)",
                    label,
                    result.get("indexed", 0),
                    result.get("skipped", 0),
                    live_total,
                    indexed,
                )
            except Exception as exc:
                logger.debug("Backfill %s reindex failed: %s", label, exc)

        # ── Declarative collection registry ──────────────────────────────
        # Each tuple is (label, collection_constant, model_loader, adapter_loader,
        # options_factory).  The loaders are deferred to keep import cost low
        # and to avoid pulling every module's models into memory if the
        # auto-backfill is disabled.
        from app.modules.bim_hub.models import BIMElement
        from app.modules.bim_hub.vector_adapter import bim_element_vector_adapter
        from app.modules.boq.models import Position
        from app.modules.boq.vector_adapter import boq_position_adapter
        from app.modules.documents.models import Document
        from app.modules.documents.vector_adapter import document_vector_adapter
        from app.modules.erp_chat.models import ChatMessage
        from app.modules.erp_chat.vector_adapter import chat_message_adapter
        from app.modules.requirements.models import Requirement
        from app.modules.requirements.vector_adapter import (
            requirement_vector_adapter,
        )
        from app.modules.risk.models import RiskItem
        from app.modules.risk.vector_adapter import risk_vector_adapter
        from app.modules.tasks.models import Task
        from app.modules.tasks.vector_adapter import task_vector_adapter
        from app.modules.validation.models import ValidationReport
        from app.modules.validation.vector_adapter import validation_report_adapter

        backfill_targets = [
            (
                "BOQ positions",
                COLLECTION_BOQ,
                Position,
                boq_position_adapter,
                [selectinload(Position.boq)],
            ),
            ("Documents", COLLECTION_DOCUMENTS, Document, document_vector_adapter, None),
            ("Tasks", COLLECTION_TASKS, Task, task_vector_adapter, None),
            ("Risks", COLLECTION_RISKS, RiskItem, risk_vector_adapter, None),
            (
                "BIM elements",
                COLLECTION_BIM_ELEMENTS,
                BIMElement,
                bim_element_vector_adapter,
                [selectinload(BIMElement.model)],
            ),
            (
                "Validation reports",
                COLLECTION_VALIDATION,
                ValidationReport,
                validation_report_adapter,
                None,
            ),
            (
                "Requirements",
                COLLECTION_REQUIREMENTS,
                Requirement,
                requirement_vector_adapter,
                [selectinload(Requirement.requirement_set)],
            ),
            (
                "Chat messages",
                COLLECTION_CHAT,
                ChatMessage,
                chat_message_adapter,
                [selectinload(ChatMessage.session)],
            ),
        ]

        for label, collection_id, model, adapter, options in backfill_targets:
            await _maybe_backfill(
                label,
                collection_id,
                model,
                adapter,
                options=options,
            )

        # ── Cost catalog (oe_cost_items) ─────────────────────────────────
        # The cost adapter needs the E5 ``passage:`` prefix at encode time
        # so it can't go through ``reindex_collection`` (which uses the
        # adapter's plain ``to_text``).  Run a dedicated delta pass that
        # uses the cost-specific helper instead.
        try:
            import os as _os

            from app.modules.costs import vector_adapter as _cost_vec
            from app.modules.costs.events import (
                _delta_reindex_all_active as _cost_reindex_active,
            )
            from app.modules.costs.models import CostItem as _CostItem

            force_backfill = _os.environ.get("OE_COST_VECTOR_FORCE_BACKFILL", "").strip() in (
                "1",
                "true",
                "True",
                "yes",
            )

            indexed_count = await _cost_vec.collection_count()
            async with async_session_factory() as _sess:
                live_total = (
                    await _sess.execute(
                        select(func.count()).select_from(_CostItem).where(_CostItem.is_active.is_(True))
                    )
                ).scalar_one() or 0

            if not live_total:
                logger.debug("Backfill Cost catalog: 0 live rows; skipping")
            elif not force_backfill and indexed_count >= live_total:
                logger.debug(
                    "Backfill Cost catalog: %d/%d already indexed; skipping",
                    indexed_count,
                    live_total,
                )
            else:
                # Cap by the same setting as every other collection so
                # we don't saturate the embedder on first boot.
                if cap > 0 and live_total > cap:
                    logger.info(
                        "Backfill Cost catalog: %d live rows exceeds cap "
                        "(%d); will index in chunks via the existing "
                        "delta pass",
                        live_total,
                        cap,
                    )
                indexed = await _cost_reindex_active()
                logger.info(
                    "Backfill Cost catalog: indexed=%d (live=%d, was=%d, force=%s)",
                    indexed,
                    live_total,
                    indexed_count,
                    force_backfill,
                )
        except Exception as exc:
            logger.debug("Backfill Cost catalog skipped: %s", exc)

        # Sentinel - keeps imports above flagged as used by ruff F401 even
        # if a future refactor drops one of the targeted collections.
        _ = COLLECTION_COSTS

        logger.info("Vector auto-backfill pass complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector auto-backfill skipped: %s", exc)


def _resolve_demo_password(env_var: str) -> tuple[str, bool]:
    """Resolve the password for one demo account.

    Returns ``(password, was_generated)``. If the operator set the matching
    env var to a non-empty string we honour it as-is. Otherwise we generate
    a fresh ``secrets.token_urlsafe(16)`` (22 url-safe chars). Generated
    passwords are persisted by ``_persist_demo_credentials`` so the CLI
    banner can read them back after the seeder runs - see BUG-D01 for why
    no hardcoded fallback is acceptable here.
    """
    env_value = os.environ.get(env_var)
    if env_value:
        return env_value, False
    return secrets.token_urlsafe(16), True


def _persist_demo_credentials(creds: dict[str, str]) -> Path | None:
    """Write generated demo credentials to a 0600 file.

    Falls back to ``~/.openestimator/.demo_credentials.json`` when the CLI
    didn't expose a data directory. Returns the path written, or ``None``
    if the write failed (best-effort - never let credential persistence
    block startup).
    """
    import json as _json
    import stat as _stat

    target_dir = os.environ.get("OE_CLI_DATA_DIR")
    if target_dir:
        base = Path(target_dir)
    else:
        base = Path.home() / ".openestimator"
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / ".demo_credentials.json"
        # Merge with existing values so we don't overwrite earlier entries
        # if the seeder runs multiple times (idempotent boot).
        existing: dict[str, str] = {}
        if path.exists():
            try:
                existing = _json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                existing = {}
        existing.update(creds)
        path.write_text(
            _json.dumps(existing, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            path.chmod(_stat.S_IRUSR | _stat.S_IWUSR)
        except OSError:
            # Best-effort on Windows - chmod is a no-op there
            pass
        return path
    except OSError as exc:
        logger.warning("Could not persist demo credentials: %s", exc)
        return None


#: The identity of a data directory, published by ``/api/health``.
#:
#: Read by the desktop launcher (``desktop/src-tauri/src/main.rs``) before it
#: attaches to a backend that is already listening on loopback. A rename here is
#: a rename there; the two sides share a file name and nothing else.
_WORKSPACE_ID_FILENAME = "workspace_id.json"


def _workspace_id_path() -> Path:
    """Resolve the workspace-identity file in the active data dir.

    Same resolution as the demo-backfill marker below, and for the same reason:
    a ``serve --data-dir`` instance is a separate installation and must carry a
    separate identity, which it does not if the path is computed any other way.
    """
    from app.core.partner_pack.state import _resolve_state_dir

    return _resolve_state_dir() / _WORKSPACE_ID_FILENAME


def _read_workspace_id(path: Path) -> str | None:
    """Return the identity recorded at ``path``, or ``None`` if there is none.

    Anything unreadable, unparseable or empty reads as absent. A caller that got
    ``None`` here either writes the file or publishes no identity at all; there
    is no third answer, and in particular no answer that is wrong.
    """
    import json as _json

    try:
        raw = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = raw.get("workspace_id") if isinstance(raw, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_workspace_id() -> str | None:
    """The identity of the installation this process serves, or ``None``.

    Which *data directory* is being served, as against which process is serving
    it. ``_INSTANCE_ID`` answers the second question and cannot be made to
    answer the first: it is a fresh uuid4 per process, so it differs across a
    restart of one install exactly as it differs between two installs, which
    makes it useless to anyone trying to tell those two cases apart. Hence a
    second field rather than a reuse of that one.

    Two properties are load bearing, and both are asserted in
    ``tests/unit/test_a_second_user_on_one_machine_is_a_second_workspace.py``.

    The value is opaque random bytes, never a path and never anything derived
    from an account name. ``/api/health`` is unauthenticated on purpose, so on
    any deployment whose port is reachable this value is readable by whoever can
    reach it, and an id built out of the data directory would publish the disk
    layout and the operating-system user of the machine serving it.

    And it is persisted, so it survives a restart. A value regenerated per boot
    would make a launcher refuse to attach to the backend it started itself, and
    the cost of refusing is not "look elsewhere", it is a second server started
    against the running one's data directory.

    Created with ``O_EXCL`` rather than written to a temporary file and renamed
    over. Renaming is the usual idiom here (``_write_demo_backfill_version``
    below uses it) and is the wrong one for this file: rename replaces what it
    finds, on POSIX and on Windows alike, so two processes starting together
    would each write an id and the loser would be left holding one that is no
    longer on disk. ``O_EXCL`` is create-if-absent in a single syscall, so the
    first writer wins and every later one reads that same value back.

    Returns ``None`` when the directory cannot be read or written - a read-only
    mount, a full disk. That omits the field from the health body, which fails
    closed: a launcher with no identity of its own attaches to nothing, and a
    candidate that publishes none is refused. Never raises, because a container
    healthcheck reads this endpoint and a 500 there is a worse outcome than an
    installation that declines to be attached to.
    """
    import json as _json

    try:
        path = _workspace_id_path()
    except Exception:  # noqa: BLE001 - an unresolvable data dir has no identity
        logger.debug("Could not resolve the workspace id path", exc_info=True)
        return None

    existing = _read_workspace_id(path)
    if existing:
        return existing

    candidate = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _json.dumps({"workspace_id": candidate}, indent=2) + "\n"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        return candidate
    except FileExistsError:
        # Somebody else got there between the read above and the create. Theirs
        # is the identity of this directory; ours was never published.
        return _read_workspace_id(path)
    except OSError:
        logger.debug("Could not establish the workspace id", exc_info=True)
        return None


_DEMO_BACKFILL_MARKER_FILENAME = "demo_backfill_marker.json"


def _demo_backfill_marker_path() -> Path:
    """Resolve the demo-backfill sentinel file in the active data dir.

    Reuses the partner-pack state resolution so a custom ``serve
    --data-dir`` instance keeps its own marker instead of sharing the
    default install's (same lesson as partner_pack_state.json).
    """
    from app.core.partner_pack.state import _resolve_state_dir

    return _resolve_state_dir() / _DEMO_BACKFILL_MARKER_FILENAME


def _read_demo_backfill_version() -> str | None:
    """Return the app version stamped by the last completed demo backfill.

    Crash-safe: any read/parse failure returns ``None`` so the seeds run
    exactly as they did before the sentinel existed.
    """
    import json as _json

    try:
        path = _demo_backfill_marker_path()
        if not path.exists():
            return None
        raw = _json.loads(path.read_text(encoding="utf-8"))
        version = raw.get("app_version") if isinstance(raw, dict) else None
        return version if isinstance(version, str) and version else None
    except Exception:  # noqa: BLE001 - unreadable marker just means "run the seeds"
        logger.debug("Demo backfill marker unreadable - running seeds", exc_info=True)
        return None


def _write_demo_backfill_version(version: str) -> None:
    """Stamp the demo-backfill sentinel with the current app version.

    Best-effort: a failed write only means the (idempotent) seeds run
    again on the next boot.
    """
    import json as _json
    from datetime import datetime as _datetime

    try:
        path = _demo_backfill_marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            _json.dumps(
                {
                    "app_version": version,
                    "completed_at": _datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:  # noqa: BLE001 - never let the sentinel block startup
        logger.debug("Could not write demo backfill marker", exc_info=True)


async def _seed_demo_account() -> None:
    """Create demo user + showcase projects if they don't exist yet.

    Idempotent - safe to call on every startup. Creates:

    * demo@openconstructionerp.com        (role=admin - full walkthrough)
    * estimator@openconstructionerp.com   (role=estimator)
    * manager@openconstructionerp.com     (role=manager)

    Each password is read from the environment if set
    (``DEMO_USER_PASSWORD``, ``DEMO_ESTIMATOR_PASSWORD``,
    ``DEMO_MANAGER_PASSWORD``), otherwise generated per-installation via
    ``secrets.token_urlsafe(16)``. Generated values are written to
    ``~/.openestimator/.demo_credentials.json`` (chmod 600) and printed
    once to the startup log. Operators who want a stable password for
    their team can set the env vars; everyone else gets a unique secret
    they can recover from the credentials file.

    Disable demo creation entirely with ``SEED_DEMO=false`` in production.
    When ``SEED_DEMO`` is unset, the persisted first-run choice (the CLI's
    "Load demo projects?" prompt / ``serve --no-demo`` / the demo-data
    purge endpoint) in ``<data-dir>/demo_seed_choice.json`` decides - see
    ``app.core.demo_seed``.
    """
    from app.core.demo_seed import seed_demo_enabled

    if not seed_demo_enabled():
        return

    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    # Email → env-var-name mapping. Order matters for stable banner output.
    #
    # Two login pages mirror this list by hand and show it on their demo
    # sign-in tiles: the ``demoAccounts`` arrays in
    # ``frontend/src/features/auth/LoginPage.tsx`` and ``LoginPageNext.tsx``.
    # Renaming an account or changing an email here means editing both of
    # them - nothing gates that, and the manager tile on LoginPageNext once
    # carried a name that existed in no seeder at all. The emails alone are
    # also mirrored in ``app.modules.users.service`` and
    # ``app.modules.users.router`` (whitelists, kept in sync by
    # ``backend/tests/integration/test_demo_login_endpoint.py``).
    demo_account_specs: list[dict[str, str]] = [
        {
            "email": "demo@openconstructionerp.com",
            "env_var": "DEMO_USER_PASSWORD",
            "full_name": "Elena Marchetti",
            "role": "admin",
        },
        {
            "email": "estimator@openconstructionerp.com",
            "env_var": "DEMO_ESTIMATOR_PASSWORD",
            "full_name": "Anna Musterfrau",
            "role": "editor",
        },
        {
            "email": "manager@openconstructionerp.com",
            "env_var": "DEMO_MANAGER_PASSWORD",
            "full_name": "Michael Carter",
            "role": "manager",
        },
    ]

    # Track generated credentials so we can persist + print them once.
    generated_creds: dict[str, str] = {}

    try:
        from app.modules.users.service import verify_password

        async with async_session_factory() as session:
            demo: User | None = None
            for acct in demo_account_specs:
                exists = (await session.execute(select(User).where(User.email == acct["email"]))).scalar_one_or_none()
                if exists is not None:
                    if acct["email"] == "demo@openconstructionerp.com":
                        demo = exists
                    # If operator set the env-var explicitly and the stored
                    # hash no longer matches that password, sync the hash so
                    # the documented credential always works after a restart.
                    env_value = os.environ.get(acct["env_var"])
                    if env_value and not verify_password(env_value, exists.hashed_password):
                        exists.hashed_password = hash_password(env_value)
                        logger.info("Demo user password synced from env: %s", acct["email"])
                    continue

                password, was_generated = _resolve_demo_password(acct["env_var"])
                if was_generated:
                    generated_creds[acct["email"]] = password

                user = User(
                    id=uuid.uuid4(),
                    email=acct["email"],
                    hashed_password=hash_password(password),
                    full_name=acct["full_name"],
                    role=acct["role"],
                    locale="en",
                    is_active=True,
                    metadata_={},
                )
                session.add(user)
                await session.flush()
                if acct["email"] == "demo@openconstructionerp.com":
                    demo = user
                logger.info(
                    "Demo user created: %s (password source: %s)",
                    acct["email"],
                    "env" if not was_generated else "generated",
                )

            # Persist generated passwords + print once. Operators who set
            # env vars never see this banner; new installs get a one-time
            # log line with the location.
            #
            # IMPORTANT: log each generated credential as a self-contained
            # ``[seed]`` line so a new developer sees the password
            # immediately at first-boot time without having to know about
            # ``~/.openestimator/.demo_credentials.json``. This was the #1
            # cause of "why won't login work" debug sessions on fresh
            # installs (see docs/qa/FRESH_INSTALL_RESULTS.md Issue 3).
            if generated_creds:
                creds_path = _persist_demo_credentials(generated_creds)
                # Email -> env-var-name lookup so each per-account banner
                # can name the exact variable that suppresses random
                # generation for that account.
                env_var_for_email = {spec["email"]: spec["env_var"] for spec in demo_account_specs}
                for email, pw in generated_creds.items():
                    env_var = env_var_for_email.get(email, "DEMO_USER_PASSWORD")
                    logger.warning("[seed] Demo user created: %s / %s", email, pw)
                    logger.warning("[seed] Pre-set %s env to skip random generation", env_var)
                logger.warning(
                    "[seed] %d demo credential(s) also saved to %s",
                    len(generated_creds),
                    creds_path or "(persistence failed - check logs)",
                )

            # 2. Capture the demo user ids while the session is open.
            estimator_user = (
                await session.execute(select(User).where(User.email == "estimator@openconstructionerp.com"))
            ).scalar_one_or_none()
            manager_user = (
                await session.execute(select(User).where(User.email == "manager@openconstructionerp.com"))
            ).scalar_one_or_none()
            demo_user_id = str(demo.id)
            estimator_user_id = str(estimator_user.id) if estimator_user else ""
            manager_user_id = str(manager_user.id) if manager_user else ""

            project_count = (
                await session.execute(select(func.count()).select_from(Project).where(Project.owner_id == demo.id))
            ).scalar() or 0

            # The two headline demo accounts (demo@ admin and manager@) are the
            # ones shown in the account switcher, so they should always display
            # every menu, regardless of any company-profile gating a tester
            # applied in the browser. Company-profile choices live in the user's
            # module_preferences, and that server map wins over the browser's
            # localStorage on sync, so writing the full_enterprise map here
            # forces all menus on for them on every login. Idempotent: it is
            # re-applied on each startup, which also backfills accounts that
            # were created before this.
            from app.core.onboarding_presets import get_preset, modules_for

            _full_preset = get_preset("full_enterprise")
            if _full_preset is not None:
                _full_modules = list(_full_preset.enabled_modules)
                _full_prefs = modules_for(_full_modules)
                for _u in (demo, manager_user):
                    if _u is None:
                        continue
                    _md = dict(_u.metadata_ or {})
                    _md["module_preferences"] = _full_prefs
                    _md["onboarding"] = {
                        "completed": True,
                        "company_type": "full_enterprise",
                        "enabled_modules": _full_modules,
                        "interface_mode": "advanced",
                    }
                    _u.metadata_ = _md

            # Persist the demo users now, before the project seed runs in a
            # separate session below.
            await session.commit()

        # ── 2b. Starter labor rate library ────────────────────────────
        # Rate templates are owner-scoped, so unlike the platform-wide library
        # seeds (waste factors, production norms, assemblies) there is no
        # ownerless row that fills the page for everyone: a NULL owner is
        # readable by an admin alone. The library is seeded against the
        # estimator account, the persona that builds rates, and the admin
        # accounts see it regardless because their collection view is
        # unscoped. Where no estimator account exists it lands on the demo
        # admin instead, so the picker is never empty.
        #
        # Its own session, like every other seeder here, and fail-soft: an
        # empty rate library is a screen worth filling, never a reason to
        # abort the demo seed. Idempotent per owner, so a restart cannot
        # double the library and a rate the user has corrected is left alone.
        rate_owner_id = estimator_user_id or demo_user_id
        if rate_owner_id:
            try:
                from app.modules.labor_rates.seed import seed_labor_rates

                async with async_session_factory() as rate_session:
                    await seed_labor_rates(rate_session, uuid.UUID(rate_owner_id))
                    await rate_session.commit()
            except Exception:
                logger.warning("Labor rate starter library seed skipped (non-fatal)", exc_info=True)

        # ── 3. Project seed (outside the user session) ────────────────
        # Two distinct seeding paths run on PostgreSQL, picked by whether a
        # partner pack is active:
        #
        #   PACK MODE  (a pack is active): seed ONLY that pack's own country
        #     project(s) so the workspace reflects the partner's region,
        #     currency and classification - nothing else.
        #
        #   GENERIC MODE (no pack): seed the rich showcase - the country
        #     projects in SHOWCASE_DEMO_IDS plus the flagship reference
        #     project installed further below - so a fresh, vanilla install
        #     lands a fully worked-out, globe-spanning portfolio.
        #
        # Both paths install each project in its own try/except so one failure
        # never aborts the rest of the seed.
        if project_count == 0:
            from app.core.partner_pack.discovery import get_active_pack

            active = None
            try:
                active = get_active_pack()
            except Exception:
                logger.debug("Active partner pack lookup failed (treating as none)", exc_info=True)

            if active is not None:
                # PACK MODE - seed only the active pack's project(s). Prefer the
                # manifest's explicit demo_template_ids (filtered to ids that
                # resolve in DEMO_TEMPLATES), then fall back to the single
                # PACK_DEMO_PROJECT flagship mapping. Tag every row with the
                # pack slug so scope_project_query keeps the workspace clean.
                from app.core.demo_projects import (
                    DEMO_TEMPLATES,
                    PACK_DEMO_PROJECT,
                    install_demo_project,
                )

                pack_ids: list[str] = []
                for demo_id in getattr(active, "demo_template_ids", None) or []:
                    if demo_id in DEMO_TEMPLATES and demo_id not in pack_ids:
                        pack_ids.append(demo_id)
                if not pack_ids:
                    fallback = PACK_DEMO_PROJECT.get(active.slug)
                    if fallback:
                        pack_ids = [fallback]

                for demo_id in pack_ids:
                    async with async_session_factory() as pk_session:
                        try:
                            pk_result = await install_demo_project(pk_session, demo_id, partner_pack=active.slug)
                            await pk_session.commit()
                            logger.info(
                                "Partner-pack demo installed: %s for pack %s (%s positions)",
                                demo_id,
                                active.slug,
                                pk_result.get("positions"),
                            )
                        except Exception:
                            await pk_session.rollback()
                            logger.warning(
                                "Failed to install partner-pack demo %s (skipping)",
                                demo_id,
                                exc_info=True,
                            )
                if not pack_ids:
                    logger.info(
                        "Partner pack %s is active but maps to no demo project; skipping demo seed.",
                        active.slug,
                    )
            else:
                # GENERIC MODE - seed the rich showcase by default. Tests ask for
                # a fast startup (OE_TEST_FAST_STARTUP), and operators can opt out
                # with OE_SKIP_SHOWCASE=1; both skip the showcase loop. The
                # flagship below still installs alongside it.
                _fast_startup = os.environ.get("OE_TEST_FAST_STARTUP", "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                _skip_showcase = os.environ.get("OE_SKIP_SHOWCASE", "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                if _fast_startup or _skip_showcase:
                    logger.debug(
                        "Showcase seed skipped (%s)",
                        "OE_TEST_FAST_STARTUP" if _fast_startup else "OE_SKIP_SHOWCASE",
                    )
                else:
                    from app.core.demo_projects import SHOWCASE_DEMO_IDS, install_demo_project

                    # One fresh session per project with its own commit/rollback,
                    # mirroring PACK MODE above. On PostgreSQL a failure inside
                    # install_demo_project aborts the surrounding transaction, so
                    # a single shared session plus one trailing commit would let
                    # one bad demo poison the txn and roll back every project that
                    # had already seeded. Isolating each project prevents that.
                    for demo_id in SHOWCASE_DEMO_IDS:
                        async with async_session_factory() as sc_session:
                            try:
                                result = await install_demo_project(sc_session, demo_id)
                                await sc_session.commit()
                                logger.info(
                                    "Showcase demo installed: %s (%s positions, %s %s)",
                                    demo_id,
                                    result.get("positions"),
                                    result.get("currency"),
                                    result.get("grand_total"),
                                )
                            except Exception:
                                await sc_session.rollback()
                                # ``exc_info`` because this failure is intermittent: a run
                                # where seven of the twelve skipped left twelve identical
                                # causeless lines, and the cause had to be reconstructed
                                # from a second boot. Every other non-fatal skip below
                                # already logs its traceback.
                                logger.warning(
                                    "Failed to install showcase demo %s (skipping)",
                                    demo_id,
                                    exc_info=True,
                                )

        # Flagship "Residential House" reference project - an ORM installer
        # running on PostgreSQL so the full CAD-to-BOQ showcase (real
        # DDC-converted IFC/RVT geometry + a CWICR-priced, BIM-linked Bill of
        # Quantities) is present out of the box. Idempotent, so it also
        # backfills existing databases on the next startup. Runs regardless of
        # project_count so an upgrade picks it up.
        #
        # Version sentinel: the whole backfill block below (flagship 6640-
        # element model + ~16MB geometry, Heilbronn showcase, equipment +
        # subcontractor demos, enrich_all) is idempotent but costs real time
        # on EVERY boot just to conclude "nothing to do". After a completed
        # run we stamp the app version into a small marker file in the data
        # dir; while the marker matches the running version the block is
        # skipped entirely. An upgrade changes app_version, so the backfills
        # still run once per version to pick up new demo content. Crash-safe:
        # an unreadable/missing marker (or a fresh DB - project_count == 0)
        # runs the seeds exactly as before.
        _seed_fast_startup = os.environ.get("OE_TEST_FAST_STARTUP", "").lower() in ("1", "true", "yes")
        _running_version = get_settings().app_version
        _backfill_current = (
            not _seed_fast_startup and project_count > 0 and _read_demo_backfill_version() == _running_version
        )
        if _seed_fast_startup:
            # The flagship installer writes a 6640-element model and ~16MB of
            # geometry; no test needs it, and it adds several seconds to every
            # per-module app startup. Skip it when the test suite asks for a
            # fast startup.
            logger.debug("Flagship seed skipped (OE_TEST_FAST_STARTUP)")
        elif _backfill_current:
            logger.info(
                "Demo backfill seeds skipped - already completed for version %s",
                _running_version,
            )
        else:
            # Tracks whether every named seeder below completed. A failed
            # seeder must NOT stamp the version marker - otherwise a
            # transient failure (DB hiccup mid-seed) would be skipped on
            # every subsequent boot until the next app upgrade instead of
            # self-healing on the next start.
            _backfill_ok = True
            try:
                from app.scripts.seed_flagship import install_flagship

                async with async_session_factory() as fl_session:
                    fl_result = await install_flagship(fl_session, demo_user_id)
                    logger.info("Flagship seed: %s", fl_result)
            except Exception:
                _backfill_ok = False
                logger.warning("Flagship seed skipped (non-fatal)", exc_info=True)

            # Retail Market Heilbronn - the ninth showcase project. Backfilled
            # flagship-style on EVERY boot (not just project_count == 0) so
            # existing installs pick it up on upgrade. install_demo_project
            # dedupes on metadata_["demo_id"], so once the project exists the
            # re-run is a cheap no-op. Operators who opted out of the showcase
            # keep their workspace clean.
            if os.environ.get("OE_SKIP_SHOWCASE", "").lower() in ("1", "true", "yes"):
                logger.debug("Retail Market Heilbronn backfill skipped (OE_SKIP_SHOWCASE)")
            else:
                try:
                    from app.core.demo_projects import install_demo_project as _install_demo

                    async with async_session_factory() as rh_session:
                        rh_result = await _install_demo(rh_session, "retail-market-heilbronn")
                        await rh_session.commit()
                        if not rh_result.get("already_installed"):
                            logger.info(
                                "Retail Market Heilbronn showcase seeded: %s (%s positions)",
                                rh_result.get("project_id"),
                                rh_result.get("positions"),
                            )
                except Exception:
                    _backfill_ok = False
                    logger.warning(
                        "Retail Market Heilbronn showcase backfill skipped (non-fatal)",
                        exc_info=True,
                    )

            # Equipment & fleet demo - a representative fleet with 90 days of
            # telemetry so the predictive Health & Analytics tab and Fleet
            # Intelligence panel arrive populated (gauge, anomalies, forecast,
            # underutilised units, savings) rather than empty. Idempotent: the
            # seed skips when EQ-0001 already exists.
            try:
                from app.modules.equipment.seed import seed_equipment_demo

                async with async_session_factory() as eq_session:
                    eq_counts = await seed_equipment_demo(eq_session)
                    await eq_session.commit()
                    if any(eq_counts.values()):
                        logger.info("Equipment demo seed: %s", eq_counts)
            except Exception:
                _backfill_ok = False
                logger.warning("Equipment demo seed skipped (non-fatal)", exc_info=True)

            # Subcontractor demo - 50 firms with varied prequalification states
            # and 24 months of rating rollups for the top 10, plus agreements on
            # the flagship project. Feeds the vendor scorecard (rating dials +
            # period history) and the procurement prequalification badges /
            # award gate. Idempotent: skips when any subcontractor exists.
            try:
                from sqlalchemy import select as _select

                from app.modules.projects.models import Project as _Project
                from app.modules.subcontractors.seed import seed_subcontractors_demo

                async with async_session_factory() as sub_session:
                    # Attach agreements to whatever demo project exists (the
                    # flagship is installed above); None just skips agreements,
                    # leaving the subs + ratings the scorecard needs.
                    _proj_id = (await sub_session.execute(_select(_Project.id).limit(1))).scalars().first()
                    sub_counts = await seed_subcontractors_demo(sub_session, project_id=_proj_id)
                    await sub_session.commit()
                    if any(sub_counts.values()):
                        logger.info("Subcontractor demo seed: %s", sub_counts)
            except Exception:
                _backfill_ok = False
                logger.warning("Subcontractor demo seed skipped (non-fatal)", exc_info=True)

            # ── Remaining feature-module demos ──────────────────────────────
            # bid management, carbon, CRM, HSE-Advanced, portal, QMS, advanced
            # scheduling (Last Planner), service management, supplier catalogs,
            # variations, photos, takeoff, clash, costmodel, moc, markups,
            # catalog and BIM grouping each ship a demo seeder. They used to be
            # inlined here; the same list now lives in a reusable, fail-soft
            # coroutine so the in-app partner-pack apply paths run the exact same
            # enrichment instead of opening with empty modules. ``enrich_all``
            # enriches every project that exists at boot, each seeder in its own
            # session so one failure cannot poison the rest.
            from app.core.demo_enrichment import enrich_all

            await enrich_all()

            # Stamp the sentinel only when every named seeder completed.
            # On a failed pass the marker stays absent/stale, so the next
            # boot retries the (idempotent) seeds instead of skipping them
            # until the next app upgrade.
            if _backfill_ok:
                _write_demo_backfill_version(_running_version)
            else:
                logger.info("Demo backfill marker not stamped - at least one seeder failed; will retry next boot")
    except Exception:
        logger.exception("Failed to seed demo account (non-fatal)")


def create_app() -> FastAPI:
    """Application factory.

    Creates and configures the FastAPI application:
    1. Load settings
    2. Configure logging
    3. Create FastAPI instance
    4. Add middleware
    5. Mount system routes
    6. Discover & load modules (on startup)
    """
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Open-source modular platform for construction cost estimation",
        contact={
            "name": "DataDrivenConstruction · OpenConstructionERP",
            "url": "https://openconstructionerp.com",
            "email": "info@datadrivenconstruction.io",
        },
        license_info={
            "name": "AGPL-3.0-or-later · DDC-CWICR-OE-2026",
            "url": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
        # Swagger UI is registered by hand further down instead of by FastAPI,
        # so the page can load its CSS and JS from this install rather than
        # from a CDN. Everything else about the route is unchanged - the
        # replacement calls the same ``get_swagger_ui_html`` with the same
        # arguments and only swaps the two asset URLs. ReDoc keeps the stock
        # route and still needs outbound internet.
        docs_url=None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        # Swagger UI draws whatever the document holds, and this document holds
        # 2923 paths, 3938 operations and 3601 component schemas. Left on the
        # stock settings the page expands every operation and the whole model
        # list on load: measured in headless Chromium against this app, 130.5s
        # from navigation to the first operation appearing, which is the "blank
        # page" an operator actually experiences and is not something caching
        # the schema on the server can fix. Collapsed, the browser lays out 365
        # tag headers instead of 3938 operation bodies, and the models section
        # is built when somebody asks for it rather than on every load.
        swagger_ui_parameters={"docExpansion": "none", "defaultModelsExpandDepth": -1},
        # BUG-394: don't expose the full OpenAPI schema in production - it
        # hands attackers a route/parameter enumeration map of every endpoint,
        # including rarely-exercised admin surfaces. Dev still gets it for
        # the Swagger/ReDoc UI and for openapi-typescript client generation.
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        swagger_ui_oauth2_redirect_url=("/api/docs/oauth2-redirect" if not settings.is_production else None),
        redirect_slashes=False,
        # Row-level-security: bind the caller's tenant to the request context on
        # every route, so the after_begin GUC listener (app.core.rls) can scope
        # tenant-owned tables in PostgreSQL. Anonymous callers bind no tenant.
        # Inert until OE_RLS_ENFORCE is enabled and requests connect through the
        # non-superuser role.
        # Read-only demo guard first, and deliberately ahead of the RLS context:
        # a refused request must not pay for token decoding or a tenant lookup,
        # and an anonymous caller must get the 403 rather than a 401. Inert
        # unless OE_DEMO_READ_ONLY is on - see app.core.demo_read_only.
        dependencies=[Depends(demo_read_only_guard), Depends(rls_request_context)],
        # NOTE: do NOT set default_response_class=ORJSONResponse here.
        # FastAPI's own deprecation warning explains why: "FastAPI now
        # serializes data directly to JSON bytes via Pydantic when a
        # return type or response model is set, which is faster and
        # doesn't need a custom response class." More importantly,
        # orjson rejects NaN/Infinity floats by default - DDC cad2data
        # BIM elements occasionally emit NaN bbox coordinates for
        # degenerate geometry, which would 500 the response. Stick with
        # FastAPI's default Pydantic-direct path; orjson is still used
        # by handlers that explicitly opt in.
    )

    # ── Boot-time schema heal verdict, scoped to this application ────────
    # Three states, and they are three: ``False`` healed, ``True`` failed,
    # ``None`` never ran. The last one is not a corner case. The heal lives
    # inside ``if "postgresql" in settings.database_url`` in the startup below,
    # so a deployment whose ``DATABASE_URL`` is not PostgreSQL never reaches it
    # and stays at this value for its whole life. Reporting that as ``False``
    # says "healed fine" about a heal that never happened, which is exactly the
    # mistake ``alembic_head_state`` exists to stop making one field away in the
    # same health payload.
    #
    # It is also the value between building the application and startup writing
    # a verdict. That window is not visible to an HTTP caller - the server does
    # not accept requests until the lifespan startup returns, and a startup that
    # raises takes the process down rather than serving - but it is visible to
    # anything holding the application object directly, an in-process ASGI test
    # client included.
    #
    # The signal exists because the heal is deliberately non-fatal, and a
    # non-fatal failure that only reaches the log is invisible on the deployment
    # it actually ruins: an external PostgreSQL whose role has no DDL rights.
    # There the heal cannot add a single column, the application starts and
    # looks fine, and the first read of any table that gained a column since
    # that database was created answers 500 with an undefined-column error.
    #
    # ``schema_heal_error`` holds the cause for the boot log and for an operator
    # with access to this process. It is deliberately NOT published by
    # ``/api/health``; see that endpoint's docstring for why.
    #
    # Both live on ``app.state`` rather than in a module global because a module
    # global outlives the application it describes: in one process that builds a
    # second application - which the test suite does routinely - that second one
    # would inherit the first one's verdict about a database it never opened.
    app.state.schema_heal_failed = None
    app.state.schema_heal_error = None

    # ── Does the schema still match the models ───────────────────────────
    # The field above says whether the heal RAISED. This one says whether the
    # database and the models agree once it has finished, which is a different
    # question with a different answer: the heal completes successfully and
    # still leaves a NOT NULL it could not carry, because adding one to a
    # populated table fails and adding the column nullable does not. Three
    # states again - True they agree, False they do not, None never asked,
    # which is where a deployment whose database is not PostgreSQL stays.
    app.state.schema_matches_models = None
    app.state.schema_divergent_columns = ()

    # ── Boot-time data-repair verdict ────────────────────────────────────
    # Same three states, for the same reason, about the other half of an
    # upgrade. The heal above moves the SCHEMA; it rewrites no rows, so a
    # migration whose body backfills, renames or de-duplicates never executes
    # on any install brought up this way while ``alembic_version`` reports head.
    # ``app.core.data_repairs`` is where the rewrites that have to reach those
    # installs are written instead, and this is the verdict of running them.
    #
    # ``None`` is again "never ran", which covers a non-PostgreSQL deployment
    # and the window before startup writes a verdict. ``True`` means rows that
    # should have been rewritten were not, either because a repair raised or
    # because the module holding it never imported and so registered nothing to
    # run. The ids are in ``data_repairs_failed_ids``, where an unimported
    # module is marked apart from a repair id, and the causes are in the log.
    app.state.data_repairs_failed = None
    app.state.data_repairs_failed_ids = ()

    # ── Boot-time data-repair LEDGER verdict ─────────────────────────────
    # The other half of the same report, and a genuinely different failure.
    # ``run_data_repairs`` writes a row per repair to ``oe_data_repair_ledger``
    # recording what it did and under which release, and that write can fail on
    # its own: an external database whose role may write rows but not create
    # tables gets correct data and no record of it. Collapsing the two into one
    # field would let the smaller failure hide behind the larger, so the runner
    # reports them separately and so does this.
    #
    # Same three states as the field above, same polarity: ``None`` the pass
    # never ran, ``False`` every ledger row was written, ``True`` at least one
    # write failed. ``False`` here cannot be mistaken for "did not run", because
    # a pass that did not run never leaves ``None``.
    app.state.data_repair_ledger_failed = None

    # ── OpenAPI origin extension ─────────────────────────────────────────
    # Stamp an x- vendor extension into info{} so any fork that exposes
    # /api/openapi.json or /api/docs leaks provenance. ``x-`` extensions
    # are valid per the OpenAPI spec and ignored by every generator /
    # client (incl. openapi-typescript), so the API surface is unchanged.
    # The token bytes XOR-decode (key 0x55) to the authorship marker.
    import threading as _threading

    from fastapi.openapi.utils import get_openapi as _get_openapi

    # Building this document walks every mounted route and every model behind
    # it, and with the module loader mounting ~190 routers that is not a small
    # job: 2922 paths and 3601 component schemas, and 140.97s to assemble on
    # the 16.8.0 stand, measured from the server's own slow-request log. It
    # runs on the event loop, so the process answers nothing at all while it
    # happens. The result was already cached here, but only lazily, by whoever
    # asked for it first, which meant the first visitor to /api/docs after
    # every restart paid the whole 141s and froze the app for everyone else
    # meanwhile. Every later request was served from the cache in about half a
    # second, so generation outweighed serialising the 6.75 MB body by roughly
    # 235 to 1. The prime at the end of the startup lifespan fills the cache
    # off the event loop so that first request is never the one that pays.
    _openapi_build_lock = _threading.Lock()

    def _routes_version() -> int | None:
        """Return the router's route-table counter, or ``None`` if unavailable.

        FastAPI keys its own schema cache on this counter and rebuilds when it
        moves. Here that invalidation is load-bearing rather than decorative:
        modules mount their routers during the startup lifespan, and
        ``enable_module`` mounts one at runtime, long after boot. A cache keyed
        on nothing but "is it populated" pins the first document forever, so a
        module enabled later never appears in the docs at all.

        Private FastAPI API, hence the getattr. If a future release drops it
        this returns ``None`` on both sides of the comparison, which degrades
        to "serve the cache until something clears it" - exactly what this
        override did before, so the fallback is the old behaviour rather than
        a new failure.
        """
        getter = getattr(app.router, "_get_routes_version", None)
        return getter() if callable(getter) else None

    def _custom_openapi() -> dict[str, Any]:
        version = _routes_version()
        if app.openapi_schema is not None and app._openapi_routes_version == version:
            return app.openapi_schema
        # One builder at a time. The startup prime runs on a worker thread, so
        # without this a request arriving mid-build starts a second, equally
        # expensive build beside it: two 141s passes competing for the same
        # core on a 2 GB VPS. Whoever loses the race re-checks under the lock
        # and takes the document the winner just cached.
        with _openapi_build_lock:
            version = _routes_version()
            if app.openapi_schema is not None and app._openapi_routes_version == version:
                return app.openapi_schema
            schema = _get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
                contact=app.contact,
                license_info=app.license_info,
            )
            _oa_tok = bytes(
                b ^ 0x55 for b in b"\x11\x11\x16\x78\x16\x02\x1c\x16\x07\x78\x1a\x10\x78\x67\x65\x67\x63"
            ).decode("ascii")
            schema.setdefault("info", {})
            schema["info"]["x-ddc-origin"] = "OpenConstructionERP · DataDrivenConstruction · " + _oa_tok
            schema["info"]["x-ddc-author"] = "Artem Boiko <info@datadrivenconstruction.io>"
            app.openapi_schema = schema
            app._openapi_routes_version = version
            return schema

    app.openapi = _custom_openapi  # type: ignore[method-assign]

    # ── Swagger UI, served from this install ─────────────────────────────
    # FastAPI's stock /api/docs pulls swagger-ui-bundle.js and swagger-ui.css
    # from cdn.jsdelivr.net, so the page renders as an empty shell anywhere
    # without outbound internet. A self-hosted VPS is what this platform is
    # for and an air-gapped site is a normal deployment, so the two files ship
    # in the wheel instead: 1.74 MB on disk, about 438 KB of the archive once
    # deflated, and no new dependency. Pinned to swagger-ui-dist 5.32.15,
    # because the stock template asks for "@5", which is a moving target.
    _SWAGGER_DIR = Path(__file__).parent / "static" / "swagger"
    _SWAGGER_ASSETS = {
        "swagger-ui-bundle.js": "application/javascript",
        "swagger-ui.css": "text/css",
    }

    if not settings.is_production:
        from fastapi import Request as _Request
        from fastapi.openapi.docs import get_swagger_ui_html as _get_swagger_ui_html
        from fastapi.openapi.docs import (
            get_swagger_ui_oauth2_redirect_html as _get_swagger_ui_oauth2_redirect_html,
        )
        from fastapi.responses import FileResponse as _FileResponse
        from fastapi.responses import HTMLResponse as _HTMLResponse
        from fastapi.responses import Response as _Response

        async def _swagger_asset(req: _Request) -> _Response:
            # Matched against the two names by hand rather than mounted as a
            # directory: a StaticFiles mount would put path traversal between
            # the network and the installed package for the sake of two files.
            # Returned rather than raised, so an unknown name stays a 404
            # instead of reaching the SPA handler and coming back as index.html.
            media_type = _SWAGGER_ASSETS.get(req.path_params.get("filename", ""))
            if media_type is None:
                return _Response(status_code=404)
            return _FileResponse(
                _SWAGGER_DIR / req.path_params["filename"],
                media_type=media_type,
                # Version-pinned bytes that only change when the wheel does.
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

        async def _swagger_ui_html(req: _Request) -> _HTMLResponse:
            # The same call FastAPI's own route makes, with the same root_path
            # handling, differing only in where the two assets come from.
            root_path = req.scope.get("root_path", "").rstrip("/")
            oauth2_redirect_url = app.swagger_ui_oauth2_redirect_url
            if oauth2_redirect_url:
                oauth2_redirect_url = root_path + oauth2_redirect_url
            return _get_swagger_ui_html(
                openapi_url=root_path + (app.openapi_url or "/api/openapi.json"),
                title=f"{app.title} - Swagger UI",
                oauth2_redirect_url=oauth2_redirect_url,
                init_oauth=app.swagger_ui_init_oauth,
                swagger_ui_parameters=app.swagger_ui_parameters,
                swagger_js_url=f"{root_path}/api/docs/assets/swagger-ui-bundle.js",
                swagger_css_url=f"{root_path}/api/docs/assets/swagger-ui.css",
                # The stock default is fastapi.tiangolo.com, a third outbound
                # request on a page that is meant to work without a network.
                swagger_favicon_url=f"{root_path}/favicon.svg",
            )

        async def _swagger_ui_redirect(req: _Request) -> _HTMLResponse:
            return _get_swagger_ui_oauth2_redirect_html()

        # ``add_route`` rather than ``@app.get``, because that is what FastAPI
        # itself uses for these three and it is the difference between a plain
        # Starlette route and one carrying the app-level dependencies declared
        # above. Documentation should not be running the read-only guard or
        # binding an RLS tenant, and the route it replaces never did.
        app.add_route("/api/docs/assets/{filename}", _swagger_asset, methods=["GET"], include_in_schema=False)
        app.add_route("/api/docs", _swagger_ui_html, methods=["GET"], include_in_schema=False)
        if app.swagger_ui_oauth2_redirect_url:
            # FastAPI registers this one inside the same block as its docs
            # route, so taking that route over means taking this one with it.
            app.add_route(
                app.swagger_ui_oauth2_redirect_url,
                _swagger_ui_redirect,
                methods=["GET"],
                include_in_schema=False,
            )

    # ── Middleware ───────────────────────────────────────────────────────
    cors_origins = settings.cors_origins
    # Security: block wildcard origins in production
    if settings.is_production and "*" in cors_origins:
        logger.warning(
            "CORS: wildcard '*' origin is not allowed in production. Set ALLOWED_ORIGINS to your actual domain(s)."
        )
        cors_origins = [o for o in cors_origins if o != "*"]
        if not cors_origins:
            cors_origins = ["https://openconstructionerp.com"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Accept", "Accept-Language"],
        # A list route that pages returns the number of matches behind the page
        # in X-Total-Count, and a BCF export returns how many topics went into
        # the archive in X-BCF-Topic-Count. A browser hides every response
        # header a server does not name here, so without this the count reaches
        # a frontend served from another origin and cannot be read there.
        expose_headers=["X-Total-Count", "X-BCF-Topic-Count"],
    )

    # ── API Version header ──────────────────────────────────────────────
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response as StarletteResponse

    class APIVersionMiddleware(BaseHTTPMiddleware):
        """Add X-API-Version response header to every API response."""

        async def dispatch(self, request: StarletteRequest, call_next):  # noqa: ANN001, ANN201
            response: StarletteResponse = await call_next(request)
            response.headers["X-API-Version"] = settings.app_version
            return response

    app.add_middleware(APIVersionMiddleware)

    # ── Reject non-finite floats in JSON request bodies ─────────────────
    # Python's ``json`` decoder accepts the non-standard ``NaN`` / ``Infinity``
    # literals by default. Several handlers use those values in Decimal
    # arithmetic downstream and raise ``decimal.InvalidOperation`` → 500.
    # We refuse them up-front with 422 so clients get a deterministic error
    # and Pydantic validators still see finite numbers.
    import re as _re

    import orjson as _orjson
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    _NONFINITE_TOKEN_RE = _re.compile(rb"\b(NaN|-?Infinity)\b")

    class _RejectNonFiniteJSONMiddleware:
        """Pure-ASGI middleware so we can rewrite the receive() stream."""

        def __init__(self, app: ASGIApp) -> None:
            self.inner = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                await self.inner(scope, receive, send)
                return
            method = scope.get("method", "").upper()
            if method not in ("POST", "PUT", "PATCH"):
                await self.inner(scope, receive, send)
                return
            headers = dict(scope.get("headers") or [])
            content_type = headers.get(b"content-type", b"").decode("latin-1", "ignore")
            if "application/json" not in content_type.lower():
                await self.inner(scope, receive, send)
                return

            # Drain body up-front so we can scan it AND replay it to the app.
            body = bytearray()
            more = True
            while more:
                message = await receive()
                if message["type"] != "http.request":
                    await self.inner(scope, receive, send)
                    return
                body.extend(message.get("body") or b"")
                more = message.get("more_body", False)

            if _NONFINITE_TOKEN_RE.search(bytes(body)):
                # Extra safety: confirm the tokens occur outside a string literal
                # before rejecting. ``orjson`` rejects non-finite floats by
                # default, so parsing failure with the token present = real
                # non-finite number.
                try:
                    _orjson.loads(bytes(body))
                except _orjson.JSONDecodeError:
                    from starlette.responses import JSONResponse

                    resp = JSONResponse(
                        status_code=422,
                        content={"detail": ("NaN and Infinity are not accepted in numeric fields")},
                    )
                    await resp(scope, receive, send)
                    return

            sent = False

            async def replay() -> Message:
                # First call: hand the app the fully buffered body. Every
                # subsequent call must delegate to the *real* receive() - it
                # MUST NOT synthesize ``http.disconnect`` here. Streaming
                # responses (SSE: /erp_chat/stream/, AI chat) run
                # ``listen_for_disconnect`` concurrently with the body
                # generator under Starlette's StreamingResponse; a premature
                # fake ``http.disconnect`` made that watcher return instantly
                # and cancel the stream before a single byte was sent (the
                # endpoint returned HTTP 200 with a 0-byte body). Forwarding
                # the genuine receive() preserves real client-disconnect
                # detection without killing live streams.
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.inner(scope, replay, send)

    app.add_middleware(_RejectNonFiniteJSONMiddleware)

    # ── DDC Fingerprint ──────────────────────────────────────────────────
    from app.middleware.fingerprint import DDCFingerprintMiddleware

    app.add_middleware(DDCFingerprintMiddleware)

    # ── Security headers (X-Frame-Options, CSP, HSTS, etc.) ──────────────
    from app.middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    # ── Request correlation ID (must precede SlowRequestLogger so its log
    # lines carry the ID via the RequestIDLogFilter context) ───────────────
    # ── Universal audit capture context (Epic H) ──────────────────────────
    # Sets the per-request AuditContext ContextVar so :func:`log_activity`
    # can persist the peer IP, User-Agent, and correlation ID without
    # service-layer callers having to thread the values manually.
    # Starlette runs middleware in REVERSE registration order - the
    # ``add_middleware(RequestIDMiddleware)`` call below must come AFTER
    # this one so the request-id ContextVar is set BEFORE
    # ActorContextMiddleware reads it via ``get_request_id()``.
    from app.middleware.actor_context import ActorContextMiddleware
    from app.middleware.request_id import RequestIDMiddleware

    app.add_middleware(ActorContextMiddleware)

    app.add_middleware(RequestIDMiddleware)

    # ── Slow request logger (warns on > 500ms responses) ──────────────────
    from app.middleware.slow_request_logger import SlowRequestLoggerMiddleware

    app.add_middleware(SlowRequestLoggerMiddleware)

    # ── Accept-Language (sets i18n context locale per request) ────────────
    from app.middleware.accept_language import AcceptLanguageMiddleware

    app.add_middleware(AcceptLanguageMiddleware)

    # ── Response compression ──────────────────────────────────────────────
    # Every screen pulls a 2.44 MB application bundle and a 2.21 MB locale
    # chunk before it draws, and both went over the wire uncompressed although
    # the browser asked for gzip each time. That is the whole of the four
    # seconds the case audits measured on the snag register and the bill
    # editor; the endpoints behind those screens answer in under a tenth of a
    # second. Text only, and only when the length is known, so exports and
    # photo bytes are passed through rather than re-compressed.
    from app.middleware.compression import CompressionMiddleware

    app.add_middleware(CompressionMiddleware)

    # ── Request-body-size backstop (added last -> outermost -> runs first) ─
    # Coarse global ceiling above every per-endpoint upload cap. Rejects an
    # absurdly large body before any other middleware or endpoint reads it, so
    # a single oversized request can't OOM the worker. Per-endpoint caps remain
    # the fine-grained defense.
    from app.middleware.body_size_limit import MaxBodySizeMiddleware

    app.add_middleware(MaxBodySizeMiddleware, max_body_bytes=settings.max_request_body_bytes)

    # ── Global exception handler - return JSON for unhandled errors ────
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from app.middleware.request_id import get_request_id

    # ── Read-only demo: translate a refused write into the 403 contract ──
    # Layer 1 raises the HTTPException itself; this is for layer 2, which fires
    # from inside SQLAlchemy's cursor execution. Two handlers, because the
    # driver may re-raise the error wrapped in a StatementError: the direct one
    # below catches the plain case, and the global handler further down walks
    # the __cause__ / __context__ chain for the wrapped one. Both answer with
    # exactly the same body, so a client cannot tell which layer refused.
    def _demo_read_only_in_chain(exc: BaseException) -> DemoReadOnlyError | None:
        seen: set[int] = set()
        cursor: BaseException | None = exc
        while cursor is not None and id(cursor) not in seen:
            if isinstance(cursor, DemoReadOnlyError):
                return cursor
            seen.add(id(cursor))
            cursor = cursor.__cause__ or cursor.__context__
        return None

    def _demo_read_only_response() -> JSONResponse:
        refusal = read_only_refusal()
        return JSONResponse(status_code=refusal.status_code, content={"detail": refusal.detail})

    @app.exception_handler(DemoReadOnlyError)
    async def demo_read_only_handler(request: Request, exc: DemoReadOnlyError) -> JSONResponse:
        logger.info(
            "demo read-only: %s %s refused at the database (%s on %s)",
            request.method,
            request.url.path,
            exc.kind,
            exc.table or "an unnamed target",
        )
        return _demo_read_only_response()

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        demo_refusal = _demo_read_only_in_chain(exc)
        if demo_refusal is not None:
            logger.info(
                "demo read-only: %s %s refused at the database (%s on %s)",
                request.method,
                request.url.path,
                demo_refusal.kind,
                demo_refusal.table or "an unnamed target",
            )
            return _demo_read_only_response()
        # Surface the SAME correlation id the RequestIDMiddleware already
        # assigned (and echoed on the X-Request-ID response header) - do NOT
        # mint a new one. A client / support engineer can quote this id and we
        # can find the matching ``logger.exception`` line below in the server
        # logs (the RequestIDLogFilter tags every record with it). The full
        # stack trace stays server-side; the client only ever sees the opaque
        # id, never the exception text.
        request_id = get_request_id()
        logger.exception(
            "Unhandled exception on %s %s (request_id=%s)",
            request.method,
            request.url.path,
            request_id or "-",
        )
        body: dict[str, str] = {"detail": "Internal server error"}
        if request_id:
            body["request_id"] = request_id
        response = JSONResponse(status_code=500, content=body)
        # The exception path bypasses the RequestIDMiddleware's normal
        # response-header injection (the middleware's call_next raised), so
        # re-attach the header here for trace correlation parity.
        if request_id:
            response.headers["X-Request-ID"] = request_id
        return response

    # BUG-API02: sanitise FastAPI's default RequestValidationError response.
    #
    # Out of the box FastAPI returns 422 with a body that exposes the path
    # parameter name and its expected Pydantic type, e.g.
    #   {"detail":[{"type":"uuid_parsing","loc":["path","user_id"],"input":"abc"}]}
    # An unauthenticated probe can read those bodies to enumerate the route
    # surface (param names + types). For path-param validation failures -
    # which mostly mean "the URL was malformed" - we collapse the response
    # to a generic 400 with no schema details.
    #
    # Body / query-param validation errors keep the legacy 422 + detail
    # behaviour because those are real client-error feedback (e.g. POST
    # /users/ with role="god" must surface "role: invalid value" so the
    # admin UI can show a useful message).  When ``app_debug`` is on, the
    # full Pydantic detail is preserved everywhere so developers can still
    # see what they broke.
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        path_only = bool(errors) and all((err.get("loc") or [None])[0] == "path" for err in errors)

        if path_only and not settings.app_debug:
            # No detail leak - just acknowledge the URL is malformed.
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid request"},
            )

        # Body / query / header validation: keep informative detail so
        # client UIs can render per-field errors.  In production we still
        # strip the raw input echo (Pydantic includes the offending value
        # in ``input`` which can echo PII / tokens).
        # ``ctx.error`` is a raw ``ValueError`` instance for ``value_error``
        # entries - not JSON-serialisable - so always coerce to ``str``
        # before emitting (regression seen with custom ``field_validator``
        # raises in BUG-MATH03 unit-catalogue checks).
        def _json_safe(v: object) -> object:
            if isinstance(v, (str, int, float, bool, type(None))):
                return v
            if isinstance(v, (list, tuple)):
                return [_json_safe(x) for x in v]
            if isinstance(v, dict):
                return {str(k): _json_safe(x) for k, x in v.items()}
            return str(v)

        def _scrub(err: dict) -> dict:
            return _json_safe(dict(err))

        if settings.app_debug:
            safe_errors = [_scrub(e) for e in errors]
        else:
            safe_errors = [{k: v for k, v in _scrub(err).items() if k != "input"} for err in errors]
        return JSONResponse(
            status_code=422,
            content={"detail": safe_errors},
        )

    # ── System Routes ───────────────────────────────────────────────────
    from app.core.i18n_router import router as i18n_router

    app.include_router(i18n_router, prefix="/api/v1")

    # Desktop first-run / bootstrap auth endpoints. The users module router is
    # auto-mounted by the loader at /api/v1/users, but the desktop shell needs
    # a short app-level path it can call without knowing the module mount, so
    # these two routes are mounted explicitly at /api/v1/auth/.
    from app.modules.users.router import desktop_auth_router

    app.include_router(desktop_auth_router, prefix="/api/v1/auth")

    # The desktop launcher's clean-stop request. Mounted at its full path (no
    # prefix) because the launcher has to be able to call it without knowing
    # anything about API versions, and refused for everyone else by the guards
    # in the module itself - desktop mode, loopback, and the launcher's token.
    from app.core.desktop_shutdown import router as desktop_shutdown_router

    app.include_router(desktop_shutdown_router)

    # Workspace white-label branding. GET is public (the login page reads it
    # before sign-in so invited users see the workspace brand); PUT/DELETE are
    # admin-only. Persisted to a JSON file in the data dir, so no migration.
    from app.core.branding_router import router as branding_router

    app.include_router(branding_router, prefix="/api/v1")

    # The third-party licence texts that ship inside every artefact. Public for
    # the same reason branding's GET is: they are published documents that say
    # nothing about this workspace. They travelled with the product for its
    # whole life with nothing able to read them, which on an offline desktop
    # install left the About panel's gnu.org link pointing at nothing.
    from app.core.license_router import router as license_router

    app.include_router(license_router, prefix="/api/v1")

    # Module management API (list / enable / disable)
    from app.core.module_router import router as module_mgmt_router

    app.include_router(module_mgmt_router)

    # Audit log API (admin-only)
    from app.core.audit_router import router as audit_router

    app.include_router(audit_router)

    # Global search API (cross-module)
    from app.core.global_search_router import router as search_router

    app.include_router(search_router)

    # Activity feed API (cross-module)
    from app.core.activity_feed_router import router as activity_router

    app.include_router(activity_router)

    # Sidebar badge counts (single endpoint for Tasks + RFI + Safety counts)
    from app.core.sidebar_badges_router import router as sidebar_badges_router

    app.include_router(sidebar_badges_router)

    # Translation service (element → catalog cross-lingual normalisation)
    from app.core.translation.router import router as translation_router

    app.include_router(translation_router, prefix="/api/v1")

    # Partner-pack system - discovers pip-installed packs via entry_points
    # and exposes the active manifest + branded resources.
    from app.core.partner_pack.discovery import get_active_pack
    from app.core.partner_pack.router import alias_router as packs_alias_router
    from app.core.partner_pack.router import router as partner_pack_router

    app.include_router(partner_pack_router)
    # Canonical Packs-umbrella alias (/api/v1/packs/*) sharing the same handlers.
    app.include_router(packs_alias_router)
    _active_pack = get_active_pack()
    if _active_pack:
        logger.info(
            "Partner pack active: %s (%s) v%s",
            _active_pack.slug,
            _active_pack.partner_name,
            _active_pack.pack_version,
        )

    # Store startup time for uptime calculation
    _startup_time: float = time.time()

    @app.get("/api/health", tags=["System"])
    async def health_check() -> dict[str, Any]:
        """Whether this process is running and fit to be used.

        This endpoint is UNAUTHENTICATED on purpose. The desktop shell polls it
        with no Authorization header to decide whether it may attach to a
        backend that is already running rather than start a second one against
        the same data directory, and container healthchecks want the same answer
        on the same terms. So everything here is public, and nothing here may
        carry text describing the internals of the deployment.

        That is why the schema-heal signal below is a boolean and only a
        boolean. What it reports is a database exception, and SQLAlchemy DBAPI
        errors stringify with the statement appended - ``[SQL: ALTER TABLE
        ...]``, frequently ``[parameters: ...]`` too - so putting the message in
        this payload would hand an anonymous caller the schema and the statement
        text of the deployment it can reach. The cause is written in full to the
        boot log, where the operator of that machine is, and is kept on
        ``app.state.schema_heal_error``. Should it ever be wanted over HTTP it
        belongs behind ``RequireRole("admin")``, beside
        ``/api/system/upgrade/status``, and not here.

        The same rule governs the two signals added since: which data repairs
        failed, and which repair modules could not be imported at all, is on
        ``app.state.data_repairs_failed_ids``, and which columns the schema has
        diverged on is on ``app.state.schema_divergent_columns``. Both are
        lists of internal names - a module path maps the deployment quite as
        well as a repair id does - and both stay in the log for the same reason
        the failing statement does.
        """
        import os as _os
        from pathlib import Path as _Path

        # Modules, and three numbers rather than one. ``modules_loaded`` was the
        # length of ``list_modules()``, which iterates the manifests that
        # parsed - so the field named for the loaded modules answered with the
        # discovered figure, counting modules the operator had switched off and
        # modules that never imported alike. Discovered, enabled and loaded move
        # independently, and a reader handed only their sum cannot tell which of
        # them dropped: a module switched off and a module that failed lower it
        # by exactly the same one, and only the second is a fault.
        #
        # Every row carries the two flags these are counted from, so the three
        # come out of one pass and cost nothing extra on an endpoint the desktop
        # launcher polls twice a second.
        _module_rows = module_loader.list_modules()
        result: dict[str, Any] = {
            "status": "healthy",
            "version": settings.app_version,
            "env": settings.app_env,
            "instance_id": _INSTANCE_ID,
            "build": f"DDC-{_BUILD_HASH}",
            "signature": build_provenance_tag(settings.app_version),
            "modules_discovered": len(_module_rows),
            "modules_enabled": sum(1 for _row in _module_rows if _row.get("enabled")),
            "modules_loaded": sum(1 for _row in _module_rows if _row.get("loaded")),
            "uptime_seconds": int(time.time() - _startup_time),
        }

        # A module the operator asked for that is not there. Counted per row and
        # never as ``modules_enabled - modules_loaded``, because those are
        # different claims: ``resolve_order`` recurses into a module's
        # dependencies without asking whether the dependency is enabled, so a
        # disabled module pulled in by an enabled one comes back loaded and not
        # enabled, and one row of that shape cancels one row of this one. The
        # subtraction then reads zero across an install that has lost a module.
        #
        # The state is reachable at runtime and not at boot: ``load_all``
        # re-raises, so a module that cannot be imported at startup takes the
        # process down and never answers this probe. ``enable_module`` is the
        # path - it marks the manifest enabled and drops the name from the
        # disabled set BEFORE importing the package, and an import that raises
        # there leaves the registry holding a module that is enabled and absent
        # until somebody restarts, with every endpoint it owns answering 404.
        #
        # It degrades the status, and it is the only module condition that does.
        # Told healthy, a person looking for a feature that is missing concludes
        # their edition does not include it and stops, which is the one wrong
        # conclusion on offer; told degraded beside the two counts, they restart
        # or reinstall, which is the fix. A disabled module is a choice and not a
        # fault, and a count lower than the last release's is not knowable here -
        # degrading on either would light this permanently, and an aggregate with
        # a permanently active cause has stopped being a signal, exactly as the
        # stale alembic stamp below did before it was made a fact. Which module
        # is missing is not published, for the reason in this endpoint's
        # docstring; it is in the boot log.
        #
        # Not closed by any of this: a manifest that fails to import is swallowed
        # by ``_discover_in``, so the module leaves all three counts at once and
        # nothing at runtime holds a baseline to notice against.
        if any(_row.get("enabled") and not _row.get("loaded") for _row in _module_rows):
            result["status"] = "degraded"

        # Which installation is answering, as against which process. The desktop
        # installer is per-machine and loopback on Windows is not per-session, so
        # a backend one account started answers this probe for every account
        # logged into the same machine, and version equality above cannot tell
        # those apart - it is the same install. This is what can. Read from disk
        # on every request rather than memoised, because the property the
        # launcher needs is that it survives a restart, and a value cached for
        # the life of a process would be indistinguishable from instance_id
        # under the test that checks it. Omitted, not empty, when the data
        # directory yields no identity: an absent field refuses an attach, and
        # an empty one would compare equal to another empty one.
        _workspace_id = _resolve_workspace_id()
        if _workspace_id:
            result["workspace_id"] = _workspace_id

        # Database connectivity (fast ping)
        try:
            from sqlalchemy import text

            from app.database import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["database"] = "ok"
        except Exception:
            result["database"] = "error"
            result["status"] = "degraded"

        # Alembic head match - does the DB's current revision equal the
        # latest script head on disk? A mismatch usually means somebody
        # forgot ``alembic upgrade head`` after a deploy and stale models
        # will start raising OperationalError as soon as a request hits a
        # new column. ``None`` if the check itself blew up (no alembic.ini
        # nearby, broken script tree, etc.) - visible but non-fatal.
        #
        # Three answers, and they are three: ``true`` at head, ``false``
        # behind it, ``null`` when this deployment cannot tell. See
        # :func:`alembic_head_state` for why an unstamped database is not a
        # mismatch and must never be reported as one.
        #
        # It is published as a fact and does NOT degrade the status, which is a
        # deliberate change and not an oversight. The product never runs
        # ``alembic upgrade``; the schema moves through ``create_all`` and the
        # boot heal, so the stamp falls behind on a normal, correct upgrade the
        # moment a release adds any revision at all. Degrading on that lit the
        # field permanently for every upgraded install, and an aggregate with a
        # permanently active cause has stopped being a signal: it has already
        # been observed to hide a total frontend outage, because ``status`` was
        # pinned to degraded by a stale stamp and could not change when
        # ``frontend_dist_present`` went false. The stamp being behind is a
        # fact worth publishing and is not by itself a degradation. Whether the
        # schema is behind is the question that is, and
        # ``schema_matches_models`` below answers that one directly.
        try:
            from alembic.runtime.migration import MigrationContext as _MigCtx
            from sqlalchemy import text as _text  # noqa: F401

            from app.database import engine as _engine

            _ini = _Path(__file__).resolve().parent.parent / "alembic.ini"
            if _ini.is_file():
                _expected = _expected_alembic_head(_ini)

                async with _engine.connect() as _conn:
                    _actual = await _conn.run_sync(
                        lambda sync_conn: _MigCtx.configure(sync_conn).get_current_revision()
                    )
                result["alembic_head_matches"] = alembic_head_state(_expected, _actual)
            else:
                result["alembic_head_matches"] = None
        except Exception as _exc:  # noqa: BLE001
            logger.warning("Alembic head check failed: %s", _exc)
            result["alembic_head_matches"] = None

        # Did the boot-time schema heal finish? This is the one signal an
        # external-PostgreSQL operator has that their role cannot issue DDL.
        # Without it that install runs with a schema frozen at whichever release
        # created the database, and reports itself healthy while every list
        # endpoint touching a newer column answers 500. The heal is non-fatal on
        # purpose and stays that way; what changes here is that its failure is
        # now sayable rather than only loggable.
        #
        # Three answers, for the same reason the head check above has three:
        # ``true`` failed, ``false`` healed, ``null`` never ran - which over
        # HTTP means a deployment whose database is not PostgreSQL. The key is
        # always present so a monitor can tell a backend that says "I cannot
        # tell" from one built before the field existed. Only a determinable
        # failure degrades the status; ``null`` is not a fault. The polarity is
        # the inverse of ``alembic_head_matches`` - here ``true`` is the bad
        # news - which is why this is read with ``is True`` and not as a truth
        # value. The cause is not published; see this endpoint's docstring.
        _heal_failed = getattr(app.state, "schema_heal_failed", None)
        result["schema_heal_failed"] = _heal_failed
        if _heal_failed is True:
            result["status"] = "degraded"

        # And whether it was enough. The field above says the heal did not
        # raise; this one says whether the database and the models actually
        # agree afterwards, which is a different question. The heal enforces a
        # NOT NULL only when a default exists to backfill the rows already in
        # the table, so on a populated table it completes successfully and
        # leaves the column accepting NULL, for good: no revision body ever
        # runs to tighten it. Until this key existed that install answered
        # healthy with ``schema_heal_failed: false`` while a constraint the
        # models rely on was simply absent.
        #
        # Three answers, and the polarity of ``alembic_head_matches`` rather
        # than of the two ``_failed`` fields: ``true`` they agree, ``false``
        # they do not, ``null`` never asked, which over HTTP means a deployment
        # whose database is not PostgreSQL or a check that could not run. Only
        # a determinable ``false`` degrades. Which columns diverge is not
        # published, for the same reason the heal's cause is not - see this
        # endpoint's docstring - and is on ``app.state.schema_divergent_columns``
        # and in the boot log.
        _schema_matches = getattr(app.state, "schema_matches_models", None)
        result["schema_matches_models"] = _schema_matches
        if _schema_matches is False:
            result["status"] = "degraded"

        # Did the boot-time data repairs run? The field above is about the
        # schema; this one is about the rows, and until it existed there was no
        # signal for that half at all. ``alembic_head_matches`` answers ``true``
        # on a database whose data rewrites never executed, because the stamp
        # and the rewrite are independent - which is precisely the failure this
        # reports. Read the two together: head matching says the schema is
        # current, this says whether the corrections that go with it landed.
        #
        # Three answers again, and the same polarity as ``schema_heal_failed``:
        # ``true`` at least one repair raised or a module that registers repairs
        # could not be imported, ``false`` every registered repair completed,
        # ``null`` the pass never ran (a deployment whose database is not
        # PostgreSQL). The import case belongs on this field rather than beside
        # it: both mean the same thing to whoever reads this payload - a
        # row-level correction this release ships did not land here - and a
        # module that fails to load is the version of that which used to answer
        # ``false``, because a repair that never registered cannot appear among
        # the repairs that raised. Read with ``is True`` and not as a truth
        # value. Which repairs failed, and which module did not import, is not
        # published for the same reason the heal's cause is not - see this
        # endpoint's docstring - and is on ``app.state.data_repairs_failed_ids``
        # and in the boot log.
        _repairs_failed = getattr(app.state, "data_repairs_failed", None)
        result["data_repairs_failed"] = _repairs_failed
        if _repairs_failed is True:
            result["status"] = "degraded"

        # And whether the record of that pass survived. The field above says
        # the rows were rewritten; this one says whether anything wrote down
        # that they were. They are separate because they fail separately: a
        # database whose role may write rows but not create tables repairs its
        # data correctly and keeps no ledger, and until this key existed that
        # install answered ``healthy`` with ``data_repairs_failed: false`` while
        # the answer to "did this repair run here" was being thrown away on
        # every boot. A ledger nobody can tell is missing is not a ledger.
        #
        # Three states and the same polarity as the two fields above: ``true``
        # at least one ledger write failed, ``false`` every one was written,
        # ``null`` the pass never ran. Read with ``is True``. Which repair's
        # write failed is not published, for the same reason the repair ids and
        # the heal's cause are not; it is in the boot log.
        _ledger_failed = getattr(app.state, "data_repair_ledger_failed", None)
        result["data_repair_ledger_failed"] = _ledger_failed
        if _ledger_failed is True:
            result["status"] = "degraded"

        # Frontend dist presence. The flag must describe what THIS process
        # serves, not what the disk holds right now: a process that started
        # while dist was mid-rebuild mounted nothing and 404s every UI route
        # even after the rebuild lands, and a mounted tree can lose its
        # index.html to a later rebuild while a live directory probe still
        # looks green. Fall back to the on-disk probe only in API-only mode,
        # where "present" can only mean "a servable build exists for the
        # next start".
        try:
            from app.cli_static import get_frontend_dir, mounted_frontend_intact

            _intact = mounted_frontend_intact()
            if _intact is None:
                try:
                    get_frontend_dir()
                    _intact = True
                except FileNotFoundError:
                    _intact = False
            result["frontend_dist_present"] = _intact
            if not result["frontend_dist_present"]:
                result["status"] = "degraded"
        except Exception:
            result["frontend_dist_present"] = False
            result["status"] = "degraded"

        # Process memory in MB, best-effort. Two different numbers live here and
        # they are not interchangeable. getrusage reports ru_maxrss, the PEAK
        # resident set since the process started, which never falls again: a demo
        # seed pushes it into the gigabytes and it stays there for the life of the
        # process, so on its own it reads as a gauge that can only climb. Current
        # RSS is what this field is named after, so it is preferred wherever the
        # platform will give it, and the peak is reported beside it under its own
        # name rather than in its place.
        current_mb = None
        peak_mb = None

        try:
            import resource

            rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS returns bytes, Linux returns KB
            if _os.uname().sysname == "Darwin":
                peak_mb = round(rss_bytes / (1024 * 1024), 1)
            else:
                peak_mb = round(rss_bytes / 1024, 1)
        except Exception:
            pass  # No getrusage here, so no peak to report

        try:
            # Linux carries current RSS in /proc/self/statm, second field, in pages.
            with open("/proc/self/statm") as statm:
                resident_pages = int(statm.read().split()[1])
            current_mb = round(resident_pages * _os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
        except Exception:
            try:
                # Windows, and anywhere without /proc, if psutil happens to be
                # installed. It is not a declared dependency, hence best-effort.
                import psutil

                proc = psutil.Process(_os.getpid())
                current_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass  # Memory reporting is best-effort

        # Fall back to the peak only when nothing can report the current figure,
        # so the field keeps its old value rather than disappearing.
        if current_mb is not None:
            result["memory_mb"] = current_mb
        elif peak_mb is not None:
            result["memory_mb"] = peak_mb
        if peak_mb is not None:
            result["memory_peak_mb"] = peak_mb

        # Active thread count - best-effort
        try:
            import threading as _threading

            result["threads"] = _threading.active_count()
        except Exception:
            pass

        return result

    @app.get("/api/source", tags=["System"])
    async def source_code() -> dict:
        """AGPL-3.0 Source Code Disclosure.

        As required by AGPL-3.0, this endpoint provides access to the
        complete corresponding source code of this application.
        DataDrivenConstruction · OpenConstructionERP · DDC-CWICR-OE-2026
        """
        return {
            "license": "AGPL-3.0",
            "source_code": "https://github.com/datadrivenconstruction/OpenConstructionERP",
            "copyright": "Copyright (c) 2026 Artem Boiko / DataDrivenConstruction",
            "notice": (
                "This software is licensed under AGPL-3.0. "
                "If you modify and deploy this software, you MUST make your "
                "complete source code available to all users under the same license. "
                "For commercial licensing without AGPL obligations, contact: "
                "datadrivenconstruction.io/contact-support/"
            ),
            "projects": {
                "CWICR": "https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR",
                "cad2data": "https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto",
            },
        }

    @app.get("/api/system/status", tags=["System"])
    async def system_status() -> dict[str, Any]:
        """Full system status: database, vector DB, AI providers."""
        # Public hosted demo flag - set OE_DEMO_MODE=true on the VPS
        # systemd unit so the frontend can show the "demo only" warning
        # banner and the /users page can strip personal data from the
        # demo registration list. Defaults to false on every fresh
        # local install.
        demo_mode = os.environ.get("OE_DEMO_MODE", "").lower() in ("1", "true", "yes")
        result: dict[str, Any] = {
            "api": {"status": "healthy", "version": settings.app_version},
            "database": {"status": "unknown"},
            "vector_db": {"status": "offline", "engine": "qdrant"},
            "ai": {"providers": []},
            "cache": {"status": "unknown"},
            "demo_mode": demo_mode,
        }

        # Cache check
        try:
            from app.core.cache import cache as app_cache

            result["cache"] = app_cache.stats()
        except Exception:
            result["cache"] = {"status": "unavailable"}

        # Database check
        try:
            from sqlalchemy import text

            from app.database import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["database"] = {
                "status": "connected",
                "engine": "postgresql",
            }
        except Exception:
            logger.warning("System status DB probe failed", exc_info=True)
            result["database"] = {"status": "error", "error": "unavailable"}

        # Vector DB check (LanceDB or Qdrant).
        #
        # ``vector_status()`` opens the embedded LanceDB connection / pings the
        # Qdrant server synchronously; on a cold or slow disk that probe can
        # block for several seconds. Two problems if we call it inline on the
        # request coroutine: (1) it stalls the whole event loop, and (2) the
        # dashboard polls this endpoint, so every poll repeats the cost. Fix:
        # run the probe in a worker thread (``asyncio.to_thread``) so it never
        # blocks the loop, and cache the result on ``app.state`` for ~60s so
        # rapid polls reuse it.
        import asyncio

        vector_cache_key = "_vector_status_cache"
        vector_cache_ttl_s = 60.0
        cached_vec = getattr(app.state, vector_cache_key, None)
        if cached_vec and (time.time() - cached_vec["checked_at"]) < vector_cache_ttl_s:
            result["vector_db"] = cached_vec["data"]
        else:
            try:
                from app.core.vector import vector_status as vs

                # Bound the probe so a wedged backend can never hang the
                # request beyond a few seconds - the offloaded thread keeps
                # running but the coroutine returns "offline" promptly.
                vstat = await asyncio.wait_for(asyncio.to_thread(vs), timeout=8.0)
                if vstat.get("connected"):
                    col = vstat.get("cost_collection") or {}
                    vector_result = {
                        "status": "connected",
                        "engine": vstat.get("engine", "lancedb"),
                        "vectors": col.get("vectors_count", 0),
                    }
                else:
                    vector_result = {
                        "status": "offline",
                        "engine": vstat.get("engine", "lancedb"),
                    }
            except Exception:
                vector_result = {"status": "offline", "engine": "lancedb"}
            result["vector_db"] = vector_result
            app.state._vector_status_cache = {
                "data": vector_result,
                "checked_at": time.time(),
            }

        # AI providers check - env vars first, then database
        providers = []
        if settings.openai_api_key:
            providers.append({"name": "OpenAI", "configured": True})
        if settings.anthropic_api_key:
            providers.append({"name": "Anthropic", "configured": True})

        # Fallback: check user-configured keys in oe_ai_settings table
        if not providers:
            try:
                from sqlalchemy import text as sa_text

                from app.database import async_session_factory

                async with async_session_factory() as ai_session:
                    row = (
                        await ai_session.execute(
                            sa_text(
                                "SELECT openai_api_key, anthropic_api_key, gemini_api_key FROM oe_ai_settings LIMIT 1"
                            )
                        )
                    ).first()
                    if row:
                        if row[0]:
                            providers.append({"name": "OpenAI", "configured": True})
                        if row[1]:
                            providers.append({"name": "Anthropic", "configured": True})
                        if row[2]:
                            providers.append({"name": "Gemini", "configured": True})
            except Exception:
                pass  # Table may not exist yet

        result["ai"] = {
            "providers": providers,
            "configured": len(providers) > 0,
        }

        return result

    @app.get("/api/system/data-security", tags=["System"])
    async def system_data_security(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Read-only deployment posture for the in-product Data & Security panel.

        Surfaces only verifiable, non-secret facts about where this instance keeps
        its data and whether it reaches out anywhere, so a self-hoster can see the
        privacy posture without taking a marketing claim on trust. No secret is
        ever returned - AI providers are reported by name and presence only, never
        their keys. Requires an authenticated user so deployment internals are not
        disclosed to anonymous callers.
        """
        demo_mode = os.environ.get("OE_DEMO_MODE", "").lower() in ("1", "true", "yes")
        # An operator who points the app at their own PostgreSQL sets DATABASE_URL;
        # with it blank the bundled embedded PostgreSQL boots. Either way the data
        # lives on the operator's own infrastructure - the flag only distinguishes
        # the bundled engine from an external one the operator manages.
        external_db = bool(os.environ.get("DATABASE_URL") or os.environ.get("OE_DATABASE_URL"))

        # AI providers configured at the deployment level (env) or by an operator
        # in the settings table. Reported by name and presence only, never the key.
        provider_names: list[str] = []
        if settings.openai_api_key:
            provider_names.append("OpenAI")
        if settings.anthropic_api_key:
            provider_names.append("Anthropic")
        if not provider_names:
            try:
                from sqlalchemy import text as sa_text

                from app.database import async_session_factory

                async with async_session_factory() as ai_session:
                    row = (
                        await ai_session.execute(
                            sa_text(
                                "SELECT openai_api_key, anthropic_api_key, gemini_api_key FROM oe_ai_settings LIMIT 1"
                            )
                        )
                    ).first()
                    if row:
                        if row[0]:
                            provider_names.append("OpenAI")
                        if row[1]:
                            provider_names.append("Anthropic")
                        if row[2]:
                            provider_names.append("Gemini")
            except Exception:
                pass  # Table may not exist yet - treat as no provider configured.

        # The source tree ships no usage analytics or third-party tracking; the
        # public demo host injects analytics at deploy time (demo_instance), so a
        # self-hosted install carries none. The platform is self-host only - there
        # is no vendor-run SaaS tier - and runs with no external AI at all (local
        # embeddings); AI reaches out only when an operator configures a provider.
        return build_data_security_posture(
            self_hosted=True,
            deployment_mode="desktop" if desktop_mode() else "server",
            demo_instance=demo_mode,
            version=settings.app_version,
            environment=settings.app_env,
            database_engine="postgresql",
            database_external=external_db,
            storage_backend=settings.storage_backend,
            ai_providers=provider_names,
            registration_mode=settings.registration_mode,
            analytics_bundled=False,
            license_name="AGPL-3.0",
            repository="https://github.com/datadrivenconstruction/OpenConstructionERP",
        )

    def _semver_tuple(v: str) -> tuple[int, ...]:
        """Parse a dotted version (``"5.2.10"``) into a sortable int tuple.

        Used by the version-check endpoint instead of raw string compare so
        ``5.2.10 > 5.2.9`` evaluates correctly (string compare returns the
        opposite because ``"1" < "9"``). Non-numeric trailing segments
        (``"5.3.0rc1"`` etc.) coerce to 0 so they sort below the same
        ``5.3.0`` release - pre-releases stay invisible to the
        "update available" pill until the real release lands.
        """
        out: list[int] = []
        for part in v.strip().lstrip("v").split("."):
            num = ""
            for ch in part:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(int(num) if num else 0)
        return tuple(out)

    def _same_version(a: str, b: str) -> bool:
        """Whether two version strings name the same release.

        The shorter side is zero-padded, so ``15.1`` and ``15.1.0`` compare
        equal. They have to: one of these numbers is written by a git tag and
        the other by a packaging tool, and neither owes the other its shape.
        """
        left, right = _semver_tuple(a), _semver_tuple(b)
        width = max(len(left), len(right))
        return left + (0,) * (width - len(left)) == right + (0,) * (width - len(right))

    @app.get("/api/system/version-check", tags=["System"])
    async def check_version() -> dict:
        """Return current vs latest published version.

        Source of truth is **PyPI** (more reliable than GitHub releases -
        Trusted-Publisher OIDC always produces a wheel, GitHub release
        creation is sometimes skipped on hotfixes). Falls back to GitHub
        releases if PyPI is unreachable. Both lookups are cached on
        ``app.state`` for 4 hours so the settings panel can poll cheaply
        without burning the unauthenticated GitHub rate limit.

        ``release_notes``, ``release_url``, ``published_at`` and ``assets``
        are answered only when the GitHub release they were read from names
        the same version as ``latest_version``. Two sources that can
        legitimately be a release apart must not be spliced into one sentence.

        ``assets`` lists the published installers as ``{name, url, size}`` so
        a client can offer the one that fits the machine it is running on.
        Matching is the caller's job, not this endpoint's: the desktop build
        answers this route to any browser that reaches it, so the platform
        this process runs on is not reliably the reader's.
        """
        import httpx

        current = settings.app_version
        repo = "datadrivenconstruction/OpenConstructionERP"
        cache_key = "_version_check_cache"

        cached = getattr(app.state, cache_key, None)
        if cached and (time.time() - cached["checked_at"]) < 14400:
            return cached["data"]

        latest: str | None = None
        # Held apart from what we will publish until we know the release this
        # metadata came from is the release we are going to name.
        gh_tag = ""
        gh_url = ""
        gh_notes = ""
        gh_published = ""
        gh_assets: list[dict] = []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                pypi = await client.get(
                    "https://pypi.org/pypi/openconstructionerp/json",
                )
                if pypi.status_code == 200:
                    latest = pypi.json().get("info", {}).get("version") or None
        except Exception:  # noqa: BLE001 - graceful degradation
            pass

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                gh = await client.get(
                    f"https://api.github.com/repos/{repo}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if gh.status_code == 200:
                    release = gh.json()
                    gh_tag = release.get("tag_name", "").lstrip("v")
                    gh_url = release.get("html_url", "")
                    gh_notes = (release.get("body") or "")[:500]
                    gh_published = release.get("published_at", "")
                    # The installers themselves. A reader on a desktop build
                    # cannot pip-upgrade and has to fetch one by hand, and the
                    # release page lists every platform at once, so naming the
                    # file that fits the machine in front of them is the
                    # difference between an action and a hunt. Only the three
                    # fields that decide "which file, how big, from where" are
                    # carried: the rest of a GitHub asset object is download
                    # counters and uploader identity, which no caller reads.
                    for asset in release.get("assets") or []:
                        name = asset.get("name") or ""
                        url = asset.get("browser_download_url") or ""
                        if not name or not url:
                            continue
                        gh_assets.append({"name": name, "url": url, "size": int(asset.get("size") or 0)})
                    if not latest:
                        latest = gh_tag
        except Exception:  # noqa: BLE001
            pass

        if not latest:
            latest = current

        # The number and the notes have to describe the same release. PyPI is
        # the source of truth for the number, and the reason it is - a hotfix
        # publishes a wheel without a GitHub release object being created - is
        # exactly the case where the newest release here describes an OLDER
        # version than the one we are about to name. Pairing them files 15.0.0's
        # notes under the heading "15.1.0 is available", and on a desktop build
        # it sends the reader to a page that does not carry the build they were
        # just told to install. So when they disagree we keep the number, drop
        # what we cannot stand behind, and point at the release list, which is
        # somewhere to go rather than somewhere wrong.
        # The installers are gated here for the same reason and more sharply.
        # Notes filed under the wrong heading mislead; an installer offered
        # under the wrong heading is downloaded and run, and the reader ends up
        # with the version they were just told to move off.
        if gh_tag and _same_version(gh_tag, latest):
            release_url = gh_url or f"https://github.com/{repo}/releases/latest"
            release_notes = gh_notes
            published_at = gh_published
            assets = gh_assets
        else:
            release_url = f"https://github.com/{repo}/releases"
            release_notes = ""
            published_at = ""
            assets = []

        update_available = _semver_tuple(latest) > _semver_tuple(current)
        # A frozen build has no pip to upgrade itself with, so advertising the
        # pip command there sends the user down a path that cannot work.
        frozen = is_frozen_build()
        result = {
            "current_version": current,
            "latest_version": latest,
            "update_available": update_available,
            "release_url": release_url,
            "release_notes": release_notes,
            "published_at": published_at,
            # Every installer on the release, unfiltered. Which one fits is a
            # question about the reader's machine, and this process is not
            # standing on it: the desktop build serves this API to any browser
            # that can reach the port, so a server-side match would answer for
            # the wrong computer. The client picks.
            "assets": assets,
            "self_upgrade_supported": not frozen,
            # Both spellings kept exactly as they were; only the decision moves.
            # This was the second hand-written copy of "which advice does this
            # install understand", and a copy is how the wording drifts.
            "upgrade_command": repair_hint(
                "pip install --upgrade openconstructionerp",
                "Download and run the latest installer",
            ),
        }
        setattr(app.state, cache_key, {"data": result, "checked_at": time.time()})
        return result

    @app.post(
        "/api/system/upgrade",
        tags=["System"],
        dependencies=[Depends(RequireRole("admin"))],
        response_model=None,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def trigger_upgrade(
        version: str | None = None,
        force: bool = False,
    ) -> JSONResponse:
        """Start ``pip install --upgrade openconstructionerp`` in this venv.

        Returns ``202`` with a job id as soon as the work is scheduled;
        poll ``GET /api/system/upgrade/status`` for the outcome and the
        pip log. It used to run inline and answer only when pip was
        finished, which no browser waits for: the client gave up at 45
        seconds and reported a failure over an upgrade still in progress
        (issue #430). Worse, with a single worker the whole server was
        unreachable while it ran.

        Asking again while one is running answers ``409`` with that job
        rather than starting a second pip against the same site-packages.

        We shell out to the **same** interpreter that's serving the API so
        the upgrade lands in the right venv (Issue #96 - Windows launcher
        uses ``%LOCALAPPDATA%/OpenConstructionERP/venv``, not the user's
        global Python).

        **Important - the running process keeps the OLD wheel in memory.**
        Python caches imports; pip can replace files on disk but cannot
        swap modules already loaded. The finished job carries
        ``restart_required=true`` and the new version pulled from
        ``importlib.metadata`` so the UI can prompt the user to restart
        their launcher (``openconstructionerp serve``) or, on managed
        installs, the host's systemd unit.

        **Admin only.** Requires an authenticated user with the ``admin``
        role (``RequireRole("admin")``); an unauthenticated or non-admin
        caller is rejected before any pip process starts. This closes the
        earlier gap where the route ran with no authentication at all, so a
        quickstart install reachable on the network could be forced to
        reinstall / downgrade by anyone.

        Additionally gated by ``ALLOW_RUNTIME_UPGRADE`` (defaults on).
        Managed deployments that upgrade through a deploy pipeline can set
        ``ALLOW_RUNTIME_UPGRADE=false`` to disable the route entirely;
        localhost dev and the desktop / Windows-installer builds leave it
        on so the Settings panel works out of the box.
        """
        import os
        import sys

        if os.environ.get("ALLOW_RUNTIME_UPGRADE", "true").lower() not in (
            "true",
            "1",
            "yes",
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Runtime upgrade is disabled on this install. "
                    "Run `pip install --upgrade openconstructionerp` from your "
                    "shell, then restart the service."
                ),
            )

        # A frozen build would feed the pip command below back into its own CLI
        # instead of upgrading anything (issue #403), so point at the installer,
        # which is the route that actually works there.
        if is_frozen_build():
            raise HTTPException(status_code=409, detail=FROZEN_REFUSAL)

        target = "openconstructionerp"
        if version and version.replace(".", "").replace("-", "").isalnum():
            target = f"openconstructionerp=={version}"

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", target]
        if force:
            # ``--force-reinstall`` does not stop at our own package. It
            # reinstalls the whole dependency set, and that set contains
            # pixeltable-pgserver, whose ``pginstall/bin/postgres`` binary is
            # the process serving this very request. Replacing it under a live
            # postmaster is a torn install on Windows, where the running image
            # is locked and pip fails halfway, and a mixed one everywhere else.
            #
            # The plain upgrade above is left alone: it only moves what changed,
            # and the ordinary case moves pure Python.
            from app.core import embedded_pg as _embedded_pg

            if _embedded_pg.is_running():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A forced reinstall would replace the PostgreSQL binaries this "
                        "application is currently running from. Stop the application "
                        "first and run `pip install --force-reinstall --upgrade "
                        "openconstructionerp` from your shell, or upgrade without the "
                        "force option, which does not touch them."
                    ),
                )
            cmd.insert(-1, "--force-reinstall")

        job, started = claim_upgrade(cmd, settings.app_version)
        if not started:
            # Already running. Hand back the one in flight rather than a second
            # pip against the same site-packages, and say so in the status code
            # so a client can tell "attached to yours" from "started mine".
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=job.as_dict())

        def _finished(_task: asyncio.Task[Any]) -> None:
            # The installed version has moved, so the cached answer to "is an
            # upgrade available" is about a version that is no longer running.
            if hasattr(app.state, "_version_check_cache"):
                del app.state._version_check_cache

        task = asyncio.create_task(asyncio.to_thread(run_upgrade, job))
        # Held on app.state because the event loop keeps only a weak reference
        # to a running task, and a collected one would abandon the upgrade.
        app.state._upgrade_task = task
        task.add_done_callback(_finished)

        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=job.as_dict())

    @app.get(
        "/api/system/upgrade/status",
        tags=["System"],
        dependencies=[Depends(RequireRole("admin"))],
    )
    async def upgrade_status() -> dict[str, Any]:
        """How the upgrade this process started is going, or how it went.

        Poll this after ``POST /api/system/upgrade``. ``status`` is ``running``,
        ``succeeded`` or ``failed``, and the pip log is carried along the whole
        way so a failure can be read rather than guessed at.

        Answers ``status: "idle"`` when this process has not run one. That is
        also the honest answer straight after a restart, including the restart
        the upgrade itself asked for: the record lived in the memory of the
        process that was replaced. By then ``running_version`` is the thing
        worth reading anyway.
        """
        job = current_upgrade()
        if job is None:
            return {
                "status": "idle",
                "job_id": None,
                "running_version": settings.app_version,
            }
        return job.as_dict()

    @app.get("/api/system/converters/version-check", tags=["System"])
    async def check_converter_versions(user: OptionalUserPayload = None) -> dict[str, Any]:
        """Compare each installed DDC converter against the build we would install.

        Reachable without credentials, and ``installed_path`` is emptied for a
        caller who has not signed in. That field is the absolute location of
        the exe on the server's own disk, which on a default install sits under
        the operator's home directory and so names their account. What the
        endpoint is for - is the installed build the one the Update button
        would fetch - is answered by the two SHAs and ``is_outdated``, none of
        which say where anything lives. The Settings panel still prints the
        path, and its reader is signed in.

        Computes the git-blob SHA-1 of every locally-installed converter and
        compares it to the SHA returned by GitHub's Contents API for the same
        file in `cad2data-Revit-IFC-DWG-DGN`, at the ref the installer is
        pinned to. A mismatch means the user's build differs from the one the
        Update button would fetch.

        "The build we would install" rather than "the latest upstream" is the
        whole point: this result drives an "Update available" badge whose
        button runs that installer, so comparing against anything the installer
        would not fetch produces a badge that cannot be cleared by pressing it.

        Cached on `app.state` for 6 h so the dashboard banner can poll
        cheaply without burning the unauthenticated GitHub rate limit
        (60 req/h). Network failures degrade gracefully - `network_ok=false`
        and `any_outdated=false` so the UI suppresses the banner.
        """
        import asyncio
        import hashlib
        import sys

        import httpx

        from app.modules.boq.cad_import import find_converter

        # The git-blob SHA comparison below only applies to the Windows `.exe`
        # builds fetched from the GitHub repo. On Linux/macOS the converters come
        # from the signed apt repo (or aren't natively available), so there is no
        # per-file SHA to compare - return a benign, non-alarming result so the
        # dashboard never shows a false "update available" banner off-Windows.
        if sys.platform != "win32":
            return {
                "network_ok": True,
                "any_outdated": False,
                # `converters` is the canonical key the Settings UI maps over;
                # it must be present on every platform or the panel crashes
                # with "Cannot read properties of undefined (reading 'map')".
                # `results` stays as a back-compat alias for older clients.
                "converters": [],
                "results": [],
                "platform": sys.platform,
                "note": (
                    "Converter version checks apply to the Windows builds; this "
                    "platform uses the DDC apt repository (Linux) or has no native build."
                ),
            }

        # Repo, ref and per-format directories come from
        # ``app.core.converter_source``, the same declaration the installer in
        # takeoff/router.py reads. This used to be a hand-copied duplicate, and
        # the copy said ``DDC_BRANCH = "main"`` while the installer fetched a
        # pinned commit. The moment upstream's branch tip moved ahead of the
        # pin, every installed converter's blob SHA would stop matching what
        # this endpoint fetched, the dashboard would raise its "Update
        # available" badge, and the button under it would reinstall byte-identical
        # files - a badge that never clears over a control that appears to do
        # nothing. The check has to compare against the ref the installer will
        # actually use, so it reads the same constant rather than a copy of it.
        #
        # ``app.core.converter_source`` imports only ``os``, so this keeps the
        # property the duplication was protecting: the endpoint still works when
        # the takeoff module is not loaded (it ships disabled in some
        # configurations) because nothing here depends on that module.
        from app.core.converter_source import (
            WINDOWS_CONVERTER_DIRS,
            resolve_converter_ref,
            resolve_converter_repo,
        )

        DDC_REPO = resolve_converter_repo()
        DDC_REF = resolve_converter_ref()
        # ext: (github_dir, exe_name, display_name). The directory comes from the
        # shared map; the exe and the display name are this endpoint's own.
        _EXE_AND_LABEL: dict[str, tuple[str, str]] = {
            "rvt": ("RvtExporter.exe", "RVT Parser"),
            "ifc": ("IfcExporter.exe", "IFC Import"),
            "dwg": ("DwgExporter.exe", "DWG/DXF Converter"),
            "dgn": ("DgnExporter.exe", "DGN Converter"),
        }
        WIN_DIRS: dict[str, tuple[str, str, str]] = {
            ext: (WINDOWS_CONVERTER_DIRS[ext], exe, label) for ext, (exe, label) in _EXE_AND_LABEL.items()
        }
        TTL = 6 * 3600

        def visible_to_caller(payload: dict[str, Any]) -> dict[str, Any]:
            """The answer as this caller may read it.

            Redaction is done on a copy rather than on the payload, and this is
            the reason the helper exists at all: the dict below is kept on
            ``app.state`` for six hours and handed to every later reader, so
            emptying it in place for one anonymous request would empty it for
            the operator who asks next. One canonical body is cached; each
            response is redacted on its way out.

            ``converters`` and ``results`` are the same list under two names
            (the second is a back-compat alias), so the redacted rows are built
            once and shared, keeping the two views identical the way the
            unredacted ones are.
            """
            if user is not None:
                return payload
            rows = [without_host_fields(row, {"installed_path": None}) for row in payload.get("converters", [])]
            return {**payload, "converters": rows, "results": rows}

        cached = getattr(app.state, "_converter_version_cache", None)
        if cached and (time.time() - cached.get("checked_at_ts", 0)) < TTL:
            return visible_to_caller(cached["data"])

        def git_blob_sha1(content: bytes) -> str:
            header = f"blob {len(content)}\0".encode()
            return hashlib.sha1(header + content).hexdigest()  # noqa: S324  # git uses SHA-1

        async def fetch_remote(ext: str, gh_dir: str, exe: str) -> dict[str, Any] | None:
            url = f"https://api.github.com/repos/{DDC_REPO}/contents/{gh_dir}/{exe}?ref={DDC_REF}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(url, headers={"Accept": "application/vnd.github+json"})
                    if r.status_code != 200:
                        return None
                    p = r.json()
                    return {
                        "sha": p.get("sha"),
                        "size": p.get("size"),
                        "download_url": p.get("download_url"),
                        "html_url": p.get("html_url"),
                    }
            except Exception:  # noqa: BLE001 - degrade gracefully
                return None

        remote_calls = [fetch_remote(ext, gh_dir, exe) for ext, (gh_dir, exe, _) in WIN_DIRS.items()]
        remote_results = await asyncio.gather(*remote_calls)

        results: list[dict[str, Any]] = []
        any_outdated = False
        network_ok = False
        for (ext, (gh_dir, exe, display)), remote in zip(WIN_DIRS.items(), remote_results, strict=True):
            path = find_converter(ext)
            installed = path is not None
            local_sha: str | None = None
            local_size: int | None = None
            if installed:
                try:
                    content = path.read_bytes()
                    local_sha = git_blob_sha1(content)
                    local_size = len(content)
                except OSError:
                    pass

            if remote is not None:
                network_ok = True

            is_outdated = bool(installed and remote and local_sha and remote.get("sha") and local_sha != remote["sha"])
            if is_outdated:
                any_outdated = True

            results.append(
                {
                    "id": ext,
                    "name": display,
                    "exe": exe,
                    "installed": installed,
                    "installed_path": str(path) if path else None,
                    "installed_size": local_size,
                    "installed_sha": local_sha,
                    "latest_size": remote["size"] if remote else None,
                    "latest_sha": remote["sha"] if remote else None,
                    "is_outdated": is_outdated,
                    "download_url": remote["download_url"] if remote else None,
                    "html_url": remote["html_url"] if remote else None,
                }
            )

        from datetime import datetime as _dt

        response = {
            "converters": results,
            # Back-compat alias so any client still reading `results` keeps working.
            "results": results,
            "any_outdated": any_outdated,
            "network_ok": network_ok,
            "checked_at": _dt.now(UTC).isoformat(),
            "ttl_seconds": TTL,
        }
        if network_ok:
            app.state._converter_version_cache = {"data": response, "checked_at_ts": time.time()}
        return visible_to_caller(response)

    @app.get("/api/system/modules", tags=["System"])
    async def list_modules(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        return {"modules": module_loader.list_modules()}

    @app.get("/api/marketplace", tags=["System"])
    async def get_marketplace() -> list[dict[str, Any]]:
        """Return all marketplace modules with runtime installed status."""
        from app.core.marketplace import get_marketplace_catalog
        from app.database import async_session_factory

        # Query loaded catalog regions so resource_catalog entries show as installed
        loaded_catalog_regions: set[str] = set()
        try:
            async with async_session_factory() as session:
                from app.modules.catalog.repository import CatalogResourceRepository

                repo = CatalogResourceRepository(session)
                region_stats = await repo.stats_by_region()
                loaded_catalog_regions = {r["region"] for r in region_stats if r.get("region")}
        except Exception:
            pass  # Graceful degradation: show all as uninstalled

        return get_marketplace_catalog(loaded_catalog_regions=loaded_catalog_regions)

    @app.get("/api/demo/catalog", tags=["System"])
    async def demo_catalog() -> list[dict[str, Any]]:
        """Return the list of available demo project templates."""
        from app.core.demo_projects import DEMO_CATALOG

        return DEMO_CATALOG

    @app.post("/api/demo/install/{demo_id}", tags=["System"])
    async def install_demo(
        demo_id: str,
        force: bool = False,
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Install a demo project with full BOQ, Schedule, Budget, and Tendering data.

        When the demo is already installed, returns the existing project info
        with ``already_installed=True`` unless ``force=True`` query param is set,
        in which case the old demo is deleted and recreated.
        """
        from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
        from app.database import async_session_factory

        if demo_id not in DEMO_TEMPLATES:
            from fastapi import HTTPException

            valid = ", ".join(sorted(DEMO_TEMPLATES.keys()))
            raise HTTPException(
                status_code=404,
                detail=f"Unknown demo_id '{demo_id}'. Valid options: {valid}",
            )

        async with async_session_factory() as session:
            result = await install_demo_project(session, demo_id, force_reinstall=force)
            await session.commit()

        return result

    @app.get("/api/demo/status", tags=["System"])
    async def demo_status(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, bool]:
        """Check which demo projects are currently installed."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            rows = (await session.execute(select(Project.metadata_))).scalars().all()

        installed: dict[str, bool] = {}
        for meta in rows:
            if isinstance(meta, dict) and meta.get("is_demo") and meta.get("demo_id"):
                installed[meta["demo_id"]] = True
        return installed

    @app.delete(
        "/api/demo/uninstall/{demo_id}",
        tags=["System"],
        dependencies=[Depends(RequireRole("admin"))],
    )
    async def uninstall_demo(
        demo_id: str,
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Remove a demo project and all its data."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            all_projects = (await session.execute(select(Project))).scalars().all()
            targets = [
                p for p in all_projects if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id") == demo_id
            ]

            if not targets:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not installed")

            for proj in targets:
                await session.delete(proj)
            await session.commit()

        return {"deleted_projects": len(targets), "demo_id": demo_id}

    @app.delete(
        "/api/demo/clear-all",
        tags=["System"],
        dependencies=[Depends(RequireRole("admin"))],
    )
    async def clear_all_demos(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Remove ALL demo projects and their data."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            all_projects = (await session.execute(select(Project))).scalars().all()
            targets = [p for p in all_projects if isinstance(p.metadata_, dict) and p.metadata_.get("is_demo")]

            for proj in targets:
                await session.delete(proj)
            await session.commit()

        return {"deleted_projects": len(targets)}

    @app.get("/api/system/validation-rules", tags=["System"])
    async def list_validation_rules(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        from app.core.validation.engine import rule_registry

        return {
            "rule_sets": rule_registry.list_rule_sets(),
            "rules": rule_registry.list_rules(),
        }

    @app.get("/api/system/hooks", tags=["System"])
    async def list_hooks(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        from app.core.hooks import hooks

        return {
            "filters": hooks.list_filters(),
            "actions": hooks.list_actions(),
        }

    @app.post("/api/v1/feedback", tags=["System"])
    async def submit_feedback(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        """Store user feedback (bug reports, ideas, general comments).

        Public endpoint (no auth) with per-IP rate limit and body-size cap -
        same posture as ``POST /api/v1/users/register`` so the shared
        ``oe_feedback`` table cannot be flooded by anonymous clients.
        """
        from datetime import datetime

        from sqlalchemy import text

        from app.core.rate_limiter import client_identifier, login_limiter
        from app.database import engine

        client_ip = client_identifier(request)
        allowed, _remaining = login_limiter.is_allowed(f"fb_{client_ip}")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many feedback submissions. Please wait a minute and try again.",
                headers={"Retry-After": "60"},
            )

        # Sanitise first - anonymous endpoint, must strip XSS payloads
        # before they reach the DB (BUG-330/389). Keep plain angle brackets
        # ("beam <200mm") by using the targeted sanitizer, not blanket
        # HTML-escape.
        from app.core.sanitize import strip_dangerous_html as _strip_xss

        category = _strip_xss(str(payload.get("category", "general")))[:20]
        subject = _strip_xss(str(payload.get("subject", ""))).strip()[:200]
        description = _strip_xss(str(payload.get("description", ""))).strip()[:2000]
        email = str(payload.get("email") or "")[:100] or None
        page_path = _strip_xss(str(payload.get("page_path", "")))[:200]

        # Reject empty submissions - prior behaviour wrote blank rows to the
        # feedback table, which made it useful for nothing except spamming.
        # Rate-limit (above) gates volume; this gates content (BUG-159).
        if not subject or not description:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Both 'subject' and 'description' are required.",
            )
        if len(subject) < 3 or len(description) < 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'subject' must be ≥3 chars and 'description' ≥10 chars.",
            )

        # Auto-create the table if needed. The INSERT below binds
        # ``created_at`` explicitly with an aware datetime - asyncpg's
        # TIMESTAMPTZ column rejects an ISO *string*.
        async with engine.begin() as conn:
            create_sql = """
                CREATE TABLE IF NOT EXISTS oe_feedback (
                    id BIGSERIAL PRIMARY KEY,
                    category TEXT NOT NULL DEFAULT 'general',
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL,
                    email TEXT,
                    page_path TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """
            await conn.execute(text(create_sql))
            await conn.execute(
                text("""
                    INSERT INTO oe_feedback (category, subject, description, email, page_path, created_at)
                    VALUES (:category, :subject, :description, :email, :page_path, :created_at)
                """),
                {
                    "category": category,
                    "subject": subject,
                    "description": description,
                    "email": email,
                    "page_path": page_path,
                    "created_at": datetime.now(UTC),
                },
            )

        return {"status": "received"}

    # ── Lifecycle ───────────────────────────────────────────────────────
    def _section(title: str) -> None:
        """Log a visual section header during startup.

        Makes it possible to scan a 60-line startup log and see at a glance
        where the server got stuck. Keeps output machine-readable because
        logger.info is still used.
        """
        logger.info("=== %s ===", title)

    @app.on_event("startup")
    async def startup() -> None:
        # Guard the whole startup sequence. If any fatal step (DB connect,
        # schema build, module load, demo seed) raises, surface the real cause
        # as a STAGE:server:fail marker and log the full traceback BEFORE
        # re-raising, so the desktop launcher shows the true reason instead of
        # the embedded-PostgreSQL shutdown noise that follows. uvicorn still
        # handles the re-raised error exactly as before.
        try:
            await _startup_impl()
        except Exception as exc:
            _emit_server_fail(exc)
            raise

    async def _startup_impl() -> None:
        _section("OpenConstructionERP")
        logger.info(
            "Starting %s v%s (env=%s)",
            settings.app_name,
            settings.app_version,
            settings.app_env,
        )

        # Validate secrets and configuration outside local development.
        # HS256 requires at least 32 bytes of entropy (RFC 7518 §3.2).
        # The denylist and the length rule live in app.config and are imported,
        # never restated. This block used to carry its own copy of both, and the
        # two had already drifted apart unnoticed: the local set was missing
        # three of the strings config.py rejects, and its length test counted
        # UTF-8 bytes where config.py counted characters, so the two disagreed
        # on any non-ASCII secret.
        #
        # Read the next branch knowing this: for APP_ENV != "development" it
        # CANNOT BE REACHED. app.config validates the secret in a pydantic
        # ``@model_validator(mode="after")``, which runs while ``Settings`` is
        # being constructed, so a weak secret has already raised long before
        # this function is called. The raise below is kept because it costs
        # nothing and states the rule at the place an operator looks for it,
        # but it is documentation, not the enforcement.
        #
        # Spelling that out is the point. Dead code describing a protection
        # that lives elsewhere reads exactly like the protection itself, and a
        # reader who believes this block is what stops a weak secret in
        # production will draw the wrong conclusion about what happens if they
        # change it. The live branch here is the development one below, which
        # rotates and persists a real secret.
        _jwt_too_short = jwt_secret_is_too_short(settings.jwt_secret)
        _jwt_is_default = jwt_secret_is_known_weak(settings.jwt_secret)
        # Any non-development environment must have a real secret. We treat
        # ``staging`` exactly like ``production`` here - not blocking it
        # would defeat the point of staging being a real deployment.
        if settings.app_env != "development":
            if _jwt_is_default:
                raise RuntimeError(
                    "FATAL: JWT_SECRET is set to an insecure default value outside development! "
                    "Set JWT_SECRET to a secure random string (min 32 chars). "
                    'Example: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            if _jwt_too_short:
                raise RuntimeError(
                    "FATAL: JWT_SECRET is shorter than 32 bytes (HS256 minimum). "
                    'Example: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
        elif _jwt_is_default or _jwt_too_short:
            # BUG-320: even in development, the hardcoded default secret is
            # published in the AGPL repo - any attacker with network access
            # to a dev box could forge tokens. Rotate to a strong random
            # secret so forged "open-source-secret" tokens stop working.
            #
            # The secret is **persisted** to ``~/.openestimator/.jwt-secret``
            # (chmod 600) and re-used across boots so the user's browser
            # session survives a ``Ctrl+C`` + relaunch of the CLI. Previously
            # this rotated on every boot, which silently invalidated every
            # active token and dumped PWA users back to the OS desktop on
            # the next request (auth → 401 → window.location to /login,
            # which for a standalone-installed PWA looks like a "crash").
            import secrets as _secrets
            from pathlib import Path as _Path

            # The CLI's default data dir is ``~/.openestimate`` (no "r")
            # per cli.py:51. The historical brand namespace ``.openestimator``
            # is honoured only as a read fallback for legacy installs.
            primary_dir = _Path.home() / ".openestimate"
            legacy_dir = _Path.home() / ".openestimator"
            secret_path = primary_dir / ".jwt-secret"
            legacy_secret_path = legacy_dir / ".jwt-secret"
            persisted: str | None = None
            for path in (secret_path, legacy_secret_path):
                try:
                    if path.is_file():
                        candidate = path.read_text(encoding="utf-8").strip()
                        if len(candidate.encode("utf-8")) >= 32:
                            persisted = candidate
                            break
                except OSError:
                    continue

            if persisted is None:
                persisted = _secrets.token_urlsafe(48)
                try:
                    secret_path.parent.mkdir(parents=True, exist_ok=True)
                    secret_path.write_text(persisted, encoding="utf-8")
                    # Best-effort chmod 600 (POSIX). On Windows the file
                    # inherits user-only ACLs from the home directory.
                    try:
                        secret_path.chmod(0o600)
                    except OSError:
                        pass
                    logger.info(
                        "JWT_SECRET was default/short - generated a fresh dev secret "
                        "and persisted it to %s. Sessions now survive restarts. "
                        "Set JWT_SECRET env var for a stable team-wide secret.",
                        secret_path,
                    )
                except OSError as _persist_err:
                    logger.warning(
                        "JWT_SECRET persistence to %s failed (%s) - falling back "
                        "to a per-process random secret. Sessions WILL be invalidated "
                        "on every restart. Set JWT_SECRET env var (>=32 bytes) "
                        "to keep sessions alive.",
                        secret_path,
                        _persist_err,
                    )
            else:
                logger.info(
                    "JWT_SECRET was default/short - loaded persisted dev secret from %s. "
                    "Existing sessions remain valid. Set JWT_SECRET env var for a "
                    "stable team-wide secret.",
                    secret_path,
                )

            try:
                # pydantic-settings blocks direct assignment when frozen,
                # but the default Settings class is mutable. If the field
                # is frozen in a future refactor, falling back to
                # ``object.__setattr__`` keeps us safe.
                settings.jwt_secret = persisted
            except Exception:
                object.__setattr__(settings, "jwt_secret", persisted)

        if settings.is_production:
            if "minioadmin" in (settings.s3_access_key + settings.s3_secret_key):
                logger.warning("S3 credentials are using development defaults")
            if "localhost" in settings.database_url:
                logger.warning("DATABASE_URL points to localhost in production")

        # Deliberately outside the ``is_production`` block above, and not a
        # missing ``if``: this covers staging too, matching the JWT guard in
        # ``app.config``. A staging box that cannot send mail is precisely the
        # one nobody notices, because nobody is waiting on its password
        # resets. The function is silent in development and silent when an
        # operator chose the transport on purpose.
        from app.core.email import report_email_config_at_startup

        report_email_config_at_startup(settings)

        # Load translations (28 languages)
        _section("i18n")
        from app.core.i18n import load_translations

        load_translations()

        # Register core permissions
        from app.core.permissions import register_core_permissions

        register_core_permissions()

        # Auto-create tables on PostgreSQL on first start.
        # Why: the v0.9.0 baseline Alembic migration is a no-op (it documents
        # that tables are created via SQLAlchemy create_all), and the
        # docker-compose.quickstart.yml entrypoint does not run
        # `alembic upgrade head` before uvicorn. Result on a fresh PG
        # volume: schema never created, login fails with
        # `relation "oe_users_user" does not exist` (issue #42).
        # SQLAlchemy create_all is idempotent on PG and harmless on existing
        # databases - it only creates tables that do not yet exist.
        _section("Database")
        if "postgresql" in settings.database_url:
            import importlib
            import pkgutil

            from app import modules as _modules_pkg
            from app.core import audit as _audit_core  # noqa: F401
            from app.core.postgres_version import validate_postgres_version
            from app.database import Base, engine

            # Validate PostgreSQL version before any schema operations. The
            # call logs the version it read, so nothing is bound here; what
            # this site wants from it is the refusal, which the re-raise
            # carries out of `_startup_impl` and stops the server coming up.
            try:
                await validate_postgres_version(engine)
            except Exception as exc:
                logger.error("PostgreSQL version validation failed: %s", exc)
                raise

            # ``audit_log`` defines the ``oe_activity_log`` table used by the
            # FSM ``log_activity()`` helper (submittals/RFI/etc. status
            # transitions). It lives in app.core (not app.modules.*) so the
            # dynamic module-models loop below never reaches it. Without this
            # explicit import the table is absent on a fresh database, so every
            # status-changing action raised an error, which poisoned the request
            # session and cascaded into a 500 on the subsequent re-fetch.
            # Register it before create_all.
            from app.core import audit_log as _audit_log_core  # noqa: F401

            # Same reason again, one table further on: ``oe_data_repair_ledger``
            # is declared in app.core, so the dynamic app.modules.* loop below
            # never reaches it and create_all would not build it. Without the
            # table the repairs still run correctly and the record of them is
            # lost on every install, which is the one failure this module was
            # written to stop having.
            from app.core import data_repairs as _data_repairs_core  # noqa: F401

            # Register EVERY module's SQLAlchemy models before create_all so
            # a fresh PostgreSQL database gets all tables. This was
            # previously a hand-maintained import list that silently omitted
            # ~18 modules (service, resources, equipment, portal,
            # daily_diary, schedule_advanced, crm, contracts, variations,
            # bid_management, qms, hse_advanced, carbon, bi_dashboards,
            # subcontractors, supplier_catalogs, property_dev,
            # compliance_docs). Their tables were never created on a clean
            # install, so every list endpoint 500'd with "no such table".
            # Discovering models dynamically makes that whole class of bug
            # impossible: any module package with a models.py is registered
            # automatically - adding a new module needs no edit here.
            for _m in pkgutil.iter_modules(_modules_pkg.__path__):
                if not _m.ispkg:
                    continue
                _models_mod = f"app.modules.{_m.name}.models"
                try:
                    importlib.import_module(_models_mod)
                except ModuleNotFoundError as exc:
                    # No models.py in this module - fine, skip it. Re-raise
                    # if the failure is a *different* missing import inside
                    # the models module (that is a real bug, not absence).
                    if exc.name != _models_mod:
                        raise

            # Add missing columns to existing tables before create_all runs.
            # create_all only ever creates whole new *tables*; it never adds a
            # *column* to a table that already exists. So after an app upgrade
            # that added a column to an existing model (for example
            # oe_boq_position.cost_line_id from the v6.4.0 cost spine), that
            # column is absent on a database first created under the older
            # version, and every ORM read of the table fails with a missing-
            # column error.
            #
            # Embedded PostgreSQL is the default no-Docker runtime and is not
            # managed by Alembic, so it needs an auto-heal via
            # ADD COLUMN IF NOT EXISTS. External PostgreSQL (a user-supplied
            # DATABASE_URL, where embedded_pg is not running) keeps managing
            # columns with Alembic and is left alone.
            # Heal column/index drift on BOTH embedded and external PostgreSQL.
            # create_all (below) only ever creates whole missing *tables*; it
            # never adds a *column* to a table that already exists. So an
            # external database first created under an older release is missing
            # every column added since (for example oe_ai_agents_run.trust from
            # v3204), and every ORM read of that table 500s with a DBAPI
            # UndefinedColumn error (e.g. GET /ai-agents/insights). The migrator
            # only issues ADD COLUMN / CREATE INDEX IF NOT EXISTS, which is
            # idempotent and non-destructive, so it is safe to run regardless of
            # who manages the schema. Wrapped non-fatally: an external DB role
            # without DDL rights (or any other failure) just logs a warning and
            # leaves schema management to the operator's `alembic upgrade head`,
            # exactly as before.
            # Collapse any duplicate from-source takeoff documents before the
            # index heal below adds their unique index (issue #369). A leftover
            # duplicate makes CREATE UNIQUE INDEX fail, so the merge must run
            # first. Idempotent and cheap when clean; non-fatal like the heal.
            try:
                from app.modules.takeoff.dedup import collapse_duplicate_source_documents

                async with engine.begin() as conn:
                    await collapse_duplicate_source_documents(conn)
            except Exception:
                logger.warning("Takeoff duplicate-document heal skipped (non-fatal)", exc_info=True)

            # Ask, BEFORE any DDL, whether this database arrived holding
            # application tables while recording no migration revision. After
            # create_all below, every database has oe_* tables and the question
            # is unanswerable, so the answer has to be taken here and carried
            # down to the stamp. Defaults to False, so any failure to tell
            # leaves the previous behaviour exactly as it was.
            _arrived_populated_unstamped = False
            try:
                from app.core.alembic_version_table import database_is_populated_but_unstamped

                async with engine.connect() as conn:
                    _arrived_populated_unstamped = await conn.run_sync(database_is_populated_but_unstamped)
                if _arrived_populated_unstamped:
                    logger.warning(
                        "This database holds application tables but records no migration revision, so it "
                        "is not known to be at head. The boot-time stamp will be refused to keep that "
                        "recoverable."
                    )
            except Exception:
                logger.warning("Could not tell whether the database arrived unstamped (non-fatal)", exc_info=True)

            from app.core.postgres_migrator import postgres_auto_migrate

            # Nothing in this codebase ever runs ``alembic upgrade``, here or
            # anywhere else, and that is a decision rather than an oversight.
            # The schema is moved by the heal below (ADD COLUMN / CREATE INDEX
            # IF NOT EXISTS) plus create_all (whole missing tables), which
            # covers additive revisions and covers nothing else: a NOT NULL, a
            # rename, a type change and a backfill all pass straight through it.
            #
            # Running the real upgrade at startup would not fix that, because of
            # what stamp_head_if_unstamped does further down. Every install this
            # boot path has ever built is recorded at head the moment create_all
            # finishes, without the revisions in between having executed - and
            # several of them say in their own docstrings that they MUST be run
            # rather than merely stamped (v3237, v3245, v3246, v3247). So
            # ``alembic upgrade head`` on those databases is a no-op that
            # replays nothing, which is exactly the population that needs it,
            # while on the databases it would touch it is an unattended schema
            # rewrite during startup with no operator watching. It is enabled by
            # neither default. What is fixed instead is the visibility: the
            # failure below is now recorded where a human reads it.
            #
            # Both exits of this try/except record a verdict, and only these two
            # do. A run that never gets here because its database is not
            # PostgreSQL keeps the ``None`` this application was built with,
            # which is what lets /api/health say "never ran" instead of "healed
            # fine".
            try:
                migrated = await postgres_auto_migrate(engine, Base)
                if migrated:
                    logger.info("PostgreSQL auto-migration: %d schema objects (columns + indexes) added", migrated)
                app.state.schema_heal_failed = False
                app.state.schema_heal_error = None
            except Exception as exc:
                _heal_error = f"{type(exc).__name__}: {exc}"
                app.state.schema_heal_failed = True
                app.state.schema_heal_error = _heal_error
                # Deliberately louder than the warning this replaces, and it
                # names the cause inline rather than leaving it in a traceback.
                # An external database whose role cannot issue DDL fails here
                # every single boot and nowhere else, and the operator meets the
                # consequence as an undefined-column 500 in an unrelated module.
                logger.error(
                    "PostgreSQL schema heal FAILED (%s). The database is missing columns this "
                    "release expects and requests touching them will fail. If this role cannot "
                    "issue DDL, run the schema change as one that can; the application will keep "
                    "starting either way. /api/health reports schema_heal_failed=true, and this "
                    "line is where the cause is: that endpoint is unauthenticated and the message "
                    "carries the failing statement, so it is not published there.",
                    _heal_error,
                    exc_info=True,
                )

            # Now ask whether it worked, which the flag above does not answer.
            # A heal that raised nothing still leaves the models and the
            # database disagreeing wherever it had to drop a NOT NULL to get a
            # column in at all. Asked as a standing question about the schema
            # rather than read off this boot's log, because the heal announces
            # that decision on the boot it makes it and is silent on every boot
            # afterwards - so an install that took the divergence on an earlier
            # release would otherwise report nothing about it forever. One
            # catalog query: 0.19s against 626 tables, 2% of the heal it
            # follows, measured on the embedded server.
            try:
                from app.core.postgres_migrator import not_null_divergences

                _divergent = await not_null_divergences(engine, Base)
                app.state.schema_divergent_columns = _divergent
                app.state.schema_matches_models = not _divergent
                if _divergent:
                    # Every name, not the first few. This line used to print
                    # ``_divergent[:5]``, which made a nine-column divergence
                    # read as five everywhere an operator could see it, and
                    # made an independent probe that had also stopped at five
                    # look like corroboration rather than the same truncation
                    # arrived at twice. Two readings that agree because one was
                    # cut to the length of the other is the most convincing
                    # wrong answer available. A count that disagrees with the
                    # list printed beside it is the one thing this must not do.
                    logger.warning(
                        "Schema divergence: %d column(s) the models declare NOT NULL accept NULL in this "
                        "database: %s. Nothing on the boot path will tighten them; each needs a backfill "
                        "and an ALTER. /api/health reports schema_matches_models=false, and the names are "
                        "here rather than there because that endpoint is unauthenticated.",
                        len(_divergent),
                        ", ".join(_divergent),
                    )
            except Exception as exc:  # noqa: BLE001
                # A diagnostic must never be able to stop a boot. Leaving the
                # field None says "could not tell", which is honest and does
                # not degrade; claiming agreement here would be the one answer
                # that is worse than no answer.
                logger.warning("Schema divergence check could not run: %s", exc)

            # The heal above adds oe_progress_entry.seq to a pre-v3258 table as
            # ADD COLUMN ... DEFAULT nextval(...), and PostgreSQL numbers the
            # existing rows while rewriting the table, so they come out in heap
            # order - while the Alembic migration numbers them by recorded_at.
            # "Latest wins" in the progress module leads with seq, so the same
            # rows answered differently depending on which path built the
            # schema. Put them back in observation order. Runs AFTER the heal
            # (takeoff's merge above runs before it) because the column it
            # repairs is one the heal itself creates - going first would leave
            # a boot-long window of wrong readings. Idempotent: a single scan
            # that finds nothing out of order and stops, on every later boot.
            try:
                from app.modules.progress.seq_repair import repair_progress_entry_seq

                async with engine.begin() as conn:
                    await repair_progress_entry_seq(conn)
            except Exception:
                logger.warning("Progress seq order repair skipped (non-fatal)", exc_info=True)

            # Same shape, different column. classified_at was declared naive
            # while the service stamped it aware, so every database built before
            # this version carries a column asyncpg will not write to. The heal
            # cannot fix it: it adds columns and never retypes them. Idempotent,
            # and a no-op the moment the reflected type comes back aware.
            try:
                from app.modules.project_route.tz_repair import widen_classified_at

                async with engine.begin() as conn:
                    await widen_classified_at(conn)
            except Exception:
                logger.warning("classified_at widening skipped (non-fatal)", exc_info=True)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("PostgreSQL tables created/verified")

            # Stamp the alembic version table to head on a fresh managed DB.
            # create_all above materialises the full current schema, so the
            # database is by definition at head; recording that lets the
            # health check report a clean state instead of "degraded" on
            # every fresh install, and makes a later ``alembic upgrade head``
            # a correct no-op rather than an attempt to replay the whole
            # chain against already-present tables. This is the runtime
            # counterpart of alembic/env.py's fresh-blank-DB shortcut (which
            # only fires when ops run migrations before the app ever boots).
            # Only stamps when the version table is empty/absent so it never
            # clobbers an existing migration state. Non-fatal.
            #
            # This is also where alembic's version table gets CREATED on the
            # canonical install, so it is where its column width is settled -
            # see app/core/alembic_version_table.py and issue #399.
            from app.core.alembic_version_table import stamp_head_if_unstamped

            try:
                async with engine.begin() as conn:
                    stamped = await conn.run_sync(
                        lambda c: stamp_head_if_unstamped(c, refuse_when_populated=_arrived_populated_unstamped)
                    )
                if stamped:
                    logger.info("Alembic version stamped to head %s on fresh DB", stamped)
            except Exception as exc:
                # Was logger.debug, which is off in every default configuration.
                # A stamp that cannot be written is the difference between
                # /api/health answering "at head" and answering "cannot tell"
                # for the life of the install, and on an external database it
                # has the same root cause as the heal failure above: no DDL
                # rights. An absent alembic.ini does not reach here at all -
                # stamp_head_if_unstamped returns None for that - so anything
                # that does is worth a line.
                logger.warning("Alembic head stamp skipped (non-fatal): %s", exc, exc_info=True)

            # ── Data repairs ─────────────────────────────────────────────
            # The stamp above has just recorded this database at head, and for
            # every ADDITIVE revision that is true: the heal and create_all
            # between them built the schema. It is not true of a revision whose
            # upgrade() rewrites ROWS. Those bodies never execute here, and the
            # stamp is what guarantees nothing downstream will ever look again.
            #
            # So the rewrites that have to reach an ordinary install are written
            # as boot-path code and registered in app.core.data_repairs, and
            # this is where they run. Deliberately NOT a replay of migration
            # bodies: the desktop bundle ships no migration tree, and a rewrite
            # over customer data needs judgement a generic replayer has nowhere
            # to put. See that module's docstring, and the gate at
            # scripts/check_data_rewrite_boot_repair.py that stops the next such
            # revision shipping without its boot-path half.
            #
            # Runs after create_all so the ledger table exists, and before the
            # module loader, so a repair also reachable from a module's
            # on_startup hook (formwork's is) has already been done by the time
            # that hook looks.
            #
            # Every repair is idempotent by contract, so this runs on every boot
            # and the ledger is never consulted to skip one. A ledger allowed to
            # answer "already done" is what alembic_version is, and that is the
            # defect this whole block exists because of.
            try:
                from app.core.data_repairs import run_data_repairs
                from app.database import async_session_factory

                _repair_report = await run_data_repairs(
                    async_session_factory,
                    app_version=settings.app_version,
                )
                publish_data_repair_verdict(app, _repair_report)
                if not _repair_report.ledger_written:
                    logger.error(
                        "Data repair ledger write FAILED on this boot. The repairs themselves are "
                        "reported separately above and may well have landed; what is missing is the "
                        "record of them, so nothing can answer what this install has run. "
                        "/api/health reports data_repair_ledger_failed=true."
                    )
                if _repair_report.discovery_failures:
                    logger.error(
                        "Data repair modules did not import: %s. Whatever they register was never in "
                        "the registry, so those repairs were not attempted on this boot and will not "
                        "appear among the failures below - a repair that never loaded cannot be a "
                        "repair that raised. This is a broken build rather than a database problem. "
                        "/api/health reports data_repairs_failed=true.",
                        ", ".join(f"{f.module} ({f.error})" for f in _repair_report.discovery_failures),
                    )
                if _repair_report.failed:
                    logger.error(
                        "Data repairs FAILED: %s. These rewrite rows the schema heal cannot reach, so "
                        "data this release expects to have been corrected is still wrong on this "
                        "database. Causes are logged above; /api/health reports "
                        "data_repairs_failed=true. Retried on the next start.",
                        ", ".join(_repair_report.failed),
                    )
                elif _repair_report.rows_changed:
                    logger.info(
                        "Data repairs: %d row(s) rewritten across %d repair(s)",
                        _repair_report.rows_changed,
                        _repair_report.attempted,
                    )
            except Exception as exc:
                # The pass itself could not run at all, which is different from a
                # repair failing inside it and is reported as the same verdict:
                # rows that should have been rewritten were not.
                publish_data_repair_verdict(app, None)
                logger.error(
                    "Data repair pass could not run (%s: %s). No registered data repair executed on "
                    "this boot, so any row-level correction this release ships is absent from this "
                    "database, and no ledger row was written either. /api/health reports "
                    "data_repairs_failed=true and data_repair_ledger_failed=true.",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

            # Provision multi-tenant row-level security (opt-in). Runs after
            # create_all so every tenant table exists on both fresh and upgraded
            # databases; a no-op that never touches the database while
            # settings.rls_enforce is off, so it is inert on a default install.
            try:
                from app.core.rls_setup import provision_rls, verify_rls_role

                rls_stats = await provision_rls(engine, Base)
                if rls_stats.get("tables"):
                    logger.info("RLS enforcement active: %d tenant tables policied", rls_stats["tables"])
                # With the flag on, every request downgrades to oe_app; if that
                # role is absent (external PG without CREATEROLE) requests 500.
                # Surface it once at boot instead of on every request. No-op off.
                await verify_rls_role(engine)
            except Exception:
                logger.warning("RLS provisioning skipped (non-fatal)", exc_info=True)
        else:
            logger.info("Using external database (Alembic manages schema)")

        # Load all modules (triggers module on_startup hooks)
        _section("Modules")
        # Modules installed at runtime live in the instance's data directory,
        # not in the source tree, so the import system has to be told about
        # that directory before anything discovers or imports a module. A
        # failure here is not fatal: the platform runs on its shipped modules.
        try:
            from app.core.module_runtime_root import attach_runtime_root

            attach_runtime_root()
        except Exception:
            logger.warning("Runtime module root not attached", exc_info=True)
        await module_loader.load_all(app)

        # Mount OpenCDE API at the spec-compliant prefix /api/v1/opencde
        # (module loader auto-mounts at /api/v1/opencde_api)
        try:
            from app.modules.opencde_api.router import router as opencde_router

            app.include_router(opencde_router, prefix="/api/v1/opencde", tags=["OpenCDE API"])
        except Exception:
            logger.debug("OpenCDE API router not available (non-fatal)")

        # Variations alias (plan §3.3) - mount changeorders also at /api/v1/variations
        try:
            from app.modules.changeorders.router import router as co_router

            app.include_router(co_router, prefix="/api/v1/variations", tags=["Variations"])
        except Exception:
            logger.debug("Variations alias not available (non-fatal)")

        # costmodel → finance/evm alias (plan §3.3)
        try:
            from app.modules.costmodel.router import router as cm_router

            app.include_router(cm_router, prefix="/api/v1/finance/evm", tags=["Finance EVM (alias)"])
        except Exception:
            logger.debug("Finance EVM alias not available (non-fatal)")

        # tendering → procurement/tenders alias (plan §3.3)
        try:
            from app.modules.tendering.router import router as tend_router

            app.include_router(
                tend_router,
                prefix="/api/v1/procurement/tenders",
                tags=["Procurement Tenders (alias)"],
            )
        except Exception:
            logger.debug("Procurement Tenders alias not available (non-fatal)")

        # Coordination Hub - module directory is ``coordination_hub`` (the
        # full name keeps the package self-describing) but the canonical
        # public URL is ``/api/v1/coordination/...`` so the surface matches
        # the industry term ("Model Coordination") rather than our internal
        # directory layout. Mount the alias here in addition to the
        # auto-mount the loader does at ``/api/v1/coordination-hub``.
        try:
            from app.modules.coordination_hub.router import (
                router as coord_router,
            )

            app.include_router(
                coord_router,
                prefix="/api/v1/coordination",
                tags=["Coordination Hub"],
            )
        except Exception:
            logger.debug("Coordination Hub alias not available (non-fatal)")

        # 4D module (Section 6) - mount schedules + EAC schedule links at /api/v2
        try:
            from app.modules.schedule.router_4d import (
                eac_schedule_links_router,
                schedules_v2_router,
            )

            app.include_router(schedules_v2_router, prefix="/api/v2")
            app.include_router(eac_schedule_links_router, prefix="/api/v2")
        except Exception:
            logger.debug("4D /api/v2 routers not available (non-fatal)")

        # Register cross-module event handlers (dataflow wiring)
        from app.core.event_handlers import register_event_handlers

        register_event_handlers()

        # Register built-in validation rules
        _section("Validation")
        from app.core.validation.rules import register_builtin_rules

        register_builtin_rules()

        # Seed demo account + 3 demo projects (idempotent)
        _section("Demo data")
        await _seed_demo_account()

        # Seed ISO 3166-1 countries + tax configs + work calendars if empty.
        # Required for the region-picker, tax-config lookups and work-calendar
        # endpoints to return data on a fresh install.
        try:
            from app.database import async_session_factory as _i18n_session_factory
            from app.modules.i18n_foundation.seed import seed_i18n_data

            async with _i18n_session_factory() as _seed_session:
                await seed_i18n_data(_seed_session)
                await _seed_session.commit()
        except Exception:
            logger.exception("i18n seed failed - countries/taxes/calendars may be empty")

        # Starter seed: small baseline of cost items + assemblies so a fresh
        # install never shows an empty /costs or /catalog before the user
        # imports a regional CWICR catalogue. Idempotent - only runs when
        # the tables are empty. Disable via OE_SKIP_STARTER_SEED=1.
        try:
            from app.database import async_session_factory as _starter_session_factory
            from app.scripts.seed_starter import seed_starter_data

            async with _starter_session_factory() as _starter_session:
                counts = await seed_starter_data(_starter_session)
                await _starter_session.commit()
                if counts["cost_items"] or counts["assemblies"]:
                    logger.info(
                        "Starter seed: %d cost items, %d assemblies inserted",
                        counts["cost_items"],
                        counts["assemblies"],
                    )
                # The Cost Explorer module's own startup index build ran during
                # module load, before this seed, so on a first boot it saw an
                # empty cost table. Build the resource->work reverse index now
                # that the starter cost items (with their resource recipes) are
                # in place, otherwise the By-resources and Substitute tabs would
                # stay empty until the next restart. Self-contained, idempotent
                # and size-capped; it swallows its own errors.
                if counts["cost_items"]:
                    from app.modules.cost_explorer.service import build_index_if_empty

                    await build_index_if_empty()
        except Exception:
            logger.exception("Starter seed failed - /costs and /catalog may be empty")

        # Regional indices seed (v3.12.0 - Stream B). Idempotent: the
        # script honours the UNIQUE(region, category, subcategory,
        # effective_date) constraint on ``oe_regional_indices``, so it
        # only inserts the OE_v3.12 baseline rows once. Failure is
        # non-fatal - the regional-adjust endpoint falls back to a 1:1
        # passthrough when no rows are on file.
        try:
            from app.scripts.seed_regional_indices import main as _seed_regional_main

            inserted = await _seed_regional_main()
            if inserted:
                logger.info(
                    "Regional indices seed: %d factor rows inserted",
                    inserted,
                )
        except Exception:
            logger.exception(
                "Regional indices seed failed - /v1/costs/regional-adjust will "
                "passthrough until an operator imports a feed"
            )

        # Property-dev house-type catalogue presets. Mirrors migration
        # v3114_propdev_house_type_catalogue's bulk_insert so fresh-blank-DB
        # installs (which take the env.py create_all+stamp shortcut and
        # never run the migration's upgrade()) still end up with the ~60
        # country presets populated. Idempotent - skips when any preset
        # row exists.
        try:
            from app.database import async_session_factory as _ht_session_factory
            from app.modules.property_dev.seed_house_type_catalogue import (
                seed_house_type_catalogue_presets,
            )

            async with _ht_session_factory() as _ht_session:
                inserted = await seed_house_type_catalogue_presets(_ht_session)
                await _ht_session.commit()
                if inserted:
                    logger.info(
                        "Property-dev house-type catalogue seed: %d preset rows",
                        inserted,
                    )
        except Exception:
            logger.exception(
                "Property-dev house-type catalogue preset seed failed - "
                "/property-dev/house-type-catalogue will return an empty list "
                "until an operator re-runs alembic or restarts the app"
            )

        # Initialize vector database (LanceDB embedded, no Docker).
        #
        # Skipped under OE_TEST_FAST_STARTUP: connecting to the vector backend
        # and loading the embedding model adds ~45s to startup, and the test
        # suite stands up a fresh app per test module. Vector endpoints still
        # work in tests because get_embedder() loads the model lazily on the
        # first call that actually needs it.
        _section("Vector DB")
        _fast_startup = os.environ.get("OE_TEST_FAST_STARTUP", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if _fast_startup:
            logger.info("Vector DB init + embedding warm-up skipped (OE_TEST_FAST_STARTUP)")
        else:
            # Run vector-DB init off the critical boot path. It opens every
            # collection (LanceDB count_rows per table, or a Qdrant round-trip),
            # which delayed the server reporting ready on a fresh install.
            # Nothing downstream awaits its result, and it is non-fatal, so
            # detach it the same way as the embedder prime below.
            async def _init_vector_db_background() -> None:
                import asyncio as _asyncio_vdb

                try:
                    await _asyncio_vdb.to_thread(_init_vector_db)
                except Exception:  # noqa: BLE001 - never fatal for startup
                    logger.debug("Vector DB background init skipped", exc_info=True)

            try:
                import asyncio as _asyncio_vdb_sched

                _asyncio_vdb_sched.create_task(_init_vector_db_background())
            except Exception:
                logger.debug("Could not schedule vector DB init", exc_info=True)

            # Pre-warm the embedder + boot the inference process pool. Both
            # are env-var-gated so dev startup stays fast unless the
            # operator opted in. See ``app.core.embedding_pool`` for the
            # full rationale and trade-offs.
            #
            # Prime the embedder in a DETACHED background task. Loading the
            # SentenceTransformer blocks for up to ~45s, and doing it inline
            # here meant the server could not answer a single request until
            # the model finished loading. ``get_embedder()`` is lazy + cached
            # (see app/core/vector.py), so any caller that needs embeddings
            # before the prime completes simply loads the model on demand and
            # semantic search lights up the moment the model is ready. The
            # load itself is CPU/IO-blocking, so the task hands it to a
            # worker thread via ``asyncio.to_thread`` - same detached pattern
            # as ``_auto_backfill_vector_collections`` below.
            # Fetch the encoder weights, if this deployment wants them. Runs on
            # its own daemon thread, is a no-op on a server deploy, and cannot
            # raise here - see app/core/embedding_installer.py. Started before
            # the prime below so a desktop first boot has the download already
            # moving while the prime decides there is nothing to load yet.
            try:
                from app.core.embedding_installer import start_background_download

                if start_background_download():
                    logger.info("Encoder weights are downloading in the background - startup does not wait for them")
            except Exception:  # noqa: BLE001 - an optional extra can never break startup
                logger.debug("Could not start the encoder download", exc_info=True)

            async def _prime_embedder_background() -> None:
                import asyncio as _asyncio_emb

                try:
                    # Priming a model that is not on disk is itself a download,
                    # and on a server deploy that is the download the platform
                    # was told not to do. So the prime runs when the weights are
                    # already installed (warm start, unchanged behaviour) or
                    # when this deployment asked for them; otherwise it stands
                    # down and the first caller that genuinely needs a vector
                    # loads the model lazily, exactly as it does today.
                    from app.core.embedding_installer import download_enabled, find_installed_model
                    from app.core.vector import get_embedder as _ge

                    if find_installed_model() is None and not download_enabled():
                        logger.info(
                            "Embedder prime skipped: no encoder installed and the background "
                            "download is off for this deployment (set OE_DOWNLOAD_EMBEDDING_MODEL=1 "
                            "to fetch it). Semantic search reports its state honestly meanwhile."
                        )
                        return

                    embedder = await _asyncio_emb.to_thread(_ge)
                    if embedder is not None:
                        logger.info("Embedder background prime complete - semantic search ready")
                except Exception as exc:  # noqa: BLE001 - never fatal for startup
                    logger.info("Embedder background prime skipped: %s", exc)

            try:
                import asyncio as _asyncio_emb_sched

                _asyncio_emb_sched.create_task(_prime_embedder_background())
            except Exception:
                logger.debug("Could not schedule embedder prime", exc_info=True)

            try:
                from app.core.embedding_pool import init_pool, maybe_preload_in_process

                preloaded = maybe_preload_in_process()
                workers = init_pool()
                if preloaded or workers:
                    logger.info(
                        "Embedding warm-up: preload=%s pool_workers=%d",
                        preloaded,
                        workers,
                    )
            except Exception as exc:  # noqa: BLE001 - never fatal for startup
                logger.warning("Embedding pool init skipped: %s", exc)

            # Auto-backfill the multi-collection vector store from existing
            # rows.  Detached as a background task so a slow embedding model
            # download or a large dataset doesn't delay startup - semantic
            # search remains available the moment the model finishes loading.
            try:
                import asyncio as _asyncio_bf

                _asyncio_bf.create_task(_auto_backfill_vector_collections())
            except Exception:
                logger.debug("Could not schedule vector backfill", exc_info=True)

        # ── KPI auto-recalculation scheduler (24-hour interval) ──────────
        import asyncio

        async def _kpi_scheduler() -> None:
            """Run KPI recalculation for all active projects every 24 hours."""
            while True:
                await asyncio.sleep(86400)  # 24 hours
                try:
                    from app.database import async_session_factory as _kpi_sf
                    from app.modules.reporting.service import ReportingService

                    async with _kpi_sf() as kpi_session:
                        svc = ReportingService(kpi_session)
                        result = await svc.auto_recalculate_kpis()
                        await kpi_session.commit()
                        logger.info(
                            "KPI scheduler: %d projects processed, %d failed",
                            result["processed"],
                            result["failed"],
                        )
                except Exception:
                    logger.exception("KPI recalculation scheduler failed")

        # Background schedulers are skipped under OE_TEST_FAST_STARTUP: the test
        # suite stands up a fresh app (and thus a fresh set of these loops) per
        # module on a single shared event loop. Left running, each module's
        # detached loops accumulate and periodically open their own DB sessions,
        # eventually exhausting the PostgreSQL connection cap (TooManyConnections)
        # for later modules. Production (flag unset) starts them as before.
        if not _fast_startup:
            asyncio.create_task(_kpi_scheduler())

        # ── File-trash retention purge (24-hour interval) ─────────────
        # Walks ``oe_file_trash`` once a day and hard-deletes every row
        # whose ``trashed_at + retention_days`` window has lapsed. The
        # registration helper is idempotent so a hot-reload during dev
        # doesn't end up running two parallel purge loops against the
        # same database.
        try:
            if not _fast_startup:
                from app.modules.file_trash.jobs import register_jobs as _ft_register_jobs

                _ft_register_jobs()
        except Exception:
            logger.exception("file_trash scheduler registration failed")

        # ── Demo upload retention (24-hour interval) ──────────────────
        # Removes visitor uploads older than the configured window from the
        # public hosted demo, seeded demo content excluded. The registration
        # helper returns without starting anything unless this deployment is a
        # read-only demo AND an operator set a positive retention window, so a
        # self-hosted install has no loop and nothing that could call the
        # sweep. See :mod:`app.core.demo_retention`.
        try:
            if not _fast_startup:
                from app.core.demo_retention import register_jobs as _retention_register_jobs

                _retention_register_jobs()
        except Exception:
            logger.exception("demo_retention scheduler registration failed")

        # ── Cost-DB cache pre-warm (runs once, in background) ──────────
        # The "Add from Database" modal in the BOQ editor calls three
        # endpoints on open: /costs/regions/, /costs/category-tree/, and
        # /costs/search/. The first two issue full-table aggregations
        # (SELECT DISTINCT region, GROUP BY 4 JSON paths) that can be slow
        # on a cold database when the active catalog holds 100 k+ rows. The
        # user reported the modal
        # "loading forever" - this prewarm pays the aggregation cost
        # once at boot so every subsequent click is a cache hit.
        async def _prewarm_cost_caches() -> None:
            await asyncio.sleep(2)  # let other startup tasks settle
            try:
                import time as _ptime

                from sqlalchemy import distinct, select
                from sqlalchemy import func as _func

                from app.database import async_session_factory as _cost_sf
                from app.modules.costs.models import CostItem
                from app.modules.costs.router import (
                    _category_tree_cache,
                    _region_cache,
                )
                from app.modules.costs.schemas import CategoryTreeNode
                from app.modules.costs.service import CostItemService

                async with _cost_sf() as cost_session:
                    # 1) Distinct region list - drives the tab bar on /costs
                    #    and the modal's region picker.
                    r = await cost_session.execute(
                        select(distinct(CostItem.region))
                        .where(CostItem.is_active.is_(True))
                        .where(CostItem.region.isnot(None))
                        .where(CostItem.region != "")
                    )
                    regions = sorted(row[0] for row in r.all())
                    _region_cache["regions"] = regions

                    # 2) Per-region item-count stats - drives the count badge
                    #    on each region tab.
                    s = await cost_session.execute(
                        select(
                            CostItem.region,
                            _func.count(CostItem.id).label("cnt"),
                        )
                        .where(CostItem.is_active.is_(True))
                        .where(CostItem.region.isnot(None))
                        .where(CostItem.region != "")
                        .group_by(CostItem.region)
                        .order_by(_func.count(CostItem.id).desc())
                    )
                    _region_cache["stats"] = [{"region": row[0], "count": row[1]} for row in s.all()]

                    # 3) Distinct top-level categories - drives the category
                    #    filter dropdown. Warm the all-regions list (the
                    #    page's default before any region tab is clicked).
                    coll_expr = CostItem.classification["collection"].as_string()
                    c = await cost_session.execute(
                        select(distinct(coll_expr))
                        .where(CostItem.is_active.is_(True))
                        .where(coll_expr.isnot(None))
                        .where(coll_expr != "")
                        .order_by(coll_expr)
                    )
                    _region_cache["categories_all"] = [row[0] for row in c.all() if row[0]]
                    _region_cache["ts"] = _ptime.monotonic()

                    svc = CostItemService(cost_session)
                    for reg in regions:
                        try:
                            raw = await svc.category_tree(region=reg, depth=4)
                            nodes = [CategoryTreeNode.model_validate(n) for n in raw]
                            key = f"tree::{reg}::d=4::p="
                            _category_tree_cache[key] = {
                                "nodes": nodes,
                                "ts": _ptime.monotonic(),
                            }
                        except Exception:
                            logger.debug(
                                "Pre-warm tree failed for region=%s",
                                reg,
                                exc_info=True,
                            )
                logger.info(
                    "Cost-DB caches pre-warmed for %d regions",
                    len(regions),
                )
            except Exception:
                logger.debug("Cost-DB pre-warm failed (non-fatal)", exc_info=True)

        if not _fast_startup:
            asyncio.create_task(_prewarm_cost_caches())

        # ── Scheduled reports worker (1-minute tick) ────────────────────
        # Polls oe_reporting_template for rows whose ``next_run_at`` is
        # due, renders each one via the existing generate_report path,
        # then advances ``next_run_at`` using the stored cron expression.
        # Deliberately uses the same asyncio-based loop as the KPI
        # scheduler (not Celery) to keep the single-process footprint -
        # the architecture guide "LIGHTWEIGHT & SIMPLE".
        async def _reports_scheduler() -> None:
            from datetime import UTC
            from datetime import datetime as _dt

            while True:
                await asyncio.sleep(60)
                try:
                    from uuid import uuid4 as _uuid4

                    from app.database import async_session_factory as _rep_sf
                    from app.modules.reporting.schemas import (
                        GenerateReportRequest as _GenReq,
                    )
                    from app.modules.reporting.service import (
                        ReportingService as _RepSvc,
                    )

                    async with _rep_sf() as rep_session:
                        svc = _RepSvc(rep_session)
                        due = await svc.list_due_templates(_dt.now(UTC))
                        for template in due:
                            if template.project_id_scope is None:
                                # Portfolio reports need cross-project
                                # context we don't have yet - pause so
                                # the worker doesn't busy-loop.
                                template.is_scheduled = False
                                template.next_run_at = None
                                await svc.template_repo.update(template)
                                continue
                            try:
                                gen = _GenReq(
                                    project_id=template.project_id_scope,
                                    template_id=template.id,
                                    report_type=template.report_type,
                                    title=f"{template.name} (scheduled {_dt.now(UTC):%Y-%m-%d %H:%M} UTC)",
                                    format="pdf",
                                    metadata={
                                        "triggered_by": "scheduler",
                                        "run_id": str(_uuid4()),
                                    },
                                )
                                report = await svc.generate_report(gen)
                                await svc.mark_template_ran(template)
                                if template.recipients:
                                    try:
                                        await svc.dispatch_report_email(
                                            report,
                                            list(template.recipients),
                                        )
                                    except Exception:
                                        logger.exception(
                                            "Scheduled report %s email dispatch failed",
                                            template.id,
                                        )
                            except Exception:
                                logger.exception(
                                    "Scheduled report %s failed",
                                    template.id,
                                )
                        await rep_session.commit()
                except Exception:
                    logger.exception("Reports scheduler tick failed")

        if not _fast_startup:
            asyncio.create_task(_reports_scheduler())

        # No-code agent builder: fire scheduled custom agents (item #29). The
        # loop lives in the ai_agents module and self-schedules via asyncio;
        # fail-soft so a scheduler hiccup never blocks startup.
        try:
            if not _fast_startup:
                from app.modules.ai_agents.scheduler import start_scheduler

                start_scheduler()
        except Exception:  # noqa: BLE001 - never block startup on the scheduler
            logger.exception("AI agent scheduler failed to start")

        # Approval SLA monitor: background sweep that nudges the responsible
        # approver when a step blows past its configured sla_hours and records
        # the breach on the project timeline. Same lightweight asyncio loop;
        # fail-soft so a hiccup never blocks startup.
        try:
            if not _fast_startup:
                from app.modules.approval_routes.sla_monitor import start_sla_checker

                start_sla_checker()
        except Exception:  # noqa: BLE001 - never block startup on the monitor
            logger.exception("Approval SLA monitor failed to start")

        # Cross-module deadline sweeper (item #18): background sweep that nudges
        # the owner when a tracked deadline (correspondence response, NCR
        # corrective action, punch item) slips overdue and escalates it past the
        # grace window. Same lightweight asyncio loop as the SLA monitor above;
        # fail-soft so a hiccup never blocks startup.
        try:
            if not _fast_startup:
                from app.modules.deadlines.sweeper import start_deadline_sweeper

                start_deadline_sweeper()
        except Exception:  # noqa: BLE001 - never block startup on the sweeper
            logger.exception("Deadline sweeper failed to start")

        # Risk auto-escalation (item #24): hourly sweep that escalates risks
        # crossing their severity threshold or with a lapsed review date. The
        # review-lapse trigger has no update event, so a periodic sweep is the
        # only path that catches it. Same lightweight asyncio loop as above;
        # the sweep is idempotent and commits nothing itself (caller commits).
        async def _risk_escalation_sweeper() -> None:
            while True:
                await asyncio.sleep(3600)
                try:
                    from app.database import async_session_factory as _risk_sf
                    from app.modules.risk.escalation import RiskEscalationService

                    async with _risk_sf() as risk_session:
                        await RiskEscalationService(risk_session).sweep()
                        await risk_session.commit()
                except Exception:
                    logger.exception("Risk escalation sweep tick failed")

        if not _fast_startup:
            asyncio.create_task(_risk_escalation_sweeper())

        _section("Ready")
        # Friendly multi-line ready banner. The CLI (`openestimate serve`)
        # exposes OE_CLI_HOST / OE_CLI_PORT / OE_CLI_DATA_DIR so we can show
        # an accurate URL after the socket is actually bound. If those env
        # vars are absent (e.g. `uvicorn app.main:create_app --factory`), we
        # fall back to a generic message.
        _cli_host = os.environ.get("OE_CLI_HOST")
        _cli_port = os.environ.get("OE_CLI_PORT")
        _cli_data_dir = os.environ.get("OE_CLI_DATA_DIR")
        if _cli_host and _cli_port:
            _url = f"http://{_cli_host}:{_cli_port}"
            logger.info("OpenConstructionERP is ready at %s", _url)
            # Demo passwords are now per-installation (BUG-D01 fix). The
            # actual values were either supplied via DEMO_*_PASSWORD env
            # vars or generated in ``_seed_demo_account`` and persisted to
            # ``~/.openestimator/.demo_credentials.json``. Pointing the
            # operator at that file beats baking a fixed password into
            # every running instance.
            logger.info(
                "Demo login: demo@openconstructionerp.com "
                "(password from DEMO_USER_PASSWORD env var or "
                "~/.openestimator/.demo_credentials.json)"
            )
            if _cli_data_dir:
                logger.info("Data directory: %s", _cli_data_dir)
            logger.info("Press Ctrl+C to stop. Docs: https://openconstructionerp.com/docs")
        else:
            logger.info("Application started successfully")

        # ── Publish the OpenAPI document ─────────────────────────────────
        # Every router this process will ever mount is mounted by now, which
        # is why the prime is here and not in create_app(). How I know: the
        # module loader runs inside this same handler, above, and the handful
        # of alias mounts that follow it are the last include_router calls in
        # the file. Priming from create_app() would cache a document built
        # before ~190 module routers existed, and a schema that is missing
        # most of the API is worse than a schema that is slow.
        #
        # Deliberately not awaited. Starlette accepts no requests until this
        # handler returns, so awaiting a ~141s build would move the stall off
        # the first docs visitor and onto every user of the app, including the
        # health check.
        #
        # The thread is worth being precise about, because this is CPU-bound
        # Python and a thread does not escape the GIL: it does not make the
        # build free, it makes it interruptible. Building on the event loop
        # blocks every request for the whole 141s. Building on a thread leaves
        # the loop scheduled against it, so requests are served throughout,
        # just slower while it runs - measured on this stand, health answered
        # in 17.1s, 0.7s and 2.2s during the build instead of not at all. A
        # visitor who arrives before it finishes waits on the same lock rather
        # than starting a second build. The task is parked on app.state
        # because asyncio keeps only a weak reference to a bare task and would
        # otherwise be free to collect it mid-build.
        #
        # Runtime module toggles stay correct without help here: enabling or
        # disabling a module moves the route counter that _custom_openapi
        # checks, so the next request rebuilds rather than serving a document
        # that describes the wrong set of modules.
        if not _fast_startup:

            async def _prime_openapi_schema() -> None:
                try:
                    started = time.perf_counter()
                    schema = await asyncio.to_thread(app.openapi)
                    logger.info(
                        "OpenAPI schema cached: %d paths in %.1fs",
                        len(schema.get("paths", {})),
                        time.perf_counter() - started,
                    )
                except Exception:
                    # Never fail a boot over the documentation. Without the
                    # cache the first /api/docs visitor pays for the build,
                    # which is exactly the old behaviour.
                    logger.warning(
                        "OpenAPI schema priming failed; the docs will build on first request",
                        exc_info=True,
                    )

            app.state.openapi_prime_task = asyncio.create_task(_prime_openapi_schema())

        # NOTE: frontend static mounting moved to create_app() (below, before
        # the startup event runs). Registering the SPA 404 exception handler
        # here (inside the startup lifespan) is TOO LATE - Starlette has
        # already built the ExceptionMiddleware by the time lifespan.startup
        # fires, and the middleware captures a COPY of app.exception_handlers
        # at build time.  Subsequent modifications to app.exception_handlers
        # (like the one mount_frontend used to do) never reach the middleware.
        # Symptom: https://.../demo/ returned a JSON 404 instead of index.html.

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("Shutting down %s", settings.app_name)
        from app.database import engine

        # Stop the collaboration-lock sweeper before closing the DB
        # engine so its last iteration cannot hit a disposed pool.
        try:
            from app.modules.collaboration_locks.sweeper import stop_sweeper

            stop_sweeper()
        except Exception:
            logger.debug("collab lock sweeper stop failed", exc_info=True)

        # Tear down the embedding inference pool so Ctrl-C doesn't
        # leave orphan Python worker processes alive.
        try:
            from app.core.embedding_pool import shutdown_pool

            shutdown_pool()
        except Exception:
            logger.debug("embedding pool shutdown failed", exc_info=True)

        # Close the Geo Hub basemap tile proxy's shared httpx connection
        # pool so a reload / Ctrl-C doesn't leave kept-alive sockets open.
        try:
            from app.modules.geo_hub.router import close_tile_client

            await close_tile_client()
        except Exception:
            logger.debug("geo tile client shutdown failed", exc_info=True)

        await engine.dispose()

        # Stop the embedded PostgreSQL cluster last (after the engine pool is
        # closed), if this process booted one. No-op otherwise.
        try:
            from app.core import embedded_pg

            embedded_pg.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("embedded PostgreSQL shutdown skipped", exc_info=True)

    # ── Frontend Static Files (CLI / single-image mode) ─────────────────────
    # Registered HERE, before the app is returned from create_app(), so the
    # SPA 404 exception handler is already in app.exception_handlers when
    # Starlette builds the ExceptionMiddleware on the first lifespan message.
    # (If this runs inside on_event("startup"), the handler is never wired up
    # and the SPA 404 fallback silently does nothing - see comment above.)
    #
    # Exception handlers are independent of routes, so it is safe to register
    # this before module routers are mounted: the handler only fires for
    # requests that do NOT match any route.
    if os.environ.get("SERVE_FRONTEND", "").lower() in ("1", "true", "yes"):
        try:
            from app.cli_static import mount_frontend

            mount_frontend(app)
        except Exception as exc:  # noqa: BLE001 - frontend is optional
            logger.warning("Frontend mount skipped: %s", exc)

    return app
