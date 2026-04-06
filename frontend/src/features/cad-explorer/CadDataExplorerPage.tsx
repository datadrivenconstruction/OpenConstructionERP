/**
 * CAD Data Explorer — Pandas-like DataFrame interface for BIM element data.
 *
 * 4 tabs: Data Table | Pivot | Charts | Describe
 * Reads session_id from URL query parameter.
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Table2,
  BarChart3,
  PieChart,
  FileSpreadsheet,
  Database,
  Filter,
  ArrowUpDown,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Layers,
  Hash,
  Box,
  Ruler,
  X,
  Save,
} from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
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
  type SavedSession,
} from './api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

type TabId = 'table' | 'pivot' | 'charts' | 'describe';

const TABS: { id: TabId; icon: React.ElementType; label: string }[] = [
  { id: 'table', icon: Table2, label: 'Data Table' },
  { id: 'pivot', icon: Layers, label: 'Pivot' },
  { id: 'charts', icon: BarChart3, label: 'Charts' },
  { id: 'describe', icon: FileSpreadsheet, label: 'Describe' },
];

const AGG_FUNCTIONS = ['sum', 'avg', 'min', 'max', 'count'];


/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (Math.abs(n) >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/* ── Stats Cards ───────────────────────────────────────────────────────── */

function StatsCards({ data }: { data: DescribeResponse }) {
  const { t } = useTranslation();
  const numericCols = data.columns.filter((c) => c.dtype === 'number');
  const stringCols = data.columns.filter((c) => c.dtype === 'string');
  const totalVolume = numericCols.find((c) => c.name.toLowerCase().includes('volume'))?.sum;
  const totalArea = numericCols.find((c) => c.name.toLowerCase().includes('area'))?.sum;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <Card className="p-3">
        <p className="text-2xs text-content-tertiary uppercase tracking-wide">{t('explorer.elements', { defaultValue: 'Elements' })}</p>
        <p className="text-lg font-bold text-content-primary tabular-nums">{data.total_elements.toLocaleString()}</p>
      </Card>
      <Card className="p-3">
        <p className="text-2xs text-content-tertiary uppercase tracking-wide">{t('explorer.columns', { defaultValue: 'Columns' })}</p>
        <p className="text-lg font-bold text-content-primary tabular-nums">{data.total_columns}</p>
        <p className="text-2xs text-content-quaternary">{stringCols.length} text · {numericCols.length} numeric</p>
      </Card>
      {totalVolume != null && (
        <Card className="p-3">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">{t('explorer.total_volume', { defaultValue: 'Total Volume' })}</p>
          <p className="text-lg font-bold text-oe-blue tabular-nums">{formatNumber(totalVolume)} m³</p>
        </Card>
      )}
      {totalArea != null && (
        <Card className="p-3">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">{t('explorer.total_area', { defaultValue: 'Total Area' })}</p>
          <p className="text-lg font-bold text-oe-blue tabular-nums">{formatNumber(totalArea)} m²</p>
        </Card>
      )}
    </div>
  );
}

/* ── Data Table Tab ────────────────────────────────────────────────────── */

function DataTableTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(0);
  const [pageSize] = useState(50);
  const [sortBy, setSortBy] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [filterCol, setFilterCol] = useState('');
  const [filterVal, setFilterVal] = useState('');
  const [activeFilter, setActiveFilter] = useState<{ col: string; val: string } | null>(null);

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
  const visibleCols = useMemo(() => {
    if (!data?.columns) return [];
    // Show max 12 columns, prioritize grouping + quantity
    const priority = ['category', 'type name', 'family', 'level', 'material', 'volume', 'area', 'length', 'count'];
    const sorted = [...data.columns].sort((a, b) => {
      const ai = priority.indexOf(a.toLowerCase());
      const bi = priority.indexOf(b.toLowerCase());
      if (ai >= 0 && bi >= 0) return ai - bi;
      if (ai >= 0) return -1;
      if (bi >= 0) return 1;
      return 0;
    });
    return sorted.slice(0, 12);
  }, [data?.columns]);

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
      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={14} className="text-content-tertiary" />
        <select
          value={filterCol}
          onChange={(e) => setFilterCol(e.target.value)}
          className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs"
        >
          <option value="">{t('explorer.filter_column', { defaultValue: 'Column...' })}</option>
          {describe.columns.filter((c) => c.dtype === 'string').map((c) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
        </select>
        <span className="text-2xs text-content-tertiary">=</span>
        <input
          value={filterVal}
          onChange={(e) => setFilterVal(e.target.value)}
          placeholder={t('explorer.filter_value', { defaultValue: 'Value...' })}
          className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs w-32"
          onKeyDown={(e) => e.key === 'Enter' && applyFilter()}
        />
        <Button variant="ghost" size="sm" onClick={applyFilter} disabled={!filterCol || !filterVal}>
          {t('common.apply', { defaultValue: 'Apply' })}
        </Button>
        {activeFilter && (
          <button onClick={() => setActiveFilter(null)} className="text-xs text-oe-blue hover:underline flex items-center gap-1">
            <X size={12} /> {t('explorer.clear_filter', { defaultValue: 'Clear' })}
          </button>
        )}
        {activeFilter && (
          <Badge variant="blue" size="sm">{activeFilter.col} = "{activeFilter.val}"</Badge>
        )}
        <span className="ml-auto text-2xs text-content-tertiary tabular-nums">
          {data?.total.toLocaleString() ?? '...'} {t('explorer.rows', { defaultValue: 'rows' })}
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
              ) : (data?.rows ?? []).map((row, idx) => (
                <tr key={idx} className="border-b border-border-light hover:bg-surface-secondary/30">
                  <td className="px-2 py-1.5 text-center text-content-quaternary tabular-nums">
                    {page * pageSize + idx + 1}
                  </td>
                  {visibleCols.map((col) => {
                    const val = row[col];
                    const isNum = typeof val === 'number';
                    return (
                      <td key={col} className={`px-2 py-1.5 ${isNum ? 'text-right tabular-nums' : ''} text-content-primary truncate max-w-[180px]`}>
                        {val == null ? <span className="text-content-quaternary">—</span> : isNum ? formatNumber(val) : String(val)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

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
  const stringCols = describe.columns.filter((c) => c.dtype === 'string');
  const numericCols = describe.columns.filter((c) => c.dtype === 'number');

  const [groupBy, setGroupBy] = useState<string[]>(
    stringCols.length > 0 ? [stringCols[0]!.name] : [],
  );
  const [aggCol, setAggCol] = useState(numericCols[0]?.name || '');
  const [aggFn, setAggFn] = useState('sum');
  const [result, setResult] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const handlePivot = useCallback(async () => {
    if (groupBy.length === 0 || !aggCol) return;
    setLoading(true);
    try {
      const data = await aggregate(sessionId, groupBy, { [aggCol]: aggFn, count: 'sum' });
      setResult(data);
      setExpanded(new Set());
    } catch {
      // error handled by API layer
    } finally {
      setLoading(false);
    }
  }, [sessionId, groupBy, aggCol, aggFn]);

  const toggleGroup = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Group results into a tree by first group-by column
  const tree = useMemo(() => {
    if (!result || groupBy.length < 2) return null;
    const map = new Map<string, AggregateGroup[]>();
    for (const g of result.groups) {
      const parentKey = g.key[groupBy[0]!] || '(empty)';
      if (!map.has(parentKey)) map.set(parentKey, []);
      map.get(parentKey)!.push(g);
    }
    return map;
  }, [result, groupBy]);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card className="p-4">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase tracking-wide block mb-1">
              {t('explorer.group_by', { defaultValue: 'Group By' })}
            </label>
            <div className="flex gap-1.5">
              {stringCols.map((col) => (
                <button
                  key={col.name}
                  onClick={() => setGroupBy((prev) =>
                    prev.includes(col.name) ? prev.filter((c) => c !== col.name) : [...prev, col.name]
                  )}
                  className={`px-2 py-1 rounded-md text-2xs font-medium transition-colors border ${
                    groupBy.includes(col.name)
                      ? 'bg-oe-blue text-white border-oe-blue'
                      : 'border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary'
                  }`}
                >
                  {col.name}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-2xs font-medium text-content-tertiary uppercase tracking-wide block mb-1">
              {t('explorer.aggregate', { defaultValue: 'Aggregate' })}
            </label>
            <div className="flex gap-1.5">
              <select value={aggCol} onChange={(e) => setAggCol(e.target.value)} className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs">
                {numericCols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
              </select>
              <select value={aggFn} onChange={(e) => setAggFn(e.target.value)} className="h-7 rounded-md border border-border bg-surface-primary px-2 text-xs">
                {AGG_FUNCTIONS.map((fn) => <option key={fn} value={fn}>{fn.toUpperCase()}</option>)}
              </select>
            </div>
          </div>
          <Button variant="primary" size="sm" onClick={handlePivot} disabled={groupBy.length === 0 || loading} loading={loading}>
            {t('explorer.apply_pivot', { defaultValue: 'Apply Pivot' })}
          </Button>
        </div>
      </Card>

      {/* Results */}
      {result && (
        <Card padding="none" className="overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-surface-secondary/50">
                {groupBy.map((col) => (
                  <th key={col} className="px-3 py-2 text-left text-2xs font-semibold text-content-tertiary uppercase">{col}</th>
                ))}
                <th className="px-3 py-2 text-right text-2xs font-semibold text-content-tertiary uppercase">{t('explorer.count', { defaultValue: 'Count' })}</th>
                <th className="px-3 py-2 text-right text-2xs font-semibold text-content-tertiary uppercase">{aggFn}({aggCol})</th>
              </tr>
            </thead>
            <tbody>
              {tree ? (
                // Tree view for multi-level grouping
                Array.from(tree.entries()).map(([parentKey, children]) => {
                  const isOpen = expanded.has(parentKey);
                  const parentTotal = children.reduce((s, g) => s + (g.results[aggCol] ?? 0), 0);
                  const parentCount = children.reduce((s, g) => s + g.count, 0);
                  return (
                    <React.Fragment key={parentKey}>
                      <tr
                        className="border-b border-border-light bg-surface-secondary/20 cursor-pointer hover:bg-surface-secondary/40"
                        onClick={() => toggleGroup(parentKey)}
                      >
                        <td className="px-3 py-2 font-medium text-content-primary">
                          <span className="inline-flex items-center gap-1">
                            {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            {parentKey}
                            <Badge variant="neutral" size="sm">{children.length}</Badge>
                          </span>
                        </td>
                        {groupBy.slice(1).map((col) => (
                          <td key={col} className="px-3 py-2 text-content-tertiary">—</td>
                        ))}
                        <td className="px-3 py-2 text-right font-semibold text-content-primary tabular-nums">{parentCount.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right font-semibold text-oe-blue tabular-nums">{formatNumber(parentTotal)}</td>
                      </tr>
                      {isOpen && children.map((g, i) => (
                        <tr key={i} className="border-b border-border-light">
                          <td className="px-3 py-1.5 pl-8 text-content-tertiary">{g.key[groupBy[0]!]}</td>
                          {groupBy.slice(1).map((col) => (
                            <td key={col} className="px-3 py-1.5 text-content-secondary">{g.key[col] || '—'}</td>
                          ))}
                          <td className="px-3 py-1.5 text-right tabular-nums text-content-secondary">{g.count.toLocaleString()}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-content-primary">{formatNumber(g.results[aggCol])}</td>
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })
              ) : (
                // Flat view
                result.groups.map((g, i) => (
                  <tr key={i} className="border-b border-border-light hover:bg-surface-secondary/30">
                    {groupBy.map((col) => (
                      <td key={col} className="px-3 py-2 text-content-primary">{g.key[col] || '—'}</td>
                    ))}
                    <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{g.count.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">{formatNumber(g.results[aggCol])}</td>
                  </tr>
                ))
              )}
              {/* Totals row */}
              <tr className="bg-surface-secondary/60 font-semibold">
                <td className="px-3 py-2 text-content-primary" colSpan={groupBy.length}>
                  {t('explorer.total', { defaultValue: 'Total' })}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-content-primary">{result.total_count.toLocaleString()}</td>
                <td className="px-3 py-2 text-right tabular-nums text-oe-blue">{formatNumber(result.totals[aggCol])}</td>
              </tr>
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

/* ── Charts Tab ────────────────────────────────────────────────────────── */

function ChartsTab({ sessionId, describe }: { sessionId: string; describe: DescribeResponse }) {
  const { t } = useTranslation();
  const stringCols = describe.columns.filter((c) => c.dtype === 'string');
  const numericCols = describe.columns.filter((c) => c.dtype === 'number');

  const [chartGroupBy, setChartGroupBy] = useState(stringCols[0]?.name || '');
  const [chartValue, setChartValue] = useState(
    numericCols.find((c) => c.name.toLowerCase().includes('volume'))?.name || numericCols[0]?.name || '',
  );
  const [chartType, setChartType] = useState<'bar' | 'pie'>('bar');
  const [chartData, setChartData] = useState<AggregateResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const loadChart = useCallback(async () => {
    if (!chartGroupBy || !chartValue) return;
    setLoading(true);
    try {
      const data = await aggregate(sessionId, [chartGroupBy], { [chartValue]: 'sum', count: 'sum' });
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
                  <div key={i} className="flex items-center gap-3">
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
                        <circle key={i} cx="50" cy="50" r="40" fill="none"
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
                    <div key={i} className="flex items-center gap-2 text-xs">
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
          icon={<BarChart3 size={32} />}
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

  return (
    <div className="space-y-4">
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
            {vcData.values.map((v, i) => (
              <div key={i} className="flex items-center gap-3">
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

import React, { useRef } from 'react';
import { Upload, FileUp, Loader2, CheckCircle2, Sparkles, Settings, AlertCircle } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';

function ConverterStatus() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ['cad-converters-status'],
    queryFn: () => apiGet<{ converters: { id: string; name: string; extensions: string[]; installed: boolean }[] }>('/v1/takeoff/converters'),
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
            onClick={!c.installed ? () => navigate('/modules') : undefined}
            title={!c.installed ? t('explorer.click_to_install', { defaultValue: 'Click to install this converter' }) : undefined}
          >
            {c.installed ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
            <span className="font-semibold">{c.name}</span>
            <span className="opacity-60">{c.extensions.join(', ')}</span>
            {!c.installed && (
              <span className="ml-1 underline text-2xs">{t('explorer.install', { defaultValue: 'Install' })}</span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3 text-2xs text-content-quaternary">
        {notInstalled.length > 0 && (
          <span className="flex items-center gap-1">
            <AlertCircle size={10} />
            {t('explorer.install_converters_hint', { defaultValue: 'Missing converters can be installed in' })}{' '}
            <button onClick={() => navigate('/modules')} className="text-oe-blue hover:underline ml-0.5">
              {t('explorer.modules_page', { defaultValue: 'Modules' })}
            </button>
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

      const res = await fetch('/api/v1/takeoff/cad-columns', {
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
    <div className="space-y-6">
      {/* Hero section */}
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-oe-blue-subtle">
          <Database size={28} className="text-oe-blue" />
        </div>
        <h2 className="text-xl font-bold text-content-primary">
          {t('explorer.hero_title', { defaultValue: 'CAD-BIM Data Explorer' })}
        </h2>
        <p className="mt-2 text-sm text-content-secondary max-w-lg mx-auto">
          {t('explorer.hero_desc', {
            defaultValue: 'Upload a 3D model or drawing to extract all elements into a searchable, filterable, pivotable data table — like a spreadsheet for your BIM data.',
          })}
        </p>
      </div>

      {/* Upload zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
        onClick={() => !uploading && inputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
          uploading ? 'pointer-events-none border-oe-blue/40 bg-oe-blue-subtle/20' :
          dragOver ? 'border-oe-blue bg-oe-blue-subtle/20 scale-[1.01]' :
          'border-border-light hover:border-oe-blue/40 hover:bg-surface-secondary/30'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={CAD_ACCEPT}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }}
          className="hidden"
        />

        {uploading ? (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-3">
              <Loader2 size={24} className="text-oe-blue animate-spin" />
              <div className="text-left">
                <p className="text-sm font-semibold text-content-primary">
                  {t('explorer.converting', { defaultValue: 'Converting {{name}}...', name: fileName })}
                </p>
                <p className="text-xs text-content-tertiary">
                  {remaining > 0
                    ? t('explorer.remaining', { defaultValue: '~{{time}}s remaining — extracting elements and detecting columns', time: remaining })
                    : t('explorer.finalizing', { defaultValue: 'Finalizing...' })}
                </p>
              </div>
              <div className="text-right shrink-0">
                <span className="text-lg font-bold text-oe-blue tabular-nums">{Math.round(progressPct)}%</span>
                <p className="text-2xs text-content-quaternary tabular-nums">{elapsed}s / ~{Math.round(estimatedTotal)}s</p>
              </div>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className="h-full rounded-full bg-oe-blue transition-all duration-1000 ease-linear"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        ) : done ? (
          <div className="flex items-center justify-center gap-3">
            <CheckCircle2 size={24} className="text-green-500" />
            <p className="text-sm font-semibold text-green-600">
              {t('explorer.done', { defaultValue: 'Conversion complete! Loading explorer...' })}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <FileUp size={40} className="mx-auto text-content-tertiary" />
            <div>
              <p className="text-sm font-medium text-content-primary">
                {t('explorer.drop_cad', { defaultValue: 'Drop your CAD/BIM file here' })}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('explorer.or_click', { defaultValue: 'or click to browse — max 100 MB' })}
              </p>
            </div>
            <div className="flex items-center justify-center gap-2 mt-3">
              {CAD_FORMATS.map((fmt) => (
                <span key={fmt} className={`px-2 py-0.5 rounded-md text-2xs font-bold ${FORMAT_COLORS[fmt] || 'bg-gray-100 text-gray-600'}`}>
                  .{fmt.toLowerCase()}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Features grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { icon: Table2, title: t('explorer.feat_table', { defaultValue: 'Data Table' }), desc: t('explorer.feat_table_desc', { defaultValue: 'Sort, filter, paginate all elements' }) },
          { icon: Layers, title: t('explorer.feat_pivot', { defaultValue: 'Pivot & Group' }), desc: t('explorer.feat_pivot_desc', { defaultValue: 'Group by any column, aggregate sums' }) },
          { icon: BarChart3, title: t('explorer.feat_charts', { defaultValue: 'Visualize' }), desc: t('explorer.feat_charts_desc', { defaultValue: 'Bar and pie charts by category' }) },
          { icon: Sparkles, title: t('explorer.feat_describe', { defaultValue: 'Statistics' }), desc: t('explorer.feat_describe_desc', { defaultValue: 'Column stats like df.describe()' }) },
        ].map(({ icon: Icon, title, desc }) => (
          <Card key={title} className="p-4 text-center">
            <Icon size={20} className="mx-auto text-oe-blue mb-2" />
            <p className="text-xs font-semibold text-content-primary">{title}</p>
            <p className="text-2xs text-content-tertiary mt-0.5">{desc}</p>
          </Card>
        ))}
      </div>

      {/* Converter status */}
      <ConverterStatus />
    </div>
  );
}

/* ── Saved Sessions List ────────────────────────────────────────────────── */

import { Trash2 as TrashIcon, Clock, FileText, ExternalLink } from 'lucide-react';

function SavedSessionsList({ onOpen }: { onOpen: (sessionId: string) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: sessions = [], isLoading: sessionsLoading } = useQuery({
    queryKey: ['cad-saved-sessions', activeProjectId],
    queryFn: () => listSessions(activeProjectId || undefined),
  });

  const delMut = useMutation({
    mutationFn: deleteSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cad-saved-sessions'] });
      addToast({ type: 'success', title: t('explorer.session_deleted', { defaultValue: 'Analysis deleted' }) });
    },
  });

  if (sessionsLoading) return <div className="flex justify-center py-6"><div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" /></div>;
  if (sessions.length === 0) return null;

  return (
    <Card className="p-4">
      <h3 className="text-xs font-semibold text-content-primary mb-3 flex items-center gap-1.5">
        <Clock size={13} className="text-content-tertiary" />
        {t('explorer.saved_analyses', { defaultValue: 'Saved Analyses' })}
        <Badge variant="neutral" size="sm">{sessions.length}</Badge>
      </h3>
      <div className="divide-y divide-border-light">
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className="flex items-center gap-3 py-2.5 cursor-pointer hover:bg-surface-secondary/30 rounded-lg px-2 -mx-2 transition-colors"
            onClick={() => onOpen(s.session_id)}
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle shrink-0">
              <FileText size={16} className="text-oe-blue" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-content-primary truncate">{s.display_name}</p>
              <p className="text-2xs text-content-tertiary">
                {s.filename} · {s.element_count.toLocaleString()} elements · {s.file_format.toUpperCase()}
                {s.created_at && ` · ${new Date(s.created_at).toLocaleDateString()}`}
              </p>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); onOpen(s.session_id); }}
                className="p-1.5 rounded-md hover:bg-surface-secondary text-oe-blue"
                title={t('explorer.open', { defaultValue: 'Open' })}
              >
                <ExternalLink size={14} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); delMut.mutate(s.session_id); }}
                className="p-1.5 rounded-md hover:bg-surface-secondary text-content-tertiary hover:text-semantic-error"
                title={t('common.delete', { defaultValue: 'Delete' })}
              >
                <TrashIcon size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </Card>
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

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CadDataExplorerPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get('session') || '';
  const [activeTab, setActiveTab] = useState<TabId>('table');
  const [showSaveDialog, setShowSaveDialog] = useState(false);

  const { data: describe, isLoading, error } = useQuery({
    queryKey: ['cad-describe', sessionId],
    queryFn: () => describeSession(sessionId),
    enabled: !!sessionId,
  });

  const handleSessionReady = useCallback((newSessionId: string) => {
    setSearchParams({ session: newSessionId });
  }, [setSearchParams]);

  if (!sessionId) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        <Breadcrumb items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('explorer.title', { defaultValue: 'CAD-BIM Explorer' }) },
        ]} />
        <UploadConvertZone onSessionReady={handleSessionReady} />
        <SavedSessionsList onOpen={(sid) => setSearchParams({ session: sid })} />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-6 space-y-4">
      <Breadcrumb items={[
        { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
        { label: t('nav.cad_takeoff', { defaultValue: 'CAD Takeoff' }), to: '/cad-takeoff' },
        { label: t('explorer.title', { defaultValue: 'Data Explorer' }) },
      ]} />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
            <Database size={20} className="text-oe-blue" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-content-primary">{t('explorer.title', { defaultValue: 'CAD Data Explorer' })}</h1>
            {describe && (
              <p className="text-xs text-content-tertiary">
                {describe.filename} · {describe.total_elements.toLocaleString()} elements{describe.format ? ` · ${describe.format.toUpperCase()}` : ''}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" onClick={() => setShowSaveDialog(true)}>
            <Save size={13} className="mr-1" />
            <span>{t('explorer.save_analysis', { defaultValue: 'Save Analysis' })}</span>
          </Button>
          <Button variant="secondary" size="sm" onClick={() => { setSearchParams({}); }}>
            <Upload size={13} className="mr-1" />
            <span>{t('explorer.new_file', { defaultValue: 'New File' })}</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => navigate('/cad-takeoff')}>
            {t('explorer.back_to_cad', { defaultValue: 'Back to QTO' })}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      ) : error ? (
        /* Session expired or invalid — show upload zone to re-upload */
        <div className="space-y-4">
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
          <StatsCards data={describe} />

          {/* Tab selector */}
          <div className="flex items-center gap-1 border-b border-border-light">
            {TABS.map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                  activeTab === id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-tertiary hover:text-content-primary'
                }`}
              >
                <Icon size={14} />
                {t(`explorer.tab_${id}`, { defaultValue: label })}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === 'table' && <DataTableTab sessionId={sessionId} describe={describe} />}
          {activeTab === 'pivot' && <PivotTab sessionId={sessionId} describe={describe} />}
          {activeTab === 'charts' && <ChartsTab sessionId={sessionId} describe={describe} />}
          {activeTab === 'describe' && <DescribeTab sessionId={sessionId} describe={describe} />}
        </>
      ) : null}

      {/* Save dialog */}
      {showSaveDialog && describe && (
        <SaveDialog
          sessionId={sessionId}
          filename={describe.filename}
          onClose={() => setShowSaveDialog(false)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['cad-saved-sessions'] })}
        />
      )}
    </div>
  );
}

export default CadDataExplorerPage;
