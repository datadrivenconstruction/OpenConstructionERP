// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the schedule page does with a link drawn or removed on the Gantt.
 *
 * Review findings this pins:
 * - removing a link looked it up in the relationship list, which the server
 *   pages at 200 with the newest last, so on a large plan the link was not
 *   found and nothing happened, silently. It now deletes by the pair, and a
 *   link that is not there says so;
 * - the refresh after a change ran outside the error handling, so a failed
 *   reschedule escaped as an unhandled rejection and the chart was not
 *   refetched. Now the chart is always refetched and every failure is said;
 * - a role that cannot edit the schedule got link handles and an arrow menu
 *   whose every action the server refuses. It now gets neither.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useGanttLinking } from './useGanttLinking';

const api = vi.hoisted(() => ({
  createRelationship: vi.fn(),
  deleteRelationshipBetween: vi.fn(),
  reschedule: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, scheduleApi: { ...actual.scheduleApi, ...api } };
});

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual<typeof import('react-i18next')>('react-i18next');
  const t = (key: string, a?: unknown) => {
    const opts = (typeof a === 'object' && a ? a : {}) as Record<string, unknown>;
    const text = typeof opts.defaultValue === 'string' ? opts.defaultValue : key;
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, k: string) => String(opts[k] ?? ''));
  };
  return { ...actual, useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});

let client: QueryClient;
let invalidated: unknown[][];

function setup(canEdit = true) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useGanttLinking('sch', canEdit), { wrapper }).result;
}

const toasts = () => useToastStore.getState().toasts;

beforeEach(() => {
  vi.clearAllMocks();
  api.createRelationship.mockResolvedValue({ id: 'r1' });
  api.deleteRelationshipBetween.mockResolvedValue(undefined);
  api.reschedule.mockResolvedValue([]);
  useToastStore.setState({ toasts: [] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  invalidated = [];
  const orig = client.invalidateQueries.bind(client);
  client.invalidateQueries = ((filters?: { queryKey?: unknown[] }) => {
    invalidated.push(filters?.queryKey ?? []);
    return orig(filters);
  }) as typeof client.invalidateQueries;
});

describe('useGanttLinking', () => {
  it('gives a role that cannot edit no link callbacks at all', () => {
    const result = setup(false);
    expect(result.current.onCreateLink).toBeUndefined();
    expect(result.current.onDeleteLink).toBeUndefined();
  });

  it('creates the link, reschedules and refetches edges and bars', async () => {
    const result = setup();
    await act(() => result.current.onCreateLink!('a', 'b', 'FF'));

    expect(api.createRelationship).toHaveBeenCalledWith('sch', {
      predecessor_id: 'a',
      successor_id: 'b',
      relationship_type: 'FF',
      lag_days: 0,
    });
    expect(api.reschedule).toHaveBeenCalledWith('sch');
    expect(invalidated).toContainEqual(['schedule-relationships', 'sch']);
    expect(invalidated).toContainEqual(['gantt', 'sch']);
    expect(toasts().map((t) => t.type)).toEqual(['success']);
  });

  it('says a cycle refusal in the reader language and does not reschedule', async () => {
    api.createRelationship.mockRejectedValue(
      new ApiError(400, 'Bad Request', { detail: { error: 'schedule_dependency_cycle', message: 'circular' } }),
    );
    const result = setup();
    await act(() => result.current.onCreateLink!('a', 'b', 'FS'));

    expect(api.reschedule).not.toHaveBeenCalled();
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]!.type).toBe('error');
    expect(toasts()[0]!.title).toBe('This link would make the schedule loop back on itself, so it was not added.');
  });

  it('still refetches and says so when the reschedule after a saved link fails', async () => {
    api.reschedule.mockRejectedValue(new Error('boom'));
    const result = setup();
    // Must resolve, not reject: the chart calls this as `void onCreateLink(...)`.
    await expect(result.current.onCreateLink!('a', 'b', 'FS')).resolves.toBeUndefined();

    expect(invalidated).toContainEqual(['schedule-relationships', 'sch']);
    expect(invalidated).toContainEqual(['gantt', 'sch']);
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]!.type).toBe('warning');
    expect(toasts()[0]!.title).toBe(
      'The link was saved, but the dates could not be recalculated. Recalculate the schedule to update them.',
    );
  });

  it('removes a link by its pair, not by searching a paged list', async () => {
    const result = setup();
    await act(() => result.current.onDeleteLink!('a', 'b'));

    expect(api.deleteRelationshipBetween).toHaveBeenCalledWith('sch', 'a', 'b');
    expect(api.reschedule).toHaveBeenCalledWith('sch');
    expect(toasts().map((t) => t.type)).toEqual(['success']);
  });

  it('says so when the link to remove is no longer there, and refetches', async () => {
    api.deleteRelationshipBetween.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: { error: 'relationship_not_found', message: 'Relationship not found' } }),
    );
    const result = setup();
    await expect(result.current.onDeleteLink!('a', 'b')).resolves.toBeUndefined();

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]!.title).toBe('That link no longer exists. The chart has been refreshed.');
    expect(invalidated).toContainEqual(['gantt', 'sch']);
  });

  it('treats a 404 for an activity outside the schedule as an error, not as already removed', async () => {
    api.deleteRelationshipBetween.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: { error: 'schedule_activity_not_in_schedule', message: 'x' } }),
    );
    const result = setup();
    await act(() => result.current.onDeleteLink!('a', 'b'));

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]!.type).toBe('error');
    expect(toasts()[0]!.title).toBe('Both activities must belong to this schedule.');
  });

  it('says any other removal failure and never rejects', async () => {
    api.deleteRelationshipBetween.mockRejectedValue(new Error('network down'));
    const result = setup();
    await expect(result.current.onDeleteLink!('a', 'b')).resolves.toBeUndefined();

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0]!.type).toBe('error');
  });
});
