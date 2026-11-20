// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Tendering module — integrated-5D-estimating-suite-style addenda + bid leveling.
 *
 * Backed by /api/v1/bid-management/tenders/main-contract/ — see backend/app/modules/tendering/router.py
 */

import {
  API_BASE,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  apiDelete,
  extractErrorMessageFromBody,
  fetchWithAuth,
} from '@/shared/lib/api';
import { fetchAllPages } from '@/shared/lib/apiHelpers';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface AddendumAckEntry {
  bidder_id: string;
  acknowledged_at: string;
  user_id?: string;
}

export interface AddendumDocumentChange {
  document_id?: string | null;
  drawing_number?: string;
  title: string;
  revision?: string;
  note?: string;
  superseded?: boolean;
  current_document_id?: string | null;
}

export type BoqChangeOp = 'add' | 'change' | 'delete';

export interface AddendumBoqChange {
  op: BoqChangeOp;
  position_id?: string | null;
  ordinal: string;
  description: string;
  unit: string;
  quantity_before?: number | string | null;
  quantity_after?: number | string | null;
  description_before?: string | null;
}

export interface AddendumNotified {
  recipient_id: string;
  status: 'sent' | 'failed';
  at: string;
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
  document_changes?: AddendumDocumentChange[];
  boq_changes?: AddendumBoqChange[];
  boq_revision_no?: number | null;
  previous_deadline?: string | null;
  new_deadline?: string | null;
  source_clarification_id?: string | null;
  notified?: AddendumNotified[];
  /** Invited firms that have not acknowledged this published addendum. */
  pending_recipient_ids?: string[];
}

export interface AddendumCreateBody {
  title: string;
  body?: string;
  document_changes?: AddendumDocumentChange[];
  boq_changes?: AddendumBoqChange[];
  new_deadline?: string;
  source_clarification_id?: string;
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
  return apiGet<Addendum[]>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/addenda/`);
}

export function createAddendum(
  packageId: string,
  body: AddendumCreateBody,
): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/addenda/`, body);
}

export function publishAddendum(addendumId: string): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/bid-management/tenders/main-contract/addenda/${addendumId}/publish/`, {});
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
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/bids/`,
  );
}

export function acknowledgeAddendum(
  addendumId: string,
  bidderId: string,
): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/bid-management/tenders/main-contract/addenda/${addendumId}/acknowledge/`, {
    bidder_id: bidderId,
  });
}

/* ── Clarifications (bidder Q&A) ──────────────────────────────────────── */

export type ClarificationStatus = 'open' | 'answered' | 'published';

export interface Clarification {
  id: string;
  package_id: string;
  number: number;
  question: string;
  answer: string | null;
  status: ClarificationStatus;
  recipient_id: string | null;
  asked_by_email: string | null;
  asked_at: string;
  answered_at: string | null;
  published_at: string | null;
  addendum_id: string | null;
  days_before_closing: number | null;
}


export async function listClarifications(packageId: string): Promise<Clarification[]> {
  const { items } = await fetchAllPages<Clarification>((offset, limit) =>
    apiGet<{ items: Clarification[] }>(
      `/v1/bid-management/tenders/main-contract/packages/${packageId}/clarifications/?offset=${offset}&limit=${limit}`,
    ),
  );
  return items;
}

export function createClarification(
  packageId: string,
  body: { question: string; recipient_id?: string; asked_by_email?: string },
): Promise<Clarification> {
  return apiPost<Clarification>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/clarifications/`, body);
}

export function answerClarification(
  packageId: string,
  clarificationId: string,
  answer: string,
): Promise<Clarification> {
  return apiPost<Clarification>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/clarifications/${clarificationId}/answer/`, { answer });
}

export function publishClarification(
  packageId: string,
  clarificationId: string,
): Promise<Clarification> {
  return apiPost<Clarification>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/clarifications/${clarificationId}/publish/`, {});
}

export function promoteClarification(
  packageId: string,
  clarificationId: string,
): Promise<Addendum> {
  return apiPost<Addendum>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/clarifications/${clarificationId}/promote/`, {});
}

/* ── Timeline and jurisdiction rules ──────────────────────────────────── */

export interface TenderTimelineEvent {
  kind: 'issued' | 'questions_closed' | 'addendum' | 'deadline_extended' | 'closing';
  at: string;
  label: string;
  ref_id: string | null;
  past: boolean;
}

export interface TenderRules {
  country_code: string;
  label: string;
  addendum_min_days_before_closing: number | null;
  answer_min_days_before_closing: number | null;
  questions_close_days_before_closing: number | null;
  bid_validity_days: number | null;
  extend_deadline_if_late_addendum: boolean;
  acknowledgement: string;
  public_notice_of_changes: string;
  source: string;
  statute_reference: string;
  confidence: string | number;
}

export interface TenderTimeline {
  package_id: string;
  events: TenderTimelineEvent[];
  rules: TenderRules | null;
}

export function getTenderTimeline(packageId: string): Promise<TenderTimeline> {
  return apiGet<TenderTimeline>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/timeline/`);
}

export interface AddendaValidationResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface AddendaValidation {
  package_id: string;
  passed: boolean;
  results: AddendaValidationResult[];
  rules?: TenderRules | null;
}

export function getAddendaValidation(packageId: string): Promise<AddendaValidation> {
  return apiGet<AddendaValidation>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/addenda/validation/`);
}

/* ── Bid leveling ─────────────────────────────────────────────────────── */

export function levelBids(packageId: string): Promise<LevelBidsResponse> {
  return apiPost<LevelBidsResponse>(
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/level-bids/`,
    {},
  );
}

export function getLevelingMatrix(packageId: string): Promise<LevelingMatrix> {
  return apiGet<LevelingMatrix>(
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/leveling-matrix/`,
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
  return apiGet<PackageScope>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/scope`);
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
  return apiGet<AwardRecord>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/award-record/`);
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
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/award-record/notes/`,
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
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/recipients/`,
  );
}

export function addRecipient(
  packageId: string,
  body: { company_name: string; email: string; subcontractor_id?: string | null },
): Promise<Recipient> {
  return apiPost<Recipient>(
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/recipients/`,
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
  const url = `${API_BASE}/v1/bid-management/tenders/main-contract/packages/${packageId}/recipients/import/${confirm ? '' : 'preview/'}`;
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
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/recipients/${recipientId}`,
  );
}

export function distributePackage(
  packageId: string,
  body: { recipient_ids?: string[]; resend?: boolean; message?: string },
): Promise<DistributeResponse> {
  return apiPost<DistributeResponse>(
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/distribute/`,
    body,
  );
}

/* ── Sealed submission mode ───────────────────────────────────────────── */

export type SubmissionMode = 'informal' | 'sealed';
export type SealedState = 'sealed' | 'awaiting_second' | 'opened';

export interface SealedInfo {
  state: SealedState;
  dual_opening: boolean;
  deadline_utc: string | null;
  first_approver_id: string | null;
  first_approved_at: string | null;
  opened_at: string | null;
  opened_by: string | null;
}

export interface SealedSubmission {
  bid_id: string;
  company_name: string;
  received_at: string;
  sha256: string;
}

export interface SealedStatus {
  package_id: string;
  mode: SubmissionMode;
  state: SealedState;
  dual_opening: boolean;
  deadline_utc: string | null;
  server_now: string;
  deadline_passed: boolean;
  first_approver_id: string | null;
  first_approved_at: string | null;
  opened_at: string | null;
  opened_by: string | null;
  submissions: SealedSubmission[];
}

export interface BidIntegrity {
  bid_id: string;
  receipt_sha256: string;
  current_sha256: string;
  received_at: string;
  intact: boolean;
}

export function setSubmissionMode(
  packageId: string,
  body: { mode: SubmissionMode; dual_opening: boolean },
): Promise<unknown> {
  return apiPut<unknown>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/submission-mode/`, body);
}

export function getSealedStatus(packageId: string): Promise<SealedStatus> {
  return apiGet<SealedStatus>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/sealed/`);
}

export function openSealedBids(packageId: string): Promise<SealedStatus> {
  return apiPost<SealedStatus>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/sealed/open/`, {});
}

export function getBidIntegrity(bidId: string): Promise<BidIntegrity> {
  return apiGet<BidIntegrity>(`/v1/bid-management/tenders/main-contract/bids/${bidId}/integrity/`);
}

/** The backend error code (detail) of a failed call, or an empty string. */
export function sealedErrorCode(err: unknown): string {
  const body = (err as { body?: { detail?: unknown } } | null)?.body;
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && 'code' in d) return String((d as { code: unknown }).code);
  return '';
}

/* ── GAEB X84 bid return ─────────────────────────────────────────────── */

export interface X84LineCheck {
  ordinal: string;
  position_id: string | null;
  description: string;
  unit: string;
  quantity: string;
  unit_rate: string | null;
  /** Stable codes: unknown_position, unit_mismatch, quantity_changed, unpriced, duplicate_position. */
  issues: string[];
}

export interface X84ImportPreview {
  filename: string;
  sha256: string;
  da_kind: string;
  currency: string;
  tender_currency: string;
  /** Stable codes: not_x84, currency_mismatch, no_bill, nothing_priced. */
  file_issues: string[];
  lines: X84LineCheck[];
  matched: number;
  priced: number;
  missing_ordinals: string[];
  total_amount: string;
  blocking: boolean;
}

/** Check a priced X84 against the package (no `company`) or add it as a bid. */
export async function importX84Bid<T>(
  packageId: string,
  file: File,
  company?: { name: string; email: string },
): Promise<T> {
  const body = new FormData();
  body.append('file', file);
  if (company) {
    body.append('company_name', company.name);
    body.append('contact_email', company.email);
  }
  const url = `${API_BASE}/v1/bid-management/tenders/main-contract/packages/${packageId}/bids/import-x84/${company ? '' : 'preview/'}`;
  const response = await fetchWithAuth(url, { method: 'POST', body });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(payload) ?? `HTTP ${response.status}`);
  return payload as T;
}

/* ── Package contents: preview, budget, resource scope (#571, #576) ────── */

export type ScopeKind = 'labor' | 'material' | 'machinery' | 'equipment' | 'subcontractor' | 'other';

export const SCOPE_KINDS: ScopeKind[] = ['labor', 'material', 'machinery', 'equipment', 'subcontractor', 'other'];

export interface PackagePreviewComponent {
  key: string;
  name: string;
  code: string | null;
  kind: ScopeKind;
  unit: string;
  /** Per unit of the line, decimal strings. */
  quantity: string;
  unit_cost: string;
  included: boolean;
}

export interface PackagePreviewLine {
  id: string;
  kind: 'section' | 'item';
  ordinal: string;
  short_text: string;
  long_text: string;
  unit: string;
  quantity: string;
  depth: number;
  supplied_by_others: string[];
  budget_rate: string | null;
  budget_total: string | null;
  split: boolean;
  unsplittable: boolean;
  components: PackagePreviewComponent[];
}

export interface PackagePreviewRecipient {
  company_name: string;
  email: string;
  status: string;
  link_status: string | null;
}

export interface PackagePreviewDocument {
  addendum_revision: number;
  addendum_title: string;
  published: boolean;
  title: string;
  drawing_number: string;
  revision: string;
  document_id: string | null;
}

export interface PackagePreviewIssue {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface PackagePreview {
  package_id: string;
  name: string;
  description: string;
  status: string;
  deadline: string | null;
  currency: string;
  lines: PackagePreviewLine[];
  item_count: number;
  budget_computed: string;
  budget_override: string | null;
  budget_total: string;
  scope_kinds: ScopeKind[];
  scope_active: boolean;
  recipients: PackagePreviewRecipient[];
  documents: PackagePreviewDocument[];
  bid_count: number;
  validation: PackagePreviewIssue[];
}

export function packagePreviewQueryKey(packageId: string) {
  return ['tendering-package-preview', packageId] as const;
}

export function getPackagePreview(packageId: string): Promise<PackagePreview> {
  return apiGet<PackagePreview>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/preview/`);
}

export interface PackageBudgetPatch {
  /** Decimal string, or null to clear and use the computed sum. */
  budget_override?: string | null;
  /** Null restores whole lines. */
  resource_scope?: { kinds: ScopeKind[]; excluded: Record<string, string[]> } | null;
}

export function patchPackageBudget(packageId: string, body: PackageBudgetPatch): Promise<unknown> {
  return apiPatch(`/v1/bid-management/tenders/main-contract/packages/${packageId}`, body);
}

/* ── Delete or cancel a package (#575) ─────────────────────────────────── */

export function deletePackage(packageId: string): Promise<void> {
  return apiDelete(`/v1/bid-management/tenders/main-contract/packages/${packageId}`);
}

export function cancelPackage(packageId: string, reason: string): Promise<unknown> {
  return apiPost(`/v1/bid-management/tenders/main-contract/packages/${packageId}/cancel/`, { reason });
}

/* ── Bids entered by the buyer (#573) ──────────────────────────────────── */

export function putBuyerPrices(
  bidId: string,
  body: { unit_prices: Record<string, string>; notes?: string },
): Promise<unknown> {
  return apiPut(`/v1/bid-management/tenders/main-contract/bids/${bidId}/prices/`, body);
}

/* ── Package header, rejections in bulk, filing the award ─────────────── */

export interface IssuingEntity {
  id: string;
  code: string;
  name: string;
  /** `package` when the package names it, `project` when it comes from the project. */
  source: 'package' | 'project';
}

export interface PackageHeader {
  package_id: string;
  legal_entity_id: string | null;
  trade: string | null;
  cost_line_id: string | null;
  issue_date: string | null;
  questions_until: string | null;
  bids_due: string | null;
  award_planned: string | null;
  buyer_id: string | null;
  estimator_id: string | null;
  site_manager_id: string | null;
  approver_id: string | null;
  issuing_entity: IssuingEntity | null;
  cost_line: { id: string; code: string; description: string; budget: string } | null;
  /** Decimal string in the project currency. */
  budget: string;
  currency: string;
  active_entity_count: number;
  warnings: string[];
}

export type PackageHeaderInput = Partial<
  Pick<
    PackageHeader,
    | 'legal_entity_id'
    | 'trade'
    | 'cost_line_id'
    | 'issue_date'
    | 'questions_until'
    | 'bids_due'
    | 'award_planned'
    | 'buyer_id'
    | 'estimator_id'
    | 'site_manager_id'
    | 'approver_id'
  >
>;

export type RejectionState = 'pending' | 'sent' | 'failed' | 'no_email';

export interface RejectionRow {
  bid_id: string;
  company_name: string;
  email: string;
  notified_at: string | null;
  state: RejectionState;
  last_error: string | null;
}

export interface RejectionsPreview {
  package_id: string;
  awarded: boolean;
  issuing_entity: IssuingEntity | null;
  rows: RejectionRow[];
  pending: number;
}

export interface RejectionsSendResult extends RejectionsPreview {
  sent: number;
  failed: number;
  filed: number;
  backend: string;
  smtp_configured: boolean;
}

export interface FiledDocument {
  kind: 'contract' | 'award_record' | 'award_letter' | 'rejection_letter';
  document_id: string | null;
  name: string;
  state: 'filed' | 'already_filed' | 'skipped';
  reason: string | null;
}

export function getPackageHeader(packageId: string): Promise<PackageHeader> {
  return apiGet<PackageHeader>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/header/`);
}

export function savePackageHeader(packageId: string, body: PackageHeaderInput): Promise<PackageHeader> {
  return apiPut<PackageHeader>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/header/`, body);
}

export function getRejections(packageId: string): Promise<RejectionsPreview> {
  return apiGet<RejectionsPreview>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/rejections/`);
}

export function sendRejections(packageId: string, bidIds: string[] = []): Promise<RejectionsSendResult> {
  return apiPost<RejectionsSendResult>(`/v1/bid-management/tenders/main-contract/packages/${packageId}/rejections/send/`, {
    bid_ids: bidIds,
  });
}

export function fileAwardDocuments(packageId: string): Promise<{ package_id: string; documents: FiledDocument[] }> {
  return apiPost<{ package_id: string; documents: FiledDocument[] }>(
    `/v1/bid-management/tenders/main-contract/packages/${packageId}/award-documents/file/`,
    {},
  );
}
