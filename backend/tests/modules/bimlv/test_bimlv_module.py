"""BIM-LV rules, link materialisation and the import and export endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.bim_hub.models import BIMElement, BIMModel, BOQElementLink
from app.modules.bimlv import service
from app.modules.bimlv.container import (
    ContainerPosition,
    ModelReference,
    ParsedContainer,
    read_container,
    write_container,
)
from app.modules.bimlv.router import router as bimlv_router
from app.modules.bimlv.validators import (
    BIMLV_RULE_SET,
    LinksHitPositionsRule,
    LinksMaterialiseRule,
    ModelReferenceRule,
    PositionFiguresRule,
    UniqueOrdinalsRule,
    register_bimlv_validation_rules,
)
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

GUID_A = "2O2Fr$t4X7Zf8NOew3FLOH"
GUID_B = "0YTyKcx4v7ZvEjKqLHIl5G"


def _container(**over: object) -> dict:
    base = {
        "project_id": "p1",
        "positions": [
            {"ordinal": "01.001", "quantity": "12.5", "unit_rate": "80"},
            {"ordinal": "01.002", "quantity": "3", "unit_rate": "410.50"},
        ],
        "mapping": {"01.001": [GUID_A], "01.002": [GUID_A, GUID_B]},
        "model_ref": {"filename": "house.ifc", "model_id": "m1", "guid": ""},
        **over,
    }
    return {"container": base}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (
        UniqueOrdinalsRule,
        _container(),
        _container(positions=[{"ordinal": "01.001"}, {"ordinal": "01.001"}]),
    ),
    (PositionFiguresRule, _container(), _container(positions=[{"ordinal": "01.001", "quantity": "-4"}])),
    (PositionFiguresRule, _container(), _container(positions=[{"ordinal": "01.001", "unit_rate": "9e15"}])),
    (LinksHitPositionsRule, _container(), _container(mapping={"09.999": [GUID_A]})),
    (ModelReferenceRule, _container(), _container(model_ref={"filename": "", "model_id": "", "guid": ""})),
    (
        LinksMaterialiseRule,
        {**_container(), "result": {"unmatched_ordinals": [], "unmatched_guids": []}},
        {**_container(), "result": {"unmatched_ordinals": ["77"], "unmatched_guids": [GUID_B]}},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message
    assert "cost_rules." not in failed[0].message


@pytest.mark.asyncio
async def test_empty_container_passes_every_rule() -> None:
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {})), rule_cls.__name__
        assert all(r.passed for r in await _run(rule_cls(), _container(positions=[], mapping={}))), rule_cls.__name__


@pytest.mark.asyncio
async def test_unmatched_findings_name_what_is_missing() -> None:
    bad = {**_container(), "result": {"unmatched_ordinals": ["77"], "unmatched_guids": [GUID_B]}}
    texts = [r.message for r in await _run(LinksMaterialiseRule(), bad)]
    assert any("77" in t for t in texts)
    assert any(GUID_B in t for t in texts)
    de = (await _run(LinksMaterialiseRule(), bad, "de"))[0]
    assert de.message != texts[0]


def test_registered_under_rule_set() -> None:
    register_bimlv_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([BIMLV_RULE_SET])}
    assert "bimlv.ordinals_unique" in ids
    assert len(ids) == 5


# ── Service and API on real PostgreSQL ───────────────────────────────────────


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, object, User]]:
    register_bimlv_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"lv-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(bimlv_router, prefix="/v1/bimlv")

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, session, user


async def _project_with_bill(session, user: User) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A project with a two-position bill and a model of two elements; returns project, boq, model ids."""
    project = Project(name="LV test", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Bill 1")
    session.add(boq)
    await session.flush()
    for i, (ordinal, qty, rate) in enumerate((("01.001", "12.5", "80"), ("01.002", "3", "410.50"))):
        session.add(
            Position(
                boq_id=boq.id,
                ordinal=ordinal,
                description=f"Line {ordinal}",
                unit="m3",
                quantity=qty,
                unit_rate=rate,
                total=str(Decimal(qty) * Decimal(rate)),
                sort_order=i,
            )
        )
    model = BIMModel(project_id=project.id, name="house.ifc", model_format="ifc4", status="ready")
    session.add(model)
    await session.flush()
    for guid in (GUID_A, GUID_B):
        session.add(BIMElement(model_id=model.id, stable_id=guid, element_type="IfcWall"))
    await session.flush()
    await session.commit()
    return project.id, boq.id, model.id


def _bytes(mapping: dict[str, list[str]], positions: list[ContainerPosition] | None = None) -> bytes:
    positions = positions or [
        ContainerPosition(
            ordinal="01.001", description="Line", unit="m3", quantity=Decimal("12.5"), unit_rate=Decimal(80)
        ),
        ContainerPosition(
            ordinal="01.002", description="Line", unit="m3", quantity=Decimal(3), unit_rate=Decimal("410.5")
        ),
    ]
    return write_container(positions, mapping, ModelReference(filename="house.ifc", model_id="m1", schema="IFC4"))


@pytest.mark.asyncio
async def test_materialize_links_is_idempotent_and_reports_unmatched(ctx) -> None:
    _, session, user = ctx
    project_id, _, _ = await _project_with_bill(session, user)
    parsed = read_container(_bytes({"01.001": [GUID_A], "01.002": [GUID_A, GUID_B], "09.999": [GUID_B, "ghost"]}))
    first = await service.materialize_links(project_id, parsed, session, user_id=str(user.id))
    assert (first.created, first.skipped_existing, first.matched_ordinals, first.total_ordinals) == (3, 0, 2, 3)
    assert first.unmatched_ordinals == ["09.999"]
    again = await service.materialize_links(project_id, parsed, session, user_id=str(user.id))
    assert (again.created, again.skipped_existing) == (0, 3)
    rows = (await session.execute(select(BOQElementLink))).scalars().all()
    assert {r.link_type for r in rows} == {service.LINK_TYPE}


@pytest.mark.asyncio
async def test_materialize_links_does_not_cross_projects(ctx) -> None:
    _, session, user = ctx
    project_id, _, _ = await _project_with_bill(session, user)
    other_id, _, _ = await _project_with_bill(session, user)
    parsed = read_container(_bytes({"01.001": [GUID_A]}))
    res = await service.materialize_links(project_id, parsed, session)
    assert res.created == 1
    own = (
        await session.execute(
            select(BOQElementLink)
            .join(Position, Position.id == BOQElementLink.boq_position_id)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == other_id)
        )
    ).all()
    assert own == []


@pytest.mark.asyncio
async def test_import_endpoint_creates_links_and_reports_findings(ctx) -> None:
    c, session, user = ctx
    project_id, _, _ = await _project_with_bill(session, user)
    payload = _bytes({"01.001": [GUID_A], "01.002": [GUID_B, "ghost"]})
    r = await c.post(f"/v1/bimlv/projects/{project_id}/import", files={"file": ("x.bimlv", payload)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["unmatched_guids"] == ["ghost"]
    assert body["model_reference"]["filename"] == "house.ifc"
    assert {f["rule_id"] for f in body["findings"]} == {"bimlv.links_resolve_in_project"}


@pytest.mark.asyncio
async def test_import_endpoint_refuses_ambiguous_ordinals_before_linking(ctx) -> None:
    c, session, user = ctx
    project_id, _, _ = await _project_with_bill(session, user)
    twice = [
        ContainerPosition(ordinal="01.001", unit="m3", quantity=Decimal(1), unit_rate=Decimal(1)),
        ContainerPosition(ordinal="01.001", unit="m3", quantity=Decimal(2), unit_rate=Decimal(1)),
    ]
    r = await c.post(
        f"/v1/bimlv/projects/{project_id}/import",
        files={"file": ("x.bimlv", _bytes({"01.001": [GUID_A]}, twice))},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "bimlv.ordinals_unique"
    assert (await session.execute(select(BOQElementLink))).first() is None


@pytest.mark.asyncio
async def test_import_endpoint_rejects_a_file_that_is_not_a_container(ctx) -> None:
    c, session, user = ctx
    project_id, _, _ = await _project_with_bill(session, user)
    r = await c.post(f"/v1/bimlv/projects/{project_id}/import", files={"file": ("x.bimlv", b"not a zip")})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_export_then_import_round_trips_the_links(ctx) -> None:
    c, session, user = ctx
    project_id, boq_id, _ = await _project_with_bill(session, user)
    parsed = read_container(_bytes({"01.001": [GUID_A], "01.002": [GUID_B]}))
    await service.materialize_links(project_id, parsed, session)
    await session.commit()
    r = await c.get(f"/v1/bimlv/boqs/{boq_id}/export")
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"] == "application/zip"
    back = read_container(r.content)
    assert [p.ordinal for p in back.positions] == ["01.001", "01.002"]
    assert back.mapping == {"01.001": [GUID_A], "01.002": [GUID_B]}
    assert back.model_ref.filename == "house.ifc"
    assert back.positions[0].quantity == Decimal("12.5")


@pytest.mark.asyncio
async def test_export_of_a_missing_bill_is_404(ctx) -> None:
    c, _, _ = ctx
    r = await c.get(f"/v1/bimlv/boqs/{uuid.uuid4()}/export")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_check_container_without_blocking_returns_findings(ctx) -> None:
    parsed = ParsedContainer(
        positions=[ContainerPosition(ordinal="1"), ContainerPosition(ordinal="1")],
        mapping={"1": [GUID_A]},
    )
    findings = await service.check_container(uuid.uuid4(), parsed)
    ids = {f["rule_id"] for f in findings}
    assert {"bimlv.ordinals_unique", "bimlv.model_reference_stated"} <= ids
