// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Finance module.
 *
 * Backed by /api/v1/finance/ - see backend/app/modules/finance/router.py and
 * schemas.py. The shapes here mirror the Pydantic response models exactly so
 * the page can drop straight onto the API.
 */

import { apiGet, apiPatch, apiPut } from '@/shared/lib/api';

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
