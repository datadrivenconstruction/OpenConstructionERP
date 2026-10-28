# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``or "0"`` money fallback must stay unreachable.

Several response schemas serialize money through a private helper and then add
``or "0"`` at the call site::

    @field_serializer("grand_total", when_used="json")
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"

The helper returns ``None`` for ``None``, so that ``or`` converts exactly one
input class: an absent value becomes the string ``"0"``, which a client cannot
tell apart from a real zero. Measured on the shape above, an OPTIONAL field
serializes ``None`` and ``Decimal("0")`` both to ``{'amount': '0'}``.

Today that cannot happen, because every field these serializers guard is
annotated as a required ``Decimal``. Pydantic refuses ``None`` for a required
field, both directly and through ``from_attributes`` over an ORM row with a
NULL column, and the one construct that skips validation entirely,
``model_construct``, is used nowhere in ``app``.

So the fallback is not dead code, it is a landmine. It is unreachable because
of a property of the OTHER 120 declarations, not because of anything at the 51
fallbacks themselves. Making any one of those fields optional arms all of them
at once. This test is the tripwire: relax an annotation and it fails here,
with this docstring attached, rather than shipping zeros that look real.

This codifies existing practice rather than introducing a rule.
``property_dev/schemas.py`` already splits its money serializers on exactly
this distinction: ``_ser_money_required`` covers the required fields and ends
in ``or "0"``, while ``_ser_money_opt`` covers the optional ones, carries no
fallback, and returns ``str | None`` so an absent value serializes as null.
``computed_price`` sits correctly on the optional one.

If you are here because this test failed, you have two honest options. Keep the
field required, or drop the ``or "0"`` from its serializer so an absent value
serializes as ``null`` and stays distinguishable from a real zero. Do not
silence the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Schema modules whose money serializers use the fallback. Kept explicit rather
# than globbed: a new module joining this list is a decision, not an accident.
GUARDED_SOURCES = [
    "app/modules/property_dev/schemas.py",
    "app/modules/property_dev/portal_schemas.py",
    "app/modules/property_dev/pricing_engine.py",
    "app/modules/variations/schemas.py",
    # Deliberately NOT certified_payroll/schemas.py: it spells `or "0"` on a
    # ``field_validator`` over ``str`` fields that already default to "0", so it
    # normalises input rather than inventing an amount on the way out. Same
    # three characters, different effect, and only the effect matters here.
    "app/modules/field_time/schemas.py",
    "app/modules/methodology/schemas.py",
]

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _admits_none(annotation: str) -> bool:
    """Does this annotation let ``None`` reach the serializer?"""
    compact = annotation.replace(" ", "")
    return "None" in compact or "Optional[" in compact


def _guarded_fields(source: str) -> list[tuple[str, str, str, int]]:
    """Every field guarded by a ``field_serializer`` that adds ``or "0"``.

    Args:
        source: Python source of a schema module.

    Returns:
        ``(class_name, field_name, annotation, lineno)`` per guarded field.
        A field named by the decorator but not declared on the same class is
        skipped, since its annotation lives somewhere this walker cannot see.
    """
    tree = ast.parse(source)
    found: list[tuple[str, str, str, int]] = []

    for cls in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        declared: dict[str, str] = {}
        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                declared[stmt.target.id] = ast.get_source_segment(source, stmt.annotation) or ""

        for stmt in cls.body:
            if not isinstance(stmt, ast.FunctionDef):
                continue
            body = ast.get_source_segment(source, stmt) or ""
            if 'or "0"' not in body and "or '0'" not in body:
                continue
            for decorator in stmt.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = (
                    decorator.func.attr
                    if isinstance(decorator.func, ast.Attribute)
                    else getattr(decorator.func, "id", "")
                )
                if name != "field_serializer":
                    continue
                for arg in decorator.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value in declared:
                            found.append((cls.name, arg.value, declared[arg.value], stmt.lineno))

    return found


@pytest.mark.parametrize("relative_path", GUARDED_SOURCES)
def test_every_guarded_money_field_stays_required(relative_path: str) -> None:
    """No field behind an ``or "0"`` serializer may admit ``None``."""
    path = BACKEND_ROOT / relative_path
    if not path.exists():
        pytest.skip(f"{relative_path} is not present in this tree")

    guarded = _guarded_fields(path.read_text(encoding="utf-8"))

    # A file that yields nothing has either lost its fallbacks or defeated the
    # walker, and both make the pass meaningless. Fail loudly instead.
    assert guarded, (
        f'{relative_path} produced no guarded fields. Either the `or "0"` '
        f"serializers are gone, in which case delete this file from "
        f"GUARDED_SOURCES, or the walker no longer recognises them."
    )

    armed = [
        f"{relative_path}:{lineno} {cls}.{field}: {annotation}"
        for cls, field, annotation, lineno in guarded
        if _admits_none(annotation)
    ]
    assert not armed, (
        "These money fields became optional while their serializer still ends "
        'in `or "0"`, so an absent value now serializes as "0" and is '
        "indistinguishable from a real zero. See this module's docstring:\n  " + "\n  ".join(armed)
    )


def test_the_walker_can_actually_catch_an_armed_field() -> None:
    """Negative control: the check must fail on a field that IS optional.

    A matcher that has never been shown to fail proves nothing when it passes.
    The source below is the exact shape the real files would take if somebody
    relaxed one annotation, so this pins that the test above would notice.
    """
    armed_source = """
from decimal import Decimal
from pydantic import BaseModel, field_serializer


class Quote(BaseModel):
    grand_total: Decimal | None = None

    @field_serializer("grand_total", when_used="json")
    def _ser(self, v):
        return _serialize_money_string(v) or "0"
"""
    guarded = _guarded_fields(armed_source)
    assert [ann for _, _, ann, _ in guarded if _admits_none(ann)], (
        "The walker did not flag a field annotated `Decimal | None` behind an "
        '`or "0"` serializer, so it cannot protect the real modules either.'
    )

    # And the matching polarity: the same shape, required, must come back clean.
    safe_source = armed_source.replace("Decimal | None = None", "Decimal")
    guarded_safe = _guarded_fields(safe_source)
    assert guarded_safe, "the walker stopped seeing the serializer entirely"
    assert not [ann for _, _, ann, _ in guarded_safe if _admits_none(ann)], (
        "The walker flagged a required `Decimal`, so it convicts everything "
        "and its verdict on the real modules is worthless."
    )


def test_the_walker_catches_an_armed_field_in_a_real_module() -> None:
    """The same control, run against real source rather than a synthetic one.

    A matcher proved only against a hand-written snippet is proved against the
    syntax I imagined, not the syntax the tree uses: real models carry
    ``Field(...)`` defaults, multi-field decorators and ``@classmethod``
    between the decorator and the body. So this reads a shipped module, arms
    ONE annotation in memory, and pins that the walker notices.

    In memory is the whole point. Arming a real file on disk in a shared tree
    would leave a hole that documents itself as closed if anything interrupts
    the run.
    """
    path = BACKEND_ROOT / "app/modules/variations/schemas.py"
    if not path.exists():
        pytest.skip("variations/schemas.py is not present in this tree")
    source = path.read_text(encoding="utf-8")

    clean = [ann for _, _, ann, _ in _guarded_fields(source) if _admits_none(ann)]
    assert not clean, f"the real module is already armed, which this suite should have caught: {clean}"

    armed_source = source.replace(
        'final_value: Decimal = Decimal("0")',
        "final_value: Decimal | None = None",
        1,
    )
    assert armed_source != source, (
        "the anchor `final_value` is gone from variations/schemas.py, so this "
        "control silently stopped arming anything. Re-point it at a field that "
        'an `or "0"` serializer still guards.'
    )

    caught = [f"{cls}.{field}: {ann}" for cls, field, ann, _ in _guarded_fields(armed_source) if _admits_none(ann)]
    assert caught, (
        'Arming a real field behind a real `or "0"` serializer did not trip '
        "the walker, so its verdict on the shipped modules means nothing."
    )
