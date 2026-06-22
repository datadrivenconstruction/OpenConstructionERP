import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MarkupPanel } from './MarkupPanel';
import type { Markup } from './api';

/**
 * Regression tests for audit findings #4 and #5 (BOQ fixed-amount markups).
 *
 * The backend serialises ``BOQMarkup.fixed_amount`` as a Decimal-rendered JSON
 * *string* (e.g. ``"500.00"``), while ``api.ts`` historically typed it as
 * ``number``. Two symptoms followed from that one wire-vs-type mismatch:
 *
 *  - #5 (MarkupPanel): a ``typeof m.fixed_amount === 'number'`` guard rejected
 *    the string and rendered every fixed markup's Amount — and the panel's Net
 *    Total — as 0.
 *  - #4 (BOQEditorPage footer/exports): the cascade does ``running += amount``
 *    with ``running`` starting as the numeric direct cost, so a string
 *    ``fixed_amount`` triggered STRING CONCATENATION (1000 + "500.00" =>
 *    "1000500.00") and poisoned the Net Total / VAT / Gross footer + exports.
 *
 * MarkupPanel runs the exact same ``running += amount`` cascade as the editor
 * footer's ``markupTotals`` memo, so rendering it with the real Decimal-string
 * wire value exercises both the display path (#5) and the additive-cascade
 * contract (#4): the fix coerces through ``toNum`` so the markup shows its real
 * value and the Net Total stays a finite, correctly-summed number.
 */

function renderPanel(markups: Markup[], directCost: number) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MarkupPanel
        boqId="boq-1"
        markups={markups}
        directCost={directCost}
        currencySymbol=""
        currencyCode=""
        locale="en-US"
        fmt={new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      />
    </QueryClientProvider>,
  );
}

function fixedMarkup(fixedAmount: number | string): Markup {
  return {
    id: 'm-fixed',
    boq_id: 'boq-1',
    name: 'Site overhead',
    markup_type: 'fixed',
    category: 'overhead',
    percentage: 0,
    // The wire value: a Decimal rendered as a JSON string.
    fixed_amount: fixedAmount,
    apply_to: 'direct_cost',
    sort_order: 0,
    is_active: true,
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

describe('MarkupPanel fixed-amount markups (audit #4/#5)', () => {
  it('renders the real fixed amount from a Decimal-as-string wire value (not 0)', () => {
    // fixed_amount arrives as the string "50000.00"; the old typeof-number
    // guard rejected it and rendered the markup's Amount (and its Net Total
    // contribution) as 0. With a non-zero direct cost the real amount is
    // visible and the Net Total is the sum (10,000 + 50,000).
    renderPanel([fixedMarkup('50000.00')], 10000);

    // The fixed markup's Amount cell shows its real value, never 0.00.
    expect(screen.getAllByText('50,000.00').length).toBeGreaterThan(0);
    // Net Total = direct cost + fixed amount, summed as numbers.
    expect(screen.getByText('60,000.00')).toBeInTheDocument();
  });

  it('sums the cascade as numbers, not string concatenation, for the Net Total', () => {
    // directCost (number) + fixed_amount (string) must add to 1,500.00 — the
    // pre-fix code produced "1000500.00" via string concatenation.
    renderPanel([fixedMarkup('500.00')], 1000);

    expect(screen.getByText('1,500.00')).toBeInTheDocument();
    expect(screen.queryByText('1000500.00')).toBeNull();
  });
});
