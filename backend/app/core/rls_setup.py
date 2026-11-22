# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Idempotent PostgreSQL setup for row-level-security enforcement.

Runs from the startup auto-migrator when ``settings.rls_enforce`` is on, inside
its advisory-locked transaction, so workers provision it one at a time and a role
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

import asyncio
import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import get_settings
from app.core.rls import APP_ROLE, GRANTED_GUC_NAME, GUC_NAME, SYSTEM_ROLE, rls_enabled

logger = logging.getLogger(__name__)

# Advisory-lock key that serialises RLS provisioning across workers / replicas
# on a shared external database, so they run the idempotent DDL one at a time. Distinct
# from the schema-heal key in ``postgres_migrator`` (826340271) so the two
# never contend. Arbitrary but must stay constant across releases.
_RLS_ADVISORY_LOCK_KEY = 826340272

# How long a worker that finds the provisioning lock taken waits for its holder,
# and how often it asks. Same bound as the schema heal in ``postgres_migrator``.
_RLS_LOCK_WAIT_SECONDS = 60.0
_RLS_LOCK_POLL_SECONDS = 0.5

# Name of the isolation policy created on each tenant table. Stable so the
# catalog guard (pg_policies) recognises an already-provisioned table.
_POLICY_NAME = "oe_tenant_isolation"

# The tenant-scoping column. Only tables that declare it are policied.
_TENANT_COLUMN = "tenant_id"

# The project-scoping column. A table carrying both is one a grant can widen,
# because the grant arm has a project to match against; a table with a tenant and
# no project has nothing a grant could name.
_PROJECT_COLUMN = "project_id"

# Name of the second policy, the grant arm (ADR 006). A different name from
# ``_POLICY_NAME`` and not a replacement for it: permissive policies on one table
# are OR'd, so installing a second one *adds* an arm to the predicate instead of
# rewriting the arm that is already there. The tenant policy this file has always
# installed keeps its name, its predicate and its ``IS NULL`` discriminator, which
# is what lets :func:`policy_is_strict` keep reading a mode off a deparsed qual
# without learning a third shape.
_GRANT_POLICY_NAME = "oe_project_grant_read"

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


def permissive_predicate() -> str:
    """The rollout predicate: tenant-owned rows are scoped, NULL rows stay shared.

    Cast the tenant column to text before comparing to the GUC. current_setting
    always returns text, so a text-family tenant_id (the GUID type renders as
    varchar(36) today) compares directly - but a native-uuid or otherwise
    non-text tenant_id would raise "operator does not exist: uuid = text" and
    500 every read. ``::text`` keeps the predicate correct for any column type.

    The ``IS NULL`` arm is what makes a first rollout non-breaking: legacy and
    system rows, and the columns still nullable because the app-layer tenant
    scope is only partly rolled out, stay visible to every caller. It is also
    the reason this mode is not the end state - a row whose ``tenant_id`` was
    never set is readable and writable by every tenant on the install.
    :func:`rls_readiness_report` counts exactly those rows as ``null_tenant_rows``.
    """
    return f"({_TENANT_COLUMN} IS NULL OR {_TENANT_COLUMN}::text = current_setting('{GUC_NAME}', true))"


def strict_predicate() -> str:
    """The enforced predicate: only the bound tenant's rows are reachable.

    Same ``::text`` reasoning as :func:`permissive_predicate`, without the
    ``IS NULL`` escape. Two consequences, both intended:

    * a row whose ``tenant_id`` is NULL belongs to nobody and is hidden from
      everybody, so an ownership backfill has to happen before this is safe;
    * an anonymous request binds an empty GUC, ``current_setting`` returns the
      empty string, and no row matches - the policy fails closed rather than
      widening to "all rows".

    Provisioning this predicate is refused unless the readiness report is clean,
    because applying it to a database that still holds NULL-tenant rows would
    hide live business data from its own owners.
    """
    return f"({_TENANT_COLUMN}::text = current_setting('{GUC_NAME}', true))"


def grant_read_predicate() -> str:
    """The grant arm: rows of a project the caller's company was invited to.

    Reads the second GUC, which the ``after_begin`` listener in
    :mod:`app.core.rls` stamps beside ``app.current_tenant`` with the ids of the
    projects the caller's organization holds a live grant on. ``string_to_array``
    over an empty setting yields one empty element rather than an empty array, and
    an empty element matches no ``project_id``, so a caller with no grants reaches
    nothing through this arm - it fails closed the same way the tenant arm does
    for an anonymous caller.

    Cast to text for the reason :func:`permissive_predicate` casts: a native-uuid
    column compared against ``current_setting`` raises "operator does not exist"
    and 500s every read, and the cast keeps the predicate correct for any column
    type.

    ``ANY`` over an array rather than a correlated ``EXISTS`` against the grant
    table, which the ADR rejected and the million-row measurement beside this
    module is what settles: the array is built once per request and the planner
    turns the predicate into a hash semi-join against a value it already has,
    while ``EXISTS`` re-plans a lookup per candidate row.
    """
    return f"({_PROJECT_COLUMN}::text = ANY (string_to_array(current_setting('{GRANTED_GUC_NAME}', true), ',')))"


def both_column_tables(base) -> list[str]:  # noqa: ANN001 - declarative Base
    """Tables a grant can widen: a ``tenant_id`` and a ``project_id``.

    Intersected with :func:`tenant_tables` rather than recomputed, so the two
    lists can never disagree about which tables carry a tenant, and the defensive
    deny-set applies to both arms.
    """
    names: list[str] = []
    for table in base.metadata.sorted_tables:
        if table.name in _NEVER_POLICY:
            continue
        if _TENANT_COLUMN in table.columns and _PROJECT_COLUMN in table.columns:
            names.append(table.name)
    return names


def _grant_policy_statements(table_name: str) -> list[str]:
    """Idempotent DDL that installs the grant arm on one both-column table.

    ``FOR SELECT`` and not ``FOR ALL``, which is the whole of the write story:
    permissive ``WITH CHECK`` expressions are OR'd too, so a grant arm on writes
    would let a grantee insert a row carrying the *owner's* ``tenant_id`` into a
    project it was merely invited to. Restricting this policy to reads leaves
    inserts, updates and deletes governed by the tenant policy alone, so a
    grantee writes rows carrying its own tenant and those rows stay its own
    afterwards - owner decision 3, enforced by the database rather than by
    every call site remembering it.

    No ``ENABLE``/``FORCE`` here: the tenant policy already ran both on this
    table, and running them again would be a second statement whose only effect
    is to make the provisioning log harder to read.
    """
    quoted = f'"{table_name}"'
    return [
        f"""DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = '{table_name}' AND policyname = '{_GRANT_POLICY_NAME}'
              ) THEN
                CREATE POLICY "{_GRANT_POLICY_NAME}" ON {quoted}
                  FOR SELECT
                  USING {grant_read_predicate()};
              END IF;
            END $$;""",
    ]


def policy_is_strict(qual: str | None) -> bool | None:
    """Read the mode of an installed policy from its deparsed ``pg_policies.qual``.

    ``True`` for a strict predicate, ``False`` for the permissive one, ``None``
    when the expression is absent or is not recognisable as either. ``None``
    means "do not touch it": a policy this code cannot classify may have been
    written by an administrator or by another release, and guessing its mode in
    order to drop it is how live data gets hidden or exposed.

    The discriminator is the ``IS NULL`` arm, which only the permissive
    predicate has. PostgreSQL deparses the expression rather than storing the
    text that created it, so comparing against the emitted SQL string would be
    brittle; the presence of the arm is stable across deparsing.
    """
    if not qual or not isinstance(qual, str):
        return None
    upper = qual.upper()
    if "IS NULL" in upper:
        return False
    if _TENANT_COLUMN.upper() in upper and GUC_NAME.upper() in upper:
        return True
    return None


def _policy_statements(table_name: str, *, strict: bool = False) -> list[str]:
    """Idempotent DDL that enables RLS and installs the policy on one table.

    ``strict=False`` (the default) emits byte-identically what it always has, so
    an install that never sets ``OE_RLS_STRICT`` provisions exactly the same SQL
    it did before this parameter existed.

    The ``CREATE POLICY`` is guarded on ``pg_policies`` and therefore never
    replaces a policy that is already installed. Switching mode is handled by
    :func:`apply_rls`, which drops a policy whose installed mode differs from
    the requested one before these statements run - so the guard here stays a
    pure no-op check and the mode transition is explicit rather than something
    this function has to guess at.
    """
    quoted = f'"{table_name}"'
    predicate = strict_predicate() if strict else permissive_predicate()
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


async def _installed_policy_modes(conn: AsyncConnection) -> dict[str, bool]:
    """Map tenant table -> installed policy strictness, best effort.

    One set-based catalog read rather than one query per table. Any failure - a
    login without catalog rights, a non-PostgreSQL dialect, or a unit-test
    connection that implements only ``execute`` - yields an empty map, which
    means "nothing is known, so change nothing". Reconciling the mode is an
    addition on top of the guarded ``CREATE POLICY``, never a precondition for
    provisioning, so an unreadable catalog must not stop RLS being applied.
    """
    try:
        rows = (
            await conn.execute(
                text("SELECT tablename, qual FROM pg_policies WHERE schemaname = 'public' AND policyname = :p"),
                {"p": _POLICY_NAME},
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 - unknown means leave every policy alone
        logger.debug("RLS policy-mode census unavailable: %s", exc)
        return {}

    modes: dict[str, bool] = {}
    for row in rows or []:
        try:
            name, qual = row[0], row[1]
        except (IndexError, KeyError, TypeError):
            continue
        is_strict = policy_is_strict(qual if isinstance(qual, str) else None)
        if is_strict is not None and name:
            modes[str(name)] = is_strict
    return modes


def strict_readiness_verdict(report: dict[str, object]) -> tuple[bool, list[str]]:
    """Whether a readiness report permits provisioning the strict predicate.

    Pure, so the rule can be pinned without a database. Only an explicit
    ``ready_for_strict is True`` is accepted; a report that is missing the key,
    or that carries any blocker at all, refuses and names the blocker codes.

    Failing closed on a report this code does not fully understand is the right
    bias here because the two errors are not symmetric: a wrong "yes" hides live
    business rows from their own owners, while a wrong "no" leaves one more boot
    running the permissive policy that was already in place.
    """
    if report.get("ready_for_strict") is True:
        return True, []
    raw = report.get("blockers") or []
    codes = sorted({str(b.get("code", "unknown")) for b in raw if isinstance(b, dict)})
    return False, codes or ["readiness_unknown"]


async def apply_rls(  # noqa: ANN001 - Base
    conn: AsyncConnection,
    base,
    *,
    strict: bool = False,
    grants: bool = False,
) -> dict[str, int]:
    """Provision RLS roles + per-table policies. No-op unless the flag is on.

    Called from :func:`app.core.postgres_migrator.postgres_auto_migrate` inside
    its advisory-locked transaction. Every statement is idempotent and wrapped
    in a SAVEPOINT, so re-running on each boot is safe and one failure never
    poisons the rest.

    ``strict`` selects the enforced predicate (no ``IS NULL`` escape) over the
    rollout one. It is honoured only when the readiness report is clean; when
    the report names a blocker the request is refused, the refusal is logged and
    returned, and provisioning continues in permissive mode so that asking for
    strict can never leave a database with no policy at all.

    Mode changes are applied in both directions. ``CREATE POLICY`` is guarded on
    ``pg_policies`` and so never replaces an installed policy, which means a
    strict policy would otherwise survive an operator turning ``OE_RLS_STRICT``
    back off and keep hiding NULL-tenant rows after the rollback. A policy whose
    installed mode differs from the requested one is therefore dropped first,
    and the guarded create then installs the requested predicate.
    """
    if not rls_enabled():
        return {"roles": 0, "tables": 0}

    tables = tenant_tables(base)

    effective_strict = strict
    refused: list[str] = []
    if strict:
        ok, codes = strict_readiness_verdict(await rls_readiness_report(conn, tables))
        if not ok:
            effective_strict = False
            refused = codes
            logger.warning(
                "RLS strict policy refused (blockers: %s) - provisioning the permissive "
                "policy instead so no row is hidden from its owner. Resolve the blockers "
                "reported by GET /api/v1/admin/rls/readiness, then boot again.",
                ", ".join(codes),
            )

    roles_applied = await _run_best_effort(conn, _role_setup_statements(), what="role")

    installed = await _installed_policy_modes(conn)
    replaced = 0
    for name in tables:
        known = installed.get(name)
        if known is None or known == effective_strict:
            continue
        replaced += await _run_best_effort(
            conn,
            [f'DROP POLICY IF EXISTS "{_POLICY_NAME}" ON "{name}"'],
            what=f"policy-mode {name}",
        )

    tables_done = 0
    for name in tables:
        applied = await _run_best_effort(conn, _policy_statements(name, strict=effective_strict), what=f"policy {name}")
        if applied:
            tables_done += 1

    granted = await _apply_grant_policies(conn, base, grants=grants)

    logger.info(
        "RLS enforcement provisioned: %d role statements, %d/%d tenant tables policied, mode=%s, "
        "%d policy(ies) replaced, %d grant arm(s)",
        roles_applied,
        tables_done,
        len(tables),
        "strict" if effective_strict else "permissive",
        replaced,
        granted,
    )
    stats: dict[str, int] = {"roles": roles_applied, "tables": tables_done, "policies_replaced": replaced}
    if refused:
        stats["strict_refused"] = len(refused)
    stats["grant_tables"] = granted
    return stats


async def _apply_grant_policies(conn: AsyncConnection, base, *, grants: bool) -> int:  # noqa: ANN001 - Base
    """Install the grant arm where it is wanted and remove it where it is not.

    Removal is the half that matters. ``CREATE POLICY`` here is guarded on
    ``pg_policies`` and so never replaces an installed policy, which means a grant
    arm would otherwise survive an operator turning ``OE_PROJECT_GRANTS`` back off
    and keep widening reads after the rollback - the same trap the strict-mode
    transition is written to avoid. Turning the flag off is therefore a real
    rollback: every grant policy is dropped, and the tenant policy that was never
    touched is still there to answer on its own.

    Returns the number of both-column tables left holding the grant arm, which is
    zero when the flag is off.
    """
    wide = both_column_tables(base)
    if not grants:
        for name in wide:
            await _run_best_effort(
                conn,
                [f'DROP POLICY IF EXISTS "{_GRANT_POLICY_NAME}" ON "{name}"'],
                what=f"grant-policy-rollback {name}",
            )
        return 0
    armed = 0
    for name in wide:
        if await _run_best_effort(conn, _grant_policy_statements(name), what=f"grant-policy {name}"):
            armed += 1
    return armed


def grants_requested() -> bool:
    """Return True when the operator asked for cross-organization participation.

    A separate reader for the same reason :func:`strict_requested` is one: a test
    monkeypatches this exactly as it monkeypatches the enforcement flag, and the
    two flags resolve the same way. Unlike strict, this is not a sub-mode of
    ``rls_enforce`` - the application-layer arm is live with row-level security
    off, which is the state every install is in today - but
    :func:`apply_rls` still returns before consulting it when enforcement is off,
    because with no policies installed there is nothing for a second policy to
    widen.
    """
    return bool(get_settings().project_grants_enforce)


def strict_requested() -> bool:
    """Return True when the operator asked for the strict tenant predicate.

    A separate reader rather than an inline ``get_settings()`` so a test can
    monkeypatch it exactly as it monkeypatches :func:`app.core.rls.rls_enabled`,
    and so the two flags are resolved the same way. Strict is a sub-mode of
    enforcement, not a switch of its own: with ``rls_enforce`` off,
    :func:`apply_rls` returns before this is ever consulted, so ``OE_RLS_STRICT``
    alone changes nothing on a default install.
    """
    return bool(get_settings().rls_strict)


async def provision_rls(engine: AsyncEngine, base) -> dict[str, int]:  # noqa: ANN001 - Base
    """Provision RLS in its own advisory-locked transaction. Call after startup.

    Runs *after* ``Base.metadata.create_all`` so every tenant table exists
    (whether the database is fresh or upgraded), takes a transaction-scoped
    advisory lock so workers on a shared external database provision one at
    a time, and bounds each DDL with ``lock_timeout`` so it never stalls live
    traffic. A no-op that never opens a transaction while the flag is off.

    Provisioning failures are logged by the caller (``main`` startup /
    ``cli init-db``). Server startup separately requires the runtime-role
    preflight to pass; provisioning success alone cannot establish that.
    """
    if not rls_enabled():
        return {"roles": 0, "tables": 0}

    async with engine.begin() as conn:
        # A worker that finds the lock taken waits for the holder and then runs
        # the provisioning itself. It used to skip at once and go straight on to
        # verify_rls_role and to serving requests, both of which assume the
        # holder's roles and policies are committed. On a fresh database that
        # worker logged "role does not exist" for a role the holder was creating
        # in that very moment, and its first requests could fail on
        # ``SET LOCAL ROLE``. Every statement is idempotent, so running after the
        # holder changes nothing it completed and is this worker's own check.
        if not await _take_rls_lock(conn):
            logger.warning(
                "RLS provisioning: another worker held the lock for more than %.0fs - not verified on this worker",
                _RLS_LOCK_WAIT_SECONDS,
            )
            return {"roles": 0, "tables": 0}

        # Never stall live traffic: cap how long any policy/grant DDL waits for
        # its lock. A busy table simply defers to the next boot.
        await conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        return await apply_rls(conn, base, strict=strict_requested(), grants=grants_requested())


async def _take_rls_lock(conn: AsyncConnection) -> bool:
    """Take the provisioning lock, waiting up to ``_RLS_LOCK_WAIT_SECONDS`` for its holder.

    Polls the non-blocking form so the wait is bounded here and not by whatever
    ``lock_timeout`` the role or the database carries.
    """
    deadline = time.monotonic() + _RLS_LOCK_WAIT_SECONDS
    announced = False
    while True:
        got_lock = (
            await conn.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"),
                {"k": _RLS_ADVISORY_LOCK_KEY},
            )
        ).scalar()
        if got_lock:
            return True
        if time.monotonic() >= deadline:
            return False
        if not announced:
            logger.info("RLS provisioning: another worker holds the lock - waiting to verify after it")
            announced = True
        await asyncio.sleep(_RLS_LOCK_POLL_SECONDS)


class RLSConfigurationError(RuntimeError):
    """Explicitly enabled RLS cannot safely assume the request role."""


async def verify_rls_role(engine: AsyncEngine) -> bool:
    """Require an assumable, non-bypassing request role when RLS is enabled.

    Disabled mode returns False without opening a connection. Enabled mode
    raises RLSConfigurationError on any failed check so startup cannot silently
    serve requests with a missing, inaccessible or RLS-bypassing role. This is
    only a role precondition, not proof of policy or tenant coverage.

    The connecting role may still be privileged for migrations/background work;
    this check concerns only oe_app, which request transactions assume.
    """
    if not rls_enabled():
        return False
    try:
        async with engine.begin() as conn:
            role = (
                (
                    await conn.execute(
                        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"),
                        {"r": APP_ROLE},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if role is None:
                raise RLSConfigurationError(
                    f"RLS is enabled but runtime role {APP_ROLE!r} does not exist. "
                    "Provision the request role and grant it to the application login."
                )
            if role["rolsuper"] or role["rolbypassrls"]:
                raise RLSConfigurationError(
                    f"RLS is enabled but runtime role {APP_ROLE!r} has SUPERUSER or BYPASSRLS. "
                    "The request role must have NOSUPERUSER and NOBYPASSRLS; "
                    "existing role attributes require administrator review."
                )
            # Prove membership/SET permissions, not merely catalog presence.
            # SET LOCAL resets on commit; no role change leaks into the pool.
            await conn.execute(text(f'SET LOCAL ROLE "{APP_ROLE}"'))
        logger.info("RLS request role %r is assumable, NOSUPERUSER and NOBYPASSRLS", APP_ROLE)
        return True
    except RLSConfigurationError:
        raise
    except Exception as exc:
        raise RLSConfigurationError(
            f"RLS is enabled but runtime role {APP_ROLE!r} could not be verified or assumed. "
            "Check database connectivity and the application login's permission to SET ROLE."
        ) from exc


# ── Readiness report ─────────────────────────────────────────────────────────
#
# Enforcement stays off. This answers the operator's question "what stops me
# from turning on OE_RLS_ENFORCE with a strict policy?" from the database as
# it is, without changing anything in it.

#: Where the user ids live, so a tenant value can be recognised as one.
_USERS_TABLE = "oe_users_user"


def readiness_blockers(tables: list[dict[str, object]], *, dialect: str, users: int) -> list[dict[str, object]]:
    """What stands between this database and a strict tenant policy.

    Pure, so the rules can be pinned without a database. ``tables`` holds the
    per-table measurements :func:`rls_readiness_report` takes.

    * ``not_postgres``: row-level security exists only in PostgreSQL.
    * ``tenant_is_user``: the tenant values are user ids. The login issues no
      tenant claim, so ``resolve_tenant_id`` falls back to the user id and every
      user is a tenant of their own. Enforcing then hides a colleague's rows from
      everybody else on the same install, which is why this alone blocks it.
    * ``null_tenant_rows``: rows a strict policy would hide from every request.
    """
    if dialect != "postgresql":
        return [{"code": "not_postgres", "dialect": dialect}]
    blockers: list[dict[str, object]] = []
    user_tenant_rows = sum(int(t["rows_with_user_tenant"]) for t in tables)
    if user_tenant_rows:
        blockers.append(
            {
                "code": "tenant_is_user",
                "rows": user_tenant_rows,
                "users": users,
                "tables": sorted(str(t["table"]) for t in tables if t["rows_with_user_tenant"]),
            }
        )
    for table in tables:
        if table["null_tenant_rows"]:
            blockers.append({"code": "null_tenant_rows", "table": table["table"], "rows": table["null_tenant_rows"]})
    return blockers


async def rls_readiness_report(
    conn: AsyncConnection,
    tables: list[str],
    *,
    users_table: str = _USERS_TABLE,
) -> dict[str, object]:
    """Measure every tenant table and say what blocks strict enforcement.

    Read-only. A table missing from this database (a module never installed) is
    skipped rather than failing the report.
    """
    dialect = conn.dialect.name
    report: dict[str, object] = {"enforced": rls_enabled(), "dialect": dialect, "tables": []}
    if dialect != "postgresql":
        report["blockers"] = readiness_blockers([], dialect=dialect, users=0)
        report["ready_for_strict"] = False
        return report

    existing = set(
        (
            await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(:names)"),
                {"names": [*tables, users_table]},
            )
        ).scalars()
    )
    has_users = users_table in existing
    users = (await conn.execute(text(f'SELECT count(*) FROM "{users_table}"'))).scalar_one() if has_users else 0
    user_match = (
        f'count(*) FILTER (WHERE {_TENANT_COLUMN}::text IN (SELECT id::text FROM "{users_table}"))'
        if has_users
        else "0"
    )
    measured: list[dict[str, object]] = []
    unmeasured: list[dict[str, str]] = []
    for name in sorted(t for t in tables if t in existing):
        # One table that cannot be read (a privilege, a column a module renamed)
        # is reported as such instead of turning the whole report into a 500.
        try:
            async with conn.begin_nested():
                row = (
                    (
                        await conn.execute(
                            text(
                                f"SELECT count(*) AS rows, "
                                f"count(*) FILTER (WHERE {_TENANT_COLUMN} IS NULL) AS null_tenant_rows, "
                                f"count(DISTINCT {_TENANT_COLUMN}) AS tenants, "
                                f"{user_match} AS rows_with_user_tenant "
                                f'FROM "{name}"'
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                policy = (
                    (
                        await conn.execute(
                            text(
                                "SELECT c.relrowsecurity AS enabled, "
                                "EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public' "
                                "AND p.tablename = :t AND p.policyname = :p) AS policy "
                                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                "WHERE n.nspname = 'public' AND c.relname = :t"
                            ),
                            {"t": name, "p": _POLICY_NAME},
                        )
                    )
                    .mappings()
                    .one()
                )
                measured.append(
                    {
                        "table": name,
                        "rows": int(row["rows"]),
                        "null_tenant_rows": int(row["null_tenant_rows"]),
                        "tenants": int(row["tenants"]),
                        "rows_with_user_tenant": int(row["rows_with_user_tenant"]),
                        "rls_enabled": bool(policy["enabled"]),
                        "policy_installed": bool(policy["policy"]),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - one table never fails the report
            logger.warning("RLS readiness: could not measure %s: %s", name, exc)
            unmeasured.append({"table": name, "error": type(exc).__name__})
    blockers = readiness_blockers(measured, dialect=dialect, users=int(users))
    blockers += [{"code": "unmeasured_table", **entry} for entry in unmeasured]
    report.update(
        {
            "tables": measured,
            "users": int(users),
            "blockers": blockers,
            "ready_for_strict": not blockers,
        }
    )
    return report
