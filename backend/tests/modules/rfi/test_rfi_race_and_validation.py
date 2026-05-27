"""‌⁠‍R5 deep-audit tests for the RFI race-safety + schema validation surface.

Scope:
    1. ``(project_id, rfi_number)`` UniqueConstraint is reflected on the
       ``oe_rfi_rfi`` table (BUG-RFI-UNIQ).
    2. ``create_rfi`` retries on ``IntegrityError`` and ultimately
       succeeds with a fresh number after a transient collision.
    3. ``create_rfi`` surfaces HTTP 409 after exhausting the retry budget
       on persistent collisions — instead of writing a duplicate row.
    4. ``RFICreate.cost_impact_value`` rejects garbage like
       ``"definitely cheap"`` (BUG-RFI-DEC) — protects the variation
       builder from getting a non-numeric blob into ChangeOrder.
    5. ``RFICreate.cost_impact_value`` rejects ``Inf`` / ``NaN`` — they
       parse with Decimal but cannot become a valid currency amount.
    6. The permission registry knows every RFI verb the router declares —
       fails fast in unit time if any route would 403 every caller.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.rfi.models import RFI
from app.modules.rfi.schemas import RFICreate
from app.modules.rfi.service import RFIService

# ── Helpers (same in-memory stub family as test_rfi_state_fsm) ───────────


class _StubSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        self.rollback_count += 1


class _CollidingRepo:
    """RFI repo that raises ``IntegrityError`` a fixed number of times."""

    def __init__(self, *, collisions: int) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.collisions_remaining = collisions
        self._counter = 0

    async def next_rfi_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"RFI-{self._counter:03d}"

    async def create(self, rfi: Any) -> Any:
        if self.collisions_remaining > 0:
            self.collisions_remaining -= 1
            raise IntegrityError("INSERT", {}, Exception("UNIQUE violated"))
        if getattr(rfi, "id", None) is None:
            rfi.id = uuid.uuid4()
        now = datetime.now(UTC)
        rfi.created_at = now
        rfi.updated_at = now
        if getattr(rfi, "attachments", None) is None:
            rfi.attachments = []
        self.rows[rfi.id] = rfi
        return rfi

    async def get_by_id(self, rfi_id: uuid.UUID) -> Any:
        return self.rows.get(rfi_id)

    async def update_fields(self, rfi_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(rfi_id)
        if obj is None:
            return
        for k, v in fields.items():
            setattr(obj, k, v)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        self.rows.pop(rfi_id, None)


def _make_service_with_collisions(collisions: int) -> RFIService:
    service = RFIService.__new__(RFIService)
    service.session = _StubSession()
    service.repo = _CollidingRepo(collisions=collisions)
    return service


# ── 1. Schema reflection: UniqueConstraint is declared ───────────────────


class TestSchemaUniqueConstraint:
    def test_rfi_number_uniqueness_per_project_is_in_model(self) -> None:
        """The model carries the named UniqueConstraint we migrate to."""
        names = {getattr(c, "name", None) for c in RFI.__table__.constraints}
        assert "uq_rfi_project_number" in names, (
            f"Expected uq_rfi_project_number UniqueConstraint on oe_rfi_rfi. Found constraints: {names}"
        )

    def test_attachments_column_present(self) -> None:
        cols = {c.name for c in RFI.__table__.columns}
        assert "attachments" in cols


# ── 2-3. Service-level retry-on-IntegrityError ───────────────────────────


class TestCreateRetry:
    @pytest.mark.asyncio
    async def test_one_collision_then_success(self) -> None:
        service = _make_service_with_collisions(collisions=2)
        data = RFICreate(
            project_id=uuid.uuid4(),
            subject="Race-safe create",
            question="?",
        )
        rfi = await service.create_rfi(data, user_id=str(uuid.uuid4()))
        # After 2 collisions, the 3rd attempt should succeed with
        # RFI-003 because ``next_rfi_number`` was called once per attempt.
        assert rfi.rfi_number == "RFI-003"
        assert service.session.rollback_count == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise_409(self) -> None:
        from fastapi import HTTPException

        # 5 retries in the budget; supply 10 collisions to exhaust it.
        service = _make_service_with_collisions(collisions=10)
        data = RFICreate(
            project_id=uuid.uuid4(),
            subject="High contention",
            question="?",
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_rfi(data, user_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 409
        assert "contention" in exc_info.value.detail.lower()
        # All 5 retries rolled back.
        assert service.session.rollback_count == 5  # type: ignore[attr-defined]


# ── 4-5. Cost-impact Decimal validation ──────────────────────────────────


class TestCostImpactValueValidation:
    def test_non_numeric_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Cost concern",
                question="How much?",
                cost_impact=True,
                cost_impact_value="definitely cheap",
            )

    def test_inf_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Cost concern",
                question="How much?",
                cost_impact=True,
                cost_impact_value="Infinity",
            )

    def test_nan_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RFICreate(
                project_id=uuid.uuid4(),
                subject="Cost concern",
                question="How much?",
                cost_impact=True,
                cost_impact_value="NaN",
            )

    def test_clean_decimal_round_trips(self) -> None:
        """A real amount stays a real amount, normalised to canonical form."""
        payload = RFICreate(
            project_id=uuid.uuid4(),
            subject="Cost concern",
            question="How much?",
            cost_impact=True,
            cost_impact_value="12500.50",
        )
        assert payload.cost_impact_value == "12500.50"

    def test_whitespace_is_trimmed_before_parsing(self) -> None:
        """Leading/trailing whitespace shouldn't fail the gate."""
        payload = RFICreate(
            project_id=uuid.uuid4(),
            subject="Cost concern",
            question="How much?",
            cost_impact=True,
            cost_impact_value="  9999.00  ",
        )
        assert payload.cost_impact_value == "9999.00"

    def test_empty_string_passes_through(self) -> None:
        """Honest unknown — empty string is not garbage."""
        payload = RFICreate(
            project_id=uuid.uuid4(),
            subject="Cost concern",
            question="How much?",
            cost_impact=False,
            cost_impact_value="",
        )
        assert payload.cost_impact_value == ""


# ── 6. Permission registry has every RFI verb ────────────────────────────


class TestPermissionRegistryCoverage:
    def test_all_router_permissions_are_registered(self) -> None:
        """Each ``RequirePermission("rfi.X")`` the router declares must
        appear in the registry. A missing key would 403 every caller at
        runtime; this test fails fast in unit time instead.
        """
        from app.core.permissions import permission_registry
        from app.modules.rfi.permissions import register_rfi_permissions

        register_rfi_permissions()
        keys = set(permission_registry.list_all().keys())
        # ``create / read / update / delete`` from the original module
        # plus the R5 additions: ``assign`` (assigner role gate),
        # ``respond`` (respondent gate coarse layer), ``close`` (terminal
        # state lock-down).
        for verb in ("create", "read", "update", "delete", "assign", "respond", "close"):
            assert f"rfi.{verb}" in keys, (
                f"rfi.{verb} is referenced by the router but is missing "
                f"from the permission registry — endpoint would 403."
            )
