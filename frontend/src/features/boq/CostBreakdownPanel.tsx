import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, TrendingUp } from 'lucide-react';
import {
  boqApi,
  type CostBreakdownCategory,
  type CostBreakdownMarkup,
  type CostBreakdownResource,
} from './api';

/* ── Constants ──────────────────────────────────────────────────────── */

/** Colors for the donut chart segments and bar breakdown. */
const CATEGORY_COLORS: Record<string, string> = {
  material: '#3b82f6', // blue-500
  labor: '#f59e0b', // amber-500
  equipment: '#8b5cf6', // violet-500
  subcontractor: '#ec4899', // pink-500
  other: '#6b7280', // gray-500
};

const CATEGORY_BG_CLASSES: Record<string, string> = {
  material: 'bg-blue-500',
  labor: 'bg-amber-500',
  equipment: 'bg-violet-500',
  subcontractor: 'bg-pink-500',
  other: 'bg-gray-500',
};

const CATEGORY_TEXT_CLASSES: Record<string, string> = {
  material: 'text-blue-600 dark:text-blue-400',
  labor: 'text-amber-600 dark:text-amber-400',
  equipment: 'text-violet-600 dark:text-violet-400',
  subcontractor: 'text-pink-600 dark:text-pink-400',
  other: 'text-gray-600 dark:text-gray-400',
};

/* ── Helpers ─────────────────────────────────────────────────────────── */

function createCBFormatter(locale: string) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtCompact(n: number, fmt: Intl.NumberFormat): string {
  if (Math.abs(n) >= 1_000_000) {
    return `${fmt.format(n / 1_000_000)}M`;
  }
  if (Math.abs(n) >= 10_000) {
    return `${fmt.format(n / 1_000)}K`;
  }
  return fmt.format(n);
}

/** Build a CSS conic-gradient string from categories + markups. */
function buildConicGradient(
  categories: CostBreakdownCategory[],
  markups: CostBreakdownMarkup[],
  grandTotal: number,
): string {
  if (grandTotal <= 0) return 'conic-gradient(#e5e7eb 0deg 360deg)';

  const segments: { color: string; pct: number }[] = [];

  for (const cat of categories) {
    segments.push({
      color: CATEGORY_COLORS[cat.type] ?? '#6b7280',
      pct: (cat.amount / grandTotal) * 100,
    });
  }
  for (const m of markups) {
    // Try to guess color by name
    const nameLower = m.name.toLowerCase();
    let color = '#9ca3af'; // gray-400 default
    if (nameLower.includes('overhead') || nameLower.includes('bgk') || nameLower.includes('agk')) {
      color = '#a855f7'; // purple-500
    } else if (nameLower.includes('profit') || nameLower.includes('gewinn') || nameLower.includes('w&g')) {
      color = '#22c55e'; // green-500
    }
    segments.push({ color, pct: (m.amount / grandTotal) * 100 });
  }

  let angle = 0;
  const stops: string[] = [];
  for (const seg of segments) {
    const start = angle;
    angle += (seg.pct / 100) * 360;
    stops.push(`${seg.color} ${start.toFixed(1)}deg ${angle.toFixed(1)}deg`);
  }

  return `conic-gradient(${stops.join(', ')})`;
}

/* ── Component ───────────────────────────────────────────────────────── */

export function CostBreakdownPanel({ boqId, locale = 'de-DE' }: { boqId: string; locale?: string }) {
  const { t } = useTranslation();
  const fmt = useMemo(() => createCBFormatter(locale), [locale]);
  const [collapsed, setCollapsed] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['boq-cost-breakdown', boqId],
    queryFn: () => boqApi.getCostBreakdown(boqId),
    enabled: !!boqId,
    staleTime: 5000,
  });

  const conicGradient = useMemo(() => {
    if (!data) return 'conic-gradient(#e5e7eb 0deg 360deg)';
    return buildConicGradient(data.categories, data.markups, data.grand_total);
  }, [data]);

  /* ── Loading state ─────────────────────────────────────────────────── */

  // Only show loading skeleton on very first load (no data yet)
  if (isLoading && !data) {
    return (
      <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs p-4">
        <div className="flex items-center gap-2 text-xs text-content-tertiary animate-pulse">
          <TrendingUp size={14} />
          {t('boq.cost_breakdown_loading', { defaultValue: 'Loading cost breakdown...' })}
        </div>
      </div>
    );
  }

  if (!data || data.direct_cost === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <button
        type="button"
        className="flex items-center justify-between w-full px-5 py-3.5 text-left hover:bg-surface-secondary/50 transition-colors"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <div className="flex items-center gap-2">
          {collapsed ? (
            <ChevronRight size={16} className="text-content-tertiary" />
          ) : (
            <ChevronDown size={16} className="text-content-tertiary" />
          )}
          <TrendingUp size={16} className="text-content-secondary" />
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.cost_breakdown', { defaultValue: 'Cost Breakdown' })}
          </span>
        </div>
        <span className="text-sm font-bold text-content-primary tabular-nums">
          {fmtCompact(data.grand_total, fmt)}
        </span>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4 space-y-5">
          {/* ── Donut Chart + Legend ──────────────────────────────────── */}
          <div className="flex items-start gap-6">
            {/* Donut */}
            <div className="relative flex-shrink-0">
              <div
                className="w-32 h-32 rounded-full"
                style={{
                  background: conicGradient,
                  mask: 'radial-gradient(circle, transparent 55%, black 56%)',
                  WebkitMask: 'radial-gradient(circle, transparent 55%, black 56%)',
                }}
              />
              {/* Center label */}
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-[10px] text-content-tertiary uppercase tracking-wide">
                  {t('boq.cost_breakdown_total', { defaultValue: 'Total' })}
                </span>
                <span className="text-sm font-bold text-content-primary tabular-nums">
                  {fmtCompact(data.grand_total, fmt)}
                </span>
              </div>
            </div>

            {/* Legend */}
            <div className="flex-1 space-y-1.5 pt-1">
              {data.categories.map((cat) => (
                <div key={cat.type} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2.5 h-2.5 rounded-sm flex-shrink-0 ${CATEGORY_BG_CLASSES[cat.type] ?? 'bg-gray-500'}`}
                    />
                    <span className="text-content-secondary capitalize">
                      {t(`boq.cost_category_${cat.type}`, { defaultValue: cat.type })}
                    </span>
                  </div>
                  <span className="text-content-primary font-medium tabular-nums">
                    {cat.percentage.toFixed(1)}%
                  </span>
                </div>
              ))}
              {data.markups.map((m) => (
                <div key={m.name} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0 bg-purple-500" />
                    <span className="text-content-secondary">{m.name}</span>
                  </div>
                  <span className="text-content-primary font-medium tabular-nums">
                    {((m.amount / data.grand_total) * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Horizontal Bar Breakdown ──────────────────────────────── */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
              {t('boq.cost_breakdown_by_category', { defaultValue: 'By Category' })}
            </h4>
            {data.categories.map((cat) => (
              <CategoryBar key={cat.type} category={cat} directCost={data.direct_cost} fmt={fmt} />
            ))}
          </div>

          {/* ── Top Resources ─────────────────────────────────────────── */}
          {data.top_resources.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                {t('boq.cost_breakdown_top_resources', { defaultValue: 'Top Resources' })}
              </h4>
              <div className="space-y-1">
                {data.top_resources.map((res, idx) => (
                  <ResourceRow key={`${res.name}-${idx}`} resource={res} fmt={fmt} />
                ))}
              </div>
            </div>
          )}

          {/* ── Summary ───────────────────────────────────────────────── */}
          <div className="border-t border-border pt-3 space-y-1.5">
            <SummaryRow
              label={t('boq.direct_cost', { defaultValue: 'Direct Cost' })}
              value={data.direct_cost}
              fmt={fmt}
            />
            {data.markups.map((m) => (
              <SummaryRow
                key={m.name}
                label={`${m.name} (${m.percentage}%)`}
                value={m.amount}
                fmt={fmt}
                secondary
              />
            ))}
            <div className="border-t border-border pt-1.5">
              <SummaryRow
                label={t('boq.grand_total', { defaultValue: 'Grand Total' })}
                value={data.grand_total}
                fmt={fmt}
                bold
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────────────────── */

function CategoryBar({
  category,
  directCost,
  fmt,
}: {
  category: CostBreakdownCategory;
  directCost: number;
  fmt: Intl.NumberFormat;
}) {
  const { t } = useTranslation();
  const widthPct = directCost > 0 ? (category.amount / directCost) * 100 : 0;

  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-xs">
        <span className={`font-medium capitalize ${CATEGORY_TEXT_CLASSES[category.type] ?? 'text-gray-600'}`}>
          {t(`boq.cost_category_${category.type}`, { defaultValue: category.type })}
          <span className="text-content-tertiary ml-1.5">
            ({category.item_count} {t('boq.cost_breakdown_items', { defaultValue: 'items' })})
          </span>
        </span>
        <span className="text-content-primary font-medium tabular-nums">
          {fmtCompact(category.amount, fmt)}
        </span>
      </div>
      <div className="w-full h-2 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${CATEGORY_BG_CLASSES[category.type] ?? 'bg-gray-500'}`}
          style={{ width: `${Math.max(widthPct, 0.5)}%` }}
        />
      </div>
    </div>
  );
}

function ResourceRow({
  resource,
  fmt,
}: {
  resource: CostBreakdownResource;
  fmt: Intl.NumberFormat;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between text-xs py-1 px-2 rounded hover:bg-surface-secondary/50">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span
          className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${CATEGORY_BG_CLASSES[resource.type] ?? 'bg-gray-500'}`}
        />
        <span className="text-content-secondary truncate">{resource.name}</span>
        <span className="text-content-tertiary flex-shrink-0">
          ({resource.positions_count} {t('boq.cost_breakdown_pos', { defaultValue: 'pos.' })})
        </span>
      </div>
      <span className="text-content-primary font-medium tabular-nums ml-3 flex-shrink-0">
        {fmtCompact(resource.total_cost, fmt)}
      </span>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  fmt,
  bold,
  secondary,
}: {
  label: string;
  value: number;
  fmt: Intl.NumberFormat;
  bold?: boolean;
  secondary?: boolean;
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span
        className={
          bold
            ? 'font-bold text-content-primary text-sm'
            : secondary
              ? 'text-content-tertiary'
              : 'text-content-secondary font-medium'
        }
      >
        {label}
      </span>
      <span
        className={`tabular-nums ${bold ? 'font-bold text-content-primary text-sm' : secondary ? 'text-content-tertiary' : 'text-content-primary font-medium'}`}
      >
        {fmtCompact(value, fmt)}
      </span>
    </div>
  );
}
