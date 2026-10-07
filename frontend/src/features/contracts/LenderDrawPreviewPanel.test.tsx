// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LenderDrawPreviewPanel } from './LenderDrawPreviewPanel';
import { loadLenderPreparation } from './lenderDrawSources';
import type { LenderPreparation } from './lenderDrawPreview';
import type { ClaimSubRollup } from '@/features/subcontractors/api';
import { claimKey } from './claimQueries';

vi.mock('./lenderDrawSources', () => ({ loadLenderPreparation: vi.fn() }));
const load = vi.mocked(loadLenderPreparation);
const context = { projectId: 'project-1', contractId: 'contract-1', claimId: 'claim-1' };

function draft(claimId = 'claim-1'): LenderPreparation {
  return {
    kind: 'draft_lender_preparation', read_at: '2026-10-07T12:00:00Z',
    application: {
      claim_id: claimId, contract_id: 'contract-1', project_id: 'project-1',
      application_number: claimId, currency: 'KWD', claim_status: 'draft', retainage_percent: '5',
      period_start: '2026-02-01', period_end: '2026-02-28',
      summary: {
        original_contract_sum: '100.001', change_orders_net: '-2.123', contract_sum_to_date: '97.878',
        total_completed_stored: '50.000', retainage: '2.500', total_earned_less_retainage: '47.500',
        previous_certificates_total: '7.123', previous_certificates_basis: 'reconstructed',
        current_payment_due: '40.377', balance_to_finish: '50.378',
      }, lines: [], certification: {},
    },
    subcontractors: { status: 'unavailable' }, contract_documents: { status: 'available', data: [] },
    claim_waivers: { status: 'unavailable' },
    not_included: ['loan_facility', 'lender_approval', 'stored_material_evidence', 'contract_change_order_log'],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 120000 } } });
  const view = render(<QueryClientProvider client={client}><LenderDrawPreviewPanel {...context} /></QueryClientProvider>);
  return { client, ...view };
}

describe('lender preparation is a read-only draft', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('reads only when opened, preserves precise amounts, and labels unavailable sources', async () => {
    load.mockResolvedValue(draft());
    setup();
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    expect(await screen.findByText('KWD 40.377')).toBeInTheDocument();
    expect(screen.getByText('KWD 7.123')).toBeInTheDocument();
    expect(screen.getByText('Status: draft')).toBeInTheDocument();
    expect(screen.getByText('Recorded certified amount').nextElementSibling).toHaveTextContent('Not set');
    expect(screen.getByText(/0 recorded; not independently verified/)).toBeInTheDocument();
    expect(screen.getByText(/2026-02-01.*2026-02-28/)).toBeInTheDocument();
    expect(screen.getAllByText(/Unavailable; omitted/)).toHaveLength(2);
    expect(screen.getByText(/Previous certified amounts are rebuilt/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download draft JSON' })).toBeEnabled();
  });

  it('does not show a late previous-claim response after navigation', async () => {
    const first = deferred<LenderPreparation>();
    load.mockReturnValueOnce(first.promise).mockResolvedValueOnce(draft('claim-2'));
    const { client, rerender } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    expect(screen.getByRole('button', { name: 'Download draft JSON' })).toBeDisabled();
    rerender(<QueryClientProvider client={client}><LenderDrawPreviewPanel {...context} claimId="claim-2" /></QueryClientProvider>);
    await act(async () => { first.resolve(draft()); });
    expect(screen.queryByRole('button', { name: 'Download draft JSON' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    expect(await screen.findByText(/claim-2: 2026-02-01/)).toBeInTheDocument();
    expect(screen.queryByText(/claim-1: 2026-02-01/)).not.toBeInTheDocument();
  });

  it('shows the recorded certified amount separately and surfaces skipped currency and period limits', async () => {
    const snapshot = draft();
    snapshot.application.claim_status = 'certified';
    snapshot.application.certification.certified_amount = '38.000';
    snapshot.subcontractors = { status: 'available', data: {
      included: [], skipped_foreign_currency: 2, period_matching: 'explicit_only',
    } as unknown as ClaimSubRollup };
    load.mockResolvedValue(snapshot);
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    expect(await screen.findByText('KWD 38.000')).toBeInTheDocument();
    expect(screen.getByText('KWD 40.377')).toBeInTheDocument();
    expect(screen.getByText('Status: certified')).toBeInTheDocument();
    expect(screen.getByText(/2 pay application line/)).toBeInTheDocument();
    expect(screen.getByText(/Subcontractor payment applications are not matched by date/)).toBeInTheDocument();
  });

  it('downloads the marked draft with unchanged canonical amounts and no mutation request', async () => {
    const snapshot = draft();
    load.mockResolvedValue(snapshot);
    const createObjectURL = vi.fn((_blob: Blob | MediaSource) => 'blob:draft');
    const revokeObjectURL = vi.fn();
    // Preserve the URL constructor for the rest of the UI while stubbing blob URLs.
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    await screen.findByText('KWD 40.377');
    fireEvent.click(screen.getByRole('button', { name: 'Download draft JSON' }));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0]![0] as Blob;
    const content = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(JSON.parse(content)).toEqual(snapshot);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:draft');
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('blocks export while refreshing and after a failed refresh even with cached data', async () => {
    const pending = deferred<LenderPreparation>();
    load.mockResolvedValueOnce(draft()).mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error('403'));
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    await screen.findByText('KWD 40.377');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(screen.getByRole('button', { name: 'Download draft JSON' })).toBeDisabled();
    await act(async () => { pending.resolve(draft()); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Download draft JSON' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
    expect(screen.getByRole('button', { name: 'Download draft JSON' })).toBeDisabled();
    expect(screen.queryByText('KWD 40.377')).not.toBeInTheDocument();
  });

  it.each(['refresh', 'replacement'] as const)(
    'blocks a stale click before an external cache %s reaches React', async (change) => {
      const pending = deferred<LenderPreparation>();
      load.mockResolvedValueOnce(draft()).mockReturnValueOnce(pending.promise);
      const createObjectURL = vi.fn(() => 'blob:stale-draft');
      vi.stubGlobal('URL', class extends URL {
        static createObjectURL = createObjectURL;
        static revokeObjectURL = vi.fn();
      });
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
      const { client } = setup();
      fireEvent.click(screen.getByRole('button', { name: 'View' }));
      await screen.findByText('KWD 40.377');
      const button = screen.getByRole('button', { name: 'Download draft JSON' });
      act(() => {
        if (change === 'refresh') {
          void client.invalidateQueries({ queryKey: claimKey(context.claimId) });
        } else {
          client.setQueryData(
            [...claimKey(context.claimId), 'lender-preparation', context.contractId, context.projectId],
            { ...draft(), read_at: '2026-10-07T13:00:00Z' },
          );
        }
        // Dispatch before leaving this batch: the button still has its old
        // render's callback, while the query cache has already changed.
        button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      });
      expect(createObjectURL).not.toHaveBeenCalled();
      if (change === 'refresh') {
        await act(async () => { pending.resolve(draft()); });
      }
    },
  );
});
