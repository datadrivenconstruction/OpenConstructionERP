// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Payment release API: a supplier contract's payment terms, its invoices with
// every step from the invoiced amount to the amount released for payment, the
// retention it holds, and rules V11 to V18. Money is a decimal STRING both
// ways; the server does every sum.
import type { TFunction } from 'i18next';

import { apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

export type InvoiceMode = 'incremental' | 'cumulative';
export type InvoiceKind = 'interim' | 'final' | 'daywork' | 'credit_note';
export type RetentionBasis = 'net' | 'gross';
export type DiscountScope = 'interim' | 'final' | 'both';
export type RetentionKind = 'interim' | 'warranty';

export const INVOICE_KINDS: readonly InvoiceKind[] = ['interim', 'final', 'daywork', 'credit_note'];
export const RELEASE_EVENTS = ['substantial_completion', 'final_completion', 'defects_period_end'] as const;
export type ReleaseEvent = (typeof RELEASE_EVENTS)[number];

export interface PaymentTerms {
  contract_id: string;
  /** False while the contract runs on the defaults, every optional feature off. */
  terms_set: boolean;
  currency: string;
  invoice_mode: InvoiceMode;
  retention_percent: string;
  retention_release_event: string;
  retention_basis: RetentionBasis;
  warranty_enabled: boolean;
  warranty_percent: string;
  warranty_release_event: string;
  warranty_period_months: number | null;
  discount_enabled: boolean;
  discount_percent: string;
  discount_days: number;
  discount_applies_to: DiscountScope;
  rounding_enabled: boolean;
  rounding_step: string;
  interim_due_days: number | null;
  final_due_days: number | null;
}

export type PaymentTermsBody = Omit<PaymentTerms, 'contract_id' | 'terms_set' | 'currency'>;

/** Every step of one release, as the server computed or froze it. */
export interface ReleaseFigures {
  key: string;
  kind: InvoiceKind;
  net: string;
  net_deduction: string;
  net_after: string;
  vat: string;
  vat_deduction: string;
  vat_after: string;
  gross: string;
  gross_deduction: string;
  gross_after: string;
  previous_releases: string;
  previous_counted: boolean;
  retention_percent: string;
  retention_base: string;
  retention: string;
  retention_source: string;
  release_before_rounding: string;
  rounding: string;
  release: string;
  discount_percent: string;
  discount: string;
  payable: string;
  due_on: string | null;
  discount_until: string | null;
  retention_held_after: string;
}

export interface LedgerInvoice {
  invoice_id: string;
  number: string;
  invoice_date: string | null;
  finance_status: string;
  kind: InvoiceKind;
  /** False while the kind is the default guess, not set by a person. */
  kind_set: boolean;
  contract_source: string | null;
  release_status: 'open' | 'released';
  released_at: string | null;
  net_deduction_note: string;
  gross_deduction_note: string;
  /** The figures in force: frozen at release, else computed now. */
  figures: ReleaseFigures;
  /** The figures as the terms compute them today. */
  computed: ReleaseFigures;
  /** A confirmed release that today's terms would compute differently (rule V12). */
  differs: boolean;
  counted: boolean;
  progress_pct: string | null;
  paid: string;
  paid_cash: string;
  discount_taken: string;
  open_amount: string;
}

export interface LedgerTotals {
  contract_value: string;
  invoiced: string;
  invoiced_pct: string | null;
  released: string;
  payable: string;
  paid: string;
  open_amount: string;
  retention_held: string;
  retention_posted: string;
}

export interface LedgerContract {
  contract_id: string;
  code: string;
  title: string;
  status: string;
  invoice_mode: InvoiceMode;
  terms_set: boolean;
  original_value: string;
  changes: string;
  current_value: string;
  changes_pct: string | null;
  measured: string;
  measured_pct: string | null;
  has_measurement: boolean;
  invoices: LedgerInvoice[];
  totals: LedgerTotals;
}

export interface LooseInvoice {
  invoice_id: string;
  number: string;
  invoice_date: string | null;
  finance_status: string;
  net: string;
  gross: string;
  paid: string;
  purchase_order_id: string | null;
}

export interface ProjectLedger {
  project_id: string;
  currency: string;
  contracts: LedgerContract[];
  other_invoices: LooseInvoice[];
  totals: LedgerTotals;
}

export interface InvoiceReleaseUpdate {
  kind?: InvoiceKind;
  contract_id?: string | null;
  net_deduction?: string;
  net_deduction_note?: string;
  gross_deduction?: string;
  gross_deduction_note?: string;
}

export interface InvoiceReleaseState {
  invoice_id: string;
  contract_id: string | null;
  kind: string;
  status: string;
  release_amount: string | null;
  payable_amount: string | null;
}

export interface RetentionPosting {
  id: string;
  contract_id: string;
  retention_kind: RetentionKind;
  event: string;
  event_on: string | null;
  amount: string;
  posted_on: string;
  status: 'posted' | 'void';
  document_ref: string;
  note: string;
}

export interface RetentionPostingCreate {
  retention_kind: RetentionKind;
  event: ReleaseEvent;
  event_on: string | null;
  amount: string;
  posted_on: string;
  document_ref?: string;
  note?: string;
}

export interface RetentionContract {
  contract_id: string;
  code: string;
  title: string;
  status: string;
  retention_percent: string;
  retention_release_event: string;
  warranty_enabled: boolean;
  warranty_percent: string;
  warranty_release_event: string;
  warranty_period_months: number | null;
  withheld: string;
  posted: string;
  held: string;
  postings: RetentionPosting[];
}

export interface RetentionRegister {
  project_id: string;
  currency: string;
  contracts: RetentionContract[];
  held: string;
  posted: string;
}

export interface ReleaseFinding {
  rule_id: string;
  /** V11 to V18. */
  rule_number: string;
  severity: 'error' | 'warning' | 'info';
  /** Already in the reader's language. */
  message: string;
  suggestion: string | null;
  element_ref: string | null;
  problem: string | null;
}

export interface ReleaseFindings {
  project_id: string;
  findings: ReleaseFinding[];
  errors: number;
  warnings: number;
}

export const paymentsApi = {
  ledger: (projectId: string) => apiGet<ProjectLedger>(`/v1/payment-release/projects/${projectId}/ledger/`),
  retention: (projectId: string) => apiGet<RetentionRegister>(`/v1/payment-release/projects/${projectId}/retention/`),
  findings: (projectId: string) => apiGet<ReleaseFindings>(`/v1/payment-release/projects/${projectId}/findings/`),
  terms: (contractId: string) => apiGet<PaymentTerms>(`/v1/payment-release/contracts/${contractId}/terms/`),
  putTerms: (contractId: string, body: PaymentTermsBody) =>
    apiPut<PaymentTerms, PaymentTermsBody>(`/v1/payment-release/contracts/${contractId}/terms/`, body),
  updateInvoice: (invoiceId: string, body: InvoiceReleaseUpdate) =>
    apiPatch<InvoiceReleaseState, InvoiceReleaseUpdate>(`/v1/payment-release/invoices/${invoiceId}/`, body),
  release: (invoiceId: string) =>
    apiPost<InvoiceReleaseState, Record<string, never>>(`/v1/payment-release/invoices/${invoiceId}/release/`, {}),
  reopen: (invoiceId: string) =>
    apiPost<InvoiceReleaseState, Record<string, never>>(`/v1/payment-release/invoices/${invoiceId}/reopen/`, {}),
  postRetention: (contractId: string, body: RetentionPostingCreate) =>
    apiPost<RetentionPosting, RetentionPostingCreate>(`/v1/payment-release/contracts/${contractId}/retention-postings/`, body),
  voidPosting: (postingId: string) =>
    apiPost<RetentionPosting, Record<string, never>>(`/v1/payment-release/retention-postings/${postingId}/void/`, {}),
};

/* ── Labels ─────────────────────────────────────────────────────────── */

export function kindLabel(t: TFunction, kind: string): string {
  switch (kind) {
    case 'interim':
      return t('cost_control.pay.kind_interim', { defaultValue: 'Interim invoice' });
    case 'final':
      return t('cost_control.pay.kind_final', { defaultValue: 'Final invoice' });
    case 'daywork':
      return t('cost_control.pay.kind_daywork', { defaultValue: 'Daywork invoice' });
    case 'credit_note':
      return t('cost_control.pay.kind_credit_note', { defaultValue: 'Credit note' });
    default:
      return kind;
  }
}

export function modeLabel(t: TFunction, mode: string): string {
  return mode === 'cumulative'
    ? t('cost_control.pay.mode_cumulative', { defaultValue: 'Cumulative invoices' })
    : t('cost_control.pay.mode_incremental', { defaultValue: 'Each invoice for new work only' });
}

export function eventLabel(t: TFunction, event: string): string {
  switch (event) {
    case 'substantial_completion':
      return t('cost_control.pay.event_substantial_completion', { defaultValue: 'Substantial completion' });
    case 'final_completion':
      return t('cost_control.pay.event_final_completion', { defaultValue: 'Final completion' });
    case 'defects_period_end':
      return t('cost_control.pay.event_defects_period_end', { defaultValue: 'End of the defects period' });
    default:
      return event;
  }
}

/** Sentences for the stable problem keys of the payment release endpoints. */
export function paymentProblem(t: TFunction, problem: string, params: Record<string, unknown> = {}): string | null {
  switch (problem) {
    case 'invoice_released':
      return t('cost_control.pay.problem_invoice_released', {
        defaultValue: 'The release is confirmed. Reopen it before changing the invoice.',
      });
    case 'invoice_open':
      return t('cost_control.pay.problem_invoice_open', { defaultValue: 'The release is not confirmed yet.' });
    case 'earlier_invoice_open':
      return t('cost_control.pay.problem_earlier_invoice_open', {
        defaultValue: 'Release the earlier invoices of this contract first. This release builds on them.',
      });
    case 'later_invoice_released':
      return t('cost_control.pay.problem_later_invoice_released', {
        defaultValue: 'A later invoice of this contract is released. Reopen that one first.',
      });
    case 'release_blocked_by_findings':
      return t('cost_control.pay.problem_release_blocked', {
        defaultValue: 'The checks found an error on this invoice. Resolve it, then release.',
      });
    case 'invoice_without_contract':
      return t('cost_control.pay.problem_invoice_without_contract', {
        defaultValue: 'Name the contract of this invoice before releasing it.',
      });
    case 'contract_in_other_project':
      return t('cost_control.pay.problem_contract_in_other_project', {
        defaultValue: 'That contract belongs to another project.',
      });
    case 'not_a_supplier_contract':
      return t('cost_control.pay.problem_not_a_supplier_contract', {
        defaultValue: 'Payment terms apply to supplier and subcontract contracts only.',
      });
    case 'exceeds_held':
      return t('cost_control.pay.problem_exceeds_held', {
        defaultValue: 'The contract holds only {{held}} of retention.',
        held: String(params.held ?? ''),
      });
    case 'posting_void':
      return t('cost_control.pay.problem_posting_void', { defaultValue: 'This posting is already void.' });
    default:
      return null;
  }
}
