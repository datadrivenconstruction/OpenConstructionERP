// PPC trend and variance Pareto​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Percent plan complete per week as bars with the average as a dashed line,
 * and the Pareto of reasons for variance: bars by count and a cumulative
 * percent line. Plain SVG, no chart dependency.
 */
import { useTranslation } from 'react-i18next';
import { Card, Skeleton } from '@/shared/ui';
import { usePpcHistory, type LpsParetoRow, type LpsPpcWeek } from './api';
import { LpsValidationPanel } from './LpsValidationPanel';

const W = 320;
const H = 140;
const PAD = { l: 28, r: 28, t: 8, b: 20 };

function num(v: string | null | undefined): number {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

const RNC_EN: Record<string, string> = {
  manpower: 'Manpower',
  material: 'Material',
  equipment: 'Equipment',
  info: 'Information',
  weather: 'Weather',
  predecessor: 'Predecessor',
  changes: 'Changes',
  quality: 'Quality',
  other: 'Other',
};

export function PpcTrendChart({ weeks, average }: { weeks: LpsPpcWeek[]; average: string | null }) {
  const { t } = useTranslation();
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const slot = weeks.length > 0 ? plotW / weeks.length : plotW;
  const y = (pct: number) => PAD.t + plotH - (Math.min(Math.max(pct, 0), 100) / 100) * plotH;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <h4 className="text-xs font-semibold text-content-secondary">
          {t('schedule_advanced.ppc_trend_title', { defaultValue: 'PPC per week' })}
        </h4>
        {average != null && (
          <span className="text-xs text-content-secondary" data-testid="ppc-average">
            {t('schedule_advanced.ppc_average', { defaultValue: 'Average {{value}}%', value: num(average).toFixed(0) })}
          </span>
        )}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={t('schedule_advanced.ppc_trend_title', { defaultValue: 'PPC per week' })}
      >
        {[0, 50, 100].map((g) => (
          <g key={g}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(g)} y2={y(g)} stroke="currentColor" className="text-border-light" strokeWidth="0.5" />
            <text x={PAD.l - 4} y={y(g) + 3} textAnchor="end" fontSize="8" fill="currentColor" className="text-content-tertiary">
              {g}
            </text>
          </g>
        ))}
        {weeks.map((w, i) => {
          const v = w.ppc_percent == null ? null : num(w.ppc_percent);
          const x = PAD.l + i * slot + slot * 0.15;
          return (
            <g key={w.week_plan_id}>
              {v != null && (
                <rect
                  data-testid="ppc-bar"
                  x={x}
                  y={y(v)}
                  width={slot * 0.7}
                  height={PAD.t + plotH - y(v)}
                  fill="currentColor"
                  className="text-oe-blue"
                  rx="1"
                >
                  <title>{`${w.week_start_date}: ${v.toFixed(0)}%`}</title>
                </rect>
              )}
              <text x={x + slot * 0.35} y={H - 6} textAnchor="middle" fontSize="7" fill="currentColor" className="text-content-tertiary">
                {w.week_start_date.slice(5)}
              </text>
            </g>
          );
        })}
        {average != null && (
          <line
            x1={PAD.l}
            x2={W - PAD.r}
            y1={y(num(average))}
            y2={y(num(average))}
            stroke="currentColor"
            className="text-semantic-warning"
            strokeWidth="1"
            strokeDasharray="4 3"
          />
        )}
      </svg>
    </div>
  );
}

export function VariancePareto({ rows }: { rows: LpsParetoRow[] }) {
  const { t } = useTranslation();
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const max = Math.max(1, ...rows.map((r) => r.count));
  const slot = rows.length > 0 ? plotW / rows.length : plotW;
  const yc = (c: number) => PAD.t + plotH - (c / max) * plotH;
  const yp = (p: number) => PAD.t + plotH - (Math.min(Math.max(p, 0), 100) / 100) * plotH;
  const points = rows
    .map((r, i) => `${(PAD.l + i * slot + slot / 2).toFixed(1)},${yp(num(r.cumulative_percent)).toFixed(1)}`)
    .join(' ');
  const catLabel = (c: string) => t(`schedule_advanced.rnc.${c}`, { defaultValue: RNC_EN[c] ?? c });
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold text-content-secondary">
        {t('schedule_advanced.pareto_title', { defaultValue: 'Reasons for variance' })}
      </h4>
      {rows.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('schedule_advanced.pareto_empty', { defaultValue: 'No missed commitments recorded yet.' })}
        </p>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            role="img"
            aria-label={t('schedule_advanced.pareto_title', { defaultValue: 'Reasons for variance' })}
          >
            {rows.map((r, i) => {
              const x = PAD.l + i * slot + slot * 0.15;
              return (
                <g key={r.category}>
                  <rect
                    data-testid="pareto-bar"
                    x={x}
                    y={yc(r.count)}
                    width={slot * 0.7}
                    height={PAD.t + plotH - yc(r.count)}
                    fill="currentColor"
                    className="text-oe-blue"
                    rx="1"
                  >
                    <title>{`${catLabel(r.category)}: ${r.count}`}</title>
                  </rect>
                  <text x={x + slot * 0.35} y={H - 6} textAnchor="middle" fontSize="7" fill="currentColor" className="text-content-tertiary">
                    {catLabel(r.category).slice(0, 8)}
                  </text>
                </g>
              );
            })}
            <polyline
              data-testid="pareto-line"
              points={points}
              fill="none"
              stroke="currentColor"
              className="text-semantic-warning"
              strokeWidth="1.5"
            />
          </svg>
          <ul className="mt-1 space-y-0.5 text-2xs text-content-secondary">
            {rows.map((r) => (
              <li key={r.category} data-testid="pareto-row">
                {t('schedule_advanced.pareto_row', {
                  defaultValue: '{{category}}: {{count}} ({{percent}}%, cumulative {{cumulative}}%)',
                  category: catLabel(r.category),
                  count: r.count,
                  percent: num(r.percent).toFixed(0),
                  cumulative: num(r.cumulative_percent).toFixed(0),
                })}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function PpcPanel({ masterId }: { masterId: string }) {
  const { t } = useTranslation();
  const q = usePpcHistory(masterId);
  return (
    <div className="space-y-4">
      <Card padding="md">
        <h3 className="mb-3 text-sm font-semibold text-content-primary">
          {t('schedule_advanced.ppc_history_title', { defaultValue: 'Plan reliability' })}
        </h3>
        {q.isLoading ? (
          <Skeleton height={120} />
        ) : q.isError || !q.data ? (
          <p className="text-xs text-content-tertiary">
            {t('schedule_advanced.ppc_error', { defaultValue: 'PPC history could not be loaded.' })}
          </p>
        ) : q.data.weeks.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('schedule_advanced.ppc_empty', { defaultValue: 'PPC appears once a weekly plan is closed.' })}
          </p>
        ) : (
          <div className="grid gap-6 md:grid-cols-2">
            <PpcTrendChart weeks={q.data.weeks} average={q.data.average_ppc} />
            <VariancePareto rows={q.data.pareto} />
          </div>
        )}
      </Card>
      <LpsValidationPanel masterId={masterId} />
    </div>
  );
}
