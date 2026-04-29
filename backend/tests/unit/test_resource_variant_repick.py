"""Unit tests for the per-resource variant re-pick helper logic.

These tests exercise the pure-data branch of
``BOQService.repick_resource_variant`` indirectly through the
``_stamp_resource_variant_snapshots`` helper plus the validation path
the service runs before mutating the row. They are intentionally
DB-free — the in-process SQLite session is not required to verify:

* available_variants must be present and non-empty
* variant_code must resolve in available_variants
* resource_idx must be in range
* selecting a variant updates only that resource's snapshot

Higher-level HTTP coverage (router auth, full PATCH round-trip, audit
log emission) lives in ``tests/integration/test_boq_variants.py`` once
the integration test client is wired up.

Run::

    cd backend
    python -m pytest tests/unit/test_resource_variant_repick.py -v
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

import pytest

from app.modules.boq.service import _stamp_resource_variant_snapshots


def _make_metadata() -> dict[str, Any]:
    """Two variant-bearing resources, both already snapshotted."""
    return {
        "currency": "EUR",
        "resources": [
            {
                "name": "Concrete C30/37",
                "code": "BET.C30",
                "type": "material",
                "unit": "m3",
                "quantity": 1.0,
                "unit_rate": 185.0,
                "total": 185.0,
                "variant": {"label": "C30/37 ready-mix", "price": 185.0, "index": 1},
                "variant_snapshot": {
                    "label": "C30/37 ready-mix",
                    "rate": 185.0,
                    "currency": "EUR",
                    "captured_at": "2026-04-29T10:00:00+00:00",
                    "source": "user_pick",
                },
                "available_variants": [
                    {"index": 0, "label": "C25/30 ready-mix", "price": 165.0, "price_per_unit": None},
                    {"index": 1, "label": "C30/37 ready-mix", "price": 185.0, "price_per_unit": None},
                    {"index": 2, "label": "C35/45 ready-mix", "price": 215.0, "price_per_unit": None},
                ],
            },
            {
                "name": "Reinforcement steel 8mm",
                "code": "REB.8MM",
                "type": "material",
                "unit": "kg",
                "quantity": 90.0,
                "unit_rate": 1.50,
                "total": 135.0,
                "variant": {"label": "8mm BSt500", "price": 1.50, "index": 0},
                "variant_snapshot": {
                    "label": "8mm BSt500",
                    "rate": 1.50,
                    "currency": "EUR",
                    "captured_at": "2026-04-29T10:00:00+00:00",
                    "source": "user_pick",
                },
                "available_variants": [
                    {"index": 0, "label": "8mm BSt500", "price": 1.50, "price_per_unit": None},
                    {"index": 1, "label": "10mm BSt500", "price": 1.65, "price_per_unit": None},
                ],
            },
        ],
    }


# ── Idempotency: stamping a metadata that already carries matching snapshots
#    leaves captured_at unchanged on every resource ────────────────────────


def test_stamp_resource_variants_idempotent_with_unchanged_picks() -> None:
    meta = _make_metadata()
    before = [deepcopy(r["variant_snapshot"]) for r in meta["resources"]]
    _stamp_resource_variant_snapshots(meta, position_currency="EUR")
    after = [r["variant_snapshot"] for r in meta["resources"]]
    assert after[0]["captured_at"] == before[0]["captured_at"]
    assert after[1]["captured_at"] == before[1]["captured_at"]


# ── Selective re-stamp: dropping ONE snapshot freshens only that row ──────


def test_stamp_resource_variants_restamps_only_dropped_resource() -> None:
    meta = _make_metadata()
    original_other = deepcopy(meta["resources"][1]["variant_snapshot"])

    # Simulate a re-pick on resource 0: caller picks the C35/45 variant,
    # patches unit_rate, and drops the stale snapshot. Stamper should
    # generate a fresh one for index 0 only.
    target = meta["resources"][0]
    new_variant = {"label": "C35/45 ready-mix", "price": 215.0, "index": 2}
    target["variant"] = new_variant
    target["unit_rate"] = 215.0
    target.pop("variant_snapshot", None)

    _stamp_resource_variant_snapshots(meta, position_currency="EUR")

    new_snap = meta["resources"][0]["variant_snapshot"]
    assert new_snap["label"] == "C35/45 ready-mix"
    assert new_snap["rate"] == 215.0
    assert new_snap["currency"] == "EUR"
    assert new_snap["source"] == "user_pick"

    # Resource 1 untouched — its snapshot must be bit-for-bit identical.
    assert meta["resources"][1]["variant_snapshot"] == original_other


# ── available_variants is a frontend-cached array; the helper itself
#    doesn't touch it (re-pick validation is in the service layer). The
#    helper simply preserves any extra keys on the resource dict. ─────────


def test_stamp_does_not_drop_available_variants() -> None:
    meta = _make_metadata()
    _stamp_resource_variant_snapshots(meta, position_currency="EUR")
    for r in meta["resources"]:
        assert isinstance(r.get("available_variants"), list)
        assert len(r["available_variants"]) >= 2


# ── Service-layer validation contract ─────────────────────────────────────
#
# The service rejects re-pick attempts that violate the contract before any
# DB write. The unit tests below exercise that branch directly using a
# minimal stub for the position/repository so the SQLAlchemy session never
# enters the picture.


class _StubPosition:
    """Minimal duck-type for app.modules.boq.models.Position used by the service."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.id = "pos-1"
        self.boq_id = "boq-1"
        self.metadata_ = metadata
        self.unit_rate = "185.0"
        self.quantity = "1"
        self.total = "185.0"
        self.version = 0
        self.ordinal = "01.001"


class _StubPositionRepo:
    def __init__(self, position: _StubPosition) -> None:
        self._pos = position
        self.calls: list[dict[str, Any]] = []

    async def get_by_id(self, _pid: Any) -> _StubPosition | None:
        return self._pos

    async def update_fields(self, _pid: Any, **fields: Any) -> None:
        # Track the patched fields so tests can assert on them.
        self.calls.append(fields)
        # Mirror the update onto the in-memory stub so the service's
        # subsequent ``session.refresh`` is a no-op.
        for k, v in fields.items():
            setattr(self._pos, k, v)


class _StubSession:
    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


@pytest.fixture
def stub_service_with_position():
    """Build a ``BOQService`` instance with stub session + stub repo so we
    can exercise the validation branches of ``repick_resource_variant``
    without hitting a DB."""
    from app.modules.boq.service import BOQService

    def _build(metadata: dict[str, Any]) -> tuple[Any, _StubPosition, _StubPositionRepo]:
        pos = _StubPosition(metadata)
        repo = _StubPositionRepo(pos)
        svc = BOQService.__new__(BOQService)  # bypass __init__ to skip DB plumbing
        svc.session = _StubSession()  # type: ignore[attr-defined]
        svc.position_repo = repo  # type: ignore[attr-defined]
        # Stub _ensure_not_locked so we don't need a BOQ row.

        async def _no_lock(_boq_id: Any) -> None:
            return None

        svc._ensure_not_locked = _no_lock  # type: ignore[assignment]

        # Stub get_boq for activity-log resolution path.
        async def _get_boq(_bid: Any):  # noqa: ANN001
            class _B:
                project_id = None

            return _B()

        svc.get_boq = _get_boq  # type: ignore[assignment]

        # Stub log_activity so we can verify the call without a DB.
        svc._activity_log_calls = []  # type: ignore[attr-defined]

        async def _log_activity(**kwargs: Any) -> None:
            svc._activity_log_calls.append(kwargs)  # type: ignore[attr-defined]

        svc.log_activity = _log_activity  # type: ignore[assignment]
        return svc, pos, repo

    return _build


@pytest.mark.asyncio
async def test_repick_invalid_resource_idx_raises_422(stub_service_with_position) -> None:
    from fastapi import HTTPException

    svc, _pos, _repo = stub_service_with_position(_make_metadata())
    with pytest.raises(HTTPException) as ei:
        await svc.repick_resource_variant("pos-1", 99, "C35/45 ready-mix")
    assert ei.value.status_code == 422
    assert "out of range" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_repick_negative_resource_idx_raises_422(stub_service_with_position) -> None:
    from fastapi import HTTPException

    svc, _pos, _repo = stub_service_with_position(_make_metadata())
    with pytest.raises(HTTPException) as ei:
        await svc.repick_resource_variant("pos-1", -1, "C35/45 ready-mix")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_repick_unknown_variant_code_raises_422(stub_service_with_position) -> None:
    from fastapi import HTTPException

    svc, _pos, _repo = stub_service_with_position(_make_metadata())
    with pytest.raises(HTTPException) as ei:
        await svc.repick_resource_variant("pos-1", 0, "DOES.NOT.EXIST")
    assert ei.value.status_code == 422
    assert "not found" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_repick_resource_without_available_variants_raises_422(
    stub_service_with_position,
) -> None:
    from fastapi import HTTPException

    meta = _make_metadata()
    # Strip the cached variants from resource 0 to simulate a legacy row.
    meta["resources"][0].pop("available_variants", None)
    svc, _pos, _repo = stub_service_with_position(meta)
    with pytest.raises(HTTPException) as ei:
        await svc.repick_resource_variant("pos-1", 0, "C35/45 ready-mix")
    assert ei.value.status_code == 422
    assert "no cached variants" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_repick_position_with_no_resources_raises_422(stub_service_with_position) -> None:
    from fastapi import HTTPException

    svc, _pos, _repo = stub_service_with_position({"currency": "EUR"})
    with pytest.raises(HTTPException) as ei:
        await svc.repick_resource_variant("pos-1", 0, "Anything")
    assert ei.value.status_code == 422
    assert "no resources" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_repick_updates_only_target_resource(stub_service_with_position) -> None:
    meta = _make_metadata()
    original_other_snapshot = deepcopy(meta["resources"][1]["variant_snapshot"])
    original_other_unit_rate = meta["resources"][1]["unit_rate"]

    svc, _pos, repo = stub_service_with_position(meta)
    # Sleep briefly so any timestamp drift on the OTHER row would be visible
    # (timespec=seconds resolution on the snapshot helper).
    time.sleep(1.1)

    await svc.repick_resource_variant("pos-1", 0, "C35/45 ready-mix")

    assert len(repo.calls) == 1
    patched_meta = repo.calls[0]["metadata_"]
    new_resources = patched_meta["resources"]
    # Target resource: variant + unit_rate updated, snapshot freshened.
    assert new_resources[0]["variant"]["label"] == "C35/45 ready-mix"
    assert new_resources[0]["variant"]["price"] == 215.0
    assert new_resources[0]["unit_rate"] == 215.0
    assert new_resources[0]["variant_snapshot"]["label"] == "C35/45 ready-mix"
    assert new_resources[0]["variant_snapshot"]["rate"] == 215.0
    assert new_resources[0]["variant_snapshot"]["source"] == "user_pick"
    # available_variants preserved on the target row.
    assert isinstance(new_resources[0].get("available_variants"), list)
    assert len(new_resources[0]["available_variants"]) == 3

    # Other resource untouched — snapshot and rate identical bit-for-bit.
    assert new_resources[1]["unit_rate"] == original_other_unit_rate
    assert new_resources[1]["variant_snapshot"] == original_other_snapshot


@pytest.mark.asyncio
async def test_repick_recomputes_position_unit_rate(stub_service_with_position) -> None:
    """Position-level unit_rate sums the per-unit subtotals after the swap."""
    meta = _make_metadata()
    svc, _pos, repo = stub_service_with_position(meta)
    await svc.repick_resource_variant("pos-1", 0, "C25/30 ready-mix")

    assert len(repo.calls) == 1
    new_unit_rate = float(repo.calls[0]["unit_rate"])
    # 1.0 * 165.0 + 90.0 * 1.50 = 165.0 + 135.0 = 300.0
    assert new_unit_rate == 300.0


@pytest.mark.asyncio
async def test_repick_drops_variant_default_marker(stub_service_with_position) -> None:
    """A resource that previously held variant_default loses the marker on
    explicit pick — the user made a deliberate choice."""
    meta = _make_metadata()
    # Replace resource 0's explicit variant with a default-strategy marker
    # so we can verify the helper drops it on re-pick.
    meta["resources"][0].pop("variant", None)
    meta["resources"][0]["variant_default"] = "mean"
    meta["resources"][0]["variant_snapshot"]["source"] = "default_mean"

    svc, _pos, repo = stub_service_with_position(meta)
    await svc.repick_resource_variant("pos-1", 0, "C30/37 ready-mix")

    patched = repo.calls[0]["metadata_"]["resources"][0]
    assert "variant_default" not in patched
    assert patched["variant"]["label"] == "C30/37 ready-mix"
    assert patched["variant_snapshot"]["source"] == "user_pick"


@pytest.mark.asyncio
async def test_repick_emits_activity_log_when_actor_provided(
    stub_service_with_position,
) -> None:
    svc, _pos, _repo = stub_service_with_position(_make_metadata())
    await svc.repick_resource_variant(
        "pos-1", 0, "C25/30 ready-mix", actor_id="user-1"
    )
    assert len(svc._activity_log_calls) == 1  # type: ignore[attr-defined]
    call = svc._activity_log_calls[0]  # type: ignore[attr-defined]
    assert call["action"] == "position.resource_variant_repicked"
    assert call["target_type"] == "position"
    assert call["metadata_"]["resource_idx"] == 0
    assert call["metadata_"]["variant_code"] == "C25/30 ready-mix"


@pytest.mark.asyncio
async def test_repick_no_activity_log_when_actor_omitted(
    stub_service_with_position,
) -> None:
    svc, _pos, _repo = stub_service_with_position(_make_metadata())
    await svc.repick_resource_variant("pos-1", 0, "C25/30 ready-mix")
    # The service still records calls into ``_activity_log_calls`` only via
    # ``log_activity``; without an actor the ``if actor_id is not None`` guard
    # in service.py keeps that list empty.
    assert svc._activity_log_calls == []  # type: ignore[attr-defined]
