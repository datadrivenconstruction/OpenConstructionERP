// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/cost-control/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/cost-control/api')>();
  return { ...actual, costControlApi: { ...actual.costControlApi, setVector: vi.fn() } };
});

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, costModelApi: { ...actual.costModelApi, getSpineLines: vi.fn() } };
});

import { costControlApi } from '@/features/cost-control/api';
import { costModelApi } from './api';
import { AccountChooser, overrideReason } from './AccountChooser';

const LINES = [
  { id: 'line-a', code: '331', description: 'External walls', status: 'active' },
  { id: 'line-b', code: '361', description: 'Roofs', status: 'active' },
];

function renderChooser(props: Partial<Parameters<typeof AccountChooser>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountChooser
        projectId="p-1"
        kind="change_order_item"
        targetId="it-1"
        costLineId="line-a"
        source="contract_line"
        canEdit
        {...props}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  if (!('scrollIntoView' in HTMLElement.prototype)) {
    // @ts-expect-error jsdom has no scrollIntoView
    HTMLElement.prototype.scrollIntoView = () => {};
  } else {
    vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {});
  }
  vi.mocked(costModelApi.getSpineLines).mockResolvedValue(LINES as never);
  vi.mocked(costControlApi.setVector).mockResolvedValue({ cost_line_id: 'line-b', source: 'manual', override: true });
});

describe('AccountChooser', () => {
  it('names the cost line and where it came from', async () => {
    renderChooser();
    expect(await screen.findByText('331 External walls')).toBeInTheDocument();
    expect(screen.getByText(/from the contract line/)).toBeInTheDocument();
  });

  it('shows a row on no cost line as such and offers no change without the right', async () => {
    renderChooser({ costLineId: null, canEdit: false });
    expect(await screen.findByText('No cost line')).toBeInTheDocument();
    expect(screen.queryByTestId('account-change-it-1')).not.toBeInTheDocument();
  });

  it('sets another line, and the empty choice takes the inherited one back', async () => {
    renderChooser();
    fireEvent.click(await screen.findByTestId('account-change-it-1'));
    fireEvent.click(await screen.findByTestId('account-picker-it-1'));
    fireEvent.click(await screen.findByRole('option', { name: /361 Roofs/ }));
    await waitFor(() =>
      expect(costControlApi.setVector).toHaveBeenCalledWith('p-1', {
        kind: 'change_order_item',
        id: 'it-1',
        mode: 'set',
        cost_line_id: 'line-b',
      }),
    );
  });

  it('reads the reason of a standing override', () => {
    expect(overrideReason({ cost_line_override: { reason: 'Carried as contingency' } })).toBe('Carried as contingency');
    expect(overrideReason({})).toBe('');
    expect(overrideReason(null)).toBe('');
  });
});
