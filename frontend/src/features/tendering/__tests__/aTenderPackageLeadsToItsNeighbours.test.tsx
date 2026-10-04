// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A tender package is one step of a chain: it was raised from a bill, a
// bid-management package may run its invitations and leveling, and an award
// drafts a contract and a purchase order. The package screen knew the bill id
// and sent "Formalise as Contract" to the bare contracts register even after
// the award had drafted the contract. What is pinned here is where each link
// on an opened package lands, and that the award links name the record the
// award stamped, and nothing when no record carries the stamp.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateSpy };
});

vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
      opts[name] === undefined ? `{{${name}}}` : String(opts[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

const apiGetMock = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: (url: string, ...rest: unknown[]) => apiGetMock(url, ...rest),
    apiPost: vi.fn(() => Promise.resolve({})),
    apiPatch: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]),
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn() }),
}));

vi.mock('@/stores/useProjectContextStore', () => {
  const state = { activeProjectId: 'proj-1', activeProjectName: 'Riverside' };
  return {
    useProjectContextStore: (selector?: (s: typeof state) => unknown) => (selector ? selector(state) : state),
  };
});

vi.mock('@/stores/useToastStore', () => {
  const state = { addToast: vi.fn(), toasts: [], removeToast: vi.fn() };
  return {
    useToastStore: Object.assign(
      (selector?: (s: typeof state) => unknown) => (selector ? selector(state) : state),
      { getState: () => state },
    ),
  };
});

import { TenderingPage } from '../TenderingPage';

type Status = 'collecting' | 'awarded';

function tenderPackage(status: Status) {
  return {
    id: 'tp-1',
    project_id: 'proj-1',
    boq_id: 'boq-7',
    name: 'Concrete works',
    description: '',
    status,
    deadline: null,
    metadata: {},
    bid_count: 0,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

interface World {
  status: Status;
  bidPackages?: unknown[];
  contracts?: unknown[];
  contractsTotal?: number;
  orders?: unknown[];
}

function setWorld(world: World): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/v1/boq/boqs/')) return Promise.resolve([]);
    if (url.startsWith('/v1/tendering/packages/?')) return Promise.resolve([tenderPackage(world.status)]);
    if (url === '/v1/tendering/packages/tp-1') return Promise.resolve({ ...tenderPackage(world.status), bids: [] });
    if (url.startsWith('/v1/tendering/packages/tp-1/scope')) {
      return Promise.resolve({
        package_id: 'tp-1',
        boq_id: 'boq-7',
        boq_name: 'Main bill',
        covers_whole_bill: true,
        sections_recorded: true,
        included_position_count: 3,
        boq_position_count: 3,
        sections: [],
      });
    }
    if (url.startsWith('/v1/tendering/packages/tp-1/comparison')) {
      return Promise.resolve({
        package_id: 'tp-1',
        package_name: 'Concrete works',
        bid_count: 0,
        bid_companies: [],
        budget_total: 0,
        rows: [],
        bid_totals: [],
      });
    }
    if (url.startsWith('/v1/bid-management/bid-packages/')) return Promise.resolve(world.bidPackages ?? []);
    if (url.startsWith('/v1/contracts/contracts/')) {
      const items = world.contracts ?? [];
      return Promise.resolve({ items, total: world.contractsTotal ?? items.length, offset: 0, limit: 200 });
    }
    if (url.startsWith('/v1/procurement/')) {
      const items = world.orders ?? [];
      return Promise.resolve({ items, total: items.length, offset: 0, limit: 100 });
    }
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/tendering?package=tp-1']}>
        <TenderingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function related() {
  return within(await screen.findByTestId('tender-related'));
}

const DRAFTED_CONTRACT = {
  id: 'ct-9',
  code: 'CONTRACT-TND-AB12',
  status: 'draft',
  metadata: { source: 'tendering.package.awarded', tender_package_id: 'tp-1' },
};
const DRAFTED_ORDER = { id: 'po-3', po_number: 'PO-0042', status: 'draft', metadata: { tender_package_id: 'tp-1' } };

beforeEach(() => {
  navigateSpy.mockClear();
  apiGetMock.mockReset();
});

afterEach(() => cleanup());

describe('an open tender package links to its neighbours', () => {
  it('links to the bill it was raised from, by name', async () => {
    setWorld({ status: 'collecting' });
    renderPage();

    const strip = await related();
    const link = await strip.findByRole('link', { name: /BOQ: Main bill/ });
    expect(link.getAttribute('href')).toBe('/boq/boq-7');
  });

  it('links to the bid-management package raised for it, and not to an unrelated one', async () => {
    setWorld({
      status: 'collecting',
      bidPackages: [
        { id: 'bp-1', code: 'BP-001', tender_id: 'tp-1' },
        { id: 'bp-2', code: 'BP-002', tender_id: 'tp-other' },
        { id: 'bp-3', code: 'BP-003', tender_id: null },
      ],
    });
    renderPage();

    const strip = await related();
    const link = await strip.findByRole('link', { name: /Bid package BP-001/ });
    expect(link.getAttribute('href')).toBe('/bid-management?highlight=bp-1');
    expect(strip.queryByText(/BP-002/)).toBeNull();
    expect(strip.queryByText(/BP-003/)).toBeNull();
  });

  it('does not look for an award before there is one', async () => {
    setWorld({ status: 'collecting', contracts: [DRAFTED_CONTRACT], orders: [DRAFTED_ORDER] });
    renderPage();

    await related();
    expect(apiGetMock.mock.calls.some(([u]) => String(u).startsWith('/v1/contracts/'))).toBe(false);
    expect(screen.queryByText(/Contract CONTRACT-TND-AB12/)).toBeNull();
  });
});

describe('an awarded tender package links to what the award drafted', () => {
  it('names the contract and the purchase order the award stamped', async () => {
    setWorld({
      status: 'awarded',
      contracts: [{ id: 'ct-hand', code: 'HAND-1', status: 'active', metadata: {} }, DRAFTED_CONTRACT],
      orders: [DRAFTED_ORDER],
    });
    renderPage();

    const strip = await related();
    const contract = await strip.findByRole('link', { name: /Contract CONTRACT-TND-AB12/ });
    expect(contract.getAttribute('href')).toBe('/contracts?highlight=ct-9');
    const order = await strip.findByRole('link', { name: /Purchase order PO-0042/ });
    expect(order.getAttribute('href')).toBe('/procurement');
    expect(strip.queryByText(/HAND-1/)).toBeNull();
  });

  it('opens the drafted contract from the primary button instead of the bare register', async () => {
    setWorld({ status: 'awarded', contracts: [DRAFTED_CONTRACT] });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Open contract CONTRACT-TND-AB12/ }));

    expect(navigateSpy).toHaveBeenCalledWith('/contracts?highlight=ct-9');
  });

  it('finds the contract through a linked bid package when only that key was stamped', async () => {
    setWorld({
      status: 'awarded',
      bidPackages: [{ id: 'bp-1', code: 'BP-001', tender_id: 'tp-1' }],
      contracts: [{ id: 'ct-bm', code: 'CONTRACT-BM-1', status: 'draft', metadata: { bid_package_id: 'bp-1' } }],
    });
    renderPage();

    const strip = await related();
    const contract = await strip.findByRole('link', { name: /Contract CONTRACT-BM-1/ });
    expect(contract.getAttribute('href')).toBe('/contracts?highlight=ct-bm');
  });

  it('passes over a terminated contract and keeps the plain register button', async () => {
    setWorld({
      status: 'awarded',
      contracts: [{ ...DRAFTED_CONTRACT, status: 'terminated' }],
    });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Formalise as Contract/ }));

    expect(navigateSpy).toHaveBeenCalledWith('/contracts');
    expect(screen.queryByText(/Contract CONTRACT-TND-AB12/)).toBeNull();
  });
});
