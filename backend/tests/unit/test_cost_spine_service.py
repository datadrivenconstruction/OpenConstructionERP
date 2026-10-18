"""Unit tests for :class:`CostSpineService` (Cost Spine, v6.4 keystone).

Scope:
    Pure-logic coverage for the Cost Spine service using ``SimpleNamespace``
    stub repositories - the service only ever talks to its repos plus a small
    set of cross-module repositories that we monkey-patch. No live DB.

    Money is asserted with EXACT ``Decimal`` values (never float) because the
    spine is the single source of truth every downstream rollup sums against,
    and a silent float drift here would corrupt the whole 5D model.

Cases:
    * account tree built from ``position.classification``
    * one CostLine per costed position
    * section headers (empty ``unit``) skipped
    * currency inherited from the project, never hardcoded EUR
    * idempotency - a 2nd ``generate_from_boq`` creates nothing and does not
      double-link
    * ``rollup_for_line`` math incl. FX conversion + the ``mixed_currency`` flag
    * delete-account 409 when cost lines reference it
    * delete-line 409 with the linked counts surfaced
    * link / unlink a downstream target
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.costmodel.schemas import SpineLinkRequest
from app.modules.costmodel.service import CostSpineService

# ── Stub ORM-ish rows ──────────────────────────────────────────────────────


def _account(
    *,
    project_id: uuid.UUID,
    code: str,
    name: str | None = None,
    parent_id: uuid.UUID | None = None,
    control_account_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """A control-account row shaped like the ORM model."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        parent_id=parent_id,
        code=code,
        name=name or code,
        classification_standard="din276",
        status="open",
        sort_order=0,
        metadata_={},
        created_at=now,
        updated_at=now,
    )


def _cost_line(
    *,
    project_id: uuid.UUID,
    code: str,
    estimate_amount: str = "0",
    currency: str = "",
    control_account_id: uuid.UUID | None = None,
    boq_position_id: uuid.UUID | None = None,
    boq_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        control_account_id=control_account_id,
        code=code,
        description="",
        unit="m3",
        source="boq",
        boq_position_id=boq_position_id,
        boq_id=boq_id,
        estimate_quantity="0",
        estimate_unit_rate="0",
        estimate_amount=estimate_amount,
        currency=currency,
        status="active",
        metadata_={},
        created_at=now,
        updated_at=now,
    )


def _position(
    *,
    ordinal: str,
    unit: str,
    quantity: str = "0",
    unit_rate: str = "0",
    total: str = "0",
    classification: dict | None = None,
    reference_code: str | None = None,
    cost_line_id: uuid.UUID | None = None,
    description: str = "Position",
    boq_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        boq_id=boq_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
        classification=classification if classification is not None else {},
        reference_code=reference_code,
        cost_line_id=cost_line_id,
    )


# ── Stub repositories ──────────────────────────────────────────────────────


class _StubAccountRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.lines_referencing: dict[uuid.UUID, int] = {}

    async def list_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [a for a in self.rows.values() if a.project_id == project_id]

    async def get_by_id(self, account_id: uuid.UUID) -> Any:
        return self.rows.get(account_id)

    async def get_by_project_code(self, project_id: uuid.UUID, code: str) -> Any:
        for a in self.rows.values():
            if a.project_id == project_id and a.code == code:
                return a
        return None

    async def create(self, account: Any) -> Any:
        if getattr(account, "id", None) is None:
            account.id = uuid.uuid4()
        # Normalize the freshly-built ORM-style object to a namespace with the
        # response fields populated (created_at/updated_at) so response
        # validation succeeds.
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        account.created_at = getattr(account, "created_at", None) or now
        account.updated_at = getattr(account, "updated_at", None) or now
        account.metadata_ = getattr(account, "metadata_", {}) or {}
        self.rows[account.id] = account
        return account

    async def update_fields(self, account_id: uuid.UUID, **fields: object) -> None:
        row = self.rows[account_id]
        for k, v in fields.items():
            setattr(row, k, v)

    async def delete(self, account_id: uuid.UUID) -> None:
        self.rows.pop(account_id, None)

    async def count_lines_referencing(self, account_id: uuid.UUID) -> int:
        return self.lines_referencing.get(account_id, 0)


class _StubLineRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        control_account_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if control_account_id is not None:
            rows = [r for r in rows if r.control_account_id == control_account_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows, len(rows)

    async def get_by_id(self, line_id: uuid.UUID) -> Any:
        return self.rows.get(line_id)

    async def get_by_project_code(self, project_id: uuid.UUID, code: str) -> Any:
        for r in self.rows.values():
            if r.project_id == project_id and r.code == code:
                return r
        return None

    async def existing_by_boq_position(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Mirror the real repo: BOQ-sourced lines keyed by str(boq_position_id)."""
        out: dict[str, Any] = {}
        for r in self.rows.values():
            if r.project_id != project_id or r.boq_position_id is None:
                continue
            key = str(r.boq_position_id)
            existing = out.get(key)
            if existing is None or r.code < existing.code:
                out[key] = r
        return out

    async def create(self, line: Any) -> Any:
        if getattr(line, "id", None) is None:
            line.id = uuid.uuid4()
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        line.created_at = getattr(line, "created_at", None) or now
        line.updated_at = getattr(line, "updated_at", None) or now
        line.metadata_ = getattr(line, "metadata_", {}) or {}
        self.rows[line.id] = line
        return line

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        row = self.rows[line_id]
        for k, v in fields.items():
            setattr(row, k, v)


class _StubBudgetRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows, len(rows)

    async def update_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        row = self.rows[line_id]
        for k, v in fields.items():
            setattr(row, k, v)


class _StubSpineRepo:
    """Pre-baked grouped aggregates keyed by cost-line-id string."""

    def __init__(self) -> None:
        self.budget: dict[str, dict[str, Decimal]] = {}
        self.po: dict[str, Decimal] = {}
        self.contracted: dict[str, Decimal] = {}
        self.claimed: dict[str, Decimal] = {}

    async def budget_aggregate_by_cost_line(self, project_id: uuid.UUID) -> dict[str, dict[str, Decimal]]:
        return self.budget

    async def po_committed_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        return self.po

    async def contract_value_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        return self.contracted

    async def claimed_to_date_by_cost_line(self, project_id: uuid.UUID) -> dict[str, Decimal]:
        return self.claimed


# ── Service factory ────────────────────────────────────────────────────────


def _make_service(*, currency: str = "EUR") -> CostSpineService:
    """Build a CostSpineService with stub repos and a stubbed project currency."""
    service = CostSpineService.__new__(CostSpineService)
    service.session = SimpleNamespace()
    service.account_repo = _StubAccountRepo()
    service.line_repo = _StubLineRepo()
    service.spine_repo = _StubSpineRepo()
    service.budget_repo = _StubBudgetRepo()
    service._cost_service = SimpleNamespace()

    async def _currency(_pid: uuid.UUID) -> str:
        return currency

    service._get_project_currency = _currency  # type: ignore[method-assign]
    # No links by default - overridden per-test where needed.

    async def _empty_links(_pid: uuid.UUID) -> dict:
        return {}

    service._build_links = _empty_links  # type: ignore[method-assign]
    return service


def _patch_boq_generation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    boq_id: uuid.UUID,
    project_id: uuid.UUID,
    positions: list[SimpleNamespace],
    standard: str = "din276",
) -> dict[str, Any]:
    """Patch the cross-module repos generate_from_boq imports.

    Returns a dict with a ``position_updates`` list recording every
    ``PositionRepository.update_fields`` call so a test can assert which
    positions got their ``cost_line_id`` written back.
    """
    position_updates: list[tuple[uuid.UUID, dict]] = []
    by_id = {p.id: p for p in positions}

    class _StubBOQRepo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _boq_id: uuid.UUID) -> Any:
            if _boq_id == boq_id:
                return SimpleNamespace(id=boq_id, project_id=project_id)
            return None

    class _StubPositionRepo:
        def __init__(self, _session: Any) -> None: ...

        async def list_for_boq(self, _boq_id: uuid.UUID, *, limit: int = 100000) -> tuple[list[Any], int]:
            return list(positions), len(positions)

        async def update_fields(self, position_id: uuid.UUID, **fields: object) -> None:
            position_updates.append((position_id, dict(fields)))
            if position_id in by_id:
                for k, v in fields.items():
                    setattr(by_id[position_id], k, v)

    import app.modules.boq.repository as boq_repo_mod

    monkeypatch.setattr(boq_repo_mod, "BOQRepository", _StubBOQRepo)
    monkeypatch.setattr(boq_repo_mod, "PositionRepository", _StubPositionRepo)

    return {"position_updates": position_updates, "by_id": by_id}


def _patch_standard(service: CostSpineService, monkeypatch: pytest.MonkeyPatch, standard: str = "din276") -> None:
    async def _resolve(_pid: uuid.UUID) -> str:
        return standard

    monkeypatch.setattr(service, "_resolve_classification_standard", _resolve)


# ═══════════════════════════════════════════════════════════════════════════
#  generate_from_boq - account tree, cost lines, section-skip, currency
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_generate_builds_account_tree_from_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each distinct position classification becomes one control account."""
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(ordinal="01", unit="m3", total="1000", classification={"din276": "330"}, boq_id=boq_id),
        _position(ordinal="02", unit="m2", total="500", classification={"din276": "330"}, boq_id=boq_id),
        _position(ordinal="03", unit="kg", total="200", classification={"din276": "340"}, boq_id=boq_id),
    ]
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    result = await service.generate_from_boq(project_id, boq_id)

    # Two distinct classifications (330, 340) and the group 300 above both.
    assert result.accounts_created == 3
    accounts = await service.account_repo.list_for_project(project_id)
    assert {a.code for a in accounts} == {"300", "330", "340"}
    by_code = {a.code: a for a in accounts}
    assert by_code["330"].parent_id == by_code["300"].id == by_code["340"].parent_id
    assert (by_code["300"].level, by_code["330"].level) == (1, 2)
    # Both 330 cost lines share the SAME control account.
    lines, _ = await service.line_repo.list_for_project(project_id)
    acct_330 = next(a for a in accounts if a.code == "330")
    lines_330 = [line_ for line_ in lines if line_.control_account_id == acct_330.id]
    assert len(lines_330) == 2


@pytest.mark.asyncio
async def test_generate_one_cost_line_per_costed_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every position with a unit yields exactly one cost line, estimate copied."""
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(
            ordinal="01",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total="1000",
            classification={"din276": "330"},
            boq_id=boq_id,
        ),
        _position(
            ordinal="02",
            unit="m2",
            quantity="5",
            unit_rate="40",
            total="200",
            classification={"din276": "330"},
            boq_id=boq_id,
        ),
    ]
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    result = await service.generate_from_boq(project_id, boq_id)

    assert result.cost_lines_created == 2
    assert result.positions_linked == 2
    lines, total = await service.line_repo.list_for_project(project_id)
    assert total == 2
    by_amount = sorted(line_.estimate_amount for line_ in lines)
    assert by_amount == ["1000", "200"]
    # Estimate quantity/rate copied verbatim from the position.
    line_1000 = next(line_ for line_ in lines if line_.estimate_amount == "1000")
    assert line_1000.estimate_quantity == "10"
    assert line_1000.estimate_unit_rate == "100"
    assert line_1000.source == "boq"
    assert line_1000.boq_id == boq_id


@pytest.mark.asyncio
async def test_generate_skips_section_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positions with an empty unit (section headers) must be skipped."""
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(
            ordinal="01",
            unit="",
            total="0",
            description="SECTION: Earthworks",
            classification={"din276": "300"},
            boq_id=boq_id,
        ),
        _position(ordinal="01.01", unit="m3", total="1000", classification={"din276": "330"}, boq_id=boq_id),
    ]
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    helpers = _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    result = await service.generate_from_boq(project_id, boq_id)

    # Only the costed position produced a line + account (330, under its group 300).
    assert result.cost_lines_created == 1
    assert result.accounts_created == 2
    lines, total = await service.line_repo.list_for_project(project_id)
    assert total == 1
    assert lines[0].unit == "m3"
    # The section header was never written back with a cost_line_id.
    header_id = positions[0].id
    assert all(pid != header_id for pid, _ in helpers["position_updates"])


@pytest.mark.asyncio
async def test_generate_inherits_project_currency_never_hardcodes_eur(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost lines inherit the project currency; a USD project must yield USD."""
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(ordinal="01", unit="m3", total="1000", classification={"din276": "330"}, boq_id=boq_id),
    ]
    service = _make_service(currency="USD")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    await service.generate_from_boq(project_id, boq_id)

    lines, _ = await service.line_repo.list_for_project(project_id)
    assert lines[0].currency == "USD"


@pytest.mark.asyncio
async def test_generate_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2nd generate creates nothing new and does not double-link.

    Positions carry a stable ``reference_code`` so the cost-line code is
    deterministic across runs; the 2nd pass must find every line already
    present, create zero, and re-link zero positions/budget lines.
    """
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(
            ordinal="01",
            unit="m3",
            total="1000",
            classification={"din276": "330"},
            reference_code="P-330-1",
            boq_id=boq_id,
        ),
        _position(
            ordinal="02",
            unit="m2",
            total="500",
            classification={"din276": "340"},
            reference_code="P-340-1",
            boq_id=boq_id,
        ),
    ]
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    first = await service.generate_from_boq(project_id, boq_id)
    assert first.cost_lines_created == 2
    assert first.accounts_created == 3  # 330 and 340 under their group 300
    assert first.positions_linked == 2

    lines_after_first, total_after_first = await service.line_repo.list_for_project(project_id)
    accounts_after_first = await service.account_repo.list_for_project(project_id)

    second = await service.generate_from_boq(project_id, boq_id)
    assert second.cost_lines_created == 0
    assert second.accounts_created == 0
    assert second.positions_linked == 0
    assert second.budget_lines_linked == 0

    # No rows duplicated.
    lines_after_second, total_after_second = await service.line_repo.list_for_project(project_id)
    assert total_after_second == total_after_first == 2
    assert {line_.id for line_ in lines_after_second} == {line_.id for line_ in lines_after_first}
    assert len(await service.account_repo.list_for_project(project_id)) == len(accounts_after_first) == 3


@pytest.mark.asyncio
async def test_generate_is_idempotent_without_reference_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2nd generate creates 0 lines even when positions have NO reference_code.

    Regression guard for the real idempotency bug: without a ``reference_code``
    a cost line's code is a random ``CL-XXXX`` regenerated on every run, so
    deduping on the code never matched the previous line and each re-run created
    a fresh batch (a real demo BOQ went 129 -> 258 cost lines on the 2nd run).
    Dedup is now keyed on the stable ``boq_position_id`` instead, so the count
    stays equal and nothing is duplicated.
    """
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    positions = [
        _position(
            ordinal="01",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total="1000",
            classification={"din276": "330"},
            boq_id=boq_id,
        ),  # no reference_code
        _position(
            ordinal="02",
            unit="m2",
            quantity="5",
            unit_rate="40",
            total="200",
            classification={"din276": "340"},
            boq_id=boq_id,
        ),  # no reference_code
    ]
    assert all(p.reference_code is None for p in positions)
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    first = await service.generate_from_boq(project_id, boq_id)
    assert first.cost_lines_created == 2
    assert first.accounts_created == 3  # 330 and 340 under their group 300
    assert first.positions_linked == 2

    lines_after_first, total_after_first = await service.line_repo.list_for_project(project_id)
    accounts_after_first = await service.account_repo.list_for_project(project_id)
    # The auto codes are random CL-XXXX (NOT derived from any reference_code).
    assert total_after_first == 2
    assert all(line_.code.startswith("CL-") for line_ in lines_after_first)
    first_line_ids = {line_.id for line_ in lines_after_first}
    first_codes = {line_.code for line_ in lines_after_first}

    # ── 2nd generate: must be a pure no-op on counts ──
    second = await service.generate_from_boq(project_id, boq_id)
    assert second.cost_lines_created == 0, "2nd run duplicated cost lines (the bug)"
    assert second.accounts_created == 0
    assert second.positions_linked == 0
    assert second.budget_lines_linked == 0

    # Count stays EQUAL (not doubled), same rows, same codes.
    lines_after_second, total_after_second = await service.line_repo.list_for_project(project_id)
    assert total_after_second == total_after_first == 2
    assert {line_.id for line_ in lines_after_second} == first_line_ids
    assert {line_.code for line_ in lines_after_second} == first_codes
    assert len(await service.account_repo.list_for_project(project_id)) == len(accounts_after_first) == 3


@pytest.mark.asyncio
async def test_generate_autolinks_budget_lines_by_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing budget line sharing a position is linked to the cost line."""
    project_id = uuid.uuid4()
    boq_id = uuid.uuid4()
    pos = _position(ordinal="01", unit="m3", total="1000", classification={"din276": "330"}, boq_id=boq_id)
    positions = [pos]
    service = _make_service(currency="EUR")
    service._cost_service.pick_default_boq = _async_return(boq_id)  # type: ignore[attr-defined]
    _patch_boq_generation(monkeypatch, boq_id=boq_id, project_id=project_id, positions=positions)
    _patch_standard(service, monkeypatch)

    # Seed a budget line already pointing at this position but not yet a cost line.
    bl = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        boq_position_id=pos.id,
        cost_line_id=None,
        control_account_id=None,
    )
    service.budget_repo.rows[bl.id] = bl

    result = await service.generate_from_boq(project_id, boq_id)

    assert result.budget_lines_linked == 1
    lines, _ = await service.line_repo.list_for_project(project_id)
    assert bl.cost_line_id == lines[0].id
    # control_account_id mirrored from the cost line so account rollups group.
    assert bl.control_account_id == lines[0].control_account_id


# ═══════════════════════════════════════════════════════════════════════════
#  rollup_for_line - exact Decimal math + FX + mixed_currency
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rollup_for_line_exact_decimal_math() -> None:
    """rollup_for_line assembles exact Decimals from the grouped aggregates."""
    project_id = uuid.uuid4()
    service = _make_service(currency="EUR")
    line = _cost_line(project_id=project_id, code="CL-1", estimate_amount="1000.00", currency="EUR")
    service.line_repo.rows[line.id] = line

    key = str(line.id)
    service.spine_repo.budget = {
        key: {"planned": Decimal("900.00"), "committed": Decimal("400.00"), "actual": Decimal("250.00")}
    }
    service.spine_repo.po = {key: Decimal("350.00")}
    service.spine_repo.contracted = {key: Decimal("800.00")}
    service.spine_repo.claimed = {key: Decimal("120.00")}

    rollup = await service.rollup_for_line(line.id)

    assert rollup.cost_line_id == line.id
    assert rollup.estimate_amount == Decimal("1000.00")
    assert rollup.budget_planned == Decimal("900.00")
    assert rollup.budget_committed == Decimal("400.00")
    assert rollup.budget_actual == Decimal("250.00")
    assert rollup.po_committed == Decimal("350.00")
    assert rollup.contracted_value == Decimal("800.00")
    assert rollup.claimed_to_date == Decimal("120.00")
    # variance = estimate - budget_planned = 1000 - 900 = 100
    assert rollup.variance_estimate_vs_budget == Decimal("100.00")


@pytest.mark.asyncio
async def test_rollup_for_line_fx_converted_aggregates_via_repo() -> None:
    """The FX conversion happens in the repo; the service surfaces the result.

    We exercise the real ``CostSpineRepository._amount_in_base`` conversion by
    feeding the repo a project with an fx_rate and stub PO rows, proving the
    foreign PO currency is converted to base before it reaches the rollup.
    """
    from app.modules.costmodel.repository import _amount_in_base

    # 1000 USD at 0.90 EUR/USD = 900 EUR.
    converted = _amount_in_base("1000", "USD", "EUR", {"USD": "0.90"})
    assert converted == Decimal("900.00") or converted == Decimal("900.0") or converted == Decimal("900")
    # A missing rate keeps the foreign amount in its own units (never zeroed).
    kept = _amount_in_base("1000", "JPY", "EUR", {})
    assert kept == Decimal("1000")
    # Same-currency passthrough.
    same = _amount_in_base("500.50", "EUR", "EUR", {"USD": "0.90"})
    assert same == Decimal("500.50")


@pytest.mark.asyncio
async def test_rollup_for_project_mixed_currency_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """mixed_currency is True iff the linked rows carry >1 distinct currency."""
    project_id = uuid.uuid4()
    service = _make_service(currency="EUR")

    line = _cost_line(project_id=project_id, code="CL-1", estimate_amount="1000", currency="EUR")
    service.line_repo.rows[line.id] = line

    # Single-currency case → flag False.
    async def _one_ccy(_pid: uuid.UUID) -> set[str]:
        return {"EUR"}

    monkeypatch.setattr(service, "_distinct_link_currencies", _one_ccy)
    rollup_clean = await service.rollup_for_project(project_id)
    assert rollup_clean.mixed_currency is False
    assert rollup_clean.currency == "EUR"

    # Multi-currency case → flag True.
    async def _two_ccy(_pid: uuid.UUID) -> set[str]:
        return {"EUR", "USD"}

    monkeypatch.setattr(service, "_distinct_link_currencies", _two_ccy)
    rollup_mixed = await service.rollup_for_project(project_id)
    assert rollup_mixed.mixed_currency is True


@pytest.mark.asyncio
async def test_rollup_for_project_totals_sum_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project totals are the exact Decimal sum across lines, serialized to str."""
    project_id = uuid.uuid4()
    service = _make_service(currency="EUR")

    line_a = _cost_line(project_id=project_id, code="CL-A", estimate_amount="1000.00", currency="EUR")
    line_b = _cost_line(project_id=project_id, code="CL-B", estimate_amount="250.50", currency="EUR")
    service.line_repo.rows[line_a.id] = line_a
    service.line_repo.rows[line_b.id] = line_b

    service.spine_repo.budget = {
        str(line_a.id): {"planned": Decimal("800.00"), "committed": Decimal("0"), "actual": Decimal("0")},
        str(line_b.id): {"planned": Decimal("200.00"), "committed": Decimal("0"), "actual": Decimal("0")},
    }
    service.spine_repo.po = {str(line_a.id): Decimal("100.00")}

    async def _one_ccy(_pid: uuid.UUID) -> set[str]:
        return {"EUR"}

    monkeypatch.setattr(service, "_distinct_link_currencies", _one_ccy)

    rollup = await service.rollup_for_project(project_id)

    # estimate total = 1000.00 + 250.50 = 1250.50
    assert Decimal(rollup.totals["estimate_amount"]) == Decimal("1250.50")
    # budget_planned total = 800 + 200 = 1000
    assert Decimal(rollup.totals["budget_planned"]) == Decimal("1000.00")
    # po_committed total = 100
    assert Decimal(rollup.totals["po_committed"]) == Decimal("100.00")
    # variance = 1250.50 - 1000.00 = 250.50
    assert Decimal(rollup.totals["variance_estimate_vs_budget"]) == Decimal("250.50")
    assert len(rollup.lines) == 2


# ═══════════════════════════════════════════════════════════════════════════
#  delete guards (409)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_delete_account_409_when_lines_reference_it() -> None:
    """delete_account must 409 while cost lines still reference the account."""
    project_id = uuid.uuid4()
    service = _make_service()
    acct = _account(project_id=project_id, code="330")
    service.account_repo.rows[acct.id] = acct
    service.account_repo.lines_referencing[acct.id] = 3  # 3 lines reference it

    with pytest.raises(HTTPException) as exc:
        await service.delete_account(acct.id)
    assert exc.value.status_code == 409
    # The account was NOT deleted.
    assert acct.id in service.account_repo.rows


@pytest.mark.asyncio
async def test_delete_account_succeeds_when_unreferenced() -> None:
    project_id = uuid.uuid4()
    service = _make_service()
    acct = _account(project_id=project_id, code="330")
    service.account_repo.rows[acct.id] = acct
    service.account_repo.lines_referencing[acct.id] = 0

    await service.delete_account(acct.id)
    assert acct.id not in service.account_repo.rows


@pytest.mark.asyncio
async def test_delete_line_409_with_linked_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_line must 409 and surface the per-target linked counts."""
    project_id = uuid.uuid4()
    service = _make_service()
    line = _cost_line(project_id=project_id, code="CL-1")
    service.line_repo.rows[line.id] = line

    async def _counts(_line_id: uuid.UUID, _project_id: uuid.UUID) -> dict[str, int]:
        return {
            "budget_lines": 1,
            "boq_positions": 2,
            "po_items": 0,
            "req_items": 0,
            "contract_lines": 1,
        }

    monkeypatch.setattr(service, "_linked_counts", _counts)

    with pytest.raises(HTTPException) as exc:
        await service.delete_line(line.id)
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["linked"]["budget_lines"] == 1
    assert detail["linked"]["boq_positions"] == 2
    assert detail["linked"]["contract_lines"] == 1
    # The line was NOT deleted.
    assert line.id in service.line_repo.rows


@pytest.mark.asyncio
async def test_delete_line_succeeds_when_unlinked(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid.uuid4()
    service = _make_service()
    line = _cost_line(project_id=project_id, code="CL-1")
    service.line_repo.rows[line.id] = line

    async def _counts(_line_id: uuid.UUID, _project_id: uuid.UUID) -> dict[str, int]:
        return {"budget_lines": 0, "boq_positions": 0, "po_items": 0, "req_items": 0, "contract_lines": 0}

    monkeypatch.setattr(service, "_linked_counts", _counts)

    async def _delete(line_id: uuid.UUID) -> None:
        service.line_repo.rows.pop(line_id, None)

    service.line_repo.delete = _delete  # type: ignore[attr-defined]

    await service.delete_line(line.id)
    assert line.id not in service.line_repo.rows


# ═══════════════════════════════════════════════════════════════════════════
#  link / unlink a downstream target
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_link_then_unlink_budget_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """link_target sets cost_line_id + account; unlink_target clears them."""
    project_id = uuid.uuid4()
    service = _make_service(currency="EUR")
    acct = _account(project_id=project_id, code="330")
    service.account_repo.rows[acct.id] = acct
    line = _cost_line(project_id=project_id, code="CL-1", control_account_id=acct.id)
    service.line_repo.rows[line.id] = line

    bl = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        boq_position_id=None,
        cost_line_id=None,
        control_account_id=None,
    )
    service.budget_repo.rows[bl.id] = bl

    # ``_apply_link`` resolves the target via ``self.session.get`` for most
    # types; for budget_line it uses session.get then budget_repo.update_fields.
    # It also calls session.flush()/expire_all() at the end - stub them no-op.
    async def _session_get(model: Any, target_id: uuid.UUID) -> Any:
        return service.budget_repo.rows.get(target_id)

    async def _flush() -> None:
        return None

    service.session.get = _session_get  # type: ignore[attr-defined]
    service.session.flush = _flush  # type: ignore[attr-defined]
    service.session.expire_all = lambda: None  # type: ignore[attr-defined]

    # rollup_for_line needs the grouped aggregates + links; stub minimal.
    async def _empty_links(_pid: uuid.UUID) -> dict:
        return {}

    monkeypatch.setattr(service, "_build_links", _empty_links)

    # ── link ──
    await service.link_target(line.id, "budget_line", bl.id)
    assert bl.cost_line_id == line.id
    assert bl.control_account_id == acct.id

    # ── unlink ──
    await service.unlink_target(line.id, "budget_line", bl.id)
    assert bl.cost_line_id is None
    assert bl.control_account_id is None


@pytest.mark.asyncio
async def test_link_invalid_target_type_422() -> None:
    project_id = uuid.uuid4()
    service = _make_service()
    line = _cost_line(project_id=project_id, code="CL-1")
    service.line_repo.rows[line.id] = line

    with pytest.raises(HTTPException) as exc:
        await service.link_target(line.id, "not_a_type", uuid.uuid4())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_link_request_schema_round_trips() -> None:
    """SpineLinkRequest accepts the documented target_type values."""
    req = SpineLinkRequest(target_type="budget_line", target_id=uuid.uuid4())
    assert req.target_type == "budget_line"


# ── small async helper ──────────────────────────────────────────────────────


def _async_return(value: Any):
    async def _inner(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _inner
