// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for leases, rent schedules, rent roll and arrears (/v1/leasing).
 * Money arrives and leaves as decimal strings.
 */
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/leasing';

export type LeaseStatus = 'draft' | 'active' | 'notice' | 'ended';
export type Frequency = 'monthly' | 'quarterly' | 'semiannual' | 'annual';
export type EscalationKind = 'none' | 'fixed' | 'index';
export type UnitKind = 'plot' | 'asset' | 'unit';

export interface Lease {
  id: string;
  project_id: string;
  code: string;
  unit_kind: UnitKind;
  unit_ref: string;
  unit_label: string;
  tenant_contact_id: string;
  landlord_legal_entity_id: string | null;
  start_date: string;
  end_date: string;
  term_months: number;
  rent_amount: string;
  currency: string;
  frequency: Frequency;
  deposit: string;
  escalation_kind: EscalationKind;
  escalation_rate: string | null;
  escalation_index: string | null;
  escalation_every_months: number;
  tax_code: string | null;
  tax_rate: string;
  payment_terms_days: number;
  status: LeaseStatus;
  break_date: string | null;
  notice_date: string | null;
  ended_on: string | null;
  renewed_from_id: string | null;
  document_ids: string[];
  ext_refs: Record<string, unknown>;
  notes: string | null;
}

export interface LeaseCreate {
  project_id: string;
  code: string;
  unit_kind: UnitKind;
  unit_ref: string;
  unit_label?: string;
  tenant_contact_id: string;
  landlord_legal_entity_id?: string | null;
  start_date: string;
  end_date: string;
  rent_amount: string;
  currency: string;
  frequency: Frequency;
  deposit: string;
  escalation_kind: EscalationKind;
  escalation_rate?: string | null;
  escalation_every_months?: number;
  tax_rate?: string;
  payment_terms_days?: number;
  break_date?: string | null;
}

export interface ScheduleLine {
  id: string;
  lease_id: string;
  seq: number;
  period_start: string;
  period_end: string;
  due_date: string;
  amount: string;
  tax_code: string | null;
  tax_amount: string;
  review_number: number;
  invoice_id: string | null;
}

export interface Schedule {
  lease_id: string;
  currency: string;
  total: string;
  items: ScheduleLine[];
}

export interface LeaseEvent {
  id: string;
  kind: string;
  event_date: string;
  payload: Record<string, unknown>;
  actor_id: string | null;
}

export interface LeaseDetail {
  lease: Lease;
  events: LeaseEvent[];
  documents: { id: string; name: string; category: string }[];
}

export interface RentRollRow {
  lease_id: string;
  code: string;
  unit_label: string;
  unit_ref: string;
  tenant_contact_id: string;
  tenant_name: string;
  status: LeaseStatus;
  start_date: string;
  end_date: string;
  currency: string;
  frequency: Frequency;
  current_rent: string;
  annual_rent: string;
  deposit: string;
  next_due_date: string | null;
  break_date: string | null;
}

export interface ArrearsRow {
  lease_id: string;
  code: string;
  unit_label: string;
  tenant_contact_id: string;
  tenant_name: string;
  currency: string;
  invoice_id: string;
  invoice_number: string;
  due_date: string | null;
  days_past_due: number;
  bucket: 'current' | '1_30' | '31_60' | '61_90' | 'over_90';
  total: string;
  paid: string;
  due: string;
}

export interface ValidationIssue {
  rule_id: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
}

export const fetchLeases = (projectId: string) =>
  apiGet<{ items: Lease[]; total: number }>(`${BASE}/?project_id=${projectId}`).then((r) => r.items);

export const fetchLease = (id: string) => apiGet<LeaseDetail>(`${BASE}/${id}`);

export const createLease = (payload: LeaseCreate) => apiPost<Lease>(`${BASE}/`, payload);

export const updateLease = (id: string, payload: Partial<LeaseCreate>) => apiPatch<Lease>(`${BASE}/${id}`, payload);

export const deleteLease = (id: string) => apiDelete(`${BASE}/${id}`);

export const activateLease = (id: string) => apiPost<Lease>(`${BASE}/${id}/activate`, {});

export const terminateLease = (id: string, payload: { effective: string; reason?: string }) =>
  apiPost<Lease>(`${BASE}/${id}/terminate`, payload);

export const renewLease = (id: string, payload: { end_date: string; rent_amount?: string }) =>
  apiPost<Lease>(`${BASE}/${id}/renew`, payload);

export const fetchSchedule = (id: string) => apiGet<Schedule>(`${BASE}/${id}/schedule`);

export const regenerateSchedule = (id: string) => apiPost<Schedule>(`${BASE}/${id}/schedule`, {});

export const validateLease = (id: string) =>
  apiGet<{ status: string; checked: number; results: ValidationIssue[] }>(`${BASE}/${id}/validate`);

export const linkDocument = (id: string, documentId: string) =>
  apiPost<Lease>(`${BASE}/${id}/documents`, { document_id: documentId });

export const unlinkDocument = (id: string, documentId: string) => apiDelete(`${BASE}/${id}/documents/${documentId}`);

export const runSchedule = (projectId: string, asOf?: string) =>
  apiPost<{ invoices_created: number; skipped: number }>(`${BASE}/schedule/run`, {
    project_id: projectId,
    as_of: asOf || null,
  });

export const fetchRentRoll = (projectId: string) =>
  apiGet<{ as_of: string; items: RentRollRow[]; totals: Record<string, string> }>(
    `${BASE}/rent-roll?project_id=${projectId}`,
  );

export const fetchArrears = (projectId: string) =>
  apiGet<{ as_of: string; items: ArrearsRow[]; totals: Record<string, Record<string, string>> }>(
    `${BASE}/arrears?project_id=${projectId}`,
  );

export const fetchExportProfiles = () =>
  apiGet<{ profiles: string[] }>(`${BASE}/export-profiles`).then((r) => r.profiles);

export const downloadExport = (projectId: string, format: string) =>
  downloadWithAuth(`${API_BASE}${BASE}/export?project_id=${projectId}&format=${format}`, `leases.${format}`);

export const fetchProjectDocuments = (projectId: string) =>
  apiGet<{ items: { id: string; name: string; category: string }[]; total: number }>(
    `/v1/documents/?project_id=${projectId}&limit=200`,
  ).then((r) => r.items);
