// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MatchAnalyticsCard — §10 production observability dashboard for the
// match-elements page. Reads from /api/v1/match_elements/analytics and
// renders:
//
//   * KPI tiles  — searches, pick rate, mean score, p95 latency
//   * Alerts     — §10 thresholds (low score, picked-rank>4, zero-hit
//                  with hard filter); auto-hidden when sample size is
//                  too small to be meaningful
//   * Breakdowns — by country, source_type, ifc_class (top-N by volume)
//   * Histograms — relax tier + confidence band distributions
//
// Renders nothing on auth-fail / 0-row windows (lets the page stay clean
// on a fresh deploy). Collapsed by default — expand for drill-down.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  ChevronUp,
  Loader2,
  TrendingUp,
  XOctagon,
} from 'lucide-react';

import {
  matchElementsApi,
  type AnalyticsAlert,
  type AnalyticsBreakdown,
  type MatchAnalyticsResponse,
} from './api';
import { fmtPercent, fmtFixed, getIntlLocale } from '@/shared/lib/formatters';

const WINDOW_OPTIONS = [1, 7, 30, 90] as const;

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return fmtPercent(v * 100);
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—';
  return fmtFixed(v, digits);
}

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `${Math.round(v)} ms`;
}

function Tile({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'neutral' | 'positive' | 'warning' | 'critical';
}) {
  const toneClass = {
    neutral: 'border-border bg-surface-primary',
    positive: 'border-emerald-300/70 dark:border-emerald-800/70 bg-emerald-50/40 dark:bg-emerald-950/20',
    warning: 'border-amber-300/70 dark:border-amber-700/70 bg-amber-50/40 dark:bg-amber-950/20',
    critical: 'border-red-300/70 dark:border-red-800/70 bg-red-50/40 dark:bg-red-950/20',
  }[tone];
  return (
    <div className={`rounded-lg border ${toneClass} px-3 py-2`}>
      <div className="text-[11px] uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="text-lg font-semibold text-content-primary leading-tight">{value}</div>
      {hint && <div className="text-[11px] text-content-tertiary mt-0.5">{hint}</div>}
    </div>
  );
}

function AlertRow({ alert }: { alert: AnalyticsAlert }) {
  const isCritical = alert.severity === 'critical';
  const Icon = isCritical ? XOctagon : AlertTriangle;
  const tone = isCritical
    ? 'border-red-300 dark:border-red-800 bg-red-50/70 dark:bg-red-950/30 text-red-900 dark:text-red-100'
    : 'border-amber-300 dark:border-amber-700 bg-amber-50/70 dark:bg-amber-950/30 text-amber-900 dark:text-amber-100';
  return (
    <div className={`rounded-lg border px-3 py-2 flex items-start gap-2 ${tone}`}>
      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold leading-tight">{alert.title}</div>
        <div className="text-[12px] mt-0.5">{alert.detail}</div>
        <div className="text-[11px] mt-1 opacity-80">
          {fmtPct(alert.metric)} ≥ {fmtPct(alert.threshold)} · {alert.spec_ref}
        </div>
      </div>
    </div>
  );
}

function BreakdownTable({
  rows,
  caption,
  emptyLabel,
}: {
  rows: AnalyticsBreakdown[];
  caption: string;
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return (
      <div>
        <div className="text-[11px] uppercase tracking-wide text-content-tertiary mb-1">
          {caption}
        </div>
        <div className="text-xs text-content-tertiary italic">{emptyLabel}</div>
      </div>
    );
  }
  const max = Math.max(...rows.map((r) => r.searches));
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-content-tertiary mb-1">
        {caption}
      </div>
      <div className="space-y-1">
        {rows.map((r) => {
          const pct = max > 0 ? (r.searches / max) * 100 : 0;
          return (
            <div key={r.key} className="flex items-center gap-2 text-xs">
              <div className="w-24 shrink-0 truncate text-content-secondary" title={r.key}>
                {r.key}
              </div>
              <div className="flex-1 relative h-4 rounded bg-surface-tertiary overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 bg-sky-400/70 dark:bg-sky-500/60"
                  style={{ width: `${pct}%` }}
                />
                <div className="absolute inset-0 flex items-center justify-end pr-1.5 text-[10.5px] font-medium text-content-primary">
                  {r.searches}
                </div>
              </div>
              <div className="w-16 text-right text-content-tertiary tabular-nums">
                {fmtNum(r.mean_score, 2)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Histogram({
  data,
  caption,
}: {
  data: Record<string, number>;
  caption: string;
}) {
  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) {
    return null;
  }
  const max = Math.max(...entries.map(([, v]) => v));
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-content-tertiary mb-1">
        {caption}
      </div>
      <div className="flex items-end gap-1 h-16">
        {entries.map(([k, v]) => {
          const h = max > 0 ? (v / max) * 100 : 0;
          return (
            <div key={k} className="flex-1 flex flex-col items-center justify-end gap-0.5">
              <div className="text-[10px] tabular-nums text-content-tertiary">{v}</div>
              <div
                className="w-full rounded-t bg-indigo-400/70 dark:bg-indigo-500/60"
                style={{ height: `${Math.max(2, h)}%` }}
              />
              <div className="text-[10px] text-content-secondary">{k}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface MatchAnalyticsCardProps {
  /** Optional — scopes the dashboard to a single project. Omit for tenant-wide rollup. */
  projectId?: string | null;
}

export function MatchAnalyticsCard({ projectId }: MatchAnalyticsCardProps) {
  const { t } = useTranslation();
  const [days, setDays] = useState<number>(7);
  const [open, setOpen] = useState(false);

  const q = useQuery<MatchAnalyticsResponse>({
    queryKey: ['match-analytics', projectId ?? null, days],
    queryFn: () => matchElementsApi.getAnalytics({ project_id: projectId ?? null, days }),
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  });

  if (q.isLoading) {
    return (
      <div
        className="rounded-xl border border-border bg-surface-primary px-3 py-2 text-xs text-content-tertiary inline-flex items-center gap-2"
        role="status"
        aria-live="polite"
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        {t('match_elements.analytics_loading', 'Loading match analytics…')}
      </div>
    );
  }

  // Soft-fail: don't block the page on analytics being unreachable.
  if (q.isError || !q.data) return null;

  const data = q.data;
  const empty = data.total_searches === 0;
  const headerTone = data.alerts.some((a) => a.severity === 'critical')
    ? 'border-red-300 dark:border-red-800 bg-red-50/40 dark:bg-red-950/20'
    : data.alerts.length > 0
      ? 'border-amber-300 dark:border-amber-700 bg-amber-50/40 dark:bg-amber-950/20'
      : 'border-border bg-surface-primary';

  const headlinePickRate = empty ? '—' : fmtPct(data.pick_rate);
  const headlineMeanScore = empty ? '—' : fmtNum(data.mean_top_score, 2);

  return (
    <div className={`rounded-xl border ${headerTone}`}>
      <div className="w-full flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 flex items-center gap-2.5 text-left min-w-0"
          aria-expanded={open}
        >
          <span className="shrink-0 w-6 h-6 rounded-md bg-sky-500 text-white inline-flex items-center justify-center">
            <BarChart3 className="w-3.5 h-3.5" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-content-primary leading-tight">
              {t('match_elements.analytics_title', 'Match analytics')}
              {data.alerts.length > 0 && (
                <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-200 text-amber-900 dark:bg-amber-800 dark:text-amber-100">
                  <AlertTriangle className="w-2.5 h-2.5" />
                  {t('match_elements.analytics_alerts_count', '{{n}} alert', {
                    n: data.alerts.length,
                    count: data.alerts.length,
                  })}
                </span>
              )}
            </div>
            <div className="text-[11px] text-content-tertiary truncate">
              {empty
                ? t(
                    'match_elements.analytics_empty_caption',
                    'No searches yet in the last {{days}}d window - run /match-elements to populate.',
                    { days: data.window_days },
                  )
                : t(
                    'match_elements.analytics_caption',
                    '{{n}} searches · {{picks}} picks · pick rate {{rate}} · mean score {{score}} · last {{days}}d',
                    {
                      n: data.total_searches,
                      picks: data.total_with_pick,
                      rate: headlinePickRate,
                      score: headlineMeanScore,
                      days: data.window_days,
                    },
                  )}
            </div>
          </div>
        </button>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="shrink-0 text-xs rounded border border-border bg-surface-primary px-2 py-1 text-content-primary"
          aria-label={t('match_elements.analytics_window_label', 'Window')}
        >
          {WINDOW_OPTIONS.map((d) => (
            <option key={d} value={d}>
              {t('match_elements.analytics_window_days', '{{n}}d', { n: d })}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={
            open
              ? t('match_elements.analytics_collapse', 'Collapse analytics')
              : t('match_elements.analytics_expand', 'Expand analytics')
          }
          aria-expanded={open}
          className="shrink-0 p-1 text-content-tertiary hover:text-content-primary"
        >
          {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {open && (
        <div className="px-3 pb-3 space-y-3 border-t border-border/60 pt-3">
          {data.alerts.length > 0 && (
            <div className="space-y-1.5">
              {data.alerts.map((a) => (
                <AlertRow key={a.id} alert={a} />
              ))}
            </div>
          )}

          {!empty && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Tile
                  label={t('match_elements.analytics_tile_searches', 'Searches')}
                  value={String(data.total_searches)}
                  hint={t(
                    'match_elements.analytics_tile_searches_hint',
                    'last {{days}}d',
                    { days: data.window_days },
                  )}
                />
                <Tile
                  label={t('match_elements.analytics_tile_pick_rate', 'Pick rate')}
                  value={fmtPct(data.pick_rate)}
                  hint={t(
                    'match_elements.analytics_tile_pick_rate_hint',
                    '{{n}} picks',
                    { n: data.total_with_pick },
                  )}
                  tone={data.pick_rate >= 0.5 ? 'positive' : 'neutral'}
                />
                <Tile
                  label={t('match_elements.analytics_tile_score', 'Mean score')}
                  value={fmtNum(data.mean_top_score, 2)}
                  hint={t(
                    'match_elements.analytics_tile_score_hint',
                    'p95 {{p}}',
                    { p: fmtNum(data.p95_top_score, 2) },
                  )}
                  tone={
                    data.low_score_pct >= 0.2
                      ? 'warning'
                      : (data.mean_top_score ?? 0) >= 0.6
                        ? 'positive'
                        : 'neutral'
                  }
                />
                <Tile
                  label={t('match_elements.analytics_tile_latency', 'Latency p95')}
                  value={fmtMs(data.p95_took_ms)}
                  hint={t(
                    'match_elements.analytics_tile_latency_hint',
                    'mean {{m}}',
                    { m: fmtMs(data.mean_took_ms) },
                  )}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Tile
                  label={t('match_elements.analytics_tile_low_score', 'Low score (<0.3)')}
                  value={fmtPct(data.low_score_pct)}
                  tone={data.low_score_pct >= 0.2 ? 'warning' : 'neutral'}
                />
                <Tile
                  label={t('match_elements.analytics_tile_zero_hit', 'Zero-hit')}
                  value={fmtPct(data.zero_hit_pct)}
                  tone={data.zero_hit_pct >= 0.1 ? 'warning' : 'neutral'}
                />
                <Tile
                  label={t('match_elements.analytics_tile_pick_above_4', 'Picks at rank > 4')}
                  value={fmtPct(data.high_picked_rank_pct)}
                  hint={t(
                    'match_elements.analytics_tile_pick_above_4_hint',
                    'mean rank {{r}}',
                    { r: fmtNum(data.mean_picked_rank, 1) },
                  )}
                  tone={data.high_picked_rank_pct >= 0.2 ? 'warning' : 'neutral'}
                />
                <Tile
                  label={t('match_elements.analytics_tile_rerank', 'BGE rerank')}
                  value={fmtPct(data.bge_rerank_pct)}
                  hint={
                    data.llm_rerank_pct > 0
                      ? t(
                          'match_elements.analytics_tile_rerank_llm_hint',
                          'LLM rerank {{p}}',
                          { p: fmtPct(data.llm_rerank_pct) },
                        )
                      : undefined
                  }
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Histogram
                  data={data.relax_tier_distribution}
                  caption={t(
                    'match_elements.analytics_hist_tier',
                    'Relax tier distribution',
                  )}
                />
                <Histogram
                  data={data.confidence_band_distribution}
                  caption={t(
                    'match_elements.analytics_hist_band',
                    'Confidence band distribution',
                  )}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <BreakdownTable
                  rows={data.by_country}
                  caption={t('match_elements.analytics_by_country', 'By country')}
                  emptyLabel={t(
                    'match_elements.analytics_breakdown_empty',
                    'no data',
                  )}
                />
                <BreakdownTable
                  rows={data.by_source_type}
                  caption={t('match_elements.analytics_by_source', 'By source type')}
                  emptyLabel={t(
                    'match_elements.analytics_breakdown_empty',
                    'no data',
                  )}
                />
                <BreakdownTable
                  rows={data.by_ifc_class}
                  caption={t('match_elements.analytics_by_ifc', 'By IFC class')}
                  emptyLabel={t(
                    'match_elements.analytics_breakdown_empty',
                    'no data',
                  )}
                />
              </div>

              <div className="text-[10.5px] text-content-tertiary inline-flex items-center gap-1">
                <TrendingUp className="w-3 h-3" />
                {t(
                  'match_elements.analytics_footer',
                  'Generated {{at}} · {{ref}}',
                  {
                    at: new Date(data.generated_at).toLocaleString(getIntlLocale()),
                    ref: 'MAPPING_PROCESS.md §10',
                  },
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
