// @ts-nocheck
/**
 * The spreadsheet import dialog against a mocked API: preview, a mapping
 * change, the date order, the client-visible confirmation and the commit,
 * plus the two refusals the dialog handles itself (a duplicate file and
 * errors found at commit time).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./tabularImport', async () => {
  const actual = await vi.importActual<typeof import('./tabularImport')>('./tabularImport');
  return {
    ...actual,
    previewSpreadsheet: vi.fn(),
    commitSpreadsheet: vi.fn(),
    downloadTemplate: vi.fn(),
  };
});

import { ApiError } from '@/shared/lib/api';
import { commitSpreadsheet, previewSpreadsheet } from './tabularImport';
import { ScheduleSpreadsheetImportDialog } from './ScheduleSpreadsheetImportDialog';

const COLUMNS = [
  { index: 0, header: 'ID', field: 'id', confidence: 1, tier: 'exact' },
  { index: 1, header: 'Task', field: 'name', confidence: 0.8, tier: 'synonym' },
  { index: 2, header: 'Begin', field: null, confidence: 0, tier: 'none' },
  { index: 3, header: 'Duration', field: 'duration', confidence: 1, tier: 'exact' },
  { index: 4, header: 'Client', field: 'client_visible', confidence: 0.8, tier: 'synonym' },
];

const ACTIVITIES = [
  { ref: 'A10', activity_code: 'A10', name: 'Handover', start_date: '', end_date: '', duration_days: 0, activity_type: 'milestone', client_visible: false },
  { ref: 'A20', activity_code: 'A20', name: 'Roof on', start_date: '', end_date: '', duration_days: 5, activity_type: 'task', client_visible: false },
  { ref: 'A30', activity_code: 'A30', name: 'Snagging', start_date: '', end_date: '', duration_days: 3, activity_type: 'task', client_visible: false },
];

const UNCONFIRMED = {
  code: 'date_order_unconfirmed',
  severity: 'error',
  row: 2,
  column: 2,
  message: "Dates such as '03/04/2026' read either day first or month first; confirm the order",
  params: { example: '03/04/2026', suggested: 'dmy', suggested_by: 'durations', columns: [2] },
};

function preview(overrides = {}) {
  return {
    sha256: 'a'.repeat(64),
    filename: 'plan.csv',
    file_format: 'csv',
    encoding: 'utf-8',
    delimiter: ',',
    sheet: null,
    header_row: 1,
    columns: COLUMNS,
    mapping: { id: 0, name: 1, duration: 3, client_visible: 4 },
    date_order: null,
    date_order_source: null,
    outline_source: null,
    row_count: 3,
    activity_count: 3,
    relationship_count: 1,
    has_errors: false,
    sample_rows: [{ row: 2, values: ['A10', 'Handover', '03/04/2026', '0', 'yes'], cells: {} }],
    issues: [],
    client_visible_suggested: ['A20'],
    document: { schedule: { name: 'plan', start_date: null, end_date: null }, activities: ACTIVITIES, relationships: [] },
    duplicate_of: [],
    ...overrides,
  };
}

const RESULT = {
  schedule_id: 's-new',
  schedule_name: 'plan',
  replaced: false,
  activity_count: 3,
  relationship_count: 1,
  critical_count: 2,
  project_duration_days: 8,
  validation: { rule_sets: ['schedule_quality'], errors: 0, warnings: 0, infos: 0, findings: [] },
  warnings: [],
};

function renderDialog(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onImported = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ScheduleSpreadsheetImportDialog open onClose={vi.fn()} projectId="p1" onImported={onImported} {...props} />
    </QueryClientProvider>,
  );
  return { onImported };
}

const FILE = new File(['ID,Task,Begin,Duration,Client\n'], 'plan.csv', { type: 'text/csv' });

async function chooseFile() {
  fireEvent.change(screen.getByLabelText(/Spreadsheet \(\.xlsx/i), { target: { files: [FILE] } });
  await screen.findByText(/Columns/);
}

function importButton() {
  return screen.getByRole('button', { name: /^import$/i });
}

describe('ScheduleSpreadsheetImportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('previews, remaps a column, confirms the date order and commits only the confirmed client refs', async () => {
    previewSpreadsheet
      .mockResolvedValueOnce(preview({ has_errors: true, date_order: 'dmy', date_order_source: 'suggested', issues: [UNCONFIRMED] }))
      .mockResolvedValueOnce(
        preview({
          has_errors: true,
          date_order: 'dmy',
          date_order_source: 'suggested',
          issues: [UNCONFIRMED],
          columns: COLUMNS.map((c) => (c.index === 2 ? { ...c, field: 'start', confidence: 1, tier: 'override' } : c)),
        }),
      )
      .mockResolvedValueOnce(
        preview({
          date_order: 'dmy',
          date_order_source: 'explicit',
          columns: COLUMNS.map((c) => (c.index === 2 ? { ...c, field: 'start', confidence: 1, tier: 'override' } : c)),
        }),
      );
    commitSpreadsheet.mockResolvedValue(RESULT);
    const { onImported } = renderDialog();

    await chooseFile();
    expect(previewSpreadsheet).toHaveBeenNthCalledWith(1, { projectId: 'p1', file: FILE, columnMapping: null, dateOrder: null });
    // The unconfirmed order blocks the import and names the file's own example.
    expect(screen.getByText(/Dates such as "03\/04\/2026" read either way/)).toBeInTheDocument();
    expect(importButton()).toBeDisabled();

    // Mapping: the unrecognised "Begin" column becomes the start date.
    fireEvent.change(screen.getByLabelText('Import column "Begin" as'), { target: { value: 'start' } });
    await waitFor(() => expect(previewSpreadsheet).toHaveBeenCalledTimes(2));
    expect(previewSpreadsheet.mock.calls[1][0]).toMatchObject({ columnMapping: '{"2":"start"}', dateOrder: null });
    expect(await screen.findByText('Chosen by you')).toBeInTheDocument();

    // Date order: day first, sent with the mapping kept.
    fireEvent.click(screen.getByLabelText(/Day first/));
    await waitFor(() => expect(previewSpreadsheet).toHaveBeenCalledTimes(3));
    expect(previewSpreadsheet.mock.calls[2][0]).toMatchObject({ columnMapping: '{"2":"start"}', dateOrder: 'dmy' });
    await waitFor(() => expect(importButton()).toBeEnabled());

    // Client visibility: nothing is ticked until the person ticks it.
    const picker = screen.getByTestId('tabular-client-picker');
    for (const box of within(picker).getAllByRole('checkbox')) expect(box).not.toBeChecked();
    fireEvent.click(within(picker).getByRole('button', { name: /Tick the 1 row the file suggests/ }));
    fireEvent.click(within(picker).getByRole('checkbox', { name: /A10/ }));

    fireEvent.click(importButton());
    await screen.findByTestId('tabular-import-result');
    const request = commitSpreadsheet.mock.calls[0][0];
    expect(request).toMatchObject({
      projectId: 'p1',
      file: FILE,
      expectedSha256: 'a'.repeat(64),
      target: 'new',
      columnMapping: '{"2":"start"}',
      dateOrder: 'dmy',
      allowDuplicate: false,
    });
    expect([...request.clientVisibleRefs].sort()).toEqual(['A10', 'A20']);
    expect(onImported).toHaveBeenCalledWith(RESULT);
    expect(screen.getByText('Schedule "plan" was created')).toBeInTheDocument();
  });

  it('commits with no client-visible refs when none were ticked, whatever the file suggests', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    commitSpreadsheet.mockResolvedValue(RESULT);
    renderDialog();
    await chooseFile();
    fireEvent.click(importButton());
    await screen.findByTestId('tabular-import-result');
    expect(commitSpreadsheet.mock.calls[0][0].clientVisibleRefs).toEqual([]);
  });

  it('offers to import a duplicate file again after a 409, and sends allow_duplicate only then', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    commitSpreadsheet
      .mockRejectedValueOnce(
        new ApiError(409, 'Conflict', {
          detail: { code: 'duplicate_import', message: 'This file was already imported into the project', schedule_ids: ['s9'] },
        }),
      )
      .mockResolvedValueOnce(RESULT);
    renderDialog();
    await chooseFile();

    fireEvent.click(importButton());
    const notice = await screen.findByTestId('tabular-duplicate');
    expect(commitSpreadsheet.mock.calls[0][0].allowDuplicate).toBe(false);
    expect(importButton()).toBeDisabled();

    fireEvent.click(within(notice).getByLabelText('Import it again anyway'));
    fireEvent.click(importButton());
    await screen.findByTestId('tabular-import-result');
    expect(commitSpreadsheet).toHaveBeenCalledTimes(2);
    expect(commitSpreadsheet.mock.calls[1][0].allowDuplicate).toBe(true);
  });

  it('lists the errors of a 422 refusal by sheet row and column', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    commitSpreadsheet.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: {
          code: 'import_has_errors',
          message: 'The file has errors to fix before it can be imported',
          issues: [
            { code: 'date_invalid', severity: 'error', row: 7, column: 2, message: "'xx' is not a date", params: { field: 'start', value: 'xx' } },
            { code: 'name_missing', severity: 'error', row: 9, column: null, message: 'The row has no activity name', params: {} },
          ],
        },
      }),
    );
    renderDialog();
    await chooseFile();
    fireEvent.click(importButton());

    const list = await screen.findByTestId('tabular-commit-issues');
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAttribute('data-code', 'date_invalid');
    expect(items[0]).toHaveTextContent('Row 7, column "Begin":');
    expect(items[0]).toHaveTextContent("'xx' is not a date");
    expect(items[1]).toHaveTextContent('Row 9:');
    expect(screen.getByRole('alert')).toHaveTextContent('The file has errors to fix before it can be imported');
    expect(screen.queryByTestId('tabular-import-result')).not.toBeInTheDocument();
  });

  it('offers replacing only a draft schedule it was opened from', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    commitSpreadsheet.mockResolvedValue({ ...RESULT, replaced: true, schedule_id: 's1', schedule_name: 'Main' });
    renderDialog({ schedule: { id: 's1', name: 'Main', status: 'draft' } });
    await chooseFile();
    fireEvent.click(screen.getByLabelText(/Replace the contents of "Main"/));
    fireEvent.click(screen.getByRole('button', { name: /Replace contents/ }));
    await screen.findByTestId('tabular-import-result');
    expect(commitSpreadsheet.mock.calls[0][0]).toMatchObject({ target: 'replace', scheduleId: 's1' });
    expect(screen.getByText('The contents of "Main" were replaced')).toBeInTheDocument();
  });

  it('starts on "replace" when asked to and the schedule is a draft, and on "new" otherwise', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    commitSpreadsheet.mockResolvedValue({ ...RESULT, replaced: true });
    renderDialog({ schedule: { id: 's1', name: 'Main', status: 'draft' }, defaultTarget: 'replace' });
    await chooseFile();
    expect(screen.getByLabelText(/Replace the contents of "Main"/)).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: /Replace contents/ }));
    await screen.findByTestId('tabular-import-result');
    expect(commitSpreadsheet.mock.calls[0][0]).toMatchObject({ target: 'replace', scheduleId: 's1' });
  });

  it('falls back to a new schedule when "replace" is asked for a schedule that is not a draft', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    renderDialog({ schedule: { id: 's1', name: 'Main', status: 'active' }, defaultTarget: 'replace' });
    await chooseFile();
    expect(screen.getByLabelText('A new schedule')).toBeChecked();
    expect(importButton()).toBeEnabled();
  });

  it('keeps replacing unavailable for a schedule that is not a draft', async () => {
    previewSpreadsheet.mockResolvedValue(preview());
    renderDialog({ schedule: { id: 's1', name: 'Main', status: 'active' } });
    await chooseFile();
    expect(screen.getByLabelText(/Replace the contents of "Main"/)).toBeDisabled();
    expect(screen.getByText('Only a draft schedule can be replaced.')).toBeInTheDocument();
  });
});
