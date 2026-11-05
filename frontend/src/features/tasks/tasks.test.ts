import { describe, expect, it } from 'vitest';
import { assigneeFields } from './assignee';
import { buildTasksInsights } from './tasksInsights';

const t = ((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k) as never;
const UID = '123e4567-e89b-12d3-a456-426614174000';

describe('assigneeFields', () => {
  it('links the contact only when both the contact and a name are present', () => {
    expect(assigneeFields({ assigned_to: 'Ann', assignee_user_id: '', assignee_contact_id: 'c1' })).toEqual({
      assignee_contact_id: 'c1',
    });
  });
  it('links a user chosen from the list', () => {
    expect(assigneeFields({ assigned_to: 'Ann', assignee_user_id: UID, assignee_contact_id: '' })).toEqual({
      responsible_id: UID,
      assignee_contact_id: null,
      metadata: { assignee_name: null },
    });
  });
  it('treats a pasted user id as the user link', () => {
    const r = assigneeFields({ assigned_to: UID, assignee_user_id: '', assignee_contact_id: '' });
    expect(r).toMatchObject({ responsible_id: UID });
  });
  it('keeps free text as a name and clears the links', () => {
    expect(assigneeFields({ assigned_to: '  Site crew ', assignee_user_id: '', assignee_contact_id: '' })).toEqual({
      responsible_id: null,
      assignee_contact_id: null,
      metadata: { assignee_name: 'Site crew' },
    });
  });
});

describe('buildTasksInsights', () => {
  const base = { task_type: 'task', priority: 'high', due_date: null };
  const tasks = [
    { ...base, title: 'B', status: 'completed', assigned_to_name: null, created_at: '2026-02-01T00:00:00Z', completed_at: '2026-02-04T00:00:00Z', metadata: { assignee_name: 'Crew' } },
    { ...base, title: 'A', status: 'open', assigned_to_name: 'Ann', created_at: '2026-01-01T00:00:00Z', is_overdue: true },
  ];
  it('orders rows by creation and derives open, overdue, done and age', () => {
    const rows = buildTasksInsights(tasks, 'EUR', t).datasets[0]!.rows;
    expect(rows.map((r) => r.title)).toEqual(['A', 'B']);
    expect(rows[0]).toMatchObject({ open: 1, overdue: 1, done: 0, assignee: 'Ann', status: 'Open' });
    expect(rows[1]).toMatchObject({ open: 0, overdue: 0, done: 1, age: 3, assignee: 'Crew' });
  });
  it('falls back to Unassigned and yields an empty dataset for an empty register', () => {
    const one = buildTasksInsights([{ ...tasks[1]!, assigned_to_name: null }], '', t);
    expect(one.datasets[0]!.rows[0]!.assignee).toBe('Unassigned');
    expect(buildTasksInsights([], '', t).datasets[0]!.rows).toEqual([]);
  });
  it('ships the built-in KPIs', () => {
    expect(buildTasksInsights(tasks, '', t).builtins.map((b) => b.id)).toContain('kpi-overdue');
  });
});
