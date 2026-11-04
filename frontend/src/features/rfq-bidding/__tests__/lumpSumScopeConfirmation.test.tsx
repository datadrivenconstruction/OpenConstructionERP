// A lump-sum quote with no line prices stays out of the ranking until the estimator confirms its scope.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: () => Promise.resolve({ items: [], total: 0 }),
}));

import { ExcludedQuoteRow } from '../RFQBiddingPage';
import type { QuoteComparison } from '../api';

const t = (k: string, o?: Record<string, unknown>) => String(o?.defaultValue ?? k);

function quote(reasons: string[]): QuoteComparison {
  return { bid_id: 'b-1', bidder_contact_id: 'c-1', reasons } as unknown as QuoteComparison;
}

function mount(reasons: string[], onConfirmScope = vi.fn(), confirmingScope = false) {
  render(
    <ul>
      <ExcludedQuoteRow
        quote={quote(reasons)}
        bidderName={() => 'Alpha Ltd'}
        onConfirmScope={onConfirmScope}
        confirmingScope={confirmingScope}
        t={t}
      />
    </ul>,
  );
  return onConfirmScope;
}

afterEach(cleanup);

describe('Lump-sum scope confirmation', () => {
  it('offers the toggle with its explanation for an unconfirmed lump sum', () => {
    const onConfirm = mount(['lump_sum_scope_unconfirmed']);
    expect(screen.getByText('Lump sum only: scope coverage not confirmed')).toBeTruthy();
    expect(screen.getByText(/covers the whole scope/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm full scope' }));
    expect(onConfirm).toHaveBeenCalledWith('b-1');
  });

  it('is not offered for other exclusion reasons', () => {
    mount(['withdrawn']);
    expect(screen.queryByRole('button', { name: 'Confirm full scope' })).toBeNull();
  });

  it('disables the button while the confirmation is saving', () => {
    mount(['lump_sum_scope_unconfirmed'], vi.fn(), true);
    expect((screen.getByRole('button', { name: 'Confirm full scope' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
