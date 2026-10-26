"""Handover dossier checklist: config, scope matching and the validation rules."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationEngine, rule_registry
from app.modules.closeout import dossier as dz
from app.modules.closeout.validators import register_closeout_validation_rules


def test_config_defaults_and_normalisation():
    cfg = dz.normalise_config(None)
    assert "acceptance" in cfg["required_categories"]
    assert cfg["share_expires_in_days"] == 30
    cfg = dz.normalise_config(
        {
            "required_categories": ["As_Built", "as_built", "bad key!", "warranty"],
            "require_punch_photos": 0,
            "share_expires_in_days": 9999,
            "unknown": True,
        }
    )
    assert cfg["required_categories"] == ["as_built", "warranty"]
    assert cfg["require_punch_photos"] is False
    assert cfg["share_expires_in_days"] == 365
    assert "unknown" not in cfg


def test_scope_normalisation_and_labels():
    assert dz.normalise_scope("area", "  ") == {"kind": "project", "value": None}
    assert dz.normalise_scope("bogus", "x") == {"kind": "project", "value": None}
    scope = dz.normalise_scope("area", "Level 2")
    assert scope == {"kind": "area", "value": "Level 2"}
    assert dz.scope_label(scope) == "area: Level 2"
    assert dz.scope_slug(scope) == "area-Level_2"


@pytest.mark.parametrize(
    ("area", "expected"),
    [("Level 2", True), ("level 2 / Room 2.14", True), ("Level 2/Core", True), ("Level 20", False), (None, False)],
)
def test_area_scope_matches_exactly_or_as_path_prefix(area, expected):
    assert dz.matches_scope({"kind": "area", "value": "Level 2"}, area=area) is expected


def test_asset_scope_and_project_scope():
    assert dz.matches_scope({"kind": "asset", "value": "AHU-01"}, asset_refs=("x", "ahu-01")) is True
    assert dz.matches_scope({"kind": "asset", "value": "AHU-01"}, asset_refs=(None,)) is False
    assert dz.matches_scope({"kind": "project", "value": None}, area=None) is True


def _context(**over):
    ctx = {
        "config": dz.normalise_config(None),
        "categories": {
            c: {"present": True, "verified": True} for c in dz.DEFAULT_DOSSIER_CONFIG["required_categories"]
        },
        "punch": {"open": [], "without_photo": []},
        "commissioning": {"pending": [], "open_critical_issues": 0},
        "acceptance": {"bound": True, "signed": True, "signing_status": "fully_signed"},
    }
    ctx.update(over)
    return ctx


async def _run(ctx):
    register_closeout_validation_rules()
    report = await ValidationEngine(rule_registry).validate(data=ctx, rule_sets=[dz.DOSSIER_RULE_SET])
    return [r for r in report.results if not r.passed]


async def test_complete_dossier_passes():
    assert await _run(_context()) == []


async def test_missing_category_and_unsigned_acceptance_are_errors():
    ctx = _context(
        categories={"as_built": {"present": False, "verified": False}},
        acceptance={"bound": True, "signed": False, "signing_status": "partially_signed"},
    )
    failed = await _run(ctx)
    ids = {r.rule_id for r in failed}
    assert "closeout.dossier_category_present" in ids
    assert "closeout.dossier_acceptance_signed" in ids
    assert all(str(r.severity) == "error" for r in failed if r.rule_id == "closeout.dossier_acceptance_signed")


async def test_open_punch_and_missing_photos_are_reported_per_item():
    ctx = _context(
        punch={"open": [{"id": "1", "title": "Door"}], "without_photo": [{"id": "2", "title": "Wall"}]},
    )
    failed = await _run(ctx)
    assert {(r.rule_id, r.element_ref) for r in failed} == {
        ("closeout.dossier_punch_resolved", "1"),
        ("closeout.dossier_punch_photos", "2"),
    }


async def test_switched_off_requirements_are_silent():
    cfg = dz.normalise_config(
        {
            "require_punch_resolved": False,
            "require_punch_photos": False,
            "require_signed_acceptance": False,
            "require_commissioning_complete": False,
        }
    )
    ctx = _context(
        config=cfg,
        punch={"open": [{"id": "1", "title": "Door"}], "without_photo": [{"id": "2", "title": "x"}]},
        acceptance={"bound": False, "signed": False},
        commissioning={"pending": [{"id": "s", "name": "AHU"}], "open_critical_issues": 2},
    )
    assert await _run(ctx) == []


async def test_commissioning_pending_and_critical_issues_warn():
    ctx = _context(commissioning={"pending": [{"id": "s1", "name": "Chiller"}], "open_critical_issues": 2})
    failed = await _run(ctx)
    assert {r.rule_id for r in failed} == {"closeout.dossier_commissioning_complete"}
    assert len(failed) == 2
    assert all(str(r.severity) == "warning" for r in failed)


async def test_long_item_lists_are_capped_with_a_summary_row():
    items = [{"id": str(i), "title": f"Item {i}"} for i in range(60)]
    failed = await _run(_context(punch={"open": items, "without_photo": []}))
    assert len(failed) == 51
    assert failed[-1].details == {"total": 60}


async def test_unverified_evidence_warns_only_when_required():
    cats = {c: {"present": True, "verified": False} for c in dz.DEFAULT_DOSSIER_CONFIG["required_categories"]}
    assert await _run(_context(categories=cats)) == []
    cfg = dz.normalise_config({"require_verified_evidence": True})
    failed = await _run(_context(categories=cats, config=cfg))
    assert failed and {r.rule_id for r in failed} == {"closeout.dossier_evidence_verified"}
