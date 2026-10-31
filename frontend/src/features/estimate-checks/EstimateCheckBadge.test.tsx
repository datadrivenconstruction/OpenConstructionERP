// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { CheckResponse, KpiResult } from './api';

const api = vi.hoisted(() => ({
  check: vi.fn(),
  preference: vi.fn(),
  accept: vi.fn(),
  withdraw: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  savePreference: vi.fn(),
}));
vi.mock('./api', () => ({ estimateChecksApi: api }));

const moduleState = vi.hoisted(() => ({ enabled: true }));
vi.mock('@/stores/useModuleStore', () => ({
  useModuleStore: (sel: (s: { isModuleEnabled: (k: string) => boolean }) => unknown) =>
    sel({ isModuleEnabled: () => moduleState.enabled }),
}));

import { EstimateCheckBadge } from './EstimateCheckBadge';
import { formatValue, worstTone } from './labels';

function kpi(over: Partial<KpiResult>): KpiResult {
  return {
    kpi_id: 'labour_share',
    group: 'labour',
    unit: 'pct',
    unit_label: null,
    value: 62,
    low: 25,
    high: 40,
    compared: 12,
    status: 'warning',
    confidence: 0.8,
    reason: 'outside_history',
    positions: [{ id: 'p1', ordinal: '01.001', description: 'Concrete wall' }],
    position_count: 1,
    accepted: null,
    ...over,
  };
}

const response: CheckResponse = {
  boq_id: 'b1',
  revision: 'r',
  currency: 'EUR',
  comparables_scope: 'currency',
  comparables_pool: 12,
  counts: { normal: 1, suspect: 1, warning: 1, accepted: 0 },
  kpis: [
    kpi({}),
    kpi({ kpi_id: 'overhead_pct', group: 'markup', value: 10, low: 8, high: 12, status: 'normal', reason: 'within_history' }),
    kpi({ kpi_id: 'zero_rate', group: 'data_quality', unit: 'count', value: 2, status: 'suspect', reason: 'count_found', position_count: 2 }),
  ],
};

function renderBadge(onJump = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <EstimateCheckBadge boqId="b1" onJumpToPosition={onJump} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('EstimateCheckBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    moduleState.enabled = true;
    api.check.mockResolvedValue(response);
    api.preference.mockResolvedValue({ display_mode: 'badge' });
  });

  it('shows warning and suspect counts and opens nothing by itself', async () => {
    renderBadge();
    expect(await screen.findByTestId('estimate-check-badge-warning')).toHaveTextContent('1');
    expect(screen.getByTestId('estimate-check-badge-suspect')).toHaveTextContent('1');
    expect(screen.queryByTestId('estimate-check-panel')).toBeNull();
  });

  it('leaves no trace when the module is disabled', async () => {
    moduleState.enabled = false;
    const { container } = renderBadge();
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
    expect(api.check).not.toHaveBeenCalled();
  });

  it('renders nothing when the user chose off, and does not compute the check', async () => {
    api.preference.mockResolvedValue({ display_mode: 'off' });
    const { container } = renderBadge();
    await waitFor(() => expect(api.preference).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
    expect(api.check).not.toHaveBeenCalled();
  });

  it('renders nothing when the backend module is missing', async () => {
    api.check.mockRejectedValue(new Error('404'));
    const { container } = renderBadge();
    await waitFor(() => expect(api.check).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it('panel lists only flagged items by default and jumps to a position', async () => {
    const onJump = vi.fn();
    renderBadge(onJump);
    fireEvent.click(await screen.findByTestId('estimate-check-badge'));
    expect(await screen.findByTestId('estimate-check-kpi-labour_share')).toBeInTheDocument();
    expect(screen.queryByTestId('estimate-check-kpi-overhead_pct')).toBeNull();
    fireEvent.click(screen.getByText(/Show 1 position/));
    fireEvent.click(screen.getByText('Concrete wall'));
    expect(onJump).toHaveBeenCalledWith('p1');
  });

  it('accepting needs a reason', async () => {
    api.accept.mockResolvedValue(response);
    renderBadge();
    fireEvent.click(await screen.findByTestId('estimate-check-badge'));
    const row = await screen.findByTestId('estimate-check-kpi-labour_share');
    fireEvent.click(row.querySelector('button[title]') as HTMLElement);
    const save = await screen.findByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/Why is this figure/), { target: { value: 'Night shifts' } });
    fireEvent.click(save);
    await waitFor(() => expect(api.accept).toHaveBeenCalledWith('b1', 'labour_share', 'Night shifts'));
  });
});

describe('labels', () => {
  it('formats values by unit', () => {
    expect(formatValue(12.345, 'pct', 'en', 'EUR')).toBe('12.3 %');
    expect(formatValue(3, 'count', 'en', 'EUR')).toBe('3');
    expect(formatValue(46.1, 'money', 'en', 'EUR', 'm3')).toBe('46.10 EUR / m3');
    expect(formatValue(null, 'pct', 'en', 'EUR')).toBe('-');
  });

  it('worst tone wins per group', () => {
    expect(worstTone([kpi({ status: 'normal' }), kpi({ status: 'suspect' })])).toBe('suspect');
    expect(worstTone([kpi({ status: 'warning', accepted: { reason: 'x', accepted_by: 'u', accepted_at: null, status_at_accept: 'warning', value_at_accept: null } })])).toBe('accepted');
  });
});
