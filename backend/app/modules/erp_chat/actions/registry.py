# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of the action kinds the assistant may propose.

The chat stream enumerates it to offer the model its ``propose_*`` tools and
to route a tool call to the spec that validates it::

    from app.modules.erp_chat.actions.registry import get_spec_for_tool, tool_definitions

    tools = [*TOOL_DEFINITIONS, *tool_definitions()]   # Anthropic format
    spec = get_spec_for_tool("propose_create_task")     # None for a read tool

The built-in specs register themselves on first access, so importing this
module never imports a domain module (BOQ, tasks) and cannot create an import
cycle with them.
"""

from __future__ import annotations

import threading
from typing import Any

from app.modules.erp_chat.actions.base import ActionSpec

_SPECS: dict[str, ActionSpec] = {}
_BY_TOOL: dict[str, ActionSpec] = {}
_LOCK = threading.Lock()
_BUILTINS_LOADED = False


def register_spec(spec: ActionSpec) -> ActionSpec:
    """Register ``spec`` under its action type and tool name (re-registering replaces)."""
    with _LOCK:
        _SPECS[spec.action_type] = spec
        _BY_TOOL[spec.tool_name] = spec
    return spec


def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from app.modules.erp_chat.actions.boq_add_position import BOQAddPositionSpec
    from app.modules.erp_chat.actions.boq_update_position import BOQUpdatePositionSpec
    from app.modules.erp_chat.actions.task_create import TaskCreateSpec

    for spec in (BOQAddPositionSpec(), BOQUpdatePositionSpec(), TaskCreateSpec()):
        if spec.action_type not in _SPECS:
            register_spec(spec)
    _BUILTINS_LOADED = True


def all_specs() -> list[ActionSpec]:
    """Every registered spec, in registration order."""
    _ensure_builtins()
    return list(_SPECS.values())


def get_spec(action_type: str) -> ActionSpec | None:
    """The spec for ``action_type`` (e.g. ``"boq.add_position"``), or None."""
    _ensure_builtins()
    return _SPECS.get(action_type)


def get_spec_for_tool(tool_name: str) -> ActionSpec | None:
    """The spec behind a ``propose_*`` tool name, or None for any other tool."""
    _ensure_builtins()
    return _BY_TOOL.get(tool_name)


def tool_names() -> frozenset[str]:
    """Names of every proposal tool."""
    _ensure_builtins()
    return frozenset(_BY_TOOL)


def tool_definitions() -> list[dict[str, Any]]:
    """Every proposal tool in Anthropic format: ``{name, description, input_schema}``."""
    return [spec.tool_definition() for spec in all_specs()]


def openai_tool_definitions() -> list[dict[str, Any]]:
    """Every proposal tool in OpenAI ``tools`` format (``{"type": "function", "function": ...}``)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.tool_name,
                "description": spec.tool_description,
                "parameters": spec.input_schema(),
            },
        }
        for spec in all_specs()
    ]
