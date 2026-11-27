// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The composition panel shows stored vs derived rate with the per-row issues and
// the missing exchange rates; a match is proposed with its confidence and only
// replaces a resource after a second, confirming click. Refusals are worded
// from the HTTP status.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./positionCostItemApi', async (orig) => ({
  ...(await orig<typeof import('./positionCostItemApi')>()),
  positionCostItemApi: {
    composition: vi.fn(),
    match: vi.fn(),
    replace: vi.fn(),
    save: vi.fn(),
    refresh: vi.fn(),
  },
}));

import { ApiError } from '@/shared/lib/api';
import { positionCostItemApi, confidencePercent, refusalText } from './positionCostItemApi';
import { PositionCompositionDialog } from './PositionCompositionDialog';

const api = vi.mocked(positionCostItemApi);

const COMPOSITION = {
  stored_unit_rate: '100',
  derived_unit_rate: '80',
  delta: '20',
  coherent: false,
  fx_missing: ['CHF'],
  components: [{ index: 0, name: 'Mason', quantity: '2', unit_rate: '40', issues: ['unpriced'] }],
};

function renderDialog(onChanged = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PositionCompositionDialog positionId="p1" onClose={vi.fn()} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return onChanged;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.composition.mockResolvedValue(COMPOSITION);
  api.match.mockResolvedValue([
    { cost_item_id: 'c1', code: 'R1', description: 'Mason skilled', unit: 'h', unit_rate: 50, currency: 'EUR', score: 0.824 },
  ]);
  api.replace.mockResolvedValue({});
});

describe('PositionCompositionDialog', () => {
  it('shows stored vs derived rate, the delta, the row issue and the missing exchange rate', async () => {
    renderDialog();
    expect(await screen.findByTestId('composition-summary')).toHaveTextContent('100');
    expect(screen.getByTestId('composition-summary')).toHaveTextContent('80');
    expect(screen.getByTestId('composition-summary')).toHaveTextContent('20');
    expect(screen.getByTestId('composition-fx')).toHaveTextContent('CHF');
    expect(screen.getByText('unpriced')).toBeTruthy();
  });

  it('proposes a match with its confidence and replaces only after confirmation', async () => {
    const onChanged = renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /Find match/i }));
    expect(await screen.findByTestId('match-confidence')).toHaveTextContent('82');
    fireEvent.click(screen.getByRole('button', { name: /^Replace$/ }));
    expect(api.replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Confirm replace/i }));
    await waitFor(() => expect(api.replace).toHaveBeenCalledWith('p1', 0, 'c1', 0.824));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
});

describe('refusalText', () => {
  it('words a repeat save, a section and a stale replace from the status', () => {
    expect(refusalText(new ApiError(409, 'Conflict', {}), 'save').key).toBe('boq.position_cost.err_exists');
    expect(refusalText(new ApiError(422, 'Unprocessable', {}), 'refresh').key).toBe('boq.position_cost.err_not_savable');
    expect(refusalText(new ApiError(422, 'Unprocessable', {}), 'replace').key).toBe('boq.position_cost.err_candidate');
    expect(refusalText(new ApiError(409, 'Conflict', {}), 'replace').key).toBe('boq.position_cost.err_locked');
    expect(refusalText(new Error('x'), 'save').key).toBe('boq.position_cost.err_generic');
  });

  it('rounds the confidence to a whole percent inside 0..100', () => {
    expect(confidencePercent(0.824)).toBe(82);
    expect(confidencePercent(1.4)).toBe(100);
    expect(confidencePercent(-1)).toBe(0);
  });
});
