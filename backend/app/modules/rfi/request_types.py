# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request types as data: the pure half of the technical request register.

The RFI module keeps one register for every formal question or deviation request
the parties of a project send each other. What kind of request a row is - a
Request for Information, a Technical Query, a Vendor Query, a Concession Request -
is a row in the project's type catalogue, not a branch in the code. A type
carries:

* ``code`` - the stable key a request row stores (``TQ``, ``SQ``),
* ``name_i18n`` - its name per language, so the catalogue speaks the reader's language,
* ``number_prefix`` and ``number_digits`` - numbering per type (``TQ-0001``),
* ``default_response_days`` - the response SLA in business days,
* ``required_fields`` - what must be filled before the request is issued,
* ``default_route_id`` - the approval route that signs its answer off, if any.

Catalogues are built from shipped presets (``presets/*.json``) and edited per
project. Nothing in here touches the database: this module loads and checks the
presets and holds the rules every source of types is held to, so the service,
the validation rules and the tests ask the same functions.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

__all__ = [
    "CODE_PATTERN",
    "DEFAULT_RESPONSE_DAYS",
    "DEFAULT_TYPE_CODE",
    "MAX_DIGITS",
    "MIN_DIGITS",
    "PREFIX_PATTERN",
    "REQUIRED_FIELD_CHOICES",
    "CatalogueProblem",
    "Preset",
    "RequestTypeSpec",
    "builtin_default_type",
    "catalogue_problems",
    "format_request_number",
    "get_preset",
    "list_presets",
    "localized_text",
    "missing_required_fields",
    "number_regex",
]

DEFAULT_TYPE_CODE = "RFI"
"""The type every request has unless it names another, and every pre-existing row was."""

DEFAULT_RESPONSE_DAYS = 14
"""Business days to respond when a type names no SLA of its own (the RFI default since R1)."""

CODE_PATTERN = r"^[A-Z][A-Z0-9_]{0,31}$"
PREFIX_PATTERN = r"^[A-Z][A-Z0-9]{0,9}$"
MIN_DIGITS = 3
MAX_DIGITS = 6

# Request columns a type may demand before the request is issued. Each one is a
# real column of ``oe_rfi_rfi`` that the create and edit form offers, so a type
# never asks for something the reader has no field to type into. ``date_required``
# and ``change_order_id`` are columns too, but the form has no input for the
# first and the second is set by raising a variation, so neither is offered.
REQUIRED_FIELD_CHOICES: tuple[str, ...] = (
    "assigned_to",
    "response_due_date",
    "discipline",
    "priority",
    "linked_drawing_ids",
    "cost_impact_value",
    "schedule_impact_days",
)

_PRESET_DIR = Path(__file__).resolve().parent / "presets"
_CODE_RE = re.compile(CODE_PATTERN)
_PREFIX_RE = re.compile(PREFIX_PATTERN)


@dataclass(frozen=True)
class RequestTypeSpec:
    """One request type, wherever it came from (preset, project catalogue, built-in)."""

    code: str
    number_prefix: str
    number_digits: int = 4
    name_i18n: Mapping[str, str] = field(default_factory=dict)
    description_i18n: Mapping[str, str] = field(default_factory=dict)
    default_response_days: int | None = None
    required_fields: tuple[str, ...] = ()
    default_route_id: uuid.UUID | None = None
    is_active: bool = True
    sort_order: int = 0
    preset_code: str | None = None
    id: uuid.UUID | None = None

    @property
    def is_builtin(self) -> bool:
        """True for the fallback type a project without a catalogue row still has."""
        return self.id is None

    @property
    def response_days(self) -> int:
        """The SLA to apply, falling back to the platform default."""
        return self.default_response_days or DEFAULT_RESPONSE_DAYS


@dataclass(frozen=True)
class Preset:
    """A shipped set of request types a project can load in one step."""

    code: str
    name_i18n: Mapping[str, str]
    description_i18n: Mapping[str, str]
    types: tuple[RequestTypeSpec, ...]


@dataclass(frozen=True)
class CatalogueProblem:
    """One thing wrong with a set of types, named so a rule and an HTTP error can both say it."""

    code: str  # machine key: duplicate_code | duplicate_prefix | invalid_code | ...
    type_code: str
    detail: str


def format_request_number(prefix: str, sequence: int, digits: int) -> str:
    """``("TQ", 7, 4)`` -> ``"TQ-0007"``. A sequence wider than ``digits`` is kept whole."""
    return f"{prefix}-{sequence:0{digits}d}"


def number_regex(prefix: str) -> str:
    """The pattern a canonical number of this prefix matches, for the MAX(...) scan.

    The prefix is validated against :data:`PREFIX_PATTERN` (letters and digits
    only) before it reaches here, so it needs no escaping inside the pattern.
    """
    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"invalid number prefix: {prefix!r}")
    return f"^{prefix}-[0-9]+$"


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def missing_required_fields(spec: RequestTypeSpec, values: Mapping[str, Any]) -> list[str]:
    """The fields ``spec`` requires that ``values`` leaves empty, in the type's own order.

    ``0`` and ``False`` count as filled: a schedule impact of zero days is an
    answer, not a gap. Unknown names in ``required_fields`` are reported by
    :func:`catalogue_problems`, never silently treated as satisfied here.
    """
    return [name for name in spec.required_fields if _is_empty(values.get(name))]


def localized_text(texts: Mapping[str, str] | None, locale: str | None, fallback: str) -> str:
    """Pick the text for ``locale``: exact tag, then its language, then English, then ``fallback``."""
    if not texts:
        return fallback
    if locale:
        tag = locale.replace("_", "-")
        for candidate in (tag, tag.split("-")[0]):
            value = texts.get(candidate)
            if value:
                return value
    return texts.get("en") or fallback


def catalogue_problems(types: Iterable[RequestTypeSpec]) -> list[CatalogueProblem]:
    """Everything that makes a set of types unusable as one project's catalogue.

    Codes and prefixes must be unique (a prefix shared by two types would hand
    both the same number sequence), each code and prefix must have the shape the
    numbering and the URL use, digits must lie in range, and every required
    field must be one the request form offers.
    """
    problems: list[CatalogueProblem] = []
    seen_codes: set[str] = set()
    seen_prefixes: dict[str, str] = {}
    for spec in types:
        if not _CODE_RE.match(spec.code):
            problems.append(
                CatalogueProblem("invalid_code", spec.code, f"code {spec.code!r} must match {CODE_PATTERN}")
            )
        if spec.code in seen_codes:
            problems.append(CatalogueProblem("duplicate_code", spec.code, f"code {spec.code!r} is used twice"))
        seen_codes.add(spec.code)
        if not _PREFIX_RE.match(spec.number_prefix):
            problems.append(
                CatalogueProblem(
                    "invalid_prefix", spec.code, f"prefix {spec.number_prefix!r} must match {PREFIX_PATTERN}"
                )
            )
        elif spec.number_prefix in seen_prefixes:
            problems.append(
                CatalogueProblem(
                    "duplicate_prefix",
                    spec.code,
                    f"prefix {spec.number_prefix!r} is already used by {seen_prefixes[spec.number_prefix]!r}",
                )
            )
        else:
            seen_prefixes[spec.number_prefix] = spec.code
        if not MIN_DIGITS <= spec.number_digits <= MAX_DIGITS:
            problems.append(
                CatalogueProblem(
                    "invalid_digits", spec.code, f"number digits must lie between {MIN_DIGITS} and {MAX_DIGITS}"
                )
            )
        unknown = [f for f in spec.required_fields if f not in REQUIRED_FIELD_CHOICES]
        if unknown:
            problems.append(
                CatalogueProblem("unknown_required_field", spec.code, "unknown required fields: " + ", ".join(unknown))
            )
        if spec.default_response_days is not None and spec.default_response_days < 1:
            problems.append(CatalogueProblem("invalid_sla", spec.code, "default response days must be at least 1"))
        if not spec.name_i18n.get("en"):
            problems.append(CatalogueProblem("missing_english_name", spec.code, "an English name is required"))
    return problems


def _spec_from_json(raw: Mapping[str, Any], *, preset_code: str, order: int) -> RequestTypeSpec:
    return RequestTypeSpec(
        code=str(raw["code"]),
        number_prefix=str(raw.get("number_prefix") or raw["code"]),
        number_digits=int(raw.get("number_digits", 4)),
        name_i18n=dict(raw.get("name_i18n") or {}),
        description_i18n=dict(raw.get("description_i18n") or {}),
        default_response_days=raw.get("default_response_days"),
        required_fields=tuple(raw.get("required_fields") or ()),
        sort_order=int(raw.get("sort_order", order * 10)),
        preset_code=preset_code,
    )


@cache
def _load_presets() -> tuple[Preset, ...]:
    presets: list[Preset] = []
    for path in sorted(_PRESET_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        code = str(raw["code"])
        types = tuple(_spec_from_json(t, preset_code=code, order=i) for i, t in enumerate(raw["types"]))
        problems = catalogue_problems(types)
        if problems:
            # A shipped preset that breaks the catalogue rules is a packaging
            # bug; refusing to load it is louder than handing a project a
            # catalogue whose numbering collides.
            raise ValueError(f"preset {code!r} is invalid: " + "; ".join(p.detail for p in problems))
        presets.append(
            Preset(
                code=code,
                name_i18n=dict(raw.get("name_i18n") or {}),
                description_i18n=dict(raw.get("description_i18n") or {}),
                types=types,
            )
        )
    return tuple(sorted(presets, key=lambda p: (_preset_order(p.code), p.code)))


def _preset_order(code: str) -> int:
    # General construction first: it is the preset every project can use.
    return 0 if code == "general_construction" else 1


def list_presets() -> list[Preset]:
    """Every shipped preset, general construction first."""
    return list(_load_presets())


def get_preset(code: str) -> Preset:
    """The shipped preset named ``code``; :class:`KeyError` when there is none."""
    for preset in _load_presets():
        if preset.code == code:
            return preset
    raise KeyError(code)


@cache
def builtin_default_type() -> RequestTypeSpec:
    """The RFI type a project has before anyone loads a catalogue.

    Taken from the general construction preset rather than written out again,
    so the name a project sees before and after loading the preset is the same
    data. It has no id: it is not a row, and it numbers ``RFI-001`` exactly as
    the register did before types existed.
    """
    for spec in get_preset("general_construction").types:
        if spec.code == DEFAULT_TYPE_CODE:
            return RequestTypeSpec(
                code=spec.code,
                number_prefix=spec.number_prefix,
                number_digits=spec.number_digits,
                name_i18n=spec.name_i18n,
                description_i18n=spec.description_i18n,
                default_response_days=spec.default_response_days,
                required_fields=spec.required_fields,
                sort_order=spec.sort_order,
                preset_code=None,
            )
    raise LookupError("the general construction preset has no RFI type")
