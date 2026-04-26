# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schema package for EAC v2.

Holds the canonical ``EacRuleDefinition`` JSON Schema and helpers for
loading it from disk so Python and TypeScript layers stay in lockstep.
"""

import json
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).parent / "EacRuleDefinition.schema.json"


def load_rule_definition_schema() -> dict[str, Any]:
    """Return the full ``EacRuleDefinition`` JSON Schema as a dict.

    Caches nothing — the file is small and reading it on demand keeps
    the module import-time light.
    """
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


__all__ = ["load_rule_definition_schema"]
