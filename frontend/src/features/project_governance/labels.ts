// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the governance screens show for a code: phase, gate, area and
// document names, and the closed vocabularies (gate state, outcome, check,
// document, condition). The vocabularies are written as key maps rather than
// built from the code at runtime, so the key test can enumerate them and a
// translator can find every key by grep.

import { getErrorMessage } from '@/shared/lib/api';

import { governanceErrorCode } from './api';
import type {
  CheckStatus,
  ConditionStatus,
  DocumentStatus,
  EvidenceItem,
  GateStatus,
  GovernanceLabel,
  Outcome,
  Severity,
} from './api';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const GATE_STATUS: Record<GateStatus, KeyText> = {
  not_started: ['governance.project.gate_status.not_started', 'Not started'],
  in_preparation: ['governance.project.gate_status.in_preparation', 'In preparation'],
  in_review: ['governance.project.gate_status.in_review', 'In review'],
  on_hold: ['governance.project.gate_status.on_hold', 'On hold'],
  decided: ['governance.project.gate_status.decided', 'Decided'],
};

export const OUTCOME: Record<Outcome, KeyText> = {
  go: ['governance.project.outcome.go', 'Go'],
  go_with_conditions: ['governance.project.outcome.go_with_conditions', 'Go with conditions'],
  hold: ['governance.project.outcome.hold', 'Hold'],
  recycle: ['governance.project.outcome.recycle', 'Recycle'],
  stop: ['governance.project.outcome.stop', 'Stop'],
};

export const OUTCOME_HINT: Record<Outcome, KeyText> = {
  go: ['governance.project.outcome_hint.go', 'Everything required is in place. The project moves to the next phase.'],
  go_with_conditions: [
    'governance.project.outcome_hint.go_with_conditions',
    'The project moves on, and each open point becomes a condition with an owner and a due date.',
  ],
  hold: ['governance.project.outcome_hint.hold', 'The gate pauses until a resume date. Nothing moves meanwhile.'],
  recycle: [
    'governance.project.outcome_hint.recycle',
    'The phase is reworked. Readiness checks go stale and the gate is reviewed again.',
  ],
  stop: [
    'governance.project.outcome_hint.stop',
    'The project ends at this gate. Open frame documents become read-only.',
  ],
};

export const CHECK_STATUS: Record<CheckStatus, KeyText> = {
  not_assessed: ['governance.project.check_status.not_assessed', 'Not assessed'],
  ready: ['governance.project.check_status.ready', 'Ready'],
  ready_with_risks: ['governance.project.check_status.ready_with_risks', 'Ready with risks'],
  not_ready: ['governance.project.check_status.not_ready', 'Not ready'],
  not_applicable: ['governance.project.check_status.not_applicable', 'Not applicable'],
};

export const DOCUMENT_STATUS: Record<DocumentStatus, KeyText> = {
  draft: ['governance.project.document_status.draft', 'Draft'],
  in_review: ['governance.project.document_status.in_review', 'In review'],
  approved_at_gate: ['governance.project.document_status.approved_at_gate', 'Approved'],
  binding: ['governance.project.document_status.binding', 'Binding'],
  superseded: ['governance.project.document_status.superseded', 'Superseded'],
};

export const CONDITION_STATUS: Record<ConditionStatus, KeyText> = {
  open: ['governance.project.condition_status.open', 'Open'],
  cleared: ['governance.project.condition_status.cleared', 'Cleared'],
  waived: ['governance.project.condition_status.waived', 'Waived'],
  overdue: ['governance.project.condition_status.overdue', 'Overdue'],
};

export const SEVERITY: Record<Severity, KeyText> = {
  critical: ['governance.project.severity.critical', 'Critical'],
  essential: ['governance.project.severity.essential', 'Essential'],
  recommended: ['governance.project.severity.recommended', 'Recommended'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  GATE_STATUS,
  OUTCOME,
  OUTCOME_HINT,
  CHECK_STATUS,
  DOCUMENT_STATUS,
  CONDITION_STATUS,
  SEVERITY,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(t: TFn, map: Record<T, KeyText>, code: T | '' | null | undefined): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/**
 * A catalogue code written for a reader: `cost_finance` becomes "Cost finance".
 *
 * The last resort when neither the API nor the locale names the item. It is
 * never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function fromLabel(label: GovernanceLabel | null | undefined, ctx: LabelContext): string {
  if (!label) return '';
  if (label.key && ctx.exists(label.key)) return ctx.t(label.key);
  if (label.text) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    return label.text[ctx.language] ?? label.text[lang] ?? label.text.en ?? Object.values(label.text)[0] ?? '';
  }
  return '';
}

/** The text the server filled for the reader's language, with English as the fallback. Empty when it sent none. */
function filledText(label: GovernanceLabel | null | undefined, ctx: LabelContext): string {
  if (!label?.text) return '';
  const lang = ctx.language.split('-')[0] ?? 'en';
  return label.text[ctx.language] ?? label.text[lang] ?? label.text.en ?? '';
}

export type CatalogueItemKind = 'phase' | 'gate' | 'area' | 'doc' | 'criterion';

/**
 * The name of a catalogue item: the project's own override first, then the
 * label the API sent, then the catalogue key in the locale, then the code.
 *
 * The key guess tries the pinned catalogue and then `neutral`, because the
 * national phase models borrow their areas and documents from it.
 */
export function catalogueName(
  ctx: LabelContext,
  args: {
    kind: CatalogueItemKind;
    code: string;
    catalogueId?: string | null;
    label?: GovernanceLabel | null;
    override?: string | null;
  },
): string {
  if (args.override && args.override.trim()) return args.override.trim();
  const fromApi = fromLabel(args.label, ctx);
  if (fromApi) return fromApi;
  const catalogues = [args.catalogueId, 'neutral'].filter((c): c is string => !!c);
  for (const cat of catalogues) {
    const key = ['governance', 'catalogue', cat, args.kind, args.code].join('.');
    if (ctx.exists(key)) return ctx.t(key);
  }
  return humanizeCode(args.code);
}

/** The bare catalogue id from a gate's `"source:id@version"` reference. */
export function catalogueIdOf(ref: string | null | undefined): string | null {
  if (!ref) return null;
  const afterSource = ref.includes(':') ? ref.slice(ref.indexOf(':') + 1) : ref;
  const id = afterSource.split('@')[0];
  return id || null;
}

/**
 * The English of every refusal and blocker code the backend sends, as
 * `governance.errors.<code>`. Mirrors the module's `messages/en.json`, so a
 * blocker renders a sentence even before the locale carries the key.
 */
export const ERROR_TEXT: Record<string, string> = {
  unknown_outcome: 'This decision outcome is not known',
  gate_not_in_review: 'The gate is not in review, so no decision can be recorded on it',
  gate_not_decided: 'Only a decided gate can be reopened',
  rationale_required: 'Write down the reason for this decision',
  required_document_not_approved: 'A required frame document is not ready for approval at this gate',
  area_without_owner: 'This management area has no owner, so nobody can attest its readiness',
  area_not_ready: 'This management area is not ready for the gate',
  evidence_not_met: 'Required readiness evidence for this area is not met',
  unknown_criterion: "This readiness criterion is not part of the project's model for this area and gate",
  unknown_evidence_not_acknowledged:
    'Readiness evidence of this area is unconfirmed or carries a warning. Confirm that you have seen it before you let the gate pass',
  check_stale: 'A document changed after readiness was confirmed, so the area must be confirmed again',
  condition_overdue: 'A condition from an earlier gate is overdue and must be cleared or waived first',
  conditions_required: 'A go with conditions needs at least one condition',
  conditions_not_allowed: 'Only a go with conditions can carry conditions',
  condition_text_required: 'Every condition needs a text',
  condition_unknown_area: 'The condition names an area that is not part of this project',
  waiver_needs_rationale: 'A waiver needs a written reason',
  not_applicable_needs_rationale: 'Marking this not applicable needs a written reason',
  not_applicable_not_accepted: 'The decider has not accepted this area as not applicable',
  decider_not_entitled: 'You are not entitled to decide this gate by its approval route',
  decider_is_area_owner: 'Under the four-eyes rule an area owner or deputy may not decide this gate',
  hold_needs_resume_date: 'A hold needs a resume date in the future',
  proceed_at_risk_needs_conditions: 'Proceeding at risk is only possible with a go with conditions',
  proceed_at_risk_area_not_blocking: 'This area is not blocking, so it cannot be named as proceeding at risk',
  project_stopped: 'The project was stopped at a gate',
  document_read_only: 'This frame document is read-only because the project was stopped',
  binding_requires_change_request: 'This frame document is binding and changes only through a change request',
  phase_mapping_missing: 'The new phase model needs a mapping for this phase',
  phase_mapping_unknown_target: 'The mapping names a phase the new model does not have',
  no_decision_route: 'No approval route is chosen for the gate decisions of this project',
  no_change_route: 'No approval route is chosen for changes to the binding documents of this project',
  route_not_pinnable: 'This approval route cannot be chosen: it must be an active route of this project for this kind of decision',
  route_not_at_final_step: 'The approval route has not reached its final step yet',
  route_not_pending: 'The approval route of this gate is no longer pending',
  concurrent_decision: 'Somebody else decided this gate a moment ago; reload and check the decision',
  gate_out_of_order: 'The project is not in the phase this gate leaves',
  model_missing: 'No governance model is set for this project',
  model_exists: 'A governance model is already set; change it with a phase mapping',
  unknown_catalogue: 'This catalogue is not known',
  area_not_found: 'Management area not found',
  gate_not_found: 'Gate not found',
  document_not_found: 'Frame document not found',
  condition_not_found: 'Condition not found',
  change_request_not_found: 'Change request not found',
  check_not_found: 'Readiness check not found',
  not_area_owner: 'Only the owner or deputy of this area may do this',
  owner_not_project_member: 'The owner must have access to this project',
  unknown_document_type: 'This document type is not part of the catalogue for this area',
  container_not_in_project: 'The CDE container does not belong to this project',
  invalid_transition: 'This change of state is not allowed',
  condition_not_open: 'Only an open condition can be cleared or waived',
  document_not_binding: 'Only a binding frame document can be changed through a change request',
  no_pending_revision: 'There is no newer revision to make binding',
  change_request_not_open: 'This change request is no longer open',
  invalid_status: 'This status is not allowed here',
  decision_immutable: 'A gate decision cannot be changed or deleted',
  document_exists: 'This frame document is already tracked for the area',
  catalogue_code_taken: 'A catalogue with this code already exists',
  catalogue_retired: 'This catalogue is retired and can no longer be edited or pinned',
  catalogue_invalid: 'The catalogue draft breaks a catalogue rule and cannot be published',
  pack_catalogue_invalid: 'The active pack declares this catalogue, but its file is missing or breaks the catalogue rules',
  area_retired: 'This area was retired by a change of the phase model and takes no new documents',
  settings_frozen_in_review: 'This cannot be changed while a gate is in review or on hold; decide the gate first',
  null_not_allowed: 'This field cannot be empty',
  gate_not_on_hold: 'Only a gate on hold can be resumed',
  gate_historic: 'This gate belongs to a phase model the project no longer uses',
  later_gate_active: 'A later gate was already started, so this gate cannot be reopened',
  model_unchanged: 'This phase model is already the one the project uses',
  not_condition_owner: 'Only the owner of this condition or a manager may clear it',
  route_needs_more_approvals: 'The last step of the approval route still waits for other approvers',
  activity_not_in_project: 'This schedule activity does not belong to the project',
  target_date_owned_by_schedule: 'The target date comes from the linked schedule activity and is changed there',
};

/** The sentence for a blocker or refusal code, translated when the locale has it. */
/** The short mark of an evidence item that waits for the decider: a warning reads differently from no answer. */
export function evidenceMark(t: TFn, state: string | null | undefined): string {
  return state === 'warning'
    ? t('governance.project.gate.evidence_warning', { defaultValue: 'warning' })
    : t('governance.project.gate.evidence_unconfirmed', { defaultValue: 'unconfirmed' });
}

/**
 * What one evidence item says. A source that failed or gave no answer has no name of
 * its own, so it reads as the sentence that says so.
 *
 * The sentence the server filled comes before the key of the label. A module may send a
 * sentence with values in it (a code, a due date) that it filled itself and sends no
 * parameters for, so the key alone would print the placeholders as they stand.
 */
export function evidenceText(
  t: TFn,
  ctx: LabelContext,
  item: Pick<EvidenceItem, 'code'> & Partial<Pick<EvidenceItem, 'label' | 'error'>>,
): string {
  if (item.error) {
    return t('governance.evidence.provider_failed', {
      defaultValue: 'This evidence source could not be read right now.',
    });
  }
  if (item.code.endsWith(':no_answer')) {
    return t('governance.evidence.no_answer', {
      defaultValue: 'This evidence source gave no answer, so it counts as unknown.',
    });
  }
  const filled = filledText(item.label, ctx);
  if (filled) return filled;
  return catalogueName(ctx, { kind: 'doc', code: item.code, label: item.label });
}

export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const english = ERROR_TEXT[code] ?? serverMessage ?? humanizeCode(code);
  return t(['governance', 'errors', code].join('.'), { defaultValue: english });
}

/**
 * The sentence for a failed request: the governance refusal in the reader's
 * language when the server named a code, the shared error message otherwise.
 */
export function refusalText(t: TFn, err: unknown): string {
  const code = governanceErrorCode(err);
  return code ? errorText(t, code, getErrorMessage(err)) : getErrorMessage(err);
}
