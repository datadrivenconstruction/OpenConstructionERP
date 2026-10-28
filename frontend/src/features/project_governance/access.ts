// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who may press which governance button, and in words why not.
//
// The server decides. Every permission here is read from a `can` flag the
// server sent (model, gate detail, condition, frame document), because only
// the server knows the caller's permissions, the route entitlement and the
// four-eyes rule. Nothing is derived from the role name. What the client adds
// is what holds for everyone and reads better said first: the gate's state, a
// stopped project, an area without an owner. Where the server sends no flag,
// the button stays enabled and the server's refusal is shown after the click.

import type {
  FrameDocument,
  GateArea,
  GateDetail,
  GovernanceArea,
  GovernanceCondition,
  GovernanceGate,
  GovernanceModel,
  Outcome,
} from './api';
import type { KeyText } from './labels';

export type DisabledReason =
  | 'role_edit'
  | 'role_manage'
  | 'role_decide'
  | 'four_eyes'
  | 'gate_not_in_review'
  | 'gate_not_ready_to_submit'
  | 'project_stopped'
  | 'area_without_owner'
  | 'not_area_owner'
  | 'area_not_applicable'
  | 'condition_closed'
  | 'not_condition_owner'
  | 'document_without_file';

export const DISABLED_REASON: Record<DisabledReason, KeyText> = {
  role_edit: ['governance.project.disabled.role_edit', 'Your role can view governance but not edit it. An editor or manager can.'],
  role_manage: ['governance.project.disabled.role_manage', 'Only a project manager can change this.'],
  role_decide: [
    'governance.project.disabled.role_decide',
    'Only a manager named on the gate approval route can decide a gate.',
  ],
  four_eyes: [
    'governance.project.disabled.four_eyes',
    'Four-eyes rule: you own or deputise an area of this gate, so someone else has to decide it.',
  ],
  gate_not_in_review: [
    'governance.project.disabled.gate_not_in_review',
    'Submit the gate for review first. A decision is recorded on a gate in review.',
  ],
  gate_not_ready_to_submit: [
    'governance.project.disabled.gate_not_ready_to_submit',
    'Only a gate in preparation can be submitted for review.',
  ],
  project_stopped: ['governance.project.disabled.project_stopped', 'The project was stopped at a gate.'],
  area_without_owner: [
    'governance.project.disabled.area_without_owner',
    'This area has no owner yet. Assign one on the area page, then the owner confirms readiness.',
  ],
  not_area_owner: [
    'governance.project.disabled.not_area_owner',
    'Only the owner or deputy of this area confirms its readiness.',
  ],
  area_not_applicable: [
    'governance.project.disabled.area_not_applicable',
    'This area is marked not applicable for the project.',
  ],
  condition_closed: ['governance.project.disabled.condition_closed', 'This condition is already closed.'],
  not_condition_owner: [
    'governance.project.disabled.not_condition_owner',
    'Only the condition owner or a manager can clear it.',
  ],
  document_without_file: [
    'governance.project.disabled.document_without_file',
    'Attach a file first. A document goes to gate review with a file behind it.',
  ],
};

/** null means allowed; otherwise the first reason that stops the action. */
/**
 * A refusal the server named with a code this screen has no reason for. It is
 * shown through `governance.errors.<code>` or a neutral sentence, never mapped
 * onto a known reason: a plausible wrong reason is worse than none.
 */
export interface ServerRefusal {
  server: string;
}

export type Verdict = DisabledReason | ServerRefusal | null;

export interface Viewer {
  userId: string | null;
}

function ownsArea(viewer: Viewer, area: Pick<GateArea, 'owner_user_id' | 'deputy_user_id'>): boolean {
  return !!viewer.userId && (area.owner_user_id === viewer.userId || area.deputy_user_id === viewer.userId);
}

/** Server refusal codes that name a reason the screen can explain. */
const REASON_OF_CODE: Record<string, DisabledReason> = {
  decider_is_area_owner: 'four_eyes',
  decider_not_entitled: 'role_decide',
  gate_not_in_review: 'gate_not_in_review',
  project_stopped: 'project_stopped',
  not_area_owner: 'not_area_owner',
  area_without_owner: 'area_without_owner',
  not_condition_owner: 'not_condition_owner',
  condition_not_open: 'condition_closed',
};

/** Which permission an action needs, so `missing_permission` names the right one. */
export type PermissionLevel = 'edit' | 'decide' | 'manage';

const MISSING_PERMISSION: Record<PermissionLevel, DisabledReason> = {
  edit: 'role_edit',
  decide: 'role_decide',
  manage: 'role_manage',
};

/**
 * The verdict for a server refusal code: a known reason, or the code itself
 * for the screen to resolve. `missing_permission` says only that a permission
 * is missing, so the caller names which one the action needs.
 */
export function reasonOfCode(
  code: string | null | undefined,
  permission: PermissionLevel = 'decide',
): DisabledReason | ServerRefusal {
  if (code === 'missing_permission') return MISSING_PERMISSION[permission];
  return (code && REASON_OF_CODE[code]) || { server: code ?? '' };
}

/** A flag the server sent with an optional refusal code, read as a verdict. */
function flagVerdict(
  allowed: boolean | null | undefined,
  reason: string | null | undefined,
  permission: PermissionLevel,
): Verdict {
  return allowed ? null : reasonOfCode(reason, permission);
}

/**
 * The server refuses to change the four-eyes rule or whether an area applies
 * while a gate of the current model is in review or on hold, because either
 * would change who may decide a gate that is already with its deciders. The
 * screen says so before the click; the server stays the one that enforces it.
 */
export function frozenInReview(gates: ReadonlyArray<Pick<GovernanceGate, 'status' | 'historic'>>): Verdict {
  const held = gates.some((g) => !g.historic && (g.status === 'in_review' || g.status === 'on_hold'));
  return held ? { server: 'settings_frozen_in_review' } : null;
}

/** Manage rights, as the server reports them on the model. */
export function canManage(model: Pick<GovernanceModel, 'can'>): Verdict {
  return model.can.manage ? null : 'role_manage';
}

export function canSubmitGate(model: GovernanceModel, detail: GateDetail): Verdict {
  if (!detail.can.edit) return 'role_edit';
  if (model.stopped) return 'project_stopped';
  if (detail.gate.status !== 'in_preparation') return 'gate_not_ready_to_submit';
  return null;
}

/**
 * Whether the viewer may open the decision dialog on this gate.
 *
 * Gate state and a stopped project explain first, because they hold for
 * everyone; then the server's answer, which knows route entitlement and
 * four-eyes. A refusal code this screen does not know travels as is.
 */
export function canDecide(model: GovernanceModel, detail: GateDetail): Verdict {
  if (model.stopped) return 'project_stopped';
  if (detail.gate.status !== 'in_review') return 'gate_not_in_review';
  return detail.can.decide ? null : reasonOfCode(detail.can.decide_reason);
}

/**
 * Whether the caller may record this one outcome, by the server's flag for it.
 *
 * `can.decide` only says that some outcome is open to the caller. Which ones
 * differs: on a route that is already approved a go is still open and a stop
 * is not. An outcome the server did not answer for is left to the request.
 */
export function outcomeVerdict(detail: Pick<GateDetail, 'can'>, outcome: Outcome): Verdict {
  const flag = detail.can.outcomes?.[outcome];
  if (!flag) return null;
  return flagVerdict(flag.allowed, flag.reason, 'decide');
}

/** Resuming a held gate, as the server reports it on the gate. */
export function canResume(detail: Pick<GateDetail, 'can'>): Verdict {
  return flagVerdict(detail.can.resume, detail.can.resume_reason, 'decide');
}

/** Reopening a decided gate, as the server reports it on the gate. */
export function canReopen(detail: Pick<GateDetail, 'can'>): Verdict {
  return flagVerdict(detail.can.reopen, detail.can.reopen_reason, 'decide');
}

/** Adding a condition to a gate passed with conditions, as the server reports it on the gate. */
export function canAddCondition(detail: Pick<GateDetail, 'can'>): Verdict {
  return flagVerdict(detail.can.add_condition, detail.can.add_condition_reason, 'decide');
}

export function canConfirmCheck(
  viewer: Viewer,
  model: GovernanceModel,
  area: GateArea,
  detail: Pick<GateDetail, 'can'>,
): Verdict {
  if (!detail.can.edit) return 'role_edit';
  if (model.stopped) return 'project_stopped';
  if (!area.applicable) return 'area_not_applicable';
  if (!area.owner_user_id) return 'area_without_owner';
  if (!ownsArea(viewer, area)) return 'not_area_owner';
  return null;
}

export function canEditArea(model: Pick<GovernanceModel, 'can'>): Verdict {
  return canManage(model);
}

export type DocumentAction = 'attach' | 'submit' | 'return';

/**
 * Whether a frame document action is open to the caller.
 *
 * A document without a file cannot be submitted by anybody, which is said
 * first. Then the server's flag on the document decides: it knows the edit
 * permission and whether the caller owns the area. Without a flag nothing is
 * guessed: the button is open and the server's refusal shows after the click.
 */
export function documentVerdict(doc: Pick<FrameDocument, 'can' | 'container_id'>, action: DocumentAction): Verdict {
  if (action === 'submit' && !doc.container_id) return 'document_without_file';
  if (!doc.can) return null;
  const reason = doc.can[`${action}_reason` as const];
  return flagVerdict(doc.can[action], reason, 'edit');
}

/**
 * Tracking a further frame document follows the area's own flag: the server
 * knows the edit permission, who owns the area and whether it is retired.
 * Without a flag nothing is guessed and the server's refusal shows after the click.
 */
export function canAddDocument(area: Pick<GovernanceArea, 'can'>): Verdict {
  if (!area.can) return null;
  return flagVerdict(area.can.add_document, area.can.add_document_reason, 'edit');
}

/** Raising a change request follows the document's own flag; the route then decides who approves it. */
export function canRaiseChange(doc: Pick<FrameDocument, 'can'>): Verdict {
  if (!doc.can || doc.can.change_request === undefined) return null;
  return flagVerdict(doc.can.change_request, doc.can.change_request_reason, 'edit');
}

/** Clearing follows the condition's own flag: the edit permission plus owner-or-manager, checked by the server. */
export function canClearCondition(condition: GovernanceCondition): Verdict {
  if (condition.status === 'cleared' || condition.status === 'waived') return 'condition_closed';
  return flagVerdict(condition.can.clear, condition.can.clear_reason, 'edit');
}

/** Waiving follows the condition's own flag, which the server sets from the decide permission. */
export function canWaiveCondition(condition: GovernanceCondition): Verdict {
  if (condition.status === 'cleared' || condition.status === 'waived') return 'condition_closed';
  return flagVerdict(condition.can.waive, condition.can.waive_reason, 'decide');
}
