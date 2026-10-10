// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The parts of the UBL-TR (e-Fatura) screen that decide something and draw
 * nothing: the form's shape, the checks the server will apply to it, which
 * catalogue sentence a finding gets, and which field a finding points at.
 *
 * Kept apart from the components because each of these has an answer that can
 * be wrong while the screen looks right, and a pure function can be asked
 * directly.
 */
import type { EInvoiceViolation, TrEInvoiceFields } from './api';

/**
 * The scenarios and invoice types the export supports. The API validates
 * against the same two sets (``SUPPORTED_PROFILES`` and
 * ``SUPPORTED_INVOICE_TYPES`` in the einvoice module) and does not serve them,
 * so they are repeated here. They are codes of the format, written the same in
 * every language.
 */
export const TR_SCENARIOS = ['TEMELFATURA', 'TICARIFATURA', 'EARSIVFATURA'] as const;
export const TR_INVOICE_TYPES = ['SATIS', 'TEVKIFAT', 'IADE', 'ISTISNA'] as const;

/** The invoice type that answers another invoice. */
export const TR_RETURN_TYPE = 'IADE';

/** The currency a Turkish invoice needs no exchange rate for. */
export const TR_HOME_CURRENCY = 'TRY';

/** The fields of the Turkish block this screen edits, as the inputs hold them. */
export type TrFormState = {
  profile_id: string;
  invoice_type: string;
  document_id: string;
  series: string;
  issue_time: string;
  exchange_rate: string;
  exchange_rate_date: string;
  exemption_reason_code: string;
  exemption_reason: string;
  original_invoice_id: string;
  original_document_id: string;
  original_issue_date: string;
};

export type TrFieldName = keyof TrFormState;

/**
 * Party details an e-Fatura needs and an EN 16931 invoice does not. They live
 * in ``metadata.einvoice.seller`` and ``metadata.einvoice.buyer`` of the
 * invoice, above the e-invoice settings and the linked contact.
 */
export const TR_PARTY_KEYS = ['tax_office', 'district', 'building_number'] as const;
export type TrPartyKey = (typeof TR_PARTY_KEYS)[number];
export type TrPartyRole = 'seller' | 'buyer';
export type TrPartyFieldName = `${TrPartyRole}_${TrPartyKey}`;
export type TrPartyFormState = Record<TrPartyFieldName, string>;

export const TR_PARTY_ROLES: readonly TrPartyRole[] = ['seller', 'buyer'];

export function trPartyField(role: TrPartyRole, key: TrPartyKey): TrPartyFieldName {
  return `${role}_${key}`;
}

export const EMPTY_TR_FORM: TrFormState = {
  profile_id: '',
  invoice_type: '',
  document_id: '',
  series: '',
  issue_time: '',
  exchange_rate: '',
  exchange_rate_date: '',
  exemption_reason_code: '',
  exemption_reason: '',
  original_invoice_id: '',
  original_document_id: '',
  original_issue_date: '',
};

export const EMPTY_TR_PARTIES: TrPartyFormState = {
  seller_tax_office: '',
  seller_district: '',
  seller_building_number: '',
  buyer_tax_office: '',
  buyer_district: '',
  buyer_building_number: '',
};

/** The stored block as the inputs hold it. */
export function trFormFromFields(fields: TrEInvoiceFields): TrFormState {
  return {
    profile_id: fields.profile_id ?? '',
    invoice_type: fields.invoice_type ?? '',
    document_id: fields.document_id ?? '',
    series: fields.series ?? '',
    issue_time: fields.issue_time ?? '',
    exchange_rate: fields.exchange_rate ?? '',
    exchange_rate_date: fields.exchange_rate_date ?? '',
    exemption_reason_code: fields.exemption_reason_code ?? '',
    exemption_reason: fields.exemption_reason ?? '',
    original_invoice_id: fields.original_invoice_id ?? '',
    original_document_id: fields.original_invoice?.document_id ?? '',
    original_issue_date: fields.original_invoice?.issue_date ?? '',
  };
}

/** A browser's time input drops the seconds when they are zero; the format writes them. */
function fullTime(value: string): string {
  return /^\d{2}:\d{2}$/.test(value) ? `${value}:00` : value;
}

/**
 * The block to send. The write replaces the whole block, so every field this
 * screen does not show (per-line withholding, notes, the TaxTotal convention,
 * the customization id, the amount in words) is carried over from what was
 * stored instead of being cleared by a save that never mentioned it.
 */
export function trFieldsFromForm(form: TrFormState, stored: TrEInvoiceFields): TrEInvoiceFields {
  const originalNumber = form.original_document_id.trim();
  const originalDate = form.original_issue_date.trim();
  return {
    ...stored,
    profile_id: form.profile_id.trim().toUpperCase(),
    invoice_type: form.invoice_type.trim().toUpperCase(),
    document_id: form.document_id.trim().toUpperCase(),
    series: form.series.trim().toUpperCase(),
    issue_time: fullTime(form.issue_time.trim()),
    exchange_rate: form.exchange_rate.trim(),
    exchange_rate_date: form.exchange_rate_date.trim(),
    exemption_reason_code: form.exemption_reason_code.trim().toUpperCase(),
    exemption_reason: form.exemption_reason.trim(),
    original_invoice_id: form.original_invoice_id.trim(),
    original_invoice:
      originalNumber || originalDate ? { document_id: originalNumber, issue_date: originalDate } : null,
  };
}

export function sameForm<T extends Record<string, string>>(left: T, right: T): boolean {
  return Object.keys(left).every((key) => left[key] === right[key]);
}

/* ── Checks, as the schema applies them ───────────────────────────────── */

/**
 * What is wrong with one field, as the suffix of an i18n key under
 * ``einvoice.tr.error``.
 */
export type TrFieldError =
  | 'document_id_format'
  | 'document_id_series'
  | 'series_format'
  | 'issue_time_format'
  | 'exchange_rate_format'
  | 'date_format'
  | 'exemption_reason_length'
  | 'original_incomplete'
  | 'original_document_id_length';

const DOCUMENT_ID = /^[A-Z0-9]{3}20[0-9]{2}[0-9]{9}$/;
const SERIES = /^[A-Z0-9]{3}$/;
const TIME = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/;
const DECIMAL = /^(\d+\.?\d*|\.\d+)$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export const EXEMPTION_REASON_MAX = 500;
export const ORIGINAL_DOCUMENT_ID_MAX = 64;

/** A date written YYYY-MM-DD that exists in the calendar. */
export function isIsoDate(value: string): boolean {
  const parts = ISO_DATE.exec(value);
  if (!parts) return false;
  const [year, month, day] = [Number(parts[1]), Number(parts[2]), Number(parts[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/**
 * A decimal greater than zero, judged on the digits. The rate is never parsed
 * into a float: it travels to the server as the text that was typed.
 */
export function isPositiveDecimal(value: string): boolean {
  return DECIMAL.test(value) && /[1-9]/.test(value);
}

/**
 * The checks the server applies to the block, so a mistake is named beside
 * its field before a save is refused. The exemption reason code is left to
 * the server: the published code list is not served, and a copy of it here
 * would go stale the next time the revenue administration revises it.
 */
export function validateTrForm(form: TrFormState): Partial<Record<TrFieldName, TrFieldError>> {
  const errors: Partial<Record<TrFieldName, TrFieldError>> = {};
  const documentId = form.document_id.trim().toUpperCase();
  const series = form.series.trim().toUpperCase();

  if (series && !SERIES.test(series)) errors.series = 'series_format';
  if (documentId && !DOCUMENT_ID.test(documentId)) errors.document_id = 'document_id_format';
  else if (documentId && series && !errors.series && !documentId.startsWith(series)) {
    errors.document_id = 'document_id_series';
  }

  const time = form.issue_time.trim();
  if (time && !TIME.test(time)) errors.issue_time = 'issue_time_format';

  const rate = form.exchange_rate.trim();
  if (rate && !isPositiveDecimal(rate)) errors.exchange_rate = 'exchange_rate_format';

  const rateDate = form.exchange_rate_date.trim();
  if (rateDate && !isIsoDate(rateDate)) errors.exchange_rate_date = 'date_format';

  if (form.exemption_reason.trim().length > EXEMPTION_REASON_MAX) {
    errors.exemption_reason = 'exemption_reason_length';
  }

  const originalNumber = form.original_document_id.trim();
  const originalDate = form.original_issue_date.trim();
  if (originalNumber.length > ORIGINAL_DOCUMENT_ID_MAX) {
    errors.original_document_id = 'original_document_id_length';
  } else if (!originalNumber && originalDate) {
    errors.original_document_id = 'original_incomplete';
  }
  if (originalDate && !isIsoDate(originalDate)) errors.original_issue_date = 'date_format';
  else if (originalNumber && !originalDate) errors.original_issue_date = 'original_incomplete';

  return errors;
}

/* ── Party details in the invoice metadata ────────────────────────────── */

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** The party details this invoice states for itself; blank where it states none. */
export function trPartiesFromMetadata(metadata: unknown): TrPartyFormState {
  const einvoice = asRecord(asRecord(metadata).einvoice);
  const out: TrPartyFormState = { ...EMPTY_TR_PARTIES };
  for (const role of TR_PARTY_ROLES) {
    const party = asRecord(einvoice[role]);
    for (const key of TR_PARTY_KEYS) {
      const value = party[key];
      out[trPartyField(role, key)] = typeof value === 'string' ? value : '';
    }
  }
  return out;
}

/**
 * The invoice metadata with the party details written in. Everything else in
 * the object is kept, because the column is replaced whole. A blank detail is
 * removed rather than stored empty, so the e-invoice settings and the linked
 * contact answer for it again.
 */
export function metadataWithTrParties(metadata: unknown, parties: TrPartyFormState): Record<string, unknown> {
  const base = asRecord(metadata);
  const einvoice: Record<string, unknown> = { ...asRecord(base.einvoice) };
  for (const role of TR_PARTY_ROLES) {
    const party: Record<string, unknown> = { ...asRecord(einvoice[role]) };
    for (const key of TR_PARTY_KEYS) {
      const value = parties[trPartyField(role, key)].trim();
      if (value) party[key] = value;
      else delete party[key];
    }
    if (Object.keys(party).length > 0) einvoice[role] = party;
    else delete einvoice[role];
  }
  return { ...base, einvoice };
}

/* ── Findings ─────────────────────────────────────────────────────────── */

const RULE_PREFIX = 'einvoice.rule.';

/**
 * Rules that carry two sentences under one id. The report sends the id and
 * the values, not which sentence it meant, so the values decide: the short
 * form of a rule is the one raised with nothing to quote.
 */
const RULE_VARIANTS: Record<string, { suffix: string; applies: (params: Record<string, string>) => boolean }> = {
  'TR-ID-01': { suffix: 'empty', applies: (params) => !('document_id' in params) },
  'TR-DATE-01': { suffix: 'early', applies: (params) => 'earliest' in params },
  'TR-PARTY-04': { suffix: 'country', applies: (params) => 'country_code' in params },
  'TR-LINE-01': { suffix: 'none', applies: (params) => !('line' in params) },
  'TR-TAX-01': { suffix: 'none', applies: (params) => !('group' in params) },
};

/** The catalogue key of the sentence for one finding. */
export function ruleKey(violation: Pick<EInvoiceViolation, 'rule_id' | 'params'>): string {
  const variant = RULE_VARIANTS[violation.rule_id];
  const base = `${RULE_PREFIX}${violation.rule_id}`;
  return variant && variant.applies(violation.params ?? {}) ? `${base}.${variant.suffix}` : base;
}

/**
 * The placeholders of a catalogue sentence that the finding has no value for.
 * One id can be raised from several places with different values, and a
 * sentence printed with a hole in it says less than the engine's own.
 */
export function missingPlaceholders(template: string, values: Record<string, unknown>): string[] {
  const missing: string[] = [];
  for (const match of template.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)) {
    const name = match[1];
    if (name && !(name in values) && !missing.includes(name)) missing.push(name);
  }
  return missing;
}

/** A field of this screen a finding can send the reader to. */
export type TrFocusTarget = TrFieldName | TrPartyFieldName;

const PARTY_WRAPPERS: Record<string, TrPartyRole> = {
  AccountingSupplierParty: 'seller',
  AccountingCustomerParty: 'buyer',
};

/**
 * The field at fault, when the finding names one this screen holds. A finding
 * about the taxes, the lines or the invoice date is fixed elsewhere and gets
 * no jump: a link that lands on an unrelated input is worse than none.
 */
export function focusTargetFor(violation: Pick<EInvoiceViolation, 'rule_id' | 'term'>): TrFocusTarget | null {
  const term = violation.term ?? '';
  if (violation.rule_id.startsWith('TR-EXM-')) return 'exemption_reason_code';
  if (violation.rule_id === 'TR-WH-01' || violation.rule_id === 'TR-WH-02') return 'invoice_type';
  if (term === 'ProfileID') return 'profile_id';
  if (term === 'InvoiceTypeCode') return 'invoice_type';
  if (term === 'ID') return 'document_id';
  if (term.startsWith('PricingExchangeRate')) return 'exchange_rate';
  if (term.startsWith('BillingReference')) return 'original_document_id';

  const [wrapper, ...rest] = term.split('/');
  const role = wrapper ? PARTY_WRAPPERS[wrapper] : undefined;
  if (!role) return null;
  const path = rest.join('/');
  if (path.startsWith('PartyTaxScheme')) return `${role}_tax_office`;
  if (path === 'PostalAddress') return `${role}_district`;
  return null;
}

/** The DOM id of the input that holds one field. */
export function trFieldId(name: TrFocusTarget): string {
  return `einvoice-tr-${name}`;
}
