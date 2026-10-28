// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Line-of-Balance (LOB) chart.
 *
 * X-axis = working days (time), Y-axis = location sequence (top-to-bottom).
 * Each (activity, location) renders as a diagonal bar — the slope is the
 * crew production rate. Bars of the same trade share a colour; the critical
 * trade is drawn bold; activities with an observed rhythm break get an
 * amber dashed outline. Pure SVG, no chart library.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import type { LineOfBalance, LineOfBalanceBar } from './api';

const PALETTE = [
  '#2563eb', // blue
  '#64748b', // slate
  '#d97706', // amber
  '#059669', // emerald
  '#7c3aed', // violet
  '#dc2626', // red
  '#0891b2', // cyan
  '#db2777', // pink
];

interface Props {
  lob: LineOfBalance;
}

function fmtDay(day: number): string {
  return `D${day}`;
}

export function LineOfBalanceView({ lob }: Props) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<LineOfBalanceBar | null>(null);

  // Stable colour per activity name.
  const colorFor = useMemo(() => {
    const names = Array.from(new Set(lob.bars.map((b) => b.activity_name)));
    const map = new Map<string, string>();
    names.forEach((n, i) => map.set(n, PALETTE[i % PALETTE.length]!));
    return (name: string) => map.get(name) ?? PALETTE[0]!;
  }, [lob.bars]);

  const locations = useMemo(() => {
    const seen = new Map<string, { id: string; name: string; order: number }>();
    for (const b of lob.bars) {
      if (!seen.has(b.location_id)) {
        seen.set(b.location_id, {
          id: b.location_id,
          name: b.location_name,
          order: b.sequence_order,
        });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.order - b.order);
  }, [lob.bars]);

  const legend = useMemo(() => {
    const seen = new Map<string, string>();
    for (const b of lob.bars) {
      if (!seen.has(b.activity_name)) seen.set(b.activity_name, colorFor(b.activity_name));
    }
    return Array.from(seen.entries());
  }, [lob.bars, colorFor]);

  if (lob.bars.length === 0) {
    return (
      <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-8 text-center text-sm text-content-tertiary">
        {t('takt.no_lob', {
          defaultValue: 'No line-of-balance data yet. Add locations and activities, then compute.',
        })}
      </div>
    );
  }

  // ── Geometry ──────────────────────────────────────────────────────────
  const padLeft = 96;
  const padTop = 28;
  const padBottom = 36;
  const rowH = 46;
  const makespan = Math.max(1, lob.total_makespan_days);
  const plotW = 720;
  const chartW = padLeft + plotW + 24;
  const chartH = padTop + locations.length * rowH + padBottom;
  const dayToX = (d: number) => padLeft + (d / makespan) * plotW;
  const orderToRow = new Map(locations.map((l, i) => [l.order, i]));

  // Gridlines roughly every ~makespan/8 days.
  const step = Math.max(1, Math.ceil(makespan / 8));
  const ticks: number[] = [];
  for (let d = 0; d <= makespan; d += step) ticks.push(d);
  if (ticks[ticks.length - 1] !== makespan) ticks.push(makespan);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {legend.map(([name, color]) => (
          <span key={name} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-4 rounded-sm"
              style={{ backgroundColor: color }}
              aria-hidden
            />
            {name}
          </span>
        ))}
        {lob.critical_path.length > 0 && (
          <span className="inline-flex items-center gap-1.5 text-content-secondary">
            <span className="inline-block h-1 w-5 rounded-sm bg-rose-500" aria-hidden />
            {t('takt.critical_path', { defaultValue: 'Critical trade' })}
          </span>
        )}
      </div>

      <div className="relative overflow-x-auto rounded-lg border border-border-light bg-surface-primary p-2">
        <svg
          width={chartW}
          height={chartH}
          role="img"
          aria-label={t('takt.lob_aria', { defaultValue: 'Line-of-balance diagram' })}
          className="min-w-full"
        >
          {/* vertical gridlines + day labels */}
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
                {fmtDay(d)}
              </text>
            </g>
          ))}

          {/* location rows + labels */}
          {locations.map((loc, i) => {
            const y = padTop + i * rowH;
            return (
              <g key={loc.id}>
                <line
                  x1={padLeft}
                  y1={y + rowH}
                  x2={padLeft + plotW}
                  y2={y + rowH}
                  stroke="currentColor"
                  className="text-border-light"
                  strokeWidth={1}
                />
                <text
                  x={padLeft - 10}
                  y={y + rowH / 2 + 4}
                  textAnchor="end"
                  className="fill-content-secondary text-[11px] font-medium"
                >
                  {loc.name}
                </text>
              </g>
            );
          })}

          {/* diagonal bars */}
          {lob.bars.map((b, idx) => {
            const row = orderToRow.get(b.sequence_order) ?? 0;
            const yTop = padTop + row * rowH + 8;
            const yBot = padTop + row * rowH + rowH - 8;
            const x1 = dayToX(b.start_day);
            const x2 = dayToX(b.end_day);
            const color = colorFor(b.activity_name);
            return (
              <g
                key={`${b.activity_id}-${b.location_id}-${idx}`}
                onMouseEnter={() => setHover(b)}
                onMouseLeave={() => setHover((h) => (h === b ? null : h))}
                style={{ cursor: 'pointer' }}
              >
                {/* the diagonal sweep: start at top-left of the cell, end bottom-right */}
                <line
                  x1={x1}
                  y1={yTop}
                  x2={x2}
                  y2={yBot}
                  stroke={color}
                  strokeWidth={b.is_critical ? 5 : 3}
                  strokeLinecap="round"
                  opacity={0.9}
                />
                {b.has_rhythm_break && (
                  <line
                    x1={x1}
                    y1={yTop}
                    x2={x2}
                    y2={yBot}
                    stroke="#f59e0b"
                    strokeWidth={1.5}
                    strokeDasharray="3 3"
                    strokeLinecap="round"
                  />
                )}
                <circle cx={x1} cy={yTop} r={3} fill={color} />
                <circle cx={x2} cy={yBot} r={3} fill={color} />
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
