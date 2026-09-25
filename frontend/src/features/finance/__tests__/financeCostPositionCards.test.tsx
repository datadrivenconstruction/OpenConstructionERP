// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Finance summary cards show the project's cost position: budget,
 * committed, invoiced, paid, and what is still unpaid, each with its basis.
 *
 * The dashboard returned committed all along and the screen never drew it,
 * and the card labelled "Total Invoiced (Payable)" showed the unpaid
 * supplier invoices, gross, which is a different figure. The numbers below
 * are the ones the backend integration test asserts for the same scenario
 * (tests/integration/test_finance_project_cost_position.py), so a card that
 * reads the wrong field shows the wrong number here.
 *
 * Run:  npx vitest run src/features/finance/__tests__/financeCostPositionCards.test.tsx
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { FinanceSummaryCards } from '../FinancePage';

const harness = vi.hoisted(() => ({
  dashboard: {} as Record<string, unknown>,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = String(opts.defaultValue ?? '');
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return _key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: harness.dashboard,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  }),
  useMutation: () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn(), setQueryData: vi.fn() }),
}));

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn().mockResolvedValue({}),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (e: unknown) => String(e),
  triggerDownload: vi.fn(),
  API_BASE: '/api',
  getAuthToken: () => 'tok',
  ApiError: class ApiError extends Error {},
}));

/** The Croatian contractor scenario, as the API serialises it (strings). */
const SCENARIO = {
  total_budget_original: '400000.00',
  total_budget_revised: '400000.00',
  total_committed: '172000.00',
  total_invoiced: '72000.00',
  total_paid: '78500.00',
  total_actual: '68500.00',
  total_payable: '2500.00',
  total_receivable: '0',
  total_overdue: '0',
  total_payments: '50000.00',
  budget_consumed_pct: 17.1,
  budget_warning_level: 'normal',
  currency: 'EUR',
};

function renderCards() {
  return render(
    <MemoryRouter>
      <FinanceSummaryCards projectId="proj-1" />
    </MemoryRouter>,
  );
}

/** Digits of a whole amount, whatever the grouping separator. */
function amount(whole: string): RegExp {
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '[,.\\s\\u00a0\\u202f]?');
  return new RegExp(grouped);
}

describe('Finance cost position cards', () => {
  it.each([
    ['budget', 'Total Budget', '400000', 'Net of VAT'],
    ['committed', 'Committed', '172000', 'Net of VAT'],
    ['invoiced', 'Invoiced', '72000', 'Net of VAT'],
    ['paid', 'Paid', '78500', 'Incl. VAT'],
    ['unpaid', 'Unpaid supplier invoices', '2500', 'Incl. VAT'],
    ['remaining', 'Remaining Budget', '331500', 'Net of VAT'],
  ])('shows %s from its own field, labelled, with its basis', (key, label, whole, basis) => {
    harness.dashboard = SCENARIO;
    renderCards();

    const card = screen.getByTestId(`finance-card-${key}`);
    expect(within(card).getByText(label)).toBeInTheDocument();
    expect(card.textContent).toMatch(amount(whole));
    expect(within(card).getByText(basis)).toBeInTheDocument();
  }, 120000);

  it('no longer calls the unpaid balance "Total Invoiced"', () => {
    harness.dashboard = SCENARIO;
    renderCards();
    expect(screen.queryByText('Total Invoiced (Payable)')).not.toBeInTheDocument();
  }, 120000);

  it('treats a project with only commitments as having financial data', () => {
    harness.dashboard = {
      ...SCENARIO,
      total_budget_original: '0',
      total_budget_revised: '0',
      total_invoiced: '0',
      total_paid: '0',
      total_actual: '0',
      total_payable: '0',
      total_committed: '50000.00',
    };
    renderCards();
    expect(screen.getByTestId('finance-card-committed').textContent).toMatch(amount('50000'));
  }, 120000);
});
