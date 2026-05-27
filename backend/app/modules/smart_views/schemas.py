# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views Pydantic schemas — request / response models.

The :class:`SmartViewRule` is the heart of the API surface: a single
rule has a *selector* (which elements does it match?) and an *action*
(what does it do to them?). The evaluator in ``evaluator.py``
consumes the validated rules directly — every field listed here is a
public contract.

Rule example — "Color walls by FireRating"::

    {
      "id": "rule-1",
      "selector": {
          "ifc_class": "IfcWall",
          "property": "FireRating",
          "operator": "exists",
          "value": null
      },
      "action": "color",
      "action_args": {"color_by_property": "FireRating"},
      "order": 0
    }
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Constants ────────────────────────────────────────────────────────────

#: Permitted scope types. ``federation`` is reserved for the v4 Slice 1
#: federation feature; the evaluator and CRUD already support it so the
#: surface ships unified rather than forcing a follow-up schema bump.
SCOPE_TYPES: tuple[str, ...] = ("user", "project", "federation")

#: Permitted selector operators. ``eq`` and ``neq`` are equality (with
#: type-tolerant string compare for non-numeric values). ``contains`` is
#: substring on the stringified value. ``regex`` runs ``re.search`` with
#: a hard length-cap on the input pattern (no ReDoS via huge patterns).
#: ``gt`` / ``lt`` / ``between`` coerce both sides to ``float``.
#: ``in`` checks set-membership against ``value`` (a list). ``exists``
#: ignores ``value`` and just asserts presence of the property.
OPERATORS: tuple[str, ...] = (
    "eq",
    "neq",
    "contains",
    "regex",
    "gt",
    "lt",
    "in",
    "exists",
    "between",
)

#: Permitted rule actions. ``isolate`` is a shorthand for
#: "hide everything not matched by this rule"; the evaluator applies it
#: by hiding the *complement* of the selector instead of the match.
ACTIONS: tuple[str, ...] = ("show", "hide", "color", "transparent", "isolate")

#: Hard caps that prevent a pathological rule list from DoS'ing the
#: evaluator. 64 rules per view is already well past what any human
#: would author; 512 chars per regex is enough for a real query and
#: short enough to make catastrophic backtracking practically harmless
#: against the ~50k-element bound the bim_hub bulk import enforces.
MAX_RULES_PER_VIEW: int = 64
MAX_REGEX_LENGTH: int = 512
MAX_IN_LIST_SIZE: int = 1024


# ── Rule (selector + action) ─────────────────────────────────────────────


class SmartViewSelector(BaseModel):
    """‌⁠‍Predicate describing which elements a rule applies to.

    All four fields are optional individually so the schema can express
    "match every IfcWall regardless of property" (``ifc_class`` only),
    "match every element where Material exists" (``property`` +
    ``operator='exists'``), or the full quad
    "ifc_class=IfcWall AND FireRating between [60,120]".
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    # Maps onto either the indexed ``BIMElement.element_type`` column or
    # the source-native ``properties.ifc_class`` JSON key. The evaluator
    # tries both — Revit-sourced elements use ``element_type``, IFC ones
    # often surface the strict entity name under ``properties.ifc_class``.
    ifc_class: str | None = Field(default=None, max_length=100)
    # Property name to inspect (free-form key inside
    # ``BIMElement.properties``). Required for every operator other than
    # ``ifc_class``-only selectors — enforced by the model_validator.
    property: str | None = Field(default=None, max_length=200)
    operator: (
        Literal[
            "eq",
            "neq",
            "contains",
            "regex",
            "gt",
            "lt",
            "in",
            "exists",
            "between",
        ]
        | None
    ) = None
    # Whatever the operator compares against. ``None`` is legal for
    # ``exists`` and for ``ifc_class``-only selectors.
    value: Any = None

    @field_validator("value")
    @classmethod
    def _bound_value(cls, v: Any) -> Any:
        """Reject obviously-pathological values before they reach the evaluator."""
        if isinstance(v, str) and len(v) > 4096:
            raise ValueError("selector.value string is too long (max 4096 chars)")
        if isinstance(v, list) and len(v) > MAX_IN_LIST_SIZE:
            raise ValueError(f"selector.value list is too long (max {MAX_IN_LIST_SIZE} items)")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> SmartViewSelector:
        """Cross-field consistency — operator/value/property must align."""
        # An empty selector is meaningless. Require at least one of
        # ifc_class / property to be set.
        if not self.ifc_class and not self.property:
            raise ValueError("selector must define at least one of 'ifc_class' or 'property'")

        if self.operator is None:
            # Bare ``ifc_class`` selector — no operator/value/property
            # constraints to check.
            return self

        if self.operator in {"exists"}:
            # ``exists`` ignores ``value`` but needs a property name.
            if not self.property:
                raise ValueError("operator 'exists' requires a non-empty 'property' name")
            return self

        if self.operator in {"gt", "lt"}:
            if self.value is None:
                raise ValueError(f"operator {self.operator!r} requires a numeric 'value'")
            # Defer the coercion to the evaluator so non-finite values
            # are rejected centrally; just sanity-check the type here.
            if isinstance(self.value, (list, dict, tuple)):
                raise ValueError(f"operator {self.operator!r} requires a scalar 'value'")
            return self

        if self.operator == "between":
            if not (isinstance(self.value, (list, tuple)) and len(self.value) == 2):
                raise ValueError("operator 'between' requires a [low, high] pair as 'value'")
            return self

        if self.operator == "in":
            if not isinstance(self.value, list):
                raise ValueError("operator 'in' requires a list as 'value'")
            return self

        if self.operator == "regex":
            if not isinstance(self.value, str):
                raise ValueError("operator 'regex' requires a string pattern")
            if len(self.value) > MAX_REGEX_LENGTH:
                raise ValueError(f"operator 'regex' pattern too long (max {MAX_REGEX_LENGTH} chars)")
            return self

        # eq / neq / contains — value is required.
        if self.value is None:
            raise ValueError(f"operator {self.operator!r} requires a non-null 'value'")
        return self


class SmartViewActionArgs(BaseModel):
    """‌⁠‍Optional per-action arguments.

    Only the keys relevant to the chosen action are read by the
    evaluator; the others are tolerated so authors can edit a rule in
    place without losing previous customisation when they flip the
    action verb. ``extra='forbid'`` is intentionally NOT set so a
    forward-compatible field can ship without breaking old views.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Used by action='color'. ``#RRGGBB`` or ``#RRGGBBAA`` hex.
    color: str | None = Field(default=None, max_length=9)
    # Used by action='transparent'. Clamped to [0.0, 1.0] in evaluator.
    opacity: float | None = None
    # Used by action='color' to bucket-colour every match by a property
    # value (deterministic HCL hash). ``color`` and ``color_by_property``
    # are mutually exclusive — ``color_by_property`` wins if both are
    # present.
    color_by_property: str | None = Field(default=None, max_length=200)

    @field_validator("color")
    @classmethod
    def _hex_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith("#") or len(v) not in (4, 7, 9):
            raise ValueError("color must be a #RGB / #RRGGBB / #RRGGBBAA hex string")
        hex_part = v[1:]
        try:
            int(hex_part, 16)
        except ValueError as exc:
            raise ValueError("color hex digits must be 0-9 a-f") from exc
        return v

    @field_validator("opacity")
    @classmethod
    def _opacity_range(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not (0.0 <= float(v) <= 1.0):
            raise ValueError("opacity must be in [0.0, 1.0]")
        return float(v)


class SmartViewRule(BaseModel):
    """‌⁠‍A single rule: (selector → action).

    ``order`` decides the evaluation order — lower runs first; later
    rules overwrite earlier ones (last-write-wins). Two rules with the
    same ``order`` resolve by their stable ``id`` (lexicographic) so
    behaviour is deterministic across saves.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    selector: SmartViewSelector
    action: Literal["show", "hide", "color", "transparent", "isolate"]
    action_args: SmartViewActionArgs = Field(default_factory=SmartViewActionArgs)
    order: int = 0


# ── SmartView (top-level) ────────────────────────────────────────────────


class SmartViewBase(BaseModel):
    """‌⁠‍Shared fields between create/update payloads + response."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    rules: list[SmartViewRule] = Field(default_factory=list)
    default_action: Literal["show_all", "hide_all"] = "show_all"

    @field_validator("rules")
    @classmethod
    def _bound_rules(cls, v: list[SmartViewRule]) -> list[SmartViewRule]:
        if len(v) > MAX_RULES_PER_VIEW:
            raise ValueError(f"smart view has too many rules ({len(v)}, max {MAX_RULES_PER_VIEW})")
        return v


class SmartViewCreate(SmartViewBase):
    """Request body for ``POST /smart-views/``."""

    scope_type: Literal["user", "project", "federation"] = "user"
    scope_id: UUID


class SmartViewUpdate(BaseModel):
    """Request body for ``PUT /smart-views/{id}``.

    Every field is optional so the UI can do a per-field patch without
    re-sending the rules list (which can be several KB on a long view).
    The scope is intentionally NOT updatable — a view's owner / scope
    is fixed at creation time.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    rules: list[SmartViewRule] | None = None
    default_action: Literal["show_all", "hide_all"] | None = None

    @field_validator("rules")
    @classmethod
    def _bound_rules(cls, v: list[SmartViewRule] | None) -> list[SmartViewRule] | None:
        if v is not None and len(v) > MAX_RULES_PER_VIEW:
            raise ValueError(f"smart view has too many rules ({len(v)}, max {MAX_RULES_PER_VIEW})")
        return v


class SmartViewResponse(BaseModel):
    """Response shape for read / list / create / update endpoints.

    ``share_token`` surfaces only when the authoring user is the caller —
    the service layer redacts it for everyone else (a project-scoped
    view's token must not leak to collaborators who don't own it). The
    field is exposed as a plain string so the UI can build the share
    URL client-side (``/share/<token>``) without an extra round-trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    scope_type: str
    scope_id: UUID
    name: str
    description: str | None = None
    rules: list[SmartViewRule] = Field(default_factory=list)
    default_action: str = "show_all"
    color_legend: dict[str, Any] | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    # NULL means "not shared". Only populated for the author.
    share_token: str | None = None


class SmartViewPresetSummary(BaseModel):
    """A single entry in the preset catalogue.

    Returned by ``SmartViewService.list_presets`` so the UI can render
    install cards without needing to know the rule schema in detail.
    The full rule list is intentionally NOT included — clients install
    by id (``preset_id``) and the service re-validates the canonical
    template on the server side. That avoids drift where a stale UI
    bundle persists an old rule list against a freshly-shipped preset.
    """

    model_config = ConfigDict(from_attributes=True)

    preset_id: str
    category: str
    name: str
    description: str
    rule_count: int


class SmartViewShareInfo(BaseModel):
    """Returned by ``create_share_token`` / surfaced in the share modal.

    ``url`` is the server-side absolute path to the share landing page —
    the front-end converts it to an absolute URL when copying to
    clipboard. Keeping the path here (not a fully-qualified URL) avoids
    hardcoding the deployment host in the service layer.
    """

    model_config = ConfigDict(from_attributes=True)

    view_id: UUID
    share_token: str
    url: str


# ── Evaluator ────────────────────────────────────────────────────────────


class ElementState(BaseModel):
    """‌⁠‍Resolved per-element visual state produced by the evaluator."""

    model_config = ConfigDict(extra="forbid")

    visible: bool = True
    color: str | None = None
    opacity: float = 1.0


class SmartViewEvaluateResponse(BaseModel):
    """Payload returned by ``POST /smart-views/{id}/evaluate``.

    ``states`` is keyed by element ``stable_id`` (the GUID the source
    file gave the element, *not* the internal UUID — it survives
    re-imports). ``legend`` is populated only when at least one rule
    uses ``color_by_property``.
    """

    states: dict[str, ElementState]
    legend: dict[str, str] | None = None
    element_count: int = 0
    rule_count: int = 0
