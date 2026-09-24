# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of the action kinds the assistant may propose.

The chat stream enumerates it to offer the model its ``propose_*`` tools and
to route a tool call to the spec that validates it::

    from app.modules.erp_chat.actions.registry import get_spec_for_tool, tool_definitions

    tools = [*TOOL_DEFINITIONS, *tool_definitions()]   # Anthropic format
    spec = get_spec_for_tool("propose_create_task")     # None for a read tool

Two views of the same registry:

* **registered** - every spec this build knows (``all_specs()``,
  ``get_spec()``). The lifecycle service resolves stored actions through it,
  so a proposal made while a module was on still renders after it is
  switched off.
* **available** - the specs whose modules (``ActionSpec.modules``) are loaded
  and enabled in this process right now (``all_specs(available_only=True)``).
  Everything the model sees goes through this view: ``tool_definitions()``,
  ``openai_tool_definitions()``, ``tool_names()`` and ``get_spec_for_tool()``
  agree with each other, so a module switched off at runtime takes its tool
  out of the next turn instead of failing it.

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
    from app.modules.erp_chat.actions.rfi_create import RFICreateSpec
    from app.modules.erp_chat.actions.task_create import TaskCreateSpec

    for spec in (BOQAddPositionSpec(), BOQUpdatePositionSpec(), TaskCreateSpec(), RFICreateSpec()):
        if spec.action_type not in _SPECS:
            register_spec(spec)
    _BUILTINS_LOADED = True


def module_available(name: str) -> bool:
    """Whether the module with manifest name ``name`` is loaded, enabled and serving its routes.

    A process whose module loader loaded nothing did not boot the module
    system (a unit test, a script): there is nothing to filter by, and every
    module counts as available. In the running app the loader has loaded every
    enabled module, and a module that is disabled, failed to load, or is not
    installed at all is unavailable - the same modules whose REST routes are
    not mounted.
    """
    from app.core.module_loader import module_loader

    loaded = module_loader.loaded_modules
    if not loaded:
        return True
    module = loaded.get(name)
    return module is not None and module.router is not None and module_loader.is_enabled(name)


def is_available(spec: ActionSpec) -> bool:
    """Whether every module ``spec`` writes to is available now (see :func:`module_available`)."""
    return all(module_available(name) for name in spec.modules)


def all_specs(*, available_only: bool = False) -> list[ActionSpec]:
    """Registered specs in registration order; with ``available_only``, only those the model may use now."""
    _ensure_builtins()
    specs = list(_SPECS.values())
    return [spec for spec in specs if is_available(spec)] if available_only else specs


def get_spec(action_type: str, *, available_only: bool = False) -> ActionSpec | None:
    """The spec for ``action_type`` (e.g. ``"boq.add_position"``), or None.

    Registered view by default, so a stored action keeps its spec while its
    module is off; the service refuses to apply it then (``module_unavailable``).
    """
    _ensure_builtins()
    spec = _SPECS.get(action_type)
    if spec is not None and available_only and not is_available(spec):
        return None
    return spec


def get_spec_for_tool(tool_name: str) -> ActionSpec | None:
    """The spec behind a ``propose_*`` tool the model may use now; None for any other tool.

    A tool whose module is switched off is None as well, exactly as if it had
    never been offered, so the stream treats a stale call like any unknown tool.
    """
    _ensure_builtins()
    spec = _BY_TOOL.get(tool_name)
    return spec if spec is not None and is_available(spec) else None


def get_registered_spec_for_tool(tool_name: str) -> ActionSpec | None:
    """The spec behind a ``propose_*`` tool name whether or not its module is on (to explain a refusal)."""
    _ensure_builtins()
    return _BY_TOOL.get(tool_name)


def tool_names() -> frozenset[str]:
    """Names of the proposal tools the model may use now."""
    return frozenset(spec.tool_name for spec in all_specs(available_only=True))


def tool_definitions() -> list[dict[str, Any]]:
    """The proposal tools the model may use now, in Anthropic format: ``{name, description, input_schema}``."""
    return [spec.tool_definition() for spec in all_specs(available_only=True)]


def openai_tool_definitions() -> list[dict[str, Any]]:
    """The same tools in OpenAI ``tools`` format (``{"type": "function", "function": ...}``)."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.tool_name,
                "description": spec.tool_description,
                "parameters": spec.input_schema(),
            },
        }
        for spec in all_specs(available_only=True)
    ]
