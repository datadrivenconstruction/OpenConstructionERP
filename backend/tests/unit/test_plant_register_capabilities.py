"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What ``PlantService.capabilities`` tells a caller, and the guard names of the router.

``applies`` is the server's word on whether an action exists in this state.
Editing and managing the register exist on every project, so a caller without
the right must see them refused with a reason, never hidden.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.plant_register.schemas import Capability
from app.modules.plant_register.service import PlantService

_ROUTER = Path(__file__).resolve().parents[2] / "app" / "modules" / "plant_register" / "router.py"
OWNER = uuid.uuid4()
OTHER = uuid.uuid4()


def _service(area: Any) -> PlantService:
    service = PlantService(None)  # type: ignore[arg-type]

    async def _area(project_id: uuid.UUID) -> Any:
        return area

    service._area = _area  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "can_edit", "can_manage", "edit", "manage"),
    [
        (OTHER, True, True, (True, None), (True, None)),
        (OWNER, True, False, (True, None), (False, "manage_required")),
        (OTHER, True, False, (False, "not_equipment_owner"), (False, "manage_required")),
        (OTHER, False, False, (False, "edit_permission_required"), (False, "manage_required")),
    ],
)
async def test_a_refused_action_still_applies(
    user: uuid.UUID, can_edit: bool, can_manage: bool, edit: tuple[bool, str | None], manage: tuple[bool, str | None]
) -> None:
    area = SimpleNamespace(owner_user_id=OWNER, deputy_user_id=None)
    can = await _service(area).capabilities(uuid.uuid4(), user, can_edit=can_edit, can_manage=can_manage)
    assert set(can) == {"edit", "manage"}
    for name, (allowed, reason) in (("edit", edit), ("manage", manage)):
        verdict = Capability(**can[name])  # the response model must accept exactly what the service answers
        assert verdict.applies is True, name
        assert (verdict.allowed, verdict.reason) == (allowed, reason), name


def test_the_response_model_does_not_invent_applies() -> None:
    with pytest.raises(ValueError, match="applies"):
        Capability(allowed=True, reason=None)  # type: ignore[call-arg]


def test_the_router_guards_carry_module_unique_names() -> None:
    """The IDOR census trusts a guard by name, so a generic ``_read`` must not be one."""
    tree = ast.parse(_ROUTER.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)}
    assert {"_plant_read", "_plant_edit", "_plant_manage"} <= defined
    assert not {"_read", "_edit", "_manage"} & defined
    for name in ("_plant_read", "_plant_edit", "_plant_manage"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        first = (
            fn.body[1]
            if isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
            else fn.body[0]
        )
        call = first.value.value if isinstance(first, ast.Expr) and isinstance(first.value, ast.Await) else None
        assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "verify_project_access", name
