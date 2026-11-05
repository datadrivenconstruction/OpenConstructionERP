import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getRef, resetRefCacheForTests } from '@/shared/lib/offline/refCache';
import { downloadForOffline, packItemCount } from './offlinePrefetch';

const session = { token: 't', pin: '1234', projectId: 'proj-1', userId: 'u' };
const pack = {
  project_id: 'proj-1',
  server_time: '2026-11-04T08:00:00Z',
  punch_items: [{ id: 'p1', title: 'Paint', priority: 'low', status: 'open' }],
  inspections: [{ id: 'i1', title: 'Pour', inspection_type: 'concrete', status: 'scheduled', checklist_data: [] }],
  roster: [{ id: 'r1', name: 'A' }],
  punch_truncated: false,
  inspections_truncated: false,
};

describe('downloadForOffline', () => {
  beforeEach(() => resetRefCacheForTests());

  it('stores punch items, checklists and the roster for the session project', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify(pack), { status: 200 }));
    const count = await downloadForOffline(session, fetchImpl as unknown as typeof fetch);
    expect(count).toBe(2);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe('/api/v1/field-diary/offline-pack/');
    expect((init.headers as Record<string, string>)['X-Field-PIN']).toBe('1234');
    expect((await getRef('proj-1', 'punch_items'))?.payload).toHaveLength(1);
    expect((await getRef('proj-1', 'inspections'))?.payload).toHaveLength(1);
    expect((await getRef('proj-1', 'roster'))?.payload).toHaveLength(1);
  });

  it('returns null and stores nothing when the request does not land', async () => {
    const offline = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await downloadForOffline(session, offline as unknown as typeof fetch)).toBeNull();
    const expired = vi.fn().mockResolvedValue(new Response('{}', { status: 401 }));
    expect(await downloadForOffline(session, expired as unknown as typeof fetch)).toBeNull();
    expect(await getRef('proj-1', 'punch_items')).toBeNull();
  });

  it('counts punch items and inspections', () => {
    expect(packItemCount(pack)).toBe(2);
  });
});
