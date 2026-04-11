"""Unit tests for :class:`RiskVectorAdapter`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_RISKS
from app.modules.risk.vector_adapter import (
    RiskVectorAdapter,
    risk_vector_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "title": "Asbestos in existing substructure",
        "description": "Legacy pipe insulation may contain asbestos",
        "mitigation_strategy": "Commission asbestos survey before demolition",
        "contingency_plan": "Engage licensed removal contractor",
        "category": "environmental",
        "impact_severity": "critical",
        "risk_tier": "tier_1",
        "probability": "medium",
        "impact_cost": "250000",
        "status": "open",
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert risk_vector_adapter.collection_name == COLLECTION_RISKS
    assert risk_vector_adapter.module_name == "risks"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = RiskVectorAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "Asbestos in existing substructure",
        "Legacy pipe insulation may contain asbestos",
        "mitigation: Commission asbestos survey before demolition",
        "contingency: Engage licensed removal contractor",
        "category=environmental",
        "severity=critical",
        "tier=tier_1",
        "probability=medium",
        "impact_cost=250000",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = RiskVectorAdapter()
    row = _make_row(
        description="",
        mitigation_strategy="",
        contingency_plan="",
        category="",
        impact_severity="",
        risk_tier="",
    )
    text = adapter.to_text(row)
    assert "Asbestos in existing substructure" in text
    assert "mitigation:" not in text
    assert "category=" not in text


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = RiskVectorAdapter()
    row = _make_row(
        description=None,
        mitigation_strategy=None,
        contingency_plan=None,
        category=None,
        impact_severity=None,
        risk_tier=None,
        probability=None,
        impact_cost=None,
    )
    text = adapter.to_text(row)
    assert "Asbestos in existing substructure" in text


def test_to_text_skips_zero_impact_cost() -> None:
    """The adapter treats '0' as not-a-signal to avoid diluting embeddings."""
    adapter = RiskVectorAdapter()
    row = _make_row(impact_cost="0")
    assert "impact_cost=" not in adapter.to_text(row)


def test_to_text_separator_uses_pipe() -> None:
    adapter = RiskVectorAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_probability_empty_string_skipped() -> None:
    adapter = RiskVectorAdapter()
    row = _make_row(probability="")
    assert "probability=" not in adapter.to_text(row)


# -- to_payload ------------------------------------------------------------


def test_to_payload_builds_title_from_risk_title() -> None:
    adapter = RiskVectorAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "Asbestos in existing substructure"
    assert payload["status"] == "open"
    assert payload["category"] == "environmental"
    assert payload["impact"] == "critical"
    assert payload["probability"] == "medium"
    assert payload["severity"] == "tier_1"


def test_to_payload_clips_long_title() -> None:
    adapter = RiskVectorAdapter()
    payload = adapter.to_payload(_make_row(title="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_empty_title_yields_empty() -> None:
    adapter = RiskVectorAdapter()
    payload = adapter.to_payload(_make_row(title=None))
    assert payload["title"] == ""


def test_to_payload_defaults_when_optional_fields_missing() -> None:
    adapter = RiskVectorAdapter()
    payload = adapter.to_payload(
        _make_row(
            status=None,
            category=None,
            impact_severity=None,
            probability=None,
            risk_tier=None,
        ),
    )
    assert payload["status"] == ""
    assert payload["category"] == ""
    assert payload["impact"] == ""
    assert payload["probability"] == ""
    assert payload["severity"] == ""


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = RiskVectorAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = RiskVectorAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
