// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which action a record offers in which state, and what a form must carry
// before it is sent.
//
// The tables mirror backend/app/modules/quality_concept/fsm.py without the
// actions another module owns: approving a concept and reopening a binding one
// happen at the governance gate, releasing a stage at its hold gate, accepting a unit through the
// handover act. Those never get a button here. This is about state only; who
// may act is decided by the server, and its refusal is shown as it arrives.

import type {
  AcceptanceState,
  Capable,
  CertificationAction,
  CertificationState,
  ConceptState,
  CreditAction,
  CreditState,
  Proof,
  StageState,
  SurveyAction,
  SurveyState,
} from './api';

/**
 * Whether the server lets this reader take an action on a record. The flag
 * decides whenever the record carries one; `fallback` only stands in for a
 * record that came without flags.
 */
export function may(row: Capable | null | undefined, action: string, fallback = true): boolean {
  const can = row?.can;
  if (can && action in can) return can[action] === true;
  return fallback;
}

/** The code of the reason the server gives for a closed action, or null. */
export function whyNot(row: Capable | null | undefined, action: string): string | null {
  if (row?.can?.[action] !== false) return null;
  return row.can_reason?.[action] ?? null;
}

/** The distinct reasons the server gives for those of the named actions that are closed, in button order. */
export function closedReasons(row: Capable | null | undefined, actions: readonly string[]): string[] {
  const out: string[] = [];
  for (const action of actions) {
    const reason = whyNot(row, canKey(action));
    if (reason && !out.includes(reason)) out.push(reason);
  }
  return out;
}

/**
 * The reasons every row of a list gives for its own buttons. One row is not a
 * list: its reasons stay on the row.
 */
export function sharedReasons<T extends Capable>(rows: readonly T[], actionsOf: (row: T) => readonly string[]): string[] {
  if (rows.length < 2) return [];
  const [first, ...rest] = rows.map((row) => closedReasons(row, actionsOf(row)));
  return (first ?? []).filter((code) => rest.every((codes) => codes.includes(code)));
}

/** The buttons of a row that is only edited or removed. */
export const planRowActions = (): readonly string[] => ['edit', 'delete'];

/** The capability flag behind each button, where the two are not named alike. */
export const CAN_KEY: Record<string, string> = {
  approve_waiver: 'decide_waiver',
  reject_waiver: 'decide_waiver',
  pass: 'record_pass',
  fail: 'record_fail',
};

export function canKey(action: string): string {
  return CAN_KEY[action] ?? action;
}

export type ConceptAction = 'submit' | 'return';

export const CONCEPT_ACTIONS: Record<ConceptState, ConceptAction[]> = {
  draft: ['submit'],
  in_review: ['return'],
  approved: [],
  binding: [],
  revising: ['submit'],
};

/** A concept can be edited while it is a draft or under revision. */
export function conceptEditable(state: ConceptState): boolean {
  return state === 'draft' || state === 'revising';
}

export const CERTIFICATION_ACTIONS: Record<CertificationState, CertificationAction[]> = {
  planned: ['register', 'abandon'],
  registered: ['assess_design', 'assess_post_construction', 'abandon'],
  design_assessed: ['assess_post_construction', 'abandon'],
  post_construction_assessed: ['certify', 'miss_level', 'abandon'],
  certified: [],
  level_missed: [],
  abandoned: [],
};

export const CREDIT_ACTIONS: Record<CreditState, CreditAction[]> = {
  targeted: ['submit_evidence', 'drop'],
  evidence_submitted: ['achieve', 'not_achieve', 'return', 'drop'],
  achieved: [],
  not_achieved: ['submit_evidence'],
  dropped: ['reinstate'],
};

export type ProofAction = 'accept' | 'request_waiver' | 'approve_waiver' | 'reject_waiver' | 'reopen';

/**
 * What a proof offers. A waiver is a request first and a decision second, and
 * the request is visible as a rationale on a proof that has no decision yet.
 */
export function proofActions(proof: Pick<Proof, 'decision' | 'state' | 'requested_by' | 'decision_rationale'>): ProofAction[] {
  if (proof.decision !== 'none') return ['reopen'];
  const out: ProofAction[] = [];
  if (proof.state === 'delivered') out.push('accept');
  if (waiverPending(proof)) out.push('approve_waiver', 'reject_waiver');
  else out.push('request_waiver');
  return out;
}

export function waiverPending(proof: Pick<Proof, 'decision' | 'requested_by' | 'decision_rationale'>): boolean {
  return proof.decision === 'none' && !!proof.requested_by && proof.decision_rationale.trim().length > 0;
}

export type StageAction = 'open_test' | 'pass' | 'fail' | 'request_release' | 'not_applicable' | 'reinstate';

/** Read from the computed state: `blocked` and `ready` are recomputed from the preconditions on every read. */
export const STAGE_ACTIONS: Record<StageState, StageAction[]> = {
  blocked: ['not_applicable'],
  ready: ['open_test', 'not_applicable'],
  in_test: ['pass', 'fail', 'not_applicable'],
  failed: ['open_test'],
  passed: ['request_release', 'open_test'],
  released: ['open_test'],
  stale: ['request_release', 'open_test'],
  not_applicable: ['reinstate'],
};

/** Stage steps that change the plan rather than record progress; the server keeps them for a manager. */
export const PLAN_STAGE_ACTIONS: ReadonlySet<StageAction> = new Set<StageAction>(['not_applicable', 'reinstate']);

export type AcceptanceAction =
  | 'request'
  | 'schedule_inspection'
  | 'withdraw'
  | 'refuse'
  | 'confirm_deemed'
  | 'record_dates'
  | 'confirm_effects';

export const ACCEPTANCE_ACTIONS: Record<AcceptanceState, AcceptanceAction[]> = {
  planned: ['request', 'record_dates'],
  requested: ['schedule_inspection', 'refuse', 'withdraw', 'record_dates', 'confirm_deemed'],
  inspection_scheduled: ['refuse', 'record_dates', 'confirm_deemed'],
  refused: ['request'],
  accepted: ['confirm_effects'],
  accepted_with_reservations: ['confirm_effects'],
  deemed_accepted: ['confirm_effects'],
};

/** Unit steps anyone who may edit can record; every other step is kept for a manager. */
export const RECORDING_UNIT_ACTIONS: ReadonlySet<AcceptanceAction> = new Set<AcceptanceAction>([
  'request',
  'record_dates',
]);

/** An effect whose confirmation still holds; a revoked one is proposed again. */
export function effectInForce(effect: { outcome?: Record<string, unknown> | null }): boolean {
  return !effect.outcome?.revoked_at;
}

export function isAccepted(state: AcceptanceState): boolean {
  return state === 'accepted' || state === 'accepted_with_reservations' || state === 'deemed_accepted';
}

export const SURVEY_ACTIONS: Record<SurveyState, SurveyAction[]> = {
  planned: ['invite', 'record_survey', 'refuse_access'],
  invited: ['record_survey', 'refuse_access'],
  surveyed: ['issue_report'],
  report_issued: ['close'],
  closed: [],
  access_refused: ['close'],
};

/** Actions the server refuses without a written reason. */
export function needsRationale(
  machine: 'certification' | 'stage' | 'acceptance' | 'preservation',
  action: string,
): boolean {
  if (machine === 'certification') return action === 'abandon';
  if (machine === 'stage') return action === 'not_applicable';
  if (machine === 'acceptance') return action === 'refuse';
  return action === 'refuse_access';
}

/** A certification step that records the level the assessor granted. */
export function needsAchievedLevel(action: CertificationAction): boolean {
  return action === 'certify' || action === 'miss_level';
}

/**
 * Points as the server wants them: a plain non-negative decimal written with a
 * dot. Returns the cleaned string, or null when the text is not such a number.
 * A comma is read as the decimal mark, because that is how half of the readers
 * type it; anything else (a thousands separator, a sign, an exponent) is refused
 * rather than guessed.
 */
export function pointsString(text: string): string | null {
  const s = text.trim().replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  return s;
}

/** Split a free text field into its non-empty lines, for lists the reader types one per line. */
export function lines(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

export interface PackageDraft {
  ref: string;
  code: string;
  title: string;
  no_proofs_rationale: string;
}

export type PackageProblem = 'ref_required' | 'ref_duplicate';

/** The first thing wrong with a package scope, or null. Rows the reader left fully empty are ignored. */
export function packageScopeProblem(rows: PackageDraft[]): PackageProblem | null {
  const seen = new Set<string>();
  for (const row of filledPackages(rows)) {
    const ref = row.ref.trim();
    if (!ref) return 'ref_required';
    if (seen.has(ref)) return 'ref_duplicate';
    seen.add(ref);
  }
  return null;
}

export function filledPackages(rows: PackageDraft[]): PackageDraft[] {
  return rows
    .filter((r) => r.ref.trim() || r.code.trim() || r.title.trim() || r.no_proofs_rationale.trim())
    .map((r) => ({
      ref: r.ref.trim(),
      code: r.code.trim(),
      title: r.title.trim(),
      no_proofs_rationale: r.no_proofs_rationale.trim(),
    }));
}

/**
 * A precondition that could not be read and therefore does not block: the
 * server reports it as met and flags it, and the screen must not show it as passed.
 */
export function preconditionNotApplicable(pre: { met: boolean; params: Record<string, unknown> }): boolean {
  return pre.met && pre.params.not_applicable === true;
}

/**
 * A reference to a record of another module goes into a request only when the
 * reader changed it, so a stored reference the reader cannot list is never
 * sent back. An emptied field is sent as null, which clears it.
 */
export function refChange<K extends string>(
  field: K,
  before: string | null | undefined,
  now: string,
): Partial<Record<K, string | null>> {
  if ((before ?? '') === now) return {};
  return { [field]: now || null } as Partial<Record<K, string | null>>;
}

/** Share of a whole as a number between 0 and 100, safe for an empty whole. */
export function percent(done: number, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}
