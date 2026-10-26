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
      downloadProgressSheet: vi.fn(),
      previewProgressSheet: vi.fn(),
      applyProgressSheet: vi.fn(),
    },
  };
});

import { interopApi } from './interopApi';
import { ProgressSheetDialog } from './ProgressSheetDialog';

const PREVIEW = {
  schedule_id: 's1',
  filename: 'progress.xlsx',
  sha256: 'f'.repeat(64),
  exported_at: '2026-05-01T10:00:00Z',
  exported_data_date: null,
  status_date: '2026-05-06',
  row_count: 3,
  changed_count: 2,
  error_count: 1,
  stale_count: 1,
  rows: [
    {
      row_number: 2,
      activity_id: 'a1',
      activity_code: 'A1',
      name: 'Excavation',
      changes: { percent_complete: { old: 0, new: 60 } },
      issues: [],
      stale: false,
      has_errors: false,
      applicable: true,
    },
    {
      row_number: 3,
      activity_id: 'a2',
      activity_code: 'A2',
      name: 'Foundations',
      changes: { percent_complete: { old: 10, new: 20 } },
      issues: [{ rule_id: 'x.unchanged_since_export', code: 'fail', severity: 'warning', message: 'Changed in the app' }],
      stale: true,
      has_errors: false,
      applicable: true,
    },
    {
      row_number: 4,
      activity_id: 'a3',
      activity_code: 'A3',
      name: 'Walls',
      changes: {},
      issues: [{ rule_id: 'x.values_in_range', code: 'percent_out_of_range', severity: 'error', message: 'Too high' }],
      stale: false,
      has_errors: true,
      applicable: false,
    },
  ],
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProgressSheetDialog
        open
        onClose={() => {}}
        scheduleId="s1"
        canEdit
        activities={[
          { wbs_code: '01.1', assignee_id: 'u1', assignee_name: 'Ann' },
          { wbs_code: '02.1', assignee_id: null },
        ]}
      />
    </QueryClientProvider>,
  );
}

describe('ProgressSheetDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('downloads the sheet with the chosen scope', async () => {
    interopApi.downloadProgressSheet.mockResolvedValue(4);
    renderDialog();
    fireEvent.change(screen.getByTestId('ps-wbs'), { target: { value: '02' } });
    fireEvent.change(screen.getByTestId('ps-assignee'), { target: { value: 'u1' } });
    fireEvent.click(screen.getByTestId('progress-sheet-download'));
    await waitFor(() =>
      expect(interopApi.downloadProgressSheet).toHaveBeenCalledWith(
        's1',
        expect.objectContaining({ wbs: '02', assigneeId: 'u1', includeCompleted: false }),
      ),
    );
  });

  it('previews an upload, preselects only safe rows and applies them', async () => {
    interopApi.previewProgressSheet.mockResolvedValue(PREVIEW);
    interopApi.applyProgressSheet.mockResolvedValue({
      schedule_id: 's1',
      batch_id: 'b',
      status_date: '2026-05-06',
      applied_count: 1,
      applied_activity_ids: ['a1'],
      skipped: [],
      data_date_advanced: true,
    });
    renderDialog();
    fireEvent.click(screen.getByRole('tab', { name: /upload/i }));
    const file = new File(['x'], 'progress.xlsx');
    fireEvent.change(screen.getByTestId('ps-file'), { target: { files: [file] } });

    await screen.findByTestId('ps-row-2');
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    expect(boxes[2]).toBeDisabled();
    expect(screen.getByText('Too high')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('progress-sheet-apply'));
    await waitFor(() =>
      expect(interopApi.applyProgressSheet).toHaveBeenCalledWith(
        's1',
        file,
        expect.objectContaining({ sha256: PREVIEW.sha256, rowNumbers: [2] }),
      ),
    );
  });

  it('lets the user take a stale row on purpose', async () => {
    interopApi.previewProgressSheet.mockResolvedValue(PREVIEW);
    interopApi.applyProgressSheet.mockResolvedValue({ ...PREVIEW, applied_count: 2, skipped: [] });
    renderDialog();
    fireEvent.click(screen.getByRole('tab', { name: /upload/i }));
    fireEvent.change(screen.getByTestId('ps-file'), { target: { files: [new File(['x'], 'p.xlsx')] } });
    await screen.findByTestId('ps-row-3');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(screen.getByTestId('progress-sheet-apply'));
    await waitFor(() =>
      expect(interopApi.applyProgressSheet).toHaveBeenCalledWith(
        's1',
        expect.anything(),
        expect.objectContaining({ rowNumbers: [2, 3] }),
      ),
    );
  });
});
