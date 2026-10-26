// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./interopApi', async () => {
  const actual = await vi.importActual<typeof import('./interopApi')>('./interopApi');
  return {
    ...actual,
    interopApi: {
      ...actual.interopApi,
      getImportSource: vi.fn(),
      acceptImportRecalculation: vi.fn(),
      restoreImportSourceDates: vi.fn(),
    },
  };
});

import { ApiError } from '@/shared/lib/api';
import { interopApi } from './interopApi';
import { ImportSourcePanel } from './ImportSourcePanel';

const COMPARISON = {
  schedule_id: 's1',
  source: {
    format: 'xer',
    filename: 'programme.xer',
    sha256: 'a'.repeat(64),
    size_bytes: 1200,
    document_id: 'd1',
    document_issue: null,
    imported_at: '2026-05-01T10:00:00Z',
    imported_by: 'u1',
    activity_count: 2,
    status: 'pending_review',
    accepted_at: null,
    accepted_by: null,
  },
  activity_count: 2,
  deviating_count: 1,
  max_finish_deviation_days: 3,
  source_finish: '2026-05-15',
  current_finish: '2026-05-18',
  project_finish_deviation_days: 3,
  activities: [
    {
      activity_id: 'a1',
      activity_code: 'A1000',
      name: 'Excavation',
      source_id: '501',
      source_start: '2026-05-04',
      source_finish: '2026-05-08',
      source_duration_days: 5,
      current_start: '2026-05-04',
      current_finish: '2026-05-08',
      current_duration_days: 5,
      start_deviation_days: 0,
      finish_deviation_days: 0,
    },
    {
      activity_id: 'a2',
      activity_code: 'A1010',
      name: 'Foundations',
      source_id: '502',
      source_start: '2026-05-11',
      source_finish: '2026-05-15',
      source_duration_days: 5,
      current_start: '2026-05-12',
      current_finish: '2026-05-18',
      current_duration_days: 5,
      start_deviation_days: 1,
      finish_deviation_days: 3,
    },
  ],
};

function renderPanel(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ImportSourcePanel scheduleId="s1" canEdit {...props} />
    </QueryClientProvider>,
  );
}

describe('ImportSourcePanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders nothing for a schedule that was not imported', async () => {
    interopApi.getImportSource.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'x' }));
    const { container } = renderPanel();
    await waitFor(() => expect(interopApi.getImportSource).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows deviating activities with source and recalculated dates', async () => {
    interopApi.getImportSource.mockResolvedValue(COMPARISON);
    renderPanel();
    await screen.findByTestId('import-source-panel');
    expect(screen.getByText('Foundations')).toBeInTheDocument();
    expect(screen.queryByText('Excavation')).not.toBeInTheDocument();
    expect(screen.getByText('+3')).toBeInTheDocument();
  });

  it('accepts the recalculated dates', async () => {
    interopApi.getImportSource.mockResolvedValue(COMPARISON);
    interopApi.acceptImportRecalculation.mockResolvedValue({ ...COMPARISON.source, status: 'accepted' });
    renderPanel();
    fireEvent.click(await screen.findByTestId('import-source-accept'));
    await waitFor(() => expect(interopApi.acceptImportRecalculation).toHaveBeenCalledWith('s1'));
  });

  it('shows a banner only while deviations are under review', async () => {
    interopApi.getImportSource.mockResolvedValue(COMPARISON);
    const onOpen = vi.fn();
    renderPanel({ compact: true, onOpen });
    await screen.findByTestId('import-source-banner');
    fireEvent.click(screen.getByText(/Review/));
    expect(onOpen).toHaveBeenCalled();
  });

  it('shows no banner once accepted', async () => {
    interopApi.getImportSource.mockResolvedValue({
      ...COMPARISON,
      source: { ...COMPARISON.source, status: 'accepted' },
    });
    const { container } = renderPanel({ compact: true });
    await waitFor(() => expect(interopApi.getImportSource).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="import-source-banner"]')).toBeNull();
  });
});
