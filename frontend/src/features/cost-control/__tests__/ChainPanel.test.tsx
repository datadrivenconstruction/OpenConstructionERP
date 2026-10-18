// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ApiError } from '@/shared/lib/api';

vi.mock('@/shared/lib/permissionGates', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/permissionGates')>();
  return { ...actual, useHasPermission: () => true };
});

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    costControlApi: {
      chain: vi.fn(),
      assign: vi.fn(),
      inheritAll: vi.fn(),
      directCost: vi.fn(),
      setVector: vi.fn(),
    },
  };
});

vi.mock('@/features/costmodel/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/costmodel/api')>();
  return { ...actual, costModelApi: { ...actual.costModelApi, getSpineLines: vi.fn() } };
});

import { costControlApi, type ChainReport } from '../api';
import { costModelApi } from '@/features/costmodel/api';
import { ChainPanel } from '../ChainPanel';

const REPORT: ChainReport = {
  project_id: 'p-1',
  currency: 'EUR',
  buckets: [
    {
      kind: 'contract_line',
      count: 2,
      amount: '700.00',
      inheritable: 1,
      in_report: true,
      items: [
        {
          kind: 'contract_line',
          id: 'cl-1',
          group_id: 'k-1',
          group_code: 'SC-01',
          group_title: 'Shell works',
          code: '010',
          description: 'Walls',
          amount: '500.00',
          can_inherit: true,
        },
        {
          kind: 'contract_line',
          id: 'cl-2',
          group_id: 'k-1',
          group_code: 'SC-01',
          group_title: 'Shell works',
          code: '020',
          description: 'Site cleaning',
          amount: '200.00',
          can_inherit: false,
        },
      ],
    },
    { kind: 'invoice_line', count: 0, amount: '0', inheritable: 0, in_report: false, items: [] },
  ],
  findings: [
    {
      rule_id: 'cost_chain.invoice_has_contract',
      severity: 'error',
      message: 'Supplier invoice SUP-7 for 120.00 EUR belongs to no contract or order.',
      suggestion: 'Link its lines to a contract, or record it as a direct cost on one account.',
      element_ref: 'inv-7',
      details: { problem: 'invoice_without_contract' },
    },
  ],
};

const LINES = [
  { id: 'line-a', code: '331', description: 'External walls', status: 'active' },
  { id: 'line-b', code: '361', description: 'Roofs', status: 'active' },
];

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChainPanel projectId="p-1" currency="EUR" canEdit />
    </QueryClientProvider>,
  );
}

async function pick(testId: string, label: RegExp) {
  fireEvent.click(await screen.findByTestId(testId));
  fireEvent.click(await screen.findByRole('option', { name: label }));
}

beforeEach(() => {
  vi.clearAllMocks();
  if (!('scrollIntoView' in HTMLElement.prototype)) {
    // @ts-expect-error jsdom has no scrollIntoView
    HTMLElement.prototype.scrollIntoView = () => {};
  } else {
    vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {});
  }
  vi.mocked(costControlApi.chain).mockResolvedValue(REPORT);
  vi.mocked(costModelApi.getSpineLines).mockResolvedValue(LINES as never);
});

describe('ChainPanel', () => {
  it('lists the buckets with money and the checks in the words the server sent', async () => {
    renderPanel();
    expect(await screen.findByTestId('suspense-contract_line')).toBeInTheDocument();
    expect(screen.queryByTestId('suspense-invoice_line')).not.toBeInTheDocument();
    expect(screen.getByText(/SUP-7 for 120.00 EUR/)).toBeInTheDocument();
    expect(screen.getByText(/record it as a direct cost/)).toBeInTheDocument();
  });

  it('takes every inheritable account over in one step', async () => {
    vi.mocked(costControlApi.inheritAll).mockResolvedValue({ contract_line: 1, change_order_item: 0, invoice_line: 0 });
    renderPanel();
    fireEvent.click(await screen.findByTestId('chain-inherit-all'));
    await waitFor(() => expect(costControlApi.inheritAll).toHaveBeenCalledWith('p-1'));
  });

  it('puts a row on a cost line, and asks why when it inherits another one', async () => {
    vi.mocked(costControlApi.assign)
      .mockRejectedValueOnce(
        new ApiError(422, 'Unprocessable', {
          detail: { problem: 'override_reason_required', message: 'x' },
        }),
      )
      .mockResolvedValueOnce({ assigned: 1 });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /contract lines/i }));
    await pick('suspense-put-cl-1', /361 Roofs/);
    await waitFor(() =>
      expect(costControlApi.assign).toHaveBeenCalledWith('p-1', {
        cost_line_id: 'line-b',
        items: [{ kind: 'contract_line', id: 'cl-1' }],
      }),
    );
    fireEvent.change(await screen.findByTestId('override-reason-input'), {
      target: { value: 'Roof works carry the parapet walls' },
    });
    fireEvent.click(screen.getByTestId('override-reason-confirm'));
    await waitFor(() =>
      expect(costControlApi.assign).toHaveBeenLastCalledWith('p-1', {
        cost_line_id: 'line-b',
        items: [{ kind: 'contract_line', id: 'cl-1' }],
        reason: 'Roof works carry the parapet walls',
      }),
    );
  });

  it('records a supplier invoice without a contract as a direct cost', async () => {
    vi.mocked(costControlApi.directCost).mockResolvedValue({
      contract_id: 'k-9',
      contract_code: 'DC-SUP-7',
      contract_line_id: 'kl-9',
    });
    renderPanel();
    await pick('direct-cost-inv-7', /331 External walls/);
    await waitFor(() => expect(costControlApi.directCost).toHaveBeenCalledWith('p-1', 'inv-7', 'line-a'));
  });

  it('says so when nothing is left', async () => {
    vi.mocked(costControlApi.chain).mockResolvedValue({ ...REPORT, buckets: [], findings: [] });
    renderPanel();
    expect(await screen.findByText(/chain checks pass/i)).toBeInTheDocument();
  });
});
