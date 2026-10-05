// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { vi } from 'vitest';
import { MarkupRowEditor, bandsToWire, readBandDraft, validateBandDraft } from './MarkupRowEditor';
import { MarkupPanel } from './MarkupPanel';
import type { Markup } from './api';

const updateMarkup = vi.fn((_boqId: string, markupId: string, data: Record<string, unknown>) =>
  Promise.resolve({ id: markupId, ...data }),
);

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    boqApi: {
      ...actual.boqApi,
      updateMarkup: (boqId: string, markupId: string, data: Record<string, unknown>) =>
        updateMarkup(boqId, markupId, data),
    },
  };
});

/**
 * The row editor is what lets an estimator build a real stack in the panel:
 * AGK on Herstellkosten (a running total after BGK), a bond off a tiered card,
 * a fixed site set-up sum. These tests pin what the editor shows for each
 * choice and what it sends, because the preview is the whole point: the
 * estimator sees the base and the amount move before anything is saved.
 */

function row(overrides: Partial<Markup> = {}): Markup {
  return {
    id: 'm-agk',
    boq_id: 'boq-1',
    name: 'AGK',
    markup_type: 'percentage',
    category: 'overhead',
    percentage: 8,
    fixed_amount: '0.00',
    apply_to: 'direct_cost',
    sort_order: 1,
    is_active: true,
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderEditor(markup: Markup, onSave = vi.fn()) {
  render(
    <MarkupRowEditor
      markup={markup}
      directCost={100000}
      runningBefore={110000}
      currencyCode=""
      locale="en-US"
      onSave={onSave}
      onCancel={vi.fn()}
    />,
  );
  return onSave;
}

const preview = () => ({
  base: screen.queryByTestId('markup-preview-base')?.textContent ?? null,
  amount: screen.getByTestId('markup-preview-amount').textContent,
});

describe('band card helpers', () => {
  it('seeds one open-ended band at the current rate, so switching does not move the amount', () => {
    expect(readBandDraft({}, 8)).toEqual([{ upTo: '', rate: '8' }]);
  });

  it('reads a stored card in cascade order, open-ended band last', () => {
    const draft = readBandDraft(
      {
        bands: [
          { up_to: null, percentage: '1' },
          { up_to: '500000', percentage: '1.5' },
          { up_to: '100000', percentage: '2.5' },
        ],
      },
      0,
    );
    expect(draft.map((b) => b.upTo)).toEqual(['100000', '500000', '']);
  });

  it('accepts a contiguous, rising card and refuses the shapes that cannot mean one thing', () => {
    expect(validateBandDraft([{ upTo: '100000', rate: '2.5' }, { upTo: '', rate: '1.5' }])).toEqual([]);
    // A band in the middle with no limit.
    expect(validateBandDraft([{ upTo: '', rate: '2' }, { upTo: '', rate: '1' }])).toEqual([
      { index: 0, issue: 'limit' },
    ]);
    // Limits that do not climb.
    expect(validateBandDraft([{ upTo: '500', rate: '2' }, { upTo: '200', rate: '1' }])).toEqual([
      { index: 1, issue: 'order' },
    ]);
    // A rate outside 0-100.
    expect(validateBandDraft([{ upTo: '', rate: '120' }])).toEqual([{ index: 0, issue: 'rate' }]);
  });

  it('sends Decimal strings and null for the open band', () => {
    expect(bandsToWire([{ upTo: '100 000', rate: '2,5' }, { upTo: '', rate: '1' }])).toEqual([
      { up_to: '100000', percentage: '2.5' },
      { up_to: null, percentage: '1' },
    ]);
  });
});

describe('MarkupRowEditor', () => {
  it('previews a direct-cost line on the direct cost', () => {
    renderEditor(row());
    expect(preview()).toEqual({ base: '100,000.00', amount: '8,000.00' });
  });

  it('moves the base to the running total and saves only apply_to (AGK on Herstellkosten)', () => {
    const onSave = renderEditor(row());
    fireEvent.click(screen.getByRole('radio', { name: /Running total/ }));
    // 8 % of EKT 100,000 + BGK 10,000.
    expect(preview()).toEqual({ base: '110,000.00', amount: '8,800.00' });

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSave).toHaveBeenCalledWith({ apply_to: 'cumulative' });
  });

  it('explains every base in plain words', () => {
    renderEditor(row());
    expect(screen.getByText(/Only the sum of the positions/)).toBeInTheDocument();
    expect(screen.getByText(/Sum of positions plus every active markup above this line/)).toBeInTheDocument();
    expect(screen.getByText(/Works the same as running total/)).toBeInTheDocument();
  });

  it('turns a line into a fixed amount, hides the base and sends money as a string', () => {
    const onSave = renderEditor(row());
    fireEvent.click(screen.getByRole('radio', { name: 'Fixed amount' }));

    expect(screen.queryByRole('radio', { name: /Running total/ })).toBeNull();
    expect(screen.getByText('A fixed amount does not depend on a base.')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '12500.50' } });
    expect(preview()).toEqual({ base: null, amount: '12,500.50' });

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSave).toHaveBeenCalledWith({ markup_type: 'fixed', fixed_amount: '12500.50' });
  });

  it('refuses a negative fixed amount before the round-trip', () => {
    const onSave = renderEditor(row({ markup_type: 'fixed', fixed_amount: '100.00' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '-5' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Enter an amount of zero or more.');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('builds a bond card band by band and previews the tiered premium', () => {
    const onSave = renderEditor(row({ name: 'Bond', category: 'bond', percentage: 1, apply_to: 'cumulative' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Banded rates' }));

    // Seeded at the current rate: the same 1 % of 110,000 the percentage charged.
    expect(screen.getAllByTestId('markup-band-row')).toHaveLength(1);
    expect(preview().amount).toBe('1,100.00');

    fireEvent.click(screen.getByRole('button', { name: 'Add band' }));
    const rows = screen.getAllByTestId('markup-band-row');
    expect(rows).toHaveLength(2);
    // The new band sits in front of the open-ended one and needs a limit.
    expect(screen.getByRole('alert')).toHaveTextContent('Enter an upper limit above zero');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();

    const [first, second] = rows;
    fireEvent.change(within(first!).getByLabelText('Up to'), { target: { value: '100000' } });
    fireEvent.change(within(first!).getByLabelText('Rate (%)'), { target: { value: '2.5' } });
    fireEvent.change(within(second!).getByLabelText('Rate (%)'), { target: { value: '1.5' } });

    // 100,000 at 2.5 % + 10,000 at 1.5 %.
    expect(preview().amount).toBe('2,650.00');
    // "From" of the second band is the first band's limit: contiguous by construction.
    expect(within(second!).getByText('100,000.00')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSave).toHaveBeenCalledWith({
      markup_type: 'banded',
      metadata: {
        bands: [
          { up_to: '100000', percentage: '2.5' },
          { up_to: null, percentage: '1.5' },
        ],
      },
    });
  });

  it('flags limits that do not climb', () => {
    renderEditor(
      row({
        markup_type: 'banded',
        metadata: { bands: [{ up_to: '1000', percentage: '2' }, { up_to: null, percentage: '1' }] },
      }),
    );
    const [, second] = screen.getAllByTestId('markup-band-row');
    fireEvent.change(within(second!).getByLabelText('Up to'), { target: { value: '500' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Each upper limit must be higher than the one before it.');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });

  it('sends nothing when nothing changed', () => {
    const onSave = renderEditor(row());
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSave).toHaveBeenCalledWith({});
  });
});

describe('MarkupPanel row order', () => {
  function renderPanel(markups: Markup[]) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MarkupPanel
          boqId="boq-1"
          markups={markups}
          directCost={100000}
          currencySymbol=""
          currencyCode=""
          locale="en-US"
          fmt={new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        />
      </QueryClientProvider>,
    );
  }

  it('renumbers every line on a move and saves only those whose place changed', async () => {
    updateMarkup.mockClear();
    // Two lines share sort_order 0, the shape an old add could leave behind.
    renderPanel([
      row({ id: 'a', name: 'BGK', sort_order: 0 }),
      row({ id: 'b', name: 'AGK', sort_order: 0 }),
      row({ id: 'c', name: 'W+G', sort_order: 2 }),
    ]);

    const downButtons = screen.getAllByRole('button', { name: 'Move down' });
    const upButtons = screen.getAllByRole('button', { name: 'Move up' });
    // The ends cannot move further.
    expect(upButtons[0]).toBeDisabled();
    expect(downButtons[2]).toBeDisabled();

    fireEvent.click(upButtons[2]!);

    await waitFor(() => expect(updateMarkup).toHaveBeenCalledTimes(2));
    const calls = updateMarkup.mock.calls.map(([, id, data]) => [id, data]);
    // New order a, c, b: c moves into place 1, b to place 2. a already holds 0.
    expect(calls).toEqual(
      expect.arrayContaining([
        ['c', { sort_order: 1 }],
        ['b', { sort_order: 2 }],
      ]),
    );
  });

  it('shows each line base in the table and opens the editor from the row', () => {
    renderPanel([
      row({ id: 'a', name: 'BGK', sort_order: 0, percentage: 10 }),
      row({ id: 'b', name: 'AGK', sort_order: 1, apply_to: 'cumulative' }),
    ]);
    expect(screen.getByRole('button', { name: 'Sum of positions' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Running total incl. rows above' })).toBeInTheDocument();

    const toggles = screen.getAllByRole('button', { name: 'Edit calculation' });
    fireEvent.click(toggles[1]!);
    expect(toggles[1]).toHaveAttribute('aria-expanded', 'true');
    // AGK's running total is EKT plus BGK: 100,000 + 10,000.
    expect(preview()).toEqual({ base: '110,000.00', amount: '8,800.00' });
  });
});
