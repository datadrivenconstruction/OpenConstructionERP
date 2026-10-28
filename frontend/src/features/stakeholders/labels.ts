// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the stakeholder screens show for a code. Catalogue items
// (categories, classes, levels, roles, decision types) are named by the pinned
// framework; the closed vocabularies (statuses, letters, flags) are written as
// key maps rather than built from the code at runtime, so the key test can
// enumerate them and a translator can find every key by grep.

import type {
  CommitmentStatus,
  EventStatus,
  FrameworkItem,
  Letter,
  PlanStatus,
  QuorumKind,
  ReadinessCode,
  StakeholderStatus,
} from './api';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const STAKEHOLDER_STATUS: Record<StakeholderStatus, KeyText> = {
  active: ['stakeholders.ui.status.active', 'Active'],
  dormant: ['stakeholders.ui.status.dormant', 'Dormant'],
  archived: ['stakeholders.ui.status.archived', 'Archived'],
};

export const COMMITMENT_STATUS: Record<CommitmentStatus, KeyText> = {
  proposed: ['stakeholders.commitment_status.proposed', 'Proposed'],
  agreed: ['stakeholders.commitment_status.agreed', 'Agreed'],
  in_progress: ['stakeholders.commitment_status.in_progress', 'In progress'],
  fulfilled: ['stakeholders.commitment_status.fulfilled', 'Fulfilled'],
  verified: ['stakeholders.commitment_status.verified', 'Verified'],
  withdrawn: ['stakeholders.commitment_status.withdrawn', 'Withdrawn'],
  breached: ['stakeholders.commitment_status.breached', 'Breached'],
};

/** What pressing a transition does, as the button says it. */
export const COMMITMENT_ACTION: Record<Exclude<CommitmentStatus, 'proposed'>, KeyText> = {
  agreed: ['stakeholders.ui.commitment.action.agreed', 'Agree'],
  in_progress: ['stakeholders.ui.commitment.action.in_progress', 'Start work'],
  fulfilled: ['stakeholders.ui.commitment.action.fulfilled', 'Mark fulfilled'],
  verified: ['stakeholders.ui.commitment.action.verified', 'Verify and close'],
  withdrawn: ['stakeholders.ui.commitment.action.withdrawn', 'Withdraw'],
  breached: ['stakeholders.ui.commitment.action.breached', 'Confirm breach'],
};

export const COMMITMENT_CATEGORY: Record<string, KeyText> = {
  noise: ['stakeholders.commitment_category.noise', 'Noise'],
  traffic: ['stakeholders.commitment_category.traffic', 'Traffic'],
  working_hours: ['stakeholders.commitment_category.working_hours', 'Working hours'],
  information: ['stakeholders.commitment_category.information', 'Information'],
  compensation: ['stakeholders.commitment_category.compensation', 'Compensation'],
  design_change: ['stakeholders.commitment_category.design_change', 'Design change'],
  access: ['stakeholders.commitment_category.access', 'Access'],
  environment: ['stakeholders.commitment_category.environment', 'Environment'],
  other: ['stakeholders.commitment_category.other', 'Other'],
};

export const PLAN_STATUS: Record<PlanStatus, KeyText> = {
  planned: ['stakeholders.plan_status.planned', 'Planned'],
  active: ['stakeholders.plan_status.active', 'Active'],
  paused: ['stakeholders.plan_status.paused', 'Paused'],
  completed: ['stakeholders.plan_status.completed', 'Completed'],
  cancelled: ['stakeholders.plan_status.cancelled', 'Cancelled'],
};

export const EVENT_STATUS: Record<EventStatus, KeyText> = {
  planned: ['stakeholders.ui.event_status.planned', 'Planned'],
  held: ['stakeholders.ui.event_status.held', 'Held'],
  cancelled: ['stakeholders.ui.event_status.cancelled', 'Cancelled'],
};

export const READINESS: Record<ReadinessCode, KeyText> = {
  register_present: ['stakeholders.evidence.register_present', 'At least one external stakeholder is assessed'],
  key_stakeholders_planned: [
    'stakeholders.evidence.key_stakeholders_planned',
    'Every key stakeholder with an engagement gap has a communication plan',
  ],
  mandates_complete: [
    'stakeholders.evidence.mandates_complete',
    'Every required decision type has one deciding role or body',
  ],
  roles_filled: ['stakeholders.evidence.roles_filled', 'No required role is vacant'],
  commitments_tracked: ['stakeholders.evidence.commitments_tracked', 'No commitment is breached without a rationale'],
};

/** The five letters of the mandate matrix, spelled out. */
export const LETTER: Record<Letter, KeyText> = {
  P: ['stakeholders.ui.letter.p', 'Proposes'],
  D: ['stakeholders.ui.letter.d', 'Decides'],
  A: ['stakeholders.ui.letter.a', 'Approves alongside'],
  C: ['stakeholders.ui.letter.c', 'Is consulted'],
  I: ['stakeholders.ui.letter.i', 'Is informed'],
};

export const QUORUM: Record<QuorumKind, KeyText> = {
  min_members: ['stakeholders.ui.quorum.min_members', 'A minimum number of members'],
  majority: ['stakeholders.ui.quorum.majority', 'More than half of the voting members'],
  unanimous: ['stakeholders.ui.quorum.unanimous', 'Every voting member'],
};

/** Flags the who-decides lookup may answer with. */
export const DECIDER_FLAG: Record<string, KeyText> = {
  mandate_missing: ['stakeholders.ui.flag.mandate_missing', 'Nobody is marked as the one who decides this.'],
  role_vacant: ['stakeholders.ui.flag.role_vacant', 'The deciding role has no holder today.'],
  unknown_body: ['stakeholders.ui.flag.unknown_body', 'The deciding body no longer exists.'],
  body_inquorate: ['stakeholders.ui.flag.body_inquorate', 'The deciding body has too few valid members to decide.'],
  authority_not_evaluated: [
    'stakeholders.ui.flag.authority_not_evaluated',
    'The amount limit could not be checked, because no authority schedule is connected.',
  ],
};

/** Where a commitment was made. */
export const COMMITMENT_SOURCE: Record<string, KeyText> = {
  manual: ['stakeholders.ui.source.manual', 'Nowhere on record'],
  event: ['stakeholders.ui.source.event', 'At a recorded stakeholder event'],
  meeting: ['stakeholders.ui.source.meeting', 'In a project meeting'],
  correspondence: ['stakeholders.ui.source.correspondence', 'In a letter'],
  permit_condition: ['stakeholders.ui.source.permit_condition', 'As a condition of a permit'],
};

/** Why a document cannot be filed for the gate right now. */
export const FILE_BLOCK: Record<string, KeyText> = {
  no_permission: ['stakeholders.ui.file_block.no_permission', 'Your role can download this document but not file it for the gate.'],
  frame_document_missing: [
    'stakeholders.ui.file_block.frame_document_missing',
    'The gate has no place to file this document yet. Attach a document container to its frame document on the project governance screen first.',
  ],
  frame_document_read_only: [
    'stakeholders.ui.file_block.frame_document_read_only',
    'The project is stopped, so its frame documents take no new revision until it resumes.',
  ],
};

/** Why the server will not let the reader make a move on a commitment. */
export const COMMITMENT_BLOCK: Record<string, KeyText> = {
  no_permission: ['stakeholders.ui.block.no_permission', 'Your role can view commitments but not change them.'],
  approval_pending: ['stakeholders.ui.block.approval_pending', 'An approval is still running for this commitment.'],
  owner_and_due_required: ['stakeholders.ui.block.owner_and_due_required', 'Set an owner and a due date first.'],
  owner_cannot_verify: [
    'stakeholders.ui.block.owner_cannot_verify',
    'The owner of a commitment cannot verify it. Someone else has to.',
  ],
  mandate_missing: [
    'stakeholders.ui.block.mandate_missing',
    'The mandate matrix names nobody who decides commitments to stakeholders.',
  ],
  body_inquorate: ['stakeholders.ui.block.body_inquorate', 'The deciding body has too few valid members to decide.'],
  not_decider: ['stakeholders.ui.block.not_decider', 'Only whoever decides commitments to stakeholders can do this.'],
};

/** Notes a write on the organisation or a commitment may come back with. */
export const WRITE_NOTE: Record<string, KeyText> = {
  frame_document_binding: [
    'stakeholders.ui.note.frame_document_binding',
    'The organisation document is already binding at a gate. File a new revision so the gate record matches.',
  ],
  area_owner_was_previous_holder: [
    'stakeholders.ui.note.area_owner_was_previous_holder',
    'The previous holder still owns a management area in project governance. Check the area owners.',
  ],
  release_item_not_checked: [
    'stakeholders.ui.note.release_item_not_checked',
    'This commitment has a cost, and nothing checked it against a release item.',
  ],
  no_commitment_matrix: [
    'stakeholders.ui.note.no_commitment_matrix',
    'This commitment has a cost, and the project has no commitment matrix to release it from.',
  ],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  STAKEHOLDER_STATUS,
  COMMITMENT_STATUS,
  COMMITMENT_ACTION,
  COMMITMENT_CATEGORY,
  PLAN_STATUS,
  EVENT_STATUS,
  READINESS,
  LETTER,
  QUORUM,
  DECIDER_FLAG,
  COMMITMENT_SOURCE,
  COMMITMENT_BLOCK,
  FILE_BLOCK,
  WRITE_NOTE,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab(t: TFn, map: Record<string, KeyText>, code: string | null | undefined): string {
  if (!code) return '';
  const entry = map[code];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/**
 * A catalogue code written for a reader: `keep_informed` becomes "Keep informed".
 *
 * The last resort when neither the framework nor the locale names the item. It
 * is never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * The name of a framework item: the tenant's own text in the reader's language
 * first, then the shipped message key, then the code.
 */
export function itemName(
  ctx: LabelContext,
  item: Pick<FrameworkItem, 'code'> & Partial<Pick<FrameworkItem, 'name_key' | 'labels'>>,
): string {
  if (item.labels) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    const text = item.labels[ctx.language] ?? item.labels[lang] ?? item.labels.en;
    if (text) return text;
  }
  if (item.name_key && ctx.exists(item.name_key)) return ctx.t(item.name_key);
  return humanizeCode(item.code);
}

/** The name of a code looked up in one list of the framework; an unknown code reads humanised. */
export function nameOf(ctx: LabelContext, list: readonly FrameworkItem[], code: string | null | undefined): string {
  if (!code) return '';
  const item = list.find((x) => x.code === code);
  return item ? itemName(ctx, item) : humanizeCode(code);
}

/**
 * The sentence for a refusal code. The server already wrote it in the
 * reader's language; the locale key covers a request that failed before it
 * could, and the humanised code is the floor.
 */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  return t(['stakeholders', 'errors', code].join('.'), { defaultValue: serverMessage || humanizeCode(code) });
}
