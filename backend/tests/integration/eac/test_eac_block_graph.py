# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for EAC block-graph persistence and its validation rules.

Two halves.

The **API half** drives the real router through ``httpx.AsyncClient`` over an
``ASGITransport``. A synchronous ``TestClient`` would create its own event loop
and bind the async session factory to it, so every await inside the app would
then belong to a loop the test is not running on.

The **rule half** proves each of the four ``eac_graph`` rules by constructing
the input it rejects and then re-running that same input with the rule removed
from the set. A rule that was never load-bearing shows up immediately: the
rejection survives its removal, because some neighbouring rule was carrying it.
Each rejecting fixture is kept minimal on purpose - a hand-built cycle is very
easy to accidentally also make dangling, and then both rules fire and neither is
proved.

Removal is done by registering the *other* rules into a scratch rule set and
validating against that, never by editing ``validators.py``. A source edit can
silently fail to apply; a registry call cannot.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Importing the ORM module registers the EAC tables with Base.metadata.
import app.modules.eac.models  # noqa: F401
from app.core.validation.engine import rule_registry, validation_engine
from app.main import create_app
from app.modules.eac.schemas_graph import BlockWrite, ConnectionWrite
from app.modules.eac.service import graph_body_to_validation_data, normalise_graph_body
from app.modules.eac.validators import (
    _EAC_GRAPH_RULES,
    EAC_GRAPH_RULE_SET,
    register_eac_graph_rules,
)

API = "/api/v1/eac"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    """Test client with the full app lifecycle, so the module loader runs."""
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    """Register, promote and log in a unique user; return its Bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"eac-graph-{unique}@blocks.io"
    password = f"EacGraph{unique}9"

    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "EAC Graph Tester"},
    )
    # Creating and deleting graphs needs EDITOR / MANAGER.
    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


# ── Graph builders ───────────────────────────────────────────────────────────


def _slots(*, out_type: str = "predicate", in_type: str = "predicate") -> list[dict[str, Any]]:
    """A block with one input and one output handle."""
    return [
        {"id": "in", "label": "in", "direction": "input", "dataType": in_type},
        {"id": "out", "label": "out", "direction": "output", "dataType": out_type},
    ]


def _block(
    client_id: str,
    *,
    kind: str = "and",
    color: str = "logic",
    slots: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    x: float = 0.0,
    y: float = 0.0,
) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "kind": kind,
        "color": color,
        "title": client_id.upper(),
        "position": {"x": x, "y": y},
        "slots": slots if slots is not None else _slots(),
        "params": params or {},
    }


def _conn(client_id: str, source: str, target: str, *, data_type: str = "predicate") -> dict[str, Any]:
    return {
        "client_id": client_id,
        "source_block_client_id": source,
        "source_slot_id": "out",
        "target_block_client_id": target,
        "target_slot_id": "in",
        "data_type": data_type,
    }


def _sound_graph() -> dict[str, Any]:
    """A two-block, one-wire graph with nothing wrong with it."""
    return {
        "blocks": [_block("b1", x=10, y=20), _block("b2", x=220, y=20)],
        "connections": [_conn("c1", "b1", "b2")],
    }


# ── Rule-level helpers ───────────────────────────────────────────────────────


async def _findings(body: dict[str, Any], *, exclude_rule_id: str | None = None) -> list[str]:
    """Rule ids that fail on ``body``, optionally with one rule removed.

    With ``exclude_rule_id`` set, the remaining rules are registered into a
    throwaway rule set and the graph validated against that instead. The
    scratch set is always torn down, so a failing assertion cannot leave the
    process-global registry holding a stray set for later tests.
    """
    blocks = [BlockWrite.model_validate(b) for b in body["blocks"]]
    connections = [ConnectionWrite.model_validate(c) for c in body["connections"]]
    data = graph_body_to_validation_data(blocks, connections)

    if exclude_rule_id is None:
        report = await validation_engine.validate(data=data, rule_sets=[EAC_GRAPH_RULE_SET])
        return sorted({r.rule_id for r in report.results if not r.passed and not r.is_engine_error})

    probe_set = f"eac_graph_probe_{uuid.uuid4().hex[:8]}"
    survivors = [r for r in _EAC_GRAPH_RULES if r.rule_id != exclude_rule_id]
    assert len(survivors) == len(_EAC_GRAPH_RULES) - 1, (
        f"rule id {exclude_rule_id!r} does not exist, so the removal check would "
        "silently run the full rule set and report a false pass"
    )
    try:
        for rule in survivors:
            rule_registry.register(rule, [probe_set])
        report = await validation_engine.validate(data=data, rule_sets=[probe_set])
        return sorted({r.rule_id for r in report.results if not r.passed and not r.is_engine_error})
    finally:
        rule_registry.unregister_rule_set(probe_set)


@pytest.fixture(autouse=True)
def _rules_registered():
    """The rules land via the module ``on_startup`` hook, which unit runs skip."""
    register_eac_graph_rules()


# ── 1. The rule set is reachable at all ──────────────────────────────────────


@pytest.mark.asyncio
async def test_eac_graph_rule_set_resolves_to_rules() -> None:
    """A rule set nobody registers into reports a clean pass without running.

    Every assertion below asserts the *absence* of a finding on the clean path
    and the *presence* of one on the broken path. If the set were empty, the
    absence half would pass vacuously, so pin reachability first.
    """
    assert rule_registry.has_rules(EAC_GRAPH_RULE_SET)
    assert len(_EAC_GRAPH_RULES) == 4


@pytest.mark.asyncio
async def test_a_sound_graph_has_no_findings() -> None:
    """The control: the rejecting fixtures below must differ from this only in the defect."""
    assert await _findings(_sound_graph()) == []


# ── 2. Rule: dangling block / slot reference ─────────────────────────────────


def _dangling_graph() -> dict[str, Any]:
    """A wire whose target block is not on the canvas.

    Deliberately acyclic and type-clean, so only one rule can fire on it.
    """
    return {
        "blocks": [_block("b1")],
        "connections": [_conn("c1", "b1", "ghost")],
    }


def _dangling_slot_graph() -> dict[str, Any]:
    """Both blocks present, but the wire names a slot neither declares."""
    body = _sound_graph()
    body["connections"][0]["target_slot_id"] = "nonexistent"
    return body


@pytest.mark.asyncio
async def test_dangling_block_reference_is_rejected() -> None:
    assert await _findings(_dangling_graph()) == ["eac_graph.block_reference_exists"]


@pytest.mark.asyncio
async def test_dangling_slot_reference_is_rejected() -> None:
    """A foreign key could never catch this: the block exists, the slot does not."""
    assert await _findings(_dangling_slot_graph()) == ["eac_graph.block_reference_exists"]


@pytest.mark.asyncio
async def test_removing_the_reference_rule_lets_the_dangling_graph_through() -> None:
    """Removal check: without this rule, nothing else objects to a dangling wire."""
    assert await _findings(_dangling_graph(), exclude_rule_id="eac_graph.block_reference_exists") == []
    assert await _findings(_dangling_slot_graph(), exclude_rule_id="eac_graph.block_reference_exists") == []


# ── 3. Rule: cycles ──────────────────────────────────────────────────────────


def _cyclic_graph() -> dict[str, Any]:
    """A -> B -> C -> A. Every block present, every slot real, types compatible."""
    return {
        "blocks": [_block("b1"), _block("b2", x=200), _block("b3", x=400)],
        "connections": [
            _conn("c1", "b1", "b2"),
            _conn("c2", "b2", "b3"),
            _conn("c3", "b3", "b1"),
        ],
    }


def _self_loop_graph() -> dict[str, Any]:
    """The degenerate cycle. The canvas store refuses to draw one of these."""
    return {"blocks": [_block("b1")], "connections": [_conn("c1", "b1", "b1")]}


@pytest.mark.asyncio
async def test_cycle_is_rejected() -> None:
    assert await _findings(_cyclic_graph()) == ["eac_graph.no_cycles"]


@pytest.mark.asyncio
async def test_self_loop_is_rejected_as_a_cycle() -> None:
    assert await _findings(_self_loop_graph()) == ["eac_graph.no_cycles"]


@pytest.mark.asyncio
async def test_removing_the_cycle_rule_lets_the_cyclic_graph_through() -> None:
    """Removal check: the cycle fixture is otherwise entirely well-formed."""
    assert await _findings(_cyclic_graph(), exclude_rule_id="eac_graph.no_cycles") == []
    assert await _findings(_self_loop_graph(), exclude_rule_id="eac_graph.no_cycles") == []


@pytest.mark.asyncio
async def test_a_diamond_is_not_a_cycle() -> None:
    """Two paths converging is normal wiring, not a loop.

    A depth-first search that marks a node visited once and never clears it
    reports this as a cycle. Without this case the cycle rule could be wrong in
    the direction that blocks real work, and every other test would still pass.
    """
    body = {
        "blocks": [_block("b1"), _block("b2", x=200), _block("b3", x=200, y=200), _block("b4", x=400)],
        "connections": [
            _conn("c1", "b1", "b2"),
            _conn("c2", "b1", "b3"),
            _conn("c3", "b2", "b4"),
            _conn("c4", "b3", "b4"),
        ],
    }
    assert await _findings(body) == []


# ── 4. Rule: slot type compatibility ─────────────────────────────────────────


def _type_mismatch_graph() -> dict[str, Any]:
    """A predicate output feeding an attribute input. Acyclic, nothing dangling."""
    return {
        "blocks": [
            _block("b1", slots=[{"id": "out", "label": "o", "direction": "output", "dataType": "predicate"}]),
            _block("b2", x=200, slots=[{"id": "in", "label": "i", "direction": "input", "dataType": "attribute"}]),
        ],
        "connections": [_conn("c1", "b1", "b2")],
    }


def _backwards_wire_graph() -> dict[str, Any]:
    """A wire leaving an input and arriving at an output."""
    return {
        "blocks": [
            _block("b1", slots=[{"id": "out", "label": "o", "direction": "input", "dataType": "predicate"}]),
            _block("b2", x=200, slots=[{"id": "in", "label": "i", "direction": "output", "dataType": "predicate"}]),
        ],
        "connections": [_conn("c1", "b1", "b2")],
    }


@pytest.mark.asyncio
async def test_incompatible_slot_types_are_rejected() -> None:
    """Mirrors the canvas test `rejects type-mismatched connections`."""
    assert await _findings(_type_mismatch_graph()) == ["eac_graph.slot_type_compatible"]


@pytest.mark.asyncio
async def test_backwards_wire_is_rejected() -> None:
    assert await _findings(_backwards_wire_graph()) == ["eac_graph.slot_type_compatible"]


@pytest.mark.asyncio
async def test_removing_the_type_rule_lets_the_mismatch_through() -> None:
    """Removal check."""
    assert await _findings(_type_mismatch_graph(), exclude_rule_id="eac_graph.slot_type_compatible") == []
    assert await _findings(_backwards_wire_graph(), exclude_rule_id="eac_graph.slot_type_compatible") == []


@pytest.mark.asyncio
async def test_variable_output_into_a_number_input_is_allowed() -> None:
    """The compatibility matrix is not identity: variable feeds number."""
    body = {
        "blocks": [
            _block("b1", slots=[{"id": "out", "label": "o", "direction": "output", "dataType": "variable"}]),
            _block("b2", x=200, slots=[{"id": "in", "label": "i", "direction": "input", "dataType": "number"}]),
        ],
        "connections": [_conn("c1", "b1", "b2", data_type="variable")],
    }
    assert await _findings(body) == []


# ── 5. Rule: parameter domain ────────────────────────────────────────────────


def _one_bound_range_graph() -> dict[str, Any]:
    """`between` carrying a single bound. One block, no wires at all."""
    return {
        "blocks": [
            _block(
                "b1",
                kind="constraint",
                color="constraint",
                params={"operator": "between", "values": [5]},
            )
        ],
        "connections": [],
    }


def _unknown_operator_graph() -> dict[str, Any]:
    return {
        "blocks": [_block("b1", kind="constraint", color="constraint", params={"operator": "roughly", "value": 3})],
        "connections": [],
    }


def _unary_with_value_graph() -> dict[str, Any]:
    """`exists` takes no operand, but one is set."""
    return {
        "blocks": [_block("b1", kind="constraint", color="constraint", params={"operator": "exists", "value": 7})],
        "connections": [],
    }


def _bad_aggregate_graph() -> dict[str, Any]:
    return {
        "blocks": [_block("b1", kind="variable", color="variable", params={"aggregate": "median"})],
        "connections": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder",
    [
        _one_bound_range_graph,
        _unknown_operator_graph,
        _unary_with_value_graph,
        _bad_aggregate_graph,
    ],
    ids=["range_needs_two_bounds", "unknown_operator", "unary_carries_a_value", "unknown_aggregate"],
)
async def test_parameter_outside_its_domain_is_rejected(builder) -> None:
    assert await _findings(builder()) == ["eac_graph.parameter_domain"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder",
    [
        _one_bound_range_graph,
        _unknown_operator_graph,
        _unary_with_value_graph,
        _bad_aggregate_graph,
    ],
    ids=["range_needs_two_bounds", "unknown_operator", "unary_carries_a_value", "unknown_aggregate"],
)
async def test_removing_the_domain_rule_lets_bad_parameters_through(builder) -> None:
    """Removal check: these fixtures have no wires, so no other rule can fire."""
    assert await _findings(builder(), exclude_rule_id="eac_graph.parameter_domain") == []


@pytest.mark.asyncio
async def test_a_well_formed_range_constraint_passes() -> None:
    """The domain rule must accept the correct form, or it just rejects everything."""
    body = {
        "blocks": [
            _block(
                "b1",
                kind="constraint",
                color="constraint",
                params={"operator": "between", "values": [100, 250], "unit": "mm"},
            )
        ],
        "connections": [],
    }
    assert await _findings(body) == []


# ── 6. Normalisation ─────────────────────────────────────────────────────────


def test_duplicate_wire_on_the_same_slot_pair_is_collapsed() -> None:
    """The canvas store dedupes rather than rejects, so the server must too."""
    blocks = [BlockWrite.model_validate(_block("b1")), BlockWrite.model_validate(_block("b2"))]
    connections = [
        ConnectionWrite.model_validate(_conn("c1", "b1", "b2")),
        ConnectionWrite.model_validate(_conn("c2", "b1", "b2")),
    ]
    kept_blocks, kept_connections = normalise_graph_body(blocks, connections)
    assert len(kept_blocks) == 2
    assert [c.client_id for c in kept_connections] == ["c1"]


def test_a_dangling_wire_is_kept_not_quietly_dropped() -> None:
    """Deleting the evidence would let a broken graph report a clean validation."""
    blocks = [BlockWrite.model_validate(_block("b1"))]
    connections = [ConnectionWrite.model_validate(_conn("c1", "b1", "ghost"))]
    _, kept = normalise_graph_body(blocks, connections)
    assert [c.client_id for c in kept] == ["c1"]


# ── 7. API round trip ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_read_round_trips_the_canvas(client, auth_headers) -> None:
    """What the editor saved is what it gets back, ids and coordinates included."""
    payload = {"name": "Wall takeoff method", **_sound_graph()}
    created = await client.post(f"{API}/graphs", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Wall takeoff method"
    assert [b["client_id"] for b in body["blocks"]] == ["b1", "b2"]
    assert [b["ordinal"] for b in body["blocks"]] == [0, 1]
    assert body["blocks"][0]["position"] == {"x": 10.0, "y": 20.0}
    assert body["blocks"][0]["slots"][0]["dataType"] == "predicate"
    assert body["connections"][0]["source_block_client_id"] == "b1"
    assert body["validation_status"] == "passed"

    fetched = await client.get(f"{API}/graphs/{body['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["blocks"] == body["blocks"]
    assert fetched.json()["connections"] == body["connections"]


@pytest.mark.asyncio
async def test_expanded_is_not_persisted(client, auth_headers) -> None:
    """`expanded` is pure UI state; the store keeps it out of its own history."""
    payload = {"name": "no expanded", **_sound_graph()}
    created = await client.post(f"{API}/graphs", json=payload, headers=auth_headers)
    assert created.status_code == 201
    assert all("expanded" not in block for block in created.json()["blocks"])


@pytest.mark.asyncio
async def test_update_replaces_the_whole_canvas(client, auth_headers) -> None:
    created = await client.post(f"{API}/graphs", json={"name": "replace me", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]

    updated = await client.put(
        f"{API}/graphs/{graph_id}",
        json={"blocks": [_block("only")], "connections": []},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert [b["client_id"] for b in updated.json()["blocks"]] == ["only"]
    assert updated.json()["connections"] == []


@pytest.mark.asyncio
async def test_rename_leaves_the_canvas_alone(client, auth_headers) -> None:
    """Omitting blocks and connections must not be read as "delete everything"."""
    created = await client.post(f"{API}/graphs", json={"name": "before", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]

    renamed = await client.put(f"{API}/graphs/{graph_id}", json={"name": "after"}, headers=auth_headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "after"
    assert len(renamed.json()["blocks"]) == 2


@pytest.mark.asyncio
async def test_a_stale_revision_is_refused(client, auth_headers) -> None:
    """Two tabs editing one methodology must not silently overwrite each other."""
    created = await client.post(f"{API}/graphs", json={"name": "concurrent", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]
    revision = created.json()["revision"]

    first = await client.put(
        f"{API}/graphs/{graph_id}",
        json={"blocks": [_block("b1")], "connections": [], "expected_revision": revision},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["revision"] == revision + 1

    stale = await client.put(
        f"{API}/graphs/{graph_id}",
        json={"blocks": [_block("b9")], "connections": [], "expected_revision": revision},
        headers=auth_headers,
    )
    assert stale.status_code == 409
    still = await client.get(f"{API}/graphs/{graph_id}", headers=auth_headers)
    assert [b["client_id"] for b in still.json()["blocks"]] == ["b1"]


@pytest.mark.asyncio
async def test_an_incomplete_graph_still_saves_but_is_flagged(client, auth_headers) -> None:
    """A methodology mid-edit must persist; the estimator is told it is not sound."""
    created = await client.post(
        f"{API}/graphs", json={"name": "work in progress", **_dangling_graph()}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_status"] == "errors"
    assert [f["rule_id"] for f in body["validation"]["findings"]] == ["eac_graph.block_reference_exists"]
    # And it really is on disk, dangling wire and all.
    fetched = await client.get(f"{API}/graphs/{body['id']}", headers=auth_headers)
    assert fetched.json()["connections"][0]["target_block_client_id"] == "ghost"


@pytest.mark.asyncio
async def test_duplicate_remaps_ids_and_keeps_the_wiring(client, auth_headers) -> None:
    """The trap: copying wires verbatim leaves every one of them dangling."""
    created = await client.post(f"{API}/graphs", json={"name": "original", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]

    copied = await client.post(f"{API}/graphs/{graph_id}:duplicate", json={}, headers=auth_headers)
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["id"] != graph_id
    assert body["name"] == "original (copy)"

    new_ids = {b["client_id"] for b in body["blocks"]}
    assert new_ids.isdisjoint({"b1", "b2"}), "block ids must not be reused across graphs"
    # Every wire must land on a block of the copy, not on an id from the source.
    endpoints = {c["source_block_client_id"] for c in body["connections"]} | {
        c["target_block_client_id"] for c in body["connections"]
    }
    assert endpoints <= new_ids
    # Topology preserved: still exactly one wire, and the copy validates clean.
    assert len(body["connections"]) == 1
    assert body["validation_status"] == "passed"

    # The original is untouched.
    original = await client.get(f"{API}/graphs/{graph_id}", headers=auth_headers)
    assert [b["client_id"] for b in original.json()["blocks"]] == ["b1", "b2"]


@pytest.mark.asyncio
async def test_delete_removes_the_graph_and_its_canvas(client, auth_headers) -> None:
    created = await client.post(f"{API}/graphs", json={"name": "doomed", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]

    deleted = await client.delete(f"{API}/graphs/{graph_id}", headers=auth_headers)
    assert deleted.status_code == 204
    gone = await client.get(f"{API}/graphs/{graph_id}", headers=auth_headers)
    assert gone.status_code == 404


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_list_returns_the_tenant_own_graphs(client, auth_headers) -> None:
    name = f"listed-{uuid.uuid4().hex[:6]}"
    await client.post(f"{API}/graphs", json={"name": name, **_sound_graph()}, headers=auth_headers)

    listed = await client.get(f"{API}/graphs", params={"search": name}, headers=auth_headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert [r["name"] for r in rows] == [name]
    assert rows[0]["block_count"] == 2
    assert rows[0]["connection_count"] == 1
    assert "blocks" not in rows[0]


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_another_tenant_cannot_read_the_graph(client, auth_headers) -> None:
    """A graph owned by someone else reads as absent, not as forbidden."""
    created = await client.post(f"{API}/graphs", json={"name": "private", **_sound_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]

    unique = uuid.uuid4().hex[:8]
    email = f"eac-other-{unique}@blocks.io"
    password = f"EacOther{unique}9"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Other Tenant"},
    )
    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    other = {"Authorization": f"Bearer {login.json().get('access_token', '')}"}

    assert (await client.get(f"{API}/graphs/{graph_id}", headers=other)).status_code == 404
    assert (await client.delete(f"{API}/graphs/{graph_id}", headers=other)).status_code == 404


@pytest.mark.asyncio
async def test_validate_endpoint_checks_an_unsaved_canvas(client, auth_headers) -> None:
    """The editor checks the canvas while the estimator is still wiring it."""
    resp = await client.post(f"{API}/graphs:validate", json=_cyclic_graph(), headers=auth_headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["status"] == "errors"
    assert [f["rule_id"] for f in report["findings"]] == ["eac_graph.no_cycles"]

    clean = await client.post(f"{API}/graphs:validate", json=_sound_graph(), headers=auth_headers)
    assert clean.json()["status"] == "passed"
    assert clean.json()["findings"] == []


@pytest.mark.asyncio
async def test_validate_endpoint_refreshes_a_saved_graph_status(client, auth_headers) -> None:
    created = await client.post(f"{API}/graphs", json={"name": "recheck", **_cyclic_graph()}, headers=auth_headers)
    graph_id = created.json()["id"]
    assert created.json()["validation_status"] == "errors"

    fixed = await client.put(
        f"{API}/graphs/{graph_id}",
        json={"blocks": _sound_graph()["blocks"], "connections": _sound_graph()["connections"]},
        headers=auth_headers,
    )
    assert fixed.json()["validation_status"] == "passed"

    rechecked = await client.post(f"{API}/graphs/{graph_id}:validate", headers=auth_headers)
    assert rechecked.status_code == 200
    assert rechecked.json()["status"] == "passed"


@pytest.mark.asyncio
async def test_unknown_slot_data_type_is_refused_at_the_schema(client, auth_headers) -> None:
    """The nine slot types are a closed set; an unknown one is a 422, not a save."""
    body = _sound_graph()
    body["blocks"][0]["slots"][0]["dataType"] = "quaternion"
    resp = await client.post(f"{API}/graphs", json={"name": "bad slot", **body}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_reports_how_many_matched(client, auth_headers) -> None:
    """The body is one page; the header says how many the filter found."""
    name = f"counted-{uuid.uuid4().hex[:6]}"
    for index in range(3):
        await client.post(
            f"{API}/graphs",
            json={"name": f"{name}-{index}", **_sound_graph()},
            headers=auth_headers,
        )

    page = await client.get(f"{API}/graphs", params={"search": name, "limit": 2}, headers=auth_headers)
    assert page.status_code == 200
    assert len(page.json()) == 2
    assert page.headers["X-Total-Count"] == "3"


# ── 8. The score is the engine's own, never a substitute ─────────────────────


def _multi_fault_graph() -> dict[str, Any]:
    """Two dangling wires and a cycle, for comparing against a single fault."""
    return {
        "blocks": [_block("b1"), _block("b2")],
        "connections": [
            _conn("c1", "b1", "ghost1"),
            _conn("c2", "b2", "ghost2"),
            _conn("c3", "b1", "b2"),
            _conn("c4", "b2", "b1"),
        ],
    }


@pytest.mark.asyncio
async def test_an_unchecked_canvas_reports_no_score(client, auth_headers) -> None:
    """A blank canvas must not read as a perfect methodology.

    Every rule stays silent when it has nothing to examine, so the engine
    reports SKIPPED and no score at all. The trap this pins down is the
    tempting substitution ``score=1.0 if nothing failed``: an empty graph has
    no findings for exactly the reason that it also has no quality signal, so
    that expression turns "never checked" into "100%".
    """
    created = await client.post(f"{API}/graphs", json={"name": "blank"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_status"] == "pending"
    assert body["validation"]["score"] is None

    fetched = await client.get(f"{API}/graphs/{body['id']}", headers=auth_headers)
    assert fetched.json()["validation"]["score"] is None


@pytest.mark.asyncio
async def test_the_score_discriminates_one_fault_from_several(client, auth_headers) -> None:
    """One bad wire and a wreck must not land on the same number.

    Read back rather than taken from the save response, because the read path
    is where a score is easiest to reinvent from the findings list. Any such
    expression collapses these two graphs onto one value: both have findings,
    so both would score the same.
    """
    one = await client.post(f"{API}/graphs", json={"name": "one fault", **_dangling_graph()}, headers=auth_headers)
    many = await client.post(
        f"{API}/graphs", json={"name": "many faults", **_multi_fault_graph()}, headers=auth_headers
    )
    one_read = await client.get(f"{API}/graphs/{one.json()['id']}", headers=auth_headers)
    many_read = await client.get(f"{API}/graphs/{many.json()['id']}", headers=auth_headers)

    one_score = one_read.json()["validation"]["score"]
    many_score = many_read.json()["validation"]["score"]
    assert one_score is not None and many_score is not None
    # Strictly between the extremes: a single fault is neither perfect nor a
    # total loss, which is the whole reason the engine caps rather than zeroes.
    assert 0.0 < many_score < one_score < 1.0


@pytest.mark.asyncio
async def test_the_stored_score_survives_a_reread(client, auth_headers) -> None:
    """The read path returns what was stored, not a number derived from findings."""
    created = await client.post(
        f"{API}/graphs",
        json={"name": "scored", **_dangling_graph()},
        headers=auth_headers,
    )
    saved_score = created.json()["validation"]["score"]
    assert saved_score is not None
    assert 0.0 < saved_score < 1.0

    fetched = await client.get(f"{API}/graphs/{created.json()['id']}", headers=auth_headers)
    assert fetched.json()["validation"]["score"] == saved_score

    clean = await client.put(
        f"{API}/graphs/{created.json()['id']}",
        json=_sound_graph(),
        headers=auth_headers,
    )
    assert clean.json()["validation"]["score"] == 1.0


# ── 9. Validation is not a viewer-level operation ────────────────────────────


@pytest_asyncio.fixture
async def viewer_headers(client):
    """Register and activate a user, leaving it at the default viewer role."""
    unique = uuid.uuid4().hex[:8]
    email = f"eac-viewer-{unique}@blocks.io"
    password = f"EacViewer{unique}9"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "EAC Viewer"},
    )

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        result = await session.execute(
            update(User).where(User.email == email.lower()).values(role="viewer", is_active=True)
        )
        assert result.rowcount == 1, "viewer fixture did not find the user it just registered"
        await session.commit()

    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


@pytest.mark.asyncio
async def test_a_viewer_reads_graphs_but_cannot_run_the_rules(client, viewer_headers) -> None:
    """Both validate routes need ``eac.run``, matching rule dry-run and compile.

    A validate call feeds user-supplied content to the rule engine, and the
    saved-graph variant writes the outcome back onto the row. Neither belongs
    behind a read permission. The read assertion is what makes this
    discriminating: without it, three 403s would be equally consistent with an
    account that simply cannot reach the module at all.
    """
    listed = await client.get(f"{API}/graphs", headers=viewer_headers)
    assert listed.status_code == 200, listed.text

    unsaved = await client.post(f"{API}/graphs:validate", json=_sound_graph(), headers=viewer_headers)
    assert unsaved.status_code == 403, unsaved.text

    # A random id: the gate must refuse before the handler ever looks the graph
    # up, so this is 403 rather than the 404 a permitted caller would see.
    saved = await client.post(f"{API}/graphs/{uuid.uuid4()}:validate", headers=viewer_headers)
    assert saved.status_code == 403, saved.text
