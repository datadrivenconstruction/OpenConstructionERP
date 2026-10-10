// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The correspondence log and the form of one entry can be printed by the
// server in Turkish and in English, and until this the screen had no way to
// ask for either. These hold the page to the routes as they are declared
// (backend/app/modules/correspondence/export_routes.py): the project, the
// format and the language on the log, the language alone on the form,
// trailing slashes kept. The page is rendered whole, so a control that is
// built but never mounted fails here too.

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

import { CorrespondencePage } from './CorrespondencePage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

const PROJECT = { id: 'p-1', name: 'İstanbul Veri Merkezi' };

const ROW = {
  id: 'c-1',
  project_id: 'p-1',
  reference_number: 'COR-014',
  subject: 'Notice of delayed access to plant room',
  direction: 'outgoing',
  correspondence_type: 'letter',
  from_contact_id: null,
  to_contact_ids: [],
  date_sent: '2026-10-02',
  date_received: null,
  status: 'open',
  notes: null,
  created_by: null,
  created_at: '2026-10-02T08:00:00Z',
  updated_at: '2026-10-02T08:00:00Z',
};

/** Routes a GET by path; `rows` is what the register holds. */
function routeGet(rows: unknown[], projects: unknown[] = [PROJECT]): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/correspondence/')) {
      return Promise.resolve({ items: rows, total: rows.length, offset: 0, limit: 100 });
    }
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects);
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 100 });
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/correspondence']}>
        <CorrespondencePage />
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

describe('exporting the correspondence log', () => {
  it('downloads it as a PDF in the interface language in one click', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Notice of delayed access to plant room');

    const button = screen.getByTestId('correspondence-export') as HTMLButtonElement;
    expect(button.textContent).toContain('Export log');
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/correspondence/export/?project_id=p-1&format=pdf&locale=en']);
  });

  it('downloads the workbook in Turkish when that is what is picked', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Notice of delayed access to plant room');

    fireEvent.click(screen.getByTestId('correspondence-export-more'));
    // The route takes no filter, and the control says so.
    expect(screen.getByText(/The whole register is exported/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('correspondence-export-lang-tr'));
    fireEvent.click(screen.getByTestId('correspondence-export-item-register-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/correspondence/export/?project_id=p-1&format=xlsx&locale=tr']);
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Notice of delayed access to plant room');

    fireEvent.click(screen.getByTestId('correspondence-export'));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast?.type).toBe('error');
    expect(toast?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is disabled, with the reason, while the register holds nothing', async () => {
    routeGet([]);
    renderPage();

    const button = screen.getByTestId('correspondence-export') as HTMLButtonElement;
    await waitFor(() => expect(button.getAttribute('title')).toBe('There are no records to export yet'));
    expect(button.disabled).toBe(true);
    expect((screen.getByTestId('correspondence-export-more') as HTMLButtonElement).disabled).toBe(true);
  });

  it('is disabled, with the reason, when no project is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    routeGet([], []);
    renderPage();

    const button = screen.getByTestId('correspondence-export') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('Please select a project first');
    fireEvent.click(button);
    expect(api.downloadWithAuth).not.toHaveBeenCalled();
  });
});

describe('printing one correspondence entry', () => {
  it('downloads its form from the expanded row, in the language picked', async () => {
    routeGet([ROW]);
    renderPage();
    fireEvent.click(await screen.findByText('Notice of delayed access to plant room'));

    const print = await screen.findByTestId('correspondence-pdf-c-1');
    expect(print.textContent).toContain('Print / PDF');
    fireEvent.click(print);
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('correspondence-pdf-c-1-more'));
    fireEvent.click(screen.getByTestId('correspondence-pdf-c-1-lang-tr'));
    fireEvent.click(screen.getByTestId('correspondence-pdf-c-1-item-pdf'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(2));

    expect(downloadedUrls()).toEqual([
      '/api/v1/correspondence/c-1/export/pdf/?locale=en',
      '/api/v1/correspondence/c-1/export/pdf/?locale=tr',
    ]);
    // The second argument is only a fallback; the server names the file.
    expect(api.downloadWithAuth.mock.calls[0]?.[1]).toBe('COR-014.pdf');
  });
});
