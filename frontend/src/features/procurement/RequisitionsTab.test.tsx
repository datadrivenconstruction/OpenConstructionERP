// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The approval and ordering controls of the requisitions tab (issue #516).
//
// A rejection without a reason is refused at the control, the same rule the
// server enforces, so the reject button stays disabled until one is typed. The
// conversion sends exactly the selected requisitions with the vendor they
// agree on, and a selection naming two vendors never gets as far as a request.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));

import { apiGet, apiPost } from '@/shared/lib/api';
import { ConvertToPOModal, DecisionModal, canOfferDecision } from './RequisitionsTab';
import { positionLabel } from './POSourceRequisitions';
import type { Requisition } from './requisitionsApi';

const mockGet = vi.mocked(apiGet);
const mockPost = vi.mocked(apiPost);

const V1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const V2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

function req(over: Partial<Requisition> = {}): Requisition {
  return {
    id: over.id ?? 'r1',
    project_id: 'p1',
    req_number: over.req_number ?? 'MR-0001',
    status: 'approved',
    title: null,
    required_date: null,
    notes: null,
    requester_id: null,
    po_id: null,
    vendor_id: V1,
    vendor_name: 'Steel Supply',
    items: [],
    reconciliation: {},
    history: [],
    created_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T00:00:00Z',
    ...over,
  };
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockGet.mockResolvedValue({
    items: [
      { id: V1, code: 'V-1', name: 'Steel Supply', status: 'active' },
      { id: V2, code: 'V-2', name: 'Concrete Works', status: 'active' },
    ],
    total: 2,
    offset: 0,
    limit: 200,
  });
});

describe('DecisionModal', () => {
  it('keeps reject disabled until a reason is given, then passes the reason on', async () => {
    const onConfirm = vi.fn();
    wrap(<DecisionModal mode="reject" busy={false} onClose={() => {}} onConfirm={onConfirm} />);
    const button = screen.getByRole('button', { name: /^reject$/i });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByRole('textbox'), 'Wrong grade of steel');
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(onConfirm).toHaveBeenCalledWith('Wrong grade of steel');
  });

  it('lets an approval go through without a comment', async () => {
    const onConfirm = vi.fn();
    wrap(<DecisionModal mode="approve" busy={false} onClose={() => {}} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }));
    expect(onConfirm).toHaveBeenCalledWith('');
  });
});

describe('ConvertToPOModal', () => {
  it('sends the selected requisitions with the vendor they agree on', async () => {
    mockPost.mockResolvedValue({
      po_id: 'po-1',
      po_number: 'PO-0007',
      project_id: 'p1',
      requisition_ids: ['r1', 'r2'],
      line_count: 2,
      vendor_warnings: [],
    });
    const onConverted = vi.fn();
    wrap(
      <ConvertToPOModal
        projectId="p1"
        open
        onClose={() => {}}
        onConverted={onConverted}
        requisitions={[req(), req({ id: 'r2', req_number: 'MR-0002' })]}
      />,
    );
    const create = screen.getByRole('button', { name: /create draft order/i });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    await waitFor(() => expect(onConverted).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith('/v1/procurement/requisitions/convert-to-po', {
      project_id: 'p1',
      requisition_ids: ['r1', 'r2'],
      vendor_id: V1,
      delivery_date: null,
      lines: undefined,
      idempotency_key: expect.any(String),
    });
  });

  it('orders part of a line when its quantity is lowered, and the rest stays for later', async () => {
    mockPost.mockResolvedValue({
      po_id: 'po-2',
      po_number: 'PO-0008',
      project_id: 'p1',
      requisition_ids: ['r1'],
      line_count: 1,
      vendor_warnings: [],
    });
    const line = (id: string, description: string, toOrder: string) =>
      ({
        id,
        description,
        unit: 'm3',
        quantity_requested: toOrder,
        quantity_ordered: '0',
        quantity_received: '0',
        quantity_consumed: '0',
        quantity_outstanding: toOrder,
        quantity_to_order: toOrder,
        catalog_item_id: null,
        cost_line_id: null,
        sort_order: 0,
        sources: [],
      }) as Requisition['items'][number];
    wrap(
      <ConvertToPOModal
        projectId="p1"
        open
        onClose={() => {}}
        onConverted={() => {}}
        requisitions={[req({ items: [line('i1', 'Concrete', '71.4000'), line('i2', 'Rebar', '3.2500')] })]}
      />,
    );
    const concrete = screen.getByRole('textbox', { name: /concrete/i });
    const rebar = screen.getByRole('textbox', { name: /rebar/i });
    expect(concrete).toHaveValue('71.4000');
    await userEvent.clear(concrete);
    await userEvent.type(concrete, '30');
    await userEvent.clear(rebar);
    const create = screen.getByRole('button', { name: /create draft order/i });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0]![1]).toMatchObject({
      lines: [{ requisition_item_id: 'i1', quantity: '30' }],
    });
  });

  it('does not offer a requisition that is ordered in an external system', () => {
    wrap(
      <ConvertToPOModal
        projectId="p1"
        open
        onClose={() => {}}
        onConverted={() => {}}
        requisitions={[req({ order_owner: 'external' })]}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/external purchasing system/i);
    expect(screen.getByRole('button', { name: /create draft order/i })).toBeDisabled();
  });

  it('never sends a selection that names two vendors', async () => {
    wrap(
      <ConvertToPOModal
        projectId="p1"
        open
        onClose={() => {}}
        onConverted={() => {}}
        requisitions={[req(), req({ id: 'r2', vendor_id: V2, vendor_name: 'Concrete Works' })]}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/different vendors/i);
    expect(screen.getByRole('button', { name: /create draft order/i })).toBeDisabled();
    expect(mockPost).not.toHaveBeenCalled();
  });
});

describe('canOfferDecision', () => {
  const submitted = { status: 'submitted' as const, submitted_by: 'u-1' };

  it('hides the decision from the person who submitted it', () => {
    expect(canOfferDecision(submitted, 'u-1', 'admin')).toBe(false);
    expect(canOfferDecision(submitted, 'u-2', 'admin')).toBe(true);
  });

  it('offers it to managers and above only, and only while submitted', () => {
    expect(canOfferDecision(submitted, 'u-2', 'manager')).toBe(true);
    expect(canOfferDecision(submitted, 'u-2', 'editor')).toBe(false);
    expect(canOfferDecision(submitted, 'u-2', 'estimator')).toBe(false);
    expect(canOfferDecision(submitted, 'u-2', null)).toBe(false);
    expect(canOfferDecision({ ...submitted, status: 'approved' }, 'u-2', 'admin')).toBe(false);
  });

  it('leaves the decision to the next designated approver alone', () => {
    const chained = { ...submitted, next_approver_id: 'u-3' };
    expect(canOfferDecision(chained, 'u-2', 'admin')).toBe(false);
    expect(canOfferDecision(chained, 'u-3', 'manager')).toBe(true);
    expect(canOfferDecision(chained, 'u-3', 'manager', ['procurement.read'])).toBe(false);
  });

  it('follows the real permission once the permission list is known', () => {
    const granted = ['procurement.read', 'procurement.approve_requisition'];
    expect(canOfferDecision(submitted, 'u-2', 'editor', granted)).toBe(true);
    expect(canOfferDecision(submitted, 'u-2', 'manager', ['procurement.read'])).toBe(false);
    expect(canOfferDecision(submitted, 'u-2', 'admin', [])).toBe(true);
    expect(canOfferDecision(submitted, 'u-1', 'editor', granted)).toBe(false);
    expect(canOfferDecision({ ...submitted, status: 'draft' }, 'u-2', 'editor', granted)).toBe(false);
  });
});

describe('positionLabel', () => {
  it('names the position by ordinal and description, falling back to the short id', () => {
    const id = '12345678-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    expect(positionLabel({ boq_position_id: id, position_ordinal: '01.02', position_description: 'Concrete' })).toBe(
      '01.02 Concrete',
    );
    expect(positionLabel({ boq_position_id: id, position_ordinal: null, position_description: null })).toBe('12345678');
    expect(positionLabel({ boq_position_id: null })).toBe('-');
  });
});
