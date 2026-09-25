# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a package raised from the bill takes the rows it was asked for.

"Send to tender" on a bill with no sections packaged nothing, and a priced
line loose at the top of the bill was left out of a whole-bill package. Every
top-level row is now a unit of scope, and one section can go on its own.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.tendering.schemas import CreatePackageFromBOQData
from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bill, _project

pytestmark = pytest.mark.asyncio


async def test_a_flat_bill_packages_every_line(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, [("a", "01", "Wall", "m3", None), ("b", "02", "Slab", "m2", None)])

    package = await TenderingService(pg_session).create_package_from_boq(
        CreatePackageFromBOQData(project_id=project.id, boq_id=boq.id, package_name="All")
    )

    template = {row["position_id"] for row in package.metadata_["line_item_template"]}
    assert template == {str(pos["a"].id), str(pos["b"].id)}


async def test_one_section_is_packaged_on_its_own(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(
        pg_session,
        project,
        [
            ("s1", "01", "Earthworks", "", None),
            ("dig", "01.01", "Dig", "m3", "s1"),
            ("s2", "02", "Concrete", "", None),
            ("pour", "02.01", "Pour", "m3", "s2"),
            ("loose", "03", "Site sign", "pcs", None),
        ],
    )
    svc = TenderingService(pg_session)

    one = await svc.create_package_from_boq(
        CreatePackageFromBOQData(project_id=project.id, boq_id=boq.id, section_ids=[pos["s2"].id], package_name="C")
    )
    assert {r["position_id"] for r in one.metadata_["line_item_template"]} == {str(pos["s2"].id), str(pos["pour"].id)}

    whole = await svc.create_package_from_boq(
        CreatePackageFromBOQData(project_id=project.id, boq_id=boq.id, package_name="All")
    )
    assert str(pos["loose"].id) in {r["position_id"] for r in whole.metadata_["line_item_template"]}, (
        "a priced line at the top of the bill was left out of a whole-bill package"
    )


async def test_a_pick_that_names_no_top_level_row_is_refused(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(
        pg_session, project, [("s1", "01", "Earthworks", "", None), ("dig", "01.01", "Dig", "m3", "s1")]
    )

    with pytest.raises(HTTPException) as exc:
        await TenderingService(pg_session).create_package_from_boq(
            CreatePackageFromBOQData(
                project_id=project.id, boq_id=boq.id, section_ids=[pos["dig"].id], package_name="Nested"
            )
        )
    assert exc.value.status_code == 422
