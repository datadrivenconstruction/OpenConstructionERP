// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the E-Signature Registry.
 *
 * All endpoints are prefixed with /v1/signing/. The registry is a
 * jurisdiction-neutral attestation log: it records who must sign a
 * document, who signed or declined, against which content hash and with
 * which certificate metadata. It never accepts a private key, a
 * certificate file or a password, and it names no vendor - a signature
 * is described only by its legal capability.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Jurisdiction-neutral signature capability families. */
export type SigningCapability =
  | 'qualified_electronic'
  | 'advanced_electronic'
  | 'simple_electronic'
  | 'digital_certificate';

/** Full session lifecycle. Only draft / awaiting_signatures are caller-settable. */
export type SigningSessionStatus =
  | 'draft'
  | 'awaiting_signatures'
  | 'partially_signed'
  | 'fully_signed'
  | 'declined'
  | 'expired';

export type SignatureStatus = 'signed' | 'declined';

export interface SignatoryEntry {
  name: string;
  role: string;
  /** Whether this signatory must sign for the session to reach fully_signed. */
  required?: boolean;
}

export interface SignatureResponse {
  id: string;
  session_id: string;
  project_id: string;
  signatory_name: string;
  signatory_role: string;
  signed_at: string;
  cert_subject: string | null;
  cert_valid_until: string | null;
  content_hash: string;
  status: SignatureStatus;
  notes: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** True when this signature's content hash no longer matches the session's current hash. */
  stale: boolean | null;
}

export interface SigningSession {
  id: string;
  project_id: string;
  document_ref: string;
  document_content_hash: string;
  /** The capability the session REQUIRES of the signature. */
  provider_capability: SigningCapability;
  /**
   * What the resolved provider actually delivers, taken from the provider's
   * own capability. Never defaulted to `provider_capability`: core ships one
   * provider, which performs no cryptography and delivers `simple_electronic`,
   * so the two differ for every stronger tier. `null` means no derivation has
   * recorded one yet, and must render as that rather than as the requirement.
   * Typed wider than `SigningCapability` because an adapter pack may introduce
   * a capability this build's vocabulary does not know.
   */
  delivered_capability: string | null;
  signatory_map: SignatoryEntry[];
  status: SigningSessionStatus;
  expires_at: string | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  required_count: number;
  signed_count: number;
  declined_count: number;
  signatures: SignatureResponse[];
}

export interface CertExpiryFlag {
  session_id: string;
  signature_id: string;
  signatory_name: string;
  signatory_role: string;
  cert_subject: string | null;
  cert_valid_until: string;
  days_until_expiry: number;
  expired: boolean;
}

export interface SigningSessionFilters {
  project_id: string;
  status?: SigningSessionStatus | '';
  capability?: SigningCapability | '';
}

export interface CreateSigningSessionPayload {
  project_id: string;
  document_ref: string;
  document_content_hash: string;
  provider_capability?: SigningCapability;
  signatory_map?: SignatoryEntry[];
  expires_at?: string | null;
  status?: 'draft' | 'awaiting_signatures';
  metadata?: Record<string, unknown>;
}

export interface UpdateSigningSessionPayload {
  document_ref?: string;
  document_content_hash?: string;
  provider_capability?: SigningCapability;
  signatory_map?: SignatoryEntry[];
  expires_at?: string | null;
  status?: 'draft' | 'awaiting_signatures';
  metadata?: Record<string, unknown>;
}

export interface AttestationCreatePayload {
  signatory_name: string;
  signatory_role: string;
  content_hash: string;
  cert_subject?: string | null;
  cert_valid_until?: string | null;
  signed_at?: string | null;
  notes?: string;
}

export interface DeclineCreatePayload {
  signatory_name: string;
  signatory_role: string;
  reason?: string;
}

export interface StaleSignatories {
  session_id: string;
  content_hash: string;
  stale_signatories: string[];
}

export interface SigningManifest {
  session_id?: string;
  [key: string]: unknown;
}

export interface SigningCodeLabel {
  code: string;
  label: string;
}

export interface SigningMeta {
  capabilities: SigningCodeLabel[];
  statuses: SigningCodeLabel[];
  default_provider: Record<string, unknown>;
}

/* ── Sessions CRUD ─────────────────────────────────────────────────────── */

export async function fetchSigningSessions(
  filters: SigningSessionFilters,
): Promise<SigningSession[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.capability) params.set('capability', filters.capability);
  return apiGet<SigningSession[]>(`/v1/signing/sessions/?${params.toString()}`);
}

export async function fetchSigningSession(id: string): Promise<SigningSession> {
  return apiGet<SigningSession>(`/v1/signing/sessions/${id}/`);
}

export async function createSigningSession(
  data: CreateSigningSessionPayload,
): Promise<SigningSession> {
  return apiPost<SigningSession>('/v1/signing/sessions/', data);
}

export async function updateSigningSession(
  id: string,
  data: UpdateSigningSessionPayload,
): Promise<SigningSession> {
  return apiPatch<SigningSession>(`/v1/signing/sessions/${id}/`, data);
}

export async function deleteSigningSession(id: string): Promise<void> {
  await apiDelete(`/v1/signing/sessions/${id}/`);
}

/* ── Attestation / decline ────────────────────────────────────────────── */

export async function attestSigningSession(
  id: string,
  data: AttestationCreatePayload,
): Promise<SigningSession> {
  return apiPost<SigningSession>(`/v1/signing/sessions/${id}/attest`, data);
}

export async function declineSigningSession(
  id: string,
  data: DeclineCreatePayload,
): Promise<SigningSession> {
  return apiPost<SigningSession>(`/v1/signing/sessions/${id}/decline`, data);
}

/* ── Views ─────────────────────────────────────────────────────────────── */

export async function fetchStaleSignatories(
  id: string,
  contentHash?: string,
): Promise<StaleSignatories> {
  const qs = contentHash ? `?content_hash=${encodeURIComponent(contentHash)}` : '';
  return apiGet<StaleSignatories>(`/v1/signing/sessions/${id}/stale${qs}`);
}

export async function fetchSigningManifest(id: string): Promise<SigningManifest> {
  return apiGet<SigningManifest>(`/v1/signing/sessions/${id}/manifest`);
}

export async function fetchExpiringCerts(
  projectId: string,
  withinDays = 30,
): Promise<CertExpiryFlag[]> {
  const params = new URLSearchParams();
  params.set('project_id', projectId);
  params.set('within_days', String(withinDays));
  return apiGet<CertExpiryFlag[]>(`/v1/signing/expiring-certs?${params.toString()}`);
}

export async function fetchSigningMeta(): Promise<SigningMeta> {
  return apiGet<SigningMeta>('/v1/signing/meta');
}

/**
 * Trigger a browser download of a session's manifest as a JSON file. The
 * manifest endpoint returns plain JSON (no binary payload on the backend),
 * so this builds the file client-side rather than fetching a blob.
 *
 * The filename is keyed on the document_ref (the human-meaningful part) plus
 * an 8-char slice of the session id, since a document can be re-submitted
 * across more than one signing session and document_ref alone would collide.
 */
export function downloadSigningManifest(session: SigningSession, manifest: SigningManifest): void {
  const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `signing-manifest-${session.document_ref.replace(/[^\w.-]+/g, '_')}-${session.id.slice(0, 8)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
