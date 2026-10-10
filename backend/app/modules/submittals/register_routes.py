# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Register header routes for submittals: the counts and the vocabularies.

    GET /summary/      - Counts above the register for one project
    GET /vocabulary/   - Types, disciplines and outcome codes with labels

Both are static paths, so the module router includes :data:`register_router`
before its ``/{submittal_id}`` routes, like the export router.

The summary answers what a project manager asks of the register each week:
how many are with the reviewer and how many of those are past the contract's
review period, which long-lead items are still not approved, and which have
already passed the date their approval was needed by. A count that cannot be
worked out (no review period recorded) is reported as unknown, in its own
figure, instead of being folded into "not overdue".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.core.register_context import AcceptLanguageHeader, LocaleQuery
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.submittals.pdf_translations import CATALOGUE, resolve_pdf_locale
from app.modules.submittals.schemas import (
    SUBMITTAL_SORT_FIELDS,
    SUBMITTAL_TYPES,
    SubmittalCodeCount,
    SubmittalOutcomeCount,
    SubmittalRegisterSummary,
    SubmittalVocabulary,
    SubmittalVocabularyEntry,
)
from app.modules.submittals.service import SubmittalService
from app.modules.submittals.tracking import DEFAULT_REVIEW_CODES, DISCIPLINES, REVIEW_OUTCOMES

register_router = APIRouter()


def _counts(tally: dict[str, int]) -> list[SubmittalCodeCount]:
    return [SubmittalCodeCount(code=code, count=count) for code, count in tally.items()]


@register_router.get(
    "/summary/",
    response_model=SubmittalRegisterSummary,
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def get_register_summary(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> SubmittalRegisterSummary:
    """Counts above a project's submittal register, as of today."""
    await verify_project_access(project_id, user_id, session)
    data = await SubmittalService(session).register_summary(project_id)
    return SubmittalRegisterSummary(
        project_id=project_id,
        as_of=data["as_of"],
        total=data["total"],
        by_status=_counts(data["by_status"]),
        by_type=_counts(data["by_type"]),
        by_discipline=_counts(data["by_discipline"]),
        by_outcome=[
            SubmittalOutcomeCount(code=code, count=count, review_code=DEFAULT_REVIEW_CODES.get(code))
            for code, count in data["by_outcome"].items()
        ],
        awaiting_review=data["awaiting_review"],
        review_overdue=data["review_overdue"],
        review_period_unknown=data["review_period_unknown"],
        long_lead=data["long_lead"],
        long_lead_awaiting_approval=data["long_lead_awaiting_approval"],
        approval_late=data["approval_late"],
        long_lead_without_lead_time=data["long_lead_without_lead_time"],
    )


@register_router.get(
    "/vocabulary/",
    response_model=SubmittalVocabulary,
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def get_vocabulary(
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> SubmittalVocabulary:
    """The codes the submittal pickers offer, labelled in the request language.

    The discipline list is the default one. The field accepts any lower-case
    code, so a client may offer these and still let a project type its own.
    English and Turkish labels exist; any other language reads the English.
    """
    language = resolve_pdf_locale(locale, accept_language)
    return SubmittalVocabulary(
        locale=language,
        types=[
            SubmittalVocabularyEntry(code=code, label=CATALOGUE.label("type", code, language))
            for code in SUBMITTAL_TYPES
        ],
        disciplines=[
            SubmittalVocabularyEntry(
                code=item.code, label=CATALOGUE.label("discipline", item.code, language), short_code=item.short
            )
            for item in DISCIPLINES
        ],
        outcomes=[
            SubmittalVocabularyEntry(
                code=code, label=CATALOGUE.label("status", code, language), short_code=DEFAULT_REVIEW_CODES[code]
            )
            for code in REVIEW_OUTCOMES
        ],
        sort_fields=list(SUBMITTAL_SORT_FIELDS),
    )
