// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The decisions of the UBL-TR (e-Fatura) screen, asked directly.
//
// Each of these can be wrong while the screen looks right. A save that drops
// the fields the form does not show still succeeds. A finding printed with the
// wrong one of a rule's two sentences still reads as a sentence. A jump that
// lands on the wrong input still moves the focus. So they are pinned here, on
// the functions, instead of through a render that would have to be read by
// eye to tell the difference.

import { describe, expect, it } from 'vitest';

import type { TrEInvoiceFields } from './api';
import {
  EMPTY_TR_FORM,
  EMPTY_TR_PARTIES,
  focusTargetFor,
  isPositiveDecimal,
  metadataWithTrParties,
  missingPlaceholders,
  ruleKey,
  trFieldsFromForm,
  trFormFromFields,
  trPartiesFromMetadata,
  validateTrForm,
} from './einvoiceTr';

const STORED: TrEInvoiceFields = {
  profile_id: 'TICARIFATURA',
  invoice_type: '',
  document_id: '',
  series: '',
  issue_time: '',
  exchange_rate: '',
  exchange_rate_date: '',
  exemption_reason_code: '',
  exemption_reason: '',
  original_invoice: null,
  original_invoice_id: '',
  line_withholding: { 'line-1': '601' },
  tax_total_convention: 'computed',
  customization_id: 'TR1.2.1',
  amount_in_words: false,
  notes: ['Printed on the invoice'],
};

describe('trFieldsFromForm', () => {
  it('sends back the fields the form does not show, because the write replaces the block', () => {
    const sent = trFieldsFromForm({ ...trFormFromFields(STORED), series: 'abc' }, STORED);

    expect(sent.series).toBe('ABC');
    expect(sent.line_withholding).toEqual({ 'line-1': '601' });
    expect(sent.tax_total_convention).toBe('computed');
    expect(sent.customization_id).toBe('TR1.2.1');
    expect(sent.amount_in_words).toBe(false);
    expect(sent.notes).toEqual(['Printed on the invoice']);
  });

  it('writes the seconds a browser time input leaves out', () => {
    expect(trFieldsFromForm({ ...EMPTY_TR_FORM, issue_time: '14:30' }, STORED).issue_time).toBe('14:30:00');
    expect(trFieldsFromForm({ ...EMPTY_TR_FORM, issue_time: '14:30:05' }, STORED).issue_time).toBe('14:30:05');
  });

  it('sends no original invoice when neither its number nor its date is given', () => {
    expect(trFieldsFromForm(EMPTY_TR_FORM, STORED).original_invoice).toBeNull();
    expect(
      trFieldsFromForm(
        { ...EMPTY_TR_FORM, original_document_id: 'ABC2026000000001', original_issue_date: '2026-03-01' },
        STORED,
      ).original_invoice,
    ).toEqual({ document_id: 'ABC2026000000001', issue_date: '2026-03-01' });
  });

  it('round-trips a stored original invoice through the form', () => {
    const stored = { ...STORED, original_invoice: { document_id: 'ABC2026000000001', issue_date: '2026-03-01' } };

    expect(trFieldsFromForm(trFormFromFields(stored), stored)).toEqual(stored);
  });
});

describe('validateTrForm', () => {
  it('accepts an empty form: every field is optional until the report asks for it', () => {
    expect(validateTrForm(EMPTY_TR_FORM)).toEqual({});
  });

  it('judges the invoice number as the server will, after upper-casing it', () => {
    expect(validateTrForm({ ...EMPTY_TR_FORM, document_id: 'abc2026000000001' })).toEqual({});
    expect(validateTrForm({ ...EMPTY_TR_FORM, document_id: 'ABC2026' }).document_id).toBe('document_id_format');
    // Sixteen characters, but the year does not start with 20.
    expect(validateTrForm({ ...EMPTY_TR_FORM, document_id: 'ABC1999000000001' }).document_id).toBe(
      'document_id_format',
    );
  });

  it('requires the number to start with the series when both are given', () => {
    const form = { ...EMPTY_TR_FORM, document_id: 'ABC2026000000001' };

    expect(validateTrForm({ ...form, series: 'ABC' })).toEqual({});
    expect(validateTrForm({ ...form, series: 'XYZ' }).document_id).toBe('document_id_series');
    expect(validateTrForm({ ...form, series: 'AB' }).series).toBe('series_format');
  });

  it('takes the exchange rate as digits and refuses zero', () => {
    expect(isPositiveDecimal('34.5120')).toBe(true);
    expect(isPositiveDecimal('0.000')).toBe(false);
    expect(isPositiveDecimal('34,5')).toBe(false);
    expect(isPositiveDecimal('-1')).toBe(false);
    expect(validateTrForm({ ...EMPTY_TR_FORM, exchange_rate: '0' }).exchange_rate).toBe('exchange_rate_format');
  });

  it('refuses a date that is not in the calendar and a time that is not on the clock', () => {
    expect(validateTrForm({ ...EMPTY_TR_FORM, exchange_rate_date: '2026-02-30' }).exchange_rate_date).toBe(
      'date_format',
    );
    expect(validateTrForm({ ...EMPTY_TR_FORM, issue_time: '25:00:00' }).issue_time).toBe('issue_time_format');
    expect(validateTrForm({ ...EMPTY_TR_FORM, issue_time: '09:15' })).toEqual({});
  });

  it('asks for both halves of the original invoice once one is given', () => {
    expect(validateTrForm({ ...EMPTY_TR_FORM, original_document_id: 'ABC2026000000001' }).original_issue_date).toBe(
      'original_incomplete',
    );
    expect(validateTrForm({ ...EMPTY_TR_FORM, original_issue_date: '2026-03-01' }).original_document_id).toBe(
      'original_incomplete',
    );
  });
});

describe('party details in the invoice metadata', () => {
  const metadata = {
    po_id: 'po-7',
    einvoice: {
      buyer_reference: 'L-1',
      seller: { name: 'Kept as it was', tax_office: 'Old office' },
      tr: { profile_id: 'TEMELFATURA' },
    },
  };

  it('reads what the invoice states and leaves the rest blank', () => {
    expect(trPartiesFromMetadata(metadata)).toEqual({ ...EMPTY_TR_PARTIES, seller_tax_office: 'Old office' });
    expect(trPartiesFromMetadata(null)).toEqual(EMPTY_TR_PARTIES);
  });

  it('writes a detail without touching anything else in the object', () => {
    const next = metadataWithTrParties(metadata, {
      ...EMPTY_TR_PARTIES,
      seller_tax_office: 'New office',
      buyer_district: 'Central',
    });

    expect(next).toEqual({
      po_id: 'po-7',
      einvoice: {
        buyer_reference: 'L-1',
        seller: { name: 'Kept as it was', tax_office: 'New office' },
        buyer: { district: 'Central' },
        tr: { profile_id: 'TEMELFATURA' },
      },
    });
  });

  it('removes a blanked detail so the settings answer for it again', () => {
    const next = metadataWithTrParties(metadata, EMPTY_TR_PARTIES);

    expect(next.einvoice).toEqual({
      buyer_reference: 'L-1',
      seller: { name: 'Kept as it was' },
      tr: { profile_id: 'TEMELFATURA' },
    });
  });
});

describe('ruleKey', () => {
  it('picks the short sentence of a rule raised with nothing to quote', () => {
    expect(ruleKey({ rule_id: 'TR-ID-01', params: {} })).toBe('einvoice.rule.TR-ID-01.empty');
    expect(ruleKey({ rule_id: 'TR-ID-01', params: { document_id: 'ABC' } })).toBe('einvoice.rule.TR-ID-01');
    expect(ruleKey({ rule_id: 'TR-LINE-01' })).toBe('einvoice.rule.TR-LINE-01.none');
    expect(ruleKey({ rule_id: 'TR-LINE-01', params: { line: '2', problems: 'no quantity' } })).toBe(
      'einvoice.rule.TR-LINE-01',
    );
    expect(ruleKey({ rule_id: 'TR-TAX-01', params: {} })).toBe('einvoice.rule.TR-TAX-01.none');
  });

  it('picks the second sentence by the value only that one names', () => {
    expect(ruleKey({ rule_id: 'TR-DATE-01', params: { issue_date: '2004-01-01', earliest: '2005-01-01' } })).toBe(
      'einvoice.rule.TR-DATE-01.early',
    );
    expect(ruleKey({ rule_id: 'TR-DATE-01', params: { issue_date: '2027-01-01', today: '2026-10-10' } })).toBe(
      'einvoice.rule.TR-DATE-01',
    );
    expect(ruleKey({ rule_id: 'TR-PARTY-04', params: { role: 'customer', country_code: 'XX' } })).toBe(
      'einvoice.rule.TR-PARTY-04.country',
    );
    expect(ruleKey({ rule_id: 'TR-PARTY-04', params: { role: 'customer', missing: 'district' } })).toBe(
      'einvoice.rule.TR-PARTY-04',
    );
  });

  it('leaves every other rule on its own id, the EN 16931 ones included', () => {
    expect(ruleKey({ rule_id: 'BR-DE-15' })).toBe('einvoice.rule.BR-DE-15');
    expect(ruleKey({ rule_id: 'OCE-TR-22', params: { status: 'draft' } })).toBe('einvoice.rule.OCE-TR-22');
  });
});

describe('missingPlaceholders', () => {
  it('names the values a sentence asks for and the finding does not carry', () => {
    expect(missingPlaceholders('Code {{code}} with {{percent}} percent', { code: '601' })).toEqual(['percent']);
    expect(missingPlaceholders('Code {{code}} with {{percent}} percent', { code: '601', percent: '40' })).toEqual([]);
    expect(missingPlaceholders('No values at all.', {})).toEqual([]);
  });
});

describe('focusTargetFor', () => {
  it('sends a finding to the field that holds what it names', () => {
    expect(focusTargetFor({ rule_id: 'TR-PROFILE-01', term: 'ProfileID' })).toBe('profile_id');
    expect(focusTargetFor({ rule_id: 'TR-TYPE-01', term: 'InvoiceTypeCode' })).toBe('invoice_type');
    expect(focusTargetFor({ rule_id: 'TR-ID-01', term: 'ID' })).toBe('document_id');
    expect(focusTargetFor({ rule_id: 'TR-CUR-01', term: 'PricingExchangeRate/CalculationRate' })).toBe(
      'exchange_rate',
    );
    expect(focusTargetFor({ rule_id: 'OCE-TR-12', term: 'BillingReference/InvoiceDocumentReference/ID' })).toBe(
      'original_document_id',
    );
    expect(focusTargetFor({ rule_id: 'TR-EXM-01', term: 'TaxSubtotal[0]' })).toBe('exemption_reason_code');
  });

  it('tells the seller from the buyer by the element the finding sits in', () => {
    expect(
      focusTargetFor({ rule_id: 'TR-PARTY-05', term: 'AccountingSupplierParty/PartyTaxScheme/TaxScheme/Name' }),
    ).toBe('seller_tax_office');
    expect(
      focusTargetFor({ rule_id: 'TR-PARTY-05', term: 'AccountingCustomerParty/PartyTaxScheme/TaxScheme/Name' }),
    ).toBe('buyer_tax_office');
    expect(focusTargetFor({ rule_id: 'TR-PARTY-04', term: 'AccountingCustomerParty/PostalAddress' })).toBe(
      'buyer_district',
    );
  });

  it('offers no jump for what is fixed somewhere else', () => {
    // The taxes, the lines and the invoice date are not fields of this screen.
    expect(focusTargetFor({ rule_id: 'OCE-TR-22', term: 'TaxTotal' })).toBeNull();
    expect(focusTargetFor({ rule_id: 'TR-LINE-01', term: 'InvoiceLine' })).toBeNull();
    expect(focusTargetFor({ rule_id: 'TR-DATE-01', term: 'IssueDate' })).toBeNull();
    expect(focusTargetFor({ rule_id: 'TR-PARTY-01', term: 'AccountingCustomerParty/PartyIdentification/ID' })).toBeNull();
    expect(focusTargetFor({ rule_id: 'BR-DE-15', term: 'BT-10' })).toBeNull();
    expect(focusTargetFor({ rule_id: 'OCE-PAY-01', term: null })).toBeNull();
  });
});
