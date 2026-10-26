// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers and React Query hooks for the Guarantees module: the register of
 * bank guarantees and bonds (bid, performance, advance payment, retention,
 * warranty, parent company), their lifecycle events, bank credit lines and the
 * company-wide exposure view.
 *
 * Mounted at `/api/v1/guarantees`. Money is a decimal STRING on the wire and is
 * kept as a string here; dates are `YYYY-MM-DD`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* -- Vocabularies (in lock-step with the backend module) ------------------- */

export type GuaranteeType =
  | 'bid_bond'
  | 'performance_bond'
  | 'advance_payment'
  | 'retention_bond'
  | 'warranty_bond'
  | 'parent_company';

export type GuaranteeDirection = 'given' | 'received';

export type GuaranteeStatus =
  | 'draft'
  | 'requested'
  | 'issued'
  | 'extended'
  | 'reduced'
  | 'released'
  | 'called'
  | 'expired';

export type AlertBand = 60 | 30 | 14;

export const GUARANTEE_TYPES: GuaranteeType[] = [
  'bid_bond',
  'performance_bond',
  'advance_payment',
  'retention_bond',
  'warranty_bond',
  'parent_company',
];

export const GUARANTEE_DIRECTIONS: GuaranteeDirection[] = ['given', 'received'];

export const GUARANTEE_STATUSES: GuaranteeStatus[] = [
  'draft',
  'requested',
  'issued',
  'extended',
  'reduced',
  'released',
  'called',
  'expired',
];

/** Mirrors the backend transition table; released and called are final. */
export const ALLOWED_TRANSITIONS: Record<GuaranteeStatus, GuaranteeStatus[]> = {
  draft: ['requested', 'issued'],
  requested: ['draft', 'issued'],
  issued: ['extended', 'reduced', 'released', 'called', 'expired'],
  extended: ['extended', 'reduced', 'released', 'called', 'expired'],
  reduced: ['extended', 'reduced', 'released', 'called', 'expired'],
  expired: ['extended'],
  released: [],
  called: [],
};

/** Live = counts towards exposure. */
export const LIVE_STATUSES: GuaranteeStatus[] = ['issued', 'extended', 'reduced'];

export const VALIDATION_RULE_IDS = [
  'guarantees.performance_bond_before_first_payment',
  'guarantees.expiry_covers_defects_period',
  'guarantees.advance_covers_outstanding',
  'guarantees.amount_matches_contract_percent',
] as const;

/** Only draft and requested guarantees may be deleted. */
export function isDeletable(status: GuaranteeStatus): boolean {
  return status === 'draft' || status === 'requested';
}

/** Transitions that need an extra field in the request. */
export function transitionNeeds(to: GuaranteeStatus): 'expiry' | 'amount' | null {
  if (to === 'extended') return 'expiry';
  if (to === 'reduced') return 'amount';
  return null;
}

/* -- Wire types ------------------------------------------------------------- */

export interface GuaranteeDocument {
  id: string;
  document_id: string;
  kind: string;
  title: string;
  created_at: string;
}

export interface Guarantee {
  id: string;
  project_id: string;
  reference: string;
  guarantee_type: GuaranteeType;
  direction: GuaranteeDirection;
  status: GuaranteeStatus;
  issuer_bank: string | null;
  bank_reference: string | null;
  beneficiary: string | null;
  applicant: string | null;
  amount: string;
  original_amount: string;
  currency: string;
  percent_of_contract: string | null;
  contract_value: string | null;
  issue_date: string | null;
  expiry_date: string | null;
  auto_extend: boolean;
  extension_months: number | null;
  claim_period_days: number | null;
  defects_period_months: number | null;
  advance_amount: string | null;
  advance_recovered: string | null;
  advance_recovery_pct: string | null;
  replaces_cash_retention: boolean;
  commission_rate_pct: string | null;
  form_code: string | null;
  contract_id: string | null;
  contract_security_id: string | null;
  subcontractor_id: string | null;
  tender_id: string | null;
  bid_id: string | null;
  facility_id: string | null;
  notes: string | null;
  metadata: Record<string, unknown>;
  documents: GuaranteeDocument[];
  created_at: string;
  updated_at: string;
  days_to_expiry: number | null;
  alert_band: AlertBand | null;
  outstanding_advance: string | null;
}

export type GuaranteeEventAction =
  | 'created'
  | 'updated'
  | 'status_changed'
  | 'extended'
  | 'reduced'
  | 'released'
  | 'called'
  | 'document_linked'
  | 'document_unlinked';

export interface GuaranteeEvent {
  id: string;
  action: GuaranteeEventAction;
  from_status: GuaranteeStatus | null;
  to_status: GuaranteeStatus | null;
  amount_before: string | null;
  amount_after: string | null;
  changes: Record<string, unknown>;
  source: string | null;
  source_id: string | null;
  note: string | null;
  actor_id: string | null;
  created_at: string;
}

export interface GuaranteeFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  element_ref: string | null;
  details: Record<string, unknown> | null;
}

export interface GuaranteeDetail extends Guarantee {
  events: GuaranteeEvent[];
  findings: GuaranteeFinding[];
}

export interface GuaranteeFilters {
  guarantee_type?: GuaranteeType | '';
  status?: GuaranteeStatus | '';
  direction?: GuaranteeDirection | '';
  contract_id?: string;
}

export interface GuaranteeCreate {
  reference: string;
  guarantee_type: GuaranteeType;
  direction: GuaranteeDirection;
  status?: GuaranteeStatus;
  issuer_bank?: string | null;
  bank_reference?: string | null;
  beneficiary?: string | null;
  applicant?: string | null;
  amount: string;
  currency: string;
  percent_of_contract?: string | null;
  contract_value?: string | null;
  issue_date?: string | null;
  expiry_date?: string | null;
  auto_extend?: boolean;
  extension_months?: number | null;
  claim_period_days?: number | null;
  defects_period_months?: number | null;
  advance_amount?: string | null;
  advance_recovery_pct?: string | null;
  replaces_cash_retention?: boolean;
  commission_rate_pct?: string | null;
  form_code?: string | null;
  contract_id?: string | null;
  subcontractor_id?: string | null;
  tender_id?: string | null;
  bid_id?: string | null;
  facility_id?: string | null;
  notes?: string | null;
}

export type GuaranteeUpdate = Partial<GuaranteeCreate>;

export interface TransitionBody {
  status: GuaranteeStatus;
  new_expiry_date?: string;
  new_amount?: string;
  note?: string;
}

export interface MoneyTotal {
  currency: string;
  amount: string;
}

export interface BankTotal extends MoneyTotal {
  bank: string;
}

export interface TypeTotal extends MoneyTotal {
  guarantee_type: GuaranteeType;
}

export interface CreditLineUsage {
  facility_id: string;
  bank_name: string;
  currency: string;
  limit_amount: string;
  used_amount: string;
  available_amount: string;
  utilisation_pct: string | number | null;
}

export interface Exposure {
  live_count: number;
  totals: MoneyTotal[];
  by_bank: BankTotal[];
  by_type: TypeTotal[];
  held: unknown[];
  credit_lines: CreditLineUsage[];
  expiring: Guarantee[];
}

export interface GuaranteeSummary {
  project_id: string;
  live_count: number;
  expiring_count: number;
  expired_count: number;
  totals: MoneyTotal[];
  next_expiry: string | null;
}

export interface Facility {
  id: string;
  name: string;
  bank_name: string;
  currency: string;
  limit_amount: string;
  expiry_date: string | null;
  notes: string | null;
}

export type FacilityInput = Omit<Facility, 'id'>;

export interface PaymentGate {
  contract_id: string;
  allowed: boolean;
  reason: string | null;
  performance_bond_id: string | null;
}

export interface CommissionResult {
  posted: boolean;
  amount: string;
  days: number;
}

export interface GuaranteeDefaultsEntry {
  percent_of_contract?: string | number | null;
  defects_period_months?: number | null;
  claim_period_days?: number | null;
  advance_recovery_pct?: string | number | null;
  replaces_cash_retention?: boolean | null;
  form_code?: string | null;
  note?: string | null;
  source?: string | null;
}

export interface GuaranteeDefaults {
  country: string;
  origin: string;
  types: Partial<Record<GuaranteeType, GuaranteeDefaultsEntry>>;
}

/* -- Pure helpers ------------------------------------------------------------ */

/** Tailwind classes per alert band: 14 red, 30 amber, 60 yellow. */
export function alertBandClass(band: AlertBand | null): string {
  if (band === 14) return 'bg-rose-100 text-rose-700';
  if (band === 30) return 'bg-amber-100 text-amber-700';
  if (band === 60) return 'bg-yellow-100 text-yellow-700';
  return 'bg-surface-secondary text-content-tertiary';
}

/** Share of a credit line in use, 0..100, or null when the line has no limit. */
export function utilisationPercent(line: Pick<CreditLineUsage, 'utilisation_pct'>): number | null {
  const raw = line.utilisation_pct;
  if (raw === null || raw === undefined || raw === '') return null;
  const n = Number(raw);
  return Number.isFinite(n) ? Math.max(0, n) : null;
}

/** Bar width 0..100 for an amount against the largest amount in the list. */
export function barWidth(amount: string, max: number): number {
  const n = Number(amount);
  if (!Number.isFinite(n) || max <= 0) return 0;
  return Math.max(0, Math.min(100, (n / max) * 100));
}

/** Drops empty strings and undefined so a PATCH or POST body carries only set values. */
export function compactBody<T extends object>(body: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(body)) {
    if (v === '' || v === undefined) continue;
    out[k] = v;
  }
  return out as Partial<T>;
}

/* -- Fetchers ------------------------------------------------------------------ */

const BASE = '/v1/guarantees';

function qs(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export function fetchGuarantees(projectId: string, filters: GuaranteeFilters = {}): Promise<Guarantee[]> {
  return apiGet<Guarantee[]>(
    `${BASE}/projects/${projectId}/guarantees${qs({
      guarantee_type: filters.guarantee_type || undefined,
      status: filters.status || undefined,
      direction: filters.direction || undefined,
      contract_id: filters.contract_id,
    })}`,
  );
}

export function fetchGuarantee(projectId: string, id: string): Promise<GuaranteeDetail> {
  return apiGet<GuaranteeDetail>(`${BASE}/projects/${projectId}/guarantees/${id}`);
}

export function createGuarantee(projectId: string, body: GuaranteeCreate): Promise<Guarantee> {
  return apiPost<Guarantee, GuaranteeCreate>(`${BASE}/projects/${projectId}/guarantees`, body);
}

export function updateGuarantee(projectId: string, id: string, body: GuaranteeUpdate): Promise<Guarantee> {
  return apiPatch<Guarantee, GuaranteeUpdate>(`${BASE}/projects/${projectId}/guarantees/${id}`, body);
}

export function deleteGuarantee(projectId: string, id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/projects/${projectId}/guarantees/${id}`);
}

export function transitionGuarantee(projectId: string, id: string, body: TransitionBody): Promise<Guarantee> {
  return apiPost<Guarantee, TransitionBody>(`${BASE}/projects/${projectId}/guarantees/${id}/transition`, body);
}

export function advanceRecovery(
  projectId: string,
  id: string,
  body: { recovered_amount: string; note?: string },
): Promise<Guarantee> {
  return apiPost<Guarantee>(`${BASE}/projects/${projectId}/guarantees/${id}/advance-recovery`, body);
}

export function postCommission(projectId: string, id: string, periodEnd: string): Promise<CommissionResult> {
  return apiPost<CommissionResult>(
    `${BASE}/projects/${projectId}/guarantees/${id}/commission?period_end=${encodeURIComponent(periodEnd)}`,
  );
}

export function linkDocument(
  projectId: string,
  id: string,
  body: { document_id: string; kind: string; title: string },
): Promise<Guarantee> {
  return apiPost<Guarantee>(`${BASE}/projects/${projectId}/guarantees/${id}/documents`, body);
}

export function unlinkDocument(projectId: string, id: string, documentId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/projects/${projectId}/guarantees/${id}/documents/${documentId}`);
}

export function fetchProjectExposure(projectId: string): Promise<Exposure> {
  return apiGet<Exposure>(`${BASE}/projects/${projectId}/exposure`);
}

export function fetchCompanyExposure(): Promise<Exposure> {
  return apiGet<Exposure>(`${BASE}/exposure`);
}

export function fetchSummary(projectId: string): Promise<GuaranteeSummary> {
  return apiGet<GuaranteeSummary>(`${BASE}/projects/${projectId}/summary`);
}

export function fetchPortfolio(): Promise<GuaranteeSummary[]> {
  return apiGet<GuaranteeSummary[]>(`${BASE}/portfolio`);
}

export function fetchValidation(projectId: string): Promise<{ findings: GuaranteeFinding[] }> {
  return apiGet<{ findings: GuaranteeFinding[] }>(`${BASE}/projects/${projectId}/validation`);
}

export function fetchFacilities(): Promise<Facility[]> {
  return apiGet<Facility[]>(`${BASE}/facilities`);
}

export function createFacility(body: FacilityInput): Promise<Facility> {
  return apiPost<Facility, FacilityInput>(`${BASE}/facilities`, body);
}

export function updateFacility(id: string, body: Partial<FacilityInput>): Promise<Facility> {
  return apiPatch<Facility, Partial<FacilityInput>>(`${BASE}/facilities/${id}`, body);
}

export function deleteFacility(id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/facilities/${id}`);
}

export function runAlerts(): Promise<unknown> {
  return apiPost<unknown>(`${BASE}/alerts/run`);
}

export function fetchPaymentGate(contractId: string): Promise<PaymentGate> {
  return apiGet<PaymentGate>(`${BASE}/contracts/${contractId}/payment-gate`);
}

export function fetchDefaults(country: string): Promise<GuaranteeDefaults> {
  return apiGet<GuaranteeDefaults>(`${BASE}/defaults${qs({ country })}`);
}

/* -- Hooks --------------------------------------------------------------------- */

export const guaranteeKeys = {
  all: ['guarantees'] as const,
  list: (projectId: string, filters: GuaranteeFilters) => ['guarantees', 'list', projectId, filters] as const,
  detail: (projectId: string, id: string) => ['guarantees', 'detail', projectId, id] as const,
  validation: (projectId: string) => ['guarantees', 'validation', projectId] as const,
  summary: (projectId: string) => ['guarantees', 'summary', projectId] as const,
  exposure: (projectId?: string) => ['guarantees', 'exposure', projectId ?? 'company'] as const,
  facilities: ['guarantees', 'facilities'] as const,
  defaults: (country: string) => ['guarantees', 'defaults', country] as const,
};

export function useGuarantees(projectId: string, filters: GuaranteeFilters = {}) {
  return useQuery({
    queryKey: guaranteeKeys.list(projectId, filters),
    queryFn: () => fetchGuarantees(projectId, filters),
    enabled: !!projectId,
  });
}

export function useGuarantee(projectId: string, id: string) {
  return useQuery({
    queryKey: guaranteeKeys.detail(projectId, id),
    queryFn: () => fetchGuarantee(projectId, id),
    enabled: !!projectId && !!id,
  });
}

export function useGuaranteeValidation(projectId: string) {
  return useQuery({
    queryKey: guaranteeKeys.validation(projectId),
    queryFn: () => fetchValidation(projectId),
    enabled: !!projectId,
  });
}

export function useGuaranteeSummary(projectId: string) {
  return useQuery({
    queryKey: guaranteeKeys.summary(projectId),
    queryFn: () => fetchSummary(projectId),
    enabled: !!projectId,
    staleTime: 60 * 1000,
  });
}

export function useExposure(projectId?: string) {
  return useQuery({
    queryKey: guaranteeKeys.exposure(projectId),
    queryFn: () => (projectId ? fetchProjectExposure(projectId) : fetchCompanyExposure()),
  });
}

export function useFacilities() {
  return useQuery({ queryKey: guaranteeKeys.facilities, queryFn: fetchFacilities });
}

export function useGuaranteeDefaults(country: string) {
  return useQuery({
    queryKey: guaranteeKeys.defaults(country),
    queryFn: () => fetchDefaults(country),
    enabled: !!country,
    staleTime: 10 * 60 * 1000,
  });
}

/** Every write refreshes the whole `guarantees` cache: lists, details, exposure and summaries move together. */
export function useGuaranteeMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: guaranteeKeys.all }),
  });
}
