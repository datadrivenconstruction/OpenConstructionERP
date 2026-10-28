# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every demo project gets its permits and design data through the normal install, with no warning.

The permits and design seeders write through services that refuse a live change to a binding
frame. The governance story binds the frame first, so these projects used to log a skipped
seed and stay empty. The enrichment now records their history under ``RECORDING_DEMO_HISTORY``.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import select

from app.core.demo_history import RECORDING_DEMO_HISTORY
from tests.pg.test_every_pack_installs import fresh_db, pack_template_url  # noqa: F401  (fixtures)

pytestmark = pytest.mark.asyncio

_WATCHED = (
    "app.modules.permits",
    "app.modules.design_management",
    "app.core.demo_enrichment",
    "app.core.demo_projects",
)


@pytest.mark.timeout(1500)
async def test_every_demo_project_gets_permits_and_design_rows(fresh_db, caplog) -> None:  # noqa: F811
    from app.core.demo_enrichment import enrich_projects
    from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
    from app.modules.design_management.models import DesignSetup
    from app.modules.permits.models import PermitRoadmap

    caplog.set_level(logging.INFO)
    factory = fresh_db
    pids: dict[str, uuid.UUID] = {}
    for demo_id in sorted(DEMO_TEMPLATES):
        async with factory() as s:
            res = await install_demo_project(s, demo_id)
            await s.commit()
        pids[demo_id] = uuid.UUID(str(res["project_id"]))
    await enrich_projects(list(pids.values()))

    async with factory() as s:
        roadmaps = set((await s.execute(select(PermitRoadmap.project_id))).scalars())
        setups = set((await s.execute(select(DesignSetup.project_id))).scalars())
    missing = {d: (p in roadmaps, p in setups) for d, p in pids.items() if p not in roadmaps or p not in setups}
    assert not missing, f"demo projects without permits roadmap / design setup: {missing}"

    warnings = [
        f"{r.name}: {r.getMessage()}"
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith(_WATCHED)
    ]
    assert not warnings, "the demo install logged warnings:\n" + "\n".join(warnings[:40])
    # The flag does not outlive the seed.
    assert RECORDING_DEMO_HISTORY.get() is False
