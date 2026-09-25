// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { QueryClient } from '@tanstack/react-query';
import { scheduleApi } from './api';

/**
 * Refetch what a generation changed and resolve once the new plan is loaded.
 *
 * The caller awaits this before closing the dialog and announcing success.
 * Firing the invalidations and moving on left the page on the schedule it had
 * before (an empty one, the first time) for the second or so the refetch took,
 * directly under a toast saying the schedule had been generated.
 */
export async function refreshAfterGenerate(queryClient: QueryClient, scheduleId: string): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] }),
    queryClient.invalidateQueries({ queryKey: ['schedules'] }),
  ]);
}

/**
 * Calendar days from ``start`` to ``end``, both included, or ``null`` when
 * either date is missing or unreadable or the end comes before the start.
 * This is the ``total_project_days`` the BOQ generator fits the plan into.
 */
export function projectWindowDays(start: string, end: string): number | null {
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  if (!iso.test(start) || !iso.test(end)) return null;
  const s = Date.parse(`${start}T00:00:00Z`);
  const e = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return null;
  return Math.round((e - s) / 86_400_000) + 1;
}

/**
 * Generate a schedule from a BOQ inside the project's window.
 *
 * The start goes onto the schedule first, because the generator draws every
 * date from it; the window travels as ``total_project_days``. Without it the
 * server falls back to a guess of a year or eighteen months whatever the
 * project says, which is how a generated plan came to run for two years.
 */
export async function generateInWindow(
  scheduleId: string,
  boqId: string,
  start: string,
  end: string,
): Promise<unknown> {
  const days = projectWindowDays(start, end);
  if (days == null) throw new Error('invalid project window');
  await scheduleApi.updateSchedule(scheduleId, { start_date: start });
  return scheduleApi.generateFromBOQ(scheduleId, boqId, days);
}
