# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pins for the independent review of the commitment release module (pure, no database)."""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.modules.commitment_release.router import router

CLIENT_DATE_PARAMS = {"today", "as_of"}
# Writes that may take a day from the caller, each with its reason. Anything else is a defect.
CLIENT_DATE_EXEMPT = {
    # A saved scenario is a what-if: "what would stopping cost on that day". The day is the question
    # itself, it is stored only on the scenario row, and no release, rate or decision ever reads it.
    ("/projects/{project_id}/scenarios", "as_of"),
}


def _routes() -> list[APIRoute]:
    return [r for r in router.routes if isinstance(r, APIRoute)]


def test_no_write_route_takes_a_date_from_the_caller() -> None:
    """The FX date and the validity of an assignment are the server's; only a GET may ask for a day."""
    offenders = []
    for route in _routes():
        if route.methods == {"GET"}:
            continue
        taken = ({p.name for p in route.dependant.query_params} | _body_fields(route)) & CLIENT_DATE_PARAMS
        taken = {name for name in taken if (route.path, name) not in CLIENT_DATE_EXEMPT}
        if taken:
            offenders.append((sorted(route.methods), route.path, sorted(taken)))
    assert offenders == []


def _body_fields(route: APIRoute) -> set[str]:
    """Field names of the JSON body models a route takes."""
    names: set[str] = set()
    for param in route.dependant.body_params:
        model = getattr(param.field_info, "annotation", None)
        names |= set(getattr(model, "model_fields", {}) or {})
    return names


def test_the_body_scan_sees_the_one_exempt_date_and_the_exemption_is_still_needed() -> None:
    """The scan reads request bodies (else the exemption list would be decoration), and nothing on it is stale."""
    seen = {
        (route.path, name)
        for route in _routes()
        if route.methods != {"GET"}
        for name in _body_fields(route) & CLIENT_DATE_PARAMS
    }
    assert seen == CLIENT_DATE_EXEMPT


def test_read_routes_still_offer_a_day() -> None:
    by_path = {r.path: r for r in _routes() if r.methods == {"GET"}}
    assert "today" in {p.name for p in by_path["/projects/{project_id}/items"].dependant.query_params}
    assert "as_of" in {p.name for p in by_path["/projects/{project_id}/exposure"].dependant.query_params}


def _flat(node: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in node.items():
        out |= _flat(value, f"{prefix}{key}.") if isinstance(value, dict) else {f"{prefix}{key}"}
    return out


def test_every_refusal_code_has_a_message_in_every_language_the_module_ships() -> None:
    """A refused action answers a code; a code without a message shows the raw key to the user."""
    import json
    import re
    from pathlib import Path

    import app.modules.commitment_release as module

    root = Path(module.__file__).parent
    codes: set[str] = set()
    for source in root.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        codes |= set(re.findall(r"(?:CommitmentError|conflict|forbidden|not_found)\(\s*\"([a-z_0-9]+)\"", text))
        codes |= set(re.findall(r"rationale=\"([a-z_0-9]+)\"", text))
    codes |= {"four_eyes_no_approver", "four_eyes_requester_is_approver", "commitment_guard_unavailable"}
    codes |= {"not_item_owner", "manage_required", "not_requester", "not_entitled_decider", "four_eyes_violation"}
    codes |= {"release_pending", "invalid_transition", "no_pending_release", "item_closed"}
    assert len(codes) > 60
    files = sorted((root / "messages").glob("*.json"))
    assert {"de.json", "en.json"} <= {f.name for f in files}
    for file in files:
        keys = _flat(json.loads(file.read_text(encoding="utf-8")))
        missing = sorted(c for c in codes if f"commitment.errors.{c}" not in keys)
        assert missing == [], (file.name, missing)


def test_every_parameter_a_method_reads_is_described_as_a_fraction_field() -> None:
    from app.modules.commitment_release.catalogue import (
        ABORT_BASIS_KIND,
        METHOD_PARAMETERS,
        parameter_fields,
        register_kinds,
    )
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    seen = set()
    for basis in get_catalogue_kind(ABORT_BASIS_KIND).shipped():
        fields = parameter_fields(basis)
        assert [f["name"] for f in fields] == list(basis.parameters)
        assert set(METHOD_PARAMETERS[basis.method]) <= {f["name"] for f in fields}
        for f in fields:
            assert (f["type"], f["unit"], f["min"], f["max"]) == ("fraction", "fraction_of_one", "0", "1")
            assert f["required"] is (f["default"] is None)
            assert f["label_key"] == f"commitment.abort_parameter.{f['name']}"
            seen.add(f["label_key"])
    assert seen
    import json
    from pathlib import Path

    import app.modules.commitment_release as module

    bundle = json.loads((Path(module.__file__).parent / "messages" / "en.json").read_text(encoding="utf-8"))
    assert seen <= _flat(bundle)


def test_parameters_of_another_basis_and_values_outside_a_share_are_refused() -> None:
    from app.modules.commitment_release.catalogue import ABORT_BASIS_KIND, parameter_violation, register_kinds
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    register_kinds()
    bases = {b.id: b for b in get_catalogue_kind(ABORT_BASIS_KIND).shipped()}
    fee = next(b for b in bases.values() if b.method == "fee_on_unperformed")
    presumed = next(b for b in bases.values() if b.method == "price_less_saved_costs")
    assert parameter_violation(fee, {"fee_pct": "0.1"}) is None
    assert parameter_violation(fee, {}) is None
    # The value entered under the fee basis does not ride along when the basis changes.
    assert parameter_violation(presumed, {"fee_pct": "0.1"}) == ("abort_parameter_not_in_basis", "fee_pct")
    assert parameter_violation(bases["custom"], {"fee_pct": "0.1"}) == ("abort_parameter_not_in_basis", "fee_pct")
    assert parameter_violation(None, {"fee_pct": "0.1"}) == ("abort_parameter_not_in_basis", "fee_pct")
    assert parameter_violation(fee, {"fee_pct": "10"}) == ("abort_parameter_invalid", "fee_pct")
    assert parameter_violation(fee, {"fee_pct": "-0.1"}) == ("abort_parameter_invalid", "fee_pct")
    assert parameter_violation(fee, {"fee_pct": "ten"}) == ("abort_parameter_invalid", "fee_pct")


def test_the_module_hears_events_again_after_the_bus_was_emptied(monkeypatch) -> None:
    """An app restarted in one process empties the bus; registering again must subscribe again."""
    import asyncio

    from app.core.events import event_bus
    from app.modules.commitment_release import events

    heard: list[tuple[str, str]] = []

    async def record(data: dict, *, verdict: str, session_factory=None) -> None:
        heard.append((data["target_id"], verdict))

    monkeypatch.setattr(events, "handle_route_event", record)
    kept = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    kept_wildcard = list(event_bus._wildcard_handlers)

    async def fire(target: str) -> None:
        await event_bus.publish("approval_routes.instance.completed", {"target_id": target})
        pending = event_bus.pending_tasks()
        if pending:
            await asyncio.gather(*pending)

    try:
        event_bus.clear()
        events.register_commitment_subscribers()
        asyncio.run(fire("first"))
        event_bus.clear()
        asyncio.run(fire("nobody listens"))
        events.register_commitment_subscribers()
        events.register_commitment_subscribers()
        asyncio.run(fire("second"))
        subscribed = {name for name, handlers in event_bus._handlers.items() if events._on_document in handlers}
    finally:
        event_bus.clear()
        event_bus._handlers.update(kept)
        event_bus._wildcard_handlers.extend(kept_wildcard)
    # Heard once per event while subscribed, never while the bus was empty, and not twice after two calls.
    assert heard == [("first", "approved"), ("second", "approved")]
    # Every document event of the table is subscribed.
    assert subscribed == set(events.DOCUMENT_EVENTS)


def test_no_shipped_text_of_the_module_lost_a_character_on_the_way() -> None:
    """Every catalogue, message bundle and source file is UTF-8 and holds no replacement character.

    A file written in a one byte code page and read back as UTF-8 turns the section sign into
    U+FFFD; the statute names of the abort bases are where that shows.
    """
    import json
    from pathlib import Path

    import app.modules.commitment_release as module

    root = Path(module.__file__).parent
    files = [f for f in root.rglob("*") if f.suffix in (".json", ".py")]
    assert len(files) > 20
    broken = [f.name for f in files if "�" in f.read_text(encoding="utf-8")]
    assert broken == []
    for lang in ("en", "de"):
        bundle = json.loads((root / "messages" / f"{lang}.json").read_text(encoding="utf-8"))
        names = bundle["commitment"]["catalogue"]
        assert "§ 648 BGB" in names["de_bgb_648"]["name"]
        assert "§ 8" in names["de_vob_b_8_1"]["name"]
        assert "§ 648 BGB" in names["de_vob_b_8_1"]["refers_to_bgb_648"]
