// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the E-invoice Clearance module.
 *
 * Backed by /api/v1/einvoice-clearance/ — see
 * backend/app/modules/einvoice_clearance/router.py
 *
 * Two shapes of this contract are unusual enough to state here, because a
 * caller that assumes the ordinary shape is wrong in a way nothing reports:
 *
 * A **rejection is a 200**. `submit` and `cancel` answer with
 * `SubmissionResult.accepted === false` and the authority's own code and words.
 * The request succeeded; what came back is a fact about the invoice.
 *
 * A **refusal carries findings**. The 409 and 422 bodies are
 * `{detail: {message, findings}}`, and `getErrorMessage` resolves only the
 * message — the names of what blocked the submission are in `findings` and have
 * to be read out of the error deliberately. `findingsFromError` in
 * ./documentStatus does that.
 *
 * Money arrives as a plain-decimal **string**, not a number, matching the
 * finance module: a binary float cannot hold 0.10 and a tax authority's
 * arithmetic is exact. It stays a string all the way to `formatCurrency`.
 */

import { API_BASE, apiDelete, apiGet, apiPost, apiPut, getAuthToken } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/**
 * The nine states, kept equal to `DOCUMENT_STATUSES` in the module's models.py.
 *
 * Three of them are one idea per regime: a clearance country's yes is
 * `cleared`, a reporting country's is `reported`, a network's is `delivered`.
 * The union is a convenience for the screen's own maps — anything read off the
 * wire is typed `string`, because /meta is the authority on this vocabulary and
 * a status added there must not be narrowed away by this file.
 */
export type DocumentStatus =
  | 'draft'
  | 'validated'
  | 'queued'
  | 'submitted'
  | 'cleared'
  | 'reported'
  | 'delivered'
  | 'rejected'
  | 'cancelled';

export interface CountryRegime {
  country: string;
  regime: string;
  platform: string;
  label: string;
  /** What the authority hands back, in the words the accountant will hear. */
  identifier_label: string;
  document_format: string;
  en16931_profile: string;
  profile_fields: string[];
  document_fields: string[];
  /** Fields a document may carry that no submission requires (invoice mentions). */
  optional_document_fields?: string[];
  /** Keys of the registration's settings this country's rules read. */
  profile_setting_fields?: string[];
  /** Company sizes the country dates its waves by, in the order to offer them. */
  company_sizes?: string[];
  /** Null means the platform has no cancellation flow at all. */
  cancellation_window_days: number | null;
  is_cancellable: boolean;
  correction_mechanism: string;
  notes: string;
}

export interface ClearanceAdapter {
  key: string;
  label: string;
  /** `*` means the adapter serves every country. */
  countries: string[];
}

export interface ClearanceMeta {
  regimes: string[];
  statuses: string[];
  event_types: string[];
  countries: CountryRegime[];
  adapters: ClearanceAdapter[];
}

export interface ClearanceProfile {
  id: string;
  company_key: string;
  country: string;
  regime: string;
  platform: string;
  tax_registration_id: string;
  network_participant_id: string;
  /** A reference to the certificate, never the certificate and never a key. */
  certificate_reference: string;
  adapter_key: string;
  sandbox: boolean;
  is_active: boolean;
  settings: Record<string, unknown>;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ClearanceDocument {
  id: string;
  project_id: string;
  invoice_id: string | null;
  profile_id: string;
  country: string;
  regime: string;
  document_format: string;
  invoice_number: string;
  invoice_date: string;
  currency_code: string;
  /** Plain decimal string. */
  total_amount: string;
  payload_hash: string;
  payload_media_type: string;
  /** Zero is legitimate: a national format the EN 16931 engine cannot build. */
  payload_size: number;
  country_fields: Record<string, unknown>;
  status: string;
  authority_identifier: string;
  submitted_at: string | null;
  cleared_at: string | null;
  cancelled_at: string | null;
  /** The authority's own code. Shown verbatim, never paraphrased. */
  rejection_code: string;
  rejection_message: string;
  cancellation_reason: string;
  retry_count: number;
  adapter_key: string;
  created_at: string;
  updated_at: string;
}

export interface ClearanceFinding {
  /** An i18n key. `message` is the rule's English, shown as the fallback. */
  key: string;
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string;
  details: Record<string, unknown>;
}

export interface ClearanceEvent {
  id: string;
  document_id: string;
  sequence: number;
  event_type: string;
  from_status: string;
  to_status: string;
  message: string;
  authority_code: string;
  /** The platform's answer as it came, not a paraphrase of it. */
  raw_response: Record<string, unknown>;
  actor_id: string | null;
  created_at: string;
}

export interface DocumentSaveResult {
  document: ClearanceDocument;
  findings: ClearanceFinding[];
}

export interface SubmissionResult {
  document: ClearanceDocument;
  /** False is a 200. The authority answered, and the answer was no. */
  accepted: boolean;
  authority_identifier: string;
  rejection_code: string;
  rejection_message: string;
  /** The adapter's own line, distinct from the authority's rejection message. */
  message: string;
  findings: ClearanceFinding[];
}

export interface ResolveBody {
  outcome: 'cleared' | 'rejected';
  authority_identifier?: string;
  rejection_code?: string;
  rejection_message?: string;
  /** Mandatory: a hand-written status change has to say where it came from. */
  note: string;
}

/**
 * What a registration is written with.
 *
 * Only the identity is required. Which of the rest a country actually needs is
 * not a property of this type: /meta answers it per country in `profile_fields`,
 * and the form asks for exactly those. Mexico wants a certificate reference and
 * Germany wants a network participant id, and neither is a field the other
 * would know what to do with.
 */
export interface ProfileWriteBody {
  company_key: string;
  country: string;
  tax_registration_id?: string;
  network_participant_id?: string;
  /** A reference to the certificate. Never the certificate, never a key. */
  certificate_reference?: string;
  adapter_key?: string;
  /** True is the server default and stays the default here. See `createProfile`. */
  sandbox?: boolean;
  is_active?: boolean;
  settings?: Record<string, unknown>;
  notes?: string;
}

/**
 * What a clearance document is created with.
 *
 * `country_fields` carries the national fields the country format needs and the
 * EN 16931 semantic model has nowhere to put. /meta names them per country in
 * `document_fields`; there is no fixed set.
 */
export interface DocumentCreateBody {
  project_id: string;
  profile_id: string;
  /** Null when the document does not come from an invoice already in Finance. */
  invoice_id?: string | null;
  invoice_number?: string;
  invoice_date?: string;
  currency_code?: string;
  /** Plain decimal string, as everywhere else money crosses this boundary. */
  total_amount?: string;
  /* `Record<string, string>`, not `unknown`: the server declares
     `dict[str, str]` and Pydantic rejects anything else, so a looser type here
     only moves the failure from the compiler to a request the operator has
     already filled in. */
  country_fields?: Record<string, string>;
  payload?: string | null;
  payload_media_type?: string;
}

/** The same, minus what a document cannot be moved between after creation. */
export type DocumentUpdateBody = Omit<
  DocumentCreateBody,
  'project_id' | 'profile_id' | 'invoice_id'
>;

/** The stored bytes, as stored. */
export interface StoredPayload {
  text: string;
  mediaType: string;
  filename: string;
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/einvoice-clearance';

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

/**
 * The vocabularies the screen renders itself from.
 *
 * Statuses, regimes and the installed adapters are read from here rather than
 * hardcoded, so a country added to the backend registry shows up without a
 * frontend change.
 */
export function getMeta(): Promise<ClearanceMeta> {
  return apiGet<ClearanceMeta>(`${BASE}/meta`);
}

export function listProfiles(params: {
  country?: string;
  companyKey?: string;
  activeOnly?: boolean;
} = {}): Promise<ClearanceProfile[]> {
  return apiGet<ClearanceProfile[]>(
    `${BASE}/profiles/${qs({
      country: params.country,
      company_key: params.companyKey,
      active_only: params.activeOnly,
    })}`,
  );
}

/**
 * Register a legal entity with one country platform.
 *
 * Step one of the module, and until now the step with no way in: this screen
 * could read registrations and never make one, so a new installation had an
 * empty list, nothing to file a document under, and no button anywhere that
 * would change that.
 *
 * `sandbox` is left to the server's default of true rather than sent as false,
 * and the form keeps it that way until somebody turns it off deliberately. The
 * same call with sandbox off is a real filing with a tax authority, and a form
 * that quietly defaults to that is worse than no form.
 */
export function createProfile(body: ProfileWriteBody): Promise<ClearanceProfile> {
  return apiPost<ClearanceProfile, ProfileWriteBody>(`${BASE}/profiles/`, body);
}

/** A full replacement, matching the PUT on the router. Send every field. */
export function updateProfile(
  profileId: string,
  body: ProfileWriteBody,
): Promise<ClearanceProfile> {
  return apiPut<ClearanceProfile, ProfileWriteBody>(`${BASE}/profiles/${profileId}`, body);
}

/**
 * Remove a registration.
 *
 * The server refuses this while documents are filed under it, which is the
 * behaviour to want: the registration is the only record of the identity those
 * documents were sent with, and an authority that asks will ask about it.
 * Deactivating with `is_active` is the way to retire one that has history.
 */
export function deleteProfile(profileId: string): Promise<void> {
  return apiDelete(`${BASE}/profiles/${profileId}`);
}

/**
 * Prepare one invoice for one country platform.
 *
 * Answers with the document and the findings from the check the server runs on
 * the way in, so a national field that is missing is named at once rather than
 * at submission time.
 */
export function createDocument(body: DocumentCreateBody): Promise<DocumentSaveResult> {
  return apiPost<DocumentSaveResult, DocumentCreateBody>(`${BASE}/documents/`, body);
}

/** Correct a document that has not been sent yet. Also a full replacement. */
export function updateDocument(
  documentId: string,
  body: DocumentUpdateBody,
): Promise<DocumentSaveResult> {
  return apiPut<DocumentSaveResult, DocumentUpdateBody>(`${BASE}/documents/${documentId}`, body);
}

export function listDocuments(params: {
  projectId: string;
  country?: string;
  status?: string;
  regime?: string;
  invoiceId?: string;
}): Promise<ClearanceDocument[]> {
  return apiGet<ClearanceDocument[]>(
    `${BASE}/documents/${qs({
      project_id: params.projectId,
      country: params.country,
      status: params.status,
      regime: params.regime,
      invoice_id: params.invoiceId,
    })}`,
  );
}

export function getDocument(documentId: string): Promise<ClearanceDocument> {
  return apiGet<ClearanceDocument>(`${BASE}/documents/${documentId}`);
}

export function listDocumentEvents(documentId: string): Promise<ClearanceEvent[]> {
  return apiGet<ClearanceEvent[]>(`${BASE}/documents/${documentId}/events`);
}

/**
 * Exactly the document that was or will be sent.
 *
 * Fetched by hand rather than through `apiGet`, which parses every success body
 * as JSON: this endpoint serves the stored bytes with the stored media type,
 * which is XML for most countries. It is bearer-guarded, so a plain `<a href>`
 * would 401.
 */
export async function fetchDocumentPayload(documentId: string): Promise<StoredPayload> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: '*/*' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${BASE}/documents/${documentId}/payload`, {
    method: 'GET',
    headers,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  return {
    text: await res.text(),
    mediaType: res.headers.get('Content-Type') ?? '',
    filename: match?.[1] ?? `einvoice_${documentId}.xml`,
  };
}

/** Dry run against the country rules. Sends nothing to anybody. */
export function validateDocument(documentId: string): Promise<DocumentSaveResult> {
  return apiPost<DocumentSaveResult>(`${BASE}/documents/${documentId}/validate`);
}

/**
 * Put the document to the platform. Irreversible.
 *
 * `acceptWarnings` is discovered rather than chosen up front: a first attempt
 * is refused with 422 carrying the warnings, and the caller sends again once a
 * human has read them. Errors are never waivable this way.
 */
export function submitDocument(
  documentId: string,
  acceptWarnings = false,
): Promise<SubmissionResult> {
  return apiPost<SubmissionResult, { accept_warnings: boolean }>(
    `${BASE}/documents/${documentId}/submit`,
    { accept_warnings: acceptWarnings },
  );
}

/**
 * Record by hand what the platform did with a document left in doubt.
 *
 * The only way out of `submitted` when the adapter failed before the platform
 * answered. A clearance country refuses this without the identifier, because
 * the invoice is not valid without one.
 */
export function resolveDocument(
  documentId: string,
  body: ResolveBody,
): Promise<ClearanceDocument> {
  return apiPost<ClearanceDocument, ResolveBody>(
    `${BASE}/documents/${documentId}/resolve`,
    body,
  );
}

/** Withdraw a document the platform has already accepted. Irreversible. */
export function cancelDocument(
  documentId: string,
  reason: string,
): Promise<SubmissionResult> {
  return apiPost<SubmissionResult, { reason: string }>(
    `${BASE}/documents/${documentId}/cancel`,
    { reason },
  );
}
