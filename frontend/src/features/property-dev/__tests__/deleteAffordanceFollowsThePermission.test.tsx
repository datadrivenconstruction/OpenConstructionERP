// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The delete affordance has to follow the permission, not a role list that
 * was true once.
 *
 * `property_dev.owner_scoped_delete` sits at EDITOR level because on those
 * routes the wall is ownership rather than role. The drawer used to gate its
 * delete button on four role strings that predate that change, so the button
 * was shown to roles the ownership check rejects and hidden from the role the
 * change was made for. A UI that hides the button reads as a fix that did not
 * land, which is worse than one that shows a button the server refuses.
 *
 * This mounts the real drawer and asks the rendered document. It deliberately
 * does not assert on the constant, on a class name, or on a test id: a class
 * assertion has gone green over broken UI here before, and asserting on the
 * constant would only restate the source line it is supposed to check. The
 * query is by accessible role and name, which is what a person clicking has.
 *
 * The other half of the invariant, that the constant equals what the backend
 * admits, is enforced by scripts/check_role_mirrors_match_the_backend.py. This
 * file proves the constant reaches the screen; that one proves it is right.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    listSelections: vi.fn().mockResolvedValue([]),
    deleteBuyer: vi.fn().mockResolvedValue(undefined),
  };
});

import { BuyerDetailDrawer } from '../PropertyDevPage';
import { useAuthStore } from '@/stores/useAuthStore';

const BUYER = {
  id: 'b-1',
  development_id: 'd-1',
  plot_id: null,
  full_name: 'Test Buyer',
  email: 'buyer@example.com',
  phone: null,
  status: 'reserved',
  freeze_deadline: null,
  deposit_amount: null,
  currency: 'EUR',
  metadata: {},
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
};

function mountAs(role: string | null) {
  act(() => {
    useAuthStore.setState({ userRole: role, isAuthenticated: role !== null });
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BuyerDetailDrawer
          buyerId="b-1"
          buyers={[BUYER]}
          plots={[]}
          developmentId="d-1"
          onClose={() => {}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function deleteButton() {
  return screen.queryByRole('button', { name: 'Delete' });
}

describe('buyer delete affordance', () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({ userRole: null, isAuthenticated: false });
    });
  });

  it('offers delete to an editor, the role owner-scoped delete was lowered for', () => {
    mountAs('editor');
    expect(deleteButton()).toBeEnabled();
  });

  it('offers delete to an alias that resolves to editor', () => {
    // The permission admits a closure, not the three role names in the
    // mapping. An estimator resolves to EDITOR through ROLE_ALIASES and is
    // served by the backend, so hiding the button from them would be the
    // same defect in a less obvious costume.
    mountAs('estimator');
    expect(deleteButton()).toBeEnabled();
  });

  it('still offers delete to an admin', () => {
    mountAs('admin');
    expect(deleteButton()).toBeEnabled();
  });

  it('shows a viewer delete disabled, with the reason', () => {
    // Without this the suite would pass on a component that shows the button
    // unconditionally, which is the cheapest wrong way to make the three
    // assertions above go green.
    mountAs('viewer');
    expect(deleteButton()).toBeDisabled();
    expect(deleteButton()).toHaveAttribute('title', 'Only a manager or administrator can do this.');
  });

  it('shows delete disabled while the role is still unknown', () => {
    mountAs(null);
    expect(deleteButton()).toBeDisabled();
  });
});
