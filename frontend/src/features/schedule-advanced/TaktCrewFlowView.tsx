// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Takt Crew Flow view.
 *
 * Crew-centric counterpart to the line-of-balance chart. Y-axis = trades
 * (crews), X-axis = working days. Each crew's bar shows it cycling through
 * locations over time — the colour encodes the location, so the eye reads
 * the "train" of one crew marching down the building. Rhythm breaks are
 * outlined amber. Pure SVG.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import type { LineOfBalance, LineOfBalanceBar } from './api';

const LOC_PALETTE = [
  '#2563eb',
  '#059669',
  '#dc2626',
  '#d97706',
  '#7c3aed',
  '#0891b2',
  '#db2777',
  '#64748b',
];

interface Props {
  lob: LineOfBalance;
}

export function TaktCrewFlowView({ lob }: Props) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<LineOfBalanceBar | null>(null);

  const colorForLocation = useMemo(() => {
    const orders = Array.from(new Set(lob.bars.map((b) => b.sequence_order))).sort((a, b) => a - b);
    const map = new Map<number, string>();
    orders.forEach((o, i) => map.set(o, LOC_PALETTE[i % LOC_PALETTE.length]!));
    return (order: number) => map.get(order) ?? LOC_PALETTE[0]!;
  }, [lob.bars]);

  // Trades (crews) along the y-axis, in first-seen order.
  const crews = useMemo(() => {
    const seen = new Map<string, { id: string; name: string }>();
    for (const b of lob.bars) {
      if (!seen.has(b.activity_id)) seen.set(b.activity_id, { id: b.activity_id, name: b.activity_name });
    }
    return Array.from(seen.values());
  }, [lob.bars]);

  const locationLegend = useMemo(() => {
    const seen = new Map<number, { name: string; color: string }>();
    for (const b of lob.bars) {
      if (!seen.has(b.sequence_order)) {
        seen.set(b.sequence_order, { name: b.location_name, color: colorForLocation(b.sequence_order) });
      }
    }
    return Array.from(seen.entries()).sort((a, b) => a[0] - b[0]);
  }, [lob.bars, colorForLocation]);

  if (lob.bars.length === 0) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-8 text-center text-sm text-content-tertiary">
        {t('takt.no_lob', {
          defaultValue: 'No line-of-balance data yet. Add locations and activities, then compute.',
        })}
      </div>
    );
  }

  const padLeft = 120;
  const padTop = 24;
  const padBottom = 36;
  const rowH = 40;
  const barH = 18;
  const makespan = Math.max(1, lob.total_makespan_days);
  const plotW = 720;
  const chartW = padLeft + plotW + 24;
  const chartH = padTop + crews.length * rowH + padBottom;
  const dayToX = (d: number) => padLeft + (d / makespan) * plotW;
  const crewRow = new Map(crews.map((c, i) => [c.id, i]));

  const step = Math.max(1, Math.ceil(makespan / 8));
  const ticks: number[] = [];
  for (let d = 0; d <= makespan; d += step) ticks.push(d);
  if (ticks[ticks.length - 1] !== makespan) ticks.push(makespan);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="text-content-tertiary">{t('takt.location', { defaultValue: 'Location' })}:</span>
        {locationLegend.map(([order, { name, color }]) => (
          <span key={order} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 rounded-sm" style={{ backgroundColor: color }} aria-hidden />
            {name}
          </span>
        ))}
      </div>

      <div className="relative overflow-x-auto rounded-lg border border-border-light bg-surface-primary p-2">
        <svg
          width={chartW}
          height={chartH}
          role="img"
          aria-label={t('takt.crewflow_aria', { defaultValue: 'Takt crew flow diagram' })}
          className="min-w-full"
        >
          {ticks.map((d) => (
            <g key={`tick-${d}`}>
              <line
                x1={dayToX(d)}
                y1={padTop}
                x2={dayToX(d)}
                y2={chartH - padBottom}
                stroke="currentColor"
                className="text-border-light"
                strokeWidth={1}
              />
              <text
                x={dayToX(d)}
                y={chartH - padBottom + 16}
                textAnchor="middle"
                className="fill-content-tertiary text-[10px]"
              >
                D{d}
              </text>
            </g>
          ))}

          {crews.map((crew, i) => {
            const y = padTop + i * rowH;
            return (
              <text
                key={crew.id}
                x={padLeft - 10}
                y={y + rowH / 2 + 4}
                textAnchor="end"
                className="fill-content-secondary text-[11px] font-medium"
              >
                {crew.name}
              </text>
            );
          })}

          {lob.bars.map((b, idx) => {
            const row = crewRow.get(b.activity_id) ?? 0;
            const y = padTop + row * rowH + (rowH - barH) / 2;
            const x = dayToX(b.start_day);
            const w = Math.max(2, dayToX(b.end_day) - x);
            const color = colorForLocation(b.sequence_order);
            return (
              <g
                key={`${b.activity_id}-${b.location_id}-${idx}`}
                onMouseEnter={() => setHover(b)}
                onMouseLeave={() => setHover((h) => (h === b ? null : h))}
                style={{ cursor: 'pointer' }}
              >
                <rect
                  x={x}
                  y={y}
                  width={w}
                  height={barH}
                  rx={3}
                  fill={color}
                  opacity={0.88}
                  stroke={b.has_rhythm_break ? '#f59e0b' : 'none'}
                  strokeWidth={b.has_rhythm_break ? 2 : 0}
                  strokeDasharray={b.has_rhythm_break ? '3 3' : undefined}
                />
              </g>
            );
          })}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute left-2 top-2 z-10 rounded-md border border-border-light bg-surface-primary px-3 py-2 text-xs shadow-md"
            role="status"
          >
            <div className="font-semibold text-content-primary">{hover.activity_name}</div>
            <div className="text-content-secondary">{hover.location_name}</div>
            <div className="mt-1 text-content-tertiary tabular-nums">
              {t('takt.day_range', {
                start: hover.start_day,
                end: hover.end_day,
                defaultValue: 'Day {{start}} → {{end}}',
              })}
            </div>
            <div className="text-content-tertiary tabular-nums">
              {t('takt.crew_size', { defaultValue: 'Crew' })}: {hover.crew_size}
            </div>
            {hover.has_rhythm_break && (
              <div className="mt-1 inline-flex items-center gap-1 text-amber-600">
                <AlertTriangle size={11} />
                {t('takt.rhythmBreak', { defaultValue: 'Takt rhythm break' })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
