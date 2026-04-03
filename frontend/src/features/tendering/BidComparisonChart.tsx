import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface BidTotal {
  bid_id: string;
  company_name: string;
  total: number;
  currency: string;
  deviation_pct: number;
  status: string;
}

interface BidComparisonChartProps {
  bidTotals: BidTotal[];
  budgetTotal: number;
  currency: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

const CHART_PADDING_TOP = 40;
const CHART_PADDING_BOTTOM = 80;
const CHART_PADDING_LEFT = 80;
const CHART_PADDING_RIGHT = 24;
const BAR_GAP_RATIO = 0.3;
const MIN_CHART_HEIGHT = 300;
const TICK_COUNT = 5;

function formatCompact(amount: number, currency: string): string {
  if (amount >= 1_000_000) {
    return `${(amount / 1_000_000).toFixed(1)}M ${currency}`;
  }
  if (amount >= 1_000) {
    return `${(amount / 1_000).toFixed(0)}K ${currency}`;
  }
  return `${amount.toFixed(0)} ${currency}`;
}

function formatFull(amount: number, currency: string): string {
  const safe = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: safe,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${safe}`;
  }
}

function getBarColor(
  total: number,
  lowestTotal: number,
  highestTotal: number,
  bidCount: number,
): string {
  if (bidCount <= 1) return 'var(--color-oe-blue, #3b82f6)';
  if (total === lowestTotal) return 'var(--oe-success, #15803d)';
  if (total === highestTotal) return 'var(--oe-error, #dc2626)';
  return 'var(--color-oe-blue, #3b82f6)';
}

function niceNum(range: number, round: boolean): number {
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / Math.pow(10, exponent);
  let niceFraction: number;
  if (round) {
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
  } else {
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
  }
  return niceFraction * Math.pow(10, exponent);
}

function computeYAxis(maxValue: number): { min: number; max: number; step: number } {
  if (maxValue <= 0) return { min: 0, max: 100, step: 20 };
  const range = niceNum(maxValue * 1.15, false);
  const step = niceNum(range / TICK_COUNT, true);
  const max = Math.ceil(maxValue * 1.15 / step) * step;
  return { min: 0, max, step };
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function BidComparisonChart({
  bidTotals,
  budgetTotal,
  currency,
}: BidComparisonChartProps) {
  const { t } = useTranslation();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [svgWidth, setSvgWidth] = useState(600);

  const containerNodeRef = useRef<HTMLDivElement | null>(null);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    containerNodeRef.current = node;
    if (node) setSvgWidth(node.clientWidth);
  }, []);

  useEffect(() => {
    const node = containerNodeRef.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSvgWidth(entry.contentRect.width);
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const { lowestTotal, highestTotal, yAxis, chartArea, bars, budgetY } = useMemo(() => {
    const allValues = bidTotals.map((b) => b.total);
    const lowest = allValues.length > 0 ? Math.min(...allValues) : 0;
    const highest = allValues.length > 0 ? Math.max(...allValues) : 0;

    const maxVal = Math.max(highest, budgetTotal);
    const yAx = computeYAxis(maxVal);

    const area = {
      x: CHART_PADDING_LEFT,
      y: CHART_PADDING_TOP,
      width: svgWidth - CHART_PADDING_LEFT - CHART_PADDING_RIGHT,
      height: MIN_CHART_HEIGHT - CHART_PADDING_TOP - CHART_PADDING_BOTTOM,
    };

    const barCount = bidTotals.length;
    const totalBarWidth = barCount > 0 ? area.width / barCount : area.width;
    const barWidth = totalBarWidth * (1 - BAR_GAP_RATIO);
    const gapWidth = totalBarWidth * BAR_GAP_RATIO;

    const barsArr = bidTotals.map((bid, i) => {
      const barHeight = yAx.max > 0 ? (bid.total / yAx.max) * area.height : 0;
      return {
        x: area.x + i * totalBarWidth + gapWidth / 2,
        y: area.y + area.height - Math.max(barHeight, 0),
        width: Math.max(barWidth, 0),
        height: Math.max(barHeight, 0),
        bid,
      };
    });

    const budgetYPos =
      yAx.max > 0
        ? area.y + area.height - (budgetTotal / yAx.max) * area.height
        : area.y + area.height;

    return {
      lowestTotal: lowest,
      highestTotal: highest,
      yAxis: yAx,
      chartArea: area,
      bars: barsArr,
      budgetY: budgetYPos,
    };
  }, [bidTotals, budgetTotal, svgWidth]);

  const yTicks = useMemo(() => {
    const ticks: number[] = [];
    for (let v = yAxis.min; v <= yAxis.max; v += yAxis.step) {
      ticks.push(v);
    }
    return ticks;
  }, [yAxis]);

  if (bidTotals.length === 0) {
    return null;
  }

  return (
    <div className="mb-4">
      <h5 className="text-xs font-semibold text-content-secondary uppercase tracking-wider mb-3">
        {t('tendering.bid_totals_chart', 'Bid Totals Overview')}
      </h5>
      <div ref={containerRef} className="w-full">
        <svg
          ref={svgRef}
          width={svgWidth}
          height={MIN_CHART_HEIGHT}
          className="select-none"
          role="img"
          aria-label={t('tendering.bid_comparison_chart_label', 'Bar chart comparing bid totals')}
        >
          {/* Y-axis grid lines and labels */}
          {yTicks.map((tick) => {
            const y =
              chartArea.y +
              chartArea.height -
              (yAxis.max > 0 ? (tick / yAxis.max) * chartArea.height : 0);
            return (
              <g key={tick}>
                <line
                  x1={chartArea.x}
                  y1={y}
                  x2={chartArea.x + chartArea.width}
                  y2={y}
                  stroke="var(--color-border-light, #e5e7eb)"
                  strokeWidth={1}
                />
                <text
                  x={chartArea.x - 8}
                  y={y + 4}
                  textAnchor="end"
                  className="text-[10px]"
                  fill="var(--color-content-tertiary, #9ca3af)"
                >
                  {formatCompact(tick, currency)}
                </text>
              </g>
            );
          })}

          {/* Budget reference line */}
          {budgetTotal > 0 && (
            <g>
              <line
                x1={chartArea.x}
                y1={budgetY}
                x2={chartArea.x + chartArea.width}
                y2={budgetY}
                stroke="var(--oe-warning, #f59e0b)"
                strokeWidth={1.5}
                strokeDasharray="6 4"
              />
              <text
                x={chartArea.x + chartArea.width + 2}
                y={budgetY - 6}
                className="text-[10px] font-medium"
                fill="var(--oe-warning, #f59e0b)"
                textAnchor="end"
              >
                {t('tendering.budget', 'Budget')}
              </text>
            </g>
          )}

          {/* Bars */}
          {bars.map((bar, i) => {
            const color = getBarColor(
              bar.bid.total,
              lowestTotal,
              highestTotal,
              bidTotals.length,
            );
            const isHovered = hoveredIndex === i;
            return (
              <g
                key={bar.bid.bid_id}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex(null)}
                className="cursor-pointer"
              >
                {/* Bar */}
                <rect
                  x={bar.x}
                  y={bar.y}
                  width={bar.width}
                  height={Math.max(bar.height, 1)}
                  rx={3}
                  fill={color}
                  opacity={isHovered ? 1 : 0.85}
                  className="transition-opacity duration-150"
                />

                {/* Deviation label above bar */}
                <text
                  x={bar.x + bar.width / 2}
                  y={bar.y - 8}
                  textAnchor="middle"
                  className="text-[10px] font-semibold"
                  fill={
                    bar.bid.deviation_pct < -0.1
                      ? 'var(--oe-success, #15803d)'
                      : bar.bid.deviation_pct > 0.1
                        ? 'var(--oe-error, #dc2626)'
                        : 'var(--color-content-tertiary, #9ca3af)'
                  }
                >
                  {bar.bid.deviation_pct > 0 ? '+' : ''}
                  {bar.bid.deviation_pct.toFixed(1)}%
                </text>

                {/* Company name on X axis */}
                <text
                  x={bar.x + bar.width / 2}
                  y={chartArea.y + chartArea.height + 16}
                  textAnchor="middle"
                  className="text-[11px] font-medium"
                  fill="var(--color-content-primary, #1f2937)"
                >
                  {bar.bid.company_name.length > 14
                    ? `${bar.bid.company_name.slice(0, 12)}...`
                    : bar.bid.company_name}
                </text>

                {/* Hover tooltip */}
                {isHovered && (
                  <g>
                    <rect
                      x={bar.x + bar.width / 2 - 70}
                      y={bar.y - 44}
                      width={140}
                      height={28}
                      rx={6}
                      fill="var(--color-surface-primary, #ffffff)"
                      stroke="var(--color-border, #d1d5db)"
                      strokeWidth={1}
                      filter="drop-shadow(0 2px 4px rgba(0,0,0,0.08))"
                    />
                    <text
                      x={bar.x + bar.width / 2}
                      y={bar.y - 26}
                      textAnchor="middle"
                      className="text-[11px] font-semibold"
                      fill="var(--color-content-primary, #1f2937)"
                    >
                      {formatFull(bar.bid.total, bar.bid.currency)}
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {/* X-axis base line */}
          <line
            x1={chartArea.x}
            y1={chartArea.y + chartArea.height}
            x2={chartArea.x + chartArea.width}
            y2={chartArea.y + chartArea.height}
            stroke="var(--color-border, #d1d5db)"
            strokeWidth={1}
          />

          {/* Legend */}
          <g transform={`translate(${chartArea.x}, ${MIN_CHART_HEIGHT - 20})`}>
            {bidTotals.length > 1 && (
              <>
                <rect x={0} y={0} width={10} height={10} rx={2} fill="var(--oe-success, #15803d)" />
                <text
                  x={14}
                  y={9}
                  className="text-[10px]"
                  fill="var(--color-content-secondary, #6b7280)"
                >
                  {t('tendering.lowest', 'Lowest')}
                </text>
                <rect x={60} y={0} width={10} height={10} rx={2} fill="var(--oe-error, #dc2626)" />
                <text
                  x={74}
                  y={9}
                  className="text-[10px]"
                  fill="var(--color-content-secondary, #6b7280)"
                >
                  {t('tendering.highest', 'Highest')}
                </text>
                <rect x={130} y={0} width={10} height={10} rx={2} fill="var(--color-oe-blue, #3b82f6)" />
                <text
                  x={144}
                  y={9}
                  className="text-[10px]"
                  fill="var(--color-content-secondary, #6b7280)"
                >
                  {t('tendering.other', 'Other')}
                </text>
              </>
            )}
            {budgetTotal > 0 && (
              <g transform={`translate(${bidTotals.length > 1 ? 200 : 0}, 0)`}>
                <line
                  x1={0}
                  y1={5}
                  x2={20}
                  y2={5}
                  stroke="var(--oe-warning, #f59e0b)"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                />
                <text
                  x={24}
                  y={9}
                  className="text-[10px]"
                  fill="var(--color-content-secondary, #6b7280)"
                >
                  {t('tendering.budget_line', 'Budget')}
                </text>
              </g>
            )}
          </g>
        </svg>
      </div>
    </div>
  );
}
