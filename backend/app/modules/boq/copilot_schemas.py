# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic v2 schemas for the BOQ per-position AI copilot.

The copilot is a position-scoped chat. The user sends a free-text message
(:class:`CopilotChatRequest`); the assistant replies with prose plus zero or
more structured :class:`CopilotActionProposal` actions
(:class:`CopilotChatResponse`). Chat never writes: every action is proposed for
review, and the estimator accepts or rejects them through
:class:`CopilotReviewRequest` / :class:`CopilotReviewResponse`, which apply the
accepted ones via the existing ``BOQService.update_position`` write path.
:class:`CopilotApplyRequest` / :class:`CopilotApplyResponse` (one client-sent
action) remain for API compatibility.

Action contract (the four supported mutations and their ``payload`` shapes):

* ``update_description`` -> ``{"description": str}``
* ``set_quantity``       -> ``{"quantity": float, "unit"?: str}``
* ``set_unit_rate``      -> ``{"unit_rate": float|str, "currency"?: str}``
* ``add_resources``      -> ``{"resources": [ {name, type, unit, quantity,
                              unit_rate, code?, currency?}, ... ]}``

``before`` captures the position fields the action would change (so the UI can
show a diff and an undo). ``source`` carries the grounding catalogue reference
(e.g. the CWICR ``code`` the price came from) when the action cites one. All
prices/resources the model proposes MUST reference a provided catalogue code -
the service prompt forbids invented prices.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.boq.schemas import PositionResponse

# Action type discriminator - the four position mutations the copilot can
# propose. Kept as a module-level alias so both the proposal schema and the
# service validation read from one definition.
CopilotActionType = Literal[
    "update_description",
    "set_quantity",
    "set_unit_rate",
    "add_resources",
]

# Lifecycle status of a single proposed action.
#   needs_review - proposed, waiting for a person to accept or reject it
#   applied      - accepted by a person and written to the position
#   dismissed    - rejected by a person
#   failed       - an apply attempt raised; ``payload``/``before`` retained for retry
#   auto_applied - legacy: written by the copilot on its own before 18.1. Kept
#                  so stored threads still parse; never produced any more.
CopilotActionStatus = Literal[
    "auto_applied",
    "needs_review",
    "applied",
    "dismissed",
    "failed",
]


class CopilotMessageOut(BaseModel):
    """One persisted copilot turn returned to the client."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    position_id: UUID
    boq_id: UUID
    project_id: UUID
    role: str
    content: str
    # Structured proposals for an assistant turn (None / empty for user turns).
    actions: list[CopilotActionProposal] = Field(default_factory=list)
    created_at: datetime
    created_by: UUID | None = None


class CopilotActionProposal(BaseModel):
    """A single structured change the copilot proposes for the position.

    The same shape is used three ways: returned from ``chat`` (with a server
    computed ``status``), echoed inside a persisted :class:`CopilotMessageOut`,
    and sent back by the client to ``apply`` a previously-proposed action.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    action_type: CopilotActionType
    # The new value(s), shape depends on ``action_type`` (see module docstring).
    payload: dict[str, Any] = Field(default_factory=dict)
    # Snapshot of the position fields this action would overwrite, so the UI can
    # render a before/after diff and offer undo. Empty when nothing to show.
    before: dict[str, Any] = Field(default_factory=dict)
    # Model self-reported confidence in [0, 1], shown to the reviewer; at or
    # above 0.85 the review list preselects the proposal. It never applies
    # anything by itself. Clamped by the service; never trusted blindly.
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Grounding reference, e.g. {"code": "CWICR-...", "unit_rate": 185.0,
    # "currency": "EUR", "description": "..."} for the catalogue row the price
    # came from. None when the action cites no catalogue item.
    source: dict[str, Any] | None = None
    status: CopilotActionStatus = "needs_review"
    # Human-readable note for a failed apply (the exception summary). Empty
    # otherwise. Surfaced so the user knows why an accepted change did not take.
    error: str = ""


# Resolve the forward reference used in CopilotMessageOut.actions.
CopilotMessageOut.model_rebuild()


class CopilotChatRequest(BaseModel):
    """Request body for ``POST /positions/{position_id}/copilot/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=2000)


class CopilotChatResponse(BaseModel):
    """Response from a copilot chat turn.

    ``assistant_message`` is the persisted assistant turn (its ``actions`` carry
    the server-resolved per-action ``status``). ``actions`` is the same list
    hoisted to the top level for convenience so the client does not have to
    reach into the message.
    """

    assistant_message: CopilotMessageOut
    actions: list[CopilotActionProposal] = Field(default_factory=list)


class CopilotApplyRequest(BaseModel):
    """Request body for ``POST /positions/{position_id}/copilot/apply``.

    The client sends back a single action it previously received as a
    ``needs_review`` proposal; the service applies it via ``update_position``.
    """

    action: CopilotActionProposal


class CopilotApplyResponse(BaseModel):
    """Response from applying one copilot action.

    ``position`` is the updated position (reusing the canonical
    :class:`PositionResponse` shape so the client refreshes the row exactly as
    it would from any other position endpoint). ``action`` echoes the applied
    action with ``status='applied'`` (or ``'failed'`` with an ``error`` note).
    """

    position: PositionResponse
    action: CopilotActionProposal


class CopilotReviewRequest(BaseModel):
    """Request body for ``POST /positions/{position_id}/copilot/review``.

    Addresses proposals by their index in the stored assistant turn
    ``message_id``. The server applies the accepted ones from the payloads it
    stored with that turn and marks the rejected ones dismissed; indices left
    out of both lists stay pending.
    """

    message_id: UUID
    accept: list[int] = Field(default_factory=list, max_length=50)
    reject: list[int] = Field(default_factory=list, max_length=50)


class CopilotReviewResponse(BaseModel):
    """Response from reviewing one assistant turn.

    ``position`` is the position after every accepted proposal was applied (the
    client mirrors it in one step, so one undo reverts the whole review).
    ``message`` is the assistant turn with each proposal's new status:
    ``applied``, ``dismissed``, or ``failed`` with an ``error`` note.
    """

    position: PositionResponse
    message: CopilotMessageOut
