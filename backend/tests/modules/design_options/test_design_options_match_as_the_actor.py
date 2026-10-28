"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Generating a design option matches as the user who asked for it.

An imported price list is a user-owned catalogue, and so is its Match index.
The generate flow hands its matching to the element-matching service; the
user it passes along decides which imported catalogues the ranker may search.
Here the real match run and the real ranker routing run, so a project whose
region names another user's catalogue proves the actor actually arrives.
Only session creation, bulk confirm and the apply are stood in for.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.match_elements import service as match_service_module
from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_boq,
    make_option,
    make_project,
    make_set,
    make_user,
)
from tests.modules.design_options.test_design_options_generate import FakeMatchService
from tests.unit.test_match_catalogue_binding import (
    _bind,
    _private_catalogue,
    _record_routing,
    _text_session,
)


class _RealRunMatch(FakeMatchService):
    """Stand-in whose ``run_match`` is the real one, on a real text session."""

    def __init__(self, real: object) -> None:
        super().__init__()
        self.real = real
        self.actors: list[uuid.UUID | None] = []

    async def run_match(self, session, _session_id, req, actor_id):  # type: ignore[override]
        self.actors.append(actor_id)
        await self.real.run_match(session, self.session_id, req, actor_id)


async def _generate_as(session: AsyncSession, monkeypatch: pytest.MonkeyPatch, user, region: str) -> list[str]:
    from app.core.match_service import ranker_qdrant

    project = await make_project(session, user.id)
    project.region = region
    await session.flush()
    await _bind(session, project.id, region)
    option_set = await make_set(session, project.id)
    boq = await make_boq(session, project.id)
    option = await make_option(session, option_set, name="Brick", bim_model_id=uuid.uuid4(), boq_id=boq.id)
    real = match_service_module.get_service()
    text_sid = await _text_session(session, project.id, None)
    fake = _RealRunMatch(real)
    fake.session_id = text_sid
    monkeypatch.setattr(match_service_module, "get_service", lambda: fake)
    await session.commit()

    routed = _record_routing(monkeypatch)
    ranker_qdrant._catalog_status_cache.clear()
    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/generate/",
            json={"dry_run": True, "method": "vector"},
        )
    assert res.status_code == 200, res.text
    assert fake.actors == [user.id]
    monkeypatch.setattr(match_service_module, "get_service", lambda: real)
    return list(routed)


async def test_generate_matches_against_the_actors_catalogue_and_no_one_elses(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    name, private = await _private_catalogue(session, monkeypatch, alice.id)

    assert private in await _generate_as(session, monkeypatch, alice, name)
    bob_routed = await _generate_as(session, monkeypatch, bob, name)
    assert bob_routed, "B's generate never reached the ranker"
    assert private not in bob_routed
