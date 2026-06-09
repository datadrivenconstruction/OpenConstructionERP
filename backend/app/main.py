# OpenConstructionERP - DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · CAD2DATA Pipeline
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""‌⁠‍OpenEstimate​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - FastAPI application factory.

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

import hashlib as _hashlib
import logging
import os
import secrets
import time
import uuid
import uuid as _instance_uuid
from typing import Any

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

from app.config import Settings, build_provenance_tag, get_settings
from app.core.module_loader import module_loader
from app.dependencies import RequireRole, get_current_user_id

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """‌⁠‍Configure structured logging."""
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
    """‌⁠‍Initialize vector database on startup (non-blocking, never fatal).

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
            logger.warning(
                "LanceDB init failed (%s). Semantic search is disabled. "
                "Install the embedded vector backend with: pip install openconstructionerp[vector]",
                error,
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
    """
    if os.environ.get("SEED_DEMO", "true").lower() in ("false", "0", "no"):
        return

    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    # Email → env-var-name mapping. Order matters for stable banner output.
    demo_account_specs: list[dict[str, str]] = [
        {
            "email": "demo@openconstructionerp.com",
            "env_var": "DEMO_USER_PASSWORD",
            "full_name": "Demo User",
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
            "full_name": "Thomas Müller",
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

        # ── 3. Project seed (outside the user session) ────────────────
        # Two distinct seeding paths run on PostgreSQL, picked by whether a
        # partner pack is active:
        #
        #   PACK MODE  (a pack is active): seed ONLY that pack's own country
        #     project(s) so the workspace reflects the partner's region,
        #     currency and classification - nothing else.
        #
        #   GENERIC MODE (no pack): seed the rich nine-project showcase - the
        #     eight country projects in SHOWCASE_DEMO_IDS plus the flagship
        #     reference project installed further below - so a fresh, vanilla
        #     install lands a fully worked-out, globe-spanning portfolio.
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
                            )
                if not pack_ids:
                    logger.info(
                        "Partner pack %s is active but maps to no demo project; skipping demo seed.",
                        active.slug,
                    )
            else:
                # GENERIC MODE - seed the rich showcase by default. Tests ask for
                # a fast startup (OE_TEST_FAST_STARTUP), and operators can opt out
                # with OE_SKIP_SHOWCASE=1; both skip the eight-project loop. The
                # flagship below still installs and provides the ninth project.
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
                                logger.warning(
                                    "Failed to install showcase demo %s (skipping)",
                                    demo_id,
                                )

        # Flagship "Residential House" reference project - an ORM installer
        # running on PostgreSQL so the full CAD-to-BOQ showcase (real
        # DDC-converted IFC/RVT geometry + a CWICR-priced, BIM-linked Bill of
        # Quantities) is present out of the box. Idempotent, so it also
        # backfills existing databases on the next startup. Runs regardless of
        # project_count so an upgrade picks it up.
        if os.environ.get("OE_TEST_FAST_STARTUP", "").lower() in ("1", "true", "yes"):
            # The flagship installer writes a 6640-element model and ~16MB of
            # geometry; no test needs it, and it adds several seconds to every
            # per-module app startup. Skip it when the test suite asks for a
            # fast startup.
            logger.debug("Flagship seed skipped (OE_TEST_FAST_STARTUP)")
        else:
            try:
                from app.scripts.seed_flagship import install_flagship

                async with async_session_factory() as fl_session:
                    fl_result = await install_flagship(fl_session, demo_user_id)
                    logger.info("Flagship seed: %s", fl_result)
            except Exception:
                logger.warning("Flagship seed skipped (non-fatal)", exc_info=True)

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
                logger.warning("Subcontractor demo seed skipped (non-fatal)", exc_info=True)

            # ── Remaining feature-module demos ──────────────────────────────
            # bid management, carbon, CRM, HSE-Advanced, portal, QMS, advanced
            # scheduling (Last Planner), service management, supplier catalogs
            # and variations each ship a demo seeder that was never wired into
            # startup, so those modules opened empty. Run them across the demo
            # projects so every module arrives populated. Each runs in its own
            # session (one failure cannot poison the rest); the seeders that are
            # not internally idempotent are gated on a marker table so a restart
            # never duplicates their rows.
            try:
                from sqlalchemy import func as _func
                from sqlalchemy import select as _msel

                from app.modules.accommodation.seed import seed_accommodation
                from app.modules.bid_management.seed import seed_bid_management_demo
                from app.modules.bim_hub.seed import seed_bim_hub
                from app.modules.carbon.models import CarbonInventory
                from app.modules.carbon.seed import seed_carbon_demo
                from app.modules.catalog.seed import seed_catalog
                from app.modules.clash.seed import seed_clash
                from app.modules.costmodel.seed import seed_costmodel
                from app.modules.crm.seed import seed_crm_demo
                from app.modules.documents.photos_seed import seed_photos
                from app.modules.hse_advanced.seed import seed_hse_advanced_demo
                from app.modules.markups.seed import seed_markups
                from app.modules.moc.seed import seed_moc
                from app.modules.portal.seed import seed_portal_demo
                from app.modules.projects.models import Project as _Proj2
                from app.modules.qms.models import ITPPlan
                from app.modules.qms.seed import seed_qms
                from app.modules.schedule_advanced.models import MasterSchedule
                from app.modules.schedule_advanced.seed import seed_schedule_advanced_demo
                from app.modules.service.seed import seed_service_demo
                from app.modules.supplier_catalogs.seed import seed_supplier_catalogs
                from app.modules.takeoff.seed import seed_takeoff_demo
                from app.modules.tendering.seed import seed_tendering
                from app.modules.variations.models import Notice
                from app.modules.variations.seed import seed_variations_demo

                async with async_session_factory() as _pid_s:
                    _all_pids = list((await _pid_s.execute(_msel(_Proj2.id))).scalars().all())
                # Keep the flagship reference project first so seeders that cap
                # at a few projects (advanced scheduling, QMS, supplier catalog)
                # always cover the project users land on.
                _flagship_id = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")
                _all_pids.sort(key=lambda _p: 0 if _p == _flagship_id else 1)
                _first_pid = _all_pids[0] if _all_pids else None

                # (name, marker model gating a restart-safe skip, coroutine builder).
                # A None marker means the seeder self-guards against duplicates.
                _module_seeders = [
                    ("crm", None, lambda s: seed_crm_demo(s)),
                    ("service", None, lambda s: seed_service_demo(s)),
                    ("bid_management", None, lambda s: seed_bid_management_demo(s, _all_pids)),
                    ("hse_advanced", None, lambda s: seed_hse_advanced_demo(s, _all_pids)),
                    ("portal", None, lambda s: seed_portal_demo(s, _all_pids)),
                    ("supplier_catalogs", None, lambda s: seed_supplier_catalogs(s, _first_pid)),
                    ("carbon", CarbonInventory, lambda s: seed_carbon_demo(s, _all_pids)),
                    (
                        "schedule_advanced",
                        MasterSchedule,
                        lambda s: seed_schedule_advanced_demo(s, _all_pids),
                    ),
                    ("variations", Notice, lambda s: seed_variations_demo(s, _all_pids)),
                    # ── Modules that shipped without any startup seeder at all ──
                    # Each new seeder below is internally idempotent (it returns
                    # an empty dict once its own marker rows already exist), so
                    # they are wired with a None marker and re-checked cheaply on
                    # every restart. A None marker is required here rather than a
                    # global row-count gate because several of these (takeoff,
                    # tendering, markups) legitimately share their table with
                    # rows seeded elsewhere or by users, so a table-wide count
                    # would skip the projects that are still empty.
                    ("costmodel", None, lambda s: seed_costmodel(s, _all_pids)),
                    ("moc", None, lambda s: seed_moc(s, _all_pids)),
                    ("tendering", None, lambda s: seed_tendering(s, _all_pids)),
                    ("takeoff", None, lambda s: seed_takeoff_demo(s, _all_pids)),
                    ("accommodation", None, lambda s: seed_accommodation(s, _all_pids)),
                    ("markups", None, lambda s: seed_markups(s, _all_pids)),
                    ("catalog", None, lambda s: seed_catalog(s, _all_pids)),
                    # Site photos drop real JPEGs into the gallery so the Photos
                    # module and the dashboard "latest photos" widget are never
                    # empty on a fresh install. Self-guards on an existing seeded
                    # photo for the flagship project.
                    ("photos", None, lambda s: seed_photos(s, _all_pids)),
                    # bim_hub groups the BIM models that already exist for a
                    # project, so it runs near the end (after every other
                    # seeder). clash runs right after it so its clash results
                    # reference the freshly grouped models; clash also feeds the
                    # coordination_hub dashboard's clash rollup.
                    ("bim_hub", None, lambda s: seed_bim_hub(s, _all_pids)),
                    ("clash", None, lambda s: seed_clash(s, _all_pids)),
                ]
                for _name, _marker, _build in _module_seeders:
                    try:
                        if _marker is not None:
                            async with async_session_factory() as _chk:
                                _n = (await _chk.execute(_msel(_func.count()).select_from(_marker))).scalar_one()
                            if _n:
                                continue
                        async with async_session_factory() as _ms:
                            _counts = await _build(_ms)
                            await _ms.commit()
                            if isinstance(_counts, dict) and any(_counts.values()):
                                logger.info("%s demo seed: %s", _name, _counts)
                    except Exception:
                        logger.warning("%s demo seed skipped (non-fatal)", _name, exc_info=True)

                # QMS seeds one project at a time and is not internally
                # idempotent; loop the demo projects, skipping any that already
                # carry an ITP plan so a restart never duplicates.
                for _pid in _all_pids:
                    try:
                        async with async_session_factory() as _qs:
                            _has = (
                                await _qs.execute(_msel(ITPPlan.id).where(ITPPlan.project_id == _pid).limit(1))
                            ).scalar_one_or_none()
                            if _has is None:
                                await seed_qms(_qs, project_id=_pid)
                                await _qs.commit()
                    except Exception:
                        logger.warning("qms demo seed skipped for %s (non-fatal)", _pid, exc_info=True)
            except Exception:
                logger.warning("Feature-module demo seeds skipped (non-fatal)", exc_info=True)
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
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        # BUG-394: don't expose the full OpenAPI schema in production - it
        # hands attackers a route/parameter enumeration map of every endpoint,
        # including rarely-exercised admin surfaces. Dev still gets it for
        # the Swagger/ReDoc UI and for openapi-typescript client generation.
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        swagger_ui_oauth2_redirect_url=("/api/docs/oauth2-redirect" if not settings.is_production else None),
        redirect_slashes=False,
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

    # ── OpenAPI origin extension ─────────────────────────────────────────
    # Stamp an x- vendor extension into info{} so any fork that exposes
    # /api/openapi.json or /api/docs leaks provenance. ``x-`` extensions
    # are valid per the OpenAPI spec and ignored by every generator /
    # client (incl. openapi-typescript), so the API surface is unchanged.
    # The token bytes XOR-decode (key 0x55) to the authorship marker.
    from fastapi.openapi.utils import get_openapi as _get_openapi

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
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
        return schema

    app.openapi = _custom_openapi  # type: ignore[method-assign]

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

    # ── Global exception handler - return JSON for unhandled errors ────
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

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
    from app.core.partner_pack.router import router as partner_pack_router

    app.include_router(partner_pack_router)
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
        import os as _os
        from pathlib import Path as _Path

        result: dict[str, Any] = {
            "status": "healthy",
            "version": settings.app_version,
            "env": settings.app_env,
            "instance_id": _INSTANCE_ID,
            "build": f"DDC-{_BUILD_HASH}",
            "signature": build_provenance_tag(settings.app_version),
            "modules_loaded": len(module_loader.list_modules()),
            "uptime_seconds": int(time.time() - _startup_time),
        }

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
        try:
            from alembic.config import Config as _AlembicConfig
            from alembic.runtime.migration import MigrationContext as _MigCtx
            from alembic.script import ScriptDirectory as _ScriptDir
            from sqlalchemy import text as _text  # noqa: F401

            from app.database import engine as _engine

            _ini = _Path(__file__).resolve().parent.parent / "alembic.ini"
            if _ini.is_file():
                _cfg = _AlembicConfig(str(_ini))
                _script = _ScriptDir.from_config(_cfg)
                _expected = _script.get_current_head()

                async with _engine.connect() as _conn:
                    _actual = await _conn.run_sync(
                        lambda sync_conn: _MigCtx.configure(sync_conn).get_current_revision()
                    )
                result["alembic_head_matches"] = _expected == _actual
                if _expected != _actual:
                    result["status"] = "degraded"
            else:
                result["alembic_head_matches"] = None
        except Exception as _exc:  # noqa: BLE001
            logger.warning("Alembic head check failed: %s", _exc)
            result["alembic_head_matches"] = None

        # Frontend dist presence - the wheel ships ``app/_frontend_dist/``;
        # a missing ``index.html`` means the SPA shell will 404 and users
        # see a blank page even though /api endpoints work.
        try:
            _dist_index = _Path(__file__).resolve().parent / "_frontend_dist" / "index.html"
            result["frontend_dist_present"] = _dist_index.is_file()
            if not result["frontend_dist_present"]:
                result["status"] = "degraded"
        except Exception:
            result["frontend_dist_present"] = False
            result["status"] = "degraded"

        # Process memory (RSS) in MB - available on all platforms
        try:
            import resource

            rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS returns bytes, Linux returns KB
            if _os.uname().sysname == "Darwin":
                result["memory_mb"] = round(rss_bytes / (1024 * 1024), 1)
            else:
                result["memory_mb"] = round(rss_bytes / 1024, 1)
        except Exception:
            try:
                # Windows / fallback via psutil if available
                import psutil

                proc = psutil.Process(_os.getpid())
                result["memory_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass  # Memory reporting is best-effort

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
        except Exception as exc:
            result["database"] = {"status": "error", "error": str(exc)[:100]}

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

    @app.get("/api/system/version-check", tags=["System"])
    async def check_version() -> dict:
        """Return current vs latest published version.

        Source of truth is **PyPI** (more reliable than GitHub releases -
        Trusted-Publisher OIDC always produces a wheel, GitHub release
        creation is sometimes skipped on hotfixes). Falls back to GitHub
        releases if PyPI is unreachable. Both lookups are cached on
        ``app.state`` for 4 hours so the settings panel can poll cheaply
        without burning the unauthenticated GitHub rate limit.
        """
        import httpx

        current = settings.app_version
        repo = "datadrivenconstruction/OpenConstructionERP"
        cache_key = "_version_check_cache"

        cached = getattr(app.state, cache_key, None)
        if cached and (time.time() - cached["checked_at"]) < 14400:
            return cached["data"]

        latest: str | None = None
        release_url = f"https://github.com/{repo}/releases/latest"
        release_notes = ""
        published_at = ""

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
                    if not latest:
                        latest = gh_tag
                    release_url = release.get("html_url", release_url)
                    release_notes = (release.get("body") or "")[:500]
                    published_at = release.get("published_at", "")
        except Exception:  # noqa: BLE001
            pass

        if not latest:
            latest = current

        update_available = _semver_tuple(latest) > _semver_tuple(current)
        result = {
            "current_version": current,
            "latest_version": latest,
            "update_available": update_available,
            "release_url": release_url,
            "release_notes": release_notes,
            "published_at": published_at,
            "upgrade_command": "pip install --upgrade openconstructionerp",
        }
        setattr(app.state, cache_key, {"data": result, "checked_at": time.time()})
        return result

    @app.post("/api/system/upgrade", tags=["System"])
    async def trigger_upgrade(
        version: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run ``pip install --upgrade openconstructionerp`` in this venv.

        Best-effort one-click upgrade. We shell out to the **same**
        interpreter that's serving the API so the upgrade lands in the
        right venv (Issue #96 - Windows launcher uses
        ``%LOCALAPPDATA%/OpenConstructionERP/venv``, not the user's
        global Python). Captures stdout+stderr so the UI can show the
        installer log.

        **Important - the running process keeps the OLD wheel in memory.**
        Python caches imports; pip can replace files on disk but cannot
        swap modules already loaded. The response includes
        ``restart_required=true`` and the new version pulled from
        ``importlib.metadata`` so the UI can prompt the user to restart
        their launcher (``openconstructionerp serve``) or, on managed
        installs, the host's systemd unit.

        Gated by ``ALLOW_RUNTIME_UPGRADE=true`` (default off in
        production) - VPS / staging installs use a deploy pipeline, not
        in-app upgrades. Localhost dev / Windows-installer installs ship
        with the flag on so the Settings panel works out of the box.
        """
        import os
        import subprocess
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

        target = "openconstructionerp"
        if version and version.replace(".", "").replace("-", "").isalnum():
            target = f"openconstructionerp=={version}"

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", target]
        if force:
            cmd.insert(-1, "--force-reinstall")

        proc = subprocess.run(  # noqa: S603 - args are sanitised above
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        new_version = settings.app_version
        try:
            from importlib.metadata import version as _v

            new_version = _v("openconstructionerp")
        except Exception:  # noqa: BLE001
            pass

        if hasattr(app.state, "_version_check_cache"):
            del app.state._version_check_cache

        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": " ".join(cmd),
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
            "installed_version": new_version,
            "running_version": settings.app_version,
            "restart_required": new_version != settings.app_version,
            "restart_hint": (
                "Restart your launcher (start.bat / `openconstructionerp serve`) "
                "or the host's systemd unit to load the new version."
            ),
        }

    @app.get("/api/system/converters/version-check", tags=["System"])
    async def check_converter_versions() -> dict[str, Any]:
        """Compare each installed DDC converter against the latest on GitHub.

        Computes the git-blob SHA-1 of every locally-installed converter and
        compares it to the SHA returned by GitHub's Contents API for the
        same file in `cad2data-Revit-IFC-DWG-DGN`. A mismatch means the
        user has an older build and a newer one is available.

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
                "results": [],
                "platform": sys.platform,
                "note": (
                    "Converter version checks apply to the Windows builds; this "
                    "platform uses the DDC apt repository (Linux) or has no native build."
                ),
            }

        # Per-format directory inside the repo. Mirrors `_WINDOWS_CONVERTER_DIRS`
        # in takeoff/router.py - duplicated here so the system endpoint
        # works even when the takeoff module is not loaded (it ships
        # disabled by default in some configurations).
        DDC_REPO = "datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN"
        DDC_BRANCH = "main"
        WIN_DIRS: dict[str, tuple[str, str, str]] = {
            # ext: (github_dir, exe_name, display_name)
            "rvt": ("DDC_WINDOWS_Converters/DDC_CONVERTER_REVIT", "RvtExporter.exe", "Revit (RVT) Parser"),
            "ifc": ("DDC_WINDOWS_Converters/DDC_CONVERTER_IFC", "IfcExporter.exe", "IFC Import"),
            "dwg": ("DDC_WINDOWS_Converters/DDC_CONVERTER_DWG", "DwgExporter.exe", "DWG/DXF Converter"),
            "dgn": ("DDC_WINDOWS_Converters/DDC_CONVERTER_DGN", "DgnExporter.exe", "DGN Converter"),
        }
        TTL = 6 * 3600

        cached = getattr(app.state, "_converter_version_cache", None)
        if cached and (time.time() - cached.get("checked_at_ts", 0)) < TTL:
            return cached["data"]

        def git_blob_sha1(content: bytes) -> str:
            header = f"blob {len(content)}\0".encode()
            return hashlib.sha1(header + content).hexdigest()  # noqa: S324  # git uses SHA-1

        async def fetch_remote(ext: str, gh_dir: str, exe: str) -> dict[str, Any] | None:
            url = f"https://api.github.com/repos/{DDC_REPO}/contents/{gh_dir}/{exe}?ref={DDC_BRANCH}"
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
            "any_outdated": any_outdated,
            "network_ok": network_ok,
            "checked_at": _dt.now(UTC).isoformat(),
            "ttl_seconds": TTL,
        }
        if network_ok:
            app.state._converter_version_cache = {"data": response, "checked_at_ts": time.time()}
        return response

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
        _section("OpenConstructionERP")
        logger.info(
            "Starting %s v%s (env=%s)",
            settings.app_name,
            settings.app_version,
            settings.app_env,
        )

        # Validate secrets and configuration outside local development.
        # HS256 requires at least 32 bytes of entropy (RFC 7518 §3.2).
        _insecure_secrets = {"change-me-in-production", "openestimate-local-dev-key", ""}
        _jwt_too_short = len(settings.jwt_secret.encode("utf-8")) < 32
        _jwt_is_default = settings.jwt_secret in _insecure_secrets
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

        # Load translations (24 languages)
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

            # ``audit_log`` defines the ``oe_activity_log`` table used by the
            # FSM ``log_activity()`` helper (submittals/RFI/etc. status
            # transitions). It lives in app.core (not app.modules.*) so the
            # dynamic module-models loop below never reaches it. Without this
            # explicit import the table is absent on a fresh database, so every
            # status-changing action raised an error, which poisoned the request
            # session and cascaded into a 500 on the subsequent re-fetch.
            # Register it before create_all.
            from app.core import audit_log as _audit_log_core  # noqa: F401
            from app.database import Base, engine

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
            from app.core import embedded_pg as _embedded_pg

            if _embedded_pg.is_running():
                from app.core.postgres_migrator import postgres_auto_migrate

                migrated = await postgres_auto_migrate(engine, Base)
                if migrated:
                    logger.info("PostgreSQL auto-migration: %d columns added", migrated)

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
            def _stamp_head_if_unstamped(sync_conn: object) -> str | None:
                from pathlib import Path as _StampPath

                from alembic.config import Config as _StampConfig
                from alembic.runtime.migration import MigrationContext as _StampMigCtx
                from alembic.script import ScriptDirectory as _StampScriptDir

                mig_ctx = _StampMigCtx.configure(sync_conn)
                if mig_ctx.get_current_revision() is not None:
                    return None  # already stamped - leave existing state untouched
                ini = _StampPath(__file__).resolve().parent.parent / "alembic.ini"
                if not ini.is_file():
                    return None
                script = _StampScriptDir.from_config(_StampConfig(str(ini)))
                mig_ctx.stamp(script, "heads")
                return script.get_current_head()

            try:
                async with engine.begin() as conn:
                    stamped = await conn.run_sync(_stamp_head_if_unstamped)
                if stamped:
                    logger.info("Alembic version stamped to head %s on fresh DB", stamped)
            except Exception:
                logger.debug("Alembic head stamp skipped (non-fatal)", exc_info=True)
        else:
            logger.info("Using external database (Alembic manages schema)")

        # Load all modules (triggers module on_startup hooks)
        _section("Modules")
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
            _init_vector_db()

            # Pre-warm the embedder + boot the inference process pool. Both
            # are env-var-gated so dev startup stays fast unless the
            # operator opted in. See ``app.core.embedding_pool`` for the
            # full rationale and trade-offs.
            #
            # We unconditionally call get_embedder() here as well: the
            # auto-backfill task (scheduled below) and /match-elements
            # vector matcher both call ``encode_texts_async`` from worker
            # threads. On Windows + Anaconda the first SentenceTransformer
            # load from a worker thread can race with concurrent torch
            # imports and silently leave the singleton at None - every
            # subsequent encode then raises "No embedding model available".
            # Loading on the main thread once primes the singleton so
            # later calls just hit the cache.
            try:
                from app.core.vector import get_embedder as _ge

                _ge()
            except Exception as exc:  # noqa: BLE001 - never fatal for startup
                logger.info("Embedder main-thread prime skipped: %s", exc)

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

        asyncio.create_task(_kpi_scheduler())

        # ── File-trash retention purge (24-hour interval) ─────────────
        # Walks ``oe_file_trash`` once a day and hard-deletes every row
        # whose ``trashed_at + retention_days`` window has lapsed. The
        # registration helper is idempotent so a hot-reload during dev
        # doesn't end up running two parallel purge loops against the
        # same database.
        try:
            from app.modules.file_trash.jobs import register_jobs as _ft_register_jobs

            _ft_register_jobs()
        except Exception:
            logger.exception("file_trash scheduler registration failed")

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

        asyncio.create_task(_reports_scheduler())

        # No-code agent builder: fire scheduled custom agents (item #29). The
        # loop lives in the ai_agents module and self-schedules via asyncio;
        # fail-soft so a scheduler hiccup never blocks startup.
        try:
            from app.modules.ai_agents.scheduler import start_scheduler

            start_scheduler()
        except Exception:  # noqa: BLE001 - never block startup on the scheduler
            logger.exception("AI agent scheduler failed to start")

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
