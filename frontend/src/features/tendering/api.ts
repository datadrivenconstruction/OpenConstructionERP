// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Tendering module — integrated-5D-estimating-suite-style addenda + bid leveling.
 *
 * Backed by /api/v1/tendering/ — see backend/app/modules/tendering/router.py
 */

import {
  API_BASE,
  apiGet,
  apiPost,
  apiDelete,
  extractErrorMessageFromBody,
  fetchWithAuth,
} from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface AddendumAckEntry {
  bidder_id: string;
  acknowledged_at: string;
  user_id?: string;
}

export interface Addendum {
  id: string;
  package_id: string;
  revision_no: number;
  title: string;
  body: string | null;
  published_at: string | null;
  published_by_user_id: string | null;
  acknowledged_by: AddendumAckEntry[];
  created_at: string;
  updated_at: string;
}

export interface BidLevelingSummary {
  bid_id: string;
  company_name: string;
  /** Money fields ride as Decimal-as-string in JSON (v3 §10). */
  raw_amount: number | string;
  leveled_amount: number | string;
  matched_lines: number;
  scaled_lines: number;
  imputed_lines: number;
  currency: string;
}

export interface LevelingMatrixCell {
  bid_id: string;
  company_name: string;
  raw_total: number;
  leveled_total: number;
  status: '' | 'matched' | 'scaled' | 'imputed';
  /** Money field - Decimal-as-string in JSON (v3 §10). */
  unit_rate: number | string;
}

export interface LevelingMatrixRow {
  position_id: string | null;
  line_code: string;
  description: string;
  unit: string;
  reference_quantity: number;
  reference_rate: number;
  reference_total: number;
  cells: LevelingMatrixCell[];
}

export interface LevelingMatrix {
  package_id: string;
  package_name: string;
  /** ISO currency the matrix is computed in (the package currency). */
  currency: string;
  /** Bids excluded because they were quoted in a different currency. */
  excluded_off_currency: number;
  bid_summaries: BidLevelingSummary[];
  rows: LevelingMatrixRow[];
}

export interface LevelBidsResponse {
  package_id: string;
  package_name: string;
  /** ISO currency the leveling was computed in (the package currency). */
  currency: string;
  /** Bids excluded because they were quoted in a different currency. */
  excluded_off_currency: number;
  bid_count: number;
  reference_line_count: number;
  bid_summaries: BidLevelingSummary[];
}

/* ── Addenda ──────────────────────────────────────────────────────────── */

export function listAddenda(packageId: string): Promise<Addendum[]> {
  return apiGet<Addendum[]>(`/v1/tendering/packages/${packageId}/addenda/`);
}

export function createAddendum(
  packageId: string,
  body: { title: string; body?: string },
): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/tendering/packages/${packageId}/addenda/`, body);
}

export function publishAddendum(addendumId: string): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/tendering/addenda/${addendumId}/publish/`, {});
}

/** Minimal bidder shape needed to record an addendum acknowledgement. */
export interface BidderSummary {
  id: string;
  company_name: string;
}

export function listPackageBidders(
  packageId: string,
): Promise<BidderSummary[]> {
  return apiGet<BidderSummary[]>(
    `/v1/tendering/packages/${packageId}/bids/`,
  );
}

export function acknowledgeAddendum(
  addendumId: string,
  bidderId: string,
): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/tendering/addenda/${addendumId}/acknowledge/`, {
    bidder_id: bidderId,
  });
}

/* ── Bid leveling ─────────────────────────────────────────────────────── */

export function levelBids(packageId: string): Promise<LevelBidsResponse> {
  return apiPost<LevelBidsResponse>(
    `/v1/tendering/packages/${packageId}/level-bids/`,
    {},
  );
}

export function getLevelingMatrix(packageId: string): Promise<LevelingMatrix> {
  return apiGet<LevelingMatrix>(
    `/v1/tendering/packages/${packageId}/leveling-matrix/`,
  );
}

/* ── Package scope ────────────────────────────────────────────────────── */

export interface PackageScopeSection {
  id: string;
  ordinal: string;
  description: string;
  position_count: number;
}

/**
 * Which part of the bill a package was raised over. Levelling already narrows
 * to this scope, so the number a bidder is measured against depends on it;
 * `sections_recorded` is false when the sections had to be derived from a flat
 * position list rather than read from the package's own metadata.
 */
export interface PackageScope {
  package_id: string;
  boq_id: string | null;
  boq_name: string;
  covers_whole_bill: boolean;
  sections_recorded: boolean;
  included_position_count: number;
  boq_position_count: number;
  sections: PackageScopeSection[];
}

export function getPackageScope(packageId: string): Promise<PackageScope> {
  return apiGet<PackageScope>(`/v1/tendering/packages/${packageId}/scope`);
}

/* ── Award record (Vergabevermerk) ─────────────────────────────────────── */

/** One fact the procedure itself recorded. `key` is a code, the label is ours. */
export interface AwardRecordFact {
  key: string;
  text: string;
  /** Money field - Decimal-as-string in JSON (v3 §10). */
  amount: string | null;
  currency: string;
  count: number | null;
  at: string | null;
  /** A status code the fact carries, such as a bid's own status. */
  state: string;
}

export interface AwardRecordStatement {
  text: string;
  value: string;
  recorded_at: string | null;
  recorded_by: string | null;
}

/**
 * One section of the record. `procedure` sections are assembled from what the
 * procedure recorded; `reasoning` sections are what a person had to write.
 * `not_due_yet` means the procedure has not reached that stage, so it is not a
 * gap; only `missing` is.
 */
export interface AwardRecordSection {
  key: string;
  source: 'procedure' | 'reasoning';
  state: 'recorded' | 'missing' | 'not_due_yet';
  facts: AwardRecordFact[];
  statement: string;
  value: string;
  recorded_at: string | null;
  recorded_by: string | null;
  superseded: AwardRecordStatement[];
}

export interface AwardRecordGap {
  section: string;
  source: string;
}

export interface AwardRecord {
  package_id: string;
  package_name: string;
  project_name: string;
  /** The package's lifecycle status, which is the stage the record stands at. */
  stage: string;
  currency: string;
  /** False until a person writes the first statement; nothing is stored before that. */
  started: boolean;
  started_at: string | null;
  is_complete: boolean;
  sections: AwardRecordSection[];
  gaps: AwardRecordGap[];
}

export function getAwardRecord(packageId: string): Promise<AwardRecord> {
  return apiGet<AwardRecord>(`/v1/tendering/packages/${packageId}/award-record/`);
}

/**
 * Write one statement into the record. Statements are append-only: writing a
 * section again supersedes the earlier statement and leaves it readable.
 */
export function recordAwardRecordNote(
  packageId: string,
  body: { section: string; text: string; value?: string },
): Promise<AwardRecord> {
  return apiPost<AwardRecord>(
    `/v1/tendering/packages/${packageId}/award-record/notes/`,
    body,
  );
}

/* ── Distribution ─────────────────────────────────────────────────────── */

export interface Recipient {
  id: string;
  company_name: string;
  email: string;
  subcontractor_id: string | null;
  contact_id: string | null;
  /** "pending" before the first send, then "sent" or "failed". */
  status: string;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface DistributeResultEntry {
  recipient_id: string;
  company_name: string;
  email: string;
  status: 'sent' | 'failed' | 'skipped';
  detail: string;
}

export interface DistributeResponse {
  package_id: string;
  package_name: string;
  /** Resolved email backend ("console" | "smtp" | "noop" | "memory"). */
  backend: string;
  /** True only when EMAIL_BACKEND=smtp and SMTP_HOST is configured. */
  smtp_configured: boolean;
  sent_count: number;
  failed_count: number;
  skipped_count: number;
  results: DistributeResultEntry[];
}

export function listRecipients(packageId: string): Promise<Recipient[]> {
  return apiGet<Recipient[]>(
    `/v1/tendering/packages/${packageId}/recipients/`,
  );
}

export function addRecipient(
  packageId: string,
  body: { company_name: string; email: string; subcontractor_id?: string | null },
): Promise<Recipient> {
  return apiPost<Recipient>(
    `/v1/tendering/packages/${packageId}/recipients/`,
    body,
  );
}

export interface RecipientImportRow {
  line: number;
  company: string;
  contact_name: string;
  email: string;
  trade: string;
  vat_id: string;
  /** Stable codes: company_missing, email_invalid, duplicate_in_file, already_invited. */
  issues: string[];
  valid: boolean;
}

export interface RecipientImportPreview {
  total: number;
  valid: number;
  rows: RecipientImportRow[];
}

export interface RecipientImportResult {
  added: Recipient[];
  skipped: RecipientImportRow[];
  contacts_created: number;
  contacts_linked: number;
}

/** Check a CSV/XLSX recipient file (`confirm` false) or add its valid rows (`confirm` true). */
export async function importRecipients<T extends RecipientImportPreview | RecipientImportResult>(
  packageId: string,
  file: File,
  confirm: boolean,
): Promise<T> {
  const body = new FormData();
  body.append('file', file);
  const url = `${API_BASE}/v1/tendering/packages/${packageId}/recipients/import/${confirm ? '' : 'preview/'}`;
  const response = await fetchWithAuth(url, { method: 'POST', body });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(payload) ?? `HTTP ${response.status}`);
  return payload as T;
}

export function removeRecipient(
  packageId: string,
  recipientId: string,
): Promise<void> {
  return apiDelete(
    `/v1/tendering/packages/${packageId}/recipients/${recipientId}`,
  );
}

export function distributePackage(
  packageId: string,
  body: { recipient_ids?: string[]; resend?: boolean; message?: string },
): Promise<DistributeResponse> {
  return apiPost<DistributeResponse>(
    `/v1/tendering/packages/${packageId}/distribute/`,
    body,
  );
}
