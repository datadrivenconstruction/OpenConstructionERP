# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The one sanctioned way for a test to narrow the process-wide evidence registry."""

from __future__ import annotations

import pytest

from app.modules.project_governance import evidence as evd
from tests.pg.governance_fixtures import only_evidence


async def _answers(session, project_id, attempt, area):
    return []


@pytest.fixture
def registry():
    """Three providers of two modules, on top of whatever the process already holds."""
    before = dict(evd._REGISTRY)
    before_links = dict(evd._LINK_ROUTES)
    evd.register_evidence_provider("procurement", _answers, name="probe_packages", blocking=True)
    evd.register_evidence_provider("procurement", _answers, name="probe_awards", blocking=True)
    evd.register_evidence_provider("permits", _answers, name="probe_permits", blocking=True)
    yield before
    evd._REGISTRY.clear()
    evd._REGISTRY.update(before)
    evd._LINK_ROUTES.clear()
    evd._LINK_ROUTES.update(before_links)


def test_nothing_named_leaves_an_empty_registry_and_everything_comes_back(registry) -> None:
    whole = dict(evd._REGISTRY)
    assert {"probe_packages", "probe_awards", "probe_permits"} <= set(whole)
    with only_evidence():
        assert evd._REGISTRY == {}
    assert whole == evd._REGISTRY


def test_a_word_keeps_a_provider_by_name_or_every_provider_of_an_area(registry) -> None:
    with only_evidence("probe_permits"):
        assert set(evd._REGISTRY) == {"probe_permits"}
    with only_evidence("procurement"):
        assert {"probe_packages", "probe_awards"} <= set(evd._REGISTRY)
        assert "probe_permits" not in evd._REGISTRY
        assert all(p.key == "procurement" for p in evd._REGISTRY.values())


def test_what_a_test_registers_inside_is_gone_afterwards_also_when_it_fails(registry) -> None:
    whole = dict(evd._REGISTRY)
    links = dict(evd._LINK_ROUTES)

    def _mine() -> None:
        evd.register_evidence_provider("design", _answers, name="probe_design", blocking=True)
        evd.register_evidence_link("probe_kind", "/projects/{project_id}/probe/{id}")

    seen: dict[str, set[str]] = {}

    def _a_test_that_fails() -> None:
        with only_evidence(register=_mine):
            seen["providers"] = set(evd._REGISTRY)
            seen["links"] = set(evd._LINK_ROUTES)
            raise RuntimeError("the test failed")

    with pytest.raises(RuntimeError):
        _a_test_that_fails()
    assert seen["providers"] == {"probe_design"}
    assert "probe_kind" in seen["links"]
    assert whole == evd._REGISTRY
    assert links == evd._LINK_ROUTES
