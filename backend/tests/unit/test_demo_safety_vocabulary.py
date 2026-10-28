# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo estate must speak the safety module's own vocabulary.

Same failure as the variations module, in two places at once. The seeder inserts
through the ORM, so nothing it writes ever passes the Pydantic layer that owns
the vocabulary, and the columns are plain ``String`` with no enum behind them.
What was seeded, measured 07.08:

* ``incident_type`` held ``first_aid`` and ``recordable``. ``IncidentCreate``
  accepts injury, near_miss, property_damage, environmental, fire. ``first_aid``
  is a *treatment* type and sat on rows that already carried
  ``treatment_type: first_aid``; ``recordable`` is the OSHA recordability
  concept, which has its own ``osha_recordable`` flag.
* ``severity`` held ``serious``, which is not on the module's minor / moderate /
  major / severe / critical scale.
* ``observation_type`` held ``unsafe_behavior``, ``housekeeping``,
  ``environmental`` and ``noise``. The module accepts four values and the type
  picker in the UI offers exactly those four, so a reader who opened one of
  those rows could not re-select the value the row already held.
* ``status`` on 14 of 17 observations was ``resolved``, which the module does not
  accept either. ``resolved`` is a real state in the punchlist state machine,
  which is presumably where it was borrowed from.

The second defect is not vocabulary but content: every incident and every
observation was seeded terminal, so the Open Incidents tile read zero on every
demo project and the register showed a reader nothing to act on.

The hand-written blocks are local variables inside ``_seed_module_data`` and
cannot be imported, so they are read out of the source with ``ast``. That is
weaker than calling the code, and it is why the generated half below is checked
by constructing the real schema objects rather than by matching strings.
"""

from __future__ import annotations

import ast
import itertools
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import demo_projects
from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data
from app.modules.safety.schemas import IncidentCreate, ObservationCreate

_BASE = datetime(2026, 1, 15, tzinfo=UTC)


def _generate(demo_id: str) -> dict[str, list[dict]]:
    template = DEMO_TEMPLATES[demo_id]
    return _generate_module_data(
        template,
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=_BASE,
    )


# ── The generated half, checked against the schema itself ────────────────


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_generated_safety_incidents_pass_the_modules_own_schema(demo_id: str) -> None:
    rows = _generate(demo_id)["safety_incidents"]
    assert rows, f"{demo_id} generated no incidents, the check would be vacuous"
    for row in rows:
        # incident_number is assigned by the service, not accepted on create.
        payload = {k: v for k, v in row.items() if k != "incident_number"}
        IncidentCreate(project_id=uuid.uuid4(), **payload)


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_generated_safety_observations_pass_the_modules_own_schema(demo_id: str) -> None:
    rows = _generate(demo_id)["safety_observations"]
    assert rows, f"{demo_id} generated no observations, the check would be vacuous"
    for row in rows:
        payload = {k: v for k, v in row.items() if k != "observation_number"}
        ObservationCreate(project_id=uuid.uuid4(), **payload)


def test_the_schema_still_refuses_the_words_that_were_actually_seeded() -> None:
    """A green run above must mean the data is right, not that nothing is read."""
    base: dict[str, Any] = {
        "project_id": uuid.uuid4(),
        "incident_date": "2026-01-20",
        "description": "x",
        "incident_type": "near_miss",
    }
    for refused in ("first_aid", "recordable"):
        with pytest.raises(ValidationError):
            IncidentCreate(**{**base, "incident_type": refused})
    with pytest.raises(ValidationError):
        IncidentCreate(**{**base, "severity": "serious"})

    obs: dict[str, Any] = {
        "project_id": uuid.uuid4(),
        "description": "x",
        "observation_type": "unsafe_condition",
    }
    for refused in ("unsafe_behavior", "housekeeping", "environmental", "noise"):
        with pytest.raises(ValidationError):
            ObservationCreate(**{**obs, "observation_type": refused})
    with pytest.raises(ValidationError):
        ObservationCreate(**{**obs, "status": "resolved"})


# ── The content half ─────────────────────────────────────────────────────


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_a_generated_project_has_something_still_open(demo_id: str) -> None:
    """A register seeded entirely terminal shows a reader nothing to act on."""
    data = _generate(demo_id)
    incidents = data["safety_incidents"]
    assert [r for r in incidents if r["status"] != "closed"], (
        f"{demo_id} seeds {len(incidents)} incidents and closes every one, so the Open Incidents tile reads zero"
    )
    actions = [a for r in incidents for a in r.get("corrective_actions") or []]
    assert [a for a in actions if a["status"] != "completed"], (
        f"{demo_id} completes all {len(actions)} corrective actions"
    )
    obs = data["safety_observations"]
    assert [r for r in obs if r["status"] != "closed"], f"{demo_id} closes all {len(obs)} observations"


def test_no_two_projects_get_the_same_generated_incident_register() -> None:
    """Two demo projects rendered a safety screen identical down to the pixel.

    Measured in the case-capture run: two different projects compared 0 bits
    apart and 1.00 alike on text, because every project that falls through to
    the generator got the same four titles in the same order.

    The assertion is pairwise on purpose. Asking whether the registers are not
    *all* identical is a much weaker question than it looks: it passes on two
    distinct registers shared out among every project, which is exactly the
    state a sliding window over a seven-entry pool produced - 34 templates,
    7 registers, every project sharing with at least four others. Only a
    pairwise check can see the pair that was actually reported.
    """
    registers = {
        demo_id: tuple(r["title"] for r in _generate(demo_id)["safety_incidents"]) for demo_id in DEMO_TEMPLATES
    }
    collisions = [(a, b) for a, b in itertools.combinations(sorted(registers), 2) if registers[a] == registers[b]]
    assert not collisions, (
        f"{len(collisions)} pair(s) of demo projects render an identical incident register: {collisions[:5]}"
    )


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_one_register_does_not_repeat_an_incident(demo_id: str) -> None:
    """Spreading the pool must not hand one project the same incident twice.

    The picks step through the pool rather than sliding along it, so a step
    that shared a factor with the pool length would revisit an entry before
    the fourth pick. The pool length is prime to prevent that; this is the
    check that says so.
    """
    titles = [r["title"] for r in _generate(demo_id)["safety_incidents"]]
    assert len(set(titles)) == len(titles), f"{demo_id} lists the same incident more than once: {titles}"


def test_the_generated_register_is_stable_for_one_project() -> None:
    """The rotation is derived from demo_id, so re-seeding must not reshuffle."""
    demo_id = sorted(DEMO_TEMPLATES)[0]
    first = [r["title"] for r in _generate(demo_id)["safety_incidents"]]
    second = [r["title"] for r in _generate(demo_id)["safety_incidents"]]
    assert first == second


# ── The hand-written half, read out of the source ────────────────────────

_OK_INCIDENT_TYPE = {"injury", "near_miss", "property_damage", "environmental", "fire"}
_OK_SEVERITY = {"minor", "moderate", "major", "severe", "critical"}
_OK_INCIDENT_STATUS = {"reported", "investigating", "corrective_action", "closed"}
_OK_OBSERVATION_TYPE = {"positive", "unsafe_act", "unsafe_condition", "near_miss"}
_OK_OBSERVATION_STATUS = {"open", "in_progress", "closed"}


def _literal_records(marker: str) -> list[dict[str, Any]]:
    """Every dict literal in demo_projects.py carrying ``marker`` as a key.

    The hand-written safety blocks are local variables inside a function, so
    there is nothing to import. Only literal values are read; a key whose value
    is computed is skipped rather than guessed at.
    """
    source = Path(demo_projects.__file__).read_text(encoding="utf-8")
    out: list[dict[str, Any]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        record = {
            key.value: value.value
            for key, value in zip(node.keys, node.values, strict=False)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
        }
        if marker in record:
            out.append(record)
    return out


def test_hand_written_incidents_speak_the_modules_vocabulary() -> None:
    records = _literal_records("incident_number")
    assert len(records) >= 8, f"only found {len(records)} incident literals, the scan has drifted"
    for field, allowed in (
        ("incident_type", _OK_INCIDENT_TYPE),
        ("severity", _OK_SEVERITY),
        ("status", _OK_INCIDENT_STATUS),
    ):
        seen = {r[field] for r in records if field in r}
        assert not seen - allowed, (
            f"hand-written incidents use {field} values the module refuses: {sorted(seen - allowed)}"
        )


def test_hand_written_observations_speak_the_modules_vocabulary() -> None:
    records = _literal_records("observation_number")
    assert len(records) >= 17, f"only found {len(records)} observation literals, the scan has drifted"
    for field, allowed in (
        ("observation_type", _OK_OBSERVATION_TYPE),
        ("status", _OK_OBSERVATION_STATUS),
    ):
        seen = {r[field] for r in records if field in r}
        assert not seen - allowed, (
            f"hand-written observations use {field} values the module refuses: {sorted(seen - allowed)}"
        )
