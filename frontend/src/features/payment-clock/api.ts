// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Payment Clock module.
 *
 * Backed by /api/v1/payment-clock/ — see
 * backend/app/modules/payment_clock/router.py
 *
 * Money and percentages arrive as plain-decimal **strings**, not numbers. The
 * backend serialises them that way on purpose: a payment application is the
 * last place in the product where a double-rounding artefact is acceptable.
 * They stay strings here too, and are parsed only where one is compared or
 * formatted.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Kept equal to the Literals in the module's schemas.py. */
export type DayBasis = 'calendar' | 'business';
export type NoticeType =
  | 'payment_notice'
  | 'pay_less_notice'
  | 'default_payment_notice';
export type SourceType =
  | 'contracts_progress_claim'
  | 'subcontractors_payment_application'
  | 'manual';
export type ApplicationStatus = 'open' | 'paid' | 'disputed' | 'closed';
export type EventType =
  | 'payment_notice_missed'
  | 'notice_out_of_time'
  | 'pay_less_notice_without_basis'
  | 'final_date_before_due_date'
  | 'payment_overdue';

export interface Regime {
  id: string;
  code: string;
  jurisdiction: string;
  country_code: string;
  statute: string;
  statute_reference: string;
  due_date_basis: string;
  due_date_days: number;
  due_date_day_basis: DayBasis;
  payment_notice_basis: string;
  payment_notice_days: number | null;
  payment_notice_day_basis: DayBasis;
  final_date_basis: string;
  final_date_days: number | null;
  final_date_day_basis: DayBasis;
  pay_less_days: number | null;
  pay_less_day_basis: DayBasis;
  no_notice_effect: string;
  interest_basis: string;
  interest_reference_rate: string;
  interest_margin_percent: string | null;
  interest_fixed_percent: string | null;
  interest_statute: string;
  notes: string;
  /** Composed by the router from the pure clock helper, not stored. */
  interest_description: string;
}

export interface PaymentApplication {
  id: string;
  project_id: string;
  regime_id: string;
  source_type: SourceType;
  source_id: string | null;
  reference: string;
  application_date: string;
  period_start: string | null;
  period_end: string | null;
  applied_amount: string;
  currency: string;
  due_date: string | null;
  payment_notice_deadline: string | null;
  pay_less_deadline: string | null;
  final_date: string | null;
  /** True once somebody stated the statutory dates instead of computing them. */
  dates_overridden: boolean;
  status: ApplicationStatus;
  paid_at: string | null;
  paid_amount: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  regime_code: string;
  jurisdiction: string;
}

export interface Notice {
  id: string;
  application_id: string;
  notice_type: NoticeType;
  issued_at: string;
  notified_amount: string | null;
  currency: string;
  basis_of_calculation: string;
  served_by: string;
  served_to: string;
  reference: string;
  created_at: string;
  updated_at: string;
}

export interface ClockEvent {
  id: string;
  application_id: string;
  event_type: EventType;
  severity: string;
  rule_id: string;
  detected_at: string;
  deadline_date: string | null;
  days_late: number | null;
  amount: string | null;
  currency: string;
  consequence: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ClockFinding {
  /** An i18n key. `message` is the rule's English, shown only as a fallback. */
  key: string;
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string;
  details: Record<string, unknown>;
}

export interface NotifiedSum {
  amount: string | null;
  currency: string;
  source: string;
  explanation: string;
  /** Stable code for the sentence, so the page can say it in the reader's
   *  language. Empty on a reading written before the codes existed. */
  reason?: string;
  params?: Record<string, string>;
}

export interface ApplicationClock {
  application: PaymentApplication;
  notices: Notice[];
  events: ClockEvent[];
  findings: ClockFinding[];
  notified_sum: NotifiedSum;
  derivation: string[];
  interest_description: string;
}

export interface ApplicationCreate {
  project_id: string;
  regime_code: string;
  source_type?: SourceType;
  source_id?: string | null;
  reference?: string;
  application_date: string;
  period_start?: string | null;
  period_end?: string | null;
  applied_amount: string;
  currency: string;
  status?: ApplicationStatus;
  paid_at?: string | null;
  paid_amount?: string | null;
  notes?: string;
  holidays?: string[];
  due_date?: string | null;
  payment_notice_deadline?: string | null;
  pay_less_deadline?: string | null;
  final_date?: string | null;
}

export type ApplicationUpdate = Partial<
  Omit<ApplicationCreate, 'project_id' | 'regime_code' | 'holidays'>
>;

export interface NoticeCreate {
  notice_type: NoticeType;
  issued_at: string;
  notified_amount?: string | null;
  currency?: string;
  basis_of_calculation?: string;
  served_by?: string;
  served_to?: string;
  reference?: string;
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/payment-clock';

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

export function listRegimes(countryCode = ''): Promise<Regime[]> {
  return apiGet<Regime[]>(`${BASE}/regimes/${qs({ country_code: countryCode })}`);
}

export function listApplications(params: {
  projectId: string;
  status?: string;
  overdueOnly?: boolean;
  limit?: number;
  offset?: number;
}): Promise<PaymentApplication[]> {
  return apiGet<PaymentApplication[]>(
    `${BASE}/applications/${qs({
      project_id: params.projectId,
      status: params.status,
      overdue_only: params.overdueOnly,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

export function getClock(applicationId: string, asOf?: string): Promise<ApplicationClock> {
  return apiGet<ApplicationClock>(
    `${BASE}/applications/${applicationId}${qs({ as_of: asOf })}`,
  );
}

export function openClock(body: ApplicationCreate): Promise<PaymentApplication> {
  return apiPost<PaymentApplication, ApplicationCreate>(`${BASE}/applications/`, body);
}

export function amendClock(
  applicationId: string,
  body: ApplicationUpdate,
): Promise<PaymentApplication> {
  return apiPatch<PaymentApplication, ApplicationUpdate>(
    `${BASE}/applications/${applicationId}`,
    body,
  );
}

export function deleteClock(applicationId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/applications/${applicationId}`);
}

/**
 * Recompute the statutory dates from the regime.
 *
 * Refused with 409 on a row whose dates were set by hand unless `force` is
 * given; the caller has to mean it, because overwriting them is overwriting
 * evidence of what the parties worked to.
 */
export function recomputeClock(
  applicationId: string,
  force = false,
  holidays: string[] = [],
): Promise<ApplicationClock> {
  return apiPost<ApplicationClock, { force: boolean; holidays: string[] }>(
    `${BASE}/applications/${applicationId}/recompute`,
    { force, holidays },
  );
}

export function serveNotice(applicationId: string, body: NoticeCreate): Promise<Notice> {
  return apiPost<Notice, NoticeCreate>(
    `${BASE}/applications/${applicationId}/notices`,
    body,
  );
}

export function deleteNotice(noticeId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/notices/${noticeId}`);
}

/**
 * Bring the breach register of one project up to today.
 *
 * Reads never write the register, so a deadline that passed since the last
 * change to a clock is filed only when somebody asks for it here.
 */
export function refreshRegister(projectId: string): Promise<ClockEvent[]> {
  return apiPost<ClockEvent[], Record<string, never>>(
    `${BASE}/events/refresh${qs({ project_id: projectId })}`,
    {},
  );
}

export function listEvents(params: {
  projectId: string;
  eventType?: string;
  limit?: number;
}): Promise<ClockEvent[]> {
  return apiGet<ClockEvent[]>(
    `${BASE}/events/${qs({
      project_id: params.projectId,
      event_type: params.eventType,
      limit: params.limit,
    })}`,
  );
}
