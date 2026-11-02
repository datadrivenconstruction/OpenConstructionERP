// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Finance's tab lives in ?tab=. It used to be read once on mount and then
 * deleted, so /finance?tab=retention opened the Retention tab and at once
 * became /finance: a menu row pointing there lit for one render and a reload
 * fell back to Budgets. These tests pin that the param now stays, that a
 * click writes it back (replacing, keeping the other params), and that a
 * link followed while the page is open switches the tab.
 *
 * The page is rendered with no active project. The tab bar sits above the
 * project gate, so the tab state is fully observable without any tab's data.
 *
 * Run:  npx vitest run src/features/finance/__tests__/tabFromUrl.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate, useNavigationType } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => '',
}));

// A tenant with an e-invoicing market sees every tab the list declares.
vi.mock('@/features/einvoice-clearance/useEInvoiceMarkets', () => ({
  EINVOICE_SETUP_QUERY_KEY: ['einvoice-clearance', 'setup'],
  useEInvoiceMarkets: () => ({ enabled: true, rows: [], isVisibleFor: () => true }),
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), custom: [] }),
}));

import { FinancePage } from '../FinancePage';
import { DEFAULT_FINANCE_TAB, FINANCE_TABS } from '../financeTabs';
import { tabIds } from '@/shared/ui';

/** Prints the live URL and the last history action, and follows a link on demand. */
function Probe({ follow }: { follow?: string }) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  return (
    <>
      <span data-testid="search">{location.search}</span>
      <span data-testid="nav-type">{navigationType}</span>
      {follow && (
        <button type="button" onClick={() => navigate(follow)}>
          follow link
        </button>
      )}
    </>
  );
}

function renderAt(entry: string, follow?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <FinancePage />
        <Probe follow={follow} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const selected = (name: string) =>
  screen.getByRole('tab', { name }).getAttribute('aria-selected');

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiGet.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
});

afterEach(() => cleanup());

describe('the Finance tab in the URL', () => {
  it('opens on the tab the link names and leaves the param in place', async () => {
    renderAt('/finance?tab=retention');

    expect(await screen.findByRole('tab', { name: 'Retention' })).toBeTruthy();
    expect(selected('Retention')).toBe('true');
    expect(selected('Budgets')).toBe('false');
    // The regression: the param used to be deleted on mount.
    expect(screen.getByTestId('search').textContent).toBe('?tab=retention');
  });

  it('falls back to Budgets on a value it does not know', async () => {
    renderAt('/finance?tab=retainage');

    await screen.findByRole('tab', { name: 'Budgets' });
    expect(selected('Budgets')).toBe('true');
  });

  it('opens on Budgets without a tab param, and writes nothing', async () => {
    renderAt('/finance');

    await screen.findByRole('tab', { name: 'Budgets' });
    expect(selected('Budgets')).toBe('true');
    expect(screen.getByTestId('search').textContent).toBe('');
    expect(screen.getByTestId('nav-type').textContent).toBe('POP');
  });

  it('writes a tab click back to the URL, replacing, and keeps the other params', async () => {
    renderAt('/finance?buyer=b-1&tab=retention');

    fireEvent.click(await screen.findByRole('tab', { name: 'Payments' }));

    expect(selected('Payments')).toBe('true');
    const params = new URLSearchParams(screen.getByTestId('search').textContent ?? '');
    expect(params.get('tab')).toBe('payments');
    expect(params.get('buyer')).toBe('b-1');
    expect(screen.getByTestId('nav-type').textContent).toBe('REPLACE');
  });

  it('renders exactly the tabs financeTabs.ts lists, so a link checked against it is real', async () => {
    renderAt('/finance');

    const tablist = await screen.findByRole('tablist', { name: 'Finance sections' });
    const rendered = within(tablist).getAllByRole('tab').map((tab) => tab.id);
    expect(rendered).toEqual(FINANCE_TABS.map((id) => tabIds('finance').tabId(id)));
    expect(FINANCE_TABS).toContain(DEFAULT_FINANCE_TAB);
  });

  it('switches tab when a link is followed while the page is open', async () => {
    renderAt('/finance?tab=invoices', '/finance?tab=retention');

    await screen.findByRole('tab', { name: 'Invoices' });
    expect(selected('Invoices')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'follow link' }));

    expect(selected('Retention')).toBe('true');
    expect(selected('Invoices')).toBe('false');
  });
});
