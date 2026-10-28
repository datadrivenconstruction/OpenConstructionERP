# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the EAC semantic validator (EAC-1.3 §2).

Covers the FR-1.10 semantic checks the JSON Schema cannot express:

* Reference existence (``alias_id`` resolves; ``${project.var}`` resolves)
* Standard variable allowlist (``${Volume}``, ``${Length}``, ...)
* ``between`` / ``not_between``: ``min <= max``
* Regex pattern ReDoS heuristic
* Local-variable cyclic dependencies
"""

from __future__ import annotations

import uuid

import pytest

# simpleeval (the sandboxed formula evaluator) is not declared in pyproject and
# is not a transitive of any base/dev dependency, so a [dev]-only install (the
# CI test job) does not have it. The eac validator imports safe_eval at module
# top, which imports simpleeval, so guard the whole module so it skips cleanly
# instead of erroring during collection.
pytest.importorskip("simpleeval", reason="simpleeval is not in the [dev] install")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.eac.models  # noqa: F401 — register tables
from app.modules.eac.engine.validator import ValidatorIssue, validate_rule
from app.modules.eac.models import EacGlobalVariable, EacParameterAlias
from app.modules.eac.schemas import EacRuleDefinition
from tests._pg import transactional_session

# ── Fixture: PostgreSQL session (rolled back per test) with a seeded alias ──


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # Runs against the shared schema-loaded ``oe_test_unit`` database inside an
    # outer transaction that is rolled back on teardown, so each test starts
    # from an empty database. PostgreSQL enforces foreign keys natively.
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def seeded_alias(session: AsyncSession) -> EacParameterAlias:
    """Insert a single alias the validator should accept."""
    alias = EacParameterAlias(
        scope="org",
        scope_id=None,
        name="alias_thickness",
        value_type_hint="number",
        default_unit="mm",
        version=1,
        is_built_in=True,
        tenant_id=None,
    )
    session.add(alias)
    await session.flush()
    return alias


def _rule(body: dict) -> EacRuleDefinition:
    return EacRuleDefinition.model_validate(body)


# ── 1. Existing alias passes ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validator_passes_on_existing_alias(session: AsyncSession, seeded_alias: EacParameterAlias) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "ok",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {
                    "kind": "alias",
                    "alias_id": str(seeded_alias.id),
                },
                "constraint": {"operator": "exists"},
            },
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid, f"unexpected issues: {result.issues}"
    assert result.issues == []


# ── 2. Unknown alias_id fails ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_validator_fails_on_unknown_alias_id(session: AsyncSession) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "bad_alias",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {
                    "kind": "alias",
                    "alias_id": "alias_does_not_exist_xyz",
                },
                "constraint": {"operator": "exists"},
            },
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = [i.code for i in result.issues]
    assert "alias_not_found" in codes


# ── 3. Unknown global variable fails ────────────────────────────────────


@pytest.mark.asyncio
async def test_validator_fails_on_unknown_global_var(session: AsyncSession) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "missing_global",
            "output_mode": "aggregate",
            "result_unit": "m3",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "formula": "Volume * project.MISSING_VAR",
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = [i.code for i in result.issues]
    assert "global_var_not_found" in codes


# ── 4. Standard variable accepted without alias ─────────────────────────


@pytest.mark.asyncio
async def test_validator_passes_on_standard_var(session: AsyncSession) -> None:
    """``Volume`` is a standard FR-1.7 variable — no alias entry needed."""
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "standard_var",
            "output_mode": "aggregate",
            "result_unit": "m3",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "formula": "Volume * 2",
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid, f"unexpected issues: {result.issues}"


# ── 5. ReDoS regex rejected ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validator_fails_on_redos_regex(session: AsyncSession) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "redos",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {
                    "kind": "regex",
                    "pset_name": None,
                    "pattern": "(a+)+b",
                    "case_sensitive": False,
                },
                "constraint": {"operator": "exists"},
            },
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = [i.code for i in result.issues]
    assert "redos_regex" in codes


# ── 6. Cyclic local variable rejected ───────────────────────────────────


@pytest.mark.asyncio
async def test_validator_fails_on_cyclic_local_var(session: AsyncSession) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "cyclic",
            "output_mode": "aggregate",
            "result_unit": "m3",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "formula": "a + b",
            "local_variables": [
                {"name": "a", "expression": "b * 2"},
                {"name": "b", "expression": "a + 1"},
            ],
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = [i.code for i in result.issues]
    assert "cyclic_local_var" in codes


# ── 7. between min > max rejected ───────────────────────────────────────


@pytest.mark.asyncio
async def test_validator_fails_on_between_min_greater_than_max(
    session: AsyncSession, seeded_alias: EacParameterAlias
) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "bad_between",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {
                    "kind": "alias",
                    "alias_id": str(seeded_alias.id),
                },
                "constraint": {
                    "operator": "between",
                    "min": 0.5,
                    "max": 0.1,
                    "inclusive": True,
                },
            },
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = [i.code for i in result.issues]
    assert "between_min_greater_than_max" in codes


# ── 8. Multiple problems → multiple issues ──────────────────────────────


@pytest.mark.asyncio
async def test_validator_returns_multiple_issues_at_once(
    session: AsyncSession,
) -> None:
    """A rule with 3 distinct problems must surface 3 issues in one pass.

    The validator does NOT fail-fast — it accumulates so the UI can show
    every blocker the user has to address.
    """
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "many_bugs",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "and",
                "children": [
                    {
                        "kind": "triplet",
                        "attribute": {
                            "kind": "alias",
                            "alias_id": "alias_does_not_exist",
                        },
                        "constraint": {"operator": "exists"},
                    },
                    {
                        "kind": "triplet",
                        "attribute": {
                            "kind": "regex",
                            "pset_name": None,
                            "pattern": "(a*)*b",
                            "case_sensitive": False,
                        },
                        "constraint": {"operator": "exists"},
                    },
                    {
                        "kind": "triplet",
                        "attribute": {"kind": "exact", "name": "X"},
                        "constraint": {
                            "operator": "between",
                            "min": 100,
                            "max": 1,
                            "inclusive": True,
                        },
                    },
                ],
            },
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid is False
    codes = sorted(i.code for i in result.issues)
    # We expect AT LEAST these three. The validator may add more (e.g.
    # global_var checks that pass), but the three deliberate problems
    # must each surface their own code.
    assert "alias_not_found" in codes
    assert "redos_regex" in codes
    assert "between_min_greater_than_max" in codes


# ── Sanity: ValidatorIssue is a frozen dataclass ────────────────────────


def test_validator_issue_is_immutable() -> None:
    """Issues are frozen so callers can't mutate them in flight."""
    issue = ValidatorIssue(
        code="x",
        severity="error",
        path="$",
        message_i18n_key="eac.validator.x",
        context={},
    )
    with pytest.raises(Exception):
        issue.code = "y"  # type: ignore[misc]


# ── Smoke: project-scoped global var resolves ───────────────────────────


@pytest.mark.asyncio
async def test_validator_passes_on_existing_global_var(
    session: AsyncSession,
) -> None:
    """A global variable that exists at org or project scope is accepted."""
    var = EacGlobalVariable(
        scope="org",
        scope_id=uuid.uuid4(),
        name="MAX_THICKNESS",
        value_type="number",
        value_json={"value": 500},
        tenant_id=uuid.uuid4(),
    )
    session.add(var)
    await session.flush()

    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "uses_global",
            "output_mode": "aggregate",
            "result_unit": "m",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "formula": "MIN(Length, org.MAX_THICKNESS)",
        }
    )
    result = await validate_rule(rule, session=session)
    assert result.valid, f"unexpected issues: {result.issues}"
