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
  Table2, BarChart3, PieChart, FileSpreadsheet, Database, Filter,
  ArrowUpDown, ChevronDown, ChevronRight, ChevronLeft, Layers, X, Save,
  Download as DownloadIcon, Columns3, Search as SearchIcon,
  Upload, FileUp, Loader2, CheckCircle2, Settings, AlertCircle, FolderOpen,
  TrendingUp, Hash, Clock,
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

/* ── Data Table Tab ────────────────────────────────────────────────────── */

function DataTableTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
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

  // Client-side global search on visible rows
  const displayRows = useMemo(() => {
    if (!data?.rows) return [];
    if (!globalSearch.trim()) return data.rows;
    const q = globalSearch.toLowerCase();
    return data.rows.filter((row) =>
      Object.values(row).some((v) => v != null && String(v).toLowerCase().includes(q))
    );
  }, [data?.rows, globalSearch]);

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

  // Default: prefer 'category', then 'type name', then first available
  const [groupBy, setGroupBy] = useState<string[]>(() => {
    const preferred = ['category', 'type name', 'family', 'level'];
    for (const p of preferred) {
      const found = stringCols.find((c) => c.name.toLowerCase() === p);
      if (found) return [found.name];
    }
    return stringCols.length > 0 ? [stringCols[0]!.name] : [];
  });
  // Allow multiple aggregate columns — auto-select exact matches first
  const [aggCols, setAggCols] = useState<string[]>(() => {
    const defaults: string[] = [];
    for (const name of ['volume', 'area', 'length', 'count']) {
      const exact = numericCols.find((c) => c.name.toLowerCase() === name);
      if (exact) defaults.push(exact.name);
    }
    return defaults.length > 0 ? defaults : topNumericCols.slice(0, 3).map((c) => c.name);
  });
  const [aggFn, setAggFn] = useState('sum');
  const [result, setResult] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDesc, setSortDesc] = useState(true);
  const [showCreateBOQ, setShowCreateBOQ] = useState(false);

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
  useEffect(() => { runPivot(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleGroupBy = useCallback((col: string) => {
    setGroupBy((prev) => prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]);
  }, []);

  const toggleAggCol = useCallback((col: string) => {
    setAggCols((prev) => prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]);
  }, []);

  const toggleExpand = useCallback((key: string) => {
    setExpanded((prev) => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; });
  }, []);

  // Sort results
  const sortedGroups = useMemo(() => {
    if (!result) return [];
    const groups = [...result.groups];
    if (sortCol) {
      groups.sort((a, b) => {
        const va = a.results[sortCol] ?? 0;
        const vb = b.results[sortCol] ?? 0;
        return sortDesc ? vb - va : va - vb;
      });
    }
    return groups;
  }, [result, sortCol, sortDesc]);

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

/* ── Charts Tab ────────────────────────────────────────────────────────── */

function ChartsTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  // For charts: text columns with reasonable cardinality (< 100 unique for good visualization)
  const stringCols = describe.columns
    .filter((c) => c.dtype === 'string' && c.non_null > 0 && c.unique < 100)
    .sort((a, b) => b.non_null - a.non_null);
  // Only useful numeric for values — same keyword priority as Pivot
  const QTY_KEYS = ['volume', 'area', 'length', 'count', 'width', 'height', 'depth', 'weight', 'mass', 'perimeter'];
  const numericCols = useMemo(() => describe.columns
    .filter((c) => c.dtype === 'number' && c.non_null > 0)
    .sort((a, b) => {
      const aK = QTY_KEYS.some((k) => a.name.toLowerCase() === k) ? 10000 : QTY_KEYS.some((k) => a.name.toLowerCase().includes(k)) ? 5000 : 0;
      const bK = QTY_KEYS.some((k) => b.name.toLowerCase() === k) ? 10000 : QTY_KEYS.some((k) => b.name.toLowerCase().includes(k)) ? 5000 : 0;
      return (bK + b.non_null) - (aK + a.non_null);
    })
    .slice(0, 20), [describe]);

  const [chartGroupBy, setChartGroupBy] = useState(() => {
    const cat = stringCols.find((c) => c.name.toLowerCase() === 'category');
    return cat?.name || stringCols[0]?.name || '';
  });
  const [chartValue, setChartValue] = useState(
    numericCols.find((c) => c.name.toLowerCase() === 'volume')?.name || numericCols[0]?.name || '',
  );
  const [chartType, setChartType] = useState<'bar' | 'pie'>('bar');
  const [chartData, setChartData] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const loadChart = useCallback(async () => {
    if (!chartGroupBy || !chartValue) return;
    setLoading(true);
    try {
      const data = await aggregate(sessionId, [chartGroupBy], { [chartValue]: 'sum' });
      setChartData(data);
    } catch { /* */ } finally { setLoading(false); }
  }, [sessionId, chartGroupBy, chartValue]);

  useEffect(() => { loadChart(); }, [loadChart]);

  const sortedGroups = useMemo(() => {
    if (!chartData) return [];
    return [...chartData.groups]
      .sort((a, b) => (b.results[chartValue] ?? 0) - (a.results[chartValue] ?? 0))
      .slice(0, 20);
  }, [chartData, chartValue]);

  const maxVal = sortedGroups.length > 0 ? Math.max(...sortedGroups.map((g) => g.results[chartValue] ?? 0)) : 1;
  const totalVal = sortedGroups.reduce((s, g) => s + (g.results[chartValue] ?? 0), 0);

  const BAR_COLORS = ['#3B82F6', '#22C55E', '#F97316', '#A855F7', '#EF4444', '#06B6D4', '#EC4899', '#84CC16', '#F59E0B', '#6366F1'];

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.group_by', { defaultValue: 'Group By' })}</label>
            <select value={chartGroupBy} onChange={(e) => setChartGroupBy(e.target.value)} className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs">
              {stringCols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.value', { defaultValue: 'Value' })}</label>
            <select value={chartValue} onChange={(e) => setChartValue(e.target.value)} className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs">
              {numericCols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase block mb-1">{t('explorer.chart_type', { defaultValue: 'Type' })}</label>
            <div className="flex gap-1">
              <button onClick={() => setChartType('bar')} className={`px-2 py-1 rounded text-2xs font-medium border ${chartType === 'bar' ? 'bg-oe-blue text-white border-oe-blue' : 'border-border text-content-tertiary'}`}>
                <BarChart3 size={12} className="inline mr-1" />{t('explorer.bar', { defaultValue: 'Bar' })}
              </button>
              <button onClick={() => setChartType('pie')} className={`px-2 py-1 rounded text-2xs font-medium border ${chartType === 'pie' ? 'bg-oe-blue text-white border-oe-blue' : 'border-border text-content-tertiary'}`}>
                <PieChart size={12} className="inline mr-1" />{t('explorer.pie', { defaultValue: 'Pie' })}
              </button>
            </div>
          </div>
        </div>
      </Card>

      {loading ? (
        <div className="flex items-center justify-center py-12"><div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" /></div>
      ) : chartData && sortedGroups.length > 0 ? (
        <Card className="p-4">
          {chartType === 'bar' ? (
            <div className="space-y-2">
              {sortedGroups.map((g, i) => {
                const val = g.results[chartValue] ?? 0;
                const pct = maxVal > 0 ? (val / maxVal) * 100 : 0;
                const color = BAR_COLORS[i % BAR_COLORS.length]!;
                return (
                  <div key={Object.values(g.key).join('-')} className="flex items-center gap-3">
                    <span className="w-32 text-xs text-content-secondary truncate shrink-0 text-right">
                      {Object.values(g.key)[0] || '—'}
                    </span>
                    <div className="flex-1 h-6 bg-surface-secondary rounded-md overflow-hidden relative">
                      <div
                        className="h-full rounded-md transition-all duration-500"
                        style={{ width: `${pct}%`, backgroundColor: color }}
                      />
                      <span className="absolute inset-y-0 right-2 flex items-center text-2xs font-medium text-content-primary tabular-nums">
                        {formatNumber(val)}
                      </span>
                    </div>
                    <span className="text-2xs text-content-quaternary tabular-nums w-12 text-right shrink-0">
                      {g.count.toLocaleString()}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            /* Pie chart — CSS-based */
            <div className="flex items-start gap-6">
              <div className="relative w-48 h-48 shrink-0">
                <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                  {(() => {
                    let offset = 0;
                    return sortedGroups.slice(0, 10).map((g, i) => {
                      const val = g.results[chartValue] ?? 0;
                      const pct = totalVal > 0 ? (val / totalVal) * 100 : 0;
                      const dashArray = `${pct} ${100 - pct}`;
                      const el = (
                        <circle key={Object.values(g.key).join('-')} cx="50" cy="50" r="40" fill="none"
                          stroke={BAR_COLORS[i % BAR_COLORS.length]}
                          strokeWidth="20" strokeDasharray={dashArray}
                          strokeDashoffset={-offset}
                        />
                      );
                      offset += pct;
                      return el;
                    });
                  })()}
                </svg>
              </div>
              <div className="flex-1 space-y-1.5">
                {sortedGroups.slice(0, 10).map((g, i) => {
                  const val = g.results[chartValue] ?? 0;
                  const pct = totalVal > 0 ? ((val / totalVal) * 100).toFixed(1) : '0';
                  return (
                    <div key={Object.values(g.key).join('-')} className="flex items-center gap-2 text-xs">
                      <div className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: BAR_COLORS[i % BAR_COLORS.length] }} />
                      <span className="flex-1 text-content-secondary truncate">{Object.values(g.key)[0] || '—'}</span>
                      <span className="text-content-primary font-medium tabular-nums">{formatNumber(val)}</span>
                      <span className="text-content-quaternary tabular-nums w-10 text-right">{pct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </Card>
      ) : (
        <EmptyState
          icon={<BarChart3 size={28} strokeWidth={1.5} />}
          title={t('explorer.no_chart_data', { defaultValue: 'No chart data' })}
          description={t('explorer.select_columns_for_chart', { defaultValue: 'Select group by and value columns to generate a chart.' })}
        />
      )}
    </div>
  );
}

/* ── Describe Tab ──────────────────────────────────────────────────────── */

function DescribeTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const [selectedCol, setSelectedCol] = useState<string | null>(null);

  const { data: vcData } = useQuery({
    queryKey: ['cad-value-counts', sessionId, selectedCol],
    queryFn: () => valueCounts(sessionId, selectedCol!, 30),
    enabled: !!selectedCol,
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

/* ── Data Explorer Empty State Animation ────────────────────────────── */

function DataExplorerEmptyAnimation() {
  return (
    <div className="mx-auto mb-6 relative" style={{ width: 260, height: 150, opacity: 0.6 }}>
      <style>{`
        /* Bar chart columns grow upward */
        @keyframes explorerBarGrow0 {
          0%, 5% { transform: scaleY(0); opacity: 0; }
          15%, 52% { transform: scaleY(1); opacity: 1; }
          65%, 100% { transform: scaleY(1); opacity: 0.2; }
        }
        @keyframes explorerBarGrow1 {
          0%, 9% { transform: scaleY(0); opacity: 0; }
          20%, 52% { transform: scaleY(1); opacity: 1; }
          65%, 100% { transform: scaleY(1); opacity: 0.2; }
        }
        @keyframes explorerBarGrow2 {
          0%, 13% { transform: scaleY(0); opacity: 0; }
          25%, 52% { transform: scaleY(1); opacity: 1; }
          65%, 100% { transform: scaleY(1); opacity: 0.2; }
        }
        @keyframes explorerBarGrow3 {
          0%, 17% { transform: scaleY(0); opacity: 0; }
          30%, 52% { transform: scaleY(1); opacity: 1; }
          65%, 100% { transform: scaleY(1); opacity: 0.2; }
        }
        @keyframes explorerBarGrow4 {
          0%, 21% { transform: scaleY(0); opacity: 0; }
          35%, 52% { transform: scaleY(1); opacity: 1; }
          65%, 100% { transform: scaleY(1); opacity: 0.2; }
        }
        /* Pie chart segments rotate into view */
        @keyframes explorerPieSegA {
          0%, 6% { opacity: 0; transform: rotate(-90deg) scale(0.5); }
          20%, 52% { opacity: 1; transform: rotate(0deg) scale(1); }
          65%, 100% { opacity: 0.2; transform: rotate(0deg) scale(1); }
        }
        @keyframes explorerPieSegB {
          0%, 12% { opacity: 0; transform: rotate(90deg) scale(0.5); }
          26%, 52% { opacity: 1; transform: rotate(0deg) scale(1); }
          65%, 100% { opacity: 0.2; transform: rotate(0deg) scale(1); }
        }
        @keyframes explorerPieSegC {
          0%, 18% { opacity: 0; transform: rotate(-120deg) scale(0.5); }
          32%, 52% { opacity: 1; transform: rotate(0deg) scale(1); }
          65%, 100% { opacity: 0.2; transform: rotate(0deg) scale(1); }
        }
        /* Data table rows slide in one by one */
        @keyframes explorerRowSlide {
          0%, 30% { transform: translateX(16px); opacity: 0; }
          42%, 55% { transform: translateX(0); opacity: 0.85; }
          68%, 100% { transform: translateX(0); opacity: 0.15; }
        }
        /* Dashboard cards fade and scale in */
        @keyframes explorerCardIn {
          0%, 45% { transform: scale(0.85) translateY(8px); opacity: 0; }
          56%, 65% { transform: scale(1) translateY(0); opacity: 0.9; }
          78%, 100% { transform: scale(1) translateY(0); opacity: 0.15; }
        }
        /* Subtle overall float */
        @keyframes explorerFloat {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-2px); }
        }
        /* Axis line fade */
        @keyframes explorerAxisIn {
          0%, 3% { opacity: 0; transform: scaleX(0); }
          12%, 55% { opacity: 0.5; transform: scaleX(1); }
          68%, 100% { opacity: 0.1; transform: scaleX(1); }
        }
        @keyframes explorerAxisYIn {
          0%, 3% { opacity: 0; transform: scaleY(0); }
          12%, 55% { opacity: 0.5; transform: scaleY(1); }
          68%, 100% { opacity: 0.1; transform: scaleY(1); }
        }
      `}</style>

      <div style={{ animation: 'explorerFloat 7s ease-in-out infinite' }}>
        {/* ── Bar Chart (left section) ── */}
        <div style={{ position: 'absolute', left: 0, top: 10, width: 100, height: 120 }}>
          {/* Y axis */}
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 2, height: 100,
            background: 'linear-gradient(180deg, rgba(99,102,241,0.3), rgba(16,185,129,0.3))',
            borderRadius: 1,
            transformOrigin: 'top center',
            animation: 'explorerAxisYIn 9s ease-out infinite',
          }} />
          {/* X axis */}
          <div style={{
            position: 'absolute', left: 0, top: 100, width: 95, height: 2,
            background: 'linear-gradient(90deg, rgba(99,102,241,0.3), rgba(16,185,129,0.3))',
            borderRadius: 1,
            transformOrigin: 'left center',
            animation: 'explorerAxisIn 9s ease-out infinite',
          }} />
          {/* Bar columns */}
          {[
            { h: 60, color: 'linear-gradient(180deg, var(--oe-blue), #6366f1)', idx: 0 },
            { h: 82, color: 'linear-gradient(180deg, #6366f1, #8b5cf6)', idx: 1 },
            { h: 45, color: 'linear-gradient(180deg, #10b981, #059669)', idx: 2 },
            { h: 72, color: 'linear-gradient(180deg, var(--oe-blue), #3b82f6)', idx: 3 },
            { h: 55, color: 'linear-gradient(180deg, #10b981, #34d399)', idx: 4 },
          ].map((bar, i) => (
            <div key={i} style={{
              position: 'absolute',
              left: 8 + i * 18,
              bottom: 20,
              width: 12,
              height: bar.h,
              borderRadius: '3px 3px 0 0',
              background: bar.color,
              transformOrigin: 'bottom center',
              animation: `explorerBarGrow${bar.idx} 9s ease-out infinite`,
              boxShadow: '0 -2px 6px rgba(99,102,241,0.08)',
            }} />
          ))}
          {/* Bar chart label placeholder */}
          <div style={{
            position: 'absolute', left: 8, top: 106, width: 82, height: 4,
            borderRadius: 2,
            background: 'rgba(99,102,241,0.1)',
            animation: 'explorerAxisIn 9s ease-out infinite',
          }} />
        </div>

        {/* ── Pie Chart (center-top section) ── */}
        <div style={{ position: 'absolute', left: 110, top: 6, width: 52, height: 52 }}>
          {/* Pie segment A — large slice (top-right) */}
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 52, height: 52,
            borderRadius: '50%',
            background: `conic-gradient(
              var(--oe-blue) 0deg 140deg,
              transparent 140deg 360deg
            )`,
            transformOrigin: 'center center',
            animation: 'explorerPieSegA 9s ease-out infinite',
          }} />
          {/* Pie segment B — medium slice */}
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 52, height: 52,
            borderRadius: '50%',
            background: `conic-gradient(
              transparent 0deg 140deg,
              #10b981 140deg 250deg,
              transparent 250deg 360deg
            )`,
            transformOrigin: 'center center',
            animation: 'explorerPieSegB 9s ease-out infinite',
          }} />
          {/* Pie segment C — small slice */}
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 52, height: 52,
            borderRadius: '50%',
            background: `conic-gradient(
              transparent 0deg 250deg,
              #8b5cf6 250deg 330deg,
              transparent 330deg 360deg
            )`,
            transformOrigin: 'center center',
            animation: 'explorerPieSegC 9s ease-out infinite',
          }} />
          {/* Remaining slice (static, appears last) */}
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 52, height: 52,
            borderRadius: '50%',
            background: `conic-gradient(
              transparent 0deg 330deg,
              rgba(99,102,241,0.25) 330deg 360deg
            )`,
            transformOrigin: 'center center',
            animation: 'explorerPieSegC 9s ease-out infinite',
            animationDelay: '0.2s',
          }} />
          {/* Center hole (donut) */}
          <div style={{
            position: 'absolute', left: 14, top: 14, width: 24, height: 24,
            borderRadius: '50%',
            background: 'var(--surface-primary, #ffffff)',
            boxShadow: 'inset 0 0 8px rgba(0,0,0,0.03)',
          }} />
        </div>

        {/* ── Data Table Rows (right section) ── */}
        <div style={{ position: 'absolute', right: 0, top: 8, width: 80, height: 110 }}>
          {/* Table header */}
          <div style={{
            display: 'flex', gap: 2, marginBottom: 4,
            animation: 'explorerRowSlide 9s ease-out infinite',
          }}>
            <div style={{ flex: 2, height: 9, borderRadius: '4px 0 0 0', background: 'linear-gradient(90deg, var(--oe-blue), #6366f1)' }} />
            <div style={{ flex: 1, height: 9, borderRadius: '0 4px 0 0', background: 'linear-gradient(90deg, #6366f1, #8b5cf6)' }} />
          </div>
          {/* Table data rows */}
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} style={{
              display: 'flex', gap: 2, marginBottom: 3,
              animation: 'explorerRowSlide 9s ease-out infinite',
              animationDelay: `${0.1 + i * 0.08}s`,
            }}>
              <div style={{
                flex: 2, height: 7, borderRadius: 2,
                background: i % 2 === 0
                  ? 'rgba(99,102,241,0.12)'
                  : 'rgba(16,185,129,0.12)',
              }} />
              <div style={{
                flex: 1, height: 7, borderRadius: 2,
                background: 'rgba(139,92,246,0.1)',
              }} />
            </div>
          ))}
        </div>

        {/* ── Dashboard Mini Cards (bottom center) ── */}
        <div style={{ position: 'absolute', left: 106, bottom: 2, display: 'flex', gap: 6 }}>
          {[
            { w: 46, bg: 'linear-gradient(135deg, rgba(59,130,246,0.1), rgba(99,102,241,0.05))', border: 'rgba(59,130,246,0.15)' },
            { w: 46, bg: 'linear-gradient(135deg, rgba(16,185,129,0.1), rgba(5,150,105,0.05))', border: 'rgba(16,185,129,0.15)' },
            { w: 46, bg: 'linear-gradient(135deg, rgba(139,92,246,0.1), rgba(99,102,241,0.05))', border: 'rgba(139,92,246,0.15)' },
          ].map((card, i) => (
            <div key={i} style={{
              width: card.w, height: 36, borderRadius: 6,
              background: card.bg,
              border: `1px solid ${card.border}`,
              animation: 'explorerCardIn 9s ease-out infinite',
              animationDelay: `${i * 0.15}s`,
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              justifyContent: 'center', padding: '0 6px', gap: 3,
            }}>
              {/* Mini stat line */}
              <div style={{ width: '60%', height: 4, borderRadius: 2, background: i === 0 ? 'rgba(59,130,246,0.25)' : i === 1 ? 'rgba(16,185,129,0.25)' : 'rgba(139,92,246,0.25)' }} />
              <div style={{ width: '40%', height: 3, borderRadius: 2, background: 'rgba(99,102,241,0.1)' }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ConverterStatus() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['cad-converters-status'],
    queryFn: () => apiGet<{ converters: { id: string; name: string; extensions: string[]; installed: boolean }[] }>('/v1/takeoff/converters/'),
    staleTime: 60000,
  });

  if (!data?.converters) return null;

  const installed = data.converters.filter((c) => c.installed);
  const notInstalled = data.converters.filter((c) => !c.installed);

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-content-primary flex items-center gap-1.5">
          <Settings size={13} className="text-content-tertiary" />
          {t('explorer.converters', { defaultValue: 'CAD Converters' })}
          <span className="text-2xs text-content-quaternary font-normal ml-1">
            — {t('explorer.converters_desc', { defaultValue: 'DDC Community converters for extracting BIM element data' })}
          </span>
        </h3>
        <Badge variant={installed.length === data.converters.length ? 'success' : 'warning'} size="sm">
          {installed.length}/{data.converters.length} {t('explorer.installed', { defaultValue: 'installed' })}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        {data.converters.map((c) => (
          <div
            key={c.id}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-2xs font-medium border transition-colors ${
              c.installed
                ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-900/20 dark:text-green-400 dark:border-green-800'
                : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800 cursor-pointer hover:bg-amber-100'
            }`}
            onClick={!c.installed ? () => window.open('https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto', '_blank') : undefined}
            title={!c.installed ? t('explorer.requires_external', { defaultValue: 'External tool — click for setup instructions' }) : undefined}
          >
            {c.installed ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
            <span className="font-semibold">{c.name}</span>
            <span className="opacity-60">{c.extensions.join(', ')}</span>
            {!c.installed && (
              <span className="ml-1 underline text-2xs">{t('explorer.setup_guide', { defaultValue: 'Setup Guide' })}</span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3 text-2xs text-content-quaternary">
        {notInstalled.length > 0 && (
          <span className="flex items-center gap-1">
            <AlertCircle size={10} />
            {t('explorer.converters_external_hint', { defaultValue: 'CAD converters require DDC cad2data tools installed on your server' })}
          </span>
        )}
        <span className="flex items-center gap-1 ml-auto">
          {t('explorer.powered_by', { defaultValue: 'Powered by' })}{' '}
          <a href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN" target="_blank" rel="noopener noreferrer" className="text-oe-blue hover:underline">
            DDC cad2data Converters
          </a>
        </span>
      </div>
    </Card>
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
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get('session') || '';
  const [activeTab, setActiveTab] = useState<TabId>('table');
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showSaveToProjectDialog, setShowSaveToProjectDialog] = useState(false);

  const { data: describe, isLoading, error } = useQuery({
    queryKey: ['cad-describe', sessionId],
    queryFn: () => describeSession(sessionId),
    enabled: !!sessionId,
  });

  const handleSessionReady = useCallback((newSessionId: string) => {
    setSearchParams({ session: newSessionId });
  }, [setSearchParams]);

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
      console.error('Failed to delete CAD session:', err.message);
    },
  });

  if (!sessionId) {
    const recentSessions = allSessions.slice(0, 12);
    const LANDING_FORMAT_COLORS: Record<string, string> = {
      RVT: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
      IFC: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
      DWG: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
      DGN: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
    };

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
        <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50/50 dark:from-gray-900 dark:via-gray-900 dark:to-blue-950/20 overflow-y-auto">
          <div className="w-full max-w-6xl px-6 py-10">
            {/* Hero title */}
            <div className="text-center mb-10">
              <h1 className="text-2xl font-bold text-content-primary tracking-tight">
                {t('explorer.hero_title', { defaultValue: 'CAD/BIM Data Explorer' })}
              </h1>
              <p className="text-sm text-content-secondary mt-2 max-w-lg mx-auto">
                {t('explorer.hero_subtitle', { defaultValue: 'Analyze building element data in a powerful spreadsheet interface. Filter, pivot, chart, and export quantities from your IFC and Revit models.' })}
              </p>
            </div>

            {/* 3-column layout: Upload | Features | Animation */}
            <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr_0.8fr] gap-8 items-start mb-10">

              {/* LEFT -- Upload card */}
              <div>
                <div className="rounded-2xl bg-surface-primary border border-border-light shadow-lg shadow-black/5 dark:shadow-black/20 p-6">
                  <UploadConvertZone onSessionReady={handleSessionReady} />
                  <p className="text-[10px] text-content-quaternary mt-3 text-center">
                    {t('explorer.upload_hint_formats', { defaultValue: 'Supported formats:' })}{' '}
                    <span className="font-semibold text-content-tertiary">IFC, RVT, DWG, DGN, DXF, RFA</span>
                    {' | '}
                    {t('explorer.upload_hint_size', { defaultValue: 'Max file size: 100 MB' })}
                  </p>
                </div>
              </div>

              {/* CENTER -- Feature explanation cards */}
              <div className="space-y-3">
                <h2 className="text-xs font-bold text-content-secondary uppercase tracking-widest mb-2">
                  {t('explorer.what_you_get', { defaultValue: 'What you get' })}
                </h2>
                {FEATURE_CARDS.map((f, i) => (
                  <div key={i} className={`flex items-start gap-3 rounded-xl p-3.5 bg-surface-primary/60 dark:bg-surface-primary/40 border ${f.border} hover:border-border-light transition-colors`}>
                    <div className={`w-9 h-9 rounded-lg ${f.color} border flex items-center justify-center shrink-0`}><f.icon size={16} className={f.ic} /></div>
                    <div className="min-w-0">
                      <h3 className="text-xs font-semibold text-content-primary leading-tight">{f.title}</h3>
                      <p className="text-[11px] text-content-quaternary leading-snug mt-0.5">{f.desc}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* RIGHT -- CSS animation preview */}
              <div className="flex items-center justify-center">
                <DataExplorerEmptyAnimation />
              </div>
            </div>

            {/* Recent sessions -- card grid */}
            {recentSessions.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-content-primary flex items-center gap-2">
                <Clock size={15} className="text-content-tertiary" />
                {t('explorer.recent_models', { defaultValue: 'Recent Models' })}
                <Badge variant="neutral" size="sm">{allSessions.length}</Badge>
              </h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
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

                // Estimate column count from element_count (heuristic for display)
                const colCount = describe ? describe.total_columns : null;

                return (
                  <button
                    key={s.session_id}
                    className="relative w-full text-left rounded-xl border border-border-light bg-surface-elevated p-4 hover:shadow-lg hover:border-oe-blue/30 hover:-translate-y-0.5 transition-all duration-200 group cursor-pointer"
                    onClick={() => setSearchParams({ session: s.session_id })}
                  >
                    {/* Delete button */}
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(t('explorer.delete_session_confirm', { defaultValue: 'Delete this analysis? This cannot be undone.' }))) {
                          deleteSessionMutation.mutate(s.session_id);
                        }
                      }}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}
                      className="absolute top-2.5 right-2.5 h-6 w-6 flex items-center justify-center rounded-md text-content-quaternary hover:text-semantic-error hover:bg-semantic-error-bg opacity-0 group-hover:opacity-100 transition-all cursor-pointer z-10"
                      title={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <X size={14} />
                    </span>

                    {/* Header: name + format badge */}
                    <div className="flex items-start gap-2.5 mb-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-surface-secondary shrink-0">
                        <Database size={16} className="text-content-tertiary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-semibold text-content-primary truncate">{s.display_name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`px-1.5 py-0.5 rounded text-2xs font-bold shrink-0 ${LANDING_FORMAT_COLORS[fmt] || 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'}`}>
                            {fmt || '?'}
                          </span>
                          {s.is_permanent && (
                            <span className="inline-flex items-center gap-0.5 text-2xs text-green-600 dark:text-green-400 font-medium">
                              <Save size={10} />
                              {t('explorer.saved_label', { defaultValue: 'Saved' })}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Stats row */}
                    <div className="flex items-center gap-3 text-2xs text-content-tertiary">
                      <span className="inline-flex items-center gap-1 tabular-nums">
                        <Hash size={10} className="text-content-quaternary" />
                        {s.element_count.toLocaleString()} {t('explorer.elements_short', { defaultValue: 'elements' })}
                      </span>
                      {colCount != null && (
                        <span className="inline-flex items-center gap-1 tabular-nums">
                          <Columns3 size={10} className="text-content-quaternary" />
                          {colCount} {t('explorer.cols_short', { defaultValue: 'cols' })}
                        </span>
                      )}
                      <span className="ml-auto inline-flex items-center gap-1 tabular-nums text-content-quaternary">
                        <Clock size={10} />
                        {timeAgo}
                      </span>
                    </div>

                    {/* Hover arrow indicator */}
                    <div className="absolute bottom-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
                      <ChevronRight size={16} className="text-oe-blue" />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

            {/* Converter status */}
            <ConverterStatus />
          </div>
        </div>
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
                <span className="text-[10px] font-medium text-content-tertiary">{t('explorer.columns', { defaultValue: 'Columns' })}</span>
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
            onClick={() => setShowSaveToProjectDialog(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border bg-oe-blue/10 text-oe-blue border-oe-blue/30 hover:bg-oe-blue/20"
          >
            <FolderOpen size={13} />
            {t('explorer.save_to_project_btn', { defaultValue: 'Save to Project' })}
          </button>
          <button
            onClick={() => setShowSaveDialog(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary"
          >
            <Save size={13} />
            {t('explorer.save_analysis', { defaultValue: 'Save' })}
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
