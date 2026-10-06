// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Settings entry a desktop admin has in place of the update-reference-data
// command: look first, then apply after confirming, and only the entries the
// preview showed as ready.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

import {
  ReferenceDataPanel,
  REFERENCE_DATA_APPLY_URL,
  REFERENCE_DATA_PREVIEW_URL,
  groupByStatus,
  type ReferenceChange,
  type ReferenceDataPreview,
} from '../ReferenceDataPanel';

const change = (key: string, status: ReferenceChange['status'], reason: string, label: string): ReferenceChange => ({
  key,
  kind: key.startsWith('country:') ? 'country' : 'tax',
  action: status === 'ready' ? 'add' : 'none',
  status,
  reason,
  label,
  detail: '',
  rows_added: status === 'ready' ? 1 : 0,
  fields: status === 'ready' ? [{ field: 'rate_pct', before: null, after: '9.0' }] : [],
});

const preview: ReferenceDataPreview = {
  ready: 2,
  kept: 1,
  review: 1,
  changes: [
    change('tax:IE/VAT_RED_9', 'ready', 'new', 'IE VAT_RED_9 VAT Second Reduced'),
    change('tax:HU/AFA_5', 'ready', 'new', 'HU AFA_5 VAT Reduced 5%'),
    change('tax:AT/VAT', 'review', 'rate_differs', 'AT VAT VAT Standard'),
    change('tax:DE/VAT#edited', 'kept', 'edited_locally', 'DE VAT Our label'),
  ],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReferenceDataPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});
afterEach(cleanup);

describe('ReferenceDataPanel', () => {
  it('orders the groups ready, review, kept and drops empty ones', () => {
    expect(groupByStatus(preview.changes).map(([status]) => status)).toEqual(['ready', 'review', 'kept']);
    expect(groupByStatus([preview.changes[0]!]).map(([status]) => status)).toEqual(['ready']);
  });

  it('writes nothing until the admin has looked and confirmed, then only the ready keys', async () => {
    apiGet.mockResolvedValue(preview);
    apiPost.mockResolvedValue({
      applied: ['tax:IE/VAT_RED_9', 'tax:HU/AFA_5'],
      skipped: [],
      rows_added: 2,
      rows_updated: 0,
      preview: { ready: 0, kept: 1, review: 1, changes: preview.changes.slice(2) },
    });
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));
    await waitFor(() => expect(screen.getByTestId('reference-data-preview')).toBeInTheDocument());
    expect(apiGet).toHaveBeenCalledWith(REFERENCE_DATA_PREVIEW_URL);
    expect(screen.getByText('IE VAT_RED_9 VAT Second Reduced')).toBeInTheDocument();
    expect(screen.getByTestId('reference-data-review')).toHaveTextContent('AT VAT VAT Standard');
    expect(screen.getByTestId('reference-data-kept')).toHaveTextContent('DE VAT Our label');
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^apply updates$/i }));
    expect(apiPost).not.toHaveBeenCalled();
    const buttons = await screen.findAllByRole('button', { name: /^apply updates$/i });
    fireEvent.click(buttons[buttons.length - 1]!);

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost).toHaveBeenCalledWith(REFERENCE_DATA_APPLY_URL, { keys: ['tax:IE/VAT_RED_9', 'tax:HU/AFA_5'] });
    await waitFor(() => expect(screen.queryByTestId('reference-data-ready')).toBeNull());
  });

  it('offers no Apply button when nothing is ready', async () => {
    apiGet.mockResolvedValue({ ready: 0, kept: 0, review: 0, changes: [] });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));
    await waitFor(() => expect(screen.getByTestId('reference-data-preview')).toBeInTheDocument());
    expect(screen.getByText(/already matches this release/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^apply updates$/i })).toBeNull();
  });
});
