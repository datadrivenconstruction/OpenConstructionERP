/**
 * Buyer-portal public API helpers.
 *
 * Unlike ``shared/lib/api.ts`` (which auto-injects the internal JWT),
 * the buyer-portal endpoints are PUBLIC — authenticated via the magic-
 * link token in the URL, NOT via the auth-store bearer header. We use
 * raw ``fetch`` to keep the internal token out of these requests.
 *
 * All paths are mounted at ``/api/v1/property-dev/portal/*``.
 */

const PORTAL_BASE = '/api/v1/property-dev/portal';

/* ── Types ─────────────────────────────────────────────────────────── */

export type PortalKycCode =
  | 'passport'
  | 'national_id'
  | 'address_proof'
  | 'income_statement'
  | 'bank_statement'
  | 'tax_return'
  | 'source_of_funds'
  | 'aml_questionnaire'
  | 'power_of_attorney'
  | 'other';

export interface PortalVerifyResponse {
  buyer_id: string;
  buyer_full_name: string;
  reservation_id: string | null;
  sales_contract_id: string | null;
  scope_summary: string;
}

export interface PortalReservationCard {
  id: string;
  reservation_number: string;
  plot_id: string;
  plot_number: string;
  plot_area_m2: string;
  plot_address: string;
  deposit_amount: string;
  currency: string;
  status: string;
  cooling_off_until: string | null;
  expires_at: string | null;
  signed_on: string | null;
}

export interface PortalSalesContractCard {
  id: string;
  contract_number: string;
  plot_id: string;
  signing_date: string | null;
  total_value: string;
  currency: string;
  status: string;
}

export interface PortalInstalmentRow {
  id: string;
  sequence: number;
  milestone_label: string;
  due_date: string | null;
  amount: string;
  amount_paid: string;
  amount_outstanding: string;
  status: 'pending' | 'due' | 'overdue' | 'paid' | 'waived' | 'cancelled';
  paid_at: string | null;
  currency: string;
}

export interface PortalDocumentRow {
  id: string;
  title: string;
  doc_type: string;
  delivered_at: string | null;
  download_url: string;
}

export interface PortalKycRequest {
  code: string;
  label: string;
  description: string;
  is_uploaded: boolean;
}

export interface PortalOverviewResponse {
  buyer_id: string;
  buyer_full_name: string;
  buyer_email: string;
  buyer_language: string;
  development_name: string;
  reservation: PortalReservationCard | null;
  sales_contract: PortalSalesContractCard | null;
  payment_schedule_total: string;
  payment_schedule_paid: string;
  payment_schedule_outstanding: string;
  payment_schedule_currency: string;
  instalments: PortalInstalmentRow[];
  documents: PortalDocumentRow[];
  kyc_requests: PortalKycRequest[];
}

export interface PortalKycUploadResponse {
  document_id: string;
  document_type: string;
  accepted_at: string;
  storage_path: string;
}

export interface PortalContactAgentResponse {
  activity_id: string;
  accepted_at: string;
}

export interface PortalTokenRow {
  id: string;
  buyer_id: string;
  reservation_id: string | null;
  sales_contract_id: string | null;
  jwt_id: string;
  issued_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  issued_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PortalIssueResponse {
  token: string;
  expires_at: string;
  portal_url: string;
  row: PortalTokenRow;
}

/* ── Public (no auth) helpers ──────────────────────────────────────── */

/**
 * Backend 401 ``detail.code`` discriminator. The verify endpoint is
 * single-use (common modern-SaaS convention) so the frontend needs to
 * distinguish "this link was already redeemed" (render the "request a
 * new link" CTA) from the generic invalid/expired/revoked bucket.
 */
export const PORTAL_TOKEN_ALREADY_USED_CODE = 'portal_token_already_used';
export const PORTAL_TOKEN_INVALID_OR_EXPIRED_CODE =
  'portal_token_invalid_or_expired';

/**
 * Extract the discriminator from a 401 body — defensive against
 * misshaped error envelopes (anything that isn't the known code falls
 * back to ``INVALID`` so existing UI states keep working).
 */
function _extract401Code(body: unknown): string {
  if (!body || typeof body !== 'object') return 'INVALID';
  const detail = (body as { detail?: unknown }).detail;
  if (detail && typeof detail === 'object') {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === 'string' && code) return code;
  }
  return 'INVALID';
}

/**
 * Verify a magic-link token.
 *
 * Throws:
 *   - ``"ALREADY_USED"`` when the backend returns 401 with
 *     ``detail.code === 'portal_token_already_used'`` — the magic-link
 *     was previously redeemed and must NOT be retried. The page maps
 *     this to a dedicated CTA via :class:`RecoveryCard`-style messaging.
 *   - ``"INVALID"`` for every other 401 (forged / expired / revoked).
 *   - Generic ``Error(message)`` for other failure statuses.
 */
export async function verifyPortalToken(
  token: string,
): Promise<PortalVerifyResponse> {
  const res = await fetch(`${PORTAL_BASE}/verify/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (res.status === 401) {
    const body = await res.json().catch(() => ({}));
    const code = _extract401Code(body);
    throw new Error(
      code === PORTAL_TOKEN_ALREADY_USED_CODE ? 'ALREADY_USED' : 'INVALID',
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Verify failed (${res.status})`);
  }
  return (await res.json()) as PortalVerifyResponse;
}

/**
 * Fetch the buyer-portal landing-page payload.
 *
 * Same 401 discriminator as :func:`verifyPortalToken` — the overview
 * endpoint does NOT consume the token (single-use is enforced only on
 * ``/verify/``), so in practice this throws ``ALREADY_USED`` only when
 * a verify-and-revoke race left a previously-consumed link behind.
 */
export async function fetchPortalOverview(
  token: string,
): Promise<PortalOverviewResponse> {
  const res = await fetch(
    `${PORTAL_BASE}/buyer/${encodeURIComponent(token)}/overview/`,
    { headers: { Accept: 'application/json' } },
  );
  if (res.status === 401) {
    const body = await res.json().catch(() => ({}));
    const code = _extract401Code(body);
    throw new Error(
      code === PORTAL_TOKEN_ALREADY_USED_CODE ? 'ALREADY_USED' : 'INVALID',
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Overview failed (${res.status})`);
  }
  return (await res.json()) as PortalOverviewResponse;
}

/** Upload a KYC document. ``file`` is the raw browser File object. */
export async function uploadPortalKyc(
  token: string,
  documentType: PortalKycCode,
  file: File,
): Promise<PortalKycUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const url = `${PORTAL_BASE}/buyer/${encodeURIComponent(
    token,
  )}/upload-kyc/?document_type=${encodeURIComponent(documentType)}`;
  const res = await fetch(url, { method: 'POST', body: form });
  if (res.status === 401) throw new Error('INVALID');
  if (res.status === 415) throw new Error('UNSUPPORTED_MEDIA_TYPE');
  if (res.status === 413) throw new Error('FILE_TOO_LARGE');
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Upload failed (${res.status})`);
  }
  return (await res.json()) as PortalKycUploadResponse;
}

/** Send a message to the assigned sales agent. */
export async function contactPortalAgent(
  token: string,
  message: string,
  callbackPhone?: string,
): Promise<PortalContactAgentResponse> {
  const res = await fetch(
    `${PORTAL_BASE}/buyer/${encodeURIComponent(token)}/contact-agent/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        message,
        callback_phone: callbackPhone || null,
      }),
    },
  );
  if (res.status === 401) throw new Error('INVALID');
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessageFromBody(body) ?? `Contact failed (${res.status})`);
  }
  return (await res.json()) as PortalContactAgentResponse;
}

/* ── Internal (JWT-authed) helpers for the manager UI ───────────── */

import { apiPost, apiGet, extractErrorMessageFromBody } from '@/shared/lib/api';

export interface PortalIssueRequest {
  buyer_id: string;
  reservation_id?: string;
  sales_contract_id?: string;
}

/** MANAGER+: mint a fresh buyer-portal link. */
export async function issuePortalToken(
  body: PortalIssueRequest,
): Promise<PortalIssueResponse> {
  return apiPost<PortalIssueResponse, PortalIssueRequest>(
    '/v1/property-dev/portal/issue/',
    body,
  );
}

/** List active (non-revoked, non-expired) tokens for a buyer. */
export async function listBuyerPortalTokens(
  buyerId: string,
): Promise<PortalTokenRow[]> {
  return apiGet<PortalTokenRow[]>(
    `/v1/property-dev/portal/buyer-links/${buyerId}/`,
  );
}

/** MANAGER+: revoke a token row. */
export async function revokePortalToken(tokenId: string): Promise<void> {
  return apiPost<void>(
    `/v1/property-dev/portal/tokens/${tokenId}/revoke/`,
    undefined,
  );
}
