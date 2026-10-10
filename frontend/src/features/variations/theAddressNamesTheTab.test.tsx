// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The open tab of the variations workspace lives in the address, in both
// directions. It used to be read from ?tab= once, at mount, and kept in state
// after that. A sidebar row for the extension of time claims
// (/variations?tab=eot) then did nothing when it was clicked with the page
// already open: the address changed and the page did not hear it. The same
// held for the browser's back button, and a tab clicked by hand left an
// address that still named the tab the reader had come in on.
//
// Also covered here: the three registers the page exports, because which one
// the button leads with follows the tab.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate, type NavigateFunction } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  downloadWithAuth: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

const project = vi.hoisted(() => ({ id: 'p-1' as string | null }));
vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => project.id,
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), setOpen: vi.fn(), custom: [] }),
}));

import { DetailDrawer, VariationsPage } from './VariationsPage';
import type { VariationRequest } from './api';
import { DEFAULT_VARIATIONS_TAB, VARIATIONS_EOT_TAB, VARIATIONS_TABS, isVariationsTab } from './variationsTabs';
import { useToastStore } from '@/stores/useToastStore';

const PROJECT = { id: 'p-1', name: 'İstanbul Veri Merkezi', currency: 'TRY' };

const REQUEST: VariationRequest = {
  id: 'vr-1',
  project_id: 'p-1',
  notice_id: null,
  code: 'VR-001',
  title: 'Additional chilled water branch to level 3',
  description: '',
  requested_by: null,
  requested_at: null,
  classification: 'scope_change',
  urgency: 'med',
  estimated_cost_impact: '9000.00',
  estimated_schedule_days: 0,
  currency: 'TRY',
  status: 'draft',
  submitted_at: null,
  decision_at: null,
  decision_notes: '',
  decided_by: null,
  submitted_boq_id: null,
  submitted_boq_total: null,
  submitted_boq_snapshot_id: null,
  agreed_cost_impact: null,
  agreed_basis: '',
  agreed_variance_note: '',
  metadata: {},
  created_at: '2026-08-19T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
};

function routeGet(projects: unknown[] = [PROJECT]): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve(projects);
    if (path.startsWith('/v1/variations/dashboard/')) return Promise.reject(new Error('no dashboard'));
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    return Promise.resolve([]);
  });
}

/** The router as the page sees it, for a test to read and to drive. */
const router: { navigate: NavigateFunction | null; search: string } = { navigate: null, search: '' };

function RouterProbe() {
  router.navigate = useNavigate();
  router.search = useLocation().search;
  return null;
}

function renderAt(address: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[address]}>
        <RouterProbe />
        <VariationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function openTab(): string {
  return screen.getByRole('tab', { selected: true }).id.replace('variations-tab-', '');
}

function go(to: string | number): void {
  act(() => {
    if (typeof to === 'number') router.navigate!(to);
    else router.navigate!(to);
  });
}

function downloadedUrls(): string[] {
  return api.downloadWithAuth.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  project.id = 'p-1';
  api.downloadWithAuth.mockResolvedValue(undefined);
  useToastStore.setState({ toasts: [] });
  routeGet();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('the tab ids', () => {
  it('are one typed list with the default and the extension of time tab in it', () => {
    expect(VARIATIONS_TABS).toEqual(['notices', 'requests', 'orders', 'daywork', 'eot']);
    expect(VARIATIONS_TABS).toContain(DEFAULT_VARIATIONS_TAB);
    expect(VARIATIONS_TABS).toContain(VARIATIONS_EOT_TAB);
    expect(isVariationsTab('eot')).toBe(true);
    expect(isVariationsTab('claims')).toBe(false);
    expect(isVariationsTab(null)).toBe(false);
  });
});

describe('the tab the variations workspace shows', () => {
  it('is the one the address names', () => {
    renderAt('/variations?tab=eot');
    expect(openTab()).toBe('eot');
  });

  it('is the default when the address names none, or one the page does not have', () => {
    renderAt('/variations');
    expect(openTab()).toBe('notices');
    cleanup();
    renderAt('/variations?tab=no-such-tab');
    expect(openTab()).toBe('notices');
  });

  it('follows the address when it changes with the page already open', () => {
    renderAt('/variations');
    expect(openTab()).toBe('notices');
    // What a sidebar row does: same page, another ?tab=.
    go('/variations?tab=eot');
    expect(openTab()).toBe('eot');
    go('/variations');
    expect(openTab()).toBe('notices');
  });

  it('is written to the address when a tab is clicked', () => {
    renderAt('/variations');
    fireEvent.click(screen.getByRole('tab', { name: /Orders/ }));
    expect(openTab()).toBe('orders');
    expect(new URLSearchParams(router.search).get('tab')).toBe('orders');
  });

  it('goes back with the browser, one tab at a time', () => {
    renderAt('/variations?tab=requests');
    fireEvent.click(screen.getByRole('tab', { name: /EoT Claims/ }));
    expect(openTab()).toBe('eot');
    go(-1);
    expect(openTab()).toBe('requests');
    expect(new URLSearchParams(router.search).get('tab')).toBe('requests');
  });

  it('drops the record a link highlighted when the reader moves to another tab', () => {
    renderAt('/variations?tab=orders&highlight=vo-1');
    fireEvent.click(screen.getByRole('tab', { name: /Daywork/ }));
    const params = new URLSearchParams(router.search);
    expect(params.get('tab')).toBe('daywork');
    expect(params.get('highlight')).toBeNull();
  });

  it('leaves the search behind on the tab it was typed on', () => {
    renderAt('/variations');
    const search = screen.getByRole('textbox') as HTMLInputElement;
    fireEvent.change(search, { target: { value: 'piling' } });
    expect(search.value).toBe('piling');
    go('/variations?tab=eot');
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('');
  });
});

describe('exporting the variation registers', () => {
  it('leads with the register the open tab is a view of', async () => {
    renderAt('/variations');
    const button = screen.getByTestId('variations-export') as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(button.getAttribute('title')).toBe('Notice register: PDF document, English');
    fireEvent.click(button);
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));

    go('/variations?tab=eot');
    expect(screen.getByTestId('variations-export').getAttribute('title')).toBe(
      'Claims register (disruption and extension of time): PDF document, English',
    );
    fireEvent.click(screen.getByTestId('variations-export'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(2));

    expect(downloadedUrls()).toEqual([
      '/api/v1/variations/notices/export/?project_id=p-1&format=pdf&locale=en',
      '/api/v1/variations/claims/export/?project_id=p-1&format=pdf&locale=en',
    ]);
  });

  it('offers all three registers in both formats, and downloads the one picked in Turkish', async () => {
    renderAt('/variations?tab=requests');
    await waitFor(() => expect((screen.getByTestId('variations-export') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId('variations-export-more'));

    expect(screen.getAllByRole('menuitem')).toHaveLength(6);
    expect(screen.getByText(/The whole register is exported/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('variations-export-lang-tr'));
    fireEvent.click(screen.getByTestId('variations-export-item-variation-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual([
      '/api/v1/variations/variation-requests/export/?project_id=p-1&format=xlsx&locale=tr',
    ]);
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    renderAt('/variations');
    const button = screen.getByTestId('variations-export') as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0]?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is not offered when there is no project to export from', async () => {
    // With no project this page shows one message in place of the workspace,
    // header and all, so there is no control to disable.
    project.id = null;
    routeGet([]);
    renderAt('/variations');
    await screen.findByText('Select a project to manage variations');
    expect(screen.queryByTestId('variations-export')).toBeNull();
    expect(api.downloadWithAuth).not.toHaveBeenCalled();
  });
});

describe('printing one variation request', () => {
  it('downloads its form from the drawer, in the language picked', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DetailDrawer
            selected={{ kind: 'requests', id: REQUEST.id }}
            projectId="p-1"
            notices={[]}
            requests={[REQUEST]}
            orders={[]}
            daywork={[]}
            eot={[]}
            currency="TRY"
            onClose={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByTestId('variation-request-pdf-more'));
    fireEvent.click(screen.getByTestId('variation-request-pdf-lang-tr'));
    fireEvent.click(screen.getByTestId('variation-request-pdf-item-pdf'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/variations/variation-requests/vr-1/export/pdf/?locale=tr']);
    expect(api.downloadWithAuth.mock.calls[0]?.[1]).toBe('VR-001.pdf');
  });
});
