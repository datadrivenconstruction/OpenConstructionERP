// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Cost-Value Reconciliation (CVR) & Cashflow.
 *
 * Every path is built from BASE ('/v1/cvr'); apiGet / apiPost already prepend
 * '/api', so we never write '/api/v1' here. Every monetary value crosses the
 * wire as a Decimal-as-string (e.g. "1234.56"), never a number: format it for
 * display with formatCurrency / toNum from '@/shared/lib/money' and never call
 * .toFixed on it or use '+' to add two of them.
 */

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

const BASE = '/v1/cvr';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type CvrReportStatus = 'draft' | 'final';
export type PaymentApplicationStatus = 'draft' | 'submitted' | 'certified' | 'paid';

export interface CvrReport {
  id: string;
  project_id: string;
  period: string; // YYYY-MM
  title: string | null;
  status: CvrReportStatus;
  currency: string;
  notes: string | null;
  line_count: number;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CvrReportList {
  items: CvrReport[];
  total: number;
}

/** Money fields are Decimal-as-string. */
export interface CvrLine {
  id: string;
  report_id: string;
  cost_code: string;
  description: string;
  cost_to_date: string;
  value_to_date: string;
  accruals: string;
  forecast_cost: string;
  forecast_value: string;
  sort_order: number;
  margin_to_date: string;
  forecast_margin: string;
  flags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Report roll-up. Every money field (and both percentages) is a string. */
export interface CvrSummary {
  report_id: string;
  project_id: string;
  period: string;
  status: CvrReportStatus;
  currency: string;
  line_count: number;
  total_cost_to_date: string;
  total_value_to_date: string;
  total_accruals: string;
  total_forecast_cost: string;
  total_forecast_value: string;
  margin_to_date: string;
  forecast_margin: string;
  margin_to_date_pct: string;
  forecast_margin_pct: string;
  warnings: string[];
}

export interface CashflowPoint {
  id: string;
  project_id: string;
  period: string;
  cash_in: string;
  cash_out: string;
  net: string;
  currency: string;
  label: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CashflowSeriesEntry {
  period: string;
  cash_in: string;
  cash_out: string;
  net: string;
  cumulative_cash_in: string;
  cumulative_cash_out: string;
  cumulative_net: string;
}

export interface CashflowSeries {
  project_id: string;
  currency: string;
  points: CashflowSeriesEntry[];
  total_cash_in: string;
  total_cash_out: string;
  net_position: string;
}

export interface PaymentApplication {
  id: string;
  project_id: string;
  period: string;
  application_number: string | null;
  gross_value: string;
  retention: string;
  net_value: string;
  currency: string;
  status: PaymentApplicationStatus;
  notes: string | null;
  /** The contract progress claim the application was raised from, if any. */
  progress_claim_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PaymentApplicationList {
  items: PaymentApplication[];
  total: number;
}

/* ── Payloads ──────────────────────────────────────────────────────────── */

export interface CreateCvrReportPayload {
  project_id: string;
  period: string;
  title?: string;
  currency?: string;
  status?: CvrReportStatus;
  notes?: string;
}

export interface CreateCvrLinePayload {
  cost_code?: string;
  description?: string;
  cost_to_date?: string;
  value_to_date?: string;
  accruals?: string;
  forecast_cost?: string;
  forecast_value?: string;
  sort_order?: number;
  /** When set, must equal the report currency (single-currency guard). */
  currency?: string;
}

export type UpdateCvrLinePayload = CreateCvrLinePayload;

export interface CreateCashflowPointPayload {
  project_id: string;
  period: string;
  cash_in?: string;
  cash_out?: string;
  currency?: string;
  label?: string;
}

/** Partial update for a cashflow point. period / project_id are immutable. */
export interface UpdateCashflowPointPayload {
  cash_in?: string;
  cash_out?: string;
  currency?: string;
  label?: string;
}

export interface CreatePaymentApplicationPayload {
  project_id: string;
  period: string;
  /** Raise the application from this progress claim (same project). */
  progress_claim_id?: string;
  application_number?: string;
  gross_value?: string;
  retention?: string;
  currency?: string;
  status?: PaymentApplicationStatus;
  notes?: string;
}

/* ── Reports ───────────────────────────────────────────────────────────── */

export async function fetchCvrReports(projectId: string): Promise<CvrReportList> {
  return apiGet<CvrReportList>(`${BASE}/reports/?project_id=${encodeURIComponent(projectId)}`);
}

export async function createCvrReport(data: CreateCvrReportPayload): Promise<CvrReport> {
  return apiPost<CvrReport>(`${BASE}/reports/`, data);
}

export async function updateCvrReport(
  id: string,
  data: Partial<CreateCvrReportPayload>,
): Promise<CvrReport> {
  return apiPatch<CvrReport>(`${BASE}/reports/${id}`, data);
}

export async function deleteCvrReport(id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/reports/${id}`);
}

export async function finalizeCvrReport(id: string): Promise<CvrReport> {
  return apiPost<CvrReport>(`${BASE}/reports/${id}/finalize/`, {});
}

export async function fetchCvrSummary(reportId: string): Promise<CvrSummary> {
  return apiGet<CvrSummary>(`${BASE}/reports/${reportId}/summary/`);
}

/* ── Lines ─────────────────────────────────────────────────────────────── */

export async function fetchCvrLines(reportId: string): Promise<CvrLine[]> {
  return apiGet<CvrLine[]>(`${BASE}/reports/${reportId}/lines/`);
}

export async function createCvrLine(
  reportId: string,
  data: CreateCvrLinePayload,
): Promise<CvrLine> {
  return apiPost<CvrLine>(`${BASE}/reports/${reportId}/lines/`, data);
}

export async function updateCvrLine(lineId: string, data: UpdateCvrLinePayload): Promise<CvrLine> {
  return apiPatch<CvrLine>(`${BASE}/lines/${lineId}`, data);
}

export async function deleteCvrLine(lineId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/lines/${lineId}`);
}

/* ── Cashflow ──────────────────────────────────────────────────────────── */

export async function fetchCashflowPoints(projectId: string): Promise<CashflowPoint[]> {
  return apiGet<CashflowPoint[]>(`${BASE}/cashflow/?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchCashflowSeries(projectId: string): Promise<CashflowSeries> {
  return apiGet<CashflowSeries>(
    `${BASE}/cashflow/series/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createCashflowPoint(
  data: CreateCashflowPointPayload,
): Promise<CashflowPoint> {
  return apiPost<CashflowPoint>(`${BASE}/cashflow/`, data);
}

export async function updateCashflowPoint(
  id: string,
  data: UpdateCashflowPointPayload,
): Promise<CashflowPoint> {
  return apiPatch<CashflowPoint>(`${BASE}/cashflow/${id}`, data);
}

export async function deleteCashflowPoint(id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/cashflow/${id}`);
}

/* ── Payment applications ──────────────────────────────────────────────── */

export async function fetchPaymentApplications(
  projectId: string,
): Promise<PaymentApplicationList> {
  return apiGet<PaymentApplicationList>(
    `${BASE}/payment-applications/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createPaymentApplication(
  data: CreatePaymentApplicationPayload,
): Promise<PaymentApplication> {
  return apiPost<PaymentApplication>(`${BASE}/payment-applications/`, data);
}

export async function updatePaymentApplication(
  id: string,
  data: Partial<CreatePaymentApplicationPayload>,
): Promise<PaymentApplication> {
  return apiPatch<PaymentApplication>(`${BASE}/payment-applications/${id}`, data);
}

/** A contract progress claim offered by the payment application picker. */
export interface ProgressClaimOption {
  id: string;
  contract_id: string;
  contract_code: string;
  claim_number: string;
  status: string;
  /** YYYY-MM the claim bills, from its period end; null when unreadable. */
  period: string | null;
  gross_amount: string;
  retention_amount: string;
  net_due: string;
  currency: string;
}

export async function fetchProgressClaimOptions(projectId: string): Promise<ProgressClaimOption[]> {
  // The route is not paged, it answers with every claim of the project.
  const page = await apiGet<Pick<Page<ProgressClaimOption>, 'items' | 'total'>>(
    `${BASE}/progress-claims/?project_id=${encodeURIComponent(projectId)}`,
  );
  return page.items;
}

export async function deletePaymentApplication(id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/payment-applications/${id}`);
}
