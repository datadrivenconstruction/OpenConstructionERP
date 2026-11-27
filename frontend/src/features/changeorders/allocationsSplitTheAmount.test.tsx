// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A change order of 900.00 linked to two orders raises neither until it is
 * split. The split saves only when the shares add up to 900.00, and it saves
 * the share of each order.
 *
 * Run:  npx vitest run src/features/changeorders/allocationsSplitTheAmount.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { ChangeOrderAllocations } from './ChangeOrderAllocations';

const api = vi.hoisted(() => ({ apiPatch: vi.fn() }));

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string; n?: number }) =>
      (opts?.defaultValue ?? _key).replace('{{n}}', String(opts?.n ?? '')),
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/shared/lib/api', () => ({ apiPatch: api.apiPatch }));

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

beforeEach(() => api.apiPatch.mockReset());

describe('ChangeOrderAllocations', () => {
  it('warns while unallocated and saves only a split that adds up', async () => {
    api.apiPatch.mockResolvedValue({});
    wrap(
      <ChangeOrderAllocations orderId="co-1" poIds={['a', 'b']} allocations={[]} amount="900.00" currency="USD" canEdit />,
    );
    expect(screen.getByTestId('co-allocations-missing')).toBeInTheDocument();
    const save = screen.getByTestId('co-allocations-save');
    fireEvent.change(screen.getByTestId('co-allocation-a'), { target: { value: '600' } });
    fireEvent.change(screen.getByTestId('co-allocation-b'), { target: { value: '200' } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId('co-allocation-b'), { target: { value: '300' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(api.apiPatch).toHaveBeenCalledWith('/v1/changeorders/co-1', {
        commitment_allocations: [
          { kind: 'purchase_order', id: 'a', amount: '600' },
          { kind: 'purchase_order', id: 'b', amount: '300' },
        ],
      }),
    );
  });

  it('is absent for a change order linked to one order', () => {
    const { container } = wrap(
      <ChangeOrderAllocations orderId="co-1" poIds={['a']} allocations={[]} amount="900.00" currency="USD" canEdit />,
    );
    expect(container.querySelector('[data-testid="co-allocations"]')).toBeNull();
  });
});
