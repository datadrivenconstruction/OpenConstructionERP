"""‌⁠‍In-process rank trace — sits in backend/ so import resolution matches the live server."""

import asyncio
import io
import logging
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("app.core.match_service").setLevel(logging.DEBUG)
logging.getLogger("app.modules.costs").setLevel(logging.DEBUG)


async def main():
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/openestimate.db")
    os.environ.setdefault("DATABASE_SYNC_URL", "sqlite:///./data/openestimate.db")
    from sqlalchemy import select

    from app.core.match_service import match_envelope
    from app.core.match_service.envelope import ElementEnvelope
    from app.database import async_session_factory
    from app.modules.costs.query_builder import build_search_plan
    from app.modules.projects.models import Project

    env = ElementEnvelope(
        source="boq",
        category="wall",
        description="Concrete C30/37 wall, 240mm reinforced",
        unit_hint="m2",
        project_currency="USD",
        project_region="US",
    )
    print(f"envelope: desc={env.description!r}")

    plan = build_search_plan(env)
    print(f"\nplan.dense_query: {plan.dense_query!r}")
    print(f"plan.hard_filters: {plan.hard_filters}")
    print(f"plan.soft_boosts: {plan.soft_boosts}")

    async with async_session_factory() as db:
        proj = (await db.execute(select(Project).where(Project.currency == "USD"))).scalar_one_or_none()
        if proj is None:
            print("no USD project")
            return
        pid = proj.id
        print(f"project: {pid} {proj.name}")
        resp = await match_envelope(env, project_id=pid, top_k=8, db=db)
    print(
        f"\nmatch_envelope: status={resp.status} catalog={resp.catalog_id} took={resp.took_ms}ms cands={len(resp.candidates)}"
    )
    for c in resp.candidates[:8]:
        print(
            f"  score={c.score:.4f} vec={c.vector_score:.4f} code={c.code!r:30} unit_rate={c.unit_rate} cur={c.currency!r}"
        )
        print(f"    desc={(c.description or '')[:80]!r}  boosts={c.boosts_applied}")


asyncio.run(main())
