# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid Management module — Round-7 security audit regressions.

Pins down the eight guarantees the R7 audit swept across the module:

1. **Owner-IDOR on package** — ``_verify_package_access`` returns 404
   (never 403) when the caller does not own the package's project.

2. **Owner-IDOR on submission** — the submission-level helper rejects
   cross-tenant access through the inv -> pkg chain.

3. **Bidder-impersonation on submission** — a manager on package A
   cannot create a submission row binding a project-A invitation to a
   project-B bidder snapshot.

4. **Bidder-impersonation on Q&A / Rejection / Scorecard** — the same
   cross-package bidder reference is refused at the service level.

5. **Cross-package line-item poisoning** — a submission line cannot
   reference a line_item belonging to a different package.

6. **Decimal-string money serialization** — every money field on the
   response models round-trips through ``Decimal`` (never ``float``).

7. **FSM rejection** — illegal lifecycle transitions surface 409 with
   no state mutation (e.g. draft -> awarded, awarded a draft package).

8. **RBAC** — viewer cannot mutate, editor cannot award/record
   scorecards, MANAGER required for award / scorecard / delete.

The tests run against in-memory stub repositories (no SQLite engine,
no FastAPI app boot) so they stay sub-second and reproducible.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.bid_management.schemas import (
    BidAwardCreate,
    BidAwardResponse,
    BidPackageResponse,
    BidQACreate,
    BidRejectionCreate,
    BidSubmissionCreate,
    BidSubmissionLineCreate,
    BidSubmissionResponse,
)
from app.modules.bid_management.service import (
    INVITATION_TRANSITIONS,
    PACKAGE_TRANSITIONS,
    BidManagementService,
    allowed_invitation_transitions,
    allowed_package_transitions,
)  # noqa: I001

# ── Stub repositories ────────────────────────────────────────────────────


class _StubRepo:
    """Generic in-memory async repo. Holds rows keyed by id."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, key: uuid.UUID) -> Any:
        return self.rows.get(key)

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        return item

    async def update_fields(self, key: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(key)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, key: uuid.UUID) -> None:
        self.rows.pop(key, None)


class _StubPackageRepo(_StubRepo):
    async def get_by_code(self, code: str) -> Any:
        for row in self.rows.values():
            if getattr(row, "code", None) == code:
                return row
        return None

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [
            r
            for r in self.rows.values()
            if getattr(r, "project_id", None) == project_id and (status is None or getattr(r, "status", "") == status)
        ]
        return rows[offset : offset + limit], len(rows)


class _StubLineRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "package_id", None) == package_id]

    async def bulk_create(self, items: list[Any]) -> list[Any]:
        for item in items:
            await self.create(item)
        return items


class _StubInvitationRepo(_StubRepo):
    async def list_for_package(
        self,
        package_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "package_id", None) == package_id and (status is None or getattr(r, "status", "") == status)
        ]

    async def invitations_pending(self, package_id: uuid.UUID) -> list[Any]:
        return [
            r
            for r in self.rows.values()
            if getattr(r, "package_id", None) == package_id
            and getattr(r, "status", "") in ("pending", "sent", "opened")
        ]


class _StubBidderRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "package_id", None) == package_id]


class _StubSubmissionRepo(_StubRepo):
    async def submissions_for_package(self, package_id: uuid.UUID) -> list[Any]:
        # Reach through invitation -> package; tests wire invitations into the
        # service's invitation_repo.
        return list(self.rows.values())

    async def get_by_invitation(self, invitation_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if getattr(row, "invitation_id", None) == invitation_id:
                return row
        return None


class _StubSubmissionLineRepo(_StubRepo):
    async def list_for_submission(self, submission_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "submission_id", None) == submission_id]

    async def bulk_create(self, items: list[Any]) -> list[Any]:
        for item in items:
            await self.create(item)
        return items


class _StubQARepo(_StubRepo):
    async def q_and_a_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "package_id", None) == package_id]


class _StubAwardRepo(_StubRepo):
    async def get_for_package(self, package_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if getattr(row, "package_id", None) == package_id:
                return row
        return None


class _StubRejectionRepo(_StubRepo):
    async def list_for_package(self, package_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "package_id", None) == package_id]


class _StubComparisonRepo(_StubRepo):
    async def get_for_package(self, package_id: uuid.UUID) -> Any:
        for row in self.rows.values():
            if getattr(row, "package_id", None) == package_id:
                return row
        return None


class _StubLevelingRepo(_StubRepo):
    async def levelings_for_comparison(self, comparison_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "comparison_id", None) == comparison_id]

    async def delete_for_comparison(self, comparison_id: uuid.UUID) -> None:
        keep = {k: v for k, v in self.rows.items() if getattr(v, "comparison_id", None) != comparison_id}
        self.rows = keep


class _StubSession:
    """Async-session shim that records add() calls but skips real I/O."""

    def __init__(self) -> None:
        self.added: list[Any] = []
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
        if self.svc is None:
            return None
        # Best-effort dispatch by ORM class name to the matching repo.
        name = getattr(model, "__name__", "")
        mapping = {
            "BidPackage": self.svc.package_repo,
            "BidPackageLineItem": self.svc.line_repo,
            "BidInvitation": self.svc.invitation_repo,
            "Bidder": self.svc.bidder_repo,
            "BidSubmission": self.svc.submission_repo,
            "BidSubmissionLine": self.svc.submission_line_repo,
            "BidQA": self.svc.qa_repo,
            "BidComparison": self.svc.comparison_repo,
            "BidLeveling": self.svc.leveling_repo,
            "BidAward": self.svc.award_repo,
            "BidRejection": self.svc.rejection_repo,
        }
        repo = mapping.get(name)
        if repo is None:
            return None
        return repo.rows.get(key)


def _make_service() -> BidManagementService:
    """Construct a BidManagementService wired to in-memory stubs."""
    svc = BidManagementService.__new__(BidManagementService)
    svc.session = _StubSession()
    svc.package_repo = _StubPackageRepo()
    svc.line_repo = _StubLineRepo()
    svc.invitation_repo = _StubInvitationRepo()
    svc.bidder_repo = _StubBidderRepo()
    svc.submission_repo = _StubSubmissionRepo()
    svc.submission_line_repo = _StubSubmissionLineRepo()
    svc.qa_repo = _StubQARepo()
    svc.comparison_repo = _StubComparisonRepo()
    svc.leveling_repo = _StubLevelingRepo()
    svc.award_repo = _StubAwardRepo()
    svc.rejection_repo = _StubRejectionRepo()
    svc.session.svc = svc
    return svc


def _seed_package(
    svc: BidManagementService,
    *,
    project_id: uuid.UUID,
    status: str = "draft",
    code: str | None = None,
    currency: str = "EUR",
) -> Any:
    pkg = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        tender_id=None,
        code=code or f"PKG-{uuid.uuid4().hex[:6]}",
        title="Pkg",
        scope_description="",
        instructions_to_bidders="",
        submission_deadline=None,
        decision_due_by=None,
        currency=currency,
        total_budget_estimate="0",
        status=status,
        confidentiality_level="limited",
        published_at=None,
        closed_at=None,
        awarded_at=None,
        created_by=None,
        metadata_={},
    )
    svc.package_repo.rows[pkg.id] = pkg
    return pkg


def _seed_bidder(svc: BidManagementService, *, package_id: uuid.UUID, status: str = "active") -> Any:
    bidder = SimpleNamespace(
        id=uuid.uuid4(),
        package_id=package_id,
        company_name="Acme Construction GmbH",
        contact_name="",
        contact_email="",
        contact_phone="",
        country="",
        status=status,
        disqualification_reason=None,
        notes="",
    )
    svc.bidder_repo.rows[bidder.id] = bidder
    return bidder


def _seed_invitation(svc: BidManagementService, *, package_id: uuid.UUID, status: str = "sent") -> Any:
    inv = SimpleNamespace(
        id=uuid.uuid4(),
        package_id=package_id,
        bidder_ref_id=None,
        invitee_email="bid@acme.test",
        invitee_company_name="Acme",
        sent_at=None,
        opened_at=None,
        submission_received_at=None,
        declined_at=None,
        decline_reason=None,
        status=status,
        token_hash=None,
    )
    svc.invitation_repo.rows[inv.id] = inv
    return inv


def _seed_line_item(svc: BidManagementService, *, package_id: uuid.UUID) -> Any:
    line = SimpleNamespace(
        id=uuid.uuid4(),
        package_id=package_id,
        code="L-1",
        description="",
        unit="m2",
        quantity="100",
        alternative_allowed=False,
        order_index=0,
        parent_line_id=None,
        spec_attachment_url=None,
        is_mandatory=True,
    )
    svc.line_repo.rows[line.id] = line
    return line


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
    """Stub ProjectRepository.get_by_id + UserRepository for verify_project_access.

    A project is "missing" iff its id isn't in the ``owners`` dict; the
    stubbed UserRepository returns a non-admin role so admin-bypass does
    not muddy the cross-tenant test cases.
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
            return SimpleNamespace(role="editor")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )


# ── 1. Owner-IDOR on package GET ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_idor_get_package_blocks_cross_tenant_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user owning project A must NOT be able to load a package on
    project B — the router's ``_verify_package_access`` must return 404
    (never 403) per the R5/R6 leak-safe policy in
    ``dependencies.verify_project_access``.
    """
    from app.modules.bid_management.router import _verify_package_access

    svc = _make_service()
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-1")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    # session.get(BidPackage, ...) dispatches via _StubSession to the
    # package_repo, so the package lookup itself succeeds; the access
    # check fails because USER_A does not own PROJECT_B.
    with pytest.raises(HTTPException) as exc:
        await _verify_package_access(svc.session, pkg_b.id, USER_A)
    assert exc.value.status_code == 404, (
        f"cross-tenant GET on package must 404, got {exc.value.status_code}: {exc.value.detail!r}"
    )


@pytest.mark.asyncio
async def test_owner_access_allows_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the legitimate project owner must still load
    the package."""
    from app.modules.bid_management.router import _verify_package_access

    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-1")
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A})

    returned = await _verify_package_access(svc.session, pkg_a.id, USER_A)
    assert returned.id == pkg_a.id


@pytest.mark.asyncio
async def test_owner_idor_get_unknown_package_also_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-existent package id must 404 — and the error message must
    NOT differ between 'missing' and 'forbidden' so the caller cannot
    enumerate ids by probing 403 vs 404 timing/messages.
    """
    from app.modules.bid_management.router import _verify_package_access

    svc = _make_service()
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A})

    with pytest.raises(HTTPException) as exc:
        await _verify_package_access(svc.session, uuid.uuid4(), USER_A)
    assert exc.value.status_code == 404


# ── 2. Owner-IDOR through submission chain ────────────────────────────────


@pytest.mark.asyncio
async def test_owner_idor_submission_chain_blocks_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_verify_submission_access`` walks sub -> inv -> pkg.  A USER_A
    request for a submission whose ultimate package lives on PROJECT_B
    must 404."""
    from app.modules.bid_management.router import _verify_submission_access

    svc = _make_service()
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-2")
    inv_b = _seed_invitation(svc, package_id=pkg_b.id)
    sub_b = SimpleNamespace(
        id=uuid.uuid4(),
        invitation_id=inv_b.id,
        bidder_id=uuid.uuid4(),
    )
    svc.submission_repo.rows[sub_b.id] = sub_b
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    with pytest.raises(HTTPException) as exc:
        await _verify_submission_access(svc.session, sub_b.id, USER_A)
    assert exc.value.status_code == 404


# ── 3. Bidder-impersonation on submission ────────────────────────────────


@pytest.mark.asyncio
async def test_bidder_impersonation_submission_cross_package_rejected() -> None:
    """A submission referencing a bidder from a DIFFERENT package must
    be rejected (404, leak-safe) — without this guard a manager on
    package A who knows a project-B bidder UUID could forge a
    submission row that pollutes the leveling matrix.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-IMP")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-IMP")
    inv_a = _seed_invitation(svc, package_id=pkg_a.id)
    bidder_on_b = _seed_bidder(svc, package_id=pkg_b.id)

    data = BidSubmissionCreate(
        invitation_id=inv_a.id,
        bidder_id=bidder_on_b.id,
        total_amount=Decimal("100000.00"),
        currency="EUR",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.record_submission(data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bidder_impersonation_submission_same_package_allowed() -> None:
    """Happy path: a submission with bidder belonging to the same package
    as the invitation must succeed (regression guard)."""
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-OK")
    inv_a = _seed_invitation(svc, package_id=pkg_a.id)
    bidder_a = _seed_bidder(svc, package_id=pkg_a.id)

    data = BidSubmissionCreate(
        invitation_id=inv_a.id,
        bidder_id=bidder_a.id,
        total_amount=Decimal("12345.67"),
        currency="EUR",
    )
    sub = await svc.record_submission(data)
    assert sub.bidder_id == bidder_a.id
    assert sub.invitation_id == inv_a.id


# ── 4. Bidder-impersonation on Q&A / Rejection / Scorecard ───────────────


@pytest.mark.asyncio
async def test_bidder_impersonation_qa_cross_package_rejected() -> None:
    """``create_qa`` with a bidder_id pointing at a foreign package
    must 404 — otherwise project A's Q&A board could be polluted with
    questions attributed to a project-B bidder.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-QA")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-QA")
    bidder_on_b = _seed_bidder(svc, package_id=pkg_b.id)

    data = BidQACreate(
        package_id=pkg_a.id,
        bidder_id=bidder_on_b.id,
        question="Spec clarification on pump room",
        asked_by_email="ops@b.test",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_qa(data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bidder_impersonation_rejection_cross_package_rejected() -> None:
    """``create_rejection`` must refuse a bidder_id from a different
    package — otherwise rejection audit history would mix cross-tenant
    bidder ids.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-REJ")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-REJ")
    bidder_on_b = _seed_bidder(svc, package_id=pkg_b.id)

    data = BidRejectionCreate(
        package_id=pkg_a.id,
        bidder_id=bidder_on_b.id,
        rejection_code="other",
        rejection_reason="x",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_rejection(data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bidder_impersonation_scorecard_cross_package_rejected() -> None:
    """``record_subcontractor_scorecard`` must refuse a foreign bidder
    so a manager on project A cannot plant retaliatory scores against
    project-B's subcontractor.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-SC")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-SC")
    bidder_on_b = _seed_bidder(svc, package_id=pkg_b.id)

    with pytest.raises(HTTPException) as exc:
        await svc.record_subcontractor_scorecard(
            pkg_a.id,
            bidder_on_b.id,
            on_time_score=Decimal("90"),
            quality_score=Decimal("85"),
            safety_score=Decimal("100"),
            commercial_score=Decimal("70"),
            notes="cross-tenant attempt",
        )
    assert exc.value.status_code == 404


# ── 5. Cross-package line-item poisoning on submission lines ─────────────


@pytest.mark.asyncio
async def test_cross_package_line_item_on_submission_line_rejected() -> None:
    """A submission line cannot reference a line_item from a different
    package — without this, the leveling matrix could ingest
    project-B's line items into a project-A submission.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, code="A-LI")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, code="B-LI")
    inv_a = _seed_invitation(svc, package_id=pkg_a.id)
    bidder_a = _seed_bidder(svc, package_id=pkg_a.id)
    sub_a = await svc.record_submission(
        BidSubmissionCreate(
            invitation_id=inv_a.id,
            bidder_id=bidder_a.id,
            total_amount=Decimal("0"),
            currency="EUR",
        )
    )
    line_on_b = _seed_line_item(svc, package_id=pkg_b.id)

    data = BidSubmissionLineCreate(
        submission_id=sub_a.id,
        line_item_id=line_on_b.id,
        unit_price=Decimal("100.00"),
        quantity_priced=Decimal("10.00"),
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_submission_line(data)
    assert exc.value.status_code == 404


# ── 6. Decimal-string money serialization ────────────────────────────────


def test_money_fields_serialize_as_decimal_strings_not_floats() -> None:
    """Every money field on the bid_management response models is typed
    as Decimal; the json-mode dump emits a STRING.  Catches a future
    "let's switch to float" perf refactor.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    sub = BidSubmissionResponse(
        id=uuid.uuid4(),
        invitation_id=uuid.uuid4(),
        bidder_id=uuid.uuid4(),
        total_amount=Decimal("99999.1234"),
        completeness_score=Decimal("87.5"),
        created_at=now,
        updated_at=now,
    )
    payload = sub.model_dump(mode="json")
    assert isinstance(payload["total_amount"], str), (
        f"total_amount must serialize as string, got "
        f"{type(payload['total_amount']).__name__}: {payload['total_amount']!r}"
    )
    assert payload["total_amount"] == "99999.1234"
    assert isinstance(payload["completeness_score"], str)

    # Round-trip an award response too
    award = BidAwardResponse(
        id=uuid.uuid4(),
        package_id=uuid.uuid4(),
        awarded_bidder_id=uuid.uuid4(),
        awarded_amount=Decimal("250000.50"),
        currency="EUR",
        created_at=now,
        updated_at=now,
    )
    award_payload = award.model_dump(mode="json")
    assert isinstance(award_payload["awarded_amount"], str)
    assert award_payload["awarded_amount"] == "250000.50"


def test_no_float_columns_on_bid_management_money_models() -> None:
    """Defensive guard: every money-shaped column on the bid_management
    ORM models is ``Numeric(p, q)`` — never ``Float``.  Float would
    silently re-introduce binary-FP rounding to bid totals.
    """
    from sqlalchemy import Float, Numeric

    from app.modules.bid_management import models as bm_models

    money_columns: list[tuple[str, str, type]] = []
    for name in dir(bm_models):
        obj = getattr(bm_models, name)
        table = getattr(obj, "__table__", None)
        if table is None:
            continue
        for col in table.columns:
            cname = col.name.lower()
            if any(
                k in cname
                for k in (
                    "amount",
                    "total",
                    "price",
                    "score",
                    "adjustment",
                    "quantity",
                    "budget",
                    "rate",
                )
            ):
                money_columns.append((obj.__name__, col.name, type(col.type)))

    assert money_columns, "guard self-check: expected to find money columns"
    floats = [(cls, col) for cls, col, typ in money_columns if isinstance(typ, type) and issubclass(typ, Float)]
    assert not floats, (
        f"Float columns leaked into bid_management money model: {floats!r}. All money fields must use Numeric(p, q)."
    )
    numerics = [(cls, col) for cls, col, typ in money_columns if isinstance(typ, type) and issubclass(typ, Numeric)]
    assert numerics, "expected at least one Numeric money column"


# ── 7. FSM rejection of invalid transitions ──────────────────────────────


def test_fsm_package_terminal_states_have_no_outbound_transitions() -> None:
    """``awarded`` and ``cancelled`` are terminal states — no further
    transitions allowed."""
    assert allowed_package_transitions("awarded") == set()
    assert allowed_package_transitions("cancelled") == set()


def test_fsm_package_draft_cannot_jump_to_awarded() -> None:
    """``draft`` can only flow to ``published`` / ``cancelled`` — a
    draft package cannot leap straight to ``awarded``.
    """
    assert "awarded" not in allowed_package_transitions("draft")
    assert "open" not in allowed_package_transitions("draft")


def test_fsm_invitation_submitted_is_terminal() -> None:
    """Once an invitation reaches ``submitted`` there are no further
    transitions — re-opening a submitted invitation would corrupt the
    submission audit trail.
    """
    assert allowed_invitation_transitions("submitted") == set()


@pytest.mark.asyncio
async def test_award_draft_package_rejected_with_409() -> None:
    """``award_package`` requires the package to be in ``closed`` state.
    Trying to award a draft must 409.
    """
    svc = _make_service()
    pkg = _seed_package(svc, project_id=PROJECT_A, status="draft", code="A-DRAFT")
    bidder = _seed_bidder(svc, package_id=pkg.id)

    data = BidAwardCreate(
        package_id=pkg.id,
        awarded_bidder_id=bidder.id,
        awarded_amount=Decimal("100000"),
        currency="EUR",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.award_package(pkg.id, data, user_id=USER_A)
    assert exc.value.status_code == 409
    # Package status must NOT have changed.
    assert pkg.status == "draft"


@pytest.mark.asyncio
async def test_award_disqualified_bidder_rejected_with_409() -> None:
    """Cannot award to a disqualified bidder even when the package is
    in the correct ``closed`` state — the FSM on the bidder enforces this.
    """
    svc = _make_service()
    pkg = _seed_package(svc, project_id=PROJECT_A, status="closed", code="A-DQ")
    bidder = _seed_bidder(svc, package_id=pkg.id, status="disqualified")

    data = BidAwardCreate(
        package_id=pkg.id,
        awarded_bidder_id=bidder.id,
        awarded_amount=Decimal("100000"),
        currency="EUR",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.award_package(pkg.id, data, user_id=USER_A)
    assert exc.value.status_code == 409
    assert pkg.status == "closed"


@pytest.mark.asyncio
async def test_award_cross_package_bidder_rejected_with_404() -> None:
    """Award referencing a bidder from a different package must 404 —
    closes the cross-tenant award-by-foreign-bidder path.
    """
    svc = _make_service()
    pkg_a = _seed_package(svc, project_id=PROJECT_A, status="closed", code="A-X")
    pkg_b = _seed_package(svc, project_id=PROJECT_B, status="closed", code="B-X")
    bidder_on_b = _seed_bidder(svc, package_id=pkg_b.id)

    data = BidAwardCreate(
        package_id=pkg_a.id,
        awarded_bidder_id=bidder_on_b.id,
        awarded_amount=Decimal("100000"),
        currency="EUR",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.award_package(pkg_a.id, data, user_id=USER_A)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_package_patch_cannot_jump_status_via_generic_update() -> None:
    """``update_package`` must refuse a generic PATCH that tries to flip
    ``status`` — lifecycle changes go through the dedicated endpoints
    (publish / open-bids / close / cancel / award), which is critical
    because those endpoints stamp timestamps and emit events.
    """
    from app.modules.bid_management.schemas import BidPackageUpdate

    svc = _make_service()
    pkg = _seed_package(svc, project_id=PROJECT_A, status="draft", code="A-PJ")

    data = BidPackageUpdate(status="awarded")  # type: ignore[call-arg]
    with pytest.raises(HTTPException) as exc:
        await svc.update_package(pkg.id, data)
    assert exc.value.status_code == 409
    assert pkg.status == "draft"  # state unchanged


# ── 8. RBAC ──────────────────────────────────────────────────────────────


def test_rbac_viewer_cannot_mutate_or_award() -> None:
    """A plain VIEWER must not carry write or lifecycle permissions."""
    from app.core.permissions import Role, permission_registry
    from app.modules.bid_management.permissions import (
        register_bid_management_permissions,
    )

    register_bid_management_permissions()
    for perm in (
        "bid_management.create",
        "bid_management.update",
        "bid_management.delete",
        "bid_management.award",
        "bid_management.publish",
        "bid_management.open_bids",
        "bid_management.disqualify_bidder",
        "bid_management.cancel",
        "bid_management.record_scorecard",
    ):
        assert not permission_registry.role_has_permission(Role.VIEWER, perm), f"VIEWER must NOT carry {perm}"


def test_rbac_editor_can_create_but_not_award_or_score() -> None:
    """EDITOR (estimator) can author packages / lines but must NOT be
    able to award, cancel, disqualify, delete, or plant scorecards —
    these are MANAGER-or-higher actions.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.bid_management.permissions import (
        register_bid_management_permissions,
    )

    register_bid_management_permissions()
    assert permission_registry.role_has_permission(Role.EDITOR, "bid_management.create")
    assert permission_registry.role_has_permission(Role.EDITOR, "bid_management.update")
    for elevated in (
        "bid_management.delete",
        "bid_management.award",
        "bid_management.publish",
        "bid_management.open_bids",
        "bid_management.disqualify_bidder",
        "bid_management.cancel",
        "bid_management.record_scorecard",
    ):
        assert not permission_registry.role_has_permission(Role.EDITOR, elevated), (
            f"EDITOR must NOT carry {elevated} — it is a MANAGER-or-higher action"
        )


def test_rbac_manager_carries_award_and_scorecard() -> None:
    """MANAGER must carry award + record_scorecard so the post-award
    workflow (recording subcontractor performance) is operable.
    """
    from app.core.permissions import Role, permission_registry
    from app.modules.bid_management.permissions import (
        register_bid_management_permissions,
    )

    register_bid_management_permissions()
    for perm in (
        "bid_management.award",
        "bid_management.record_scorecard",
        "bid_management.delete",
        "bid_management.publish",
        "bid_management.open_bids",
        "bid_management.disqualify_bidder",
        "bid_management.cancel",
    ):
        assert permission_registry.role_has_permission(Role.MANAGER, perm), f"MANAGER must carry {perm}"


# ── 9. Self-check on FSM transition map shape ────────────────────────────


def test_package_fsm_map_complete_and_closed() -> None:
    """All package statuses referenced from any transition map MUST
    appear as keys in PACKAGE_TRANSITIONS — otherwise a transition
    could land in an undeclared state with no further moves recognised,
    silently bricking the package lifecycle.
    """
    declared = set(PACKAGE_TRANSITIONS.keys())
    referenced: set[str] = set()
    for nexts in PACKAGE_TRANSITIONS.values():
        referenced.update(nexts)
    missing = referenced - declared
    assert not missing, f"PACKAGE_TRANSITIONS references undeclared states: {missing}"


def test_invitation_fsm_map_complete_and_closed() -> None:
    """Same closure guarantee for the invitation lifecycle."""
    declared = set(INVITATION_TRANSITIONS.keys())
    referenced: set[str] = set()
    for nexts in INVITATION_TRANSITIONS.values():
        referenced.update(nexts)
    missing = referenced - declared
    assert not missing, f"INVITATION_TRANSITIONS references undeclared states: {missing}"


# ── 10. Schema validator pinning ─────────────────────────────────────────


def test_package_response_decimal_default_serializes_as_string() -> None:
    """A package response with default total_budget_estimate (Decimal("0"))
    must still emit a string in JSON mode — regression guard against a
    Pydantic config change that disables Decimal->string coercion.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    resp = BidPackageResponse(
        id=uuid.uuid4(),
        project_id=PROJECT_A,
        code="DEFAULTS",
        created_at=now,
        updated_at=now,
    )
    payload = resp.model_dump(mode="json")
    assert isinstance(payload["total_budget_estimate"], str)
    assert payload["total_budget_estimate"] == "0"
