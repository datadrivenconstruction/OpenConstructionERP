// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which delivery model button may be pressed, and in words why not.
//
// The server decides and says so: the model carries `can`, one answer per
// action, computed by the same function that enforces it. A verdict here is
// that answer, so a button never disagrees with the request behind it. The
// reason is the server's refusal code and is worded by
// `delivery_model.errors.<code>`.
//
// Two things the flags do not cover:
// - Starting a model. There is no model yet, so nothing carries a flag, and
//   the role is the only thing known (delivery_model.manage is the manager).
// - Risk allocations, packages and owner-furnished items stay editable while
//   a decision is proposed, where `can.edit` (the comparison) already says no.
//   For those the state half of `can.edit` is replaced by the status rule the
//   API documents; the permission half is kept as sent.

import type { Capability, DeliveryModel, ModelAction } from './api';
import type { KeyText } from './labels';
import { allocationsFrozen } from './rules';
import { ROLE_ALIASES, ROLE_RANK } from '@/shared/lib/roles';

export type DeliveryLevel = 'read' | 'edit' | 'manage';

const LEVEL_RANK: Record<DeliveryLevel, number> = { read: 0, edit: 1, manage: 2 };

/**
 * Whether a role reaches a level. No role and an unknown role both deny: an
 * absent role is not the viewer role here, because `read` sits at the
 * viewer's rank.
 */
export function roleAllows(role: string | null | undefined, level: DeliveryLevel): boolean {
  if (!role) return false;
  const r = role.trim().toLowerCase();
  const canonical = ROLE_ALIASES[r] ?? r;
  const rank = (ROLE_RANK as Record<string, number>)[canonical];
  if (rank === undefined) return false;
  return rank >= LEVEL_RANK[level];
}

/** Reasons this screen words itself. Every other reason is a server code. */
export const DISABLED_REASON: Record<string, KeyText> = {
  role_manage: ['delivery_model.ui.disabled.role_manage', 'Only a project manager can do this.'],
};

/** null means allowed; otherwise the reason that stops the action. */
export type Verdict = string | null;

export interface Viewer {
  userId: string | null;
  role: string | null;
}

type CanModel = Pick<DeliveryModel, 'can'>;
type CanAndStatus = Pick<DeliveryModel, 'can' | 'status'>;

/** A flag that did not arrive denies: an unknown answer is not a yes. */
function verdictOf(flag: Capability | undefined): Verdict {
  if (!flag) return 'permission_missing';
  return flag.allowed ? null : (flag.reason ?? 'permission_missing');
}

/**
 * Whether the action exists in this state at all. When it does not, the screen
 * shows nothing for it: no disabled button and no reason. A flag that did not
 * arrive, or one without `applies`, counts as existing, so it is shown and
 * denied rather than silently dropped.
 */
export function actionApplies(model: CanModel, action: ModelAction): boolean {
  return model.can?.[action]?.applies !== false;
}

/** Reasons about the person, not about the state of the model. */
const PERSON_REASONS = new Set(['permission_missing', 'not_area_owner']);

/** The verdict when only the person can stop the action. */
export function personOnly(verdict: Verdict): Verdict {
  return verdict && PERSON_REASONS.has(verdict) ? verdict : null;
}

/** Starting the model: nothing carries a flag before a model exists. */
export function canManage(viewer: Viewer): Verdict {
  return roleAllows(viewer.role, 'manage') ? null : 'role_manage';
}

/** Options, weights, scores and the owner situation. */
export function canEditComparison(model: CanModel): Verdict {
  return verdictOf(model.can?.edit);
}

export function canPropose(model: CanModel): Verdict {
  return verdictOf(model.can?.propose);
}

export function canWithdraw(model: CanModel): Verdict {
  return verdictOf(model.can?.withdraw);
}

export function canReopen(model: CanModel): Verdict {
  return verdictOf(model.can?.reopen);
}

export function canCloseReopening(model: CanModel): Verdict {
  return verdictOf(model.can?.close_reopening);
}

/**
 * Pinning another catalogue has no flag of its own. It needs the right to
 * propose and a model that can still be proposed for, and nothing else: a
 * missing carrier document or a comparison that is not ready does not stop it.
 */
export function canChangeCatalogue(model: CanModel): Verdict {
  const verdict = verdictOf(model.can?.propose);
  const person = personOnly(verdict);
  if (person) return person;
  return actionApplies(model, 'propose') ? null : (verdict ?? 'model_not_editable');
}

/** Risk allocations, packages and owner-furnished items: open until the decision is approved. */
export function canEditPlan(model: CanAndStatus): Verdict {
  const person = personOnly(verdictOf(model.can?.edit));
  if (person) return person;
  return allocationsFrozen(model.status) ? 'model_not_editable' : null;
}

export const canEditAllocations = canEditPlan;
