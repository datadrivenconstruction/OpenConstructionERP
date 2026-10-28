// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * NCR status lifecycle (FSM), mirrored from the backend.
 *
 * The single source of truth lives in the API layer
 * (backend/app/modules/ncr/service.py :: _NCR_STATUS_TRANSITIONS). This module
 * re-declares the same graph so the lifecycle stepper offers only moves the API
 * will actually accept, and never renders an action the backend would reject
 * with a 400.
 *
 * The happy path runs identified -> under_review -> corrective_action ->
 * verification -> closed. `void` is an off-ramp reachable from any pre-closed
 * state; it is a terminal state kept off the linear stage track.
 */

import type { NCRStatus } from './api';

/**
 * Canonical lifecycle order (the happy path through the FSM). Used to lay the
 * stepper out left to right and to tell "done" stages from "upcoming" ones.
 * `void` is deliberately excluded - it is a terminal off-ramp, not a stage.
 */
export const NCR_STAGES: readonly NCRStatus[] = [
  'identified',
  'under_review',
  'corrective_action',
  'verification',
  'closed',
] as const;

/**
 * Legal next statuses for each current status. Mirrors the backend
 * _NCR_STATUS_TRANSITIONS exactly. Terminal states (`closed`, `void`) have no
 * outgoing moves.
 */
export const NCR_FSM_NEXT: Record<NCRStatus, readonly NCRStatus[]> = {
  identified: ['under_review', 'void'],
  under_review: ['corrective_action', 'identified', 'void'],
  corrective_action: ['verification', 'under_review', 'void'],
  verification: ['closed', 'corrective_action'],
  closed: [],
  void: [],
};

/** Index of a status within {@link NCR_STAGES} (-1 for `void`, which is not a
 *  stage on the linear track). */
export function ncrStageIndex(status: NCRStatus): number {
  return NCR_STAGES.indexOf(status);
}

/**
 * Split the legal moves from `status` into forward steps (later in the
 * lifecycle), backward steps (earlier, i.e. send-back), and whether the NCR can
 * be voided. Forward moves are the primary actions, backward moves are
 * secondary, and void is a destructive escape hatch. The move to `closed` is a
 * forward move but the UI routes it through the dedicated close endpoint (which
 * enforces the corrective-action requirement), not a plain status PATCH.
 */
export function ncrNextMoves(status: NCRStatus): {
  forward: NCRStatus[];
  backward: NCRStatus[];
  canVoid: boolean;
} {
  const here = ncrStageIndex(status);
  const forward: NCRStatus[] = [];
  const backward: NCRStatus[] = [];
  let canVoid = false;
  for (const next of NCR_FSM_NEXT[status] ?? []) {
    if (next === 'void') {
      canVoid = true;
      continue;
    }
    if (ncrStageIndex(next) > here) forward.push(next);
    else backward.push(next);
  }
  return { forward, backward, canVoid };
}
