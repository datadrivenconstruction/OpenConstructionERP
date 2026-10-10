// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Transmittals.
 *
 * All endpoints are prefixed with /v1/transmittals/.
 */

import { apiDelete, apiGet, apiPatch, apiPost, type Page } from '@/shared/lib/api';
import { downloadRecordPdf, downloadRegister, type DocumentFormat } from '@/shared/lib/documentExport';

/* ── Types ─────────────────────────────────────────────────────────────── */

// Mirrors the backend status lifecycle exactly: draft -> issued -> responded
// (the service sets `responded` once every recipient has submitted a response).
// Receipt acknowledgement is tracked per recipient (`acknowledged_at`), never as
// a transmittal status - the UI derives an "acknowledged" stat from recipients.
export type TransmittalStatus = 'draft' | 'issued' | 'responded';

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
  email: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  response: string | null;
}

// The backend RecipientResponse returns org/user UUIDs and an
// `acknowledged_at` timestamp, but no resolved `name`/`company` and no
// `acknowledged` boolean. Normalise the wire shape into the UI shape so the
// detail view never renders `undefined` for a recipient name or undercounts
// acknowledgements. `name`/`company` may be hydrated server-side later (via
// joined org/user records) — we read them when present and fall back to a
// readable identifier otherwise.
interface RecipientWire {
  id: string;
  name?: string | null;
  company?: string | null;
  // Free-text identity columns the backend now stores directly (a recipient is
  // usually an external party, not a system user or a stored contact).
  recipient_name?: string | null;
  recipient_email?: string | null;
  acknowledged?: boolean | null;
  acknowledged_at?: string | null;
  recipient_org_id?: string | null;
  recipient_user_id?: string | null;
  action_required?: string | null;
  response?: string | null;
}

export interface TransmittalItem {
  id: string;
  document_title: string;
  document_ref: string | null;
  revision: string | null;
  revision_id?: string | null;
  document_id?: string | null;
}

// The backend ItemResponse carries `description`/`notes`/`item_number` rather
// than the UI's `document_title`/`document_ref`/`revision`. Map the fields so
// the detail view shows the description instead of `undefined`, while still
// honouring an already-shaped `document_title` if a future endpoint sends one.
interface ItemWire {
  id: string;
  document_title?: string | null;
  description?: string | null;
  document_ref?: string | null;
  revision?: string | null;
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
  // Free-form server-side dict; the create form stashes the typed recipient
  // names here under `recipients_text` (the recipients table only keys on
  // org/user UUIDs).
  metadata: Record<string, unknown>;
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

// One recipient on create or on a post-hoc add. A recipient is usually named
// by free text (an external party); org/user ids are for recipients picked
// from contacts or system users.
export interface CreateRecipientPayload {
  recipient_name?: string;
  recipient_email?: string;
  recipient_org_id?: string;
  recipient_user_id?: string;
  action_required?: string;
}

export interface CreateTransmittalPayload {
  project_id: string;
  subject: string;
  purpose_code: TransmittalPurpose;
  cover_note?: string;
  response_due_date?: string;
  items?: CreateItemPayload[];
  // The create form's "Recipients" field is split into structured recipient
  // rows here so the transmittal has real recipients and can actually be issued
  // (issuing requires at least one recipient). Free-text names/emails land in
  // recipient_name / recipient_email.
  recipients?: CreateRecipientPayload[];
  metadata?: Record<string, unknown>;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

// The backend speaks `purpose_code` / `response_due_date` / `is_locked`;
// the UI shapes expect `purpose` / `response_due` / `locked`. Normalise
// here so consumers never see untranslated i18n keys like
// `transmittals.purpose_undefined`.
type TransmittalWire = Omit<
  Transmittal,
  'purpose' | 'response_due' | 'locked' | 'recipients' | 'items' | 'metadata'
> & {
  purpose?: TransmittalPurpose;
  purpose_code?: TransmittalPurpose;
  response_due?: string | null;
  response_due_date?: string | null;
  locked?: boolean;
  is_locked?: boolean;
  recipients?: RecipientWire[];
  items?: ItemWire[];
  metadata?: Record<string, unknown> | null;
};

function normaliseItem(i: ItemWire): TransmittalItem {
  // Backend sends `description`; UI reads `document_title`. Prefer an explicit
  // title, fall back to the description, and never surface `undefined`.
  const document_title = i.document_title?.trim() || i.description?.trim() || '';
  return {
    id: i.id,
    document_title,
    document_ref: i.document_ref ?? null,
    revision: i.revision ?? null,
    revision_id: i.revision_id ?? null,
    document_id: i.document_id ?? null,
  };
}

// Short, stable label for a recipient when the backend has not (yet) hydrated
// a human-readable name. We never want the UI to print `undefined`.
function recipientFallbackLabel(r: RecipientWire): string {
  const named = r.recipient_name?.trim() || r.recipient_email?.trim();
  if (named) return named;
  const id = r.recipient_user_id ?? r.recipient_org_id;
  if (id) return `#${id.slice(0, 8)}`;
  return r.action_required ?? 'Recipient';
}

function normaliseRecipient(r: RecipientWire): TransmittalRecipient {
  const name = r.name?.trim() || r.recipient_name?.trim() || recipientFallbackLabel(r);
  const email = r.recipient_email?.trim() || null;
  // Derive the acknowledged flag from `acknowledged_at` when the backend does
  // not send an explicit boolean, so the "{ack}/{total} acknowledged" header
  // and the per-row check icon reflect reality instead of always reading 0.
  const acknowledged = r.acknowledged ?? r.acknowledged_at != null;
  return {
    id: r.id,
    name,
    company: r.company ?? null,
    email,
    acknowledged,
    acknowledged_at: r.acknowledged_at ?? null,
    response: r.response ?? null,
  };
}

function normaliseTransmittal(t: TransmittalWire): Transmittal {
  const purpose = (t.purpose ?? t.purpose_code ?? 'for_information') as TransmittalPurpose;
  const response_due = t.response_due ?? t.response_due_date ?? null;
  const locked = t.locked ?? t.is_locked ?? false;
  const recipients = (t.recipients ?? []).map(normaliseRecipient);
  const items = (t.items ?? []).map(normaliseItem);
  const metadata = t.metadata ?? {};
  return { ...t, purpose, response_due, locked, recipients, items, metadata } as Transmittal;
}

/**
 * Read one page of the register, and say how big the register is.
 *
 * The ceiling below is 100 rows, so on a busy project this is a slice. The
 * caller gets the whole envelope rather than the rows alone, because a count
 * the caller never sees is a count it cannot show the reader.
 */
export async function fetchTransmittals(filters?: TransmittalFilters): Promise<Page<Transmittal>> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  // Raise from the server default cap (50) to its accepted ceiling (le=100) so
  // the list and client-side search cover up to 100 records instead of
  // silently dropping older rows.
  params.set('limit', '100');
  const qs = params.toString();
  const page = await apiGet<Page<TransmittalWire>>(`/v1/transmittals/?${qs}`);
  return { ...page, items: page.items.map(normaliseTransmittal) };
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

export async function addRecipient(
  transmittalId: string,
  data: CreateRecipientPayload,
): Promise<void> {
  await apiPost(`/v1/transmittals/${transmittalId}/recipients/`, data);
}

export async function deleteRecipient(transmittalId: string, recipientId: string): Promise<void> {
  await apiDelete(`/v1/transmittals/${transmittalId}/recipients/${recipientId}`);
}

/* ── Printed documents ─────────────────────────────────────────────────── */

/**
 * Download the transmittal register of a project (GET /export/, trailing
 * slash as the route declares it). The route takes no filter: the register
 * is exported whole.
 */
export function downloadTransmittalRegister(
  projectId: string,
  format: DocumentFormat,
  locale: string,
): Promise<void> {
  return downloadRegister('/v1/transmittals/export/', projectId, format, locale, 'transmittal-register');
}

/** Download the cover sheet of one transmittal (GET /{id}/export/pdf/). */
export function downloadTransmittalPdf(id: string, locale: string, transmittalNumber?: string): Promise<void> {
  return downloadRecordPdf(
    `/v1/transmittals/${encodeURIComponent(id)}/export/pdf/`,
    locale,
    transmittalNumber || 'transmittal',
  );
}
