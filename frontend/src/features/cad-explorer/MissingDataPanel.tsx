/**
 * MissingDataPanel — missingno-style column fill-rate visualisation.
 *
 * Rendered as a sub-tab of the Describe tab. Fetches
 * /v1/takeoff/cad-data/missingness/ and paints one vertical stripe per
 * BIM/CAD attribute on a <canvas>: BLACK cell = value present, LIGHT-GRAY
 * cell = missing/null. A right-hand strip shows a per-row completeness
 * sparkline (0..1). Category / element-type <select>s re-filter the rows
 * before the matrix is rebuilt (server-side — we never downsample on the
 * client so a 500k-row model stays responsive).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Card, Badge } from '@/shared/ui';
import { Copy as CopyIcon, Loader2 } from 'lucide-react';
import {
  fetchMissingness,
  valueCounts,
  type ColumnMissingness,
  type MissingnessSortKey,
} from './api';
import { useToastStore } from '@/stores/useToastStore';

interface MissingDataPanelProps {
  sessionId: string;
}

interface TooltipState {
  x: number;
  y: number;
  column: ColumnMissingness;
}

/* ── Canvas colours (aligned with OE palette) ───────────────────────── */
const CELL_PRESENT = '#1f2937'; // slate-800 — "black"
const CELL_MISSING = '#e5e7eb'; // gray-200 — "light-gray"
const ROW_LINE = '#2563eb'; // oe-blue

function pickFilterColumn(columnNames: string[], candidates: string[]): string | null {
  const lower = columnNames.reduce<Record<string, string>>((acc, c) => {
    acc[c.toLowerCase()] = c;
    return acc;
  }, {});
  for (const cand of candidates) {
    const hit = lower[cand.toLowerCase()];
    if (hit) return hit;
  }
  return null;
}

export function MissingDataPanel({ sessionId }: MissingDataPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [elementTypeFilter, setElementTypeFilter] = useState<string>('');
  const [sortKey, setSortKey] = useState<MissingnessSortKey>('fill_desc');

  const [hover, setHover] = useState<TooltipState | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sparkRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  /* ── Primary fetch (matrix + fill-rates) ──────────────────────────── */
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['cad-missingness', sessionId, categoryFilter, elementTypeFilter, sortKey],
    queryFn: () =>
      fetchMissingness(sessionId, {
        categoryFilter: categoryFilter || undefined,
        elementTypeFilter: elementTypeFilter || undefined,
        sort: sortKey,
      }),
    staleTime: 30_000,
  });

  /* ── Dropdown options — load via value-counts on category / type ──── */
  const columnNames = useMemo(() => (data?.columns ?? []).map((c) => c.name), [data]);

  const categoryCol = useMemo(() => pickFilterColumn(columnNames, ['category']), [columnNames]);
  const typeCol = useMemo(
    () => pickFilterColumn(columnNames, ['type name', 'type', 'family']),
    [columnNames],
  );

  const { data: categoryOpts } = useQuery({
    queryKey: ['cad-value-counts-missing', sessionId, categoryCol],
    queryFn: () => valueCounts(sessionId, categoryCol!, 100),
    enabled: !!categoryCol,
    staleTime: 60_000,
  });

  const { data: typeOpts } = useQuery({
    queryKey: ['cad-value-counts-missing', sessionId, typeCol],
    queryFn: () => valueCounts(sessionId, typeCol!, 200),
    enabled: !!typeCol,
    staleTime: 60_000,
  });

  /* ── Render the matrix onto <canvas> ───────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data || data.presence_matrix.length === 0) return;

    const container = containerRef.current;
    const cssWidth = Math.max(container?.clientWidth ?? 800, 320);
    const cssHeight = 360;
    const dpr = window.devicePixelRatio || 1;

    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    // Background (missing)
    ctx.fillStyle = CELL_MISSING;
    ctx.fillRect(0, 0, cssWidth, cssHeight);

    const cols = data.columns.length;
    const rows = data.presence_matrix.length;
    if (cols === 0 || rows === 0) return;

    const colWidth = Math.max(cssWidth / cols, 1);
    const rowHeight = Math.max(cssHeight / rows, 1);

    // Draw present cells as black — batched per column for speed
    ctx.fillStyle = CELL_PRESENT;
    for (let c = 0; c < cols; c += 1) {
      const x = c * colWidth;
      // Find contiguous runs of 1s to reduce fillRect calls
      let runStart = -1;
      for (let r = 0; r < rows; r += 1) {
        const bit = data.presence_matrix[r]?.[c] ?? 0;
        if (bit === 1) {
          if (runStart === -1) runStart = r;
        } else if (runStart !== -1) {
          ctx.fillRect(x, runStart * rowHeight, Math.max(colWidth - 0.5, 0.5), (r - runStart) * rowHeight);
          runStart = -1;
        }
      }
      if (runStart !== -1) {
        ctx.fillRect(
          x,
          runStart * rowHeight,
          Math.max(colWidth - 0.5, 0.5),
          (rows - runStart) * rowHeight,
        );
      }
    }
  }, [data]);

  /* ── Row-completeness sparkline ──────────────────────────────────── */
  useEffect(() => {
    const canvas = sparkRef.current;
    if (!canvas || !data || data.row_completeness.length === 0) return;

    const cssWidth = 120;
    const cssHeight = 360;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#f9fafb';
    ctx.fillRect(0, 0, cssWidth, cssHeight);

    // Reference lines at 0%, 50%, 100%
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    [0, 0.25, 0.5, 0.75, 1].forEach((pct) => {
      const x = Math.round(pct * (cssWidth - 1)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, cssHeight);
      ctx.stroke();
    });

    ctx.strokeStyle = ROW_LINE;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const rows = data.row_completeness.length;
    for (let r = 0; r < rows; r += 1) {
      const pct = data.row_completeness[r] ?? 0;
      const x = pct * (cssWidth - 2) + 1;
      const y = (r / Math.max(rows - 1, 1)) * cssHeight;
      if (r === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }, [data]);

  /* ── Canvas hover tooltip ─────────────────────────────────────────── */
  function handleCanvasMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!data || data.columns.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const colWidth = rect.width / data.columns.length;
    const colIdx = Math.min(Math.floor(relX / colWidth), data.columns.length - 1);
    const col = data.columns[colIdx];
    if (!col) return;
    setHover({ x: e.clientX - rect.left, y: e.clientY - rect.top, column: col });
  }

  function handleCanvasLeave() {
    setHover(null);
  }

  /* ── Copy CSV summary ─────────────────────────────────────────────── */
  function handleCopyCsv() {
    if (!data) return;
    const header = 'column,non_null_count,fill_rate_pct,dtype\n';
    const body = data.columns
      .map(
        (c) =>
          `"${c.name.replaceAll('"', '""')}",${c.non_null_count},${(c.fill_rate * 100).toFixed(2)},${c.dtype}`,
      )
      .join('\n');
    const csv = header + body;
    void navigator.clipboard.writeText(csv).then(() => {
      addToast({
        type: 'success',
        title: t('explorer.missingness_csv_copied', { defaultValue: 'CSV summary copied to clipboard' }),
      });
    });
  }

  /* ── Render ───────────────────────────────────────────────────────── */
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-content-tertiary">
        <Loader2 className="animate-spin mr-2" size={16} />
        <span className="text-xs">
          {t('explorer.missingness_loading', { defaultValue: 'Computing fill-rates...' })}
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-4 border-red-200 bg-red-50 dark:bg-red-950/20 dark:border-red-900">
        <p className="text-xs text-red-700 dark:text-red-300">
          {t('explorer.missingness_error', {
            defaultValue: 'Unable to compute column fill-rates for this session.',
          })}
        </p>
      </Card>
    );
  }

  if (!data) return null;

  const footerLabel = data.sampled
    ? t('explorer.missingness_footer_sampled', {
        defaultValue: 'Showing {{n}} of {{m}} rows (random sample)',
        n: data.sampled_rows.toLocaleString(),
        m: data.total_rows.toLocaleString(),
      })
    : t('explorer.missingness_footer_full', {
        defaultValue: 'Showing all {{n}} rows',
        n: data.total_rows.toLocaleString(),
      });

  return (
    <div className="space-y-4">
      {/* ── Top controls ───────────────────────────────────────── */}
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-3">
          {categoryCol && (
            <label className="flex items-center gap-2">
              <span className="text-2xs font-semibold text-content-secondary uppercase tracking-wide">
                {t('explorer.missingness_category', { defaultValue: 'Category' })}
              </span>
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="h-7 px-2 text-xs rounded-md border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                data-testid="missingness-category-filter"
              >
                <option value="">
                  {t('explorer.missingness_all', { defaultValue: 'All' })}
                </option>
                {(categoryOpts?.values ?? []).map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.value} ({v.count.toLocaleString()})
                  </option>
                ))}
              </select>
            </label>
          )}
          {typeCol && (
            <label className="flex items-center gap-2">
              <span className="text-2xs font-semibold text-content-secondary uppercase tracking-wide">
                {t('explorer.missingness_element_type', { defaultValue: 'Element Type' })}
              </span>
              <select
                value={elementTypeFilter}
                onChange={(e) => setElementTypeFilter(e.target.value)}
                className="h-7 px-2 text-xs rounded-md border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                data-testid="missingness-type-filter"
              >
                <option value="">
                  {t('explorer.missingness_all', { defaultValue: 'All' })}
                </option>
                {(typeOpts?.values ?? []).map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.value} ({v.count.toLocaleString()})
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="flex items-center gap-2">
            <span className="text-2xs font-semibold text-content-secondary uppercase tracking-wide">
              {t('explorer.missingness_sort', { defaultValue: 'Sort columns' })}
            </span>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as MissingnessSortKey)}
              className="h-7 px-2 text-xs rounded-md border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              data-testid="missingness-sort"
            >
              <option value="fill_desc">
                {t('explorer.missingness_sort_fill_desc', { defaultValue: 'Fill-rate (high → low)' })}
              </option>
              <option value="fill_asc">
                {t('explorer.missingness_sort_fill_asc', { defaultValue: 'Fill-rate (low → high)' })}
              </option>
              <option value="alpha_asc">
                {t('explorer.missingness_sort_alpha_asc', { defaultValue: 'Alphabetical (A → Z)' })}
              </option>
              <option value="alpha_desc">
                {t('explorer.missingness_sort_alpha_desc', { defaultValue: 'Alphabetical (Z → A)' })}
              </option>
            </select>
          </label>

          <div className="ml-auto flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-2xs text-content-tertiary">
              <span className="inline-block w-3 h-3 rounded-sm" style={{ background: CELL_PRESENT }} />
              {t('explorer.missingness_legend_present', { defaultValue: 'Present' })}
              <span
                className="inline-block w-3 h-3 rounded-sm border border-border-light ml-2"
                style={{ background: CELL_MISSING }}
              />
              {t('explorer.missingness_legend_missing', { defaultValue: 'Missing' })}
            </div>
            <button
              type="button"
              onClick={handleCopyCsv}
              className="inline-flex items-center gap-1 h-7 px-2 rounded-md text-2xs border border-border-light text-content-secondary hover:bg-surface-secondary"
              data-testid="missingness-copy-csv"
            >
              <CopyIcon size={12} />
              {t('explorer.missingness_copy_csv', { defaultValue: 'Copy CSV' })}
            </button>
          </div>
        </div>
      </Card>

      {/* ── Matrix ─────────────────────────────────────────────── */}
      <Card padding="none" className="overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 flex items-center gap-2">
          <h3 className="text-xs font-semibold text-content-primary">
            {t('explorer.missingness_title', { defaultValue: 'Column Fill-Rate Matrix' })}
          </h3>
          <Badge size="sm" variant="neutral">
            {data.columns.length}{' '}
            {t('explorer.missingness_columns_suffix', { defaultValue: 'columns' })}
          </Badge>
          {isFetching && <Loader2 className="animate-spin text-content-tertiary" size={12} />}
        </div>

        <div ref={containerRef} className="relative flex p-3 gap-2">
          <div className="flex-1 relative">
            <canvas
              ref={canvasRef}
              onMouseMove={handleCanvasMove}
              onMouseLeave={handleCanvasLeave}
              data-testid="missingness-canvas"
              className="block cursor-crosshair rounded border border-border-light"
            />
            {hover && (
              <div
                className="pointer-events-none absolute z-10 px-2 py-1 rounded-md bg-content-primary text-surface-primary text-2xs shadow-lg whitespace-nowrap"
                style={{
                  left: Math.min(hover.x + 8, (containerRef.current?.clientWidth ?? 800) - 240),
                  top: Math.max(hover.y - 36, 4),
                }}
              >
                <div className="font-semibold truncate max-w-[220px]">{hover.column.name}</div>
                <div className="opacity-80">
                  {(hover.column.fill_rate * 100).toFixed(1)}%{' '}
                  {t('explorer.missingness_tooltip_filled', { defaultValue: 'filled' })}
                  {' · '}
                  {hover.column.non_null_count.toLocaleString()}{' / '}
                  {data.total_rows.toLocaleString()}
                </div>
                <div className="opacity-60">
                  {t('explorer.missingness_dtype', { defaultValue: 'type' })}: {hover.column.dtype}
                </div>
              </div>
            )}
          </div>

          {/* Per-row completeness sparkline */}
          <div className="shrink-0">
            <div className="text-2xs text-content-tertiary mb-1 text-center">
              {t('explorer.missingness_row_completeness', { defaultValue: 'Row completeness' })}
            </div>
            <canvas
              ref={sparkRef}
              data-testid="missingness-sparkline"
              className="block rounded border border-border-light"
            />
            <div className="flex justify-between text-2xs text-content-quaternary mt-0.5">
              <span>0%</span>
              <span>100%</span>
            </div>
          </div>
        </div>

        <div className="px-4 py-2 border-t border-border-light bg-surface-secondary/20 text-2xs text-content-tertiary flex items-center justify-between">
          <span data-testid="missingness-footer">{footerLabel}</span>
          {Object.keys(data.applied_filters).length > 0 && (
            <span className="text-content-secondary">
              {t('explorer.missingness_filters_applied', {
                defaultValue: 'Filters: {{summary}}',
                summary: Object.entries(data.applied_filters)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(', '),
              })}
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}

export default MissingDataPanel;
