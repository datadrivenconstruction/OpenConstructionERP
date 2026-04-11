"""Risk item vector adapter — feeds the ``oe_risks`` collection.

Each :class:`~app.modules.risk.models.RiskItem` row is embedded as a rich
concatenation of its title, description, mitigation strategy, contingency
plan, category and severity signals.  The text is intentionally verbose
because **risks are the killer cross-project use case for semantic
search** — lessons-learned reuse means an estimator on a new project
should be able to pull up "similar risks we've already faced" across the
entire tenant history, regardless of project.

The adapter is stateless and knows nothing about the event bus or HTTP
routing — wiring lives in :mod:`app.modules.risk.events` and
``router.py`` respectively.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_RISKS
from app.modules.risk.models import RiskItem


class RiskVectorAdapter:
    """Embed risk register entries into the unified vector store."""

    collection_name: str = COLLECTION_RISKS
    module_name: str = "risks"

    def to_text(self, row: RiskItem) -> str:
        """Build the canonical text that gets embedded.

        Risks benefit from a *rich* text representation because most of
        their value — the "how we handled it" knowledge — lives in the
        mitigation strategy and contingency plan, not the title alone.
        We therefore concatenate every free-text field and every
        categorical signal so that semantic queries like *"asbestos in
        existing substructure"* or *"weather delay winter foundation"*
        match historical risks even when wording diverges.
        """
        parts: list[str] = []
        if row.title:
            parts.append(row.title.strip())
        if row.description:
            parts.append(row.description.strip())
        if getattr(row, "mitigation_strategy", None):
            parts.append(f"mitigation: {row.mitigation_strategy.strip()}")
        if getattr(row, "contingency_plan", None):
            parts.append(f"contingency: {row.contingency_plan.strip()}")
        category = getattr(row, "category", None)
        if category:
            parts.append(f"category={category}")
        # Severity / probability signals — help semantic ranking group
        # "catastrophic / critical" risks together across projects.
        impact_severity = getattr(row, "impact_severity", None)
        if impact_severity:
            parts.append(f"severity={impact_severity}")
        risk_tier = getattr(row, "risk_tier", None)
        if risk_tier:
            parts.append(f"tier={risk_tier}")
        probability = getattr(row, "probability", None)
        if probability not in (None, ""):
            parts.append(f"probability={probability}")
        impact_cost = getattr(row, "impact_cost", None)
        if impact_cost not in (None, "", "0"):
            parts.append(f"impact_cost={impact_cost}")
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: RiskItem) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render a lessons-learned card without an extra Postgres roundtrip.
        """
        return {
            "title": (row.title or "")[:160],
            "status": getattr(row, "status", "") or "",
            "category": getattr(row, "category", "") or "",
            "impact": str(getattr(row, "impact_severity", "") or ""),
            "probability": str(getattr(row, "probability", "") or ""),
            "severity": (
                str(getattr(row, "risk_tier", "") or "")
                if hasattr(row, "risk_tier")
                else ""
            ),
        }

    def project_id_of(self, row: RiskItem) -> str | None:
        """Resolve the owning project id directly from the row."""
        project_id = getattr(row, "project_id", None)
        if project_id is None:
            return None
        return str(project_id)


# Singleton instance — adapters are stateless so one shared object is fine.
risk_vector_adapter = RiskVectorAdapter()
