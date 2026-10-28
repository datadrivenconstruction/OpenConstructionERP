// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the permit screens show for a code: permit type names and the
// closed vocabularies (states, outcomes, condition kinds, triggers, topics,
// clock events, evidence kinds). The vocabularies are written as key maps
// rather than built from the code at runtime, so the key test can enumerate
// them and a translator can find every key by grep.
//
// Keys under `permits.enum.*`, `permits.type.*` and `permits.errors.*` are the
// backend's own (messages/en.json); everything the screens add sits under
// `permits.ui.*`.

import type {
  AnyDischargeMode,
  ApplicantRole,
  ApplicationKind,
  ApplicationState,
  ApplicationTarget,
  ClockEventKind,
  ClockUnit,
  ConditionKind,
  ConditionState,
  ConditionView,
  DependencyOn,
  DischargeMode,
  EvidenceKind,
  Outcome,
  PermitLabel,
  PermitScope,
  PermitState,
  PermitTarget,
  ReadinessStatus,
  RequirementState,
  Topic,
  Trigger,
} from './api';
import { ERROR_TEXT } from './errorText';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const REQUIREMENT_STATE: Record<RequirementState, KeyText> = {
  not_started: ['permits.enum.state.not_started', 'Not started'],
  in_progress: ['permits.enum.state.in_progress', 'In progress'],
  granted: ['permits.enum.state.granted', 'Granted'],
  partially_granted: ['permits.enum.state.partially_granted', 'Partially granted'],
  refused: ['permits.enum.state.refused', 'Refused'],
  blocked: ['permits.enum.state.blocked', 'Blocked'],
  not_applicable: ['permits.enum.state.not_applicable', 'Not applicable'],
  not_in_force: ['permits.enum.state.not_in_force', 'Permit no longer in force'],
};

export const PERMIT_STATE: Record<PermitState, KeyText> = {
  in_force: ['permits.enum.state.in_force', 'In force'],
  suspended: ['permits.enum.state.suspended', 'Suspended'],
  lapsed: ['permits.enum.state.lapsed', 'Lapsed'],
  revoked: ['permits.enum.state.revoked', 'Revoked'],
  superseded: ['permits.enum.state.superseded', 'Superseded'],
  expired: ['permits.enum.state.expired', 'Expired'],
};

export const CONDITION_STATE: Record<ConditionState, KeyText> = {
  open: ['permits.enum.state.open', 'Open'],
  evidence_submitted: ['permits.enum.state.evidence_submitted', 'Evidence submitted'],
  discharge_applied: ['permits.enum.state.discharge_applied', 'Discharge applied for'],
  discharged: ['permits.enum.state.discharged', 'Discharged'],
  in_compliance: ['permits.enum.state.in_compliance', 'In compliance'],
  breach: ['permits.enum.state.breach', 'Breach'],
  not_triggered: ['permits.enum.state.not_triggered', 'Not triggered'],
  waived: ['permits.enum.state.waived', 'Waived'],
  superseded: ['permits.enum.state.superseded', 'Superseded'],
};

export const APPLICATION_STATE: Record<ApplicationState, KeyText> = {
  planned: ['permits.ui.app_state.planned', 'Planned'],
  preparing: ['permits.ui.app_state.preparing', 'In preparation'],
  internal_review: ['permits.ui.app_state.internal_review', 'Internal release'],
  submitted: ['permits.ui.app_state.submitted', 'Submitted'],
  validated: ['permits.ui.app_state.validated', 'Accepted as complete'],
  under_review: ['permits.ui.app_state.under_review', 'Under review'],
  info_requested: ['permits.ui.app_state.info_requested', 'Information requested'],
  decided: ['permits.ui.app_state.decided', 'Decided'],
  withdrawn: ['permits.ui.app_state.withdrawn', 'Withdrawn'],
};

/** The button that moves an application to a state, worded as what happened. */
export const APPLICATION_STEP: Record<ApplicationTarget, KeyText> = {
  preparing: ['permits.ui.app_step.preparing', 'Start preparing'],
  internal_review: ['permits.ui.app_step.internal_review', 'Send for internal release'],
  submitted: ['permits.ui.app_step.submitted', 'Record submission'],
  validated: ['permits.ui.app_step.validated', 'Authority accepted it as complete'],
  under_review: ['permits.ui.app_step.under_review', 'Authority review started'],
  info_requested: ['permits.ui.app_step.info_requested', 'Authority asked for information'],
  withdrawn: ['permits.ui.app_step.withdrawn', 'Withdraw the application'],
};

export const APPLICATION_KIND: Record<ApplicationKind, KeyText> = {
  new: ['permits.ui.app_kind.new', 'New application'],
  variation: ['permits.ui.app_kind.variation', 'Variation of a permit'],
  amendment_non_material: ['permits.ui.app_kind.amendment_non_material', 'Minor amendment'],
  extension_of_validity: ['permits.ui.app_kind.extension_of_validity', 'Extension of validity'],
  discharge_of_conditions: ['permits.ui.app_kind.discharge_of_conditions', 'Discharge of conditions'],
  early_start: ['permits.ui.app_kind.early_start', 'Early start'],
};

export const OUTCOME: Record<Outcome, KeyText> = {
  granted: ['permits.ui.outcome.granted', 'Granted'],
  granted_with_conditions: ['permits.ui.outcome.granted_with_conditions', 'Granted with conditions'],
  partially_granted: ['permits.ui.outcome.partially_granted', 'Partially granted'],
  refused: ['permits.ui.outcome.refused', 'Refused'],
  deemed_granted: ['permits.ui.outcome.deemed_granted', 'Deemed granted'],
  withdrawn: ['permits.ui.outcome.withdrawn', 'Withdrawn'],
};

export const OUTCOME_HINT: Record<Outcome, KeyText> = {
  granted: ['permits.ui.outcome_hint.granted', 'The authority granted the permit as applied for, without conditions.'],
  granted_with_conditions: [
    'permits.ui.outcome_hint.granted_with_conditions',
    'The permit is granted and carries conditions. Each one goes into the condition register.',
  ],
  partially_granted: [
    'permits.ui.outcome_hint.partially_granted',
    'Only part of the works is permitted. Describe what the permit covers.',
  ],
  refused: ['permits.ui.outcome_hint.refused', 'The authority refused. A new application can follow.'],
  deemed_granted: [
    'permits.ui.outcome_hint.deemed_granted',
    'The decision period ran out without an answer and the law treats that as a grant.',
  ],
  withdrawn: ['permits.ui.outcome_hint.withdrawn', 'The applicant withdrew before a decision.'],
};

export const CONDITION_KIND: Record<ConditionKind, KeyText> = {
  suspensive: ['permits.enum.kind.suspensive', 'Suspensive condition'],
  obligation: ['permits.enum.kind.obligation', 'Obligation'],
  time_limit: ['permits.enum.kind.time_limit', 'Time limit'],
  revocation_reserve: ['permits.enum.kind.revocation_reserve', 'Reservation of revocation'],
  reserved_obligation: ['permits.enum.kind.reserved_obligation', 'Reserved obligation'],
  information: ['permits.enum.kind.information', 'Information'],
};

export const CONDITION_KIND_HINT: Record<ConditionKind, KeyText> = {
  suspensive: ['permits.ui.kind_hint.suspensive', 'The permit takes effect only once this is met.'],
  obligation: ['permits.ui.kind_hint.obligation', 'A duty attached to the permit. The permit stays valid meanwhile.'],
  time_limit: ['permits.ui.kind_hint.time_limit', 'The permit ends or lapses at a date.'],
  revocation_reserve: ['permits.ui.kind_hint.revocation_reserve', 'The authority may revoke the permit.'],
  reserved_obligation: ['permits.ui.kind_hint.reserved_obligation', 'The authority may add duties later.'],
  information: ['permits.ui.kind_hint.information', 'A note in the decision. Nothing has to be done.'],
};

export const TRIGGER: Record<Trigger, KeyText> = {
  before_application_x: ['permits.enum.trigger.before_application_x', 'Before another application'],
  before_start: ['permits.enum.trigger.before_start', 'Before start'],
  before_stage: ['permits.enum.trigger.before_stage', 'Before a stage'],
  before_occupation: ['permits.enum.trigger.before_occupation', 'Before occupation'],
  ongoing: ['permits.enum.trigger.ongoing', 'Ongoing'],
  by_date: ['permits.enum.trigger.by_date', 'By date'],
  on_event: ['permits.enum.trigger.on_event', 'On event'],
  after_completion: ['permits.enum.trigger.after_completion', 'After completion'],
};

export const TOPIC: Record<Topic, KeyText> = {
  hse: ['permits.enum.topic.hse', 'HSE'],
  environment: ['permits.enum.topic.environment', 'Environment'],
  noise: ['permits.enum.topic.noise', 'Noise'],
  traffic: ['permits.enum.topic.traffic', 'Traffic'],
  heritage: ['permits.enum.topic.heritage', 'Heritage'],
  structural: ['permits.enum.topic.structural', 'Structural'],
  fire: ['permits.enum.topic.fire', 'Fire'],
  drainage: ['permits.enum.topic.drainage', 'Drainage'],
  ecology: ['permits.enum.topic.ecology', 'Ecology'],
  design: ['permits.enum.topic.design', 'Design'],
  admin: ['permits.enum.topic.admin', 'Administrative'],
  other: ['permits.enum.topic.other', 'Other'],
};

export const SCOPE: Record<PermitScope, KeyText> = {
  full: ['permits.enum.scope.full', 'Full'],
  partial: ['permits.enum.scope.partial', 'Partial'],
  preliminary: ['permits.enum.scope.preliminary', 'Preliminary'],
  early_start: ['permits.enum.scope.early_start', 'Early start'],
};

export const APPLICANT_ROLE: Record<ApplicantRole, KeyText> = {
  owner: ['permits.enum.applicant_role.owner', 'Owner'],
  designer: ['permits.enum.applicant_role.designer', 'Designer'],
  contractor: ['permits.enum.applicant_role.contractor', 'Contractor'],
  operator: ['permits.enum.applicant_role.operator', 'Operator'],
};

export const CLOCK_EVENT: Record<ClockEventKind, KeyText> = {
  stop: ['permits.ui.clock_event.stop', 'Clock stopped'],
  resume: ['permits.ui.clock_event.resume', 'Clock running again'],
  extension_agreed: ['permits.ui.clock_event.extension_agreed', 'Extension agreed with the authority'],
  extension_by_authority: ['permits.ui.clock_event.extension_by_authority', 'Extension by the authority'],
};

export const CLOCK_UNIT: Record<ClockUnit, KeyText> = {
  calendar_days: ['permits.ui.unit.calendar_days', 'calendar days'],
  working_days: ['permits.ui.unit.working_days', 'working days'],
  weeks: ['permits.ui.unit.weeks', 'weeks'],
  months: ['permits.ui.unit.months', 'months'],
  years: ['permits.ui.unit.years', 'years'],
};

/** A length of time with its unit, counted: key, the English for one, the English for many. */
export const PERIOD_TEXT: Record<ClockUnit, readonly [key: string, one: string, other: string]> = {
  calendar_days: ['permits.ui.period.calendar_days', '{{count}} calendar day', '{{count}} calendar days'],
  working_days: ['permits.ui.period.working_days', '{{count}} working day', '{{count}} working days'],
  weeks: ['permits.ui.period.weeks', '{{count}} week', '{{count}} weeks'],
  months: ['permits.ui.period.months', '{{count}} month', '{{count}} months'],
  years: ['permits.ui.period.years', '{{count}} year', '{{count}} years'],
};

/** "3 months" in the reader's language; empty when there is no period. */
export function periodText(t: TFn, period: number | null | undefined, unit: ClockUnit | null | undefined): string {
  if (!period || !unit) return '';
  const entry = PERIOD_TEXT[unit];
  if (!entry) return String(period);
  return t(entry[0], { count: period, defaultValue_one: entry[1], defaultValue_other: entry[2] });
}

/** Why the clock gives no decision date. */
export const CLOCK_REASON: Record<string, KeyText> = {
  no_statutory_period: [
    'permits.ui.clock_reason.no_statutory_period',
    'The law sets no decision period for this permit type.',
  ],
  clock_not_started: [
    'permits.ui.clock_reason.clock_not_started',
    'The decision period has not started yet. It starts once the authority has the application.',
  ],
};

export const EVIDENCE_KIND: Record<EvidenceKind, KeyText> = {
  report: ['permits.ui.evidence_kind.report', 'Report'],
  photo: ['permits.ui.evidence_kind.photo', 'Photo'],
  external_url: ['permits.ui.evidence_kind.external_url', 'Web link'],
  cde_revision: ['permits.ui.evidence_kind.cde_revision', 'Document revision'],
  inspection: ['permits.ui.evidence_kind.inspection', 'Inspection'],
  commissioning_item: ['permits.ui.evidence_kind.commissioning_item', 'Commissioning item'],
  discharge_decision: ['permits.ui.evidence_kind.discharge_decision', 'Discharge decision'],
};

export const DISCHARGE_MODE: Record<AnyDischargeMode, KeyText> = {
  self_certified: ['permits.ui.discharge_mode.self_certified', 'Checked and confirmed by us'],
  not_triggered: ['permits.ui.discharge_mode.not_triggered', 'The trigger did not occur'],
  waived_by_authority: ['permits.ui.discharge_mode.waived_by_authority', 'Waived by the authority'],
  authority_discharged: ['permits.ui.discharge_mode.authority_discharged', 'Discharged by the authority'],
  deemed_discharged: ['permits.ui.discharge_mode.deemed_discharged', 'Deemed discharged'],
};

export const DISCHARGE_MODE_HINT: Record<DischargeMode, KeyText> = {
  self_certified: [
    'permits.ui.discharge_hint.self_certified',
    'A second person checks the evidence the owner submitted. The owner cannot confirm their own condition.',
  ],
  not_triggered: [
    'permits.ui.discharge_hint.not_triggered',
    'The event this condition waits for did not happen, so nothing is due.',
  ],
  waived_by_authority: [
    'permits.ui.discharge_hint.waived_by_authority',
    'The authority dropped the condition in writing. The letter is stored as a document revision.',
  ],
};

export const DEPENDENCY_ON: Record<DependencyOn, KeyText> = {
  granted: ['permits.ui.dependency_on.granted', 'must be granted first'],
  submitted: ['permits.ui.dependency_on.submitted', 'must be submitted first'],
};

export const READINESS_STATUS: Record<ReadinessStatus, KeyText> = {
  ready: ['permits.ui.readiness.ready', 'Ready'],
  at_risk: ['permits.ui.readiness.at_risk', 'At risk'],
  not_ready: ['permits.ui.readiness.not_ready', 'Not ready'],
  no_roadmap: ['permits.ui.readiness.no_roadmap', 'No roadmap'],
};

/** One sentence per readiness finding; `{{detail}}` is the condition number or the roadmap row. */
export const READINESS_ITEM: Record<string, KeyText> = {
  permit_missing: ['permits.ui.readiness_item.permit_missing', '{{detail}}: not granted yet'],
  permit_due_later: ['permits.ui.readiness_item.permit_due_later', '{{detail}}: needed later, not granted yet'],
  permit_due_later_dated: [
    'permits.ui.readiness_item.permit_due_later_dated',
    '{{title}}: needed from {{date}}, not granted yet',
  ],
  permit_granted: ['permits.ui.readiness_item.permit_granted', '{{detail}}: granted'],
  permit_partial: ['permits.ui.readiness_item.permit_partial', '{{detail}}: granted in part only'],
  conditions_pending: [
    'permits.ui.readiness_item.conditions_pending',
    '{{detail}}: the conditions of the decision are not entered yet',
  ],
  schedule_conflict: [
    'permits.ui.readiness_item.schedule_conflict',
    '{{detail}}: the decision is forecast after the date it is needed',
  ],
  start_at_risk_early_start: [
    'permits.ui.readiness_item.start_at_risk_early_start',
    '{{detail}}: work starts on an early start approval, at own risk',
  ],
  suspensive_condition_open: [
    'permits.ui.readiness_item.suspensive_condition_open',
    'Condition {{detail}} must be met before the permit takes effect',
  ],
  before_start_obligation_open: [
    'permits.ui.readiness_item.before_start_obligation_open',
    'Condition {{detail}} is open and due before start',
  ],
  before_start_obligation_accepted_at_gate: [
    'permits.ui.readiness_item.before_start_obligation_accepted_at_gate',
    'Condition {{detail}} is open and was accepted as a gate condition',
  ],
  before_occupation_condition_open: [
    'permits.ui.readiness_item.before_occupation_condition_open',
    'Condition {{detail}} is open and due before occupation',
  ],
  condition_without_owner: ['permits.ui.readiness_item.condition_without_owner', 'Condition {{detail}} has no owner'],
  condition_without_trigger: [
    'permits.ui.readiness_item.condition_without_trigger',
    'Condition {{detail}} does not say when it is due',
  ],
  occupancy_permit: ['permits.ui.readiness_item.occupancy_permit', '{{detail}}: permission to occupy'],
  requirement_filed: ['permits.ui.readiness_item.requirement_filed', '{{detail}}: submitted or granted'],
  register_complete: ['permits.ui.readiness_item.register_complete', 'The condition register is complete'],
};

export const CONDITION_VIEW: Record<ConditionView | 'all' | 'proposals', KeyText> = {
  all: ['permits.ui.view.all', 'All'],
  before_start: ['permits.ui.view.before_start', 'Before start'],
  before_occupation: ['permits.ui.view.before_occupation', 'Before occupation'],
  ongoing_hse: ['permits.ui.view.ongoing_hse', 'Ongoing and HSE'],
  overdue: ['permits.ui.view.overdue', 'Overdue'],
  mine: ['permits.ui.view.mine', 'Mine'],
  proposals: ['permits.ui.view.proposals', 'To confirm'],
};

export const PERMIT_STEP: Record<PermitTarget, KeyText> = {
  suspended: ['permits.ui.permit_step.suspended', 'Suspended by the authority'],
  in_force: ['permits.ui.permit_step.in_force', 'Back in force'],
  revoked: ['permits.ui.permit_step.revoked', 'Revoked by the authority'],
  expired: ['permits.ui.permit_step.expired', 'Time limit reached'],
  lapsed: ['permits.ui.permit_step.lapsed', 'Lapsed, work did not start in time'],
};

export const PROPOSE_REASON: Record<string, KeyText> = {
  route_exempt: ['permits.ui.propose.route_exempt', 'The confirmed permit route is exempt, so no permit is proposed.'],
  route_undetermined: [
    'permits.ui.propose.route_undetermined',
    'The permit route is not determined yet. Finish the route assessment first.',
  ],
  no_types_for_route: [
    'permits.ui.propose.no_types_for_route',
    'The catalogue has no permit type for the confirmed route. Add the permits by hand.',
  ],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  REQUIREMENT_STATE,
  PERMIT_STATE,
  CONDITION_STATE,
  APPLICATION_STATE,
  APPLICATION_STEP,
  APPLICATION_KIND,
  OUTCOME,
  OUTCOME_HINT,
  CONDITION_KIND,
  CONDITION_KIND_HINT,
  TRIGGER,
  TOPIC,
  SCOPE,
  APPLICANT_ROLE,
  CLOCK_EVENT,
  CLOCK_UNIT,
  CLOCK_REASON,
  EVIDENCE_KIND,
  DISCHARGE_MODE,
  DISCHARGE_MODE_HINT,
  DEPENDENCY_ON,
  READINESS_STATUS,
  READINESS_ITEM,
  CONDITION_VIEW,
  PERMIT_STEP,
  PROPOSE_REASON,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(
  t: TFn,
  map: Record<T, KeyText>,
  code: T | '' | null | undefined,
  vars?: Record<string, unknown>,
): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1], ...vars });
}

/**
 * A catalogue code written for a reader: `road_occupation` becomes "Road occupation".
 *
 * The last resort when neither the API nor the locale names the item. It is
 * never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The name of a permit type: the catalogue key in the locale, else the code made readable. */
export function typeName(ctx: LabelContext, code: string, nameKey?: string | null): string {
  for (const key of [nameKey, ['permits', 'type', code].join('.')]) {
    if (key && ctx.exists(key)) return ctx.t(key);
  }
  return humanizeCode(code);
}

/** The name of a catalogue as the store labels it. */
export function labelText(ctx: LabelContext, label: PermitLabel | null | undefined, fallback: string): string {
  if (label?.key && ctx.exists(label.key)) return ctx.t(label.key);
  if (label?.text) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    const text = label.text[ctx.language] ?? label.text[lang] ?? label.text.en ?? Object.values(label.text)[0];
    if (text) return text;
  }
  return humanizeCode(fallback);
}

/**
 * The sentence for a refusal code, translated when the locale has it. Where
 * the locale lacks the code, the server's own sentence wins: it is already in
 * the reader's language, the built-in English is not.
 */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const fallback = serverMessage || ERROR_TEXT[code] || humanizeCode(code);
  return t(['permits', 'errors', code].join('.'), { defaultValue: fallback });
}

export { ERROR_TEXT };
