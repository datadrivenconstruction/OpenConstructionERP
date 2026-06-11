# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍The FilterSpec DSL and the request/response models.

The client never sends SQL. It sends a small, typed JSON spec that the engine
compiles into a parameterized SQLAlchemy ``select()``. There is no ``eval``, no
``exec``, no raw SQL string, and no f-string interpolation of identifiers:
identifiers are resolved through the per-entity whitelist (see ``registry.py``)
to real ORM attributes only, and values flow through SQLAlchemy bind parameters.

Two structural guards are enforced here at deserialization time, before the
complexity ceiling even runs:

    * a field-name regex (``^[a-z][a-z0-9_]*$``) that forbids dots, so a
      relationship traversal like ``project.owner_id`` can never be expressed;
    * hard caps on conditions per group (20) and nesting depth (3).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Field names address ONE whitelisted column. The regex forbids dots and spaces,
# so no relationship traversal (``foo.bar``) or arbitrary attribute can reach the
# builder - it is rejected here, at Pydantic validation, with a 422.
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Caps mirrored by the complexity ceiling in ``query_builder.estimate_cost``.
MAX_CONDITIONS_PER_GROUP = 50
MAX_GROUP_NESTING_DEPTH = 5
MAX_SORT_FIELDS = 3
MAX_GROUP_BY_FIELDS = 2
MAX_IN_LIST = 200

FilterOp = Literal[
    "eq",
    "neq",
    "lt",
    "lte",
    "gt",
    "gte",
    "contains",
    "startswith",
    "in",
    "between",
    "is_null",
    "not_null",
]

ShareScope = Literal["private", "project", "workspace"]


class FilterCondition(BaseModel):
    """A single leaf comparison: ``field op value``.

    ``value`` is validated against the field kind at bind time (see
    :meth:`FilterSpec.bind`), not here, because the kind is only known once the
    entity is resolved.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    op: FilterOp
    value: Any = None

    @field_validator("field")
    @classmethod
    def _validate_field_name(cls, v: str) -> str:
        if not FIELD_NAME_RE.match(v):
            msg = (
                f"Invalid field name {v!r}: must match {FIELD_NAME_RE.pattern} "
                "(no dots, no relationship traversal, no spaces)"
            )
            raise ValueError(msg)
        return v


class FilterGroup(BaseModel):
    """A boolean group of conditions and nested groups.

    ``join`` decides whether the members are ANDed or ORed. Nesting is capped at
    :data:`MAX_GROUP_NESTING_DEPTH` and conditions per group at
    :data:`MAX_CONDITIONS_PER_GROUP`.
    """

    model_config = ConfigDict(extra="forbid")

    join: Literal["and", "or"] = "and"
    conditions: list[FilterCondition] = Field(default_factory=list)
    groups: list[FilterGroup] = Field(default_factory=list)

    @field_validator("conditions")
    @classmethod
    def _cap_conditions(cls, v: list[FilterCondition]) -> list[FilterCondition]:
        if len(v) > MAX_CONDITIONS_PER_GROUP:
            msg = f"Too many conditions in one group: {len(v)} > {MAX_CONDITIONS_PER_GROUP}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _cap_depth(self) -> FilterGroup:
        if _group_depth(self) > MAX_GROUP_NESTING_DEPTH:
            msg = f"Filter group nesting deeper than {MAX_GROUP_NESTING_DEPTH} is not allowed"
            raise ValueError(msg)
        return self


def _group_depth(group: FilterGroup) -> int:
    """Return the nesting depth of ``group`` (1 = no nested groups)."""
    if not group.groups:
        return 1
    return 1 + max(_group_depth(g) for g in group.groups)


class SortSpec(BaseModel):
    """One sort term: a whitelisted, sortable field and a direction."""

    model_config = ConfigDict(extra="forbid")

    field: str
    direction: Literal["asc", "desc"] = "asc"

    @field_validator("field")
    @classmethod
    def _validate_field_name(cls, v: str) -> str:
        if not FIELD_NAME_RE.match(v):
            msg = f"Invalid sort field {v!r}: must match {FIELD_NAME_RE.pattern}"
            raise ValueError(msg)
        return v


class FilterSpec(BaseModel):
    """The serialized, typed query spec persisted on a saved view.

    Re-validated by Pydantic on every read and every write, never trusted as-is.
    Binding against a concrete entity (the column whitelist) happens separately
    in :meth:`bind`, called by the service before the query is built.
    """

    model_config = ConfigDict(extra="forbid")

    where: FilterGroup = Field(default_factory=FilterGroup)
    sort: list[SortSpec] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    distinct: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1)

    @field_validator("sort")
    @classmethod
    def _cap_sort(cls, v: list[SortSpec]) -> list[SortSpec]:
        if len(v) > MAX_SORT_FIELDS:
            msg = f"Too many sort fields: {len(v)} > {MAX_SORT_FIELDS}"
            raise ValueError(msg)
        return v

    @field_validator("group_by")
    @classmethod
    def _cap_group_by(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_GROUP_BY_FIELDS:
            msg = f"Too many group_by fields: {len(v)} > {MAX_GROUP_BY_FIELDS}"
            raise ValueError(msg)
        for name in v:
            if not FIELD_NAME_RE.match(name):
                msg = f"Invalid group_by field {name!r}: must match {FIELD_NAME_RE.pattern}"
                raise ValueError(msg)
        return v

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, v: list[str]) -> list[str]:
        for name in v:
            if not FIELD_NAME_RE.match(name):
                msg = f"Invalid column {name!r}: must match {FIELD_NAME_RE.pattern}"
                raise ValueError(msg)
        return v

    def bind(self, entity: Any) -> BoundSpec:
        """Validate every referenced field against the entity whitelist.

        Walks ``where``, ``sort``, ``group_by``, and ``columns`` and rejects, with
        a :class:`app.modules.saved_views.errors.WhitelistError`:

            * any field name not in ``entity.fields``;
            * an operator not allowed for the field's kind;
            * a ``columns`` entry that is not selectable;
            * a ``sort`` on a non-sortable field;
            * a ``group_by`` on a non-groupable field;
            * an ``in`` list longer than :data:`MAX_IN_LIST`;
            * a value that cannot be coerced to the field kind.

        Returns a :class:`BoundSpec` (this spec plus the resolved entity) that the
        query builder consumes. Raising here keeps every illegal identifier out of
        the builder, which only ever reads ``FieldSpec.column`` from the bound,
        validated entity.

        Args:
            entity: The resolved ``QueryableEntity`` (typed loosely to avoid a
                circular import with the registry).

        Returns:
            A :class:`BoundSpec` wrapping this spec and the entity.

        Raises:
            WhitelistError: On any non-whitelisted field, operator, or value.
        """
        from app.modules.saved_views.errors import WhitelistError

        fields = entity.fields

        def _field_or_reject(name: str) -> Any:
            spec = fields.get(name)
            if spec is None:
                raise WhitelistError(
                    f"Field {name!r} is not available on entity {entity.entity_type!r}",
                    field=name,
                )
            return spec

        # where: every condition field must be filterable + the op allowed.
        def _walk(group: FilterGroup) -> None:
            for cond in group.conditions:
                fs = _field_or_reject(cond.field)
                if not fs.filterable:
                    raise WhitelistError(
                        f"Field {cond.field!r} is not filterable",
                        field=cond.field,
                    )
                allowed = _allowed_operators(fs)
                if cond.op not in allowed:
                    raise WhitelistError(
                        f"Operator {cond.op!r} is not allowed on field {cond.field!r}",
                        field=cond.field,
                    )
                _validate_value(fs, cond)
            for sub in group.groups:
                _walk(sub)

        _walk(self.where)

        for sort in self.sort:
            fs = _field_or_reject(sort.field)
            if not fs.sortable:
                raise WhitelistError(f"Field {sort.field!r} is not sortable", field=sort.field)

        for name in self.group_by:
            fs = _field_or_reject(name)
            if not fs.groupable:
                raise WhitelistError(f"Field {name!r} is not groupable", field=name)

        for name in self.columns:
            fs = _field_or_reject(name)
            if not fs.selectable:
                raise WhitelistError(f"Field {name!r} is not selectable", field=name)

        return BoundSpec(spec=self, entity=entity)


def _allowed_operators(field_spec: Any) -> tuple[str, ...]:
    """Resolve the allowed operator set for a field.

    Uses the explicit ``operators`` tuple when set, otherwise the kind default.
    """
    if field_spec.operators:
        return field_spec.operators
    return KIND_DEFAULT_OPERATORS.get(field_spec.kind, _BASE_OPERATORS)


# Operator sets by field kind. ``string`` adds substring ops; numeric/money/date
# add ordering; ``bool``/``uuid``/``enum`` are equality + null only.
_BASE_OPERATORS: tuple[str, ...] = ("eq", "neq", "in", "is_null", "not_null")
_ORDERED_OPERATORS: tuple[str, ...] = (
    "eq",
    "neq",
    "lt",
    "lte",
    "gt",
    "gte",
    "between",
    "in",
    "is_null",
    "not_null",
)
_STRING_OPERATORS: tuple[str, ...] = (
    "eq",
    "neq",
    "contains",
    "startswith",
    "in",
    "is_null",
    "not_null",
)
KIND_DEFAULT_OPERATORS: dict[str, tuple[str, ...]] = {
    "string": _STRING_OPERATORS,
    "number": _ORDERED_OPERATORS,
    "money": _ORDERED_OPERATORS,
    "date": _ORDERED_OPERATORS,
    "bool": ("eq", "neq", "is_null", "not_null"),
    "uuid": ("eq", "neq", "in", "is_null", "not_null"),
    "enum": ("eq", "neq", "in", "is_null", "not_null"),
}


def _validate_value(field_spec: Any, cond: FilterCondition) -> None:
    """Reject a value that cannot be coerced to the field kind.

    A coercion failure is a 422 (``WhitelistError``), never a 500 at execute time.
    """
    from app.modules.saved_views.errors import WhitelistError

    op = cond.op
    if op in ("is_null", "not_null"):
        return  # value is irrelevant

    if op == "in":
        if not isinstance(cond.value, list):
            raise WhitelistError(
                f"Operator 'in' on {cond.field!r} requires a list value",
                field=cond.field,
            )
        if len(cond.value) > MAX_IN_LIST:
            raise WhitelistError(
                f"'in' list on {cond.field!r} has {len(cond.value)} elements; max is {MAX_IN_LIST}",
                field=cond.field,
            )
        for item in cond.value:
            _coerce_or_reject(field_spec, item, cond.field)
        return

    if op == "between":
        if not isinstance(cond.value, list) or len(cond.value) != 2:
            raise WhitelistError(
                f"Operator 'between' on {cond.field!r} requires a [low, high] pair",
                field=cond.field,
            )
        for item in cond.value:
            _coerce_or_reject(field_spec, item, cond.field)
        return

    _coerce_or_reject(field_spec, cond.value, cond.field)


def _coerce_or_reject(field_spec: Any, value: Any, field_name: str) -> Any:
    """Coerce a single scalar to the field kind or raise ``WhitelistError``."""
    from decimal import Decimal, InvalidOperation

    from app.modules.saved_views.errors import WhitelistError

    kind = field_spec.kind
    try:
        if kind in ("number", "money"):
            Decimal(str(value))
        elif kind == "uuid":
            uuid.UUID(str(value))
        elif kind == "date":
            datetime.fromisoformat(str(value))
        elif kind == "bool":
            if not isinstance(value, bool) and str(value).lower() not in ("true", "false", "1", "0"):
                raise ValueError(value)
        elif kind == "enum":
            allowed = field_spec.enum_values or ()
            if str(value) not in allowed:
                raise WhitelistError(
                    f"Value {value!r} is not an allowed enum value for {field_name!r}",
                    field=field_name,
                )
        # string: anything stringifiable is fine
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise WhitelistError(
            f"Value {value!r} is not valid for {kind} field {field_name!r}",
            field=field_name,
        ) from exc
    return value


class BoundSpec(BaseModel):
    """A :class:`FilterSpec` validated against a concrete entity.

    Produced only by :meth:`FilterSpec.bind`. The builder requires one of these
    so an unbound (un-whitelisted) spec can never be compiled.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: FilterSpec
    entity: Any


# ── Request / response models ──────────────────────────────────────────────


class SavedViewCreate(BaseModel):
    """Payload to create a saved view."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    spec: FilterSpec = Field(default_factory=FilterSpec)
    share_scope: ShareScope = "private"
    is_pinned: bool = False
    project_id: uuid.UUID
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")


class SavedViewUpdate(BaseModel):
    """Patch payload - every field optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    spec: FilterSpec | None = None
    share_scope: ShareScope | None = None
    is_pinned: bool | None = None
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata")


class SavedViewResponse(BaseModel):
    """A saved-view definition row. ``share_token`` deliberately does not exist."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None
    entity_type: str
    name: str
    description: str | None
    spec: dict[str, Any]
    share_scope: str
    is_pinned: bool
    metadata_: dict[str, Any] = Field(serialization_alias="metadata", validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RunRequest(BaseModel):
    """Ad-hoc run: an inline spec against a registered entity, without saving."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=64)
    project_id: uuid.UUID
    spec: FilterSpec = Field(default_factory=FilterSpec)


class RunResponse(BaseModel):
    """Result of running a view: the capped rows plus paging telemetry."""

    rows: list[dict[str, Any]]
    columns: list[str]
    total_estimate: int | None = None
    truncated: bool = False
    page: int
    page_size: int


class CountResponse(BaseModel):
    """Capped count for a reminder badge or dashboard tile."""

    count: int
    truncated: bool = False
