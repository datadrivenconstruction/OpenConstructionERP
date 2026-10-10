// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The payment certificate (hakediş) of a progress claim or of a subcontractor
// payment application, and the statutory tax routes its tax lines are decided
// through.
//
// Two mirrored route families answer with the same document, so everything
// here takes a `HakedisSource` (which kind of document, and its id) and the
// screen is written once. The types are transcribed from
// `backend/app/modules/contracts/schemas.py` (`HakedisResponse` and its
// inputs), `backend/app/modules/contracts/hakedis_document.py`
// (`document_payload`, which builds the nested objects the schema passes
// through as plain dicts) and `backend/app/modules/tax_withholding/schemas.py`
// (the `Statutory*` models).
//
// Every amount, rate and percent is a decimal STRING and stays one: nothing
// here converts to a number. `null` means "no figure", and the line that
// carries it says why.

import { apiDelete, apiGet, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl, type DocumentFormat } from '@/shared/lib/documentExport';

export type HakedisSourceKind = 'progress_claim' | 'sub_payment_application';

/** Which document a certificate belongs to. */
export interface HakedisSource {
  kind: HakedisSourceKind;
  id: string;
}

/** The languages a certificate is built in; `tr-en` prints both, Turkish first. */
export type HakedisLocale = 'tr' | 'en' | 'tr-en';

/** `_HAKEDIS_LOCALE` in both routers. */
export const HAKEDIS_LOCALES: readonly HakedisLocale[] = ['tr', 'en', 'tr-en'];

export type HakedisLineStatus = 'value' | 'held' | 'not_applicable';
export type HakedisLineOp = 'input' | 'manual' | 'sum' | 'difference' | 'tax' | 'retention';
/** The three taxes a person decides, as `TAX_CHOICE_KINDS` names them. */
export type HakedisTaxChoiceKind = 'vat_withholding' | 'income_withholding' | 'stamp_duty';
export type HakedisChoiceState = 'selected' | 'not_applicable' | 'unset';

export const HAKEDIS_TAX_CHOICE_KINDS: readonly HakedisTaxChoiceKind[] = [
  'vat_withholding',
  'income_withholding',
  'stamp_duty',
];

export interface HakedisParty {
  name: string;
  tax_number: string;
  tax_office: string;
  address: string;
}

/** One printed header row: its label per language of the locale, and its value. */
export interface HakedisLabelledRow {
  labels: string[];
  value: string;
}

export interface HakedisHeader {
  certificate_number: number;
  is_final: boolean;
  period_start: string;
  period_end: string;
  issue_date: string | null;
  project_name: string;
  contract_number: string;
  contract_title: string;
  employer: HakedisParty;
  contractor: HakedisParty;
  rows: HakedisLabelledRow[];
  party_rows: HakedisLabelledRow[];
}

/** `ColumnDef.kind` in `hakedis_layout.py`. */
export type HakedisColumnKind = 'seq' | 'text' | 'unit' | 'quantity' | 'unit_price' | 'money' | 'percent';

export interface HakedisWorksColumn {
  key: string;
  /** The letter or formula printed over the column, empty for none. */
  letter: string;
  kind: HakedisColumnKind;
  labels: string[];
}

export interface HakedisWorksRow {
  kind: 'section' | 'line' | 'subtotal' | 'total';
  title: string;
  /** The text as printed, aligned with the columns. */
  cells: string[];
  /** The number behind a numeric cell as a plain decimal string, else null. */
  values: (string | null)[];
  /** The cumulative quantity or percent is over the contract's. */
  flagged: boolean;
  /** The row lacks data and is counted in no total. */
  held: boolean;
}

export interface HakedisWorksTotals {
  previous_amount: string | null;
  period_amount: string | null;
  cumulative_amount: string | null;
  contract_amount: string | null;
}

export interface HakedisWorks {
  columns: HakedisWorksColumn[];
  rows: HakedisWorksRow[];
  totals: HakedisWorksTotals;
}

/** What a person entered for a manual line. */
export interface HakedisEntered {
  state: string;
  amount: string | null;
  pct: string | null;
  note: string;
}

export interface HakedisSummaryLine {
  key: string;
  letter: string;
  section: string;
  op: HakedisLineOp;
  sign: number;
  /** The figure a tax line prints (`vat_computed`, `vat_withheld`, ...), else empty. */
  tax_kind: string;
  status: HakedisLineStatus;
  /** Set only while `status` is `value`. */
  amount: string | null;
  /** The amount as the printed document words it. Not shown on screen. */
  text: string;
  labels: string[];
  formulas: string[];
  details: string[];
  /** What the figure rests on: base, rate, code, legal reference, a person's note. */
  basis: Record<string, string>;
  /** Why a held line is held; empty for any other line. */
  reason_key: string;
  reason_params: Record<string, string>;
  reason_text: string[];
  notes: number[];
  emphasis: boolean;
  /** A person may enter this line now. */
  enterable: boolean;
  accepts_percent: boolean;
  entered: HakedisEntered | null;
}

/** One numbered reason the document is a draft. */
export interface HakedisNote {
  number: number;
  line_key: string;
  letter: string;
  reason_key: string;
  reason_params: Record<string, string>;
  text: string[];
}

/** A category on offer for one tax, as `_category` in `hakedis_document.py` sends it. */
export interface HakedisTaxCategory {
  code: string;
  label: string;
  rate_pct: string | null;
  numerator: number | null;
  denominator: number | null;
  legal_reference: string;
  review_status: string;
  conditions: string;
  buyer_scope: string;
}

export interface HakedisTaxChoice {
  state: HakedisChoiceState;
  code: string;
  reason: string;
}

export interface HakedisTaxes {
  /** A tax module is installed. */
  available: boolean;
  /** A set of tax lines is stored for this document. */
  stored: boolean;
  /** `draft`, `confirmed`, or empty when nothing usable is stored. */
  status: string;
  /** The stored set was computed on other amounts than the certificate's. */
  stale: boolean;
  expected_net_amount: string | null;
  expected_stamp_duty_base: string | null;
  vat_rate_pct: string | null;
  document_date: string | null;
  direction: string;
  choices: Partial<Record<HakedisTaxChoiceKind, HakedisTaxChoice>>;
  buyer_is_designated: boolean | null;
  work_value_incl_vat: string | null;
  work_value_note: string;
  categories: Partial<Record<HakedisTaxChoiceKind, HakedisTaxCategory[]>>;
}

export interface HakedisFinding {
  rule_id: string;
  rule_name: string;
  severity: string;
  message: string;
  suggestion: string | null;
  /** A summary line key, a work row index, or the document. */
  element_ref: string | null;
  details: Record<string, unknown>;
  engine_error: boolean;
}

export interface HakedisSignatureRole {
  key: string;
  labels: string[];
}

export interface HakedisDocument {
  source_kind: HakedisSourceKind;
  source_id: string;
  project_id: string;
  reference: string;
  status: string;
  locale: HakedisLocale;
  locales: string[];
  layout_available: boolean;
  /** False once frozen, or once the source document no longer takes edits. */
  editable: boolean;
  frozen: boolean;
  frozen_at: string | null;
  is_draft: boolean;
  currency: string;
  country_code: string;
  flavour: 'unit_price' | 'lump_sum';
  header: HakedisHeader;
  works: HakedisWorks;
  summary: HakedisSummaryLine[];
  notes: HakedisNote[];
  taxes: HakedisTaxes;
  options: { is_final: boolean };
  signature_roles: HakedisSignatureRole[];
  /** What the next certificate states as its previous total. */
  carried_total: string | null;
  /** Failed rules only. Empty on a frozen document. */
  findings: HakedisFinding[];
  can_certify: boolean;
}

/** `HakedisLineInput`. Amount and percent travel as decimal strings. */
export interface HakedisLineInput {
  state: 'value' | 'not_applicable' | 'unset';
  amount?: string | null;
  pct?: string | null;
  note?: string;
}

/**
 * `HakedisTaxesInput`. A field left out keeps its stored value, so an empty
 * body recalculates the taxes on the certificate's current amounts.
 */
export interface HakedisTaxesInput {
  vat_withholding?: HakedisTaxChoice;
  income_withholding?: HakedisTaxChoice;
  stamp_duty?: HakedisTaxChoice;
  buyer_is_designated?: boolean | null;
  work_value_incl_vat?: string | null;
  work_value_note?: string | null;
}

function hakedisPath(source: HakedisSource): string {
  const id = encodeURIComponent(source.id);
  return source.kind === 'progress_claim'
    ? `/v1/contracts/progress-claims/${id}/hakedis`
    : `/v1/subcontractors/payment-applications/${id}/hakedis`;
}

function withLocale(path: string, locale: HakedisLocale): string {
  return `${path}?locale=${encodeURIComponent(locale)}`;
}

/**
 * The certificate of one document.
 *
 * The backend answers 404 `hakedis_not_available` where the contract has no
 * certificate layout, which is every contract outside the countries that have
 * one unless it configures its own.
 */
export function getHakedis(source: HakedisSource, locale: HakedisLocale): Promise<HakedisDocument> {
  return apiGet<HakedisDocument>(withLocale(hakedisPath(source), locale));
}

/** Enter, mark not applicable or clear one manual line. Answers the refreshed certificate. */
export function putHakedisLine(
  source: HakedisSource,
  lineKey: string,
  body: HakedisLineInput,
  locale: HakedisLocale,
): Promise<HakedisDocument> {
  return apiPut<HakedisDocument, HakedisLineInput>(
    withLocale(`${hakedisPath(source)}/lines/${encodeURIComponent(lineKey)}`, locale),
    body,
  );
}

/** State whether this certificate is the final one. */
export function putHakedisOptions(
  source: HakedisSource,
  isFinal: boolean,
  locale: HakedisLocale,
): Promise<HakedisDocument> {
  return apiPut<HakedisDocument, { is_final: boolean }>(
    withLocale(`${hakedisPath(source)}/options`, locale),
    { is_final: isFinal },
  );
}

/**
 * Store the tax choices as a draft set of statutory tax lines. No amount is
 * sent: the server takes every base from the certificate itself.
 */
export function putHakedisTaxes(
  source: HakedisSource,
  body: HakedisTaxesInput,
  locale: HakedisLocale,
): Promise<HakedisDocument> {
  return apiPut<HakedisDocument, HakedisTaxesInput>(withLocale(`${hakedisPath(source)}/taxes`, locale), body);
}

/** Absolute URL of the printed certificate in one format and language. */
export function hakedisDocumentUrl(source: HakedisSource, format: DocumentFormat, locale: string): string {
  return documentExportUrl(`${hakedisPath(source)}/${format}`, { locale });
}

/**
 * Download the printed certificate.
 *
 * @throws Error carrying the server's message when the request is refused.
 */
export function downloadHakedis(
  source: HakedisSource,
  format: DocumentFormat,
  locale: string,
  fallbackName: string,
): Promise<void> {
  return downloadWithAuth(hakedisDocumentUrl(source, format, locale), `${fallbackName}.${format}`);
}

// ── Statutory tax lines (tax_withholding) ───────────────────────────────────

/** `StatutoryOverridableLiteral`, less the VAT itself, which this screen never overrides. */
export type StatutoryFigureKind = 'vat_withheld' | 'income_withheld' | 'stamp_duty';

/** The figure each choice produces: what an override of that tax is keyed by. */
export const FIGURE_OF_CHOICE: Record<HakedisTaxChoiceKind, StatutoryFigureKind> = {
  vat_withholding: 'vat_withheld',
  income_withholding: 'income_withheld',
  stamp_duty: 'stamp_duty',
};

/** `StatutoryInputsBody`. */
export interface StatutoryInputs {
  country_code: string;
  currency_code: string;
  document_date: string;
  net_amount: string;
  /** Required by the server even when unknown: null says "could not be resolved". */
  vat_rate_pct: string | null;
  buyer_is_designated: boolean | null;
  work_value_incl_vat: string | null;
  work_value_note: string;
  stamp_duty_base: string | null;
  stamp_duty_base_same_as_net: boolean;
  vat_withholding: HakedisTaxChoice;
  income_withholding: HakedisTaxChoice;
  stamp_duty: HakedisTaxChoice;
}

/** `StatutoryFigureResponse`. */
export interface StatutoryFigure {
  kind: string;
  status: string;
  amount: string | null;
  base: string | null;
  rate_pct: string | null;
  numerator: number | null;
  denominator: number | null;
  code: string;
  currency_code: string;
  legal_reference: string;
  source_url: string;
  effective_from: string | null;
  effective_to: string | null;
  review_status: string;
  overridden: boolean;
  reason_key: string;
  reason_params: Record<string, string>;
  choice_state: string;
  choice_code: string;
  choice_reason: string;
  override_amount: string | null;
  override_reason: string;
  overridden_by: string | null;
  overridden_at: string | null;
}

/** `WithholdingFinding`. */
export interface StatutoryFinding {
  key: string;
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string;
  details: Record<string, unknown>;
}

/** `StatutoryPreviewResponse`. */
export interface StatutoryPreview {
  inputs: StatutoryInputs;
  figures: StatutoryFigure[];
  complete: boolean;
  uses_unconfirmed_rates: boolean;
  findings: StatutoryFinding[];
}

/** `StatutoryCalcResponse`. */
export interface StatutoryCalc {
  id: string;
  project_id: string;
  source_kind: string;
  source_id: string;
  source_reference: string;
  direction: string;
  status: string;
  inputs: StatutoryInputs;
  figures: StatutoryFigure[];
  complete: boolean;
  uses_unconfirmed_rates: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  unconfirmed_rates_acknowledged_by: string | null;
  unconfirmed_rates_acknowledged_at: string | null;
  reopened_by: string | null;
  reopened_at: string | null;
  reopen_reason: string;
  voided_by: string | null;
  voided_at: string | null;
  void_reason: string;
  created_at: string;
  updated_at: string;
  findings: StatutoryFinding[];
}

/** `StatutoryCategoryResponse`: one category with its whole legal basis. */
export interface StatutoryCategory {
  country_code: string;
  kind: string;
  code: string;
  labels: Record<string, string>;
  base: string;
  rate_pct: string | null;
  numerator: number | null;
  denominator: number | null;
  threshold_amount: string | null;
  threshold_currency: string;
  threshold_scope: string;
  threshold_measure: string;
  cap_amount: string | null;
  buyer_scope: string;
  work_value_threshold: string | null;
  conditions: Record<string, string>;
  effective_from: string;
  effective_to: string | null;
  legal_reference: string;
  source_url: string;
  read_date: string;
  review_status: string;
}

/** `StatutoryCategoryListResponse`. */
export interface StatutoryCategoryPage {
  items: StatutoryCategory[];
  total: number;
  offset: number;
  limit: number;
}

function statutoryPath(source: HakedisSource): string {
  return `/v1/tax-withholding/statutory/${source.kind}/${encodeURIComponent(source.id)}`;
}

/** What the figures would be for these inputs. Nothing is stored. */
export function previewStatutoryTaxes(inputs: StatutoryInputs): Promise<StatutoryPreview> {
  return apiPost<StatutoryPreview, StatutoryInputs>('/v1/tax-withholding/statutory/preview', inputs);
}

/** The categories in force on one date, with effective dates and sources. */
export function listStatutoryCategories(country: string, on: string): Promise<StatutoryCategoryPage> {
  const qs = new URLSearchParams({ country, on, limit: '500' });
  return apiGet<StatutoryCategoryPage>(`/v1/tax-withholding/statutory/categories?${qs.toString()}`);
}

/** The stored tax lines of one document. 404 while nothing is stored. */
export function getStatutoryTaxes(source: HakedisSource, projectId: string): Promise<StatutoryCalc> {
  return apiGet<StatutoryCalc>(`${statutoryPath(source)}?project_id=${encodeURIComponent(projectId)}`);
}

/** Enter an amount in place of one computed figure, with the reason. */
export function overrideStatutoryTax(
  source: HakedisSource,
  body: { project_id: string; kind: StatutoryFigureKind; amount: string; reason: string },
): Promise<StatutoryCalc> {
  return apiPost<StatutoryCalc, typeof body>(`${statutoryPath(source)}/override`, body);
}

/** Remove an entered amount and go back to the computed figure. */
export function clearStatutoryTaxOverride(
  source: HakedisSource,
  kind: StatutoryFigureKind,
  projectId: string,
): Promise<StatutoryCalc> {
  return apiDelete<StatutoryCalc>(
    `${statutoryPath(source)}/override/${kind}?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Confirm the stored figures. From here on they are frozen until reopened. */
export function confirmStatutoryTaxes(
  source: HakedisSource,
  body: { project_id: string; acknowledge_unconfirmed_rates: boolean },
): Promise<StatutoryCalc> {
  return apiPost<StatutoryCalc, typeof body>(`${statutoryPath(source)}/confirm`, body);
}

/** Take confirmed or void figures back to draft, with the reason. */
export function reopenStatutoryTaxes(
  source: HakedisSource,
  body: { project_id: string; reason: string },
): Promise<StatutoryCalc> {
  return apiPost<StatutoryCalc, typeof body>(`${statutoryPath(source)}/reopen`, body);
}
