// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for the value-realized layer. These endpoints compose figures the
// rest of the platform already computes - approved-change exposure managed, cost
// recovered, admin hours given back and a documented dispute-risk proxy - into a
// project and portfolio value-realized view, plus an adoption-vs-non-adoption
// benchmark on the firm's own projects. Money and rates are carried on the wire
// as strings and passed straight to MoneyDisplay, never coerced here.

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import type {
  AdoptionBenchmark,
  AdoptionChecklist,
  HoursSaved,
  RegionalBenchmark,
  RegionalMetric,
  TimeFactors,
  TimeFactorUpdate,
  ValueSummary,
} from './types';

const BASE = '/v1/value';

export function getValueSummary(projectId: string): Promise<ValueSummary> {
  return apiGet<ValueSummary>(`${BASE}/projects/${projectId}/summary`);
}

// Record that the user generated a project's value report (the "value case").
// Returns the same composed summary the dashboard shows; the side effect is an
// activity-log row that counts toward the guided adoption checklist.
export function recordValueReport(projectId: string): Promise<ValueSummary> {
  return apiPost<ValueSummary, Record<string, never>>(`${BASE}/projects/${projectId}/report`, {});
}

export function getPortfolioSummary(): Promise<ValueSummary> {
  return apiGet<ValueSummary>(`${BASE}/portfolio/summary`);
}

export function getHoursSaved(projectId: string, by = 'feature'): Promise<HoursSaved> {
  return apiGet<HoursSaved>(`${BASE}/projects/${projectId}/hours-saved?by=${encodeURIComponent(by)}`);
}

export function getAdoptionBenchmark(): Promise<AdoptionBenchmark> {
  return apiGet<AdoptionBenchmark>(`${BASE}/adoption-benchmark`);
}

export function getAdoptionChecklist(projectId: string, role = 'manager'): Promise<AdoptionChecklist> {
  return apiGet<AdoptionChecklist>(
    `${BASE}/projects/${projectId}/adoption-checklist?role=${encodeURIComponent(role)}`,
  );
}

// Admin-only: the tenant's editable hours-saved minute factors. The GET returns
// every seed-default pair plus any tenant overrides; the PUT applies a batch of
// overrides (a value equal to the default clears the override). Minutes are
// carried as strings - they are durations of saved effort, never money.
export function getTimeFactors(): Promise<TimeFactors> {
  return apiGet<TimeFactors>(`${BASE}/admin/time-factors`);
}

export function putTimeFactors(factors: TimeFactorUpdate[]): Promise<TimeFactors> {
  return apiPut<TimeFactors, { factors: TimeFactorUpdate[] }>(`${BASE}/admin/time-factors`, {
    factors,
  });
}

// Benchmark a dimensionless ratio (overrun_pct / recovery_rate) or cost-per-m2
// across the tenant's own projects, optionally narrowed to one region. This is
// the shared cost-benchmark endpoint (not under /v1/value); the value dashboard
// surfaces the ratio metrics as portfolio context next to the adoption view.
export function getRegionalBenchmark(
  metric: RegionalMetric,
  region?: string,
): Promise<RegionalBenchmark> {
  const body: { metric: RegionalMetric; region?: string } = { metric };
  if (region) body.region = region;
  return apiPost<RegionalBenchmark, typeof body>('/v1/costs/benchmark/', body);
}
