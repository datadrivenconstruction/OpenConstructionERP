# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where the delivery model meets the rest of the platform: bus, gate screen, demo seed, `applies`.

Pure checks; the database side of each is in ``tests/pg``.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.delivery_model import seed
from app.modules.delivery_model.catalogue import DeliveryFormsCatalogue, validate_delivery_forms
from app.modules.delivery_model.fsm import MODEL_STATES
from app.modules.delivery_model.messages import is_key_present
from app.modules.delivery_model.service import DeliveryModelService
from tests.pg.delivery_fixtures import catalogue_body_with_forms

# The five forms of the catalogue an installed pack ships: no construction manager at risk among them.
PACK_FORMS = ("design_bid_build_split", "design_bid_build_single", "design_build", "partnering_two_stage", "integrator")


# ── the subscribers survive an emptied bus ──────────────────────────────────


async def test_the_module_subscribes_again_after_the_bus_was_emptied(monkeypatch) -> None:
    """A flag kept beside the bus outlived the handlers: after ``clear`` the module never heard an event again."""
    from app.core.events import EventBus
    from app.modules.delivery_model import events

    bus = EventBus()
    heard: list[str] = []

    async def frame(data: dict, **kw) -> bool:
        heard.append(data["document_id"])
        return True

    monkeypatch.setattr(events, "event_bus", bus)
    monkeypatch.setattr(events, "handle_frame_document", frame)
    events.register_delivery_model_subscribers()
    bus.clear()
    await bus.publish("project_governance.frame_document.state_changed", {"document_id": "lost"})
    assert heard == []
    events.register_delivery_model_subscribers()
    await bus.publish("project_governance.frame_document.state_changed", {"document_id": "heard"})
    assert heard == ["heard"]


def test_the_event_the_module_listens_for_is_the_one_governance_publishes() -> None:
    from pathlib import Path

    import app.modules.project_governance.service as governance
    from app.modules.delivery_model import events

    # Governance publishes the full name as a literal, and the module subscribes to the same literal.
    name = '"project_governance.frame_document.state_changed"'
    assert name in Path(governance.__file__).read_text(encoding="utf-8")
    assert f"subscribe_once({name}" in Path(events.__file__).read_text(encoding="utf-8")


# ── the gate screen can open the evidence, and every unknown says what to do ─


def test_every_evidence_link_kind_opens_the_delivery_page() -> None:
    from app.modules.delivery_model.evidence import PROVIDER_NAME, register_gate_evidence
    from app.modules.project_governance.evidence import (
        evidence_link_href,
        unregister_evidence_link,
        unregister_evidence_provider,
    )

    for kind in ("delivery_model", "delivery_ofi"):
        unregister_evidence_link(kind)
    assert evidence_link_href("delivery_model", "p1", "p1") is None
    register_gate_evidence()
    try:
        for kind in ("delivery_model", "delivery_ofi"):
            assert evidence_link_href(kind, "p1", "p1") == "/projects/p1/delivery"
    finally:
        unregister_evidence_provider(PROVIDER_NAME)


def test_every_unknown_evidence_item_has_its_own_code_and_a_sentence_in_both_languages() -> None:
    import re
    from pathlib import Path

    from app.modules.delivery_model import evidence

    source = Path(evidence.__file__).read_text(encoding="utf-8")
    blocks = re.findall(r"EvidenceItem\((.*?)\n\s*\)", source, flags=re.S)
    unknown = [b for b in blocks if 'state="unknown"' in b]
    assert len(unknown) == 2
    codes = [re.search(r'code="([a-z_]+)"', b).group(1) for b in unknown]
    keys = [re.search(r'label_key="([a-z_.]+)"', b).group(1) for b in unknown]
    known_codes = {re.search(r'code="([a-z_]+)"', b).group(1) for b in blocks if b not in unknown}
    assert len(set(codes)) == 2 and not set(codes) & known_codes
    for key in keys:
        assert is_key_present(key, "en") and is_key_present(key, "de"), key


# ── `applies`: does the action exist in this state ──────────────────────────


@pytest.mark.parametrize("status", MODEL_STATES)
def test_an_action_that_does_not_exist_in_a_state_does_not_apply(status) -> None:
    applies = DeliveryModelService._action_applies(status, has_approved=True)
    assert applies["withdraw"] is (status == "proposed")
    assert applies["reopen"] is (status == "binding")
    assert applies["close_reopening"] is (status in ("reopened", "under_evaluation"))
    assert applies["propose"] is (status in ("draft", "under_evaluation", "reopened"))
    assert applies["edit"] is (status in ("draft", "under_evaluation", "reopened"))


def test_giving_up_a_reopening_needs_an_approved_decision_to_go_back_to() -> None:
    assert DeliveryModelService._action_applies("under_evaluation", has_approved=False)["close_reopening"] is False


# ── the demo seed on a catalogue that lacks a preferred form ────────────────


def test_the_seed_compares_only_forms_the_pinned_catalogue_has() -> None:
    assert seed.forms_to_compare(PACK_FORMS) == ["design_bid_build_single", "design_build", "design_bid_build_split"]
    assert "cm_at_risk" in seed.DEMO_FORMS and "cm_at_risk" not in seed.forms_to_compare(PACK_FORMS)
    assert seed.forms_to_compare(("integrator",)) == ["integrator"]
    assert seed.forms_to_compare(()) == []
    shipped = ("design_bid_build_split", "design_bid_build_single", "design_build", "cm_at_risk", "integrator")
    assert seed.forms_to_compare(shipped) == list(seed.DEMO_FORMS)


def test_a_five_form_catalogue_like_a_packs_is_a_valid_catalogue() -> None:
    """The fixture the database test pins: if it did not validate, that test would prove nothing."""
    body = catalogue_body_with_forms(PACK_FORMS)
    catalogue = DeliveryFormsCatalogue.model_validate(body)
    assert [f.code for f in catalogue.forms] == list(PACK_FORMS)
    assert validate_delivery_forms(catalogue, "tenant") == []
    for code in seed.SEEDED_RISKS:
        assert catalogue.category(code) is not None


def test_before_construction_nothing_is_needed_before_the_start() -> None:
    today = date(2026, 10, 13)
    dates = seed.item_dates(today, pre_construction=True)
    start = today.toordinal() + seed.START
    assert dates["package_need"].toordinal() == today.toordinal() + seed.AWARD
    assert dates["switchboard_delivery"].toordinal() > start
    assert dates["switchboard_need"] > dates["switchboard_delivery"]
    assert dates["furniture_need"].toordinal() > start
    running = seed.item_dates(today, pre_construction=False)
    assert running["switchboard_delivery"].toordinal() == today.toordinal() + 100


def test_the_package_port_is_a_frozen_read_model() -> None:
    import dataclasses
    import uuid

    from app.modules.delivery_model import public

    names = [f.name for f in dataclasses.fields(public.PackageView)]
    assert names[:3] == ["id", "code", "title"]
    view = public.PackageView(
        uuid.uuid4(), "P1", "Works", "construction", "planned", "contractor", False, True, False, None, None
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.code = "P2"  # type: ignore[misc]
