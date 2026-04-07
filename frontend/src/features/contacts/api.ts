/**
 * API helpers for Contacts Directory.
 *
 * All endpoints are prefixed with /v1/contacts/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ContactType = 'client' | 'subcontractor' | 'supplier' | 'consultant';

export type PrequalificationStatus = 'none' | 'pending' | 'approved' | 'expired' | 'rejected';

export interface Contact {
  id: string;
  company_name: string;
  contact_name: string;
  contact_type: ContactType;
  email: string;
  phone: string;
  country: string;
  address: string;
  prequalification_status: PrequalificationStatus;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ContactFilters {
  contact_type?: ContactType | '';
  country?: string;
  search?: string;
  limit?: number;
}

export interface CreateContactPayload {
  company_name: string;
  contact_name: string;
  contact_type: ContactType;
  email?: string;
  phone?: string;
  country?: string;
  address?: string;
  prequalification_status?: PrequalificationStatus;
  notes?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchContacts(filters?: ContactFilters): Promise<Contact[]> {
  const params = new URLSearchParams();
  if (filters?.contact_type) params.set('contact_type', filters.contact_type);
  if (filters?.country) params.set('country', filters.country);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.limit) params.set('limit', String(filters.limit));
  const qs = params.toString();
  return apiGet<Contact[]>(`/v1/contacts${qs ? `?${qs}` : ''}`);
}

export async function createContact(data: CreateContactPayload): Promise<Contact> {
  return apiPost<Contact>('/v1/contacts', data);
}

export async function updateContact(
  id: string,
  data: Partial<CreateContactPayload>,
): Promise<Contact> {
  return apiPatch<Contact>(`/v1/contacts/${id}`, data);
}

export async function deleteContact(id: string): Promise<void> {
  return apiDelete(`/v1/contacts/${id}`);
}

export interface ImportResult {
  imported: number;
  skipped: number;
  errors: { row: number; error: string; data: Record<string, string> }[];
  total_rows: number;
}

export async function importContactsFile(file: File): Promise<ImportResult> {
  const token = useAuthStore.getState().accessToken;
  const formData = new FormData();
  formData.append('file', file);

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/contacts/import/file', {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Import failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function exportContacts(): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/contacts/export', { method: 'GET', headers });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || 'contacts_export.xlsx';
  triggerDownload(blob, filename);
}

export async function downloadContactsTemplate(): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/contacts/template', { method: 'GET', headers });
  if (!response.ok) {
    throw new Error('Failed to download template');
  }

  const blob = await response.blob();
  triggerDownload(blob, 'contacts_import_template.xlsx');
}
