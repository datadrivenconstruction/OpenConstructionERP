"""Event taxonomy for compliance_ai.

Import the constants from here rather than string-literating at call
sites. See :mod:`app.modules.dashboards.events` for the rationale.
"""

from __future__ import annotations

from typing import Final

RULE_CREATED: Final = "compliance.rule.created"
"""Payload: ``{rule_id, title, scope_category, severity, tenant_id}``."""

RULE_UPDATED: Final = "compliance.rule.updated"

RULE_DELETED: Final = "compliance.rule.deleted"

RULE_EVALUATED: Final = "compliance.rule.evaluated"
"""Payload: ``{rule_id, snapshot_id, total, passed, failed, tenant_id}``."""

NL_RULE_GENERATED: Final = "compliance.nl_rule.generated"
"""Emitted when T13's Claude call returns a validated DSL. Payload:
``{suggested_rule_id_candidate, requirement_excerpt_first_200_chars,
warnings_count, tenant_id}``."""

SOURCE_MODULE: Final = "oe_compliance_ai"
