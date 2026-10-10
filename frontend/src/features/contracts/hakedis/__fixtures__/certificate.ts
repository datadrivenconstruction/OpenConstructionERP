// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A payment certificate as the server answers it, for the component tests.
// Small on purpose: one line in each state, one tax of each kind.

import type { HakedisDocument, HakedisSummaryLine, HakedisTaxes } from '../api';

export function summaryLine(over: Partial<HakedisSummaryLine> & { key: string }): HakedisSummaryLine {
  return {
    letter: '',
    section: 'main',
    op: 'sum',
    sign: 1,
    tax_kind: '',
    status: 'value',
    amount: '0.00',
    text: '',
    labels: [over.key],
    formulas: [],
    details: [],
    basis: {},
    reason_key: '',
    reason_params: {},
    reason_text: [],
    notes: [],
    emphasis: false,
    enterable: false,
    accepts_percent: false,
    entered: null,
    ...over,
  };
}

export function taxes(over: Partial<HakedisTaxes> = {}): HakedisTaxes {
  return {
    available: true,
    stored: false,
    status: '',
    stale: false,
    expected_net_amount: '1000.00',
    expected_stamp_duty_base: '1000.00',
    vat_rate_pct: '20',
    document_date: '2026-09-30',
    direction: 'issued',
    choices: {},
    buyer_is_designated: null,
    work_value_incl_vat: null,
    work_value_note: '',
    categories: {
      vat_withholding: [
        {
          code: '601',
          label: 'Construction works',
          rate_pct: null,
          numerator: 4,
          denominator: 10,
          legal_reference: 'VAT General Communique I/C-2.1.3.2.1',
          review_status: 'confirmed',
          conditions: 'Applies to designated buyers',
          buyer_scope: 'designated_only',
        },
      ],
      income_withholding: [
        {
          code: 'GVK94-3',
          label: 'Multi-year construction',
          rate_pct: '5',
          numerator: null,
          denominator: null,
          legal_reference: 'Income Tax Law art. 94/3',
          review_status: 'unconfirmed',
          conditions: '',
          buyer_scope: 'any',
        },
      ],
      stamp_duty: [
        {
          code: 'DV-HAKEDIS',
          label: 'Progress payment',
          rate_pct: '0.948',
          numerator: null,
          denominator: null,
          legal_reference: 'Stamp Duty Law table 1',
          review_status: 'confirmed',
          conditions: '',
          buyer_scope: 'any',
        },
      ],
    },
    ...over,
  };
}

/** A draft certificate: one value line, one entered by hand and missing, one tax undecided, one ruled out. */
export function certificate(over: Partial<HakedisDocument> = {}): HakedisDocument {
  return {
    source_kind: 'progress_claim',
    source_id: 'claim-1',
    project_id: 'project-1',
    reference: 'PC-3',
    status: 'approved',
    locale: 'en',
    locales: ['tr', 'en', 'tr-en'],
    layout_available: true,
    editable: true,
    frozen: false,
    frozen_at: null,
    is_draft: true,
    currency: 'TRY',
    country_code: 'TR',
    flavour: 'unit_price',
    header: {
      certificate_number: 3,
      is_final: false,
      period_start: '2026-09-01',
      period_end: '2026-09-30',
      issue_date: '2026-09-30',
      project_name: 'Depot',
      contract_number: 'C-7',
      contract_title: 'Main works',
      employer: { name: 'Employer Ltd', tax_number: '1112223334', tax_office: 'Kadikoy', address: '' },
      contractor: { name: 'Builder Ltd', tax_number: '5556667778', tax_office: 'Besiktas', address: '' },
      rows: [
        { labels: ['Contract'], value: 'C-7 Main works' },
        { labels: ['Certificate no.'], value: '3' },
      ],
      party_rows: [
        { labels: ['Employer'], value: 'Employer Ltd, tax no. 1112223334, Kadikoy' },
        { labels: ['Contractor'], value: 'Builder Ltd, tax no. 5556667778, Besiktas' },
      ],
    },
    works: {
      columns: [
        { key: 'seq', letter: '', kind: 'seq', labels: ['No.'] },
        { key: 'description', letter: '', kind: 'text', labels: ['Description of work'] },
        { key: 'quantity', letter: 'A', kind: 'quantity', labels: ['Quantity'] },
        { key: 'unit_price', letter: 'B', kind: 'unit_price', labels: ['Unit price'] },
        { key: 'amount', letter: 'A x B', kind: 'money', labels: ['Amount'] },
      ],
      rows: [
        {
          kind: 'line',
          title: '',
          cells: ['1', 'Excavation', '12,500', '80,00', '1.000,00'],
          values: [null, null, '12.5', '80.00', '1000.00'],
          flagged: false,
          held: false,
        },
        {
          kind: 'line',
          title: '',
          cells: ['2', 'Formwork', '', '', ''],
          values: [null, null, null, null, null],
          flagged: false,
          held: true,
        },
        {
          kind: 'total',
          title: 'Total',
          cells: ['', '', '', '', '1.000,00'],
          values: [null, null, null, null, '1000.00'],
          flagged: false,
          held: false,
        },
      ],
      totals: {
        previous_amount: '0.00',
        period_amount: '1000.00',
        cumulative_amount: '1000.00',
        contract_amount: '50000.00',
      },
    },
    summary: [
      summaryLine({
        key: 'work_done',
        letter: 'A',
        op: 'input',
        labels: ['Work Done at Contract Prices'],
        amount: '1000.00',
        basis: { source: 'work_cumulative' },
      }),
      summaryLine({
        key: 'price_adjustment',
        letter: 'B',
        op: 'manual',
        labels: ['Price Adjustment'],
        status: 'held',
        amount: null,
        reason_key: 'not_entered',
        reason_text: ['No amount has been entered.'],
        notes: [1],
        enterable: true,
      }),
      summaryLine({
        key: 'total',
        letter: 'C',
        labels: ['Total Amount'],
        formulas: ['(A + B)'],
        status: 'held',
        amount: null,
        reason_key: 'operand_held',
        reason_params: { operands: 'price_adjustment' },
        reason_text: ['Depends on held lines: price_adjustment.'],
      }),
      summaryLine({
        key: 'vat_withholding',
        letter: 'c',
        section: 'deductions',
        op: 'tax',
        sign: -1,
        tax_kind: 'vat_withheld',
        labels: ['VAT Withholding'],
        status: 'held',
        amount: null,
        reason_key: 'not_chosen',
        reason_text: ['No category has been chosen yet.'],
        notes: [2],
      }),
      summaryLine({
        key: 'delay_penalty',
        letter: 'f',
        section: 'deductions',
        op: 'manual',
        sign: -1,
        labels: ['Delay Penalty'],
        status: 'not_applicable',
        amount: null,
        text: '-',
        details: ['No delay on this contract'],
        basis: { note: 'No delay on this contract' },
        enterable: true,
        entered: { state: 'not_applicable', amount: null, pct: null, note: 'No delay on this contract' },
      }),
      summaryLine({
        key: 'payable',
        labels: ['Amount Payable to the Contractor'],
        status: 'held',
        amount: null,
        reason_key: 'operand_held',
        reason_params: { operands: 'total' },
        reason_text: ['Depends on held lines: total.'],
        emphasis: true,
      }),
    ],
    notes: [
      {
        number: 1,
        line_key: 'price_adjustment',
        letter: 'B',
        reason_key: 'not_entered',
        reason_params: {},
        text: ['No amount has been entered.'],
      },
      {
        number: 2,
        line_key: 'vat_withholding',
        letter: 'c',
        reason_key: 'not_chosen',
        reason_params: {},
        text: ['No category has been chosen yet.'],
      },
    ],
    taxes: taxes(),
    options: { is_final: false },
    signature_roles: [
      { key: 'contractor', labels: ['Contractor'] },
      { key: 'approved_by', labels: ['Approved by'] },
    ],
    carried_total: null,
    findings: [
      {
        rule_id: 'hakedis.lines_complete',
        rule_name: 'Lines complete',
        severity: 'error',
        message: 'Line B has no figure.',
        suggestion: null,
        element_ref: 'price_adjustment',
        details: {},
        engine_error: false,
      },
      {
        rule_id: 'hakedis.work_value_differs',
        rule_name: 'Work value',
        severity: 'warning',
        message: 'The work value differs from the contract.',
        suggestion: 'Check the contract value.',
        element_ref: null,
        details: {},
        engine_error: false,
      },
    ],
    can_certify: false,
    ...over,
  };
}

/** The same certificate with every line settled: nothing held, taxes confirmed, ready to certify. */
export function settledCertificate(over: Partial<HakedisDocument> = {}): HakedisDocument {
  const base = certificate();
  return certificate({
    is_draft: false,
    summary: base.summary.map((line): HakedisSummaryLine =>
      line.status === 'held'
        ? { ...line, status: 'value', amount: '100.00', reason_key: '', reason_params: {}, reason_text: [], notes: [] }
        : line,
    ),
    notes: [],
    findings: [],
    can_certify: true,
    taxes: taxes({ stored: true, status: 'confirmed' }),
    ...over,
  });
}
