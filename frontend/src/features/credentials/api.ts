// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Typed client for the professional-credentials registry
 * (``backend/app/modules/credentials``, mounted at ``/api/v1/credentials/``).
 *
 * Shapes mirror ``schemas.py`` field for field. Paths mirror ``router.py``
 * exactly, including the trailing slashes: every route there is declared with
 * one except ``/meta``, and hitting the other spelling only works by way of a
 * 307, which is a redirect we would rather not depend on for a POST body.
 *
 * The vocabularies are deliberately NOT duplicated here. ``/meta`` returns the
 * credential-type and status lists already translated for the caller's locale,
 * so the pickers are built from the server's own whitelist and cannot drift
 * from it.
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/** Holder kinds the API validates against (``HOLDER_KINDS``). */
export type HolderKind = 'person' | 'company';

/**
 * Derived credential status (``STATUSES``). Note that only `active`,
 * `suspended` and `revoked` may be *set*; the register computes
 * `expiring_soon` and `expired` from the validity window on every read.
 */
export type CredentialStatus = 'active' | 'expiring_soon' | 'expired' | 'suspended' | 'revoked';

/** The subset a caller is allowed to write (``_MANUAL_STATUSES``). */
export type ManualCredentialStatus = 'active' | 'suspended' | 'revoked';

export const MANUAL_STATUSES: ManualCredentialStatus[] = ['active', 'suspended', 'revoked'];

/** Why a holder fails a requirement (``GAP_REASONS``). */
export type GapReason = 'missing' | 'expired' | 'suspended' | 'revoked' | 'expiring_soon';

/** The audience token meaning "everyone on this project's register". */
export const APPLIES_TO_ALL = 'all';

export interface Credential {
  id: string;
  project_id: string;
  holder_name: string;
  holder_kind: HolderKind;
  holder_user_id: string | null;
  credential_type: string;
  discipline: string | null;
  authority: string | null;
  identifier: string | null;
  jurisdiction: string | null;
  issued_at: string | null;
  valid_until: string | null;
  notify_days_before: number;
  notification_obligation_days: number | null;
  notification_trigger: string | null;
  status: CredentialStatus;
  notes: string;
  metadata: Record<string, unknown>;
  verified_by: string | null;
  verified_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Signed: negative once expired, 0 on expiry day, null when perpetual. */
  days_until_expiry: number | null;
  /** The stored status column disagrees with the derived one. */
  status_is_stale: boolean;
}

export interface CredentialCreatePayload {
  project_id: string;
  holder_name: string;
  holder_kind: HolderKind;
  holder_user_id?: string | null;
  credential_type: string;
  discipline?: string | null;
  authority?: string | null;
  identifier?: string | null;
  jurisdiction?: string | null;
  issued_at?: string | null;
  valid_until?: string | null;
  notify_days_before?: number;
  notification_obligation_days?: number | null;
  notification_trigger?: string | null;
  status?: ManualCredentialStatus | null;
  notes?: string;
}

/** Every field optional — the API patches only what is sent. */
export type CredentialUpdatePayload = Partial<Omit<CredentialCreatePayload, 'project_id'>>;

export interface Requirement {
  id: string;
  project_id: string;
  credential_type: string;
  /** `all` binds every holder; anything else is matched on the discipline. */
  applies_to: string;
  holder_kind: HolderKind;
  /** True means a gap stops the holder working; false means it is a note. */
  is_blocking: boolean;
  grace_days: number;
  description: string;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface RequirementCreatePayload {
  project_id: string;
  credential_type: string;
  applies_to?: string;
  holder_kind?: HolderKind;
  is_blocking?: boolean;
  grace_days?: number;
  description?: string;
  is_active?: boolean;
}

export type RequirementUpdatePayload = Partial<Omit<RequirementCreatePayload, 'project_id'>>;

export interface ComplianceGap {
  requirement_id: string;
  credential_type: string;
  applies_to: string;
  reason: GapReason;
  is_blocking: boolean;
  grace_days: number;
  /** Null for `missing` — there is no credential to point at. */
  credential_id: string | null;
  valid_until: string | null;
  days_until_expiry: number | null;
  /** A lapse still inside the grace window: reportable, not yet stopping work. */
  within_grace: boolean;
}

export interface ComplianceHolderRow {
  holder_name: string;
  holder_kind: HolderKind;
  holder_user_id: string | null;
  discipline: string | null;
  /** The headline: can this person or firm work today. */
  is_blocked: boolean;
  gaps: ComplianceGap[];
  satisfied_count: number;
  /** Satisfied requirements met by a credential nobody has checked. */
  unverified_count: number;
}

export interface ComplianceReport {
  project_id: string;
  as_of: string;
  requirement_count: number;
  holder_count: number;
  blocked_holder_count: number;
  holders: ComplianceHolderRow[];
  /** Requirements that bind nobody, because no holder on the register matches. */
  unmatched_requirement_ids: string[];
}

export interface CredentialSummary {
  project_id: string;
  as_of: string;
  total: number;
  by_status: Record<string, number>;
  expiring_within_30_days: number;
  expired: number;
  unverified: number;
  perpetual: number;
  /** Rows whose stored status has drifted; run the refresh endpoint. */
  stale_status_count: number;
}

export interface RefreshResult {
  project_id: string;
  as_of: string;
  examined: number;
  updated: number;
}

export interface ValidationFinding {
  rule_id: string;
  severity: string;
  message: string;
  key: string;
  context: Record<string, unknown>;
}

export interface ValidationReport {
  project_id: string;
  status: string;
  /** Null when nothing was checked — an empty register scores nothing. */
  score: number | null;
  error_count: number;
  warning_count: number;
  findings: ValidationFinding[];
}

/** One option in a server-built picker; the label arrives translated. */
export interface MetaOption {
  code: string;
  label: string;
}

export interface CredentialsMeta {
  credential_types: MetaOption[];
  holder_kinds: HolderKind[];
  statuses: MetaOption[];
}

const BASE = '/v1/credentials';

/** Server-built, pre-translated pickers for the type and status vocabularies. */
export async function fetchMeta(): Promise<CredentialsMeta> {
  return apiGet<CredentialsMeta>(`${BASE}/meta`);
}

export async function fetchCredentials(params: {
  project_id: string;
  status?: CredentialStatus | '';
  credential_type?: string;
}): Promise<Credential[]> {
  const qs = new URLSearchParams({ project_id: params.project_id });
  if (params.status) qs.set('status', params.status);
  if (params.credential_type) qs.set('credential_type', params.credential_type);
  return apiGet<Credential[]>(`${BASE}/?${qs.toString()}`);
}

/** Already expired or due inside their reminder window, soonest first. */
export async function fetchExpiringSoon(params: {
  project_id: string;
  limit?: number;
}): Promise<Credential[]> {
  const qs = new URLSearchParams({ project_id: params.project_id });
  if (params.limit) qs.set('limit', String(params.limit));
  return apiGet<Credential[]>(`${BASE}/expiring-soon/?${qs.toString()}`);
}

export async function createCredential(payload: CredentialCreatePayload): Promise<Credential> {
  return apiPost<Credential, CredentialCreatePayload>(`${BASE}/`, payload);
}

export async function updateCredential(
  id: string,
  payload: CredentialUpdatePayload,
): Promise<Credential> {
  return apiPatch<Credential, CredentialUpdatePayload>(`${BASE}/${id}/`, payload);
}

export async function deleteCredential(id: string): Promise<void> {
  await apiDelete(`${BASE}/${id}/`);
}

export interface VerifyPayload {
  /** True records a verification; false clears one (a retraction). */
  verified: boolean;
  /** Date the check was performed. The API defaults to today when omitted. */
  verified_at?: string | null;
  note?: string | null;
}

/**
 * Record that a human checked this credential against its authority.
 *
 * Verification is not validity: the endpoint never changes the status, so an
 * expired ticket that was genuinely checked stays expired.
 */
export async function verifyCredential(
  id: string,
  payload: VerifyPayload,
): Promise<Credential> {
  return apiPost<Credential, VerifyPayload>(`${BASE}/${id}/verify/`, payload);
}

export async function fetchRequirements(params: {
  project_id: string;
  include_inactive?: boolean;
}): Promise<Requirement[]> {
  const qs = new URLSearchParams({ project_id: params.project_id });
  if (params.include_inactive) qs.set('include_inactive', 'true');
  return apiGet<Requirement[]>(`${BASE}/requirements/?${qs.toString()}`);
}

export async function createRequirement(payload: RequirementCreatePayload): Promise<Requirement> {
  return apiPost<Requirement, RequirementCreatePayload>(`${BASE}/requirements/`, payload);
}

export async function updateRequirement(
  id: string,
  payload: RequirementUpdatePayload,
): Promise<Requirement> {
  return apiPatch<Requirement, RequirementUpdatePayload>(`${BASE}/requirements/${id}/`, payload);
}

export async function deleteRequirement(id: string): Promise<void> {
  await apiDelete(`${BASE}/requirements/${id}/`);
}

/** Who may not work today, and what is about to stop them. */
export async function fetchCompliance(projectId: string): Promise<ComplianceReport> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiGet<ComplianceReport>(`${BASE}/compliance/?${qs.toString()}`);
}

export async function fetchSummary(projectId: string): Promise<CredentialSummary> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiGet<CredentialSummary>(`${BASE}/summary/?${qs.toString()}`);
}

export async function fetchValidation(projectId: string): Promise<ValidationReport> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiGet<ValidationReport>(`${BASE}/validate/?${qs.toString()}`);
}

/**
 * Write the derived status back onto rows that have drifted.
 *
 * Reads are already correct without this. Running it brings the indexed column
 * into line and fires the expiry event for anything that lapsed while nobody
 * was editing the register.
 */
export async function refreshStatuses(projectId: string): Promise<RefreshResult> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiPost<RefreshResult>(`${BASE}/refresh-statuses/?${qs.toString()}`);
}
