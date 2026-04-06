/**
 * CAD Data Explorer — Pandas-like DataFrame interface for BIM element data.
 *
 * 4 tabs: Data Table | Pivot | Charts | Describe
 * Reads session_id from URL query parameter.
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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
  Search,
  X,
  Download,
} from 'lucide-react';
import { Button, Card, Badge, Breadcrumb, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  describeSession,
  valueCounts,
  fetchElements,
  aggregate,
  type DescribeResponse,
  type ValueCountsResponse,
  type ElementsResponse,
  type AggregateResponse,
  type AggregateGroup,
} from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

type TabId = 'table' | 'pivot' | 'charts' | 'describe';

const TABS: { id: TabId; icon: React.ElementType; label: string }[] = [
  { id: 'table', icon: Table2, label: 'Data Table' },
  { id: 'pivot', icon: Layers, label: 'Pivot' },
  { id: 'charts', icon: BarChart3, label: 'Charts' },
  { id: 'describe', icon: FileSpreadsheet, label: 'Describe' },
];

const AGG_FUNCTIONS = ['sum', 'avg', 'min', 'max', 'count'];

const UNIT_ICONS: Record<string, React.ElementType> = {
  'm³': Box, 'm²': Ruler, 'm': Ruler, 'pcs': Hash, 'kg': Hash,
};

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

/* ── Main Page ─────────────────────────────────────────────────────────── */

import React from 'react';

export function CadDataExplorerPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session') || '';
  const [activeTab, setActiveTab] = useState<TabId>('table');

  const { data: describe, isLoading, error } = useQuery({
    queryKey: ['cad-describe', sessionId],
    queryFn: () => describeSession(sessionId),
    enabled: !!sessionId,
  });

  if (!sessionId) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-6">
        <Breadcrumb items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('explorer.title', { defaultValue: 'Data Explorer' }) },
        ]} />
        <div className="mt-8">
          <EmptyState
            icon={<Database size={36} />}
            title={t('explorer.no_session', { defaultValue: 'No data loaded' })}
            description={t('explorer.no_session_desc', { defaultValue: 'Upload a CAD/BIM file on the CAD Takeoff page first, then click "Open in Data Explorer".' })}
            action={{ label: t('explorer.go_to_cad', { defaultValue: 'Go to CAD Takeoff' }), onClick: () => navigate('/cad-takeoff') }}
          />
        </div>
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
                {describe.filename} · {describe.total_elements.toLocaleString()} elements · {describe.format.toUpperCase()}
              </p>
            )}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate('/cad-takeoff')}>
          {t('explorer.back_to_cad', { defaultValue: 'Back to CAD Takeoff' })}
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
        </div>
      ) : error ? (
        <Card className="p-6 text-center">
          <p className="text-sm text-semantic-error mb-2">{t('explorer.load_error', { defaultValue: 'Failed to load session data' })}</p>
          <p className="text-xs text-content-tertiary mb-4">{t('explorer.session_expired_hint', { defaultValue: 'The CAD session may have expired (24h limit). Please re-upload the file.' })}</p>
          <Button variant="primary" size="sm" onClick={() => navigate('/cad-takeoff')}>
            {t('explorer.reupload', { defaultValue: 'Re-upload CAD File' })}
          </Button>
        </Card>
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
    </div>
  );
}

export default CadDataExplorerPage;
