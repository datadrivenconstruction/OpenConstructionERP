// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Personal preferences for the Gantt chart's left table, kept on this device:
 * which columns show, how wide each is, and how wide the table is against the
 * chart (the splitter between them).
 */

import { create } from 'zustand';
import {
  DEFAULT_GANTT_COLUMNS,
  GANTT_COLUMN_IDS,
  ganttColumn,
  type GanttColumnId,
} from '@/shared/ui/Gantt/ganttColumns';

const STORAGE_KEY = 'oe_gantt_table_prefs';

export const GANTT_TABLE_MIN_WIDTH = 200;
export const GANTT_TABLE_MAX_WIDTH = 1200;

export type GanttColumnWidths = Partial<Record<GanttColumnId, number>>;

interface Prefs {
  columns: GanttColumnId[];
  widths: GanttColumnWidths;
  /** Width of the whole table in px; `null` lets the columns decide. */
  tableWidth: number | null;
}

/** Known ids only, once each, with the name column always present. */
export function normalizeColumns(value: unknown): GanttColumnId[] {
  const picked = new Set<GanttColumnId>(['name']);
  if (Array.isArray(value)) {
    for (const id of value) {
      if ((GANTT_COLUMN_IDS as readonly unknown[]).includes(id)) picked.add(id as GanttColumnId);
    }
  } else {
    return [...DEFAULT_GANTT_COLUMNS];
  }
  return GANTT_COLUMN_IDS.filter((id) => picked.has(id));
}

/** A column width clamped to what that column allows; a non-number gives its default. */
export function normalizeColumnWidth(id: GanttColumnId, value: unknown): number {
  const def = ganttColumn(id);
  const n = typeof value === 'number' ? value : Number.NaN;
  if (!Number.isFinite(n)) return def.defaultWidth;
  return Math.min(def.maxWidth, Math.max(def.minWidth, Math.round(n)));
}

export function normalizeTableWidth(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number.NaN;
  if (!Number.isFinite(n)) return null;
  return Math.min(GANTT_TABLE_MAX_WIDTH, Math.max(GANTT_TABLE_MIN_WIDTH, Math.round(n)));
}

function normalizeWidths(value: unknown): GanttColumnWidths {
  const out: GanttColumnWidths = {};
  if (value && typeof value === 'object') {
    for (const id of GANTT_COLUMN_IDS) {
      const raw = (value as Record<string, unknown>)[id];
      if (typeof raw === 'number' && Number.isFinite(raw)) out[id] = normalizeColumnWidth(id, raw);
    }
  }
  return out;
}

const DEFAULTS: Prefs = { columns: [...DEFAULT_GANTT_COLUMNS], widths: {}, tableWidth: null };

function read(): Prefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Record<keyof Prefs, unknown>>;
      return {
        columns: normalizeColumns(parsed.columns),
        widths: normalizeWidths(parsed.widths),
        tableWidth: normalizeTableWidth(parsed.tableWidth),
      };
    }
  } catch {
    /* storage unavailable or corrupt: fall back to defaults */
  }
  return { ...DEFAULTS, columns: [...DEFAULTS.columns] };
}

function persist(prefs: Prefs): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable */
  }
}

interface GanttTablePrefsState extends Prefs {
  toggleColumn: (id: GanttColumnId) => void;
  setColumnWidth: (id: GanttColumnId, width: number) => void;
  setTableWidth: (width: number | null) => void;
  reset: () => void;
}

const initial = read();

export const useGanttTablePrefsStore = create<GanttTablePrefsState>((set, get) => {
  const apply = (next: Partial<Prefs>) => {
    const { columns, widths, tableWidth } = { ...get(), ...next };
    persist({ columns, widths, tableWidth });
    set(next);
  };
  return {
    ...initial,
    toggleColumn: (id) => {
      if (ganttColumn(id).required) return;
      const has = get().columns.includes(id);
      apply({ columns: normalizeColumns(has ? get().columns.filter((c) => c !== id) : [...get().columns, id]) });
    },
    setColumnWidth: (id, width) => apply({ widths: { ...get().widths, [id]: normalizeColumnWidth(id, width) } }),
    setTableWidth: (width) => apply({ tableWidth: width == null ? null : normalizeTableWidth(width) }),
    reset: () => apply({ columns: [...DEFAULTS.columns], widths: {}, tableWidth: null }),
  };
});
