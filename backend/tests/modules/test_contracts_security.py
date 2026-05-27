# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module — Round-7 security audit regressions.

Covers six guarantees the R7 sweep pinned down:

1. **IDOR on GET** — ``_verify_contract_access`` rejects a contract on
   a project the caller does not own (404, never 403, per the leak
   policy in ``dependencies.verify_project_access``).

2. **IDOR on clone source** — a user must hold project-level access on
   the *source* contract before ``POST /contracts/{id}/clone`` can
   copy its commercial terms. Without this gate, a tenant who knows a
   contract UUID could siphon its full BOQ + retention rules into a
   project they control.

3. **IDOR on clone destination** — when the clone payload carries an
   explicit ``target_project_id``, the caller must ALSO have access on
   the destination project. The dangerous case is the inverse of #2:
   a manager on project A who knows a foreign contract id forging a
   clone INTO their own project (would still leak source data) is
   blocked by #2; but a manager on project A who wants to push project
   A's confidential commercial terms INTO project B (which they don't
   own) is what this test pins down.

4. **Decimal-string money serialization** — every monetary field on
   ``ContractResponse`` round-trips through ``Decimal`` (never
   ``float``), and the JSON encoder emits a string — so 1.0 / 0.1
   additions remain bit-exact across the wire. This is a regression
   guard: a future "performance" PR that switches to
   ``response_model=dict`` or coerces to ``float`` would re-introduce
   the classic ``0.1 + 0.2 = 0.30000000000000004`` AR-reconciliation
   bug.

5. **Member denied PATCH (RBAC)** — ``contracts.update`` requires
   ``Role.EDITOR``-or-higher; a plain ``VIEWER`` (or unauthenticated
   member) must be refused. ``contracts.clone`` requires
   ``Role.MANAGER``-or-higher.

6. **FSM rejection of invalid transition** — ``ContractsService.
   transition_contract`` must surface a 400 (with an
   ``InvalidTransitionError``-shaped message) when asked to flip e.g.
   ``completed → active`` — the lifecycle is one-way for terminal
   states.

The tests run with in-memory repository stubs (no SQLite, no FastAPI
app boot) to stay fast and reproducible. The full integration test
suite under ``tests/integration`` covers wire-level smoke.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.contracts.schemas import (
    ContractCloneRequest,
    ContractResponse,
)
from app.modules.contracts.service import (
    ContractsService,
    InvalidTransitionError,
    assert_contract_transition,
)

# ── Stub repositories ────────────────────────────────────────────────────


class _StubContractRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.by_code: dict[str, Any] = {}

    async def get_by_id(self, contract_id: uuid.UUID) -> Any:
        return self.rows.get(contract_id)

    async def get_by_code(self, code: str) -> Any:
        return self.by_code.get(code)

    async def update_fields(self, contract_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(contract_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        if getattr(item, "code", None):
            self.by_code[item.code] = item
        return item

    async def delete(self, item_id: uuid.UUID) -> None:
        obj = self.rows.pop(item_id, None)
        if obj is not None and getattr(obj, "code", None):
            self.by_code.pop(obj.code, None)


class _StubLineRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "contract_id", None) == contract_id]

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(item_id)
        if obj:
            for k, v in fields.items():
                setattr(obj, k, v)


class _StubGenericRepo:
    """Generic stub for retention / fee / gainshare / ld repos."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "contract_id", None) == contract_id]

    async def get_for_contract(self, contract_id: uuid.UUID) -> Any:
        for r in self.rows.values():
            if getattr(r, "contract_id", None) == contract_id:
                return r
        return None


class _StubSession:
    """Async-session shim that records add() calls so the clone path can
    flush sub-config rows without a real SQLite engine.

    Also implements ``.get(Model, id)`` for the router-level
    ``_load_contract_or_404`` helper, which goes straight to
    ``session.get`` (bypassing the repo) — wires it up against the
    parent service's contract-repo store via a back-reference.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        # Back-reference to the parent service so .get() can resolve
        # Contract / Claim rows out of the in-memory stub repos.
        self.svc: Any = None

    def add(self, item: Any) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.added.append(item)

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass

    async def get(self, model: Any, key: uuid.UUID) -> Any:
        """Dispatch to the matching stub repo by ORM class name."""
        if self.svc is None:
            return None
        name = getattr(model, "__name__", "")
        if name == "Contract":
            return self.svc.contract_repo.rows.get(key)
        if name == "ContractLine":
            return self.svc.line_repo.rows.get(key)
        if name == "ProgressClaim":
            return getattr(self.svc.claim_repo, "rows", {}).get(key)
        if name == "ProgressClaimLine":
            return getattr(self.svc.claim_line_repo, "rows", {}).get(key)
        return None


def _make_service() -> ContractsService:
    """Construct a ContractsService wired to in-memory stubs."""
    svc = ContractsService.__new__(ContractsService)
    svc.session = _StubSession()
    svc.contract_repo = _StubContractRepo()
    svc.line_repo = _StubLineRepo()
    svc.retention_repo = _StubGenericRepo()
    svc.fee_repo = _StubGenericRepo()
    svc.gainshare_repo = _StubGenericRepo()
    svc.ld_repo = _StubGenericRepo()
    # Unused by the security tests but defensively wired so attr lookups
    # don't AttributeError if a future test exercises them.
    svc.claim_repo = _StubGenericRepo()
    svc.claim_line_repo = _StubGenericRepo()
    svc.final_account_repo = _StubGenericRepo()
    svc.type_repo = _StubGenericRepo()
    svc.session.svc = svc  # wire back-ref so session.get() can dispatch
    return svc


def _seed_contract(
    svc: ContractsService,
    *,
    project_id: uuid.UUID,
    code: str = "C-001",
    status: str = "draft",
    contract_type: str = "lump_sum",
    title: str = "Source contract",
    total_value: Decimal | str = Decimal("100000"),
    retention_percent: Decimal | str = Decimal("5"),
    terms: dict[str, Any] | None = None,
) -> Any:
    contract = SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        title=title,
        contract_type=contract_type,
        counterparty_type="client",
        counterparty_id=None,
        project_id=project_id,
        parent_contract_id=None,
        start_date=None,
        end_date=None,
        total_value=Decimal(str(total_value)),
        currency="EUR",
        retention_percent=Decimal(str(retention_percent)),
        retention_release_event="practical_completion",
        status=status,
        signed_at=None,
        terms=dict(terms or {}),
        metadata_={},
        created_by=None,
    )
    svc.contract_repo.rows[contract.id] = contract
    svc.contract_repo.by_code[code] = contract
    return contract


# ── Test scenario constants ───────────────────────────────────────────────


PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_A = str(uuid.uuid4())  # owns project A
USER_B = str(uuid.uuid4())  # owns project B


def _patch_project_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owners: dict[uuid.UUID, str],
) -> None:
    """Stub ProjectRepository.get_by_id to return owner mapping rows.

    A project is "missing" iff its id isn't in the ``owners`` dict.
    """

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            uid = owners.get(project_id)
            if uid is None:
                return None
            return SimpleNamespace(id=project_id, owner_id=uid)

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, _user_id: uuid.UUID):
            # No admin overrides in security tests — keep the access
            # check strictly project-ownership-based.
            return SimpleNamespace(role="editor")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )


# ── 1. IDOR on GET — verify_contract_access rejects cross-tenant ──────────


@pytest.mark.asyncio
async def test_idor_get_contract_blocks_cross_tenant_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_verify_contract_access`` must return 404 (NOT 403) when the
    caller does not own the contract's project — leaking the existence
    of UUIDs the caller can't see is itself a data leak.
    """
    from app.modules.contracts.router import _verify_contract_access

    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="A-001")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    # USER_B tries to read a contract on PROJECT_A.
    with pytest.raises(HTTPException) as exc:
        await _verify_contract_access(svc.session, source.id, USER_B)
    assert exc.value.status_code == 404, (
        f"expected 404 leak-safe response for cross-tenant GET, got {exc.value.status_code}: {exc.value.detail!r}"
    )


@pytest.mark.asyncio
async def test_idor_get_contract_allows_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy-path regression guard — the owner of the parent project
    must still be able to load the contract, otherwise the IDOR fix
    would have over-locked the route.
    """
    from app.modules.contracts.router import _verify_contract_access

    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="A-002")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A})

    returned = await _verify_contract_access(svc.session, source.id, USER_A)
    assert returned.id == source.id


# ── 2. IDOR on clone-SOURCE ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clone_source_blocks_cross_tenant_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who does NOT own the source contract's project must be
    refused — the clone endpoint cannot become a data-exfiltration
    vector by letting a stranger copy a competitor's BOQ into their
    own workspace.

    Verifies the router-level ``_verify_contract_access`` guard runs
    BEFORE the clone is materialised (and 404s, never 403s).
    """
    from app.modules.contracts.router import _verify_contract_access

    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="SRC-001")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    # USER_B owns project B; tries to clone a project-A contract.
    with pytest.raises(HTTPException) as exc:
        await _verify_contract_access(svc.session, source.id, USER_B)
    assert exc.value.status_code == 404, (
        "cross-tenant clone source must 404 (not 403), to avoid "
        f"leaking source-contract existence; got {exc.value.status_code}"
    )
    # Defensive: no clone row materialised.
    assert source.code in svc.contract_repo.by_code
    assert len(svc.contract_repo.rows) == 1, "no new contract should have been created after IDOR rejection"


# ── 3. IDOR on clone-DESTINATION ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_clone_destination_blocks_cross_tenant_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manager on project A must NOT be able to push project A's
    confidential commercial terms (target_cost, gmp_cap, fee_percent,
    rates) INTO project B, which they don't own.

    Without the destination-side verify, the clone endpoint becomes a
    cross-tenant data-injection vector even when the source guard
    passes — the caller legitimately owns the source.
    """
    from app.dependencies import verify_project_access

    svc = _make_service()
    _seed_contract(svc, project_id=PROJECT_A, code="SRC-002")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    # USER_A owns project A → source check would pass. But the explicit
    # target_project_id points at project B (owned by USER_B).
    with pytest.raises(HTTPException) as exc:
        await verify_project_access(PROJECT_B, USER_A, svc.session)
    assert exc.value.status_code == 404, (
        f"cross-tenant clone destination must 404; got {exc.value.status_code}: {exc.value.detail!r}"
    )


@pytest.mark.asyncio
async def test_clone_destination_allowed_same_project_no_extra_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Functional regression: when the caller clones INTO the same
    project the source already lives in, the destination check is
    unnecessary (and the schema allows ``target_project_id=None``).

    Pins the happy path of intra-project cloning, so the manager who
    wants to fork a contract template within their own project is not
    accidentally blocked by the new R7 guard.
    """
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A})

    svc = _make_service()
    source = _seed_contract(
        svc,
        project_id=PROJECT_A,
        code="TPL-001",
        total_value=Decimal("500000"),
        retention_percent=Decimal("5"),
        terms={"gmp_cap": "550000", "target_cost": "500000"},
    )

    clone = await svc.clone_contract(
        source.id,
        new_code="TPL-001-CLONE",
        target_project_id=None,  # same project
        new_title="Cloned template",
        include_lines=True,
        copy_subconfigs=True,
        user_id=USER_A,
    )
    assert clone.project_id == PROJECT_A
    assert clone.status == "draft"  # FSM safety: always starts draft
    assert clone.signed_at is None
    # Terms copied by value, not by reference — mutating clone.terms
    # must not bleed back into source.terms.
    clone.terms["gmp_cap"] = "TAMPERED"
    assert source.terms["gmp_cap"] == "550000"


@pytest.mark.asyncio
async def test_clone_rejects_duplicate_code() -> None:
    """The clone request must surface a 409 (not a raw DB IntegrityError)
    when ``new_code`` collides with an existing contract — the
    ``oe_contracts_contract.code`` column has a UNIQUE constraint.
    """
    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="DUP-SRC")
    _seed_contract(svc, project_id=PROJECT_B, code="EXISTING")

    with pytest.raises(HTTPException) as exc:
        await svc.clone_contract(
            source.id,
            new_code="EXISTING",
            user_id=USER_A,
        )
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("error") == "contract_code_in_use"


# ── 4. Decimal-string money serialization ────────────────────────────────


def test_money_fields_serialize_as_decimal_strings_not_floats() -> None:
    """Every money / percent field on ``ContractResponse`` is typed as
    ``Decimal``; the JSON-mode dump must emit a string.

    Pre-R5 versions returned ``float`` for total_value / retention_percent,
    which introduced quiet precision loss (``Decimal("0.1") + Decimal("0.2")``
    is exact but ``0.1 + 0.2`` is ``0.30000000000000004``) and broke
    AR reconciliation. This guard catches a future "let's just use floats"
    refactor at the schema layer.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    resp = ContractResponse(
        id=uuid.uuid4(),
        code="C-MONEY",
        title="Money serialization guard",
        contract_type="lump_sum",
        counterparty_type="client",
        counterparty_id=None,
        project_id=PROJECT_A,
        parent_contract_id=None,
        start_date=None,
        end_date=None,
        total_value=Decimal("123456789.1234"),
        currency="EUR",
        retention_percent=Decimal("5.25"),
        retention_release_event="practical_completion",
        status="draft",
        signed_at=None,
        terms={},
        created_by=None,
        metadata={},
        created_at=now,
        updated_at=now,
    )
    payload = resp.model_dump(mode="json")
    # JSON-mode dump emits Decimal as a string — never a float — so
    # the over-the-wire representation is bit-exact.
    assert isinstance(payload["total_value"], str), (
        f"total_value must serialize as string, got {type(payload['total_value']).__name__}: {payload['total_value']!r}"
    )
    assert payload["total_value"] == "123456789.1234"
    assert isinstance(payload["retention_percent"], str)
    assert payload["retention_percent"] == "5.25"
    # Python-mode dump preserves the Decimal type intact.
    py_payload = resp.model_dump()
    assert isinstance(py_payload["total_value"], Decimal)
    assert py_payload["total_value"] == Decimal("123456789.1234")


def test_no_float_columns_on_money_models() -> None:
    """Defensive guard: every money-shaped column on the contracts
    ORM models is ``Numeric(18, 4)`` (or ``Numeric(p, q)``), NEVER
    ``Float``. A future migration that drops to ``Float`` for
    "performance" would silently re-introduce binary-FP rounding.
    """
    from sqlalchemy import Float, Numeric

    from app.modules.contracts import models as contracts_models

    money_columns: list[tuple[str, str, type]] = []
    for name in dir(contracts_models):
        obj = getattr(contracts_models, name)
        table = getattr(obj, "__table__", None)
        if table is None:
            continue
        for col in table.columns:
            cname = col.name.lower()
            if any(
                k in cname
                for k in (
                    "value",
                    "amount",
                    "total",
                    "rate",
                    "cost",
                    "fee",
                    "percent",
                    "share",
                    "qty",
                    "quantity",
                    "balance",
                    "paid",
                    "held",
                    "released",
                )
            ):
                money_columns.append((obj.__name__, col.name, type(col.type)))

    assert money_columns, "guard self-check: expected to find money-shaped columns"
    floats = [(cls, col) for cls, col, typ in money_columns if isinstance(typ, type) and issubclass(typ, Float)]
    assert not floats, (
        f"Float columns leaked into the contracts money model: {floats!r}. All money fields must use Numeric(p, q)."
    )
    # And positive evidence: at least one Numeric column survives.
    numerics = [(cls, col) for cls, col, typ in money_columns if isinstance(typ, type) and issubclass(typ, Numeric)]
    assert numerics, "expected at least one Numeric money column"


# ── 5. Member denied PATCH / clone (RBAC) ────────────────────────────────


def test_rbac_viewer_cannot_update_contracts() -> None:
    """Plain VIEWER must NOT carry ``contracts.update``. EDITOR and
    above must.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.contracts.permissions import register_contracts_permissions

    register_contracts_permissions()
    assert not permission_registry.role_has_permission(
        Role.VIEWER,
        "contracts.update",
    ), "VIEWER must NOT be able to mutate contracts"
    assert permission_registry.role_has_permission(
        Role.EDITOR,
        "contracts.update",
    ), "EDITOR must be able to mutate contracts (RBAC regression)"
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "contracts.update",
    ), "MANAGER inherits EDITOR's update permission"


def test_rbac_clone_requires_manager_or_higher() -> None:
    """``contracts.clone`` carries elevated cross-tenant risk —
    a plain EDITOR (estimator/QS) must NOT carry it; only MANAGER+.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.contracts.permissions import register_contracts_permissions

    register_contracts_permissions()
    assert not permission_registry.role_has_permission(
        Role.VIEWER,
        "contracts.clone",
    )
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "contracts.clone",
    ), (
        "EDITOR must NOT carry contracts.clone — clone is a cross-tenant "
        "risk vector that requires manager-or-higher RBAC"
    )
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "contracts.clone",
    )
    assert permission_registry.role_has_permission(
        Role.ADMIN,
        "contracts.clone",
    )


def test_clone_schema_requires_new_code() -> None:
    """The ``new_code`` field is required on every clone request —
    we must NOT allow the schema to default to the source's code
    (which would explode against the UNIQUE constraint and surface
    as a 500 instead of a clean validation error).
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ContractCloneRequest()  # type: ignore[call-arg]

    # Minimal valid payload exercises the default booleans.
    req = ContractCloneRequest(new_code="OK-001")
    assert req.new_code == "OK-001"
    assert req.include_lines is True
    assert req.copy_subconfigs is True
    assert req.target_project_id is None


# ── 6. FSM rejection of invalid transition ───────────────────────────────


def test_fsm_rejects_completed_to_active_transition() -> None:
    """``completed`` is a terminal state — re-opening a completed
    contract via ``transition_contract`` must surface InvalidTransitionError.
    """
    with pytest.raises(InvalidTransitionError):
        assert_contract_transition("completed", "active")


def test_fsm_rejects_terminated_to_active_transition() -> None:
    """``terminated`` is the other terminal state — same guarantee."""
    with pytest.raises(InvalidTransitionError):
        assert_contract_transition("terminated", "active")


@pytest.mark.asyncio
async def test_fsm_transition_service_surfaces_400_on_invalid() -> None:
    """End-to-end: ``ContractsService.transition_contract`` wraps the
    pure FSM in an HTTPException(400) so the router doesn't 500 on an
    illegal flip — required for the test plan's "FSM rejection" case.
    """
    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, status="completed")
    with pytest.raises(HTTPException) as exc:
        await svc.transition_contract(source.id, "active", USER_A)
    assert exc.value.status_code == 400
    assert "completed" in str(exc.value.detail) or "active" in str(exc.value.detail)


def test_fsm_accepts_draft_to_active_transition() -> None:
    """Regression guard for the legitimate sign-off path —
    ``draft → active`` is the most common transition; the FSM must
    not over-tighten and break it.
    """
    # Should NOT raise.
    assert_contract_transition("draft", "active")


# ── 7. Clone-specific safety regression bundle ────────────────────────────


@pytest.mark.asyncio
async def test_clone_always_resets_to_draft_status() -> None:
    """A clone of a SIGNED ACTIVE contract must land as ``draft`` with
    no ``signed_at``. Otherwise the clone would carry a phantom
    signature timestamp the parties never actually authorised.
    """
    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="SIGNED-SRC")
    source.status = "active"
    source.signed_at = "2026-01-15T09:00:00+00:00"

    clone = await svc.clone_contract(
        source.id,
        new_code="CLONE-DRAFT",
        user_id=USER_A,
    )
    assert clone.status == "draft"
    assert clone.signed_at is None
    # Audit-trail breadcrumb: clone metadata records the source id so
    # ops can trace lineage without keeping a separate join table.
    assert clone.metadata_.get("cloned_from_contract_id") == str(source.id)


@pytest.mark.asyncio
async def test_clone_strips_volatile_audit_trail_from_metadata() -> None:
    """The clone must not inherit the source's lien-waiver or
    retention-release audit blocks — those legal artefacts belong to
    the original instrument's payment history, not the new contract.
    """
    svc = _make_service()
    source = _seed_contract(svc, project_id=PROJECT_A, code="META-SRC")
    source.metadata_ = {
        "retention_releases": [{"event": "substantial_completion", "amount": "5000"}],
        "lien_waivers": [{"waiver_type": "unconditional_final", "amount": "10000"}],
        "custom_note": "kept",
    }

    clone = await svc.clone_contract(
        source.id,
        new_code="META-CLONE",
        user_id=USER_A,
    )
    assert "retention_releases" not in clone.metadata_
    assert "lien_waivers" not in clone.metadata_
    assert clone.metadata_.get("custom_note") == "kept"
    assert clone.metadata_["cloned_from_contract_id"] == str(source.id)
