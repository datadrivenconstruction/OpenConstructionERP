// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An RFQ award drafts a purchase order and the RFQ links to it as
// /procurement?po=<id>. The register read no parameter, so every such link
// landed on the bare list. What is pinned: the named order's row is scrolled to
// and marked; an order that is not on the loaded page is fetched by id and
// named above the table rather than silently missing; a link to an order that
// does not exist says so; and an order drafted from an RFQ award links back to
// that RFQ, while one raised by hand carries no such link.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() };
});

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn() }),
}));

import { ProcurementPage } from './ProcurementPage';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const mockGet = vi.mocked(apiGet);
const PROJECT_ID = 'p1';

function po(id: string, poNumber: string, metadata: Record<string, unknown> = {}) {
  return {
    id,
    project_id: PROJECT_ID,
    po_number: poNumber,
    vendor_name: 'Nordstahl GmbH',
    vendor_contact_id: null,
    issue_date: '2026-09-20',
    delivery_date: null,
    amount_total: '25000.00',
    amount_subtotal: '25000.00',
    currency_code: 'EUR',
    status: 'draft',
    description: '',
    line_items_count: 2,
    metadata,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
  };
}

const FROM_RFQ = { origin: 'rfq_award', rfq_id: 'rfq-1', rfq_number: 'RFQ-014' };

function serve(orders: ReturnType<typeof po>[], byId: Record<string, unknown> = {}) {
  mockGet.mockImplementation((path: string) => {
    if (path.includes('/v1/finance/dashboard/')) return Promise.resolve({ currency: 'EUR' });
    if (path.startsWith('/v1/procurement/?')) return Promise.resolve({ items: orders, total: orders.length, offset: 0, limit: 50 });
    const single = /^\/v1\/procurement\/([^/?]+)$/.exec(path);
    if (single) {
      const found = byId[decodeURIComponent(single[1]!)];
      return found ? Promise.resolve(found) : Promise.reject(new Error('Purchase order not found'));
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

const scrolled: Element[] = [];

beforeEach(() => {
  mockGet.mockReset();
  scrolled.length = 0;
  Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
    scrolled.push(this);
  };
  useProjectContextStore.setState({ activeProjectId: PROJECT_ID, activeProjectName: 'Riverside' });
});

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ProcurementPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function row(poNumber: string): HTMLElement {
  return screen.getByText(poNumber).closest('tr') as HTMLElement;
}

describe('?po=<id> opens the register on that order', () => {
  it('scrolls to and marks the named row, and only that one', async () => {
    serve([po('po-1', 'PO-0001'), po('po-2', 'PO-0002', FROM_RFQ)]);
    renderAt('/procurement?po=po-2');

    await screen.findByText('PO-0002');
    const target = row('PO-0002');
    expect(target.getAttribute('data-focused')).toBe('true');
    expect(row('PO-0001').getAttribute('data-focused')).toBeNull();
    await waitFor(() => expect(scrolled).toContain(target));
    expect(screen.queryByTestId('po-focus-notice')).toBeNull();
  });

  it('names an order that is not on the loaded page instead of losing it', async () => {
    serve([po('po-1', 'PO-0001')], { 'po-99': { ...po('po-99', 'PO-0099'), status: 'draft', items: [] } });
    renderAt('/procurement?po=po-99');

    const notice = await screen.findByTestId('po-focus-notice');
    await waitFor(() => expect(notice.textContent).toContain('PO-0099'));
    expect(row('PO-0001').getAttribute('data-focused')).toBeNull();
  });

  it('says so when the linked order does not exist', async () => {
    serve([po('po-1', 'PO-0001')]);
    renderAt('/procurement?po=gone');

    const notice = await screen.findByTestId('po-focus-notice');
    await waitFor(() => expect(notice.textContent).toContain('could not be found'));
  });
});

describe('an order drafted from an RFQ award names its source', () => {
  it('links the drafted order to its RFQ and leaves a hand-made one without a link', async () => {
    serve([po('po-1', 'PO-0001'), po('po-2', 'PO-0002', FROM_RFQ)]);
    renderAt('/procurement');

    await screen.findByText('PO-0002');
    const link = within(row('PO-0002')).getByTestId('po-source-rfq');
    expect(link.getAttribute('href')).toBe('/rfq-bidding?rfq=rfq-1');
    expect(link.textContent).toContain('From RFQ-014');
    expect(within(row('PO-0001')).queryByTestId('po-source-rfq')).toBeNull();
  });
});
