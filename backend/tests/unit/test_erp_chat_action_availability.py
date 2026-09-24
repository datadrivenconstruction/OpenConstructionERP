"""Which proposal tools the assistant is offered when modules are switched off.

A spec names the modules it writes to (``ActionSpec.modules``). The model is
offered its tool only while those modules are loaded, enabled and serving
their routes, and every view the chat stream reads agrees on that: the
Anthropic and OpenAI tool lists, the tool names and the tool router. A module
that is off, missing or lost its routes takes its tool out of the next turn
instead of failing the chat. A proposal stored while the module was on still
renders and can be rejected, but nobody can apply it while its module is off.
"""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.core.module_loader as module_loader_mod
from app.modules.erp_chat.actions import registry
from app.modules.erp_chat.actions.base import ActionConflictError, ActionContext, ActionValidationError
from app.modules.erp_chat.actions.service import ChatActionService, Viewer
from app.modules.erp_chat.models import ChatAction

_MODULES_DIR = Path(importlib.import_module("app.modules").__path__[0])


class _Loader:
    """The three things the registry reads from the module loader."""

    def __init__(self, loaded: dict[str, bool], disabled: set[str] | None = None) -> None:
        # ``loaded``: manifest name -> whether its router was mounted.
        self._modules = {name: SimpleNamespace(router=object() if routed else None) for name, routed in loaded.items()}
        self._disabled = set(disabled or ())
        self._manifests = set(loaded) | self._disabled

    @property
    def loaded_modules(self) -> dict[str, Any]:
        return self._modules

    def is_enabled(self, name: str) -> bool:
        return name in self._manifests and name not in self._disabled


def _every_module_on() -> dict[str, bool]:
    return {name: True for spec in registry.all_specs() for name in spec.modules}


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch):
    """Install a fake loader state; returns a setter so a test can describe the modules."""

    def _install(loaded: dict[str, bool], disabled: set[str] | None = None) -> None:
        monkeypatch.setattr(module_loader_mod, "module_loader", _Loader(loaded, disabled))

    return _install


def test_every_spec_names_the_manifest_of_the_module_it_writes_to() -> None:
    for spec in registry.all_specs():
        assert spec.modules, spec.action_type
        for name in spec.modules:
            manifest = importlib.import_module(f"app.modules.{name.removeprefix('oe_')}.manifest").manifest
            assert manifest.name == name
            assert (_MODULES_DIR / name.removeprefix("oe_") / "router.py").exists()


def test_a_process_that_did_not_boot_the_module_system_offers_every_tool(loader) -> None:
    loader({})
    registered = {spec.tool_name for spec in registry.all_specs()}
    assert registry.tool_names() == registered
    assert {t["name"] for t in registry.tool_definitions()} == registered


def test_with_every_module_on_every_tool_is_offered(loader) -> None:
    loader(_every_module_on())
    registered = {spec.tool_name for spec in registry.all_specs()}
    assert registry.tool_names() == registered
    assert registry.all_specs(available_only=True) == registry.all_specs()


def test_a_switched_off_module_takes_its_tool_out_of_every_view(loader) -> None:
    modules = _every_module_on()
    del modules["oe_tasks"]
    loader(modules, disabled={"oe_tasks"})

    assert "propose_create_task" not in registry.tool_names()
    assert "propose_create_task" not in {t["name"] for t in registry.tool_definitions()}
    assert "propose_create_task" not in {t["function"]["name"] for t in registry.openai_tool_definitions()}
    assert registry.get_spec_for_tool("propose_create_task") is None
    assert "task.create" not in {s.action_type for s in registry.all_specs(available_only=True)}
    # The other tools stay, and the four views agree on them.
    offered = registry.tool_names()
    assert "propose_add_boq_position" in offered
    assert {t["name"] for t in registry.tool_definitions()} == offered
    assert {t["function"]["name"] for t in registry.openai_tool_definitions()} == offered
    assert all(registry.get_spec_for_tool(name) is not None for name in offered)
    # The registered view still knows it, so stored proposals keep rendering.
    assert "task.create" in {s.action_type for s in registry.all_specs()}
    assert registry.get_spec("task.create") is not None
    assert registry.get_spec("task.create", available_only=True) is None


def test_a_module_that_is_missing_or_lost_its_routes_is_not_offered(loader) -> None:
    modules = _every_module_on()
    del modules["oe_tasks"]  # not installed at all: no manifest either
    modules["oe_boq"] = False  # loaded, but its router failed to mount
    loader(modules)

    offered = registry.tool_names()
    assert "propose_create_task" not in offered
    assert "propose_add_boq_position" not in offered
    assert "propose_update_boq_position" not in offered
    assert len(registry.tool_definitions()) == len(offered)


def _stored_action(action_type: str, requested_by: uuid.UUID) -> ChatAction:
    return ChatAction(
        id=uuid.uuid4(),
        action_type=action_type,
        status="proposed",
        title="Create task",
        requested_by=requested_by,
        project_id=None,
        payload={"title": "Check formwork"},
        original_payload={"title": "Check formwork"},
        preview={"fields": [], "subtitle": None, "target": None, "notes": []},
    )


def test_a_proposal_of_a_switched_off_module_can_be_rejected_but_not_applied(loader) -> None:
    modules = _every_module_on()
    del modules["oe_tasks"]
    loader(modules, disabled={"oe_tasks"})
    admin = Viewer(ctx=ActionContext(session=None, user_id=uuid.uuid4(), role="admin"), accessible_projects=None)
    action = _stored_action("task.create", requested_by=uuid.uuid4())
    service = ChatActionService(None)

    abilities = service.abilities(action, admin)
    assert (abilities.can_apply, abilities.can_edit, abilities.can_revert) == (False, False, False)
    assert abilities.can_reject
    assert abilities.blocked_by == "module_unavailable"
    with pytest.raises(ActionConflictError) as caught:
        service._spec(action)
    assert (caught.value.code, caught.value.status_code) == ("module_unavailable", 409)
    assert caught.value.message_key == "erp_chat.action.error.module_unavailable"

    loader(_every_module_on())
    back_on = service.abilities(action, admin)
    assert back_on.can_apply and back_on.blocked_by is None


@pytest.mark.asyncio
async def test_proposing_through_a_switched_off_tool_says_the_module_is_off(loader) -> None:
    modules = _every_module_on()
    del modules["oe_tasks"]
    loader(modules, disabled={"oe_tasks"})
    service = ChatActionService(None)

    with pytest.raises(ActionConflictError) as off:
        await service.propose(tool_name="propose_create_task", args={"title": "x"}, user_id=uuid.uuid4())
    assert off.value.code == "module_unavailable"
    with pytest.raises(ActionValidationError) as unknown:
        await service.propose(tool_name="propose_launch_rocket", args={}, user_id=uuid.uuid4())
    assert unknown.value.code == "unknown_action"
