"""Rules-as-Code YAML loader for BIM requirement packs.

This module is the entry point of the *rules-as-YAML* feature: it turns a
Git-reviewable YAML file (or a directory of them) into strictly-validated
``RulePack`` objects that the :mod:`rule_runtime` engine can execute.

Design goals
~~~~~~~~~~~~
* **Safe**: uses ``yaml.safe_load`` exclusively, refuses arbitrary Python
  tags, refuses long regex patterns (ReDoS-class inputs).
* **Strict**: every field validated through Pydantic v2 models; unknown
  fields are rejected so authors do not silently lose data through typos.
* **Helpful**: errors carry the file path and (when possible) the line
  number of the offending YAML node so authors can navigate from the CI
  failure straight to the file.
* **Pure**: no DB access, no network access, no I/O beyond reading the
  YAML file itself.

Why we built this
~~~~~~~~~~~~~~~~~
A common commercial moat in BIM rule-checking tools is the opacity of
their proprietary rule files.
OpenConstructionERP ships its rule packs as plain YAML in the repo so
they can be code-reviewed, diffed, branched, and shared the same way any
other source artifact is. That is a feature commercial tools cannot copy
without giving up their proprietary editor.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Constants ──────────────────────────────────────────────────────────────

SCHEMA_VERSION: str = "1.0"
"""Schema version this loader understands. Mismatch → hard error."""

MAX_REGEX_LENGTH: int = 256
"""Longest regex pattern accepted in a predicate. Anything beyond this is
treated as a denial-of-service hazard (ReDoS) and rejected at load time."""

VALID_OPERATORS: frozenset[str] = frozenset(
    {
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "contains",
        "regex",
        "exists",
        "between",
    }
)

VALID_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})

VALID_RULE_TYPES: frozenset[str] = frozenset({"property", "set_vs_set"})


# ── Errors ─────────────────────────────────────────────────────────────────


class RulePackParseError(Exception):
    """Raised when a YAML rule pack cannot be loaded or validated.

    Carries enough context (file path, line number when known, problem
    description) to be surfaced verbatim in a CI log or in the
    ``/preview-yaml`` HTTP response.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | Path | None = None,
        line: int | None = None,
    ) -> None:
        self.path = str(path) if path is not None else None
        self.line = line
        self.message = message
        location = ""
        if self.path:
            location = f" in {self.path}"
        if self.line is not None:
            location += f" (line {self.line})"
        super().__init__(f"{message}{location}")


# ── Pydantic schema ────────────────────────────────────────────────────────


class Predicate(BaseModel):
    """A single ``key OP value`` test, used in both selectors and assertions.

    Mirrors the operator vocabulary that :func:`rule_runtime.evaluate_predicate`
    knows how to execute. ``unit`` is metadata only (recorded so reports
    can render "1.5 m"); the runtime compares raw numeric values.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=255)
    op: str
    value: Any = None
    unit: str | None = Field(default=None, max_length=32)

    @field_validator("op")
    @classmethod
    def _check_op(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Unknown operator '{v}'. Valid: {', '.join(sorted(VALID_OPERATORS))}.")
        return v

    @model_validator(mode="after")
    def _validate_value_for_op(self) -> Predicate:
        op = self.op
        v = self.value
        if op == "exists":
            # `exists` ignores `value`; allow anything (typically true).
            return self
        if op == "between":
            if not (isinstance(v, list) and len(v) == 2):
                raise ValueError("Operator 'between' requires value to be a 2-element list [min, max].")
            return self
        if op == "in":
            if not isinstance(v, list):
                raise ValueError("Operator 'in' requires value to be a list.")
            return self
        if op == "regex":
            if not isinstance(v, str):
                raise ValueError("Operator 'regex' requires value to be a string pattern.")
            if len(v) > MAX_REGEX_LENGTH:
                raise ValueError(
                    f"Regex pattern is {len(v)} characters long, which exceeds the "
                    f"{MAX_REGEX_LENGTH}-char ReDoS safety limit."
                )
            # Reject patterns the regex engine itself cannot compile.
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
            return self
        # eq/neq/gt/gte/lt/lte/contains: value just needs to be present.
        if v is None:
            raise ValueError(f"Operator '{op}' requires a non-null value.")
        return self


class Selector(BaseModel):
    """Predicate set that decides whether a rule applies to a given element.

    All predicates are AND-combined. ``ifc_class`` (when set) is a
    shortcut for ``properties: [{key: ifc_class, op: eq, value: ...}]``
    but stored separately so authors do not have to repeat that line in
    every rule.
    """

    model_config = ConfigDict(extra="forbid")

    ifc_class: str | None = Field(default=None, max_length=128)
    classification: dict[str, str] | None = None
    properties: list[Predicate] = Field(default_factory=list)


class PropertyAssertion(BaseModel):
    """Single-element property check (the common case)."""

    model_config = ConfigDict(extra="forbid")

    property: Predicate


class SetVsSetAssertion(BaseModel):
    """Cross-set check (e.g. "every pipe ≥ 100 mm from every beam")."""

    model_config = ConfigDict(extra="forbid")

    set_vs_set: SetVsSetSpec


class SetVsSetSpec(BaseModel):
    """Specification of the *other* set in a cross-set assertion."""

    model_config = ConfigDict(extra="forbid")

    other_selector: Selector
    metric: Literal["clearance", "distance"] = "clearance"
    property: Predicate


# Resolve the forward reference now that SetVsSetSpec is defined.
SetVsSetAssertion.model_rebuild()


class Rule(BaseModel):
    """One rule inside a pack."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.\-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    severity: str = "warning"
    rationale: str = ""
    rule_type: str = "property"
    selector: Selector = Field(default_factory=Selector)
    # Either ``assertion.property`` or ``assertion.set_vs_set`` is set.
    assertion: PropertyAssertion | SetVsSetAssertion
    failure_message: str = ""

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, v: str) -> str:
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Unknown severity '{v}'. Valid: {', '.join(sorted(VALID_SEVERITIES))}.")
        return v

    @field_validator("rule_type")
    @classmethod
    def _check_rule_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(f"Unknown rule_type '{v}'. Valid: {', '.join(sorted(VALID_RULE_TYPES))}.")
        return v

    @model_validator(mode="after")
    def _rule_type_matches_assertion(self) -> Rule:
        is_set_vs_set = isinstance(self.assertion, SetVsSetAssertion)
        if self.rule_type == "set_vs_set" and not is_set_vs_set:
            raise ValueError("rule_type='set_vs_set' requires assertion.set_vs_set to be set.")
        if self.rule_type == "property" and is_set_vs_set:
            raise ValueError("assertion.set_vs_set is only valid when rule_type='set_vs_set'.")
        return self


class PackAppliesTo(BaseModel):
    """Optional scoping metadata (purely informational at load time)."""

    model_config = ConfigDict(extra="forbid")

    classifications: list[str] = Field(default_factory=list)
    project_regions: list[str] = Field(default_factory=list)


class PackMeta(BaseModel):
    """The ``pack:`` header block."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.\-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    source: str = "openconstructionerp"
    version: str = "1.0.0"
    applies_to: PackAppliesTo = Field(default_factory=PackAppliesTo)


class RulePack(BaseModel):
    """The top-level YAML document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    pack: PackMeta
    rules: list[Rule] = Field(default_factory=list, min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version '{v}'. This loader understands '{SCHEMA_VERSION}'.")
        return v

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> RulePack:
        seen: set[str] = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"Duplicate rule id '{r.id}' within pack.")
            seen.add(r.id)
        return self


# ── Safe loader (rejects arbitrary Python tags) ────────────────────────────


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader subclass we can extend without polluting global yaml state."""


def _forbid_python_tags(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> Any:  # noqa: ARG001
    raise yaml.constructor.ConstructorError(
        None,
        None,
        f"Refusing to construct object from tag '!!python/{tag_suffix}'; "
        "rule packs must contain only data, never code.",
        node.start_mark,
    )


# Even ``SafeLoader`` does not know any ``!!python/*`` tag, but a malicious
# author could explicitly register one or use ``!!tag:yaml.org,2002:python/*``.
# We catch all such variants up front.
_StrictSafeLoader.add_multi_constructor("tag:yaml.org,2002:python/", _forbid_python_tags)
_StrictSafeLoader.add_multi_constructor("!python/", _forbid_python_tags)


# ── Public API ─────────────────────────────────────────────────────────────


def load_rule_pack(source: str | Path, *, text: str | None = None) -> RulePack:
    """Parse and validate one YAML rule pack.

    Args:
        source: Path used to read the YAML *and* in error messages. When
            ``text`` is provided the file is not read; ``source`` is then
            purely a display label.
        text: Optional already-loaded YAML text. Useful for the
            ``preview-yaml`` endpoint which receives the text in the
            request body, not from disk.

    Returns:
        A fully validated :class:`RulePack`.

    Raises:
        RulePackParseError: with a useful file/line location on any
            failure (YAML syntax, schema mismatch, ReDoS regex, duplicate
            rule id, ...).
    """
    path = Path(source) if not isinstance(source, Path) else source

    if text is None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RulePackParseError(f"Cannot read rule pack file: {exc}", path=path) from exc

    try:
        raw = yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506 - strict subclass
    except yaml.YAMLError as exc:
        line = None
        if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
            # PyYAML marks are 0-indexed; humans count from 1.
            line = exc.problem_mark.line + 1
        raise RulePackParseError(f"YAML syntax error: {exc}", path=path, line=line) from exc

    if not isinstance(raw, dict):
        raise RulePackParseError(
            "YAML root must be a mapping with keys 'schema_version', 'pack', 'rules'.",
            path=path,
        )

    try:
        return RulePack.model_validate(raw)
    except Exception as exc:  # ValidationError or our raised ValueError
        # We deliberately do not import pydantic's ValidationError as the
        # only catchable type - Pydantic may also raise built-in ValueError
        # via field_validators. Both serialize cleanly via str().
        raise RulePackParseError(str(exc), path=path) from exc


def load_all_packs(root: str | Path) -> list[RulePack]:
    """Load every ``*.yaml`` / ``*.yml`` file under ``root`` (non-recursive).

    Files that fail to parse are *not* silently skipped: the first failure
    is raised so that broken packs cannot be deployed without notice.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise RulePackParseError(f"Rule-pack root '{root_path}' does not exist or is not a directory.")
    packs: list[RulePack] = []
    for entry in sorted(root_path.iterdir()):
        if entry.suffix.lower() not in {".yaml", ".yml"}:
            continue
        if entry.name.startswith("."):
            continue
        packs.append(load_rule_pack(entry))
    return packs


__all__ = [
    "MAX_REGEX_LENGTH",
    "SCHEMA_VERSION",
    "VALID_OPERATORS",
    "VALID_RULE_TYPES",
    "VALID_SEVERITIES",
    "PackAppliesTo",
    "PackMeta",
    "Predicate",
    "PropertyAssertion",
    "Rule",
    "RulePack",
    "RulePackParseError",
    "Selector",
    "SetVsSetAssertion",
    "SetVsSetSpec",
    "load_all_packs",
    "load_rule_pack",
]
