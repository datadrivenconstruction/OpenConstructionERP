// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A new contract starts from its project's country's usual payment terms.
//
// The form has two jobs here and both are about honesty. It shows the
// country's figures with a "Default for <country>" mark, and it sends only
// what the person changed, so the server fills the rest the same way and the
// contract records them as the country's rather than as typed. And where the
// country has no usual figures it shows empty fields and asks for the
// retention, instead of starting from a platform-wide 5 percent.
//
// The API layer runs for real (the mock is on apiGet/apiPost), so a wrong URL
// fails the test rather than passing it.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

const toast = vi.hoisted(() => ({ addToast: vi.fn() }));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof toast.addToast }) => unknown) =>
    sel({ addToast: toast.addToast }),
}));

import { CreateContractModal } from './ContractsPage';
import { ContractPaymentTermsSummary } from './ContractPaymentTerms';
import type { ContractCountryDefaults, ContractItem } from './api';

const GB: ContractCountryDefaults = {
  project_id: 'p-1',
  country_code: 'GB',
  has_defaults: true,
  standard_form: 'JCT 2016 / NEC4',
  values: {
    retention_percent: '3',
    retention_cap_percent: null,
    retention_release_split: [
      { event: 'substantial_completion', release_percent_of_held: '50' },
      { event: 'defects_period_end', release_percent_of_held: '100' },
    ],
    payment_period_days: 14,
    valuation_interval: 'monthly',
    certificate_name: 'Interim Certificate',
  },
  sources: {
    retention_percent: {
      source: 'standard_form',
      reference: 'JCT SBC 2016, Contract Particulars',
      note: 'Three percent applies when no other figure is stated.',
    },
    payment_period_days: { source: 'standard_form', reference: 'JCT SBC 2016', note: '14 days' },
  },
  release_split_source: 'table',
};

const NONE: ContractCountryDefaults = {
  project_id: 'p-1',
  country_code: 'IT',
  has_defaults: false,
  standard_form: null,
  values: {},
  sources: {},
  release_split_source: null,
};

function serve(defaults: ContractCountryDefaults | Error) {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/contracts/country-defaults/?project_id=p-1')) {
      return defaults instanceof Error ? Promise.reject(defaults) : Promise.resolve(defaults);
    }
    if (path.startsWith('/v1/contracts/contract-templates/')) return Promise.resolve([]);
    return Promise.reject(new Error(`not mocked: ${path}`));
  });
}

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreateContractModal projectId="p-1" defaultCurrency="GBP" onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function typeCode() {
  const code = screen.getByPlaceholderText('C-2026-001');
  fireEvent.change(code, { target: { value: 'C-77' } });
}

function sentPayload(): Record<string, unknown> {
  expect(api.apiPost).toHaveBeenCalledTimes(1);
  const call = api.apiPost.mock.calls[0]!;
  expect(call[0]).toBe('/v1/contracts/contracts/');
  return call[1] as Record<string, unknown>;
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPost.mockResolvedValue({ id: 'c-1' });
  toast.addToast.mockReset();
});

afterEach(cleanup);

describe('a new contract in a country with usual terms', () => {
  it("shows the country's figures, each marked as its default", async () => {
    serve(GB);
    renderModal();

    await waitFor(() =>
      expect((screen.getByTestId('contract-retention') as HTMLInputElement).value).toBe('3'),
    );
    expect((screen.getByTestId('contract-payment-days') as HTMLInputElement).value).toBe('14');
    expect((screen.getByTestId('contract-valuation-interval') as HTMLSelectElement).value).toBe(
      'monthly',
    );
    expect((screen.getByTestId('contract-certificate-name') as HTMLInputElement).value).toBe(
      'Interim Certificate',
    );
    expect((screen.getByTestId('contract-release-split') as HTMLSelectElement).value).toBe(
      'sc50_dpe100',
    );
    // No usual cap in the UK: the field is empty, not zero, and carries no mark.
    expect((screen.getByTestId('contract-retention-cap') as HTMLInputElement).value).toBe('');
    expect(screen.queryByTestId('default-hint-retention_cap_percent')).toBeNull();

    const hint = screen.getByTestId('default-hint-retention_percent');
    expect(hint.textContent).toContain('Default for United Kingdom');
    expect(hint.getAttribute('title')).toContain('Three percent applies');
  });

  it('sends nothing the person did not change, so the server records the defaults', async () => {
    serve(GB);
    renderModal();
    await waitFor(() => expect(screen.getByTestId('default-hint-retention_percent')).toBeTruthy());
    typeCode();
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));

    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    const payload = sentPayload();
    for (const field of [
      'retention_percent',
      'retention_cap_percent',
      'retention_release_split',
      'payment_period_days',
      'valuation_interval',
      'certificate_name',
    ]) {
      expect(payload).not.toHaveProperty(field);
    }
  });

  it('sends what the person changed, and the changed field loses its default mark', async () => {
    serve(GB);
    renderModal();
    await waitFor(() => expect(screen.getByTestId('default-hint-retention_percent')).toBeTruthy());

    fireEvent.change(screen.getByTestId('contract-retention'), { target: { value: '5' } });
    fireEvent.change(screen.getByTestId('contract-retention-cap'), { target: { value: '2.5' } });
    fireEvent.change(screen.getByTestId('contract-release-split'), { target: { value: 'dpe100' } });
    fireEvent.change(screen.getByTestId('contract-certificate-name'), { target: { value: '' } });

    expect(screen.queryByTestId('default-hint-retention_percent')).toBeNull();
    // Untouched fields keep theirs.
    expect(screen.getByTestId('default-hint-payment_period_days')).toBeTruthy();

    typeCode();
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    const payload = sentPayload();
    expect(payload.retention_percent).toBe(5);
    expect(payload.retention_cap_percent).toBe(2.5);
    expect(payload.retention_release_split).toEqual([
      { event: 'defects_period_end', release_percent_of_held: '100' },
    ]);
    // Cleared on purpose: sent as "none", so the server does not refill it.
    expect(payload.certificate_name).toBeNull();
    expect(payload).not.toHaveProperty('payment_period_days');
  });
});

describe('a new contract in a country with no usual terms', () => {
  it('starts empty, says why, and asks for the retention instead of assuming 5', async () => {
    serve(NONE);
    renderModal();

    await waitFor(() =>
      expect(screen.getByTestId('country-defaults-status').textContent).toContain(
        'No usual payment terms are on file for Italy',
      ),
    );
    expect((screen.getByTestId('contract-retention') as HTMLInputElement).value).toBe('');
    expect((screen.getByTestId('contract-payment-days') as HTMLInputElement).value).toBe('');
    expect(screen.queryByTestId('default-hint-retention_percent')).toBeNull();

    typeCode();
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(toast.addToast).toHaveBeenCalled());
    expect(api.apiPost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId('contract-retention'), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    expect(sentPayload().retention_percent).toBe(4);
  });

  it('leaves an untouched form to the server when the defaults could not be read', async () => {
    serve(new Error('offline'));
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId('country-defaults-status').textContent).toContain(
        'could not be loaded',
      ),
    );
    typeCode();
    fireEvent.click(screen.getByRole('button', { name: /Create/i }));
    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    expect(sentPayload()).not.toHaveProperty('retention_percent');
  });
});

function contract(overrides: Partial<ContractItem> = {}): ContractItem {
  return {
    id: 'c-1',
    code: 'C-001',
    title: 'Main works',
    contract_type: 'lump_sum',
    counterparty_type: 'client',
    counterparty_id: null,
    project_id: 'p-1',
    parent_contract_id: null,
    start_date: null,
    end_date: null,
    total_value: '100000',
    original_contract_value: null,
    currency: 'EUR',
    retention_percent: '5',
    retention_release_event: 'substantial_completion',
    status: 'draft',
    signed_at: null,
    template_code: null,
    template_version: null,
    terms: {},
    created_by: null,
    metadata: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

describe('the payment terms on a contract', () => {
  it('marks the figures its country filled in and leaves typed ones unmarked', () => {
    render(
      <ContractPaymentTermsSummary
        contract={contract({
          terms: {
            payment_terms: {
              retention_cap_percent: '5',
              payment_period_days: 21,
              valuation_interval: 'monthly',
              certificate_name: 'Abschlagsrechnung',
            },
          },
          metadata: {
            country_defaults: {
              country_code: 'DE',
              has_country_defaults: true,
              applied: {
                retention_percent: '5',
                retention_cap_percent: '5',
                payment_period_days: 21,
                retention_release_split: [
                  { event: 'substantial_completion', release_percent_of_held: '100' },
                  { event: 'defects_period_end', release_percent_of_held: '100' },
                ],
              },
              sources: { payment_period_days: { source: 'statute', reference: '§ 16 VOB/B', note: '' } },
              release_split_source: 'regional_pack',
            },
          },
        })}
      />,
    );
    const block = screen.getByTestId('contract-payment-terms');
    expect(block.textContent).toContain('Abschlagsrechnung');
    expect(screen.getByTestId('default-hint-payment_period_days').textContent).toContain(
      'Default for Germany',
    );
    // The pack's split is shown, named the way a reader knows it.
    expect(block.textContent).toContain('At completion against a defects security');
    // Typed by the author, so no mark.
    expect(screen.queryByTestId('default-hint-certificate_name')).toBeNull();
    expect(screen.queryByTestId('retention-fallback-warning')).toBeNull();
  });

  it("says when the retention rate is the platform's fallback", () => {
    render(
      <ContractPaymentTermsSummary
        contract={contract({
          metadata: {
            country_defaults: {
              country_code: null,
              has_country_defaults: false,
              applied: {},
              sources: {},
              release_split_source: null,
              fallback: ['retention_percent', 'retention_release_event'],
            },
          },
        })}
      />,
    );
    expect(screen.getByTestId('retention-fallback-warning')).toBeTruthy();
    expect(screen.getByTestId('contract-payment-terms').textContent).toContain('No cap');
  });
});
