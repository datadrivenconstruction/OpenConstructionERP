"""Unit tests for :class:`ValidationReportAdapter`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.vector_index import COLLECTION_VALIDATION
from app.modules.validation.vector_adapter import (
    ValidationReportAdapter,
    validation_report_adapter,
)

# -- Helpers ---------------------------------------------------------------


def _make_row(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid.uuid4(),
        "rule_set": "din276+boq_quality",
        "target_type": "boq",
        "target_id": str(uuid.uuid4()),
        "status": "warnings",
        "score": 0.87,
        "passed_count": 42,
        "warning_count": 3,
        "error_count": 0,
        "results": [
            {"rule_id": "boq_quality.zero_price", "message": "Position P-001 has zero unit rate"},
            {"rule_id": "din276.cost_group_required", "message": "Missing KG 330 mapping"},
        ],
        "project_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- Module-level ----------------------------------------------------------


def test_singleton_collection_name() -> None:
    assert validation_report_adapter.collection_name == COLLECTION_VALIDATION
    assert validation_report_adapter.module_name == "validation"


# -- to_text ---------------------------------------------------------------


def test_to_text_full_row_includes_every_textual_field() -> None:
    adapter = ValidationReportAdapter()
    text = adapter.to_text(_make_row())
    for needle in (
        "rule_set=din276+boq_quality",
        "target=boq",
        "status=warnings",
        "[boq_quality.zero_price] Position P-001 has zero unit rate",
        "[din276.cost_group_required] Missing KG 330 mapping",
    ):
        assert needle in text, f"missing {needle!r} in {text!r}"


def test_to_text_drops_empty_fields() -> None:
    adapter = ValidationReportAdapter()
    row = _make_row(rule_set="", target_type="", status="", results=[])
    text = adapter.to_text(row)
    assert text == ""


def test_to_text_tolerates_none_on_optional_fields() -> None:
    adapter = ValidationReportAdapter()
    row = _make_row(rule_set=None, target_type=None, status=None, results=None)
    text = adapter.to_text(row)
    assert text == ""


def test_to_text_separator_uses_pipe() -> None:
    adapter = ValidationReportAdapter()
    assert " | " in adapter.to_text(_make_row())


def test_to_text_joins_messages_with_slash_separator() -> None:
    adapter = ValidationReportAdapter()
    text = adapter.to_text(_make_row())
    assert " / " in text


def test_to_text_caps_at_50_results() -> None:
    adapter = ValidationReportAdapter()
    results = [
        {"rule_id": f"r{i}", "message": f"msg{i}"} for i in range(120)
    ]
    text = adapter.to_text(_make_row(results=results))
    assert "msg0" in text
    assert "msg49" in text
    assert "msg50" not in text
    assert "msg99" not in text


def test_to_text_ignores_non_dict_result_entries() -> None:
    adapter = ValidationReportAdapter()
    row = _make_row(results=["bad", 42, {"rule_id": "r1", "message": "keep me"}])
    text = adapter.to_text(row)
    assert "keep me" in text
    assert "bad" not in text


def test_to_text_plain_message_without_rule_id() -> None:
    adapter = ValidationReportAdapter()
    row = _make_row(results=[{"message": "bare message"}])
    text = adapter.to_text(row)
    assert "bare message" in text
    assert "[" not in text.split("|")[-1]


# -- to_payload ------------------------------------------------------------


def test_to_payload_title_assembled_from_rule_set_target_status() -> None:
    adapter = ValidationReportAdapter()
    payload = adapter.to_payload(_make_row())
    assert payload["title"] == "din276+boq_quality \u2022 boq \u2022 warnings"
    assert payload["rule_set"] == "din276+boq_quality"
    assert payload["target_type"] == "boq"
    assert payload["status"] == "warnings"


def test_to_payload_title_defaults_when_all_missing() -> None:
    adapter = ValidationReportAdapter()
    payload = adapter.to_payload(
        _make_row(rule_set=None, target_type=None, status=None),
    )
    assert "validation" in payload["title"]
    assert "unknown" in payload["title"]
    assert "pending" in payload["title"]


def test_to_payload_title_clipped() -> None:
    adapter = ValidationReportAdapter()
    payload = adapter.to_payload(_make_row(rule_set="x" * 500))
    assert len(payload["title"]) <= 160


def test_to_payload_counts_coerced_to_int() -> None:
    adapter = ValidationReportAdapter()
    payload = adapter.to_payload(
        _make_row(passed_count=None, warning_count=None, error_count=None),
    )
    assert payload["passed_count"] == 0
    assert payload["warning_count"] == 0
    assert payload["error_count"] == 0


def test_to_payload_propagates_target_id_and_score() -> None:
    adapter = ValidationReportAdapter()
    target = str(uuid.uuid4())
    payload = adapter.to_payload(_make_row(target_id=target, score=0.75))
    assert payload["target_id"] == target
    assert payload["score"] == 0.75


# -- project_id_of ---------------------------------------------------------


def test_project_id_of_returns_stringified_uuid() -> None:
    adapter = ValidationReportAdapter()
    project_id = uuid.uuid4()
    assert adapter.project_id_of(_make_row(project_id=project_id)) == str(project_id)


def test_project_id_of_returns_none_when_missing() -> None:
    adapter = ValidationReportAdapter()
    assert adapter.project_id_of(_make_row(project_id=None)) is None
