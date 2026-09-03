// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Contacts Directory.
 *
 * All endpoints are prefixed with /v1/contacts/.
 */

import { apiGet, apiPost, apiPatch, apiDelete, triggerDownload, extractErrorMessageFromBody, type Page } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Mirrors CONTACT_TYPES in the backend contacts schemas. */
export type ContactType =
  | 'client'
  | 'subcontractor'
  | 'contractor'
  | 'supplier'
  | 'consultant'
  | 'authority'
  | 'internal'
  | 'lead'
  | 'customer';

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
  metadata?: Record<string, unknown> | null;
  // ── Module bridge (v3117) ────────────────────────────────────
  // ``module_tags`` lists every module this contact participates
  // in (``property_dev_lead``, ``property_dev_buyer``, ``broker``,
  // …). The Contacts list shows them as badges and the Lead/Buyer
  // detail drawer uses them to decide whether the "Convert to …"
  // button should be visible.
  module_tags?: string[];
  // ``custom_properties`` is a per-module bucket dict. Modules
  // namespace under their own key, e.g.
  // ``{ "property_dev": { "preferred_contact_method": "email" } }``.
  // A few cross-module scalars live at the top level too - the client
  // ``brand_color`` (see features/projects/clients.ts) - hence `unknown`.
  custom_properties?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  // Computed display helpers
  contact_name?: string;
  email?: string;
  phone?: string;
  country?: string;
}

/* ── Module bridge payloads ──────────────────────────────────────── */

/** Module rows linked to a single contact (see GET /contacts/{id}/module-rows). */
export interface ContactModuleRows {
  property_dev_leads: Array<{
    id: string;
    development_id: string | null;
    source: string;
    status: string;
    lead_score: number;
    full_name: string;
    email: string;
    created_at: string | null;
  }>;
  property_dev_buyers: Array<{
    id: string;
    development_id: string | null;
    plot_id: string | null;
    status: string;
    contract_value: number;
    currency: string;
    full_name: string;
    email: string;
    created_at: string | null;
  }>;
}

/** Payload for POST /contacts/{id}/convert-to-lead. */
export interface ConvertContactToLeadPayload {
  development_id?: string;
  source?: 'web_form' | 'walk_in' | 'broker' | 'referral' | 'portal' | 'other';
  lead_score?: number;
  notes?: string;
}

/** Payload for POST /contacts/{id}/convert-to-buyer. */
export interface ConvertContactToBuyerPayload {
  development_id: string;
  plot_id?: string;
  notes?: string;
}

export interface ContactFilters {
  contact_type?: ContactType | '';
  country?: string;
  search?: string;
  limit?: number;
  tags?: string[];
}

export interface TagFacet {
  tag: string;
  count: number;
}

/** Aggregate stats from GET /v1/contacts/stats/. */
export interface ContactStats {
  total: number;
  by_type: Record<string, number>;
  by_country_top10: Record<string, number>;
  with_expiring_prequalification: number;
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

/**
 * Patch payload for an existing contact.
 *
 * Separate from `CreateContactPayload` because clearing a field has to be
 * expressible on the wire. `undefined` cannot express it: `JSON.stringify`
 * drops the key entirely, so the old value survives and emptying a phone
 * number has no effect at all. Every one of these columns is `str | None` on
 * the backend, so `null` is what clears them. An empty string is not a
 * substitute: `primary_email` runs through a format validator that rejects it.
 *
 * A key left out is left alone, because the update route dumps with
 * `exclude_unset=True`. That is what lets the form send only the fields the
 * user actually edited instead of writing its whole copy of the record back.
 */
export interface UpdateContactPayload {
  contact_type?: ContactType;
  first_name?: string | null;
  last_name?: string | null;
  company_name?: string | null;
  legal_name?: string | null;
  vat_number?: string | null;
  primary_email?: string | null;
  primary_phone?: string | null;
  website?: string | null;
  country_code?: string | null;
  address?: Record<string, unknown> | null;
  payment_terms_days?: string | null;
  prequalification_status?: PrequalificationStatus;
  notes?: string | null;
  /** Merged into the stored dict key-by-key on the server; send the whole
   *  object read-modify-written so a stale copy cannot drop another
   *  module's bucket. */
  custom_properties?: Record<string, unknown>;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/**
 * One page of the directory, envelope intact.
 *
 * The previous signature returned `Contact[]` and unwrapped a
 * `Contact[] | { items }` union, so every caller saw the rows the server
 * happened to send and nothing at all about the rows it did not. The
 * directory caps at 500 per request, which a CRM tenant with a few thousand
 * inbound leads passes without a word on screen. Callers that only need the
 * rows read `.items`; callers that put the rows in front of a person also
 * mount `TruncationNotice` with this page.
 */
export async function fetchContacts(filters?: ContactFilters): Promise<Page<Contact>> {
  const params = new URLSearchParams();
  if (filters?.contact_type) params.set('contact_type', filters.contact_type);
  if (filters?.country) params.set('country', filters.country);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.limit) params.set('limit', String(filters.limit));
  if (filters?.tags && filters.tags.length > 0) {
    for (const tag of filters.tags) {
      params.append('tag', tag);
    }
  }
  const qs = params.toString();
  return apiGet<Page<Contact>>(`/v1/contacts/${qs ? `?${qs}` : ''}`);
}

/**
 * One contact by id.
 *
 * Two callers used to answer "what is this contact called" by pulling 500
 * rows and searching them, which is a lookup that silently fails for contact
 * 501: no error, no empty state, the name just renders as a type word. The
 * per-id route has always existed.
 */
export function fetchContact(contactId: string): Promise<Contact> {
  return apiGet<Contact>(`/v1/contacts/${contactId}`);
}

export async function fetchContactTags(): Promise<TagFacet[]> {
  const res = await apiGet<{ items: TagFacet[] }>(`/v1/contacts/tags/`);
  return res.items ?? [];
}

/** Aggregate directory stats (total, by-type, top countries, expiring prequal). */
export async function fetchContactStats(): Promise<ContactStats> {
  return apiGet<ContactStats>(`/v1/contacts/stats/`);
}

export async function createContact(data: CreateContactPayload): Promise<Contact> {
  return apiPost<Contact>('/v1/contacts/', data);
}

export async function updateContact(
  id: string,
  data: UpdateContactPayload,
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
      detail = extractErrorMessageFromBody(body) ?? detail;
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
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      // FastAPI 422 returns ``detail`` as an array of objects — coercing
      // an array to a string yields ``[object Object]``. The shared helper
      // flattens it into a readable message ("loc: msg, …").
      detail = extractErrorMessageFromBody(body) ?? detail;
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

/* ── Module bridge endpoints ─────────────────────────────────────── */

/**
 * Materialise a PropDev Lead from this contact.
 *
 * Backend route: ``POST /v1/contacts/{id}/convert-to-lead``. The Lead
 * carries a ``contact_id`` FK back to this contact, and the contact's
 * ``module_tags`` array picks up ``property_dev_lead``. Returns the
 * newly created Lead payload (minimal — the PropDev module owns the
 * full schema and is the destination for the user's next click).
 */
export async function convertContactToLead(
  contactId: string,
  payload: ConvertContactToLeadPayload = {},
): Promise<{
  id: string;
  contact_id: string;
  development_id: string | null;
  source: string;
  lead_score: number;
  status: string;
  full_name: string;
  email: string;
}> {
  return apiPost(`/v1/contacts/${contactId}/convert-to-lead`, payload);
}

/**
 * Materialise a PropDev Buyer from this contact.
 *
 * Backend route: ``POST /v1/contacts/{id}/convert-to-buyer``. Same
 * pattern as :func:`convertContactToLead` but for the Buyer entity.
 */
export async function convertContactToBuyer(
  contactId: string,
  payload: ConvertContactToBuyerPayload,
): Promise<{
  id: string;
  contact_id: string;
  development_id: string;
  plot_id: string | null;
  status: string;
  full_name: string;
  email: string;
}> {
  return apiPost(`/v1/contacts/${contactId}/convert-to-buyer`, payload);
}

/**
 * List every module row (Lead / Buyer / …) linked to this contact.
 *
 * Backend route: ``GET /v1/contacts/{id}/module-rows``. Used by the
 * Contact detail drawer to render the "Linked records" section.
 */
export async function fetchContactModuleRows(
  contactId: string,
): Promise<ContactModuleRows> {
  return apiGet(`/v1/contacts/${contactId}/module-rows`);
}
