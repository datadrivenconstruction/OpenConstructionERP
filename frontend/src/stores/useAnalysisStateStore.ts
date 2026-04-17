/**
 * useAnalysisStateStore — cross-tab analysis state for the CAD Data Explorer.
 *
 * Holds slicers (multi-column chip filters), chart configuration (kind,
 * category, value, topN, format) and user-saved views. Filters are shared
 * between Data / Pivot / Charts tabs so clicking a bar filters the table.
 *
 * Views persist per session to localStorage under
 * `oe_data_explorer_views_${sessionId}` — backend persistence is a future
 * follow-up (see RFC 16 §4.4).
 */
import { create } from 'zustand';

export type ChartKind = 'bar' | 'line' | 'pie' | 'scatter';
export type ChartFormat = 'number' | 'currency' | 'percent';

export interface SlicerFilter {
  column: string;
  values: string[];
}

export interface ChartConfig {
  kind: ChartKind;
  category: string;
  value: string;
  /** null = show all groups */
  topN: number | null;
  /** When topN is set, 'top' or 'bottom' slice direction. */
  topNDirection: 'top' | 'bottom';
  format: ChartFormat;
}

export interface PivotConfigSnapshot {
  groupBy: string[];
  aggCols: string[];
  aggFn: string;
  topN: number | null;
  topNDirection: 'top' | 'bottom';
}

export interface SavedView {
  id: string;
  name: string;
  createdAt: number;
  slicers: SlicerFilter[];
  chart: ChartConfig;
  pivot: PivotConfigSnapshot | null;
}

interface AnalysisStateSnapshot {
  slicers: SlicerFilter[];
  chart: ChartConfig;
  pivot: PivotConfigSnapshot | null;
}

interface AnalysisState extends AnalysisStateSnapshot {
  sessionId: string | null;
  views: SavedView[];

  /** Switch the active session. Loads saved views from localStorage and
   *  resets slicers so they don't leak between sessions. */
  setSessionId: (id: string | null) => void;

  addSlicer: (column: string, values: string[]) => void;
  removeSlicer: (column: string) => void;
  clearSlicers: () => void;

  setChartConfig: (patch: Partial<ChartConfig>) => void;
  setPivotSnapshot: (snapshot: PivotConfigSnapshot | null) => void;

  saveView: (name: string) => SavedView;
  loadView: (id: string) => void;
  deleteView: (id: string) => void;
}

const DEFAULT_CHART: ChartConfig = {
  kind: 'bar',
  category: '',
  value: '',
  topN: null,
  topNDirection: 'top',
  format: 'number',
};

function storageKey(sessionId: string): string {
  return `oe_data_explorer_views_${sessionId}`;
}

function loadViews(sessionId: string | null): SavedView[] {
  if (!sessionId || typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(storageKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedView[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistViews(sessionId: string | null, views: SavedView[]): void {
  if (!sessionId || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey(sessionId), JSON.stringify(views));
  } catch {
    // Storage quota or access error — silently ignore; views are best-effort.
  }
}

/** Slicer debounce + diff guard — prevents chart-click → slicer → refetch
 *  feedback loops per RFC 16 §6. Values-equal check happens before any
 *  setState so React Query doesn't refire identical queries. */
function sameValues(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sorted = [...a].sort();
  const other = [...b].sort();
  return sorted.every((v, i) => v === other[i]);
}

export const useAnalysisStateStore = create<AnalysisState>((set, get) => ({
  sessionId: null,
  slicers: [],
  chart: { ...DEFAULT_CHART },
  pivot: null,
  views: [],

  setSessionId: (id) => {
    if (get().sessionId === id) return;
    set({
      sessionId: id,
      slicers: [],
      chart: { ...DEFAULT_CHART },
      pivot: null,
      views: loadViews(id),
    });
  },

  addSlicer: (column, values) => {
    const current = get().slicers;
    const existing = current.find((s) => s.column === column);
    if (existing && sameValues(existing.values, values)) return;
    const others = current.filter((s) => s.column !== column);
    set({ slicers: [...others, { column, values: [...values] }] });
  },

  removeSlicer: (column) => {
    set({ slicers: get().slicers.filter((s) => s.column !== column) });
  },

  clearSlicers: () => {
    if (get().slicers.length === 0) return;
    set({ slicers: [] });
  },

  setChartConfig: (patch) => {
    set({ chart: { ...get().chart, ...patch } });
  },

  setPivotSnapshot: (snapshot) => {
    set({ pivot: snapshot });
  },

  saveView: (name) => {
    const trimmed = name.trim() || 'Untitled view';
    const view: SavedView = {
      id: `v_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      name: trimmed,
      createdAt: Date.now(),
      slicers: get().slicers.map((s) => ({ column: s.column, values: [...s.values] })),
      chart: { ...get().chart },
      pivot: get().pivot ? { ...get().pivot! } : null,
    };
    const next = [view, ...get().views];
    set({ views: next });
    persistViews(get().sessionId, next);
    return view;
  },

  loadView: (id) => {
    const view = get().views.find((v) => v.id === id);
    if (!view) return;
    set({
      slicers: view.slicers.map((s) => ({ column: s.column, values: [...s.values] })),
      chart: { ...view.chart },
      pivot: view.pivot ? { ...view.pivot } : null,
    });
  },

  deleteView: (id) => {
    const next = get().views.filter((v) => v.id !== id);
    set({ views: next });
    persistViews(get().sessionId, next);
  },
}));
