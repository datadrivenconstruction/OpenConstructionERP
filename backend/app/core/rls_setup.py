# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Idempotent PostgreSQL setup for row-level-security enforcement.

Runs from the startup auto-migrator when ``settings.rls_enforce`` is on, inside
its advisory-locked transaction, so exactly one worker provisions it and a role
without DDL rights simply skips (best-effort per statement). It:

1. creates the non-superuser runtime role ``oe_app`` (request transactions
   ``SET LOCAL ROLE`` to it, so policies apply) and the ``oe_system`` BYPASSRLS
   role for background work, and grants them read/write on all current and
   future tables in ``public``;
2. enables row-level security and installs a tenant-isolation policy on every
   table that carries a ``tenant_id`` column.

The policy is deliberately non-breaking for a first rollout:

    USING / WITH CHECK: tenant_id IS NULL OR tenant_id::text = current_setting('app.current_tenant', true)

so a tenant can never read or write another tenant's rows, while rows with a
NULL ``tenant_id`` (legacy/system rows, and the many columns still nullable
because the app-layer tenant scope is only partly rolled out) stay shared and
inserts that do not yet set ``tenant_id`` keep working. Tightening to a strict
``tenant_id = current_setting(...)`` after a backfill is a later step.

Global reference tables (cost items, catalogs, regional indices) carry no
``tenant_id`` and so are never selected; a defensive deny-set backstops that.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.rls import APP_ROLE, GUC_NAME, SYSTEM_ROLE, rls_enabled

logger = logging.getLogger(__name__)

# Advisory-lock key that serialises RLS provisioning across workers / replicas
# on a shared external database, so only one runs the idempotent DDL. Distinct
# from the schema-heal key in ``postgres_migrator`` (826340271) so the two
# never contend. Arbitrary but must stay constant across releases.
_RLS_ADVISORY_LOCK_KEY = 826340272

# Name of the isolation policy created on each tenant table. Stable so the
# catalog guard (pg_policies) recognises an already-provisioned table.
_POLICY_NAME = "oe_tenant_isolation"

# The tenant-scoping column. Only tables that declare it are policied.
_TENANT_COLUMN = "tenant_id"

# Global reference data that must never be tenant-filtered even if it somehow
# grew a ``tenant_id`` column - filtering it would break every tenant. These
# have no tenant_id today, so this is belt-and-braces.
_NEVER_POLICY: frozenset[str] = frozenset(
    {
        "oe_costs_item",
        "oe_costs_catalog",
        "oe_regional_indices",
        "oe_catalog_resource",
        "oe_cost_item_usage",
        "oe_cost_item_resource",
    }
)


def _role_setup_statements() -> list[str]:
    """Idempotent DDL that creates and grants the RLS roles."""
    return [
        # Roles: CREATE ROLE has no IF NOT EXISTS, so guard on the catalog.
        # NOLOGIN - they are reached via SET ROLE, never a direct connection.
        f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE "{APP_ROLE}" NOSUPERUSER NOINHERIT NOLOGIN;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SYSTEM_ROLE}') THEN
                CREATE ROLE "{SYSTEM_ROLE}" NOSUPERUSER NOINHERIT NOLOGIN BYPASSRLS;
              END IF;
            END $$;""",
        # Let whoever the app connects as (embedded: superuser postgres;
        # external: the app role) SET ROLE to these. A superuser already can,
        # so this only matters for a non-superuser external app role.
        f"""DO $$ BEGIN
              EXECUTE format('GRANT "{APP_ROLE}", "{SYSTEM_ROLE}" TO %I', CURRENT_USER);
            EXCEPTION WHEN OTHERS THEN NULL;
            END $$;""",
        f'GRANT USAGE ON SCHEMA public TO "{APP_ROLE}", "{SYSTEM_ROLE}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{APP_ROLE}", "{SYSTEM_ROLE}"',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{APP_ROLE}", "{SYSTEM_ROLE}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{APP_ROLE}", "{SYSTEM_ROLE}"',  # noqa: E501
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{APP_ROLE}", "{SYSTEM_ROLE}"',  # noqa: E501
    ]


def _policy_statements(table_name: str) -> list[str]:
    """Idempotent DDL that enables RLS and installs the policy on one table."""
    quoted = f'"{table_name}"'
    # Cast the tenant column to text before comparing to the GUC. current_setting
    # always returns text, so a text-family tenant_id (the GUID type renders as
    # varchar(36) today) compares directly - but a native-uuid or otherwise
    # non-text tenant_id would raise "operator does not exist: uuid = text" and
    # 500 every read. ``::text`` keeps the predicate correct for any column type.
    predicate = f"({_TENANT_COLUMN} IS NULL OR {_TENANT_COLUMN}::text = current_setting('{GUC_NAME}', true))"
    return [
        f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY",
        # FORCE so the policy also binds the table owner. A superuser still
        # bypasses (that is the off-switch), but a non-owner like oe_app is
        # bound by ENABLE alone; FORCE is defence in depth.
        f"ALTER TABLE {quoted} FORCE ROW LEVEL SECURITY",
        f"""DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = '{table_name}' AND policyname = '{_POLICY_NAME}'
              ) THEN
                CREATE POLICY "{_POLICY_NAME}" ON {quoted}
                  USING {predicate}
                  WITH CHECK {predicate};
              END IF;
            END $$;""",
    ]


def tenant_tables(base) -> list[str]:  # noqa: ANN001 - declarative Base
    """Names of tables that carry a ``tenant_id`` column and may be policied."""
    names: list[str] = []
    for table in base.metadata.sorted_tables:
        if table.name in _NEVER_POLICY:
            continue
        if _TENANT_COLUMN in table.columns:
            names.append(table.name)
    return names


async def _run_best_effort(conn: AsyncConnection, statements: list[str], *, what: str) -> int:
    """Execute each statement in its own SAVEPOINT; count the successes.

    A single failure (missing privilege, a race) rolls back only its own nested
    transaction and is logged, so the rest of the provisioning still applies.
    """
    applied = 0
    for sql in statements:
        try:
            async with conn.begin_nested():
                await conn.execute(text(sql))
            applied += 1
        except Exception as exc:  # noqa: BLE001 - never abort the heal
            logger.warning("RLS %s statement skipped: %s", what, exc)
    return applied


async def apply_rls(conn: AsyncConnection, base) -> dict[str, int]:  # noqa: ANN001 - Base
    """Provision RLS roles + per-table policies. No-op unless the flag is on.

    Called from :func:`app.core.postgres_migrator.postgres_auto_migrate` inside
    its advisory-locked transaction. Every statement is idempotent and wrapped
    in a SAVEPOINT, so re-running on each boot is safe and one failure never
    poisons the rest.
    """
    if not rls_enabled():
        return {"roles": 0, "tables": 0}

    roles_applied = await _run_best_effort(conn, _role_setup_statements(), what="role")

    tables = tenant_tables(base)
    tables_done = 0
    for name in tables:
        applied = await _run_best_effort(conn, _policy_statements(name), what=f"policy {name}")
        if applied:
            tables_done += 1

    logger.info(
        "RLS enforcement provisioned: %d role statements, %d/%d tenant tables policied",
        roles_applied,
        tables_done,
        len(tables),
    )
    return {"roles": roles_applied, "tables": tables_done}


async def provision_rls(engine: AsyncEngine, base) -> dict[str, int]:  # noqa: ANN001 - Base
    """Provision RLS in its own advisory-locked transaction. Call after startup.

    Runs *after* ``Base.metadata.create_all`` so every tenant table exists
    (whether the database is fresh or upgraded), takes a transaction-scoped
    advisory lock so exactly one worker provisions on a shared external
    database, and bounds each DDL with ``lock_timeout`` so it never stalls live
    traffic. A no-op that never opens a transaction while the flag is off.

    Wrapped by the caller (``main`` lifespan / ``cli init-db``) so a role
    without DDL rights, or any other failure, only logs and never breaks boot.
    """
    if not rls_enabled():
        return {"roles": 0, "tables": 0}

    async with engine.begin() as conn:
        got_lock = (
            await conn.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"),
                {"k": _RLS_ADVISORY_LOCK_KEY},
            )
        ).scalar()
        if not got_lock:
            logger.info("RLS provisioning: another worker holds the lock - skipping")
            return {"roles": 0, "tables": 0}

        # Never stall live traffic: cap how long any policy/grant DDL waits for
        # its lock. A busy table simply defers to the next boot.
        await conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        return await apply_rls(conn, base)


async def verify_rls_role(engine: AsyncEngine) -> bool:
    """Warn loudly at startup if enforcement is on but ``oe_app`` is unusable.

    When the flag is on, every request transaction issues ``SET LOCAL ROLE
    "oe_app"`` (see :func:`app.core.rls.install`). If that role was never
    created - the common case being an external PostgreSQL whose app login lacks
    CREATEROLE, so :func:`provision_rls` could not create it and its best-effort
    SAVEPOINT swallowed the failure - every request then fails with a 500. This
    surfaces that misconfiguration at boot with an unmistakable error instead of
    leaving it to the first request.

    Never raises: a misconfigured flag must not by itself crash startup, so any
    failure only logs. A no-op that returns ``False`` while the flag is off.

    Returns True only when the role exists *and* is assumable by the connecting
    user; False otherwise (including the flag-off no-op).
    """
    if not rls_enabled():
        return False
    try:
        async with engine.begin() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                    {"r": APP_ROLE},
                )
            ).scalar()
            if not exists:
                logger.error(
                    "RLS ENFORCEMENT IS ON (rls_enforce=true) BUT ROLE %r DOES NOT EXIST. "
                    "provision_rls could not create it - the database login most likely lacks "
                    "CREATEROLE (common on managed/external PostgreSQL). Every request will "
                    "fail with 500 on 'SET LOCAL ROLE \"%s\"'. Create the role and grant it to "
                    "the app login, or turn rls_enforce off.",
                    APP_ROLE,
                    APP_ROLE,
                )
                return False
            # Existing in the catalog is not enough: the connecting user must be
            # able to assume it (provision_rls grants it to CURRENT_USER, but that
            # grant is best-effort too). Prove it in this throwaway transaction;
            # SET LOCAL ROLE resets on commit, so nothing leaks to the pool.
            await conn.execute(text(f'SET LOCAL ROLE "{APP_ROLE}"'))
        logger.info("RLS enforcement: runtime role %r present and assumable", APP_ROLE)
        return True
    except Exception as exc:  # noqa: BLE001 - a boot check must never crash boot
        logger.error(
            "RLS enforcement is ON but runtime role %r could not be verified: %s. "
            "Requests may fail with 500 until the role exists and is granted to the app "
            "login. Create it manually or turn rls_enforce off.",
            APP_ROLE,
            exc,
        )
        return False
