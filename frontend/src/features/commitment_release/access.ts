// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who may press which commitment button, and in words why not.
//
// The server decides and says so. Each item carries `can`, and the project
// answers `capabilities` for what is not about one item (starting or changing
// the matrix, adding an item, saving a scenario). Every flag is computed by
// the function that enforces the write and carries the refusal code when the
// answer is no. The screens read the flag and never work the answer out again
// from a role, an owner or a state.

import type { CanFlag, CommitmentItem, ItemAction, ProjectAction, ProjectCan } from './api';
import type { KeyText } from './labels';

/**
 * null means allowed; otherwise the refusal code the server gave, or
 * `unavailable` when it gave no answer at all.
 */
export type Verdict = string | null;

/** The server did not send the flag. The action stays off: an absent answer is not a yes. */
export const UNAVAILABLE = 'unavailable';

/** The answer is on its way. The action stays off, and the reason says to wait rather than that it is refused. */
export const CHECKING = 'checking';

/**
 * Why a button is off, where a sentence written for the button reads better
 * than the refusal sentence of the same code. A code that is not here is shown
 * with its refusal sentence (`commitment.errors.<code>`).
 */
export const DISABLED_REASON: Record<string, KeyText> = {
  edit_required: [
    'commitment.disabled.edit_required',
    'Your role can view the commitments but not change them. An editor or manager can.',
  ],
  manage_required: ['commitment.disabled.manage_required', 'Only a project manager can do this.'],
  matrix_missing: ['commitment.disabled.matrix_missing', 'Start the commitment matrix first.'],
  not_item_owner: ['commitment.disabled.not_item_owner', 'Only the owner of this item or a project manager can do this.'],
  not_requester: [
    'commitment.disabled.not_requester',
    'Only the person who made the request or a project manager can withdraw it.',
  ],
  release_pending: [
    'commitment.disabled.release_pending',
    'A request for this item is waiting for a decision. Wait for it or withdraw it first.',
  ],
  no_pending_release: ['commitment.disabled.no_pending_release', 'There is no request waiting for a decision.'],
  invalid_transition: ['commitment.disabled.invalid_transition', 'This is not possible in the current state of the item.'],
  item_closed: ['commitment.disabled.item_closed', 'This item was aborted or transferred and can no longer change.'],
  not_entitled_decider: [
    'commitment.disabled.not_entitled_decider',
    'You are not an approver of the tier this request needs.',
  ],
  four_eyes_violation: [
    'commitment.disabled.four_eyes_violation',
    'Four eyes: whoever made the request, owns the item or confirmed one of its preconditions cannot decide it.',
  ],
  field_frozen: ['commitment.disabled.field_frozen', 'This can change only while the item is still planned.'],
  [UNAVAILABLE]: ['commitment.disabled.unavailable', 'The server did not say whether this is allowed.'],
  [CHECKING]: ['commitment.disabled.checking', 'Checking what you may do here.'],
};

/** Every refusal code the server puts into a flag. A test holds each of them to a sentence in both locales. */
export const CAN_REASONS = [
  'not_item_owner',
  'item_closed',
  'release_pending',
  'invalid_transition',
  'no_pending_release',
  'not_requester',
  'manage_required',
  'edit_required',
  'matrix_missing',
  'field_frozen',
  'not_entitled_decider',
  'four_eyes_violation',
] as const;

/** Read one capability flag. A missing flag or a refusal without a code both deny. */
export function verdictOf(flag: CanFlag | null | undefined): Verdict {
  if (!flag) return UNAVAILABLE;
  if (flag.allowed) return null;
  return flag.reason || UNAVAILABLE;
}

export function itemVerdict(item: Pick<CommitmentItem, 'can'>, action: ItemAction): Verdict {
  return verdictOf(item.can?.[action]);
}

/** Put on hold or resume: one button, two server flags. */
export function holdVerdict(item: Pick<CommitmentItem, 'can' | 'status'>): Verdict {
  return itemVerdict(item, item.status === 'on_hold' ? 'resume' : 'hold');
}

/** What is not about one item: the matrix and its setup, a new item, a saved scenario. */
export function projectVerdict(can: ProjectCan | null | undefined, action: ProjectAction): Verdict {
  // `undefined` is a request still running; `null` is a request that failed.
  if (can === undefined) return CHECKING;
  return verdictOf(can?.[action]);
}
