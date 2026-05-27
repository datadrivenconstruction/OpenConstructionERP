"""‌⁠‍Composite alert-rule expression evaluator.

Grammar:

    Node = LeafKPI | LeafField | LogicalOp

    LeafKPI    = {"op": "kpi", "code": str, "compare": Compare, "value": Decimal}
    LeafField  = {"op": "field", "source": str, "path": str, "compare": Compare,
                  "value": Any}
    LogicalOp  = {"op": "and" | "or" | "not", "operands": [Node, ...]}

    Compare    = "lt" | "lte" | "gt" | "gte" | "eq" | "neq"

Example — fire when CPI<0.95 AND the project is in execution phase:

    {
      "op": "and",
      "operands": [
        {"op": "kpi", "code": "cpi", "compare": "lt", "value": "0.95"},
        {"op": "field", "source": "project", "path": "phase",
         "compare": "eq", "value": "execution"}
      ]
    }

The evaluator is sandboxed — it can only:
    * call registered KPI formulas via :mod:`.kpis.compute`
    * read attributes off a small allow-list of source models
      (``project`` only at v1)

It does not exec/eval arbitrary code. Unknown operators raise; that
means a bogus expression fails closed (alert doesn't fire).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpis as _kpis

logger = logging.getLogger(__name__)


VALID_COMPARES = ("lt", "lte", "gt", "gte", "eq", "neq")
VALID_LOGICAL = ("and", "or", "not")


class AlertExpressionError(ValueError):
    """‌⁠‍Raised when an expression node is malformed."""


def _coerce_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _compare(lhs: Any, op: str, rhs: Any) -> bool:
    """‌⁠‍Comparison primitive — works on numeric + string types."""
    # If both look numeric, coerce to Decimal for fair comparison
    if isinstance(lhs, (int, float, Decimal)) or (isinstance(rhs, (int, float, Decimal))):
        try:
            lhs_n = _coerce_decimal(lhs)
            rhs_n = _coerce_decimal(rhs)
        except Exception:
            lhs_n = lhs
            rhs_n = rhs
        else:
            lhs, rhs = lhs_n, rhs_n
    if op == "lt":
        return lhs < rhs
    if op == "lte":
        return lhs <= rhs
    if op == "gt":
        return lhs > rhs
    if op == "gte":
        return lhs >= rhs
    if op == "eq":
        return lhs == rhs
    if op == "neq":
        return lhs != rhs
    raise AlertExpressionError(f"Unknown compare op: {op}")


async def _read_field(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    source: str,
    path: str,
) -> Any:
    """Read a single attribute from an allow-listed source row.

    Currently only ``project`` is allowed — extending this is intentional
    cross-module coupling and should be done via a new branch here.
    """
    if source == "project":
        if project_id is None:
            return None
        try:
            from app.modules.projects.models import Project  # type: ignore

            proj = await session.get(Project, project_id)
            if proj is None:
                return None
            return getattr(proj, path, None)
        except ImportError:
            return None
        except Exception:
            logger.debug("alert_dsl: project field read failed", exc_info=True)
            return None
    raise AlertExpressionError(f"Unknown field source: {source}")


async def evaluate_alert_expression(
    expression: dict[str, Any],
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate an alert expression tree.

    Returns ``(fired, trace)`` where ``trace`` records every leaf
    evaluation for audit/debug — embedded in the ``bi.alert.triggered``
    event payload so subscribers can show *why* the alert fired.
    """
    trace: dict[str, Any] = {}

    async def _eval(node: dict[str, Any], path: str) -> bool:
        if not isinstance(node, dict):
            raise AlertExpressionError(
                f"Expected dict at {path}, got {type(node).__name__}",
            )
        op = node.get("op")
        if op == "and":
            results = [await _eval(child, f"{path}.and[{i}]") for i, child in enumerate(node.get("operands") or [])]
            return all(results) if results else True
        if op == "or":
            results = [await _eval(child, f"{path}.or[{i}]") for i, child in enumerate(node.get("operands") or [])]
            return any(results) if results else False
        if op == "not":
            operands = node.get("operands") or []
            if not operands:
                return True
            return not await _eval(operands[0], f"{path}.not")
        if op == "kpi":
            code = str(node.get("code") or "")
            compare = str(node.get("compare") or "lt")
            rhs = node.get("value")
            if compare not in VALID_COMPARES:
                raise AlertExpressionError(
                    f"Invalid compare '{compare}' at {path}",
                )
            result = await _kpis.compute(
                code,
                session,
                project_id=project_id,
            )
            lhs = result.value
            outcome = _compare(lhs, compare, _coerce_decimal(rhs))
            trace[path] = {
                "kpi": code,
                "compare": compare,
                "lhs": str(lhs),
                "rhs": str(rhs),
                "outcome": outcome,
            }
            return outcome
        if op == "field":
            source = str(node.get("source") or "")
            field_path = str(node.get("path") or "")
            compare = str(node.get("compare") or "eq")
            rhs = node.get("value")
            if compare not in VALID_COMPARES:
                raise AlertExpressionError(
                    f"Invalid compare '{compare}' at {path}",
                )
            lhs = await _read_field(session, project_id, source, field_path)
            outcome = _compare(lhs, compare, rhs)
            trace[path] = {
                "field": f"{source}.{field_path}",
                "compare": compare,
                "lhs": str(lhs),
                "rhs": str(rhs),
                "outcome": outcome,
            }
            return outcome
        raise AlertExpressionError(f"Unknown op '{op}' at {path}")

    if not expression:
        return False, trace
    fired = await _eval(expression, "$")
    return fired, trace


__all__ = [
    "AlertExpressionError",
    "VALID_COMPARES",
    "VALID_LOGICAL",
    "evaluate_alert_expression",
]
