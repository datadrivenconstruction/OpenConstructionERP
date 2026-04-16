/**
 * API helpers for Contacts Directory.
 *
 * All endpoints are prefixed with /v1/contacts/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ContactType = 'client' | 'subcontractor' | 'supplier' | 'consultant' | 'internal';

export type PrequalificationStatus = 'pending' | 'approved' | 'expired' | 'rejected';

export interface Contact {
  id: string;
  contact_type: ContactType;
  first_name: string | null;
  last_name: string | null;
  company_name: string | null;
  legal_name: string | null;
  vat_number: string | null;
  primary_email: string | null;
  primary_phone: string | null;
  website: string | null;
  country_code: string | null;
  address: Record<string, unknown> | null;
  prequalification_status: PrequalificationStatus | null;
  payment_terms_days: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // Computed display helpers
  contact_name?: string;
  email?: string;
  phone?: string;
  country?: string;
}

export interface ContactFilters {
  contact_type?: ContactType | '';
  country?: string;
  search?: string;
  limit?: number;
}

export interface CreateContactPayload {
  contact_type: ContactType;
  first_name?: string;
  last_name?: string;
  company_name?: string;
  legal_name?: string;
  vat_number?: string;
  primary_email?: string;
  primary_phone?: string;
  website?: string;
  country_code?: string;
  address?: Record<string, unknown>;
  payment_terms_days?: string;
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
  const res = await apiGet<Contact[] | { items: Contact[] }>(`/v1/contacts/${qs ? `?${qs}` : ''}`);
  return Array.isArray(res) ? res : res.items ?? [];
}

export async function createContact(data: CreateContactPayload): Promise<Contact> {
  return apiPost<Contact>('/v1/contacts/', data);
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

  const response = await fetch('/api/v1/contacts/import/file/', {
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
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/contacts/export/', { method: 'GET', headers });
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

export function downloadContactsTemplate(): void {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  fetch('/api/v1/contacts/template/', { method: 'GET', headers })
    .then((response) => {
      if (!response.ok) throw new Error('Failed to download template');
      return response.blob();
    })
    .then((blob) => {
      triggerDownload(blob, 'contacts_import_template.xlsx');
    })
    .catch((err) => {
      if (import.meta.env.DEV) console.error('Template download error:', err);
    });
}
