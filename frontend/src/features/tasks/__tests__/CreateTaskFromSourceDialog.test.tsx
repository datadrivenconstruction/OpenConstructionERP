// Tests for the cross-module "Create task" dialog and the tasks export download.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const m = vi.hoisted(() => ({
  createTask: vi.fn(),
  addToast: vi.fn(),
  triggerDownload: vi.fn(),
}));

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  createTask: m.createTask,
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof m.addToast }) => unknown) => sel({ addToast: m.addToast }),
}));
vi.mock('@/shared/ui/UserSearchInput', () => ({
  UserSearchInput: (p: { value: string; displayValue?: string; onChange: (id: string, n: string) => void }) => (
    <div>
      <span data-testid="assignee-value">{p.value}|{p.displayValue}</span>
      <button type="button" onClick={() => p.onChange('u-9', 'Eva Stone')}>
        pick-user
      </button>
    </div>
  ),
}));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  triggerDownload: m.triggerDownload,
}));

import { CreateTaskFromSourceDialog } from '../CreateTaskFromSourceDialog';
import { exportTasks } from '../api';

function renderDialog(props: Partial<React.ComponentProps<typeof CreateTaskFromSourceDialog>> = {}) {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CreateTaskFromSourceDialog
        projectId="p1"
        sourceType="rfi"
        sourceId="rfi-1"
        sourceLabel="RFI-012"
        defaultTitle="Clarify slab edge"
        onClose={onClose}
        onCreated={onCreated}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onClose, onCreated };
}

const titleInput = () => screen.getByTestId('create-task-from-source-title-input') as HTMLInputElement;
const descInput = () => screen.getByTestId('create-task-from-source-description-input') as HTMLTextAreaElement;
const submit = () => screen.getByTestId('create-task-from-source-submit') as HTMLButtonElement;

describe('CreateTaskFromSourceDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('prefills the title and a default description naming the source', () => {
    renderDialog();
    expect(titleInput().value).toBe('Clarify slab edge');
    expect(descInput().value).toBe('Follow up on RFI RFI-012.');
  });

  it('names the kind of record per source type', () => {
    renderDialog({ sourceType: 'inbound_capture', sourceLabel: 'MSG-3' });
    expect(descInput().value).toBe('Follow up on captured message MSG-3.');
  });

  it('keeps a caller-supplied description and due date', () => {
    renderDialog({ defaultDescription: 'See letter', defaultDueDate: '2026-12-01' });
    expect(descInput().value).toBe('See letter');
    expect((screen.getByTestId('create-task-from-source-due-input') as HTMLInputElement).value).toBe('2026-12-01');
  });

  it('disables submit for a blank title and re-enables it when typed', () => {
    renderDialog();
    fireEvent.change(titleInput(), { target: { value: '   ' } });
    expect(submit().disabled).toBe(true);
    fireEvent.change(titleInput(), { target: { value: 'Do it' } });
    expect(submit().disabled).toBe(false);
  });

  it('shows the no-project hint and blocks submit without a project', () => {
    renderDialog({ projectId: '' });
    expect(screen.getByTestId('create-task-from-source-no-project')).toBeTruthy();
    expect(submit().disabled).toBe(true);
    fireEvent.click(submit());
    expect(m.createTask).not.toHaveBeenCalled();
  });

  it('creates a traceable task, toasts, and closes', async () => {
    m.createTask.mockResolvedValue({ id: 't1' });
    const { onClose, onCreated } = renderDialog({ defaultDueDate: '2026-12-01' });
    fireEvent.change(titleInput(), { target: { value: '  Trim me  ' } });
    fireEvent.click(screen.getByText('pick-user'));
    fireEvent.click(submit());
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 't1' }));
    expect(m.createTask).toHaveBeenCalledWith({
      project_id: 'p1',
      title: 'Trim me',
      description: 'Follow up on RFI RFI-012.',
      task_type: 'task',
      due_date: '2026-12-01',
      responsible_id: 'u-9',
      metadata: { source: 'rfi', source_id: 'rfi-1', source_label: 'RFI-012', assignee_name: 'Eva Stone' },
    });
    expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('omits empty optional fields from the payload', async () => {
    m.createTask.mockResolvedValue({ id: 't2' });
    renderDialog();
    fireEvent.change(descInput(), { target: { value: '  ' } });
    fireEvent.click(submit());
    await waitFor(() => expect(m.createTask).toHaveBeenCalled());
    const payload = m.createTask.mock.calls[0]![0];
    expect(payload.description).toBeUndefined();
    expect(payload.due_date).toBeUndefined();
    expect(payload.responsible_id).toBeUndefined();
    expect(payload.metadata).not.toHaveProperty('assignee_name');
  });

  it('shows an error toast and stays open when creation fails', async () => {
    m.createTask.mockRejectedValue(new Error('boom'));
    const { onClose, onCreated } = renderDialog();
    fireEvent.click(submit());
    await waitFor(() =>
      expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error', message: 'boom' })),
    );
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape, on backdrop click and on Cancel, but not on inner click', () => {
    const { onClose } = renderDialog();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('create-task-from-source-dialog'));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(titleInput());
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it('prefills the assignee when the caller derived one', () => {
    renderDialog({ defaultAssigneeId: 'u-1', defaultAssigneeName: 'Ann' });
    expect(screen.getByTestId('assignee-value').textContent).toBe('u-1|Ann');
  });
});

describe('exportTasks', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('requests the project export with an encoded id and downloads the blob', async () => {
    const blob = new Blob(['x']);
    fetchMock.mockResolvedValue({
      ok: true,
      blob: async () => blob,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="plan.xlsx"' }),
    });
    await exportTasks('a b&c');
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/tasks/export/?project_id=a%20b%26c');
    expect(m.triggerDownload).toHaveBeenCalledWith(blob, expect.stringMatching(/^plan\.xlsx/));
  });

  it('falls back to a default file name', async () => {
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(), headers: new Headers() });
    await exportTasks('p1');
    expect(m.triggerDownload).toHaveBeenCalledWith(expect.anything(), 'tasks_export.xlsx');
  });

  it('throws the server detail, or an HTTP fallback when the body is not JSON', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: 'No data' }) });
    await expect(exportTasks('p1')).rejects.toThrow('No data');
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('bad json');
      },
    });
    await expect(exportTasks('p1')).rejects.toThrow('Export failed (HTTP 502)');
    expect(m.triggerDownload).not.toHaveBeenCalled();
  });
});
