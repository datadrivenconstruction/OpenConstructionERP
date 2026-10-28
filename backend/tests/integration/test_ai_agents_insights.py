"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project AI insights: ``GET /api/v1/ai-agents/insights``.

The project-dashboard "AI insights" widget reads this endpoint. There is no
separate insight table: each insight is distilled from a real completed
``AgentRun`` the user executed against the project. This pins:

* structured JSON output is parsed into title/summary/confidence/severity;
* plain-text output falls back to the humanised agent name + first line;
* running and empty-output runs are excluded (only finished, useful runs
  become insights);
* a project with no runs returns an empty list (not an error), so the widget
  shows its empty state.

Runs against the PostgreSQL cluster provisioned by ``tests/conftest.py``,
which binds the SQLAlchemy engine before any ``from app...`` import.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.ai_agents import models as _ai_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login_admin(client: AsyncClient) -> tuple[dict[str, str], uuid.UUID]:
    """Register + activate + login an admin, returning (headers, user_id)."""
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"ai-insights-{uuid.uuid4().hex[:8]}@agents.io"
    password = f"AiInsight{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Insight Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
        user_id = (await s.execute(select(User.id).where(User.email == email.lower()))).scalar_one()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


async def _make_project(client: AsyncClient, headers: dict[str, str]) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"Insights {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


async def _add_run(
    *,
    user_id: uuid.UUID,
    project_id: str,
    agent_name: str,
    status: str,
    final_output: str | None,
) -> None:
    from app.database import async_session_factory
    from app.modules.ai_agents.models import AgentRun

    async with async_session_factory() as s:
        s.add(
            AgentRun(
                agent_name=agent_name,
                project_id=uuid.UUID(project_id),
                user_id=user_id,
                status=status,
                user_input="Analyze this project",
                final_output=final_output,
                iterations=2,
                total_tokens=900,
                started_at="2026-06-01T10:00:00+00:00",
                finished_at="2026-06-01T10:00:05+00:00",
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_insights_empty_when_no_runs(http_client):
    headers, _uid = await _register_login_admin(http_client)
    project_id = await _make_project(http_client, headers)

    res = await http_client.get(
        f"/api/v1/ai-agents/insights?project_id={project_id}&limit=2",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json() == []


@pytest.mark.asyncio
async def test_insights_distill_structured_and_plaintext(http_client):
    headers, user_id = await _register_login_admin(http_client)
    project_id = await _make_project(http_client, headers)

    # Structured JSON output -> parsed directly.
    await _add_run(
        user_id=user_id,
        project_id=project_id,
        agent_name="cost_risk_scanner",
        status="completed",
        final_output=json.dumps(
            {
                "title": "Concrete price risk",
                "summary": "Unit rates for C30/37 trend 8% above budget.",
                "confidence": 0.82,
                "severity": "warning",
            }
        ),
    )
    # Plain-text output -> humanised agent name + first line.
    await _add_run(
        user_id=user_id,
        project_id=project_id,
        agent_name="boq_generator",
        status="completed",
        final_output="Generated 42 BOQ positions across 6 trades.\nReview the earthworks section.",
    )
    # Noise that must be excluded: a still-running run and a completed run
    # with no output.
    await _add_run(
        user_id=user_id,
        project_id=project_id,
        agent_name="cost_risk_scanner",
        status="running",
        final_output=None,
    )
    await _add_run(
        user_id=user_id,
        project_id=project_id,
        agent_name="classifier",
        status="completed",
        final_output="   ",
    )

    res = await http_client.get(
        f"/api/v1/ai-agents/insights?project_id={project_id}&limit=5",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    items = res.json()

    # Only the two useful completed runs become insights.
    assert len(items) == 2
    by_title = {i["title"]: i for i in items}

    assert "Concrete price risk" in by_title
    structured = by_title["Concrete price risk"]
    assert structured["summary"].startswith("Unit rates for C30/37")
    assert structured["confidence"] == pytest.approx(0.82)
    assert structured["severity"] == "warning"

    # Plain text: title is the humanised agent slug, summary is the first line.
    assert "Boq Generator" in by_title
    plain = by_title["Boq Generator"]
    assert plain["summary"] == "Generated 42 BOQ positions across 6 trades."
    assert plain["confidence"] is None
