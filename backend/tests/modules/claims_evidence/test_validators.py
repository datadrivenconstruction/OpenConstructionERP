# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Claims evidence rule set: each rule has a passing and a failing payload."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.claims_evidence.validators import (
    CLAIMS_EVIDENCE_RULE_SET,
    EvidenceCountMatchesEntriesRule,
    EvidenceDatesOrderedRule,
    EvidenceReferencesRule,
    ProvabilityScoreRule,
    register_claims_evidence_validation_rules,
)


def _entry(**kw: object) -> dict:
    base = {"ref_id": "e1", "source_module": "oe_rfi", "kind": "rfi", "occurred_at": "2026-03-10T08:00:00Z"}
    base.update(kw)
    return base


def _pack(**kw: object) -> dict:
    base = {
        "subject_ref": "CO-001",
        "basis": "change_order",
        "entry_count": 2,
        "date_from": "2026-03-01",
        "date_to": "2026-03-31",
        "sections": [{"name": "a", "entries": [_entry()]}, {"name": "b", "entries": [_entry(ref_id="e2")]}],
    }
    base.update(kw)
    return base


def _score(**kw: object) -> dict:
    base = {
        "subject_id": "s1",
        "score": 70,
        "sub_scores": [
            {"signal": "dated", "weight": 40, "earned": 40},
            {"signal": "signed", "weight": 60, "earned": 30},
        ],
    }
    base.update(kw)
    return base


def _data(pack: dict | None = None, score: dict | None = None) -> dict:
    return {"pack": pack or _pack(), "score": score or _score()}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (EvidenceCountMatchesEntriesRule, _data(), _data(_pack(entry_count=5))),
    (ProvabilityScoreRule, _data(), _data(score=_score(score=140))),
    (EvidenceReferencesRule, _data(), _data(_pack(basis=""))),
    (EvidenceDatesOrderedRule, _data(), _data(_pack(date_from="2026-04-01"))),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message


async def test_score_must_equal_earned_points() -> None:
    assert any(not r.passed for r in await _run(ProvabilityScoreRule(), _data(score=_score(score=90))))


async def test_earned_cannot_exceed_weight() -> None:
    subs = [{"signal": "dated", "weight": 40, "earned": 50}]
    data = _data(score=_score(score=50, sub_scores=subs))
    assert any(not r.passed for r in await _run(ProvabilityScoreRule(), data))


async def test_entry_without_source_fails() -> None:
    pack = _pack(sections=[{"name": "a", "entries": [_entry(source_module="")]}], entry_count=1)
    assert any(not r.passed for r in await _run(EvidenceReferencesRule(), _data(pack)))


async def test_entry_outside_window_fails() -> None:
    pack = _pack(sections=[{"name": "a", "entries": [_entry(occurred_at="2025-12-31")]}], entry_count=1)
    assert any(not r.passed for r in await _run(EvidenceDatesOrderedRule(), _data(pack)))


async def test_message_follows_locale() -> None:
    es = await _run(EvidenceReferencesRule(), _data(_pack(basis="")), locale="es")
    assert "referencia" in es[0].message


def test_registered_under_rule_set() -> None:
    register_claims_evidence_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([CLAIMS_EVIDENCE_RULE_SET])}
    assert len(ids) == 4
