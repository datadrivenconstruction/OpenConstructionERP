# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cases Pydantic schemas - request/response models.

The step shape mirrors ``PlaybookStep`` in
``frontend/src/features/cases/types.ts`` with one deliberate difference: a
shipped playbook carries ``titleKey`` + ``titleDefault`` because its text is
translated into 29 locales at build time, while an authored case carries plain
text because the author writes it in their own language and nobody translates
it afterwards. The reader renders a key when there is one and the literal when
there is not, so both kinds run through the same component.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Kept in step with ``CASE_CATEGORIES`` in :mod:`app.modules.cases.models` by
# ``test_cases_module.py``; the tuple is what the database column is checked against
# and this is what the API rejects on, so a drift between them would let a
# category through the door that the reader cannot group.
CaseCategoryLiteral = Literal[
    "estimating",
    "tendering",
    "planning",
    "bim",
    "site",
    "quality",
    "commercial",
    "handover",
]

PinSourceLiteral = Literal["builtin", "custom"]

# A step's ``to`` becomes an href in the reader. Only an in-app path is ever a
# legitimate value, so the field is restricted to one rather than sanitised
# afterwards: a leading single slash, then path characters, then an optional
# query. This rejects ``javascript:`` and friends by construction, and it also
# rejects ``//evil.example/x``, which a naive "must start with /" check lets
# straight through as a protocol-relative URL to another host.
#
# ``.`` is allowed inside a segment because a route may legitimately carry one,
# but a ``..`` segment is rejected separately below. The character class alone
# does not catch it: ``/../admin`` matches this pattern happily, and a router
# that normalises the path would then land somewhere the author never named.
#
# ``:`` is allowed because the shipped cases use route parameters - a third of
# them step through ``/projects/:projectId/files`` and the reader substitutes
# the active project at run time. Without it, copying one of the product's own
# cases produced a case the product refused to save. It costs nothing here:
# the leading slash is mandatory and unescapable, so ``javascript:`` cannot
# match this pattern with or without the colon in the class.
_ROUTE_RE = re.compile(r"^/(?!/)[A-Za-z0-9\-_/.:]*(\?[A-Za-z0-9\-_=&%.,:+]*)?$")

MAX_STEPS = 40


class CaseStep(BaseModel):
    """One step of an authored case: a screen, and why you are on it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    what: str = Field(default="", max_length=1000)
    why: str = Field(default="", max_length=1000)
    module_label: str = Field(default="", max_length=120)
    to: str = Field(min_length=1, max_length=300)
    icon: str = Field(default="", max_length=64)
    inputs: list[str] = Field(default_factory=list, max_length=12)
    outputs: list[str] = Field(default_factory=list, max_length=12)
    inputs_hint: str = Field(default="", max_length=400)
    outputs_hint: str = Field(default="", max_length=400)

    @field_validator("to")
    @classmethod
    def _check_route(cls, value: str) -> str:
        if not _ROUTE_RE.match(value):
            raise ValueError(
                "Step target must be an in-app path such as '/boq' or '/reports?tab=cost'; "
                "external and script URLs are not accepted."
            )
        if ".." in value.split("?", 1)[0].split("/"):
            raise ValueError("Step target must name a screen directly; '..' segments are not accepted.")
        return value

    @field_validator("inputs", "outputs")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()][:12]


class _CaseBody(BaseModel):
    """The writable half of a case, shared by create and update."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    long_description: str = Field(default="", max_length=4000)
    category: CaseCategoryLiteral
    company_types: list[str] = Field(default_factory=list, max_length=12)
    roles: list[str] = Field(default_factory=list, max_length=12)
    stage: str = Field(default="", max_length=64)
    est_minutes: int = Field(default=10, ge=1, le=600)
    icon: str = Field(default="", max_length=64)
    steps: list[CaseStep] = Field(default_factory=list, max_length=MAX_STEPS)
    source_playbook_id: str = Field(default="", max_length=128)
    is_shared: bool = False

    @model_validator(mode="after")
    def _unique_step_ids(self) -> _CaseBody:
        seen = [step.id for step in self.steps]
        if len(set(seen)) != len(seen):
            raise ValueError("Step ids must be unique within a case; progress is tracked by step id.")
        return self


class CaseCreateRequest(_CaseBody):
    """Create a case, either from scratch or as a copy of a shipped playbook."""


class CaseUpdateRequest(_CaseBody):
    """Replace a case. The editor saves the whole case, so this is a full PUT."""


class CaseDuplicateRequest(BaseModel):
    """Fork a case that is already stored here. The source is in the path.

    Starting from one of the shipped playbooks is *not* this endpoint: those
    live in the frontend bundle and the backend has never seen them, so the
    reader posts their contents to ``POST /`` with ``source_playbook_id`` set
    to record where the copy came from.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=200)


class CaseResponse(BaseModel):
    """One case as the reader receives it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    description: str
    long_description: str
    category: str
    company_types: list[str]
    roles: list[str]
    stage: str
    est_minutes: int
    icon: str
    steps: list[CaseStep]
    source_playbook_id: str
    is_shared: bool
    created_at: datetime
    updated_at: datetime
    # Filled by the router, not stored: whether the caller may edit this case.
    # Without it a shared case looks editable to everyone who can see it.
    can_edit: bool = True


class CaseFinding(BaseModel):
    """One validation finding shown beside the case in the editor.

    ``key`` is what the reader translates; ``message`` is the English the rule
    wrote and is only shown when a locale has no string for the key yet. The
    same split the design-option fairness notices use.
    """

    key: str
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    details: dict = Field(default_factory=dict)
    # True when the row says a check could not run, rather than saying anything
    # about the case. The evaluator already distinguishes the two, and a field
    # it fills that the response never carries is the same silence one layer
    # up: without this the reader can only tell them apart by reading English
    # prose, and an infrastructure failure is exactly the row that must not be
    # mistaken for an ordinary remark about the author's work.
    is_engine_error: bool = False


class CaseSaveResponse(BaseModel):
    """A saved case plus what validation made of it."""

    case: CaseResponse
    findings: list[CaseFinding] = Field(default_factory=list)


class PinRequest(BaseModel):
    """Pin a case to a project for the calling user."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    case_source: PinSourceLiteral
    case_id: str = Field(min_length=1, max_length=128)
    sort_order: int = Field(default=0, ge=0, le=999)
    note: str = Field(default="", max_length=500)


class PinResponse(BaseModel):
    """One pinned case."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: UUID
    case_source: str
    case_id: str
    sort_order: int
    note: str
    created_at: datetime
    updated_at: datetime


class PinReorderRequest(BaseModel):
    """Set the order of the pinned cases on one project in a single call."""

    project_id: UUID
    pin_ids: list[UUID] = Field(min_length=1, max_length=200)


__all__ = [
    "MAX_STEPS",
    "CaseCreateRequest",
    "CaseDuplicateRequest",
    "CaseResponse",
    "CaseStep",
    "CaseUpdateRequest",
    "PinReorderRequest",
    "PinRequest",
    "PinResponse",
]
