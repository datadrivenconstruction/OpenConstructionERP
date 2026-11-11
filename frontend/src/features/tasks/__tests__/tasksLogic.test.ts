// Pure-logic tests for the Tasks module: assignee payload mapping, REST
// helpers (query building, endpoints), insights builder and guide i18n keys.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  ...apiMocks,
}));

import { assigneeFields } from '../assignee';
import { fetchTasks, fetchMyTasks, createTask, updateTask, completeTask, deleteTask } from '../api';
import { buildTasksInsights } from '../tasksInsights';
import { tasksGuide } from '../tasksGuide';

const t = ((key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key) as never;
const UUID = '123e4567-e89b-12d3-a456-426614174000';

describe('assigneeFields', () => {
  const blank = { assigned_to: '', assignee_user_id: '', assignee_contact_id: '' };

  it('sends a picked contact by id only', () => {
    expect(assigneeFields({ ...blank, assigned_to: 'Ann', assignee_contact_id: 'c1' })).toEqual({
      assignee_contact_id: 'c1',
    });
  });

  it('ignores a stale contact id when the name was cleared', () => {
    expect(assigneeFields({ ...blank, assignee_contact_id: 'c1' })).toEqual({
      responsible_id: null,
      assignee_contact_id: null,
      metadata: { assignee_name: null },
    });
  });

  it('links a picked user and clears the contact and typed name', () => {
    expect(assigneeFields({ ...blank, assigned_to: 'Bob', assignee_user_id: 'u1' })).toEqual({
      responsible_id: 'u1',
      assignee_contact_id: null,
      metadata: { assignee_name: null },
    });
  });

  it('treats a pasted UUID as a user id', () => {
    expect(assigneeFields({ ...blank, assigned_to: UUID })).toMatchObject({ responsible_id: UUID });
  });

  it('keeps a typed name as plain metadata, trimmed', () => {
    expect(assigneeFields({ ...blank, assigned_to: '  Site crew  ' })).toEqual({
      responsible_id: null,
      assignee_contact_id: null,
      metadata: { assignee_name: 'Site crew' },
    });
  });
});

describe('tasks api', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetchTasks maps filters to backend query names', async () => {
    apiMocks.apiGet.mockResolvedValue({ items: [] });
    await fetchTasks({ project_id: 'p1', task_type: 'topic', status: 'open', responsible_id: 'u1' });
    const url = apiMocks.apiGet.mock.calls[0]![0] as string;
    expect(url.startsWith('/v1/tasks/?')).toBe(true);
    expect(Object.fromEntries(new URLSearchParams(url.split('?')[1]))).toEqual({
      project_id: 'p1',
      type: 'topic',
      status: 'open',
      responsible_id: 'u1',
    });
  });

  it('fetchTasks drops empty filters', async () => {
    apiMocks.apiGet.mockResolvedValue({ items: [] });
    await fetchTasks({ task_type: '', status: '' });
    expect(apiMocks.apiGet).toHaveBeenCalledWith('/v1/tasks/?');
  });

  it('fetchMyTasks passes the optional status', async () => {
    apiMocks.apiGet.mockResolvedValue({ items: [] });
    await fetchMyTasks('in_progress');
    expect(apiMocks.apiGet).toHaveBeenCalledWith('/v1/tasks/my-tasks/?status=in_progress');
  });

  it('create, update, complete and delete hit the right routes', async () => {
    apiMocks.apiPost.mockResolvedValue({});
    apiMocks.apiPatch.mockResolvedValue({});
    apiMocks.apiDelete.mockResolvedValue(undefined);
    await createTask({ project_id: 'p1', title: 'Pour slab' });
    expect(apiMocks.apiPost).toHaveBeenCalledWith('/v1/tasks/', { project_id: 'p1', title: 'Pour slab' });
    await updateTask('t1', { status: 'completed' });
    expect(apiMocks.apiPatch).toHaveBeenCalledWith('/v1/tasks/t1', { status: 'completed' });
    await completeTask('t1');
    expect(apiMocks.apiPost).toHaveBeenCalledWith('/v1/tasks/t1/complete/');
    await deleteTask('t1');
    expect(apiMocks.apiDelete).toHaveBeenCalledWith('/v1/tasks/t1');
  });
});

describe('buildTasksInsights', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-15T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  const base = {
    title: 'A',
    status: 'open',
    task_type: 'task',
    priority: 'high',
    assigned_to_name: null,
    due_date: null,
    created_at: '2026-06-01T00:00:00Z',
  };

  it('returns an empty dataset and the builtins for no tasks', () => {
    const r = buildTasksInsights([], '', t);
    expect(r.datasets[0]!.rows).toEqual([]);
    expect(r.builtins.length).toBeGreaterThan(0);
  });

  it('flags open, done and overdue per row, honouring server is_overdue', () => {
    const r = buildTasksInsights(
      [
        { ...base, title: 'late', is_overdue: true },
        { ...base, title: 'fine', due_date: '2020-01-01', is_overdue: false },
        { ...base, title: 'done', status: 'completed', is_overdue: true, completed_at: '2026-06-05T00:00:00Z' },
      ],
      'EUR',
      t,
    );
    const rows = Object.fromEntries(r.datasets[0]!.rows.map((x) => [x.title, x]));
    expect(rows.late).toMatchObject({ open: 1, overdue: 1, done: 0, age: 14 });
    expect(rows.fine).toMatchObject({ overdue: 0 });
    expect(rows.done).toMatchObject({ open: 0, overdue: 0, done: 1, age: 4 });
    expect(r.datasets[0]!.currency).toBe('EUR');
  });

  it('falls back to a due-date compare, and to Unassigned / metadata names', () => {
    const r = buildTasksInsights(
      [
        { ...base, title: 'x', due_date: '2026-06-01' },
        { ...base, title: 'y', metadata: { assignee_name: ' Crew ' } },
        { ...base, title: 'z', assigned_to_name: 'Ann' },
      ],
      '',
      t,
    );
    const rows = Object.fromEntries(r.datasets[0]!.rows.map((x) => [x.title, x]));
    expect(rows.x).toMatchObject({ overdue: 1, assignee: 'Unassigned' });
    expect(rows.y!.assignee).toBe('Crew');
    expect(rows.z!.assignee).toBe('Ann');
  });

  it('sorts rows chronologically and humanizes unknown codes', () => {
    const r = buildTasksInsights(
      [
        { ...base, title: 'b', created_at: '2026-06-10T00:00:00Z', status: 'in_progress' },
        { ...base, title: 'a', created_at: '2026-05-10T00:00:00Z' },
      ],
      '',
      t,
    );
    expect(r.datasets[0]!.rows.map((x) => x.title)).toEqual(['a', 'b']);
    expect(r.datasets[0]!.rows[1]!.status).toBe('In Progress');
    expect(r.datasets[0]!.rows[0]!.month).toBe('2026-05');
  });

  it('reads labels through tasks.* i18n keys', () => {
    const seen: string[] = [];
    const spy = ((k: string, o?: { defaultValue?: string }) => {
      seen.push(k);
      return o?.defaultValue ?? k;
    }) as never;
    buildTasksInsights([base], '', spy);
    expect(seen.filter((k) => !k.startsWith('tasks.'))).toEqual([]);
    expect(seen).toContain('tasks.status_open');
    expect(seen).toContain('tasks.priority_high');
    expect(seen).toContain('tasks.type_task');
  });

  it('builtins reference only existing dataset fields', () => {
    const r = buildTasksInsights([base], '', t);
    const keys = new Set(r.datasets[0]!.fields.map((f) => f.key));
    for (const b of r.builtins) {
      if (b.dimension) expect(keys.has(b.dimension)).toBe(true);
      if (b.measure) expect(keys.has(b.measure)).toBe(true);
    }
  });
});

describe('tasksGuide', () => {
  it('uses only guide.tasks.* keys with English defaults', () => {
    const entries: [string, string][] = [
      [tasksGuide.titleKey, tasksGuide.titleDefault],
      [tasksGuide.ctaKey!, tasksGuide.ctaDefault!],
    ];
    for (const s of tasksGuide.sections) {
      entries.push([s.titleKey, s.titleDefault], [s.bodyKey, s.bodyDefault]);
    }
    for (const [k, d] of entries) {
      expect(k.startsWith('guide.tasks.')).toBe(true);
      expect(d.trim().length).toBeGreaterThan(0);
    }
    expect(new Set(entries.map(([k]) => k)).size).toBe(entries.length);
  });
});
