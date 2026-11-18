// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Task status moves the server accepts, in lockstep with
 * `backend/app/modules/tasks/service.py:_TASK_STATUS_TRANSITIONS`.
 *
 * A draft may go straight to work or to done (it is issued on the way), so a
 * drag from the Draft column to In progress or Completed is a real move, not a
 * refusal. The status menu, the board and the complete button all read this map.
 */
import type { TaskStatus } from './api';

export const BUILTIN_STATUSES: TaskStatus[] = ['draft', 'open', 'in_progress', 'completed'];

export const STATUS_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  draft: ['open', 'in_progress', 'completed'],
  open: ['in_progress', 'completed', 'draft'],
  in_progress: ['completed', 'open'],
  completed: ['open', 'in_progress'],
};

/** True when the move is allowed; a move touching a custom status is never blocked here. */
export function canMoveStatus(from: string, to: string): boolean {
  if (from === to) return true;
  const builtinFrom = BUILTIN_STATUSES.includes(from as TaskStatus);
  const builtinTo = BUILTIN_STATUSES.includes(to as TaskStatus);
  if (!builtinFrom || !builtinTo) return true;
  return STATUS_TRANSITIONS[from as TaskStatus].includes(to as TaskStatus);
}

/** Built-in options for a task in `current`: the current value plus every legal next state. */
export function statusOptionsFor(current: string): TaskStatus[] {
  const cur = current as TaskStatus;
  if (!BUILTIN_STATUSES.includes(cur)) return [...BUILTIN_STATUSES];
  return Array.from(new Set([cur, ...STATUS_TRANSITIONS[cur]]));
}
