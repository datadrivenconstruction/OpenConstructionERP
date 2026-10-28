# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the admin-tunable hours-saved factors (PostgreSQL, py3.12).

Exercises the ``oe_value_time_factor`` read / upsert layer end to end: listing
defaults vs overrides, upserting an override (and seeing it flow into the
effective factor map), reverting to the default deleting the row, validation
rejecting bad values atomically, and that one tenant's overrides never bleed into
another tenant's effective factors.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.value.models import TimeSavedFactor
from app.modules.value.time_factors_service import (
    list_factors,
    resolve_effective_factors,
    set_factors,
)
from app.modules.value.time_saved import DEFAULT_FACTORS
from tests._pg import transactional_session

RFI = ("rfi", "rfi_answered")


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


def _tenant() -> str:
    return str(uuid.uuid4())


async def _override_count(session: AsyncSession, tenant_id: str) -> int:
    stmt = select(func.count()).select_from(TimeSavedFactor).where(TimeSavedFactor.tenant_id == tenant_id)
    return int((await session.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_list_shows_defaults_when_unset(session: AsyncSession) -> None:
    """With no overrides, every seed pair is listed as an inherited default."""
    tenant = _tenant()
    rows = await list_factors(session, tenant)

    assert len(rows) == len(DEFAULT_FACTORS)
    by_key = {(r.module, r.action): r for r in rows}
    rfi = by_key[RFI]
    assert rfi.minutes == DEFAULT_FACTORS[RFI]
    assert rfi.default_minutes == DEFAULT_FACTORS[RFI]
    assert rfi.is_override is False


@pytest.mark.asyncio
async def test_set_override_persists_and_resolves(session: AsyncSession) -> None:
    """An override is stored, marked, and shows up in the effective factor map."""
    tenant = _tenant()
    rows = await set_factors(session, tenant, [(RFI[0], RFI[1], "40")])

    rfi = {(r.module, r.action): r for r in rows}[RFI]
    assert rfi.minutes == Decimal("40.00")
    assert rfi.default_minutes == DEFAULT_FACTORS[RFI]
    assert rfi.is_override is True
    assert await _override_count(session, tenant) == 1

    effective = await resolve_effective_factors(session, tenant)
    assert effective[RFI] == Decimal("40.00")
    # An untouched pair still resolves to its default.
    assert effective[("takeoff", "takeoff_parsed")] == DEFAULT_FACTORS[("takeoff", "takeoff_parsed")]


@pytest.mark.asyncio
async def test_reverting_to_default_deletes_override(session: AsyncSession) -> None:
    """Setting a factor back to its seed default drops the override row."""
    tenant = _tenant()
    await set_factors(session, tenant, [(RFI[0], RFI[1], "40")])
    assert await _override_count(session, tenant) == 1

    # Re-set to the documented default -> the override is cleared.
    rows = await set_factors(session, tenant, [(RFI[0], RFI[1], str(DEFAULT_FACTORS[RFI]))])
    assert await _override_count(session, tenant) == 0
    rfi = {(r.module, r.action): r for r in rows}[RFI]
    assert rfi.is_override is False
    assert rfi.minutes == DEFAULT_FACTORS[RFI]


@pytest.mark.asyncio
async def test_upsert_updates_existing_row(session: AsyncSession) -> None:
    """Re-overriding the same pair updates the one row, never duplicating it."""
    tenant = _tenant()
    await set_factors(session, tenant, [(RFI[0], RFI[1], "40")])
    await set_factors(session, tenant, [(RFI[0], RFI[1], "55")])

    assert await _override_count(session, tenant) == 1
    effective = await resolve_effective_factors(session, tenant)
    assert effective[RFI] == Decimal("55.00")


@pytest.mark.asyncio
async def test_tenant_only_pair_is_creditable(session: AsyncSession) -> None:
    """An override for a pair outside the seed map is stored and resolved."""
    tenant = _tenant()
    extra = ("safety", "toolbox_talk_logged")
    rows = await set_factors(session, tenant, [(extra[0], extra[1], "12")])

    by_key = {(r.module, r.action): r for r in rows}
    assert by_key[extra].minutes == Decimal("12.00")
    assert by_key[extra].default_minutes is None
    assert by_key[extra].is_override is True

    effective = await resolve_effective_factors(session, tenant)
    assert effective[extra] == Decimal("12.00")


@pytest.mark.asyncio
async def test_negative_value_rejected_atomically(session: AsyncSession) -> None:
    """A negative minute value raises and writes nothing from the batch."""
    tenant = _tenant()
    with pytest.raises(ValueError, match="negative"):
        await set_factors(
            session,
            tenant,
            [
                (RFI[0], RFI[1], "30"),  # valid, but the batch must still roll back
                ("takeoff", "takeoff_parsed", "-5"),
            ],
        )
    # All-or-nothing: the valid row was not persisted either.
    assert await _override_count(session, tenant) == 0


@pytest.mark.asyncio
async def test_non_numeric_value_rejected(session: AsyncSession) -> None:
    """A non-numeric minute value is a ValueError (the router maps it to 422)."""
    tenant = _tenant()
    with pytest.raises(ValueError, match="number"):
        await set_factors(session, tenant, [(RFI[0], RFI[1], "lots")])
    assert await _override_count(session, tenant) == 0


@pytest.mark.asyncio
async def test_excessive_value_rejected(session: AsyncSession) -> None:
    """A value above the per-action cap is rejected."""
    tenant = _tenant()
    with pytest.raises(ValueError, match="exceed"):
        await set_factors(session, tenant, [(RFI[0], RFI[1], "9999")])
    assert await _override_count(session, tenant) == 0


@pytest.mark.asyncio
async def test_blank_module_or_action_rejected(session: AsyncSession) -> None:
    """A blank module/action is rejected before any write."""
    tenant = _tenant()
    with pytest.raises(ValueError, match="required"):
        await set_factors(session, tenant, [("", "rfi_answered", "30")])
    assert await _override_count(session, tenant) == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_overrides_are_tenant_isolated(session: AsyncSession) -> None:
    """One tenant's override never leaks into another tenant's effective factors."""
    tenant_a = _tenant()
    tenant_b = _tenant()
    await set_factors(session, tenant_a, [(RFI[0], RFI[1], "40")])

    eff_a = await resolve_effective_factors(session, tenant_a)
    eff_b = await resolve_effective_factors(session, tenant_b)
    assert eff_a[RFI] == Decimal("40.00")
    # B sees only the seed default - A's tuning is invisible.
    assert eff_b[RFI] == DEFAULT_FACTORS[RFI]
    # B's listing reports no overrides.
    assert all(not r.is_override for r in await list_factors(session, tenant_b))


@pytest.mark.asyncio
async def test_none_tenant_yields_defaults(session: AsyncSession) -> None:
    """An unresolved tenant falls back to the plain defaults, never leaking rows."""
    # Seed an override under a real tenant so the table is non-empty.
    await set_factors(session, _tenant(), [(RFI[0], RFI[1], "40")])

    effective = await resolve_effective_factors(session, None)
    assert effective == dict(DEFAULT_FACTORS)
    assert all(not r.is_override for r in await list_factors(session, None))
