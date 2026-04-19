/**
 * API helpers for Transmittals.
 *
 * All endpoints are prefixed with /v1/transmittals/.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type TransmittalStatus = 'draft' | 'issued' | 'acknowledged' | 'closed';

export type TransmittalPurpose =
  | 'for_approval'
  | 'for_information'
  | 'for_construction'
  | 'for_tender'
  | 'for_review'
  | 'for_record';

export interface TransmittalRecipient {
  id: string;
  name: string;
  company: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  response: string | null;
}

export interface TransmittalItem {
  id: string;
  document_title: string;
  document_ref: string | null;
  revision: string | null;
  revision_id?: string | null;
  document_id?: string | null;
}

export interface Transmittal {
  id: string;
  project_id: string;
  transmittal_number: string;
  subject: string;
  purpose: TransmittalPurpose;
  status: TransmittalStatus;
  cover_note: string | null;
  issued_date: string | null;
  response_due: string | null;
  locked: boolean;
  recipients: TransmittalRecipient[];
  items: TransmittalItem[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface TransmittalFilters {
  project_id?: string;
  status?: TransmittalStatus | '';
}

export interface CreateItemPayload {
  document_id?: string;
  revision_id?: string;
  item_number: number;
  description?: string;
  notes?: string;
}

export interface CreateTransmittalPayload {
  project_id: string;
  subject: string;
  purpose_code: TransmittalPurpose;
  cover_note?: string;
  response_due_date?: string;
  items?: CreateItemPayload[];
}

/* ── API Functions ─────────────────────────────────────────────────────── */

// The backend speaks `purpose_code` / `response_due_date` / `is_locked`;
// the UI shapes expect `purpose` / `response_due` / `locked`. Normalise
// here so consumers never see untranslated i18n keys like
// `transmittals.purpose_undefined`.
type TransmittalWire = Omit<Transmittal, 'purpose' | 'response_due' | 'locked'> & {
  purpose?: TransmittalPurpose;
  purpose_code?: TransmittalPurpose;
  response_due?: string | null;
  response_due_date?: string | null;
  locked?: boolean;
  is_locked?: boolean;
};

function normaliseTransmittal(t: TransmittalWire): Transmittal {
  const purpose = (t.purpose ?? t.purpose_code ?? 'for_information') as TransmittalPurpose;
  const response_due = t.response_due ?? t.response_due_date ?? null;
  const locked = t.locked ?? t.is_locked ?? false;
  return { ...t, purpose, response_due, locked } as Transmittal;
}

export async function fetchTransmittals(filters?: TransmittalFilters): Promise<Transmittal[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  const qs = params.toString();
  const res = await apiGet<TransmittalWire[] | { items: TransmittalWire[] }>(
    `/v1/transmittals/${qs ? `?${qs}` : ''}`,
  );
  const items = Array.isArray(res) ? res : res.items ?? [];
  return items.map(normaliseTransmittal);
}

export async function createTransmittal(data: CreateTransmittalPayload): Promise<Transmittal> {
  const wire = await apiPost<TransmittalWire>('/v1/transmittals/', data);
  return normaliseTransmittal(wire);
}

export async function issueTransmittal(id: string): Promise<Transmittal> {
  const wire = await apiPost<TransmittalWire>(`/v1/transmittals/${id}/issue/`);
  return normaliseTransmittal(wire);
}

export interface UpdateTransmittalPayload {
  subject?: string;
  purpose_code?: TransmittalPurpose;
  cover_note?: string | null;
  response_due_date?: string | null;
}

export async function updateTransmittal(
  id: string,
  data: UpdateTransmittalPayload,
): Promise<Transmittal> {
  const wire = await apiPatch<TransmittalWire>(`/v1/transmittals/${id}`, data);
  return normaliseTransmittal(wire);
}

export async function deleteTransmittal(id: string): Promise<void> {
  await apiDelete(`/v1/transmittals/${id}`);
}
