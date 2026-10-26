// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers and React Query hooks for the WIP report: the work-in-progress
 * schedule with over/under billing, closed month-end periods, forecast
 * overrides and the validation findings.
 *
 * Mounted at `/api/v1/wip-report`. Money and percents are decimal STRINGS on
 * the wire and stay strings here; arithmetic goes through BigInt, never floats.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut, apiDelete, downloadWithAuth } from '@/shared/lib/api';

export interface WipRow {
  project_id: string;
  project_name: string;
  currency: string;
  as_of: string;
  previous_period: string | null;
  original_contract_value: string;
  approved_changes: string;
  contract_value: string;
  estimated_cost: string;
  cost_to_date: string;
  cost_to_complete: string;
  percent_complete: string;
  percent_complete_raw: string;
  earned_revenue: string;
  billed_to_date: string;
  over_billing: string;
  under_billing: string;
  projected_gross_profit: string;
  projected_margin_pct: string;
  gross_profit_to_date: string;
  previous_gross_profit: string | null;
  /** Negative = fade, positive = gain; null without a closed period. */
  fade: string | null;
  backlog: string;
  loss_job: boolean;
  flags: string[];
  forecast_note: string;
  sources: Record<string, unknown>;
}

export interface WipTotals {
  currency: string;
  projects: number;
  contract_value: string;
  estimated_cost: string;
  cost_to_date: string;
  cost_to_complete: string;
  earned_revenue: string;
  billed_to_date: string;
  over_billing: string;
  under_billing: string;
  projected_gross_profit: string;
  fade: string;
  backlog: string;
  percent_complete: string;
}

export interface WipPortfolio {
  as_of: string;
  rows: WipRow[];
  totals: WipTotals[];
}

export interface WipPeriod {
  id: string;
  project_id: string;
  period: string;
  as_of: string;
  currency: string;
  contract_value: string;
  estimated_cost: string;
  cost_to_date: string;
  cost_to_complete: string;
  percent_complete: string;
  earned_revenue: string;
  billed_to_date: string;
  over_billing: string;
  under_billing: string;
  projected_gross_profit: string;
  gross_profit_to_date: string;
  backlog: string;
  notes: string | null;
  closed_by: string | null;
  created_at: string;
}

export interface WipForecast {
  estimated_cost: string | null;
  note: string;
}

export type WipSeverity = 'error' | 'warning' | 'info';

export interface WipFinding {
  rule_id: string;
  severity: WipSeverity;
  message: string;
  details: Record<string, unknown>;
}

export const WIP_RULE_IDS = [
  'wip_report.billed_exceeds_contract',
  'wip_report.percent_complete_over_100',
  'wip_report.eac_below_cost_to_date',
  'wip_report.large_fade',
  'wip_report.loss_job',
] as const;

/* -- Pure helpers ---------------------------------------------------------- */

const DECIMAL_RE = /^[+-]?\d+(\.\d+)?$/;

function fracLen(v: string | null | undefined): number {
  if (v == null) return 0;
  const s = String(v);
  const i = s.indexOf('.');
  return i < 0 ? 0 : s.length - i - 1;
}

/** Scale a decimal string to a BigInt with `scale` fraction digits; null when malformed. */
function toScaled(v: string | null | undefined, scale: number): bigint | null {
  if (v == null) return null;
  const s = String(v).trim();
  if (!DECIMAL_RE.test(s)) return null;
  const neg = s.startsWith('-');
  const [int = '0', frac = ''] = s.replace(/^[+-]/, '').split('.');
  const padded = (frac + '0'.repeat(scale)).slice(0, scale);
  const n = BigInt(int + padded);
  return neg ? -n : n;
}

/** Compare two decimal strings exactly. A missing or malformed value counts as zero. */
export function compareDecimal(a: string | null | undefined, b: string | null | undefined): -1 | 0 | 1 {
  const scale = Math.max(fracLen(a), fracLen(b));
  const x = toScaled(a, scale) ?? BigInt(0);
  const y = toScaled(b, scale) ?? BigInt(0);
  return x < y ? -1 : x > y ? 1 : 0;
}

export function isPositive(v: string | null | undefined): boolean {
  return compareDecimal(v, '0') > 0;
}

export function isNegative(v: string | null | undefined): boolean {
  return compareDecimal(v, '0') < 0;
}

export type BillingPosition = 'over' | 'under' | 'even';

/** Over-billed (billed ahead of earned), under-billed (earned ahead of billed) or even. */
export function billingPosition(row: Pick<WipRow, 'over_billing' | 'under_billing'>): BillingPosition {
  if (isPositive(row.over_billing)) return 'over';
  if (isPositive(row.under_billing)) return 'under';
  return 'even';
}

export type FadeTone = 'fade' | 'gain' | 'neutral';

/** Negative fade is a loss of expected profit since the last close, positive a gain. */
export function fadeTone(fade: string | null | undefined): FadeTone {
  if (fade == null) return 'neutral';
  if (isNegative(fade)) return 'fade';
  if (isPositive(fade)) return 'gain';
  return 'neutral';
}

export function fadeClass(tone: FadeTone): string {
  if (tone === 'fade') return 'text-rose-600';
  if (tone === 'gain') return 'text-emerald-600';
  return 'text-content-secondary';
}

export type WipSortKey =
  | 'project_name'
  | 'contract_value'
  | 'percent_complete'
  | 'earned_revenue'
  | 'billed_to_date'
  | 'over_billing'
  | 'under_billing'
  | 'projected_gross_profit'
  | 'fade'
  | 'backlog';

/** Stable sort; money columns compare exactly, the name column by locale. A null fade sorts last. */
export function sortRows(rows: WipRow[], key: WipSortKey, dir: 'asc' | 'desc' = 'desc'): WipRow[] {
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      let c: number;
      if (key === 'project_name') {
        c = a.r.project_name.localeCompare(b.r.project_name);
      } else if (key === 'fade') {
        const x = a.r.fade;
        const y = b.r.fade;
        if (x == null && y == null) c = 0;
        else if (x == null) return 1;
        else if (y == null) return -1;
        else c = compareDecimal(x, y);
      } else {
        c = compareDecimal(a.r[key], b.r[key]);
      }
      return c !== 0 ? c * sign : a.i - b.i;
    })
    .map((x) => x.r);
}

/** Clamp a percent string to 0-100 for a bar width (display only). */
export function barPercent(v: string | null | undefined): number {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/** `YYYY-MM` of the month before `today`. */
export function previousMonth(today: Date = new Date()): string {
  const d = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function isValidPeriod(p: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(p);
}

/** Whether a decimal string is acceptable as an estimated-cost override. */
export function isValidAmount(v: string): boolean {
  return /^\d+(\.\d+)?$/.test(v.trim());
}

/** Only the newest closed period can be reopened. */
export function latestPeriod(periods: WipPeriod[]): WipPeriod | null {
  let best: WipPeriod | null = null;
  for (const p of periods) if (!best || p.period > best.period) best = p;
  return best;
}

/** Translation key suffix for a validation rule id. */
export function ruleKey(ruleId: string): string {
  return ruleId.replace(/^wip_report\./, '');
}

/* -- Fetchers -------------------------------------------------------------- */

function qs(params: Record<string, string | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : '';
}

export function fetchPortfolio(asOf?: string): Promise<WipPortfolio> {
  return apiGet<WipPortfolio>(`/v1/wip-report/portfolio${qs({ as_of: asOf })}`);
}

export function fetchLive(projectId: string, asOf?: string): Promise<WipRow> {
  return apiGet<WipRow>(`/v1/wip-report/projects/${projectId}/live${qs({ as_of: asOf })}`);
}

export function fetchPeriods(projectId: string): Promise<WipPeriod[]> {
  return apiGet<WipPeriod[]>(`/v1/wip-report/projects/${projectId}/periods`);
}

export function closePeriod(projectId: string, body: { period: string; notes?: string }): Promise<WipPeriod> {
  return apiPost<WipPeriod, { period: string; notes?: string }>(`/v1/wip-report/projects/${projectId}/periods`, body);
}

export function reopenPeriod(projectId: string, period: string): Promise<void> {
  return apiDelete(`/v1/wip-report/projects/${projectId}/periods/${period}`);
}

export function fetchForecast(projectId: string): Promise<WipForecast> {
  return apiGet<WipForecast>(`/v1/wip-report/projects/${projectId}/forecast`);
}

export function saveForecast(projectId: string, body: WipForecast): Promise<WipForecast> {
  return apiPut<WipForecast, WipForecast>(`/v1/wip-report/projects/${projectId}/forecast`, body);
}

export function fetchValidation(projectId: string): Promise<{ findings: WipFinding[] }> {
  return apiGet<{ findings: WipFinding[] }>(`/v1/wip-report/projects/${projectId}/validation`);
}

export function exportPortfolio(format: 'xlsx' | 'pdf', asOf?: string, projectId?: string): Promise<void> {
  return downloadWithAuth(
    `/api/v1/wip-report/portfolio/export${qs({ format, as_of: asOf, project_id: projectId })}`,
    `wip-report.${format}`,
  );
}

/* -- Hooks ----------------------------------------------------------------- */

export const wipKeys = {
  all: ['wip-report'] as const,
  portfolio: (asOf?: string) => ['wip-report', 'portfolio', asOf ?? 'today'] as const,
  live: (projectId: string, asOf?: string) => ['wip-report', 'live', projectId, asOf ?? 'today'] as const,
  periods: (projectId: string) => ['wip-report', 'periods', projectId] as const,
  forecast: (projectId: string) => ['wip-report', 'forecast', projectId] as const,
  validation: (projectId: string) => ['wip-report', 'validation', projectId] as const,
};

export function useWipPortfolio(asOf?: string) {
  return useQuery({ queryKey: wipKeys.portfolio(asOf), queryFn: () => fetchPortfolio(asOf), staleTime: 60 * 1000 });
}

export function useWipLive(projectId: string, asOf?: string) {
  return useQuery({
    queryKey: wipKeys.live(projectId, asOf),
    queryFn: () => fetchLive(projectId, asOf),
    enabled: !!projectId,
  });
}

export function useWipPeriods(projectId: string) {
  return useQuery({
    queryKey: wipKeys.periods(projectId),
    queryFn: () => fetchPeriods(projectId),
    enabled: !!projectId,
  });
}

export function useWipForecast(projectId: string) {
  return useQuery({
    queryKey: wipKeys.forecast(projectId),
    queryFn: () => fetchForecast(projectId),
    enabled: !!projectId,
  });
}

export function useWipValidation(projectId: string) {
  return useQuery({
    queryKey: wipKeys.validation(projectId),
    queryFn: () => fetchValidation(projectId),
    enabled: !!projectId,
  });
}

/** Every write refreshes the whole `wip-report` cache: live row, periods, findings and the portfolio move together. */
export function useWipMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: wipKeys.all }),
  });
}
