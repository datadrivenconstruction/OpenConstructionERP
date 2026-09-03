// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The schedule's read of the two delivery modules, and how it fails.
 *
 * Both modules are optional installs. The contract this file pins down is the
 * one that keeps the schedule honest when they are missing: a 404 from either
 * router turns the whole Delivery surface off rather than rendering an empty
 * column that reads as "nothing is linked to this activity".
 *
 * It also pins the write path, because the standup link is stored on the
 * ACTIVITY (see delivery.ts) and a regression there would silently drop links.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/shared/lib/api';

vi.mock('./deliveryApi', async () => {
  const actual = await vi.importActual<typeof import('./deliveryApi')>('./deliveryApi');
  return {
    ...actual,
    fetchProjectRequests: vi.fn(),
    fetchDepartments: vi.fn(),
    fetchStandupBoard: vi.fn(),
    createStandupTask: vi.fn(),
    linkRequestToActivity: vi.fn(),
  };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, scheduleApi: { updateActivity: vi.fn() } };
});

import {
  createStandupTask,
  fetchDepartments,
  fetchProjectRequests,
  fetchStandupBoard,
  linkRequestToActivity,
} from './deliveryApi';
import { scheduleApi } from './api';
import { useDeliveryData, useDeliveryWrites } from './useDelivery';

const ACTIVITY = {
  id: 'a1',
  name: 'MCC-2 build',
  wbs_code: '3.1',
  start_date: '2026-09-01',
  end_date: '2026-09-30',
  metadata: { standup_task_ids: ['t-old'], duration_source: 'boq' },
};

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function notInstalled() {
  return Promise.reject(new ApiError(404, 'Not Found', undefined));
}

describe('useDeliveryData', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('indexes what each module returned', async () => {
    (fetchProjectRequests as any).mockResolvedValue([
      {
        id: 'r1',
        reference: 'WR-WKS-000001',
        title: 'MCC-2 build',
        project_id: 'p1',
        department: 'workshop',
        status: 'in_progress',
        quoted_hours: 180,
        hours_logged: 70,
        schedule_activity_id: 'a1',
      },
    ]);
    (fetchDepartments as any).mockResolvedValue([
      { key: 'workshop', name: 'Workshop', colour: '#7c3aed' },
    ]);
    (fetchStandupBoard as any).mockResolvedValue({
      day: '2026-09-03',
      stages: [{ id: 'done', name: 'Done', is_done: true }],
      tasks: [{ id: 't-old', title: 'Chase gear', project_id: 'p1', stage_id: 'doing' }],
    });

    const { result } = renderHook(() => useDeliveryData('p1', [ACTIVITY]), { wrapper });
    await waitFor(() => expect(result.current.enabled).toBe(true));
    expect(result.current.index.a1.requests).toHaveLength(1);
    expect(result.current.index.a1.tasks).toHaveLength(1);
    expect(result.current.index.a1.quotedHours).toBe(180);
    expect(result.current.departmentColour('workshop')).toBe('#7c3aed');
  });

  it('turns the whole surface off when neither module is installed', async () => {
    (fetchProjectRequests as any).mockImplementation(notInstalled);
    (fetchDepartments as any).mockImplementation(notInstalled);
    (fetchStandupBoard as any).mockImplementation(notInstalled);

    const { result } = renderHook(() => useDeliveryData('p1', [ACTIVITY]), { wrapper });
    await waitFor(() => expect(fetchProjectRequests).toHaveBeenCalled());
    await waitFor(() => expect(result.current.requestsAvailable).toBe(false));
    expect(result.current.standupAvailable).toBe(false);
    expect(result.current.enabled).toBe(false);
    // And it never claims an empty attachment list it did not read.
    expect(result.current.requests).toEqual([]);
    expect(result.current.board).toBeNull();
  });

  it('keeps the half that answered when only one module is missing', async () => {
    (fetchProjectRequests as any).mockResolvedValue([]);
    (fetchDepartments as any).mockResolvedValue([]);
    (fetchStandupBoard as any).mockImplementation(notInstalled);

    const { result } = renderHook(() => useDeliveryData('p1', [ACTIVITY]), { wrapper });
    await waitFor(() => expect(result.current.requestsAvailable).toBe(true));
    expect(result.current.standupAvailable).toBe(false);
    expect(result.current.enabled).toBe(true);
  });
});

describe('useDeliveryWrites', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (scheduleApi.updateActivity as any).mockResolvedValue({ id: 'a1' });
  });

  it('links a request by writing the request’s own activity field', async () => {
    (linkRequestToActivity as any).mockResolvedValue({ id: 'r1' });
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() => result.current.linkRequest('r1', 'a1'));
    expect(linkRequestToActivity).toHaveBeenCalledWith('r1', 'a1');
  });

  it('unlinks a request by clearing the same field, not by deleting anything', async () => {
    (linkRequestToActivity as any).mockResolvedValue({ id: 'r1' });
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() => result.current.linkRequest('r1', null));
    expect(linkRequestToActivity).toHaveBeenCalledWith('r1', null);
  });

  it('adds a task id to the activity metadata without dropping its siblings', async () => {
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() => result.current.linkTask(ACTIVITY, 't-new', true));
    expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', {
      metadata: { standup_task_ids: ['t-old', 't-new'] },
    });
  });

  it('removes just the one id when a task is unlinked', async () => {
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() => result.current.linkTask(ACTIVITY, 't-old', false));
    expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', {
      metadata: { standup_task_ids: [] },
    });
  });

  it('creates a board task and links the id it came back with', async () => {
    (createStandupTask as any).mockResolvedValue([{ id: 't-made' }]);
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() =>
      result.current.createTaskForActivity(ACTIVITY, {
        title: 'MCC-2 build',
        project_id: 'p1',
        due: '2026-09-30',
      }),
    );
    expect(createStandupTask).toHaveBeenCalledWith({
      title: 'MCC-2 build',
      project_id: 'p1',
      due: '2026-09-30',
    });
    expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', {
      metadata: { standup_task_ids: ['t-old', 't-made'] },
    });
  });

  it('leaves a task unlinked rather than guessing an id the board did not return', async () => {
    (createStandupTask as any).mockResolvedValue([]);
    const { result } = renderHook(() => useDeliveryWrites('s1', () => undefined), { wrapper });
    await act(() =>
      result.current.createTaskForActivity(ACTIVITY, { title: 'x', project_id: 'p1' }),
    );
    expect(scheduleApi.updateActivity).not.toHaveBeenCalled();
  });
});
