// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Deductions tab and bidder radius filter. Figures are worked example 1:
// invoice 120,000.00, levies 1,440.00, retention 11,856.00, payable 106,704.00,
// 2 % discount 2,134.08, to pay 104,569.92.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

vi.mock('../termsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../termsApi')>();
  return {
    ...actual,
    getAgreementTerms: vi.fn(),
    getLevyCatalogue: vi.fn(),
    getDeductions: vi.fn(),
  };
});

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, listPaymentApplications: vi.fn() };
});

import { SubcontractTermsPanel, StatementTable, decimalInput } from '../SubcontractTermsPanel';
import { applyBidderSearch, isFiltering } from '@/features/tendering/BidderRadiusBar';
import * as termsApi from '../termsApi';
import * as api from '../api';

const STATEMENT: termsApi.DeductionStatement = {
  agreement_id: 'ag-1',
  payment_application_id: null,
  application_number: null,
  currency: 'EUR',
  contract_sum: '400008.60',
  work_value: '120000.00',
  deduction_order: 'levies_then_retention',
  levies_total: '1440.00',
  retention_percent: '10',
  retention_amount: '11856.00',
  retention_capped: false,
  retention_cap_amount: '20000.43',
  payable: '106704.00',
  payment_discount_percent: '2',
  payment_discount_days: 14,
  payment_discount_agreed: true,
  payment_discount_amount: '2134.08',
  payable_with_discount: '104569.92',
  discount_due_date: '2026-03-16',
  discount_applies: true,
  amount_to_pay: '104569.92',
  lines: [
    { kind: 'work_value', amount: '120000.00' },
    { kind: 'levy', code: 'insurance', name: 'Construction insurance', amount: '360.00' },
    { kind: 'levy', code: 'cleaning', name: 'Site cleaning', amount: '600.00' },
    { kind: 'levy', code: 'power', name: 'Site power and water', amount: '480.00' },
    { kind: 'after_levies', amount: '118560.00' },
    { kind: 'retention', amount: '11856.00' },
    { kind: 'payable', amount: '106704.00' },
    { kind: 'payment_discount', amount: '2134.08' },
  ],
  validation: [],
};

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.mocked(termsApi.getAgreementTerms).mockResolvedValue({
    deduction_order: 'levies_then_retention',
    retention_cap_percent: '5',
    payment_discount_percent: '2',
    payment_discount_days: 14,
    payment_discount_agreed: true,
    levies: [],
  });
  vi.mocked(termsApi.getLevyCatalogue).mockResolvedValue({ items: [], pack_defaults: [] });
  vi.mocked(termsApi.getDeductions).mockResolvedValue(STATEMENT);
  vi.mocked(api.listPaymentApplications).mockResolvedValue([]);
});

describe('StatementTable', () => {
  it('shows every deduction line and the amount to pay', () => {
    render(<StatementTable statement={STATEMENT} />);
    const table = screen.getByTestId('deduction-statement');
    expect(table.textContent).toContain('Construction insurance');
    expect(table.textContent).toContain('Site power and water');
    expect(screen.getByTestId('amount-to-pay').textContent).toMatch(/104[.,\s  ]?569[.,]92/);
  });

  it('says so when the discount date was missed', () => {
    render(
      <StatementTable statement={{ ...STATEMENT, discount_applies: false, amount_to_pay: '106704.00' }} />,
    );
    expect(screen.getByText(/discount date missed/i)).toBeTruthy();
    expect(screen.getByTestId('amount-to-pay').textContent).toMatch(/106[.,\s  ]?704/);
  });
});

describe('SubcontractTermsPanel', () => {
  it('runs the worked example on the saved terms', async () => {
    wrap(<SubcontractTermsPanel agreements={[{ id: 'ag-1', title: 'Drywall', currency: 'EUR' } as api.Agreement]} />);
    await waitFor(() => expect(termsApi.getDeductions).toHaveBeenCalledWith('ag-1', { work_value: '120000.00' }));
    expect(await screen.findByTestId('deduction-statement')).toBeTruthy();
    expect(screen.getByText(/payment discount is taken last/i)).toBeTruthy();
  });

  it('asks for an agreement first', () => {
    wrap(<SubcontractTermsPanel agreements={[]} />);
    expect(screen.getByText(/Create an agreement first/i)).toBeTruthy();
  });
});

describe('decimal input and bidder ordering', () => {
  it('keeps decimal strings and accepts a comma', () => {
    expect(decimalInput('0,3')).toBe('0.3');
    expect(decimalInput('  ')).toBeNull();
  });

  it('keeps only searched firms, in search order, when a filter is on', () => {
    const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    const search = {
      items: [{ id: 'c' }, { id: 'a' }] as termsApi.BidderRow[],
      total: 2,
      radius_km: '50',
      site_has_coordinates: true,
      without_coordinates: 0,
      hidden_blocked: 0,
      validation: [],
    };
    const off = { trade: '', radiusKm: null, favouritesOnly: false, includeOutside: false };
    expect(isFiltering(off)).toBe(false);
    expect(applyBidderSearch(rows, off, search)).toEqual(rows);
    expect(applyBidderSearch(rows, { ...off, radiusKm: 50 }, search).map((r) => r.id)).toEqual(['c', 'a']);
  });
});
