// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The columns of the Gantt chart's left table: which exist, how wide they
 * start, and how a predecessor list is written the way a planner writes it
 * (`01.02 FS+3; 01.04 SS`).
 */

import { fmtList } from '@/shared/lib/formatters';
import type { GanttDependencyType } from './ganttUtils';

export type GanttColumnId =
  | 'wbs'
  | 'name'
  | 'start'
  | 'end'
  | 'duration'
  | 'predecessors'
  | 'progress'
  | 'resources';

export interface GanttColumnDef {
  id: GanttColumnId;
  /** i18n key of the header, with the English default beside it. */
  labelKey: string;
  defaultLabel: string;
  /** Width in px a column has until the reader drags it. */
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  align: 'start' | 'end';
  /** The name column is the row's identity: it cannot be hidden. */
  required?: boolean;
}

/** Every column, in the order they are drawn. */
export const GANTT_COLUMNS: readonly GanttColumnDef[] = [
  { id: 'wbs', labelKey: 'gantt.col_wbs', defaultLabel: 'WBS', defaultWidth: 64, minWidth: 40, maxWidth: 160, align: 'start' },
  {
    id: 'name',
    labelKey: 'gantt.activity_name',
    defaultLabel: 'Activity',
    defaultWidth: 124,
    minWidth: 80,
    maxWidth: 600,
    align: 'start',
    required: true,
  },
  { id: 'start', labelKey: 'gantt.start', defaultLabel: 'Start', defaultWidth: 70, minWidth: 56, maxWidth: 160, align: 'end' },
  { id: 'end', labelKey: 'gantt.end', defaultLabel: 'End', defaultWidth: 70, minWidth: 56, maxWidth: 160, align: 'end' },
  { id: 'duration', labelKey: 'gantt.col_duration', defaultLabel: 'Days', defaultWidth: 48, minWidth: 36, maxWidth: 120, align: 'end' },
  {
    id: 'predecessors',
    labelKey: 'gantt.col_predecessors',
    defaultLabel: 'Predecessors',
    defaultWidth: 120,
    minWidth: 60,
    maxWidth: 400,
    align: 'start',
  },
  { id: 'progress', labelKey: 'gantt.col_progress', defaultLabel: 'Progress', defaultWidth: 36, minWidth: 30, maxWidth: 100, align: 'end' },
  {
    id: 'resources',
    labelKey: 'gantt.col_resources',
    defaultLabel: 'Resources',
    defaultWidth: 110,
    minWidth: 60,
    maxWidth: 400,
    align: 'start',
  },
];

/** The columns shown until the reader picks others: what the table always had. */
export const DEFAULT_GANTT_COLUMNS: readonly GanttColumnId[] = ['name', 'start', 'end', 'progress'];

export const GANTT_COLUMN_IDS: readonly GanttColumnId[] = GANTT_COLUMNS.map((c) => c.id);

const BY_ID = new Map<GanttColumnId, GanttColumnDef>(GANTT_COLUMNS.map((c) => [c.id, c]));

export function ganttColumn(id: GanttColumnId): GanttColumnDef {
  return BY_ID.get(id) as GanttColumnDef;
}

/** One link into an activity, as the table writes it. */
export interface GanttPredecessor {
  /** What names the predecessor: its WBS code, else its row number or name. */
  code: string;
  type?: GanttDependencyType | string | null;
  /** Lag in days; negative is a lead. */
  lag?: number | null;
}

/**
 * Predecessors the way a planner writes them: code, then the link type and the
 * lag, separated by semicolons. A finish-to-start link with no lag is the
 * plain code (`01.02`); any other type is written out (`01.04 SS`); a lag
 * follows the type with its sign (`01.02 FS+3`, `01.03 SS-2`).
 */
export function formatPredecessors(links: readonly GanttPredecessor[] | null | undefined): string {
  if (!links || links.length === 0) return '';
  return links
    .map((link) => {
      const type = typeof link.type === 'string' && link.type ? link.type.toUpperCase() : 'FS';
      const lag = Number.isFinite(link.lag) ? Math.trunc(link.lag as number) : 0;
      if (type === 'FS' && lag === 0) return link.code;
      const sign = lag > 0 ? `+${lag}` : lag < 0 ? `${lag}` : '';
      return `${link.code} ${type}${sign}`;
    })
    .join('; ');
}

/** Resource rows as a short line: `Labour x4, Crane`. */
export function formatResources(
  rows: ReadonlyArray<{ name?: string | null; count?: number | null }> | null | undefined,
): string {
  if (!rows) return '';
  return fmtList(
    rows
      .filter((r) => r.name)
      .map((r) => {
        const count = Number(r.count);
        return Number.isFinite(count) && count > 1 ? `${r.name} ×${Math.trunc(count)}` : String(r.name);
      }),
  );
}

/** The columns to draw: the picked ones in table order, the name always among them. */
export function visibleColumns(picked: readonly GanttColumnId[]): GanttColumnDef[] {
  const wanted = new Set<GanttColumnId>(picked);
  wanted.add('name');
  return GANTT_COLUMNS.filter((c) => wanted.has(c.id));
}
