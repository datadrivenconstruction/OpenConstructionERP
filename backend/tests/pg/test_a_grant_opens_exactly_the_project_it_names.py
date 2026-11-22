# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A grant opens exactly the project it names, in the database, as the restricted role.

ADR 006, stage 3, the database arm. The application arm is
``test_a_grant_is_one_of_two_layers_and_both_have_to_answer_yes.py``; this file is
about what PostgreSQL does, which is the part that decides whether participation
is a property of the platform or of every query somebody remembers to write.

The predicate is two permissive policies on one table rather than one rewritten
policy, because permissive policies are OR'd. That has three consequences and all
three are asserted here:

* the tenant policy this product has always installed keeps its name, its
  predicate and its ``IS NULL`` discriminator, so ``policy_is_strict`` still reads
  a mode off a deparsed ``qual`` without learning a third shape, and an install
  that never sets ``OE_PROJECT_GRANTS`` provisions byte-identical SQL;
* the grant arm is ``FOR SELECT`` only. ``WITH CHECK`` expressions are OR'd too,
  so a grant arm on writes would let a grantee insert a row carrying the *owner's*
  tenant into a project it was invited to read. Reads widen; writes stay on the
  tenant arm, which is how a grantee's rows carry the grantee's own tenant and
  stay the grantee's afterwards (owner decision 3);
* turning the flag off is a real rollback. ``CREATE POLICY`` is guarded on
  ``pg_policies`` and never replaces an installed policy, so a grant arm would
  otherwise survive the operator turning ``OE_PROJECT_GRANTS`` back off and keep
  widening reads. The drop is asserted, not assumed.

Everything runs against the lane's embedded PostgreSQL 16 on probe tables, through
the repository's own ``apply_rls``, and every observation records ``current_user``
and ``rolsuper``: the cluster's session user is the ``postgres`` superuser, and a
superuser bypasses every policy without a word, so a test that did not prove it
ran as the restricted role would pass just as happily with no policy installed at
all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core import rls_setup
from app.core.rls import APP_ROLE, GRANTED_GUC_NAME
from tests.pg import rls_fixtures as rls

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

_LABELS = f'SELECT label FROM "{rls.PROBE_PROJECT}" ORDER BY label'

#: What B sees in its own right: its own rows wherever they are, plus the
#: unowned legacy row the permissive tenant arm leaves visible to everybody. The
#: legacy row is in every expectation below on purpose - it is the arm this file
#: must not change, and an expectation that quietly dropped it would hide a
#: regression in the one predicate that was already shipped.
_OWN_ROWS = {"beta in alpha", "beta in beta", rls.UNOWNED_LABEL}


@pytest.fixture(autouse=True)
def _enforcement_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """``apply_rls`` is a no-op unless enforcement is on."""
    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: True)


@pytest_asyncio.fixture
async def grant_probe(pg_engine):  # noqa: ANN001, ANN201 - the lane's async engine fixture
    """Two project-scoped probe tables and one tenant-only table, all policied.

    The tenant-only table is in the same provisioning call to show the grant arm
    lands where a project exists and nowhere else: a table with a ``tenant_id``
    and no ``project_id`` has nothing a grant could name.

    The rows are the four that matter. Alpha owns ``PROJECT_ALPHA``; beta wrote a
    row into it, which is what a grantee does; both companies have a row in
    ``PROJECT_BETA``, which nobody was granted; and one row has no tenant at all,
    which is what a legacy record looks like under the permissive arm.
    """
    base = rls.project_probe_base(rls.PROBE_PROJECT, rls.PROBE_PROJECT_SECOND)
    tenant_only = rls.probe_base(rls.PROBE_SECOND)
    async with pg_engine.begin() as conn:
        await rls.drop_probe_tables(conn, rls.PROBE_PROJECT, rls.PROBE_PROJECT_SECOND, rls.PROBE_SECOND)
        await rls.ensure_roles(conn)
        await rls.create_project_probe_tables(conn, rls.PROBE_PROJECT, rls.PROBE_PROJECT_SECOND)
        await rls.create_probe_tables(conn, rls.PROBE_SECOND)
        for table in (rls.PROBE_PROJECT, rls.PROBE_PROJECT_SECOND):
            await rls.seed_project(conn, table, ("a-p-1", rls.TENANT_A, rls.PROJECT_ALPHA, "alpha in alpha"))
            await rls.seed_project(conn, table, ("b-p-1", rls.TENANT_B, rls.PROJECT_ALPHA, "beta in alpha"))
            await rls.seed_project(conn, table, ("a-q-1", rls.TENANT_A, rls.PROJECT_BETA, "alpha in beta"))
            await rls.seed_project(conn, table, ("b-q-1", rls.TENANT_B, rls.PROJECT_BETA, "beta in beta"))
            await rls.seed_project(conn, table, ("legacy-p", None, rls.PROJECT_ALPHA, rls.UNOWNED_LABEL))
        await rls.seed(conn, rls.PROBE_SECOND, ("s-b", rls.TENANT_B, "second beta"))
        stats = await rls_setup.apply_rls(conn, base, strict=False, grants=True)
        await rls_setup.apply_rls(conn, tenant_only, strict=False, grants=True)

    try:
        yield SimpleNamespace(engine=pg_engine, base=base, tenant_only=tenant_only, stats=stats)
    finally:
        async with pg_engine.begin() as conn:
            await rls_setup.apply_rls(conn, base, strict=False, grants=False)
            await rls.drop_probe_tables(conn, rls.PROBE_PROJECT, rls.PROBE_PROJECT_SECOND, rls.PROBE_SECOND)


def _labels(outcome: rls.RoleOutcome) -> set[str]:
    """The labels a read returned, after asserting which role produced it."""
    assert outcome.error is None, outcome.error
    assert outcome.rolsuper is False, f"a superuser bypasses every policy: {outcome.current_user}"
    assert outcome.current_user == APP_ROLE, outcome.current_user
    assert outcome.session_user != APP_ROLE, "SET LOCAL ROLE did not take effect"
    assert outcome.rows is not None
    return {row[0] for row in outcome.rows}


# ── what provisioning installed ─────────────────────────────────────────────


async def test_the_grant_arm_is_a_second_policy_and_the_tenant_arm_is_untouched(grant_probe) -> None:  # noqa: ANN001
    """Two policies, one predicate each, and the older one exactly as it was."""
    assert grant_probe.stats["grant_tables"] == 2, grant_probe.stats

    async with grant_probe.engine.connect() as conn:
        tenant_arm = await rls.installed_policy(conn, rls.PROBE_PROJECT)
        grant_arm = await rls.installed_grant_policy(conn, rls.PROBE_PROJECT)

    assert tenant_arm["installed"] is True
    assert tenant_arm["is_strict"] is False, "the tenant arm kept its permissive shape"
    assert "IS NULL" in (tenant_arm["qual"] or "").upper()
    assert GRANTED_GUC_NAME not in (tenant_arm["qual"] or ""), "the grant arm was not folded into the tenant arm"
    assert tenant_arm["rls_enabled"] is True and tenant_arm["forced"] is True

    assert grant_arm["installed"] is True
    assert grant_arm["policy_name"] == "oe_project_grant_read"
    # FOR SELECT is the whole of the write story: WITH CHECK expressions are OR'd
    # as well as USING ones, so a grant arm on writes would let a grantee insert a
    # row carrying the owner's tenant into a project it was invited to read.
    assert grant_arm["cmd"] == "SELECT"
    assert "project_id" in (grant_arm["qual"] or "")
    assert GRANTED_GUC_NAME in (grant_arm["qual"] or "")
    assert "tenant_id" not in (grant_arm["qual"] or ""), "the grant arm matches a project, not a tenant"


async def test_the_grant_arm_lands_on_a_project_table_and_not_on_a_tenant_only_one(grant_probe) -> None:  # noqa: ANN001
    """A table with a tenant and no project has nothing a grant could name."""
    async with grant_probe.engine.connect() as conn:
        widened = await rls.installed_grant_policy(conn, rls.PROBE_PROJECT)
        second = await rls.installed_grant_policy(conn, rls.PROBE_PROJECT_SECOND)
        tenant_only = await rls.installed_grant_policy(conn, rls.PROBE_SECOND)
        tenant_arm = await rls.installed_policy(conn, rls.PROBE_SECOND)

    assert widened["installed"] is True
    assert second["installed"] is True, "per table, not once for the database"
    assert tenant_only["installed"] is False
    assert tenant_arm["installed"] is True, "the tenant-only table is still policied by the arm it always had"


# ── what a grantee reads ────────────────────────────────────────────────────


async def test_a_grantee_reads_exactly_the_project_it_was_invited_to_and_nothing_beside_it(grant_probe) -> None:  # noqa: ANN001
    """The whole claim, in one set comparison.

    Beta holds a grant on ``PROJECT_ALPHA`` and reads the owner's row there. It
    does not read the owner's row in ``PROJECT_BETA``, which is the "and nothing
    else" half: a predicate that widened to every project of the owner's company
    would return it, and a predicate implemented as a join against the grant table
    without the project arm would return nothing at all.
    """
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        _LABELS,
        fetch=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )

    assert _labels(outcome) == _OWN_ROWS | {"alpha in alpha"}


async def test_the_same_grant_on_a_second_table_widens_it_too(grant_probe) -> None:  # noqa: ANN001
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        f'SELECT label FROM "{rls.PROBE_PROJECT_SECOND}" ORDER BY label',
        fetch=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )

    assert _labels(outcome) == _OWN_ROWS | {"alpha in alpha"}


async def test_without_the_grant_the_owners_row_is_not_there(grant_probe) -> None:  # noqa: ANN001
    """An empty grant list, and the owner's row disappears.

    Same caller, same table, same rows, one GUC different. This is the pair with
    the test above: together they say the grant is what opened the row and not
    something else about beta's session.
    """
    outcome = await rls.as_app_role(grant_probe.engine, rls.TENANT_B, _LABELS, fetch=True, granted_projects=[])

    assert _labels(outcome) == _OWN_ROWS


async def test_a_company_that_was_never_granted_anything_sees_none_of_the_owners_rows(grant_probe) -> None:  # noqa: ANN001
    """A third company, granted nothing, on a table where it owns nothing."""
    outcome = await rls.as_app_role(
        grant_probe.engine,
        "tenant-gamma-probe",
        _LABELS,
        fetch=True,
        granted_projects=[],
    )

    assert _labels(outcome) == {rls.UNOWNED_LABEL}


async def test_an_unset_grant_guc_and_an_empty_one_match_the_same_nothing(grant_probe) -> None:  # noqa: ANN001
    """Both fail closed, and they fail closed identically.

    ``string_to_array`` over an empty setting yields one empty element rather than
    an empty array, and an empty element matches no project id; an unset GUC read
    with ``current_setting(..., true)`` yields NULL, and ``= ANY (NULL)`` is NULL,
    which a ``USING`` clause treats as false. Two different mechanisms, one
    answer, and the answer is the safe one - so a transaction that never bound
    the second GUC cannot read projects nobody granted it.
    """
    unset = await rls.as_app_role(grant_probe.engine, rls.TENANT_B, _LABELS, fetch=True)
    empty = await rls.as_app_role(grant_probe.engine, rls.TENANT_B, _LABELS, fetch=True, granted_projects=[])

    assert _labels(unset) == _OWN_ROWS
    assert unset.rows == empty.rows


async def test_a_grant_names_a_project_and_not_a_tenant(grant_probe) -> None:  # noqa: ANN001
    """Binding the owner's *tenant* id in the grant GUC opens nothing.

    The two ids are different values and ADR 005 exists because they were once
    confused. A grant arm that matched a tenant would hand a partner company the
    owner's whole estate rather than one project, so the arm is asserted to be
    keyed on the project even when it is fed something else.
    """
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        _LABELS,
        fetch=True,
        granted_projects=[rls.TENANT_A],
    )

    assert _labels(outcome) == _OWN_ROWS


# ── what a grantee writes ───────────────────────────────────────────────────


async def test_a_grantee_writes_rows_it_owns_into_the_project_it_was_invited_to(grant_probe) -> None:  # noqa: ANN001
    """A grant is a read authority that does not stop the grantee working.

    The row carries beta's own tenant, which is what makes it beta's afterwards
    and what keeps the owner from reading it back through the project arm once
    the grant is withdrawn. Committed, so what is asserted next is what the
    database kept.
    """
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        "INSERT INTO "
        f'"{rls.PROBE_PROJECT}" (id, tenant_id, project_id, label) '
        f"VALUES ('b-p-2', '{rls.TENANT_B}', '{rls.PROJECT_ALPHA}', 'beta wrote under a grant')",
        commit=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )

    assert outcome.error is None, outcome.error
    assert outcome.rolsuper is False and outcome.current_user == APP_ROLE
    assert outcome.rowcount == 1
    kept = await rls.admin_rows(
        grant_probe.engine,
        f'SELECT tenant_id, project_id FROM "{rls.PROBE_PROJECT}" WHERE id = :i',
        {"i": "b-p-2"},
    )
    assert kept == [(rls.TENANT_B, rls.PROJECT_ALPHA)], kept


async def test_a_grant_does_not_let_a_grantee_write_a_row_carrying_the_owners_tenant(grant_probe) -> None:  # noqa: ANN001
    """The write half of "a grantee writes only rows it owns".

    Beta holds a live grant on ``PROJECT_ALPHA`` and tries to insert a row there
    stamped with alpha's tenant. The grant policy is ``FOR SELECT``, so it
    contributes nothing to ``WITH CHECK``, and the tenant policy refuses it: a
    row claiming to be alpha's can only be written by alpha. A grant arm on
    writes would have allowed this, which is why the policy's command is asserted
    in the catalog as well as its effect being asserted here.
    """
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        "INSERT INTO "
        f'"{rls.PROBE_PROJECT}" (id, tenant_id, project_id, label) '
        f"VALUES ('forged', '{rls.TENANT_A}', '{rls.PROJECT_ALPHA}', 'forged as the owner')",
        commit=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )

    assert outcome.rolsuper is False and outcome.current_user == APP_ROLE
    assert outcome.error is not None, "the insert was accepted"
    assert "row-level security" in outcome.error.lower() or "WITH CHECK" in outcome.error, outcome.error
    kept = await rls.admin_rows(
        grant_probe.engine, f'SELECT id FROM "{rls.PROBE_PROJECT}" WHERE id = :i', {"i": "forged"}
    )
    assert kept == [], kept


async def test_a_grant_does_not_let_a_grantee_rewrite_the_owners_row(grant_probe) -> None:  # noqa: ANN001
    """Reading the owner's row is the grant; changing it is not."""
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        f"UPDATE \"{rls.PROBE_PROJECT}\" SET label = 'taken by the grantee' WHERE id = 'a-p-1'",
        commit=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )

    assert outcome.rolsuper is False and outcome.current_user == APP_ROLE
    assert outcome.error is None, outcome.error
    assert outcome.rowcount == 0, "the owner's row was reachable for an update"
    kept = await rls.admin_rows(
        grant_probe.engine,
        f'SELECT label FROM "{rls.PROBE_PROJECT}" WHERE id = :i',
        {"i": "a-p-1"},
    )
    assert kept == [("alpha in alpha",)], kept


# ── turning it off ──────────────────────────────────────────────────────────


async def test_turning_the_flag_off_removes_the_grant_arm_and_leaves_the_tenant_arm(grant_probe) -> None:  # noqa: ANN001
    """A rollback, not a no-op.

    ``CREATE POLICY`` is guarded on ``pg_policies`` and never replaces an
    installed policy, so without the drop a grant arm would survive an operator
    turning ``OE_PROJECT_GRANTS`` back off and keep widening reads after the
    rollback - the same trap the strict-mode transition is written to avoid.
    """
    async with grant_probe.engine.begin() as conn:
        stats = await rls_setup.apply_rls(conn, grant_probe.base, strict=False, grants=False)
    assert stats["grant_tables"] == 0, stats

    async with grant_probe.engine.connect() as conn:
        grant_arm = await rls.installed_grant_policy(conn, rls.PROBE_PROJECT)
        tenant_arm = await rls.installed_policy(conn, rls.PROBE_PROJECT)
    assert grant_arm["installed"] is False
    assert tenant_arm["installed"] is True
    assert tenant_arm["is_strict"] is False

    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        _LABELS,
        fetch=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )
    assert _labels(outcome) == _OWN_ROWS, "the owner's row is gone with the policy that let it through"

    # And provisioning again puts it back, so the flag is a switch and not a
    # one-way door.
    async with grant_probe.engine.begin() as conn:
        await rls_setup.apply_rls(conn, grant_probe.base, strict=False, grants=True)
    again = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        _LABELS,
        fetch=True,
        granted_projects=[rls.PROJECT_ALPHA],
    )
    assert _labels(again) == _OWN_ROWS | {"alpha in alpha"}


async def test_the_system_role_is_not_bound_by_either_arm(grant_probe) -> None:  # noqa: ANN001
    """``BYPASSRLS`` is the platform's own escape hatch and this file did not close it.

    Asserted because a second policy is a second thing for that role to bypass,
    and a background job that suddenly saw fewer rows would be a silent,
    platform-wide failure rather than a refusal anybody could read.
    """
    outcome = await rls.as_app_role(
        grant_probe.engine,
        rls.TENANT_B,
        _LABELS,
        fetch=True,
        role=rls.SYSTEM_ROLE,
        granted_projects=[],
    )

    assert outcome.error is None, outcome.error
    assert outcome.current_user == rls.SYSTEM_ROLE
    assert outcome.rolsuper is False
    assert {row[0] for row in outcome.rows or []} == {
        "alpha in alpha",
        "alpha in beta",
        "beta in alpha",
        "beta in beta",
        rls.UNOWNED_LABEL,
    }


async def test_the_grant_guc_is_read_with_a_missing_setting_tolerated(grant_probe) -> None:  # noqa: ANN001
    """``current_setting(..., true)`` and not the two-argument-less form.

    Without the ``true`` a transaction that never set the GUC raises
    "unrecognized configuration parameter" instead of returning nothing, which
    would turn every read on a table with the grant arm into a 500 for any caller
    that reached it without going through the request dependency - a background
    job, a repair, a test with a bare session.
    """
    async with grant_probe.engine.connect() as conn:
        await conn.execute(text(f'SET LOCAL ROLE "{APP_ROLE}"'))
        # Only the tenant GUC is bound; the grant GUC is never set in this
        # transaction.
        await conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": rls.GUC_NAME, "v": rls.TENANT_B})
        result = await conn.execute(text(_LABELS))
        labels = {row[0] for row in result.fetchall()}
        await conn.rollback()

    assert labels == _OWN_ROWS
