// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFI log used to leave this screen through GET /export/, which prints
// English whatever the reader's language. The server now has a second route,
// GET /export/register/, that prints the log in Turkish or English as a
// workbook or a PDF (backend/app/modules/rfi/export_routes.py). These hold
// the page to the new route, with the project, the format and the language,
// and to never calling the old one. The page is rendered whole, so a control
// that is built but never mounted fails here too.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

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

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), setOpen: vi.fn(), custom: [] }),
}));

vi.mock('@/features/tasks', () => ({ CreateTaskFromSourceDialog: () => null }));
vi.mock('@/features/approval-routes', () => ({ ApprovalTargetBadge: () => null }));

import { RFIPage } from '../RFIPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

const PROJECT = { id: 'p-1', name: 'İstanbul Veri Merkezi' };

const ROW = {
  id: 'r-1',
  project_id: 'p-1',
  rfi_number: 'RFI-007',
  subject: 'Duct clash at grid C4',
  question: 'Which service takes priority at the crossing?',
  official_response: null,
  status: 'open',
  raised_by: 'u-1',
  assigned_to: null,
  ball_in_court: null,
  responded_by: null,
  responded_at: null,
  cost_impact: false,
  cost_impact_value: null,
  schedule_impact: false,
  schedule_impact_days: null,
  date_required: null,
  response_due_date: null,
  linked_drawing_ids: [],
  attachments: [],
  change_order_id: null,
  created_by: null,
  priority: 'normal',
  discipline: null,
  metadata: {},
  created_at: '2026-10-04T08:00:00Z',
  updated_at: '2026-10-04T08:00:00Z',
  is_overdue: false,
  days_open: 2,
};

/** Routes a GET by path; `rows` is what the register holds. */
function routeGet(rows: unknown[], projects: unknown[] = [PROJECT]): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/rfi/?')) {
      return Promise.resolve({ items: rows, total: rows.length, offset: 0, limit: 100 });
    }
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects);
    if (path.startsWith('/v1/rfi/stats')) {
      return Promise.resolve({
        total: rows.length,
        by_status: {},
        open: rows.length,
        overdue: 0,
        avg_days_to_response: null,
        cost_impact_count: 0,
        schedule_impact_count: 0,
      });
    }
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 100 });
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/rfi']}>
        <RFIPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function downloadedUrls(): string[] {
  return api.downloadWithAuth.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  api.downloadWithAuth.mockResolvedValue(undefined);
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: PROJECT.name });
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('exporting the RFI log', () => {
  it('downloads it as a PDF in the interface language in one click', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findAllByText('Duct clash at grid C4');

    const button = screen.getByTestId('rfi-export') as HTMLButtonElement;
    expect(button.textContent).toContain('Export RFI Log');
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/rfi/export/register/?project_id=p-1&format=pdf&locale=en']);
  });

  it('downloads the workbook in Turkish when that is what is picked', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findAllByText('Duct clash at grid C4');

    fireEvent.click(screen.getByTestId('rfi-export-more'));
    // The route takes no filter, and the control says so.
    expect(screen.getByText(/The whole register is exported/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('rfi-export-lang-tr'));
    fireEvent.click(screen.getByTestId('rfi-export-item-register-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/rfi/export/register/?project_id=p-1&format=xlsx&locale=tr']);
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    routeGet([ROW]);
    renderPage();
    await screen.findAllByText('Duct clash at grid C4');

    fireEvent.click(screen.getByTestId('rfi-export'));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast?.type).toBe('error');
    expect(toast?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is disabled, with the reason, while the register holds nothing', async () => {
    routeGet([]);
    renderPage();

    const button = screen.getByTestId('rfi-export') as HTMLButtonElement;
    await waitFor(() => expect(button.getAttribute('title')).toBe('There are no records to export yet'));
    expect(button.disabled).toBe(true);
    expect((screen.getByTestId('rfi-export-more') as HTMLButtonElement).disabled).toBe(true);
  });

  it('is disabled, with the reason, when no project is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    routeGet([], []);
    renderPage();

    const button = screen.getByTestId('rfi-export') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('Please select a project first');
    fireEvent.click(button);
    expect(api.downloadWithAuth).not.toHaveBeenCalled();
  });
});
