// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * What the programme believes is attached to each activity.
 *
 * The index has to be right about three things or the Delivery column lies:
 * which requests belong to which activity, which standup tasks reach an
 * activity (directly, or through a request the board CAN link to), and which
 * of them are late or blocked - because that is what flags the row.
 */
import { describe, expect, it } from 'vitest';
import {
  atRiskActivities,
  buildDeliveryIndex,
  doneStageIds,
  isRequestLate,
  isTaskBlocked,
  isTaskLate,
  linkedTaskIds,
  loggedHoursOf,
  TASK_IDS_META_KEY,
} from './delivery';
import type { DeliveryRequest, DeliveryTask } from './deliveryApi';

const TODAY = '2026-09-03';

const activity = (id: string, taskIds: string[] = []) => ({
  id,
  name: `Activity ${id}`,
  wbs_code: id,
  start_date: '2026-09-01',
  end_date: '2026-09-10',
  metadata: taskIds.length ? { [TASK_IDS_META_KEY]: taskIds } : null,
});

const request = (over: Partial<DeliveryRequest> & { id: string }): DeliveryRequest => ({
  reference: `WR-WKS-${over.id}`,
  title: 'MCC-2 build',
  project_id: 'p1',
  department: 'workshop',
  status: 'in_progress',
  ...over,
});

const task = (over: Partial<DeliveryTask> & { id: string }): DeliveryTask => ({
  title: `Task ${over.id}`,
  project_id: 'p1',
  stage_id: 'doing',
  ...over,
});

describe('linkedTaskIds', () => {
  it('reads the ids the schedule pinned to the activity', () => {
    expect(linkedTaskIds(activity('a1', ['t1', 't2']))).toEqual(['t1', 't2']);
  });

  it('reads junk metadata as no links rather than throwing on render', () => {
    expect(linkedTaskIds({ metadata: { [TASK_IDS_META_KEY]: 't1' } })).toEqual([]);
    expect(linkedTaskIds({ metadata: null })).toEqual([]);
    expect(linkedTaskIds({ metadata: { [TASK_IDS_META_KEY]: ['t1', '', 't1', 7] } })).toEqual([
      't1',
    ]);
  });
});

describe('buildDeliveryIndex', () => {
  const base = {
    activities: [activity('a1', ['t-direct']), activity('a2')],
    doneStages: new Set(['done']),
    today: TODAY,
  };

  it('attaches a request to the activity its own field names', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [request({ id: 'r1', schedule_activity_id: 'a1' })],
      tasks: [],
    });
    expect(index.a1!.requests.map((r) => r.id)).toEqual(['r1']);
    expect(index.a2!.requests).toEqual([]);
  });

  it('drops a request pointing at an activity on another schedule', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [request({ id: 'r9', schedule_activity_id: 'somewhere-else' })],
      tasks: [],
    });
    expect(index.a1!.requests).toEqual([]);
    expect(index.a2!.requests).toEqual([]);
  });

  it('attaches a task the activity pinned, and one reached through a request', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [request({ id: 'r1', schedule_activity_id: 'a1' })],
      tasks: [
        task({ id: 't-direct' }),
        task({ id: 't-via', link_kind: 'request', link_target_id: 'r1', link_ref: 'WR-WKS-r1' }),
        task({ id: 't-other', link_kind: 'request', link_target_id: 'r-elsewhere' }),
      ],
    });
    expect(index.a1!.tasks.map((x) => x.id).sort()).toEqual(['t-direct', 't-via']);
    expect(index.a1!.indirectTaskIds.has('t-via')).toBe(true);
    expect(index.a1!.indirectTaskIds.has('t-direct')).toBe(false);
  });

  it('counts a task once when it is both pinned and reachable through a request', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [request({ id: 'r1', schedule_activity_id: 'a1' })],
      tasks: [task({ id: 't-direct', link_kind: 'request', link_target_id: 'r1' })],
    });
    expect(index.a1!.tasks).toHaveLength(1);
  });

  it('rolls hours logged and quoted up across the linked requests', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [
        request({ id: 'r1', schedule_activity_id: 'a1', quoted_hours: 180, hours_logged: 70 }),
        request({ id: 'r2', schedule_activity_id: 'a1', quoted_hours: 20, logged_hours: 5 }),
      ],
      tasks: [],
    });
    expect(index.a1!.quotedHours).toBe(200);
    expect(index.a1!.loggedHours).toBe(75);
  });

  it('flags the activity when an attachment is late or blocked', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [request({ id: 'r1', schedule_activity_id: 'a1', is_late: true, days_late: 12 })],
      tasks: [task({ id: 't-direct', waiting_on: 'Alex Example' })],
    });
    expect(index.a1!.lateRequests).toBe(1);
    expect(index.a1!.blockedTasks).toBe(1);
    expect(index.a1!.atRisk).toBe(true);
    expect(index.a2!.atRisk).toBe(false);
  });

  it('stops counting a late request once it is closed out', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [
        request({ id: 'r1', schedule_activity_id: 'a1', is_late: true, status: 'complete' }),
      ],
      tasks: [],
    });
    expect(index.a1!.lateRequests).toBe(0);
    expect(index.a1!.atRisk).toBe(false);
  });

  it('does not call a finished task late or blocked', () => {
    const index = buildDeliveryIndex({
      ...base,
      requests: [],
      tasks: [
        task({ id: 't-direct', stage_id: 'done', due: '2026-08-01', waiting_on: 'Alex Example' }),
      ],
    });
    expect(index.a1!.lateTasks).toBe(0);
    expect(index.a1!.blockedTasks).toBe(0);
  });
});

describe('at-risk listing', () => {
  it('lists only the flagged activities, worst first', () => {
    const activities = [activity('a1'), activity('a2'), activity('a3')];
    const index = buildDeliveryIndex({
      activities,
      doneStages: new Set(['done']),
      today: TODAY,
      requests: [
        request({ id: 'r1', schedule_activity_id: 'a1', is_late: true }),
        request({ id: 'r2', schedule_activity_id: 'a1', is_late: true }),
        request({ id: 'r3', schedule_activity_id: 'a2' }),
      ],
      tasks: [],
    });
    // a2 gets a blocked task so it is at risk, but less so than a1's two late
    // requests - the order is the point of the panel.
    index.a2!.blockedTasks = 1;
    index.a2!.atRisk = true;
    const rows = atRiskActivities(index, activities);
    expect(rows.map((r) => r.activity.id)).toEqual(['a1', 'a2']);
  });
});

describe('state helpers', () => {
  it('takes the board’s own done stages, honouring a per-job override', () => {
    const board = {
      day: TODAY,
      stages: [{ id: 's1', name: 'Done', is_done: true }],
      stage_overrides: { p1: [{ id: 'x1', name: 'Shipped', is_done: true }] },
      tasks: [],
    };
    expect([...doneStageIds(board, 'p1')]).toEqual(['x1']);
    expect([...doneStageIds(board, 'p2')]).toEqual(['s1']);
    expect([...doneStageIds(null, 'p1')]).toEqual([]);
  });

  it('calls a task late only when it is overdue and unfinished', () => {
    const done = new Set(['done']);
    expect(isTaskLate(task({ id: 't', due: '2026-09-02' }), done, TODAY)).toBe(true);
    expect(isTaskLate(task({ id: 't', due: TODAY }), done, TODAY)).toBe(false);
    expect(isTaskLate(task({ id: 't' }), done, TODAY)).toBe(false);
    expect(isTaskLate(task({ id: 't', due: '2026-09-02', stage_id: 'done' }), done, TODAY)).toBe(
      false,
    );
  });

  it('treats “waiting on” as blocked', () => {
    expect(isTaskBlocked(task({ id: 't', waiting_on: 'Acme Holdings' }), new Set())).toBe(true);
    expect(isTaskBlocked(task({ id: 't' }), new Set())).toBe(false);
  });

  it('reads either spelling of the logged-hours field', () => {
    expect(loggedHoursOf(request({ id: 'r', hours_logged: 70 }))).toBe(70);
    expect(loggedHoursOf(request({ id: 'r', logged_hours: 12 }))).toBe(12);
    expect(loggedHoursOf(request({ id: 'r' }))).toBe(0);
  });

  it('only calls a request late when the server did', () => {
    expect(isRequestLate(request({ id: 'r' }))).toBe(false);
    expect(isRequestLate(request({ id: 'r', is_late: true }))).toBe(true);
  });
});
