// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the banner that reports a subcontract written twice.
//
// One scenario: the 120,000 EUR drywall agreement on the Subcontractors page
// and contract SC-009 in Contracts, with nothing linking them.
//
//   * the pair is shown with both names, and nothing is shown without one;
//   * on an agreement, only that agreement's pairs are shown;
//   * Link asks first, and only then sets the agreement's contract;
//   * "These are different subcontracts" dismisses the pair on the agreement;
//   * values far apart are shown side by side, close ones are not.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  listUnlinkedTwins: vi.fn(),
  dismissUnlinkedTwin: vi.fn(),
  updateAgreement: vi.fn(),
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import * as api from './api';
import type { UnlinkedTwin } from './api';
import { UnlinkedTwinBanner } from './UnlinkedTwinBanner';

const PAIR: UnlinkedTwin = {
  agreement_id: 'ag-1',
  agreement_title: 'Drywall, block B',
  contract_id: 'ct-9',
  contract_code: 'SC-009',
  contract_title: 'Drywall subcontract',
  currency: 'EUR',
  agreement_value: '120000.00',
  contract_value: '120000.00',
  matched_on: 'counterparty',
  value_close: true,
};

function renderBanner(props: { projectId: string; agreementId?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UnlinkedTwinBanner {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listUnlinkedTwins).mockResolvedValue([PAIR]);
  vi.mocked(api.updateAgreement).mockResolvedValue({} as never);
  vi.mocked(api.dismissUnlinkedTwin).mockResolvedValue({} as never);
});

describe('UnlinkedTwinBanner', () => {
  it('shows the pair for the project', async () => {
    renderBanner({ projectId: 'prj-1' });
    expect(await screen.findByTestId('unlinked-twin-banner')).toBeInTheDocument();
    expect(api.listUnlinkedTwins).toHaveBeenCalledWith('prj-1');
    expect(screen.getByText('subcontractors.twin.message')).toBeInTheDocument();
    expect(screen.queryByText('subcontractors.twin.values_differ')).not.toBeInTheDocument();
  });

  it('shows nothing when no pair is found', async () => {
    vi.mocked(api.listUnlinkedTwins).mockResolvedValue([]);
    renderBanner({ projectId: 'prj-1' });
    await waitFor(() => expect(api.listUnlinkedTwins).toHaveBeenCalled());
    expect(screen.queryByTestId('unlinked-twin-banner')).not.toBeInTheDocument();
  });

  it('on an agreement shows only that agreement', async () => {
    renderBanner({ projectId: 'prj-1', agreementId: 'ag-other' });
    await waitFor(() => expect(api.listUnlinkedTwins).toHaveBeenCalled());
    expect(screen.queryByTestId('unlinked-twin-banner')).not.toBeInTheDocument();
  });

  it('links only after the confirmation', async () => {
    renderBanner({ projectId: 'prj-1', agreementId: 'ag-1' });
    fireEvent.click(await screen.findByRole('button', { name: /subcontractors\.twin\.link/ }));
    expect(api.updateAgreement).not.toHaveBeenCalled();
    expect(await screen.findByText('subcontractors.twin.confirm_message')).toBeInTheDocument();

    const linkButtons = screen.getAllByRole('button', { name: /subcontractors\.twin\.link/ });
    fireEvent.click(linkButtons[linkButtons.length - 1]!);
    await waitFor(() => expect(api.updateAgreement).toHaveBeenCalledWith('ag-1', { contract_id: 'ct-9' }));
    expect(api.dismissUnlinkedTwin).not.toHaveBeenCalled();
  });

  it('dismisses the pair as two subcontracts', async () => {
    renderBanner({ projectId: 'prj-1' });
    fireEvent.click(await screen.findByRole('button', { name: /subcontractors\.twin\.different/ }));
    await waitFor(() => expect(api.dismissUnlinkedTwin).toHaveBeenCalledWith('ag-1', 'ct-9'));
    expect(api.updateAgreement).not.toHaveBeenCalled();
  });

  it('shows both values when they are far apart', async () => {
    vi.mocked(api.listUnlinkedTwins).mockResolvedValue([
      { ...PAIR, contract_value: '80000.00', value_close: false },
    ]);
    renderBanner({ projectId: 'prj-1' });
    expect(await screen.findByText(/subcontractors\.twin\.values_differ/)).toBeInTheDocument();
  });
});
