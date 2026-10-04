// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
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
}

export interface BidPortalDraft {
  /** Line id -> unit price as a dot-decimal string. */
  unit_prices: Record<string, string>;
  notes: string;
  saved_at: string | null;
}

export type BidPortalState = 'open' | 'submitted' | 'closed';

export interface BidPortalView {
  state: BidPortalState;
  package_name: string;
  package_description: string;
  deadline: string | null;
  currency: string;
  project_name: string;
  buyer_name: string;
  bidder_company: string;
  expires_at: string;
  lines: BidPortalLine[];
  draft: BidPortalDraft;
  submitted_at: string | null;
  bid_amount: string | null;
  item_count: number;
  unpriced_count: number;
}

export interface BidPortalPricesBody {
  unit_prices: Record<string, string>;
  notes: string;
  currency: string;
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
  | 'rate_limited'
  | 'unknown';

export class BidPortalError extends Error {
  constructor(
    public code: BidPortalErrorCode,
    public status: number,
    public lineErrors: Array<{ line_id: string; reason: string }> = [],
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
  nothing_priced: 'nothing_priced',
  rate_limited: 'rate_limited',
  invalid_unit_prices: 'invalid_prices',
  currency_mismatch: 'currency_mismatch',
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
    const d = detail as { code: string; errors?: Array<{ line_id: string; reason: string }> };
    return new BidPortalError(DETAIL_CODES[d.code] ?? 'unknown', res.status, d.errors ?? []);
  }
  if (res.status === 404) return new BidPortalError('not_found', 404);
  if (res.status === 429) return new BidPortalError('rate_limited', 429);
  return new BidPortalError('unknown', res.status);
}

async function call(token: string, path: string, init?: RequestInit): Promise<BidPortalView> {
  const res = await fetch(`/api/v1/tendering/bid-portal/${encodeURIComponent(token)}/${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
  });
  if (!res.ok) throw await toError(res);
  return (await res.json()) as BidPortalView;
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
