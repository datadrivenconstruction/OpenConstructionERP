// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the optional preview source of <PopulatePreviewModal>.
//
// The modal previews claim lines from field progress, and the claim page's
// subcontractor panel reuses it for lines derived from the subs' approved
// amounts. What is worth pinning:
//
//   * left alone, the modal still asks field progress and nothing else, in
//     its own words;
//   * given a loader, it asks that loader only, with the caller's words;
//   * either way the commit goes through the one commit route, and the
//     success toast is the caller's when it gives one, the modal's otherwise.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  populateClaimPreview: vi.fn(),
  commitClaimLines: vi.fn(),
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import * as api from './api';
import type { ProgressClaimPopulatePreview } from './api';
import { PopulatePreviewModal } from './PopulatePreviewModal';

const populateMock = vi.mocked(api.populateClaimPreview);
const commitMock = vi.mocked(api.commitClaimLines);

function preview(over: Partial<ProgressClaimPopulatePreview> = {}): ProgressClaimPopulatePreview {
  return {
    claim_id: 'claim-1',
    contract_id: 'ctr-1',
    currency: 'USD',
    items: [
      {
        contract_line_id: 'line-1',
        contract_line_code: '03.10',
        contract_line_description: 'Footings',
        boq_position_id: 'pos-1',
        unit: null,
        contract_quantity: '1',
        contract_line_value: '10000',
        observed_pct: '20',
        period_label: null,
        recorded_at: null,
        period_completed_qty: '0',
        period_completed_value: '2000',
        cumulative_completed_value: '2000',
      },
    ],
    skipped_unlinked: 0,
    skipped_no_progress: 0,
    skipped_foreign_currency: 0,
    gross: '2000',
    retention: '0',
    prior_claims_total: '0',
    net_due: '2000',
    ...over,
  };
}

function renderModal(props: Partial<React.ComponentProps<typeof PopulatePreviewModal>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PopulatePreviewModal claimId="claim-1" currency="USD" onClose={vi.fn()} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PopulatePreviewModal preview source', () => {
  it('asks field progress when no loader is given, in its own words', async () => {
    populateMock.mockResolvedValue(preview());
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    expect(populateMock).toHaveBeenCalledWith('claim-1');
    expect(screen.getByText('Populate from progress observations')).toBeTruthy();
  });

  it('asks only the given loader, and shows the caller title and subtitle', async () => {
    const loader = vi.fn().mockResolvedValue(preview());
    renderModal({ loadPreview: loader, title: 'From the subs', subtitle: 'Approved amounts' });
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    expect(loader).toHaveBeenCalledWith('claim-1');
    expect(populateMock).not.toHaveBeenCalled();
    expect(screen.getByText('From the subs')).toBeTruthy();
    expect(screen.getByText('Approved amounts')).toBeTruthy();
    expect(screen.queryByText('Populate from progress observations')).toBeNull();
  });

  it('shows the caller empty text when the loader has nothing to suggest', async () => {
    const loader = vi.fn().mockResolvedValue(preview({ items: [] }));
    renderModal({ loadPreview: loader, emptyText: 'No sub lines yet' });
    await waitFor(() => expect(screen.getByTestId('populate-empty')).toBeTruthy());
    expect(screen.getByTestId('populate-empty').textContent).toContain('No sub lines yet');
  });

  it('commits a loaded preview through the same commit route', async () => {
    commitMock.mockResolvedValue({} as never);
    const loader = vi.fn().mockResolvedValue(preview());
    renderModal({ loadPreview: loader });
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(commitMock).toHaveBeenCalledWith('claim-1', [
        { contract_line_id: 'line-1', period_completed_pct: 20, period_completed_value: 2000 },
      ]),
    );
  });

  it('toasts its own words after a commit when the caller gives none', async () => {
    commitMock.mockResolvedValue({} as never);
    populateMock.mockResolvedValue(preview());
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith({ type: 'success', title: 'Claim populated from progress' }),
    );
  });

  it("toasts the caller's words after a commit when it gives them", async () => {
    commitMock.mockResolvedValue({} as never);
    const loader = vi.fn().mockResolvedValue(preview());
    renderModal({ loadPreview: loader, successText: 'Lines taken from the subs' });
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith({ type: 'success', title: 'Lines taken from the subs' }),
    );
  });
});

describe('PopulatePreviewModal change order lines', () => {
  it('names the line a change order line is billed with, and commits it like any other', async () => {
    commitMock.mockResolvedValue({} as never);
    const base = preview();
    populateMock.mockResolvedValue(
      preview({
        items: [
          base.items[0]!,
          {
            ...base.items[0]!,
            contract_line_id: 'line-2',
            contract_line_code: 'CO-004',
            contract_line_description: 'Owner change',
            contract_line_value: '3400',
            period_completed_value: '680',
            cumulative_completed_value: '680',
            adjusts_contract_line_id: 'line-1',
            adjusts_line_code: '03.10',
          },
        ],
      }),
    );
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    expect(screen.getByText('Change order line, billed at the percent of 03.10')).toBeTruthy();
    // Only the change order line says so.
    expect(screen.getAllByText(/Change order line, billed at the percent of/)).toHaveLength(1);
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(commitMock).toHaveBeenCalledWith('claim-1', [
        { contract_line_id: 'line-1', period_completed_pct: 20 },
        { contract_line_id: 'line-2', period_completed_pct: 20 },
      ]),
    );
  });
});

// A second-period row: the line is worth 10,000, earlier claims billed 2,000
// (20%), and the site now measures 40% to date, so this period bills 2,000.
function secondPeriod(): ProgressClaimPopulatePreview {
  const base = preview();
  return {
    ...base,
    items: [
      {
        ...base.items[0]!,
        observed_pct: '40',
        prior_completed_value: '2000',
        period_completed_value: '2000',
        cumulative_completed_value: '4000',
      },
    ],
  };
}

function digits(testId: string): string {
  return (screen.getByTestId(testId).textContent ?? '').replace(/[^0-9.]/g, '');
}

describe('PopulatePreviewModal correcting field progress', () => {
  it('commits the percent alone, so the server bills it over the earlier claims', async () => {
    commitMock.mockResolvedValue({} as never);
    populateMock.mockResolvedValue(secondPeriod());
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    expect(digits('populate-period-line-1')).toBe('2000.00');
    expect(digits('populate-to-date-line-1')).toBe('4000.00');
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(commitMock).toHaveBeenCalledWith('claim-1', [
        { contract_line_id: 'line-1', period_completed_pct: 40 },
      ]),
    );
  });

  it('works a corrected percent out over what was billed before, and commits it', async () => {
    commitMock.mockResolvedValue({} as never);
    populateMock.mockResolvedValue(secondPeriod());
    renderModal();
    const input = await screen.findByLabelText('Percent complete to date for line 03.10');
    fireEvent.change(input, { target: { value: '55' } });
    // 55% of 10,000 is 5,500 to date, of which 2,000 was billed before.
    expect(digits('populate-period-line-1')).toBe('3500.00');
    expect(digits('populate-to-date-line-1')).toBe('5500.00');
    expect(screen.getByTestId('populate-selected-summary').textContent?.replace(/[^0-9.]/g, '')).toContain(
      '3500.00',
    );
    expect(screen.getByText(/Corrected by you/)).toBeTruthy();
    fireEvent.click(screen.getByText('Commit lines'));
    await waitFor(() =>
      expect(commitMock).toHaveBeenCalledWith('claim-1', [
        { contract_line_id: 'line-1', period_completed_pct: 55 },
      ]),
    );
  });

  it('bills nothing on a percent below what was billed before, and says so', async () => {
    populateMock.mockResolvedValue(secondPeriod());
    renderModal();
    const input = await screen.findByLabelText('Percent complete to date for line 03.10');
    fireEvent.change(input, { target: { value: '10' } });
    expect(digits('populate-period-line-1')).toBe('0.00');
    expect(digits('populate-to-date-line-1')).toBe('2000.00');
    expect(screen.getByText(/Below what earlier claims already billed/)).toBeTruthy();
  });

  it('refuses to commit a percent outside 0 to 100', async () => {
    populateMock.mockResolvedValue(secondPeriod());
    renderModal();
    const input = await screen.findByLabelText('Percent complete to date for line 03.10');
    fireEvent.change(input, { target: { value: '150' } });
    expect(screen.getByRole('alert').textContent).toContain('Enter a percent from 0 to 100.');
    expect(screen.getByText('Commit lines').closest('button')?.disabled).toBe(true);
    fireEvent.change(input, { target: { value: '100' } });
    expect(screen.getByText('Commit lines').closest('button')?.disabled).toBe(false);
  });

  it('goes back to the measured percent', async () => {
    populateMock.mockResolvedValue(secondPeriod());
    renderModal();
    const input = await screen.findByLabelText('Percent complete to date for line 03.10');
    fireEvent.change(input, { target: { value: '70' } });
    expect(digits('populate-period-line-1')).toBe('5000.00');
    fireEvent.click(screen.getByLabelText(/Back to the measured/));
    expect(digits('populate-period-line-1')).toBe('2000.00');
    expect((input as HTMLInputElement).value).toBe('40');
    expect(screen.queryByText(/Corrected by you/)).toBeNull();
  });

  it('leaves the rows of another source read-only', async () => {
    const loader = vi.fn().mockResolvedValue(secondPeriod());
    renderModal({ loadPreview: loader });
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    expect(screen.queryByLabelText('Percent complete to date for line 03.10')).toBeNull();
    expect(screen.queryByRole('spinbutton')).toBeNull();
  });
});
