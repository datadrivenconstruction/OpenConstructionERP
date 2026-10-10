// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The transmittal register and the cover sheet of one transmittal can be
// printed by the server in Turkish and in English, and until this the screen
// had no way to ask for either. These hold the page to the routes as they are
// declared (backend/app/modules/transmittals/export_routes.py): the project,
// the format and the language on the register, the language alone on the
// cover sheet, trailing slashes kept. The row is an ISSUED transmittal on
// purpose: that is the one that gets printed, and the row's other actions
// are drawn for drafts only.

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

import { TransmittalsPage } from './TransmittalsPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

const PROJECT = { id: 'p-1', name: 'İstanbul Veri Merkezi' };

const ROW = {
  id: 't-1',
  project_id: 'p-1',
  transmittal_number: 'TR-0007',
  subject: 'Mechanical shop drawings, level 2',
  purpose_code: 'for_approval',
  status: 'issued',
  cover_note: null,
  issued_date: '2026-10-03',
  response_due_date: null,
  is_locked: true,
  recipients: [],
  items: [],
  metadata: {},
  created_by: null,
  created_at: '2026-10-03T08:00:00Z',
  updated_at: '2026-10-03T08:00:00Z',
};

/** Routes a GET by path; `rows` is what the register holds. */
function routeGet(rows: unknown[], projects: unknown[] = [PROJECT]): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/transmittals/')) {
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
      <MemoryRouter initialEntries={['/transmittals']}>
        <TransmittalsPage />
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

describe('exporting the transmittal register', () => {
  it('downloads it as a PDF in the interface language in one click', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Mechanical shop drawings, level 2');

    const button = screen.getByTestId('transmittals-export') as HTMLButtonElement;
    expect(button.textContent).toContain('Export register');
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/transmittals/export/?project_id=p-1&format=pdf&locale=en']);
  });

  it('downloads the workbook in Turkish when that is what is picked', async () => {
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Mechanical shop drawings, level 2');

    fireEvent.click(screen.getByTestId('transmittals-export-more'));
    // The route takes no filter, and the control says so.
    expect(screen.getByText(/The whole register is exported/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('transmittals-export-lang-tr'));
    fireEvent.click(screen.getByTestId('transmittals-export-item-register-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual(['/api/v1/transmittals/export/?project_id=p-1&format=xlsx&locale=tr']);
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    routeGet([ROW]);
    renderPage();
    await screen.findByText('Mechanical shop drawings, level 2');

    fireEvent.click(screen.getByTestId('transmittals-export'));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast?.type).toBe('error');
    expect(toast?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is disabled, with the reason, while the register holds nothing', async () => {
    routeGet([]);
    renderPage();

    const button = screen.getByTestId('transmittals-export') as HTMLButtonElement;
    await waitFor(() => expect(button.getAttribute('title')).toBe('There are no records to export yet'));
    expect(button.disabled).toBe(true);
    expect((screen.getByTestId('transmittals-export-more') as HTMLButtonElement).disabled).toBe(true);
  });

  it('is disabled, with the reason, when no project is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    routeGet([], []);
    renderPage();

    const button = screen.getByTestId('transmittals-export') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('Please select a project first');
    fireEvent.click(button);
    expect(api.downloadWithAuth).not.toHaveBeenCalled();
  });
});

describe('printing the cover sheet of an issued transmittal', () => {
  it('downloads its form from the expanded row, in the language picked', async () => {
    routeGet([ROW]);
    renderPage();
    fireEvent.click(await screen.findByText('Mechanical shop drawings, level 2'));

    const print = await screen.findByTestId('transmittal-pdf-t-1');
    expect(print.textContent).toContain('Print / PDF');
    fireEvent.click(print);
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('transmittal-pdf-t-1-more'));
    fireEvent.click(screen.getByTestId('transmittal-pdf-t-1-lang-tr'));
    fireEvent.click(screen.getByTestId('transmittal-pdf-t-1-item-pdf'));
    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(2));

    expect(downloadedUrls()).toEqual([
      '/api/v1/transmittals/t-1/export/pdf/?locale=en',
      '/api/v1/transmittals/t-1/export/pdf/?locale=tr',
    ]);
    // The second argument is only a fallback; the server names the file.
    expect(api.downloadWithAuth.mock.calls[0]?.[1]).toBe('TR-0007.pdf');
  });
});
