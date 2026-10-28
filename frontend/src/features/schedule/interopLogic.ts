// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers behind the progress sheet dialog, the scheduling profiles panel
// and the import source panel. Kept free of React so they are unit-tested
// directly.

import { compareNames } from '@/shared/lib/collator';
import type {
  ChangeCause,
  ProfileSettings,
  RecalculatedActivity,
  SheetPreviewRow,
  SourceComparisonRow,
} from './interopApi';

export interface ScopeActivity {
  wbs_code?: string | null;
  assignee_id?: string | null;
  assignee_name?: string | null;
}

/** Top-level WBS prefixes (text before the first dot), sorted, unique. */
export function wbsPrefixes(activities: ScopeActivity[]): string[] {
  const out = new Set<string>();
  for (const a of activities) {
    const code = (a.wbs_code ?? '').trim();
    if (!code) continue;
    out.add(code.split('.')[0] ?? code);
  }
  return [...out].sort((x, y) => compareNames(x, y));
}

/** Responsible people named on the activities, sorted by name. */
export function assigneeOptions(activities: ScopeActivity[]): { id: string; name: string }[] {
  const byId = new Map<string, string>();
  for (const a of activities) {
    if (a.assignee_id && !byId.has(a.assignee_id)) byId.set(a.assignee_id, a.assignee_name || a.assignee_id);
  }
  return [...byId.entries()].map(([id, name]) => ({ id, name })).sort((x, y) => compareNames(x.name, y.name));
}

/**
 * Rows ticked by default after a preview: those that change something and
 * have no error. A row whose activity changed in the app since export is left
 * for the user to tick on purpose.
 */
export function defaultSelectedRows(rows: SheetPreviewRow[]): Set<number> {
  return new Set(rows.filter((r) => r.applicable && !r.stale).map((r) => r.row_number));
}

/** Only rows that can be applied may be selected. */
export function canSelectRow(row: SheetPreviewRow): boolean {
  return row.applicable;
}

/** The settings that differ from the built-in ones, in display order. */
export function nonDefaultSettings(settings: ProfileSettings, defaults: ProfileSettings): (keyof ProfileSettings)[] {
  return (Object.keys(defaults) as (keyof ProfileSettings)[]).filter((k) => settings[k] !== defaults[k]);
}

/** A recalculated row that moves or changes its critical flag. */
export function isChangedActivity(row: RecalculatedActivity): boolean {
  return (
    row.new_start !== row.current_start ||
    row.new_end !== row.current_end ||
    row.is_critical !== row.was_critical
  );
}

/** Causes sorted by how many activities they changed, largest first. */
export function sortedEffects(effects: Partial<Record<ChangeCause, number>>): [ChangeCause, number][] {
  return (Object.entries(effects) as [ChangeCause, number][])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
}

/** A source comparison row whose dates differ from the source. */
export function isDeviating(row: SourceComparisonRow): boolean {
  return Boolean(row.start_deviation_days) || Boolean(row.finish_deviation_days);
}

/** "+3" / "-2" / "0" for a day shift; a dash when unknown. */
export function formatShift(days: number | null | undefined): string {
  if (days === null || days === undefined) return '-';
  if (days > 0) return `+${days}`;
  return String(days);
}

/** Today in ISO form (local date), for the status date default. */
export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
