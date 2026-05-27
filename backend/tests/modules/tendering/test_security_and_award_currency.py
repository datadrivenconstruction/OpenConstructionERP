"""Tendering P0 regression suite — IDOR + award currency mismatch.

Covers two security/correctness issues:

* **P0-1 — IDOR on ``PATCH /bids/{bid_id}``**: the update endpoint must
  refuse a bid that belongs to another tenant's project. We exercise
  the helper ``_verify_bid_access`` (which the route calls *before*
  ``service.update_bid``) so a future refactor that drops the guard or
  re-orders the calls will trip this test.

* **P0-2 — Currency mismatch on award**: ``apply_winner`` previously
  copied winning bid ``unit_rate`` values straight into the BOQ even
  when the bid was quoted in a non-project currency, silently
  corrupting the budget. The guard raises HTTP 400 with a structured
  ``currency_mismatch`` payload listing every offending bid/line.

Tests use in-memory stubs for the repositories so they stay pure unit
tests and don't depend on Postgres / the full FastAPI lifespan.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.tendering.router import _verify_bid_access
from app.modules.tendering.schemas import BidCreate, BidLineItem, PackageCreate
from app.modules.tendering.service import TenderingService

# ── Shared stub repository (mirrors the real one's contract) ───────────────


class _StubRepo:
    """In-memory stand-in for :class:`TenderingRepository`.

    Implements the surface area exercised by ``create_package`` /
    ``create_bid`` / ``apply_winner`` and the comparison/lifecycle
    helpers — anything else falls through to ``AttributeError`` so a
    refactor that starts using a new repo method is obvious.
    """

    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}
        self.bids: dict[uuid.UUID, Any] = {}

    async def create_package(self, package: Any) -> Any:
        if getattr(package, "id", None) is None:
            package.id = uuid.uuid4()
        now = datetime.now(UTC)
        package.created_at = now
        package.updated_at = now
        if not hasattr(package, "bids"):
            package.bids = []
        if not hasattr(package, "metadata_"):
            package.metadata_ = {}
        if not hasattr(package, "status"):
            package.status = "draft"
        self.packages[package.id] = package
        return package

    async def get_package_by_id(self, package_id: uuid.UUID) -> Any:
        return self.packages.get(package_id)

    async def update_package_fields(self, package_id: uuid.UUID, **fields: Any) -> None:
        p = self.packages.get(package_id)
        if p:
            for k, v in fields.items():
                setattr(p, k, v)

    async def create_bid(self, bid: Any) -> Any:
        if getattr(bid, "id", None) is None:
            bid.id = uuid.uuid4()
        now = datetime.now(UTC)
        bid.created_at = now
        bid.updated_at = now
        if not hasattr(bid, "status"):
            bid.status = "submitted"
        self.bids[bid.id] = bid
        return bid

    async def get_bid_by_id(self, bid_id: uuid.UUID) -> Any:
        return self.bids.get(bid_id)

    async def list_bids_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [b for b in self.bids.values() if b.package_id == package_id]

    async def update_bid_fields(self, bid_id: uuid.UUID, **fields: Any) -> None:
        b = self.bids.get(bid_id)
        if b:
            for k, v in fields.items():
                setattr(b, k, v)


class _StubSession:
    """Minimal ``AsyncSession`` shim — only what apply_winner touches.

    ``apply_winner`` reaches for ``session.get(Position, uuid)`` to read
    the position and ``session.execute(update(...))`` to write it back.
    Both are stubbed against an in-memory position store so the test
    can assert on the final rates without standing up SQLite.
    """

    def __init__(self) -> None:
        self.positions: dict[uuid.UUID, Any] = {}
        self.executed: list[Any] = []

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.positions.get(key)

    async def execute(self, stmt: Any) -> SimpleNamespace:
        # Pull the UPDATE values + WHERE pk out so we can mutate the
        # in-memory row — mirrors what the real session would do.
        try:
            values = dict(stmt.compile().params)  # type: ignore[attr-defined]
        except Exception:
            values = {}
        # SQLAlchemy parameterises pk as ``id_1`` for ``Position.id == x``.
        pk = values.pop("id_1", None) or values.pop("id", None)
        if pk and pk in self.positions:
            for k, v in values.items():
                setattr(self.positions[pk], k, v)
        self.executed.append(stmt)
        return SimpleNamespace(rowcount=1)


def _make_service(session: _StubSession | None = None) -> TenderingService:
    """Construct a TenderingService bypassing the real DB layer."""
    svc = TenderingService.__new__(TenderingService)
    svc.session = session if session is not None else SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


# ── P0-1: IDOR on PATCH /bids/{bid_id} ─────────────────────────────────────


PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


@pytest.mark.asyncio
async def test_verify_bid_access_blocks_cross_project_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User B (owns project B) must NOT be able to act on a bid in
    project A's tender package — the ownership chain
    bid → package → project → owner is what the helper verifies.

    Pre-fix, ``PATCH /bids/{bid_id}`` only consulted the bid id and
    happily mutated competing bids across tenant boundaries. The route
    now ``await``-s :func:`_verify_bid_access` first; this test pins
    the helper's reject path.
    """
    svc = _make_service()

    # Project A owns the tender + bid.
    pkg = await svc.create_package(PackageCreate(project_id=PROJECT_A, name="A-confidential package"))
    bid = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="ACME GmbH (vendor for A)",
            total_amount="100000",
            currency="EUR",
        ),
    )

    # Stub project lookup: project A → owned by USER_A, no other rows.
    project_a = SimpleNamespace(id=PROJECT_A, owner_id=USER_A)

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return project_a if project_id == PROJECT_A else None

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _StubProjectRepo)

    # USER_B trying to touch project A's bid — must be rejected (403/404)
    # consistent with sibling IDOR guards in the codebase.
    with pytest.raises(HTTPException) as exc_info:
        await _verify_bid_access(svc, svc.session, bid.id, USER_B, payload={"role": "estimator"})
    assert exc_info.value.status_code in (403, 404), (
        f"expected 403/404 for cross-tenant bid access, got {exc_info.value.status_code}"
    )


@pytest.mark.asyncio
async def test_verify_bid_access_allows_owning_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the happy path — the owner of project A
    must still be able to load the bid, otherwise the IDOR fix would
    have over-locked the route and broken legitimate edits.
    """
    svc = _make_service()
    pkg = await svc.create_package(PackageCreate(project_id=PROJECT_A, name="A-confidential package"))
    bid = await svc.create_bid(
        pkg.id,
        BidCreate(company_name="ACME GmbH", total_amount="100000"),
    )

    project_a = SimpleNamespace(id=PROJECT_A, owner_id=USER_A)

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return project_a if project_id == PROJECT_A else None

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _StubProjectRepo)

    returned = await _verify_bid_access(svc, svc.session, bid.id, USER_A, payload={"role": "estimator"})
    assert returned.id == bid.id


@pytest.mark.asyncio
async def test_verify_bid_access_missing_bid_is_404() -> None:
    """Random/forged bid_id must 404 — the route should not lower into
    ``service.update_bid`` and emit a confusing 500 traceback.
    """
    svc = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await _verify_bid_access(svc, svc.session, uuid.uuid4(), USER_A)
    assert exc_info.value.status_code == 404


def test_router_update_bid_verifies_access_before_mutation() -> None:
    """Static AST guard: the ``update_bid`` handler must ``await``
    :func:`_verify_bid_access` *before* it calls
    :meth:`TenderingService.update_bid`.

    A regression here (swapping the order, or dropping the guard
    entirely) would re-open the IDOR even if the dynamic tests above
    happen to pass for a particular fixture layout.
    """
    import ast
    from pathlib import Path

    here = Path(__file__).resolve()
    repo_root = here.parents[4]
    router_path = repo_root / "backend" / "app" / "modules" / "tendering" / "router.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8"))

    handler: ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_bid":
            handler = node
            break
    assert handler is not None, "update_bid handler not found"

    # Collect the index of the first verify_bid_access call and the
    # first service.update_bid call in body order.
    verify_idx: int | None = None
    update_idx: int | None = None
    for i, stmt in enumerate(ast.walk(handler)):
        if isinstance(stmt, ast.Call):
            fn = stmt.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name == "_verify_bid_access" and verify_idx is None:
                verify_idx = i
            if name == "update_bid" and update_idx is None:
                update_idx = i
    assert verify_idx is not None, "update_bid no longer calls _verify_bid_access"
    assert update_idx is not None, "update_bid no longer calls service.update_bid"
    assert verify_idx < update_idx, "IDOR REGRESSION: _verify_bid_access must run BEFORE service.update_bid"


# ── P0-2: Currency-mismatch guard on apply_winner ──────────────────────────


def _seed_package_with_boq(
    svc: TenderingService,
) -> tuple[Any, uuid.UUID]:
    """Helper: create a package linked to a BOQ in collecting state."""
    boq_id = uuid.uuid4()
    pkg = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_A,
        boq_id=boq_id,
        name="Concrete works",
        description="",
        status="collecting",
        deadline=None,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        bids=[],
    )
    svc.repo.packages[pkg.id] = pkg  # type: ignore[attr-defined]
    return pkg, boq_id


def _seed_position(session: _StubSession, *, currency: str = "EUR") -> uuid.UUID:
    pos_id = uuid.uuid4()
    session.positions[pos_id] = SimpleNamespace(
        id=pos_id,
        quantity="10",
        unit_rate="100",
        total="1000",
    )
    return pos_id


def _patch_project_currency(monkeypatch: pytest.MonkeyPatch, *, currency: str) -> None:
    """Stub ProjectRepository.get_by_id to return a project in `currency`."""
    project = SimpleNamespace(id=PROJECT_A, owner_id=USER_A, currency=currency)

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return project if project_id == PROJECT_A else None

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _StubProjectRepo)


@pytest.mark.asyncio
async def test_apply_winner_same_currency_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) When every bid line is in the project currency, awarding
    succeeds and the BOQ position rate is updated to the winning rate.
    """
    session = _StubSession()
    svc = _make_service(session)
    _patch_project_currency(monkeypatch, currency="EUR")

    pkg, _ = _seed_package_with_boq(svc)
    pos_id = _seed_position(session)

    bid = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="ACME GmbH",
            total_amount="1500",
            currency="EUR",
            status="submitted",
            line_items=[
                BidLineItem(
                    position_id=str(pos_id),
                    description="Concrete C30/37",
                    unit="m3",
                    quantity=10.0,
                    unit_rate=150.0,
                    total=1500.0,
                ),
            ],
        ),
    )

    result = await svc.apply_winner(pkg.id, bid.id, awarded_by=USER_A)
    assert result["positions_updated"] == 1
    # Position rate was rewritten from 100 → 150 (Decimal stringification
    # may render a trailing .0, hence the Decimal-aware compare).
    assert Decimal(session.positions[pos_id].unit_rate) == Decimal("150")


@pytest.mark.asyncio
async def test_apply_winner_different_currency_raises_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(b) When the winning bid is quoted in a non-project currency,
    awarding must 400 with a ``currency_mismatch`` payload listing the
    offending bid id and currency — never silently rewrite project-
    currency BOQ rates with foreign-currency values.
    """
    session = _StubSession()
    svc = _make_service(session)
    _patch_project_currency(monkeypatch, currency="EUR")

    pkg, _ = _seed_package_with_boq(svc)
    pos_id = _seed_position(session)

    bid = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="USA Vendor LLC",
            total_amount="1800",
            currency="USD",  # ← mismatch
            status="submitted",
            line_items=[
                BidLineItem(
                    position_id=str(pos_id),
                    description="Concrete C30/37",
                    unit="m3",
                    quantity=10.0,
                    unit_rate=180.0,
                    total=1800.0,
                ),
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.apply_winner(pkg.id, bid.id, awarded_by=USER_A)

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured detail, got {detail!r}"
    assert detail["code"] == "currency_mismatch"
    assert detail["project_currency"] == "EUR"
    offenders = detail["offenders"]
    assert any(o["bid_id"] == str(bid.id) and o["currency"] == "USD" for o in offenders), (
        f"offender list missing the USD bid: {offenders!r}"
    )

    # Critically: the BOQ position must be untouched — no foreign-
    # currency value bled into the project budget.
    assert Decimal(session.positions[pos_id].unit_rate) == Decimal("100")


@pytest.mark.asyncio
async def test_apply_winner_line_level_currency_override_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-line currency overrides (some bid imports carry an explicit
    ``currency`` per line item) are also caught — even when the bid
    header reads EUR, an embedded USD line cannot quietly slip through.
    """
    session = _StubSession()
    svc = _make_service(session)
    _patch_project_currency(monkeypatch, currency="EUR")

    pkg, _ = _seed_package_with_boq(svc)
    pos_id = _seed_position(session)

    # Build the bid by hand so we can attach a per-line currency that
    # the BidLineItem pydantic schema doesn't model.
    bid_id = uuid.uuid4()
    bid = SimpleNamespace(
        id=bid_id,
        package_id=pkg.id,
        company_name="Mixed Vendor",
        contact_email="",
        total_amount="1500",
        currency="EUR",
        submitted_at=None,
        status="submitted",
        notes="",
        line_items=[
            {
                "position_id": str(pos_id),
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity": 10.0,
                "unit_rate": 150.0,
                "total": 1500.0,
                "currency": "USD",  # ← per-line override
            }
        ],
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    svc.repo.bids[bid_id] = bid  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc_info:
        await svc.apply_winner(pkg.id, bid_id, awarded_by=USER_A)

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "currency_mismatch"
    offenders = detail["offenders"]
    assert any(o.get("scope", "").startswith("line[") and o["currency"] == "USD" for o in offenders), (
        f"per-line USD offender not flagged: {offenders!r}"
    )

    # BOQ unchanged.
    assert Decimal(session.positions[pos_id].unit_rate) == Decimal("100")


@pytest.mark.asyncio
async def test_apply_winner_missing_bid_id_keeps_existing_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) No winning bid — existing behaviour (404) is preserved.

    The currency guard must run AFTER bid lookup so a missing bid still
    surfaces as 404 rather than the new 400 ``currency_mismatch``.
    """
    session = _StubSession()
    svc = _make_service(session)
    _patch_project_currency(monkeypatch, currency="EUR")

    pkg, _ = _seed_package_with_boq(svc)

    with pytest.raises(HTTPException) as exc_info:
        await svc.apply_winner(pkg.id, uuid.uuid4(), awarded_by=USER_A)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_apply_winner_unknown_project_currency_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive default: when the project carries no currency (legacy
    rows / fresh projects), the guard must NOT block — we can't compare
    against an empty string. Awarding proceeds and the bid currency is
    accepted as-is (downstream FX handling stays the user's call).
    """
    session = _StubSession()
    svc = _make_service(session)
    _patch_project_currency(monkeypatch, currency="")

    pkg, _ = _seed_package_with_boq(svc)
    pos_id = _seed_position(session)

    bid = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="Legacy Vendor",
            total_amount="2000",
            currency="USD",
            status="submitted",
            line_items=[
                BidLineItem(
                    position_id=str(pos_id),
                    unit="m3",
                    quantity=10.0,
                    unit_rate=200.0,
                    total=2000.0,
                ),
            ],
        ),
    )

    result = await svc.apply_winner(pkg.id, bid.id, awarded_by=USER_A)
    assert result["positions_updated"] == 1
