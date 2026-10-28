"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the server tells a caller about one plant item, and the texts of a refusal.

``can`` on an item is answered by the functions the writes raise from, so the
client never has to copy a state rule. These tests pin three things: the
refusal each action gives in each state, how a refusal and the caller's right
become ``applies / allowed / reason``, and that no sub-code of a refusal
reaches a reader without a text in English and German.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.plant_register import calc
from app.modules.plant_register.errors import PlantError, blocked, conflict, worded
from app.modules.plant_register.fsm import ITEM_FSM, MANUAL_TARGETS
from app.modules.plant_register.messages import is_key_present
from app.modules.plant_register.schemas import Capability, ItemOut
from app.modules.plant_register.service import GONE_CODES, MANUAL_TARGETS_ORDERED, PlantService, item_verdict

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "plant_register"
_OPEN = ("identified", "specified", "enquired")
_CLOSED = ("handed_over", "cancelled")
MAY = {"applies": True, "allowed": True, "reason": None}
NO_RIGHT = {"applies": True, "allowed": False, "reason": "not_equipment_owner"}


def _item(status: str, **kw: Any) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), status=status, no_strategic_spare_reason="", item_class="other", **kw)


def _code(refusal: PlantError | None) -> str | None:
    return None if refusal is None else refusal.code


# ── the refusal of each action in each state ────────────────────────────────


@pytest.mark.parametrize("status", calc.ITEM_STATES)
def test_editing_is_refused_only_on_a_closed_item(status: str) -> None:
    assert _code(PlantService.edit_refusal(_item(status))) == ("item_closed" if status in _CLOSED else None)


@pytest.mark.parametrize("status", calc.ITEM_STATES)
def test_the_specification_is_open_until_the_route_is_set(status: str) -> None:
    expected = "item_closed" if status in _CLOSED else None if status in _OPEN else "specification_frozen"
    assert _code(PlantService.specification_refusal(_item(status))) == expected


@pytest.mark.parametrize("status", calc.ITEM_STATES)
@pytest.mark.parametrize("can_manage", [True, False])
def test_the_classification_needs_the_right_first_and_an_open_item_second(status: str, can_manage: bool) -> None:
    if status in _CLOSED:
        expected = "item_closed"
    elif not can_manage:
        expected = "manage_required"
    else:
        expected = None if status in _OPEN else "classification_frozen"
    assert _code(PlantService.classification_refusal(_item(status), can_manage=can_manage)) == expected


@pytest.mark.parametrize("status", calc.ITEM_STATES)
def test_the_route_is_frozen_from_ordered_on_and_on_a_cancelled_item(status: str) -> None:
    frozen = calc.is_ordered(status) or status == "cancelled"
    assert _code(PlantService.route_refusal(_item(status))) == ("route_frozen" if frozen else None)


@pytest.mark.parametrize("status", calc.ITEM_STATES)
def test_handover_exists_only_for_a_commissioned_item(status: str) -> None:
    refusal = PlantService.handover_refusal(_item(status), [], critical=False)
    assert _code(refusal) == (None if status == "commissioned" else "handover_needs_commissioned")


def test_handover_of_a_commissioned_item_lists_every_blocking_rule() -> None:
    spares = [SimpleNamespace(status="required", category="commissioning_spares")]
    refusal = PlantService.handover_refusal(_item("commissioned"), spares, critical=True)
    assert refusal is not None and refusal.code == "transition_blocked"
    assert [v["code"] for v in refusal.violations] == ["spares_not_handed_over", "critical_without_strategic_spares"]
    one = PlantService.handover_refusal(_item("commissioned"), spares, critical=False)
    assert one is not None and one.code == "spares_not_handed_over"


def _service(blockers: list[str]) -> PlantService:
    service = PlantService(None)  # type: ignore[arg-type]

    async def transition_blockers(project_id: Any, item: Any, view: Any, target: str) -> list[str]:
        return list(blockers)

    service.transition_blockers = transition_blockers  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("status", calc.ITEM_STATES)
@pytest.mark.parametrize("target", MANUAL_TARGETS_ORDERED)
async def test_a_step_without_an_edge_is_an_invalid_transition(status: str, target: str) -> None:
    refusal = await _service([]).transition_refusal(uuid.uuid4(), _item(status), {}, target)
    assert _code(refusal) == (None if ITEM_FSM.has_transition(status, target) else "invalid_transition")


@pytest.mark.asyncio
async def test_a_state_read_from_its_source_cannot_be_set_by_hand() -> None:
    refusal = await _service([]).transition_refusal(uuid.uuid4(), _item("route_set"), {}, "ordered")
    assert _code(refusal) == "state_read_from_source"


@pytest.mark.asyncio
async def test_a_guarded_step_forward_reads_the_rules_and_a_step_back_does_not() -> None:
    blockers = ["basis_quote_required", "route_inconsistent_with_package_plan:installer_mismatch"]
    forward = await _service(blockers).transition_refusal(uuid.uuid4(), _item("enquired"), {}, "route_set")
    assert forward is not None and forward.code == "transition_blocked"
    assert [(v["code"], v["reason"]) for v in forward.violations] == [
        ("basis_quote_required", ""),
        ("route_inconsistent_with_package_plan", "installer_mismatch"),
    ]
    single = await _service(blockers[:1]).transition_refusal(uuid.uuid4(), _item("specified"), {}, "enquired")
    assert _code(single) == "basis_quote_required"
    if ITEM_FSM.has_transition("enquired", "specified"):
        back = await _service(blockers).transition_refusal(uuid.uuid4(), _item("enquired"), {}, "specified")
        assert back is None


def test_the_ordered_targets_are_exactly_the_manual_ones() -> None:
    assert set(MANUAL_TARGETS_ORDERED) == set(MANUAL_TARGETS)
    assert len(MANUAL_TARGETS_ORDERED) == len(set(MANUAL_TARGETS_ORDERED))


# ── a refusal and the caller's right become one verdict ─────────────────────


@pytest.mark.parametrize("code", GONE_CODES)
@pytest.mark.parametrize("right", [MAY, NO_RIGHT])
def test_an_action_the_state_rules_out_does_not_apply_whoever_asks(code: str, right: dict[str, Any]) -> None:
    verdict = Capability(**item_verdict(conflict(code), right))
    assert (verdict.applies, verdict.allowed, verdict.reason) == (False, False, code)


def test_a_caller_without_the_right_reads_the_right_before_any_rule() -> None:
    verdict = item_verdict(blocked(["basis_quote_required"]), NO_RIGHT)
    assert verdict == {"applies": True, "allowed": False, "reason": "not_equipment_owner", "violations": []}
    assert item_verdict(None, NO_RIGHT)["reason"] == "not_equipment_owner"


def test_a_caller_with_the_right_reads_the_rule_and_every_blocker() -> None:
    refusal = blocked(["basis_quote_required", "delivery_limit_gap"])
    verdict = item_verdict(refusal, MAY)
    assert (verdict["applies"], verdict["allowed"], verdict["reason"]) == (True, False, "transition_blocked")
    assert [v["code"] for v in verdict["violations"]] == ["basis_quote_required", "delivery_limit_gap"]
    assert item_verdict(None, MAY) == {"applies": True, "allowed": True, "reason": None, "violations": []}


def test_a_right_that_is_missing_is_never_a_gone_code() -> None:
    assert not {"manage_required", "not_equipment_owner", "edit_permission_required"} & set(GONE_CODES)


@pytest.mark.asyncio
async def test_every_item_gets_every_action(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(["basis_quote_required"])

    async def capabilities(*args: Any, **kw: Any) -> dict[str, Any]:
        return {"edit": MAY, "manage": MAY}

    async def spares(project_id: Any, item_id: Any = None) -> list[Any]:
        return []

    service.capabilities = capabilities  # type: ignore[method-assign]
    service.repo = SimpleNamespace(spares=spares)  # type: ignore[assignment]
    views = [{"item": _item(s), "critical": False} for s in calc.ITEM_STATES]
    out = await service.item_capabilities(uuid.uuid4(), views, uuid.uuid4(), can_edit=True, can_manage=True)
    expected = {"edit", "edit_specification", "edit_classification", "set_route", "handover"}
    expected |= {f"transition_{t}" for t in MANUAL_TARGETS}
    for view in out:
        assert set(view["can"]) == expected, view["item"].status
        for verdict in view["can"].values():
            Capability(**verdict)
    by_status = {v["item"].status: v["can"] for v in out}
    assert by_status["specified"]["transition_enquired"]["reason"] == "basis_quote_required"
    assert by_status["handed_over"]["edit"] == {
        "applies": False,
        "allowed": False,
        "reason": "item_closed",
        "violations": [],
    }
    assert by_status["commissioned"]["handover"]["allowed"] is True


def test_an_item_response_without_capabilities_is_refused() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        ItemOut.from_view({"item": _item("identified")})


def _calls(function: str) -> set[str]:
    tree = ast.parse((_MODULE / "service.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == function)
    return {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


@pytest.mark.parametrize(
    ("write", "refusals"),
    [
        ("update_item", {"edit_refusal", "specification_refusal", "classification_refusal"}),
        ("set_route", {"route_refusal"}),
        ("transition_item", {"transition_refusal"}),
        ("handover", {"handover_blockers"}),
    ],
)
def test_each_write_raises_from_the_function_that_can_reads(write: str, refusals: set[str]) -> None:
    assert refusals <= _calls(write), write
    read = _calls("item_capabilities") | _calls("transition_refusal")
    assert (refusals - {"handover_blockers"}) <= read, write
    assert "handover_refusal" in read


# ── no sub-code reaches a reader without a text ─────────────────────────────


def _sub_reasons() -> set[str]:
    src = "\n".join((_MODULE / name).read_text(encoding="utf-8") for name in ("calc.py", "service.py"))
    found = set(re.findall(r'f"\{base\}:([a-z_]+)"', src)) | set(re.findall(r'"[a-z_]+:([a-z_]+)"', src))
    assert {"installer_mismatch", "currency"} <= found, "the scan no longer finds the sub-reasons"
    return found


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_sub_reason_of_a_refusal_has_a_text(locale: str) -> None:
    missing = [r for r in sorted(_sub_reasons()) if not is_key_present(f"plant.reasons.{r}", locale=locale)]
    assert not missing, missing


@pytest.mark.parametrize("locale", ["en", "de"])
def test_a_violation_is_worded_for_the_reader(locale: str) -> None:
    refusal = blocked(["route_inconsistent_with_package_plan:installer_mismatch", "route_missing"])
    rows = worded(refusal.violations, locale)
    first, second = rows
    assert first["reason"] == "installer_mismatch"  # still there for machines
    assert first["reason_key"] == "plant.reasons.installer_mismatch"
    assert first["reason_message"] and "_" not in first["reason_message"]
    assert first["message"] and first["message"] != first["message_key"]
    assert (second["reason"], second["reason_key"], second["reason_message"]) == ("", None, None)


@pytest.mark.parametrize("locale", ["en", "de"])
def test_the_route_rule_names_its_reason_in_words(locale: str) -> None:
    from app.modules.plant_register.validators import _reasons

    sub_reason = _reasons(["route_inconsistent_with_package_plan:installer_mismatch"], locale)
    whole_rule = _reasons(["package_plan_failed"], locale)
    both = _reasons(["route_inconsistent_with_package_plan:installer_mismatch", "package_plan_failed"], locale)
    assert both == f"{sub_reason}; {whole_rule}"
    for text in (sub_reason, whole_rule):
        assert text and not re.search(r"[a-z]+_[a-z]+", text), text


@pytest.mark.parametrize("locale", ["en", "de"])
@pytest.mark.parametrize(
    "label", ["no_area_hosts_plant", "no_phase_enables_construction_start", "frame_document_missing"]
)
def test_the_evidence_says_why_it_cannot_report_through_a_label(locale: str, label: str) -> None:
    assert is_key_present(f"plant.evidence.{label}", locale=locale)
    source = (_MODULE / "evidence.py").read_text(encoding="utf-8")
    assert not re.search(r'detail="[a-z_]+"', source), "a code in detail is shown to the reader as it stands"


def test_the_evidence_link_opens_the_register_page_of_the_project() -> None:
    from app.modules.plant_register import evidence
    from app.modules.project_governance.evidence import evidence_link_href, unregister_evidence_link
    from tests.pg.governance_fixtures import only_evidence

    project = uuid.uuid4()
    # Inside the helper the registry is this test's alone and is put back as it was on leaving.
    with only_evidence():
        unregister_evidence_link(evidence.LINK_KIND)
        assert evidence_link_href(evidence.LINK_KIND, str(project), project) is None
        evidence.register_gate_evidence()
        assert evidence_link_href(evidence.LINK_KIND, str(project), project) == f"/projects/{project}/plant-register"
    # The page is a route of the web app; a renamed route would leave the link dead.
    app_routes = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "App.tsx").read_text(
        encoding="utf-8"
    )
    assert 'path="/projects/:projectId/plant-register"' in app_routes
