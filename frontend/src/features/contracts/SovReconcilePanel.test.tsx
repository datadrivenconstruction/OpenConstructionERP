// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <SovReconcilePanel>.
//
// The reconcile writes billable lines, so a person has to see the list and
// confirm it. These pin that: nothing shows when nothing is missing, the
// first press only asks, the apply sends exactly the ticked keys, and a
// change can be set aside as already on the schedule and offered again.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getSovReconcilePreview: vi.fn(),
  applySovReconcile: vi.fn(),
  setSovReconcileExclusion: vi.fn(),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) =>
    sel({ addToast: vi.fn() }),
}));

import { SovReconcilePanel } from './SovReconcilePanel';
import * as api from './api';
import type { SovReconcilePreview } from './api';

const previewMock = vi.mocked(api.getSovReconcilePreview);
const applyMock = vi.mocked(api.applySovReconcile);
const exclusionMock = vi.mocked(api.setSovReconcileExclusion);

const PREVIEW: SovReconcilePreview = {
  contract_id: 'c-1',
  contract_status: 'active',
  can_apply: true,
  currency: 'USD',
  contract_sum: '112500.0000',
  scheduled_total: '100000.0000',
  scheduled_total_after: '112500.0000',
  items: [
    {
      source_key: 'change_order:co-7',
      source_kind: 'change_order',
      source_id: 'co-7',
      source_code: 'CO-007',
      title: 'Extra basement waterproofing',
      amount: '15000.0000',
      currency: 'USD',
      approved_on: '2026-05-04',
    },
    {
      source_key: 'variation_order:vo-3',
      source_kind: 'variation_order',
      source_id: 'vo-3',
      source_code: 'VO-003',
      title: 'Revised stair core',
      amount: '-2500.0000',
      currency: 'USD',
      approved_on: null,
    },
  ],
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SovReconcilePanel contractId="c-1" />
    </QueryClientProvider>,
  );
}

describe('SovReconcilePanel', () => {
  beforeEach(() => {
    previewMock.mockReset();
    applyMock.mockReset();
    exclusionMock.mockReset();
  });

  it('renders nothing when every approved change is on the schedule', async () => {
    previewMock.mockResolvedValue({ ...PREVIEW, items: [], can_apply: false });
    const { container } = renderPanel();
    await waitFor(() => expect(previewMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('asks before posting, then posts exactly the previewed keys', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    applyMock.mockResolvedValue({ ...PREVIEW, items: [], posted: 2 });
    renderPanel();

    expect(await screen.findByText('CO-007')).toBeInTheDocument();
    expect(screen.getByText('Revised stair core')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Reconcile change orders/ }));
    expect(applyMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(applyMock).toHaveBeenCalledWith('c-1', [
        'change_order:co-7',
        'variation_order:vo-3',
      ]),
    );
  });

  it('posts only the ticked changes', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    applyMock.mockResolvedValue({ ...PREVIEW, items: [PREVIEW.items[1]!], posted: 1 });
    renderPanel();

    fireEvent.click(await screen.findByRole('checkbox', { name: /VO-003/ }));
    fireEvent.click(screen.getByRole('button', { name: /Reconcile change orders/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('c-1', ['change_order:co-7']));
  });

  it('sets a change aside with a reason, and offers a set-aside change again', async () => {
    previewMock.mockResolvedValue(PREVIEW);
    const [co, vo] = PREVIEW.items;
    exclusionMock.mockResolvedValueOnce({
      ...PREVIEW,
      items: [vo!],
      excluded: [{ ...co!, excluded_by: 'u-1', excluded_at: null, reason: 'Line A-2' }],
    });
    renderPanel();

    const [setAside] = await screen.findAllByRole('button', { name: 'Already on the schedule' });
    fireEvent.click(setAside!);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Line A-2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set aside' }));
    await waitFor(() =>
      expect(exclusionMock).toHaveBeenCalledWith('c-1', 'change_order:co-7', true, 'Line A-2'),
    );
    expect(await screen.findByText('Set aside as already on the schedule of values')).toBeInTheDocument();
    expect(screen.getByText('Line A-2')).toBeInTheDocument();

    exclusionMock.mockResolvedValueOnce({ ...PREVIEW, excluded: [] });
    fireEvent.click(screen.getByRole('button', { name: /Offer again/ }));
    await waitFor(() =>
      expect(exclusionMock).toHaveBeenLastCalledWith('c-1', 'change_order:co-7', false, ''),
    );
  });

  it('offers no action on a contract that is not active', async () => {
    previewMock.mockResolvedValue({ ...PREVIEW, can_apply: false, contract_status: 'suspended' });
    renderPanel();
    expect(await screen.findByText('CO-007')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reconcile change orders/ })).toBeNull();
  });
});
