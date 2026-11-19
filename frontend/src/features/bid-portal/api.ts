// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bidder price-entry link: public API helpers.
 *
 * A subcontractor opens `/tendering/bid/{token}` without an account; the token in the
 * path is the credential. These calls use raw `fetch` on purpose, like the
 * buyer portal, so the internal JWT of anyone who happens to be logged in on
 * the same browser is never attached to them.
 *
 * Mounted at `/api/v1/tendering/bid-portal/{token}/`.
 */

export interface BidPortalLine {
  id: string;
  kind: 'section' | 'item';
  ordinal: string;
  short_text: string;
  long_text: string;
  unit: string;
  /** Decimal as a string; empty for a section heading. */
  quantity: string;
  depth: number;
  /** Components of the line another party supplies (owner-supplied materials). */
  supplied_by_others?: string[];
}

export interface BidPortalDraft {
  /** Line id -> unit price as a dot-decimal string. */
  unit_prices: Record<string, string>;
  notes: string;
  saved_at: string | null;
  /** unit_price: the bid is the priced lines; lump_sum: one figure for the package. */
  pricing_mode?: BidPricingMode;
  lump_sum?: string | null;
}

export type BidPricingMode = 'unit_price' | 'lump_sum';

export type BidPortalState = 'open' | 'submitted' | 'closed' | 'declined';

export type BidFileKind = 'x84' | 'offer_pdf' | 'attachment';

/** A file this firm uploaded through its link. */
export interface BidPortalFile {
  id: string;
  kind: BidFileKind;
  file_name: string;
  file_size: number;
  sha256: string;
  uploaded_at: string;
}

/** A document the buyer sends out with the package. */
export interface BidPortalDocument {
  id: string;
  name: string;
  file_size: number;
  mime_type: string;
  revision_code?: string | null;
}

export interface BidPortalView {
  state: BidPortalState;
  package_name: string;
  package_description: string;
  deadline: string | null;
  currency: string;
  project_name: string;
  buyer_name: string;
  /** The issuing company has a document logo, served at ``logo/``. */
  buyer_logo?: boolean;
  bidder_company: string;
  expires_at: string;
  lines: BidPortalLine[];
  draft: BidPortalDraft;
  submitted_at: string | null;
  /** Sealed tender: the content stays hidden until the opening. */
  sealed?: boolean;
  receipt_sha256?: string | null;
  received_at?: string | null;
  bid_amount: string | null;
  item_count: number;
  unpriced_count: number;
  declined_at?: string | null;
  decline_reason?: string | null;
  files?: BidPortalFile[];
  documents?: BidPortalDocument[];
}

/** One line of an uploaded X84 matched against the bill. */
export interface X84LineCheck {
  ordinal: string;
  position_id: string | null;
  description: string;
  unit: string;
  quantity: string;
  unit_rate: string | null;
  /** unknown_position, unit_mismatch, quantity_changed, unpriced, duplicate_position. */
  issues: string[];
}

export interface X84RuleResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  suggestion?: string | null;
}

export interface X84Preview {
  filename: string;
  sha256: string;
  file_issues: string[];
  lines: X84LineCheck[];
  matched: number;
  priced: number;
  missing_ordinals: string[];
  total_amount: string;
  blocking: boolean;
  rule_results?: X84RuleResult[];
}

export interface BidPortalPricesBody {
  unit_prices: Record<string, string>;
  notes: string;
  currency: string;
  pricing_mode: BidPricingMode;
  lump_sum: string | null;
}

/** What went wrong, as a code the page turns into a sentence. */
export type BidPortalErrorCode =
  | 'not_found'
  | 'revoked'
  | 'expired'
  | 'already_submitted'
  | 'closed'
  | 'invalid_prices'
  | 'currency_mismatch'
  | 'nothing_priced'
  | 'lump_sum_required'
  | 'lump_sum_invalid'
  | 'rate_limited'
  | 'declined'
  | 'x84_mismatch'
  | 'file_rejected'
  | 'file_too_large'
  | 'too_many_files'
  | 'unknown';

export class BidPortalError extends Error {
  constructor(
    public code: BidPortalErrorCode,
    public status: number,
    public lineErrors: Array<{ line_id: string; reason: string }> = [],
    public preview: X84Preview | null = null,
  ) {
    super(code);
    this.name = 'BidPortalError';
  }
}

const DETAIL_CODES: Record<string, BidPortalErrorCode> = {
  bid_link_not_found: 'not_found',
  bid_link_revoked: 'revoked',
  bid_link_expired: 'expired',
  bid_already_submitted: 'already_submitted',
  tender_closed: 'closed',
  sealed_deadline_passed: 'closed',
  nothing_priced: 'nothing_priced',
  lump_sum_required: 'lump_sum_required',
  lump_sum_invalid: 'lump_sum_invalid',
  rate_limited: 'rate_limited',
  invalid_unit_prices: 'invalid_prices',
  currency_mismatch: 'currency_mismatch',
  bid_declined: 'declined',
  x84_has_blocking_issues: 'x84_mismatch',
  invalid_file_kind: 'file_rejected',
  empty_file: 'file_rejected',
  file_type_not_allowed: 'file_rejected',
  not_a_pdf: 'file_rejected',
  file_too_large: 'file_too_large',
  too_many_files: 'too_many_files',
};

async function toError(res: Response): Promise<BidPortalError> {
  let detail: unknown = null;
  try {
    detail = ((await res.json()) as { detail?: unknown }).detail ?? null;
  } catch {
    detail = null;
  }
  if (typeof detail === 'string') {
    return new BidPortalError(DETAIL_CODES[detail] ?? 'unknown', res.status);
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const d = detail as { code: string; errors?: Array<{ line_id: string; reason: string }>; preview?: X84Preview };
    return new BidPortalError(DETAIL_CODES[d.code] ?? 'unknown', res.status, d.errors ?? [], d.preview ?? null);
  }
  if (res.status === 404) return new BidPortalError('not_found', 404);
  if (res.status === 429) return new BidPortalError('rate_limited', 429);
  if (res.status === 413) return new BidPortalError('file_too_large', 413);
  return new BidPortalError('unknown', res.status);
}

async function callJson<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1/tendering/bid-portal/${encodeURIComponent(token)}/${path}`, {
    ...init,
    // A FormData body sets its own multipart boundary.
    headers: {
      Accept: 'application/json',
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    },
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
  });
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

function call(token: string, path: string, init?: RequestInit): Promise<BidPortalView> {
  return callJson<BidPortalView>(token, path, init);
}

/** Address of the issuing company's logo for a bidder link. */
export function bidPortalLogoUrl(token: string): string {
  return `/api/v1/tendering/bid-portal/${encodeURIComponent(token)}/logo/`;
}

export function fetchBidPortal(token: string): Promise<BidPortalView> {
  return call(token, '');
}

export function saveBidDraft(token: string, body: BidPortalPricesBody): Promise<BidPortalView> {
  return call(token, 'draft/', { method: 'PUT', body: JSON.stringify(body) });
}

export function submitBid(token: string, body: BidPortalPricesBody): Promise<BidPortalView> {
  return call(token, 'submit/', { method: 'POST', body: JSON.stringify(body) });
}

function fileForm(file: File, extra: Record<string, string> = {}): FormData {
  const form = new FormData();
  form.append('file', file);
  for (const [key, value] of Object.entries(extra)) form.append(key, value);
  return form;
}

/** Match a priced X84 against the bill; nothing is stored. */
export function checkBidX84(token: string, file: File): Promise<X84Preview> {
  return callJson<X84Preview>(token, 'x84/check/', { method: 'POST', body: fileForm(file) });
}

/** Submit the bid from a priced X84; refused with the preview when a line does not fit. */
export function submitBidX84(token: string, file: File, notes = ''): Promise<BidPortalView> {
  return call(token, 'x84/', { method: 'POST', body: fileForm(file, { notes }) });
}

export function uploadBidFile(token: string, file: File, kind: 'offer_pdf' | 'attachment'): Promise<BidPortalView> {
  return call(token, 'files/', { method: 'POST', body: fileForm(file, { kind }) });
}

export function declineBid(token: string, reason: string): Promise<BidPortalView> {
  return call(token, 'decline/', { method: 'POST', body: JSON.stringify({ reason }) });
}

/** Download address of a request document for this link. */
export function bidPortalDocumentUrl(token: string, documentId: string): string {
  return `/api/v1/tendering/bid-portal/${encodeURIComponent(token)}/documents/${encodeURIComponent(documentId)}/`;
}

export interface TenderInfoAddendum {
  id: string;
  revision_no: number;
  title: string;
  body: string | null;
  published_at: string | null;
  new_deadline: string | null;
  boq_revision_no: number | null;
  document_changes: Array<{
    drawing_number?: string;
    title: string;
    revision?: string;
    note?: string;
    superseded?: boolean;
  }>;
  acknowledged: boolean;
}

/** A published answer. The asker is never part of it. */
export interface TenderInfoClarification {
  number: number;
  question: string;
  answer: string | null;
  published_at: string | null;
}

export interface TenderInfo {
  deadline: string | null;
  current_boq_revision: number;
  addenda: TenderInfoAddendum[];
  clarifications: TenderInfoClarification[];
}

export function fetchTenderInfo(token: string): Promise<TenderInfo> {
  return callJson<TenderInfo>(token, 'tender-info/');
}

export function askQuestion(token: string, question: string): Promise<{ number: number; status: string }> {
  return callJson(token, 'questions/', { method: 'POST', body: JSON.stringify({ question }) });
}

export function acknowledgeAddendumAsBidder(token: string, addendumId: string): Promise<unknown> {
  return callJson(token, `addenda/${encodeURIComponent(addendumId)}/acknowledge/`, { method: 'POST' });
}
