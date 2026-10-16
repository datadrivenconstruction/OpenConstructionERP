// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Finance module.
 *
 * Backed by /api/v1/finance/ - see backend/app/modules/finance/router.py and
 * schemas.py. The shapes here mirror the Pydantic response models exactly so
 * the page can drop straight onto the API.
 */

import {
  API_BASE,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  downloadWithAuth,
  extractErrorMessageFromBody,
  fetchWithAuth,
} from '@/shared/lib/api';
import { downloadRecordPdf } from '@/shared/lib/documentExport';

/* ── Retention / withholding ledger ───────────────────────────────────── */

/**
 * One retainage rollup line: either a per-counterparty group or a
 * per-(currency, direction) total.
 *
 * Money fields (scheduled / held_to_date / released_to_date / outstanding) are
 * Decimal-as-string. The ``*_pct`` fields are 0-100 percentages as strings, or
 * null when the denominator (held or scheduled retention) is zero - render
 * "n/a" in that case rather than a bogus 0%.
 *
 * Mirrors backend RetentionRollupResponse.
 */
export interface RetentionRollup {
  currency_code: string;
  direction: string; // "payable" | "receivable"
  contact_id: string | null;
  counterparty_name: string | null;
  scheduled: string;
  held_to_date: string;
  released_to_date: string;
  outstanding: string;
  payment_count: number;
  released_pct: string | null;
  outstanding_pct: string | null;
  held_vs_scheduled_pct: string | null;
  earliest_release_date: string | null;
  latest_release_date: string | null;
}

/**
 * Project retention / withholding ledger.
 *
 * ``groups`` are per-counterparty lines (each within one currency and
 * direction); ``totals`` roll them up per (currency, direction). ``as_of`` is
 * the release-date cutoff used to classify retainage as released.
 *
 * Mirrors backend RetentionLedgerResponse.
 */
export interface RetentionLedger {
  project_id: string;
  as_of: string | null;
  groups: RetentionRollup[];
  totals: RetentionRollup[];
}

/**
 * Fetch the project retention / withholding ledger: per-counterparty groups
 * and per-(currency, direction) totals of retention scheduled, held, released
 * and still outstanding. ``asOf`` is the release-date cutoff (defaults to
 * today server-side). Requires the ``finance.read`` permission.
 */
export function getRetentionLedger(
  projectId: string,
  asOf?: string,
): Promise<RetentionLedger> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  if (asOf) qs.set('as_of', asOf);
  return apiGet<RetentionLedger>(`/v1/finance/retention-ledger/?${qs.toString()}`);
}

/** Ageing bucket keys, in reading order. */
export type AgeingBucket = 'current' | '1_30' | '31_60' | '61_90' | 'over_90';

export const AGEING_BUCKETS: readonly AgeingBucket[] = ['current', '1_30', '31_60', '61_90', 'over_90'];

/** One open invoice inside an ageing line. Money is Decimal-as-string. */
export interface AgeingInvoiceLine {
  invoice_id: string;
  invoice_number: string;
  project_id: string;
  invoice_date: string | null;
  due_date: string | null;
  days_past_due: number;
  bucket: AgeingBucket;
  total: string;
  paid: string;
  due: string;
  credit: string;
  retention_held: string;
  retention_released: string;
}

/**
 * Open balances of one counterparty (a line) or a whole scope (a total),
 * within one legal entity, currency and direction. ``buckets`` adds up to
 * ``total_due``; holdback is owed but not due and is reported apart.
 *
 * Mirrors backend AgeingRollupResponse.
 */
export interface AgeingRollup {
  legal_entity_id: string | null;
  legal_entity_name: string | null;
  currency_code: string;
  direction: string;
  contact_id: string | null;
  counterparty_name: string | null;
  buckets: Record<AgeingBucket, string>;
  total_due: string;
  credit: string;
  retention_held: string;
  retention_released: string;
  invoice_count: number;
  oldest_days_past_due: number;
  invoices: AgeingInvoiceLine[];
}

export interface AgeingReport {
  as_of: string;
  buckets: AgeingBucket[];
  groups: AgeingRollup[];
  totals: AgeingRollup[];
  drafts_excluded: number;
}

export interface AgeingQuery {
  /** Narrow to one project; omitted means every project the reader can open. */
  projectId?: string;
  legalEntityId?: string;
  direction?: 'payable' | 'receivable';
  asOf?: string;
}

/**
 * AR / AP ageing as of a date, per legal entity and counterparty. Requires
 * the ``finance.read`` permission; the server scopes it to the projects the
 * reader can open, whatever the filters say.
 */
export function getAgeing(query: AgeingQuery = {}): Promise<AgeingReport> {
  const qs = new URLSearchParams();
  if (query.projectId) qs.set('project_id', query.projectId);
  if (query.legalEntityId) qs.set('legal_entity_id', query.legalEntityId);
  if (query.direction) qs.set('direction', query.direction);
  if (query.asOf) qs.set('as_of', query.asOf);
  const suffix = qs.toString();
  return apiGet<AgeingReport>(`/v1/finance/ageing/${suffix ? `?${suffix}` : ''}`);
}

/* ── Statement of account ─────────────────────────────────────────────── */

export interface AccountStatementLine {
  entry_date: string;
  kind: 'invoice' | 'payment' | 'refund' | string;
  reference: string;
  invoice_id: string;
  project_id: string;
  /** Raises the balance (an invoice or a refund). Decimal as string. */
  charge: string;
  /** Lowers the balance (a payment). Decimal as string. */
  credit: string;
  balance: string;
}

export interface AccountStatement {
  contact_id: string;
  counterparty_name: string | null;
  direction: 'payable' | 'receivable' | string;
  currency_code: string;
  legal_entity_id: string | null;
  legal_entity_name: string | null;
  date_from: string | null;
  date_to: string;
  opening_balance: string;
  closing_balance: string;
  total_charged: string;
  total_credited: string;
  lines: AccountStatementLine[];
  ageing: AgeingRollup[];
}

export interface AccountStatementQuery {
  contactId: string;
  currency: string;
  direction: 'payable' | 'receivable';
  legalEntityId?: string;
  dateFrom?: string;
  dateTo?: string;
}

function statementParams(query: AccountStatementQuery): URLSearchParams {
  const qs = new URLSearchParams({
    contact_id: query.contactId,
    currency: query.currency,
    direction: query.direction,
  });
  if (query.legalEntityId) qs.set('legal_entity_id', query.legalEntityId);
  if (query.dateFrom) qs.set('date_from', query.dateFrom);
  if (query.dateTo) qs.set('date_to', query.dateTo);
  return qs;
}

/**
 * Every posted invoice and payment with one counterparty over a period, with
 * a running balance and the balance brought forward. Requires ``finance.read``;
 * the server reads only the projects the caller can open.
 */
export function getAccountStatement(query: AccountStatementQuery): Promise<AccountStatement> {
  return apiGet<AccountStatement>(`/v1/finance/statement-of-account/?${statementParams(query)}`);
}

/** The same statement as a CSV file with opening and closing rows. */
export function downloadAccountStatementCsv(query: AccountStatementQuery, filename: string): Promise<void> {
  const qs = statementParams(query);
  qs.set('format', 'csv');
  return downloadWithAuth(`${API_BASE}/v1/finance/statement-of-account/?${qs}`, filename);
}

/* ── Supplier payment totals (annual payee returns) ──────────────────── */

export interface PayeeTotal {
  contact_id: string | null;
  payee_name: string | null;
  payee_tax_id: string | null;
  payee_address: string | null;
  payee_country_code: string | null;
  currency_code: string;
  /** Paid less refunded over the period. Decimal as string. */
  total: string;
  paid: string;
  refunded: string;
  payment_count: number;
  invoice_count: number;
  project_count: number;
  below_threshold: boolean;
}

/** The annual return the paying entity's country asks for, such as Canada's T5018. */
export interface PayeeReturnInfo {
  form: string;
  name: string;
  threshold: string;
  currency: string;
  reference: string;
  due_on: string;
  note: string;
}

export interface PayeeTotalsReport {
  legal_entity_id: string;
  legal_entity_name: string | null;
  legal_entity_tax_id: string | null;
  country_code: string | null;
  date_from: string;
  date_to: string;
  payee_return: PayeeReturnInfo | null;
  items: PayeeTotal[];
  reportable_count: number;
  missing_tax_id: number;
}

export interface PayeeTotalsQuery {
  legalEntityId: string;
  dateFrom: string;
  dateTo: string;
}

function payeeParams(query: PayeeTotalsQuery): URLSearchParams {
  return new URLSearchParams({
    legal_entity_id: query.legalEntityId,
    date_from: query.dateFrom,
    date_to: query.dateTo,
  });
}

/**
 * What one legal entity paid each supplier over a period. Requires
 * ``finance.read``; the server reads only the projects the caller can open.
 */
export function getPayeeTotals(query: PayeeTotalsQuery): Promise<PayeeTotalsReport> {
  return apiGet<PayeeTotalsReport>(`/v1/finance/payee-totals/?${payeeParams(query)}`);
}

/** The same totals as CSV, one row per payee and currency. */
export function downloadPayeeTotalsCsv(query: PayeeTotalsQuery, filename: string): Promise<void> {
  const qs = payeeParams(query);
  qs.set('format', 'csv');
  return downloadWithAuth(`${API_BASE}/v1/finance/payee-totals/?${qs}`, filename);
}

/* ── Open items carried over from another system ──────────────────────── */

export type OpenItemRowStatus = 'ready' | 'imported' | 'exists' | 'error';

export interface OpenItemRow {
  row: number;
  status: OpenItemRowStatus;
  message: string | null;
  /** Stable reason of an error or exists row, translated as finance.openitems_err_<code>. */
  code: string | null;
  params: Record<string, string>;
  direction: 'payable' | 'receivable' | null;
  invoice_number: string | null;
  counterparty: string | null;
  contact_id: string | null;
  contact_name: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency_code: string | null;
  total: string | null;
  retention_held: string | null;
  open: string | null;
  paid: string | null;
  invoice_id: string | null;
}

export interface OpenItemControlTotal {
  direction: 'payable' | 'receivable';
  currency_code: string;
  count: number;
  total: string;
  retention_held: string;
  open: string;
}

export interface OpenItemsImportResult {
  project_id: string;
  cutover_date: string;
  dry_run: boolean;
  missing_columns: string[];
  imported: number;
  ready: number;
  exists: number;
  errors: number;
  rows: OpenItemRow[];
  control_totals: OpenItemControlTotal[];
}

/**
 * Check (``dryRun``) or import a file of invoices still open at the cut-over.
 * The import is all or nothing: while any row has an error nothing is written.
 */
export async function importOpenItems(
  projectId: string,
  file: File,
  cutoverDate: string,
  dryRun: boolean,
): Promise<OpenItemsImportResult> {
  const qs = new URLSearchParams({ project_id: projectId, cutover_date: cutoverDate, dry_run: String(dryRun) });
  const body = new FormData();
  body.append('file', file);
  const response = await fetchWithAuth(`${API_BASE}/v1/finance/open-items/import/?${qs}`, { method: 'POST', body });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(payload) ?? `HTTP ${response.status}`);
  return payload as OpenItemsImportResult;
}

/** The CSV template an open items import reads. */
export function downloadOpenItemsTemplate(): Promise<void> {
  return downloadWithAuth(`${API_BASE}/v1/finance/open-items/template/`, 'open_items_template.csv');
}

/* ── E-invoice export ─────────────────────────────────────────────────── */

/** One entry of the profile registry, as the backend publishes it. */
export interface EInvoiceProfile {
  key: string;
  /** Standard name, a proper noun, so it is not translated. */
  label: string;
  syntax: string;
  region: string;
}

/**
 * The profile registry. ``default`` names the profile to offer first for a
 * seller whose country has a national format outside EN 16931 (UBL-TR for a
 * Turkish seller); ``null`` everywhere else, and absent on an older server.
 *
 * Mirrors GET /finance/einvoice-profiles.
 */
export interface EInvoiceProfileList {
  default?: string | null;
  profiles: EInvoiceProfile[];
}

export interface EInvoiceViolation {
  rule_id: string;
  /** "fatal", "warning" or "info". */
  severity: string;
  message: string;
  term: string | null;
  /** Values the engine's sentence interpolates, named as the catalogue uses them. */
  params?: Record<string, string>;
}

/** The invoice a return (IADE) answers, as its issuer numbered and dated it. */
export interface TrOriginalInvoice {
  document_id: string;
  issue_date: string;
}

/**
 * The Turkish e-invoice fields of one invoice (``metadata.einvoice.tr``).
 *
 * Mirrors backend TrEInvoiceFields. The write replaces the whole block, so a
 * caller that shows only some of these has to send the others back unchanged.
 */
export interface TrEInvoiceFields {
  profile_id: string;
  invoice_type: string;
  document_id: string;
  series: string;
  issue_time: string;
  exchange_rate: string;
  exchange_rate_date: string;
  exemption_reason_code: string;
  exemption_reason: string;
  original_invoice: TrOriginalInvoice | null;
  original_invoice_id: string;
  line_withholding: Record<string, string>;
  tax_total_convention: '' | 'net_of_withholding' | 'computed';
  customization_id: string;
  amount_in_words: boolean;
  notes: string[];
}

/**
 * Where the taxes of an invoice are read from and in what state. Amounts and
 * rates are Decimal-as-string and are shown as they arrive.
 */
export interface EInvoiceTaxSource {
  /** "invoice", or "progress_claim" when the invoice was raised from a payment certificate. */
  source_kind: string;
  source_id: string;
  project_id: string;
  country_code?: string;
  currency_code?: string;
  /** "not_stored", "draft", "confirmed", "void" or "module_absent". */
  status?: string;
  net_amount?: string;
  vat_rate_pct?: string | null;
  suggested_vat_rate_pct?: string | null;
}

/** What a UBL-TR export would write. Amounts are Decimal-as-string. */
export interface TrEInvoiceDocument {
  uuid: string;
  document_id: string;
  profile_id: string;
  invoice_type: string;
  currency: string;
  line_extension: string;
  tax_inclusive: string;
  payable: string;
  /** Fields nobody typed that followed from the data, by name. */
  inferred: Record<string, string>;
  signed: boolean;
}

/**
 * The validation report of one invoice against one profile.
 *
 * The response also carries ``problems``, the fatal messages as bare strings.
 * It is not declared: the same findings arrive in ``violations`` with the rule
 * id and severity, and ``valid`` is already defined as "no fatal finding".
 * ``document``, ``tax_source`` and ``fields`` are sent by the UBL-TR branch
 * only.
 */
export interface EInvoiceDryRun {
  format: string;
  valid: boolean;
  violations: EInvoiceViolation[];
  document?: TrEInvoiceDocument | null;
  tax_source?: EInvoiceTaxSource;
  fields?: TrEInvoiceFields;
}

/** Mirrors GET /finance/invoices/{id}/einvoice/tr. */
export interface TrEInvoiceFieldsRead {
  invoice_id: string;
  uuid: string;
  fields: TrEInvoiceFields;
  /** Why the stored block could not be read; empty when it could. */
  unreadable: string;
  tax_source: EInvoiceTaxSource;
  line_ids: string[];
}

/** Mirrors the answer of PUT /finance/invoices/{id}/einvoice/tr. */
export interface TrEInvoiceFieldsWritten {
  invoice_id: string;
  uuid: string;
  fields: TrEInvoiceFields;
}

/** The part of an invoice the e-invoice screen reads besides the report. */
export interface InvoiceMetadataRead {
  id: string;
  metadata: Record<string, unknown>;
}

export function listEInvoiceProfiles(): Promise<EInvoiceProfileList> {
  return apiGet<EInvoiceProfileList>('/v1/finance/einvoice-profiles');
}

/** Run the validation report. Never writes. */
export function dryRunEInvoice(invoiceId: string, profile: string): Promise<EInvoiceDryRun> {
  return apiGet<EInvoiceDryRun>(
    `/v1/finance/invoices/${encodeURIComponent(invoiceId)}/einvoice?format=${encodeURIComponent(profile)}&dry_run=true`,
  );
}

export function getTrEInvoiceFields(invoiceId: string): Promise<TrEInvoiceFieldsRead> {
  return apiGet<TrEInvoiceFieldsRead>(`/v1/finance/invoices/${encodeURIComponent(invoiceId)}/einvoice/tr`);
}

/** Replace the whole Turkish block of one invoice. Allowed on an issued invoice. */
export function putTrEInvoiceFields(
  invoiceId: string,
  fields: TrEInvoiceFields,
): Promise<TrEInvoiceFieldsWritten> {
  return apiPut<TrEInvoiceFieldsWritten, TrEInvoiceFields>(
    `/v1/finance/invoices/${encodeURIComponent(invoiceId)}/einvoice/tr`,
    fields,
  );
}

export function getInvoiceMetadata(invoiceId: string): Promise<InvoiceMetadataRead> {
  return apiGet<InvoiceMetadataRead>(`/v1/finance/${encodeURIComponent(invoiceId)}`);
}

/**
 * Replace the metadata of one invoice. The column is replaced rather than
 * merged, so the caller sends the whole object it read, changed.
 */
export function patchInvoiceMetadata(
  invoiceId: string,
  metadata: Record<string, unknown>,
): Promise<InvoiceMetadataRead> {
  return apiPatch<InvoiceMetadataRead, { metadata: Record<string, unknown> }>(
    `/v1/finance/${encodeURIComponent(invoiceId)}`,
    { metadata },
  );
}

/* ── Printable documents ──────────────────────────────────────────────── */

/**
 * Download the printable form of one invoice (GET /invoices/{id}/export/pdf/),
 * with the sections the workspace's document settings keep.
 */
export function downloadInvoicePdf(id: string, locale: string, invoiceNumber?: string): Promise<void> {
  return downloadRecordPdf(
    `/v1/finance/invoices/${encodeURIComponent(id)}/export/pdf/`,
    locale,
    invoiceNumber || 'invoice',
  );
}

/** Download the printable record of one payment (GET /payments/{id}/export/pdf/). */
export function downloadPaymentPdf(id: string, locale: string): Promise<void> {
  return downloadRecordPdf(`/v1/finance/payments/${encodeURIComponent(id)}/export/pdf/`, locale, 'payment');
}

/* ── Payment runs ──────────────────────────────────────────────────────── */

export type PaymentRunStatus = 'draft' | 'approved' | 'executed' | 'cancelled';

/** A finding on a run: errors block approving and paying it, warnings do not. */
export interface PaymentRunIssue {
  severity: 'error' | 'warning';
  code: string;
  message: string;
  item_id: string | null;
  invoice_id: string | null;
}

export interface PaymentRunItem {
  id: string;
  invoice_id: string;
  invoice_number: string;
  project_id: string;
  project_name: string | null;
  contact_id: string | null;
  counterparty_name: string | null;
  due_date: string | null;
  amount: string;
  open_at_proposal: string;
  payment_id: string | null;
}

/** Mirrors backend PaymentRunResponse. Money is Decimal-as-string. */
export interface PaymentRun {
  id: string;
  run_number: string;
  legal_entity_id: string | null;
  legal_entity_name: string | null;
  currency_code: string;
  payment_date: string;
  due_by: string;
  status: PaymentRunStatus;
  note: string | null;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  executed_by: string | null;
  executed_at: string | null;
  created_at: string | null;
  total: string;
  item_count: number;
  items: PaymentRunItem[];
  issues: PaymentRunIssue[];
}

export interface PaymentRunCreate {
  legal_entity_id: string | null;
  currency_code: string;
  payment_date: string;
  due_by?: string;
  note?: string;
}

const PAYMENT_RUNS = '/v1/finance/payment-runs';

export const paymentRunsApi = {
  list: () => apiGet<{ items: PaymentRun[]; total: number }>(`${PAYMENT_RUNS}/`),
  get: (id: string) => apiGet<PaymentRun>(`${PAYMENT_RUNS}/${id}`),
  create: (body: PaymentRunCreate) => apiPost<PaymentRun, PaymentRunCreate>(`${PAYMENT_RUNS}/`, body),
  updateItem: (id: string, itemId: string, amount: string) =>
    apiPatch<PaymentRun, { amount: string }>(`${PAYMENT_RUNS}/${id}/items/${itemId}`, { amount }),
  removeItem: (id: string, itemId: string) => apiDelete<PaymentRun>(`${PAYMENT_RUNS}/${id}/items/${itemId}`),
  approve: (id: string) => apiPost<PaymentRun>(`${PAYMENT_RUNS}/${id}/approve/`),
  execute: (id: string) => apiPost<PaymentRun>(`${PAYMENT_RUNS}/${id}/execute/`),
  cancel: (id: string) => apiPost<PaymentRun>(`${PAYMENT_RUNS}/${id}/cancel/`),
  downloadBankFile: (run: Pick<PaymentRun, 'id' | 'run_number'>) =>
    downloadWithAuth(`${API_BASE}${PAYMENT_RUNS}/${run.id}/bank-file.csv`, `${run.run_number}.csv`),
};

/** The findings a refused approve or execute carries in its 422 body, if any. */
export function paymentRunIssuesFrom(body: unknown): PaymentRunIssue[] {
  if (!body || typeof body !== 'object') return [];
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== 'object') return [];
  const issues = (detail as { issues?: unknown }).issues;
  return Array.isArray(issues) ? (issues as PaymentRunIssue[]) : [];
}
