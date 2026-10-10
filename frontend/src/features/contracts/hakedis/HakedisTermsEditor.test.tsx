// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the payment certificate settings of a contract.
//
// What is worth pinning:
//
//   * the card shows only for a country with a certificate layout, or for a
//     contract that already carries an entry;
//   * it is editable on a draft only;
//   * saving goes through the contract update with the whole `terms`, keeps
//     every key this screen does not edit, and sends figures as strings;
//   * an emptied form removes the entry instead of storing an empty one;
//   * the server's refusal is shown with its own sentence.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', () => ({
  updateContract: vi.fn(),
}));

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, listStatutoryCategories: vi.fn() };
});

vi.mock('@/features/projects/api', () => ({
  projectsApi: { get: vi.fn() },
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import * as contractsApi from '../api';
import type { ContractItem } from '../api';
import * as api from './api';
import { projectsApi } from '@/features/projects/api';
import { HakedisTermsCard, hakedisTermsFrom } from './HakedisTermsEditor';
import { ApiError } from '@/shared/lib/api';

const updateMock = vi.mocked(contractsApi.updateContract);
const categoriesMock = vi.mocked(api.listStatutoryCategories);
const projectMock = vi.mocked(projectsApi.get);

function contract(over: Partial<ContractItem> = {}): ContractItem {
  return {
    id: 'contract-1',
    code: 'C-7',
    title: 'Main works',
    project_id: 'project-1',
    status: 'draft',
    terms: {},
    ...over,
  } as ContractItem;
}

function renderCard(item: ContractItem) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HakedisTermsCard contract={item} />
    </QueryClientProvider>,
  );
}

function project(country: string) {
  projectMock.mockResolvedValue({ id: 'project-1', country_code: country } as Awaited<
    ReturnType<typeof projectsApi.get>
  >);
}

beforeEach(() => {
  vi.clearAllMocks();
  project('TR');
  categoriesMock.mockResolvedValue({
    items: [
      {
        country_code: 'TR',
        kind: 'vat_withholding',
        code: '601',
        labels: { en: 'Construction works', tr: 'Yapım işleri' },
        base: 'vat',
        rate_pct: null,
        numerator: 4,
        denominator: 10,
        threshold_amount: null,
        threshold_currency: '',
        threshold_scope: '',
        threshold_measure: '',
        cap_amount: null,
        buyer_scope: 'designated_only',
        work_value_threshold: null,
        conditions: {},
        effective_from: '2024-01-01',
        effective_to: null,
        legal_reference: '',
        source_url: '',
        read_date: '2026-01-01',
        review_status: 'confirmed',
      },
    ],
    total: 1,
    offset: 0,
    limit: 500,
  });
});

describe('HakedisTermsCard', () => {
  it('renders nothing for a contract in a country without a certificate layout', async () => {
    project('DE');
    const { container } = renderCard(contract());
    await waitFor(() => expect(projectMock).toHaveBeenCalledWith('project-1'));
    await waitFor(() => expect(projectMock.mock.results[0]?.type).toBe('return'));
    expect(container).toBeEmptyDOMElement();
  });

  it('shows for a contract that carries an entry, whatever the country', async () => {
    project('DE');
    renderCard(contract({ terms: { hakedis: { preset: 'TR_PRIVATE' } } }));
    expect(await screen.findByTestId('hakedis-terms')).toBeInTheDocument();
    expect(screen.getByTestId('hakedis-terms-value-preset')).toHaveTextContent('Private sector form');
    expect(screen.getByTestId('hakedis-terms-value-retention')).toHaveTextContent('Country standard');
  });

  it('is read-only once the contract has left draft', async () => {
    renderCard(contract({ status: 'active' as ContractItem['status'] }));
    expect(await screen.findByTestId('hakedis-terms')).toHaveTextContent(
      'These settings lock with the other financial terms',
    );
    expect(screen.queryByTestId('hakedis-terms-edit')).toBeNull();
  });

  it('saves through the contract update, keeping the keys it does not edit', async () => {
    const item = contract({
      terms: {
        payment_terms: { payment_period_days: 30 },
        hakedis: { letters: { retention: 'k' }, retention: { base: ['this_certificate'] } },
      },
    });
    updateMock.mockResolvedValue(item);
    renderCard(item);
    fireEvent.click(await screen.findByTestId('hakedis-terms-edit'));
    fireEvent.change(screen.getByTestId('hakedis-terms-preset'), { target: { value: 'TR_PRIVATE' } });
    fireEvent.change(screen.getByTestId('hakedis-terms-retention-source'), { target: { value: 'fixed' } });
    fireEvent.change(screen.getByTestId('hakedis-terms-retention-pct'), { target: { value: '7,5' } });
    fireEvent.change(screen.getByTestId('hakedis-terms-advance-pct'), { target: { value: '10' } });
    await screen.findByText('601 Construction works');
    fireEvent.change(screen.getByTestId('hakedis-terms-tax-vat_withholding'), { target: { value: 'code:601' } });
    fireEvent.change(screen.getByTestId('hakedis-terms-tax-stamp_duty'), { target: { value: 'not_applicable' } });
    // A tax ruled out needs its reason before the form can be saved.
    expect(screen.getByTestId('hakedis-terms-save')).toBeDisabled();
    fireEvent.change(screen.getByTestId('hakedis-terms-tax-reason-stamp_duty'), {
      target: { value: 'Paid by the employer' },
    });
    fireEvent.change(screen.getByTestId('hakedis-terms-role-select'), { target: { value: 'site_manager' } });
    fireEvent.click(screen.getByTestId('hakedis-terms-role-add'));
    fireEvent.click(screen.getByTestId('hakedis-terms-save'));
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock).toHaveBeenCalledWith('contract-1', {
      terms: {
        payment_terms: { payment_period_days: 30 },
        hakedis: {
          letters: { retention: 'k' },
          preset: 'TR_PRIVATE',
          retention: { base: ['this_certificate'], source: 'fixed', pct: '7.5' },
          advance_recovery_pct: '10',
          taxes: {
            vat_withholding: { state: 'selected', code: '601', reason: '' },
            stamp_duty: { state: 'not_applicable', code: '', reason: 'Paid by the employer' },
          },
          signature_roles: ['site_manager'],
        },
      },
    });
    await waitFor(() => expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' })));
  });

  it('removes the entry when the form is emptied', async () => {
    const item = contract({ terms: { payment_terms: {}, hakedis: { preset: 'TR' } } });
    updateMock.mockResolvedValue(item);
    renderCard(item);
    fireEvent.click(await screen.findByTestId('hakedis-terms-edit'));
    fireEvent.change(screen.getByTestId('hakedis-terms-preset'), { target: { value: '' } });
    fireEvent.click(screen.getByTestId('hakedis-terms-save'));
    await waitFor(() => expect(updateMock).toHaveBeenCalledWith('contract-1', { terms: { payment_terms: {} } }));
  });

  it("shows the server's sentence when it refuses the settings", async () => {
    updateMock.mockRejectedValue(
      new ApiError(400, 'Bad Request', {
        detail: {
          error: 'invalid_contract_terms',
          message: "hakedis 'advance_recovery_pct' must be between 0 and 100, got '140'",
          field: 'terms.hakedis',
        },
      }),
    );
    renderCard(contract());
    fireEvent.click(await screen.findByTestId('hakedis-terms-edit'));
    fireEvent.change(screen.getByTestId('hakedis-terms-advance-pct'), { target: { value: '140' } });
    fireEvent.click(screen.getByTestId('hakedis-terms-save'));
    expect(await screen.findByTestId('hakedis-terms-refusal')).toHaveTextContent(
      "hakedis 'advance_recovery_pct' must be between 0 and 100, got '140'",
    );
    // The form stays open with what was typed.
    expect(screen.getByTestId('hakedis-terms-advance-pct')).toHaveValue('140');
  });

  it('builds the entry from the form without a float in sight', () => {
    const entry = hakedisTermsFrom(
      {
        preset: '',
        retentionSource: 'none',
        retentionPct: '5',
        advanceRecoveryPct: '',
        advanceAmount: '1.250.000,10',
        taxes: {
          vat_withholding: { state: 'unset', code: '', reason: '' },
          income_withholding: { state: 'unset', code: '', reason: '' },
          stamp_duty: { state: 'unset', code: '', reason: '' },
        },
        roles: null,
      },
      { preset: 'TR', advance_recovery_pct: '10', columns: { unit_price: ['seq'] } },
    );
    // A rate is kept only for the fixed source; cleared fields drop their keys.
    expect(entry).toEqual({
      retention: { source: 'none' },
      advance_amount: '1250000.10',
      columns: { unit_price: ['seq'] },
    });
  });
});
