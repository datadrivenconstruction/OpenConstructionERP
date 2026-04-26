# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic mirror of the ``EacRuleDefinition`` JSON Schema.

Field names, types, and enums match :file:`schema/EacRuleDefinition.schema.json`
exactly. Discriminated unions (``Field(discriminator=...)``) reproduce the
JSON Schema's ``oneOf`` branches on ``kind`` / ``operator``.

Used by:

* The validator (EAC-1.3) to parse a ``definition_json`` body into a typed
  Python object.
* The auto-generated TypeScript layer (`packages/oe-schema/eac.ts`).
* CRUD endpoints in :mod:`app.modules.eac.schemas_api` to validate inbound
  payloads before they touch the database.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# ── Selector leaves ──────────────────────────────────────────────────────


class _SelectorBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategorySelector(_SelectorBase):
    kind: Literal["category"]
    values: list[str] = Field(min_length=1)


class IfcClassSelector(_SelectorBase):
    kind: Literal["ifc_class"]
    values: list[str] = Field(min_length=1)


class FamilySelector(_SelectorBase):
    kind: Literal["family"]
    values: list[str] = Field(min_length=1)


class TypeSelector(_SelectorBase):
    kind: Literal["type"]
    values: list[str] = Field(min_length=1)


class LevelSelector(_SelectorBase):
    kind: Literal["level"]
    values: list[str] = Field(min_length=1)


class DisciplineSelector(_SelectorBase):
    kind: Literal["discipline"]
    values: list[str] = Field(min_length=1)


class ClassificationCodeSelector(_SelectorBase):
    kind: Literal["classification_code"]
    system: str | None = None
    values: list[str] = Field(min_length=1)


class PsetsPresentSelector(_SelectorBase):
    kind: Literal["psets_present"]
    values: list[str] = Field(min_length=1)


class NamedGroupSelector(_SelectorBase):
    kind: Literal["named_group"]
    values: list[str] = Field(min_length=1)


class GeometryFilterSelector(_SelectorBase):
    kind: Literal["geometry_filter"]
    min_volume_m3: float | None = Field(default=None, ge=0)
    max_volume_m3: float | None = Field(default=None, ge=0)
    min_area_m2: float | None = Field(default=None, ge=0)
    max_area_m2: float | None = Field(default=None, ge=0)
    min_length_m: float | None = Field(default=None, ge=0)
    max_length_m: float | None = Field(default=None, ge=0)
    spatial: dict[str, Any] | None = None


# ── Selector combinators ────────────────────────────────────────────────


class AndSelector(_SelectorBase):
    kind: Literal["and"]
    children: list[EntitySelector] = Field(min_length=1)


class OrSelector(_SelectorBase):
    kind: Literal["or"]
    children: list[EntitySelector] = Field(min_length=1)


class NotSelector(_SelectorBase):
    kind: Literal["not"]
    child: EntitySelector


EntitySelector = Annotated[
    Union[
        AndSelector,
        OrSelector,
        NotSelector,
        CategorySelector,
        IfcClassSelector,
        FamilySelector,
        TypeSelector,
        LevelSelector,
        DisciplineSelector,
        ClassificationCodeSelector,
        PsetsPresentSelector,
        NamedGroupSelector,
        GeometryFilterSelector,
    ],
    Field(discriminator="kind"),
]


# ── Attribute references ────────────────────────────────────────────────


class _AttributeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExactAttributeRef(_AttributeBase):
    kind: Literal["exact"]
    pset_name: str | None = None
    name: str = Field(min_length=1)
    case_sensitive: bool = True


class AliasAttributeRef(_AttributeBase):
    kind: Literal["alias"]
    alias_id: str


class RegexAttributeRef(_AttributeBase):
    kind: Literal["regex"]
    pset_name: str | None = None
    pattern: str
    case_sensitive: bool = False


AttributeRef = Annotated[
    Union[ExactAttributeRef, AliasAttributeRef, RegexAttributeRef],
    Field(discriminator="kind"),
]


# ── Constraints ─────────────────────────────────────────────────────────


class _ConstraintBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EqConstraint(_ConstraintBase):
    operator: Literal["eq"]
    value: Any


class NeqConstraint(_ConstraintBase):
    operator: Literal["neq"]
    value: Any


class LtConstraint(_ConstraintBase):
    operator: Literal["lt"]
    value: float | int | str


class LteConstraint(_ConstraintBase):
    operator: Literal["lte"]
    value: float | int | str


class GtConstraint(_ConstraintBase):
    operator: Literal["gt"]
    value: float | int | str


class GteConstraint(_ConstraintBase):
    operator: Literal["gte"]
    value: float | int | str


class BetweenConstraint(_ConstraintBase):
    operator: Literal["between"]
    min: float | int | str
    max: float | int | str
    inclusive: bool = True


class NotBetweenConstraint(_ConstraintBase):
    operator: Literal["not_between"]
    min: float | int | str
    max: float | int | str
    inclusive: bool = True


class InConstraint(_ConstraintBase):
    operator: Literal["in"]
    values: list[Any] = Field(min_length=1)


class NotInConstraint(_ConstraintBase):
    operator: Literal["not_in"]
    values: list[Any] = Field(min_length=1)


class ContainsConstraint(_ConstraintBase):
    operator: Literal["contains"]
    value: str
    case_sensitive: bool = False


class NotContainsConstraint(_ConstraintBase):
    operator: Literal["not_contains"]
    value: str
    case_sensitive: bool = False


class StartsWithConstraint(_ConstraintBase):
    operator: Literal["starts_with"]
    value: str
    case_sensitive: bool = False


class EndsWithConstraint(_ConstraintBase):
    operator: Literal["ends_with"]
    value: str
    case_sensitive: bool = False


class MatchesConstraint(_ConstraintBase):
    operator: Literal["matches"]
    pattern: str
    case_sensitive: bool = False


class NotMatchesConstraint(_ConstraintBase):
    operator: Literal["not_matches"]
    pattern: str
    case_sensitive: bool = False


class ExistsConstraint(_ConstraintBase):
    operator: Literal["exists"]


class NotExistsConstraint(_ConstraintBase):
    operator: Literal["not_exists"]


class IsNullConstraint(_ConstraintBase):
    operator: Literal["is_null"]


class IsNotNullConstraint(_ConstraintBase):
    operator: Literal["is_not_null"]


class IsEmptyConstraint(_ConstraintBase):
    operator: Literal["is_empty"]


class IsNotEmptyConstraint(_ConstraintBase):
    operator: Literal["is_not_empty"]


class IsNumericConstraint(_ConstraintBase):
    operator: Literal["is_numeric"]


class IsBooleanConstraint(_ConstraintBase):
    operator: Literal["is_boolean"]


class IsDateConstraint(_ConstraintBase):
    operator: Literal["is_date"]


Constraint = Annotated[
    Union[
        EqConstraint,
        NeqConstraint,
        LtConstraint,
        LteConstraint,
        GtConstraint,
        GteConstraint,
        BetweenConstraint,
        NotBetweenConstraint,
        InConstraint,
        NotInConstraint,
        ContainsConstraint,
        NotContainsConstraint,
        StartsWithConstraint,
        EndsWithConstraint,
        MatchesConstraint,
        NotMatchesConstraint,
        ExistsConstraint,
        NotExistsConstraint,
        IsNullConstraint,
        IsNotNullConstraint,
        IsEmptyConstraint,
        IsNotEmptyConstraint,
        IsNumericConstraint,
        IsBooleanConstraint,
        IsDateConstraint,
    ],
    Field(discriminator="operator"),
]


# ── Predicates ──────────────────────────────────────────────────────────


class _PredicateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AndPredicate(_PredicateBase):
    kind: Literal["and"]
    children: list[Predicate] = Field(min_length=1)


class OrPredicate(_PredicateBase):
    kind: Literal["or"]
    children: list[Predicate] = Field(min_length=1)


class NotPredicate(_PredicateBase):
    kind: Literal["not"]
    child: Predicate


class TripletPredicate(_PredicateBase):
    kind: Literal["triplet"]
    attribute: AttributeRef
    constraint: Constraint
    treat_missing_as_fail: bool = True


Predicate = Annotated[
    Union[AndPredicate, OrPredicate, NotPredicate, TripletPredicate],
    Field(discriminator="kind"),
]


# ── Local variables, clash, issue ───────────────────────────────────────


class LocalVariableDefinition(BaseModel):
    """Rule-scoped named expression resolved before predicates / formulas."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    expression: str = Field(min_length=1)
    result_unit: str | None = None
    description: str | None = None


class ClashConfig(BaseModel):
    """Configuration for clash output mode."""

    model_config = ConfigDict(extra="forbid")

    set_a: EntitySelector
    set_b: EntitySelector
    method: Literal["exact", "obb", "sphere"]
    test: Literal["min_distance", "intersection_volume", "enclosed"]
    tolerance_m: float | None = Field(default=None, ge=0)
    min_distance_m: float | None = Field(default=None, ge=0)
    min_intersection_volume_m3: float | None = Field(default=None, ge=0)


class IssueTemplate(BaseModel):
    """Template for rendering an issue from a failed predicate."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    topic_type: Literal[
        "clash",
        "issue",
        "remark",
        "request_for_info",
        "snag",
        "warning",
        "error",
    ] = "issue"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    stage: str | None = None
    labels: list[str] = Field(default_factory=list)


# ── Top-level rule definition ───────────────────────────────────────────


class EacRuleDefinition(BaseModel):
    """Canonical declarative rule body. Mirrors the JSON Schema 1:1."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    output_mode: Literal["aggregate", "boolean", "clash", "issue"]
    result_unit: str | None = None
    tags: list[str] = Field(default_factory=list)
    selector: EntitySelector
    predicate: Predicate | None = None
    formula: str | None = None
    local_variables: list[LocalVariableDefinition] = Field(default_factory=list)
    clash_config: ClashConfig | None = None
    issue_template: IssueTemplate | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# Resolve forward references
AndSelector.model_rebuild()
OrSelector.model_rebuild()
NotSelector.model_rebuild()
AndPredicate.model_rebuild()
OrPredicate.model_rebuild()
NotPredicate.model_rebuild()
EacRuleDefinition.model_rebuild()


__all__ = [
    "AliasAttributeRef",
    "AndPredicate",
    "AndSelector",
    "AttributeRef",
    "BetweenConstraint",
    "CategorySelector",
    "ClashConfig",
    "ClassificationCodeSelector",
    "Constraint",
    "ContainsConstraint",
    "DisciplineSelector",
    "EacRuleDefinition",
    "EndsWithConstraint",
    "EntitySelector",
    "EqConstraint",
    "ExactAttributeRef",
    "ExistsConstraint",
    "FamilySelector",
    "GeometryFilterSelector",
    "GtConstraint",
    "GteConstraint",
    "IfcClassSelector",
    "InConstraint",
    "IsBooleanConstraint",
    "IsDateConstraint",
    "IsEmptyConstraint",
    "IsNotEmptyConstraint",
    "IsNotNullConstraint",
    "IsNullConstraint",
    "IsNumericConstraint",
    "IssueTemplate",
    "LevelSelector",
    "LocalVariableDefinition",
    "LtConstraint",
    "LteConstraint",
    "MatchesConstraint",
    "NamedGroupSelector",
    "NeqConstraint",
    "NotBetweenConstraint",
    "NotContainsConstraint",
    "NotExistsConstraint",
    "NotInConstraint",
    "NotMatchesConstraint",
    "NotPredicate",
    "NotSelector",
    "OrPredicate",
    "OrSelector",
    "Predicate",
    "PsetsPresentSelector",
    "RegexAttributeRef",
    "StartsWithConstraint",
    "TripletPredicate",
    "TypeSelector",
]
