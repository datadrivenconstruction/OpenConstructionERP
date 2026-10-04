// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Smoke test of the whole page: it mounts from a BOQ deep link, loads the
// stored choices, sends them to the server when the person asks for the
// calculation, renders the result, and turns a missing index into a message
// that names the group instead of a generic error. It also pins the state
// rules: saving the choices keeps the breakdown on screen, an edited index
// marks the breakdown stale, a refused edit goes back to the stored value, and
// a person without price_index.manage is offered no edit controls.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

vi.mock('@/shared/ui/BOQPicker', () => ({
  BOQPicker: () => <div data-testid="boq-picker" />,
}));

vi.mock('./resourceIndexApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./resourceIndexApi')>();
  return {
    ...actual,
    listResourceIndices: vi.fn(),
    listOverheadNorms: vi.fn(),
    getBoqSettings: vi.fn(),
    computeBoq: vi.fn(),
    computeExplicit: vi.fn(),
    saveBoqSettings: vi.fn(),
    updateResourceIndex: vi.fn(),
  };
});

import * as api from './resourceIndexApi';
import { ResourceIndexPage } from './ResourceIndexPage';

const mocked = vi.mocked(api);

const STORED: api.BOQResourceIndexSettings = {
  region_code: 'RU-MOW',
  quarter: '2026-Q1',
  default_work_type: 'concrete',
  work_types: { pos1: 'concrete' },
  resources_at_base_prices: false,
};

async function calculate() {
  const button = await screen.findByRole('button', { name: /Calculate estimate/ });
  await waitFor(() => expect(mocked.getBoqSettings).toHaveBeenCalledWith('b1'));
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(button);
  expect(await screen.findByText('Estimate totals')).toBeTruthy();
}

function indexRow(group: api.ResourceGroup, value: string): api.ResourceIndexValue {
  return {
    id: `i-${group}`,
    region_code: 'RU-MOW',
    quarter: '2026-Q1',
    resource_group: group,
    index_value: value,
    source: 'SAMPLE',
    is_sample: true,
    created_at: '',
    updated_at: '',
  };
}

function result(): api.ResourceIndexEstimate {
  const zero = '0.00';
  return {
    region_code: 'RU-MOW',
    quarter: '2026-Q1',
    on_date: '2026-02-15',
    currency: 'RUB',
    vat_rate_pct: '22.0',
    vat_tax_name: 'VAT',
    indices_used: [{ resource_group: 'labor', index_value: '1.6', source: 'SAMPLE', is_sample: true }],
    norms_used: [],
    uses_sample_data: true,
    positions: [],
    by_work_type: [],
    totals: {
      base_ot: zero, base_em: zero, base_otm: zero, base_m: zero, base_direct: zero,
      ot: zero, em: zero, otm: zero, m: zero, direct: zero, fot: zero, nr: zero, sp: zero,
      total: '1000.00', vat_rate_pct: '22.0', vat: '220.00', total_with_vat: '1220.00',
    },
    excluded: [],
    priced_count: 0,
    excluded_count: 0,
    is_complete: true,
    boq_id: 'b1',
    boq_name: 'Smeta',
    project_id: 'p1',
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/price-index/resource-index?boq=b1&project=p1']}>
        <ResourceIndexPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ResourceIndexPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.listResourceIndices.mockResolvedValue([
      indexRow('labor', '1.600000'),
      indexRow('machine', '1.300000'),
      indexRow('operator_wages', '1.600000'),
      indexRow('material', '1.200000'),
    ]);
    mocked.listOverheadNorms.mockResolvedValue([
      {
        id: 'n1', work_type_code: 'concrete', label: 'Concrete', nr_pct: '110', sp_pct: '65',
        source: '', is_sample: true, created_at: '', updated_at: '',
      },
    ]);
    mocked.getBoqSettings.mockResolvedValue({ ...STORED, work_types: { ...STORED.work_types } });
    useAuthStore.setState({ userRole: 'editor' });
  });

  afterEach(() => {
    useAuthStore.setState({ userRole: null });
  });

  it('mounts from a BOQ link and sends the stored choices to the calculation', async () => {
    mocked.computeBoq.mockResolvedValue(result());
    renderPage();
    const button = await screen.findByRole('button', { name: /Calculate estimate/ });
    await waitFor(() => expect(mocked.getBoqSettings).toHaveBeenCalledWith('b1'));
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(mocked.computeBoq).toHaveBeenCalled());
    const [boqId, sent] = mocked.computeBoq.mock.calls[0]!;
    expect(boqId).toBe('b1');
    expect(sent.region_code).toBe('RU-MOW');
    expect(sent.quarter).toBe('2026-Q1');
    expect(sent.default_work_type).toBe('concrete');
    expect(sent.work_types).toEqual({ pos1: 'concrete' });
    expect(sent.resources_at_base_prices).toBe(false);
    expect(sent.on_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(await screen.findByText('Estimate totals')).toBeTruthy();
    expect(screen.getByText(/sample indices or norms shipped for demonstration/)).toBeTruthy();
  });

  it('explains a missing index by group, not with a generic error', async () => {
    mocked.computeBoq.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: {
          code: 'missing_index',
          message: 'no index',
          groups: ['material'],
          region_code: 'RU-MOW',
          quarter: '2026-Q1',
        },
      }),
    );
    renderPage();
    const button = await screen.findByRole('button', { name: /Calculate estimate/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Materials (M)');
    expect(alert.textContent).toContain('never taken as 1');
    expect(screen.queryByText('Estimate totals')).toBeNull();
  });

  it('sends the base-price statement only when the person ticks it', async () => {
    mocked.computeBoq.mockResolvedValue(result());
    renderPage();
    const box = await screen.findByRole('checkbox', { name: /base prices of the 2022 federal base/ });
    await waitFor(() => expect(mocked.getBoqSettings).toHaveBeenCalledWith('b1'));
    expect((box as HTMLInputElement).checked).toBe(false);
    fireEvent.click(box);
    await calculate();
    expect(mocked.computeBoq.mock.calls[0]![1].resources_at_base_prices).toBe(true);
  });

  it('keeps the breakdown on screen when the choices are saved', async () => {
    mocked.computeBoq.mockResolvedValue(result());
    mocked.saveBoqSettings.mockImplementation(async (_boqId, sent) => ({ ...sent }));
    renderPage();
    await calculate();
    // Any change makes the choices dirty, which enables Save.
    fireEvent.click(screen.getByRole('checkbox', { name: /base prices of the 2022 federal base/ }));
    const save = screen.getByRole('button', { name: /Save choices/ });
    await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(mocked.saveBoqSettings).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Choices not saved yet')).toBeNull());
    expect(screen.getByText('Estimate totals')).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: /base prices/ }) as HTMLInputElement).checked).toBe(true);
  });

  it('marks the breakdown stale once an index it used is changed', async () => {
    mocked.computeBoq.mockResolvedValue(result());
    mocked.updateResourceIndex.mockResolvedValue(indexRow('labor', '1.700000'));
    renderPage();
    await calculate();
    expect(screen.queryByText(/changed after this calculation/)).toBeNull();
    const inputs = await screen.findAllByRole('textbox', { name: 'Index' });
    const labour = inputs[0]!;
    fireEvent.change(labour, { target: { value: '1.7' } });
    fireEvent.blur(labour);
    await waitFor(() => expect(mocked.updateResourceIndex).toHaveBeenCalledWith('i-labor', { index_value: '1.7' }));
    expect(await screen.findByText(/changed after this calculation/)).toBeTruthy();
    // The old figures stay readable, and one click prices again.
    expect(screen.getByText('Estimate totals')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Recalculate/ }));
    await waitFor(() => expect(mocked.computeBoq).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText(/changed after this calculation/)).toBeNull());
  });

  it('puts a refused index edit back to the stored value', async () => {
    mocked.updateResourceIndex.mockRejectedValue(new ApiError(403, 'Forbidden', { detail: 'forbidden' }));
    renderPage();
    const inputs = await screen.findAllByRole('textbox', { name: 'Index' });
    const labour = inputs[0]! as HTMLInputElement;
    expect(labour.value).toBe('1.6');
    fireEvent.change(labour, { target: { value: '9.9' } });
    fireEvent.blur(labour);
    await waitFor(() => expect(mocked.updateResourceIndex).toHaveBeenCalled());
    await waitFor(() => expect(labour.value).toBe('1.6'));
  });

  it('offers no edit controls to a person without price_index.manage', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    expect(await screen.findByText('Resource indices')).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText('1.6').length).toBeGreaterThan(0));
    expect(screen.queryAllByRole('textbox', { name: 'Index' })).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /Add index/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Add work type/ })).toBeNull();
    expect(screen.queryAllByRole('button', { name: 'Delete' })).toHaveLength(0);
  });
});
