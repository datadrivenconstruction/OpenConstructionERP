// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Grouping of clock events into day -> worker rows for the log, with missing clock-outs marked​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠. */

import { todayLocalISO } from '@/shared/lib/dates';
import type { ClockEvent } from './clockApi';

export interface WorkerDay {
  resourceId: string;
  resourceName: string;
  events: ClockEvent[];
  /** An 'in' with no matching 'out' on a day that is over. */
  missingOut: boolean;
  /** An 'in' with no 'out' yet, today: the shift is still running. */
  open: boolean;
  pending: number;
}

export interface LogDay {
  date: string;
  workers: WorkerDay[];
  missingOut: number;
  pending: number;
}

/** Local calendar date (YYYY-MM-DD) of an ISO instant. */
export function localDateOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : todayLocalISO(d);
}

/** Newest day first; inside a day, workers by name; inside a worker, events by time. */
export function groupClockEvents(events: ClockEvent[], today: string = todayLocalISO()): LogDay[] {
  const days = new Map<string, Map<string, ClockEvent[]>>();
  for (const e of events) {
    const date = localDateOf(e.occurred_at);
    const workers = days.get(date) ?? new Map<string, ClockEvent[]>();
    const list = workers.get(e.resource_id) ?? [];
    list.push(e);
    workers.set(e.resource_id, list);
    days.set(date, workers);
  }
  return [...days.entries()]
    .sort(([a], [b]) => (a < b ? 1 : a > b ? -1 : 0))
    .map(([date, workers]) => {
      const rows: WorkerDay[] = [...workers.entries()]
        .map(([resourceId, list]) => {
          const sorted = [...list].sort((x, y) => x.occurred_at.localeCompare(y.occurred_at));
          const unpaired = sorted.some((e) => e.kind === 'in' && !e.pair_event_id);
          return {
            resourceId,
            resourceName: sorted[0]?.resource_name ?? '',
            events: sorted,
            missingOut: unpaired && date < today,
            open: unpaired && date >= today,
            pending: sorted.filter((e) => e.approval_status === 'pending').length,
          };
        })
        .sort((a, b) => a.resourceName.localeCompare(b.resourceName));
      return {
        date,
        workers: rows,
        missingOut: rows.filter((r) => r.missingOut).length,
        pending: rows.reduce((n, r) => n + r.pending, 0),
      };
    });
}

/** The first day of the two-week window ending today (inclusive of both). */
export function twoWeeksAgo(today: string = todayLocalISO()): string {
  const d = new Date(`${today}T12:00:00`);
  d.setDate(d.getDate() - 13);
  return todayLocalISO(d);
}
