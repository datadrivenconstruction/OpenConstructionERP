"""Validation report vector adapter — feeds the ``oe_validation`` collection.

Each :class:`~app.modules.validation.models.ValidationReport` row is
embedded as the rule_set name plus the textual messages from each
result.  This makes the unified search layer able to answer questions
like *"which projects had warnings about zero unit prices?"* or *"show
me validation reports about missing classification codes"*.

Implements the :class:`~app.core.vector_index.EmbeddingAdapter`
protocol — see :mod:`app.core.vector_index` for the read/write helpers
that consume it.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_VALIDATION
from app.modules.validation.models import ValidationReport


class ValidationReportAdapter:
    """Embed validation reports into the unified vector store."""

    collection_name: str = COLLECTION_VALIDATION
    module_name: str = "validation"

    def to_text(self, row: ValidationReport) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the rule set name, target type, status and the
        textual messages from each result entry.  Caps message extraction
        at 50 results so a 1000-issue report doesn't blow the embedding
        token budget.
        """
        parts: list[str] = []
        if row.rule_set:
            parts.append(f"rule_set={row.rule_set}")
        if row.target_type:
            parts.append(f"target={row.target_type}")
        if row.status:
            parts.append(f"status={row.status}")
        results = getattr(row, "results", None) or []
        if isinstance(results, list):
            messages: list[str] = []
            for entry in results[:50]:
                if not isinstance(entry, dict):
                    continue
                msg = entry.get("message")
                rule_id = entry.get("rule_id")
                if isinstance(msg, str) and msg:
                    if isinstance(rule_id, str) and rule_id:
                        messages.append(f"[{rule_id}] {msg}")
                    else:
                        messages.append(msg)
            if messages:
                parts.append(" / ".join(messages))
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: ValidationReport) -> dict[str, Any]:
        """Light metadata returned with every search hit."""
        return {
            "title": (
                f"{row.rule_set or 'validation'} • "
                f"{row.target_type or 'unknown'} • "
                f"{row.status or 'pending'}"
            )[:160],
            "rule_set": row.rule_set or "",
            "target_type": row.target_type or "",
            "target_id": row.target_id or "",
            "status": row.status or "",
            "score": row.score or "",
            "passed_count": int(row.passed_count or 0),
            "warning_count": int(row.warning_count or 0),
            "error_count": int(row.error_count or 0),
        }

    def project_id_of(self, row: ValidationReport) -> str | None:
        return str(row.project_id) if getattr(row, "project_id", None) else None


validation_report_adapter = ValidationReportAdapter()
