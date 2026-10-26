// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
const getProfile = vi.fn();
vi.mock('./api', () => ({ projectsApi: { getProfile: (...a: unknown[]) => getProfile(...a) } }));

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { readWorkPrefs, writeWorkPrefs, projectStartFor } from '@/shared/lib/workPrefs';
import { useOpenProject } from './useOpenProject';

beforeEach(() => {
  localStorage.clear();
  navigate.mockReset();
  getProfile.mockReset();
});

describe('useOpenProject', () => {
  it('opens the project page without a request when nothing is chosen', async () => {
    const { result } = renderHook(() => useOpenProject());
    await result.current('p1', 'Tower');
    expect(getProfile).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('/projects/p1');
  });

  it('goes to the page chosen for the project role and makes the project active', async () => {
    writeWorkPrefs({ ...readWorkPrefs(), projectStart: { subcontractor: 'tasks' } });
    getProfile.mockResolvedValue({ profile: { role: 'subcontractor' } });
    const { result } = renderHook(() => useOpenProject());
    await result.current('p1', 'Tower');
    expect(navigate).toHaveBeenCalledWith('/tasks');
    expect(useProjectContextStore.getState().activeProjectId).toBe('p1');
  });

  it('keeps the project page for a role that has no choice', async () => {
    writeWorkPrefs({ ...readWorkPrefs(), projectStart: { subcontractor: 'tasks' } });
    getProfile.mockResolvedValue({ profile: { role: 'developer' } });
    const { result } = renderHook(() => useOpenProject());
    await result.current('p1', 'Tower');
    expect(navigate).toHaveBeenCalledWith('/projects/p1');
  });

  it('falls back to the project page when the profile cannot be read', async () => {
    writeWorkPrefs({ ...readWorkPrefs(), projectStart: { subcontractor: 'tasks' } });
    getProfile.mockRejectedValue(new Error('404'));
    const { result } = renderHook(() => useOpenProject());
    await result.current('p1', 'Tower');
    expect(navigate).toHaveBeenCalledWith('/projects/p1');
  });
});

describe('workPrefs projectStart', () => {
  it('drops unknown roles, unknown pages and the default page', () => {
    localStorage.setItem(
      'oe_work_prefs_v1',
      JSON.stringify({ projectStart: { developer: 'boq', bogus: 'tasks', subcontractor: 'nope', cost_engineer: 'overview' } }),
    );
    expect(readWorkPrefs().projectStart).toEqual({ developer: 'boq' });
    expect(projectStartFor('developer')).toBe('boq');
    expect(projectStartFor(null)).toBe('overview');
  });
});
