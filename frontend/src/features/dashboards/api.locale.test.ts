import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import i18next from 'i18next';
import * as api from './api';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

vi.mock('@/shared/lib/api', async (original) => ({
  ...(await original<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn().mockResolvedValue({}),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}));

const originalLanguage = i18next.language;
const url = (value: string) => new URL(value, 'https://example.test');
beforeEach(() => { vi.clearAllMocks(); i18next.language = 'ru'; });
afterEach(() => { i18next.language = originalLanguage; vi.unstubAllGlobals(); });

const calls: Array<[string, () => Promise<unknown>, ReturnType<typeof vi.mocked<typeof apiGet>> | ReturnType<typeof vi.mocked<typeof apiPost>>]> = [
  ['list snapshots', () => api.listSnapshots('p'), vi.mocked(apiGet)],
  ['snapshot', () => api.getSnapshot('s'), vi.mocked(apiGet)],
  ['manifest', () => api.getSnapshotManifest('s'), vi.mocked(apiGet)],
  ['delete snapshot', () => api.deleteSnapshot('s'), vi.mocked(apiDelete)],
  ['insights', () => api.getQuickInsights('s'), vi.mocked(apiGet)],
  ['values', () => api.getSmartValues('s', 'Name'), vi.mocked(apiGet)],
  ['cascade', () => api.getCascadeValues('s', { target_column: 'Name', selected: {} }), vi.mocked(apiPost)],
  ['row count', () => api.getCascadeRowCount('s', {}), vi.mocked(apiGet)],
  ['presets', () => api.listDashboardPresets(), vi.mocked(apiGet)],
  ['preset', () => api.getDashboardPreset('p'), vi.mocked(apiGet)],
  ['create preset', () => api.createDashboardPreset({ name: 'Plan' }), vi.mocked(apiPost)],
  ['update preset', () => api.updateDashboardPreset('p', { name: 'New' }), vi.mocked(apiPatch)],
  ['delete preset', () => api.deleteDashboardPreset('p'), vi.mocked(apiDelete)],
  ['share', () => api.shareDashboardPreset('p'), vi.mocked(apiPost)],
  ['sync check', () => api.getSyncReport('p'), vi.mocked(apiPost)],
  ['sync heal', () => api.applySyncHeal('p'), vi.mocked(apiPost)],
  ['rows', () => api.getSnapshotRows('s'), vi.mocked(apiGet)],
  ['integrity', () => api.getIntegrityReport({ snapshotId: 's', projectId: 'p' }), vi.mocked(apiPost)],
  ['timeline', () => api.getSnapshotTimeline({ projectId: 'p' }), vi.mocked(apiGet)],
  ['diff', () => api.diffSnapshots({ a: 'a', b: 'b' }), vi.mocked(apiGet)],
  ['federation', () => api.buildFederation({ snapshotIds: ['a', 'b'] }), vi.mocked(apiPost)],
  ['aggregate', () => api.federatedAggregate({ snapshotIds: ['a'], groupBy: ['Name'], measure: 'Count' }), vi.mocked(apiPost)],
];

it.each(calls)('%s sends the current reader locale explicitly', async (_name, call, transport) => {
  await call();
  expect(url(transport.mock.calls.at(-1)![0]).searchParams.get('locale')).toBe('ru');
  i18next.language = 'de-DE';
  await call();
  expect(url(transport.mock.calls.at(-1)![0]).searchParams.get('locale')).toBe('de');
});

it('preserves encoded identifiers, filters, pagination and mutation bodies', async () => {
  const filters = { Name: ['A&B', 'x y'] };
  await api.getSnapshotRows('s/1', { filters, columns: ['Name'], limit: 7, offset: 3, orderBy: 'Name:asc' });
  const request = url(vi.mocked(apiGet).mock.calls.at(-1)![0]);
  expect(request.pathname).toContain('s%2F1/rows');
  expect(JSON.parse(request.searchParams.get('filters')!)).toEqual(filters);
  expect(Object.fromEntries(request.searchParams)).toMatchObject({ columns: 'Name', limit: '7', offset: '3', order_by: 'Name:asc', locale: 'ru' });
  const body = { name: 'New', config_json: { filters } };
  await api.updateDashboardPreset('p', body);
  expect(vi.mocked(apiPatch).mock.calls.at(-1)![1]).toBe(body);
});

it('localizes multipart upload without changing auth or form fields', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 's' }) });
  vi.stubGlobal('fetch', fetchMock);
  const file = new File(['content'], 'test.ifc');
  await api.createSnapshot({ projectId: 'p/1', label: 'Plan', files: [file], disciplines: ['structural'], parentSnapshotId: 'old' });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [path, init] = fetchMock.mock.calls[0]!;
  expect(url(path).searchParams.get('locale')).toBe('ru');
  expect(url(path).pathname).toContain('p%2F1/snapshots');
  expect(init.headers.Authorization).toBe('Bearer test-token');
  expect(init.body.get('label')).toBe('Plan');
  const uploaded = init.body.get('files') as File;
  expect(uploaded.name).toBe(file.name);
  expect(uploaded.size).toBe(file.size);
  const content = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(uploaded);
  });
  expect(content).toBe('content');
  expect(init.body.get('disciplines')).toBe('structural');
  expect(init.body.get('parent_snapshot_id')).toBe('old');
});

it('localizes download URLs at call time and keeps export options', () => {
  i18next.language = 'pt-BR';
  const first = url(api.buildSnapshotExportUrl('s', 'csv', { limit: 10 }));
  expect(Object.fromEntries(first.searchParams)).toMatchObject({ locale: 'pt', format: 'csv', limit: '10' });
  i18next.language = '';
  expect(url(api.buildSnapshotExportUrl('s', 'xlsx')).searchParams.get('locale')).toBe('en');
});
