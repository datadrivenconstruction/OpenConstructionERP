/**
 * CAD Data Explorer — Pandas-like DataFrame interface for BIM element data.
 *
 * 4 tabs: Data Table | Pivot | Charts | Describe
 * Reads session_id from URL query parameter.
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Table2, BarChart3, PieChart, LineChart as LineChartIcon, FileSpreadsheet, Database, Filter,
  ArrowUpDown, ChevronDown, ChevronRight, ChevronLeft, Layers, X, Save,
  Download as DownloadIcon, Columns3, Search as SearchIcon,
  Upload, FileUp, Loader2, CheckCircle2, AlertCircle, FolderOpen,
  TrendingUp, Hash, Clock, ShieldCheck, Bookmark, ScatterChart as ScatterIcon, Trash2,
} from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { apiGet, apiPost } from '@/shared/lib/api';
import {
  describeSession,
  valueCounts,
  fetchElements,
  aggregate,
  saveSession,
  listSessions,
  deleteSession,
  type DescribeResponse,
  type AggregateResponse,
  type AggregateGroup,
} from './api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { MissingDataPanel } from './MissingDataPanel';
import {
  useAnalysisStateStore,
  type ChartKind,
  type ChartFormat,
} from '@/stores/useAnalysisStateStore';
import { formatValue, formatChartValue } from '@/shared/lib/numberFormat';
import { applyTopN, groupMatchesSlicers } from './aggregation';

/* ── Recharts — lazy-loaded so the initial Data Explorer bundle stays lean.
      Charts live in a ~38 kB gzipped chunk that only loads once the user
      opens the Charts tab. See RFC 16 §6. ────────────────────────────── */
type RechartsApi = typeof import('recharts');
function useRecharts(): { api: RechartsApi | null; error: Error | null } {
  const [api, setApi] = useState<RechartsApi | null>(null);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    let cancelled = false;
    import('recharts')
      .then((m) => { if (!cancelled) setApi(m); })
      .catch((e: Error) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, []);
  return { api, error };
}

/* ── Types ─────────────────────────────────────────────────────────────── */

type TabId = 'table' | 'pivot' | 'charts' | 'describe';

const TABS: { id: TabId; icon: React.ElementType; label: string; description: string }[] = [
  { id: 'table', icon: Table2, label: 'Data Table', description: 'Filter, sort and search element data' },
  { id: 'pivot', icon: Layers, label: 'Pivot', description: 'Group and aggregate data by any column' },
  { id: 'charts', icon: BarChart3, label: 'Charts', description: 'Visualize distributions and patterns' },
  { id: 'describe', icon: FileSpreadsheet, label: 'Describe', description: 'Statistical summary of all numeric columns' },
];

const AGG_FUNCTIONS = ['sum', 'avg', 'min', 'max', 'count'];


/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (Math.abs(n) >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/* ── (Stats now rendered as header pills in the session view) ──────────── */

/* ── Top-N radio (shared by Charts + Pivot) ────────────────────────────── */

interface TopNToggleProps {
  value: number | null;
  direction: 'top' | 'bottom';
  onChange: (value: number | null, direction: 'top' | 'bottom') => void;
  testIdPrefix: string;
}

const TOP_N_OPTIONS = [5, 10, 20] as const;

function TopNToggle({ value, direction, onChange, testIdPrefix }: TopNToggleProps) {
  const { t } = useTranslation();
  const active = (n: number | null, d: 'top' | 'bottom'): boolean =>
    value === n && (n == null || direction === d);

  const btnCls = (isActive: boolean): string =>
    `h-7 px-2.5 rounded-md text-2xs font-medium border transition-colors whitespace-nowrap ${
      isActive
        ? 'bg-oe-blue text-white border-oe-blue'
        : 'bg-surface-secondary text-content-tertiary border-border-light hover:bg-surface-tertiary'
    }`;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <label className="text-2xs font-semibold text-content-secondary uppercase tracking-wide">
        {t('explorer.limit', { defaultValue: 'Limit' })}
      </label>
      <button
        type="button"
        data-testid={`${testIdPrefix}-topn-all`}
        onClick={() => onChange(null, direction)}
        className={btnCls(active(null, direction))}
      >
        {t('explorer.show_all', { defaultValue: 'All' })}
      </button>
      {TOP_N_OPTIONS.map((n) => (
        <button
          key={`top-${n}`}
          type="button"
          data-testid={`${testIdPrefix}-topn-top-${n}`}
          onClick={() => onChange(n, 'top')}
          className={btnCls(active(n, 'top'))}
        >
          {t('explorer.show_top', { defaultValue: 'Top {{n}}', n })}
        </button>
      ))}
      {TOP_N_OPTIONS.map((n) => (
        <button
          key={`bot-${n}`}
          type="button"
          data-testid={`${testIdPrefix}-topn-bottom-${n}`}
          onClick={() => onChange(n, 'bottom')}
          className={btnCls(active(n, 'bottom'))}
        >
          {t('explorer.show_bottom', { defaultValue: 'Bottom {{n}}', n })}
        </button>
      ))}
    </div>
  );
}

/* ── Slicer banner (shared across Data / Pivot / Charts tabs) ──────────── */

function SlicerBanner() {
  const { t } = useTranslation();
  const slicers = useAnalysisStateStore((s) => s.slicers);
  const removeSlicer = useAnalysisStateStore((s) => s.removeSlicer);
  const clearSlicers = useAnalysisStateStore((s) => s.clearSlicers);

  return (
    <div
      data-testid="explorer-slicer-banner"
      className="flex items-center gap-2 flex-wrap px-3 py-2 border-b border-border-light bg-surface-secondary/40"
    >
      <Filter size={12} className="text-content-tertiary shrink-0" />
      <span className="text-2xs font-semibold text-content-tertiary uppercase tracking-wide shrink-0">
        {t('explorer.active_filters', { defaultValue: 'Active filters' })}
      </span>
      {slicers.length === 0 ? (
        <span className="text-2xs text-content-quaternary">
          {t('explorer.no_active_filters', {
            defaultValue: 'Click any chart bar or slice to filter across tabs.',
          })}
        </span>
      ) : (
        <>
          {slicers.map((s) => (
            <button
              key={s.column}
              type="button"
              data-testid={`slicer-chip-${s.column}`}
              onClick={() => removeSlicer(s.column)}
              className="group inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-oe-blue/10 px-2.5 py-0.5 text-2xs font-medium text-oe-blue hover:bg-oe-blue/20"
              title={t('explorer.delete_view', { defaultValue: 'Remove' })}
            >
              <span className="max-w-[140px] truncate">
                {s.column} = {s.values.join(', ')}
              </span>
              <X size={10} />
            </button>
          ))}
          <button
            type="button"
            data-testid="slicer-clear-all"
            onClick={clearSlicers}
            className="text-2xs text-content-tertiary hover:text-content-primary underline underline-offset-2"
          >
            {t('explorer.clear_all_filters', { defaultValue: 'Clear all' })}
          </button>
        </>
      )}
    </div>
  );
}

/* ── Data Table Tab ────────────────────────────────────────────────────── */

function DataTableTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const slicers = useAnalysisStateStore((s) => s.slicers);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(50);
  const [sortBy, setSortBy] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [filterCol, setFilterCol] = useState('');
  const [filterVal, setFilterVal] = useState('');
  const [activeFilter, setActiveFilter] = useState<{ col: string; val: string } | null>(null);
  const [globalSearch, setGlobalSearch] = useState('');
  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set());
  const [heatmapEnabled, setHeatmapEnabled] = useState(false);

  // When slicers change, jump back to page 1 so the user sees filtered rows
  // from the top. Guard prevents infinite loops on mount.
  const slicerSignature = useMemo(
    () => slicers.map((s) => `${s.column}=${s.values.join(',')}`).join(';'),
    [slicers],
  );
  useEffect(() => {
    setPage(0);
  }, [slicerSignature]);

  const { data, isLoading } = useQuery({
    queryKey: ['cad-elements', sessionId, page, pageSize, sortBy, sortOrder, activeFilter],
    queryFn: () => fetchElements(sessionId, {
      offset: page * pageSize,
      limit: pageSize,
      sort_by: sortBy || undefined,
      sort_order: sortOrder,
      filter_column: activeFilter?.col || undefined,
      filter_value: activeFilter?.val || undefined,
    }),
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  // Pre-compute min/max for numeric columns (for heatmap)
  const colStats = useMemo(() => {
    if (!data?.rows || !heatmapEnabled) return new Map<string, { min: number; max: number }>();
    const stats = new Map<string, { min: number; max: number }>();
    for (const col of describe.columns.filter((c) => c.dtype === 'number')) {
      if (col.min != null && col.max != null && col.max > col.min) {
        stats.set(col.name, { min: col.min, max: col.max });
      }
    }
    return stats;
  }, [data?.rows, heatmapEnabled, describe.columns]);

  function heatmapBg(col: string, val: unknown): string {
    if (!heatmapEnabled || typeof val !== 'number') return '';
    const s = colStats.get(col);
    if (!s) return '';
    const ratio = Math.max(0, Math.min(1, (val - s.min) / (s.max - s.min)));
    if (ratio < 0.33) return 'bg-blue-50/40 dark:bg-blue-900/10';
    if (ratio < 0.66) return 'bg-emerald-50/40 dark:bg-emerald-900/10';
    return 'bg-emerald-100/60 dark:bg-emerald-900/20';
  }

  // Smart column selection: priority columns first, then rest
  const allCols = useMemo(() => {
    if (!data?.columns) return [];
    const priority = ['category', 'type name', 'family', 'family name', 'level', 'material', 'workset', 'volume', 'area', 'length', 'count', 'width', 'height', 'depth'];
    return [...data.columns].sort((a, b) => {
      const ai = priority.indexOf(a.toLowerCase());
      const bi = priority.indexOf(b.toLowerCase());
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return 0;
    });
  }, [data?.columns]);

  const visibleCols = useMemo(() => {
    const cols = allCols.filter((c) => !hiddenCols.has(c));
    return cols.slice(0, 15); // max 15 visible
  }, [allCols, hiddenCols]);

  // Client-side filters: active slicer chips (cross-filter from charts /
  // pivot) first, then the global-search box. Slicers AND across columns.
  const displayRows = useMemo(() => {
    if (!data?.rows) return [];
    let rows = data.rows;
    if (slicers.length > 0) {
      rows = rows.filter((row) =>
        slicers.every((s) => {
          if (s.values.length === 0) return true;
          const cell = row[s.column];
          return s.values.includes(cell == null ? '' : String(cell));
        }),
      );
    }
    if (globalSearch.trim()) {
      const q = globalSearch.toLowerCase();
      rows = rows.filter((row) =>
        Object.values(row).some((v) => v != null && String(v).toLowerCase().includes(q)),
      );
    }
    return rows;
  }, [data?.rows, globalSearch, slicers]);

  // Export current view to CSV
  const handleExportCSV = useCallback(() => {
    if (!data?.rows || data.rows.length === 0) return;
    const cols = visibleCols;
    const header = cols.join(',');
    const rows = displayRows.map((row) =>
      cols.map((col) => {
        const val = String(row[col] ?? '');
        return val.includes(',') || val.includes('"') || val.includes('\n') ? `"${val.replace(/"/g, '""')}"` : val;
      }).join(',')
    );
    const csv = [header, ...rows].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cad-data-export.csv`;
    a.click();
    URL.revokeObjectURL(url);
    addToast({ type: 'success', title: t('explorer.exported', { defaultValue: 'Exported to CSV' }) });
  }, [data?.rows, visibleCols, displayRows, addToast, t]);

  const handleSort = useCallback((col: string) => {
    if (sortBy === col) {
      setSortOrder((o) => o === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(col);
      setSortOrder('asc');
    }
    setPage(0);
  }, [sortBy]);

  const applyFilter = useCallback(() => {
    if (filterCol && filterVal) {
      setActiveFilter({ col: filterCol, val: filterVal });
      setPage(0);
    }
  }, [filterCol, filterVal]);

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Global search */}
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <SearchIcon size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            value={globalSearch}
            onChange={(e) => setGlobalSearch(e.target.value)}
            placeholder={t('explorer.search_all', { defaultValue: 'Search all columns...' })}
            className="h-7 w-full rounded-md border border-border bg-surface-primary pl-7 pr-2 text-xs focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue outline-none"
          />
          {globalSearch && (
            <button onClick={() => setGlobalSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-content-quaternary hover:text-content-secondary">
              <X size={12} />
            </button>
          )}
        </div>

        {/* Column filter */}
        <div className="flex items-center gap-1">
          <Filter size={13} className="text-content-tertiary" />
          <select value={filterCol} onChange={(e) => setFilterCol(e.target.value)} className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-xs max-w-[120px]">
            <option value="">{t('explorer.filter_by', { defaultValue: 'Filter...' })}</option>
            {describe.columns.filter((c) => c.dtype === 'string' && c.unique < 200).map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
          </select>
          {filterCol && (
            <input
              value={filterVal}
              onChange={(e) => setFilterVal(e.target.value)}
              placeholder="="
              className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-xs w-24"
              onKeyDown={(e) => e.key === 'Enter' && applyFilter()}
            />
          )}
          {filterCol && filterVal && (
            <button onClick={applyFilter} className="h-7 px-2 rounded-md text-2xs font-medium bg-oe-blue text-white">OK</button>
          )}
        </div>

        {activeFilter && (
          <button onClick={() => setActiveFilter(null)} className="cursor-pointer">
            <Badge variant="blue" size="sm">
              {activeFilter.col}=&quot;{activeFilter.val}&quot; <X size={10} className="ml-1 inline" />
            </Badge>
          </button>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Column picker */}
        <div className="relative">
          <button
            onClick={() => setShowColumnPicker(!showColumnPicker)}
            className="h-7 px-2 rounded-md border border-border bg-surface-primary text-xs text-content-secondary hover:bg-surface-secondary flex items-center gap-1"
            title={t('explorer.columns_settings', { defaultValue: 'Show/Hide Columns' })}
          >
            <Columns3 size={13} /> {visibleCols.length}/{allCols.length}
          </button>
          {showColumnPicker && (
            <div className="absolute right-0 top-full mt-1 w-56 max-h-64 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-xl z-20 p-2">
              <p className="text-2xs font-semibold text-content-tertiary uppercase px-2 py-1 mb-1">{t('explorer.visible_columns', { defaultValue: 'Visible Columns' })}</p>
              {allCols.slice(0, 30).map((col) => (
                <label key={col} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-surface-secondary cursor-pointer text-xs">
                  <input
                    type="checkbox"
                    checked={!hiddenCols.has(col)}
                    onChange={() => setHiddenCols((prev) => { const next = new Set(prev); next.has(col) ? next.delete(col) : next.add(col); return next; })}
                    className="rounded border-border text-oe-blue focus:ring-oe-blue/30"
                  />
                  <span className="truncate text-content-secondary">{col}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Heatmap toggle */}
        <button
          onClick={() => setHeatmapEnabled((v) => !v)}
          className={`h-7 px-2 rounded-md border text-xs flex items-center gap-1 transition-colors ${
            heatmapEnabled
              ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
              : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary'
          }`}
          title={t('explorer.heatmap', { defaultValue: 'Toggle value heatmap' })}
        >
          <BarChart3 size={13} />
          {t('explorer.heatmap_short', { defaultValue: 'Heatmap' })}
        </button>

        {/* Export CSV */}
        <button
          onClick={handleExportCSV}
          className="h-7 px-2 rounded-md border border-border bg-surface-primary text-xs text-content-secondary hover:bg-surface-secondary flex items-center gap-1"
          title={t('explorer.export_csv', { defaultValue: 'Export CSV' })}
        >
          <DownloadIcon size={13} /> CSV
        </button>

        {/* Row count */}
        <span className="text-2xs text-content-tertiary tabular-nums shrink-0">
          {globalSearch ? `${displayRows.length}/` : ''}{data?.total.toLocaleString() ?? '...'} {t('explorer.rows', { defaultValue: 'rows' })}
        </span>
      </div>

      {/* Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-surface-secondary/50">
                <th className="px-2 py-2 text-center text-2xs font-medium text-content-tertiary w-10">#</th>
                {visibleCols.map((col) => (
                  <th
                    key={col}
                    onClick={() => handleSort(col)}
                    className="px-2 py-2 text-left text-2xs font-medium text-content-tertiary cursor-pointer hover:text-content-primary select-none whitespace-nowrap"
                  >
                    <span className="inline-flex items-center gap-1">
                      {col}
                      {sortBy === col && (
                        <ArrowUpDown size={10} className={sortOrder === 'desc' ? 'rotate-180' : ''} />
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i} className="border-b border-border-light">
                    <td className="px-2 py-2" colSpan={visibleCols.length + 1}>
                      <div className="h-4 bg-surface-secondary rounded animate-pulse" />
                    </td>
                  </tr>
                ))
              ) : displayRows.map((row, idx) => (
                <tr key={`row-${page * pageSize + idx}-${Object.values(row).slice(0, 2).join('-')}`} className={`border-b border-border-light hover:bg-surface-secondary/30 ${idx % 2 === 0 ? '' : 'bg-surface-secondary/10'}`}>
                  <td className="px-2 py-1.5 text-center text-content-quaternary tabular-nums text-2xs">
                    {page * pageSize + idx + 1}
                  </td>
                  {visibleCols.map((col) => {
                    const val = row[col];
                    const isNum = typeof val === 'number';
                    const isNull = val == null || val === '' || val === 'None';
                    const isSearch = globalSearch && val != null && String(val).toLowerCase().includes(globalSearch.toLowerCase());
                    return (
                      <td key={col} className={`px-2 py-1.5 ${isNum ? 'text-right tabular-nums' : ''} truncate max-w-[180px] ${isNull ? 'bg-amber-50/30 dark:bg-amber-900/5' : ''} ${isSearch ? 'bg-yellow-100 dark:bg-yellow-900/20 font-medium' : 'text-content-primary'} ${heatmapBg(col, val)}`}>
                        {isNull ? <span className="text-content-quaternary italic text-2xs">null</span> : isNum ? formatNumber(val) : String(val)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Page summary: sum of visible numeric cols for current page */}
      {displayRows.length > 0 && (
        <div className="flex items-center gap-4 text-2xs text-content-tertiary px-1">
          <span className="font-medium text-content-secondary">{t('explorer.page_summary', { defaultValue: 'Page totals:' })}</span>
          {visibleCols.filter((col) => {
            const first = displayRows.find((r) => r[col] != null);
            return first && typeof first[col] === 'number';
          }).slice(0, 5).map((col) => {
            const sum = displayRows.reduce((s, r) => s + (typeof r[col] === 'number' ? (r[col] as number) : 0), 0);
            return sum > 0 ? (
              <span key={col} className="tabular-nums">
                <span className="text-content-quaternary">{col}:</span> <span className="font-medium text-content-primary">{formatNumber(sum)}</span>
              </span>
            ) : null;
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
            <ChevronLeft size={14} className="mr-1" /> {t('common.previous', { defaultValue: 'Previous' })}
          </Button>
          <span className="text-xs text-content-tertiary tabular-nums">
            {t('explorer.page_of', { defaultValue: 'Page {{page}} of {{total}}', page: page + 1, total: totalPages })}
          </span>
          <Button variant="ghost" size="sm" onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}>
            {t('common.next', { defaultValue: 'Next' })} <ChevronRight size={14} className="ml-1" />
          </Button>
        </div>
      )}
    </div>
  );
}

/* ── Pivot Tab ─────────────────────────────────────────────────────────── */

function PivotTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const slicers = useAnalysisStateStore((s) => s.slicers);
  const pivotSnapshot = useAnalysisStateStore((s) => s.pivot);
  const setPivotSnapshot = useAnalysisStateStore((s) => s.setPivotSnapshot);

  // All text columns for grouping, sorted by usefulness
  const stringCols = useMemo(() => describe.columns
    .filter((c) => c.dtype === 'string' && c.non_null > 0)
    .sort((a, b) => {
      const scoreA = (a.unique < 100 ? 1000 : 0) + a.non_null;
      const scoreB = (b.unique < 100 ? 1000 : 0) + b.non_null;
      return scoreB - scoreA;
    }), [describe]);

  // Numeric columns for aggregation — prioritize quantity keywords
  const QUANTITY_KEYWORDS = ['volume', 'area', 'length', 'count', 'width', 'height', 'depth', 'weight', 'mass', 'perimeter', 'thickness'];
  const numericCols = useMemo(() => {
    const all = describe.columns.filter((c) => c.dtype === 'number' && c.non_null > 0);
    // Score: keyword match + high non_null + non-zero sum
    return all.sort((a, b) => {
      const aKey = QUANTITY_KEYWORDS.some((k) => a.name.toLowerCase() === k) ? 10000 : QUANTITY_KEYWORDS.some((k) => a.name.toLowerCase().includes(k)) ? 5000 : 0;
      const bKey = QUANTITY_KEYWORDS.some((k) => b.name.toLowerCase() === k) ? 10000 : QUANTITY_KEYWORDS.some((k) => b.name.toLowerCase().includes(k)) ? 5000 : 0;
      const aScore = aKey + a.non_null + ((a.sum ?? 0) > 0 ? 1000 : 0);
      const bScore = bKey + b.non_null + ((b.sum ?? 0) > 0 ? 1000 : 0);
      return bScore - aScore;
    });
  }, [describe]);

  // Top quantity columns (shown as buttons)
  const topNumericCols = useMemo(() => numericCols.slice(0, 10), [numericCols]);

  // Default: prefer 'category', then 'type name', then first available.
  // If a saved pivot snapshot is present in the analysis store, hydrate
  // from that so restored views show the same group-by / aggCols layout.
  const [groupBy, setGroupBy] = useState<string[]>(() => {
    if (pivotSnapshot?.groupBy?.length) return pivotSnapshot.groupBy;
    const preferred = ['category', 'type name', 'family', 'level'];
    for (const p of preferred) {
      const found = stringCols.find((c) => c.name.toLowerCase() === p);
      if (found) return [found.name];
    }
    return stringCols.length > 0 ? [stringCols[0]!.name] : [];
  });
  // Allow multiple aggregate columns — auto-select exact matches first
  const [aggCols, setAggCols] = useState<string[]>(() => {
    if (pivotSnapshot?.aggCols?.length) return pivotSnapshot.aggCols;
    const defaults: string[] = [];
    for (const name of ['volume', 'area', 'length', 'count']) {
      const exact = numericCols.find((c) => c.name.toLowerCase() === name);
      if (exact) defaults.push(exact.name);
    }
    return defaults.length > 0 ? defaults : topNumericCols.slice(0, 3).map((c) => c.name);
  });
  const [aggFn, setAggFn] = useState<string>(() => pivotSnapshot?.aggFn || 'sum');
  const [topN, setTopN] = useState<number | null>(() => pivotSnapshot?.topN ?? null);
  const [topNDir, setTopNDir] = useState<'top' | 'bottom'>(
    () => pivotSnapshot?.topNDirection ?? 'top',
  );
  const [result, setResult] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDesc, setSortDesc] = useState(true);
  const [showCreateBOQ, setShowCreateBOQ] = useState(false);

  // Persist the live pivot config to the analysis store so Save View
  // captures the current layout and a restored view reapplies it here.
  useEffect(() => {
    setPivotSnapshot({ groupBy, aggCols, aggFn, topN, topNDirection: topNDir });
  }, [groupBy, aggCols, aggFn, topN, topNDir, setPivotSnapshot]);

  // Re-hydrate local state when the store's pivot snapshot changes from
  // elsewhere (e.g. Load View). Diff before applying so we don't thrash.
  useEffect(() => {
    if (!pivotSnapshot) return;
    setGroupBy((cur) =>
      cur.length === pivotSnapshot.groupBy.length &&
      cur.every((c, i) => c === pivotSnapshot.groupBy[i])
        ? cur
        : pivotSnapshot.groupBy,
    );
    setAggCols((cur) =>
      cur.length === pivotSnapshot.aggCols.length &&
      cur.every((c, i) => c === pivotSnapshot.aggCols[i])
        ? cur
        : pivotSnapshot.aggCols,
    );
    if (aggFn !== pivotSnapshot.aggFn) setAggFn(pivotSnapshot.aggFn);
    if (topN !== pivotSnapshot.topN) setTopN(pivotSnapshot.topN);
    if (topNDir !== pivotSnapshot.topNDirection) setTopNDir(pivotSnapshot.topNDirection);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pivotSnapshot]);

  // Auto-run pivot on first render and when groupBy/aggCols change
  const runPivot = useCallback(async () => {
    if (groupBy.length === 0 || aggCols.length === 0) return;
    setLoading(true);
    try {
      const aggs: Record<string, string> = {};
      for (const col of aggCols) aggs[col] = aggFn;
      const data = await aggregate(sessionId, groupBy, aggs);
      setResult(data);
      setExpanded(new Set());
      setSortCol(aggCols[0] || null);
    } catch (err) {
      addToast({ type: 'error', title: t('explorer.pivot_failed', { defaultValue: 'Pivot failed' }), message: err instanceof Error ? err.message : '' });
    } finally {
      setLoading(false);
    }
  }, [sessionId, groupBy, aggCols, aggFn, addToast, t]);

  // Auto-run on mount
  const hasRunInitialPivot = useRef(false);
  useEffect(() => {
    if (hasRunInitialPivot.current) return;
    hasRunInitialPivot.current = true;
    runPivot();
  }, [runPivot]);

  const toggleGroupBy = useCallback((col: string) => {
    setGroupBy((prev) => prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]);
  }, []);

  const toggleAggCol = useCallback((col: string) => {
    setAggCols((prev) => prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]);
  }, []);

  const toggleExpand = useCallback((key: string) => {
    setExpanded((prev) => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; });
  }, []);

  // Sort results and apply cross-filter slicers + top-N trim. Slicers run
  // first (can only match on group-by columns, so rows not covered by a
  // chip are silently passed through) and then the top-N slice crops the
  // list for chart-style "top 10" analysis.
  const sortedGroups = useMemo(() => {
    if (!result) return [];
    let groups = [...result.groups];
    if (slicers.length > 0) {
      groups = groups.filter((g) => groupMatchesSlicers(g, slicers));
    }
    if (sortCol) {
      groups.sort((a, b) => {
        const va = a.results[sortCol] ?? 0;
        const vb = b.results[sortCol] ?? 0;
        if (va !== vb) return sortDesc ? vb - va : va - vb;
        // Stable tie-break by first group-by column label.
        const first = groupBy[0];
        if (!first) return 0;
        return String(a.key[first] ?? '').localeCompare(String(b.key[first] ?? ''));
      });
    }
    if (topN != null && topN > 0 && sortCol) {
      // When the user explicitly asked for top-N or bottom-N, trim.
      // Slicing honours the current sort direction.
      groups = topNDir === 'top' ? groups.slice(0, topN) : groups.slice(-topN).reverse();
    } else if (topN != null && topN > 0) {
      // No active sort column — fall back to the first agg col.
      const k = aggCols[0];
      if (k) groups = applyTopN(groups, k, topN, topNDir, groupBy[0]);
    }
    return groups;
  }, [result, sortCol, sortDesc, slicers, topN, topNDir, aggCols, groupBy]);

  // Tree grouping for multi-level
  const tree = useMemo(() => {
    if (groupBy.length < 2) return null;
    const map = new Map<string, AggregateGroup[]>();
    for (const g of sortedGroups) {
      const parentKey = g.key[groupBy[0]!] || '(empty)';
      if (!map.has(parentKey)) map.set(parentKey, []);
      map.get(parentKey)!.push(g);
    }
    return map;
  }, [sortedGroups, groupBy]);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card className="p-4 space-y-3">
        {/* Row 1: Group By */}
        <div>
          <label className="text-2xs font-semibold text-content-secondary uppercase tracking-wide mb-1.5 block">
            {t('explorer.group_by', { defaultValue: 'Group By' })} ({groupBy.length} {t('explorer.selected', { defaultValue: 'selected' })})
          </label>
          <div className="flex gap-1.5 flex-wrap">
            {stringCols.slice(0, 12).map((col) => (
              <button
                key={col.name}
                onClick={() => toggleGroupBy(col.name)}
                className={`px-2.5 py-1 rounded-lg text-2xs font-medium transition-all border whitespace-nowrap ${
                  groupBy.includes(col.name)
                    ? 'bg-oe-blue text-white border-oe-blue shadow-sm'
                    : 'border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary hover:border-border'
                }`}
              >
                {col.name}
                {groupBy.includes(col.name) && <span className="ml-1 opacity-70">×</span>}
              </button>
            ))}
            {stringCols.length > 12 && (
              <select
                value=""
                onChange={(e) => { if (e.target.value) toggleGroupBy(e.target.value); }}
                className="px-2 py-1 rounded-lg text-2xs border border-border-light bg-surface-secondary text-content-tertiary cursor-pointer"
              >
                <option value="">+{stringCols.length - 12} {t('explorer.more_columns', { defaultValue: 'more' })}</option>
                {stringCols.slice(12).map((col) => (
                  <option key={col.name} value={col.name}>{col.name} ({col.unique})</option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Row 2: Sum Columns + Function + Apply */}
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex-1">
            <label className="text-2xs font-semibold text-content-secondary uppercase tracking-wide mb-1.5 block">
              {t('explorer.sum_columns', { defaultValue: 'Sum Columns' })} ({aggCols.length})
            </label>
            <div className="flex gap-1.5 flex-wrap">
              {topNumericCols.map((col) => (
                <button
                  key={col.name}
                  onClick={() => toggleAggCol(col.name)}
                  className={`px-2.5 py-1 rounded-lg text-2xs font-medium transition-all border whitespace-nowrap ${
                    aggCols.includes(col.name)
                      ? 'bg-emerald-500 text-white border-emerald-500 shadow-sm'
                      : 'border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary hover:border-border'
                  }`}
                  title={`${col.non_null} non-null, sum=${formatNumber(col.sum)}`}
                >
                  {col.name}
                </button>
              ))}
              {numericCols.length > 10 && (
                <select
                  value=""
                  onChange={(e) => { if (e.target.value) toggleAggCol(e.target.value); }}
                  className="px-2 py-1 rounded-lg text-2xs border border-border-light bg-surface-secondary text-content-tertiary cursor-pointer"
                >
                  <option value="">+{numericCols.length - 10} {t('explorer.more_columns', { defaultValue: 'more' })}</option>
                  {numericCols.slice(10).map((col) => (
                    <option key={col.name} value={col.name}>{col.name} ({col.non_null} values)</option>
                  ))}
                </select>
              )}
            </div>
          </div>
          <div className="shrink-0 flex items-center gap-2">
            <select value={aggFn} onChange={(e) => setAggFn(e.target.value)} className="h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-xs font-medium">
              {AGG_FUNCTIONS.map((fn) => <option key={fn} value={fn}>{fn.toUpperCase()}</option>)}
            </select>
            <Button variant="primary" size="sm" onClick={runPivot} disabled={groupBy.length === 0 || aggCols.length === 0 || loading} loading={loading}>
              {t('explorer.apply_pivot', { defaultValue: 'Apply' })}
            </Button>
          </div>
        </div>

        {/* Row 3: Top-N / Bottom-N limit (RFC 16 #3) */}
        <TopNToggle
          value={topN}
          direction={topNDir}
          onChange={(n, dir) => { setTopN(n); setTopNDir(dir); }}
          testIdPrefix="pivot"
        />
      </Card>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-12"><div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" /></div>
      ) : result && sortedGroups.length > 0 ? (
        <Card padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface-secondary/50">
                  {groupBy.map((col) => (
                    <th key={col} className="px-3 py-2.5 text-left text-2xs font-semibold text-content-tertiary uppercase tracking-wide">{col}</th>
                  ))}
                  <th
                    className="px-3 py-2.5 text-right text-2xs font-semibold text-content-tertiary uppercase tracking-wide cursor-pointer hover:text-content-primary select-none"
                    onClick={() => { setSortCol(null); setSortDesc((d) => !d); }}
                  >
                    {t('explorer.count', { defaultValue: 'Count' })}
                  </th>
                  {aggCols.map((col) => (
                    <th
                      key={col}
                      className="px-3 py-2.5 text-right text-2xs font-semibold text-content-tertiary uppercase tracking-wide cursor-pointer hover:text-content-primary select-none"
                      onClick={() => { setSortCol(col); setSortDesc((d) => sortCol === col ? !d : true); }}
                    >
                      <span className="inline-flex items-center gap-1">
                        {aggFn}({col})
                        {sortCol === col && <ArrowUpDown size={10} className={sortDesc ? '' : 'rotate-180'} />}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tree ? (
                  Array.from(tree.entries()).map(([parentKey, children]) => {
                    const isOpen = expanded.has(parentKey);
                    const parentCount = children.reduce((s, g) => s + g.count, 0);
                    return (
                      <React.Fragment key={parentKey}>
                        <tr className="border-b border-border-light bg-surface-secondary/20 cursor-pointer hover:bg-surface-secondary/40" onClick={() => toggleExpand(parentKey)}>
                          <td className="px-3 py-2 font-medium text-content-primary">
                            <span className="inline-flex items-center gap-1">
                              {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                              {parentKey}
                              <Badge variant="neutral" size="sm">{children.length}</Badge>
                            </span>
                          </td>
                          {groupBy.slice(1).map((col) => <td key={col} className="px-3 py-2 text-content-tertiary">—</td>)}
                          <td className="px-3 py-2 text-right font-semibold tabular-nums">{parentCount.toLocaleString()}</td>
                          {aggCols.map((col) => (
                            <td key={col} className="px-3 py-2 text-right font-semibold text-oe-blue tabular-nums">
                              {formatNumber(children.reduce((s, g) => s + (g.results[col] ?? 0), 0))}
                            </td>
                          ))}
                        </tr>
                        {isOpen && children.map((g) => (
                          <tr key={Object.values(g.key).join('-')} className="border-b border-border-light">
                            <td className="px-3 py-1.5 pl-8 text-content-quaternary">{g.key[groupBy[0]!]}</td>
                            {groupBy.slice(1).map((col) => <td key={col} className="px-3 py-1.5 text-content-secondary">{g.key[col] || '—'}</td>)}
                            <td className="px-3 py-1.5 text-right tabular-nums text-content-secondary">{g.count.toLocaleString()}</td>
                            {aggCols.map((col) => <td key={col} className="px-3 py-1.5 text-right tabular-nums">{formatNumber(g.results[col])}</td>)}
                          </tr>
                        ))}
                      </React.Fragment>
                    );
                  })
                ) : (
                  sortedGroups.map((g) => (
                    <tr key={Object.values(g.key).join('-')} className="border-b border-border-light hover:bg-surface-secondary/30">
                      {groupBy.map((col) => <td key={col} className="px-3 py-2 text-content-primary">{g.key[col] || '—'}</td>)}
                      <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{g.count.toLocaleString()}</td>
                      {aggCols.map((col) => <td key={col} className="px-3 py-2 text-right tabular-nums font-medium">{formatNumber(g.results[col])}</td>)}
                    </tr>
                  ))
                )}
                {/* Totals */}
                <tr className="bg-surface-secondary/60 font-semibold border-t-2 border-border">
                  <td className="px-3 py-2.5 text-content-primary" colSpan={groupBy.length}>{t('explorer.total', { defaultValue: 'Total' })}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{result.total_count.toLocaleString()}</td>
                  {aggCols.map((col) => <td key={col} className="px-3 py-2.5 text-right tabular-nums text-oe-blue">{formatNumber(result.totals[col])}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-4 py-2 bg-surface-secondary/30 border-t border-border-light">
            <span className="text-2xs text-content-quaternary">
              {sortedGroups.length} {t('explorer.groups', { defaultValue: 'groups' })} · {result.total_count.toLocaleString()} {t('explorer.elements', { defaultValue: 'elements' })} · {t('explorer.click_header_sort', { defaultValue: 'Click column headers to sort' })}
            </span>
            <button
              onClick={() => {
                if (!sortedGroups.length) return;
                const header = [...groupBy, 'Count', ...aggCols.map((c) => `${aggFn}_${c}`)].join(',');
                const rows = sortedGroups.map((g) =>
                  [...groupBy.map((c) => `"${(g.key[c] || '').replace(/"/g, '""')}"`), g.count, ...aggCols.map((c) => g.results[`${aggFn}_${c}`] ?? g.results[c] ?? 0)].join(',')
                );
                const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv' });
                const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'pivot_export.csv'; a.click();
              }}
              className="h-7 px-2 rounded-md border border-border bg-surface-primary text-xs text-content-secondary hover:bg-surface-secondary flex items-center gap-1 shrink-0"
            >
              <DownloadIcon size={13} /> CSV
            </button>
            <Button variant="primary" size="sm" onClick={() => setShowCreateBOQ(true)} className="shrink-0 whitespace-nowrap">
              {t('explorer.create_boq_from_pivot', { defaultValue: 'Create BOQ' })}
            </Button>
          </div>
        </Card>
      ) : result && sortedGroups.length === 0 ? (
        <Card className="p-6 text-center">
          <p className="text-sm text-content-tertiary">{t('explorer.no_groups', { defaultValue: 'No groups found. Try different columns.' })}</p>
        </Card>
      ) : null}

      {/* Create BOQ Modal */}
      <CreateBOQFromPivotModal
        open={showCreateBOQ}
        onClose={() => setShowCreateBOQ(false)}
        groups={sortedGroups}
        groupByColumns={groupBy}
        aggColumns={aggCols}
      />
    </div>
  );
}

/* ── Charts Tab (Recharts, lazy-loaded) ───────────────────────────────── */

/** Category palette — deliberately hardcoded for consistent data viz. */
const BAR_COLORS = [
  '#3B82F6', '#22C55E', '#F97316', '#A855F7', '#EF4444',
  '#06B6D4', '#EC4899', '#84CC16', '#F59E0B', '#6366F1',
];

interface ChartSlice {
  label: string;
  value: number;
  count: number;
  colour: string;
  /** Original aggregated group — used for the drill-down modal. */
  group: AggregateGroup;
}

interface DrillContext {
  label: string;
  slice: ChartSlice;
}

function ChartsTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const chart = useAnalysisStateStore((s) => s.chart);
  const setChartConfig = useAnalysisStateStore((s) => s.setChartConfig);
  const slicers = useAnalysisStateStore((s) => s.slicers);
  const addSlicer = useAnalysisStateStore((s) => s.addSlicer);

  // For charts: text columns with reasonable cardinality (< 100 unique for good visualization)
  const stringCols = describe.columns
    .filter((c) => c.dtype === 'string' && c.non_null > 0 && c.unique < 100)
    .sort((a, b) => b.non_null - a.non_null);
  const QTY_KEYS = ['volume', 'area', 'length', 'count', 'width', 'height', 'depth', 'weight', 'mass', 'perimeter'];
  const numericCols = useMemo(() => describe.columns
    .filter((c) => c.dtype === 'number' && c.non_null > 0)
    .sort((a, b) => {
      const aK = QTY_KEYS.some((k) => a.name.toLowerCase() === k) ? 10000 : QTY_KEYS.some((k) => a.name.toLowerCase().includes(k)) ? 5000 : 0;
      const bK = QTY_KEYS.some((k) => b.name.toLowerCase() === k) ? 10000 : QTY_KEYS.some((k) => b.name.toLowerCase().includes(k)) ? 5000 : 0;
      return (bK + b.non_null) - (aK + a.non_null);
    })
    .slice(0, 20), [describe]);

  // Initialise chart config on first mount (if empty) — leave user choices
  // intact on subsequent renders.
  useEffect(() => {
    if (chart.category && chart.value) return;
    const defaultCat =
      stringCols.find((c) => c.name.toLowerCase() === 'category')?.name ||
      stringCols[0]?.name ||
      '';
    const defaultVal =
      numericCols.find((c) => c.name.toLowerCase() === 'volume')?.name ||
      numericCols[0]?.name ||
      '';
    if ((defaultCat && !chart.category) || (defaultVal && !chart.value)) {
      setChartConfig({
        category: chart.category || defaultCat,
        value: chart.value || defaultVal,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [describe]);

  const [chartData, setChartData] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [drill, setDrill] = useState<DrillContext | null>(null);

  const loadChart = useCallback(async () => {
    if (!chart.category || !chart.value) return;
    setLoading(true);
    try {
      const data = await aggregate(sessionId, [chart.category], { [chart.value]: 'sum' });
      setChartData(data);
    } catch { /* */ } finally { setLoading(false); }
  }, [sessionId, chart.category, chart.value]);

  useEffect(() => { loadChart(); }, [loadChart]);

  // Active slicers do NOT re-run the backend query — we filter client-side
  // so cross-filter is instant.
  const filteredGroups = useMemo(() => {
    if (!chartData) return [];
    if (slicers.length === 0) return chartData.groups;
    return chartData.groups.filter((g) => groupMatchesSlicers(g, slicers));
  }, [chartData, slicers]);

  const slicedGroups = useMemo(() => {
    return applyTopN(filteredGroups, chart.value, chart.topN, chart.topNDirection, chart.category)
      .slice(0, chart.topN ?? 20);
  }, [filteredGroups, chart.value, chart.topN, chart.topNDirection, chart.category]);

  const chartSlices: ChartSlice[] = useMemo(() =>
    slicedGroups.map((g, i) => ({
      label: String(g.key[chart.category] ?? '—') || '—',
      value: g.results[chart.value] ?? 0,
      count: g.count,
      colour: BAR_COLORS[i % BAR_COLORS.length]!,
      group: g,
    })),
    [slicedGroups, chart.category, chart.value],
  );

  // Debounced cross-filter — RFC 16 §6: coalesce rapid clicks.
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleSliceClick = useCallback((slice: ChartSlice) => {
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current);
    clickTimerRef.current = setTimeout(() => {
      addSlicer(chart.category, [slice.label]);
    }, 100);
  }, [addSlicer, chart.category]);

  const handleDrillDown = useCallback((slice: ChartSlice) => {
    setDrill({ label: slice.label, slice });
  }, []);

  // Close drill modal when the underlying data changes shape.
  useEffect(() => {
    if (drill && !chartSlices.some((s) => s.label === drill.label)) setDrill(null);
  }, [chartSlices, drill]);

  const formatForDisplay = useCallback((v: number | null | undefined): string =>
    formatValue(v, chart.format),
    [chart.format],
  );

  const fmtChartValue = useCallback((v: number | string): string =>
    formatChartValue(v, chart.format),
    [chart.format],
  );

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.group_by', { defaultValue: 'Group By' })}</label>
            <select
              value={chart.category}
              onChange={(e) => setChartConfig({ category: e.target.value })}
              className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs"
              data-testid="chart-category-select"
            >
              {stringCols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.value', { defaultValue: 'Value' })}</label>
            <select
              value={chart.value}
              onChange={(e) => setChartConfig({ value: e.target.value })}
              className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs"
              data-testid="chart-value-select"
            >
              {numericCols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.chart_type', { defaultValue: 'Type' })}</label>
            <div className="flex gap-1">
              {([
                { k: 'bar' as ChartKind, Icon: BarChart3, labelKey: 'explorer.bar', fallback: 'Bar' },
                { k: 'line' as ChartKind, Icon: LineChartIcon, labelKey: 'explorer.line', fallback: 'Line' },
                { k: 'pie' as ChartKind, Icon: PieChart, labelKey: 'explorer.pie', fallback: 'Pie' },
                { k: 'scatter' as ChartKind, Icon: ScatterIcon, labelKey: 'explorer.scatter', fallback: 'Scatter' },
              ]).map(({ k, Icon, labelKey, fallback }) => (
                <button
                  key={k}
                  onClick={() => setChartConfig({ kind: k })}
                  className={`px-2 py-1 rounded text-2xs font-medium border ${
                    chart.kind === k
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : 'border-border text-content-tertiary'
                  }`}
                  data-testid={`chart-type-${k}`}
                >
                  <Icon size={12} className="inline mr-1" />{t(labelKey, { defaultValue: fallback })}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.format', { defaultValue: 'Format' })}</label>
            <select
              value={chart.format}
              onChange={(e) => setChartConfig({ format: e.target.value as ChartFormat })}
              className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs"
              data-testid="chart-format-select"
            >
              <option value="number">{t('explorer.format_number', { defaultValue: 'Number' })}</option>
              <option value="currency">{t('explorer.format_currency', { defaultValue: 'Currency' })}</option>
              <option value="percent">{t('explorer.format_percent', { defaultValue: 'Percent' })}</option>
            </select>
          </div>
        </div>

        <div className="mt-3">
          <TopNToggle
            value={chart.topN}
            direction={chart.topNDirection}
            onChange={(n, dir) => setChartConfig({ topN: n, topNDirection: dir })}
            testIdPrefix="chart"
          />
        </div>

        <p className="mt-2 text-2xs text-content-quaternary">
          {t('explorer.chart_click_hint', { defaultValue: 'Click a bar / slice / point to cross-filter' })}
        </p>
      </Card>

      {loading ? (
        <div className="flex items-center justify-center py-12" data-testid="chart-loading">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      ) : chartData && chartSlices.length > 0 ? (
        <Card className="p-4" data-testid="chart-canvas">
          <LazyRechart
            slices={chartSlices}
            kind={chart.kind}
            formatAxis={fmtChartValue}
            onSliceClick={handleSliceClick}
            onSliceDoubleClick={handleDrillDown}
          />
          <div className="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              data-testid="chart-drill-first"
              onClick={() => chartSlices[0] && handleDrillDown(chartSlices[0])}
              className="text-2xs text-content-tertiary hover:text-content-primary underline underline-offset-2"
            >
              {t('explorer.drill_down_title', { defaultValue: 'Rows for {{label}}', label: chartSlices[0]?.label || '' })}
            </button>
          </div>
        </Card>
      ) : (
        <EmptyState
          icon={<BarChart3 size={28} strokeWidth={1.5} />}
          title={t('explorer.no_chart_data', { defaultValue: 'No chart data' })}
          description={t('explorer.select_columns_for_chart', { defaultValue: 'Select group by and value columns to generate a chart.' })}
        />
      )}

      <DrillDownModal
        open={!!drill}
        onClose={() => setDrill(null)}
        sessionId={sessionId}
        categoryCol={chart.category}
        valueCol={chart.value}
        slice={drill?.slice ?? null}
        format={chart.format}
        formatValue={formatForDisplay}
      />
    </div>
  );
}

/* ── Lazy-loaded Recharts surface ─────────────────────────────────────── */

interface LazyRechartProps {
  slices: ChartSlice[];
  kind: ChartKind;
  formatAxis: (v: number | string) => string;
  onSliceClick: (slice: ChartSlice) => void;
  onSliceDoubleClick: (slice: ChartSlice) => void;
}

function LazyRechart({ slices, kind, formatAxis, onSliceClick, onSliceDoubleClick }: LazyRechartProps) {
  const { t } = useTranslation();
  const { api, error } = useRecharts();

  if (error) {
    return (
      <p className="text-xs text-red-500 py-6 text-center">
        Recharts failed to load: {error.message}
      </p>
    );
  }
  if (!api) {
    return (
      <div className="flex items-center justify-center py-12" data-testid="chart-recharts-loading">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
      </div>
    );
  }

  const {
    ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
    LineChart, Line, PieChart: RPieChart, Pie, Cell,
    ScatterChart, Scatter, ZAxis,
  } = api;

  const data = slices.map((s, i) => ({
    name: s.label,
    value: s.value,
    count: s.count,
    index: i,
  }));

  // Recharts v3 type signatures are quite strict; use a permissive wrapper
  // that accepts their opaque event payloads. We narrow inside the body.
  const tooltipFormatter = ((v: unknown): string => formatAxis(v as number)) as unknown as (
    value: unknown,
    name: unknown,
    entry: unknown,
    index: number,
    payload: unknown,
  ) => string;

  const handleChartClick = (payload: unknown): void => {
    const p = payload as { activePayload?: Array<{ payload?: { index?: number } }> } | null;
    const idx = p?.activePayload?.[0]?.payload?.index;
    if (idx != null && slices[idx]) onSliceClick(slices[idx]!);
  };
  const handleCellClick = (index: number): void => {
    if (slices[index]) onSliceClick(slices[index]!);
  };
  const handleDoubleClickRow = (idx: number): void => {
    if (slices[idx]) onSliceDoubleClick(slices[idx]!);
  };
  // Cast slice-aware click handlers through unknown so they line up with
  // whichever Recharts overload the compiler picks this build.
  const pieClickHandler = ((d: { index?: number }): void => {
    if (d?.index != null && slices[d.index]) onSliceClick(slices[d.index]!);
  }) as unknown as () => void;
  const scatterClickHandler = ((d: { index?: number }): void => {
    if (d?.index != null && slices[d.index]) onSliceClick(slices[d.index]!);
  }) as unknown as () => void;
  const activeDotClickHandler = ((_e: unknown, d: { index?: number }): void => {
    if (d?.index != null && slices[d.index]) onSliceDoubleClick(slices[d.index]!);
  }) as unknown as () => void;

  if (kind === 'pie') {
    return (
      <div data-testid="chart-pie" className="w-full h-[360px]">
        <ResponsiveContainer width="100%" height="100%">
          <RPieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              outerRadius={120}
              isAnimationActive={false}
              onClick={pieClickHandler}
            >
              {data.map((_d, i) => (
                <Cell
                  key={`cell-${i}`}
                  fill={slices[i]?.colour}
                  onClick={() => handleCellClick(i)}
                  onDoubleClick={() => handleDoubleClickRow(i)}
                  style={{ cursor: 'pointer' }}
                />
              ))}
            </Pie>
            <Tooltip formatter={tooltipFormatter} />
          </RPieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (kind === 'line') {
    return (
      <div data-testid="chart-line" className="w-full h-[360px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} onClick={handleChartClick} margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="name" angle={-25} textAnchor="end" interval={0} height={60} fontSize={11} />
            <YAxis tickFormatter={(v: number) => formatAxis(v)} fontSize={11} />
            <Tooltip formatter={tooltipFormatter} />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#3B82F6"
              strokeWidth={2}
              dot={{ r: 4, stroke: '#3B82F6', strokeWidth: 2, fill: 'white' }}
              activeDot={{ r: 6, onClick: activeDotClickHandler }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (kind === 'scatter') {
    return (
      <div data-testid="chart-scatter" className="w-full h-[360px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="count" name="Count" fontSize={11} />
            <YAxis dataKey="value" name="Value" tickFormatter={(v: number) => formatAxis(v)} fontSize={11} />
            <ZAxis range={[60, 240]} />
            <Tooltip cursor={{ strokeDasharray: '3 3' }} formatter={tooltipFormatter} />
            <Scatter
              data={data}
              fill="#3B82F6"
              isAnimationActive={false}
              onClick={scatterClickHandler}
            >
              {data.map((_d, i) => (
                <Cell key={`sc-${i}`} fill={slices[i]?.colour} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    );
  }

  // Default: bar
  return (
    <div data-testid="chart-bar" className="w-full h-[360px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} onClick={handleChartClick} margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="name" angle={-25} textAnchor="end" interval={0} height={60} fontSize={11} />
          <YAxis tickFormatter={(v: number) => formatAxis(v)} fontSize={11} />
          <Tooltip formatter={tooltipFormatter} />
          <Bar dataKey="value" isAnimationActive={false}>
            {data.map((_d, i) => (
              <Cell
                key={`bar-${i}`}
                fill={slices[i]?.colour}
                onClick={() => handleCellClick(i)}
                onDoubleClick={() => handleDoubleClickRow(i)}
                style={{ cursor: 'pointer' }}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {/* Reserve testing hook so E2E can reliably trigger a drill-down. */}
      <button
        type="button"
        data-testid="chart-drill-first-bar"
        onClick={() => slices[0] && onSliceDoubleClick(slices[0])}
        className="sr-only"
      >
        {t('explorer.drill_down_title', { defaultValue: 'Drill down', label: '' })}
      </button>
    </div>
  );
}

/* ── Drill-down modal ─────────────────────────────────────────────────── */

interface DrillDownModalProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  categoryCol: string;
  valueCol: string;
  slice: ChartSlice | null;
  format: ChartFormat;
  formatValue: (v: number | null | undefined) => string;
}

function DrillDownModal({
  open, onClose, sessionId, categoryCol, valueCol, slice, format: _fmt, formatValue: fmt,
}: DrillDownModalProps) {
  const { t } = useTranslation();

  const { data, isLoading } = useQuery({
    queryKey: ['cad-elements', 'drill', sessionId, categoryCol, slice?.label],
    queryFn: () => fetchElements(sessionId, {
      offset: 0,
      limit: 200,
      filter_column: categoryCol,
      filter_value: slice?.label ?? '',
    }),
    enabled: open && !!slice,
  });

  if (!open || !slice) return null;

  const rows = data?.rows ?? [];
  const cols: string[] = data?.columns
    ? (() => {
        const priority = [categoryCol, valueCol, 'Category', 'Type Name', 'Family', 'Level'];
        const uniq = Array.from(new Set([...priority.filter((c) => data.columns.includes(c)), ...data.columns]));
        return uniq.slice(0, 8);
      })()
    : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" data-testid="chart-drill-modal">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <div className="relative w-full max-w-3xl mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-border-light">
          <div>
            <h2 className="text-base font-semibold text-content-primary">
              {t('explorer.drill_down_title', { defaultValue: 'Rows for {{label}}', label: slice.label })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {categoryCol} = {slice.label} · {valueCol} = {fmt(slice.value)}
            </p>
          </div>
          <button
            onClick={onClose}
            data-testid="chart-drill-close"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 max-h-[60vh] overflow-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-xs text-content-tertiary text-center py-6">
              {t('explorer.drill_down_empty', { defaultValue: 'No rows match this slice.' })}
            </p>
          ) : (
            <>
              <p className="text-2xs text-content-quaternary mb-2">
                {t('explorer.showing_rows', { defaultValue: 'Showing {{count}} rows', count: rows.length })}
              </p>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    {cols.map((c) => (
                      <th key={c} className="px-2 py-1.5 text-left font-medium text-content-tertiary whitespace-nowrap">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={`drill-row-${i}`} className="border-b border-border-light">
                      {cols.map((c) => {
                        const v = row[c];
                        const isNum = typeof v === 'number';
                        return (
                          <td key={c} className={`px-2 py-1.5 truncate max-w-[160px] ${isNum ? 'text-right tabular-nums' : ''}`}>
                            {v == null || v === '' ? <span className="text-content-quaternary italic">null</span> : isNum ? formatNumber(v) : String(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-border-light">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('explorer.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Saved views drawer ───────────────────────────────────────────────── */

interface ViewsDrawerProps {
  open: boolean;
  onClose: () => void;
}

function ViewsDrawer({ open, onClose }: ViewsDrawerProps) {
  const { t } = useTranslation();
  const views = useAnalysisStateStore((s) => s.views);
  const loadView = useAnalysisStateStore((s) => s.loadView);
  const deleteView = useAnalysisStateStore((s) => s.deleteView);
  const addToast = useToastStore((s) => s.addToast);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40" data-testid="views-drawer">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="absolute right-0 top-0 bottom-0 w-80 bg-surface-elevated border-l border-border-light shadow-xl overflow-y-auto">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-light sticky top-0 bg-surface-elevated">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('explorer.saved_views', { defaultValue: 'Saved views' })}
          </h3>
          <button onClick={onClose} className="h-7 w-7 rounded-lg hover:bg-surface-hover flex items-center justify-center" data-testid="views-drawer-close">
            <X size={16} />
          </button>
        </div>
        <div className="p-3 space-y-2">
          {views.length === 0 ? (
            <p className="text-xs text-content-tertiary py-6 text-center">
              {t('explorer.no_saved_views', {
                defaultValue: 'No saved views yet. Save your filters, chart and pivot configuration for later.',
              })}
            </p>
          ) : (
            views.map((v) => (
              <div
                key={v.id}
                data-testid={`view-item-${v.id}`}
                className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2.5"
              >
                <p className="text-sm font-medium text-content-primary truncate">{v.name}</p>
                <p className="text-2xs text-content-quaternary">
                  {new Date(v.createdAt).toLocaleString()} · {v.slicers.length} filters · {v.chart.kind}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      loadView(v.id);
                      addToast({ type: 'success', title: t('explorer.view_loaded', { defaultValue: 'View restored' }) });
                      onClose();
                    }}
                    data-testid={`view-load-${v.id}`}
                  >
                    {t('explorer.load_view', { defaultValue: 'Load' })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteView(v.id)}
                    data-testid={`view-delete-${v.id}`}
                  >
                    <Trash2 size={12} className="mr-1" />
                    {t('explorer.delete_view', { defaultValue: 'Delete' })}
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>
    </div>
  );
}

/* ── Describe Tab ──────────────────────────────────────────────────────── */

type DescribeSubTab = 'summary' | 'missing';

function DescribeTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const [selectedCol, setSelectedCol] = useState<string | null>(null);
  const [subTab, setSubTab] = useState<DescribeSubTab>('summary');

  const { data: vcData } = useQuery({
    queryKey: ['cad-value-counts', sessionId, selectedCol],
    queryFn: () => valueCounts(sessionId, selectedCol!, 30),
    enabled: !!selectedCol && subTab === 'summary',
  });

  // Data quality score
  const qualityScore = useMemo(() => {
    const totalCells = describe.columns.length * describe.total_elements;
    const filledCells = describe.columns.reduce((s, c) => s + c.non_null, 0);
    return totalCells > 0 ? (filledCells / totalCells) * 100 : 0;
  }, [describe]);
  const lowCoverageCols = useMemo(() =>
    describe.columns.filter((c) => c.non_null < describe.total_elements * 0.1 && c.non_null > 0).length,
  [describe]);

  const subTabBtn = (id: DescribeSubTab, label: string) => (
    <button
      key={id}
      type="button"
      onClick={() => setSubTab(id)}
      data-testid={`describe-subtab-${id}`}
      className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
        subTab === id
          ? 'bg-oe-blue text-white border-oe-blue'
          : 'bg-surface-primary text-content-secondary border-border-light hover:bg-surface-secondary'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-4">
      {/* Sub-tab switch */}
      <div className="flex items-center gap-2">
        {subTabBtn('summary', t('explorer.describe_subtab_summary', { defaultValue: 'Summary' }))}
        {subTabBtn(
          'missing',
          t('explorer.describe_subtab_missing', { defaultValue: 'Missing Data' }),
        )}
      </div>

      {subTab === 'missing' ? (
        <MissingDataPanel sessionId={sessionId} />
      ) : (
        <DescribeSummary
          describe={describe}
          selectedCol={selectedCol}
          setSelectedCol={setSelectedCol}
          vcData={vcData}
          qualityScore={qualityScore}
          lowCoverageCols={lowCoverageCols}
        />
      )}
    </div>
  );
}

interface DescribeSummaryProps {
  describe: DescribeResponse;
  selectedCol: string | null;
  setSelectedCol: (v: string | null) => void;
  vcData: Awaited<ReturnType<typeof valueCounts>> | undefined;
  qualityScore: number;
  lowCoverageCols: number;
}

function DescribeSummary({
  describe,
  selectedCol,
  setSelectedCol,
  vcData,
  qualityScore,
  lowCoverageCols,
}: DescribeSummaryProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      {/* Data quality summary */}
      <div className="grid grid-cols-3 gap-3">
        <Card className="p-3">
          <p className="text-2xs text-content-tertiary uppercase">{t('explorer.data_completeness', { defaultValue: 'Data Completeness' })}</p>
          <p className={`text-lg font-bold tabular-nums ${qualityScore > 50 ? 'text-green-600' : qualityScore > 20 ? 'text-amber-600' : 'text-red-500'}`}>
            {qualityScore.toFixed(1)}%
          </p>
        </Card>
        <Card className="p-3">
          <p className="text-2xs text-content-tertiary uppercase">{t('explorer.useful_columns', { defaultValue: 'Useful Columns' })}</p>
          <p className="text-lg font-bold text-content-primary tabular-nums">
            {describe.columns.filter((c) => c.non_null > describe.total_elements * 0.5).length}
            <span className="text-xs text-content-quaternary font-normal ml-1">/ {describe.total_columns}</span>
          </p>
        </Card>
        <Card className="p-3">
          <p className="text-2xs text-content-tertiary uppercase">{t('explorer.sparse_columns', { defaultValue: 'Sparse (<10%)' })}</p>
          <p className="text-lg font-bold text-amber-600 tabular-nums">{lowCoverageCols}</p>
        </Card>
      </div>

      {/* Column statistics table */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 py-3 border-b border-border-light bg-surface-secondary/30">
          <h3 className="text-xs font-semibold text-content-primary">
            {t('explorer.column_statistics', { defaultValue: 'Column Statistics' })}
            <span className="ml-2 text-content-tertiary font-normal">({t('explorer.like_describe', { defaultValue: 'like df.describe()' })})</span>
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-surface-secondary/50">
                <th className="px-3 py-2 text-left font-medium text-content-tertiary">{t('explorer.column', { defaultValue: 'Column' })}</th>
                <th className="px-3 py-2 text-left font-medium text-content-tertiary">{t('explorer.type', { defaultValue: 'Type' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.non_null', { defaultValue: 'Non-Null' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.unique', { defaultValue: 'Unique' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.min', { defaultValue: 'Min' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.max', { defaultValue: 'Max' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.mean', { defaultValue: 'Mean' })}</th>
                <th className="px-3 py-2 text-right font-medium text-content-tertiary">{t('explorer.sum', { defaultValue: 'Sum' })}</th>
                <th className="px-3 py-2 text-left font-medium text-content-tertiary">{t('explorer.top_value', { defaultValue: 'Top Value' })}</th>
              </tr>
            </thead>
            <tbody>
              {describe.columns.map((col) => (
                <tr
                  key={col.name}
                  className={`border-b border-border-light cursor-pointer transition-colors ${selectedCol === col.name ? 'bg-oe-blue-subtle/30' : 'hover:bg-surface-secondary/30'}`}
                  onClick={() => setSelectedCol(col.name)}
                >
                  <td className="px-3 py-2 font-medium text-content-primary">{col.name}</td>
                  <td className="px-3 py-2">
                    <Badge variant={col.dtype === 'number' ? 'blue' : 'neutral'} size="sm">{col.dtype}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{col.non_null.toLocaleString()}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{col.unique.toLocaleString()}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{col.min != null ? formatNumber(col.min) : '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{col.max != null ? formatNumber(col.max) : '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{col.mean != null ? formatNumber(col.mean) : '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">{col.sum != null ? formatNumber(col.sum) : '—'}</td>
                  <td className="px-3 py-2 text-content-secondary truncate max-w-[150px]">
                    {col.top ? `${col.top} (${col.top_freq})` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Value counts for selected column */}
      {selectedCol && vcData && (
        <Card className="p-4">
          <h3 className="text-xs font-semibold text-content-primary mb-3">
            {t('explorer.value_counts_for', { defaultValue: 'Value Counts: {{column}}', column: selectedCol })}
            <span className="ml-2 text-content-tertiary font-normal">({vcData.total.toLocaleString()} total)</span>
          </h3>
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {vcData.values.map((v) => (
              <div key={`${v.value}`} className="flex items-center gap-3">
                <span className="w-36 text-xs text-content-secondary truncate shrink-0">{v.value || '(empty)'}</span>
                <div className="flex-1 h-5 bg-surface-secondary rounded overflow-hidden relative">
                  <div
                    className="h-full rounded bg-oe-blue/60 transition-all"
                    style={{ width: `${v.percentage}%` }}
                  />
                </div>
                <span className="text-2xs text-content-primary tabular-nums w-16 text-right shrink-0">{v.count.toLocaleString()}</span>
                <span className="text-2xs text-content-quaternary tabular-nums w-12 text-right shrink-0">{v.percentage.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Converter Status (compact) ─────────────────────────────────────────── */

/* ── Create BOQ from Pivot Modal ─────────────────────────────────────── */

interface PivotBOQModalProps {
  open: boolean;
  onClose: () => void;
  groups: AggregateGroup[];
  groupByColumns: string[];
  aggColumns: string[];
}

function CreateBOQFromPivotModal({ open, onClose, groups, groupByColumns, aggColumns }: PivotBOQModalProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [projectId, setProjectId] = React.useState(activeProjectId ?? '');
  const [boqId, setBoqId] = React.useState('');
  const [creating, setCreating] = React.useState(false);

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/v1/projects/'),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => apiGet<{ id: string; name: string; status: string }[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: open && !!projectId,
  });

  // Auto-select first BOQ
  React.useEffect(() => {
    if (boqs && boqs.length > 0 && !boqId) setBoqId(boqs[0]!.id);
  }, [boqs, boqId]);

  // Detect quantity column from aggregation results
  const quantityCol = React.useMemo(() => {
    const qtyKeywords = ['volume', 'area', 'length', 'quantity', 'count', 'weight', 'mass'];
    for (const col of aggColumns) {
      if (qtyKeywords.some((kw) => col.toLowerCase().includes(kw))) return col;
    }
    return aggColumns[0] || 'count';
  }, [aggColumns]);

  const unitGuess = React.useMemo(() => {
    const col = quantityCol.toLowerCase();
    if (col.includes('volume')) return 'm\u00B3';
    if (col.includes('area')) return 'm\u00B2';
    if (col.includes('length')) return 'm';
    if (col.includes('weight') || col.includes('mass')) return 'kg';
    return 'pcs';
  }, [quantityCol]);

  const handleCreate = React.useCallback(async () => {
    if (!boqId || groups.length === 0) return;
    setCreating(true);
    try {
      let ordinal = 1;
      for (const group of groups) {
        const description = groupByColumns
          .map((col) => group.key[col] || '')
          .filter(Boolean)
          .join(' — ');

        const quantity = group.results[`sum_${quantityCol}`]
          ?? group.results[`avg_${quantityCol}`]
          ?? group.count;

        await apiPost(`/v1/boq/boqs/${boqId}/positions/`, {
          boq_id: boqId,
          ordinal: String(ordinal).padStart(2, '0') + '.001',
          description: description || `Group ${ordinal}`,
          unit: unitGuess,
          quantity: Math.round(quantity * 100) / 100,
          unit_rate: 0,
          classification: {},
          source: 'cad_import',
          metadata: {
            cad_group_key: group.key,
            cad_element_count: group.count,
            cad_aggregations: group.results,
          },
        });
        ordinal++;
      }

      addToast({
        type: 'success',
        title: t('explorer.boq_created_success', { defaultValue: '{{count}} positions created in BOQ', count: groups.length }),
      });
      onClose();
      navigate(`/boq/${boqId}`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('explorer.boq_create_failed', { defaultValue: 'Failed to create BOQ positions' }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setCreating(false);
    }
  }, [boqId, groups, groupByColumns, quantityCol, unitGuess, addToast, onClose, navigate, t]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <div className="relative w-full max-w-lg mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10">
              <Table2 size={20} className="text-accent-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('explorer.create_boq_title', { defaultValue: 'Create BOQ from Pivot' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('explorer.create_boq_subtitle', { defaultValue: '{{count}} groups will become BOQ positions', count: groups.length })}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pb-6 space-y-4">
          {/* Project selector */}
          <div>
            <label className="text-xs font-medium text-content-secondary mb-1.5 flex items-center gap-1.5">
              <FolderOpen size={12} />
              {t('common.project', { defaultValue: 'Project' })}
            </label>
            <select
              value={projectId}
              onChange={(e) => { setProjectId(e.target.value); setBoqId(''); }}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            >
              <option value="">{t('projects.select_project', { defaultValue: 'Select project...' })}</option>
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>

          {/* BOQ selector */}
          {projectId && (
            <div>
              <label className="text-xs font-medium text-content-secondary mb-1.5 flex items-center gap-1.5">
                <Table2 size={12} />
                {t('boq.title', { defaultValue: 'Bill of Quantities' })}
              </label>
              <select
                value={boqId}
                onChange={(e) => setBoqId(e.target.value)}
                className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                <option value="">{t('boq.select_boq', { defaultValue: 'Select BOQ...' })}</option>
                {boqs?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
          )}

          {/* Preview */}
          <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-3 max-h-40 overflow-y-auto">
            <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider mb-2">
              {t('explorer.positions_preview', { defaultValue: 'Positions Preview' })}
            </p>
            <div className="space-y-1">
              {groups.slice(0, 8).map((g, i) => {
                const desc = groupByColumns.map((col) => g.key[col] || '').filter(Boolean).join(' — ');
                const qty = g.results[`sum_${quantityCol}`] ?? g.results[`avg_${quantityCol}`] ?? g.count;
                return (
                  <div key={Object.values(g.key).join('-') || `group-${i}`} className="flex items-center justify-between text-xs">
                    <span className="text-content-primary truncate flex-1 mr-2">{desc || `Group ${i + 1}`}</span>
                    <span className="text-content-tertiary tabular-nums shrink-0">{Math.round(qty * 100) / 100} {unitGuess}</span>
                  </div>
                );
              })}
              {groups.length > 8 && (
                <p className="text-2xs text-content-quaternary">+{groups.length - 8} {t('common.more', { defaultValue: 'more' })}</p>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" onClick={onClose}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={handleCreate} loading={creating} disabled={!boqId || groups.length === 0}>
              {t('explorer.create_positions', { defaultValue: 'Create {{count}} Positions', count: groups.length })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}


/* ── Upload & Convert Zone ──────────────────────────────────────────────── */

const CAD_ACCEPT = '.rvt,.ifc,.dwg,.dgn,.dxf,.rfa';
const CAD_FORMATS = ['RVT', 'IFC', 'DWG', 'DGN', 'DXF', 'RFA'];
const FORMAT_COLORS: Record<string, string> = {
  RVT: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  IFC: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  DWG: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  DGN: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  DXF: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  RFA: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
};

function UploadConvertZone({
  onSessionReady,
}: {
  onSessionReady: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState('');
  const [fileSizeMB, setFileSizeMB] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [done, setDone] = useState(false);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const estimatedTotal = Math.max(30, (fileSizeMB / 50) * 60);
  const progressPct = uploading ? Math.min(95, (elapsed / estimatedTotal) * 100) : done ? 100 : 0;
  const remaining = Math.max(0, Math.round(estimatedTotal - elapsed));

  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);

  const handleFile = useCallback(async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    if (!['rvt', 'ifc', 'dwg', 'dgn', 'dxf', 'rfa'].includes(ext)) {
      addToast({ type: 'warning', title: t('explorer.invalid_format', { defaultValue: 'Unsupported file format. Use RVT, IFC, DWG, or DGN.' }) });
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      addToast({ type: 'warning', title: t('explorer.file_too_large', { defaultValue: 'File exceeds 100 MB limit.' }) });
      return;
    }

    const taskId = crypto.randomUUID();
    const sizeMB = file.size / (1024 * 1024);
    const estimatedSec = Math.max(30, (sizeMB / 50) * 60);

    setFileName(file.name);
    setFileSizeMB(sizeMB);
    setUploading(true);
    setElapsed(0);
    setDone(false);

    // Add to global queue (visible in header even if user navigates away)
    addQueueTask({
      id: taskId,
      type: 'cad_convert',
      filename: file.name,
      status: 'processing',
      progress: 0,
      message: t('explorer.converting_msg', { defaultValue: 'Converting...' }),
    });

    const start = Date.now();
    elapsedRef.current = setInterval(() => {
      const sec = Math.floor((Date.now() - start) / 1000);
      setElapsed(sec);
      const pct = Math.min(95, (sec / estimatedSec) * 100);
      updateQueueTask(taskId, {
        progress: pct,
        message: `${Math.round(pct)}% — ~${Math.max(0, Math.round(estimatedSec - sec))}s`,
      });
    }, 1000);

    try {
      const { useAuthStore } = await import('@/stores/useAuthStore');
      const token = useAuthStore.getState().accessToken;
      const form = new FormData();
      form.append('file', file);

      const res = await fetch('/api/v1/takeoff/cad-columns/', {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          'X-DDC-Client': 'OE/1.0',
          Accept: 'application/json',
        },
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || 'Conversion failed');
      }

      const data = await res.json();
      if (elapsedRef.current) clearInterval(elapsedRef.current);
      setUploading(false);
      setDone(true);

      updateQueueTask(taskId, {
        status: 'completed',
        progress: 100,
        message: `${data.total_elements} elements`,
        resultSessionId: data.session_id,
        resultUrl: `/data-explorer?session=${data.session_id}`,
        completedAt: Date.now(),
      });

      addToast({
        type: 'success',
        title: t('explorer.conversion_complete', { defaultValue: 'Conversion complete' }),
        message: t('explorer.elements_detected', { defaultValue: '{{count}} elements detected', count: data.total_elements }),
      });

      setTimeout(() => onSessionReady(data.session_id), 500);
    } catch (err) {
      if (elapsedRef.current) clearInterval(elapsedRef.current);
      setUploading(false);

      updateQueueTask(taskId, {
        status: 'error',
        progress: 0,
        error: err instanceof Error ? err.message : 'Unknown error',
        completedAt: Date.now(),
      });

      addToast({
        type: 'error',
        title: t('explorer.conversion_failed', { defaultValue: 'Conversion failed' }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  }, [addToast, t, onSessionReady, addQueueTask, updateQueueTask]);

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
        onClick={() => !uploading && inputRef.current?.click()}
        className={`relative rounded-2xl border-2 border-dashed transition-all cursor-pointer ${
          uploading ? 'pointer-events-none border-oe-blue/40 bg-oe-blue-subtle/5' :
          dragOver ? 'border-oe-blue bg-oe-blue-subtle/10 scale-[1.005] shadow-lg shadow-oe-blue/10' :
          'border-border-light hover:border-oe-blue/50 hover:bg-surface-secondary/20'
        }`}
      >
        <input ref={inputRef} type="file" accept={CAD_ACCEPT} onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }} className="hidden" />

        {uploading ? (
          <div className="px-6 py-5 space-y-3">
            <div className="flex items-center gap-4">
              <Loader2 size={20} className="text-oe-blue animate-spin shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-content-primary truncate">{t('explorer.converting', { defaultValue: 'Converting {{name}}...', name: fileName })}</p>
                <p className="text-2xs text-content-tertiary">{remaining > 0 ? `~${remaining}s remaining` : 'Finalizing...'}</p>
              </div>
              <span className="text-lg font-bold text-oe-blue tabular-nums shrink-0">{Math.round(progressPct)}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div className="h-full rounded-full bg-oe-blue transition-all duration-1000" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        ) : done ? (
          <div className="flex items-center justify-center gap-2 px-6 py-5">
            <CheckCircle2 size={18} className="text-green-500" />
            <p className="text-sm font-medium text-green-600">{t('explorer.done', { defaultValue: 'Conversion complete! Loading...' })}</p>
          </div>
        ) : (
          <div className="px-8 py-10">
            <div className="flex flex-col items-center text-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-oe-blue/10 to-blue-50 dark:from-oe-blue/20 dark:to-blue-900/10 border border-oe-blue/10">
                <FileUp size={30} className="text-oe-blue" />
              </div>
              <div>
                <p className="text-base font-bold text-content-primary mb-1">
                  {t('explorer.drop_cad', { defaultValue: 'Drop your IFC, RVT, DWG, or DGN file here' })}
                </p>
                <p className="text-sm text-content-tertiary">
                  {t('explorer.or_click', { defaultValue: 'or click to browse your files' })}
                </p>
              </div>
              <div className="flex items-center gap-2 mt-1">
                {CAD_FORMATS.map((fmt) => (
                  <span key={fmt} className={`px-2 py-1 rounded-lg text-2xs font-bold ${FORMAT_COLORS[fmt] || 'bg-gray-100 text-gray-600'}`}>.{fmt.toLowerCase()}</span>
                ))}
              </div>
              <p className="text-2xs text-content-quaternary">
                {t('explorer.max_file_size', { defaultValue: 'Max 100 MB' })} — {t('explorer.upload_auto', { defaultValue: 'Automatic conversion and element extraction' })}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Save Dialog ───────────────────────────────────────────────────────── */

function SaveDialog({
  sessionId,
  filename,
  onClose,
  onSaved,
}: {
  sessionId: string;
  filename: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const [name, setName] = useState(filename.replace(/\.[^.]+$/, '') + ' — Analysis');
  const [projectId, setProjectId] = useState(activeProjectId || '');
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!name.trim() || !projectId) return;
    setSaving(true);
    try {
      await saveSession(sessionId, projectId, name.trim());
      addToast({ type: 'success', title: t('explorer.saved', { defaultValue: 'Analysis saved permanently' }) });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err instanceof Error ? err.message : '' });
    } finally {
      setSaving(false);
    }
  }, [sessionId, projectId, name, addToast, t, onSaved, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-md mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-content-primary mb-4">
          {t('explorer.save_analysis', { defaultValue: 'Save Analysis' })}
        </h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">{t('explorer.analysis_name', { defaultValue: 'Name' })}</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">{t('explorer.project', { defaultValue: 'Project' })}</label>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              <option value="" disabled>{t('explorer.select_project', { defaultValue: 'Select project...' })}</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" size="sm" onClick={handleSave} disabled={!name.trim() || !projectId || saving} loading={saving}>
            {t('explorer.save_permanently', { defaultValue: 'Save Permanently' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Save to Project (BIM) Dialog ─────────────────────────────────────── */

function SaveToProjectDialog({
  sessionId,
  filename,
  onClose,
  onSaved,
}: {
  sessionId: string;
  filename: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const [modelName, setModelName] = useState(filename.replace(/\.[^.]+$/, ''));
  const [projectId, setProjectId] = useState(activeProjectId || '');
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!modelName.trim() || !projectId) return;
    setSaving(true);
    try {
      const result = await apiPost<{ model_id: string; element_count: number }>(
        `/v1/takeoff/sessions/${sessionId}/save-to-project?project_id=${encodeURIComponent(projectId)}`,
        { model_name: modelName.trim() },
      );
      addToast({
        type: 'success',
        title: t('explorer.saved_to_project', { defaultValue: 'Saved to BIM Hub' }),
        message: t('explorer.saved_to_project_msg', {
          defaultValue:
            '{{count}} elements saved to BIM Hub. View them in the BIM Viewer.',
        }).replace('{{count}}', String(result.element_count)),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err instanceof Error ? err.message : 'Failed to save',
      });
    } finally {
      setSaving(false);
    }
  }, [sessionId, projectId, modelName, addToast, t, onSaved, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-md mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-content-primary mb-1">
          {t('explorer.save_to_project', { defaultValue: 'Save to Project (BIM Hub)' })}
        </h3>
        <p className="text-xs text-content-tertiary mb-4">
          {t('explorer.save_to_project_desc', { defaultValue: 'Creates a BIM model with all extracted elements in the selected project.' })}
        </p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">{t('explorer.model_name', { defaultValue: 'Model Name' })}</label>
            <input
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">{t('explorer.project', { defaultValue: 'Project' })}</label>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              <option value="" disabled>{t('explorer.select_project', { defaultValue: 'Select project...' })}</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" size="sm" onClick={handleSave} disabled={!modelName.trim() || !projectId || saving} loading={saving}>
            {t('explorer.save_as_bim', { defaultValue: 'Save as BIM Model' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CadDataExplorerPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get('session') || '';
  const [activeTab, setActiveTab] = useState<TabId>('table');
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showSaveToProjectDialog, setShowSaveToProjectDialog] = useState(false);
  const [showViewsDrawer, setShowViewsDrawer] = useState(false);

  const setAnalysisSession = useAnalysisStateStore((s) => s.setSessionId);
  const saveAnalysisView = useAnalysisStateStore((s) => s.saveView);
  const savedViewsCount = useAnalysisStateStore((s) => s.views.length);

  // Bind the analysis-state store to the active session. setSessionId is a
  // no-op when the id hasn't changed, so this is safe to run on every render.
  useEffect(() => {
    setAnalysisSession(sessionId || null);
  }, [sessionId, setAnalysisSession]);

  const { data: describe, isLoading, error } = useQuery({
    queryKey: ['cad-describe', sessionId],
    queryFn: () => describeSession(sessionId),
    enabled: !!sessionId,
  });

  const handleSessionReady = useCallback((newSessionId: string) => {
    setSearchParams({ session: newSessionId });
  }, [setSearchParams]);

  const handleSaveView = useCallback(() => {
    const name = window.prompt(
      t('explorer.save_view_prompt', { defaultValue: 'Name this view' }),
      new Date().toLocaleString(),
    );
    if (!name) return;
    saveAnalysisView(name);
    addToast({ type: 'success', title: t('explorer.view_saved', { defaultValue: 'View saved' }) });
    setShowViewsDrawer(true);
  }, [saveAnalysisView, addToast, t]);

  // Load all sessions for landing page
  const { data: allSessions = [] } = useQuery({
    queryKey: ['cad-all-sessions'],
    queryFn: () => listSessions(),
    enabled: !sessionId,
  });

  const deleteSessionMutation = useMutation({
    mutationFn: (sid: string) => deleteSession(sid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cad-all-sessions'] });
    },
    onError: (err: Error) => {
      if (import.meta.env.DEV) console.error('Failed to delete CAD session:', err.message);
    },
  });

  if (!sessionId) {
    const recentSessions = allSessions.slice(0, 12);

    const FEATURE_CARDS: { icon: React.ElementType; title: string; desc: string; color: string; border: string; ic: string }[] = [
      { icon: Table2, title: t('explorer.feat_table', { defaultValue: 'Data Table' }), desc: t('explorer.feat_table_desc', { defaultValue: 'Browse all elements with sorting, filtering, and column selection. Export to CSV or Excel.' }), color: 'bg-blue-50 dark:bg-blue-950/20 border-blue-100 dark:border-blue-800', border: 'border-border-light/50', ic: 'text-blue-500' },
      { icon: Layers, title: t('explorer.feat_pivot', { defaultValue: 'Pivot Analysis' }), desc: t('explorer.feat_pivot_desc', { defaultValue: 'Group elements by storey, discipline, or type. Aggregate volumes, areas, and counts.' }), color: 'bg-purple-50 dark:bg-purple-950/20 border-purple-100 dark:border-purple-800', border: 'border-border-light/50', ic: 'text-purple-500' },
      { icon: BarChart3, title: t('explorer.feat_charts', { defaultValue: 'Charts' }), desc: t('explorer.feat_charts_desc', { defaultValue: 'Visualize quantity distributions with bar charts and pie charts.' }), color: 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-100 dark:border-emerald-800', border: 'border-border-light/50', ic: 'text-emerald-500' },
      { icon: TrendingUp, title: t('explorer.feat_stats', { defaultValue: 'Statistics' }), desc: t('explorer.feat_stats_desc', { defaultValue: 'Descriptive statistics for every numeric column -- min, max, mean, std dev.' }), color: 'bg-orange-50 dark:bg-orange-950/20 border-orange-100 dark:border-orange-800', border: 'border-border-light/50', ic: 'text-orange-500' },
    ];

    return (
      <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-6 border-s border-border-light animate-fade-in" style={{ height: 'calc(100vh - 56px)' }}>
        <div className="px-6 pt-4 pb-3 border-b border-border-light">
          <Breadcrumb items={[
            { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
            { label: t('explorer.title', { defaultValue: 'CAD-BIM Explorer' }) },
          ]} />
        </div>

        {/* Soft modern background — calm base gradient, muted blurred
            colour blobs, plus a barely-visible decorative spreadsheet
            grid behind everything so the "data explorer" identity is
            legible the moment the page paints. */}
        <div className="relative flex-1 overflow-hidden bg-gradient-to-br from-slate-50 via-white to-blue-50/30 dark:from-gray-950 dark:via-gray-900 dark:to-slate-900">
          {/* Decorative data table — SVG pattern at ~4-6% opacity.
              Header row + alternating row bands + fake column text
              blocks; all pointer-events:none so it never interferes. */}
          <svg
            aria-hidden
            className="pointer-events-none absolute inset-0 w-full h-full text-slate-400/40 dark:text-slate-300/20"
            preserveAspectRatio="xMidYMid slice"
            viewBox="0 0 1200 900"
          >
            <defs>
              <linearGradient id="tblFade" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="white" stopOpacity="0" />
                <stop offset="22%" stopColor="white" stopOpacity="1" />
                <stop offset="78%" stopColor="white" stopOpacity="1" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </linearGradient>
              <mask id="tblMask">
                <rect width="1200" height="900" fill="url(#tblFade)" />
              </mask>
            </defs>
            <g mask="url(#tblMask)" opacity="0.55">
              {/* Column separators (vertical faint lines) */}
              {[120, 300, 480, 660, 780, 900, 1020].map((x) => (
                <line key={x} x1={x} y1="40" x2={x} y2="860" stroke="currentColor" strokeWidth="0.6" strokeDasharray="2 3" />
              ))}
              {/* Header band */}
              <rect x="40" y="60" width="1120" height="34" rx="4" fill="currentColor" fillOpacity="0.08" />
              {[
                { x: 60, w: 50 },   { x: 140, w: 140 }, { x: 320, w: 140 },
                { x: 500, w: 140 }, { x: 680, w: 80 },  { x: 800, w: 80 },
                { x: 920, w: 80 },  { x: 1040, w: 70 },
              ].map((c, i) => (
                <rect key={`h-${i}`} x={c.x} y="72" width={c.w} height="10" rx="2" fill="currentColor" fillOpacity="0.35" />
              ))}
              {/* 18 data rows — alternating bands with text-block bars */}
              {Array.from({ length: 18 }).map((_, r) => {
                const y = 110 + r * 40;
                const rowBandOpacity = r % 2 === 0 ? 0 : 0.04;
                return (
                  <g key={`r-${r}`}>
                    <rect x="40" y={y} width="1120" height="34" fill="currentColor" fillOpacity={rowBandOpacity} />
                    {/* Id col (narrower) */}
                    <rect x="60" y={y + 13} width={28 + (r * 3) % 22} height="8" rx="1.5" fill="currentColor" fillOpacity="0.22" />
                    {/* Name cols (wider) */}
                    <rect x="140" y={y + 13} width={110 - (r * 7) % 40} height="8" rx="1.5" fill="currentColor" fillOpacity="0.18" />
                    <rect x="320" y={y + 13} width={120 - (r * 5) % 50} height="8" rx="1.5" fill="currentColor" fillOpacity="0.16" />
                    <rect x="500" y={y + 13} width={110 - (r * 3) % 35} height="8" rx="1.5" fill="currentColor" fillOpacity="0.18" />
                    {/* Numeric cols (right-aligned) */}
                    <rect x={760 - (r * 4) % 24} y={y + 13} width={20 + (r * 4) % 20} height="8" rx="1.5" fill="currentColor" fillOpacity="0.22" />
                    <rect x={880 - (r * 5) % 20} y={y + 13} width={20 + (r * 5) % 18} height="8" rx="1.5" fill="currentColor" fillOpacity="0.22" />
                    <rect x={1000 - (r * 6) % 16} y={y + 13} width={20 + (r * 6) % 16} height="8" rx="1.5" fill="currentColor" fillOpacity="0.22" />
                    {/* Badge-ish last col */}
                    <rect x="1040" y={y + 11} width={50 + (r * 5) % 20} height="14" rx="7" fill="currentColor" fillOpacity="0.12" />
                  </g>
                );
              })}
              {/* Horizontal grid lines between rows */}
              {Array.from({ length: 19 }).map((_, i) => (
                <line key={`hl-${i}`} x1="40" y1={110 + i * 40} x2="1160" y2={110 + i * 40} stroke="currentColor" strokeWidth="0.3" />
              ))}
            </g>
          </svg>
          <div aria-hidden className="pointer-events-none absolute -top-32 -left-32 w-[520px] h-[520px] rounded-full bg-blue-200/25 dark:bg-blue-500/8 blur-[140px]" />
          <div aria-hidden className="pointer-events-none absolute -bottom-32 -right-32 w-[520px] h-[520px] rounded-full bg-violet-200/20 dark:bg-violet-500/8 blur-[140px]" />
          <div className="absolute inset-0 overflow-y-auto overflow-x-hidden scrollbar-none z-10">
          <div className="relative max-w-7xl mx-auto px-6 pt-6 pb-4">

            {/* 2-column layout: Upload card (left) + Hero text (right) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-stretch mb-8">

              {/* LEFT — Upload card */}
              <div className="flex flex-col">
                <div className="rounded-2xl bg-white dark:bg-gray-800/60 border border-border-light shadow-lg shadow-black/5 dark:shadow-black/20 p-6 flex flex-col h-full">
                  <UploadConvertZone onSessionReady={handleSessionReady} />
                </div>
              </div>

              {/* RIGHT — Hero text + local-processing badge (chip
                  styled to match /bim and /dwg-takeoff). The
                  decorative animation was removed; the modern mesh
                  background carries the visual weight. */}
              <div className="flex flex-col justify-center gap-4">
                <div>
                  <h1 className="text-2xl font-bold text-content-primary tracking-tight leading-tight">
                    {t('explorer.hero_title', { defaultValue: 'CAD/BIM Data Explorer' })}
                  </h1>
                  <p className="text-base text-content-secondary mt-3 leading-relaxed">
                    {t('explorer.hero_subtitle', { defaultValue: 'Analyze building element data in a powerful spreadsheet interface. Filter, pivot, chart, and export quantities from your IFC and Revit models.' })}
                  </p>
                  <p className="text-xs text-content-tertiary mt-3 leading-relaxed">
                    IFC 2x3, 4.0, 4.1, 4.3 &middot; Revit 2015–2026 &middot; DWG &middot; DGN &middot; DXF &middot; RFA
                  </p>
                  <div className="mt-4 flex items-center justify-start">
                    <div className="inline-flex flex-wrap items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                      <ShieldCheck size={14} className="text-emerald-500 dark:text-emerald-400 shrink-0" />
                      <span className="text-xs text-emerald-700 dark:text-emerald-300/90 font-medium">
                        {t('common.local_processing', { defaultValue: '100% Local Processing \u00B7 Your files never leave your computer' })}
                      </span>
                      <span className="text-[10px] text-emerald-500/40">|</span>
                      <a
                        href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] text-emerald-600/80 dark:text-emerald-400/70 hover:text-emerald-700 dark:hover:text-emerald-300 hover:underline whitespace-nowrap"
                      >
                        {t('common.powered_by_cad2data', { defaultValue: 'Powered by DDC cad2data' })}
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Feature cards */}
            <div className="mb-8">
              <h2 className="text-xs font-bold text-content-tertiary uppercase tracking-widest mb-3">
                {t('explorer.what_you_get', { defaultValue: 'What you get' })}
              </h2>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {FEATURE_CARDS.map((f, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl p-4 bg-white dark:bg-gray-800/40 border border-border-light/60 hover:border-border-light hover:shadow-sm transition-all">
                    <div className={`w-8 h-8 rounded-lg ${f.color} border flex items-center justify-center shrink-0`}><f.icon size={15} className={f.ic} /></div>
                    <div className="min-w-0">
                      <h3 className="text-xs font-semibold text-content-primary leading-tight">{f.title}</h3>
                      <p className="text-[11px] text-content-tertiary leading-snug mt-1">{f.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>


            {/* Privacy + converter bar moved to top fixed header */}
          </div>{/* end max-w-7xl */}
          </div>{/* end absolute scroll wrapper */}
        </div>{/* end scroll area */}
      {/* ── Bottom Filmstrip: Recent Sessions (fixed, inside outer flex-col) ── */}
      {recentSessions.length > 0 && (
        <div className="shrink-0 border-t border-border-light bg-surface-primary">
          <div className="flex items-center px-4 py-1.5">
            <Clock size={14} className="text-content-tertiary mr-2 shrink-0" />
            <span className="text-xs font-semibold text-content-primary">
              {t('explorer.recent_models', { defaultValue: 'Recent Models' })}
            </span>
            <span className="text-[11px] text-content-quaternary ml-1.5">({allSessions.length})</span>
          </div>
          <div className="flex items-center gap-2.5 px-4 pb-2.5 overflow-x-auto">
            {recentSessions.map((s) => {
              const fmt = (s.file_format || '').toUpperCase();
              const timeAgo = s.created_at ? (() => {
                const diff = Date.now() - new Date(s.created_at).getTime();
                const mins = Math.floor(diff / 60000);
                if (mins < 60) return `${mins}m ago`;
                const hrs = Math.floor(mins / 60);
                if (hrs < 24) return `${hrs}h ago`;
                return `${Math.floor(hrs / 24)}d ago`;
              })() : '';

              return (
                <button
                  key={s.session_id}
                  onClick={() => setSearchParams({ session: s.session_id })}
                  className="group relative shrink-0 w-64 text-start rounded-xl border border-border-light bg-surface-secondary hover:bg-surface-tertiary hover:border-oe-blue/30 hover:shadow-lg transition-all duration-200 overflow-hidden"
                >
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(t('explorer.delete_session_confirm', { defaultValue: 'Delete this analysis?' }))) {
                        deleteSessionMutation.mutate(s.session_id);
                      }
                    }}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}
                    className="absolute top-2 right-2 p-1 rounded text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 transition-all z-10"
                  >
                    <X size={12} />
                  </span>
                  {/* Format accent stripe */}
                  <div className={`h-1 w-full ${
                    fmt === 'RVT' ? 'bg-blue-500' :
                    fmt === 'IFC' ? 'bg-green-500' :
                    fmt === 'DWG' ? 'bg-orange-500' :
                    fmt === 'DGN' ? 'bg-purple-500' :
                    fmt === 'DXF' ? 'bg-amber-500' :
                    'bg-gray-400'
                  }`} />
                  <div className="px-3.5 py-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-[9px] font-black tracking-tighter leading-none ${
                        fmt === 'RVT' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' :
                        fmt === 'IFC' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' :
                        fmt === 'DWG' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' :
                        fmt === 'DGN' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300' :
                        'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                      }`}>{fmt || '?'}</div>
                      <span className="text-xs font-semibold text-content-primary truncate">{s.display_name}</span>
                    </div>
                    <div className="flex items-center gap-2.5 text-[11px] text-content-tertiary">
                      <span className="font-medium tabular-nums">{s.element_count.toLocaleString()} {t('explorer.elements_short', { defaultValue: 'elements' })}</span>
                      {s.is_permanent && <span className="text-emerald-500 font-medium">saved</span>}
                      {timeAgo && <span className="ml-auto text-content-quaternary">{timeAgo}</span>}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
    );
  }

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-6 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
      {/* ── Header ── */}
      <div className="relative z-20 px-3 py-2.5 flex items-center justify-between border-b border-border-light bg-surface-primary">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-oe-blue/10 to-blue-50 dark:to-blue-950/20 border border-oe-blue/15 flex items-center justify-center">
              <Database size={18} className="text-oe-blue" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-content-primary">
                {describe ? describe.filename : t('explorer.title', { defaultValue: 'CAD-BIM Explorer' })}
              </h1>
              {describe?.format && (
                <p className="text-[10px] text-content-tertiary truncate max-w-[160px]">{describe.format.toUpperCase()} {t('explorer.data_session', { defaultValue: 'Data Session' })}</p>
              )}
            </div>
          </div>
          {describe && (
            <div className="flex items-center gap-2 ms-2">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-secondary border border-border-light">
                <Hash size={12} className="text-content-quaternary" />
                <span className="text-[10px] font-medium text-content-tertiary">{t('explorer.elements', { defaultValue: 'Elements' })}</span>
                <span className="text-[10px] font-bold text-content-primary tabular-nums">{describe.total_elements.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-secondary border border-border-light">
                <Columns3 size={12} className="text-content-quaternary" />
                <span className="text-[10px] font-medium text-content-tertiary">{t('explorer.columns', { defaultValue: 'Parameter columns' })}</span>
                <span className="text-[10px] font-bold text-content-primary tabular-nums">{describe.total_columns}</span>
              </div>
              {describe.format && (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-secondary border border-border-light">
                  <Database size={12} className="text-content-quaternary" />
                  <span className="text-[10px] font-medium text-content-tertiary">{t('explorer.format', { defaultValue: 'Format' })}</span>
                  <span className="text-[10px] font-bold text-content-primary">{describe.format.toUpperCase()}</span>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSaveView}
            data-testid="explorer-save-view-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary"
            title={t('explorer.save_view', { defaultValue: 'Save view' })}
          >
            <Bookmark size={13} />
            <span className="hidden sm:inline">{t('explorer.save_view', { defaultValue: 'Save view' })}</span>
          </button>
          <button
            onClick={() => setShowViewsDrawer(true)}
            data-testid="explorer-views-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary"
            title={t('explorer.views', { defaultValue: 'Views' })}
          >
            <Layers size={13} />
            <span className="hidden sm:inline">{t('explorer.views', { defaultValue: 'Views' })}</span>
            {savedViewsCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full text-2xs tabular-nums bg-oe-blue/10 text-oe-blue">
                {savedViewsCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setShowSaveDialog(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary"
            title={t('explorer.save_filters_hint', {
              defaultValue: 'Bookmark current filters, slicers, and chart settings so you can reopen this view later from the Views drawer.',
            })}
          >
            <Save size={13} />
            {t('explorer.save_filters', { defaultValue: 'Save Filters' })}
          </button>
          <button
            onClick={() => { setSearchParams({}); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary"
          >
            <Upload size={13} />
            <span className="hidden sm:inline">{t('explorer.new_file', { defaultValue: 'New File' })}</span>
          </button>
        </div>
      </div>

      {/* ── Content area ── */}
      <div className="flex-1 flex flex-col min-h-0">
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
          </div>
        ) : error ? (
          /* Session expired or invalid — show upload zone to re-upload */
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <Card className="p-4 border-amber-200 bg-amber-50/50 dark:bg-amber-900/10 dark:border-amber-800">
              <div className="flex items-center gap-3">
                <AlertCircle size={18} className="text-amber-600 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-content-primary">{t('explorer.session_expired_title', { defaultValue: 'Session expired or not found' })}</p>
                  <p className="text-xs text-content-tertiary">{t('explorer.session_expired_desc', { defaultValue: 'CAD sessions are valid for 24 hours. Upload your file again to continue.' })}</p>
                </div>
              </div>
            </Card>
            <UploadConvertZone onSessionReady={handleSessionReady} />
          </div>
        ) : describe ? (
          <>
            {/* Tab selector */}
            <div className="flex items-center gap-1 px-3 border-b border-border-light bg-surface-primary">
              {TABS.map(({ id, icon: Icon, label, description }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                    activeTab === id
                      ? 'border-oe-blue text-oe-blue'
                      : 'border-transparent text-content-tertiary hover:text-content-primary'
                  }`}
                  title={t(`explorer.tab_${id}_desc`, { defaultValue: description })}
                >
                  <Icon size={14} />
                  {t(`explorer.tab_${id}`, { defaultValue: label })}
                  {id === 'table' && describe && (
                    <span className={`ml-1 px-1.5 py-0.5 rounded-full text-2xs tabular-nums ${
                      activeTab === id ? 'bg-oe-blue/10' : 'bg-surface-secondary'
                    }`}>
                      {describe.total_elements.toLocaleString()}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Shared slicer banner — cross-filter chips are visible to
                 Data / Pivot / Charts tabs. Hidden on Describe (stats). */}
            {activeTab !== 'describe' && <SlicerBanner />}

            {/* Tab content — scrollable */}
            <div className="flex-1 overflow-y-auto p-4">
              {activeTab === 'table' && <DataTableTab sessionId={sessionId} describe={describe} />}
              {activeTab === 'pivot' && <PivotTab sessionId={sessionId} describe={describe} />}
              {activeTab === 'charts' && <ChartsTab sessionId={sessionId} describe={describe} />}
              {activeTab === 'describe' && <DescribeTab sessionId={sessionId} describe={describe} />}
            </div>
          </>
        ) : null}
      </div>

      <ViewsDrawer open={showViewsDrawer} onClose={() => setShowViewsDrawer(false)} />

      {/* Save dialog */}
      {showSaveDialog && describe && (
        <SaveDialog
          sessionId={sessionId}
          filename={describe.filename}
          onClose={() => setShowSaveDialog(false)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['cad-saved-sessions'] })}
        />
      )}

      {/* Save to Project (BIM) dialog */}
      {showSaveToProjectDialog && describe && (
        <SaveToProjectDialog
          sessionId={sessionId}
          filename={describe.filename}
          onClose={() => setShowSaveToProjectDialog(false)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['cad-saved-sessions'] })}
        />
      )}
    </div>
  );
}

export default CadDataExplorerPage;
