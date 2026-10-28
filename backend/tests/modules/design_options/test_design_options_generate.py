"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``POST /options/{option_id}/generate/`` - preview and priced apply.

The generate flow is assembled from other platform services: the BIM hub owns
conversion, element matching owns turning a model into confirmed groups, and the
BOQ editor owns the money rollup. The matcher itself is substituted here so the
test exercises what this module actually decides - whether an option owns its
own bill, what a dry run is allowed to write, which arguments reach the matcher,
and how the priced totals land on the option row. The rollup, the FX handling
and the by-trade bucketing all run for real against seeded positions.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel
from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.design_options.models import DesignOption
from app.modules.documents.models import Document
from app.modules.match_elements import schemas as match_schemas
from app.modules.match_elements.models import MatchGroup, MatchSession
from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_boq,
    make_option,
    make_position,
    make_project,
    make_set,
    make_user,
)


class FakeMatchService:
    """Stand-in for the element-matching service, recording what it was asked.

    Only the four calls the design-options service makes are implemented. Every
    call is recorded so a test can assert on the arguments this module chose
    (the clamped match limits, the target BOQ, the auto-confirm threshold)
    rather than on the matcher's own behaviour, which has its own suite.
    """

    def __init__(self, *, positions: list[match_schemas.ApplyPositionPreview] | None = None) -> None:
        self.positions = positions or []
        self.created_sessions: list[match_schemas.SessionCreate] = []
        self.run_calls: list[match_schemas.RunMatchRequest] = []
        self.confirm_calls: list[match_schemas.BulkConfirmRequest] = []
        self.apply_calls: list[match_schemas.ApplyToBoqRequest] = []
        self.session_id = uuid.uuid4()
        self.created_session_ids: list[uuid.UUID] = []
        self.run_error: Exception | None = None
        self.grand_total = Decimal("0")
        self.currency = ""

    async def create_session(
        self,
        _session: AsyncSession,
        data: match_schemas.SessionCreate,
        created_by: uuid.UUID | None = None,
    ) -> Any:
        # The first session gets the well-known id a test can seed groups
        # against; any further session is a genuinely new one.
        new_id = self.session_id if not self.created_sessions else uuid.uuid4()
        self.created_sessions.append(data)
        self.created_session_ids.append(new_id)
        self.created_by = created_by
        return type("_Created", (), {"id": new_id})()

    async def run_match(
        self,
        _session: AsyncSession,
        _session_id: uuid.UUID,
        req: match_schemas.RunMatchRequest,
        _actor_id: uuid.UUID | None,
    ) -> None:
        self.run_calls.append(req)
        if self.run_error is not None:
            raise self.run_error

    async def bulk_confirm(
        self,
        _session: AsyncSession,
        _session_id: uuid.UUID,
        req: match_schemas.BulkConfirmRequest,
        _actor_id: uuid.UUID | None,
    ) -> None:
        self.confirm_calls.append(req)

    async def apply_to_boq(
        self,
        _session: AsyncSession,
        _session_id: uuid.UUID,
        req: match_schemas.ApplyToBoqRequest,
        _actor_id: uuid.UUID | None,
    ) -> match_schemas.ApplyToBoqResponse:
        self.apply_calls.append(req)
        return match_schemas.ApplyToBoqResponse(
            dry_run=req.dry_run,
            boq_id=req.target_boq_id,
            positions_created=0 if req.dry_run else len(self.positions),
            positions=self.positions,
            grand_total=self.grand_total,
            currency=self.currency,
        )


def preview_line(
    *,
    group_key: str = "ifc_class:IfcWall",
    description: str = "Concrete wall",
    unit: str = "m3",
    quantity: float = 12.0,
    unit_rate: str = "150.00",
    currency: str = "EUR",
    line_total: str = "1800.00",
    section_path: list[str] | None = None,
) -> match_schemas.ApplyPositionPreview:
    """One would-be BOQ line as the matcher would report it."""
    return match_schemas.ApplyPositionPreview(
        group_key=group_key,
        section_path=section_path if section_path is not None else ["300 Building construction"],
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=Decimal(unit_rate),
        currency=currency,
        line_total=Decimal(line_total),
    )


@pytest.fixture
def fake_match(monkeypatch: pytest.MonkeyPatch) -> FakeMatchService:
    """Substitute the matching service the generate flow reaches for."""
    fake = FakeMatchService()
    monkeypatch.setattr("app.modules.match_elements.service.get_service", lambda: fake)
    return fake


async def _make_bim_model(session: AsyncSession, project_id: uuid.UUID) -> BIMModel:
    """Persist a converted model the attach route will accept."""
    model = BIMModel(
        project_id=project_id,
        name=f"Model {uuid.uuid4().hex[:6]}",
        model_format="ifc",
        element_count=42,
        status="ready",
    )
    session.add(model)
    await session.flush()
    return model


async def _seed_match_session(session: AsyncSession, project_id: uuid.UUID, session_id: uuid.UUID) -> MatchSession:
    """Persist the match session the fake service claims to have created."""
    match_session = MatchSession(id=session_id, project_id=project_id, source="bim", name="Design option")
    session.add(match_session)
    await session.flush()
    return match_session


async def _seed_group(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    group_key: str,
    status: str,
    element_count: int,
) -> MatchGroup:
    group = MatchGroup(
        session_id=session_id,
        group_key=group_key,
        status=status,
        element_count=element_count,
    )
    session.add(group)
    await session.flush()
    return group


async def _reload(session: AsyncSession, option_id: uuid.UUID) -> DesignOption:
    """Read the option back from the database, not from the identity map.

    The service writes through ``update_option_fields``, a bulk UPDATE whose
    ``synchronize_session`` also patches the in-memory instance. A plain
    ``select`` would hand back that same patched instance, so the assertion
    could not tell a row that was written from one that was only synchronised.
    Expunging first forces a real load.
    """
    session.expunge_all()
    return (await session.execute(select(DesignOption).where(DesignOption.id == option_id))).scalar_one()


async def _positions_in(session: AsyncSession, boq_id: uuid.UUID) -> list[Position]:
    return list((await session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all())


# ── Preconditions ────────────────────────────────────────────────────────────


async def test_generate_without_an_attached_model_returns_400(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """An option with no model has nothing to estimate from."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 400, res.text
    assert "Attach a BIM model" in res.json()["detail"]
    assert fake_match.run_calls == []


async def test_generate_on_an_unknown_option_returns_404(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The option is resolved before any matching work starts."""
    user = await make_user(session)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{uuid.uuid4()}/generate/", json={"dry_run": True})

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_generate_on_another_users_option_returns_404(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Pricing someone else's option reads as a missing option."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 404, res.text
    assert fake_match.apply_calls == []


async def test_generate_rejects_an_out_of_range_threshold(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """``auto_confirm_threshold`` is a confidence, so it is bounded to 0..1."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel", bim_model_id=uuid.uuid4())
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/generate/",
            json={"dry_run": True, "auto_confirm_threshold": 1.5},
        )

    assert res.status_code == 422, res.text


# ── Dry run ──────────────────────────────────────────────────────────────────


async def test_dry_run_writes_no_positions_and_leaves_the_option_untouched(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The human-confirmed gate: a preview persists nothing about the money.

    Nothing else in the module guards this. A dry run may only report what the
    apply would produce; the option's bill must stay empty and its headline
    totals, status and counts must stay exactly as they were.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()
    fake_match.positions = [preview_line(), preview_line(group_key="ifc_class:IfcSlab", line_total="900.00")]
    fake_match.grand_total = Decimal("2700.00")
    fake_match.currency = "EUR"

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert body["positions_created"] == 0
    assert body["position_count"] == 2
    assert body["direct_cost"] == "2700.00"
    assert body["grand_total"] == "2700.00"
    assert body["markups_total"] == "0"
    # GFA 1000 against a 2700 direct cost.
    assert body["cost_per_m2"] == "2.70"
    assert [line["line_total"] for line in body["preview"]] == ["1800.00", "900.00"]

    assert await _positions_in(session, boq.id) == []
    stored = await _reload(session, option.id)
    assert stored.status == "draft"
    assert stored.grand_total == "0"
    assert stored.direct_cost == "0"
    assert stored.position_count == 0
    assert stored.breakdown == []


async def test_dry_run_asks_the_matcher_to_preview_into_the_options_own_boq(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Every apply is targeted at the option's own bill, never a shared one."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/generate/",
            json={"dry_run": True, "method": "lexical", "auto_confirm_threshold": 0.8, "top_k": 25},
        )

    assert res.status_code == 200, res.text
    assert len(fake_match.run_calls) == 1
    assert fake_match.run_calls[0].method == "lexical"
    assert fake_match.run_calls[0].top_k == 25
    assert fake_match.confirm_calls[0].threshold == pytest.approx(0.8)
    assert fake_match.apply_calls[0].dry_run is True
    assert fake_match.apply_calls[0].target_boq_id == boq.id


async def test_an_unrecognised_method_falls_back_to_vector(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """An unknown method never reaches the matcher as-is."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/generate/",
            json={"dry_run": True, "method": "telepathy"},
        )

    assert res.status_code == 200, res.text
    assert fake_match.run_calls[0].method == "vector"


async def test_a_matcher_failure_degrades_to_a_warning(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A broken matcher yields an empty preview and a named warning, not a 500."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()
    fake_match.run_error = RuntimeError("embedding backend unreachable")

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    assert "match_failed" in res.json()["warnings"]


async def test_a_matcher_http_error_is_passed_through(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A deliberate HTTP error from the matcher keeps its own status code."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()
    fake_match.run_error = HTTPException(status_code=409, detail="Session already running")

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 409, res.text


async def test_a_project_without_a_floor_area_warns_instead_of_dividing(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Cost per m2 is zero and flagged, never a division by zero."""
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area=None)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()
    fake_match.grand_total = Decimal("5000")

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cost_per_m2"] == "0"
    assert body["gfa"] == "0"
    assert "no_gfa" in body["warnings"]


# ── Option-owned bill of quantities ──────────────────────────────────────────


async def test_a_first_generate_gives_the_option_its_own_boq(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """An option with no bill gets one of its own, named after the set."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id, name="Frame options")
    option = await make_option(session, option_set, name="Steel", bim_model_id=uuid.uuid4())
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    stored = await _reload(session, option.id)
    assert stored.boq_id is not None
    assert str(stored.boq_id) == res.json()["boq_id"]
    boq = (await session.execute(select(BOQ).where(BOQ.id == stored.boq_id))).scalar_one()
    assert boq.name == "Frame options / Steel"
    assert boq.estimate_type == "design_option"
    assert boq.project_id == project.id


async def test_two_options_in_a_set_never_share_a_bill(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The anti-collapse invariant: each option carries a distinct ``boq_id``."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id, name="Frame options")
    steel = await make_option(session, option_set, name="Steel", sort_order=0, bim_model_id=uuid.uuid4())
    timber = await make_option(session, option_set, name="Timber", sort_order=1, bim_model_id=uuid.uuid4())
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        first = await client.post(f"{API_PREFIX}/options/{steel.id}/generate/", json={"dry_run": True})
        second = await client.post(f"{API_PREFIX}/options/{timber.id}/generate/", json={"dry_run": True})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["boq_id"] != second.json()["boq_id"]


async def test_an_existing_boq_is_reused_rather_than_replaced(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A second generate must not orphan the bill the first one created."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    assert res.json()["boq_id"] == str(boq.id)
    assert (await _reload(session, option.id)).boq_id == boq.id


async def test_the_match_session_is_created_once_and_then_reused(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The option's match session is scoped to its own model and kept."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    model_id = uuid.uuid4()
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=model_id,
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert len(fake_match.created_sessions) == 1
    created = fake_match.created_sessions[0]
    assert created.bim_model_id == model_id
    assert created.project_id == project.id
    assert created.source == "bim"
    assert (await _reload(session, option.id)).match_session_id == fake_match.session_id


async def test_re_sourcing_the_option_does_not_reuse_the_old_models_match_session(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A second model gets its own match session, not the first model's.

    ``match_session_id`` is scoped to the model it was created from. Carrying it
    across a re-attach would price the superseded design under the name of the
    new one, which is the same failure as a stale ``bim_model_id`` but one field
    over and invisible in the option's own row.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    first = await _make_bim_model(session, project.id)
    second = await _make_bim_model(session, project.id)
    option = await make_option(session, option_set, name="Steel", boq_id=boq.id)
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(first.id)},
        )
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(second.id)},
        )
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert len(fake_match.created_sessions) == 2
    assert fake_match.created_sessions[0].bim_model_id == first.id
    assert fake_match.created_sessions[1].bim_model_id == second.id
    stored = await _reload(session, option.id)
    assert stored.bim_model_id == second.id
    assert stored.match_session_id == fake_match.created_session_ids[1]


async def test_re_attaching_the_same_model_keeps_its_match_session(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Re-attaching the model already on the option is not a change."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    model = await _make_bim_model(session, project.id)
    option = await make_option(session, option_set, name="Steel", boq_id=boq.id)
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert len(fake_match.created_sessions) == 1
    assert (await _reload(session, option.id)).match_session_id == fake_match.session_id


async def test_attaching_an_unconverted_document_drops_the_match_session_too(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Losing the model loses the session that was scoped to it."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    model = await _make_bim_model(session, project.id)
    document = Document(
        project_id=project.id,
        name="plan.dwg",
        file_path="/tmp/plan.dwg",
        file_size=1024,
        metadata_={},
    )
    session.add(document)
    option = await make_option(session, option_set, name="Steel", boq_id=boq.id)
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )
        await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})
        await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"source_document_id": str(document.id)},
        )

    stored = await _reload(session, option.id)
    assert stored.status == "converting"
    assert stored.bim_model_id is None
    assert stored.match_session_id is None


# ── Apply ────────────────────────────────────────────────────────────────────


async def test_apply_prices_the_option_from_its_own_bill(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The persisted totals come from the BOQ rollup, as decimal strings."""
    user = await make_user(session)
    project = await make_project(session, user.id, gross_floor_area="200")
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    await make_position(session, boq.id, ordinal="01.001", quantity="10", unit_rate="100", total="1000")
    await make_position(
        session,
        boq.id,
        ordinal="01.002",
        unit="m2",
        quantity="20",
        unit_rate="50",
        total="1000",
        classification={"din276": "400"},
    )
    session.add(
        BOQMarkup(boq_id=boq.id, name="Overhead", markup_type="percentage", percentage="10", apply_to="direct_cost")
    )
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    match_session = await _seed_match_session(session, project.id, fake_match.session_id)
    await _seed_group(session, match_session.id, group_key="walls", status="confirmed", element_count=7)
    await _seed_group(session, match_session.id, group_key="slabs", status="applied", element_count=3)
    await session.commit()
    fake_match.positions = [preview_line()]

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is False
    assert body["status"] == "priced"
    assert body["direct_cost"] == "2000.00"
    assert body["markups_total"] == "200.00"
    assert body["grand_total"] == "2200.00"
    assert body["cost_per_m2"] == "10.00"
    assert body["currency"] == "EUR"
    assert body["element_count"] == 10
    assert body["groups_confirmed"] == 2
    assert body["is_mixed_currency"] is False

    stored = await _reload(session, option.id)
    assert stored.status == "priced"
    assert stored.direct_cost == "2000.00"
    assert stored.markups_total == "200.00"
    assert stored.grand_total == "2200.00"
    assert stored.cost_per_m2 == "10.00"
    assert stored.gfa == "200"
    assert stored.currency == "EUR"
    assert stored.position_count == 2
    assert stored.error == ""


async def test_apply_snapshots_the_cost_per_trade(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """The by-trade breakdown buckets by classification, biggest cost first."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    await make_position(
        session,
        boq.id,
        ordinal="01.001",
        quantity="10",
        unit_rate="100",
        total="1000",
        classification={"din276": "330"},
    )
    await make_position(
        session,
        boq.id,
        ordinal="02.001",
        unit="m2",
        quantity="5",
        unit_rate="600",
        total="3000",
        classification={"din276": "420"},
    )
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 200, res.text
    breakdown = res.json()["breakdown"]
    assert [entry["key"] for entry in breakdown] == ["400", "300"]
    assert breakdown[0]["label"] == "Building services"
    assert breakdown[0]["cost"] == "3000.00"
    assert breakdown[0]["unit"] == "m2"
    assert breakdown[0]["quantity"] == "5"
    assert breakdown[1]["cost"] == "1000.00"
    assert (await _reload(session, option.id)).breakdown == breakdown


async def test_apply_flags_a_bill_that_mixes_currencies(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A blended bill is surfaced as a warning, never summed silently."""
    user = await make_user(session)
    project = await make_project(session, user.id, currency="EUR")
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    await make_position(session, boq.id, ordinal="01.001", quantity="10", unit_rate="100", total="1000")
    await make_position(
        session,
        boq.id,
        ordinal="01.002",
        quantity="10",
        unit_rate="100",
        total="1000",
        metadata_={"currency": "USD"},
    )
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["is_mixed_currency"] is True
    assert "mixed_currency" in body["warnings"]


async def test_apply_reuses_groups_a_previous_preview_confirmed(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Confirming after a preview must not silently re-run the whole match.

    Re-matching would discard the picks the estimator just confirmed, which is
    the opposite of the human-confirmed contract.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    match_session = await _seed_match_session(session, project.id, fake_match.session_id)
    await _seed_group(session, match_session.id, group_key="walls", status="confirmed", element_count=4)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 200, res.text
    assert fake_match.run_calls == []
    assert fake_match.confirm_calls == []
    assert fake_match.apply_calls[0].dry_run is False


async def test_apply_without_a_prior_preview_matches_first(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """A direct apply on an unmatched session still runs the match once."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    await _seed_match_session(session, project.id, fake_match.session_id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": False})

    assert res.status_code == 200, res.text
    assert len(fake_match.run_calls) == 1
    assert len(fake_match.confirm_calls) == 1


async def test_group_counts_report_the_sessions_real_state(
    session: AsyncSession,
    fake_match: FakeMatchService,
) -> None:
    """Totals and confirmed counts are read from the session's groups."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(
        session,
        option_set,
        name="Steel",
        bim_model_id=uuid.uuid4(),
        boq_id=boq.id,
    )
    match_session = await _seed_match_session(session, project.id, fake_match.session_id)
    await _seed_group(session, match_session.id, group_key="walls", status="confirmed", element_count=6)
    await _seed_group(session, match_session.id, group_key="slabs", status="suggested", element_count=9)
    await _seed_group(session, match_session.id, group_key="doors", status="applied", element_count=2)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/generate/", json={"dry_run": True})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["groups_total"] == 3
    assert body["groups_confirmed"] == 2
    # Only confirmed / applied groups contribute elements to the option.
    assert body["element_count"] == 8
