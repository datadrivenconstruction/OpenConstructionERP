# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Project module-presence probe.

A lightweight scanner that answers: *"does project X have any data in
module Y?"* - one boolean per sidebar module. The frontend uses the
answers to dim empty modules in the sidebar so users see, at a glance,
which surfaces actually carry data for the project they are looking at.

Design constraints
~~~~~~~~~~~~~~~~~~

* **Cheap probes only.** Each module check is a single
  ``SELECT 1 FROM <table> WHERE project_id = :pid LIMIT 1`` - no
  ``COUNT(*)``, no joins. Index hit per row, O(1) per probe.
* **Sequential + isolated.** Probes run one-by-one (an ``AsyncSession`` is not
  concurrency-safe); each rolls back on failure so one bad probe can't abort the
  shared PostgreSQL transaction and cascade the rest into false negatives.
* **Defensive.** A missing table (fresh DB, alembic not yet run) yields
  ``False`` - never a 500. ``OperationalError`` / ``ProgrammingError``
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

import logging
import time
import uuid
from typing import NamedTuple

from sqlalchemy import exc as _sa_exc
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

# InFailedSQLTransactionError was only added in SQLAlchemy 2.0. On older
# releases fall back to the broader DBAPIError under the same name, so the
# except clause further down still resolves and compiles either way.
InFailedSQLTransactionError = getattr(_sa_exc, "InFailedSQLTransactionError", DBAPIError)

logger = logging.getLogger(__name__)


# ── Cache ───────────────────────────────────────────────────────────────────

_PRESENCE_TTL_SECONDS: float = 60.0
_PRESENCE_CACHE: dict[uuid.UUID, tuple[dict[str, bool], float]] = {}


def invalidate_presence_cache(project_id: uuid.UUID | None = None) -> None:
    """Drop cache for one project (or every project when ``None``).

    Called by mutation hooks if/when we wire them in - for now the
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
                    (rendered as ``str(uuid)`` by the executor - works
                    for both PostgreSQL UUID and SQLite TEXT columns).
                    When the scope is ``"company"`` the SQL has no
                    ``:pid`` bind - it asks "does this register hold any
                    row at all?" - so the executor binds ``:pid`` only
                    when the statement references it.
        scope:      How presence is decided for this module:

                    * ``"project"`` (default) - project-scoped table; the
                      module is present only when the active project has a
                      linked row. Dims when the project is empty.
                    * ``"company"`` - company-wide register (master tables
                      such as the subcontractor directory, contacts, the
                      supplier catalogue) that has no ``project_id`` column.
                      Presence must NOT depend on the active project; it is
                      present whenever the register holds any row. Never dim
                      one of these just because the current project has no
                      linked rows.
                    * ``"hybrid"`` - rows may exist before being tied to a
                      project (e.g. CRM opportunities, whose ``project_id``
                      is nullable). Present when there is a project-linked
                      row OR a global/unlinked (``project_id IS NULL``) row.
    """

    module_key: str
    sql: str
    scope: str = "project"


def _project_probe(table: str, *, column: str = "project_id") -> str:
    """Build a standard ``SELECT 1 ... LIMIT 1`` probe on a project column."""
    return f"SELECT 1 FROM {table} WHERE {column} = :pid LIMIT 1"  # noqa: S608


def _company_probe(table: str) -> str:
    """Build a company-wide ``SELECT 1 ... LIMIT 1`` probe (no project filter).

    For master/register tables that have no ``project_id`` column. Presence
    means "the register holds at least one row", independent of any project.
    """
    return f"SELECT 1 FROM {table} LIMIT 1"  # noqa: S608


def _hybrid_probe(table: str, *, column: str = "project_id") -> str:
    """Build a probe that is true for a project-linked OR a global row.

    Used for tables whose ``project_id`` is nullable: a row counts as
    present when it is linked to this project, or when it is global
    (``project_id IS NULL``) and therefore visible regardless of the
    active project. One indexed ``SELECT 1 ... LIMIT 1`` either way.
    """
    return f"SELECT 1 FROM {table} WHERE {column} = :pid OR {column} IS NULL LIMIT 1"  # noqa: S608


# The order here is informational only - probes run concurrently. Keys
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
        "SELECT 1 FROM oe_smart_view WHERE scope_type = 'project' AND scope_id = :pid LIMIT 1",
    ),
    Probe("bim_requirements", _project_probe("oe_bim_requirement_set")),
    Probe("bcf", _project_probe("oe_bcf_topic")),
    # ── Planning & Field ───────────────────────────────────────────────
    Probe("schedule", _project_probe("oe_schedule_schedule")),
    Probe("tasks", _project_probe("oe_tasks_task")),
    # 5D = BOQ × Schedule combined; sidebar lights it up only when
    # the schedule has activities (BOQ alone is a 2D check).
    # Schedule activities link to a project via their parent Schedule, not
    # directly - so probe the project-scoped ``oe_schedule_schedule`` table.
    # (Probing oe_schedule_activity.project_id raised "column does not exist" on
    # PostgreSQL, which aborted the shared probe transaction and cascaded every
    # subsequent probe to a false negative - dimming unrelated sidebar modules.)
    Probe("5d", _project_probe("oe_schedule_schedule")),
    Probe("risk", _project_probe("oe_risk_register")),
    Probe("field_reports", _project_probe("oe_fieldreports_report")),
    Probe("daily_diary", _project_probe("oe_daily_diary_diary")),
    # The fleet register (``oe_equipment_equipment``) is company-wide and has NO
    # ``project_id`` column, and the Equipment page lists the whole fleet rather
    # than a project slice. The old ``project_id = :pid`` probe raised "column
    # does not exist" on every sweep, was swallowed, and read False forever -
    # the same shape as the subcontractor directory below (issue #228).
    Probe("equipment", _company_probe("oe_equipment_equipment"), scope="company"),
    Probe("resources", _project_probe("oe_resources_assignment")),
    # Service tickets hang off a contract and carry no ``project_id`` of their
    # own; the contract is what links the work to a project, and that link is
    # nullable because a company-wide service contract exists before it is
    # struck against a delivery project. Probe the contract, project-linked OR
    # global, like CRM below. The old ticket probe raised "column does not
    # exist" and dimmed Service on every install.
    Probe("service", _hybrid_probe("oe_service_contract"), scope="hybrid"),
    # No portal table carries a ``project_id``: access rules are per portal user
    # and per arbitrary resource. The portal register is its user list, which is
    # what the Portal page opens on, so presence is company-wide "has the portal
    # any invited user at all".
    Probe("portal", _company_probe("oe_portal_user"), scope="company"),
    # ── Commercial ─────────────────────────────────────────────────────
    Probe("finance", _project_probe("oe_finance_invoice")),
    Probe("procurement", _project_probe("oe_procurement_po")),
    Probe("tendering", _project_probe("oe_tendering_package")),
    Probe("changeorders", _project_probe("oe_changeorders_order")),
    # CRM opportunities are hybrid: a deal can exist as a global/unlinked
    # lead (``project_id IS NULL``) before it is ever tied to a delivery
    # project. Probing only ``project_id = :pid`` dimmed CRM for any project
    # that had no linked deals even though the pipeline held opportunities,
    # so probe project-linked OR global rows (issue #228).
    Probe("crm", _hybrid_probe("oe_crm_opportunity"), scope="hybrid"),
    Probe("contracts", _project_probe("oe_contracts_contract")),
    # The subcontractor directory (``oe_subcontractors_subcontractor``) is a
    # company-wide master register with NO ``project_id`` column. The old
    # ``project_id = :pid`` probe raised "column does not exist", was
    # swallowed, and always read False - dimming the directory even when it
    # held vendors (issue #228). Probe company-wide presence instead.
    Probe(
        "subcontractors",
        _company_probe("oe_subcontractors_subcontractor"),
        scope="company",
    ),
    Probe("bid_management", _project_probe("oe_bid_management_package")),
    # A project has variations activity if it has either a variation request or
    # an executed variation order (demo data seeds orders), so probe both.
    Probe(
        "variations",
        "SELECT 1 FROM oe_variations_order WHERE project_id = :pid "
        "UNION ALL SELECT 1 FROM oe_variations_request WHERE project_id = :pid LIMIT 1",  # noqa: S608
    ),
    # Supplier catalogs are vendor-scoped (company-wide); sidebar treats
    # them as present if any vendor record exists at all (cheap proxy).
    Probe(
        "supplier_catalogs",
        _company_probe("oe_supplier_catalogs_vendor"),
        scope="company",
    ),
    Probe("property_dev", _project_probe("oe_property_dev_development")),
    # ── Communication & Docs ───────────────────────────────────────────
    # Contacts are an org-wide address book (the table has no project_id), so
    # probe company-wide presence like supplier_catalogs rather than per-project.
    Probe("contacts", _company_probe("oe_contacts_contact"), scope="company"),
    Probe("meetings", _project_probe("oe_meetings_meeting")),
    Probe("rfi", _project_probe("oe_rfi_rfi")),
    Probe("submittals", _project_probe("oe_submittals_submittal")),
    Probe("transmittals", _project_probe("oe_transmittals_transmittal")),
    Probe("correspondence", _project_probe("oe_correspondence_correspondence")),
    # The asset register is a view over BIM elements flagged
    # ``is_tracked_asset``, not a table of its own - ``oe_bim_asset_register``
    # never existed, so this probe raised "relation does not exist" on every
    # sweep. Elements reach a project through their model, hence the subquery;
    # both sides are indexed and it is still one ``SELECT 1 ... LIMIT 1``.
    Probe(
        "assets",
        "SELECT 1 FROM oe_bim_element WHERE is_tracked_asset "
        "AND model_id IN (SELECT id FROM oe_bim_model WHERE project_id = :pid) LIMIT 1",  # noqa: S608
    ),
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
    Probe("closeout", _project_probe("oe_closeout_package")),
    Probe("qms", _project_probe("oe_qms_itp_plan")),
    Probe("safety", _project_probe("oe_safety_incident")),
    Probe("hse_advanced", _project_probe("oe_hse_advanced_jsa")),
    Probe("carbon", _project_probe("oe_carbon_inventory")),
    # ── AI & Analytics ─────────────────────────────────────────────────
    Probe("ai_estimate", _project_probe("oe_ai_estimate_job")),
    Probe("ai_agents", _project_probe("oe_ai_agents_run")),
    # Advisor is part of erp_chat; treat as alias of chat messages.
    Probe("advisor", _project_probe("oe_erp_chat_session")),
    # Estimation Dashboard is a BOQ aggregation - alias of boq.
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

    Returns ``(module_key, has_data)``. On PostgreSQL a failed statement aborts
    the *whole* transaction, so a single probe against a table that lacks a
    ``project_id`` column (or doesn't exist yet) would otherwise cascade every
    later probe into ``InFailedSQLTransactionError`` and dim half the sidebar.
    To prevent that we roll the (read-only) session back to a clean state on any
    error - safe because the caller now runs probes sequentially, not on a shared
    concurrent session. Errors stay swallowed: a 500 here would dim the whole
    sidebar for one unwired module, a much worse UX than a stale ``False``.
    """
    try:
        # ``str(uuid)`` works for both PostgreSQL UUID columns (cast by
        # the driver) and SQLite TEXT columns. Binding the raw UUID
        # instance only works on asyncpg and breaks SQLite tests.
        # Company-wide probes have no ``:pid`` bind, so only supply the
        # parameter when the statement actually references it.
        params = {"pid": str(project_id)} if ":pid" in probe.sql else {}
        result = await session.execute(text(probe.sql), params)
        row = result.first()
        return probe.module_key, row is not None
    except (OperationalError, ProgrammingError):
        # Missing table / column. Expected on fresh DBs or before
        # migrations land. Don't log at WARNING - too noisy.
        await _safe_rollback(session)
        logger.debug(
            "module_presence: probe %s skipped (table missing or schema mismatch)",
            probe.module_key,
        )
        return probe.module_key, False
    except InFailedSQLTransactionError:  # aborted txn from an earlier probe
        # The transaction is already poisoned; roll it back so the remaining
        # probes can keep running.
        await _safe_rollback(session)
        logger.debug("module_presence: probe %s skipped (transaction was aborted)", probe.module_key)
        return (probe.module_key, False)
    except Exception:  # noqa: BLE001
        # Anything else (e.g. dialect-specific cast failure) - still
        # return False so the endpoint stays a 200. Log loudly so we
        # notice in CI.
        await _safe_rollback(session)
        logger.exception(
            "module_presence: probe %s raised unexpected error",
            probe.module_key,
        )
        return probe.module_key, False


async def _safe_rollback(session: AsyncSession) -> None:
    """Roll back an aborted (read-only) probe transaction so the next probe runs."""
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001
        pass


async def probe_project_modules(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    use_cache: bool = True,
) -> dict[str, bool]:
    """Return ``{module_key: has_data}`` for every probe in the registry.

    Probes run **sequentially** (not via ``asyncio.gather``): an ``AsyncSession``
    is not safe for concurrent operations, and on PostgreSQL one failing probe
    aborts the shared transaction and would cascade the rest into false
    negatives. ``_run_one_probe`` rolls back on error so a bad probe can't poison
    its neighbours. Each probe is a fast indexed ``SELECT 1 ... LIMIT 1`` and the
    whole result is cached per ``project_id`` for ``_PRESENCE_TTL_SECONDS``, so
    the sequential cost is paid at most once a minute.

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

    payload: dict[str, bool] = {}
    for probe in PRESENCE_PROBES:
        key, has_data = await _run_one_probe(session, probe, project_id)
        payload[key] = has_data

    if use_cache:
        _PRESENCE_CACHE[project_id] = (dict(payload), time.monotonic())
    return payload
