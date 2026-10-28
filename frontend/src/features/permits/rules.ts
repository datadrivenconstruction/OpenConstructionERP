// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The rules the permit screens apply before they send anything: how the
// roadmap rows are put together, what a decision or a condition must carry,
// and which step a record's state leaves open.
//
// Who may act is the server's answer: a record carries `can` flags and a
// button follows them (`gate`). The state rules below are the fallback for
// a record served without flags; they mirror backend/app/modules/permits
// fsm.py and guards.py, and the server repeats every one of them.

import type {
  Application,
  ApplicationDetail,
  ApplicationTarget,
  CanFlag,
  Clock,
  ClockEventInput,
  ClockEventKind,
  ClockUnit,
  Condition,
  ConditionInput,
  ConditionKind,
  ConditionPurpose,
  ConditionRow,
  ConditionView,
  DecisionInput,
  DischargeMode,
  Outcome,
  Permit,
  PermitTarget,
  RequirementRow,
  TimelineRow,
  Topic,
  Trigger,
} from './api';
import type { KeyText } from './labels';

/**
 * Only the fields the reader changed, compared with the record as loaded.
 *
 * The PATCH routes write every field they are sent, so an untouched field
 * must not travel: an empty value sent for it would clear what is stored,
 * and a condition's text is refused outright once the condition has moved on.
 */
export function changedOnly<T extends object>(before: object, draft: T): Partial<T> {
  const was = before as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(draft)) {
    if ((was[key] ?? null) !== (value ?? null)) out[key] = value;
  }
  return out as Partial<T>;
}

/* ── Roadmap rows ─────────────────────────────────────────────────────── */

export interface RoadmapRow {
  requirement: RequirementRow;
  timeline: TimelineRow | null;
  /** The newest attempt, which is the one the state and the clock speak about. */
  application: Application | null;
  applications: Application[];
}

/** Join the three lists the roadmap is read from into one row per requirement, in roadmap order. */
export function buildRoadmapRows(
  requirements: RequirementRow[],
  timeline: TimelineRow[],
  applications: Application[],
): RoadmapRow[] {
  const byReq = new Map<string, TimelineRow>();
  for (const row of timeline) byReq.set(row.requirement_id, row);
  const apps = new Map<string, Application[]>();
  for (const a of applications) {
    const list = apps.get(a.requirement_id) ?? [];
    list.push(a);
    apps.set(a.requirement_id, list);
  }
  return [...requirements]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((requirement) => {
      const own = [...(apps.get(requirement.id) ?? [])].sort((a, b) => b.attempt - a.attempt);
      return {
        requirement,
        timeline: byReq.get(requirement.id) ?? null,
        application: own[0] ?? null,
        applications: own,
      };
    });
}

export interface RoadmapSummary {
  total: number;
  granted: number;
  inProgress: number;
  conflicts: number;
}

export function summariseRoadmap(rows: RoadmapRow[]): RoadmapSummary {
  const live = rows.filter((r) => r.requirement.applicable);
  return {
    total: live.length,
    granted: live.filter((r) => r.requirement.state === 'granted' || r.requirement.state === 'partially_granted')
      .length,
    inProgress: live.filter((r) => r.requirement.state === 'in_progress').length,
    conflicts: live.filter((r) => r.timeline?.schedule_conflict && !r.timeline.conflict_accepted).length,
  };
}

const OPEN_APPLICATION = new Set(['planned', 'preparing', 'internal_review', 'submitted', 'validated', 'under_review', 'info_requested']);
const DECIDABLE = new Set(['submitted', 'validated', 'under_review', 'info_requested']);

export function isOpenApplication(a: Pick<Application, 'state'>): boolean {
  return OPEN_APPLICATION.has(a.state);
}

/** A decision is recorded on a filed application only. */
export function isDecidable(a: Pick<Application, 'state'>): boolean {
  return DECIDABLE.has(a.state);
}

const STEP_ORDER: ApplicationTarget[] = ['preparing', 'internal_review', 'submitted', 'validated', 'under_review', 'info_requested'];

export interface ApplicationSteps {
  /** The moves the server allows, in the order the work runs, without the withdrawal. */
  steps: ApplicationTarget[];
  /** The one step that moves the application forward, or null once only the decision is left. */
  primary: ApplicationTarget | null;
}

/**
 * The server's `allowed_targets` in working order, with the next step forward named.
 *
 * The server lists what the state machine allows and sorts it by name. Which
 * of those is the next step depends on the roadmap: with internal release
 * on, an application in preparation goes to release and cannot be filed yet.
 */
export function applicationSteps(
  a: Pick<ApplicationDetail, 'state' | 'allowed_targets'>,
  internalReview: boolean,
): ApplicationSteps {
  const rank = (x: string) => STEP_ORDER.indexOf(x as ApplicationTarget);
  let steps = a.allowed_targets.filter((x) => x !== 'withdrawn');
  if (a.state === 'preparing') steps = steps.filter((x) => x !== (internalReview ? 'submitted' : 'internal_review'));
  steps = [...steps].sort((x, y) => rank(x) - rank(y));
  if (isDecidable(a)) return { steps, primary: null };
  const forward = steps.filter((x) => rank(x) > rank(a.state));
  return { steps, primary: forward[0] ?? null };
}

/** A new attempt is possible once no application of the row is still open. */
export function canStartApplication(row: Pick<RoadmapRow, 'requirement' | 'applications'>): boolean {
  return row.requirement.applicable && !row.applications.some(isOpenApplication);
}

/* ── Conditions ───────────────────────────────────────────────────────── */

export interface ConditionDraft {
  rowId: string;
  number: string;
  text: string;
  kind: ConditionKind;
  trigger: Trigger | '';
  stage_ref: string;
  event_text: string;
  due_date: string;
  topic: Topic;
  purpose: ConditionPurpose;
  owner_user_id: string;
  responsible_party: string;
  requires_authority_approval: boolean;
  evidence_required: string;
}

let draftSeq = 0;

export function newConditionDraft(number = ''): ConditionDraft {
  draftSeq += 1;
  return {
    rowId: `c${draftSeq}`,
    number,
    text: '',
    kind: 'obligation',
    trigger: 'before_start',
    stage_ref: '',
    event_text: '',
    due_date: '',
    topic: 'other',
    purpose: '',
    owner_user_id: '',
    responsible_party: '',
    requires_authority_approval: false,
    evidence_required: '',
  };
}

export function draftOfCondition(c: Condition): ConditionDraft {
  draftSeq += 1;
  return {
    rowId: `c${draftSeq}`,
    number: c.number,
    text: c.text,
    kind: c.kind,
    trigger: c.trigger,
    stage_ref: c.stage_ref,
    event_text: c.event_text,
    due_date: c.due_date ?? '',
    topic: c.topic,
    purpose: c.purpose,
    owner_user_id: c.owner_user_id ?? '',
    responsible_party: c.responsible_party,
    requires_authority_approval: c.requires_authority_approval,
    evidence_required: c.evidence_required,
  };
}

export function toConditionInput(d: ConditionDraft): ConditionInput {
  return {
    number: d.number.trim(),
    text: d.text.trim(),
    kind: d.kind,
    trigger: d.kind === 'information' ? '' : d.trigger,
    stage_ref: d.trigger === 'before_stage' ? d.stage_ref.trim() : '',
    event_text: d.trigger === 'on_event' ? d.event_text.trim() : '',
    due_date: d.due_date || null,
    topic: d.topic,
    purpose: d.kind === 'obligation' ? d.purpose : '',
    owner_user_id: d.owner_user_id || null,
    responsible_party: d.responsible_party.trim(),
    requires_authority_approval: d.requires_authority_approval,
    evidence_required: d.evidence_required.trim(),
  };
}

export type ConditionProblem =
  | 'number_required'
  | 'text_required'
  | 'stage_required'
  | 'due_date_required'
  | 'event_required'
  | 'number_repeated';

export const CONDITION_PROBLEM: Record<ConditionProblem, KeyText> = {
  number_required: ['permits.ui.problem.number_required', 'Give the condition its number from the notice.'],
  text_required: ['permits.ui.problem.text_required', 'Copy the wording of the condition from the notice.'],
  stage_required: ['permits.ui.problem.stage_required', 'Name the stage this condition must be met before.'],
  due_date_required: ['permits.ui.problem.due_date_required', 'A condition due by a date needs that date.'],
  event_required: ['permits.ui.problem.event_required', 'Describe the event that makes this condition due.'],
  number_repeated: ['permits.ui.problem.number_repeated', 'Two conditions carry the same number.'],
};

/** What one condition still lacks. Mirrors `_validate_condition_input` in the service. */
export function conditionProblems(d: ConditionDraft): ConditionProblem[] {
  const out: ConditionProblem[] = [];
  if (!d.number.trim()) out.push('number_required');
  if (!d.text.trim()) out.push('text_required');
  if (d.kind !== 'information') {
    if (d.trigger === 'before_stage' && !d.stage_ref.trim()) out.push('stage_required');
    if (d.trigger === 'by_date' && !d.due_date) out.push('due_date_required');
    if (d.trigger === 'on_event' && !d.event_text.trim()) out.push('event_required');
  }
  return out;
}

export type ConditionAction =
  | 'confirm'
  | 'edit'
  | 'add_evidence'
  | 'submit_evidence'
  | 'discharge'
  | 'breach'
  | 'in_compliance'
  | 'link_requirement';

/**
 * The steps a condition's state leaves open, in the order the panel offers them.
 *
 * An unconfirmed proposal offers only confirm or reject: until a person
 * confirms it, it counts nowhere. A note without a duty offers nothing.
 */
export function conditionActions(c: Condition): ConditionAction[] {
  if (!c.confirmed) return ['confirm'];
  if (c.kind === 'information') return [];
  const ongoing = c.trigger === 'ongoing';
  switch (c.state) {
    case 'open': {
      const out: ConditionAction[] = ['add_evidence'];
      if (ongoing) out.push('in_compliance', 'breach');
      else out.push('submit_evidence');
      out.push('discharge', 'edit');
      if (!c.requirement_id) out.push('link_requirement');
      return out;
    }
    case 'evidence_submitted':
      return ['discharge', 'add_evidence'];
    case 'in_compliance':
      return ['breach'];
    case 'breach':
      return ['in_compliance'];
    default:
      return [];
  }
}

/**
 * The ways a person can close a condition by hand in its state. Discharge by
 * the authority, and deemed discharge, come only from a decided discharge
 * application and are never offered here.
 */
export function dischargeModes(c: Pick<Condition, 'state' | 'requires_authority_approval'>): DischargeMode[] {
  if (c.state === 'evidence_submitted') {
    return c.requires_authority_approval ? ['waived_by_authority'] : ['self_certified', 'waived_by_authority'];
  }
  if (c.state === 'open') return ['not_triggered', 'waived_by_authority'];
  return [];
}

/** A trigger that did not occur must be shown by a document where the permit hangs on the condition. */
export function dischargeNeedsDocument(
  c: Pick<Condition, 'kind' | 'requires_authority_approval'>,
  mode: DischargeMode,
): boolean {
  if (mode === 'waived_by_authority') return true;
  return mode === 'not_triggered' && (c.kind === 'suspensive' || c.requires_authority_approval);
}

/** Work can be recorded as interrupted, or as running again, once its start was notified. */
export function workStep(p: Pick<Permit, 'state' | 'start_notified_at' | 'paused_since'>): 'interruption' | 'resumption' | null {
  if (p.state !== 'in_force' || !p.start_notified_at) return null;
  return p.paused_since ? 'resumption' : 'interruption';
}

export function isLiveCondition(c: Pick<Condition, 'state'>): boolean {
  return c.state !== 'superseded';
}

/** The register views, with the same membership the API's `view` filter uses. */
export function inConditionView(
  c: ConditionRow,
  view: ConditionView | 'all' | 'proposals',
  viewerId: string | null,
): boolean {
  if (view === 'proposals') return !c.confirmed;
  if (!c.confirmed) return false;
  switch (view) {
    case 'all':
      return true;
    case 'before_start':
      return c.trigger === 'before_start' && isLiveCondition(c);
    case 'before_occupation':
      return c.trigger === 'before_occupation' && isLiveCondition(c);
    case 'ongoing_hse':
      return (c.trigger === 'ongoing' || c.hse_relevant) && isLiveCondition(c);
    case 'overdue':
      return c.overdue;
    case 'mine':
      return !!viewerId && c.owner_user_id === viewerId && isLiveCondition(c);
  }
}

/* ── Decisions ────────────────────────────────────────────────────────── */

export interface DecisionDraft {
  outcome: Outcome | '';
  decision_date: string;
  served_date: string;
  reference: string;
  scope_note: string;
  appeal_deadline: string;
  conditions: ConditionDraft[];
  conditions_pending: boolean;
  document_revision_id: string;
  security_amount: string;
  security_currency: string;
  /** Discharge application only: the listed conditions the authority discharged. */
  discharged: string[];
  /** Variation only: the numbers of dropped conditions, separated by commas. */
  removed_numbers: string;
}

export function emptyDecision(today: string, reference = '', listed: string[] = []): DecisionDraft {
  return {
    outcome: '',
    decision_date: today,
    served_date: '',
    reference,
    scope_note: '',
    appeal_deadline: '',
    conditions: [],
    conditions_pending: false,
    document_revision_id: '',
    security_amount: '',
    security_currency: '',
    discharged: listed,
    removed_numbers: '',
  };
}

export type DecisionProblem =
  | 'outcome_required'
  | 'date_required'
  | 'date_in_future'
  | 'conditions_required'
  | 'scope_required'
  | 'notice_required'
  | 'security_amount_invalid'
  | 'security_currency_required'
  | ConditionProblem;

export const DECISION_PROBLEM: Record<Exclude<DecisionProblem, ConditionProblem>, KeyText> = {
  outcome_required: ['permits.ui.problem.outcome_required', 'Choose what the authority decided.'],
  date_required: ['permits.ui.problem.date_required', 'Enter the date of the decision.'],
  date_in_future: ['permits.ui.problem.date_in_future', 'The decision date cannot be in the future.'],
  conditions_required: [
    'permits.ui.problem.conditions_required',
    'Enter at least one condition, or tick that the conditions follow later.',
  ],
  scope_required: ['permits.ui.problem.scope_required', 'Describe which part of the works the permit covers.'],
  notice_required: [
    'permits.ui.problem.notice_required',
    'A deemed grant of this permit type needs the notice that confirms it, as a document.',
  ],
  security_amount_invalid: [
    'permits.ui.problem.security_amount_invalid',
    'Write the security as a plain amount, for example 25000.00.',
  ],
  security_currency_required: [
    'permits.ui.problem.security_currency_required',
    'Give the currency of the security as a three-letter code.',
  ],
};

/** The outcomes that create a permit, and so may carry conditions. */
export function grantsPermit(outcome: Outcome | ''): boolean {
  return (
    outcome === 'granted' ||
    outcome === 'granted_with_conditions' ||
    outcome === 'partially_granted' ||
    outcome === 'deemed_granted'
  );
}

export function carriesConditions(outcome: Outcome | ''): boolean {
  return outcome === 'granted_with_conditions' || outcome === 'partially_granted';
}

const AMOUNT = /^\d{1,14}(\.\d{1,4})?$/;

/** What the application the decision is recorded on adds to the rules. */
export interface DecisionContext {
  today: string;
  /** The catalogue asks for the confirming notice when the grant is only deemed. */
  deemedNeedsNotice: boolean;
}

/** Everything a decision draft still lacks, each problem once. The server repeats every check. */
export function decisionProblems(d: DecisionDraft, ctx: DecisionContext): DecisionProblem[] {
  const { today } = ctx;
  const out = new Set<DecisionProblem>();
  if (d.outcome === 'deemed_granted' && ctx.deemedNeedsNotice && !d.document_revision_id) out.add('notice_required');
  if (!d.outcome) out.add('outcome_required');
  if (!d.decision_date) out.add('date_required');
  else if (d.decision_date > today) out.add('date_in_future');
  if (d.outcome === 'partially_granted' && !d.scope_note.trim()) out.add('scope_required');
  if (carriesConditions(d.outcome)) {
    if (d.outcome === 'granted_with_conditions' && d.conditions.length === 0 && !d.conditions_pending) {
      out.add('conditions_required');
    }
    const seen = new Set<string>();
    for (const c of d.conditions) {
      for (const problem of conditionProblems(c)) out.add(problem);
      const n = c.number.trim();
      if (n && seen.has(n)) out.add('number_repeated');
      seen.add(n);
    }
  }
  const amount = d.security_amount.trim();
  if (amount) {
    if (!AMOUNT.test(amount)) out.add('security_amount_invalid');
    if (!/^[A-Za-z]{3}$/.test(d.security_currency.trim())) out.add('security_currency_required');
  }
  return [...out];
}

/** How the application kind shapes what a decision is asked for. */
export interface DecisionShape {
  /** The conditions a discharge application listed; empty for every other kind. */
  listed: string[];
  /** A variation replaces a permit, so it may drop conditions of the old one. */
  varies: boolean;
}

export function toDecisionInput(d: DecisionDraft, shape: DecisionShape = { listed: [], varies: false }): DecisionInput {
  const withConditions = carriesConditions(d.outcome);
  const amount = d.security_amount.trim();
  const granted = grantsPermit(d.outcome);
  const partial = shape.listed.length > 0 && granted && d.discharged.length < shape.listed.length;
  return {
    document_revision_id: d.document_revision_id || null,
    // Left out, the server discharges every listed condition; a subset is named.
    discharged_condition_ids: partial ? d.discharged : null,
    removed_condition_numbers:
      shape.varies && granted
        ? d.removed_numbers
            .split(',')
            .map((n) => n.trim())
            .filter(Boolean)
        : [],
    outcome: d.outcome as Outcome,
    decision_date: d.decision_date,
    served_date: d.served_date || null,
    reference: d.reference.trim(),
    scope_note: d.outcome === 'partially_granted' ? d.scope_note.trim() : '',
    conditions: withConditions ? d.conditions.map(toConditionInput) : [],
    conditions_pending: withConditions && d.conditions_pending,
    appeal_deadline: d.appeal_deadline || null,
    security_amount: grantsPermit(d.outcome) && amount ? amount : null,
    security_currency: grantsPermit(d.outcome) && amount ? d.security_currency.trim().toUpperCase() : '',
  };
}

/* ── Clock ────────────────────────────────────────────────────────────── */

export interface ClockEventDraft {
  kind: ClockEventKind;
  at: string;
  period: string;
  unit: ClockUnit;
  reason: string;
}

/** A stopped clock can only run again; a running one can stop or be extended. */
export function clockEventKinds(clock: Pick<Clock, 'stopped_now' | 'start'>): ClockEventKind[] {
  if (!clock.start) return [];
  return clock.stopped_now ? ['resume'] : ['stop', 'extension_agreed', 'extension_by_authority'];
}

export function isExtension(kind: ClockEventKind): boolean {
  return kind === 'extension_agreed' || kind === 'extension_by_authority';
}

export type ClockEventProblem = 'at_required' | 'period_required' | 'reason_required';

export const CLOCK_EVENT_PROBLEM: Record<ClockEventProblem, KeyText> = {
  at_required: ['permits.ui.problem.at_required', 'Enter the date this happened.'],
  period_required: ['permits.ui.problem.period_required', 'An extension needs its length as a whole number.'],
  reason_required: ['permits.ui.problem.reason_required', 'An extension by the authority needs its reasons.'],
};

export function clockEventProblems(d: ClockEventDraft): ClockEventProblem[] {
  const out: ClockEventProblem[] = [];
  if (!d.at) out.push('at_required');
  if (isExtension(d.kind) && !/^[1-9]\d{0,3}$/.test(d.period.trim())) out.push('period_required');
  if (d.kind === 'extension_by_authority' && !d.reason.trim()) out.push('reason_required');
  return out;
}

export function toClockEventInput(d: ClockEventDraft): ClockEventInput {
  const base: ClockEventInput = { kind: d.kind, at: d.at, reason: d.reason.trim() };
  return isExtension(d.kind) ? { ...base, period: Number(d.period.trim()), unit: d.unit } : base;
}

/* ── Permits ──────────────────────────────────────────────────────────── */

/** How a button stands: left out, offered, or shown disabled with the refusal code. */
export interface Gate {
  show: boolean;
  enabled: boolean;
  reason: string | null;
}

/** A button follows the server flag; a record served without one falls back to the client rule. */
export function gate(flag: CanFlag | null | undefined, fallback: boolean): Gate {
  if (!flag) return { show: fallback, enabled: true, reason: null };
  return { show: flag.applies !== false, enabled: flag.allowed, reason: flag.allowed ? null : flag.reason };
}

const PERMIT_TARGET_ORDER: PermitTarget[] = ['suspended', 'in_force', 'revoked', 'expired', 'lapsed'];

/** The states a permit can be moved to by hand. A lapsed permit returns only through an extension decision. */
export function permitTargets(p: Pick<Permit, 'state' | 'can'>): PermitTarget[] {
  const served = p.can?.transition;
  if (served) return PERMIT_TARGET_ORDER.filter((x) => served[x] !== undefined && served[x]?.applies !== false);
  if (p.state === 'in_force') return ['suspended', 'revoked', 'expired'];
  if (p.state === 'suspended') return ['in_force', 'revoked'];
  return [];
}

/** The start of works is notified once, on a permit in force. */
export function canNotifyStart(p: Pick<Permit, 'state' | 'start_notified_at'>): boolean {
  return p.state === 'in_force' && !p.start_notified_at;
}

/** Whole days from `from` to `to`, both `YYYY-MM-DD`; negative when `to` is earlier. */
export function daysBetween(from: string, to: string): number {
  const a = Date.UTC(Number(from.slice(0, 4)), Number(from.slice(5, 7)) - 1, Number(from.slice(8, 10)));
  const b = Date.UTC(Number(to.slice(0, 4)), Number(to.slice(5, 7)) - 1, Number(to.slice(8, 10)));
  return Math.round((b - a) / 86_400_000);
}
