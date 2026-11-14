# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every demo the public chooser offers is a real, seeded project in its own market.

The chooser (``frontend/src/shared/lib/demoProfiles.ts``) names each demo by its
``demo_id`` and pairs it with a UI language and a country pack. A slug with no
template would show a card that opens nothing; a template in another language
than the market switch sets would open German data under a French menu. The
install check runs the real seeder for the two demos added to the chooser and
counts what the project holds, so neither opens an empty screen.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import DEMO_TEMPLATES, SHOWCASE_DEMO_IDS, install_demo_project

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PROFILES_TS = REPO_ROOT / "frontend" / "src" / "shared" / "lib" / "demoProfiles.ts"
PACKS_DIR = REPO_ROOT / "packs"

_PROFILE = re.compile(r"slug: '([a-z0-9-]+)',\s*locale: '([A-Za-z-]+)',\s*pack: '([a-z0-9-]+)'")


def _profiles() -> list[tuple[str, str, str]]:
    return _PROFILE.findall(PROFILES_TS.read_text(encoding="utf-8"))


def test_the_chooser_offers_seven_demos() -> None:
    slugs = [slug for slug, _locale, _pack in _profiles()]
    assert len(slugs) == 7
    assert len(set(slugs)) == 7
    assert slugs[0] == "full-showcase-riyadh"
    assert {"school-paris", "office-shanghai"} <= set(slugs)


@pytest.mark.parametrize(("slug", "locale", "pack"), _profiles())
def test_each_demo_has_a_template_in_its_own_language_and_pack(slug: str, locale: str, pack: str) -> None:
    template = DEMO_TEMPLATES[slug]
    assert template.locale.split("-")[0] == locale.split("-")[0]
    assert (PACKS_DIR / pack).is_dir(), f"{slug}: pack {pack} is not shipped"
    positions = [item for section in template.sections for item in section[3]]
    assert len(positions) >= 25, f"{slug}: a thin bill would read as an empty demo"
    assert template.total_months > 0
    assert template.tender_packages or template.tender_companies


@pytest.mark.parametrize("demo_id", ["school-paris", "office-shanghai"])
def test_new_demos_are_seeded_on_a_fresh_install(demo_id: str) -> None:
    assert demo_id in SHOWCASE_DEMO_IDS


@pytest.mark.parametrize("demo_id", ["school-paris", "office-shanghai"])
async def test_new_demos_install_with_bill_schedule_budget_and_tender(demo_id: str) -> None:
    from app.modules.boq.models import BOQ, Position
    from app.modules.costmodel.models import BudgetLine
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.tendering.models import TenderPackage
    from tests._pg import transactional_session

    template = DEMO_TEMPLATES[demo_id]
    async with transactional_session() as session:
        result = await install_demo_project(session, demo_id)
        pid = uuid.UUID(result["project_id"])

        async def count(model, *where) -> int:
            return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()

        boq_ids = (await session.execute(select(BOQ.id).where(BOQ.project_id == pid))).scalars().all()
        assert boq_ids, "no bill of quantities"
        expected = sum(len(s[3]) for s in template.sections)
        quantities = (await session.execute(select(Position.quantity).where(Position.boq_id.in_(boq_ids)))).scalars()
        assert sum(1 for q in quantities if Decimal(str(q or 0)) > 0) >= expected
        schedule_ids = (await session.execute(select(Schedule.id).where(Schedule.project_id == pid))).scalars().all()
        assert schedule_ids, "no schedule"
        assert await count(Activity, Activity.schedule_id.in_(schedule_ids)) >= 6
        assert await count(BudgetLine, BudgetLine.project_id == pid) > 0, "no budget lines"
        assert await count(TenderPackage, TenderPackage.project_id == pid) > 0, "no tender package"


def test_full_showcase_description_states_the_direct_cost_of_its_bill() -> None:
    template = DEMO_TEMPLATES["full-showcase-riyadh"]
    direct = sum(item[3] * item[4] for section in template.sections for item in section[3])
    stated = re.search(r"SAR (\d+) million", template.project_description)
    assert stated, "the description names no direct cost"
    assert abs(int(stated.group(1)) * 1_000_000 - direct) / direct < 0.02
