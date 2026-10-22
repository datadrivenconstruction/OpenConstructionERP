# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Frozen rule snapshots and reasoned overrides of the procurement concept.

A snapshot is taken when a package's procedure is set and never changes; an
override of a rule outcome needs a reason and records who and when; a project
only ever sees its own snapshots.
"""

from __future__ import annotations

import copy
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.validation.engine import ValidationContext
from app.modules.procurement_concept.errors import ProcurementError
from app.modules.procurement_concept.models import RuleOverride, RuleSnapshot
from app.modules.procurement_concept.service import ProcurementConceptService
from app.modules.procurement_concept.validators import PROCUREMENT_RULES
from tests._pg import isolated_engine
from tests.pg.procurement_concept_fixtures import World, add_contract_package, build_world, put, svc_call

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

OPEN_WORKS = {"estimated_value": "900000", "currency": "EUR", "procedure_code": "open"}


@pytest_asyncio.fixture
async def pair():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        a = await build_world(factory)
        b = await build_world(factory)
        for w in (a, b):
            await add_contract_package(w, "W1", "construction")
            await put(w, "W1", OPEN_WORKS)
        yield a, b


async def _snaps(w: World, code: str = "W1") -> list[dict]:
    return await svc_call(w, "rule_snapshots", w.project_id, w.packages[code])


async def _override(w: World, snap: dict, **kw) -> dict:
    data = {"rule_code": "threshold_source_confirmed", "outcome": "pass", "reason": "Checked on the source"}
    data.update(kw)
    return await svc_call(
        w,
        "override_rule",
        w.project_id,
        w.packages["W1"],
        uuid.UUID(snap["id"]),
        data,
        actor_id=w.manager,
        can_manage=True,
    )


def _other(snap: dict, rule_code: str = "threshold_source_confirmed") -> str:
    original = next(o["outcome"] for o in snap["result"]["outcomes"] if o["rule_code"] == rule_code)
    return "fail" if original == "pass" else "pass"


async def test_snapshot_is_taken_when_the_procedure_is_set(pair) -> None:
    a, _ = pair
    (snap,) = await _snaps(a)
    assert snap["procedure_code"] == "open"
    assert snap["inputs"]["estimated_value"] == "900000.00" or snap["inputs"]["estimated_value"] == "900000"
    assert snap["inputs"]["currency"] == "EUR"
    assert snap["catalogue"]["id"] and snap["catalogue"]["version"] >= 1
    assert snap["catalogue"]["review_status"] in ("verified", "unconfirmed", "needs_review")
    assert any(r["kind"] == "procedure" and r["id"] == "procedure:open" for r in snap["rules"])
    assert {o["rule_code"] for o in snap["result"]["outcomes"]} >= {"procedure_allowed_for_value"}
    assert snap["integrity_ok"] is True
    assert snap["taken_by"] == str(a.manager)


async def test_snapshot_does_not_change_when_the_catalogue_or_the_package_changes(pair, monkeypatch) -> None:
    a, _ = pair
    (before,) = await _snaps(a)

    real = ProcurementConceptService.catalogue_of

    async def emptied(self, concept):
        cat = await real(self, concept)
        # The pinned catalogue "changes": every jurisdiction rule is gone.
        return cat.model_copy(update={"jurisdictions": ()})

    monkeypatch.setattr(ProcurementConceptService, "catalogue_of", emptied)
    live = await svc_call(a, "threshold_check", a.project_id, a.packages["W1"])
    assert live["thresholds"] == []  # the live check follows the catalogue ...
    await put(a, "W1", {"estimated_value": "50000"})  # ... and so does the value, without a new procedure
    after = await _snaps(a)
    assert after == [before]  # ... the snapshot does not


async def test_changing_the_procedure_adds_a_snapshot_and_keeps_the_old_one(pair) -> None:
    a, _ = pair
    (first,) = await _snaps(a)
    await put(a, "W1", {"procedure_code": "restricted"})
    newest, oldest = await _snaps(a)
    assert newest["procedure_code"] == "restricted"
    assert oldest == first


async def test_a_snapshot_row_cannot_be_updated(pair) -> None:
    a, _ = pair
    async with a.factory() as s:
        row = (await s.execute(sa.select(RuleSnapshot))).scalars().first()
        row.result = {"status": "below"}
        with pytest.raises(ValueError, match="frozen"):
            await s.flush()


async def test_override_without_reason_is_rejected_and_stores_nothing(pair) -> None:
    a, _ = pair
    (snap,) = await _snaps(a)
    for reason in ("", "   "):
        with pytest.raises(ProcurementError) as exc:
            await _override(a, snap, outcome=_other(snap), reason=reason)
        assert exc.value.code == "override_reason_required"
        assert exc.value.status_code == 422
    with pytest.raises(ProcurementError) as exc:
        await _override(a, snap, outcome=_other(snap), rule_code="no_such_rule")
    assert exc.value.code == "override_rule_unknown"
    (after,) = await _snaps(a)
    assert after["overrides"] == []


async def test_override_records_who_when_and_why_and_leaves_the_snapshot_as_taken(pair) -> None:
    a, _ = pair
    (snap,) = await _snaps(a)
    out = await _override(a, snap, outcome=_other(snap))
    assert out["reason"] == "Checked on the source"
    assert out["overridden_by"] == str(a.manager)
    assert out["overridden_at"]
    (after,) = await _snaps(a)
    assert [o["id"] for o in after["overrides"]] == [out["id"]]
    assert after["overrides"][0]["original_outcome"] != after["overrides"][0]["override_outcome"]
    assert after["result"] == snap["result"] and after["digest"] == snap["digest"] and after["integrity_ok"]


async def test_a_user_without_the_procurement_area_cannot_override(pair) -> None:
    a, _ = pair
    (snap,) = await _snaps(a)
    with pytest.raises(ProcurementError) as exc:
        await svc_call(
            a,
            "override_rule",
            a.project_id,
            a.packages["W1"],
            uuid.UUID(snap["id"]),
            {"rule_code": "threshold_source_confirmed", "outcome": _other(snap), "reason": "x"},
            actor_id=a.outsider,
            can_manage=False,
        )
    assert exc.value.status_code in (403, 404)


async def test_validation_flags_an_override_without_reason(pair) -> None:
    a, _ = pair
    (snap,) = await _snaps(a)
    async with a.factory() as s:
        s.add(
            RuleOverride(
                project_id=a.project_id,
                snapshot_id=uuid.UUID(snap["id"]),
                rule_code="threshold_source_confirmed",
                original_outcome="warn",
                override_outcome="pass",
                reason="",
                overridden_by=a.manager,
                overridden_at=sa.func.now(),
            )
        )
        await s.commit()
    findings = await svc_call(a, "findings", a.project_id)
    bare = [f for f in findings if f["code"] == "rule_override_without_reason"]
    assert len(bare) == 1 and bare[0]["severity"] == "error"
    rule = next(r for r in PROCUREMENT_RULES if r.key == "rule_override_has_reason")()
    results = await rule.validate(ValidationContext(data={"findings": copy.deepcopy(findings)}))
    assert [r.passed for r in results] == [False]


async def test_snapshots_and_overrides_are_bound_to_their_project(pair) -> None:
    a, b = pair
    (snap_b,) = await _snaps(b)
    with pytest.raises(ProcurementError) as exc:
        await svc_call(a, "rule_snapshots", a.project_id, b.packages["W1"])
    assert exc.value.status_code == 404
    with pytest.raises(ProcurementError) as exc:
        await svc_call(
            a,
            "override_rule",
            a.project_id,
            a.packages["W1"],
            uuid.UUID(snap_b["id"]),
            {"rule_code": "threshold_source_confirmed", "outcome": "pass", "reason": "x"},
            actor_id=a.manager,
            can_manage=True,
        )
    assert exc.value.status_code == 404
    with pytest.raises(ProcurementError) as exc:
        await svc_call(
            a,
            "override_rule",
            a.project_id,
            b.packages["W1"],
            uuid.UUID(snap_b["id"]),
            {"rule_code": "threshold_source_confirmed", "outcome": "pass", "reason": "x"},
            actor_id=a.manager,
            can_manage=True,
        )
    assert exc.value.status_code == 404
    (still,) = await _snaps(b)
    assert still["overrides"] == []
