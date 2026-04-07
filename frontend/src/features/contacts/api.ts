/**
 * API helpers for Contacts Directory.
 *
 * All endpoints are prefixed with /v1/contacts/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

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
