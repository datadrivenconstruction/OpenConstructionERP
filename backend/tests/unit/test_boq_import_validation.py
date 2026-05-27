"""‌⁠‍Inline-validation-on-BOQ-import regression tests.

Stream B wires the validation engine into every BOQ import path (Excel /
CSV / GAEB X83/X84) so DIN276, NRM, GAEB, MasterFormat, DPGF and the
universal ``boq_quality`` rule packs fire AT import time instead of
later via the standalone ``POST /boqs/{id}/validate/`` endpoint.

Per the OpenEstimate philosophy:

* validation is a first-class citizen of the core workflow,
* the marketing pitch promises "Validierungs-Pipeline beim Import —
  meckert direkt, nicht erst in Zeile 452",
* but the import handlers historically only persisted rows and returned
  ``{imported, skipped, errors, warnings}`` — no validation report.

These tests pin three behaviours against regression:

1. A clean import surfaces a ``validation_report`` with ``passed`` status
   so the frontend can render the green-traffic-light validation dashboard
   inline on the import success modal.
2. An import that contains a missing-quantity row surfaces at least one
   ERROR result in the report that cites the failing position by
   ``element_ref`` (so the UI can deep-link back to the row).
3. With the ``IMPORT_INLINE_VALIDATION`` feature flag turned off the
   import response carries ``validation_report: None`` — the user opted
   out of the inline sweep, the standalone ``/validate/`` endpoint
   remains the way to run validation manually.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.boq.router import _run_import_validation

# ── Auto-register built-in rules ────────────────────────────────────────────
# The validation engine ships with an empty registry; ``register_builtin_rules``
# wires DIN276 + GAEB + boq_quality + NRM + MasterFormat + DPGF + ÖNORM +
# SINAPI + GESN + GB/T + CPWD + Birim Fiyat + Sekisan onto the global
# ``rule_registry``. ``app.main`` does this at app startup; unit tests
# that bypass the FastAPI lifecycle have to do it themselves.


@pytest.fixture(autouse=True)
def _ensure_rules_registered() -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    if not rule_registry.list_rule_sets():
        register_builtin_rules()


# ── Test doubles ────────────────────────────────────────────────────────────


def _make_position(
    *,
    ordinal: str,
    unit: str = "m3",
    quantity: float = 10.0,
    unit_rate: float = 120.0,
    parent_id: str | None = None,
    description: str = "Concrete C30/37 — foundation slab",
    classification: dict | None = None,
) -> SimpleNamespace:
    """Build a position-like object that mirrors the ORM attributes the
    helper reads (id, ordinal, description, unit, quantity, unit_rate,
    total, classification, parent_id, source).
    """
    total = quantity * unit_rate
    return SimpleNamespace(
        id=uuid.uuid4(),
        parent_id=(uuid.UUID(parent_id) if parent_id else None),
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
        classification=classification or {},
        source="gaeb_import",
    )


def _make_boq_data(positions: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=uuid.uuid4(),
        positions=positions,
    )


def _make_project(
    *,
    region: str = "DACH",
    standard: str = "din276",
    rule_sets: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        region=region,
        classification_standard=standard,
        validation_rule_sets=rule_sets or ["boq_quality"],
    )


class _StubService:
    """Minimal stub of ``BOQService`` exposing only what the helper reads."""

    def __init__(self, boq_data: SimpleNamespace) -> None:
        self._boq_data = boq_data
        self.session = object()  # opaque — _StubProjectRepo ignores it

    async def get_boq_with_positions(self, _boq_id: uuid.UUID) -> SimpleNamespace:
        return self._boq_data


class _StubProjectRepo:
    """Patched in for ``ProjectRepository`` to skip the SQL round-trip."""

    def __init__(self, _session: Any) -> None:
        pass

    async def get_by_id(self, _project_id: uuid.UUID) -> SimpleNamespace:
        return _StubProjectRepo._project  # set per-test via monkeypatch


# ── Helpers ─────────────────────────────────────────────────────────────────


def _patch_project_repo(monkeypatch: pytest.MonkeyPatch, project: SimpleNamespace) -> None:
    """Wire the stub ProjectRepository so the helper's lazy import picks it up."""
    _StubProjectRepo._project = project  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )


def _reset_settings_cache() -> None:
    """``get_settings`` is ``@lru_cache``-d; clear so env vars re-resolve."""
    from app.config import get_settings

    get_settings.cache_clear()


# ── Test 1: clean GAEB-style import → validation_report present, passed ────


def test_clean_import_yields_passed_validation_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean BOQ import must produce a validation_report dict with
    ``status='passed'`` and a non-None ``score`` so the frontend can
    render the green-traffic-light dashboard inline."""
    _reset_settings_cache()
    monkeypatch.delenv("IMPORT_INLINE_VALIDATION", raising=False)

    positions = [
        _make_position(
            ordinal="01.001",
            unit="m3",
            quantity=10.0,
            unit_rate=120.0,
            classification={"din276": "330"},
        ),
        _make_position(
            ordinal="01.002",
            unit="m2",
            quantity=50.0,
            unit_rate=45.0,
            classification={"din276": "340"},
        ),
        _make_position(
            ordinal="01.003",
            unit="kg",
            quantity=2500.0,
            unit_rate=1.2,
            classification={"din276": "350"},
        ),
    ]
    boq_data = _make_boq_data(positions)
    service = _StubService(boq_data)
    project = _make_project()
    _patch_project_repo(monkeypatch, project)

    report = asyncio.run(_run_import_validation(uuid.uuid4(), service, service.session))  # type: ignore[arg-type]

    assert report is not None, "Inline validation must run when feature flag is on"
    assert "status" in report, "Report must carry the engine summary fields"
    assert "score" in report
    assert "counts" in report
    assert "rule_sets" in report
    assert "results" in report
    # No missing-quantity / missing-unit-rate / missing-unit issues —
    # the report should not contain ERROR-severity findings.
    errors = [r for r in report["results"] if r["severity"] == "error" and not r["passed"]]
    assert errors == [], f"Expected no errors on a clean import, got: {errors!r}"
    # Engine status must reflect the all-clear (it can still be 'warnings'
    # because boq_quality.* contains optional benchmark checks, but
    # 'errors' must not appear).
    assert report["status"] in {"passed", "warnings"}, f"Unexpected status on a clean import: {report['status']!r}"


# ── Test 2: missing-quantity row → at least one ERROR with element_ref ─────


def test_missing_quantity_import_surfaces_error_with_element_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If one of the imported rows has quantity=0, the inline validation
    must surface at least one ERROR-severity finding whose ``element_ref``
    matches the failing position's id — so the UI can deep-link to it."""
    _reset_settings_cache()
    monkeypatch.delenv("IMPORT_INLINE_VALIDATION", raising=False)

    good = _make_position(ordinal="01.001", unit="m3", quantity=10.0, unit_rate=120.0)
    bad = _make_position(
        ordinal="01.002",
        unit="m3",
        quantity=0.0,  # ← missing/zero quantity: boq_quality.position_has_quantity fires
        unit_rate=120.0,
    )
    boq_data = _make_boq_data([good, bad])
    service = _StubService(boq_data)
    project = _make_project()
    _patch_project_repo(monkeypatch, project)

    report = asyncio.run(_run_import_validation(uuid.uuid4(), service, service.session))  # type: ignore[arg-type]
    assert report is not None

    errors = [r for r in report["results"] if r["severity"] == "error" and not r["passed"]]
    assert errors, (
        "Expected at least one ERROR-severity rule failure on a row with "
        f"quantity=0; got results: {report['results']!r}"
    )
    # The failing rule must point back at the bad position by id so the
    # frontend can scroll to / highlight it in the BOQ grid.
    bad_id = str(bad.id)
    refs = {r["element_ref"] for r in errors if r.get("element_ref")}
    assert bad_id in refs, (
        f"Expected an ERROR result citing position id {bad_id} (ordinal {bad.ordinal}); got element_refs: {refs!r}"
    )
    # And the overall report status must be 'errors' so the UI flips to red.
    assert report["status"] == "errors", (
        f"Expected status='errors' when a blocking rule fails, got {report['status']!r}"
    )


# ── Test 3: feature flag off → no validation_report ─────────────────────────


def test_feature_flag_off_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``IMPORT_INLINE_VALIDATION=False`` the helper must short-
    circuit to None so the import response carries ``validation_report:
    None`` — the user opted out of the inline sweep."""
    monkeypatch.setenv("IMPORT_INLINE_VALIDATION", "false")
    _reset_settings_cache()

    try:
        positions = [_make_position(ordinal="01.001")]
        boq_data = _make_boq_data(positions)
        service = _StubService(boq_data)
        project = _make_project()
        _patch_project_repo(monkeypatch, project)

        report = asyncio.run(
            _run_import_validation(uuid.uuid4(), service, service.session)  # type: ignore[arg-type]
        )
        assert report is None, (
            f"Inline validation must short-circuit to None when the feature flag is off; got: {report!r}"
        )
    finally:
        # Reset the cached settings so subsequent tests see the default.
        monkeypatch.delenv("IMPORT_INLINE_VALIDATION", raising=False)
        _reset_settings_cache()
