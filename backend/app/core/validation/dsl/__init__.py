# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance DSL — author validation rules as YAML/JSON snippets.

Companion to :mod:`app.core.validation.engine` that lets non-programmer
users (compliance officers, QS leads, project owners) compose new
:class:`~app.core.validation.engine.ValidationRule` subclasses without
editing Python code.

The DSL is intentionally narrow:

* No loops other than the ``forEach`` / ``count`` / ``sum`` aggregators.
* No code execution, ``eval``/``exec``, attribute traversal, or imports.
* Field access is restricted to the dotted path syntax we parse
  ourselves — callers can never reach ``__class__`` / ``__globals__``.
* YAML is loaded via ``yaml.safe_load`` so no Python tags are honoured
  (cf. ``!!python/object``).

Layered modules::

    parser.py     — YAML/JSON → typed AST + structural lint
    evaluator.py  — AST → list[RuleResult] over a ValidationContext
    __init__.py   — public ``compile_rule`` / ``parse_definition`` API

Public API
----------

* :func:`parse_definition` — string or dict → :class:`RuleDefinition`.
  Raises :class:`DSLSyntaxError` on bad input. Pure / no side effects.
* :func:`validate_definition` — boolean syntax check (used by the
  ``/validate-syntax`` endpoint to give live feedback before saving).
* :func:`compile_rule` — :class:`RuleDefinition` → dynamic
  ``ValidationRule`` subclass instance ready to register with the
  engine's :class:`~app.core.validation.engine.RuleRegistry`.
* :class:`DSLError` hierarchy — typed errors carrying ``message_key``
  for i18n on the API surface.
"""

from __future__ import annotations

from app.core.validation.dsl.evaluator import (
    DSLEvaluationError,
    compile_rule,
)
from app.core.validation.dsl.parser import (
    DSLError,
    DSLSyntaxError,
    DSLTypeError,
    RuleDefinition,
    parse_definition,
    validate_definition,
)

__all__ = [
    "DSLError",
    "DSLEvaluationError",
    "DSLSyntaxError",
    "DSLTypeError",
    "RuleDefinition",
    "compile_rule",
    "parse_definition",
    "validate_definition",
]
