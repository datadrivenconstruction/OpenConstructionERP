// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The payment terms a contract started from can be corrected while it is a draft.
//
// The card used to be read-only, so a GB contract created on the JCT defaults
// kept them: nothing in the app changed the cap, the split, the period, the
// interval or the certificate name afterwards. The edit sends only what
// changed, because the server reads an unsent field as untouched and keeps
// its "Default for" mark, and it is offered only on a draft, because the
// server locks the terms once the contract leaves draft.
//
// The API layer runs for real (the mock is on apiPatch), so a wrong URL fails.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

import { ContractPaymentTermsCard } from './ContractPaymentTermsEditor';
import type { ContractItem } from './api';

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
    currency: 'GBP',
    retention_percent: '3.00',
    retention_release_event: 'substantial_completion',
    status: 'draft',
    signed_at: null,
    template_code: null,
    template_version: null,
    terms: {
      payment_terms: {
        retention_release_split: [
          { event: 'substantial_completion', release_percent_of_held: '50' },
          { event: 'defects_period_end', release_percent_of_held: '100' },
        ],
        payment_period_days: 14,
        valuation_interval: 'monthly',
        certificate_name: 'Interim Certificate',
      },
    },
    created_by: null,
    metadata: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

function renderCard(c: ContractItem) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractPaymentTermsCard contract={c} />
    </QueryClientProvider>,
  );
}

function sentPatch(): Record<string, unknown> {
  expect(api.apiPatch).toHaveBeenCalledTimes(1);
  const call = api.apiPatch.mock.calls[0]!;
  expect(call[0]).toBe('/v1/contracts/contracts/c-1');
  return call[1] as Record<string, unknown>;
}

function saveButton(): HTMLButtonElement {
  return screen.getByTestId('payment-terms-save') as HTMLButtonElement;
}

beforeEach(() => {
  api.apiPatch.mockResolvedValue(contract());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('editing the payment terms of a contract', () => {
  it('is offered on a draft and not once the contract is signed', () => {
    renderCard(contract({ status: 'active' }));
    expect(screen.queryByTestId('payment-terms-edit')).toBeNull();
    expect(screen.getByTestId('contract-payment-terms')).toBeTruthy();
    cleanup();

    renderCard(contract());
    expect(screen.getByTestId('payment-terms-edit')).toBeTruthy();
  });

  it('sends only the figures that changed, a cleared one as null', async () => {
    renderCard(contract());
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    // Nothing changed yet, so there is nothing to save.
    expect(saveButton().disabled).toBe(true);

    fireEvent.change(screen.getByTestId('edit-retention-percent'), { target: { value: '5' } });
    fireEvent.change(screen.getByTestId('edit-retention-cap'), { target: { value: '5' } });
    fireEvent.change(screen.getByTestId('edit-certificate-name'), { target: { value: '' } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(api.apiPatch).toHaveBeenCalled());
    expect(sentPatch()).toEqual({
      retention_percent: 5,
      retention_cap_percent: 5,
      certificate_name: null,
    });
    await waitFor(() => expect(screen.queryByTestId('contract-payment-terms-editor')).toBeNull());
  });

  it('reads 3 over 3.00 as unchanged', () => {
    renderCard(contract());
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    fireEvent.change(screen.getByTestId('edit-retention-percent'), { target: { value: '3' } });
    expect(saveButton().disabled).toBe(true);
  });

  it('sends the release pattern picked, and a pattern no preset describes is kept untouched', async () => {
    const odd = [
      { event: 'substantial_completion' as const, release_percent_of_held: '40' },
      { event: 'final_completion' as const, release_percent_of_held: '100' },
    ];
    renderCard(contract({ terms: { payment_terms: { retention_release_split: odd } } }));
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    const select = screen.getByTestId('edit-release-split') as HTMLSelectElement;
    expect(select.value).toBe('__current__');

    fireEvent.change(screen.getByTestId('edit-payment-days'), { target: { value: '30' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.apiPatch).toHaveBeenCalled());
    expect(sentPatch()).toEqual({ payment_period_days: 30 });
  });

  it('sends a preset split as its steps', async () => {
    renderCard(contract());
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    fireEvent.change(screen.getByTestId('edit-release-split'), { target: { value: 'fc100' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.apiPatch).toHaveBeenCalled());
    expect(sentPatch()).toEqual({
      retention_release_split: [{ event: 'final_completion', release_percent_of_held: '100' }],
    });
  });

  it("names the regional pack's split where the contract states none of its own", () => {
    renderCard(
      contract({
        terms: { payment_terms: { payment_period_days: 21 } },
        metadata: {
          country_defaults: {
            country_code: 'DE',
            has_country_defaults: true,
            applied: {
              retention_release_split: [
                { event: 'substantial_completion', release_percent_of_held: '100' },
                { event: 'defects_period_end', release_percent_of_held: '100' },
              ],
            },
            sources: {},
            release_split_source: 'regional_pack',
          },
        },
      }),
    );
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    const select = screen.getByTestId('edit-release-split') as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(select.selectedOptions[0]?.textContent).toContain('As the regional pack sets it');
    expect(select.selectedOptions[0]?.textContent).not.toContain('Not stated');
  });

  it('refuses a payment period that is not a whole number of days', () => {
    renderCard(contract());
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    fireEvent.change(screen.getByTestId('edit-payment-days'), { target: { value: '14.5' } });
    expect(screen.getByTestId('payment-terms-invalid')).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    fireEvent.click(saveButton());
    expect(api.apiPatch).not.toHaveBeenCalled();
  });

  it('says why the server refused and stays open', async () => {
    api.apiPatch.mockRejectedValueOnce(new Error('Financial terms cannot be edited'));
    renderCard(contract());
    fireEvent.click(screen.getByTestId('payment-terms-edit'));
    fireEvent.change(screen.getByTestId('edit-payment-days'), { target: { value: '21' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(toast.addToast).toHaveBeenCalled());
    expect(toast.addToast.mock.calls[0]![0]).toMatchObject({ type: 'error' });
    expect(screen.getByTestId('contract-payment-terms-editor')).toBeTruthy();
  });
});
