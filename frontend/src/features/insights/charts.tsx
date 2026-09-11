// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Recharts wrappers for Module Insights. One {@link SeriesChart} draws bar,
 * line, area and donut from the same `{name, value}[]` shape the aggregator
 * produces, plus a {@link KpiTile} for single-number insights.
 *
 * Theming: grid, axes and the tooltip are painted with the app's CSS custom
 * properties (the same `var(--color-*)` tokens BidComparisonChart uses), so the
 * charts read correctly in both light and dark themes rather than being pinned
 * to one. Every chart gets an explicit pixel height because a ResponsiveContainer
 * with no measurable height renders blank.
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useTranslation } from 'react-i18next';
import { fmtCompact, fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { formatCompactCurrency } from '@/shared/lib/money';
import { hasEnoughPoints } from '@/shared/lib/chartDataFloor';
import type { SeriesPoint } from './aggregate';
import type { ChartKind, ValueFormat } from './types';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export const CHART_HEIGHT = 216;

/** Categorical palette - shared with the dashboards Quick-Insight panel so the
 *  product speaks one visual language across surfaces. */
export const CHART_PALETTE = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#8b5cf6', // violet
  '#ef4444', // red
  '#14b8a6', // teal
  '#ec4899', // pink
  '#a3e635', // lime
];

export function paletteColor(i: number): string {
  return CHART_PALETTE[((i % CHART_PALETTE.length) + CHART_PALETTE.length) % CHART_PALETTE.length] ?? CHART_PALETTE[0]!;
}

const GRID = 'var(--color-border-light, #e5e7eb)';
const AXIS = 'var(--color-content-tertiary, #9ca3af)';
const MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

/* ── Value formatting ──────────────────────────────────────────────────── */

/** Compact form for axis ticks and KPI tiles: 12.3K, 1.2M, 45%. */
export function formatCompact(v: number, format: ValueFormat = 'number', currency?: string): string {
  if (!Number.isFinite(v)) return '-';
  if (format === 'percent') return `${fmtFixed(v, Math.abs(v) < 10 ? 1 : 0)}%`;
  if (format === 'currency' && currency) return formatCompactCurrency(v, currency);
  const abs = Math.abs(v);
  if (abs < 1_000) return `${Math.round(v * 100) / 100}`;
  return fmtCompact(v);
}

/** Full form for tooltips: locale grouping and a real currency symbol. */
export function formatFull(v: number, format: ValueFormat = 'number', currency?: string): string {
  if (!Number.isFinite(v)) return '-';
  if (format === 'percent') return fmtPercent(v);
  const locale = getNumberLocale();
  if (format === 'currency') {
    const code = (currency || '').trim().toUpperCase();
    if (/^[A-Z]{3}$/.test(code)) {
      try {
        return new Intl.NumberFormat(locale, {
          style: 'currency',
          currency: code,
          minimumFractionDigits: 0,
          maximumFractionDigits: 0,
        }).format(v);
      } catch {
        /* fall through to plain number */
      }
    }
  }
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(v);
}

function truncTick(s: string): string {
  return s.length > 9 ? `${s.slice(0, 8)}…` : s;
}

/* ── Themed tooltip ────────────────────────────────────────────────────── */

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: SeriesPoint }>;
  format?: ValueFormat;
  currency?: string;
}

function VizTooltip({ active, payload, format = 'number', currency }: TooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0];
  if (!p) return null;
  return (
    <div className="rounded-lg border border-border bg-surface-primary px-2.5 py-1.5 text-xs shadow-lg">
      <div className="max-w-[180px] truncate font-medium text-content-primary">{p.payload.name}</div>
      <div className="tabular-nums text-content-secondary">{formatFull(p.value, format, currency)}</div>
    </div>
  );
}

/* ── The one series chart ──────────────────────────────────────────────── */

export interface SeriesChartProps {
  points: SeriesPoint[];
  kind: Exclude<ChartKind, 'kpi'>;
  color?: number;
  format?: ValueFormat;
  currency?: string;
}

export function SeriesChart({ points, kind, color = 0, format = 'number', currency }: SeriesChartProps) {
  if (!points.length) return <ChartEmpty />;
  // Between "no data" and a real chart there used to be nothing, so one row
  // drew a donut with a single segment and one month drew a line with one
  // point. Saying "not enough data yet" is honest; drawing it anyway is not.
  if (!hasEnoughPoints(kind, points.length)) return <ChartEmpty reason="insufficient" />;
  const stroke = paletteColor(color);
  const tip = <VizTooltip format={format} currency={currency} />;

  if (kind === 'donut') {
    return (
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <PieChart>
          <Pie
            data={points}
            dataKey="value"
            nameKey="name"
            innerRadius={46}
            outerRadius={78}
            paddingAngle={1}
            stroke="var(--color-surface-primary, #ffffff)"
            strokeWidth={2}
          >
            {points.map((_, i) => (
              <Cell key={i} fill={paletteColor(i)} />
            ))}
          </Pie>
          <Tooltip content={tip} />
          <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // Bar, line and area share the same axes. An array of children (not a
  // Fragment) keeps recharts happy while staying DRY.
  const axes = [
    <CartesianGrid key="g" strokeDasharray="3 3" stroke={GRID} vertical={false} />,
    <XAxis
      key="x"
      dataKey="name"
      tick={{ fill: AXIS, fontSize: 11 }}
      tickLine={false}
      axisLine={{ stroke: GRID }}
      tickFormatter={truncTick}
      interval="preserveStartEnd"
      minTickGap={8}
    />,
    <YAxis
      key="y"
      tick={{ fill: AXIS, fontSize: 11 }}
      tickLine={false}
      axisLine={false}
      width={46}
      tickFormatter={(v: number) => formatCompact(v, format)}
    />,
    <Tooltip
      key="t"
      content={tip}
      cursor={{ fill: 'var(--color-border-light, #e5e7eb)', fillOpacity: 0.4 }}
    />,
  ];

  if (kind === 'line') {
    return (
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={points} margin={MARGIN}>
          {axes}
          <Line type="monotone" dataKey="value" stroke={stroke} strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (kind === 'area') {
    const gid = `insight-area-${color}`;
    return (
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <AreaChart data={points} margin={MARGIN}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          {axes}
          <Area type="monotone" dataKey="value" stroke={stroke} strokeWidth={2.25} fill={`url(#${gid})`} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // bar
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={points} margin={MARGIN}>
        {axes}
        <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={56} fill={stroke}>
          {points.map((_, i) => (
            <Cell key={i} fill={stroke} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * The two non-chart states.
 *
 * `empty` keeps the em-dash it has always had - there is nothing to say
 * about no rows. `insufficient` says so in words, because a user looking at
 * a panel that refuses to draw deserves to know the panel is working and the
 * data is thin, rather than reading a dash as a bug.
 */
function ChartEmpty({ reason = 'empty' }: { reason?: 'empty' | 'insufficient' }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-center justify-center px-3 text-center text-xs text-content-tertiary"
      style={{ height: CHART_HEIGHT }}
      data-testid={reason === 'insufficient' ? 'chart-not-enough-data' : 'chart-empty'}
    >
      {reason === 'insufficient'
        ? t('insights.not_enough_data', { defaultValue: 'Not enough data' })
        : '—'}
    </div>
  );
}

/* ── KPI tile ──────────────────────────────────────────────────────────── */

export interface KpiTileProps {
  label: string;
  value: number;
  format?: ValueFormat;
  currency?: string;
  color?: number;
  caption?: string;
}

export function KpiTile({ label, value, format = 'number', currency, color = 0, caption }: KpiTileProps) {
  const accent = paletteColor(color);
  return (
    <div className="relative overflow-hidden rounded-xl border border-border-light bg-surface-primary p-3.5">
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} aria-hidden />
      <div className="pl-1.5">
        <div className="truncate text-2xs font-medium uppercase tracking-wider text-content-tertiary" title={label}>
          {label}
        </div>
        <div className="mt-1 text-2xl font-semibold tabular-nums text-content-primary">
          {formatFull(value, format, currency)}
        </div>
        {caption && <div className="mt-0.5 truncate text-2xs text-content-tertiary">{caption}</div>}
      </div>
    </div>
  );
}
