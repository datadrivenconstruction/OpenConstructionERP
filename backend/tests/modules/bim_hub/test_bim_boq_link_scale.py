# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A generated 50 000-element model through the real service, timed step by step.

Opt-in (``OE_BIM_SCALE=1``, element count from ``OE_BIM_SCALE_N``): it writes a
whole model, so it is a measurement, not a unit test. Every figure it asserts is
derived from the generator, so a wrong sum or a dropped element fails it.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.bim_hub.schemas import BIMElementCreate, BIMQuantityMapCreate, QuantityMapApplyRequest
from app.modules.bim_hub.service import BIMHubService

pytestmark = pytest.mark.skipif(os.environ.get("OE_BIM_SCALE") != "1", reason="scale measurement, opt-in")

N = int(os.environ.get("OE_BIM_SCALE_N", "50000"))


def _elements(n: int, *, bump_every: int = 0) -> list[BIMElementCreate]:
    out = []
    for i in range(n):
        vol = Decimal(i % 97 + 1) / 10
        if bump_every and i % bump_every == 0:
            vol += 1
        out.append(
            BIMElementCreate(
                stable_id=f"G{i:06d}",
                element_type="Wall" if i % 2 == 0 else "Slab",
                storey=f"L{i % 20}",
                quantities={"volume_m3": str(vol), "area_m2": str(vol * 4)},
                properties={"material": "C30/37" if i % 3 else "C25/30"},
                geometry_hash=f"h{i}-{int(bool(bump_every and i % bump_every == 0))}",
            )
        )
    return out


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_50k_model_maps_and_recomputes(session) -> None:
    from app.modules.bim_hub.models import BIMModel
    from app.modules.bim_hub.validators import register_bim_link_validation_rules
    from app.modules.boq.change_review import ChangeReviewService
    from tests.modules.bim_hub.test_bim_boq_link import _position, _project

    register_bim_link_validation_rules()
    timings: dict[str, float] = {}

    def tick(label: str, t0: float) -> None:
        timings[label] = round(time.perf_counter() - t0, 2)

    svc = BIMHubService(session)
    pid = await _project(session)
    pos = await _position(session, pid, unit="m3", rate="100")
    model = BIMModel(project_id=pid, name="Gen", status="ready", version="1")
    session.add(model)
    await session.flush()

    t0 = time.perf_counter()
    await svc.bulk_import_elements(model.id, _elements(N))
    tick("import", t0)

    await svc.create_quantity_map(
        BIMQuantityMapCreate(
            project_id=pid,
            name="Walls",
            element_type_filter="Wall",
            quantity_source="volume_m3",
            unit="m3",
            boq_target={"position_id": str(pos.id)},
        )
    )
    t0 = time.perf_counter()
    preview = await svc.apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id, dry_run=True))
    tick("rules_preview", t0)
    t0 = time.perf_counter()
    applied = await svc.apply_quantity_maps(
        QuantityMapApplyRequest(model_id=model.id, dry_run=False, preview_fingerprint=preview.preview_fingerprint)
    )
    tick("rules_apply", t0)
    walls = (N + 1) // 2
    assert applied.links_created == walls

    t0 = time.perf_counter()
    await svc.restore_model_quantity(pos.id)
    tick("quantity_sync", t0)
    await session.refresh(pos)
    expected = sum(Decimal(i % 97 + 1) / 10 for i in range(0, N, 2))
    assert Decimal(pos.quantity) == expected.quantize(Decimal("0.0001"))
    assert pos.metadata_["bim_link_quantity"]["element_count"] == walls

    t0 = time.perf_counter()
    report = await svc.link_check(model.id)
    tick("link_check", t0)
    assert report["unlinked_total"] == N - walls

    v2 = BIMModel(project_id=pid, name="Gen", status="ready", version="2", parent_model_id=model.id)
    session.add(v2)
    await session.flush()
    await svc.bulk_import_elements(v2.id, _elements(N, bump_every=50))
    t0 = time.perf_counter()
    diff = await svc.compute_diff(v2.id, model.id)
    tick("diff", t0)
    assert diff.diff_summary["modified"] == len(range(0, N, 50))
    assert diff.diff_summary["added"] == 0
    assert diff.diff_summary["deleted"] == 0

    t0 = time.perf_counter()
    proposals = await ChangeReviewService(session).bim_quantity_proposals(pos.boq_id)
    tick("impact_preview", t0)
    assert proposals is not None

    print(f"\nBIM scale N={N} " + " ".join(f"{k}={v}s" for k, v in timings.items()))
