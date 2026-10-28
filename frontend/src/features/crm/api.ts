// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the CRM module.
 *
 * Backed by /api/v1/crm/ — see backend/app/modules/crm/router.py and
 * schemas.py. Endpoints cover accounts, leads (with qualify/convert flows),
 * opportunities (with stage transitions + win/lose), activities,
 * pipeline metrics and win/loss analytics.
 */

import { ApiError, apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Refused removals ─────────────────────────────────────────────────── */

export interface RemovalHolder {
  kind: string;
  count: number;
}

/**
 * The structured 409 body returned when a record cannot be deleted because
 * something still refers to it:
 *
 *     {"detail": {"code", "message", "remediation", "holders": [...]}}
 *
 * `holders` carries the kind and the count rather than a sentence, so the UI
 * can name what is in the way in the reader's own language. `message` is the
 * English fallback the server builds for callers that are not this app.
 */
export interface RemovalRefusal {
  code: string;
  message: string;
  remediation: string;
  holders: RemovalHolder[];
}

/**
 * Pull the structured refusal out of a thrown error, or null if this is not
 * one. A caller that gets null falls back to `getErrorMessage`, which already
 * renders `detail.message` readably, so nothing ever shows "[object Object]".
 */
export function parseRemovalRefusal(err: unknown): RemovalRefusal | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body as { detail?: unknown } | null | undefined;
  const detail = body?.detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== 'string' || typeof d.message !== 'string') return null;
  const holders = Array.isArray(d.holders)
    ? d.holders.flatMap((h): RemovalHolder[] => {
        if (!h || typeof h !== 'object') return [];
        const entry = h as Record<string, unknown>;
        if (typeof entry.kind !== 'string' || typeof entry.count !== 'number') return [];
        return [{ kind: entry.kind, count: entry.count }];
      })
    : [];
  return {
    code: d.code,
    message: d.message,
    remediation: typeof d.remediation === 'string' ? d.remediation : '',
    holders,
  };
}

/* ── Enums ────────────────────────────────────────────────────────────── */

export type AccountSize = 'sme' | 'mid' | 'enterprise';
export type AccountStatus = 'active' | 'dormant' | 'lost';

export type LeadSource =
  | 'web'
  | 'referral'
  | 'event'
  | 'cold_outreach'
  | 'inbound';

export type LeadStatus =
  | 'new'
  | 'qualifying'
  | 'qualified'
  | 'disqualified'
  | 'converted';

export type OpportunityStatus = 'open' | 'won' | 'lost' | 'abandoned';

export type ActivityKind = 'call' | 'meeting' | 'email' | 'task' | 'note';

export type ActivityOutcome =
  | 'no_answer'
  | 'voicemail'
  | 'positive'
  | 'negative'
  | 'neutral';

/* ── Domain types ─────────────────────────────────────────────────────── */

export interface PipelineStage {
  id: string;
  code: string;
  name: string;
  display_order: number;
  default_probability_percent: number;
  is_final: boolean;
  is_won: boolean;
  is_lost: boolean;
  color: string;
  created_at: string;
  updated_at: string;
}

export interface Account {
  id: string;
  name: string;
  industry: string | null;
  size_category: AccountSize;
  country: string | null;
  website: string | null;
  primary_contact_id: string | null;
  description: string;
  status: AccountStatus;
  owner_user_id: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface Lead {
  id: string;
  account_id: string | null;
  contact_name: string;
  contact_email: string | null;
  contact_phone: string | null;
  source: LeadSource;
  status: LeadStatus;
  assigned_to: string | null;
  qualification_notes: string;
  qualified_at: string | null;
  converted_at: string | null;
  converted_opportunity_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Opportunity {
  id: string;
  account_id: string;
  title: string;
  description: string;
  estimated_value: number | string;
  currency: string;
  expected_close_date: string | null;
  probability_percent: number;
  stage_id: string;
  weighted_value: number | string;
  source: LeadSource;
  owner_user_id: string | null;
  status: OpportunityStatus;
  won_at: string | null;
  lost_at: string | null;
  lost_reason_code: string | null;
  notes: string;
  /** References a row in the shared Contacts directory
   *  (oe_contacts_contact). CRM never duplicates contact data. */
  primary_contact_id: string | null;
  /** References a delivery/estimate Project (oe_projects_project). */
  project_id: string | null;
  competitor_names: string[];
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: string;
  owner_user_id: string | null;
  account_id: string | null;
  opportunity_id: string | null;
  lead_id: string | null;
  kind: ActivityKind;
  subject: string;
  body: string;
  due_at: string | null;
  completed_at: string | null;
  outcome: ActivityOutcome | null;
  external_calendar_event_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface StageHistory {
  id: string;
  opportunity_id: string;
  from_stage_id: string | null;
  to_stage_id: string;
  changed_at: string | null;
  changed_by: string | null;
  duration_in_previous_seconds: number | null;
  created_at: string;
}

export interface CurrencyTotal {
  currency: string;
  total: number | string;
}

export interface CrmDashboard {
  open_opportunities: number;
  weighted_value: number | string;
  pipeline_value: number | string;
  leads_open: number;
  activities_due_soon: number;
  win_rate_30d: number | string;
  /** Keyed by stage_id. Backend buckets carry count + total + weighted
   *  (no embedded stage name — resolve names from the stages list). */
  by_stage: Record<
    string,
    { count: number; total: number | string; weighted: number | string }
  >;
  /** Per-currency truth (never blends ISO codes). Use these for display. */
  by_currency?: CurrencyTotal[];
  weighted_by_currency?: CurrencyTotal[];
  mixed_currency?: boolean;
}

export interface WinLossAnalytics {
  period_start: string | null;
  period_end: string | null;
  won_count: number;
  lost_count: number;
  abandoned_count: number;
  win_rate: number | string;
  average_sales_cycle_days: number;
  lost_reasons_breakdown: Record<string, number>;
  won_value: number | string;
  lost_value: number | string;
  won_value_by_currency?: CurrencyTotal[];
  lost_value_by_currency?: CurrencyTotal[];
  mixed_currency?: boolean;
}

export interface PipelineMetrics {
  open_count: number;
  weighted_value: number | string;
  total_value: number | string;
  by_stage: Record<
    string,
    { count: number; total: number | string; weighted: number | string }
  >;
  win_rate_30d: number | string;
  by_currency?: CurrencyTotal[];
  weighted_by_currency?: CurrencyTotal[];
  mixed_currency?: boolean;
}

/* ── Payloads ─────────────────────────────────────────────────────────── */

export interface AccountCreatePayload {
  name: string;
  industry?: string;
  size_category?: AccountSize;
  country?: string;
  website?: string;
  primary_contact_id?: string | null;
  description?: string;
  status?: AccountStatus;
  owner_user_id?: string | null;
  tags?: string[];
}

export interface LeadCreatePayload {
  account_id?: string | null;
  contact_name: string;
  contact_email?: string;
  contact_phone?: string;
  source?: LeadSource;
  status?: LeadStatus;
  assigned_to?: string | null;
  qualification_notes?: string;
}

export interface OpportunityCreatePayload {
  account_id: string;
  title: string;
  description?: string;
  estimated_value?: number;
  currency?: string;
  expected_close_date?: string | null;
  probability_percent?: number;
  stage_id: string;
  source?: LeadSource;
  owner_user_id?: string | null;
  notes?: string;
  primary_contact_id?: string | null;
  project_id?: string | null;
  competitor_names?: string[];
}

export interface OpportunityMoveStagePayload {
  to_stage_id: string;
  override_probability_percent?: number;
}

export interface OpportunityWinPayload {
  won_at?: string;
  win_reason_code?: string;
}

export interface OpportunityLosePayload {
  lost_reason_code: string;
  lost_at?: string;
}

export interface LeadQualifyPayload {
  qualification_notes?: string;
}

export interface LeadConvertPayload {
  account_id: string;
  title: string;
  estimated_value?: number;
  currency?: string;
  expected_close_date?: string | null;
  stage_id: string;
  probability_percent?: number;
  description?: string;
}

export interface ActivityCreatePayload {
  owner_user_id?: string | null;
  account_id?: string | null;
  opportunity_id?: string | null;
  lead_id?: string | null;
  kind?: ActivityKind;
  subject?: string;
  body?: string;
  due_at?: string | null;
  completed_at?: string | null;
  outcome?: ActivityOutcome;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

function normaliseList<T>(res: T[] | { items: T[] } | null | undefined): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res;
  return res.items ?? [];
}

async function safeGetList<T>(path: string): Promise<T[]> {
  try {
    const res = await apiGet<T[] | { items: T[] }>(path);
    return normaliseList(res);
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'status' in err) {
      const s = (err as { status: number }).status;
      if (s === 404 || s === 501) return [];
    }
    throw err;
  }
}

function withQs(path: string, params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/* ── Accounts ─────────────────────────────────────────────────────────── */

export function listAccounts(params?: {
  industry?: string;
  owner_user_id?: string;
  status?: AccountStatus;
  offset?: number;
  limit?: number;
}): Promise<Account[]> {
  return safeGetList<Account>(withQs('/v1/crm/accounts/', params ?? {}));
}

export function getAccount(id: string): Promise<Account> {
  return apiGet<Account>(`/v1/crm/accounts/${id}`);
}

export function createAccount(data: AccountCreatePayload): Promise<Account> {
  return apiPost<Account>('/v1/crm/accounts/', data);
}

export function updateAccount(
  id: string,
  data: Partial<AccountCreatePayload>,
): Promise<Account> {
  return apiPatch<Account>(`/v1/crm/accounts/${id}`, data);
}

export function deleteAccount(id: string): Promise<void> {
  return apiDelete(`/v1/crm/accounts/${id}`);
}

/* ── Leads ────────────────────────────────────────────────────────────── */

export function listLeads(params?: {
  status?: LeadStatus;
  assigned_to?: string;
  source?: LeadSource;
  offset?: number;
  limit?: number;
}): Promise<Lead[]> {
  return safeGetList<Lead>(withQs('/v1/crm/leads/', params ?? {}));
}

export function getLead(id: string): Promise<Lead> {
  return apiGet<Lead>(`/v1/crm/leads/${id}`);
}

export function createLead(data: LeadCreatePayload): Promise<Lead> {
  return apiPost<Lead>('/v1/crm/leads/', data);
}

export function updateLead(id: string, data: Partial<LeadCreatePayload>): Promise<Lead> {
  return apiPatch<Lead>(`/v1/crm/leads/${id}`, data);
}

/**
 * Delete a lead outright.
 *
 * The backend refuses with a structured 409 when the lead has been converted
 * to an opportunity or carries logged activities - deleting either would erase
 * where a live deal came from, or take the activity log with it via the
 * CASCADE on `CrmActivity.lead_id`. Pass the thrown error to
 * `parseRemovalRefusal` to find out which.
 */
export function deleteLead(id: string): Promise<void> {
  return apiDelete(`/v1/crm/leads/${id}`);
}

export function qualifyLead(id: string, data: LeadQualifyPayload): Promise<Lead> {
  return apiPost<Lead>(`/v1/crm/leads/${id}/qualify`, data);
}

export function disqualifyLead(id: string): Promise<Lead> {
  return apiPost<Lead>(`/v1/crm/leads/${id}/disqualify`, {});
}

export function convertLead(
  id: string,
  data: LeadConvertPayload,
): Promise<Opportunity> {
  return apiPost<Opportunity>(`/v1/crm/leads/${id}/convert`, data);
}

/* ── Opportunities ────────────────────────────────────────────────────── */

export function listOpportunities(params?: {
  owner_user_id?: string;
  stage_id?: string;
  status?: OpportunityStatus;
  account_id?: string;
  offset?: number;
  limit?: number;
}): Promise<Opportunity[]> {
  return safeGetList<Opportunity>(withQs('/v1/crm/opportunities/', params ?? {}));
}

export function getOpportunity(id: string): Promise<Opportunity> {
  return apiGet<Opportunity>(`/v1/crm/opportunities/${id}`);
}

export function createOpportunity(
  data: OpportunityCreatePayload,
): Promise<Opportunity> {
  return apiPost<Opportunity>('/v1/crm/opportunities/', data);
}

export function updateOpportunity(
  id: string,
  data: Partial<OpportunityCreatePayload>,
): Promise<Opportunity> {
  return apiPatch<Opportunity>(`/v1/crm/opportunities/${id}`, data);
}

export function deleteOpportunity(id: string): Promise<void> {
  return apiDelete(`/v1/crm/opportunities/${id}`);
}

export function moveOpportunityStage(
  id: string,
  data: OpportunityMoveStagePayload,
): Promise<Opportunity> {
  return apiPost<Opportunity>(`/v1/crm/opportunities/${id}/move-stage`, data);
}

export function winOpportunity(
  id: string,
  data: OpportunityWinPayload,
): Promise<Opportunity> {
  return apiPost<Opportunity>(`/v1/crm/opportunities/${id}/win`, data);
}

export function loseOpportunity(
  id: string,
  data: OpportunityLosePayload,
): Promise<Opportunity> {
  return apiPost<Opportunity>(`/v1/crm/opportunities/${id}/lose`, data);
}

export function getOpportunityHistory(id: string): Promise<StageHistory[]> {
  return safeGetList<StageHistory>(`/v1/crm/opportunities/${id}/history`);
}

/* ── Pipeline stages ──────────────────────────────────────────────────── */

export function listPipelineStages(): Promise<PipelineStage[]> {
  return safeGetList<PipelineStage>('/v1/crm/pipeline-stages/');
}

/* ── Win/loss reasons ─────────────────────────────────────────────────── */

export interface WinLossReason {
  id: string;
  code: string;
  label: string;
  category: string;
  is_win_reason: boolean;
  is_loss_reason: boolean;
}

export function listWinLossReasons(): Promise<WinLossReason[]> {
  return safeGetList<WinLossReason>('/v1/crm/win-loss-reasons/');
}

/* ── Activities ───────────────────────────────────────────────────────── */

export function listActivities(params?: {
  owner_user_id?: string;
  opportunity_id?: string;
  account_id?: string;
  lead_id?: string;
  kind?: ActivityKind;
  due_before?: string;
  offset?: number;
  limit?: number;
}): Promise<Activity[]> {
  return safeGetList<Activity>(withQs('/v1/crm/activities/', params ?? {}));
}

export function getActivity(id: string): Promise<Activity> {
  return apiGet<Activity>(`/v1/crm/activities/${id}`);
}

export function createActivity(data: ActivityCreatePayload): Promise<Activity> {
  return apiPost<Activity>('/v1/crm/activities/', data);
}

export function updateActivity(
  id: string,
  data: Partial<ActivityCreatePayload>,
): Promise<Activity> {
  return apiPatch<Activity>(`/v1/crm/activities/${id}`, data);
}

export function deleteActivity(id: string): Promise<void> {
  return apiDelete(`/v1/crm/activities/${id}`);
}

/* ── Dashboards ───────────────────────────────────────────────────────── */

export function getCrmDashboard(params?: { owner_user_id?: string }): Promise<CrmDashboard> {
  return apiGet<CrmDashboard>(withQs('/v1/crm/dashboard', params ?? {}));
}

export function getPipelineMetrics(): Promise<PipelineMetrics> {
  return apiGet<PipelineMetrics>('/v1/crm/pipeline/metrics');
}

export function getWinLossAnalytics(params?: {
  period_start?: string;
  period_end?: string;
}): Promise<WinLossAnalytics> {
  return apiGet<WinLossAnalytics>(withQs('/v1/crm/analytics/win-loss', params ?? {}));
}
