# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Readiness evidence provider registry: registration, blocking, failure, not-applicable areas."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.project_governance import evaluator as ev
from app.modules.project_governance import evidence as evd

pytestmark = pytest.mark.asyncio

ATTEMPT = evd.GateAttempt(gate_id=uuid.uuid4(), gate_code="g1", attempt_no=1)
PID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(evd._REGISTRY)
    links = dict(evd._LINK_ROUTES)
    evd._REGISTRY.clear()
    evd._LINK_ROUTES.clear()
    yield
    evd._REGISTRY.clear()
    evd._REGISTRY.update(saved)
    evd._LINK_ROUTES.clear()
    evd._LINK_ROUTES.update(links)


def _area(code: str, applicable: bool = True):
    return SimpleNamespace(code=code, applicable=applicable, retired=False)


def _ctx(evidence) -> ev.GateContext:
    return ev.GateContext(
        gate_code="g1",
        gate_status="in_review",
        areas=(ev.AreaState(code="site", owner_user_id="o", applicable=True),),
        documents=(),
        checks=(ev.CheckState(area_code="site", status="ready", confirmed_by="o"),),
        prior_conditions=(),
        today=date(2026, 10, 11),
        evidence=tuple(
            ev.EvidenceState(area_code=e.area_code, code=e.item.code, state=e.item.state, blocking=e.blocking)
            for e in evidence
        ),
    )


def _const(state: str, code: str = "x"):
    async def provider(session, project_id, attempt, area):
        return [evd.EvidenceItem(code=code, state=state, label_key="k", link=("hold_point", "1"))]

    return provider


async def test_registration_matches_area_code_and_wildcard() -> None:
    evd.register_evidence_provider("site", _const("met", "a"), name="p_site")
    evd.register_evidence_provider("*", _const("met", "b"), name="p_all")
    evd.register_evidence_provider("design", _const("met", "c"), name="p_design")
    got = await evd.collect_evidence(None, PID, ATTEMPT, [_area("site")])
    assert sorted(e.item.code for e in got) == ["a", "b"]
    assert {p.name for p in evd.evidence_providers()} == {"p_site", "p_all", "p_design"}
    assert got[0].as_dict()["link"] == {"kind": "hold_point", "id": "1", "href": None}


async def test_not_met_blocks_only_from_a_blocking_provider() -> None:
    evd.register_evidence_provider("site", _const("not_met", "info"), name="informative")
    got = await evd.collect_evidence(None, PID, ATTEMPT, [_area("site")])
    assert not [v for v in ev.gate_blockers(_ctx(got)) if v.code == "evidence_not_met"]

    evd.register_evidence_provider("site", _const("not_met", "hard"), name="blocking", blocking=True)
    got = await evd.collect_evidence(None, PID, ATTEMPT, [_area("site")])
    blockers = [v for v in ev.gate_blockers(_ctx(got)) if v.code == "evidence_not_met"]
    assert [(v.area_code, v.ref) for v in blockers] == [("site", "hard")]


async def test_a_failing_provider_shows_unknown_and_does_not_block(caplog) -> None:
    async def broken(session, project_id, attempt, area):
        raise RuntimeError("boom")

    evd.register_evidence_provider("site", broken, name="broken", blocking=True)
    evd.register_evidence_provider("site", _const("met", "ok"), name="fine")
    got = await evd.collect_evidence(None, PID, ATTEMPT, [_area("site")])
    states = {e.provider: (e.item.state, e.error) for e in got}
    assert states == {"broken": ("unknown", True), "fine": ("met", False)}
    assert not [v for v in ev.gate_blockers(_ctx(got)) if v.code == "evidence_not_met"]
    assert "broken" in caplog.text


async def test_a_not_applicable_area_is_not_asked() -> None:
    calls: list[str] = []

    async def spy(session, project_id, attempt, area):
        calls.append(area.code)
        return [evd.EvidenceItem(code="x", state="not_met")]

    evd.register_evidence_provider("*", spy, name="spy", blocking=True)
    got = await evd.collect_evidence(None, PID, ATTEMPT, [_area("site", applicable=False), _area("design")])
    assert calls == ["design"]
    assert {e.area_code for e in got} == {"design"}


async def test_an_invalid_state_is_rejected() -> None:
    with pytest.raises(ValueError):
        evd.EvidenceItem(code="x", state="maybe")


def _linked(kind: str = "plant_register", link_id: str = "42") -> evd.CollectedEvidence:
    item = evd.EvidenceItem(code="c", state="met", link=(kind, link_id))
    return evd.CollectedEvidence("site", "p", False, item)


async def test_a_link_opens_where_the_owning_module_registered_its_kind() -> None:
    evd.register_evidence_link("plant_register", "/projects/{project_id}/plant/{id}")
    assert _linked().as_dict(PID)["link"] == {
        "kind": "plant_register",
        "id": "42",
        "href": f"/projects/{PID}/plant/42",
    }


async def test_a_kind_nobody_registered_has_no_address() -> None:
    evd.register_evidence_link("plant_register", "/projects/{project_id}/plant")
    assert _linked("permits").as_dict(PID)["link"]["href"] is None


async def test_a_route_that_needs_the_project_gives_nothing_without_one() -> None:
    evd.register_evidence_link("plant_register", "/projects/{project_id}/plant")
    assert _linked().as_dict()["link"]["href"] is None
    evd.register_evidence_link("plant_register", "/plant/{id}")
    assert _linked().as_dict()["link"]["href"] == "/plant/42"


@pytest.mark.parametrize(
    "route",
    [
        "projects/{project_id}/plant",
        "https://elsewhere.example/{id}",
        "//elsewhere.example/x",
        "/plant/{name}",
        "/x/{}",
    ],
)
async def test_a_route_that_is_not_a_path_of_the_app_is_refused(route: str) -> None:
    with pytest.raises(ValueError, match="evidence link route"):
        evd.register_evidence_link("plant_register", route)
    assert "plant_register" not in evd._LINK_ROUTES
