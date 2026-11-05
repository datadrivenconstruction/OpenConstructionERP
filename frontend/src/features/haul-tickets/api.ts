// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API helpers for haul tickets (/v1/haul_tickets). Decimals travel as strings. */
import { API_BASE, apiGet, apiPost, apiDelete, downloadWithAuth, fetchWithAuth } from '@/shared/lib/api';


export type TicketStatus = 'issued' | 'loaded' | 'delivered' | 'verified' | 'invoiced' | 'rejected';
export type HaulType = 'earthworks' | 'aggregates' | 'concrete' | 'asphalt' | 'waste' | 'other';
export type GroupBy = 'day' | 'haulier' | 'material' | 'haul_type';
export type Unit = 't' | 'm3' | 'load';
export type RateBasis = 't' | 'm3' | 'load' | 'hour';

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
}

export interface Ticket {
  id: string;
  project_id: string;
  ticket_number: string;
  haul_type: HaulType;
  direction: string;
  ticket_date: string;
  origin: string;
  destination: string;
  material_name: string;
  unit: Unit;
  gross_t: string | null;
  tare_t: string | null;
  net_t: string | null;
  volume_m3: string | null;
  loads: number;
  quantity: string;
  haulier_name: string;
  plate: string;
  driver_name: string;
  rate_basis: string;
  rate: string | null;
  currency: string;
  amount: string;
  status: TicketStatus;
  reject_reason: string;
  receiver_name: string;
  has_signature: boolean;
  findings: Finding[];
}

export interface TicketList {
  items: Ticket[];
  total: number;
  offset: number;
  limit: number;
}

export interface TicketCreate {
  project_id: string;
  ticket_number?: string;
  haul_type: HaulType;
  ticket_date?: string;
  origin?: string;
  destination?: string;
  material_name?: string;
  unit: Unit;
  gross_t?: string | null;
  tare_t?: string | null;
  volume_m3?: string | null;
  loads: number;
  haulier_name?: string;
  plate?: string;
  rate?: string | null;
  rate_basis: RateBasis;
}

export interface SummaryRow {
  key: string;
  label: string;
  loads: number;
  tonnes: string;
  volume_m3: string;
  amount: string;
  tickets: number;
}

export interface Summary {
  group_by: GroupBy;
  rows: SummaryRow[];
  totals: SummaryRow;
}

export interface Invoice {
  id: string;
  haulier_name: string;
  invoice_number: string;
  invoice_date: string | null;
  currency: string;
  total: string;
  status: string;
  findings: Finding[];
}

export interface ImportPreview {
  headers: string[];
  mapping: Record<string, number>;
  target_fields: string[];
  rows: Record<string, unknown>[];
  total: number;
  duplicates: number;
}

export interface TicketFilter {
  status?: string;
  q?: string;
}

function qs(params: Record<string, string | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const fetchTickets = (projectId: string, f: TicketFilter) =>
  apiGet<TicketList>(`/v1/haul_tickets/projects/${projectId}/tickets${qs({ ...f, limit: '500' })}`);

export const createTicket = (body: TicketCreate) => apiPost<Ticket>(`/v1/haul_tickets/tickets/`, body);

export const transitionTicket = (id: string, status: TicketStatus, reason = '') =>
  apiPost<Ticket>(`/v1/haul_tickets/tickets/${id}/status`, { status, reason });

export const deleteTicket = (id: string) => apiDelete(`/v1/haul_tickets/tickets/${id}`);

export const downloadTicketPdf = (id: string, number: string) =>
  downloadWithAuth(`${API_BASE}/v1/haul_tickets/tickets/${id}/pdf`, `haul-ticket-${number || id}.pdf`);

export const fetchSummary = (projectId: string, groupBy: GroupBy, verifiedOnly: boolean) =>
  apiGet<Summary>(
    `/v1/haul_tickets/projects/${projectId}/summary${qs({ group_by: groupBy, verified_only: verifiedOnly ? 'true' : undefined })}`,
  );

export const fetchInvoices = async (projectId: string): Promise<Invoice[]> =>
  (await apiGet<{ items: Invoice[]; total: number }>(`/v1/haul_tickets/projects/${projectId}/invoices?limit=500`)).items;

export const reconcileInvoice = (id: string) => apiPost<Invoice>(`/v1/haul_tickets/invoices/${id}/reconcile`);

export const acceptInvoice = (id: string) => apiPost<Invoice>(`/v1/haul_tickets/invoices/${id}/accept`);

export const deleteInvoice = (id: string) => apiDelete(`/v1/haul_tickets/invoices/${id}`);

export const downloadDisposalRegister = (projectId: string) =>
  downloadWithAuth(`${API_BASE}/v1/haul_tickets/projects/${projectId}/disposal-register?format=csv`, 'disposal-register.csv');

async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}/v1/haul_tickets${path}`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export function previewImport(projectId: string, file: File, mapping?: Record<string, number>, kg = false) {
  const form = new FormData();
  form.set('file', file);
  if (mapping) form.set('mapping', JSON.stringify(mapping));
  form.set('weights_in_kg', String(kg));
  return upload<ImportPreview>(`/projects/${projectId}/import/preview`, form);
}

export function commitImport(projectId: string, file: File, mapping: Record<string, number>, kg: boolean) {
  const form = new FormData();
  form.set('file', file);
  form.set('mapping', JSON.stringify(mapping));
  form.set('weights_in_kg', String(kg));
  return upload<{ created: number; skipped_duplicates: number; ticket_ids: string[] }>(
    `/projects/${projectId}/import/commit`,
    form,
  );
}
