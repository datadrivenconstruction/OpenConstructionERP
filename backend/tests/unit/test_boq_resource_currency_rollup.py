"""Issue #111 (skolodi follow-up) — resource-level currency in section subtotal.

The owner's v2.9.29 fix and #131 converted a position priced in a foreign
currency *via* ``metadata.currency``.  The contributor's actual data
(``Prueba_2.csv``) is a DIFFERENT shape the position-level path can never
catch:

* project BASE currency = ARS
* additional currency = USD, rate 1415  (1 USD = 1415 ARS)
* a position whose ``metadata.currency`` is **unset** but whose
  ``metadata.resources`` are priced in **USD**

At write time ``update_position`` derives the position ``unit_rate`` as
``Σ(r.quantity × r.unit_rate)`` with NO currency conversion, so the stored
position ``total`` is a raw number that silently mixes USD resource money
into an ARS-base project.  Because the position carries no
``metadata.currency``, ``_position_total_in_base`` treats the whole total
as base ARS — a USD 25 000 resource is rolled up as 25 000 ARS instead of
25 000 × 1415 = 35 375 000 ARS.  The defect surfaces in **two** places the
contributor circled: the per-position resource subtotal AND the section
subtotal (both read the same un-converted number).

These tests pin the resource-currency-aware rollup.  Test isolation uses the
shared PostgreSQL helpers in ``tests._pg``: each test runs inside an outer
transaction that is rolled back on teardown, so the production database is
never touched.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_resource_currency_rollup.py -v --tb=short
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.boq.service import (
    BOQService,
    _leaf_total_base_with_resources,
    _resource_total_in_base,
)
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        from app.modules.users.models import User

        s.add(
            User(
                id=OWNER_ID,
                email=f"o-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="O",
            )
        )
        await s.flush()
        await s.commit()
        yield s


# ── Pure helper: resource-currency-aware leaf total ──────────────────────


def test_resource_total_in_base_converts_foreign_resource():
    # One USD resource, base ARS, rate 1 USD = 1415 ARS.
    resources = [{"name": "Recurso_1", "quantity": 1, "unit_rate": 25000, "currency": "USD"}]
    out = _resource_total_in_base(resources, {"USD": "1415"}, "ARS")
    assert out == pytest.approx(25000 * 1415)  # 35_375_000


def test_leaf_total_base_with_resources_scales_by_position_qty():
    """Prueba_2 position 0040: pos qty 2, one USD resource @ 25000.

    Stored position total = 50000 (qty 2 × resource-derived unit_rate
    25000), currency UNSET.  Correct base value = 50000 × 1415.
    """

    class _Pos:
        total = "50000"
        quantity = "2"
        metadata_ = {
            "resources": [
                {
                    "name": "Recurso_1",
                    "code": "",
                    "type": "operator",
                    "unit": "HH",
                    "quantity": 1,
                    "unit_rate": 25000,
                    "total": 25000,
                    "currency": "USD",
                }
            ]
        }

    out = _leaf_total_base_with_resources(_Pos(), {"USD": "1415"}, "ARS")
    assert out == Decimal("70750000.00")  # 50000 × 1415


def test_leaf_total_base_without_resources_uses_position_currency():
    """Non-resource position keeps the existing metadata.currency path."""

    class _Pos:
        total = "500"
        quantity = "50"
        metadata_ = {"currency": "USD"}

    out = _leaf_total_base_with_resources(_Pos(), {"USD": "1.10"}, "EUR")
    assert out == Decimal("550.00")


def test_leaf_total_base_mixed_resource_currencies():
    """A position with a USD resource AND an ARS resource converts only
    the USD portion. pos qty 1 so total == unit_rate sum."""

    class _Pos:
        total = "26000"  # 25000 USD-priced + 1000 ARS-priced (raw mix)
        quantity = "1"
        metadata_ = {
            "resources": [
                {"name": "A", "quantity": 1, "unit_rate": 25000, "currency": "USD"},
                {"name": "B", "quantity": 1, "unit_rate": 1000, "currency": "ARS"},
            ]
        }

    out = _leaf_total_base_with_resources(_Pos(), {"USD": "1415"}, "ARS")
    # 25000×1415 (USD) + 1000 (already ARS) = 35_376_000
    assert out == pytest.approx(25000 * 1415 + 1000)


# ── Service-level rollup mirroring Prueba_2.csv ──────────────────────────


async def _make_prueba2_boq(session):
    """Recreate the exact ``Prueba_2.csv`` scenario.

    Base ARS project, USD additional currency @ 1415.  One section with
    four leaf positions; position 0040 is resource-driven in USD.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="Prueba_2",
            owner_id=OWNER_ID,
            currency="ARS",
            fx_rates=[{"code": "USD", "rate": "1415", "label": "USD"}],
        )
    )
    await session.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project_id, name="Prueba_2 BOQ")
    session.add(boq)
    await session.flush()

    section = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01",
        description="Seccion",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=0,
    )
    session.add(section)
    await session.flush()

    # 0010 / 0020 / 0030 — plain ARS positions (no currency, no resources).
    for ordn, qty, rate, tot in (
        ("0010", "9.4248", "10", "94.248"),
        ("0020", "3", "1", "3"),
        ("0030", "24", "3", "72"),
    ):
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=ordn,
                description=f"p{ordn}",
                unit="m2",
                quantity=qty,
                unit_rate=rate,
                total=tot,
                sort_order=int(ordn),
            )
        )
    # 0040 — qty 2, one USD resource @ 25000 (Prueba_2 exact shape).
    session.add(
        Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="0040",
            description="prueba 4",
            unit="m2",
            quantity="2",
            unit_rate="25000",
            total="50000",
            metadata_={
                "resources": [
                    {
                        "name": "Recurso_1",
                        "code": "",
                        "type": "operator",
                        "unit": "HH",
                        "quantity": 1,
                        "unit_rate": 25000,
                        "total": 25000,
                        "currency": "USD",
                    }
                ]
            },
            sort_order=40,
        )
    )
    await session.commit()
    return boq


@pytest.mark.asyncio
async def test_prueba2_section_subtotal_converts_usd_resource(session):
    boq = await _make_prueba2_boq(session)
    service = BOQService(session)
    structured = await service.get_boq_structured(boq.id)

    # Plain ARS positions: 94.248 + 3 + 72 = 169.248
    # Position 0040: 50000 USD × 1415 = 70_750_000 ARS
    expected = Decimal("94.248") + Decimal("3") + Decimal("72") + Decimal("70750000")

    assert len(structured.sections) == 1
    # Place #1 — the section subtotal the contributor circled. The rollup
    # returns Decimal now (v3 §10); coerce before approx — pytest.approx
    # cannot subtract a Decimal from a float.
    assert float(structured.sections[0].subtotal) == pytest.approx(float(expected))
    assert float(structured.direct_cost) == pytest.approx(float(expected))
    # Grand Total has no markups here so it equals direct cost.
    assert float(structured.grand_total) == pytest.approx(float(expected))
    # The OLD buggy value would have been ~50_169.248 (USD summed as ARS).
    assert structured.direct_cost > 70_000_000


@pytest.mark.asyncio
async def test_prueba2_export_fx_frozen_table(session):
    """Enhancement (b): FX rates are per-project and frozen into export."""
    boq = await _make_prueba2_boq(session)
    service = BOQService(session)
    base, fx_map = await service.get_export_fx(boq.id)
    assert base == "ARS"
    assert fx_map == {"USD": "1415"}
