// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Punch list status lifecycle (FSM), mirrored from the backend.
 *
 * The single source of truth lives in the API layer
 * (backend/app/modules/punchlist/service.py :: VALID_TRANSITIONS). This module
 * re-declares the same graph so the closure stepper and the list/kanban quick
 * actions offer only moves the API will actually accept, and never render an
 * action the backend would reject with a 400.
 */

import type { PunchStatus } from './api';

/**
 * Canonical closure lifecycle order (the happy path through the FSM). Used to
 * lay the stepper out left to right and to tell "done" stages from "upcoming"
 * ones. Reopen jumps back to `open`, which is index 0.
 */
export const PUNCH_STAGES: readonly PunchStatus[] = [
  'open',
  'assigned',
  'in_progress',
  'resolved',
  'verified',
  'closed',
] as const;

/**
 * Legal next statuses for each current status. Mirrors the backend
 * VALID_TRANSITIONS plus the universal reopen: every status may move back to
 * `open`. `open` itself is only a forward origin (no self-move offered).
 */
export const PUNCH_FSM_NEXT: Record<PunchStatus, readonly PunchStatus[]> = {
  open: ['assigned', 'in_progress'],
  assigned: ['in_progress', 'open'],
  // The backend also accepts in_progress -> verified, but only when the
  // deployment lets a verifier sign off their own work
  // (`punchlist_verify_policy`). Under the default four-eyes rule the item has
  // to be resolved first, so the shortcut is never offered here.
  in_progress: ['resolved', 'assigned', 'open'],
  resolved: ['verified', 'open'],
  verified: ['closed', 'open'],
  closed: ['open'],
};

/** Index of a status within {@link PUNCH_STAGES} (0 when unknown). */
export function punchStageIndex(status: PunchStatus): number {
  const i = PUNCH_STAGES.indexOf(status);
  return i < 0 ? 0 : i;
}

/**
 * Split the legal moves from `status` into forward steps (later in the
 * lifecycle) and backward steps (earlier, i.e. reopen / unassign). Forward
 * moves are the primary actions; backward moves are the secondary ones.
 */
export function punchNextMoves(status: PunchStatus): {
  forward: PunchStatus[];
  backward: PunchStatus[];
} {
  const here = punchStageIndex(status);
  const forward: PunchStatus[] = [];
  const backward: PunchStatus[] = [];
  for (const next of PUNCH_FSM_NEXT[status] ?? []) {
    if (punchStageIndex(next) > here) forward.push(next);
    else backward.push(next);
  }
  return { forward, backward };
}
