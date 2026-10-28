// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The decision dialog's own reading of the rules the server enforces on
// POST .../gates/{id}/decide, so the decider sees what is missing before the
// request instead of after it. The server stays the authority: it repeats
// every check and adds the blockers the client cannot see.

import type {
  ConditionInput,
  DecisionInput,
  EvidenceRef,
  GateArea,
  GateDetail,
  GovernanceGate,
  Outcome,
  Violation,
} from './api';
import type { KeyText } from './labels';

export interface ConditionDraft extends ConditionInput {
  /** Stable row id for React keys; never sent. */
  rowId: string;
}

export interface DecisionDraft {
  outcome: Outcome | null;
  rationale: string;
  conditions: ConditionDraft[];
  proceedAtRisk: string[];
  acceptedNotApplicable: string[];
  holdResumeDate: string;
  /** `evidenceKey` of each unknown evidence item the decider ticked. */
  acknowledged?: string[];
}

export type DecisionProblem =
  | 'outcome_required'
  | 'rationale_required'
  | 'conditions_required'
  | 'condition_text_required'
  | 'hold_needs_resume_date'
  | 'not_applicable_not_accepted'
  | 'evidence_not_acknowledged';

export const DECISION_PROBLEM: Record<DecisionProblem, KeyText> = {
  outcome_required: ['governance.project.decision.problem.outcome_required', 'Choose an outcome.'],
  rationale_required: [
    'governance.project.decision.problem.rationale_required',
    'Write down the reason. Every outcome other than go needs one on record.',
  ],
  conditions_required: [
    'governance.project.decision.problem.conditions_required',
    'A go with conditions needs at least one condition.',
  ],
  condition_text_required: [
    'governance.project.decision.problem.condition_text_required',
    'Every condition needs a text.',
  ],
  hold_needs_resume_date: [
    'governance.project.decision.problem.hold_needs_resume_date',
    'A hold needs a resume date after today.',
  ],
  not_applicable_not_accepted: [
    'governance.project.decision.problem.not_applicable_not_accepted',
    'Accept every area marked not applicable, or send the gate back.',
  ],
  evidence_not_acknowledged: [
    'governance.project.decision.problem.evidence_not_acknowledged',
    'Tick every evidence item listed for confirmation.',
  ],
};

/** Outcomes whose rationale the record must carry. Everything except a plain go. */
export function needsRationale(outcome: Outcome | null): boolean {
  return outcome !== null && outcome !== 'go';
}

/** Outcomes that let the gate pass, which are the ones that answer for unknown evidence. */
export function letsGatePass(outcome: Outcome | null): boolean {
  return outcome === 'go' || outcome === 'go_with_conditions';
}

/** One evidence item as a single string, for a set of ticked items. */
export function evidenceKey(ref: EvidenceRef): string {
  return [ref.area_code, ref.code].join(' ');
}

/**
 * The unknown evidence a passing decision has to name. This is the server's list
 * (`can.acknowledge`), not one worked out here from the evidence states.
 */
export function evidenceToAcknowledge(detail: GateDetail): NonNullable<GateDetail['can']['acknowledge']> {
  return detail.can.acknowledge ?? [];
}

/** Area codes that are not applicable on this gate, by area flag or by check. */
export function notApplicableAreas(detail: GateDetail): string[] {
  return detail.areas
    .filter((a) => !a.applicable || a.check?.status === 'not_applicable')
    .map((a) => a.code);
}

/**
 * The blocker codes a proceed-at-risk lifts. This is the server's set
 * (`PROCEED_AT_RISK_LIFTABLE` in evaluator.py), not a wider one: naming an area whose only
 * blocker is anything else, a stale check included, is refused with
 * `proceed_at_risk_area_not_blocking`.
 */
export const AT_RISK_LIFTABLE: readonly string[] = ['area_not_ready', 'evidence_not_met'];

/** Area codes whose readiness blocks the gate, which are the only ones a decider may name as proceeding at risk. */
export function atRiskCandidates(detail: GateDetail): string[] {
  const codes = new Set<string>();
  for (const b of detail.blockers) {
    if (b.area_code && AT_RISK_LIFTABLE.includes(b.code)) codes.add(b.area_code);
  }
  return [...codes];
}

export function decisionProblems(draft: DecisionDraft, detail: GateDetail, today: string): DecisionProblem[] {
  const problems: DecisionProblem[] = [];
  if (!draft.outcome) return ['outcome_required'];
  if (needsRationale(draft.outcome) && !draft.rationale.trim()) problems.push('rationale_required');
  if (draft.outcome === 'go_with_conditions') {
    if (draft.conditions.length === 0) problems.push('conditions_required');
    else if (draft.conditions.some((c) => !c.text.trim())) problems.push('condition_text_required');
  }
  if (draft.outcome === 'hold' && (!draft.holdResumeDate || draft.holdResumeDate <= today)) {
    problems.push('hold_needs_resume_date');
  }
  if (draft.outcome === 'go' || draft.outcome === 'go_with_conditions') {
    const accepted = new Set(draft.acceptedNotApplicable);
    if (notApplicableAreas(detail).some((code) => !accepted.has(code))) problems.push('not_applicable_not_accepted');
    const seen = new Set(draft.acknowledged ?? []);
    if (evidenceToAcknowledge(detail).some((ref) => !seen.has(evidenceKey(ref)))) {
      problems.push('evidence_not_acknowledged');
    }
  }
  return problems;
}

/**
 * A condition as the server takes it: empty fields as null and the text
 * trimmed. A document type without an area is dropped, because the server
 * matches a document only as the pair (area, document type).
 */
export function toConditionInput(c: ConditionInput): ConditionInput {
  const area = c.area_code || null;
  return {
    text: c.text.trim(),
    severity: c.severity,
    area_code: area,
    document_type: area ? c.document_type || null : null,
    owner_user_id: c.owner_user_id || null,
    due_date: c.due_date || null,
  };
}

/** A condition with nothing filled in yet. */
export function emptyCondition(): ConditionInput {
  return { text: '', severity: 'essential', area_code: '', document_type: '', owner_user_id: '', due_date: '' };
}

/** The frame document types of one area on this gate, which are the only ones a condition on that area may name. */
export function areaDocumentTypes(areas: GateArea[], areaCode: string | null | undefined): string[] {
  if (!areaCode) return [];
  const area = areas.find((a) => a.code === areaCode);
  return [...new Set((area?.documents ?? []).map((d) => d.doc_type))];
}

/** The gate's blockers that name a missing required frame document. */
export function documentBlockers(detail: GateDetail): Violation[] {
  return detail.blockers.filter(
    (b) => b.code === 'required_document_not_approved' && !!b.area_code && !!b.document_type,
  );
}

/** Whether a condition of the draft covers this missing document, by the pair the server matches on. */
export function coversDocument(conditions: ConditionInput[], blocker: Violation): boolean {
  return conditions.some(
    (c) => !!c.document_type && c.area_code === blocker.area_code && c.document_type === blocker.document_type,
  );
}

/** The condition that turns a missing required document into a go with conditions. */
export function conditionForDocument(blocker: Violation, text: string): ConditionInput {
  return { ...emptyCondition(), text, area_code: blocker.area_code ?? '', document_type: blocker.document_type ?? '' };
}

/**
 * Whether reopening a gate moves the project back to the phase before it.
 *
 * The server decides this, not the request: it rewinds exactly when the
 * reopened decision had advanced the phase (`reopen_rewinds_phase` in
 * evaluator.py). This mirrors it only to tell the reader beforehand.
 */
export function reopenRewind(gate: Pick<GovernanceGate, 'last_outcome'>): 'forced' | 'none' {
  return gate.last_outcome === 'go' || gate.last_outcome === 'go_with_conditions' ? 'forced' : 'none';
}

/** The day after an ISO date, for a date field that must lie in the future. */
export function dayAfter(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(day.getTime())) return isoDate;
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

/** A reopening is only accepted with a written reason. */
export function reopenProblem(rationale: string): 'rationale_required' | null {
  return rationale.trim() ? null : 'rationale_required';
}

/**
 * The request body for a draft that passed `decisionProblems`. The unknown evidence
 * goes along only on an outcome that lets the gate pass, and only the items the
 * server asked for and the decider ticked.
 */
export function toDecisionInput(draft: DecisionDraft, detail?: GateDetail): DecisionInput {
  const outcome = draft.outcome ?? 'go';
  const withConditions = outcome === 'go_with_conditions';
  const seen = new Set(draft.acknowledged ?? []);
  const named =
    detail && letsGatePass(outcome)
      ? evidenceToAcknowledge(detail)
          .filter((ref) => seen.has(evidenceKey(ref)))
          .map((ref) => ({ area_code: ref.area_code, code: ref.code }))
      : [];
  return {
    outcome,
    rationale: draft.rationale.trim(),
    conditions: withConditions ? draft.conditions.map(({ rowId: _rowId, ...c }) => toConditionInput(c)) : [],
    proceed_at_risk_areas: withConditions ? draft.proceedAtRisk : [],
    accepted_not_applicable: draft.acceptedNotApplicable,
    hold_resume_date: outcome === 'hold' ? draft.holdResumeDate : null,
    ...(named.length > 0 ? { acknowledged_evidence: named } : {}),
  };
}

/** Whether a waiver may be sent: the rationale is the whole of the rule the client can check. */
export function waiverProblem(rationale: string): 'waiver_needs_rationale' | null {
  return rationale.trim() ? null : 'waiver_needs_rationale';
}
