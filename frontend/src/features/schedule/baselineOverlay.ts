// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Programme baselines B0, B1, ... on the Gantt: which baseline is the
// approved one, and the baseline dates of each live activity. Mirrors
// backend schedule/baseline_revisions.py and gantt_pdf.build_rows.

import type { ScheduleBaseline } from './api';

export interface BaselineApproval {
  approved_by?: string;
  approved_at?: string;
}

/** The approval stamp of a baseline, or null when it is a saved version only. */
export function approvalOf(baseline: Pick<ScheduleBaseline, 'metadata_'>): BaselineApproval | null {
  const stamp = baseline.metadata_?.approval as BaselineApproval | undefined;
  return stamp && stamp.approved_at ? stamp : null;
}

/** Baselines of one schedule, oldest first. */
export function baselinesOfSchedule(all: ScheduleBaseline[], scheduleId: string): ScheduleBaseline[] {
  return all
    .filter((b) => b.schedule_id === scheduleId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/**
 * The schedule's one approved baseline: among active rows the latest approval
 * wins, rows without a stamp rank by creation after stamped ones.
 */
export function effectiveBaseline(baselines: ScheduleBaseline[]): ScheduleBaseline | null {
  const rank = (b: ScheduleBaseline): string => {
    const stamp = approvalOf(b);
    return `${stamp ? 1 : 0}|${stamp?.approved_at ?? ''}|${b.created_at}`;
  };
  let best: ScheduleBaseline | null = null;
  for (const b of baselines) {
    if (b.is_active && (!best || rank(b) > rank(best))) best = b;
  }
  return best;
}

export interface BaselineDates {
  start: string;
  end: string;
}

interface SnapshotRow {
  id?: unknown;
  wbs_code?: unknown;
  start_date?: unknown;
  end_date?: unknown;
}

const day = (value: unknown): string | null =>
  typeof value === 'string' && value.length >= 10 ? value.slice(0, 10) : null;

/**
 * Baseline start/end per live activity id. Matches by activity id, then by WBS
 * code, so a baseline captured from an import with other ids still lines up.
 */
export function baselineDatesById(
  snapshot: Record<string, unknown> | null | undefined,
  activities: Array<{ id: string; wbs_code?: string | null }>,
): Map<string, BaselineDates> {
  const raw = snapshot?.activities;
  const rows = Array.isArray(raw) ? (raw as SnapshotRow[]) : Array.isArray(snapshot) ? (snapshot as SnapshotRow[]) : [];
  const byId = new Map<string, SnapshotRow>();
  const byWbs = new Map<string, SnapshotRow>();
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    if (row.id != null) byId.set(String(row.id), row);
    if (typeof row.wbs_code === 'string' && row.wbs_code && !byWbs.has(row.wbs_code)) byWbs.set(row.wbs_code, row);
  }
  const out = new Map<string, BaselineDates>();
  for (const act of activities) {
    const row = byId.get(act.id) ?? (act.wbs_code ? byWbs.get(act.wbs_code) : undefined);
    const start = day(row?.start_date);
    const end = day(row?.end_date) ?? start;
    if (start && end) out.set(act.id, { start, end });
  }
  return out;
}
