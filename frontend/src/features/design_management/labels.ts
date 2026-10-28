// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the design screens show for a code: the closed vocabularies
// (states, purposes, kinds), the names of catalogue items (numbering scheme,
// its fields and code lists, report kinds, permit profiles, phases) and the
// sentence for each refusal code. The vocabularies are key maps rather than
// keys built at runtime, so the key test can enumerate them and a translator
// can find every key by grep.

import type {
  ApprovalPointKind,
  ApprovalPointState,
  CdeState,
  CommentSeverity,
  CommentState,
  DeliverableState,
  DesignLabel,
  DesignOption,
  DesignPhase,
  DistFormat,
  IndependentCheck,
  NumberingField,
  NumberingScheme,
  PartyKind,
  PermitCondition,
  PermitItemKind,
  PermitState,
  Purpose,
  ReleaseState,
  ReportState,
  ReportsCatalogue,
  ReviewOutcome,
  ReviewState,
  RoleState,
  WbsKind,
} from './api';
import { ERROR_TEXT } from './errors';
import { UI, type UiCountKey, type UiKey } from './text';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

/** A screen string by its key; the English lives in `text.ts` and travels as `defaultValue`. */
export function ui(t: TFn, key: UiKey, vars?: Record<string, unknown>): string {
  return t(key, { defaultValue: UI[key], ...vars });
}

/** A screen string that depends on a number: the locale picks the plural form, English is the default. */
export function uiCount(t: TFn, key: UiCountKey, count: number, vars?: Record<string, unknown>): string {
  return t(key, {
    count,
    defaultValue_one: UI[`${key}_one`],
    defaultValue_other: UI[`${key}_other`],
    ...vars,
  });
}

export const CDE_STATE:Record<CdeState, KeyText> = {
  wip: ['design.cde_state.wip', 'Work in progress'],
  shared: ['design.cde_state.shared', 'Shared'],
  published: ['design.cde_state.published', 'Published'],
  archived: ['design.cde_state.archived', 'Archived'],
};

export const PURPOSE: Record<Purpose, KeyText> = {
  for_approval: ['design.purpose.for_approval', 'For approval'],
  for_review: ['design.purpose.for_review', 'For review'],
  for_information: ['design.purpose.for_information', 'For information'],
  for_construction: ['design.purpose.for_construction', 'For construction'],
  for_tender: ['design.purpose.for_tender', 'For tender'],
  for_record: ['design.purpose.for_record', 'For record'],
};

export const REPORT_STATE: Record<ReportState, KeyText> = {
  required: ['design.report_state.required', 'Required'],
  commissioned: ['design.report_state.commissioned', 'Commissioned'],
  in_progress: ['design.report_state.in_progress', 'In progress'],
  submitted: ['design.report_state.submitted', 'Submitted'],
  under_check: ['design.report_state.under_check', 'Under check'],
  remarks: ['design.report_state.remarks', 'Remarks'],
  accepted: ['design.report_state.accepted', 'Accepted'],
  rejected: ['design.report_state.rejected', 'Rejected'],
  not_required: ['design.report_state.not_required', 'Not required'],
};

export const INDEPENDENT_CHECK: Record<IndependentCheck, KeyText> = {
  none: ['design.independent_check.none', 'None'],
  optional: ['design.independent_check.optional', 'Optional'],
  required_by_rule: ['design.independent_check.required_by_rule', 'Required by rule'],
};

export const PERMIT_ITEM: Record<PermitItemKind, KeyText> = {
  drawing: ['design.permit_item.drawing', 'Drawing'],
  report: ['design.permit_item.report', 'Report'],
  form: ['design.permit_item.form', 'Form'],
};

export const ROLE_STATE: Record<RoleState, KeyText> = {
  planned: ['design.ui.role_state.planned', 'Planned'],
  appointed: ['design.ui.role_state.appointed', 'Appointed'],
  active: ['design.ui.role_state.active', 'Active'],
  released: ['design.ui.role_state.released', 'Released'],
};

export const PARTY_KIND: Record<PartyKind, KeyText> = {
  owner: ['design.ui.party_kind.owner', 'Owner'],
  lead_designer: ['design.ui.party_kind.lead_designer', 'Lead designer'],
  discipline_designer: ['design.ui.party_kind.discipline_designer', 'Discipline designer'],
  specialist: ['design.ui.party_kind.specialist', 'Specialist'],
  checker: ['design.ui.party_kind.checker', 'Independent checker'],
  authority: ['design.ui.party_kind.authority', 'Authority'],
  contractor_designer: ['design.ui.party_kind.contractor_designer', "Contractor's designer"],
};

export const APPROVAL_STATE: Record<ApprovalPointState, KeyText> = {
  open: ['design.ui.approval_state.open', 'Open'],
  in_review: ['design.ui.approval_state.in_review', 'Waiting for the decision'],
  approved: ['design.ui.approval_state.approved', 'Approved'],
  rejected: ['design.ui.approval_state.rejected', 'Rejected'],
};

export const APPROVAL_KIND: Record<ApprovalPointKind, KeyText> = {
  owner_approval: ['design.ui.approval_kind.owner_approval', 'Owner approval'],
  user_signoff: ['design.ui.approval_kind.user_signoff', 'User sign-off'],
  cost_check: ['design.ui.approval_kind.cost_check', 'Cost check'],
  authority: ['design.ui.approval_kind.authority', 'Authority'],
  internal_review: ['design.ui.approval_kind.internal_review', 'Internal review'],
};

export const DELIVERABLE_STATE: Record<DeliverableState, KeyText> = {
  not_started: ['design.ui.deliverable_state.not_started', 'Not started'],
  in_progress: ['design.ui.deliverable_state.in_progress', 'In progress'],
  issued_for_review: ['design.ui.deliverable_state.issued_for_review', 'Issued for review'],
  accepted: ['design.ui.deliverable_state.accepted', 'Accepted'],
  waived: ['design.ui.deliverable_state.waived', 'Waived'],
};

export const RELEASE_STATE: Record<ReleaseState, KeyText> = {
  draft: ['design.ui.release_state.draft', 'Draft'],
  ready: ['design.ui.release_state.ready', 'Ready to issue'],
  issued: ['design.ui.release_state.issued', 'Issued'],
  cancelled: ['design.ui.release_state.cancelled', 'Cancelled'],
};

export const REVIEW_STATE: Record<ReviewState, KeyText> = {
  planned: ['design.ui.review_state.planned', 'Planned'],
  open: ['design.ui.review_state.open', 'Open for comments'],
  comments_closed: ['design.ui.review_state.comments_closed', 'Comments closed'],
  concluded: ['design.ui.review_state.concluded', 'Concluded'],
};

export const REVIEW_OUTCOME: Record<ReviewOutcome, KeyText> = {
  accepted: ['design.ui.review_outcome.accepted', 'Accepted'],
  accepted_with_comments: ['design.ui.review_outcome.accepted_with_comments', 'Accepted with comments'],
  rework: ['design.ui.review_outcome.rework', 'Rework needed'],
};

export const COMMENT_STATE: Record<CommentState, KeyText> = {
  open: ['design.ui.comment_state.open', 'Open'],
  answered: ['design.ui.comment_state.answered', 'Answered'],
  closed: ['design.ui.comment_state.closed', 'Closed'],
  rejected: ['design.ui.comment_state.rejected', 'Rejected'],
};

export const SEVERITY: Record<CommentSeverity, KeyText> = {
  minor: ['design.ui.severity.minor', 'Minor'],
  major: ['design.ui.severity.major', 'Major'],
  critical: ['design.ui.severity.critical', 'Critical'],
};

export const PERMIT_STATE: Record<PermitState, KeyText> = {
  assembling: ['design.ui.permit_state.assembling', 'Being assembled'],
  ready: ['design.ui.permit_state.ready', 'Ready to submit'],
  submitted: ['design.ui.permit_state.submitted', 'Submitted'],
  under_review: ['design.ui.permit_state.under_review', 'Under review by the authority'],
  remarks: ['design.ui.permit_state.remarks', 'Remarks from the authority'],
  approved: ['design.ui.permit_state.approved', 'Approved'],
  partially_approved: ['design.ui.permit_state.partially_approved', 'Partly approved'],
  refused: ['design.ui.permit_state.refused', 'Refused'],
  withdrawn: ['design.ui.permit_state.withdrawn', 'Withdrawn'],
};

export const CONDITION_STATE: Record<PermitCondition['state'], KeyText> = {
  proposed: ['design.ui.condition_state.proposed', 'To confirm'],
  confirmed: ['design.ui.condition_state.confirmed', 'Confirmed, task created'],
  dismissed: ['design.ui.condition_state.dismissed', 'Dismissed'],
};

export const WBS_KIND: Record<WbsKind, KeyText> = {
  location: ['design.ui.wbs_kind.location', 'Location'],
  system: ['design.ui.wbs_kind.system', 'System'],
  package: ['design.ui.wbs_kind.package', 'Work package'],
  phase: ['design.ui.wbs_kind.phase', 'Phase'],
  cost: ['design.ui.wbs_kind.cost', 'Cost group'],
};

export const DIST_FORMAT: Record<DistFormat, KeyText> = {
  pdf: ['design.ui.dist_format.pdf', 'PDF'],
  native: ['design.ui.dist_format.native', 'Native file'],
  both: ['design.ui.dist_format.both', 'PDF and native file'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  CDE_STATE,
  PURPOSE,
  REPORT_STATE,
  INDEPENDENT_CHECK,
  PERMIT_ITEM,
  ROLE_STATE,
  PARTY_KIND,
  APPROVAL_STATE,
  APPROVAL_KIND,
  DELIVERABLE_STATE,
  RELEASE_STATE,
  REVIEW_STATE,
  REVIEW_OUTCOME,
  COMMENT_STATE,
  SEVERITY,
  PERMIT_STATE,
  CONDITION_STATE,
  WBS_KIND,
  DIST_FORMAT,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(t: TFn, map: Record<T, KeyText>, code: T | '' | null | undefined): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/** The options of a select built from a vocabulary, in the order the map lists them. */
export function vocabOptions<T extends string>(t: TFn, map: Record<T, KeyText>): Array<{ value: T; label: string }> {
  return (Object.keys(map) as T[]).map((code) => ({ value: code, label: vocab(t, map, code) }));
}

/**
 * A code written for a reader: `structural_design` becomes "Structural design".
 *
 * The last resort when neither the API nor the locale names the item. It is
 * never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function fromTexts(texts: Record<string, string> | null | undefined, language: string): string {
  if (!texts) return '';
  const lang = language.split('-')[0] ?? 'en';
  return texts[language] ?? texts[lang] ?? texts.en ?? Object.values(texts)[0] ?? '';
}

/**
 * The name of a catalogue item: its message key in the locale first, then the
 * texts the catalogue carries, then the code made readable.
 */
export function catalogueLabel(
  ctx: LabelContext,
  item: { key?: string | null; labels?: Record<string, string> | null; code: string },
): string {
  if (item.key && ctx.exists(item.key)) return ctx.t(item.key);
  return fromTexts(item.labels, ctx.language) || humanizeCode(item.code);
}

/** The name of a picker choice: its key in the locale, then the texts it carries, then its plain label. */
export function optionLabel(ctx: LabelContext, item: DesignOption): string {
  if (item.label_key && ctx.exists(item.label_key)) return ctx.t(item.label_key);
  return fromTexts(item.label_text, ctx.language) || item.label || item.code || item.id;
}

export function labelOf(ctx: LabelContext, label: DesignLabel | null | undefined, code: string): string {
  return catalogueLabel(ctx, { key: label?.key, labels: label?.text, code });
}

export function schemeName(ctx: LabelContext, scheme: Pick<NumberingScheme, 'id' | 'name_key' | 'labels'>): string {
  return catalogueLabel(ctx, { key: scheme.name_key, labels: scheme.labels, code: scheme.id });
}

export function fieldLabel(ctx: LabelContext, field: NumberingField): string {
  return catalogueLabel(ctx, { key: field.label_key, labels: field.labels, code: field.code });
}

export function phaseName(ctx: LabelContext, phases: DesignPhase[], code: string | null | undefined): string {
  if (!code) return '';
  const phase = phases.find((p) => p.code === code);
  return phase ? labelOf(ctx, phase.name, code) : humanizeCode(code);
}

export function reportKindName(ctx: LabelContext, catalogue: ReportsCatalogue, code: string): string {
  const kind = catalogue.report_kinds.find((k) => k.code === code);
  return catalogueLabel(ctx, {
    key: kind?.name_key || ['design', 'catalogue', 'report', code].join('.'),
    labels: kind?.labels,
    code,
  });
}

export function permitProfileName(ctx: LabelContext, catalogue: ReportsCatalogue, code: string): string {
  const profile = catalogue.permit_steps.find((p) => p.code === code);
  return catalogueLabel(ctx, {
    key: profile?.name_key || ['design', 'catalogue', 'permit_profile', code].join('.'),
    labels: profile?.labels,
    code,
  });
}

/** The sentence for a refusal code, translated when the locale has it, else what the server wrote. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const english = ERROR_TEXT[code] ?? serverMessage ?? humanizeCode(code);
  return t(['design', 'errors', code].join('.'), { defaultValue: english });
}
