// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * 6×6 discipline-pair heat-map for the Coordination Hub.
 *
 * Cells are rendered as a CSS grid (no Recharts dependency — a fixed 6×6
 * layout is too small to justify the chart-library overhead). Each
 * non-empty cell carries:
 *   * its open-count as the visible number
 *   * a background tint scaled by the count
 *   * a hover tooltip with a per-cell breakdown (total / open / resolved /
 *     cost-impact contribution)
 * Clicking a cell navigates to ``/clash?project=<pid>&disciplineA=<row>&disciplineB=<col>``
 * — the ClashPage reads those params and pre-applies the pair filter.
 */

import clsx from 'clsx';
import { useMemo, useState } from 'react';
import { Radar } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import type { CanonicalTrade, TradeMatrixResponse } from './types';

/** What drives the heat-map intensity + the headline number per cell. */
export type MatrixWeighting = 'count' | 'cost';

/** Coerce the wire value (Decimal-as-string) to a finite number. */
function toNum(v: string | number | undefined | null): number {
  if (v == null) return 0;
  const n = typeof v === 'number' ? v : Number.parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

export interface CoordinationTradeMatrixProps {
  data: TradeMatrixResponse | undefined;
  isLoading?: boolean;
  /**
   * Optional project id appended to the click-through deep link so the
   * ClashPage can resolve the right project even when the user landed
   * from an external link (no global project context selected yet).
   */
  projectId?: string | null;
  /**
   * When `true` the component drops its own card chrome (outer border /
   * padding / shadow) and inner title+subtitle — it is being rendered
   * inside a `GlassPanel` that already supplies them, so the standalone
   * wrapper would double the title and nest a card-in-a-card. Standalone
   * callers leave it `false` to keep the self-contained card.
   */
  embedded?: boolean;
}

/** Background-color ramp by clash count. Pure Tailwind so it tree-shakes. */
function tintForCount(open: number, maxOpen: number): string {
  if (open <= 0) return 'bg-slate-50';
  // Map (open / maxOpen) into one of five tints. Avoid a continuous
  // gradient because Tailwind purges unused classes — we need explicit
  // class strings.
  const ratio = maxOpen > 0 ? open / maxOpen : 0;
  if (ratio < 0.2) return 'bg-amber-50';
  if (ratio < 0.4) return 'bg-amber-100';
  if (ratio < 0.6) return 'bg-amber-200';
  if (ratio < 0.8) return 'bg-red-200';
  return 'bg-red-300';
}

/** Foreground colour by tint — keeps the count readable on dark cells. */
function textForCount(open: number, maxOpen: number): string {
  const ratio = maxOpen > 0 ? open / maxOpen : 0;
  if (open <= 0) return 'text-content-tertiary';
  if (ratio < 0.6) return 'text-amber-900';
  return 'text-red-900';
}

/** English fallback labels, kept for the aria-string builder (which renders
 *  values directly so a screen reader never reads a raw `{{key}}`). */
const DISCIPLINE_LABELS: Record<CanonicalTrade, string> = {
  arch: 'Arch',
  struct: 'Struct',
  mep: 'MEP',
  landscape: 'Landscape',
  civil: 'Civil',
  other: 'Other',
};

/** Localised discipline label — routes the six canonical trades through
 *  i18next so the matrix axes translate with the rest of the page. Falls
 *  back to the English label, then the raw key, for any unknown trade. */
function disciplineLabel(
  t: (key: string, opts?: Record<string, unknown>) => string,
  trade: CanonicalTrade,
): string {
  return t(`coordination_hub.trade_${trade}`, {
    defaultValue: DISCIPLINE_LABELS[trade] ?? trade,
  });
}

export function CoordinationTradeMatrix({
  data,
  isLoading,
  projectId,
  embedded = false,
}: CoordinationTradeMatrixProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Weight the heat-map by raw clash count (default) or by open
  // cost-impact. The cost view answers "which discipline pair is costing
  // money", not just "which has the most clashes" - a single Struct x MEP
  // clash through a chiller can outweigh fifty cosmetic ones.
  const [weighting, setWeighting] = useState<MatrixWeighting>('count');

  const currency = data?.currency || '';
  const totalCost = toNum(data?.total_cost_impact);
  const hasCost = useMemo(
    () => (data?.cells ?? []).some((c) => toNum(c.cost_impact) > 0),
    [data?.cells],
  );

  if (isLoading || !data) {
    return (
      <div
        data-testid="coordination-matrix-skeleton"
        className={
          embedded
            ? 'animate-pulse'
            : 'animate-pulse rounded-xl border border-border bg-surface p-4 shadow-sm'
        }
      >
        {!embedded ? <div className="h-4 w-1/3 rounded bg-slate-200" /> : null}
        <div
          className={
            embedded
              ? 'h-64 w-full rounded bg-slate-100'
              : 'mt-4 h-64 w-full rounded bg-slate-100'
          }
        />
      </div>
    );
  }

  const trades = data.trades;
  // Build a lookup so a (row, col) miss renders as zero.
  const cellMap = new Map<string, CellAgg>();
  for (const cell of data.cells) {
    cellMap.set(`${cell.row}::${cell.col}`, {
      count: cell.count,
      open: cell.open,
      resolved: cell.resolved,
      cost: toNum(cell.cost_impact),
    });
  }
  // The intensity ramp scales by whichever metric the operator is
  // weighting on, so the hottest cell is always the one that matters
  // most under the current lens (count vs money).
  const effectiveWeighting: MatrixWeighting =
    weighting === 'cost' && hasCost ? 'cost' : 'count';
  const maxOpen = data.cells.reduce(
    (acc, c) => (c.open > acc ? c.open : acc),
    0,
  );
  const maxCost = data.cells.reduce(
    (acc, c) => (toNum(c.cost_impact) > acc ? toNum(c.cost_impact) : acc),
    0,
  );

  // No clashes at all: a 6x6 grid of dashes is meaningless. Show a real
  // empty state that tells the user how to populate the matrix instead.
  const hasAnyClash = data.cells.some((c) => c.count > 0);
  if (!hasAnyClash) {
    const emptyBody = (
      <div
        data-testid="coordination-matrix-empty"
        className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-surface-secondary/30 px-6 py-10 text-center"
      >
        <Radar size={28} className="text-content-tertiary" strokeWidth={1.5} />
        <p className="mt-3 text-sm font-medium text-content-secondary">
          {t('coordination.matrix_empty_title', {
            defaultValue: 'No clashes detected yet',
          })}
        </p>
        <p className="mt-1 max-w-sm text-xs text-content-tertiary">
          {t('coordination.matrix_empty_desc', {
            defaultValue:
              'Run a clash detection over your federated models to populate the discipline heat-map.',
          })}
        </p>
        <button
          type="button"
          data-testid="coordination-matrix-empty-cta"
          onClick={() => {
            const params = new URLSearchParams();
            if (projectId) params.set('project', projectId);
            navigate(`/clash${params.toString() ? `?${params.toString()}` : ''}`);
          }}
          className="mt-4 inline-flex h-9 items-center justify-center rounded-md bg-oe-blue px-4 text-sm font-medium text-white transition-colors hover:bg-oe-blue/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
        >
          {t('coordination.matrix_empty_cta', {
            defaultValue: 'Run clash detection',
          })}
        </button>
      </div>
    );
    return <div data-testid="coordination-trade-matrix">{emptyBody}</div>;
  }

  const grid = (
    <div className="overflow-x-auto">
      <div
        className="grid gap-1"
        style={{
          gridTemplateColumns: `auto repeat(${trades.length}, minmax(60px, 1fr))`,
        }}
      >
        {/* Top-left corner */}
        <div />
        {/* Column headers */}
        {trades.map((col) => (
          <div
            key={`col-${col}`}
            className="text-center text-xs font-medium uppercase tracking-wide text-content-secondary"
          >
            {disciplineLabel(t, col)}
          </div>
        ))}
        {/* Rows */}
        {trades.map((row) => (
          <RowFragment
            key={`row-${row}`}
            row={row}
            trades={trades}
            cellMap={cellMap}
            maxOpen={maxOpen}
            maxCost={maxCost}
            weighting={effectiveWeighting}
            currency={currency}
            navigate={navigate}
            projectId={projectId ?? null}
            t={t}
          />
        ))}
      </div>
    </div>
  );

  // Weighting toggle + cost caption. Only offered when the payload
  // actually carries priced cost-impact (graceful degradation: a project
  // with no BOQ-linked clashes never shows a money toggle that would
  // weight everything to zero).
  const controls = (
    <div
      data-testid="coordination-matrix-controls"
      className="mb-3 flex flex-wrap items-center justify-between gap-2"
    >
      <div className="text-xs text-content-tertiary">
        {effectiveWeighting === 'cost' && currency ? (
          <span data-testid="coordination-matrix-cost-caption">
            {t('coordination.matrix_weighted_by_cost', {
              defaultValue: 'Weighted by open cost impact',
            })}
            {' · '}
            <MoneyDisplay amount={totalCost} currency={currency} compact />
          </span>
        ) : (
          <span>
            {t('coordination.matrix_weighted_by_count', {
              defaultValue: 'Weighted by open clash count',
            })}
          </span>
        )}
      </div>
      {hasCost ? (
        <div
          role="group"
          aria-label={t('coordination.matrix_weighting_aria', {
            defaultValue: 'Heat-map weighting',
          })}
          className="inline-flex overflow-hidden rounded-lg border border-border text-xs"
        >
          <button
            type="button"
            data-testid="coordination-matrix-weight-count"
            aria-pressed={weighting === 'count'}
            onClick={() => setWeighting('count')}
            className={clsx(
              'px-3 py-1 font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              weighting === 'count'
                ? 'bg-oe-blue text-white'
                : 'bg-surface text-content-secondary hover:bg-surface-secondary',
            )}
          >
            {t('coordination.matrix_weight_count', { defaultValue: 'Count' })}
          </button>
          <button
            type="button"
            data-testid="coordination-matrix-weight-cost"
            aria-pressed={weighting === 'cost'}
            onClick={() => setWeighting('cost')}
            className={clsx(
              'px-3 py-1 font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              weighting === 'cost'
                ? 'bg-oe-blue text-white'
                : 'bg-surface text-content-secondary hover:bg-surface-secondary',
            )}
          >
            {t('coordination.matrix_weight_cost', { defaultValue: 'Cost' })}
          </button>
        </div>
      ) : null}
    </div>
  );

  // Embedded inside a GlassPanel: it already paints the card + title, so
  // we drop our own chrome to avoid a card-in-a-card with a doubled title.
  if (embedded) {
    return (
      <div data-testid="coordination-trade-matrix">
        {controls}
        {grid}
      </div>
    );
  }

  return (
    <div
      data-testid="coordination-trade-matrix"
      className="rounded-xl border border-border bg-surface p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-content-primary">
            {t('coordination.trade_matrix_title', {
              defaultValue: 'Trade Matrix',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('coordination.trade_matrix_subtitle', {
              defaultValue:
                'Open clashes by discipline pair - click a cell to drill down.',
            })}
          </p>
        </div>
      </div>
      {controls}
      {grid}
    </div>
  );
}

/** One aggregated discipline-pair cell (lookup value). */
interface CellAgg {
  count: number;
  open: number;
  resolved: number;
  cost: number;
}

interface RowFragmentProps {
  row: CanonicalTrade;
  trades: CanonicalTrade[];
  cellMap: Map<string, CellAgg>;
  maxOpen: number;
  maxCost: number;
  weighting: MatrixWeighting;
  currency: string;
  navigate: ReturnType<typeof useNavigate>;
  projectId: string | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function RowFragment({
  row,
  trades,
  cellMap,
  maxOpen,
  maxCost,
  weighting,
  currency,
  navigate,
  projectId,
  t,
}: RowFragmentProps) {
  // Hovered cell key → drives the rich tooltip overlay. Plain HTML
  // ``title`` is also set so screen readers + non-pointer devices still
  // get the breakdown.
  const [hovered, setHovered] = useState<string | null>(null);
  return (
    <>
      <div className="text-right text-xs font-medium uppercase tracking-wide text-content-secondary">
        {disciplineLabel(t, row)}
      </div>
      {trades.map((col) => {
        // The server emits each pair once (row index ≤ col index). For
        // the mirror half we look up the swapped key so the matrix shows
        // both halves symmetrically.
        const key1 = `${row}::${col}`;
        const key2 = `${col}::${row}`;
        const cell = cellMap.get(key1) ?? cellMap.get(key2);
        const open = cell?.open ?? 0;
        const total = cell?.count ?? 0;
        const resolved = cell?.resolved ?? 0;
        const cost = cell?.cost ?? 0;
        const isEmpty = total === 0;
        // Intensity + headline number follow the active weighting lens.
        const intensity = weighting === 'cost' ? cost : open;
        const intensityMax = weighting === 'cost' ? maxCost : maxOpen;
        const tint = tintForCount(intensity, intensityMax);
        const fg = textForCount(intensity, intensityMax);
        const cellKey = `${row}-${col}`;
        // Compact money for the in-cell figure (e.g. "1.2k") so the grid
        // stays legible; the tooltip carries the precise breakdown.
        const costDisplay =
          cost >= 1000
            ? `${Math.round(cost / 100) / 10}k`
            : String(Math.round(cost));
        const cellValue =
          weighting === 'cost' ? (cost > 0 ? costDisplay : '—') : open;
        const tooltipPlain = isEmpty
          ? t('coordination.matrix_tooltip_empty', { defaultValue: '—' })
          : t('coordination.matrix_tooltip', {
              defaultValue:
                '{{open}} open · {{resolved}} resolved · {{total}} total',
              open,
              resolved,
              total,
            });
        return (
          <div
            key={`cellwrap-${row}-${col}`}
            className="relative"
            onMouseEnter={() => !isEmpty && setHovered(cellKey)}
            onMouseLeave={() => setHovered((prev) => (prev === cellKey ? null : prev))}
            onFocus={() => !isEmpty && setHovered(cellKey)}
            onBlur={() => setHovered((prev) => (prev === cellKey ? null : prev))}
          >
            <button
              type="button"
              data-testid={`matrix-cell-${row}-${col}`}
              disabled={isEmpty}
              title={tooltipPlain}
              aria-label={(() => {
                // Build the aria string with concrete values so screen
                // readers (and tests) always see the interpolated form.
                // The i18n template is still used as the formatting hint
                // — we render values directly so the SR never reads a
                // ``{{open}}`` placeholder when the locale lookup misses.
                const rowLabel = DISCIPLINE_LABELS[row] ?? row;
                const colLabel = DISCIPLINE_LABELS[col] ?? col;
                if (isEmpty) {
                  return `No clashes for ${rowLabel} × ${colLabel}`;
                }
                return (
                  `${open} open clashes between ${rowLabel} and ${colLabel}. ` +
                  'Press Enter to drill down.'
                );
              })()}
              onClick={() => {
                if (isEmpty) return;
                const params = new URLSearchParams();
                if (projectId) params.set('project', projectId);
                params.set('disciplineA', row);
                params.set('disciplineB', col);
                navigate(`/clash?${params.toString()}`);
              }}
              onKeyDown={(e) => {
                // Enter / Space already trigger onClick natively; we add
                // explicit handling so the test runner can dispatch a
                // keyboard event without going through a click first.
                if (isEmpty) return;
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  const params = new URLSearchParams();
                  if (projectId) params.set('project', projectId);
                  params.set('disciplineA', row);
                  params.set('disciplineB', col);
                  navigate(`/clash?${params.toString()}`);
                }
              }}
              className={clsx(
                'flex h-12 w-full items-center justify-center rounded-md border border-transparent text-sm font-semibold transition-colors',
                tint,
                fg,
                isEmpty
                  ? 'cursor-default opacity-60'
                  : 'hover:border-border-strong focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              )}
            >
              {isEmpty ? '—' : cellValue}
            </button>
            {hovered === cellKey && !isEmpty ? (
              <div
                role="tooltip"
                data-testid={`matrix-cell-tooltip-${row}-${col}`}
                className="pointer-events-none absolute left-1/2 top-full z-20 mt-1 -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-slate-900 px-2 py-1 text-xs font-medium text-white shadow-lg"
              >
                <div className="font-semibold">
                  {disciplineLabel(t, row)} × {disciplineLabel(t, col)}
                </div>
                <div>
                  {t('coordination.matrix_tooltip_total', {
                    defaultValue: 'Total',
                  })}
                  : {total}
                </div>
                <div>
                  {t('coordination.matrix_tooltip_open', {
                    defaultValue: 'Open',
                  })}
                  : {open}
                </div>
                <div>
                  {t('coordination.matrix_tooltip_resolved', {
                    defaultValue: 'Resolved',
                  })}
                  : {resolved}
                </div>
                {cost > 0 && currency ? (
                  <div data-testid={`matrix-cell-tooltip-cost-${row}-${col}`}>
                    {t('coordination.matrix_tooltip_cost', {
                      defaultValue: 'Open cost impact',
                    })}
                    :{' '}
                    <MoneyDisplay amount={cost} currency={currency} compact />
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}
