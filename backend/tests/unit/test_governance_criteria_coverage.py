# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every readiness criterion of a shipped phase model says how it is judged.

Governance never evaluates a criterion: the area owner ticks it and a tick blocks nothing. A criterion
that a module can read from its data is covered by that module's gate evidence provider
(``evidence_provider``); a criterion that is a human call says ``manual_only``; a provider that is not
merged yet is allowed by ``pending_provider`` naming its module. Once that module exists in the tree
the allowance fails, so it has to become an ``evidence_provider``.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

import pytest

import app.modules as modules_pkg
from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import evidence as evd

_REPO = Path(__file__).resolve().parents[3]
_MODULES_DIR = Path(modules_pkg.__path__[0])


def _shipped_phase_models() -> list[tuple[str, cat.Catalogue]]:
    out = [(f"shipped:{c.id}", c) for c in cat.list_catalogues()]
    for path in sorted((_REPO / "packs").glob("*/src/*/catalogues/phase_model/*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            (f"pack:{path.parts[-5 - 1]}:{body['id']}", cat.catalogue_from_body(body, source="pack", origin=str(path)))
        )
    return out


def _registered_provider_names() -> set[str]:
    """Provider names every module with an ``evidence`` file registers, in a registry of their own."""
    saved = dict(evd._REGISTRY)
    saved_links = dict(evd._LINK_ROUTES)
    evd._REGISTRY.clear()
    try:
        for info in pkgutil.iter_modules([str(_MODULES_DIR)]):
            if not (_MODULES_DIR / info.name / "evidence.py").is_file() or info.name == "project_governance":
                continue
            register = getattr(
                importlib.import_module(f"app.modules.{info.name}.evidence"), "register_gate_evidence", None
            )
            if register is not None:
                register()
        return {p.name for p in evd.evidence_providers()}
    finally:
        evd._REGISTRY.clear()
        evd._REGISTRY.update(saved)
        evd._LINK_ROUTES.clear()
        evd._LINK_ROUTES.update(saved_links)


def _problems() -> list[str]:
    providers = _registered_provider_names()
    problems: list[str] = []
    for label, catalogue in _shipped_phase_models():
        for c in catalogue.readiness_criteria:
            where = f"{label}: {c.area}/{c.gate}/{c.code}"
            if c.evidence_provider:
                if c.evidence_provider not in providers:
                    problems.append(f"{where}: evidence_provider {c.evidence_provider!r} is not registered")
            elif c.pending_provider:
                if (_MODULES_DIR / c.pending_provider).is_dir():
                    problems.append(
                        f"{where}: module {c.pending_provider!r} exists but does not provide the criterion; "
                        "replace pending_provider by evidence_provider (or manual_only)"
                    )
            elif not c.manual_only:
                problems.append(f"{where}: no evidence_provider, pending_provider or manual_only")
    return problems


def test_every_shipped_criterion_has_a_provider_or_is_marked_manual() -> None:
    assert _problems() == []


def test_the_gate_looks_at_a_real_population() -> None:
    models = _shipped_phase_models()
    assert sum(len(c.readiness_criteria) for _, c in models) >= 70
    assert len(_registered_provider_names()) >= 8


def test_a_criterion_without_any_marker_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    bare = cat.ReadinessCriterion(code="x", area="a", gate="g", name_key="k")
    assert not (bare.evidence_provider or bare.pending_provider or bare.manual_only)
    models = [("t", cat.Catalogue.model_construct(id="t", readiness_criteria=(bare,)))]
    monkeypatch.setitem(globals(), "_shipped_phase_models", lambda: models)
    assert any("no evidence_provider" in p for p in _problems())


def test_a_pending_allowance_for_an_existing_module_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = cat.ReadinessCriterion(code="x", area="a", gate="g", name_key="k", pending_provider="staffing")
    models = [("t", cat.Catalogue.model_construct(id="t", readiness_criteria=(stale,)))]
    monkeypatch.setitem(globals(), "_shipped_phase_models", lambda: models)
    assert any("exists but does not provide" in p for p in _problems())


def test_an_unregistered_provider_name_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    ghost = cat.ReadinessCriterion(code="x", area="a", gate="g", name_key="k", evidence_provider="nobody.nothing")
    models = [("t", cat.Catalogue.model_construct(id="t", readiness_criteria=(ghost,)))]
    monkeypatch.setitem(globals(), "_shipped_phase_models", lambda: models)
    assert any("is not registered" in p for p in _problems())


def test_the_markers_are_exclusive() -> None:
    with pytest.raises(ValueError, match="exclusive"):
        cat.ReadinessCriterion(code="x", area="a", gate="g", name_key="k", manual_only=True, pending_provider="m")
