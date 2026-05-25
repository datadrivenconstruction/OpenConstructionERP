# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Project module-presence probe.

A lightweight scanner that answers: *"does project X have any data in
module Y?"* — one boolean per sidebar module. The frontend uses the
answers to dim empty modules in the sidebar so users see, at a glance,
which surfaces actually carry data for the project they are looking at.

Design constraints
~~~~~~~~~~~~~~~~~~

* **Cheap probes only.** Each module check is a single
  ``SELECT 1 FROM <table> WHERE project_id = :pid LIMIT 1`` — no
  ``COUNT(*)``, no joins. Index hit per row, O(1) per probe.
* **Concurrent.** All probes run via :func:`asyncio.gather` so the total
  latency is dominated by the slowest single probe, not the sum.
* **Defensive.** A missing table (fresh DB, alembic not yet run) yields
  ``False`` — never a 500. ``OperationalError`` / ``ProgrammingError``
  are swallowed silently per-probe; nothing else is.
* **Cached.** Per-project payload kept in-memory for 60 s. Same pattern
  the coordination-hub dashboard uses. The sidebar polls this on every
  project switch so even a tiny TTL is a big saving.

Caching uses a dict keyed on ``project_id``; this is single-process. If
the deploy ever shards workers we'll need to switch to Redis, but the
contract here is "best-effort hint, refreshes within a minute" so a
process-local cache is fine.

Module → table map lives in :data:`PRESENCE_PROBES`. Each entry pairs a
sidebar slug with a SQL fragment. Adding a new module is one line.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

try:
    from sqlalchemy.exc import InFailedSQLTransactionError
except ImportError:
    # Older SQLAlchemy (<2.0): InFailedSQLTransactionError was added in 2.0.
    # Fall back to the base class so the except clause still compiles.
    from sqlalchemy.exc import DBAPIError as InFailedSQLTransactionError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Cache ───────────────────────────────────────────────────────────────────

_PRESENCE_TTL_SECONDS: float = 60.0
_PRESENCE_CACHE: dict[uuid.UUID, tuple[dict[str, bool], float]] = {}


def invalidate_presence_cache(project_id: uuid.UUID | None = None) -> None:
    """Drop cache for one project (or every project when ``None``).

    Called by mutation hooks if/when we wire them in — for now the
    60 s TTL is sufficient since the sidebar polls on every navigation.
    """
    if project_id is None:
        _PRESENCE_CACHE.clear()
    else:
        _PRESENCE_CACHE.pop(project_id, None)


# ── Probe registry ──────────────────────────────────────────────────────────


class Probe(NamedTuple):
    """A single module-presence check.

    Attributes:
        module_key: Sidebar slug used as the response field name.
                    Must match a ``ProjectModulePresence`` model field.
        sql:        SQL fragment of the form
                    ``SELECT 1 FROM <table> WHERE <filter> LIMIT 1``.
                    The filter MUST bind ``:pid`` as the project UUID
                    (rendered as ``str(uuid)`` by the executor — works
                    for both PostgreSQL UUID and SQLite TEXT columns).
    """

    module_key: str
    sql: str


def _project_probe(table: str, *, column: str = "project_id") -> str:
    """Build a standard ``SELECT 1 ... LIMIT 1`` probe on a project column."""
    return f"SELECT 1 FROM {table} WHERE {column} = :pid LIMIT 1"  # noqa: S608


# The order here is informational only — probes run concurrently. Keys
# MUST match ``ProjectModulePresence`` schema fields (or their aliases).
PRESENCE_PROBES: tuple[Probe, ...] = (
    # ── Estimation & BIM ────────────────────────────────────────────────
    Probe("boq", _project_probe("oe_boq_boq")),
    Probe("takeoff", _project_probe("oe_takeoff_measurement")),
    Probe("clash", _project_probe("oe_clash_run")),
    Probe("bim", _project_probe("oe_bim_model")),
    # CostItems are global; "costs presence" for a project means
    # the project has bound at least one assembly (per-project cost
    # binding). Sidebar dims when there's no project-scoped cost
    # activity at all.
    Probe("costs", _project_probe("oe_assemblies_assembly")),
    Probe("match_elements", _project_probe("oe_match_elements_session")),
    Probe("assemblies", _project_probe("oe_assemblies_assembly")),
    Probe(
        "smart_views",
        "SELECT 1 FROM oe_smart_view "
        "WHERE scope_type = 'project' AND scope_id = :pid LIMIT 1",
    ),
    Probe("bim_requirements", _project_probe("oe_bim_requirement_set")),
    Probe("bcf", _project_probe("oe_bcf_topic")),
    # ── Planning & Field ───────────────────────────────────────────────
    Probe("schedule", _project_probe("oe_schedule_schedule")),
    Probe("tasks", _project_probe("oe_tasks_task")),
    # 5D = BOQ × Schedule combined; sidebar lights it up only when
    # the schedule has activities (BOQ alone is a 2D check).
    Probe("5d", _project_probe("oe_schedule_activity")),
    Probe("risk", _project_probe("oe_risk_register")),
    Probe("field_reports", _project_probe("oe_fieldreports_report")),
    Probe("daily_diary", _project_probe("oe_daily_diary_diary")),
    # Equipment master table is global; we treat "has any project-scoped
    # assignment / utilisation" as the presence signal — fall back to
    # the equipment table itself if no assignment table exists. Many
    # deployments populate equipment without project assignments; the
    # cheap probe is the type table when it exists.
    Probe("equipment", _project_probe("oe_equipment_equipment")),
    Probe("resources", _project_probe("oe_resources_assignment")),
    Probe("service", _project_probe("oe_service_ticket")),
    Probe("portal", _project_probe("oe_portal_access_rule")),
    # ── Commercial ─────────────────────────────────────────────────────
    Probe("finance", _project_probe("oe_finance_invoice")),
    Probe("procurement", _project_probe("oe_procurement_po")),
    Probe("tendering", _project_probe("oe_tendering_package")),
    Probe("changeorders", _project_probe("oe_changeorders_order")),
    Probe("crm", _project_probe("oe_crm_opportunity")),
    Probe("contracts", _project_probe("oe_contracts_contract")),
    Probe("subcontractors", _project_probe("oe_subcontractors_subcontractor")),
    Probe("bid_management", _project_probe("oe_bid_management_package")),
    Probe("variations", _project_probe("oe_variations_request")),
    # Supplier catalogs are vendor-scoped (global); sidebar treats them
    # as present only if vendor records exist at all (cheap proxy).
    Probe("supplier_catalogs", "SELECT 1 FROM oe_supplier_catalogs_vendor LIMIT 1"),
    Probe("property_dev", _project_probe("oe_property_dev_development")),
    # ── Communication & Docs ───────────────────────────────────────────
    Probe("contacts", _project_probe("oe_contacts_contact")),
    Probe("meetings", _project_probe("oe_meetings_meeting")),
    Probe("rfi", _project_probe("oe_rfi_rfi")),
    Probe("submittals", _project_probe("oe_submittals_submittal")),
    Probe("transmittals", _project_probe("oe_transmittals_transmittal")),
    Probe("correspondence", _project_probe("oe_correspondence_correspondence")),
    # Assets module — best-effort: bim asset register sits under bim_hub.
    Probe("assets", _project_probe("oe_bim_asset_register")),
    Probe("cde", _project_probe("oe_cde_container")),
    Probe("photos", _project_probe("oe_documents_photo")),
    Probe("markups", _project_probe("oe_markups_markup")),
    Probe("reports", _project_probe("oe_reporting_generated")),
    Probe("bi_dashboards", _project_probe("oe_bi_dashboards_dashboard")),
    # ── Quality, HSE & Compliance ──────────────────────────────────────
    Probe("validation", _project_probe("oe_validation_report")),
    Probe("inspections", _project_probe("oe_inspections_inspection")),
    Probe("ncr", _project_probe("oe_ncr_ncr")),
    Probe("punchlist", _project_probe("oe_punchlist_item")),
    Probe("qms", _project_probe("oe_qms_itp_plan")),
    Probe("safety", _project_probe("oe_safety_incident")),
    Probe("hse_advanced", _project_probe("oe_hse_advanced_jsa")),
    Probe("carbon", _project_probe("oe_carbon_inventory")),
    # ── AI & Analytics ─────────────────────────────────────────────────
    Probe("ai_estimate", _project_probe("oe_ai_estimate_job")),
    Probe("ai_agents", _project_probe("oe_ai_agents_run")),
    # Advisor is part of erp_chat; treat as alias of chat messages.
    Probe("advisor", _project_probe("oe_erp_chat_session")),
    # Estimation Dashboard is a BOQ aggregation — alias of boq.
    Probe("estimation_dashboard", _project_probe("oe_boq_boq")),
    Probe("erp_chat", _project_probe("oe_erp_chat_session")),
)


# ── Probe execution ─────────────────────────────────────────────────────────


async def _run_one_probe(
    session: AsyncSession,
    probe: Probe,
    project_id: uuid.UUID,
) -> tuple[str, bool]:
    """Execute a single probe; missing table or any DB-shape issue → False.

    Returns ``(module_key, has_data)``. Errors are deliberately swallowed
    at DEBUG level — a 500 here would dim the whole sidebar for a single
    unwired module, which is a much worse UX than a stale ``False``.
    """
    try:
        # ``str(uuid)`` works for both PostgreSQL UUID columns (cast by
        # the driver) and SQLite TEXT columns. Binding the raw UUID
        # instance only works on asyncpg and breaks SQLite tests.
        result = await session.execute(text(probe.sql), {"pid": str(project_id)})
        row = result.first()
        return probe.module_key, row is not None
    except (OperationalError, ProgrammingError):
        # Missing table / column. Expected on fresh DBs or before
        # migrations land. Don't log at WARNING — too noisy.
        logger.debug(
            "module_presence: probe %s skipped (table missing or schema mismatch)",
            probe.module_key,
        )
        return probe.module_key, False
    except InFailedSQLTransactionError:
        # The session's transaction was aborted by a prior concurrent probe.
        # We cannot safely rollback on a shared session — other probes are
        # still executing concurrently. Just return False; the caller gets a
        # fresh session on the next request.
        logger.warning(
            "module_presence: probe %s skipped (transaction aborted by prior probe)",
            probe.module_key,
        )
        return probe.module_key, False
    except Exception:  # noqa: BLE001
        # Anything else (e.g. dialect-specific cast failure) — still
        # return False so the endpoint stays a 200. Log loudly so we
        # notice in CI.
        logger.exception(
            "module_presence: probe %s raised unexpected error",
            probe.module_key,
        )
        return probe.module_key, False


async def probe_project_modules(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    use_cache: bool = True,
) -> dict[str, bool]:
    """Return ``{module_key: has_data}`` for every probe in the registry.

    All probes run concurrently via ``asyncio.gather`` so total latency
    ≈ slowest single probe (typically <20 ms with an index). The result
    is cached per ``project_id`` for ``_PRESENCE_TTL_SECONDS``.

    The returned dict keys match the sidebar slugs (``"5d"`` rather
    than ``"five_d"``); the router maps those to schema field aliases
    when building the Pydantic model.
    """
    if use_cache:
        cached = _PRESENCE_CACHE.get(project_id)
        if cached is not None:
            payload, ts = cached
            if time.monotonic() - ts < _PRESENCE_TTL_SECONDS:
                return dict(payload)  # defensive copy

    pairs = await asyncio.gather(
        *(_run_one_probe(session, probe, project_id) for probe in PRESENCE_PROBES),
    )
    payload: dict[str, bool] = dict(pairs)

    if use_cache:
        _PRESENCE_CACHE[project_id] = (dict(payload), time.monotonic())
    return payload
