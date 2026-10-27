// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Label tables for the accounting sync vocabularies. Each entry pairs a locale
 * key with its English text, so a label is never built from a template literal
 * and the key set stays greppable.
 */
import type { TFunction } from 'i18next';
import type { BadgeVariant } from '@/shared/ui/Badge';
import type { DocumentRecordType, DocumentSource, ExportKind, LogAction, LogStatus, Provider, TaxDirection } from './api';

interface Label {
  key: string;
  en: string;
}

const PROVIDER_LABELS: Record<Provider, Label> = {
  xero: { key: 'accountingSync.provider.xero', en: 'Xero' },
  qbo: { key: 'accountingSync.provider.qbo', en: 'QuickBooks' },
  datev: { key: 'accountingSync.provider.datev', en: 'DATEV' },
  journal: { key: 'accountingSync.provider.journal', en: 'Journal (CSV / Excel)' },
  saft: { key: 'accountingSync.provider.saft', en: 'SAF-T' },
};

const PROVIDER_HELP: Record<Provider, Label> = {
  xero: {
    key: 'accountingSync.provider.xero_help',
    en: 'Live sync with Xero through OAuth. Approved invoices and bills are pushed, payments come back.',
  },
  qbo: {
    key: 'accountingSync.provider.qbo_help',
    en: 'Live sync with QuickBooks Online through OAuth. Approved invoices and bills are pushed, payments come back.',
  },
  datev: {
    key: 'accountingSync.provider.datev_help',
    en: 'EXTF file for a German tax advisor. No live connection: you download the file and hand it over.',
  },
  journal: {
    key: 'accountingSync.provider.journal_help',
    en: 'A plain journal as CSV or Excel for any country and any accounting package.',
  },
  saft: {
    key: 'accountingSync.provider.saft_help',
    en: 'SAF-T, the OECD standard audit file in XML, for tax authorities that ask for it.',
  },
};

const CATEGORY_LABELS: Record<string, Label> = {
  ar_control: { key: 'accountingSync.category.ar_control', en: 'Receivables (customers)' },
  ap_control: { key: 'accountingSync.category.ap_control', en: 'Payables (suppliers)' },
  revenue: { key: 'accountingSync.category.revenue', en: 'Revenue' },
  revenue_reduced: { key: 'accountingSync.category.revenue_reduced', en: 'Revenue, reduced tax rate' },
  subcontract_cost: { key: 'accountingSync.category.subcontract_cost', en: 'Subcontract cost' },
  material_cost: { key: 'accountingSync.category.material_cost', en: 'Material cost' },
  guarantee_fees: { key: 'accountingSync.category.guarantee_fees', en: 'Guarantee fees' },
  payroll_cost: { key: 'accountingSync.category.payroll_cost', en: 'Payroll cost' },
  payroll_liability: { key: 'accountingSync.category.payroll_liability', en: 'Wages payable' },
  retention_receivable: { key: 'accountingSync.category.retention_receivable', en: 'Retention receivable' },
  retention_payable: { key: 'accountingSync.category.retention_payable', en: 'Retention payable' },
  bank: { key: 'accountingSync.category.bank', en: 'Bank' },
  output_tax: { key: 'accountingSync.category.output_tax', en: 'Output tax (sales)' },
  input_tax: { key: 'accountingSync.category.input_tax', en: 'Input tax (purchases)' },
};

const RULE_LABELS: Record<string, Label> = {
  'accounting_sync.unmapped_account': {
    key: 'accountingSync.rule.unmapped_account',
    en: 'Account not mapped',
  },
  'accounting_sync.tax_code_mismatch': {
    key: 'accountingSync.rule.tax_code_mismatch',
    en: 'Tax code does not match the mapping',
  },
  'accounting_sync.closed_period': {
    key: 'accountingSync.rule.closed_period',
    en: 'Posting date is in a closed period',
  },
  'accounting_sync.total_mismatch': {
    key: 'accountingSync.rule.total_mismatch',
    en: 'Net and tax do not add up to the gross total',
  },
  'accounting_sync.contact_missing_tax_id': {
    key: 'accountingSync.rule.contact_missing_tax_id',
    en: 'Counterparty has no tax ID',
  },
};

const EXPORT_LABELS: Record<ExportKind, Label> = {
  datev_postings: { key: 'accountingSync.export.datev_postings', en: 'DATEV postings (EXTF)' },
  datev_master: { key: 'accountingSync.export.datev_master', en: 'DATEV account master data' },
  journal_csv: { key: 'accountingSync.export.journal_csv', en: 'Journal CSV' },
  journal_xlsx: { key: 'accountingSync.export.journal_xlsx', en: 'Journal Excel' },
  saft: { key: 'accountingSync.export.saft', en: 'SAF-T XML' },
};

const COLUMN_LABELS: Record<string, Label> = {
  entry_no: { key: 'accountingSync.column.entry_no', en: 'Entry no.' },
  posting_date: { key: 'accountingSync.column.posting_date', en: 'Posting date' },
  document_number: { key: 'accountingSync.column.document_number', en: 'Document number' },
  source: { key: 'accountingSync.column.source', en: 'Source' },
  account: { key: 'accountingSync.column.account', en: 'Account' },
  account_name: { key: 'accountingSync.column.account_name', en: 'Account name' },
  debit: { key: 'accountingSync.column.debit', en: 'Debit' },
  credit: { key: 'accountingSync.column.credit', en: 'Credit' },
  currency: { key: 'accountingSync.column.currency', en: 'Currency' },
  tax_code: { key: 'accountingSync.column.tax_code', en: 'Tax code' },
  tax_key: { key: 'accountingSync.column.tax_key', en: 'Tax key' },
  tax_rate: { key: 'accountingSync.column.tax_rate', en: 'Tax rate' },
  tax_amount: { key: 'accountingSync.column.tax_amount', en: 'Tax amount' },
  cost_centre: { key: 'accountingSync.column.cost_centre', en: 'Cost centre' },
  project: { key: 'accountingSync.column.project', en: 'Project' },
  counterparty: { key: 'accountingSync.column.counterparty', en: 'Counterparty' },
  description: { key: 'accountingSync.column.description', en: 'Description' },
};

const SOURCE_LABELS: Record<DocumentSource, Label> = {
  invoice: { key: 'accountingSync.doc_source.invoice', en: 'Invoice' },
  interim_payment: { key: 'accountingSync.doc_source.interim_payment', en: 'Interim payment' },
  subcontractor: { key: 'accountingSync.doc_source.subcontractor', en: 'Subcontractor' },
  procurement: { key: 'accountingSync.doc_source.procurement', en: 'Procurement' },
  guarantee_fee: { key: 'accountingSync.doc_source.guarantee_fee', en: 'Guarantee fee' },
  payroll: { key: 'accountingSync.doc_source.payroll', en: 'Payroll' },
};

const RECORD_TYPE_LABELS: Record<DocumentRecordType, Label> = {
  ar_invoice: { key: 'accountingSync.record.ar_invoice', en: 'Sales invoice' },
  ap_bill: { key: 'accountingSync.record.ap_bill', en: 'Supplier bill' },
};

const ACTION_LABELS: Record<LogAction, Label> = {
  push: { key: 'accountingSync.action.push', en: 'Push' },
  pull: { key: 'accountingSync.action.pull', en: 'Pull' },
  export: { key: 'accountingSync.action.export', en: 'Export' },
  connect: { key: 'accountingSync.action.connect', en: 'Connect' },
};

const LOG_STATUS_LABELS: Record<LogStatus, Label> = {
  success: { key: 'accountingSync.status.success', en: 'Synced' },
  failed: { key: 'accountingSync.status.failed', en: 'Failed' },
  skipped: { key: 'accountingSync.status.skipped', en: 'Skipped' },
};

const DIRECTION_LABELS: Record<TaxDirection, Label> = {
  sales: { key: 'accountingSync.direction.sales', en: 'Sales' },
  purchase: { key: 'accountingSync.direction.purchase', en: 'Purchase' },
};

const SEVERITY_LABELS: Record<string, Label> = {
  error: { key: 'accountingSync.severity.error', en: 'Error' },
  warning: { key: 'accountingSync.severity.warning', en: 'Warning' },
  info: { key: 'accountingSync.severity.info', en: 'Note' },
};

function humanize(code: string): string {
  const s = code.replace(/[._]/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function pick(table: Record<string, Label>, t: TFunction, code: string, fallbackToCode = true): string {
  const l = table[code];
  if (l) return t(l.key, { defaultValue: l.en });
  return fallbackToCode ? humanize(code) : code;
}

export const providerLabel = (t: TFunction, v: Provider) => pick(PROVIDER_LABELS, t, v);
export const providerHelp = (t: TFunction, v: Provider) => pick(PROVIDER_HELP, t, v);
export const categoryLabel = (t: TFunction, v: string) => pick(CATEGORY_LABELS, t, v);
export const columnLabel = (t: TFunction, v: string) => pick(COLUMN_LABELS, t, v);
export const exportLabel = (t: TFunction, v: ExportKind) => pick(EXPORT_LABELS, t, v);
export const sourceLabel = (t: TFunction, v: string) => pick(SOURCE_LABELS, t, v);
export const recordTypeLabel = (t: TFunction, v: string) => pick(RECORD_TYPE_LABELS, t, v);
export const actionLabel = (t: TFunction, v: string) => pick(ACTION_LABELS, t, v);
export const logStatusLabel = (t: TFunction, v: string) => pick(LOG_STATUS_LABELS, t, v);
export const directionLabel = (t: TFunction, v: string) => pick(DIRECTION_LABELS, t, v);
export const severityLabel = (t: TFunction, v: string) => pick(SEVERITY_LABELS, t, v);
export const ruleLabel = (t: TFunction, ruleId: string) => {
  const l = RULE_LABELS[ruleId];
  return l ? t(l.key, { defaultValue: l.en }) : humanize(ruleId.split('.').pop() ?? ruleId);
};

export function logStatusVariant(s: string): BadgeVariant {
  if (s === 'success') return 'success';
  if (s === 'failed') return 'error';
  return 'neutral';
}

/** Tailwind classes per finding severity. */
export function severityClass(severity: string): string {
  if (severity === 'error') return 'bg-rose-100 text-rose-700';
  if (severity === 'warning') return 'bg-amber-100 text-amber-700';
  return 'bg-sky-100 text-sky-700';
}
