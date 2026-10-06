import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import { scheduleApi } from './api';

vi.mock('@/shared/lib/api', () => ({ apiGet: vi.fn(), apiDelete: vi.fn(), apiPost: vi.fn(),
  apiPatch: vi.fn(), apiPut: vi.fn(), API_BASE: '', getAuthToken: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

describe('schedule lifecycle API contract', () => {
  it('old delete and explicit archive use the non-destructive endpoint', () => {
    scheduleApi.deleteSchedule('s1');
    scheduleApi.archiveSchedule('s1');
    expect(apiDelete).toHaveBeenNthCalledWith(1, '/v1/schedule/schedules/s1');
    expect(apiDelete).toHaveBeenNthCalledWith(2, '/v1/schedule/schedules/s1');
  });
  it('restore and purge have distinct endpoints and verbs', () => {
    scheduleApi.restoreSchedule('s1');
    scheduleApi.purgeSchedule('s1');
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/schedule/schedules/s1/restore/', {});
    expect(apiDelete).toHaveBeenCalledExactlyOnceWith('/v1/schedule/schedules/s1/permanent/');
  });
  it.each(['current', 'archived', 'all'] as const)('serializes %s filter alongside pagination', (archiveState) => {
    scheduleApi.listSchedules('project', { archiveState, offset: 3, limit: 20 });
    expect(apiGet).toHaveBeenCalledTimes(1);
    const query = new URL(String(vi.mocked(apiGet).mock.calls[0]?.[0]), 'https://test').searchParams;
    expect(query.get('archive_state')).toBe(archiveState);
    expect(query.get('project_id')).toBe('project');
    expect(query.get('offset')).toBe('3');
    expect(query.get('limit')).toBe('20');
  });
});
