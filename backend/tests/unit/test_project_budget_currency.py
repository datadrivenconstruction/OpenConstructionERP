"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every write path into ``oe_finance_budget`` must supply a currency.

``ProjectBudget.currency_code`` deliberately carries no database default
(``finance/models.py:197-206``): "no DB default; service code MUST supply
currency from the project context so per-project rollups don't silently
bias toward EUR". The column defaults to ``""`` in Python only so raw-SQL
backfills during migration stay safe.

Nothing enforced that contract, so four of the six construction sites
omitted the keyword and wrote budget lines with an empty currency. Those
rows reach the finance table with no currency at all, and ``MoneyDisplay``
- which correctly refuses to guess one - renders every cell as an
em-dash. The screen reads as lost numbers rather than an empty state.

The first test is a static gate rather than a behavioural one on purpose:
the defect is a *class* (a new write path forgetting the field), each
instance sits behind a different trigger (a demo install, an approved
estimate, an approved variation, a locked BOQ), and a gate that only
covers the four known sites would not catch the fifth.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from tests._pg import transactional_session

_APP_ROOT = Path(__file__).resolve().parents[2] / "app"
_MODEL = "ProjectBudget"
_REQUIRED_KEYWORD = "currency_code"


def _construction_sites(root: Path) -> list[tuple[Path, int, set[str]]]:
    """Return (file, lineno, keyword names) for every ``ProjectBudget(...)`` call."""
    found: list[tuple[Path, int, set[str]]] = []
    for path in root.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Cheap pre-filter - parsing every file under app/ is needless work.
        if f"{_MODEL}(" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != _MODEL:
                continue
            found.append((path, node.lineno, {kw.arg for kw in node.keywords if kw.arg}))
    return found


def test_every_project_budget_write_supplies_a_currency() -> None:
    """No ``ProjectBudget(...)`` may be constructed without ``currency_code``."""
    sites = _construction_sites(_APP_ROOT)

    # Guard the guard: if the scan finds nothing the assertion below is
    # vacuously true and this test would pass over a deleted model.
    assert sites, f"no {_MODEL}(...) construction sites found under {_APP_ROOT} - scan is broken"

    missing = [
        f"{path.relative_to(_APP_ROOT.parent)}:{lineno}"
        for path, lineno, keywords in sites
        if _REQUIRED_KEYWORD not in keywords
    ]
    assert not missing, (
        f"{_MODEL} written without {_REQUIRED_KEYWORD} at: {', '.join(missing)}. "
        "Resolve it from the project (see FinanceService.create_budget) - an "
        "empty currency renders as an em-dash instead of money."
    )


@pytest_asyncio.fixture
async def session_project():
    """Yield (session, project_id) for a USD project on an isolated PG session."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_id = uuid.uuid4()
        project_id = uuid.uuid4()
        s.add(
            User(
                id=owner_id,
                email=f"budget-{uuid.uuid4().hex[:6]}@test.io",
                hashed_password="x",
                full_name="Budget Owner",
            ),
        )
        await s.flush()
        s.add(
            Project(
                id=project_id,
                name="Budget Currency Test",
                owner_id=owner_id,
                currency="USD",
            ),
        )
        await s.commit()
        yield s, project_id


@pytest.mark.asyncio
async def test_create_budget_inherits_the_project_currency(session_project) -> None:
    """A budget line created without a currency picks up the project's.

    Regression pin, not evidence of the fix: this path
    (``FinanceService.create_budget``) already resolved the currency and is
    green before and after. It is here so the resolver cannot be dropped
    from the one write path that had it right.
    """
    from app.modules.finance.schemas import BudgetCreate
    from app.modules.finance.service import FinanceService

    session, project_id = session_project
    service = FinanceService(session)

    budget = await service.create_budget(
        BudgetCreate(
            project_id=project_id,
            category="Earthworks",
            original_budget="1000.00",
        ),
    )
    await session.commit()
    await session.refresh(budget)

    assert budget.currency_code == "USD"
