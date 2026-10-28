# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Compliance rule-pack registry + project assignment (Item #27).

Covers:
1. The pure rule-pack helpers (lookup, validation, region suggestion, rule-set
   resolution) in app.modules.contracts.compliance_packs.
2. Every shipped pack references rule sets that the validation engine actually
   registers — so a pack can never point the gate at a non-existent rule set.
3. The project-level ``set_compliance_rule_packs`` service method validates pack
   ids, rejects unknown ones with 422, and normalises an empty selection to the
   universal default.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.contracts.compliance_packs import (
    DEFAULT_PACK_ID,
    RULE_PACKS,
    WORKFLOW_CONTRACT_SIGNATURE,
    get_rule_pack,
    list_rule_packs,
    resolve_rule_sets,
    suggest_pack_for_region,
    valid_pack_ids,
)

# ── 1. Pure helpers ──────────────────────────────────────────────────────


def test_get_rule_pack_known_and_unknown() -> None:
    assert get_rule_pack("universal") is not None
    assert get_rule_pack("does_not_exist") is None


def test_list_rule_packs_returns_all() -> None:
    packs = list_rule_packs()
    ids = {p["id"] for p in packs}
    assert ids == set(RULE_PACKS.keys())
    assert "universal" in ids


def test_valid_pack_ids_filters_and_dedupes() -> None:
    out = valid_pack_ids(
        ["universal", "bogus", "de_compliance", "universal"],
    )
    assert out == ["universal", "de_compliance"]


def test_suggest_pack_for_region() -> None:
    assert suggest_pack_for_region("DACH") == "de_compliance"
    assert suggest_pack_for_region("United Kingdom") == "uk_compliance"
    assert suggest_pack_for_region("USA") == "us_compliance"
    assert suggest_pack_for_region("Mexico") == "mx_compliance"
    assert suggest_pack_for_region("MX") == "mx_compliance"
    # Unknown / empty → default.
    assert suggest_pack_for_region("Mars") == DEFAULT_PACK_ID
    assert suggest_pack_for_region(None) == DEFAULT_PACK_ID


def test_resolve_rule_sets_union_dedup_and_workflow_filter() -> None:
    sets = resolve_rule_sets(["universal", "de_compliance"])
    # Union, de-duplicated, order-preserving.
    assert sets[0] == "boq_quality"
    assert "din276" in sets
    assert "gaeb" in sets
    assert len(sets) == len(set(sets))
    # A workflow no pack enforces yields nothing.
    assert resolve_rule_sets(["universal"], workflow="nonexistent_gate") == []
    # Unknown pack ids are skipped, not errors.
    assert resolve_rule_sets(["bogus"]) == []


def test_every_pack_enforces_signature_workflow() -> None:
    for pack in RULE_PACKS.values():
        assert WORKFLOW_CONTRACT_SIGNATURE in pack["enforced_workflows"], (
            f"pack {pack['id']} does not enforce the contract-signature gate"
        )


# ── 2. Shipped packs reference real registered rule sets ─────────────────


def test_pack_rule_sets_exist_in_engine() -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    known_sets = set(rule_registry.list_rule_sets().keys())

    for pack in RULE_PACKS.values():
        for rs in pack["rule_sets"]:
            assert rs in known_sets, (
                f"pack {pack['id']} references unknown rule set {rs!r}; known sets: {sorted(known_sets)}"
            )


# ── 3. Project assignment service method ─────────────────────────────────


class _StubProjectRepo:
    def __init__(self, project: Any) -> None:
        self._project = project
        self.updated: dict[str, Any] = {}

    async def get_by_id(self, _project_id: uuid.UUID) -> Any:
        return self._project

    async def update_fields(self, _project_id: uuid.UUID, **fields: Any) -> None:
        self.updated.update(fields)
        for k, v in fields.items():
            setattr(self._project, k, v)


class _StubSession:
    async def refresh(self, _obj: Any) -> None:
        pass


def _make_project_service(project: Any) -> Any:
    from app.modules.projects.service import ProjectService

    svc = ProjectService.__new__(ProjectService)
    svc.session = _StubSession()
    svc.repo = _StubProjectRepo(project)
    svc.settings = None
    return svc


@pytest.mark.asyncio
async def test_set_compliance_rule_packs_valid() -> None:
    project = SimpleNamespace(
        id=uuid.uuid4(),
        name="P1",
        status="active",
        compliance_rule_packs=["universal"],
    )
    svc = _make_project_service(project)

    result = await svc.set_compliance_rule_packs(
        project.id,
        ["de_compliance", "universal"],
    )
    assert result.compliance_rule_packs == ["de_compliance", "universal"]
    assert svc.repo.updated["compliance_rule_packs"] == ["de_compliance", "universal"]


@pytest.mark.asyncio
async def test_set_compliance_rule_packs_rejects_unknown() -> None:
    from fastapi import HTTPException

    project = SimpleNamespace(
        id=uuid.uuid4(),
        name="P1",
        status="active",
        compliance_rule_packs=["universal"],
    )
    svc = _make_project_service(project)

    with pytest.raises(HTTPException) as exc:
        await svc.set_compliance_rule_packs(project.id, ["universal", "totally_made_up"])
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "unknown_compliance_rule_packs"
    assert "totally_made_up" in exc.value.detail["unknown_packs"]
    # Project unchanged.
    assert project.compliance_rule_packs == ["universal"]


@pytest.mark.asyncio
async def test_set_compliance_rule_packs_empty_falls_back_to_default() -> None:
    project = SimpleNamespace(
        id=uuid.uuid4(),
        name="P1",
        status="active",
        compliance_rule_packs=["de_compliance"],
    )
    svc = _make_project_service(project)

    result = await svc.set_compliance_rule_packs(project.id, [])
    assert result.compliance_rule_packs == [DEFAULT_PACK_ID]
