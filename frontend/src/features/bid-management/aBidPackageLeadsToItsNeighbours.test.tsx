// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A bid package sits between a tender package and the contract its award
// drafts. The register could not be opened on one package from elsewhere, the
// drawer did not link back to the tender package whose id it holds, and
// "Formalise as Contract" opened the bare contracts register even after the
// award had drafted the contract. What is pinned: ?highlight=<id> opens that
// package's drawer, closing the drawer drops the param, and the drawer's links
// land on the tender package and on the records the award stamped.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';

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
    apiDelete: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'proj-1' }));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn() }),
}));

vi.mock('@/stores/useToastStore', () => {
  const state = { addToast: vi.fn(), toasts: [], removeToast: vi.fn() };
  return {
    useToastStore: Object.assign(
      (selector?: (s: typeof state) => unknown) => (selector ? selector(state) : state),
      { getState: () => state },
    ),
  };
});

import { BidManagementPage } from './BidManagementPage';

function bidPackage(overrides: Record<string, unknown> = {}) {
  return {
    id: 'bp-1',
    project_id: 'proj-1',
    tender_id: 'tp-1',
    code: 'BP-001',
    title: 'Groundworks',
    scope_description: 'Excavation and blinding',
    instructions_to_bidders: '',
    submission_deadline: null,
    decision_due_by: null,
    currency: 'EUR',
    total_budget_estimate: '120000',
    status: 'open',
    confidentiality_level: 'standard',
    published_at: null,
    closed_at: null,
    awarded_at: null,
    created_by: null,
    metadata: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

interface World {
  pkg: ReturnType<typeof bidPackage>;
  contracts?: unknown[];
  orders?: unknown[];
}

function setWorld(world: World): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/v1/bid-management/bid-packages/?')) return Promise.resolve([world.pkg]);
    if (url === `/v1/bid-management/bid-packages/${world.pkg.id}`) return Promise.resolve(world.pkg);
    if (url.startsWith('/v1/contracts/contracts/')) {
      const items = world.contracts ?? [];
      return Promise.resolve({ items, total: items.length, offset: 0, limit: 200 });
    }
    if (url.startsWith('/v1/procurement/')) {
      const items = world.orders ?? [];
      return Promise.resolve({ items, total: items.length, offset: 0, limit: 100 });
    }
    return Promise.resolve([]);
  });
}

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname + loc.search}</div>;
}

function renderPage(entry = '/bid-management?highlight=bp-1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <BidManagementPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function drawer() {
  return within(await screen.findByRole('dialog'));
}

beforeEach(() => {
  apiGetMock.mockReset();
});

afterEach(() => cleanup());

describe('the bid-management register opens on one package', () => {
  it('opens the drawer of the package the link names', async () => {
    setWorld({ pkg: bidPackage() });
    renderPage();

    const d = await drawer();
    expect(await d.findByText('Groundworks')).toBeTruthy();
  });

  it('drops the param when the drawer is closed', async () => {
    setWorld({ pkg: bidPackage() });
    renderPage();

    const d = await drawer();
    await d.findByText('Groundworks');
    fireEvent.click(d.getByRole('button', { name: 'Close' }));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/bid-management'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens no drawer without the param', async () => {
    setWorld({ pkg: bidPackage() });
    renderPage('/bid-management');

    await screen.findAllByText('BP-001');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('the drawer links to its neighbours', () => {
  it('links back to the tender package it belongs to', async () => {
    setWorld({ pkg: bidPackage() });
    renderPage();

    const strip = within(await (await drawer()).findByTestId('bid-package-related'));
    expect(strip.getByRole('link', { name: /Tender package/ }).getAttribute('href')).toBe('/tendering?package=tp-1');
  });

  it('draws no tender pill for a package raised on its own', async () => {
    setWorld({ pkg: bidPackage({ tender_id: null }) });
    renderPage();

    const d = await drawer();
    await d.findByText('Groundworks');
    expect(d.queryByRole('link', { name: /Tender package/ })).toBeNull();
  });

  it('names the contract and the order an award drafted', async () => {
    setWorld({
      pkg: bidPackage({ status: 'awarded', tender_id: null }),
      contracts: [
        { id: 'ct-x', code: 'OTHER', status: 'draft', metadata: { bid_package_id: 'bp-other' } },
        { id: 'ct-1', code: 'CONTRACT-BID-001', status: 'draft', metadata: { bid_package_id: 'bp-1' } },
      ],
      orders: [{ id: 'po-1', po_number: 'PO-0007', status: 'draft', metadata: { bid_package_id: 'bp-1' } }],
    });
    renderPage();

    const d = await drawer();
    const strip = within(await d.findByTestId('bid-package-related'));
    expect((await strip.findByRole('link', { name: /Contract CONTRACT-BID-001/ })).getAttribute('href')).toBe(
      '/contracts?highlight=ct-1',
    );
    expect((await strip.findByRole('link', { name: /Purchase order PO-0007/ })).getAttribute('href')).toBe(
      '/procurement',
    );
    // The primary action opens the drafted contract, not the register.
    const primary = await d.findByRole('button', { name: /Open contract CONTRACT-BID-001/ });
    expect(primary.closest('a')?.getAttribute('href')).toBe('/contracts?highlight=ct-1');
    expect(strip.queryByText(/OTHER/)).toBeNull();
  });

  it('keeps the register link while no contract carries the stamp', async () => {
    setWorld({ pkg: bidPackage({ status: 'awarded' }), contracts: [] });
    renderPage();

    const d = await drawer();
    const primary = await d.findByRole('button', { name: /Formalise as Contract/ });
    expect(primary.closest('a')?.getAttribute('href')).toBe('/contracts');
  });
});
