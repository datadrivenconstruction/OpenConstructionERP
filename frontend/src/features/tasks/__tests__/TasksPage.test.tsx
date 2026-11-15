// Page-level tests for the Tasks kanban board: states, filters, create, status moves.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const m = vi.hoisted(() => ({
  fetchTasks: vi.fn(),
  fetchMyTasks: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  completeTask: vi.fn(),
  deleteTask: vi.fn(),
  exportTasks: vi.fn(),
  addToast: vi.fn(),
}));

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  fetchTasks: m.fetchTasks,
  fetchMyTasks: m.fetchMyTasks,
  createTask: m.createTask,
  updateTask: m.updateTask,
  completeTask: m.completeTask,
  deleteTask: m.deleteTask,
  exportTasks: m.exportTasks,
}));
vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: vi.fn(async () => [{ id: 'p1', name: 'Tower A' }]),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (sel: (s: { addToast: typeof m.addToast }) => unknown) => sel({ addToast: m.addToast }),
    { getState: () => ({ addToast: m.addToast }) },
  ),
}));

import { TasksPage } from '../TasksPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import type { Task } from '../api';

function task(over: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    title: 'Review drawings',
    description: null,
    task_type: 'task',
    status: 'open',
    priority: 'normal',
    responsible_id: null,
    assigned_to: null,
    assigned_to_name: null,
    due_date: null,
    checklist: [],
    checklist_progress: 0,
    created_by: null,
    meeting_id: null,
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    is_overdue: false,
    ...over,
  };
}
const page = (items: Task[]) => ({ items, total: items.length, offset: 0, limit: 100 });

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TasksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
    m.fetchTasks.mockResolvedValue(page([]));
    m.fetchMyTasks.mockResolvedValue(page([]));
  });

  it('shows the empty state with a create action when the project has no tasks', async () => {
    renderPage();
    expect(await screen.findByText('No tasks yet')).toBeInTheDocument();
    expect(m.fetchTasks).toHaveBeenCalledWith(expect.objectContaining({ project_id: 'p1' }));
    fireEvent.click(screen.getAllByRole('button', { name: /New Task/ }).at(-1)!);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('places tasks in their status columns', async () => {
    m.fetchTasks.mockResolvedValue(
      page([
        task({ id: 'a', title: 'Pour slab', status: 'open' }),
        task({ id: 'b', title: 'Pull cables', status: 'in_progress' }),
      ]),
    );
    renderPage();
    const open = await screen.findByRole('group', { name: /^Open column, 1 tasks/ });
    expect(within(open).getByText('Pour slab')).toBeInTheDocument();
    const prog = screen.getByRole('group', { name: /^In Progress column, 1 tasks/ });
    expect(within(prog).getByText('Pull cables')).toBeInTheDocument();
  });

  it('shows a recovery card and refetches on retry when loading fails', async () => {
    m.fetchTasks.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    const retry = await screen.findByRole('button', { name: /retry|try again/i });
    m.fetchTasks.mockResolvedValue(page([task({ title: 'Back again' })]));
    fireEvent.click(retry);
    expect(await screen.findByText('Back again')).toBeInTheDocument();
  });

  it('filters by search text and reports no matches', async () => {
    m.fetchTasks.mockResolvedValue(
      page([task({ id: 'a', title: 'Pour slab' }), task({ id: 'b', title: 'Pull cables' })]),
    );
    renderPage();
    await screen.findByText('Pour slab');
    fireEvent.change(screen.getByPlaceholderText('Search tasks...'), { target: { value: 'cables' } });
    expect(screen.queryByText('Pour slab')).not.toBeInTheDocument();
    expect(screen.getByText('Pull cables')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Search tasks...'), { target: { value: 'zzz' } });
    expect(await screen.findByText('No matching tasks')).toBeInTheDocument();
  });

  it('queries the server by type when a type tab is chosen', async () => {
    m.fetchTasks.mockResolvedValue(page([task({})]));
    renderPage();
    await screen.findByText('Review drawings');
    fireEvent.click(screen.getByRole('button', { name: 'Decision' }));
    await waitFor(() =>
      expect(m.fetchTasks).toHaveBeenLastCalledWith(expect.objectContaining({ task_type: 'decision' })),
    );
  });

  it('switches to the cross-project endpoint for My Tasks', async () => {
    m.fetchMyTasks.mockResolvedValue(page([task({ title: 'Mine only' })]));
    renderPage();
    await screen.findByText('No tasks yet');
    fireEvent.click(screen.getByLabelText('My Tasks'));
    expect(await screen.findByText('Mine only')).toBeInTheDocument();
    expect(m.fetchMyTasks).toHaveBeenCalled();
  });

  it('creates a task with the typed title and the active project', async () => {
    m.createTask.mockResolvedValue(task({ id: 'new', title: 'Check rebar' }));
    renderPage();
    await screen.findByText('No tasks yet');
    fireEvent.click(screen.getAllByRole('button', { name: /New Task/ }).at(-1)!);
    const dialog = await screen.findByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: /Create Task/ });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByPlaceholderText(/Review structural drawings/), {
      target: { value: 'Check rebar' },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(m.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: 'p1', title: 'Check rebar', task_type: 'task' }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
  });

  it('keeps the dialog open and toasts an error when create fails', async () => {
    m.createTask.mockRejectedValue(new Error('nope'));
    renderPage();
    await screen.findByText('No tasks yet');
    fireEvent.click(screen.getAllByRole('button', { name: /New Task/ }).at(-1)!);
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByPlaceholderText(/Review structural drawings/), { target: { value: 'X' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Create Task/ }));
    await waitFor(() => expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' })));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('moves a task to another column through the status select', async () => {
    m.fetchTasks.mockResolvedValue(page([task({ id: 'a', title: 'Pour slab', status: 'open' })]));
    m.updateTask.mockResolvedValue(task({ id: 'a', status: 'in_progress' }));
    renderPage();
    await screen.findByText('Pour slab');
    fireEvent.change(screen.getByLabelText('Change status'), { target: { value: 'in_progress' } });
    await waitFor(() => expect(m.updateTask).toHaveBeenCalledWith('a', { status: 'in_progress' }));
  });

  it('offers no completed target from draft and never calls the server', async () => {
    m.fetchTasks.mockResolvedValue(page([task({ id: 'a', status: 'draft' })]));
    renderPage();
    await screen.findByText('Review drawings');
    const select = screen.getByLabelText('Change status') as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).not.toContain('completed');
    expect(m.updateTask).not.toHaveBeenCalled();
  });

  it('completes a task only after confirmation', async () => {
    m.fetchTasks.mockResolvedValue(page([task({ id: 'a', status: 'open' })]));
    m.completeTask.mockResolvedValue(task({ id: 'a', status: 'completed' }));
    renderPage();
    await screen.findByText('Review drawings');
    fireEvent.click(screen.getByTitle('Complete'));
    expect(m.completeTask).not.toHaveBeenCalled();
    const completeBtns = await screen.findAllByRole('button', { name: 'Complete' });
    fireEvent.click(completeBtns[completeBtns.length - 1]!);
    await waitFor(() => expect(m.completeTask).toHaveBeenCalledWith('a'));
  });

  it('deletes a task only after confirmation', async () => {
    m.fetchTasks.mockResolvedValue(page([task({ id: 'a' })]));
    m.deleteTask.mockResolvedValue(undefined);
    renderPage();
    await screen.findByText('Review drawings');
    fireEvent.click(screen.getByTitle('Delete'));
    expect(m.deleteTask).not.toHaveBeenCalled();
    const confirmBtns = await screen.findAllByRole('button', { name: 'Delete' });
    fireEvent.click(confirmBtns[confirmBtns.length - 1]!);
    await waitFor(() => expect(m.deleteTask).toHaveBeenCalledWith('a'));
  });

  it('hides the board and disables export when no project is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null } as never);
    const { fetchProjectList } = await import('@/shared/lib/projectList');
    (fetchProjectList as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText('requiresProject.title')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Export/ })).toBeDisabled();
    expect(m.fetchTasks).not.toHaveBeenCalled();
  });
});
