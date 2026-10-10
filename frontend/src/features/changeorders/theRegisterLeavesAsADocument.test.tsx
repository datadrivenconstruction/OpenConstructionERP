// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The change order register and the form of one change order can be printed
// by the server in Turkish and in English, and until this the screen offered
// only a CSV it built itself from the rows on screen. These hold the page to
// the routes as they are declared
// (backend/app/modules/changeorders/export_routes.py): the project, the
// format and the language on the register, the language alone on the form,
// trailing slashes kept. The CSV of the rows shown is still there, as an
// entry of the same control.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/** The query string the page mounts with; `?highlight=<id>` opens that record. */
let search = '';

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(search), vi.fn()],
  };
});

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve({})),
  downloadWithAuth: vi.fn(),
}));

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, ...api };
});

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    getApprovals: vi.fn(() => Promise.resolve([])),
    advanceApproval: vi.fn(() => Promise.resolve({})),
    startApprovalChain: vi.fn(() => Promise.resolve([])),
    simulateImpact: vi.fn(() => Promise.resolve({})),
    publishScenario: vi.fn(() => Promise.resolve({})),
    aiDraftChangeOrder: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('@/features/contracts/api', () => ({
  listContracts: vi.fn(() => Promise.resolve([])),
}));

vi.mock('@/features/claims-evidence', () => ({
  ProvabilityGauge: () => null,
  EvidenceThreadPanel: () => null,
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), setOpen: vi.fn(), custom: [] }),
}));

vi.mock('./ImpactSimulator', () => ({ ImpactSimulator: () => null }));
vi.mock('./AIDraftModal', () => ({ AIDraftModal: () => null }));

const project = vi.hoisted(() => ({ activeProjectId: 'p-1' as string | null }));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (selector?: (s: typeof project) => unknown) => (selector ? selector(project) : project),
}));

// A viewer: the documents are open to anyone who can read the register.
const auth = { userRole: 'viewer', accessToken: '' };
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector?: (s: typeof auth) => unknown) => (selector ? selector(auth) : auth),
}));

import { ChangeOrdersPage } from './ChangeOrdersPage';
import { useToastStore } from '@/stores/useToastStore';

const ORDER = {
  id: 'co-1',
  project_id: 'p-1',
  code: 'CO-003',
  title: 'Revised plant room slab',
  description: 'Thicker slab to carry the chillers.',
  reason_category: 'design_change',
  status: 'approved',
  submitted_by: null,
  submitted_by_name: null,
  approved_by: null,
  approved_by_name: null,
  rejected_by: null,
  rejected_by_name: null,
  submitted_at: null,
  approved_at: null,
  rejected_at: null,
  cost_impact: '12500.00',
  schedule_impact_days: 4,
  currency: 'TRY',
  metadata: {},
  item_count: 0,
  created_at: '2026-08-01T09:00:00Z',
  updated_at: '2026-08-01T10:00:00Z',
  current_approval_step: 0,
  items: [],
};

function routeGet(rows: unknown[], projects: unknown[] = [{ id: 'p-1', name: 'İstanbul Veri Merkezi', currency: 'TRY' }]) {
  api.apiGet.mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/?')) return Promise.resolve(projects);
    if (url.startsWith('/v1/changeorders/co-1')) return Promise.resolve(ORDER);
    if (url.startsWith('/v1/changeorders/?')) return Promise.resolve(rows);
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/changeorders${search}`]}>
        <ChangeOrdersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function downloadedUrls(): string[] {
  return api.downloadWithAuth.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  search = '';
  project.activeProjectId = 'p-1';
  api.downloadWithAuth.mockResolvedValue(undefined);
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('exporting the change order register', () => {
  it('downloads it as a PDF in the interface language in one click, for a viewer too', async () => {
    routeGet([ORDER]);
    renderPage();
    await screen.findByText('Revised plant room slab');

    const button = screen.getByTestId('changeorders-export') as HTMLButtonElement;
    expect(button.textContent).toContain('Export register');
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/changeorders/export/?project_id=p-1&format=pdf&locale=en']);
  });

  it('downloads the workbook in Turkish when that is what is picked', async () => {
    routeGet([ORDER]);
    renderPage();
    await screen.findByText('Revised plant room slab');

    fireEvent.click(screen.getByTestId('changeorders-export-more'));
    expect(screen.getByText(/The whole register is exported/)).toBeTruthy();
    // The CSV the page builds from the rows on screen is kept, and named for what it is.
    expect(screen.getByTestId('changeorders-export-item-csv-view').textContent).toContain('CSV of the rows shown');
    fireEvent.click(screen.getByTestId('changeorders-export-lang-tr'));
    fireEvent.click(screen.getByTestId('changeorders-export-item-register-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/changeorders/export/?project_id=p-1&format=xlsx&locale=tr']);
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    routeGet([ORDER]);
    renderPage();
    await screen.findByText('Revised plant room slab');

    fireEvent.click(screen.getByTestId('changeorders-export'));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast?.type).toBe('error');
    expect(toast?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is disabled, with the reason, while the register holds nothing', async () => {
    routeGet([]);
    renderPage();

    const button = screen.getByTestId('changeorders-export') as HTMLButtonElement;
    await waitFor(() => expect(button.getAttribute('title')).toBe('There are no records to export yet'));
    expect(button.disabled).toBe(true);
  });

  it('is disabled, with the reason, when no project is selected', () => {
    project.activeProjectId = null;
    routeGet([], []);
    renderPage();

    const button = screen.getByTestId('changeorders-export') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('Please select a project first');
  });
});

describe('printing one change order', () => {
  it('downloads its form from the detail view, in the language picked', async () => {
    search = '?highlight=co-1';
    routeGet([ORDER]);
    renderPage();

    const print = await screen.findByTestId('changeorder-pdf');
    expect(print.textContent).toContain('Print / PDF');
    fireEvent.click(print);
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('changeorder-pdf-more'));
    fireEvent.click(screen.getByTestId('changeorder-pdf-lang-tr'));
    fireEvent.click(screen.getByTestId('changeorder-pdf-item-pdf'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(2));

    expect(downloadedUrls()).toEqual([
      '/api/v1/changeorders/co-1/export/pdf/?locale=en',
      '/api/v1/changeorders/co-1/export/pdf/?locale=tr',
    ]);
    expect(api.downloadWithAuth.mock.calls[0]?.[1]).toBe('CO-003.pdf');
  });
});
