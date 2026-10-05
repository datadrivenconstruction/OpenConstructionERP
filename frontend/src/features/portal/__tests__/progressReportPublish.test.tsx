// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A generated progress report stays internal until a person releases it to
// the client portal. The internal tab says which reports the client can see
// and offers the one action that changes it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, second?: unknown) => {
      if (second && typeof second === 'object' && 'defaultValue' in second) {
        return String((second as { defaultValue?: string }).defaultValue ?? '');
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'p1' }));
vi.mock('@/features/projects/api', () => ({
  projectsApi: { list: vi.fn().mockResolvedValue([{ id: 'p1', name: 'Villa Rossi' }]) },
}));

const apiMocks = vi.hoisted(() => ({
  listProgressReports: vi.fn(),
  publishProgressReport: vi.fn(),
  unpublishProgressReport: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), ...apiMocks }));

const { ProgressReportsTab } = await import('../ProgressReportsTab');
const { useAuthStore } = await import('@/stores/useAuthStore');

function report(id: string, title: string, publishedAt: string | null) {
  return {
    id,
    project_id: 'p1',
    template_id: null,
    report_type: 'progress_report',
    title,
    generated_at: '2026-10-05T08:00:00Z',
    format: 'html',
    storage_key: `reports/${id}.html`,
    published_at: publishedAt,
  };
}

function mount(role = 'manager') {
  useAuthStore.setState({ userRole: role });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProgressReportsTab />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null });
  vi.clearAllMocks();
});

describe('progress reports reach the client only once published', () => {
  it('marks each report as internal or visible and offers the matching action', async () => {
    apiMocks.listProgressReports.mockResolvedValue([
      report('r1', 'Week 40 draft', null),
      report('r2', 'Week 39', '2026-09-29T10:00:00Z'),
    ]);
    mount();
    await waitFor(() => expect(screen.getByText('Week 40 draft')).toBeTruthy());

    const draftRow = screen.getByText('Week 40 draft').closest('tr')!;
    const releasedRow = screen.getByText('Week 39').closest('tr')!;
    expect(draftRow.textContent).toContain('Internal only');
    expect(draftRow.textContent).toContain('Show to client');
    expect(releasedRow.textContent).toContain('Visible to client');
    expect(releasedRow.textContent).toContain('Hide from client');
  });

  it('publishes a draft and takes a released report back', async () => {
    apiMocks.listProgressReports.mockResolvedValue([
      report('r1', 'Week 40 draft', null),
      report('r2', 'Week 39', '2026-09-29T10:00:00Z'),
    ]);
    apiMocks.publishProgressReport.mockResolvedValue(report('r1', 'Week 40 draft', '2026-10-05T09:00:00Z'));
    apiMocks.unpublishProgressReport.mockResolvedValue(report('r2', 'Week 39', null));
    mount();
    await waitFor(() => expect(screen.getByText('Week 40 draft')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /Show to client/ }));
    await waitFor(() => expect(apiMocks.publishProgressReport).toHaveBeenCalledWith('r1'));

    fireEvent.click(screen.getByRole('button', { name: /Hide from client/ }));
    await waitFor(() => expect(apiMocks.unpublishProgressReport).toHaveBeenCalledWith('r2'));
    expect(apiMocks.publishProgressReport).toHaveBeenCalledTimes(1);
  });

  it('shows an editor the state but not the action the backend would refuse', async () => {
    apiMocks.listProgressReports.mockResolvedValue([report('r1', 'Week 40 draft', null)]);
    mount('editor');
    await waitFor(() => expect(screen.getByText('Week 40 draft')).toBeTruthy());

    const row = screen.getByText('Week 40 draft').closest('tr')!;
    expect(row.textContent).toContain('Internal only');
    expect(screen.queryByRole('button', { name: /Show to client/ })).toBeNull();
  });
});
