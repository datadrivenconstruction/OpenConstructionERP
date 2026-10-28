"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PlantService._audit against the real ``log_activity``, not a mock.

A cloud PG run once failed 14 tests because ``_audit`` forwarded extras such as
``item=`` straight into ``log_activity``, which rejects unknown keywords. These
tests collect every keyword the service actually passes to ``_audit`` and send
each one through the real audit function.
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.audit_log import ActivityLog
from app.modules.plant_register.service import PlantService

_SERVICE = Path(__file__).resolve().parents[2] / "app" / "modules" / "plant_register" / "service.py"


class _StubSession:
    """Records added rows; no savepoint support, so ``log_activity`` uses its stub path."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


def _audit_keywords() -> set[str]:
    tree = ast.parse(_SERVICE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_audit":
            names.update(kw.arg for kw in node.keywords if kw.arg)
    return names


def test_the_service_passes_extras_to_audit() -> None:
    # Guards the test below against scanning nothing.
    # State changes are audited by the state machine itself; ``_audit`` carries the other writes.
    assert {"item", "route", "fields", "steps", "catalogue"} <= _audit_keywords()


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", sorted(_audit_keywords()))
async def test_every_audit_keyword_is_accepted_by_the_real_log_activity(keyword: str) -> None:
    session = _StubSession()
    service = PlantService(session)  # type: ignore[arg-type]
    value: Any = ["b", "a"] if keyword in {"fields", "steps"} else str(uuid.uuid4())
    await service._audit(uuid.uuid4(), "plant_item", uuid.uuid4(), "probe", **{keyword: value})
    rows = [r for r in session.added if isinstance(r, ActivityLog)]
    assert len(rows) == 1
    row = rows[0]
    assert row.module == "plant_register"
    if keyword in {"from_status", "to_status"}:
        assert getattr(row, keyword) == value
    else:
        assert row.metadata_[keyword] == value


@pytest.mark.asyncio
async def test_audit_metadata_is_json_plain() -> None:
    session = _StubSession()
    ref = uuid.uuid4()
    await PlantService(session)._audit(  # type: ignore[arg-type]
        None, "plant_item", ref, "probe", package=ref, amount=Decimal("1.10"), steps={"x"}
    )
    (row,) = session.added
    assert row.metadata_ == {"package": str(ref), "amount": "1.10", "steps": ["x"]}
    assert row.actor_id is None
