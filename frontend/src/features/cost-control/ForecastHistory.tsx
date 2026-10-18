// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How the forecast moved: one point per saved forecast against the plan, and
// the list underneath with the change from the previous one. This is the part
// a client asks for in every cost meeting ("it was 1.97 million at the
// calculation, why is it 2.38 now?"), so it reads without opening anything.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Lock, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import { num, type SnapshotSummary } from './api';
import { snapshotStatusLabel, stageLabel } from './labels';

const H = 200;
const PAD_X = 56;
const PAD_TOP = 30;
const PAD_BOTTOM = 52;
/** Below this gap between two points the amounts would overlap, so only the dates are written. */
const MIN_LABEL_GAP = 96;

/** The drawing is laid out at the width it is shown at, so a wide page gets a wide chart, not a centred strip. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const w = Math.round(entry?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Chart({ points, currency }: { points: SnapshotSummary[]; currency: string }) {
  const { t } = useTranslation();
  const [ref, W] = useWidth(640);
  const forecasts = points.map((p) => num(p.totals.forecast));
  const plans = points.map((p) => num(p.totals.planned));
  const all = [...forecasts, ...plans].filter((v) => v > 0);
  if (points.length < 2 || all.length === 0) return null;
  const min = Math.min(...all) * 0.97;
  const max = Math.max(...all) * 1.03;
  const step = (W - 2 * PAD_X) / (points.length - 1);
  const x = (i: number) => PAD_X + i * step;
  const y = (v: number) => H - PAD_BOTTOM - ((v - min) / (max - min || 1)) * (H - PAD_TOP - PAD_BOTTOM);
  const line = (values: number[]) => values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ');
  const showAmounts = step >= MIN_LABEL_GAP;
  return (
    <figure className="mb-4">
      <div ref={ref} className="w-full">
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          className="block max-w-full"
          role="img"
          aria-label={t('cost_control.chart_label', { defaultValue: 'Forecast over time against the plan' })}
        >
          <path d={line(plans)} fill="none" strokeWidth={1.5} strokeDasharray="4 4" className="stroke-content-quaternary" />
          <path d={line(forecasts)} fill="none" strokeWidth={2.5} className="stroke-oe-blue" />
          {forecasts.map((v, i) => (
            <g key={points[i]!.id}>
              <circle cx={x(i)} cy={y(v)} r={4} className="fill-oe-blue">
                <title>{`${fmtDate(points[i]!.taken_on)}: ${fmtCurrency(v, currency)}`}</title>
              </circle>
              {showAmounts && (
                <text
                  x={x(i)}
                  // Below the plan the dashed line runs just above the point, so the amount goes underneath.
                  y={v < plans[i]! ? y(v) + 18 : y(v) - 10}
                  textAnchor="middle"
                  className="fill-content-primary text-[11px] font-semibold tabular-nums"
                >
                  {fmtCurrency(v, currency)}
                </text>
              )}
              <text x={x(i)} y={H - 10} textAnchor="middle" className="fill-content-tertiary text-[11px]">
                {fmtDate(points[i]!.taken_on, { day: '2-digit', month: 'short', year: 'numeric' })}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <figcaption className="flex gap-4 text-2xs text-content-tertiary">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-oe-blue" />
          {t('cost_control.col_forecast', { defaultValue: 'Forecast' })}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 border-t border-dashed border-content-quaternary" />
          {t('cost_control.col_planned', { defaultValue: 'Planned' })}
        </span>
      </figcaption>
    </figure>
  );
}

export interface ForecastHistoryProps {
  snapshots: SnapshotSummary[];
  currency: string;
  /** Whether the reader may delete a draft. A frozen snapshot is never deleted. */
  canDelete: boolean;
  onDelete: (id: string) => void;
  onOpen: (id: string) => void;
}

export function ForecastHistory({ snapshots, currency, canDelete, onDelete, onOpen }: ForecastHistoryProps) {
  const { t } = useTranslation();
  const [pendingDelete, setPendingDelete] = useState<SnapshotSummary | null>(null);
  const newestFirst = useMemo(() => [...snapshots].reverse(), [snapshots]);

  if (snapshots.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('cost_control.history_none', {
          defaultValue:
            'No forecast saved yet. Save one now and again every month: the saved forecasts show how the cost moved and why.',
        })}
      </p>
    );
  }

  return (
    <div>
      <Chart points={snapshots} currency={currency} />
      <ul className="divide-y divide-border-light">
        {newestFirst.map((s, i) => {
          const prev = newestFirst[i + 1];
          const delta = prev ? num(s.totals.forecast) - num(prev.totals.forecast) : null;
          return (
            <li key={s.id} className="flex items-center gap-3 py-2.5 text-sm">
              <span className="w-24 shrink-0 text-content-tertiary">{fmtDate(s.taken_on)}</span>
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 text-start text-content-primary hover:underline"
                onClick={() => onOpen(s.id)}
              >
                <span className="truncate">
                  {s.label || stageLabel(t, s.stage)}
                  {s.label && <span className="ml-2 text-xs text-content-tertiary">{stageLabel(t, s.stage)}</span>}
                </span>
                <span
                  className={`flex shrink-0 items-center gap-1 rounded px-1.5 py-px text-2xs font-medium ${
                    s.status === 'draft'
                      ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                      : 'bg-surface-secondary text-content-tertiary'
                  }`}
                >
                  {s.status !== 'draft' && <Lock size={10} />}
                  {snapshotStatusLabel(t, s.status)}
                </span>
                <ChevronRight size={14} className="shrink-0 text-content-quaternary" />
              </button>
              <span className="shrink-0 font-medium tabular-nums text-content-primary">
                {fmtCurrency(s.totals.forecast, currency)}
              </span>
              <span
                className={`w-28 shrink-0 text-right text-xs tabular-nums ${
                  delta === null || Math.abs(delta) < 0.005
                    ? 'text-content-tertiary'
                    : delta > 0
                      ? 'text-semantic-error'
                      : 'text-semantic-success'
                }`}
              >
                {delta === null ? '' : `${delta > 0 ? '+' : ''}${fmtCurrency(delta, currency)}`}
              </span>
              {canDelete && s.status === 'draft' && (
                <button
                  type="button"
                  className="shrink-0 rounded p-1 text-content-quaternary hover:text-semantic-error"
                  onClick={() => setPendingDelete(s)}
                  aria-label={t('cost_control.draft_delete', { defaultValue: 'Delete draft' })}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={!!pendingDelete}
        title={t('cost_control.draft_delete', { defaultValue: 'Delete draft' })}
        message={t('cost_control.draft_delete_confirm', {
          defaultValue: 'The draft of {{date}} and the reasons written on it are removed for everyone.',
          date: pendingDelete ? fmtDate(pendingDelete.taken_on) : '',
        })}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) onDelete(pendingDelete.id);
          setPendingDelete(null);
        }}
      />
    </div>
  );
}
