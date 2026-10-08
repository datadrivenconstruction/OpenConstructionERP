# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A quantity rule finds what property search finds, on a real Revit wall.

The DDC import keeps at most 30 properties per element row in the database,
while the Parquet sidecar keeps every column. A Revit wall carries 60+
parameters with the phases near the end, so ``phase created`` was cut from the
row: property search (sidecar) found the walls of phase "Progetto", and a
quantity rule on the same parameter (database row) matched nothing.

Two fixes, each pinned here. The phase parameters now survive the cap. And a
rule, a dynamic group or the change review that names a property an element's
row lacks reads it from the model's sidecar for just those elements, so models
imported before this change work without a re-import. The rows in the
database are never rewritten by that read.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.bim_hub import dataframe_store as ds
from app.modules.bim_hub.ifc_processor import _excel_elements_to_bim_result
from app.modules.bim_hub.service import BIMHubService

# ── The cap keeps the phases ───────────────────────────────────────────────


def _revit_wall_row(phase: str = "Progetto") -> dict[str, Any]:
    # Header order as a DDC Revit export writes it: identity first, then the
    # instance parameters, phase parameters near the end.
    row: dict[str, Any] = {
        "id": "312001",
        "category": "OST_Walls",
        "name": "Muro 30",
        "type name": "Muro 30",
        "family name": "Basic Wall",
        "level": "Piano terra",
        "area": 12.5,
        "volume": 3.75,
        "length": 5.0,
    }
    for i in range(60):
        row[f"param {i:02d}"] = f"v{i}"
    row["phase created"] = phase
    row["phase demolished"] = "Nessuno"
    return row


def test_a_60_parameter_wall_keeps_its_phases(tmp_path: Path) -> None:
    result = _excel_elements_to_bim_result([_revit_wall_row()], tmp_path, geometry_supported=False)
    props = result["elements"][0]["properties"]
    assert props.get("phase created") == "Progetto"
    assert props.get("phase demolished") == "Nessuno"
    rule = SimpleNamespace(element_type_filter="", property_filter={"Phase Created": "Progetto"})
    element = SimpleNamespace(element_type=result["elements"][0].get("element_type"), properties=props, quantities={})
    assert BIMHubService._rule_matches_element(rule, element)


# ── Quantity source names a property the way the filter does ─────────────


@pytest.mark.parametrize("source", ["property:spessore", "property:Spessore", "property: SPESSORE "])
def test_a_property_quantity_source_resolves_its_key_like_the_filter(source: str) -> None:
    element = SimpleNamespace(properties={"spessore": "0.30"}, quantities={})
    assert BIMHubService._extract_quantity(element, source) == Decimal("0.30")


# ── Against the database ───────────────────────────────────────────────────

# Wall -> (phase created, fase restauro, spessore muro) in the SIDECAR. None
# of the three is in the database row: the cap dropped them.
WALLS: dict[str, tuple[str | None, str | None, str | None]] = {
    "312001": ("Progetto", "Consolidamento", "0.30"),
    "312002": ("PROGETTO", "consolidamento", "0.25"),
    "312003": ("  progetto ", None, "0.40"),
    "312004": ("Stato di fatto", "Consolidamento", "0.50"),
    "312005": ("Stato di fatto", "Demolizione", None),
}
# An element written by ``ensure_parquet`` before it had a mesh_ref: the
# sidecar row id is its stable_id.
NO_MESH_STABLE_ID = "a1b2c3d4-no-mesh"


@pytest_asyncio.fixture
async def session():
    from tests._pg import transactional_session

    async with transactional_session() as s:
        yield s


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    return tmp_path


def _sidecar_row(row_id: str, phase: str | None, fase: str | None, spessore: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {"id": row_id, "category": "Walls"}
    for i in range(60):
        row[f"param {i:02d}"] = f"v{i}"
    row["phase created"] = phase
    row["fase restauro"] = fase
    row["spessore muro"] = spessore
    return row


async def _capped_model(s, data_dir: Path):
    """A restoration model as imported before the fix: rows capped, sidecar complete."""
    from app.modules.bim_hub.models import BIMElement, BIMModel
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="O")
    s.add(owner)
    await s.flush()
    project = Project(id=uuid.uuid4(), name="Restauro", description="", owner_id=owner.id, currency="EUR")
    s.add(project)
    await s.flush()
    boq = BOQ(project_id=project.id, name="Computo", description="", status="draft", is_locked=False)
    s.add(boq)
    model = BIMModel(project_id=project.id, name="restauro.rvt", status="ready")
    s.add(model)
    await s.flush()

    capped = {"category": "Walls", **{f"param {i:02d}": f"v{i}" for i in range(29)}}
    by_ref: dict[str, uuid.UUID] = {}
    sidecar: list[dict[str, Any]] = []
    for mesh_ref, (phase, fase, spessore) in WALLS.items():
        el = BIMElement(
            model_id=model.id,
            stable_id=uuid.uuid4().hex,
            mesh_ref=mesh_ref,
            element_type="Walls",
            properties=dict(capped),
            quantities={"area": 10.0},
        )
        s.add(el)
        await s.flush()
        by_ref[mesh_ref] = el.id
        sidecar.append(_sidecar_row(mesh_ref, phase, fase, spessore))
    el = BIMElement(
        model_id=model.id,
        stable_id=NO_MESH_STABLE_ID,
        mesh_ref=None,
        element_type="Walls",
        properties=dict(capped),
        quantities={"area": 10.0},
    )
    s.add(el)
    await s.flush()
    by_ref[NO_MESH_STABLE_ID] = el.id
    sidecar.append(_sidecar_row(NO_MESH_STABLE_ID, "Progetto", "Consolidamento", "0.20"))
    # A door the rules' type filter skips, with the phase in its row.
    s.add(
        BIMElement(
            model_id=model.id,
            stable_id=uuid.uuid4().hex,
            mesh_ref="400001",
            element_type="Doors",
            properties={"category": "Doors", "phase created": "Progetto"},
            quantities={"area": 2.0},
        )
    )
    await s.flush()
    ds.write_dataframe(str(project.id), str(model.id), sidecar, data_root=data_dir / "bim")
    return project, boq, model, by_ref


def _search(project, model, data_dir: Path, column: str, value: str, by_ref: dict[str, uuid.UUID]) -> set[uuid.UUID]:
    """Element ids property search finds for ``column = value``, mapped like the viewer maps them."""
    rows = ds.query_parquet(
        str(project.id),
        str(model.id),
        columns=["id"],
        filters=[{"column": column, "op": "=", "value": value}],
        data_root=data_dir / "bim",
    )
    return {by_ref[str(r["id"])] for r in rows}


def _rule(project_id: uuid.UUID, name: str, property_filter: dict[str, str], source: str, unit: str):
    from app.modules.bim_hub.models import BIMQuantityMap

    return BIMQuantityMap(
        project_id=project_id,
        name=name,
        element_type_filter="Wall*",
        property_filter=property_filter,
        quantity_source=source,
        multiplier="1",
        waste_factor_pct="0",
        unit=unit,
        boq_target={"auto_create": True, "unit_rate": "10"},
        is_active=True,
    )


@pytest.mark.asyncio
async def test_rule_matches_exactly_what_property_search_finds(session, data_dir: Path) -> None:
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest

    project, _boq, model, by_ref = await _capped_model(session, data_dir)
    phase = _rule(project.id, "Muri di progetto", {"Phase Created": "Progetto"}, "area", "m2")
    # Not a key the import's priority list knows: only the sidecar read can find it.
    fase = _rule(project.id, "Consolidamenti", {" FASE RESTAURO ": "consolidamento"}, "property:Spessore Muro", "m")
    session.add_all([phase, fase])
    await session.flush()

    result = await BIMHubService(session).apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id, dry_run=True))

    def matched(rule) -> set[uuid.UUID]:
        return {uuid.UUID(r["element_id"]) for r in result.results if r["rule_id"] == str(rule.id)}

    def skipped(rule) -> set[uuid.UUID]:
        return {uuid.UUID(r["element_id"]) for r in result.skipped if r["rule_id"] == str(rule.id)}

    found_phase = _search(project, model, data_dir, "phase created", "Progetto", by_ref)
    assert found_phase == {by_ref["312001"], by_ref["312002"], by_ref["312003"], by_ref[NO_MESH_STABLE_ID]}
    assert matched(phase) == found_phase

    found_fase = _search(project, model, data_dir, "fase restauro", "Consolidamento", by_ref)
    assert found_fase == {by_ref["312001"], by_ref["312002"], by_ref["312004"], by_ref[NO_MESH_STABLE_ID]}
    # The quantity source is a capped property too, read back the same way.
    assert matched(fase) | skipped(fase) == found_fase
    assert skipped(fase) == set()
    quantities = {uuid.UUID(r["element_id"]): r["raw_quantity"] for r in result.results if r["rule_id"] == str(fase.id)}
    assert quantities[by_ref["312004"]] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_apply_writes_positions_and_leaves_the_element_rows_alone(session, data_dir: Path) -> None:
    from app.modules.bim_hub.models import BIMElement
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest
    from app.modules.boq.models import Position

    project, boq, model, by_ref = await _capped_model(session, data_dir)
    session.add(_rule(project.id, "Muri di progetto", {"Phase Created": "Progetto"}, "area", "m2"))
    await session.flush()

    service = BIMHubService(session)
    checked = await service.apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id))
    result = await service.apply_quantity_maps(
        QuantityMapApplyRequest(
            model_id=model.id,
            dry_run=False,
            preview_fingerprint=checked.preview_fingerprint,
        )
    )

    assert result.matched_elements == 4
    rows = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
    assert [Decimal(p.quantity) for p in rows] == [Decimal("40")]
    session.expire_all()
    stored = (await session.execute(select(BIMElement).where(BIMElement.id == by_ref["312001"]))).scalar_one()
    assert "phase created" not in stored.properties
    assert len(stored.properties) == 30


@pytest.mark.asyncio
async def test_a_model_without_a_sidecar_still_applies(session, data_dir: Path) -> None:
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest

    project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    (data_dir / "bim" / str(project.id) / str(model.id) / "elements.parquet").unlink()
    session.add(_rule(project.id, "Muri di progetto", {"Phase Created": "Progetto"}, "area", "m2"))
    await session.flush()

    result = await BIMHubService(session).apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id, dry_run=True))

    assert result.matched_elements == 0


@pytest.mark.asyncio
async def test_dynamic_group_reads_a_capped_property(session, data_dir: Path) -> None:
    project, _boq, model, by_ref = await _capped_model(session, data_dir)
    group = SimpleNamespace(
        project_id=project.id,
        model_id=None,
        filter_criteria={"property_filter": {"Fase Restauro": "Consolidamento"}},
        is_dynamic=True,
        element_ids=[],
    )

    members = await BIMHubService(session)._resolve_members_for_group(group)

    assert set(members) == _search(project, model, data_dir, "fase restauro", "Consolidamento", by_ref)


@pytest.mark.asyncio
async def test_change_review_candidates_read_a_capped_property(session, data_dir: Path) -> None:
    from app.modules.boq.change_review import ChangeReviewService

    project, _boq, model, by_ref = await _capped_model(session, data_dir)
    rule = _rule(project.id, "Muri di progetto", {"Phase Created": "Progetto"}, "property:spessore muro", "m")
    session.add(rule)
    await session.flush()

    candidates = await ChangeReviewService(session)._rule_candidates(model.id, rule, {})
    matched = {c.element_id for c in candidates if BIMHubService._rule_matches_element(rule, c)}

    assert matched == _search(project, model, data_dir, "phase created", "Progetto", by_ref)
    by_id = {c.element_id: c for c in candidates}
    assert BIMHubService._extract_quantity(by_id[by_ref["312002"]], rule.quantity_source) == Decimal("0.25")


@pytest.mark.asyncio
async def test_change_review_linked_elements_read_a_capped_quantity_source(session, data_dir: Path) -> None:
    """A position a rule created keeps counting its linked walls by the rule's quantity source.

    The linked elements count whatever their type (the rule may since have
    been narrowed), so the sidecar is read for them without a type check.
    """
    from app.modules.bim_hub.models import BIMElement
    from app.modules.boq.change_review import ChangeReviewService, rule_method_quantity

    project, _boq, model, by_ref = await _capped_model(session, data_dir)
    stable_ids = (
        (
            await session.execute(
                select(BIMElement.stable_id).where(BIMElement.id.in_([by_ref["312001"], by_ref["312004"]]))
            )
        )
        .scalars()
        .all()
    )
    review = ChangeReviewService(session)
    elems = list((await review._elements_by_stable_id(model.id, stable_ids)).values())
    rule = _rule(project.id, "Porte", {}, "property:Spessore Muro", "m")
    rule.element_type_filter = "Doors"

    assert rule_method_quantity(rule, elems) == Decimal("0")
    await review._fill_capped_properties(elems, rule, check_type=False)
    assert rule_method_quantity(rule, elems) == Decimal("0.80")


# ── "Test this rule": the unsaved rule runs on the server engine ─────────


def _draft(**overrides: Any):
    from app.modules.bim_hub.schemas import QuantityRuleDraft

    body: dict[str, Any] = {
        "element_type_filter": "Wall*",
        "property_filter": {"Phase Created": "Progetto"},
        "quantity_source": "property:Spessore Muro",
        "multiplier": "2",
        "waste_factor_pct": "10",
        "unit": "m",
    }
    body.update(overrides)
    return QuantityRuleDraft(**body)


@pytest.mark.asyncio
async def test_testing_an_unsaved_rule_selects_what_apply_selects(session, data_dir: Path) -> None:
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest, QuantityRulePreviewRequest

    project, _boq, model, by_ref = await _capped_model(session, data_dir)
    draft = _draft()

    preview = await BIMHubService(session).preview_quantity_rule(
        QuantityRulePreviewRequest(model_id=model.id, rule=draft)
    )

    saved = _rule(project.id, "Muri di progetto", draft.property_filter, draft.quantity_source, "m")
    saved.multiplier, saved.waste_factor_pct = draft.multiplier, draft.waste_factor_pct
    session.add(saved)
    await session.flush()
    applied = await BIMHubService(session).apply_quantity_maps(QuantityMapApplyRequest(model_id=model.id, dry_run=True))

    tested = {uuid.UUID(m.element_id) for m in preview.matches}
    assert tested == {uuid.UUID(r["element_id"]) for r in applied.results}
    assert tested == _search(project, model, data_dir, "phase created", "Progetto", by_ref)
    assert preview.skips == []
    assert preview.scanned == 7
    assert preview.matched_types == ["Walls"]
    # 0.30 + 0.25 + 0.40 + 0.20 = 1.15, x2, +10 %.
    assert preview.total_adjusted == pytest.approx(2.53)
    by_id = {uuid.UUID(m.element_id): m for m in preview.matches}
    assert by_id[by_ref["312003"]].raw_quantity == pytest.approx(0.40)
    assert by_id[by_ref["312003"]].adjusted_quantity == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_testing_an_unsaved_rule_reports_skips_with_their_reason(session, data_dir: Path) -> None:
    from app.modules.bim_hub.schemas import QuantityRulePreviewRequest

    _project, _boq, model, by_ref = await _capped_model(session, data_dir)
    service = BIMHubService(session)

    missing = await service.preview_quantity_rule(
        QuantityRulePreviewRequest(
            model_id=model.id, rule=_draft(property_filter={}, quantity_source="property:assente")
        )
    )
    assert {s.reason for s in missing.skips} == {"missing_property"}
    assert len(missing.skips) == 6
    assert missing.matches == []

    bad = await service.preview_quantity_rule(
        QuantityRulePreviewRequest(model_id=model.id, rule=_draft(multiplier="due"))
    )
    assert {s.reason for s in bad.skips} == {"invalid_decimal"}
    assert {uuid.UUID(s.element_id) for s in bad.skips} >= {by_ref["312001"]}


@pytest.mark.asyncio
async def test_the_preview_route_needs_access_to_the_model(session, data_dir: Path) -> None:
    from fastapi import HTTPException

    from app.modules.bim_hub.router import preview_quantity_rule
    from app.modules.bim_hub.schemas import QuantityRulePreviewRequest

    project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    service = BIMHubService(session)
    body = QuantityRulePreviewRequest(model_id=model.id, rule=_draft())

    result = await preview_quantity_rule(body, str(project.owner_id), service=service)
    assert len(result.matches) == 4

    with pytest.raises(HTTPException) as refused:
        await preview_quantity_rule(body, str(uuid.uuid4()), service=service)
    assert refused.value.status_code in (403, 404)


async def _row_counts(s, boq_id: uuid.UUID, model_id: uuid.UUID) -> tuple[int, int]:
    from sqlalchemy import func

    from app.modules.bim_hub.models import BIMElement, BOQElementLink
    from app.modules.boq.models import Position

    positions = (await s.execute(select(func.count()).select_from(Position).where(Position.boq_id == boq_id))).scalar()
    links = (
        await s.execute(
            select(func.count())
            .select_from(BOQElementLink)
            .join(BIMElement, BIMElement.id == BOQElementLink.bim_element_id)
            .where(BIMElement.model_id == model_id)
        )
    ).scalar()
    return int(positions or 0), int(links or 0)


@pytest.mark.asyncio
async def test_testing_a_rule_counts_what_apply_then_writes_and_writes_nothing(session, data_dir: Path) -> None:
    """On the capped 60-parameter walls: the test's selection and total are the apply's, and the test writes nothing."""
    from app.modules.bim_hub.models import BIMElement
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest, QuantityRulePreviewRequest
    from app.modules.boq.models import Position

    project, boq, model, by_ref = await _capped_model(session, data_dir)
    # Ids read now: the row check below expires every loaded instance.
    project_id, boq_id, model_id = project.id, boq.id, model.id
    draft = _draft(quantity_source="area", multiplier="1", waste_factor_pct="0", unit="m2")
    service = BIMHubService(session)

    before = await _row_counts(session, boq_id, model_id)
    preview = await service.preview_quantity_rule(QuantityRulePreviewRequest(model_id=model_id, rule=draft))
    assert not session.new and not session.dirty and not session.deleted
    await session.flush()
    assert await _row_counts(session, boq_id, model_id) == before == (0, 0)
    session.expire_all()
    stored = (await session.execute(select(BIMElement).where(BIMElement.id == by_ref["312001"]))).scalar_one()
    assert "phase created" not in stored.properties

    saved = _rule(project_id, "Muri di progetto", draft.property_filter, "area", "m2")
    session.add(saved)
    await session.flush()
    checked = await service.apply_quantity_maps(QuantityMapApplyRequest(model_id=model_id))
    applied = await service.apply_quantity_maps(
        QuantityMapApplyRequest(
            model_id=model_id,
            dry_run=False,
            preview_fingerprint=checked.preview_fingerprint,
        )
    )

    assert preview.match_count == applied.matched_elements == 4
    assert {uuid.UUID(m.element_id) for m in preview.matches} == {uuid.UUID(r["element_id"]) for r in applied.results}
    positions = (await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
    assert [Decimal(p.quantity) for p in positions] == [Decimal(str(preview.total_adjusted))] == [Decimal("40.0")]
    assert preview.sidecar == "full"


@pytest.mark.asyncio
async def test_the_test_lists_a_sample_but_counts_and_sums_every_element(
    session, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.bim_hub import service as service_module
    from app.modules.bim_hub.schemas import QuantityRulePreviewRequest

    _project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    monkeypatch.setattr(service_module, "PREVIEW_SAMPLE_LIMIT", 2)
    service = BIMHubService(session)

    preview = await service.preview_quantity_rule(QuantityRulePreviewRequest(model_id=model.id, rule=_draft()))
    assert (len(preview.matches), preview.match_count) == (2, 4)
    assert preview.total_adjusted == pytest.approx(2.53)

    missing = await service.preview_quantity_rule(
        QuantityRulePreviewRequest(
            model_id=model.id, rule=_draft(property_filter={}, quantity_source="property:assente")
        )
    )
    assert (len(missing.skips), missing.skip_count) == (2, 6)


@pytest.mark.asyncio
async def test_a_project_viewer_can_test_a_rule_but_not_apply_one(session, data_dir: Path) -> None:
    from fastapi import HTTPException

    from app.dependencies import RequirePermission
    from app.modules.bim_hub.permissions import register_bim_hub_permissions
    from app.modules.bim_hub.router import preview_quantity_rule
    from app.modules.bim_hub.schemas import QuantityRulePreviewRequest
    from app.modules.projects.member_schemas import AddProjectMemberRequest
    from app.modules.projects.member_service import add_project_member
    from app.modules.users.models import User

    project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    viewer = User(id=uuid.uuid4(), email=f"v-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="V")
    session.add(viewer)
    await session.flush()
    await add_project_member(session, project.id, AddProjectMemberRequest(user_id=viewer.id, role="viewer"))

    register_bim_hub_permissions()
    payload = {"sub": str(viewer.id), "role": "viewer", "permissions": []}
    # The test route asks for bim.read, which a viewer holds; apply asks for bim.create.
    await RequirePermission("bim.read")(payload)
    with pytest.raises(HTTPException) as no_apply:
        await RequirePermission("bim.create")(payload)
    assert no_apply.value.status_code == 403

    body = QuantityRulePreviewRequest(model_id=model.id, rule=_draft())
    result = await preview_quantity_rule(body, str(viewer.id), service=BIMHubService(session))
    assert result.match_count == 4

    with pytest.raises(HTTPException) as stranger:
        await preview_quantity_rule(body, str(uuid.uuid4()), service=BIMHubService(session))
    assert stranger.value.status_code in (403, 404)


# ── A sidecar rebuilt from the database rows says so ─────────────────────


def test_sidecar_state_tells_a_rebuilt_sidecar_from_the_converters(tmp_path: Path) -> None:
    root = tmp_path / "bim"
    ds.write_dataframe("p", "full", [{"id": "312001", "phase created": "Progetto"}], data_root=root)
    ds.write_dataframe("p", "rebuilt", [{"id": "312001", "stable_id": "s1"}], data_root=root, source=ds.SOURCE_DATABASE)
    # What the retry wrote before it stamped the source: stable_id and no other id.
    ds.write_dataframe("p", "old-retry", [{"stable_id": "s1", "element_type": "Walls"}], data_root=root)

    assert ds.sidecar_state("p", "full", data_root=root) == "full"
    assert ds.sidecar_state("p", "rebuilt", data_root=root) == "rebuilt"
    assert ds.sidecar_state("p", "old-retry", data_root=root) == "rebuilt"
    assert ds.sidecar_state("p", "none", data_root=root) == "missing"
    # The marker does not hide the columns or their labels.
    assert [c["name"] for c in ds.read_schema("p", "rebuilt", data_root=root)] == ["id", "stable_id"]


@pytest.mark.asyncio
async def test_the_rule_test_reports_a_rebuilt_sidecar(session, data_dir: Path) -> None:
    from app.modules.bim_hub.schemas import QuantityRulePreviewRequest

    project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    ds.write_dataframe(
        str(project.id),
        str(model.id),
        [{"id": "312001", "category": "Walls"}],
        data_root=data_dir / "bim",
        source=ds.SOURCE_DATABASE,
    )
    preview = await BIMHubService(session).preview_quantity_rule(
        QuantityRulePreviewRequest(model_id=model.id, rule=_draft())
    )
    assert preview.sidecar == "rebuilt"
    assert preview.match_count == 0


@pytest.mark.asyncio
async def test_the_parquet_status_tells_the_search_panel_the_sidecar_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.bim_hub import router as bim_router

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    model_id = uuid.uuid4()
    ds.write_dataframe("p1", str(model_id), [{"id": "1", "stable_id": "s"}], source=ds.SOURCE_DATABASE)

    async def _access(_service: Any, _model_id: Any, _user: Any) -> Any:
        return SimpleNamespace(project_id="p1", metadata_={"parquet_status": "ok"})

    monkeypatch.setattr(bim_router, "_verify_model_access", _access)
    body = await bim_router.get_parquet_status(model_id, user_id="u1", service=None)  # type: ignore[arg-type]
    assert body["sidecar"] == "rebuilt"
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_a_rebuilt_sidecar_keeps_the_revit_property_names(session, data_dir: Path) -> None:
    """The import lowercases every header; the rebuild must still show "Phase Created"."""
    project, _boq, model, _by_ref = await _capped_model(session, data_dir)
    model.metadata_ = {"column_labels": {"phase created": "Phase Created", "category": "Category"}}
    await session.flush()
    sidecar = data_dir / "bim" / str(project.id) / str(model.id) / "elements.parquet"
    sidecar.unlink()

    assert await BIMHubService(session).ensure_parquet(str(project.id), str(model.id))

    labels = {c["name"]: c.get("label") for c in ds.read_schema(str(project.id), str(model.id))}
    assert labels["phase created"] == "Phase Created"
    assert labels["category"] == "Category"
    assert ds.sidecar_state(str(project.id), str(model.id)) == "rebuilt"
