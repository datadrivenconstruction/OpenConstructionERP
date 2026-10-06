// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { QueryClient } from '@tanstack/react-query';
import { scheduleApi, type GenerateFromBoqOptions } from './api';

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
    queryClient.invalidateQueries({ queryKey: ['schedule-record', scheduleId] }),
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
 * The window a generation is asked to fit.
 *
 * The start travels in the request and the server writes it to the schedule
 * together with the plan, so a refused or failed generation leaves the
 * schedule's start as it was (it used to be saved first, on its own). The end
 * becomes ``total_project_days``. With no end there is no window: the plan
 * takes as long as the work needs and nothing is shortened. An end before the
 * start, or one without a start, is refused here.
 */
export function generationWindow(start: string, end: string): GenerateFromBoqOptions {
  const startDate = /^\d{4}-\d{2}-\d{2}$/.test(start) ? start : null;
  if (!end) return { startDate };
  const days = projectWindowDays(start, end);
  if (days == null) throw new Error('invalid project window');
  return { startDate, totalProjectDays: days };
}

/**
 * Generate a schedule from a BOQ inside the project's window.
 *
 * ``replace`` lets the server delete the schedule's activities first, in the
 * same transaction; without it a populated schedule is refused with
 * ``schedule_has_activities``.
 */
export async function generateInWindow(
  scheduleId: string,
  boqId: string,
  start: string,
  end: string,
  replace = false,
  workers: number | null = null,
): Promise<unknown> {
  return scheduleApi.generateFromBOQ(scheduleId, boqId, {
    ...generationWindow(start, end),
    replace,
    ...(workers != null ? { workersPerPosition: workers } : {}),
  });
}

/** What :func:`generateInWindow` would write, for the person to confirm. Writes nothing. */
export function previewInWindow(
  scheduleId: string,
  boqId: string,
  start: string,
  end: string,
  workers: number | null = null,
) {
  return scheduleApi.previewGenerateFromBOQ(scheduleId, boqId, {
    ...generationWindow(start, end),
    ...(workers != null ? { workersPerPosition: workers } : {}),
  });
}

/** The most workers per position a generation takes, as the server allows. */
export const MAX_WORKERS_PER_POSITION = 20;

/** The workers field as a number from 1 to 20; ``null`` for empty (the fewest that fit) or anything else. */
export function parseWorkers(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const n = Number(value.trim());
  return n >= 1 && n <= MAX_WORKERS_PER_POSITION ? n : null;
}

/** Something the last generation from a BOQ could not do as asked. */
export type GenerationWarning =
  | { code: 'plan_exceeds_window'; planned_end: string; requested_end: string }
  | { code: 'durations_shortened'; percent: number };

type ScheduleMetadataHolder = { metadata_?: Record<string, unknown>; metadata?: Record<string, unknown> };

function boqGenerationRecord(schedule: ScheduleMetadataHolder | null | undefined): unknown {
  // The API sends the field as ``metadata_``; ``metadata`` is accepted too.
  const meta = schedule?.metadata_ ?? schedule?.metadata;
  return meta?.boq_generation;
}

/**
 * The warnings the last generation left on the schedule, under
 * ``metadata_.boq_generation.warnings``. Anything not shaped like a known
 * warning is dropped, so an old or hand-edited record shows nothing rather
 * than a broken sentence.
 */
export function generationWarnings(schedule: ScheduleMetadataHolder | null | undefined): GenerationWarning[] {
  const record = boqGenerationRecord(schedule);
  if (!record || typeof record !== 'object') return [];
  const warnings = (record as { warnings?: unknown }).warnings;
  if (!Array.isArray(warnings)) return [];
  return warnings.filter((w): w is GenerationWarning => {
    if (!w || typeof w !== 'object') return false;
    const item = w as Record<string, unknown>;
    if (item.code === 'plan_exceeds_window') {
      return typeof item.planned_end === 'string' && typeof item.requested_end === 'string';
    }
    return item.code === 'durations_shortened' && typeof item.percent === 'number';
  });
}

/**
 * The workers per position the last generation was asked for, so generating
 * again builds the same plan. ``null`` when the generator chose the number
 * itself: it chooses again for the dates given now.
 */
export function generationWorkers(schedule: ScheduleMetadataHolder | null | undefined): number | null {
  const record = boqGenerationRecord(schedule);
  if (!record || typeof record !== 'object') return null;
  const { workers_per_position: workers, workers_assumed: assumed } = record as Record<string, unknown>;
  if (assumed !== false || typeof workers !== 'number' || !Number.isInteger(workers)) return null;
  return workers >= 1 && workers <= MAX_WORKERS_PER_POSITION ? workers : null;
}

/** When the last generation ran, so a dismissed warning stays dismissed only for that run. */
export function generationStamp(schedule: ScheduleMetadataHolder | null | undefined): string {
  const record = boqGenerationRecord(schedule);
  if (!record || typeof record !== 'object') return '';
  const stamp = (record as { generated_at?: unknown }).generated_at;
  return typeof stamp === 'string' ? stamp : '';
}
