// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CwicrMatchPanel } from '../CwicrMatchPanel';

vi.mock('../api', () => ({
  matchCwicr: vi.fn(),
}));

import { matchCwicr } from '../api';

const fakeRows = [
  {
    cost_item_id: 'id-001',
    code: 'CWICR-001',
    description: 'Reinforced concrete wall C30/37',
    unit: 'm3',
    unit_rate: 185.0,
    currency: 'EUR',
    score: 0.92,
    source: 'lexical',
  },
  {
    cost_item_id: 'id-002',
    code: 'CWICR-002',
    description: 'Concrete blinding C12/15',
    unit: 'm3',
    unit_rate: 95.0,
    currency: 'EUR',
    score: 0.71,
    source: 'lexical',
  },
];

describe('CwicrMatchPanel', () => {
  beforeEach(() => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockReset();
  });

  it('renders the search input and mode selector', () => {
    render(<CwicrMatchPanel onApply={() => undefined} />);
    expect(screen.getByTestId('cwicr-match-input')).toBeInTheDocument();
    expect(screen.getByTestId('cwicr-match-mode')).toBeInTheDocument();
    expect(screen.getByTestId('cwicr-match-submit')).toBeInTheDocument();
  });

  it('does not call the API when query is blank', async () => {
    render(<CwicrMatchPanel onApply={() => undefined} />);
    fireEvent.click(screen.getByTestId('cwicr-match-submit'));
    // Submit is disabled when query is empty — so matchCwicr must NOT fire.
    expect(matchCwicr).not.toHaveBeenCalled();
  });

  it('renders ranked results after a successful search', async () => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockResolvedValueOnce(fakeRows);

    render(<CwicrMatchPanel onApply={() => undefined} initialQuery="concrete wall" />);

    fireEvent.click(screen.getByTestId('cwicr-match-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cwicr-match-results')).toBeInTheDocument();
    });

    // Both rows are rendered.
    expect(screen.getByTestId('cwicr-match-row-CWICR-001')).toBeInTheDocument();
    expect(screen.getByTestId('cwicr-match-row-CWICR-002')).toBeInTheDocument();

    // Score is shown as percent (0.92 → 92%).
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('71%')).toBeInTheDocument();

    // matchCwicr received the right body.
    expect(matchCwicr).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'concrete wall', mode: 'lexical' }),
    );
  });

  it('forwards unit, lang and region hints to the API', async () => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(
      <CwicrMatchPanel
        initialQuery="brick wall"
        unitHint="m2"
        langHint="de"
        region="DE_BERLIN"
        onApply={() => undefined}
      />,
    );
    fireEvent.click(screen.getByTestId('cwicr-match-submit'));

    await waitFor(() => {
      expect(matchCwicr).toHaveBeenCalledWith(
        expect.objectContaining({
          query: 'brick wall',
          unit: 'm2',
          lang: 'de',
          region: 'DE_BERLIN',
        }),
      );
    });
  });

  it('calls onApply with the chosen row and shows the Applied state', async () => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockResolvedValueOnce(fakeRows);

    const onApply = vi.fn();
    render(<CwicrMatchPanel onApply={onApply} initialQuery="concrete wall" />);
    fireEvent.click(screen.getByTestId('cwicr-match-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cwicr-match-row-CWICR-001')).toBeInTheDocument();
    });

    const applyBtn = screen.getByTestId('cwicr-match-apply-CWICR-001');
    fireEvent.click(applyBtn);

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'CWICR-001', cost_item_id: 'id-001' }),
    );
    // After clicking Apply, the button shows the "Applied" label.
    expect(applyBtn.textContent || '').toMatch(/Applied/);
  });

  it('renders an error banner when the API throws', async () => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'));

    render(<CwicrMatchPanel onApply={() => undefined} initialQuery="concrete wall" />);
    fireEvent.click(screen.getByTestId('cwicr-match-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cwicr-match-error')).toBeInTheDocument();
    });
    // The mocked t() returns the defaultValue verbatim (no {{message}}
    // interpolation). What we care about here is just that the error
    // banner appears on a failed call — no rows table.
    expect(screen.queryByTestId('cwicr-match-results')).not.toBeInTheDocument();
  });

  it('renders the empty state after a successful search with no rows', async () => {
    (matchCwicr as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(<CwicrMatchPanel onApply={() => undefined} initialQuery="zzz nothing" />);
    fireEvent.click(screen.getByTestId('cwicr-match-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cwicr-match-empty')).toBeInTheDocument();
    });
  });
});
