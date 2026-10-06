# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for the module builder."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from app.modules.module_builder.spec import DueFeature, FieldSpec, LinkTarget, ModuleSpec, StatusFeature

# A UI language tag such as "de" or "pt-BR". Checked strictly because it is
# written into the assistant's instructions.
LOCALE_PATTERN = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$"

FeatureName = Literal["status", "due", "export", "comments"]
Confidence = Literal["high", "medium", "low"]


class DraftRequest(BaseModel):
    """What the user typed in the first step of the wizard."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=10, max_length=4000)
    # The language the person reads the wizard in. The assistant writes the
    # labels, the messages and its reasons in it.
    locale: str | None = Field(default=None, max_length=16, pattern=LOCALE_PATTERN)


class _WithoutNulls(BaseModel):
    """Leaves unset optional keys out of the JSON, as the contract's ``?`` reads."""

    # No return annotation on purpose: pydantic would publish it as the
    # response schema in place of the model's own fields.
    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: SerializerFunctionWrapHandler):
        dumped: dict[str, Any] = handler(self)
        return {k: v for k, v in dumped.items() if v is not None}


class SuggestionPatch(_WithoutNulls):
    """What applying a suggestion changes. Exactly one part is set."""

    field: FieldSpec | None = None
    status: StatusFeature | None = None
    due: DueFeature | None = None
    export: Literal[True] | None = None
    comments: Literal[True] | None = None


class Suggestion(_WithoutNulls):
    """Something the module could also do. Never applied until a person ticks it.

    ``id`` is stable (``link:contract``, ``feature:status``), so suggestions
    from the assistant and from the rules merge by it.
    """

    id: str
    kind: Literal["link", "feature"]
    target: LinkTarget | None = None
    feature: FeatureName | None = None
    confidence: Confidence
    # Resolved by the frontend as ``module_builder.reason.<reason_code>``.
    reason_code: str | None = None
    reason_params: dict[str, str | int] | None = None
    # The assistant's own words, already in the reader's language. Shown only
    # where there is no reason_code.
    reason: str | None = None
    patch: SuggestionPatch


class DraftResponse(BaseModel):
    """A spec the wizard can now show, edit and install. Nothing was written.

    The spec carries no links and no functions: the assistant's ideas for those
    arrive as ``suggestions`` and reach the spec only when a person ticks them.
    """

    spec: ModuleSpec
    source: str = Field(description="assistant when drafted from a sentence, wizard when filled in by hand")
    suggestions: list[Suggestion] = Field(default_factory=list)


class SuggestRequest(BaseModel):
    """Ask what a spec could also do, by the rules rather than an assistant."""

    model_config = ConfigDict(extra="forbid")

    spec: ModuleSpec
    locale: str | None = Field(default=None, max_length=16, pattern=LOCALE_PATTERN)


class SuggestResponse(BaseModel):
    suggestions: list[Suggestion]


class LookupItem(BaseModel):
    id: str
    label: str
    sublabel: str | None = None


class LookupResponse(BaseModel):
    items: list[LookupItem]


class LookupLabelsResponse(BaseModel):
    # Only the ids the caller may see. A missing id means "not yours to see",
    # which is deliberately the same as "does not exist".
    labels: dict[str, str]


class LinkTargetInfo(BaseModel):
    target: str
    module: str
    # False when the owning module is switched off here: no link can be built to it.
    available: bool


class PreviewFile(BaseModel):
    path: str
    lines: int
    content: str


class PreviewRequest(BaseModel):
    """Ask what a spec would generate. Changes nothing on the server."""

    model_config = ConfigDict(extra="forbid")

    spec: ModuleSpec


class PreviewResponse(BaseModel):
    """Everything that would land on disk, before any of it does."""

    spec: ModuleSpec
    files: list[PreviewFile]
    total_lines: int
    # Shown in the review step, so the URL is known before install rather than
    # discovered afterwards.
    base_path: str
    # Proof, for the install call that follows, that these files were rendered
    # for this person to read. Install will not write a spec that arrives
    # without one, which is what makes the review step a rule rather than a
    # screen. See :mod:`app.modules.module_builder.review_token`.
    review_token: str


class InstallRequest(BaseModel):
    """Install a spec that has been previewed.

    Deliberately not the same body as :class:`PreviewRequest`. The two endpoints
    used to take an identical payload, so an install carried no evidence that
    anyone had looked at the generated code; the extra field is that evidence,
    and keeping the types apart is what stops them drifting back together.
    """

    model_config = ConfigDict(extra="forbid")

    spec: ModuleSpec
    review_token: str


class InstalledProblem(BaseModel):
    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class InstalledModuleRead(BaseModel):
    key: str
    module_name: str
    display_name: str
    version: str
    generated_at: str
    entity: str
    field_count: int
    rule_count: int
    # The screen fetches ``{base_path}/ui-spec`` and everything else under it.
    base_path: str
    # "quarantined": the server would not load it at startup, because its
    # code may hold what a name put there. Its routes are not mounted, so
    # base_path answers 404; it can be removed, or built again under its key.
    status: Literal["installed", "quarantined"] = "installed"
    # Why, when quarantined: ``code`` is ``unsafe_code`` (``params.files``
    # names the files) or ``unverifiable``.
    problem: InstalledProblem | None = None


class UpgradeChange(BaseModel):
    """One thing an upgrade adds or rewords."""

    kind: Literal[
        "field_added",
        "link_added",
        "feature_added",
        "feature_changed",
        "state_added",
        "rule_added",
        "field_changed",
        "label_changed",
    ]
    field: str | None = None
    feature: str | None = None
    state: str | None = None
    rule: str | None = None


class UpgradePreviewResponse(PreviewResponse):
    """The files of the upgraded module, and what the upgrade changes.

    The review token is for this upgrade only: install refuses it, and the
    upgrade refuses an install token.
    """

    changes: list[UpgradeChange]
    record_count: int


class UpgradeRequest(BaseModel):
    """Upgrade an installed module to a spec previewed for that upgrade."""

    model_config = ConfigDict(extra="forbid")

    spec: ModuleSpec
    review_token: str


class UpgradeResponse(BaseModel):
    key: str
    module_name: str
    base_path: str
    record_count: int
    changes: list[UpgradeChange]


class InstalledList(BaseModel):
    items: list[InstalledModuleRead]
    total: int
    runtime_root: str


class UninstallResponse(BaseModel):
    key: str
    module_name: str
    removed: bool
    data_dropped: bool


class FieldTypeInfo(BaseModel):
    """One choice in the wizard's field-type list."""

    type: str
    label: str
    hint: str


class RuleKindInfo(BaseModel):
    kind: str
    label: str
    hint: str
    applies_to: list[str]
    needs_other_field: bool = False
    needs_bounds: bool = False


class VocabularyResponse(BaseModel):
    """What the wizard is allowed to offer, read from the spec rather than copied.

    The frontend would otherwise carry its own list of field types and rule
    kinds, and the two would drift the first time one is added here.
    """

    field_types: list[FieldTypeInfo]
    rule_kinds: list[RuleKindInfo]
    reserved_field_names: list[str]
    reserved_keys: list[str]
    max_fields: int
    assistant_available: bool
    # Their presence is how the wizard tells this server understands links and
    # functions; an older server sends neither.
    link_targets: list[LinkTargetInfo] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    # An installed module can be upgraded in place. Absent on older servers.
    upgrade: bool = False
