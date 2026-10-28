# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Change-intelligence API routes (auto-mounted at /api/v1/change-intelligence).

Access control mirrors every other project-scoped router: the caller must be
authenticated and pass :func:`verify_project_access` for the requested project
(owner / team-member / admin), which 404s on both "missing" and "denied" so it
never leaks project existence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.change_intelligence.schemas import (
    ChangeDriverAnalyticsOut,
    ChangeRunRateOut,
    ChangeWatchOut,
    ClarifiedRequestOut,
    ClarifyIn,
    CommitmentOut,
    CommitmentRegisterOut,
    CommsDigestOut,
    CoordinationPlanOut,
    CoordinationStepOut,
    CurrencyExposureOut,
    CurrencyImpactOut,
    CurrencyTotalOut,
    CycleTimeBoardOut,
    DecisionImpactOut,
    DecisionImpactRowOut,
    DelayRiskBoardOut,
    DelayRiskFactorOut,
    DelayRiskItemOut,
    DisputeExposureSummaryOut,
    DisputeRiskBoardOut,
    DisputeRiskItemOut,
    DriverCurrencyOut,
    DriverTrendPointOut,
    ImpactProjectionOut,
    IntakeDraftOut,
    IntakePreviewIn,
    IntakePreviewOut,
    IntakeProfileOut,
    IntakeProfilesOut,
    ItemAgingOut,
    KindImpactOut,
    NoticeClockOut,
    NoticeRegisterOut,
    NoticeRegisterSummaryOut,
    OwnerLoadOut,
    OwnershipChainOut,
    OwnershipSegmentOut,
    ParetoRowOut,
    PartyDwellOut,
    PartyLoadOut,
    RiskFactorOut,
    RunRateForecastOut,
    RunRatePointOut,
    ScopeAmbiguityLineOut,
    ScopeAmbiguityReportOut,
    ThreadDigestOut,
    WatchResultOut,
)
from app.modules.change_intelligence.scope_service import assess_project_scope
from app.modules.change_intelligence.service import (
    build_change_drivers,
    build_change_run_rate,
    build_change_watch,
    build_commitment_register,
    build_comms_digest_for_project,
    build_coordination_plan,
    build_decision_impact,
    build_delay_risk_board,
    build_dispute_risk_board,
    build_impact_projection,
    build_ownership_chain_for,
    build_project_board,
    clarify_change_note,
    intake_canonical_fields,
    list_intake_profiles,
    preview_intake,
)
from app.modules.change_intelligence.time_bar import DEFAULT_DUE_SOON_DAYS
from app.modules.change_intelligence.time_bar_service import build_notice_register

router = APIRouter(tags=["Change Intelligence"])


@router.get(
    "/projects/{project_id}/cycle-time",
    response_model=CycleTimeBoardOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_cycle_time_board(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> CycleTimeBoardOut:
    """Per-party "waiting on whom" board over a project's open change records."""
    await verify_project_access(project_id, user_id or "", session)

    board = await build_project_board(session, project_id)
    return CycleTimeBoardOut(
        project_id=str(project_id),
        as_of=board.as_of,
        total_open=board.total_open,
        total_overdue=board.total_overdue,
        unassigned_open=board.unassigned_open,
        parties=[PartyLoadOut.model_validate(p) for p in board.parties],
        items=[ItemAgingOut.model_validate(r) for r in board.items],
    )


@router.get(
    "/projects/{project_id}/impact",
    response_model=ImpactProjectionOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_impact_projection(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ImpactProjectionOut:
    """Committed cost and schedule impact of a project's approved changes."""
    await verify_project_access(project_id, user_id or "", session)

    projection = await build_impact_projection(session, project_id)
    return ImpactProjectionOut(
        project_id=str(project_id),
        approved_count=projection.approved_count,
        total_schedule_delta_days=projection.total_schedule_delta_days,
        primary_currency=projection.primary_currency,
        primary_currency_cost=str(projection.primary_currency_cost),
        by_kind=[
            KindImpactOut(
                kind=k.kind,
                count=k.count,
                total_cost=str(k.total_cost),
                total_days=k.total_days,
            )
            for k in projection.by_kind
        ],
        by_currency=[
            CurrencyImpactOut(currency=c.currency, total_cost=str(c.total_cost), count=c.count)
            for c in projection.by_currency
        ],
    )


@router.post(
    "/clarify",
    response_model=ClarifiedRequestOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def clarify_change_request(
    payload: ClarifyIn,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ClarifiedRequestOut:
    """Turn a rough change note into a structured, well-formed request draft.

    Stateless text analysis (no project record is read or written), so it needs
    authentication but no project-scoped access check.
    """
    clarified = clarify_change_note(payload.note, payload.contract_standard)
    return ClarifiedRequestOut.model_validate(clarified)


@router.get(
    "/projects/{project_id}/coordination",
    response_model=CoordinationPlanOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_coordination_plan(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> CoordinationPlanOut:
    """Ranked "what to act on first" plan over the project's open change items."""
    await verify_project_access(project_id, user_id or "", session)

    plan = await build_coordination_plan(session, project_id)
    return CoordinationPlanOut(
        project_id=str(project_id),
        generated_at=plan.generated_at,
        total=plan.total,
        overdue_count=plan.overdue_count,
        due_soon_count=plan.due_soon_count,
        steps=[CoordinationStepOut.model_validate(s) for s in plan.steps],
    )


@router.get(
    "/projects/{project_id}/comms-digest",
    response_model=CommsDigestOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_comms_digest(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> CommsDigestOut:
    """Open correspondence threads for the project and who owes the next reply."""
    await verify_project_access(project_id, user_id or "", session)

    digest = await build_comms_digest_for_project(session, project_id)
    return CommsDigestOut(
        project_id=str(project_id),
        generated_at=digest.generated_at,
        thread_count=digest.thread_count,
        open_count=digest.open_count,
        awaiting_us_count=digest.awaiting_us_count,
        threads=[ThreadDigestOut.model_validate(t) for t in digest.threads],
    )


@router.get(
    "/changes/{kind}/{entity_id}/ownership-chain",
    response_model=OwnershipChainOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_ownership_chain(
    kind: str,
    entity_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> OwnershipChainOut:
    """Reconstructed ball-in-court hand-off chain + dwell-time for one change.

    ``kind`` is the change-family token (``change_order`` / ``variation_notice``
    / ``variation_request`` / ``variation_order`` / ``moc_entry``). The record's
    project drives :func:`verify_project_access`, so the chain is only returned
    to a caller who may see the underlying change. An unknown kind or a missing
    record both 404, consistent with the rest of the project-scoped surface.
    """
    try:
        chain, project_id = await build_ownership_chain_for(session, kind, entity_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Unknown change kind '{kind}'. Use one of: change_order, "
                "variation_notice, variation_request, variation_order, moc_entry."
            ),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No change of that kind and id was found in a project you can access. Check the id and try again.",
        ) from exc

    await verify_project_access(project_id, user_id or "", session)

    return OwnershipChainOut(
        kind=kind,
        entity_id=str(entity_id),
        project_id=str(project_id),
        as_of=chain.as_of.isoformat(),
        current_holder=chain.current_holder,
        ownership_ambiguous=chain.ownership_ambiguous,
        has_current_holder=chain.has_current_holder,
        has_unrecorded_origin=chain.has_unrecorded_origin,
        chain_inconsistent=chain.chain_inconsistent,
        unchanged_across_transition=chain.unchanged_across_transition,
        total_handoffs=chain.total_handoffs,
        ambiguity_reasons=list(chain.ambiguity_reasons),
        segments=[
            OwnershipSegmentOut(
                party=seg.party,
                from_ts=seg.from_ts.isoformat(),
                to_ts=seg.to_ts.isoformat() if seg.to_ts is not None else None,
                dwell_days=seg.dwell_days,
                is_open=seg.is_open,
                set_by=seg.set_by,
                reason=seg.reason,
            )
            for seg in chain.segments
        ],
        dwell_by_party=[
            PartyDwellOut(party=pd.party, dwell_days=pd.dwell_days, segment_count=pd.segment_count)
            for pd in chain.dwell_by_party
        ],
    )


@router.get(
    "/projects/{project_id}/dispute-risk",
    response_model=DisputeRiskBoardOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_dispute_risk_board(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> DisputeRiskBoardOut:
    """Ranked dispute-exposure radar over the project's open changes.

    Each open change is scored for how likely it is to turn into a dispute, why
    (its dominant driver), and the single most useful cure, money-weighted by
    the cost at risk. The per-currency summary never blends currencies.
    """
    await verify_project_access(project_id, user_id or "", session)

    ranked, summary = await build_dispute_risk_board(session, project_id)
    return DisputeRiskBoardOut(
        project_id=str(project_id),
        generated_at=datetime.now(UTC).isoformat(),
        items=[
            DisputeRiskItemOut(
                change_id=it.change_id,
                change_ref=it.change_ref,
                kind=it.kind,
                title=it.title,
                exposure_score=it.exposure_score,
                band=it.band,
                dominant_driver=it.dominant_driver,
                recommended_cure=it.recommended_cure,
                intrinsic_exposure=it.intrinsic_exposure,
                money_multiplier=it.money_multiplier,
                money_basis=str(it.money_basis),
                currency=it.currency,
                factors=[
                    RiskFactorOut(
                        name=f.name,
                        weight=f.weight,
                        fraction=f.fraction,
                        weighted=f.weighted,
                        is_driver=f.is_driver,
                    )
                    for f in it.factors
                ],
            )
            for it in ranked
        ],
        summary=DisputeExposureSummaryOut(
            item_count=summary.item_count,
            band_counts=summary.band_counts,
            by_currency=[
                CurrencyExposureOut(
                    currency=c.currency,
                    item_count=c.item_count,
                    money_basis_total=str(c.money_basis_total),
                    exposure_weighted_amount=str(c.exposure_weighted_amount),
                )
                for c in summary.by_currency
            ],
            top_driver_counts=summary.top_driver_counts,
        ),
    )


@router.get(
    "/decision-impact",
    response_model=DecisionImpactOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_decision_impact(
    project_id: uuid.UUID,
    candidate_change_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> DecisionImpactOut:
    """Preview what approving one candidate change adds to the committed baseline.

    Gathers the project's committed change-order and variation-order impacts as
    the baseline, resolves the candidate change by id from any change-family
    table, and returns the before / after position per (kind, currency) plus a
    per-currency rollup. Every money / day figure is a string and currencies are
    never blended. A candidate id not found in the project 404s.
    """
    await verify_project_access(project_id, user_id or "", session)

    try:
        impact, candidate = await build_decision_impact(session, project_id, candidate_change_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate change not found in this project. Check the change id belongs to this project.",
        ) from exc

    return DecisionImpactOut(
        project_id=str(project_id),
        candidate_change_id=str(candidate_change_id),
        candidate_kind=candidate.kind,
        candidate_currency=candidate.currency,
        rows=[
            DecisionImpactRowOut(
                kind=r.kind,
                currency=r.currency,
                current_committed_cost=str(r.current_committed_cost),
                candidate_cost_delta=str(r.candidate_cost_delta),
                resulting_cost=str(r.resulting_cost),
                current_committed_days=str(r.current_committed_days),
                candidate_days_delta=str(r.candidate_days_delta),
                resulting_days=str(r.resulting_days),
            )
            for r in impact.rows
        ],
        totals_by_currency=[
            CurrencyTotalOut(
                currency=t.currency,
                current_committed_cost=str(t.current_committed_cost),
                candidate_cost_delta=str(t.candidate_cost_delta),
                resulting_cost=str(t.resulting_cost),
                current_committed_days=str(t.current_committed_days),
                candidate_days_delta=str(t.candidate_days_delta),
                resulting_days=str(t.resulting_days),
            )
            for t in impact.totals_by_currency
        ],
    )


@router.get(
    "/projects/{project_id}/change-watch",
    response_model=ChangeWatchOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_change_watch(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ChangeWatchOut:
    """Proactive watch: which open changes are quietly drifting toward trouble.

    Classifies each change as stalled / incomplete / lost (or ok) from its age,
    movement and ownership, worst-first, with a per-class count.
    """
    await verify_project_access(project_id, user_id or "", session)

    watch = await build_change_watch(session, project_id)
    return ChangeWatchOut(
        project_id=str(project_id),
        generated_at=datetime.now(UTC).isoformat(),
        item_count=watch.item_count,
        counts=watch.counts,
        items=[
            WatchResultOut(
                change_id=r.change_id,
                kind=r.kind,
                classification=r.classification,
                reasons=list(r.reasons),
                idle_days=r.idle_days,
                overdue_days=r.overdue_days,
            )
            for r in watch.items
        ],
    )


@router.get(
    "/projects/{project_id}/intake/profiles",
    response_model=IntakeProfilesOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_intake_profiles(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> IntakeProfilesOut:
    """List the intake mapping profiles a foreign change record can be read with.

    Built-in presets today (a generic tracker-spreadsheet dialect and a generic
    email-intake-form dialect). The list is project-scoped so per-project custom
    profiles can extend it later without changing the contract.
    """
    await verify_project_access(project_id, user_id or "", session)
    canonical = intake_canonical_fields()
    return IntakeProfilesOut(
        project_id=str(project_id),
        profiles=[
            IntakeProfileOut(
                profile_name=p.profile_name,
                required_fields=list(p.required_fields),
                canonical_fields=canonical,
                field_alias_count=len(p.field_aliases),
                unit_synonym_count=len(p.unit_synonyms),
                value_synonym_count=len(p.value_synonyms),
            )
            for p in list_intake_profiles()
        ],
    )


@router.post(
    "/projects/{project_id}/intake/preview",
    response_model=IntakePreviewOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def preview_intake_record(
    project_id: uuid.UUID,
    payload: IntakePreviewIn,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> IntakePreviewOut:
    """Normalize one foreign change-request record and show how it maps.

    Stateless preview: the foreign record is read with the selected profile and
    the canonical draft is returned with its diagnostics (unmapped columns,
    missing required fields, parse warnings, completeness). Nothing is persisted.
    An unknown profile name 404s.
    """
    await verify_project_access(project_id, user_id or "", session)
    try:
        result = preview_intake(payload.profile_name, payload.record)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Unknown intake profile '{payload.profile_name}'. Call the intake "
                "profiles endpoint for this project to see the available profile names."
            ),
        ) from exc

    draft = result.draft
    return IntakePreviewOut(
        project_id=str(project_id),
        profile_name=payload.profile_name,
        draft=IntakeDraftOut(
            title=draft.title,
            description=draft.description,
            cost_impact=str(draft.cost_impact) if draft.cost_impact is not None else None,
            currency=draft.currency,
            schedule_impact_days=(str(draft.schedule_impact_days) if draft.schedule_impact_days is not None else None),
            requested_by=draft.requested_by,
            source_ref=draft.source_ref,
        ),
        unmapped_fields=list(result.unmapped_fields),
        missing_required=list(result.missing_required),
        warnings=list(result.warnings),
        completeness=result.completeness,
    )


@router.get(
    "/projects/{project_id}/delay-risk",
    response_model=DelayRiskBoardOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_delay_risk_board(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> DelayRiskBoardOut:
    """Rank the project's open changes by how likely they are to overrun.

    Each open change is graded into a [0, 1] risk and a low / elevated / high
    band from its dwell against its response window, its holder's overdue rate
    and open load, and its size against the contract, with the ranked factor
    contributions so a row shows why it is at risk. Highest risk first.
    """
    await verify_project_access(project_id, user_id or "", session)

    ranked, items_by_id = await build_delay_risk_board(session, project_id)
    band_counts: dict[str, int] = {"low": 0, "elevated": 0, "high": 0}
    items: list[DelayRiskItemOut] = []
    for result in ranked:
        band_counts[result.band] = band_counts.get(result.band, 0) + 1
        aging = items_by_id.get(result.change_id)
        items.append(
            DelayRiskItemOut(
                change_id=result.change_id,
                change_ref=aging.code if aging is not None else "",
                kind=aging.kind if aging is not None else "",
                title=aging.title if aging is not None else "",
                party=aging.party if aging is not None else "",
                risk=result.risk,
                band=result.band,
                age_days=aging.age_days if aging is not None else 0.0,
                overdue=aging.overdue if aging is not None else False,
                days_to_due=aging.days_to_due if aging is not None else None,
                top_factors=[
                    DelayRiskFactorOut(name=f.name, value=f.value, contribution=f.contribution)
                    for f in result.top_factors
                ],
            )
        )
    return DelayRiskBoardOut(
        project_id=str(project_id),
        generated_at=datetime.now(UTC).isoformat(),
        item_count=len(items),
        band_counts=band_counts,
        items=items,
    )


@router.get(
    "/projects/{project_id}/scope-ambiguity",
    response_model=ScopeAmbiguityReportOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_scope_ambiguity(
    project_id: uuid.UUID,
    session: SessionDep,
    boq_id: uuid.UUID | None = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ScopeAmbiguityReportOut:
    """Grade how vague each BOQ line's scope is, worst-first, before it is priced.

    Reads the project's bill-of-quantities lines (optionally a single bill via
    ``boq_id``) and scores each for the tell-tale signals of a downstream
    variation - a provisional sum or allowance, vague placeholder wording, a
    missing quantity or unit, an under-specified description - returning the
    ranked lines, a per-band count, the project ambiguity index and the dominant
    reasons. A section heading (a line that is a parent of other lines) is exempt
    from the quantity / unit / under-specification signals. Read-only; a
    ``boq_id`` from another project resolves to no rows rather than leaking it.
    """
    await verify_project_access(project_id, user_id or "", session)

    report = await assess_project_scope(session, project_id=project_id, boq_id=boq_id)
    return ScopeAmbiguityReportOut(
        project_id=str(project_id),
        boq_id=str(boq_id) if boq_id is not None else None,
        line_count=len(report.lines),
        ambiguity_index=report.ambiguity_index,
        counts_by_band=report.counts_by_band,
        top_reasons=list(report.top_reasons),
        lines=[ScopeAmbiguityLineOut.model_validate(line) for line in report.lines],
    )


@router.get(
    "/projects/{project_id}/notice-register",
    response_model=NoticeRegisterOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_notice_register(
    project_id: uuid.UUID,
    session: SessionDep,
    standard: str | None = None,
    due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> NoticeRegisterOut:
    """Contractual notice and time-bar register for a project's open changes.

    Derives every open notice / response clock from the event date already on
    each change order, variation notice / request, and extension-of-time claim,
    adds the notice period for the project's contract standard (an optional
    ``standard`` override wins), and classifies each clock met / upcoming /
    due-soon / overdue. Required notices (a claim notice, an EOT notice) are
    checked against correspondence for proof on file; a required notice with none
    on file, or a lapsed bar, is flagged so an entitlement is not quietly lost.
    Read-only and worst-first. ``due_soon_days`` sets the amber window (clamped to
    1..90).
    """
    await verify_project_access(project_id, user_id or "", session)

    window = max(1, min(due_soon_days, 90))
    register = await build_notice_register(
        session,
        project_id,
        standard_override=standard,
        due_soon_days=window,
    )
    return NoticeRegisterOut(
        project_id=register.project_id,
        contract_standard=register.contract_standard,
        generated_at=register.generated_at.isoformat(),
        due_soon_days=register.due_soon_days,
        clocks=[
            NoticeClockOut(
                source_kind=c.source_kind,
                source_id=c.source_id,
                source_ref=c.source_ref,
                title=c.title,
                standard=c.standard,
                notice_type=c.notice_type,
                clause_ref=c.clause_ref,
                trigger_date=c.trigger_date.isoformat() if c.trigger_date is not None else None,
                period_days=c.period_days,
                day_basis=c.day_basis,
                deadline=c.deadline.isoformat() if c.deadline is not None else None,
                days_remaining=c.days_remaining,
                status=c.status,
                requires_notice=c.requires_notice,
                proof_on_file=c.proof_on_file,
                satisfied_at=c.satisfied_at.isoformat() if c.satisfied_at is not None else None,
                served_late=c.served_late,
                entitlement_at_risk=c.entitlement_at_risk,
                is_open=c.is_open,
            )
            for c in register.clocks
        ],
        summary=NoticeRegisterSummaryOut(
            total=register.summary.total,
            open_total=register.summary.open_total,
            counts_by_status=register.summary.counts_by_status,
            at_risk=register.summary.at_risk,
            proof_missing=register.summary.proof_missing,
            overdue=register.summary.overdue,
            due_soon=register.summary.due_soon,
        ),
    )


@router.get(
    "/projects/{project_id}/commitments",
    response_model=CommitmentRegisterOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_commitment_register(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> CommitmentRegisterOut:
    """Owner-ranked, overdue-first register of open commitments across sources.

    Consolidates meeting action items, risk mitigation actions, open change
    orders, and RFIs / submittals awaiting a response into one owe-list, ranked
    overdue-first, with per-owner load and per-source counts.
    """
    await verify_project_access(project_id, user_id or "", session)

    register = await build_commitment_register(session, project_id)
    return CommitmentRegisterOut(
        project_id=str(project_id),
        generated_at=register.generated_at,
        total_open=register.total_open,
        overdue_count=register.overdue_count,
        by_owner=[OwnerLoadOut.model_validate(o) for o in register.by_owner],
        by_source=register.by_source,
        items=[CommitmentOut.model_validate(c) for c in register.items],
    )


@router.get(
    "/projects/{project_id}/change-drivers",
    response_model=ChangeDriverAnalyticsOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_change_drivers(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ChangeDriverAnalyticsOut:
    """Pareto of change cost and count by originating cause and responsible party.

    Aggregates the project's change orders (by reason category), disruption and
    extension-of-time claims (by root cause) and risk-register entries (by
    category) into a cost-ranked Pareto with a running cumulative percentage,
    the same rolled up by responsible party, a per-currency split, and a
    month-over-month trend. Money is a string; currencies are never blended.
    """
    await verify_project_access(project_id, user_id or "", session)

    analytics = await build_change_drivers(session, project_id)
    return ChangeDriverAnalyticsOut(
        project_id=str(project_id),
        total_count=analytics.total_count,
        total_cost=str(analytics.total_cost),
        primary_currency=analytics.primary_currency,
        by_cause=[
            ParetoRowOut(
                key=r.key,
                count=r.count,
                cost=str(r.cost),
                cost_pct=r.cost_pct,
                cumulative_pct=r.cumulative_pct,
            )
            for r in analytics.by_cause
        ],
        by_party=[
            ParetoRowOut(
                key=r.key,
                count=r.count,
                cost=str(r.cost),
                cost_pct=r.cost_pct,
                cumulative_pct=r.cumulative_pct,
            )
            for r in analytics.by_party
        ],
        by_currency=[
            DriverCurrencyOut(currency=c.currency, count=c.count, cost=str(c.cost)) for c in analytics.by_currency
        ],
        trend=[DriverTrendPointOut(month=t.month, count=t.count, cost=str(t.cost)) for t in analytics.trend],
    )


@router.get(
    "/projects/{project_id}/run-rate",
    response_model=ChangeRunRateOut,
    dependencies=[Depends(RequirePermission("change_intelligence.read"))],
)
async def get_change_run_rate(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ChangeRunRateOut:
    """Cumulative change value over time vs contract, intake rate and forecast.

    Places every change order and variation on the timeline, tracks the
    cumulative approved-plus-pending change value month by month against the
    original contract value, reports the intake rate (changes per month) and a
    simple linear burn-rate forecast of the final change percentage at
    completion. Every money and percentage figure is a string.
    """
    await verify_project_access(project_id, user_id or "", session)

    run_rate = await build_change_run_rate(session, project_id)
    forecast = None
    if run_rate.forecast is not None:
        fc = run_rate.forecast
        forecast = RunRateForecastOut(
            method=fc.method,
            elapsed_days=fc.elapsed_days,
            total_days=fc.total_days,
            rate_per_day=str(fc.rate_per_day),
            final_change_value=str(fc.final_change_value),
            final_change_pct=str(fc.final_change_pct) if fc.final_change_pct is not None else None,
            at_date=fc.at_date,
        )
    return ChangeRunRateOut(
        project_id=str(project_id),
        original_contract_value=(
            str(run_rate.original_contract_value) if run_rate.original_contract_value is not None else None
        ),
        currency=run_rate.currency,
        change_count=run_rate.change_count,
        approved_value=str(run_rate.approved_value),
        pending_value=str(run_rate.pending_value),
        total_change_value=str(run_rate.total_change_value),
        current_change_pct=str(run_rate.current_change_pct) if run_rate.current_change_pct is not None else None,
        intake_rate_per_month=run_rate.intake_rate_per_month,
        points=[
            RunRatePointOut(
                month=p.month,
                approved_value=str(p.approved_value),
                pending_value=str(p.pending_value),
                cumulative_value=str(p.cumulative_value),
                change_pct=str(p.change_pct) if p.change_pct is not None else None,
            )
            for p in run_rate.points
        ],
        forecast=forecast,
    )
