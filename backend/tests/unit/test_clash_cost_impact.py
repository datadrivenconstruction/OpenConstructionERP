# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Baseline unit tests for the clash_cost_impact money pipeline.

Three layers, all in-process — no real DB engine, no network:

* **Pure arithmetic** — exercise the rework + labour math through the
  service's :meth:`_compute_impact` kernel with hand-built fakes for
  ``ClashResult`` + ``Project`` + BOQ ``Position``. Asserts that the
  pipeline is **Decimal-accurate** (no IEEE-754 drift on 1/3-style
  fractions) and that the rollup loop does not accumulate per-clash
  2-dp rounding.

* **Money-rounding direction** — pin that we use ROUND_HALF_UP (the
  conventional money mode), not Python's default ROUND_HALF_EVEN
  ("banker's rounding"). 0.125 must round to 0.13 on the wire.

* **Auth required** — mount the router on a minimal FastAPI app with no
  auth deps overridden; an unauthenticated request to either endpoint
  must return 401 (the ``RequirePermission("clash.read")`` dependency
  trips the JWT gate first).

Per ``feedback_test_isolation.md`` DATABASE_URL is redirected to a fresh
temp SQLite file BEFORE ``app`` is imported, so an accidental engine
touch can never bleed into the dev / prod DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-cost-impact-"))
_TMP_DB = _TMP_DIR / "clash_cost_impact.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.modules.clash_cost_impact.router import router  # noqa: E402
from app.modules.clash_cost_impact.service import (  # noqa: E402
    ClashCostImpactService,
    _money_round,
)

# ── Fakes ────────────────────────────────────────────────────────────────


def _fake_position(total: str, *, cad_ids: list[str] | None = None) -> SimpleNamespace:
    """Mimic the BOQ ``Position`` columns the service reads.

    Real ``Position`` stores money as ``String`` to dodge SQLite's REAL
    precision loss (see ``backend/app/modules/boq/models.py``) — we mirror
    that here so ``_to_decimal(p.total)`` exercises its real string path.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        ordinal="01.01",
        description="Concrete wall, 240mm",
        total=total,  # canonical: STRING money on the ORM
        cad_element_ids=cad_ids or [],
    )


def _fake_clash(
    *,
    a_stable: str = "STBL-A",
    b_stable: str = "STBL-B",
    a_disc: str = "structural",
    b_disc: str = "mechanical",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        a_stable_id=a_stable,
        b_stable_id=b_stable,
        a_discipline=a_disc,
        b_discipline=b_disc,
    )


def _fake_project(currency: str = "EUR", *, meta: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        currency=currency,
        metadata_=meta or {},
    )


# ── Pure: decimal accuracy of _compute_impact ────────────────────────────


def test_compute_impact_is_decimal_accurate_on_thirds():
    """A position total of 100/3 EUR feeds rework_total without IEEE drift.

    100/3 = 33.33333… Decimal exact. 10% rework_factor of 100/3 is exactly
    10/3 = 3.3333… The wire boundary rounds to 2dp (3.33). What we pin
    here: the **internal** ``total`` Decimal we return alongside the
    payload is exact down to the last preserved digit — NOT a float that
    quietly converted to 3.3333333333333335 along the way.
    """
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(currency="EUR")
    clash = _fake_clash(a_stable="STBL-A", b_stable="STBL-B")
    # Three positions summing to 100/3 → rework_total = 33.33333…
    affected = [
        _fake_position(total="11.11111111", cad_ids=["STBL-A"]),
        _fake_position(total="11.11111111", cad_ids=["STBL-A"]),
        _fake_position(total="11.11111111", cad_ids=["STBL-A"]),
    ]
    payload, total_decimal = svc._compute_impact(clash, project, affected)

    # Rework total before factor — exact Decimal arithmetic.
    expected_rework = Decimal("33.33333333")
    expected_rework_subtotal = expected_rework * Decimal("0.10")  # = 3.333333333
    # struct ↔ mech labour: 8h × 50.0 = 400.0
    expected_labour_subtotal = Decimal("400.0")
    expected_total = expected_rework_subtotal + expected_labour_subtotal

    # The exact Decimal must round-trip out of the kernel unchanged.
    assert total_decimal == expected_total
    # ...and crucially the kernel must still be holding Decimal type
    # (a stray ``float()`` cast anywhere in the rework / labour chain
    # would surface here as the wrong type).
    assert isinstance(total_decimal, Decimal)
    # The 2-dp wire total is the conventionally-rounded view of the same
    # number — assert it's a string-safe float.
    assert payload["total_estimate"] == _money_round(expected_total)
    assert payload["confidence"] == "high"
    assert payload["currency"] == "EUR"


def test_compute_impact_no_boq_overlap_yields_labour_only_medium():
    """No BOQ position touches the clash → only labour subtotal, ``medium``."""
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(currency="USD")
    clash = _fake_clash(
        a_stable="STBL-X",
        b_stable="STBL-Y",
        a_disc="architectural",
        b_disc="electrical",  # 4h
    )
    payload, total_decimal = svc._compute_impact(clash, project, [])

    # 4h × 50.0 = 200.0 labour only; no rework.
    assert total_decimal == Decimal("200.0")
    assert payload["total_estimate"] == 200.0
    assert payload["components"]["rework_subtotal"] == 0.0
    assert payload["confidence"] == "medium"
    # Currency authoritatively reflects the project — no EUR fallback.
    assert payload["currency"] == "USD"


def test_compute_impact_no_guids_yields_low_confidence_zero():
    """Both stable_ids empty → labour suppressed, confidence = ``low``."""
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(currency="EUR")
    clash = _fake_clash(a_stable="", b_stable="")
    payload, total_decimal = svc._compute_impact(clash, project, [])
    assert total_decimal == Decimal("0")
    assert payload["total_estimate"] == 0.0
    assert payload["confidence"] == "low"


def test_money_round_uses_half_up_not_bankers():
    """0.125 → 0.13 on the wire. Pin away from Decimal's HALF_EVEN default."""
    # If the helper had ever silently regressed to ROUND_HALF_EVEN
    # ("banker's rounding"), 0.125 would round DOWN to 0.12 — a quiet
    # 1-cent loss every time the cents end in .x25. That's wrong for
    # money: every QS handbook uses ROUND_HALF_UP.
    assert _money_round(Decimal("0.125")) == 0.13
    assert _money_round(Decimal("0.135")) == 0.14
    # And the standard "round 0.5 up" sanity check.
    assert _money_round(Decimal("0.5")) == 0.5  # already 2dp


def test_compute_impact_per_project_metadata_overrides_apply():
    """Per-project rework_factor + blended_rate from metadata are honoured."""
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(
        currency="EUR",
        meta={
            "clash_cost_impact": {
                # Accept percent form (20 → 0.20).
                "rework_factor": "20",
                "blended_rate": "65.0",
            }
        },
    )
    clash = _fake_clash(a_disc="structural", b_disc="mechanical")  # 8h
    affected = [_fake_position(total="1000.00", cad_ids=["STBL-A"])]
    payload, total_decimal = svc._compute_impact(clash, project, affected)
    # rework: 1000 × 0.20 = 200; labour: 8 × 65 = 520; total = 720.
    assert total_decimal == Decimal("720.00")
    assert payload["total_estimate"] == 720.0
    assert payload["components"]["rework_factor_pct"] == 20.0
    assert payload["components"]["blended_rate"] == 65.0


def test_rollup_returns_exact_decimal_no_accumulated_rounding(monkeypatch):
    """A 3-clash rollup whose per-clash totals carry sub-cent tails must
    sum to the EXACT Decimal sum, NOT the sum of the 2-dp-rounded floats.

    Without the fix this asserts: per-clash totals of 0.005 each round to
    0.01 (half-up), summed as floats = 0.03, but the exact sum is 0.015
    → wire shows 0.02 if we sum Decimals first then round. We MUST sum
    Decimals first.
    """
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(currency="EUR")

    # Three clashes whose computed totals each have a 0.005 tail that
    # would round half-up to a different value than the exact sum.
    clashes = [_fake_clash(a_stable=f"S-{i}", b_stable="", a_disc="x", b_disc="y") for i in range(3)]

    # Patch _compute_impact to return our chosen tails.
    sub_cent = Decimal("0.005")

    def _fake_compute(_self, _clash, _project, _affected):
        # Payload is unused by the rollup loop (only ``total_decimal``);
        # we still build it so the function honours its contract.
        return (
            {"total_estimate": _money_round(sub_cent)},  # = 0.01 per clash
            sub_cent,  # exact Decimal
        )

    monkeypatch.setattr(ClashCostImpactService, "_compute_impact", _fake_compute)

    # Bypass the DB loaders by patching them too.
    async def _fake_load_project(_self, _pid):
        return project

    async def _fake_open(_self, _pid, *, status_filter="open"):
        return clashes

    async def _fake_positions(_self, _pid):
        return []

    monkeypatch.setattr(ClashCostImpactService, "_load_project", _fake_load_project)
    monkeypatch.setattr(ClashCostImpactService, "_open_clashes_for_project", _fake_open)
    monkeypatch.setattr(ClashCostImpactService, "_positions_for_project", _fake_positions)

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(svc.rollup_for_project(project.id, status_filter="open"))
    assert result is not None
    # Exact sum: 3 × 0.005 = 0.015 → ROUND_HALF_UP → 0.02.
    # If we summed the rounded floats instead we'd get 0.01 + 0.01 + 0.01
    # = 0.03 — the regression we are guarding against.
    assert result["total_open_impact"] == 0.02
    assert result["clash_count"] == 3
    assert result["currency"] == "EUR"


def test_rollup_empty_project_uses_project_currency_not_eur_hardcode():
    """A currency-less project gets ``""``, not a silent ``"EUR"`` fallback.

    Per ``v3_db_eur_defaults_killed.md`` — no DB-level EUR defaults. The
    service-layer is required to surface what the project actually has.
    """
    svc = ClashCostImpactService(session=None)  # type: ignore[arg-type]
    project = _fake_project(currency="")  # explicitly currency-less

    import asyncio
    import types

    async def _fake_load_project(_self, _pid):
        return project

    async def _fake_open(_self, _pid, *, status_filter="open"):
        return []  # no clashes → early return path

    svc._load_project = types.MethodType(_fake_load_project, svc)  # type: ignore[method-assign]
    svc._open_clashes_for_project = types.MethodType(_fake_open, svc)  # type: ignore[method-assign]

    result = asyncio.get_event_loop().run_until_complete(svc.rollup_for_project(project.id, status_filter="open"))
    assert result is not None
    assert result["currency"] == ""
    assert result["total_open_impact"] == 0.0


# ── Auth: unauthenticated requests return 401 ────────────────────────────


@pytest.fixture
def unauth_client() -> TestClient:
    """Mount the router with no auth deps overridden.

    ``RequirePermission("clash.read")`` chains through
    ``get_current_user_payload`` which raises 401 when no Bearer token
    is present — that's the gate we are pinning here.
    """
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/clash-cost-impact")
    return TestClient(app)


def test_clash_impact_unauthenticated_returns_401(unauth_client: TestClient):
    """``GET /clash/{id}/impact`` 401s when no JWT is presented."""
    resp = unauth_client.get(f"/api/v1/clash-cost-impact/clash/{uuid.uuid4()}/impact")
    assert resp.status_code == 401, resp.text


def test_project_rollup_unauthenticated_returns_401(unauth_client: TestClient):
    """``GET /project/{id}/rollup`` 401s when no JWT is presented."""
    resp = unauth_client.get(f"/api/v1/clash-cost-impact/project/{uuid.uuid4()}/rollup")
    assert resp.status_code == 401, resp.text
