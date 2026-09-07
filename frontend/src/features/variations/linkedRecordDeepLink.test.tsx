// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Variation Order drawer renders its "linked records" pills only when the
// order carries the id of the linked record. It then threw that id away and
// navigated to the bare module list, so the user landed on a register and had
// to find by hand the record the app had just identified for them. The pill
// looked healthy from every angle a test usually checks: the condition was
// right, the button rendered, the route existed.
//
// So the assertion here is about the id, not about the click working: the
// change order pill must navigate to that change order. `?highlight=<id>` is
// the house convention for list screens and ChangeOrdersPage now reads it.
//
// The contract pill was pinned to the bare register here for as long as the
// contract page could not select a contract from the URL. It reads
// `?highlight=` now (Issue #435, the navigation pass), so the pill carries the
// contract id the same way, and the assertion moved with it.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import { DetailDrawer, changeOrderDeepLink } from './VariationsPage';
import type { VariationOrder } from './api';

const ORDER: VariationOrder = {
  id: 'vo-1',
  project_id: 'p-1',
  variation_request_id: null,
  code: 'VO-001',
  title: 'Extra piling to grid F',
  final_cost_impact: '12500.00',
  final_schedule_days: 4,
  currency: 'EUR',
  agreed_at: null,
  signed_by: null,
  status: 'issued',
  reference_change_order_id: 'co-42',
  affected_contract_id: 'ct-7',
  implementation_started_at: null,
  implementation_completed_at: null,
  metadata: {},
  created_at: '2026-03-01T09:00:00Z',
  updated_at: '2026-03-01T09:00:00Z',
};

function renderDrawer(order: VariationOrder) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DetailDrawer
        selected={{ kind: 'orders', id: order.id }}
        projectId="p-1"
        notices={[]}
        requests={[]}
        orders={[order]}
        daywork={[]}
        eot={[]}
        currency="EUR"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateSpy.mockClear();
});

describe('variation order linked-record deep links', () => {
  it('carries the change order id into the destination', () => {
    renderDrawer(ORDER);

    fireEvent.click(screen.getByText('Change order'));

    expect(navigateSpy).toHaveBeenCalledWith('/changeorders?highlight=co-42');
  });

  it('does not land the user on the bare change order register', () => {
    renderDrawer(ORDER);

    fireEvent.click(screen.getByText('Change order'));

    // The defect this file exists for: the id was used to decide whether to
    // render the pill and then discarded on the way out.
    expect(navigateSpy).not.toHaveBeenCalledWith('/changeorders');
  });

  it('escapes an id that would otherwise break out of the query string', () => {
    expect(changeOrderDeepLink('a b&highlight=evil')).toBe(
      '/changeorders?highlight=a%20b%26highlight%3Devil',
    );
  });

  it('renders no pills when the order links to nothing', () => {
    renderDrawer({ ...ORDER, reference_change_order_id: null, affected_contract_id: null });

    expect(screen.queryByText('Change order')).toBeNull();
    expect(screen.queryByText('Contract')).toBeNull();
  });

  it('carries the contract id into the contract register', () => {
    renderDrawer(ORDER);

    fireEvent.click(screen.getByText('Contract'));

    expect(navigateSpy).toHaveBeenCalledWith('/contracts?highlight=ct-7');
    expect(navigateSpy).not.toHaveBeenCalledWith('/contracts');
  });
});
