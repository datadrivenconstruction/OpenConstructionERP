import type { Activity } from './api';

export interface StartFloorPatch {
  constraint_type: 'start_no_earlier';
  constraint_date: string;
}

const REPLACEABLE = new Set(['', 'as_soon_as_possible', 'start_no_earlier']);

/**
 * The "start no earlier than" floor to store when a bar is dragged or resized
 * to start on `newStart`.
 *
 * A bar dragged later gets a floor at its new start, so rescheduling keeps it
 * there and pushes its successors. A floor that already exists follows the bar
 * when it moves earlier (the network still clamps it to its predecessors).
 * A constraint the planner set on purpose (must start on, finish no later...)
 * is never overwritten. Returns null when nothing should be written.
 */
export function startFloorPatch(
  activity: Pick<Activity, 'start_date' | 'constraint_type' | 'constraint_date'> | undefined,
  newStart: string,
): StartFloorPatch | null {
  if (!activity || !newStart || newStart === activity.start_date) return null;
  const current = activity.constraint_type ?? '';
  if (!REPLACEABLE.has(current)) return null;
  const later = newStart > activity.start_date;
  if (!later && current !== 'start_no_earlier') return null;
  return { constraint_type: 'start_no_earlier', constraint_date: newStart };
}
