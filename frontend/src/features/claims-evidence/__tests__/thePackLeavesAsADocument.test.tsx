// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The evidence pack could leave the platform only as JSON, which nobody can
// attach to a claim letter. The server now prints it as a PDF or a workbook
// in Turkish and in English
// (backend/app/modules/claims_evidence/export_routes.py). These hold both
// surfaces to those routes: the project-wide pack, which is filed under the
// label and the basis the screen is showing, and the thread of one change,
// which still records the export in the audit trail whichever format is taken.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  downloadWithAuth: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ClaimsEvidencePage } from '../ClaimsEvidencePage';
import { EvidenceThreadPanel } from '../EvidenceThreadPanel';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

const PROJECT = { id: 'p-1', name: 'İstanbul Veri Merkezi' };

function pack(entryCount: number) {
  const entries = Array.from({ length: entryCount }, (_, i) => ({
    ref_id: `e-${i}`,
    kind: 'change_order',
    title: 'Relocate the site access gate',
    occurred_at: '2026-03-02T00:00:00Z',
    source: 'changeorders',
  }));
  return {
    subject_ref: 'project',
    basis: 'dispute',
    entry_count: entryCount,
    date_from: entryCount ? '2026-03-02T00:00:00Z' : null,
    date_to: entryCount ? '2026-03-02T00:00:00Z' : null,
    content_digest: 'abcdef0123456789',
    sections: entryCount ? [{ name: 'changes', entries }] : [],
  };
}

function routeGet(entryCount: number, projects: unknown[] = [PROJECT]): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects);
    if (path.startsWith('/v1/claims-evidence/')) return Promise.resolve(pack(entryCount));
    return Promise.resolve([]);
  });
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function downloadedUrls(): string[] {
  return api.downloadWithAuth.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  api.downloadWithAuth.mockResolvedValue(undefined);
  api.apiPost.mockResolvedValue(pack(1));
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: PROJECT.name });
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('exporting the project evidence pack', () => {
  it('downloads the PDF in one click, filed under the project name and the basis on screen', async () => {
    routeGet(2);
    mount(<ClaimsEvidencePage />);
    const button = screen.getByTestId('claims-evidence-export') as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(button.textContent).toContain('Export pack');

    fireEvent.change(screen.getByLabelText('Basis'), { target: { value: 'delay' } });
    await waitFor(() => expect((screen.getByTestId('claims-evidence-export') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId('claims-evidence-export'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    const url = new URL(downloadedUrls()[0]!, 'http://localhost');
    expect(url.pathname).toBe('/api/v1/claims-evidence/projects/p-1/pack/export/');
    // The Turkish letters of the project name survive the query string.
    expect(url.searchParams.get('subject_ref')).toBe('İstanbul Veri Merkezi');
    expect(url.searchParams.get('basis')).toBe('delay');
    expect(url.searchParams.get('format')).toBe('pdf');
    expect(url.searchParams.get('locale')).toBe('en');
  });

  it('downloads the workbook in Turkish when that is what is picked', async () => {
    routeGet(2);
    mount(<ClaimsEvidencePage />);
    await waitFor(() => expect((screen.getByTestId('claims-evidence-export') as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(screen.getByTestId('claims-evidence-export-more'));
    // The data file is still offered beside the two documents.
    expect(screen.getByTestId('claims-evidence-export-item-json').textContent).toContain('JSON data file');
    fireEvent.click(screen.getByTestId('claims-evidence-export-lang-tr'));
    fireEvent.click(screen.getByTestId('claims-evidence-export-item-xlsx'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    const url = new URL(downloadedUrls()[0]!, 'http://localhost');
    expect(url.searchParams.get('format')).toBe('xlsx');
    expect(url.searchParams.get('locale')).toBe('tr');
  });

  it('shows what the server said when the download is refused', async () => {
    api.downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    routeGet(2);
    mount(<ClaimsEvidencePage />);
    const button = screen.getByTestId('claims-evidence-export') as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0]?.message).toBe('Bu projeye erişim yetkiniz yok');
  });

  it('is disabled, with the reason, while the pack holds nothing', async () => {
    routeGet(0);
    mount(<ClaimsEvidencePage />);
    const button = screen.getByTestId('claims-evidence-export') as HTMLButtonElement;
    await screen.findByText('No evidence yet');
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('There are no records to export yet');
  });

  it('is disabled, with the reason, when no project is selected', () => {
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    routeGet(0, []);
    mount(<ClaimsEvidencePage />);
    const button = screen.getByTestId('claims-evidence-export') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('title')).toBe('Please select a project first');
  });
});

describe('exporting the evidence thread of one change', () => {
  it('downloads the document from the reconstruct route and still records the export', async () => {
    routeGet(1);
    mount(<EvidenceThreadPanel projectId="p-1" subjectType="change_order" subjectId="co-1" />);
    fireEvent.click(screen.getByText(/Reconstruct evidence thread/i));

    fireEvent.click(await screen.findByTestId('evidence-thread-export-more'));
    fireEvent.click(screen.getByTestId('evidence-thread-export-lang-tr'));
    fireEvent.click(screen.getByTestId('evidence-thread-export-item-pdf'));

    await waitFor(() => expect(api.downloadWithAuth).toHaveBeenCalledTimes(1));
    expect(downloadedUrls()).toEqual([
      '/api/v1/claims-evidence/projects/p-1/reconstruct/change_order/co-1/export/?format=pdf&locale=tr',
    ]);
    // The audit row is written by the POST, not by the document route.
    expect(api.apiPost).toHaveBeenCalledWith(
      '/v1/claims-evidence/projects/p-1/reconstruct/change_order/co-1/export',
      {},
    );
  });
});
