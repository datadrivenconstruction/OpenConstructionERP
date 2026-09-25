// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <SovReconcilePanel>.
//
// The reconcile writes billable lines, so a person has to see the list and
// confirm it. These pin that: nothing shows when nothing is missing, the
// first press only asks, and the apply sends exactly the keys the preview
// listed.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getSovReconcilePreview: vi.fn(),
  applySovReconcile: vi.fn(),
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

  it('offers no action on a contract that is not active', async () => {
    previewMock.mockResolvedValue({ ...PREVIEW, can_apply: false, contract_status: 'suspended' });
    renderPanel();
    expect(await screen.findByText('CO-007')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reconcile change orders/ })).toBeNull();
  });
});
