# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The trainer API contract is the same on both sides of the wire.

Wave 0 of the Academy trainer freezes one contract that two independent teams
build against: the Pydantic schemas in ``app/modules/trainer/schemas.py`` and
their TypeScript mirror in ``frontend/src/features/trainer/types.ts``. Nothing
at runtime connects the two, so drift between them would only show up as a
broken page. This file is what connects them:

* every fixture response validates against its schema and is exactly what the
  generator builds today, in both its JSON and its TypeScript form;
* every schema model has an interface of the same name with the same fields,
  the same nullability and the matching TypeScript type;
* every ``Literal`` has a ``const`` array with exactly its values;
* the lock list in ``locks.py`` equals the one in ``lockRegistry.ts``;
* the fixture responses agree with the fixture course they claim to describe.

The TypeScript files are parsed as text. They are written one property per line
for exactly this reason, and each parser below has a test that it found what it
expected to find, so a parser that silently matches nothing cannot pass.
"""

from __future__ import annotations

import importlib.util
import json
import re
import types
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, EmailStr

from app.modules.trainer import locks, schemas

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures" / "trainer"
TRAINER_SRC = REPO_ROOT / "frontend" / "src" / "features" / "trainer"
TYPES_TS = TRAINER_SRC / "types.ts"
LOCK_REGISTRY_TS = TRAINER_SRC / "lockRegistry.ts"

#: Python ``Literal`` alias -> the TypeScript ``const`` array that mirrors it.
LITERAL_MIRRORS: dict[str, str] = {
    "TaskStatus": "TASK_STATUSES",
    "LockState": "LOCK_STATES",
    "LockKind": "LOCK_KINDS",
    "RingId": "RING_IDS",
    "WeekDayState": "WEEK_DAY_STATES",
    "OutsideCourse": "OUTSIDE_COURSE_MODES",
    "ValueKind": "VALUE_KINDS",
    "CheckKind": "CHECK_KINDS",
    "AnswerKind": "ANSWER_KINDS",
    "ItemVerdict": "ITEM_VERDICTS",
    "ItemSource": "ITEM_SOURCES",
    "AttemptVerdict": "ATTEMPT_VERDICTS",
    "DiagnosisKind": "DIAGNOSIS_KINDS",
    "ReadbackState": "READBACK_STATES",
    "EnrolmentStatus": "ENROLMENT_STATUSES",
    "EnrolmentSource": "ENROLMENT_SOURCES",
}


def _load_generator():
    """Import the fixture generator by path; ``tests/fixtures/trainer`` is not a package."""
    path = FIXTURES_DIR / "generate_api_fixtures.py"
    spec = importlib.util.spec_from_file_location("trainer_fixture_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


# ── Python side: what the schemas declare ────────────────────────────────────


def _literal_aliases() -> dict[str, tuple[str, ...]]:
    """Every module-level ``Literal`` alias in schemas.py, plus ``LockKind``."""
    found = {
        name: get_args(value)
        for name, value in vars(schemas).items()
        if not name.startswith("_") and get_origin(value) is Literal
    }
    found["LockKind"] = get_args(locks.LockKind)
    return found


def _schema_models() -> dict[str, type[BaseModel]]:
    return {
        name: value
        for name, value in vars(schemas).items()
        if isinstance(value, type) and issubclass(value, schemas._Schema) and value is not schemas._Schema
    }


_ALIASES_BY_ARGS: dict[tuple[str, ...], set[str]] = {}
for _name, _args in _literal_aliases().items():
    _ALIASES_BY_ARGS.setdefault(_args, set()).add(_name)


def _expected_ts_types(annotation: object) -> set[str]:
    """The TypeScript spellings a field with this annotation may use.

    A set, because two aliases can share the same values (``RingId`` and
    ``CheckKind``); either name is a faithful mirror then.
    """
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is type(None):
        return {"null"}
    if origin is Annotated:
        return _expected_ts_types(args[0])
    if origin in (Union, types.UnionType):
        if {a for a in args} == {schemas.NumbersCheckView, schemas.ChoiceCheckView}:
            return {"CheckView"}
        options = [_expected_ts_types(a) for a in args]
        if len(options) == 2 and {"null"} in options:
            inner = next(o for o in options if o != {"null"})
            return {f"{t} | null" for t in inner}
        msg = f"no TypeScript rule for union {annotation!r}"
        raise AssertionError(msg)
    if origin is Literal:
        names = _ALIASES_BY_ARGS.get(args)
        if names:
            return set(names)
        return {" | ".join(f"'{a}'" for a in args)}
    if origin is list:
        return {f"{t}[]" if " " not in t else f"({t})[]" for t in _expected_ts_types(args[0])}
    if annotation in (str, uuid.UUID, datetime, date) or annotation is EmailStr:
        return {"string"}
    if annotation is int:
        return {"number"}
    if annotation is bool:
        return {"boolean"}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation.__name__}
    msg = f"no TypeScript rule for {annotation!r}"
    raise AssertionError(msg)


# ── TypeScript side: what types.ts and lockRegistry.ts declare ──────────────

_INTERFACE_RE = re.compile(r"^export interface (\w+) \{\n(.*?)^\}", re.M | re.S)
_PROP_RE = re.compile(r"^\s+(\w+)(\??): (.+);$")
_CONST_RE = re.compile(r"^export const (\w+) = \[(.*?)\] as const;$", re.M)
_TYPE_FROM_CONST_RE = re.compile(r"^export type (\w+) = \(typeof (\w+)\)\[number\];$", re.M)


def _ts_interfaces(text: str) -> dict[str, dict[str, str]]:
    """``{interface: {prop: type}}``. An optional (``?``) prop is reported as an error."""
    out: dict[str, dict[str, str]] = {}
    for name, body in _INTERFACE_RE.findall(text):
        props: dict[str, str] = {}
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            match = _PROP_RE.match(line)
            assert match, f"{name}: unparseable line {line!r}"
            prop, optional, ts_type = match.groups()
            assert not optional, f"{name}.{prop} is optional; the contract sends null, never undefined"
            props[prop] = ts_type
        out[name] = props
    return out


def _ts_consts(text: str) -> dict[str, tuple[str, ...]]:
    return {name: tuple(re.findall(r"'([^']*)'", body)) for name, body in _CONST_RE.findall(text)}


@pytest.fixture(scope="module")
def types_ts() -> str:
    return TYPES_TS.read_text(encoding="utf-8")


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(GEN.FIXTURES))
def test_every_fixture_response_validates_against_its_schema(name: str) -> None:
    """The JSON on disk parses into the schema and dumps back to the same data."""
    text = (FIXTURES_DIR / "api" / f"{name}.json").read_text(encoding="utf-8")
    model = GEN.FIXTURE_SCHEMAS[name].model_validate_json(text)
    assert model.model_dump(mode="json") == json.loads(text)


def test_the_fixture_files_are_what_the_generator_builds_today() -> None:
    """A schema edit without a regenerated fixture fails here, on both sides."""
    stale = []
    for path, expected in GEN.expected_files().items():
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual != expected:
            stale.append(str(path.relative_to(REPO_ROOT)))
    assert not stale, (
        "fixture files differ from the generator output; run "
        "`python tests/fixtures/trainer/generate_api_fixtures.py` from backend/:\n  " + "\n  ".join(stale)
    )


def test_the_generator_covers_every_response_named_in_the_brief() -> None:
    assert set(GEN.FIXTURES) == {"me", "task", "attempt_pass", "attempt_fail", "readback"}


# ── Interfaces ───────────────────────────────────────────────────────────────


def test_the_interface_parser_reads_types_ts(types_ts: str) -> None:
    """A parser that matched nothing would make every check below vacuous."""
    interfaces = _ts_interfaces(types_ts)
    assert len(interfaces) >= 30
    assert interfaces["TrainerMe"]["week"] == "WeekInfo | null"


def test_every_schema_model_has_an_interface_of_the_same_name(types_ts: str) -> None:
    interfaces = set(_ts_interfaces(types_ts))
    models = set(_schema_models())
    assert models - interfaces == set(), "schema models without a TypeScript interface"
    assert interfaces - models == set(), "TypeScript interfaces without a schema model"


@pytest.mark.parametrize("model_name", sorted(_schema_models()))
def test_every_interface_has_the_fields_and_types_of_its_model(types_ts: str, model_name: str) -> None:
    ts_props = _ts_interfaces(types_ts)[model_name]
    model = _schema_models()[model_name]
    assert set(ts_props) == set(model.model_fields), f"{model_name}: field names differ"
    for field_name, info in model.model_fields.items():
        expected = _expected_ts_types(info.annotation)
        assert ts_props[field_name] in expected, (
            f"{model_name}.{field_name}: TypeScript says {ts_props[field_name]!r}, the schema implies {expected}"
        )


# ── Literals ─────────────────────────────────────────────────────────────────


def test_every_literal_is_mirrored_and_every_mirror_is_a_literal(types_ts: str) -> None:
    assert set(_literal_aliases()) == set(LITERAL_MIRRORS), "a Literal alias is missing from LITERAL_MIRRORS"
    assert set(_ts_consts(types_ts)) == set(LITERAL_MIRRORS.values()), (
        "types.ts const arrays differ from the mirror map"
    )


@pytest.mark.parametrize(("alias", "const"), sorted(LITERAL_MIRRORS.items()))
def test_every_literal_has_the_same_values_in_typescript(types_ts: str, alias: str, const: str) -> None:
    assert _ts_consts(types_ts)[const] == _literal_aliases()[alias]
    derived = dict(_TYPE_FROM_CONST_RE.findall(types_ts))
    assert derived.get(alias) == const, f"types.ts should declare `export type {alias} = (typeof {const})[number];`"


# ── Locks ────────────────────────────────────────────────────────────────────


def _ts_locks() -> tuple[list[tuple[str, str, str]], str]:
    text = LOCK_REGISTRY_TS.read_text(encoding="utf-8")
    entries = re.findall(r"lockId: '([^']+)',\s*kind: '([^']+)',\s*module: '([^']+)'", text)
    prefix = re.search(r"^export const BADGE_PREFIX = '([^']+)';$", text, re.M)
    return entries, prefix.group(1) if prefix else ""


def test_the_lock_registry_parser_reads_lock_registry_ts() -> None:
    entries, prefix = _ts_locks()
    assert len(entries) >= 5
    assert prefix


def test_the_lock_ids_in_locks_py_equal_those_in_lock_registry_ts() -> None:
    entries, prefix = _ts_locks()
    assert entries == [(spec.lock_id, spec.kind, spec.module) for spec in locks.LOCKS]
    assert prefix == locks.BADGE_PREFIX


def test_the_lock_list_is_the_one_the_interface_decisions_fixed() -> None:
    """Decision 5: exactly these five, plus ``badge:<course>``."""
    assert {
        "boq.markups_panel",
        "bid_management",
        "contracts.progress_claims",
        "contracts",
        "variations",
    } == locks.LOCK_IDS
    assert locks.is_known_lock_id("badge:any-course")
    for unknown in ("badge:", "finance", "tendering", "changeorders", "markups", ""):
        assert not locks.is_known_lock_id(unknown), unknown


# ── Fixture responses against the fixture course ─────────────────────────────


def test_the_me_fixture_describes_the_fixture_course() -> None:
    course = json.loads((FIXTURES_DIR / "course_fixture_v1.json").read_text(encoding="utf-8"))
    me = GEN.build_me()
    assert me.course.id == course["id"]
    assert [(t.id, t.n, t.opens, t.module) for t in me.tasks] == [
        (t["id"], t["n"], t["opens"], t["module"]) for t in course["tasks"]
    ]
    assert [u.lock_id for u in me.unlocks] == [t["opens"] for t in course["tasks"]]


def test_the_task_fixture_offers_only_the_course_task_checks() -> None:
    course = json.loads((FIXTURES_DIR / "course_fixture_v1.json").read_text(encoding="utf-8"))
    view = GEN.build_task()
    spec = next(t for t in course["tasks"] if t["id"] == view.id)
    assert [c.id for c in view.checks] == [c["id"] for c in spec["checks"]]
    numbers = next(c for c in spec["checks"] if c["kind"] == "numbers")
    view_numbers = next(c for c in view.checks if isinstance(c, schemas.NumbersCheckView))
    assert [f.key for f in view_numbers.fields] == numbers["expects"]
    assert view.hints_total == len(spec["hints"])
    assert view.hints == spec["hints"][: len(view.hints)]


def test_no_fixture_response_carries_a_graded_value() -> None:
    """The redaction rule, held on the fixtures every UI test is built from."""
    blob = json.dumps({name: m.model_dump(mode="json") for name, m in GEN.build_all().items()})
    for leak in ('"correct"', '"wrong_value"', '"expected"', '"answer_key"', '"delta"', '"tolerance"'):
        assert leak not in blob, leak


def test_the_redacted_models_cannot_carry_a_secret_field() -> None:
    """``extra="forbid"`` is what keeps a careless service from leaking a key."""
    with pytest.raises(ValueError, match="correct"):
        schemas.ChoiceOption.model_validate({"index": 0, "text": "x", "correct": True})
    with pytest.raises(ValueError, match="delta"):
        schemas.Diagnosis.model_validate({"id": "d", "kind": "error", "message": "m", "related": [], "delta": "-1"})


def test_a_check_over_zero_items_can_never_pass() -> None:
    data = GEN.build_attempt_pass().model_dump(mode="json")
    data.update(graded_items=0, passed_items=0, fields=[])
    with pytest.raises(ValueError, match="at least one graded item"):
        schemas.AttemptResult.model_validate(data)


def test_money_is_a_decimal_string_never_a_float() -> None:
    with pytest.raises(ValueError, match="decimal string"):
        schemas.RelatedValue.model_validate({"name": "x", "value": "1,520.70", "kind": "money"})
    with pytest.raises(ValueError):
        schemas.RelatedValue.model_validate({"name": "x", "value": 1520.7, "kind": "money"})
