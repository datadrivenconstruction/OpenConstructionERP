import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '@/shared/lib/api';
import { useModuleStore } from './useModuleStore';
import { selectModuleRoutes } from '@/modules/ModuleRoutes';
import type { ModuleManifest } from '@/modules/_types';

vi.mock('@/shared/lib/api', () => ({ apiGet: vi.fn(), apiPatch: vi.fn(() => Promise.resolve()) }));
const mockApiGet = vi.mocked(apiGet);

const Page = () => null;
const survey = {
  id: 'survey_core',
  routes: [{ path: '/survey/plan', title: 'plan', component: Page }],
  offRoutes: [{ path: '/survey/*', title: 'setup', component: Page }],
} as unknown as ModuleManifest;

describe('module state at boot', () => {
  beforeEach(() => {
    localStorage.clear();
    mockApiGet.mockReset();
    useModuleStore.setState({ serverLoaded: false, enabledModules: { survey_core: false } });
  });

  it('a new browser learns the account turned survey on, once, however many callers ask', async () => {
    mockApiGet.mockResolvedValue({ modules: { survey_core: true } });
    await Promise.all([useModuleStore.getState().syncFromServer(), useModuleStore.getState().syncFromServer()]);
    expect(mockApiGet).toHaveBeenCalledTimes(1);
    expect(useModuleStore.getState().serverLoaded).toBe(true);
    expect(useModuleStore.getState().isModuleEnabled('survey_core')).toBe(true);
    expect(JSON.parse(localStorage.getItem('oe_enabled_modules')!).survey_core).toBe(true);
  });

  it('a failed load still ends the wait', async () => {
    mockApiGet.mockRejectedValue(new Error('offline'));
    await useModuleStore.getState().syncFromServer();
    expect(useModuleStore.getState().serverLoaded).toBe(true);
  });

  it('routes of a locally-off module wait for the answer instead of 404 or setup', () => {
    const off = () => false;
    expect(selectModuleRoutes([survey], off, true)).toEqual([{ route: survey.routes[0], waiting: true }]);
    expect(selectModuleRoutes([survey], off, false)).toEqual([{ route: survey.offRoutes![0], waiting: false }]);
    expect(selectModuleRoutes([survey], () => true, true)).toEqual([{ route: survey.routes[0], waiting: false }]);
  });
});
