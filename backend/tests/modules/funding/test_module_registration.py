# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The module is discovered, mountable, and registers what it says it does.

A module that fails to import drops out of the registry silently rather than
raising, so "it is in the folder" is not evidence that it loads. The same is
true one layer down: a permission nobody registered denies nothing, and a rule
set nobody registered validates nothing, and neither says a word about it.
"""

from __future__ import annotations

from app.core.module_loader import ModuleLoader
from app.core.permissions import Role, permission_registry
from app.core.validation.engine import rule_registry
from app.database import Base
from app.modules.funding import manifest as module_manifest
from app.modules.funding import on_startup, router
from app.modules.funding.models import (
    FundingApplication,
    FundingCostAllocation,
    FundingDisbursement,
    FundingObligation,
    FundingProgramme,
    FundingProofOfUse,
)
from app.modules.funding.validators import FUNDING_RULE_SET, FUNDING_RULES

EXPECTED_PERMISSIONS = {
    "funding.read": Role.VIEWER,
    "funding.create": Role.EDITOR,
    "funding.update": Role.EDITOR,
    "funding.delete": Role.MANAGER,
    "funding.manage_programmes": Role.MANAGER,
    "funding.submit_application": Role.EDITOR,
    "funding.record_award": Role.MANAGER,
    "funding.request_disbursement": Role.EDITOR,
    "funding.confirm_receipt": Role.MANAGER,
    "funding.submit_proof_of_use": Role.EDITOR,
    "funding.close_application": Role.MANAGER,
}

TABLES = [
    FundingProgramme,
    FundingApplication,
    FundingDisbursement,
    FundingProofOfUse,
    FundingObligation,
    FundingCostAllocation,
]


def test_the_loader_discovers_the_module() -> None:
    found = {module.name: module for module in ModuleLoader().discover()}
    assert "oe_funding" in found
    discovered = found["oe_funding"]
    assert discovered.display_name == module_manifest.manifest.display_name
    assert discovered.auto_install is True


def test_the_manifest_declares_the_modules_it_actually_uses() -> None:
    """Projects and users, because every route is project-scoped and permissioned."""
    assert set(module_manifest.manifest.depends) == {"oe_users", "oe_projects"}


def test_the_router_mounts_the_four_entry_points_the_page_calls() -> None:
    paths = {getattr(route, "path", "") for route in router.router.routes}
    assert "/programmes/" in paths
    assert "/applications/" in paths
    assert "/obligations/" in paths
    assert "/projects/{project_id}/summary" in paths


def test_recording_an_award_is_its_own_endpoint_and_not_a_field_update() -> None:
    """It sets the amount, the period and the conditions, and derives every deadline."""
    paths = {getattr(route, "path", "") for route in router.router.routes}
    assert "/applications/{application_id}/award" in paths
    assert "/disbursements/{disbursement_id}/receipt" in paths
    assert "/proofs/{proof_id}/accept" in paths


def test_all_six_tables_are_registered_on_the_shared_metadata() -> None:
    for model in TABLES:
        assert model.__tablename__ in Base.metadata.tables, model.__name__


def test_the_table_names_follow_the_modules_convention() -> None:
    for model in TABLES:
        assert model.__tablename__.startswith("oe_funding_"), model.__name__
    assert len({model.__tablename__ for model in TABLES}) == len(TABLES)


def test_every_relationship_says_how_it_loads() -> None:
    """An unannotated relationship is a lazy load waiting to happen.

    On an async session a lazy load does not fetch, it raises MissingGreenlet
    at whatever point somebody first reads the attribute, which is usually a
    route that worked in review and fails in production.
    """
    from sqlalchemy import inspect

    for model in TABLES:
        for relationship in inspect(model).relationships:
            assert relationship.lazy in ("raise_on_sql", "selectin"), (
                f"{model.__name__}.{relationship.key} loads as {relationship.lazy!r}"
            )


def test_every_child_repository_sorts_by_a_column_its_model_has() -> None:
    """The sort key is a string, so nothing else would catch a typo in it.

    It has to be a string: a mapped column assigned to a plain class is a
    descriptor, and reading it back off the repository instance makes
    SQLAlchemy treat the repository as a row and raise UnmappedInstanceError
    when the query runs. Holding the name is safe and this test replaces the
    spelling check that holding the column used to give for free.
    """
    from sqlalchemy import inspect

    from app.modules.funding.repository import (
        CostAllocationRepository,
        DisbursementRepository,
        ObligationRepository,
        ProofOfUseRepository,
    )

    repositories = [
        DisbursementRepository,
        ProofOfUseRepository,
        ObligationRepository,
        CostAllocationRepository,
    ]
    for repository in repositories:
        columns = {column.key for column in inspect(repository.model).columns}
        assert repository.order_by_column in columns, (
            f"{repository.__name__} sorts by {repository.order_by_column!r}, "
            f"which {repository.model.__name__} does not have"
        )
        # Reading the resolved attribute off an instance is what used to
        # fail, so the test does exactly that rather than checking the name
        # alone.
        assert repository(None).order_by is not None  # type: ignore[arg-type]


async def test_startup_registers_the_permissions_and_the_rule_set() -> None:
    await on_startup()

    granted = permission_registry.list_all()
    for permission, role in EXPECTED_PERMISSIONS.items():
        assert granted.get(permission) == role, permission

    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([FUNDING_RULE_SET])}
    assert registered == {rule_class().rule_id for rule_class in FUNDING_RULES}


async def test_startup_is_idempotent() -> None:
    """The loader may call it again after a module is toggled off and on."""
    await on_startup()
    await on_startup()
    registered = [rule.rule_id for rule in rule_registry.get_rules_for_sets([FUNDING_RULE_SET])]
    assert len(registered) == len(set(registered)) == len(FUNDING_RULES)


def test_the_award_decision_sits_above_ordinary_editing() -> None:
    """Recording somebody else's decision is not the same right as filling in a form."""
    assert EXPECTED_PERMISSIONS["funding.record_award"] == Role.MANAGER
    assert EXPECTED_PERMISSIONS["funding.confirm_receipt"] == Role.MANAGER
    assert EXPECTED_PERMISSIONS["funding.manage_programmes"] == Role.MANAGER
    assert EXPECTED_PERMISSIONS["funding.submit_application"] == Role.EDITOR
